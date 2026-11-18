"""Which files hold no research, remembered by their content, so that a repository's thousands of data files (results
logs, run configs, notebooks) are read once, not at every look.

research-diff reads its markers from scripts and configs (`research-diff:` in a comment, a `research:` block), and
those globs (`**/*.py`, `**/*.json`, ...) take in every log and output file of a research repository too. A file is
remembered by its git blob id when the source knows it (the engine's working tree, a commit: the same blob at another
commit is the same answer), else by its path, size and time on disk. Files bigger than SCAN_MAX are not read for
markers (a config with a research block is small); a results file a `results:` names is still read, by its own path.

Kept in memory and in .git/research-diff-cache/seen.json, beside research-diff's own folder rather than in it: its
writes must not move system-diff's engine version (which watches .git/research-diff/) and redraw the pages.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional

SCAN_MAX = 2 * 1024 * 1024        # bytes: a bigger file is data, not a config
SAVE_EVERY = 30.0                 # seconds between two writes of the file
FILE = "seen.json"
MOST = 200_000                    # entries kept (the oldest go first)

_LOCK = threading.Lock()
_MEM: Dict[str, Dict[str, bool]] = {}
_SAVED: Dict[str, float] = {}
_DIRTY: Dict[str, int] = {}


def _dir(root: Path) -> Optional[Path]:
    try:
        from . import store
        d = store.home(root).parent / "research-diff-cache"
        d.mkdir(exist_ok=True)
        return d
    except Exception:  # noqa: BLE001 - not a git repository: memory only
        return None


def _known(root: Path) -> Dict[str, bool]:
    key = str(Path(root).resolve())
    with _LOCK:
        got = _MEM.get(key)
        if got is not None:
            return got
    got = {}
    d = _dir(root)
    if d is not None:
        try:
            raw = json.loads((d / FILE).read_text(encoding="utf-8"))
            got = {str(k): bool(v) for k, v in raw.items()} if isinstance(raw, dict) else {}
        except (OSError, ValueError):
            got = {}
    with _LOCK:
        return _MEM.setdefault(key, got)


def key(source, root: Path, path: str, stat: bool = True) -> Optional[str]:
    """What a file is known by: its blob id, else (on disk) its path, size and time."""
    blobs = getattr(source, "blobs", None)
    if blobs:
        sha = blobs.get(path)
        if sha:
            return str(sha)
    if not stat:
        return None
    try:
        st = os.stat(Path(root) / path)
    except OSError:
        return None
    return f"{path}|{st.st_size}|{st.st_mtime_ns}"


def _size(root: Path, path: str) -> int:
    try:
        return os.stat(Path(root) / path).st_size
    except OSError:
        return 0


class Seen:
    """For one read of a source: which of its files to read (`wanted`), and what each held (`note`)."""

    def __init__(self, source, root: Path, on_disk: bool):
        self.source, self.root, self.on_disk = source, Path(root), on_disk
        self.known = _known(self.root)
        self.keys: Dict[str, Optional[str]] = {}

    def wanted(self, paths: Iterable[str]) -> List[str]:
        out = []
        for p in paths:
            k = key(self.source, self.root, p, stat=self.on_disk)
            self.keys[p] = k
            if k is not None and self.known.get(k) is False:
                continue                      # read before: no research in it
            if self.on_disk and _size(self.root, p) > SCAN_MAX:
                self.note(p, False)
                continue
            out.append(p)
        return out

    def note(self, path: str, holds: bool) -> None:
        k = self.keys.get(path)
        if k is None or self.known.get(k) == holds:
            return
        with _LOCK:
            self.known[k] = holds
            r = str(self.root.resolve())
            _DIRTY[r] = _DIRTY.get(r, 0) + 1

    def save(self, force: bool = False) -> None:
        r = str(self.root.resolve())
        with _LOCK:
            if not _DIRTY.get(r) or (not force and time.time() - _SAVED.get(r, 0.0) < SAVE_EVERY):
                return
            data = dict(list(self.known.items())[-MOST:])
            _DIRTY[r] = 0
            _SAVED[r] = time.time()
        d = _dir(self.root)
        if d is None:
            return
        tmp = d / f".{FILE}.{os.getpid()}.tmp"
        try:
            tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
            os.replace(tmp, d / FILE)
        except OSError:
            pass


def holds_research(text: str) -> bool:
    """Whether a script or config can hold research at all: a `research-diff:` comment or a `research:` block."""
    return "research" in text or "Research" in text or "RESEARCH" in text


def forget(root: Path) -> None:
    """For tests: what was learned about a repository."""
    with _LOCK:
        _MEM.pop(str(Path(root).resolve()), None)
