"""What the person is optimising the study for: the things they keep asking for while they iterate ("three seeds for
every number", "don't overclaim beyond the 8k split", "keep the paper under 8 pages", "compare against warm-up"),
learned from their own requests by an LLM in the background, or added by them. Kept in front of them (the pane, the
web page) and in front of Claude and every agent (the hooks' context), and cleared by them when wrong.

Each objective: {"id", "text", "evidence": [the person's own words], "since", "by": "llm"|"person"}. An LLM's objective
is kept only if every quote it gives is in a request the person really sent.

The LLM is the one your Claude Code uses (system-diff's narrate.complete finds it); RESEARCH_DIFF_LLM=off (or
SYSTEM_DIFF_LLM=off) turns it off. Only the requests are sent, never the files.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, List, Optional

from . import activity, store

FILE = "objectives.json"
MIN_NEW = 3            # requests since the last learning before learning again
MIN_GAP = 600          # seconds between two learnings
SYSTEM = (
    "You read the requests a researcher sent to their AI assistant while running experiments and writing a paper, and "
    "list what they keep optimising the study for: standards for evidence, scope of the claims, methods they insist "
    "on, constraints on the paper. Only what they asked for more than once or stated as a rule. Each objective is one "
    "short imperative sentence. For each, quote the exact words from their requests that show it. Answer with JSON "
    "only: {\"objectives\": [{\"text\": \"...\", \"evidence\": [\"exact quote\", ...]}]}; at most 6.")


def off() -> bool:
    return os.environ.get("RESEARCH_DIFF_LLM", "").lower() in ("off", "0", "no", "false") or \
        os.environ.get("SYSTEM_DIFF_LLM", "").lower() in ("off", "0", "no", "false")


def _state(root: Path) -> dict:
    s = store.read(root, FILE, None) or {}
    s.setdefault("objectives", [])
    s.setdefault("cleared", [])
    s.setdefault("learned_at", 0)
    s.setdefault("learned_upto", 0)
    return s


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]


def current(root: Path) -> List[dict]:
    try:
        s = _state(root)
    except Exception:  # noqa: BLE001
        return []
    return [o for o in s["objectives"] if o["id"] not in s["cleared"]]


def add(root: Path, text: str, by: str = "person", evidence: Optional[List[str]] = None) -> dict:
    s = _state(root)
    oid = slug(text)
    s["cleared"] = [c for c in s["cleared"] if c != oid]
    o = next((x for x in s["objectives"] if x["id"] == oid), None)
    if o is None:
        o = {"id": oid, "text": text.strip(), "evidence": evidence or [], "since": time.strftime("%Y-%m-%d"), "by": by}
        s["objectives"].append(o)
    store.write(root, FILE, s)
    return o


def clear(root: Path, oid: str) -> bool:
    s = _state(root)
    if not any(o["id"] == oid for o in s["objectives"]) or oid in s["cleared"]:
        return False
    s["cleared"].append(oid)
    store.write(root, FILE, s)
    return True


def restore(root: Path, oid: str) -> bool:
    s = _state(root)
    if oid not in s["cleared"]:
        return False
    s["cleared"].remove(oid)
    store.write(root, FILE, s)
    return True


def context(root: Path) -> str:
    got = current(root)
    if not got:
        return ""
    return "The person's objectives for this study (learned from their requests; respect them):\n" + \
        "\n".join(f"- {o['text']}" for o in got)


def validate(answer: str, requests: List[str]) -> List[dict]:
    m = re.search(r"\{.*\}", answer, re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return []
    said = " \n ".join(r.lower() for r in requests)
    out = []
    for o in data.get("objectives", [])[:6]:
        text, quotes = str(o.get("text", "")).strip(), [str(q).strip() for q in o.get("evidence", []) if str(q).strip()]
        if text and quotes and all(q.lower() in said for q in quotes):
            out.append({"text": text[:160], "evidence": quotes[:3]})
    return out


def learn(root: Path, ask: Optional[Callable[[str, str], Optional[str]]] = None) -> List[dict]:
    """Ask the LLM for the objectives in the person's requests; keep the ones whose quotes check out."""
    reqs = activity.requests(root, 80)
    texts = [r.get("text", "") for r in reqs if r.get("text")]
    s = _state(root)
    s["learned_at"] = time.time()
    s["learned_upto"] = reqs[-1]["at"] if reqs else s["learned_upto"]
    store.write(root, FILE, s)
    if not texts:
        return []
    if ask is None:
        if off():
            return []
        from system_diff.narrate import complete

        def ask(user: str, system: str) -> Optional[str]:
            got = complete(user, system, root, {}, timeout=120, limit=6000)
            return got[0] if got else None
    answer = ask("The researcher's requests, oldest first:\n" + "\n".join(f"{i}. {t[:500]}" for i, t in
                                                                          enumerate(texts, 1)), SYSTEM) or ""
    found = validate(answer, texts)
    for o in found:
        add(root, o["text"], by="llm", evidence=o["evidence"])
    return found


def ensure(root: Path) -> bool:
    """Cheap enough for every prompt: start learning in the background when enough is new. Never waits or raises."""
    try:
        if off():
            return False
        s = _state(root)
        reqs = activity.requests(root, 50)
        new = [r for r in reqs if r.get("at", 0) > s["learned_upto"]]
        if len(new) < MIN_NEW or time.time() - s["learned_at"] < MIN_GAP:
            return False
        s["learned_at"] = time.time()
        store.write(root, FILE, s)
        flags = {"start_new_session": True} if os.name != "nt" else {"creationflags": 0x08000000 | 0x00000200}
        subprocess.Popen([sys.executable, "-m", "research_diff", "--repo", str(root), "objectives", "learn"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **flags)
        return True
    except Exception:  # noqa: BLE001 - never in the way of a prompt
        return False
