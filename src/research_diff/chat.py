"""The web page's conversation with Claude: what was asked (from the page's Send to Claude box, or in the chat),
Claude's answers, what Claude POINTS AT in the evidence graph while it answers (the point_to tool), and the NOTES it
keeps beside a node (the note tool: a finding about a claim, a table, a result).

Kept under .git/research-diff/ (never committed): answers.jsonl, pointing.json, notes.json.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Dict, List, Optional

from . import activity, store

TAIL = 400_000
SECRETISH = re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*[=:]\s*\S+")


def _texts(content) -> List[str]:
    if isinstance(content, str):
        return [content]
    return [c.get("text", "") for c in content or [] if isinstance(c, dict) and c.get("type") == "text"]


def _is_prompt(content) -> bool:
    if isinstance(content, str):
        return True
    return isinstance(content, list) and any(isinstance(c, dict) and c.get("type") == "text" for c in content) and \
        not any(isinstance(c, dict) and c.get("type") == "tool_result" for c in content)


def transcript_answer(path: str) -> str:
    """The turn's final assistant text from a Claude Code transcript (JSONL), read from its tail."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - TAIL))
            raw = f.read().decode("utf-8", errors="replace")
    except (OSError, TypeError, ValueError):
        return ""
    turn: List[tuple] = []
    for line in raw.splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if not isinstance(d, dict) or d.get("isSidechain") or d.get("type") not in ("user", "assistant"):
            continue
        content = (d.get("message") or {}).get("content")
        if d["type"] == "user":
            turn = [] if _is_prompt(content) and not d.get("isMeta") else turn + [("tool", [])]
        else:
            turn.append(("said", [t for t in _texts(content) if t.strip()]))
    cut = max((i for i, (k, _t) in enumerate(turn) if k == "tool"), default=-1)
    last = [t for k, ts in turn[cut + 1:] if k == "said" for t in ts]
    if not last:
        last = [t for k, ts in turn if k == "said" for t in ts][-1:]
    return "\n\n".join(t.strip() for t in last).strip()


def answered(root: Path, payload: dict) -> Optional[dict]:
    """At Stop: keep the turn's answer with the request it answers. Never raises."""
    try:
        text = payload.get("last_assistant_message")
        if not isinstance(text, str) or not text.strip():
            text = transcript_answer(payload.get("transcript_path") or "")
        if not text.strip():
            return None
        prompt = activity.last_request(root)
        sent = {x.get("text") for x in store.lines(root, "delivered.jsonl", 50)}
        rec = {"prompt": prompt[:1000], "text": SECRETISH.sub(r"\1=***", text)[:8000], "web": prompt in sent,
               "pointing": pointing(root).get("ids", [])}
        store.append(root, "answers.jsonl", rec)
        return rec
    except Exception:  # noqa: BLE001
        return None


def answers(root: Path, last: int = 6) -> List[dict]:
    return store.lines(root, "answers.jsonl", last)


def point(root: Path, ids: List[str], note: str = "") -> dict:
    rec = {"at": time.time(), "ids": [str(i) for i in ids if str(i).strip()][:12], "note": note[:300],
           "question": activity.last_request(root)[:300]}
    store.write(root, "pointing.json", rec)
    return rec


def pointing(root: Path) -> dict:
    return store.read(root, "pointing.json", {}) or {}


def add_note(root: Path, node: str, text: str) -> dict:
    notes = store.read(root, "notes.json", {"items": []}) or {"items": []}
    rec = {"id": f"n{int(time.time() * 1000) % 10 ** 10}", "node": node, "text": text.strip()[:300],
           "at": time.time(), "question": activity.last_request(root)[:200]}
    notes["items"] = (notes["items"] + [rec])[-200:]
    store.write(root, "notes.json", notes)
    return rec


def clear_note(root: Path, nid: str) -> bool:
    notes = store.read(root, "notes.json", {"items": []}) or {"items": []}
    kept = [n for n in notes["items"] if n["id"] != nid]
    store.write(root, "notes.json", {"items": kept})
    return len(kept) != len(notes["items"])


def notes_by_node(root: Path) -> Dict[str, List[dict]]:
    out: Dict[str, List[dict]] = {}
    for n in (store.read(root, "notes.json", {"items": []}) or {"items": []})["items"]:
        out.setdefault(n["node"], []).append(n)
    return out
