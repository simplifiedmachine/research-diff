"""WORTH A LOOK: what a person should look at first in a research diff, ranked by consequence, each with why it
matters, in plain words. Built only from the diff (no LLM), so it never says what the markers do not.

Most consequence first: the paper contradicting itself, then a contradiction of a paper statement, a statement whose
verdict got worse, a hypothesis refuted, a number that stopped meeting what a claim expects, a claim left without
evidence, a number that moved under a claim, a status change; new ideas, links and numbers last.
"""
from __future__ import annotations

from typing import Dict, List, Optional

WORSE = {"supported": 0, "unsupported": 1, "contested": 2, "contradicted": 3}


def _title(nodes: Dict[str, dict], nid: str) -> str:
    n = nodes.get(nid) or {}
    return f"{nid} ({n['title'][:60]})" if n.get("title") else nid


def items(d: dict, after: Optional[dict] = None, objectives: Optional[List[dict]] = None) -> List[dict]:
    """[{score, title, why, ids, entity, op}] most consequential first."""
    nodes = (after or {}).get("nodes", {})
    out: List[dict] = []

    def add(score: int, title: str, why: str, ids: List[str], c: dict) -> None:
        out.append({"score": score, "title": title, "why": why, "ids": ids, "entity": c["entity"], "op": c["op"]})

    contradicted = {c["id"].split(" → ")[1] for c in d["changes"] if c["entity"] == "contradiction" and c["op"] == "add"}
    for c in d["changes"]:
        e, op = c["entity"], c["op"]
        if e == "warning" and op == "add" and c["id"].split()[0] in contradicted and any(
                w in c["id"] for w in (" is contradicted by ", " is weakened by ", " expects ", "which is refuted")):
            continue   # said already, as the contradiction it is
        if e == "contradiction":
            s, t = c["id"].split(" → ")
            kinds = (nodes.get(s, {}).get("kind"), nodes.get(t, {}).get("kind"))
            if op == "add":
                own = all(k in ("claim", "finding") for k in kinds)
                add(100 if own else 90,
                    f"{'The paper contradicts itself: ' if own else ''}{c['label']}",
                    "two statements of your own paper cannot both stand: one has to go, or be narrowed" if own else
                    f"{_title(nodes, t)} no longer stands on its own evidence; a reviewer will find this",
                    [s, t], c)
            else:
                add(25, f"Resolved: {c['label']}", "a contradiction you had is gone", [s, t], c)
        elif e == "verdict":
            old, new = [x.strip() for x in c["label"].split(": ", 1)[1].split("→")]
            back = {"no evidence": "unsupported"}
            worse = WORSE.get(back.get(new, new), 0) > WORSE.get(back.get(old, old), 0)
            add(80 if worse else 30, c["label"],
                ("; ".join(c["detail"]) or "its evidence changed") if worse else "its evidence got stronger",
                [c["id"]], c)
        elif e == "status":
            refuted = "refuted" in c["impact"]
            add(70 if refuted else 35, c["label"],
                "everything that relies on it loses its support" if refuted else "a status you set moved", [c["id"]], c)
        elif e == "warning" and op == "add":
            w = c["id"]
            score = 75 if " expects " in w else 60 if "relies on nothing" in w else 50
            add(score, w, "a claim's number no longer holds" if " expects " in w else
                "a claim with nothing behind it" if "relies on nothing" in w else "the map has a new gap", [w.split()[0]], c)
        elif e == "metric" and op == "change":
            nid = c["id"].split(" ", 1)[0]
            add(45, c["label"] + (f" ({c['detail'][0]})" if c["detail"] else ""), "a number the paper may quote moved",
                [nid], c)
        elif e in ("claim", "finding"):
            add(40 if op == "add" else 55, f"{'New' if op == 'add' else 'Dropped'} {e}: {c['label']}",
                "a statement in the paper" + (" — check what backs it" if op == "add" else " is gone"), [c["id"]], c)
        elif e in ("hypothesis", "experiment", "result", "question"):
            add(20, f"{'New' if op == 'add' else 'Dropped'} {e}: {c['label']}", "", [c["id"]], c)
        elif e == "warning":
            add(15, f"Resolved: {c['id']}", "", [c["id"].split()[0]], c)
        elif e == "link":
            add(10, f"{'New' if op == 'add' else 'Gone'} link: {c['id']}", "", c["id"].split()[::2], c)
        elif e == "metric":
            add(12, c["label"], "", [c["id"].split(" ", 1)[0]], c)
    for o in objectives or []:
        words = {w for w in o["text"].lower().split() if len(w) > 4}
        for it in out:
            if words & set(it["title"].lower().split()):
                it["score"] += 5
                it["objective"] = o["text"]
    out.sort(key=lambda x: (-x["score"], x["title"]))
    return out


def worth_a_look(d: dict, after: Optional[dict] = None, n: int = 5, objectives: Optional[List[dict]] = None) -> List[dict]:
    return [x for x in items(d, after, objectives) if x["score"] >= 30][:n]
