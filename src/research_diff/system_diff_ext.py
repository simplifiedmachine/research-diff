"""research-diff inside system-diff: its tabs in system-diff's own engine, web page and pane (system-diff's extension
contract, system_diff/extensions.py), so there is one engine, one port, one page, one pane and one cache.

    Research      what changed in the research since your checkpoint, on the diagram, and what is worth a look
    Evidence      the evidence graph on system-diff's diagram: claims and findings by verdict, what supports and what
                  contradicts each; the interactive graph below it
    Paper         the paper section by section: statements, tables and figures, numbers checked, summaries, review;
                  each paper file opened beside it
    Auto-research the campaign's controls and state

Fast: the research is read from the files system-diff's engine already holds in memory (ctx.live.source: no git, no
snapshot), once per version of the working tree and of research-diff's own state, and the pages are cached by
system-diff per engine version. The base of the diff (your checkpoint's commit) is read once per commit.
"""
from __future__ import annotations

import dataclasses
import json
import os
import threading
from pathlib import Path
from typing import Dict, List, Tuple
from urllib.parse import quote

NAME = "research"
VIEWS = [("research", "Research", "s"), ("evidence", "Evidence", "e"), ("paper", "Paper", "p"),
         ("auto", "Auto-research", "u")]
WATCH = ["research-diff/", "research-diff/auto/"]

STATUS = {"supported": "added", "contested": "changed", "contradicted": "removed", "unsupported": "same",
          "holds": "same"}
EDGE = {"+": ("data", "added", "supports"), "~": ("data", "changed", "supports"), "-": ("network", "removed", "contradicts"),
        "?": ("network", "removed", "broken"), "0": ("data", "same", "void"), "o": ("data", "same", "ungrounded")}
SIGN = {"supported": "✓", "contested": "◐", "contradicted": "✗", "unsupported": "○", "holds": "·"}
COLUMNS = [("evidence", "Evidence"), ("hypothesis", "Hypotheses"), ("finding", "Findings"), ("claim", "Claims")]
# system-diff's legend, in the evidence graph's words (laid out by its renderer, so the spacing holds)
LEGEND = [("op", "added", "supported"), ("op", "changed", "contested"), ("op", "removed", "contradicted"),
          ("agent", "agent", "● Claude points at it"), ("line", "data", "supports"), ("line", "network", "contradicts")]

_LOCK = threading.Lock()
_STATE: Dict[tuple, dict] = {}
_BASE: Dict[tuple, dict] = {}


# ── the research, read once per version ────────────────────────────────────────────────────────────────────────────

def _stamp(root: Path) -> tuple:
    from . import compare, store
    h = store.home(root)
    out = []
    for d in (h, h / "auto"):
        try:
            out.append(tuple(sorted((e.name, e.stat().st_mtime_ns) for e in os.scandir(d))))
        except OSError:
            out.append(())
    return tuple(out) + (compare.checkpoint_sha(root),)


