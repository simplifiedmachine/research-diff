"""research-diff inside system-diff: its tabs in system-diff's own engine, web page and pane (system-diff's extension
contract, system_diff/extensions.py), so there is one engine, one port, one page, one pane and one cache.

    Now           what changed in the research since your checkpoint, on the diagram, what Claude is on, and what
                  is worth a look (several studies: one box each, first)
    Evidence      the evidence graph on system-diff's diagram: claims and findings by verdict, what supports and what
                  contradicts each
    Paper         the paper section by section: statements, tables and figures, numbers checked, summaries
    Review        what to fix before trusting the paper, worst first: the paper contradicting itself, claims their
                  evidence or their own numbers contradict, agents contradicting each other, claims nothing backs;
                  the paper's review by Claude; exactly what changed since the checkpoint
    Agents        the research team: who owns which claims, experiments and sections, the workflow (auto-research's
                  runs on it too), what they told each other, the agents worth keeping
    Auto-research the campaign's controls and state
    History       how the research got here: each change (a turn, or a commit of the study's files) and what it did
                  to the claims

In a research repository system-diff opens on Now and folds its own tabs (the software system's Now, Review, Agents,
Topics and History) behind one "System" tab (home()); there research-diff's tabs take those names, oriented to the
research. With a system-diff that cannot fold its tabs, they keep names of their own (Research, Problems, Team,
Timeline) so that no two tabs share a name.

Fast: the research is read from the files system-diff's engine already holds in memory (ctx.live.source: no git, no
snapshot), once per version of the working tree and of research-diff's own state, and the pages are cached by
system-diff per engine version. The base of the diff (your checkpoint's commit) is read once per commit.
"""
from __future__ import annotations

import dataclasses
import json
import os
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .board import WORKFLOW_KINDS, WORKFLOW_TEMPLATES, step_log, workflow, workflow_action  # noqa: F401 (the hooks)

NAME = "research"


def _folds() -> bool:
    """Whether this system-diff opens a research repository on research-diff's tabs, its own behind one "System" tab
    (0.11): then research-diff's tabs take the names of the ones they stand for there."""
    try:
        from system_diff import extensions
        return callable(getattr(extensions, "home", None))
    except Exception:  # noqa: BLE001
        return False


SAME = _folds()
# (view, tab, key, the tab of system-diff's it stands for in a research repository: where system-diff folds its own
# tabs away it may give this one that tab's key and place; it reads the first three)
VIEWS = [("research", "Now" if SAME else "Research", "s", "now"), ("evidence", "Evidence", "e"),
         ("paper", "Paper", "p"), ("check", "Review" if SAME else "Problems", "v", "review"),
         ("team", "Agents" if SAME else "Team", "g", "agents"), ("auto", "Auto-research", "u"),
         ("timeline", "History" if SAME else "Timeline", "y", "history")]
LABEL = {v[0]: v[1] for v in VIEWS}
WATCH = ["research-diff/", "research-diff/auto/"]
VERDICT_ORDER = {"contradicted": 0, "contested": 1, "unsupported": 2, "supported": 3, "holds": 4}
NEEDS_EVIDENCE = ("claim", "finding")       # a hypothesis or a question with nothing behind it yet is not a problem

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
    if sid in (ONE, SPLIT):            # the person's switch, in the studies list: remembered for the repository
        studies.set_split(root, sid == SPLIT)
        sid = ""
    split_off = bool(found) and not studies.split_on(root)
    if split_off:
        found = []
    if found and sid not in {x["id"] for x in found}:
        sid = found[0]["id"]                 # the first study, until one is picked
    if not found:
        sid = ""
    out = _study_state(ctx, src, ident, root, cfg, found, sid)
    return {**out, "studies": found, "study": sid, "rest": rest, "split_off": split_off,
            "could_split": len(studies.detect(src.files, cfg))}


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


ONE, SPLIT = "~one", "~split"          # the switch's parts: show the repository as one study, or split it again


