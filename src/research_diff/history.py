"""How the research got here: a timeline of what changed in it, each told as what the person asked for and what the
research got ("You asked: run the LR-scaling ablation → it got: R2, H1 supported → contested, 1 new contradiction (C2
contradicts C1)"). For the whole study or one node.

ENTRIES come from two places:
  turn     the Stop hook, when a turn changed the research: the request it came under, the diff of the turn
  commit   git: each commit that changed the research, against its parent (`research-diff history --commits N`)

Each: {"id", "at", "source", "request", "commit", "message", "headline", "items" (worth a look, ranked), "ids" (every
node it touched), "by" (the agents that edited)}. Kept in .git/research-diff/history.jsonl.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import List, Optional, Tuple

from system_diff.sources import git

from . import config, store
from .diff import diff
from .extract import extract
from .rank import items

FILE = "history.jsonl"


def touched(d: dict) -> List[str]:
    ids: List[str] = []
    for c in d["changes"]:
        if c["entity"] == "warning":
            continue
        for part in c["id"].replace("→", " ").split():
            if part[:1].isupper() and part[1:2].isdigit() and part not in ids:
                ids.append(part)
    return ids


def entry(d: dict, after: dict, source: str, request: str = "", commit: str = "", message: str = "",
          by: Optional[List[str]] = None, at: Optional[float] = None, base: str = "", head: str = "") -> dict:
    ranked = items(d, after)
    key = f"{source}:{commit or ''}:{at or time.time()}:{d['headline']}"
    return {"id": hashlib.sha1(key.encode()).hexdigest()[:10], "at": at or round(time.time(), 1), "source": source,
            "request": request[:300], "commit": commit, "message": message, "headline": d["headline"],
            "items": [{k: x[k] for k in ("title", "why", "ids", "score")} for x in ranked[:8]], "ids": touched(d),
            "by": by or [], "base": base, "head": head,
            "sentence": (ranked[0]["title"] if ranked else d["headline"])}


def record(root: Path, e: dict) -> None:
    store.append(root, FILE, e)


def load(root: Path, node: str = "", last: int = 200) -> List[dict]:
    got = store.lines(root, FILE)
    got += [e for e in commits(root) if not any(x.get("commit") == e["commit"] for x in got)]
    got.sort(key=lambda e: e.get("at", 0))
    if node:
        got = [e for e in got if node in e.get("ids", [])]
    return got[-last:]


def commits(root: Path, n: int = 0) -> List[dict]:
    """The research's history from git: each of the last `n` commits (0: those cached) that changed the research."""
    cache = store.read(root, "commits.json", {}) or {}
    if n:
        try:
            log = git("log", f"-{n}", "--format=%H%x09%ct%x09%s", cwd=root).strip().splitlines()
        except (OSError, subprocess.CalledProcessError):
            log = []
        for line in reversed(log):
            sha, ct, msg = line.split("\t", 2)
            if sha in cache:
                continue
            try:
                parent = git("rev-parse", "--verify", "-q", f"{sha}^", cwd=root).strip()
            except subprocess.CalledProcessError:
                parent = ""
            from .compare import CommitTree
            src = CommitTree(sha, root)
            cfg = config.load(src, root)
            b = extract(src, cfg)
            a = extract(CommitTree(parent, root), cfg) if parent else {"ref": "", "nodes": {}, "links": [],
                                                                       "warnings": []}
            d = diff(a, b, cfg)
            cache[sha] = entry(d, b, "commit", commit=sha[:9], message=msg, at=float(ct), base=parent,
                               head=sha) if d["changes"] else None
        store.write(root, "commits.json", cache)
    return [e for e in cache.values() if e]


RECENT = 30                 # the commits the History tab reads
_FILLING: set = set()
_FILL_LOCK = threading.Lock()
EMPTY = {"ref": "", "nodes": {}, "links": [], "warnings": []}


def _cache_name(sid: str) -> str:
    return f"commits-{re.sub(r'[^A-Za-z0-9_.-]+', '_', sid)}.json" if sid else "commits.json"


_LOGS: dict = {}


def _log(root: Path, n: int, spec: tuple) -> List[str]:
    """`git log` of the last n commits (of some paths), asked once per HEAD: a program start costs seconds on some
    machines, and the same HEAD has the same history."""
    try:
        from system_diff import gitfs
        head = gitfs.head(root)
    except Exception:  # noqa: BLE001
        head = None
    key = (str(root), head, n, spec)
    if head is not None and key in _LOGS:
        return _LOGS[key]
    try:
        log = git("log", f"-{n}", "--format=%H%x09%ct%x09%s", *spec, cwd=root).strip().splitlines()
    except Exception:  # noqa: BLE001 - no commits yet, or git cannot say
        log = []
    log = [ln for ln in log if ln.count("\t") >= 2]
    if head is not None:
        _LOGS[key] = log
        while len(_LOGS) > 64:
            _LOGS.pop(next(iter(_LOGS)))
    return log


