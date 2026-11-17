"""The EVIDENCE GRAPH: which statements of the paper (claims and findings) are backed by which evidence (results,
runs, experiments' numbers, hypotheses, other statements, optionally citations), and above all which evidence
CONTRADICTS them, including the paper's own statements contradicting each other.

Every edge comes from a marker, so the same files always give the same graph:

  supports / supported by     R1 supports C1                       + support
  relies on                   C1 relies on H1                      + support, as long as H1 holds
  expects                     C1 expects E1.results acc > 0.85     + when the number meets it, - when it does not
  contradicts / refutes       R4 contradicts C1, C2 contradicts C1 - contradiction
  weakens                     R2 weakens H1                        - contradiction (a weaker one)

A support only counts while its source HOLDS (one with no evidence of its own is UNGROUNDED: drawn, not counted): a result or hypothesis that is refuted, or that is itself contradicted,
breaks the support it gave (a BROKEN SUPPORT, said with why: "C1 relies on H1, which R4 contradicts"). So a
contradiction reaches every statement built on what it contradicts.

Each statement gets a VERDICT:
  supported     evidence for it, none against it
  contested     evidence for it and against it
  contradicted  evidence against it, none for it (or the person marked it refuted)
  unsupported   no evidence either way

Owners: who (which agent) owns each node, from the marker's own `by:` line, else the agents' claims (agents.py), so the
graph shows where one agent's result contradicts another agent's claim.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from .extract import EXPECT_RX, OPS

REFUTED = {"refuted", "rejected", "retracted", "false", "wrong", "failed", "dropped"}
SUPPORTED = {"supported", "confirmed", "true", "accepted", "verified"}
VERDICTS = ("contradicted", "contested", "unsupported", "supported")
WORD = {"contradicted": "contradicted", "contested": "contested", "unsupported": "no evidence",
        "supported": "supported", "holds": "holds"}


def _role(kind: str, statements: set) -> str:
    return "statement" if kind in statements else "hypothesis" if kind == "hypothesis" else "evidence"


def _edges(bp: dict, cfg: dict) -> List[dict]:
    nodes = bp["nodes"]
    out: Dict[tuple, dict] = {}

    def add(frm: str, to: str, sign: str, kind: str, why: str) -> None:
        out.setdefault((frm, to, kind), {"from": frm, "to": to, "sign": sign, "kind": kind, "why": why})

    for s, rel, t in bp["links"]:
        if s not in nodes or t not in nodes or s == t:
            continue
        if rel == "supports":
            add(s, t, "+", "supports", f"{s} supports {t}")
        elif rel == "relies on":
            add(t, s, "+", "relies on", f"{s} relies on {t}")
        elif rel == "contradicts":
            add(s, t, "-", "contradicts", f"{s} contradicts {t}")
        elif rel == "weakens":
            add(s, t, "-", "weakens", f"{s} weakens {t}")
        elif rel == "shows" and nodes[s]["kind"] in ("table", "figure"):
            add(s, t, "+", "shows", f"{t} points at {s}" + (f" ({nodes[s]['title'][:50]})" if nodes[s]["title"] else ""))
    for nid, n in nodes.items():
        for e in n.get("expects", []):
            m = EXPECT_RX.match(e)
            if not m or m.group(1) not in nodes:
                continue
            target, metric, op, want = m.group(1), m.group(2), m.group(3), float(m.group(4))
            got = nodes[target]["metrics"].get(metric)
            if got is None:
                continue
            if OPS[op](got, want):
                add(target, nid, "+", "expects", f"{metric} = {got:g}, as {nid} expects ({op} {want:g})")
            else:
                add(target, nid, "-", "expects", f"{metric} = {got:g}, but {nid} expects {op} {want:g}")
    for c in bp.get("checks", []):         # the numbers the paper prints, against the results (paper.py)
        if c["from"] in nodes and c["to"] in nodes:
            out.setdefault((c["from"], c["to"], "number" + c["sign"]),
                           {"from": c["from"], "to": c["to"], "sign": c["sign"], "kind": "number", "why": c["why"]})
    if cfg.get("evidence", {}).get("citations"):
        for nid, n in nodes.items():
            for key in n.get("sources", []):
                add(f"cite:{key}", nid, "+", "cites", f"{nid} cites {key}")
    return [out[k] for k in sorted(out)]


def build(bp: dict, cfg: dict, owners: Optional[Dict[str, str]] = None) -> dict:
    """The evidence graph of a research map: nodes, edges, a verdict per statement, conflicts, and one sentence."""
    statements = set(cfg.get("evidence", {}).get("statements", ["claim", "finding"])) | {"paragraph"}
    # A paragraph with no marker whose numbers disagree with the results (an abstract restating an old number) is a
    # statement of the paper too: drawn in its section, contradicted by the result.
    nodes = dict(bp["nodes"])
    for i in bp.get("issues", []):
        nodes.setdefault(i["node"], {"kind": "paragraph", "title": i.get("text") or f"a paragraph of {i['section']}",
                                     "status": "", "files": [i["file"]], "metrics": {}, "sources": [],
                                     "section": i["section"], "line": int(i["node"].rsplit(":", 1)[1])})
    bp = {**bp, "nodes": nodes, "checks": list(bp.get("checks", [])) + [
        {"from": i["from"], "to": i["node"], "sign": "-", "why": i["why"]} for i in bp.get("issues", [])]}
    edges = _edges(bp, cfg)
    owners = owners or {}
    into: Dict[str, List[dict]] = {}
    for e in edges:
        into.setdefault(e["to"], []).append(e)

    verdict: Dict[str, str] = {}
    against: Dict[str, List[dict]] = {}
    backing: Dict[str, List[dict]] = {}
    voided: Dict[str, List[dict]] = {}
    visiting: set = set()

    def judge(nid: str) -> str:
        if nid in verdict:
            return verdict[nid]
        if nid in visiting:          # a cycle (C1 relies on C2 relies on C1): judged by what is known so far
            return "holds"
        visiting.add(nid)
        n = nodes.get(nid, {"status": "", "kind": "source"})
        pro, con, void, weak = [], [], [], []
        for e in into.get(nid, []):
            src = judge(e["from"])
            if e["sign"] == "-" and src == "contradicted" and e["from"] != nid:
                void.append({**e, "effective": "0", "why": e["why"] + f" (but {e['from']} is itself contradicted)"})
            elif e["sign"] == "-":
                con.append({**e, "effective": "-"})
            elif src == "unsupported" and e["sign"] == "+":
                weak.append({**e, "effective": "o", "why": e["why"] + f" (but {e['from']} has no evidence yet)"})
            elif src in ("contradicted",):
                why = _broken(e, nodes, against.get(e["from"], []))
                con.append({**e, "effective": "?", "why": why})
            else:
                pro.append({**e, "effective": "+" if src != "contested" else "~"})
        status = n.get("status", "")
        if status in REFUTED:
            v = "contradicted"
            con.insert(0, {"from": nid, "to": nid, "sign": "-", "kind": "status", "effective": "-",
                           "why": f"{nid} is marked {status}"})
        elif con and (pro or status in SUPPORTED):     # the person's own "supported" is a say for it
            v = "contested"
        elif con:
            v = "contradicted"
        elif pro:
            v = "supported"
        elif status in SUPPORTED:
            v = "supported"
        elif _role(n.get("kind", ""), statements) == "evidence":
            v = "holds"              # a result, a run, a number: evidence in itself, until something contradicts it
        else:
            v = "unsupported"
        visiting.discard(nid)
        verdict[nid], against[nid], backing[nid], voided[nid] = v, con, pro + weak, void
        return v

    for nid in nodes:
        judge(nid)
    for e in edges:
        judge(e["from"])

    # What is drawn: every statement, and everything with a path of evidence edges into one.
    keep = {k for k, n in nodes.items() if n["kind"] in statements}
    frontier = list(keep)
    while frontier:
        nid = frontier.pop()
        for e in into.get(nid, []):
            if e["from"] not in keep:
                keep.add(e["from"])
                frontier.append(e["from"])

    def owner(nid: str) -> str:
        return (nodes.get(nid, {}).get("by") or owners.get(nid) or "").strip()

    out_nodes: Dict[str, dict] = {}
    for nid in sorted(keep, key=lambda k: _order(k, nodes)):
        n = nodes.get(nid)
        if n is None:   # a citation
            out_nodes[nid] = {"kind": "source", "role": "evidence", "title": nid[5:], "status": "", "metrics": {},
                              "section": "", "file": "", "line": 0, "owner": "", "verdict": verdict.get(nid, "holds")}
            continue
        title = n["title"]
        if not title and "." in nid and nid.split(".")[0] in nodes:   # E1.results: the numbers of E1
            base = nodes[nid.split(".")[0]]
            title = f"Numbers of {nid.split('.')[0]}" + (f": {base['title']}" if base["title"] else "")
        out_nodes[nid] = {"kind": n["kind"], "role": _role(n["kind"], statements), "title": title,
                          "status": n["status"], "metrics": n["metrics"], "section": n.get("section", ""),
                          "file": (n["files"] or [""])[0], "line": n.get("line", 0), "owner": owner(nid),
                          "verdict": verdict[nid]}
    effective = {(x["from"], x["to"], x["kind"]): x for nid in keep for x in backing.get(nid, []) + against.get(nid, [])
                 + voided.get(nid, [])}
    out_edges = [effective.get((e["from"], e["to"], e["kind"]), {**e, "effective": e["sign"]}) for e in edges
                 if e["from"] in keep and e["to"] in keep]
    out_edges = [{k: e[k] for k in ("from", "to", "sign", "kind", "effective", "why")} for e in out_edges]

    stmts = []
    for nid, n in out_nodes.items():
        if n["role"] != "statement":
            continue
        stmts.append({"id": nid, **{k: n[k] for k in ("kind", "title", "section", "status", "verdict", "owner", "file",
                                                     "line")},
                      "for": [_brief(x) for x in backing[nid]], "against": [_brief(x) for x in against[nid]]})
    conflicts = [e for e in out_edges if e["sign"] == "-" and e["from"] != e["to"]
                 and out_nodes[e["from"]]["role"] == "statement" and out_nodes[e["to"]]["role"] == "statement"]
    cross = [e for e in out_edges if e["effective"] in ("-", "?") and out_nodes[e["from"]]["owner"]
             and out_nodes[e["to"]]["owner"] and out_nodes[e["from"]]["owner"] != out_nodes[e["to"]]["owner"]]
    counts = {v: sum(1 for s in stmts if s["verdict"] == v) for v in VERDICTS}
    return {"ref": bp.get("ref", ""), "nodes": out_nodes, "edges": out_edges, "statements": stmts,
            "conflicts": [{"from": e["from"], "to": e["to"], "why": e["why"]} for e in conflicts],
            "cross_agent": [{"from": e["from"], "to": e["to"], "why": e["why"],
                             "owners": [out_nodes[e["from"]]["owner"], out_nodes[e["to"]]["owner"]]} for e in cross],
            "counts": counts, "headline": headline(stmts, conflicts)}


def _broken(e: dict, nodes: dict, src_against: List[dict]) -> str:
    """Why a support no longer holds: its source is refuted or contradicted."""
    s, t = e["from"], e["to"]
    how = "relies on" if e["kind"] == "relies on" else "is supported by"
    status = nodes.get(s, {}).get("status", "")
    if status in REFUTED:
        return f"{t} {how} {s}, which is {status}"
    by = [x["from"] for x in src_against if x["from"] != s]
    return f"{t} {how} {s}, which {', '.join(by[:3])} {'contradict' if len(by) > 1 else 'contradicts'}" if by \
        else f"{t} {how} {s}, which is contradicted"


def _brief(e: dict) -> dict:
    return {"from": e["from"], "kind": e["kind"], "effective": e["effective"], "why": e["why"]}


def _order(nid: str, nodes: dict) -> tuple:
    n = nodes.get(nid)
    if n is None:
        return (9, "", 0, nid)
    m = re.match(r"([A-Za-z])(\d+)", nid)
    paper = n["kind"] in ("claim", "finding", "paragraph")      # the paper's statements in the paper's own order
    return (4 if paper else "QHERFC".find(nid[0]) if m else 9, (n["files"] or [""])[0] if paper else "",
            n.get("line", 0) if paper else int(m.group(2)) if m else 0, nid)


def plural(n: int, word: str, many: str = "") -> str:
    return f"{n} {word if n == 1 else many or word + 's'}"


def headline(stmts: List[dict], conflicts: List[dict]) -> str:
    if not stmts:
        return "No claims or findings marked in the paper yet."
    c = {v: sum(1 for s in stmts if s["verdict"] == v) for v in VERDICTS}
    parts = [f"{c[v]} {WORD[v]}" for v in ("supported", "contested", "contradicted", "unsupported") if c[v]]
    out = plural(len(stmts), "statement") + ": " + ", ".join(parts)
    if conflicts:
        out += "; " + "; ".join(f"{e['from']} contradicts {e['to']}" for e in conflicts[:2]) + \
               (f" (+{len(conflicts) - 2} more)" if len(conflicts) > 2 else "")
    return out + "."


def changes(a: dict, b: dict) -> List[dict]:
    """What changed in the evidence between two graphs: verdicts that moved, contradictions that appeared or went."""
    out: List[dict] = []
    for s in b["statements"]:
        old = next((x for x in a["statements"] if x["id"] == s["id"]), None)
        if old and old["verdict"] != s["verdict"]:
            out.append({"op": "change", "entity": "verdict", "id": s["id"],
                        "label": f"{s['id']}: {WORD[old['verdict']]} → {WORD[s['verdict']]}",
                        "detail": [x["why"] for x in s["against"][:2]] if s["verdict"] in ("contested", "contradicted")
                        else [], "impact": [f"now-{s['verdict']}"]})
    def contra(g: dict) -> Dict[str, str]:
        return {f"{e['from']} → {e['to']}": e["why"] for e in g["edges"] if e["effective"] in ("-", "?")}
    ca, cb = contra(a), contra(b)
    for k in sorted(set(cb) - set(ca)):
        out.append({"op": "add", "entity": "contradiction", "id": k, "label": cb[k], "detail": [],
                    "impact": ["new-contradiction"]})
    for k in sorted(set(ca) - set(cb)):
        out.append({"op": "remove", "entity": "contradiction", "id": k, "label": ca[k], "detail": [],
                    "impact": ["resolved-contradiction"]})
    return out


def chain(g: dict, nid: str, depth: int = 4) -> List[str]:
    """One node's evidence, as indented lines: what backs it and what contradicts it, down to the evidence."""
    lines: List[str] = []
    into: Dict[str, List[dict]] = {}
    for e in g["edges"]:
        into.setdefault(e["to"], []).append(e)
    mark = {"+": "✓", "~": "◐", "-": "✗", "?": "✗", "0": "·", "o": "○"}

    def walk(x: str, d: int, seen: set) -> None:
        for e in into.get(x, []):
            n = g["nodes"].get(e["from"], {})
            lines.append("  " * d + f"{mark[e['effective']]} {e['from']} {n.get('title', '')[:60]}".rstrip()
                         + f"  ({e['why']})")
            if d < depth and e["from"] not in seen:
                walk(e["from"], d + 1, seen | {e["from"]})
    walk(nid, 1, {nid})
    return lines


def to_markdown(g: dict) -> str:
    """The graph as Markdown: one table of statements and verdicts, and what contradicts each. For PR comments."""
    icon = {"supported": "✅", "contested": "⚠️", "contradicted": "❌", "unsupported": "⚪"}
    rows = ["| | Statement | Section | Owner | For | Against |", "|---|---|---|---|---|---|"]
    for s in g["statements"]:
        rows.append(f"| {icon[s['verdict']]} | **{s['id']}** {s['title'][:70]} | {s['section'] or ''} | "
                    f"{s['owner'] or ''} | {', '.join(x['from'] for x in s['for']) or '—'} | "
                    f"{'; '.join(x['why'] for x in s['against']) or '—'} |")
    out = [f"**{g['headline']}**", "", *rows]
    if g["conflicts"]:
        out += ["", "**The paper contradicts itself:** " + "; ".join(c["why"] for c in g["conflicts"])]
    if g["cross_agent"]:
        out += ["", "**Across agents:** " + "; ".join(f"{c['why']} ({c['owners'][0]} → {c['owners'][1]})"
                                                     for c in g["cross_agent"])]
    return "\n".join(out)
