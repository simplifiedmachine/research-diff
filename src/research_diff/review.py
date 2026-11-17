"""The paper read against itself and its results by the person's own LLM: where one section contradicts another
(the abstract says more than the results show, the discussion takes back what the results claim), where a claim says
more than its evidence, where the text and the numbers disagree. What the markers and the number checks cannot see.

Every finding is checked before it is kept: each quote must be in the paper word for word (spacing aside), each
section named must exist, each id must be on the map. Kept in .git/research-diff/review.json with the paper's blob ids,
so a review stands until the paper changes. A finding between two marked statements can be written as a link
(`% contradicted by: C2` under C1) with `research-diff review --patch`, checked like `suggest --links`.

The review runs on `research-diff review`, the `review_paper` tool, and after a turn that changed the paper (in the
background, at most every few minutes); never with RESEARCH_DIFF_LLM=off.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

from . import compare, objectives, paper, paperview, store

FILE = "review.json"
MIN_GAP = 300
ASK: Optional[Callable[[str, str], Optional[str]]] = None
SYSTEM = (
    "You are a careful reviewer of a researcher's own paper. Find where the paper contradicts ITSELF (one section "
    "against another: abstract, introduction, results, discussion, conclusion), where the text and its numbers or "
    "tables disagree, and where a claim says more than its evidence. Only what the given text shows; quote it exactly. "
    "Answer with JSON only: {\"findings\": [{\"kind\": \"contradiction\"|\"numbers\"|\"overclaim\", \"sections\": "
    "[section titles], \"quotes\": [exact quotes from the text, each under 200 characters], \"ids\": [statement ids "
    "it concerns, if marked], \"why\": \"one or two sentences\"}]}; at most 8, most serious first; [] if none.")
KINDS = ("contradiction", "numbers", "overclaim")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", paper.plain(s)).strip().lower()


def material(root: Path, config_path: Optional[str] = None) -> dict:
    """What the review is given: every paper file's sections (plain text), the statements and their verdicts, the
    results' numbers; and the paper's blob ids, which the review is kept by."""
    g, bp, _cfg = compare.evidence_of(root, ".", config_path)
    files = [p["path"] for p in bp.get("paper", [])]
    secs, blobs = [], {}
    for f in files:
        o = paperview.outline(root, f, bp, g)
        blobs[f] = o.get("blob", "")
        secs += [{"file": f, "title": c["title"], "text": c["text"]} for c in o["chunks"] if c["text"].strip()]
    stmts = [{"id": s["id"], "section": s["section"], "verdict": s["verdict"], "title": s["title"]}
             for s in g["statements"]]
    nums = {k: n["metrics"] for k, n in bp["nodes"].items() if n["metrics"]}
    return {"sections": secs, "statements": stmts, "numbers": nums, "blobs": blobs, "ids": list(bp["nodes"]),
            "bp": bp}


def prompt(m: dict) -> str:
    body = "\n\n".join(f"### {s['title']} ({s['file']})\n{s['text']}" for s in m["sections"])[:60000]
    return ("Statements marked in the paper, with the verdict their evidence gives:\n" +
            "\n".join(f"- {s['id']} ({s['section']}, {s['verdict']}): {s['title']}" for s in m["statements"]) +
            "\n\nThe results' numbers:\n" + "\n".join(f"- {k}: " + ", ".join(f"{a}={b:g}" for a, b in v.items())
                                                     for k, v in m["numbers"].items()) +
            "\n\nThe paper, section by section:\n\n" + body)


def validate(answer: str, m: dict) -> List[dict]:
    hit = re.search(r"\{.*\}", answer or "", re.S)
    if not hit:
        return []
    try:
        data = json.loads(hit.group(0))
    except ValueError:
        return []
    text = " \n ".join(_norm(s["text"]) for s in m["sections"])
    titles = {s["title"] for s in m["sections"]}
    out = []
    for f in (data.get("findings") or [])[:8]:
        if not isinstance(f, dict):
            continue
        quotes = [str(q) for q in f.get("quotes") or [] if str(q).strip()]
        secs = [str(s) for s in f.get("sections") or []]
        ids = [str(i) for i in f.get("ids") or []]
        if not quotes or not all(_norm(q) in text for q in quotes):
            continue                      # a quote the paper does not have: not kept
        if any(s not in titles for s in secs) or any(i not in m["ids"] for i in ids):
            continue
        out.append({"kind": f.get("kind") if f.get("kind") in KINDS else "contradiction", "sections": secs,
                    "quotes": [q[:200] for q in quotes[:3]], "ids": ids, "why": str(f.get("why", ""))[:400]})
    return out


def _ask(root: Path, user: str) -> Optional[tuple]:
    if ASK is not None:
        got = ASK(user, SYSTEM)
        return (got, "test") if got else None
    if objectives.off() or os.environ.get("PYTEST_CURRENT_TEST"):
        return None
    from system_diff.narrate import complete
    return complete(user, SYSTEM, root, {}, timeout=240, limit=12000)


def run(root: Path, config_path: Optional[str] = None) -> dict:
    """Review the paper now; keep and return the review."""
    m = material(root, config_path)
    if not m["sections"]:
        return {"findings": [], "why": "no paper files (the `paper` globs of research-diff.toml) with text"}
    got = _ask(root, prompt(m))
    if not got:
        r = {"blobs": m["blobs"], "at": time.time(), "by": "", "findings": [], "why": "no LLM answered"}
    else:
        r = {"blobs": m["blobs"], "at": time.time(), "by": got[1], "findings": validate(got[0], m)}
    store.write(root, FILE, r)
    return r


def current(root: Path) -> dict:
    """The latest review, and whether the paper changed since (`stale`)."""
    r = store.read(root, FILE, None) or {}
    if not r:
        return {}
    stale = False
    for f, b in (r.get("blobs") or {}).items():
        try:
            stale |= paperview.blob_id((Path(root) / f).read_bytes()) != b
        except OSError:
            stale = True
    return {**r, "stale": stale}


def ensure(root: Path) -> bool:
    """After a turn: review again in the background when the paper changed and the last review is not too recent."""
    try:
        if objectives.off() or os.environ.get("PYTEST_CURRENT_TEST"):
            return False
        r = current(root)
        if r and (not r.get("stale") or time.time() - r.get("at", 0) < MIN_GAP):
            return False
        flags = {"start_new_session": True} if os.name != "nt" else {"creationflags": 0x08000000 | 0x00000200}
        subprocess.Popen([sys.executable, "-m", "research_diff", "--repo", str(root), "review", "--quiet"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **flags)
        return True
    except Exception:  # noqa: BLE001 - never in the way of a turn
        return False


def links_from(r: dict, bp: dict) -> List[dict]:
    """Findings between two marked statements, as links for suggest's patch: the later one contradicts the earlier."""
    out = []
    for f in r.get("findings", []):
        ids = [i for i in f["ids"] if bp["nodes"].get(i, {}).get("kind") in ("claim", "finding")]
        if f["kind"] == "contradiction" and len(ids) >= 2:
            out.append({"from": ids[1], "rel": "contradicts", "to": ids[0], "why": f["why"]})
    return out