def commits_of(root: Path, scope: Optional[tuple] = None, sid: str = "", n: int = RECENT,
               read: bool = False) -> Tuple[List[dict], int]:
    """One study's history from git (the whole repository's without one): its last `n` commits that changed the
    research, each against its parent, oldest first; and how many of them are not read yet. `read` reads those (each
    commit's research once: a commit never changes, so they are kept, one file per study)."""
    root = Path(root)
    name = _cache_name(sid)
    cache = store.read(root, name, {}) or {}
    spec: List[str] = []
    if scope:                          # its folder, and its own folder inside a shared one (results/<study>/...)
        mine = scope[0].strip("/")
        spec = ["--", f"{mine}/", f":(glob)*/{mine}/**"]
    log = _log(root, n, tuple(spec))
    todo = [ln for ln in log if ln.split("\t", 1)[0] not in cache]
    if read and todo:
        memo: dict = {}

        from .compare import CommitTree

        def research_at(sha: str) -> Tuple[dict, dict]:
            if sha not in memo:
                src = CommitTree(sha, root)             # its submodules' papers too, at the commits it records
                cfg = config.load(src, root)
                memo[sha] = (extract(src, cfg, scope), cfg)
            return memo[sha]
        for line in reversed(todo):     # oldest first: a commit's parent is often the one read just before
            sha, ct, msg = line.split("\t", 2)
            try:
                parent = git("rev-parse", "--verify", "-q", f"{sha}^", cwd=root).strip()
            except (OSError, subprocess.CalledProcessError):
                parent = ""
            try:
                b, cfg = research_at(sha)
                a = research_at(parent)[0] if parent else EMPTY
                d = diff(a, b, cfg)
                cache[sha] = entry(d, b, "commit", commit=sha[:9], message=msg, at=float(ct), base=parent,
                                   head=sha) if d["changes"] else None
            except Exception:  # noqa: BLE001 - a commit that cannot be read is left out, the others go on
                cache[sha] = None
        store.write(root, name, cache)       # once: every write moves the engine's version and redraws the pages
        todo = []
    listed = [ln.split("\t", 1)[0] for ln in reversed(log)]
    return [cache[x] for x in listed if cache.get(x)], len(todo)


def fill(root: Path, scope: Optional[tuple] = None, sid: str = "", n: int = RECENT) -> bool:
    """Read the commits not read yet in the background (in the foreground under tests); True while it goes on."""
    key = (str(Path(root).resolve()), sid)
    if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("RESEARCH_DIFF_HOOK_SYNC"):
        commits_of(root, scope, sid, n, read=True)
        return False
    with _FILL_LOCK:
        if key in _FILLING:
            return True
        _FILLING.add(key)

    def run() -> None:
        try:
            commits_of(root, scope, sid, n, read=True)
        finally:
            with _FILL_LOCK:
                _FILLING.discard(key)
    threading.Thread(target=run, name="research-diff history", daemon=True).start()
    return True


def for_study(root: Path, scope: Optional[tuple] = None, sid: str = "", n: int = RECENT) -> Tuple[List[dict], bool]:
    """What the History tab lists, oldest first: the turns kept (the whole repository's, when it is one study) and the
    study's last commits; True while commits are still being read."""
    got, missing = commits_of(root, scope, sid, n)
    reading = fill(root, scope, sid, n) if missing else False
    if missing and not reading:                 # read just now, in the foreground
        got, _ = commits_of(root, scope, sid, n)
    turns = [] if sid else store.lines(root, FILE)
    out = turns + [e for e in got if not any(t.get("commit") == e["commit"] for t in turns)]
    return sorted(out, key=lambda e: e.get("at", 0)), reading


def text(entries: List[dict]) -> str:
    out = []
    for e in entries:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(e["at"]))
        who = f" [{', '.join(e['by'])}]" if e.get("by") else ""
        head = f"You asked: “{e['request']}”" if e.get("request") else \
            f"Commit {e['commit']}: {e['message']}" if e.get("commit") else "A change no request explains"
        out.append(f"{when}{who}  {head}\n    → {e.get('sentence') or e['headline']}   [{e['id']}]")
        for x in e["items"][:3]:
            out.append(f"      · {x['title']}" + (f" — {x['why']}" if x["why"] else ""))
    return "\n".join(out) or "No history yet: it is kept from the next turn that changes the research " \
                             "(or run: research-diff history --commits 50)."


def compare_points(root: Path, a: str, b: str):
    """What changed between two points of the research's life: history entries (by id: the state after each) or git
    refs, or `.` (the working tree)."""
    from . import compare as cmp
    entries = {e["id"]: e for e in load(root, last=10_000)}

    def point(x: str) -> str:
        e = entries.get(x)
        if e is None:
            return x
        return e.get("head") or (e.get("commit") and git("rev-parse", e["commit"], cwd=root).strip()) or x
    return cmp.compare(root, point(a), point(b))