def _nav(S: dict, view: str) -> List[dict]:
    """The studies, for system-diff's pinned list on the left, and the switch to read the repository as one."""
    if S.get("split_off"):
        return [{"id": SPLIT, "title": f"Split into {S['could_split']} studies", "sub": "found from the folders",
                 "active": False, "target": {"view": view, "part": SPLIT + "@"}}]
    items = [{"id": x["id"], "title": x["title"], "sub": x["path"], "active": x["id"] == S["study"],
              "target": {"view": view, "part": x["id"] + "@"}} for x in S.get("studies", [])]
    if items:
        items.append({"id": ONE, "title": "Show as one study", "sub": "if these are not separate works",
                      "active": False, "target": {"view": view, "part": ONE + "@"}})
    return items


def _study_title(S: dict) -> str:
    me = next((x for x in S.get("studies", []) if x["id"] == S.get("study")), None)
    return me["title"] if me else ""


# ── the evidence graph as system-diff's diagram model ──────────────────────────────────────────────────────────────

def evidence_model(g: dict, focus: str = "", only: Optional[set] = None) -> dict:
    from . import evgraph
    keep = set(g["nodes"])
    if only is not None:                           # some statements: those, and what backs or contradicts them
        keep = {i for i in only if i in g["nodes"]}
        keep |= {e["from"] for e in g["edges"] if e["to"] in keep}
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


