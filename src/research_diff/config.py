"""What a research project tells research-diff about itself: which files hold its notes, experiment configs, scripts
and paper. Read from `--config`, else `research-diff.toml`, else `[tool.research-diff]` in pyproject.toml; every key
is optional, and with none every Markdown, config, Python and LaTeX file is read for markers.
"""
from __future__ import annotations

import json
import tomllib
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Optional

FILE = "research-diff.toml"

DEFAULTS: Dict[str, Any] = {
    "notes": ["**/*.md"],
    "configs": ["**/*.yaml", "**/*.yml", "**/*.json", "**/*.toml"],
    "scripts": ["**/*.py", "**/*.ipynb"],
    "paper": ["**/*.tex"],
    "runs": ["research/runs.json"],               # tracker runs, written by `research-diff sync`
    "trackers": {"mlflow": "mlruns", "wandb": "wandb"},
    "skip": ["node_modules", "__pycache__", "dist", "build", ".venv*", "venv", ".git", "site-packages"],
    "ignore": ["README.md", "CHANGELOG.md"],     # never read for markers (globs)
    "kinds": {"Q": "question", "H": "hypothesis", "E": "experiment", "R": "result", "C": "claim"},
    "picture": {"columns": [["question", "Questions"], ["hypothesis", "Hypotheses"], ["experiment", "Experiments"],
                            ["result", "Results"], ["claim", "Claims"]]},
    "readme": {"file": "README.md", "svg": "docs/research.svg",   # the picture's file; `image` links to it (default: the file)
               "image": "",
               "begin": "<!-- research-map:begin -->", "end": "<!-- research-map:end -->"},
}


def merge(base: Dict[str, Any], over: Dict[str, Any]) -> Dict[str, Any]:
    out = deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else deepcopy(v)
    return out


def parse(text: str, name: str) -> Dict[str, Any]:
    if not text.strip():
        return {}
    if name.endswith(".json"):
        return json.loads(text)
    data = tomllib.loads(text)
    return data.get("tool", {}).get("research-diff", {}) if name.endswith("pyproject.toml") else data


def load(source=None, root: Optional[Path] = None, path: Optional[str] = None) -> Dict[str, Any]:
    """The project's settings over the defaults; the commit's own research-diff.toml wins over the one on disk."""
    if path:
        p = Path(path)
        return merge(DEFAULTS, parse(p.read_text(encoding="utf-8"), p.name))
    for name in (FILE, "pyproject.toml"):
        text = source.read(name) if source is not None and name in source.files else ""
        if not text and root is not None and (root / name).is_file():
            text = (root / name).read_text(encoding="utf-8")
        got = parse(text, name) if text else {}
        if got:
            return merge(DEFAULTS, got)
    return deepcopy(DEFAULTS)