def as_text(r: dict) -> str:
    if not r:
        return "No review yet: research-diff review (it asks your LLM)."
    head = f"Review of the paper{' (the paper changed since: run it again)' if r.get('stale') else ''}" + \
        (f", by {r['by']}" if r.get("by") else "") + f": {len(r.get('findings', []))} finding(s)"
    lines = [head] + ([f"  {r['why']}"] if r.get("why") else [])
    for f in r.get("findings", []):
        lines.append(f"\n✦ {f['kind']}" + (f" ({' vs '.join(f['sections'])})" if f["sections"] else "") +
                     (f" [{', '.join(f['ids'])}]" if f["ids"] else "") + f": {f['why']}")
        lines += [f"    “{q}”" for q in f["quotes"]]
    return "\n".join(lines)


def headline(r: dict) -> str:
    n = len(r.get("findings", []))
    return "" if not r else f"✦ review: {n} finding{'' if n == 1 else 's'}" + (" (paper changed since)" if r.get(
        "stale") else "")


def worth(r: dict) -> List[dict]:
    """The review's findings as worth-a-look items (marked ✦: an LLM's reading, checked against the text)."""
    return [{"score": 85 if f["kind"] == "contradiction" else 65, "title": f"✦ {f['why']}",
             "why": " / ".join(f"“{q}”" for q in f["quotes"][:2]), "ids": f["ids"], "entity": "review", "op": "add"}
            for f in r.get("findings", []) if not r.get("stale")]


def evidence_for(r: dict) -> Dict[str, List[str]]:
    by: Dict[str, List[str]] = {}
    for f in r.get("findings", []):
        for i in f["ids"]:
            by.setdefault(i, []).append(f["why"])
    return by

