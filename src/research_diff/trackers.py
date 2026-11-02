"""Runs from experiment trackers, as results: MLflow's local file store (`mlruns/`) and W&B's local run folders
(`wandb/`), read with the standard library. A run belongs to an experiment when it is tagged with its id:
`research-diff.experiment` (or `research_id`) as an MLflow tag or param, or `research_id` in the W&B config.

Tracker folders are usually git-ignored, so a checkpoint could not see them. `sync` writes their runs into
`research/runs.json`, which is tracked: the runs are then on the map, in git, and in the next diff.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

RUNS = "research/runs.json"
TAGS = ("research-diff.experiment", "research_id", "research-diff")


def _last_metric(path: Path) -> float:
    """MLflow keeps one line per step, `timestamp value step`; the last one is the run's value."""
    lines = [ln.split() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return float(lines[-1][1])


def read_mlflow(store: Path) -> List[Dict[str, Any]]:
    out = []
    for meta in sorted(store.glob("*/*/meta.yaml")):
        run = meta.parent
        exp = ""
        for kind in ("tags", "params"):
            for t in TAGS:
                p = run / kind / t
                if p.is_file():
                    exp = exp or p.read_text(encoding="utf-8").strip()
        if not exp:
            continue
        metrics = {}
        for m in sorted((run / "metrics").glob("**/*")) if (run / "metrics").is_dir() else []:
            if m.is_file():
                try:
                    metrics[m.relative_to(run / "metrics").as_posix()] = _last_metric(m)
                except (ValueError, IndexError):
                    continue
        name_file = run / "tags" / "mlflow.runName"
        out.append({"experiment": exp, "source": "mlflow", "run": run.name,
                    "name": name_file.read_text(encoding="utf-8").strip() if name_file.is_file() else run.name[:8],
                    "metrics": metrics})
    return out


def _wandb_config_value(text: str, key: str) -> str:
    """W&B's config.yaml keeps each key as `key:\\n  desc: …\\n  value: X`."""
    m = re.search(rf"^{re.escape(key)}:\s*\n(?:\s+.*\n)*?\s+value:\s*(.+)$", text, re.M)
    return m.group(1).strip().strip("'\"") if m else ""


def read_wandb(folder: Path) -> List[Dict[str, Any]]:
    out = []
    for run in sorted(p for p in folder.glob("*run-*") if p.is_dir()):
        files = run / "files"
        cfg = (files / "config.yaml").read_text(encoding="utf-8") if (files / "config.yaml").is_file() else ""
        exp = next((v for k in TAGS if (v := _wandb_config_value(cfg, k))), "")
        summary = files / "wandb-summary.json"
        if not exp or not summary.is_file():
            continue
        try:
            data = json.loads(summary.read_text(encoding="utf-8"))
        except ValueError:
            continue
        metrics = {k: float(v) for k, v in data.items() if isinstance(v, (int, float)) and not isinstance(v, bool)
                   and not k.startswith("_")}
        out.append({"experiment": exp, "source": "wandb", "run": run.name.rsplit("-", 1)[-1], "name": run.name,
                    "metrics": metrics})
    return out


def sync(root: Path, mlflow: str = "mlruns", wandb: str = "wandb") -> Dict[str, Any]:
    """Write the trackers' tagged runs to research/runs.json. Returns {runs, written}; nothing is written when no
    tracker folder exists, and the file only changes when a run does."""
    runs: List[Dict[str, Any]] = []
    if (root / mlflow).is_dir():
        runs += read_mlflow(root / mlflow)
    if (root / wandb).is_dir():
        runs += read_wandb(root / wandb)
    if not runs and not (root / RUNS).is_file():
        return {"runs": 0, "written": False}
    runs.sort(key=lambda r: (r["experiment"], r["source"], r["run"]))
    text = json.dumps({"runs": runs}, indent=1, sort_keys=True) + "\n"
    path = root / RUNS
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return {"runs": len(runs), "written": False}
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return {"runs": len(runs), "written": True}


def run_nodes(text: str) -> List[Dict[str, Any]]:
    """The runs of a runs.json, for extract."""
    try:
        return list(json.loads(text).get("runs") or [])
    except (ValueError, AttributeError):
        return []
