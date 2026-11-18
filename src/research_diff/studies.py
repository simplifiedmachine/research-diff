"""Several studies in one repository: a folder per paper, each with its own notes, configs, results and paper, and ids
of its own (each paper has its C1). Each study is read on its own: its folder's files, those under its name in a
shared folder (results/<study>/...), and the files at the repository's top (a root research-diff.toml).

Found in research-diff.toml (`studies = ["tradeoff", ...]`, or `[[studies]]` with `name` and `path`), else from what
the top-level folders hold, never from their names: a study is a folder with a paper of its own (a LaTeX file, or a
file the `paper` globs name) and work of its own beside it (code or data: experiments, configs, results), when two or
more folders are. Folders inside git submodules count like any other (their files are read too). The person can read
the repository as one study (the switch at the end of the list, or `studies = false`).
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

# What a folder's files say about it, by their kind (never by the folder's name): a paper, or work beside one.
PAPER_EXT = {".tex"}
WORK_EXT = {".py", ".ipynb", ".r", ".jl", ".m", ".sh", ".c", ".cc", ".cpp", ".cu", ".rs", ".go", ".java", ".js",
            ".ts", ".json", ".jsonl", ".csv", ".tsv", ".yaml", ".yml", ".toml", ".parquet", ".npy", ".npz", ".h5",
            ".hdf5", ".pkl", ".pt", ".log"}


def detect(files: List[str], cfg: Dict[str, Any]) -> List[dict]:
    """The studies of a repository, in order: those research-diff.toml names; else the top-level folders that each
    hold a paper and work of their own (two or more, or none)."""
    given = cfg.get("studies")
    if given is False:                 # studies = false: the repository is one study
        return []
    if given:
        out = []
        for x in given:
            path = (x.get("path") if isinstance(x, dict) else str(x)).strip("/")
            name = (x.get("name") if isinstance(x, dict) else "") or _title(path)
            if path:
                out.append({"id": path, "title": name, "path": path})
        return out
    from system_diff.extract import glob_rx
    extra = [glob_rx(g) for g in cfg.get("paper", []) if not str(g).endswith(".tex")]   # a Markdown paper, named
    tops: Dict[str, set] = {}
    for f in files:
        parts = PurePosixPath(f).parts
        if len(parts) < 2 or parts[0].startswith("."):
            continue
        signs = tops.setdefault(parts[0], set())
        ext = PurePosixPath(f).suffix.lower()
        if ext in PAPER_EXT or (extra and any(r.match(f) for r in extra)):
            signs.add("paper")
        elif ext in WORK_EXT:
            signs.add("work")
    dirs = [d for d, signs in tops.items() if {"paper", "work"} <= signs]
    if len(dirs) < 2:
        return []
    return [{"id": d, "title": _title(d), "path": d} for d in sorted(dirs, key=_order)]


def _title(folder: str) -> str:
    """1_tradeoff_reward_model_eval -> "1 · tradeoff reward model eval"; reward-models -> "reward models"."""
    m = re.match(r"^(\d+)[_\-. ]+(.*)$", folder)
    words = (m.group(2) if m else folder).replace("_", " ").replace("-", " ").strip()
    return f"{m.group(1)} · {words}" if m else words


def _order(folder: str) -> tuple:
    """A natural order: 2_x before 10_x, a2 before a10."""
    return tuple((0, int(t), "") if t.isdigit() else (1, 0, t.lower()) for t in re.split(r"(\d+)", folder) if t)


def belongs(path: str, folder: str) -> bool:
    """A file of a study: in its folder, or in a shared folder under its name (results/<study>/...)."""
    folder = folder.strip("/")
    parts = PurePosixPath(path).parts
    return bool(parts) and (parts[0] == folder or folder in parts[1:-1])


def of_study(path: str, folder: str) -> bool:
    """What a study reads: its own files, and the files at the repository's top (research-diff.toml, a shared notes
    file); never another folder's (slides, shared scripts, other studies')."""
    return belongs(path, folder) or "/" not in path.strip("/")


def at(found: List[dict], folder: str) -> str:
    """The study a folder is, or is inside (a picked project: "2_x", "2_x/paper"), else ""."""
    f = (folder or "").strip("/")
    for x in found:
        p = x["path"].strip("/")
        if f == p or f.startswith(p + "/"):
            return x["id"]
    return ""


def scope(found: List[dict], sid: str) -> Optional[Tuple[str, List[str]]]:
    if not found or not any(s["id"] == sid for s in found):
        return None
    me = next(s for s in found if s["id"] == sid)
    return me["path"], [s["path"] for s in found if s["id"] != sid]


def split(part: str) -> Tuple[str, str]:
    """A view's part: "<study>@<node>" when the repository holds several studies; "<node>" otherwise."""
    if "@" in (part or ""):
        a, _, b = part.partition("@")
        return a, b
    return "", part or ""


def join(study: str, node: str = "") -> str:
    return f"{study}@{node}" if study else node


# The person's own choice, per repository: read as one study even when studies are found (detection can be wrong).
PREF = "studies.json"


def split_on(root) -> bool:
    from . import store
    return bool((store.read(root, PREF, {}) or {}).get("split", True))


def set_split(root, on: bool) -> None:
    from . import store
    store.write(root, PREF, {"split": bool(on)})
