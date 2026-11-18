"""Several studies in one repository: a folder per paper (1_tradeoff_reward_model_eval/, 2_behavioral_field/, ...),
each with its own notes, configs, results and paper, and ids of its own (each paper has its C1). Each study is read on
its own: its folder's files, plus the shared files outside every study (a root research-diff.toml, shared scripts).

Found in research-diff.toml (`studies = ["1_tradeoff_reward_model_eval", ...]`, or `[[studies]]` with `name` and
`path`), else from the paper files: every top-level folder that holds a paper file is a study, when there are two or
more. Folders inside git submodules count like any other (their files are read too).
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

from system_diff.extract import glob_rx


# A top-level folder by one of these names holds the repository's own paper, not a study of its own.
PAPER_FOLDERS = {"paper", "papers", "tex", "latex", "doc", "docs", "manuscript", "writeup", "writing", "draft", "drafts"}


def detect(files: List[str], cfg: Dict[str, Any]) -> List[dict]:
    given = cfg.get("studies")
    if given:
        out = []
        for x in given:
            path = (x.get("path") if isinstance(x, dict) else str(x)).strip("/")
            name = (x.get("name") if isinstance(x, dict) else "") or path
            if path:
                out.append({"id": path, "title": name, "path": path})
        return out
    rxs = [glob_rx(g) for g in cfg.get("paper", [])]
    dirs: List[str] = []
    for f in files:
        parts = PurePosixPath(f).parts
        if len(parts) > 1 and parts[0].lower() not in PAPER_FOLDERS and any(r.match(f) for r in rxs) \
                and parts[0] not in dirs:
            dirs.append(parts[0])
    if len(dirs) < 2:
        return []
    return [{"id": d, "title": _title(d), "path": d} for d in sorted(dirs)]


def _title(folder: str) -> str:
    """1_tradeoff_reward_model_eval -> "1 · tradeoff reward model eval"."""
    m = re.match(r"^(\d+)[_\-. ]+(.*)$", folder)
    words = (m.group(2) if m else folder).replace("_", " ").replace("-", " ").strip()
    return f"{m.group(1)} · {words}" if m else words


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
