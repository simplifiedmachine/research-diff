"""research-diff's own files, kept in the repository's git dir (.git/research-diff/; a linked worktree's own): never
committed, never sent anywhere. JSON written whole and atomically; JSONL appended, one event a line, trimmed as it grows.
"""
from __future__ import annotations

import json
import os
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, List

from system_diff.sources import git

KEEP_LINES = 2000


@lru_cache(maxsize=16)
def _git_dir(root: str) -> str:
    return git("rev-parse", "--absolute-git-dir", cwd=Path(root)).strip()


def home(root: Path) -> Path:
    d = Path(_git_dir(str(Path(root).resolve()))) / "research-diff"
    d.mkdir(parents=True, exist_ok=True)
    return d


def read(root: Path, name: str, default: Any = None) -> Any:
    try:
        return json.loads((home(root) / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write(root: Path, name: str, data: Any) -> None:
    path = home(root) / name
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def append(root: Path, name: str, item: dict) -> None:
    path = home(root) / name
    item = {"at": round(time.time(), 3), **item}
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")
    try:
        if path.stat().st_size > KEEP_LINES * 400:
            lines = path.read_text(encoding="utf-8").splitlines()[-KEEP_LINES // 2:]
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass


def lines(root: Path, name: str, last: int = 0) -> List[dict]:
    try:
        raw = (home(root) / name).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for ln in raw[-last:] if last else raw:
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out