class _Merged:
    """The engine's files and, beside them, the files of the repository's git submodules (the engine lists a submodule
    as one entry: its own files are read from disk here)."""
    label = "working tree"

    def __init__(self, src, root: Path):
        self._src, self.root = src, Path(root)
        extra: List[str] = []
        if (self.root / ".gitmodules").is_file():
            from system_diff.sources import git
            try:
                listed = git("ls-files", "-z", "-c", "--recurse-submodules", cwd=self.root).split("\0")
            except Exception:  # noqa: BLE001
                listed = []
            known = set(src.files)
            extra = [f for f in listed if f and f not in known]
        self._extra = set(extra)
        self.files = sorted(set(src.files) | self._extra)

    def read(self, path: str) -> str:
        if path in self._extra:
            try:
                return (self.root / path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                return ""
        return self._src.read(path)

    def read_many(self, paths) -> Dict[str, str]:
        mine = [p for p in paths if p not in self._extra]
        out = dict(self._src.read_many(mine)) if mine else {}
        out.update({p: self.read(p) for p in paths if p in self._extra})
        return out


def _source(ctx):
    """(source of the working tree, a key that is the same for the same files, root)."""
    from . import compare
    root = Path(ctx.root)
    live = getattr(ctx, "live", None)
    src = getattr(live, "source", None) if live is not None else None
    if src is not None:
        merged = _Merged(src, root)
        return merged, (getattr(live, "identity", "") or None, len(merged._extra)), root
    work = compare.WorkSource(root)
    return work, None, root


def state(ctx) -> dict:
    """Everything the tabs draw from, for the study the view's part names (a repository with several papers holds a
    study per paper folder): the map, the diff since the checkpoint, the evidence graph, worth a look."""
    from . import studies
    src, ident, root = _source(ctx)
    from . import config
    cfg = config.load(src, root)
    found = studies.detect(src.files, cfg)
    sid, rest = studies.split(ctx.part or "")
    if found and sid not in {x["id"] for x in found}:
        sid = found[0]["id"]                 # the first study, until one is picked
    if not found:
        sid = ""
    out = _study_state(ctx, src, ident, root, cfg, found, sid)
    return {**out, "studies": found, "study": sid, "rest": rest}


def _study_state(ctx, src, ident, root: Path, cfg: dict, found: List[dict], sid: str) -> dict:
    from . import activity, agents, chat, compare, evidence, objectives, rank, review, studies
    from .diff import diff
    from .extract import extract
    key = (str(root), ident, sid, _stamp(root)) if ident is not None else None
    if key is not None:
        with _LOCK:
            if key in _STATE:
                return _STATE[key]
    sc = studies.scope(found, sid)
    after = extract(src, cfg, sc)
    after["ref"] = "working tree"
    sha, label = compare.resolve(root, "checkpoint")
    bkey = (str(root), sha, sid, json.dumps(cfg, sort_keys=True, default=str))
    with _LOCK:
        before = _BASE.get(bkey)
    if before is None:
        from system_diff.sources import GitSource
        before = extract(GitSource(sha, root), cfg, sc)
        before["ref"] = label
        with _LOCK:
            _BASE[bkey] = before
            while len(_BASE) > 16:
                _BASE.pop(next(iter(_BASE)))
    c = compare.Comparison(diff(before, after, cfg), before, after, cfg, label)
    g = evidence.build(c.after, c.cfg, agents.owners(root))
    g["notes"] = {k: [n["text"] for n in v] for k, v in chat.notes_by_node(root).items()}
    g["pointing"] = chat.pointing(root).get("ids", [])
    objs = objectives.current(root)
    rv = review.current(root)
    worth = sorted(review.worth(rv) + rank.worth_a_look(c.diff, c.after, 6, objs), key=lambda x: -x["score"])[:7]
    out = {"cmp": c, "map": c.after, "graph": g, "objectives": objs, "review": rv, "worth": worth,
           "focus": activity.focus(root, c.after), "request": activity.last_request(root), "root": root,
           "notes": chat.notes_by_node(root), "pointing": chat.pointing(root)}
    if key is not None:
        with _LOCK:
            _STATE[key] = out
            while len(_STATE) > 24:
                _STATE.pop(next(iter(_STATE)))
    return out


def _part(S: dict, node: str = "") -> str:
    from . import studies
    return studies.join(S.get("study", ""), node)


def _nav(S: dict, view: str) -> List[dict]:
    """The studies, for system-diff's pinned list on the left (shown once it has one)."""
    return [{"id": x["id"], "title": x["title"], "sub": x["path"], "active": x["id"] == S["study"],
             "target": {"view": view, "part": x["id"] + "@"}} for x in S.get("studies", [])]


def _study_title(S: dict) -> str:
    me = next((x for x in S.get("studies", []) if x["id"] == S.get("study")), None)
    return me["title"] if me else ""


# ── the evidence graph as system-diff's diagram model ──────────────────────────────────────────────────────────────

def evidence_model(g: dict, focus: str = "") -> dict:
    from . import evgraph
    keep = set(g["nodes"])
    if focus and focus in g["nodes"]:              # zoomed in: the node, what it rests on and what rests on it
        keep, grew = {focus}, True
        up, down = {focus}, {focus}
        while grew:
            grew = False
            for e in g["edges"]:
                if e["to"] in up and e["from"] not in up:
                    up.add(e["from"])
                    grew = True
                if e["from"] in down and e["to"] not in down:
                    down.add(e["to"])
                    grew = True
        keep = up | down
    nodes = []
    for nid, n in g["nodes"].items():
        if nid not in keep:
            continue
        v = n["verdict"]
        sub = " · ".join(x for x in ((f"{SIGN[v]} {v}" if v != "holds" else n["kind"]), n.get("owner", "")) if x)
        lines = [{"text": f"{k} = {val:.4g}", "status": "same"} for k, val in list(n["metrics"].items())[:2]] \
            if n["role"] == "evidence" else []
        nodes.append({"id": nid, "col": evgraph.column_of(n), "title": f"{nid} {n['title']}".strip()[:90], "sub": sub,
                      "status": STATUS.get(v, "same"), "type": "store" if n["role"] == "evidence" else "component",
                      "lines": lines, "focus": nid == focus, "agent": nid in g.get("pointing", [])})
    edges = []
    for e in g["edges"]:
        if e["from"] in keep and e["to"] in keep:
            kind, status, label = EDGE.get(e["effective"], ("data", "same", ""))
            edges.append({"from": e["from"], "to": e["to"], "kind": kind, "status": status,     # green says supports:
                          "label": label if kind == "network" else ""})                       # only the red is named
    return {"nodes": nodes, "edges": edges, "columns": COLUMNS}


def _svg(model: dict, label: str, legend: bool = True) -> str:
    from system_diff import pictures
    if not legend:
        return pictures.architecture_svg(model, label=label)
    with _LOCK:                                    # the renderer reads its legend from a module constant
        was = pictures.ARCH_LEGEND
        pictures.ARCH_LEGEND = LEGEND
        try:
            return pictures.architecture_svg(model, label=label)
        finally:
            pictures.ARCH_LEGEND = was


def _lights(model: dict) -> Dict[str, List[str]]:
    from system_diff import canvas
    try:
        return dict(canvas.layered(model["nodes"], model["edges"], model["columns"], width=100).lights)
    except Exception:  # noqa: BLE001
        return {}


def _why(g: dict, nid: str) -> str:
    st = next((s for s in g["statements"] if s["id"] == nid), None)
    n = g["nodes"].get(nid, {})
    if st:
        said = [f"✗ {x['why']}" for x in st["against"]] + [f"✓ {x['why']}" for x in st["for"]]
        return f"{SIGN[st['verdict']]} {st['verdict']}" + (f" · § {st['section']}" if st["section"] else "") + \
            ("\n" + "\n".join(said[:6]) if said else "\nnothing backs it yet")
    uses = [e["why"] for e in g["edges"] if e["from"] == nid][:5]
    return f"{n.get('kind', '')}" + ("\n" + "\n".join(uses) if uses else "")


def _count(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _detail(S: dict, nid: str) -> dict:
    """A box's card, in the page's own shape (What it is · How it works · Worth knowing · Facts), in plain words."""
    g = S["graph"]
    n = g["nodes"].get(nid, {})
    st = next((s for s in g["statements"] if s["id"] == nid), None)
    where = f"{n.get('file', '')}:{n.get('line', '')}" if n.get("file") else ""
    facts: List[dict] = []
    insights: List[str] = []
    if st:
        pro = [x for x in st["for"] if x["effective"] in ("+", "~")]
        weak = [x for x in st["for"] if x["effective"] == "o"]
        con = st["against"]
        verdict = {"supported": "stands on its evidence", "contested": "has evidence for it and against it",
                   "contradicted": "is contradicted by its evidence", "unsupported": "has no evidence behind it yet"}
        head = f"This {n.get('kind', 'statement')} {verdict.get(st['verdict'], st['verdict'])}" + \
            (f": {_count(len(pro), 'piece')} of evidence for it" if pro else "") + \
            (f", {_count(len(con), 'thing')} against it" if con else "") + "."
        how = [f"Against it: {x['why']}." for x in con[:3]] + [f"For it: {x['why']}." for x in pro[:3]]
        for x in con:
            w = x["why"]
            if " says " in w and ", but " in w:
                insights.append("Update the number in the paper, or rerun what it comes from: " + w.split(", but ")[1] + ".")
            elif x["kind"] == "contradicts" and g["nodes"].get(x["from"], {}).get("role") == "statement":
                insights.append(f"{x['from']} and {nid} cannot both stand in the paper: drop or narrow one of them.")
            elif x["effective"] == "?":
                insights.append(f"Its support from {x['from']} no longer holds: give it other evidence or narrow it.")
            elif x["kind"] == "expects":
                insights.append("A number it expects does not hold any more: change the claim or the experiment.")
        if not pro and not con:
            insights.append("Write what backs it under its marker (`relies on:`, `supported by:`, or an `expects:`).")
        if weak:
            insights.append(f"{_count(len(weak), 'support')} only rests on what has no evidence yet.")
        if pro:
            facts.append({"title": "For it", "summary": ", ".join(x["from"] for x in pro[:6]),
                          "items": [x["why"] for x in pro]})
        if con:
            facts.append({"title": "Against it", "summary": ", ".join(x["from"] for x in con[:6]),
                          "items": [x["why"] for x in con]})
    else:
        backs = [e for e in g["edges"] if e["from"] == nid]
        metrics = list(n.get("metrics", {}).items())
        head = f"{n.get('title') or nid}" + (f" ({n.get('kind')})" if n.get("kind") else "") + \
            (f": {', '.join(f'{k} = {v:.4g}' for k, v in metrics[:3])}" if metrics else "") + "."
        how = [f"{e['why']}." for e in backs[:4]]
        if n.get("verdict") in ("contradicted", "contested"):
            insights.append("Itself contradicted: what it supports is weakened too.")
        if metrics:
            facts.append({"title": "Numbers", "summary": _count(len(metrics), "metric"),
                          "items": [f"{k} = {v:.6g}" for k, v in metrics]})
        if backs:
            facts.append({"title": "It backs or contradicts", "summary": ", ".join(e["to"] for e in backs[:6]),
                          "items": [e["why"] for e in backs]})
    place = " · ".join(x for x in (where, f"§ {n['section']}" if n.get("section") else "",
                                   f"owned by {n['owner']}" if n.get("owner") else "") if x)
    if place:
        facts.append({"title": "Where", "summary": place, "items": []})
    said = g.get("notes", {}).get(nid) or []
    if said:
        facts.append({"title": "Claude's notes", "summary": said[-1][:120], "items": said})
    return {"kind": n.get("kind", ""), "title": f"{nid} · {n.get('title', '')}".strip(" ·"), "headline": head,
            "how": how, "insights": insights[:3], "facts": facts, "inside": "Click to see its evidence chain"}


def _web_diagram(S: dict, model: dict, view: str, title: str, aside: str, part: str) -> dict:
    return {"svg": _svg(model, title), "title": title, "aside": aside, "lights": _lights(model),
            "details": {"b:" + n["id"]: _detail(S, n["id"]) for n in model["nodes"]},
            "enter": {"b:" + n["id"]: {"view": view, "part": _part(S, n["id"])} for n in model["nodes"]},
            "files": {}, "pick": ("b:" + part) if part else ""}


def _notes(items: List[dict]) -> List[dict]:
    return [{"sign": i.get("sign", "·"), "status": i.get("status", ""), "text": i.get("text", ""),
             "why": i.get("why", ""), "ask": ""} for i in items]


def _statement_notes(g: dict) -> List[dict]:
    order = {"contradicted": 0, "contested": 1, "unsupported": 2, "supported": 3}
    out = []
    for s in sorted(g["statements"], key=lambda s: (order[s["verdict"]], s["file"], s["line"])):
        why = "; ".join(x["why"] for x in s["against"][:2]) or "; ".join(x["why"] for x in s["for"][:2]) or \
            "nothing backs it yet"
        out.append({"sign": SIGN[s["verdict"]], "status": STATUS[s["verdict"]],
                    "text": f"{s['id']} {s['title']}" + (f"  · {s['owner']}" if s["owner"] else ""), "why": why})
    return out


def studies_model(ctx, S: dict) -> dict:
    """One box per study: its title, its statements' verdicts, its contradictions; a click opens its Evidence."""
    nodes = []
    for x in S["studies"]:
        T = state(dataclasses.replace(ctx, part=x["id"] + "@"))
        st = T["graph"]["statements"]
        bad = sum(1 for s in st if s["verdict"] == "contradicted")
        mixed = sum(1 for s in st if s["verdict"] == "contested")
        ok = sum(1 for s in st if s["verdict"] == "supported")
        status = "removed" if bad else "changed" if mixed else "added" if st else "same"
        lines = [{"text": f"✓ {ok}  ◐ {mixed}  ✗ {bad}", "status": status}]
        if T["cmp"].diff["changes"]:
            lines.append({"text": "changed since your checkpoint", "status": "changed"})
        nodes.append({"id": x["id"], "col": "study", "title": x["title"], "sub": _count(len(st), "statement"),
                      "status": status, "type": "component", "lines": lines})
    return {"nodes": nodes, "edges": [], "columns": [("study", "Studies")]}


# ── the views: web ──────────────────────────────────────────────────────────────────────────────────────────────────

def web(ctx) -> dict:
    out = _web(ctx)
    S = state(ctx)
    if S["studies"]:
        out["nav"] = _nav(S, ctx.view)
        name = _study_title(S)
        out["title"] = f"{out.get('title', '')} · {name}" if name and ctx.part else out.get("title", "")
    return out


def _web(ctx) -> dict:
    from . import autoresearch, graph, paperview, review
    S = state(ctx)
    g, part, view = S["graph"], S["rest"], ctx.view
    if view == "research" and S["studies"] and not ctx.part:       # several studies: one box each, first
        model = studies_model(ctx, S)
        return {"title": "Research", "headline": f"{len(S['studies'])} studies in this repository: pick one",
                "diagram": {"svg": _svg(model, "Studies"), "title": "Studies", "aside": "click a study to open it",
                            "lights": {}, "details": {"b:" + n["id"]: {"title": n["title"], "headline": n["sub"],
                                                                       "how": [l["text"] for l in n["lines"]],
                                                                       "insights": [], "facts": []}
                                                      for n in model["nodes"]},
                            "enter": {"b:" + n["id"]: {"view": "research", "part": n["id"] + "@"}
                                      for n in model["nodes"]}, "files": {}, "pick": ""},
                "sections": []}
    if view == "evidence":
        model = evidence_model(g, part)
        sections = []
        bad = [{"sign": "✗", "status": "removed", "text": "The paper contradicts itself: " + c["why"]} for c in
               g["conflicts"]] + [{"sign": "⚑", "status": "changed", "text": f"Across agents: {c['why']}",
                                   "why": f"{c['owners'][0]} → {c['owners'][1]}"} for c in g["cross_agent"]]
        if bad:
            sections.append({"title": "Contradictions", "aside": "", "kind": "notes", "items": _notes(bad)})
        sections.append({"title": "Statements", "aside": "worst first", "kind": "notes",
                         "items": _notes(_statement_notes(g))})
        return {"title": "Evidence", "headline": g["headline"],
                "diagram": _web_diagram(S, model, "evidence", f"Evidence of {part}" if part else "Evidence",
                                        "hover a box for what supports and contradicts it · click to zoom in", part),
                "sections": sections}
    if view == "paper":
        files = [x["path"] for x in S["map"].get("paper", [])]
        sections = []
        for path in files:
            o = paperview.outline(S["root"], path, S["map"], g)
            summ = o.get("summary") or {}
            items = []
            for c in o["chunks"]:
                bad = [n for n in c["numbers"] if n["sign"] == "-"]
                ok = sum(1 for n in c["numbers"] if n["sign"] == "+")
                cs = (summ.get("sections") or {}).get(c["title"], {})
                why = " ".join(f"✦ {cs[k]}" for k in ("says", "watch") if cs.get(k)) or \
                    ", ".join(f"{st['id']} {st['verdict'] or st['kind']}" for st in c["statements"])
                items.append({"sign": "✗" if bad else "§", "status": "removed" if bad else "same",
                              "text": f"§ {c['title']}" + (f" · ✓ {ok} numbers match" if ok else "")
                              + (f" · {len(bad)} stale" if bad else ""), "why": "; ".join(n["why"] for n in bad[:2]) or why})
            sections.append({"title": path, "aside": "✦ summarised" if summ else "", "kind": "notes",
                             "items": _notes(items)})
            sections.append({"title": f"{path}, opened", "aside": "outline beside the text, stale numbers in red",
                             "kind": "frame", "items": [{"src": "/x/research/file?path=" + quote(path), "height": 760}]})
        rv = S["review"]
        if rv.get("findings"):
            sections.append({"title": "Review", "aside": review.headline(rv), "kind": "notes", "items": _notes(
                [{"sign": "✦", "status": "removed" if f["kind"] == "contradiction" else "changed",
                  "text": f["why"], "why": " / ".join(f"“{q}”" for q in f["quotes"][:2])} for f in rv["findings"]])})
        return {"title": "Paper", "headline": f"{len(files)} paper file{'' if len(files) == 1 else 's'} · "
                + (review.headline(rv) or "no review yet: ask Claude to review the paper"), "diagram": {},
                "sections": sections or [{"title": "No paper yet", "aside": "", "kind": "lines", "items": [
                    {"text": "research-diff reads the files the `paper` globs of research-diff.toml name.",
                     "style": "muted"}]}]}
    if view == "auto":
        c = autoresearch.campaign(S["root"])
        head = f"Auto-research {c['state']}: {c['goal']}" if c else "Auto-research is off"
        return {"title": "Auto-research", "headline": head, "diagram": {},
                "sections": [{"title": "Auto-research", "aside": "servers, campaign, iterations", "kind": "frame",
                              "items": [{"src": "/x/research/auto", "height": 1100}]}]}
    # research: what changed since the checkpoint, on the research map
    c = S["cmp"]
    model = graph.diff_graph(c.diff, c.before, c.after, c.cfg) or graph.map_graph(c.after, c.cfg)
    model = {**model, "columns": [tuple(x) for x in model["columns"]]}
    sections = [{"title": "Worth a look", "aside": f"since {c.base}", "kind": "notes", "items": _notes(
        [{"sign": "⚑", "status": "removed" if w["score"] >= 80 else "changed" if w["score"] >= 45 else "same",
          "text": w["title"], "why": w["why"]} for w in S["worth"]] or [{"sign": "·", "status": "same",
                                                                       "text": "Nothing new of consequence."}])},
                {"title": "Exactly", "aside": "", "kind": "lines", "items": [
                    {"text": ln, "style": {"+": "added", "~": "changed", "-": "removed"}.get(ln[:1], "muted")}
                    for ln in c.diff["plan"].splitlines()]}]
    if S["objectives"]:
        sections.append({"title": "Your objectives", "aside": "", "kind": "notes",
                         "items": _notes([{"sign": "◆", "status": "same", "text": o["text"]} for o in S["objectives"]])})
    svg = _svg(model, "Research diff" if c.diff["changes"] else "Research map", legend=False)
    return {"title": "Research", "headline": c.diff["headline"],
            "diagram": {"svg": svg, "title": "What changed in the research" if c.diff["changes"] else "The research",
                        "aside": f"since {c.base}", "lights": _lights(model), "details": {},
                        "enter": {"b:" + n["id"]: {"view": "evidence", "part": _part(S, n["id"])}
                                  for n in model["nodes"]},
                        "files": {}, "pick": ""},
            "sections": sections}


# ── the views: pane ─────────────────────────────────────────────────────────────────────────────────────────────────

def pane(ctx) -> dict:
    from system_diff import canvas
    from . import page as rpage
    S = state(ctx)
    g, part, width = S["graph"], S["rest"], max(40, ctx.width)
    name = _study_title(S)
    if ctx.view == "research" and S["studies"] and not ctx.part:   # several studies: pick one
        p = canvas.Page(width)
        p.heading("Studies", "Enter opens one")
        model = studies_model(ctx, S)
        grid = canvas.layered(model["nodes"], [], model["columns"], width=width, zoom=ctx.zoom)
        p.grid(grid, slot=1, on={"b:" + n["id"]: {"enter": {"zoom": n["id"] + "@"}} for n in model["nodes"]})
        return p.json(view="research", part="")
    if ctx.view == "evidence":
        p = canvas.Page(width)
        p.heading("Evidence" + (f" of {part}" if part else "") + (f" · {name}" if name else ""), g["headline"])
        model = evidence_model(g, part)
        grid = canvas.layered(model["nodes"], model["edges"], model["columns"], width=width, zoom=ctx.zoom)
        for n in model["nodes"]:
            grid.details["b:" + n["id"]] = canvas.detail_rows(_why(g, n["id"]).replace("\n", " · "), p.width, "muted",
                                                              (n["id"] + "  ", "bold"))
        p.grid(grid, slot=2, on={"b:" + n["id"]: {"enter": {"zoom": _part(S, n["id"])}} for n in model["nodes"]})
        p.blank()
        p.add(["+ supported  ~ contested  − contradicted · dashed: contradicts", "muted"])
        for c in g["conflicts"]:
            p.add(["✗ The paper contradicts itself: " + c["why"], "removed"])
        for s in _statement_notes(g):
            if s["status"] in ("removed", "changed"):
                p.para(f"{s['sign']} {s['text']}: {s['why']}", "attention" if s["status"] == "changed" else "removed")
        return p.json(view="evidence", part=ctx.part or "")
    if ctx.view == "research" and not part:          # what changed, on the research map, then worth a look
        from . import graph
        c = S["cmp"]
        model = graph.diff_graph(c.diff, c.before, c.after, c.cfg) or graph.map_graph(c.after, c.cfg)
        p = canvas.Page(width)
        p.heading(("What changed in the research" if c.diff["changes"] else "The research") +
                  (f" · {name}" if name else ""), f"since {c.base}")
        cols = [tuple(x) for x in model["columns"]]
        grid = canvas.layered(model["nodes"], model["edges"], cols, width=width, zoom=ctx.zoom)
        p.grid(grid, slot=1, on={"b:" + n["id"]: {"enter": {"zoom": _part(S, n["id"])}} for n in model["nodes"]})
        rp = rpage.Page("now", "", width)
        rpage.view_now(S, rp)
        for row in rp.rows[1:]:                       # its first row is the activity line: the heading says it
            p.add(*[r[:2] for r in row]) if row else p.blank()
        return p.json(view="research", part=ctx.part or "")
    # the others: research-diff's own rows, from the state read once (zoomed in: the node's evidence chain)
    view = {"research": "now", "paper": "paper", "auto": "auto"}.get(ctx.view, "now")
    rp = rpage.Page("now" if part else view, part, width)
    {"now": rpage.view_now, "paper": rpage.view_paper, "auto": rpage.view_auto}["now" if part else view](S, rp)
    data = rp.data()
    data["view"], data["part"] = ctx.view, ctx.part or ""
    return data


# ── its own pages, framed in the tabs: /x/research/<path> ──────────────────────────────────────────────────────────

def route(ctx, method: str, path: str, query: Dict[str, str], body: bytes) -> Tuple[int, str, bytes]:
    from . import autoresearch, evgraph, paperview, webparts
    html, js = "text/html; charset=utf-8", "application/json"
    if method == "GET" and path == "graph":
        return 200, html, evgraph.standalone(state(ctx)["graph"]).encode()
    if method == "GET" and path == "file":
        S = state(ctx)
        f = (query.get("path") or "").replace("\\", "/").lstrip("/")
        for x in S.get("studies", []):          # the study whose file it is
            if f.startswith(x["path"].rstrip("/") + "/"):
                S = state(dataclasses.replace(ctx, part=x["id"] + "@"))
        if ".." in f.split("/") or f not in paperview.research_files(S["map"]):
            return 404, html, b"<p>Only the research's own files open here.</p>"
        st = paperview.summarize(S["root"], f, S["map"], S["graph"])     # in the engine's process: a thread
        return 200, html, webparts.file_page(paperview.outline(S["root"], f, S["map"], S["graph"]), st).encode()
    if method == "GET" and path == "auto":
        return 200, html, webparts.auto_page("/x/research/auto").encode()
    if method == "GET" and path == "auto/status":
        return 200, js, json.dumps(autoresearch.web_status(Path(ctx.root))).encode()
    if method == "POST" and path.startswith("auto/"):
        try:
            got = autoresearch.web_action(Path(ctx.root), path[len("auto/"):], json.loads(body or b"{}"))
        except ValueError as exc:
            return 400, js, json.dumps({"error": str(exc)}).encode()
        return 200, js, json.dumps(got).encode()
    return 404, js, b'{"error": "no such page"}'


# research-diff's MCP tools stay in its own server (`research-diff mcp`): a session in the terminal gets it from
# research-diff's plugin, and system-diff's app attaches it to the sessions it starts (MCP_SERVER below), so code-only
# repositories never carry research tools, and neither tool's server depends on the other's.
MCP_SERVER = {"command": "research-diff", "args": ["mcp"]}


def file_ok(path: str) -> bool:
    """The research's files the page may show beside code: the paper and the notes, the configs."""
    return path.endswith((".tex", ".md", ".bib", ".yaml", ".yml", ".csv"))

