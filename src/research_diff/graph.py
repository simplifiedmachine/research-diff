"""The research map and diff as pictures, drawn by system-diff's renderer: a column per kind (questions, hypotheses,
experiments, results, claims), a blue band on what is supported, a dashed box around what is refuted, and lines for
what links to what: grey for links, blue for supports, amber for weakens."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from system_diff import pictures

EDGE_KIND = {"supports": "data", "weakens": "network"}
LEGEND = [("band", "new", "supported"), ("dashed", "", "refuted"),
          ("line", "call", "links"), ("line", "data", "supports"), ("line", "network", "weakens")]


def _node(nid: str, n: dict, status: str = "") -> dict:
    sub = " · ".join(x for x in (n["status"], f"{len(n['sources'])} sources" if n["sources"] else "") if x)
    lines = [{"text": f"{k} = {v:.4g}", "code": True} for k, v in list(n["metrics"].items())[:4]]
    style = "new" if n["status"] == "supported" else "legacy" if n["status"] == "refuted" else ""
    node = {"id": nid, "col": n["kind"], "title": f"{nid} {n['title']}".strip(), "sub": sub or (n["files"][0] if n["files"] else ""),
            "type": "store" if n["kind"] == "result" else "component", "style": style, "lines": lines}
    if status:
        node["status"] = status
    return node


def map_graph(bp: dict, cfg: Dict[str, Any]) -> dict:
    nodes = [_node(k, n) for k, n in bp["nodes"].items() if n["kind"] in {c[0] for c in cfg["picture"]["columns"]}]
    ids = {n["id"] for n in nodes}
    edges = [{"from": s, "to": t, "kind": EDGE_KIND.get(r, "call")} for s, r, t in bp["links"] if s in ids and t in ids]
    styles = {n["style"] for n in nodes}
    kinds = {e["kind"] for e in edges}
    legend = [x for x in LEGEND if (x[0] == "band" and "new" in styles) or (x[0] == "dashed" and "legacy" in styles)
              or (x[0] == "line" and x[1] in kinds)]
    warn = bp.get("warnings") or []
    return {"columns": cfg["picture"]["columns"], "nodes": nodes, "edges": edges, "legend": legend,
            "footer": [f"{len(warn)} warning{'' if len(warn) == 1 else 's'}: " + "; ".join(warn[:3])
                       + (" …" if len(warn) > 3 else "")] if warn else []}


def map_svg(bp: dict, cfg: Dict[str, Any]) -> str:
    return pictures.map_svg(map_graph(bp, cfg), label="Research map")


def diff_graph(d: dict, a: dict, b: dict, cfg: Dict[str, Any]) -> Optional[dict]:
    """What changed, lit, with the ideas it links to beside it; None when nothing changed."""
    status: Dict[str, str] = {}
    lines: Dict[str, List[dict]] = {}
    links_changed: Dict[tuple, str] = {}
    word = {"add": "added", "remove": "removed", "change": "changed"}
    for c in d["changes"]:
        op = word[c["op"]]
        if c["entity"] in ("question", "hypothesis", "experiment", "result", "claim"):
            status[c["id"]] = op
        elif c["entity"] in ("status", "title"):
            status.setdefault(c["id"], "changed")
            if c["entity"] == "status":
                lines.setdefault(c["id"], []).append({"text": c["label"].split(": ", 1)[1], "status": "changed"})
        elif c["entity"] == "metric":
            nid = c["id"].split(" ", 1)[0]
            status.setdefault(nid, "changed")
            lines.setdefault(nid, []).append({"text": c["label"].split(" ", 1)[1], "code": True, "status": op})
        elif c["entity"] == "link":
            s, rest = c["id"].split(" ", 1)
            rel, t = rest.rsplit(" ", 1)
            links_changed[(s, rel, t)] = op
    hot = set(status) | {x for (s, _r, t) in links_changed for x in (s, t)}
    if not hot:
        return None
    both = {**a["nodes"], **b["nodes"]}
    near = set(hot)
    for s, r, t in b["links"]:
        if s in hot or t in hot:
            near |= {s, t}
    nodes = []
    for nid in both:
        if nid in near and both[nid]["kind"] in {c[0] for c in cfg["picture"]["columns"]}:
            n = _node(nid, both[nid], status.get(nid, "same"))
            if nid in lines:
                n["lines"] = lines[nid]
            nodes.append(n)
    ids = {n["id"] for n in nodes}
    edges = [{"from": s, "to": t, "kind": EDGE_KIND.get(r, "call"), "status": op}
             for (s, r, t), op in links_changed.items() if s in ids and t in ids]
    seen = {(e["from"], e["to"]) for e in edges}
    edges += [{"from": s, "to": t, "kind": EDGE_KIND.get(r, "call"), "status": "same"} for s, r, t in b["links"]
              if s in ids and t in ids and (s, t) not in seen]
    new_w = [c["id"] for c in d["changes"] if c["entity"] == "warning" and c["op"] == "add"]
    return {"columns": cfg["picture"]["columns"], "nodes": nodes, "edges": edges,
            "footer": ["New warning: " + "; ".join(new_w)] if new_w else []}


def diff_svg(d: dict, a: dict, b: dict, cfg: Dict[str, Any]) -> Optional[str]:
    g = diff_graph(d, a, b, cfg)
    return pictures.map_svg(g, diff=True, label="Research diff") if g else None
