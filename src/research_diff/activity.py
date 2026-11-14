"""What the AI agent is doing, as it does it: the person's requests, and the files it reads and edits (written by
Claude Code's hooks), each with the agent that did it (Claude Code's `agent_id` for a subagent; "main" otherwise).

From these, the FOCUS: the research node being worked on now (the marker in the file last edited, else last read), which
the pane zooms in on and the status line names. And the TURN: the working tree as it was when the person last sent a
prompt, so a diff can show what this one turn did (`--base turn`).

Kept in .git/research-diff/activity.jsonl; state.json holds the latest look in a few words, for the status line.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import store

LOG = "activity.jsonl"
STATE = "state.json"


def record(root: Path, kind: str, **fields) -> None:
    store.append(root, LOG, {"kind": kind, **{k: v for k, v in fields.items() if v not in (None, "")}})


def events(root: Path, last: int = 300) -> List[dict]:
    return store.lines(root, LOG, last)


def relative(root: Path, path: str) -> str:
    try:
        return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except (ValueError, OSError):
        return path.replace("\\", "/")


def nodes_in(bp: dict, path: str) -> List[str]:
    return [nid for nid, n in bp["nodes"].items() if path in n["files"]]


def focus(root: Path, bp: dict, agent: str = "") -> Optional[Tuple[str, str, str]]:
    """(node id, "editing"|"reading", agent) the agent last worked on; None when nothing it touched is on the map."""
    for ev in reversed(events(root)):
        if ev.get("kind") not in ("edit", "read") or (agent and ev.get("agent", "main") != agent):
            continue
        ids = nodes_in(bp, ev.get("path", ""))
        if ids:
            return ids[0] if len(ids) == 1 else _closest(bp, ids, ev.get("line", 0)), \
                "editing" if ev["kind"] == "edit" else "reading", ev.get("agent", "main")
    return None


def _closest(bp: dict, ids: List[str], line: int) -> str:
    if not line:
        return ids[-1]
    before = [i for i in ids if bp["nodes"][i].get("line", 0) <= line]
    return max(before, key=lambda i: bp["nodes"][i].get("line", 0)) if before else ids[0]


def requests(root: Path, last: int = 50) -> List[dict]:
    return [e for e in events(root, 2000) if e.get("kind") == "prompt"][-last:]


def last_request(root: Path) -> str:
    got = requests(root, 1)
    return got[-1].get("text", "") if got else ""


def edited_since(root: Path, since: float) -> Dict[str, List[str]]:
    """{agent: [paths]} edited since a time."""
    out: Dict[str, List[str]] = {}
    for e in events(root, 1000):
        if e.get("kind") == "edit" and e.get("at", 0) >= since and e.get("path"):
            paths = out.setdefault(e.get("agent", "main"), [])
            if e["path"] not in paths:
                paths.append(e["path"])
    return out


def write_state(root: Path, **fields) -> None:
    store.write(root, STATE, {"at": time.time(), **fields})


def read_state(root: Path) -> dict:
    return store.read(root, STATE, {}) or {}


def ago(t: float) -> str:
    s = max(0, int(time.time() - t))
    return f"{s}s ago" if s < 60 else f"{s // 60}m ago" if s < 3600 else f"{s // 3600}h ago" if s < 86400 \
        else f"{s // 86400}d ago"