def _span(root: Path, path: str, line: int) -> int:
    """The last line of the paragraph a marker starts at (its comment lines and its text), for the viewer to light."""
    try:
        lines = (Path(root) / path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return line
    end = max(line, 1)
    if path.endswith((".md", ".markdown")):         # a Markdown marker: its heading down to the next heading
        while end < len(lines) and not lines[end].lstrip().startswith("#"):
            end += 1
        while end > line and not lines[end - 1].strip():
            end -= 1
        return end
    while end < len(lines) and lines[end].strip():
        end += 1
    return end


def _where(S: dict, nid: str) -> dict:
    """{"path", "line", "end"} of a node written in a notes or paper file; {} for a number in a results file."""
    n = S["graph"]["nodes"].get(nid, {})
    f, line = n.get("file", ""), int(n.get("line") or 0)
    if not f or not line or not f.endswith((".tex", ".md", ".markdown")):
        return {}
    return {"path": f, "line": line, "end": _span(S["root"], f, line)}


def _web_diagram(S: dict, model: dict, view: str, title: str, aside: str, part: str) -> dict:
    files = {"b:" + n["id"]: w for n in model["nodes"] if (w := _where(S, n["id"]))}
    details = {}
    for n in model["nodes"]:
        d = _detail(S, n["id"])
        d["inside"] = "Click to open it in " + files["b:" + n["id"]]["path"] if "b:" + n["id"] in files \
            else "Click to see its evidence chain"
        details["b:" + n["id"]] = d
    return {"svg": _svg(model, title), "title": title, "aside": aside, "lights": _lights(model), "details": details,
            "enter": {"b:" + n["id"]: {"view": view, "part": _part(S, n["id"])} for n in model["nodes"]
                      if "b:" + n["id"] not in files},           # a click opens the file; Enter in the pane still zooms
            "files": files, "pick": ("b:" + part) if part else ""}


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
    if S["studies"] or S.get("split_off"):
        out["nav"] = _nav(S, ctx.view)
        out["nav_title"] = "Studies"
        name = _study_title(S)
        out["title"] = f"{out.get('title', '')} · {name}" if name and ctx.part else out.get("title", "")
    return out


def _web(ctx) -> dict:
    from . import autoresearch, graph, paperview, review
    S = state(ctx)
    g, part, view = S["graph"], S["rest"], ctx.view
    if view == "check":
        return _web_check(S)
    if view == "team":
        return _web_team(S)
    if view == "timeline":
        return _web_timeline(S, part)
    if view == "research" and S["studies"] and not ctx.part:       # several studies: one box each, first
        model = studies_model(ctx, S)
        return {"title": LABEL["research"], "headline": f"{len(S['studies'])} studies in this repository: pick one",
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
        nodes, where, details, sections = [], {}, {}, []
        for path in files:
            o = paperview.outline(S["root"], path, S["map"], g)
            summ = o.get("summary") or {}
            for c in o["chunks"]:
                bad = [n for n in c["numbers"] if n["sign"] == "-"]
                ok = sum(1 for n in c["numbers"] if n["sign"] == "+")
                verdicts = [st["verdict"] for st in c["statements"]]
                worst = "removed" if bad or "contradicted" in verdicts else "changed" if "contested" in verdicts \
                    else "added" if c["statements"] or ok else "same"
                bid = f"sec:{path}:{c['line']}"
                lines = [{"text": f"{st['id']} {SIGN.get(st['verdict'] or 'unsupported', '·')} {st['verdict'] or st['kind']}",
                          "status": STATUS.get(st["verdict"] or "unsupported", "same")} for st in c["statements"][:3]]
                if ok or bad:
                    lines.append({"text": f"numbers: ✓ {ok}" + (f"  ✗ {len(bad)} stale" if bad else ""),
                                  "status": "removed" if bad else "added"})
                nodes.append({"id": bid, "col": path, "title": "§ " + c["title"], "status": worst, "type": "component",
                              "sub": f"lines {c['line']}-{c['end']}", "lines": lines})
                where["b:" + bid] = {"path": path, "line": c["line"], "end": c["end"]}
                cs = (summ.get("sections") or {}).get(c["title"], {})
                details["b:" + bid] = {
                    "title": "§ " + c["title"], "headline": cs.get("says") or f"{len(c['statements'])} statements",
                    "how": [x for x in (cs.get("claims"),) if x], "insights": [x for x in (cs.get("watch"),) if x]
                    + [n["why"] for n in bad[:3]], "inside": f"Click to open {path} here",
                    "facts": [{"title": "Statements", "summary": ", ".join(st["id"] for st in c["statements"]) or "none",
                               "items": [f"{st['id']} {st['title']}" for st in c["statements"]]}]
                    + ([{"title": "Numbers", "summary": f"{ok} match, {len(bad)} stale",
                         "items": [n["why"] for n in c["numbers"]]}] if c["numbers"] else [])}
        rv = S["review"]
        if rv.get("findings"):
            sections.append({"title": "Review", "aside": review.headline(rv), "kind": "notes", "items": _notes(
                [{"sign": "✦", "status": "removed" if f["kind"] == "contradiction" else "changed",
                  "text": f["why"], "why": " / ".join(f"“{q}”" for q in f["quotes"][:2])} for f in rv["findings"]])})
        model = {"nodes": nodes, "edges": [], "columns": [(f, f) for f in files]}
        diagram = {"svg": _svg(model, "Paper", legend=False), "title": "The paper, section by section",
                   "aside": "hover a section for its summary · click to open it", "lights": {}, "details": details,
                   "enter": {}, "files": where, "pick": ""} if nodes else {}
        return {"title": "Paper", "headline": f"{len(files)} paper file{'' if len(files) == 1 else 's'} · "
                + (review.headline(rv) or "no review yet: ask Claude to review the paper"), "diagram": diagram,
                "sections": sections or ([] if nodes else [{"title": "No paper yet", "aside": "", "kind": "lines",
                                                            "items": [{"text": "research-diff reads the files the "
                                                                       "`paper` globs of research-diff.toml name.",
                                                                       "style": "muted"}]}])}
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
    sections = [{"title": "Worth a look", "aside": f"since {c.base} · exactly what changed: {LABEL['check']}",
                 "kind": "notes", "items": _notes(
        [{"sign": "⚑", "status": "removed" if w["score"] >= 80 else "changed" if w["score"] >= 45 else "same",
          "text": w["title"], "why": w["why"]} for w in S["worth"]] or [{"sign": "·", "status": "same",
                                                                       "text": "Nothing new of consequence."}])}]
    now = _right_now(S)
    if now:
        sections.insert(0, {"title": "Right now", "aside": "", "kind": "notes", "items": _notes(now)})
    if S["objectives"]:
        sections.append({"title": "Your objectives", "aside": "", "kind": "notes",
                         "items": _notes([{"sign": "◆", "status": "same", "text": o["text"]} for o in S["objectives"]])})
    svg = _svg(model, "Research diff" if c.diff["changes"] else "Research map", legend=False)
    return {"title": LABEL["research"], "headline": c.diff["headline"],
            "diagram": {"svg": svg, "title": "What changed in the research" if c.diff["changes"] else "The research",
                        "aside": f"since {c.base}", "lights": _lights(model), "details": {},
                        "enter": {"b:" + n["id"]: {"view": "evidence", "part": _part(S, n["id"])}
                                  for n in model["nodes"]},
                        "files": {}, "pick": ""},
            "sections": sections}


def _right_now(S: dict) -> List[dict]:
    """What Claude (or an agent) is on in the research, and what the person last asked."""
    out = []
    f = S.get("focus")
    if f:
        nid, how, who = f
        title = S["graph"]["nodes"].get(nid, {}).get("title", "")
        out.append({"sign": "●", "status": "changed", "text": f"{'Claude' if who == 'main' else who} is {how} {nid}",
                    "why": title})
    if S.get("request"):
        out.append({"sign": "◆", "status": "same", "text": "You asked: " + S["request"][:200], "why": ""})
    return out


def _where_text(s: dict) -> str:
    return f"{s['file']}:{s['line']}" if s.get("file") and s.get("line") else s.get("file") or ""


def problems(S: dict) -> List[dict]:
    """What in the research needs fixing, worst first: [{"rank", "sign", "status", "text", "why", "ids"}]. The paper
    contradicting itself; claims their evidence, their own numbers or a broken support contradict; agents
    contradicting each other; claims with evidence both ways; claims and findings nothing backs yet."""
    g = S["graph"]
    out: List[dict] = []
    pairs = {(c["from"], c["to"]) for c in g["conflicts"]}
    cross = {(c["from"], c["to"]): c["owners"] for c in g["cross_agent"]}
    for c in g["conflicts"]:
        who = cross.get((c["from"], c["to"]))
        out.append({"rank": 0, "sign": "✗", "status": "removed", "ids": [c["to"], c["from"]],
                    "text": f"The paper contradicts itself: {c['from']} against {c['to']}"
                    + (f" ({who[0]}'s against {who[1]}'s)" if who else ""), "why": c["why"]})
    for c in g["cross_agent"]:
        if (c["from"], c["to"]) in pairs:
            continue
        out.append({"rank": 2, "sign": "⚑", "status": "changed", "ids": [c["to"], c["from"]],
                    "text": f"Agents disagree: {c['owners'][0]}'s {c['from']} against {c['owners'][1]}'s {c['to']}",
                    "why": c["why"]})
    for s in sorted(g["statements"], key=lambda s: (s["file"], s["line"])):
        name, where = f"{s['id']} {s['title']}".strip()[:100], _where_text(s)
        at = f" · {where}" if where else ""
        if s["verdict"] == "contradicted":
            against = [x for x in s["against"] if (x["from"], s["id"]) not in pairs | set(cross)]
            if not against:
                continue                      # said above: the paper, or two agents, against itself
            if all(x["kind"] == "number" for x in against):
                text = f"{name}: a number in the paper is out of date"
            elif all(x["effective"] == "?" for x in against):
                text = f"{name}: what it relies on no longer holds"
            else:
                text = f"{name}: contradicted by its evidence"
            out.append({"rank": 1, "sign": "✗", "status": "removed", "ids": [s["id"]] + [x["from"] for x in against],
                        "text": text, "why": "; ".join(x["why"] for x in against[:2]) + at})
        elif s["verdict"] == "contested":
            out.append({"rank": 3, "sign": "◐", "status": "changed", "ids": [s["id"]],
                        "text": f"{name}: evidence for it and against it",
                        "why": "; ".join(x["why"] for x in s["against"][:2]) + at})
        elif s["verdict"] == "unsupported" and s["kind"] in NEEDS_EVIDENCE:
            out.append({"rank": 4, "sign": "○", "status": "same", "ids": [s["id"]],
                        "text": f"{name}: nothing backs it yet",
                        "why": "write what backs it under its marker (relies on: / supported by: / expects:)" + at})
    return sorted(out, key=lambda x: x["rank"])


def _problems_headline(found: List[dict]) -> str:
    if not found:
        return "Nothing to fix: every claim stands on its evidence and the paper agrees with itself"
    n = {r: sum(1 for x in found if x["rank"] == r) for r in range(5)}
    parts = [(n[0] + n[1], "contradiction", "contradictions"),
             (n[2], "disagreement between agents", "disagreements between agents"),
             (n[3], "claim with evidence both ways", "claims with evidence both ways"),
             (n[4], "claim with nothing behind it", "claims with nothing behind them")]
    return f"{len(found)} to fix: " + ", ".join(f"{k} {one if k == 1 else many}" for k, one, many in parts if k)


def _web_check(S: dict) -> dict:
    """Review: what to fix before trusting the paper, worst first, on the evidence diagram; the paper's review by
    Claude; exactly what changed since the checkpoint."""
    from . import review
    g, c, rv = S["graph"], S["cmp"], S["review"]
    found = problems(S)
    sections = [{"title": "To fix", "aside": "worst first · hover a box above for what backs and contradicts it",
                 "kind": "notes", "items": _notes(found) or _notes([{"sign": "✓", "status": "added",
                                                                     "text": _problems_headline(found)}])}]
    findings = rv.get("findings") or []
    sections.append({"title": "The paper's review", "aside": review.headline(rv) or "by Claude, on request",
                     "kind": "notes", "items": _notes(
                         [{"sign": "✦", "status": "removed" if f["kind"] == "contradiction" else "changed",
                           "text": f["why"], "why": " / ".join(f"“{q}”" for q in f["quotes"][:2])} for f in findings]
                         or [{"sign": "·", "status": "same", "text": "No review yet: ask Claude to review the paper "
                              "(review_paper): claims that contradict each other across sections, numbers that differ "
                              "from the results, claims bigger than their evidence."}])})
    sections.append({"title": f"Exactly, since {c.base}", "aside": "research-diff checkpoint marks it as seen",
                     "kind": "lines", "items": [
                         {"text": ln, "style": {"+": "added", "~": "changed", "-": "removed"}.get(ln[:1], "muted")}
                         for ln in c.diff["plan"].splitlines()] or [{"text": "Nothing changed.", "style": "muted"}]})
    ids = {i for x in found for i in x["ids"] if i in g["nodes"]}
    diagram = {}
    if ids:
        model = evidence_model(g, only=ids)
        diagram = _web_diagram(S, model, "evidence", "What needs fixing",
                               "each with what backs and contradicts it · click one to open it", "")
        diagram["pick"] = "b:" + found[0]["ids"][0] if found[0]["ids"][0] in g["nodes"] else ""
    return {"title": LABEL["check"], "headline": _problems_headline(found), "diagram": diagram, "sections": sections}


def _board(root: Path) -> Optional[dict]:
    """system-diff's workflow board (the team's plan as it runs, auto-research's runs on it), when it has one."""
    try:
        from system_diff import pane as sdp
    except Exception:  # noqa: BLE001
        return None
    f = getattr(sdp, "workflow_section", None) or getattr(sdp, "_workflow_section", None)
    try:
        return f(Path(root)) if f is not None else None
    except Exception:  # noqa: BLE001 - the tab stands without it
        return None


def _ids_text(ids: List[str], most: int = 8) -> str:
    return ", ".join(ids[:most]) + (f" and {len(ids) - most} more" if len(ids) > most else "")


def _web_team(S: dict) -> dict:
    """Agents: the research team, who owns which claims, experiments and sections (lit on the evidence diagram), the
    workflow, what the agents told each other, where they contradict each other, the agents worth keeping."""
    from . import agents
    root, g = S["root"], S["graph"]
    st = agents.state(root)
    team = agents.team(root, g)
    plan = st.get("plan") or {}
    msgs = [m for m in st.get("messages") or [] if isinstance(m, dict) and m.get("at")]
    now = time.time()
    start = min([m["at"] for m in msgs] or [now - 3600])
    span = max(60.0, now - start)
    said: Dict[str, dict] = {}
    for m in msgs:
        said[m.get("from", "")] = m
    lanes = []
    for i, a in enumerate(team):
        last = said.get(a["name"])
        verdicts = "  ".join(f"{SIGN.get(k, '·')} {n}" for k, n in
                             sorted(a["verdicts"].items(), key=lambda kv: VERDICT_ORDER.get(kv[0], 9)))
        lanes.append({"name": a["name"], "colour": i, "area": _ids_text(a["owns"]) or "owns nothing yet",
                      "live": bool(last and now - last["at"] < 120), "doing": str(last["text"])[:160] if last else "",
                      "progress": verdicts, "unread": a["unread"],
                      "marks": [{"pos": (m["at"] - start) / span,
                                 "kind": "change" if str(m.get("text", "")).startswith("CONTRADICTION") else "message"}
                                for m in msgs if m.get("from") == a["name"]][-40:],
                      "blocks": ["b:" + x for x in a["owns"] if x in g["nodes"]]})
    sections = []
    board = _board(root)
    if board:
        sections.append(board)
    sections.append({"title": "The research team", "kind": "lanes", "items": lanes,
                     "aside": f"plan: {plan['task'][:140]}" if plan.get("task") else
                     "who owns what: `by: <agent>` under a marker, or the team Claude plans (plan_agents)"})
    if g["cross_agent"]:
        sections.append({"title": "Agents contradicting each other", "aside": "", "kind": "notes", "items": _notes(
            [{"sign": "✗", "status": "removed", "text": f"{c['owners'][0]}'s {c['from']} against {c['owners'][1]}'s "
              f"{c['to']}", "why": c["why"]} for c in g["cross_agent"]])})
    if msgs:
        sections.append({"title": "What they told each other", "aside": "newest first, on the topics of the claims "
                         "they touched", "kind": "notes", "items": _notes(
                             [{"sign": "✉", "status": "removed" if str(m.get("text", "")).startswith("CONTRADICTION")
                               else "same", "text": f"{m.get('from', '')}: {str(m.get('text', ''))[:200]}",
                               "why": time.strftime("%H:%M", time.localtime(m["at"])) + f" · {m.get('topic', '')}"}
                              for m in reversed(msgs[-15:])])})
    lib, keep = agents.library(root), agents.worth_keeping(root)
    if lib or keep:
        sections.append({"title": "Saved agents", "aside": "reused by name in later plans and sessions",
                         "kind": "notes", "items": _notes(
                             [{"sign": "◆", "status": "added", "text": a["name"],
                               "why": f"{a['description'][:100]} · {a['scope']} · planned {a['planned']}×, finished "
                                      f"{a['finished']}×"} for a in lib]
                             + [{"sign": "◇", "status": "changed", "text": k["name"], "why": "worth keeping: " + k["why"]}
                                for k in keep])})
    diagram = {}
    if g["nodes"]:
        model = evidence_model(g)
        diagram = _web_diagram(S, model, "evidence", "Who works on what",
                               "each box says whose it is · hover an agent below to light its part", "")
        for a in team:
            diagram["lights"]["ag:" + a["name"]] = ["b:" + x for x in a["owns"] if x in g["nodes"]]
    head = (f"{_count(len(team), 'agent')}" + (f" · {plan['task'][:120]}" if plan.get("task") else "")) if team else \
        "No research team yet: ask Claude to plan one (plan_agents), or write `by: <agent>` under the markers each " \
        "agent owns"
    return {"title": LABEL["team"], "headline": head, "diagram": diagram, "sections": sections}


def _asked(e: dict) -> str:
    return (f"You asked: “{e['request'][:120]}”" if e.get("request") else
            f"{e['commit']}: {e['message'][:120]}" if e.get("commit") else "A change no request explains")


def _entry_status(e: dict) -> str:
    said = (e.get("headline", "") + " " + " ".join(i.get("title", "") for i in e.get("items", []))).lower()
    return "removed" if "contradict" in said else "changed" if ("contested" in said or "→" in said) else "added"


def _when(at: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(at))


def _web_timeline(S: dict, part: str) -> dict:
    """History: how the research got here, each change (a turn, or a commit of the study's files) one box, newest
    first, by what it did to the claims; one opened: what it got, and what it touched as it stands now."""
    from . import history, studies
    root, g = S["root"], S["graph"]
    scope = studies.scope(S["studies"], S["study"]) if S["studies"] else None
    entries, reading = history.for_study(root, scope, S["study"])
    if part.startswith("#"):
        e = next((x for x in entries if x["id"] == part[1:]), None)
        if e is not None:
            ids = {i for i in e.get("ids", []) if i in g["nodes"]}
            diagram = _web_diagram(S, evidence_model(g, only=ids), "evidence", "What it touched, as it stands now",
                                   "click one to open it", "") if ids else {}
            sections = [{"title": "What it got", "aside": e["headline"], "kind": "notes", "items": _notes(
                [{"sign": "·", "status": "same", "text": i["title"], "why": i["why"]} for i in e["items"]]
                or [{"sign": "·", "status": "same", "text": e["headline"]}])}]
            return {"title": LABEL["timeline"], "headline": f"{_when(e['at'])} · {_asked(e)}", "diagram": diagram,
                    "sections": sections}
    shown = list(reversed(entries))[:24]
    now = time.time()

    def column(at: float) -> str:
        age = now - at
        return "Today" if age < 86400 else "This week" if age < 7 * 86400 else "This month" if age < 31 * 86400 \
            else "Earlier"
    nodes = [{"id": "h" + e["id"], "col": column(e["at"]), "title": _asked(e)[:80], "type": "component",
              "sub": _when(e["at"]) + (f" · by {', '.join(e['by'])}" if e.get("by") else ""),
              "status": _entry_status(e),
              "lines": [{"text": i["title"][:70], "status": "same"} for i in e["items"][:2]]} for e in shown]
    columns = [(c, c) for c in ("Today", "This week", "This month", "Earlier") if any(n["col"] == c for n in nodes)]
    diagram = {}
    if nodes:
        model = {"nodes": nodes, "edges": [], "columns": columns}
        diagram = {"svg": _svg(model, "History", legend=False), "title": "How the research got here",
                   "aside": "newest first · click a change to see what it did", "lights": {},
                   "details": {"b:h" + e["id"]: {"title": _asked(e), "headline": e["headline"],
                                                 "how": [f"{i['title']}" + (f": {i['why']}" if i["why"] else "")
                                                         for i in e["items"][:4]],
                                                 "insights": [], "inside": "Click to see what it did",
                                                 "facts": [{"title": "It touched", "summary": _ids_text(e["ids"]),
                                                            "items": []}] if e.get("ids") else []} for e in shown},
                   "enter": {"b:h" + e["id"]: {"view": "timeline", "part": _part(S, "#" + e["id"])} for e in shown},
                   "files": {}, "pick": ""}
    head = (f"{_count(len(entries), 'change')} to the research" if entries else
            "No history yet: each commit that changes the research shows here")
    if reading:
        head += " · reading the last commits…"
    return {"title": LABEL["timeline"], "headline": head, "diagram": diagram, "sections": []}


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
    view = {"research": "now", "paper": "paper", "auto": "auto", "check": "review", "team": "agents",
            "timeline": "history"}.get(ctx.view, "now")
    zoom = bool(part) and view != "history"                    # History's part is an entry ("#id"), not a node
    rp = rpage.Page("now" if zoom else view, part, width)
    {"now": rpage.view_now, "paper": rpage.view_paper, "auto": rpage.view_auto, "review": rpage.view_review,
     "agents": rpage.view_agents, "history": rpage.view_history}["now" if zoom else view](S, rp)
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


def applies(root) -> bool:
    """Whether a repository has research for research-diff to read (its server is worth attaching to a session
    there): a research-diff.toml, a [tool.research-diff] table, or a LaTeX paper among its files. Cheap: no reading."""
    root = Path(root)
    if (root / "research-diff.toml").is_file():
        return True
    try:
        if "[tool.research-diff]" in (root / "pyproject.toml").read_text(encoding="utf-8", errors="replace"):
            return True
    except OSError:
        pass
    from system_diff.sources import git
    try:
        return bool(git("ls-files", "-z", "--", "*.tex", cwd=root).strip("\0"))
    except Exception:  # noqa: BLE001
        return False


MANIFESTS = ("pyproject.toml", "setup.py", "package.json", "go.mod", "Cargo.toml", "pom.xml", "build.gradle",
             "build.gradle.kts", "Gemfile", "composer.json")


def _settings(root: Path) -> dict:
    """research-diff's settings at the repository's root (research-diff.toml, else [tool.research-diff]), read cheaply."""
    import tomllib
    for f, table in ((root / "research-diff.toml", ()), (root / "pyproject.toml", ("tool", "research-diff"))):
        try:
            d = tomllib.loads(f.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            continue
        for k in table:
            d = d.get(k) if isinstance(d, dict) else None
        if isinstance(d, dict) and (d or not table):
            return d
    return {}


def home(ctx) -> Optional[dict]:
    """Where a repository whose main work is research opens: research-diff's Now, with system-diff's own tabs (the
    software system's) folded behind one "System" tab. Research is the main work where a research-diff.toml sits at the
    root, or where there is a LaTeX paper and no software project's manifest at the root; `home = "research"` or
    `home = "system"` in research-diff.toml says it for good."""
    root = Path(ctx.root)
    said = str(_settings(root).get("home") or "").lower()
    if said in ("research", "system"):
        return {"view": "research", "system": "collapsed"} if said == "research" else None
    if (root / "research-diff.toml").is_file():
        return {"view": "research", "system": "collapsed"}
    if any((root / m).is_file() for m in MANIFESTS):
        return None
    return {"view": "research", "system": "collapsed"} if applies(root) else None


def _state_for_file(ctx, path: str) -> dict:
    """The state of the study a file belongs to."""
    S = state(ctx)
    for x in S.get("studies", []):
        if path.startswith(x["path"].rstrip("/") + "/"):
            return state(dataclasses.replace(ctx, part=x["id"] + "@"))
    return S


def outline(ctx, path: str, text: str) -> dict:
    """system-diff's file viewer, for a paper or notes file: its sections (and the statements in each) as the
    outline, and the LLM's summary of each section (made in the engine's process the first time, kept by version)."""
    from . import paperview
    S = _state_for_file(ctx, path)
    o = paperview.outline(S["root"], path, S["map"], S["graph"])
    chunks = []
    for c in o["chunks"]:
        chunks.append({"line": c["line"], "end": c["end"], "depth": max(0, c["level"] - 1), "qual": c["title"],
                       "name": "§ " + c["title"], "kind": "section"})
        for st in c["statements"]:
            ln = int(st.get("line") or c["line"])
            chunks.append({"line": ln, "end": _span(S["root"], path, ln), "depth": c["level"],
                           "qual": f"{c['title']} / {st['id']}", "name": f"{st['id']} {st['title'][:60]}",
                           "kind": st.get("verdict") or st["kind"]})
    got = paperview.summarize(S["root"], path, S["map"], S["graph"])
    if got["state"] == "done":
        summary = {"state": "done", "file": got.get("file", ""), "by": got.get("by", ""),
                   "chunks": {t: {"what": v.get("says", ""), "how": v.get("claims", ""), "watch": v.get("watch", "")}
                              for t, v in (got.get("sections") or {}).items()}}
    else:
        summary = {"state": got["state"], "why": got.get("why", "")}
    return {"outline": {"chunks": chunks}, "summary": summary}


def _find(ctx, text: str):
    from . import studies
    raw = str(text or "").strip().strip("`")
    raw = raw[2:] if raw.startswith("b:") else raw
    sid, nid = studies.split(raw)
    S = state(dataclasses.replace(ctx, part=(sid + "@") if sid else (ctx.part or "")))
    return S, nid


def resolve(ctx, text: str):
    """research-diff's ids (C1, R2, tab:main, 2_behavioral_field@C1) for point_to, note and answers' links."""
    S, nid = _find(ctx, text)
    if nid not in S["graph"]["nodes"]:
        return None
    w = _where(S, nid)
    return {"id": nid, "file": f"{w['path']}:{w['line']}" if w else ""}


def source(ctx, block: str):
    """Where a research-diff block comes from (ui_source): the file and line of its marker; what to change."""
    S, nid = _find(ctx, ctx.part or block)
    n = S["graph"]["nodes"].get(nid) or S["map"]["nodes"].get(nid)
    if not n:
        return None
    f = n.get("file") or (n.get("files") or [""])[0]
    line = int(n.get("line") or 0)
    return {"files": [{"path": f, "line": line}] if f else [],
            "config": {"in": f or "the research's files",
                       "change": "edit the marker lines under its definition (status:, relies on:, supports:, "
                                 "contradicts:, expects:, by:) or the text it stands for; the graphs redraw from them"}}


def file_ok(path: str) -> bool:
    """The research's files the page may show beside code: the paper and the notes, the configs."""
    return path.endswith((".tex", ".md", ".bib", ".yaml", ".yml", ".csv"))

