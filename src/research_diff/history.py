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
import subprocess
import time
from pathlib import Path
from typing import List, Optional

from system_diff.sources import GitSource, git

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
          by: Optional[List[str]] = None, at: Optional[float] = None) -> dict:
    ranked = items(d, after)
    key = f"{source}:{commit or ''}:{at or time.time()}:{d['headline']}"
    return {"id": hashlib.sha1(key.encode()).hexdigest()[:10], "at": at or round(time.time(), 1), "source": source,
            "request": request[:300], "commit": commit, "message": message, "headline": d["headline"],
            "items": [{k: x[k] for k in ("title", "why", "ids", "score")} for x in ranked[:8]], "ids": touched(d),
            "by": by or []}


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
            src = GitSource(sha, root)
            cfg = config.load(src, root)
            b = extract(src, cfg)
            a = extract(GitSource(parent, root), cfg) if parent else {"ref": "", "nodes": {}, "links": [],
                                                                       "warnings": []}
            d = diff(a, b, cfg)
            cache[sha] = entry(d, b, "commit", commit=sha[:9], message=msg, at=float(ct)) if d["changes"] else None
        store.write(root, "commits.json", cache)
    return [e for e in cache.values() if e]


def text(entries: List[dict]) -> str:
    out = []
    for e in entries:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(e["at"]))
        who = f" [{', '.join(e['by'])}]" if e.get("by") else ""
        head = f"You asked: “{e['request']}”" if e.get("request") else \
            f"Commit {e['commit']}: {e['message']}" if e.get("commit") else "A change no request explains"
        out.append(f"{when}{who}  {head}\n    → it got: {e['headline']}")
        for x in e["items"][:3]:
            out.append(f"      · {x['title']}" + (f" — {x['why']}" if x["why"] else ""))
    return "\n".join(out) or "No history yet: it is kept from the next turn that changes the research " \
                             "(or run: research-diff history --commits 50)."
