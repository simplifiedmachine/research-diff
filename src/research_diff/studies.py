"""Several studies in one repository: a folder per paper (1_tradeoff_reward_model_eval/, 2_behavioral_field/, ...),
each with its own notes, configs, results and paper, and ids of its own (each paper has its C1). Each study is read on
its own: its folder's files, plus the shared files outside every study (a root research-diff.toml, shared scripts).

Found in research-diff.toml (`studies = ["1_tradeoff_reward_model_eval", ...]`, or `[[studies]]` with `name` and
`path`), else from the folders: numbered top-level folders (1_x, 2_y, ...), else those holding a paper/ or an
experiments/ folder or a LaTeX file. A study's files are its folder's and those under its name in a shared folder
(results/<study>/...), read whatever the `paper`/`notes`/`configs` globs say. Folders inside git submodules count like
any other (their files are read too).
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional, Tuple


# A top-level folder by one of these names holds the repository's own paper, not a study of its own.
PAPER_FOLDERS = {"paper", "papers", "tex", "latex", "doc", "docs", "manuscript", "writeup", "writing", "draft", "drafts"}


# Top-level folders that are shared by the studies, never one of them.
SHARED_FOLDERS = {"results", "result", "scripts", "script", "data", "datasets", "tools", "src", "lib", "tests",
                  "test", "notebooks", "configs", "config", "figures", "assets", "node_modules", "venv", "env"}
NUMBERED = re.compile(r"^\d+[_\-. ]")


def detect(files: List[str], cfg: Dict[str, Any]) -> List[dict]:
    """The studies of a repository, in order. From research-diff.toml when it names them; else from its folders:
    numbered top-level folders (1_x, 2_y, ...) when there are two or more; else every top-level folder that holds a
    paper/ or experiments/ folder, or a LaTeX file. Two or more, or none."""
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
    tops: Dict[str, set] = {}
    for f in files:
        parts = PurePosixPath(f).parts
        if len(parts) < 2 or parts[0].startswith("."):
            continue
        low = parts[0].lower()
        if low in PAPER_FOLDERS or low in SHARED_FOLDERS:
            continue
        signs = tops.setdefault(parts[0], set())
        if len(parts) > 2 and parts[1].lower() in ("paper", "papers", "experiments", "experiment"):
            signs.add("folder")
        if f.endswith(".tex"):
            signs.add("tex")
    numbered = sorted(d for d in tops if NUMBERED.match(d))
    dirs = numbered if len(numbered) >= 2 else sorted(d for d, signs in tops.items() if signs)
    if len(dirs) < 2:
        return []
    return [{"id": d, "title": _title(d), "path": d} for d in sorted(dirs, key=_order)]


def _order(folder: str) -> tuple:
    m = re.match(r"^(\d+)", folder)
    return (int(m.group(1)) if m else 10 ** 9, folder)


def belongs(path: str, folder: str) -> bool:
    """A file of a study: in its folder, or in a shared folder under its name (results/<study>/...)."""
    folder = folder.strip("/")
    parts = PurePosixPath(path).parts
    return bool(parts) and (parts[0] == folder or folder in parts[1:-1])


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


# The person's own choice, per repository: read as one study even when studies are found (detection can be wrong).
PREF = "studies.json"


def split_on(root) -> bool:
    from . import store
    return bool((store.read(root, PREF, {}) or {}).get("split", True))


def set_split(root, on: bool) -> None:
    from . import store
    store.write(root, PREF, {"split": bool(on)})
