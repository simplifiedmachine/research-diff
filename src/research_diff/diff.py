"""What an iteration did to the research: ideas added or dropped, statuses that moved, numbers that changed, links made
or broken, and warnings that appeared or went away. One sentence (headline) and the exact list (plan)."""
from __future__ import annotations

from typing import Dict, List

PLURAL = {"question": "questions", "hypothesis": "hypotheses", "experiment": "experiments", "result": "results",
          "claim": "claims", "note": "notes"}


def _num(x: float) -> str:
    return f"{x:.4g}"


def diff(a: dict, b: dict) -> dict:
    changes: List[dict] = []

    def add(op, entity, key, label="", detail=(), impact=()):
        changes.append({"op": op, "entity": entity, "id": key, "label": label or key, "detail": list(detail),
                        "impact": list(impact)})

    na, nb = a["nodes"], b["nodes"]
    for nid in [k for k in nb if k not in na] + [k for k in na if k not in nb]:
        n = nb.get(nid) or na[nid]
        op = "add" if nid in nb else "remove"
        add(op, n["kind"], nid, f"{nid}: {n['title']}" if n["title"] else nid,
            [f"status: {n['status']}"] if n["status"] and op == "add" else [], [("new-" if op == "add" else "dropped-") + n["kind"]])
    for nid in [k for k in nb if k in na]:
        x, y = na[nid], nb[nid]
        if x["status"] != y["status"]:
            impact = "refuted" if y["status"] == "refuted" else "supported" if y["status"] == "supported" else "status-change"
            add("change", "status", nid, f"{nid}: {x['status'] or 'no status'} → {y['status'] or 'no status'}", [], [impact])
        if x["title"] != y["title"] and x["title"] and y["title"]:
            add("change", "title", nid, f"{nid}: {y['title']}", [f"was: {x['title']}"])
        for key in sorted(set(x["metrics"]) | set(y["metrics"])):
            u, v = x["metrics"].get(key), y["metrics"].get(key)
            if u == v:
                continue
            if u is None:
                add("add", "metric", f"{nid} {key}", f"{nid} {key}: {_num(v)}", [], ["new-result"])
            elif v is None:
                add("remove", "metric", f"{nid} {key}", f"{nid} {key}", [f"was {_num(u)}"], ["dropped-result"])
            else:
                d = v - u
                add("change", "metric", f"{nid} {key}", f"{nid} {key}: {_num(u)} → {_num(v)}",
                    [f"{'+' if d >= 0 else '−'}{_num(abs(d))}" + (f" ({d / u * 100:+.1f}%)" if u else "")], ["result-moved"])
    la, lb = {tuple(x) for x in a["links"]}, {tuple(x) for x in b["links"]}
    for link in sorted(lb - la) + sorted(la - lb):
        add("add" if link in lb else "remove", "link", " ".join(link), "", [], [])
    wa, wb = set(a["warnings"]), set(b["warnings"])
    for w in sorted(wb - wa):
        add("add", "warning", w, "", [], ["new-warning"])
    for w in sorted(wa - wb):
        add("remove", "warning", w, "", [], ["resolved-warning"])
    return {"from": a["ref"], "to": b["ref"], "changes": changes, "headline": headline(changes),
            "plan": plan(changes), "warnings": b["warnings"]}


def headline(changes: List[dict]) -> str:
    """One sentence: what the iteration did to the research."""
    parts: List[str] = []
    for op, verb in (("add", "adds"), ("remove", "drops")):
        groups: Dict[str, List[str]] = {}
        for c in changes:
            if c["op"] == op and c["entity"] in PLURAL:
                groups.setdefault(c["entity"], []).append(c["id"])
        phrases = [f"{len(ids)} {k if len(ids) == 1 else PLURAL[k]} ({', '.join(ids[:3])}{' +' + str(len(ids) - 3) + ' more' if len(ids) > 3 else ''})"
                   for k, ids in groups.items()]
        if phrases:
            parts.append(verb + " " + (", ".join(phrases[:-1]) + " and " + phrases[-1] if len(phrases) > 1 else phrases[0]))
    parts += [c["label"] for c in changes if c["entity"] == "status"]
    moved = [c for c in changes if c["entity"] == "metric" and c["op"] == "change"]
    if moved:
        shown = "; ".join(f"{c['label']} ({c['detail'][0]})" for c in moved[:2])
        parts.append(shown + (f" and {len(moved) - 2} more numbers" if len(moved) > 2 else ""))
    new_metrics = [c for c in changes if c["entity"] == "metric" and c["op"] == "add"]
    if new_metrics:
        parts.append(f"{len(new_metrics)} new number{'' if len(new_metrics) == 1 else 's'}")
    links = [c for c in changes if c["entity"] == "link"]
    if links:
        made = sum(1 for c in links if c["op"] == "add")
        parts.append(" and ".join(x for x in (f"{made} new link{'' if made == 1 else 's'}" if made else "",
                                              f"{len(links) - made} link{'' if len(links) - made == 1 else 's'} gone"
                                              if len(links) - made else "") if x))
    new_w = [c["id"] for c in changes if c["entity"] == "warning" and c["op"] == "add"]
    if new_w:
        parts.append(f"{len(new_w)} new warning{'' if len(new_w) == 1 else 's'} ({new_w[0]}{'…' if len(new_w) > 1 else ''})")
    gone_w = sum(1 for c in changes if c["entity"] == "warning" and c["op"] == "remove")
    if gone_w:
        parts.append(f"{gone_w} warning{'' if gone_w == 1 else 's'} resolved")
    if not parts:
        return "No change to the research."
    s = "; ".join(parts)
    return s[0].upper() + s[1:] + "."


def plan(changes: List[dict]) -> str:
    """The exact list, `terraform plan`-style."""
    sym = {"add": "+", "change": "~", "remove": "-"}
    out = []
    for c in changes:
        tag = f"   [{', '.join(c['impact'])}]" if c["impact"] else ""
        label = f" — {c['label']}" if c["label"] != c["id"] else ""
        out.append(f"{sym[c['op']]} {c['entity']} {c['id']}{label}{tag}")
        out += [f"    {x}" for x in c["detail"]]
    return "\n".join(out) or "no change to the research"
