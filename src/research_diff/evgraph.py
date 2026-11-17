"""The evidence graph drawn for people: an SVG (for the README, the paper's appendix, a slide), an interactive HTML
page (click a statement to see the evidence chain behind it; show only the contradictions; one agent's work), and
Mermaid (GitHub draws it in a pull-request comment).

Left to right: EVIDENCE (results, runs, numbers, citations), HYPOTHESES, FINDINGS, CLAIMS; the paper's statements in a
band per paper section. One meaning per colour: green supports, red contradicts, a dashed red line is a BROKEN SUPPORT
(it backed the statement, but its source is refuted or contradicted), amber is contested. A statement's border says
its verdict; the coloured stripe on a box's left is the agent that owns it.

Deterministic: the same graph gives the same picture, byte for byte. Standard library only.
"""
from __future__ import annotations

import json
from html import escape
from typing import Dict, List, Tuple

from .evidence import WORD

W = 236                 # a box's width
GAP_X = 110             # between columns
GAP_Y = 14              # between boxes
PAD = 28
CHARS = 31              # a title line, in characters at 12.5px
COLUMNS = [("evidence", "Evidence"), ("hypothesis", "Hypotheses"), ("finding", "Findings"), ("claim", "Claims")]
VERDICT_COLOR = {"supported": "#2e7d32", "contested": "#e08a00", "contradicted": "#c62828", "unsupported": "#8a8f98",
                 "holds": "#5f6b7a"}
VERDICT_ICON = {"supported": "✓", "contested": "◐", "contradicted": "✗", "unsupported": "○", "holds": ""}
EDGE_COLOR = {"+": "#2e7d32", "~": "#e08a00", "-": "#c62828", "?": "#c62828", "0": "#b0b6bf", "o": "#8a8f98"}
AGENT_COLORS = ["#1565c0", "#6a1b9a", "#00838f", "#ad1457", "#5d4037", "#283593", "#558b2f", "#ef6c00"]
KIND_WORD = {"result": "result", "experiment": "experiment", "hypothesis": "hypothesis", "claim": "claim",
             "finding": "finding", "question": "question", "source": "citation", "note": "note", "table": "table",
             "figure": "figure", "paragraph": "paragraph, no marker"}


def wrap(text: str, n: int = CHARS, most: int = 3) -> List[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + (1 if cur else 0) > n and cur:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}" if cur else w
    if cur:
        lines.append(cur)
    if len(lines) > most:
        lines = lines[:most]
        lines[-1] = lines[-1][: n - 1].rstrip() + "…"
    return lines or [""]


def agent_colors(g: dict) -> Dict[str, str]:
    owners = sorted({n["owner"] for n in g["nodes"].values() if n["owner"]})
    return {o: AGENT_COLORS[i % len(AGENT_COLORS)] for i, o in enumerate(owners)}


def column_of(n: dict) -> str:
    if n["role"] == "statement":
        return "finding" if n["kind"] == "finding" else "claim"
    return "hypothesis" if n["role"] == "hypothesis" else "evidence"


def box_lines(nid: str, n: dict) -> Tuple[List[str], List[str]]:
    title = wrap(n["title"] or nid)
    extra = [f"{k} = {v:.4g}" for k, v in list(n["metrics"].items())[:3]] if n["role"] == "evidence" else []
    return title, extra


def box_height(nid: str, n: dict) -> int:
    title, extra = box_lines(nid, n)
    return 26 + 16 * len(title) + 15 * len(extra) + (22 if n["role"] != "evidence" or n["verdict"] != "holds" else 4)


def layout(g: dict) -> dict:
    """Where every box goes: {id: (x, y, h)}, the columns used, the section bands, and the size."""
    nodes = g["nodes"]
    used = [c for c in COLUMNS if any(column_of(n) == c[0] for n in nodes.values())]
    x_of = {c[0]: PAD + i * (W + GAP_X) for i, c in enumerate(used)}
    top = PAD + 64
    pos: Dict[str, Tuple[int, int, int]] = {}
    bands: List[Tuple[str, int, int]] = []
    paper = [c for c in ("finding", "claim") if c in x_of]
    sections: List[str] = []
    for nid, n in nodes.items():
        if n["role"] == "statement" and n["section"] not in sections:
            sections.append(n["section"])
    y = top
    for sec in sections:
        y0 = y
        y += 26 if sec else 8
        bottom = y
        for col in paper:
            yy = y
            for nid, n in nodes.items():
                if n["role"] == "statement" and n["section"] == sec and column_of(n) == col:
                    h = box_height(nid, n)
                    pos[nid] = (x_of[col], yy, h)
                    yy += h + GAP_Y
            bottom = max(bottom, yy)
        y = bottom + 10
        bands.append((sec, y0, y - y0))
        y += 12
    into: Dict[str, List[str]] = {}
    for e in g["edges"]:
        into.setdefault(e["from"], []).append(e["to"])
    for col in ("hypothesis", "evidence"):
        if col not in x_of:
            continue
        want = []
        for nid, n in nodes.items():
            if column_of(n) != col:
                continue
            ys = [pos[t][1] + pos[t][2] / 2 for t in into.get(nid, []) if t in pos]
            want.append((sum(ys) / len(ys) if ys else 10 ** 6, nid))
        want.sort()
        yy = top
        for desire, nid in want:
            h = box_height(nid, nodes[nid])
            at = max(yy, int(desire - h / 2)) if desire < 10 ** 6 else yy
            pos[nid] = (x_of[col], at, h)
            yy = at + h + GAP_Y
    width = PAD * 2 + len(used) * W + (len(used) - 1) * GAP_X + 60
    height = max([p[1] + p[2] for p in pos.values()] + [top]) + 96
    return {"pos": pos, "columns": used, "x": x_of, "bands": bands, "width": width, "height": height, "top": top}


def _free_y(want: float, boxes: List[Tuple[int, int]]) -> float:
    """The y nearest `want` that runs between a column's boxes rather than through one."""
    spans = sorted((y - 7, y + h + 7) for y, h in boxes)
    for lo, hi in spans:
        if lo < want < hi:
            options = [lo, hi]
            for o in sorted(options, key=lambda o: abs(o - want)):
                if not any(a < o < b for a, b in spans):
                    return o
    return want


def _edge_path(a: Tuple[int, int, int], b: Tuple[int, int, int], k: int, L: dict) -> Tuple[str, float, float]:
    (ax, ay, ah), (bx, by, bh) = a, b
    sy, ty = ay + ah / 2, by + bh / 2
    if ax == bx:                       # same column: an arc on its right
        x = ax + W
        bulge = 46 + 14 * (k % 4)
        return (f"M{x},{sy:.1f} C{x + bulge},{sy:.1f} {x + bulge},{ty:.1f} {x + 4},{ty:.1f}", x + bulge * 0.75,
                (sy + ty) / 2)
    forward = ax < bx
    sx, tx = (ax + W, bx - 4) if forward else (ax, bx + W + 4)
    # The columns in between: cross each through a gap between its boxes, not behind a box.
    xs = sorted(x for x in L["x"].values() if min(ax, bx) < x < max(ax, bx))
    if not forward:
        xs.reverse()
    pts = [(sx, sy)]
    for i, x in enumerate(xs):
        frac = (i + 1) / (len(xs) + 1)
        y = _free_y(sy + (ty - sy) * frac, [(p[1], p[2]) for p in L["pos"].values() if p[0] == x])
        pts += [(x - 6, y), (x + W + 6, y)] if forward else [(x + W + 6, y), (x - 6, y)]
    pts.append((tx, ty))
    d = f"M{pts[0][0]},{pts[0][1]:.1f}"
    for i in range(0, len(pts) - 1, 2):
        (x0, y0), (x1, y1) = pts[i], pts[i + 1]
        mid = (x0 + x1) / 2
        d += f" C{mid:.1f},{y0:.1f} {mid:.1f},{y1:.1f} {x1},{y1:.1f}"
        if i + 2 < len(pts):
            d += f" L{pts[i + 2][0]},{pts[i + 2][1]:.1f}"
    (x0, y0), (x1, y1) = pts[-2], pts[-1]
    return d, (x0 + x1) / 2, (y0 + y1) / 2


def svg(g: dict, title: str = "Evidence map") -> str:
    """The evidence graph as one SVG, with data-* attributes the HTML page uses (they change nothing drawn)."""
    L = layout(g)
    pos, nodes = L["pos"], g["nodes"]
    colors = agent_colors(g)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {L["width"]} {L["height"]}" width="{L["width"]}" '
           f'height="{L["height"]}" font-family="-apple-system, Segoe UI, Helvetica, Arial, sans-serif" '
           f'role="img" aria-label="{escape(title)}">',
           "<defs>" + "".join(
               f'<marker id="ah{i}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
               f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{c}"/></marker>'
               for i, c in enumerate(EDGE_COLOR.values())) + "</defs>",
           '<rect width="100%" height="100%" fill="#ffffff"/>',
           f'<text x="{PAD}" y="{PAD + 6}" font-size="17" font-weight="700" fill="#1f2328">{escape(title)}</text>',
           f'<text x="{PAD}" y="{PAD + 28}" font-size="13" fill="#57606a">{escape(g["headline"])}</text>']
    for col, label in L["columns"]:
        out.append(f'<text x="{L["x"][col]}" y="{L["top"] - 12}" font-size="11" font-weight="700" letter-spacing="1" '
                   f'fill="#8a8f98">{label.upper()}</text>')
    paper = [c for c in ("finding", "claim") if c in L["x"]]
    if paper:
        bx = L["x"][paper[0]] - 12
        bw = L["x"][paper[-1]] + W + 12 - bx
        for sec, y0, h in L["bands"]:
            out.append(f'<rect x="{bx}" y="{y0}" width="{bw}" height="{h}" rx="10" fill="#f4f6f9" stroke="#e3e7ec"/>')
            if sec:
                out.append(f'<text x="{bx + 12}" y="{y0 + 17}" font-size="11.5" font-weight="600" fill="#57606a">'
                           f'§ {escape(sec)}</text>')
    marker = {c: i for i, c in enumerate(EDGE_COLOR)}
    same_col = 0
    for e in g["edges"]:
        if e["from"] not in pos or e["to"] not in pos:
            continue
        k = 0
        if pos[e["from"]][0] == pos[e["to"]][0]:
            k, same_col = same_col, same_col + 1
        d, mx, my = _edge_path(pos[e["from"]], pos[e["to"]], k, L)
        eff = e["effective"]
        c = EDGE_COLOR[eff]
        dash = ' stroke-dasharray="2 4"' if eff == "o" else \
            ' stroke-dasharray="6 4"' if eff in ("?", "0") or e["kind"] == "weakens" else ""
        width = 2.4 if eff in ("-", "?") else 1.6
        out.append(f'<g class="edge" data-from="{escape(e["from"])}" data-to="{escape(e["to"])}" data-sign="{eff}">'
                   f'<title>{escape(e["why"])}</title><path d="{d}" fill="none" stroke="{c}" stroke-width="{width}"'
                   f'{dash} marker-end="url(#ah{marker[eff]})" opacity="0.9"/>')
        if eff in ("-", "?"):
            out.append(f'<circle cx="{mx:.1f}" cy="{my:.1f}" r="8" fill="#fff" stroke="{c}" stroke-width="1.5"/>'
                       f'<text x="{mx:.1f}" y="{my + 4:.1f}" font-size="11" text-anchor="middle" fill="{c}" '
                       f'font-weight="700">✗</text>')
        out.append("</g>")
    for nid, n in nodes.items():
        if nid not in pos:
            continue
        x, y, h = pos[nid]
        v = n["verdict"]
        border = VERDICT_COLOR[v] if n["role"] != "evidence" or v != "holds" else "#d0d7de"
        bw = 2.2 if n["role"] != "evidence" or v != "holds" else 1
        tip = f"{nid}: {n['title']}" + (f" ({n['file']}:{n['line']})" if n["file"] else "")
        out.append(f'<g class="node" data-id="{escape(nid)}" data-owner="{escape(n["owner"])}" data-verdict="{v}">'
                   f'<title>{escape(tip)}</title>'
                   f'<rect x="{x}" y="{y}" width="{W}" height="{h}" rx="8" fill="#ffffff" stroke="{border}" '
                   f'stroke-width="{bw}"/>')
        if n["owner"]:
            out.append(f'<rect x="{x}" y="{y + 6}" width="4" height="{h - 12}" rx="2" fill="{colors[n["owner"]]}"/>')
        out.append(f'<text x="{x + 12}" y="{y + 18}" font-size="12" font-weight="700" fill="#1f2328">{escape(nid)}'
                   f'<tspan font-weight="400" fill="#8a8f98" font-size="10.5">  {KIND_WORD.get(n["kind"], n["kind"])}'
                   f'</tspan></text>')
        if n["owner"]:
            out.append(f'<text x="{x + W - 10}" y="{y + 18}" font-size="10.5" text-anchor="end" '
                       f'fill="{colors[n["owner"]]}" font-weight="600">● {escape(n["owner"][:18])}</text>')
        title, extra = box_lines(nid, n)
        yy = y + 36
        for line in title:
            out.append(f'<text x="{x + 12}" y="{yy}" font-size="12.5" fill="#24292f">{escape(line)}</text>')
            yy += 16
        for line in extra:
            out.append(f'<text x="{x + 12}" y="{yy - 1}" font-size="11" fill="#57606a" '
                       f'font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace">{escape(line)}</text>')
            yy += 15
        if n["role"] != "evidence" or v != "holds":
            word = f"{VERDICT_ICON[v]} {WORD[v]}".strip()
            pw = 12 + 6.6 * len(word)
            out.append(f'<rect x="{x + 10}" y="{yy - 6}" width="{pw:.0f}" height="18" rx="9" '
                       f'fill="{VERDICT_COLOR[v]}" opacity="0.12"/><text x="{x + 16}" y="{yy + 7}" font-size="11" '
                       f'font-weight="600" fill="{VERDICT_COLOR[v]}">{escape(word)}</text>')
        out.append("</g>")
    ly = L["height"] - 34
    lx = PAD
    for label, c, dash in (("supports", EDGE_COLOR["+"], ""), ("contradicts", EDGE_COLOR["-"], ""),
                           ("broken support (its source is refuted or contradicted)", EDGE_COLOR["?"], "6 4"),
                           ("support from a contested source", EDGE_COLOR["~"], ""),
                           ("ungrounded (its source has no evidence yet)", EDGE_COLOR["o"], "2 4")):
        sign = {"supports": "+", "contradicts": "-"}.get(label) or ("?" if dash == "6 4" else "o" if dash else "~")
        if label != "supports" and not any(e["effective"] == sign for e in g["edges"]):
            continue
        out.append(f'<line x1="{lx}" y1="{ly}" x2="{lx + 26}" y2="{ly}" stroke="{c}" stroke-width="2.2"'
                   + (f' stroke-dasharray="{dash}"' if dash else "") + "/>"
                   f'<text x="{lx + 32}" y="{ly + 4}" font-size="11" fill="#57606a">{escape(label)}</text>')
        lx += 46 + int(6.2 * len(label))
    if colors:
        lx = PAD
        out.append(f'<text x="{lx}" y="{ly + 22}" font-size="11" fill="#57606a">agents:</text>')
        lx += 50
        for name, c in colors.items():
            out.append(f'<rect x="{lx}" y="{ly + 13}" width="4" height="12" rx="2" fill="{c}"/>'
                       f'<text x="{lx + 9}" y="{ly + 23}" font-size="11" fill="{c}" font-weight="600">'
                       f'{escape(name)}</text>')
            lx += 24 + int(6.5 * len(name))
    out.append("</svg>")
    return "\n".join(out) + "\n"


def mermaid(g: dict) -> str:
    """The graph in Mermaid (GitHub draws it in Markdown): sections as subgraphs, green and red links."""
    nodes = g["nodes"]
    safe = {nid: "n_" + "".join(ch if ch.isalnum() else "_" for ch in nid) for nid in nodes}
    lines = ["flowchart LR"]

    def label(nid: str, n: dict) -> str:
        t = (n["title"] or "")[:48].replace('"', "'")
        v = f"<br/>{VERDICT_ICON[n['verdict']]} {WORD[n['verdict']]}" if n["role"] != "evidence" or \
            n["verdict"] != "holds" else ""
        own = f"<br/><i>{n['owner']}</i>" if n["owner"] else ""
        return f'{safe[nid]}["<b>{nid}</b> {t}{v}{own}"]'
    sections: Dict[str, List[str]] = {}
    for nid, n in nodes.items():
        if n["role"] == "statement":
            sections.setdefault(n["section"], []).append(nid)
        else:
            lines.append("  " + label(nid, n))
    for i, (sec, ids) in enumerate(sections.items()):
        if sec:
            lines.append(f'  subgraph s{i}["§ {sec[:40]}"]')
        lines += ["    " + label(nid, nodes[nid]) for nid in ids]
        if sec:
            lines.append("  end")
    styles = []
    for i, e in enumerate(x for x in g["edges"] if x["from"] in safe and x["to"] in safe):
        arrow = "-.->" if e["effective"] in ("?", "0", "o") or e["kind"] == "weakens" else "-->"
        word = {"+": "supports", "~": "supports", "-": "contradicts", "?": "broken", "0": "void",
                "o": "ungrounded"}[e["effective"]]
        lines.append(f"  {safe[e['from']]} {arrow}|{word}| {safe[e['to']]}")
        styles.append(f"  linkStyle {i} stroke:{EDGE_COLOR[e['effective']]},stroke-width:2px")
    lines += styles
    for v, c in VERDICT_COLOR.items():
        lines.append(f"  classDef {v} stroke:{c},stroke-width:2px")
    for nid, n in nodes.items():
        if n["role"] != "evidence" or n["verdict"] != "holds":
            lines.append(f"  class {safe[nid]} {n['verdict']}")
    return "\n".join(lines) + "\n"


PAGE = """<title>__TITLE__</title>
<style>
:root{--bg:#f6f8fa;--panel:#fff;--ink:#1f2328;--muted:#57606a;--line:#d0d7de;--red:#c62828;--green:#2e7d32;
--amber:#e08a00;color-scheme:light}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#0d1117;--panel:#161b22;--ink:#e6edf3;
--muted:#8d96a0;--line:#30363d;color-scheme:dark}}
:root[data-theme=dark]{--bg:#0d1117;--panel:#161b22;--ink:#e6edf3;--muted:#8d96a0;--line:#30363d;color-scheme:dark}
body{background:var(--bg);color:var(--ink);font:14px/1.45 -apple-system,Segoe UI,Helvetica,Arial,sans-serif;margin:0}
.wrap{display:flex;gap:16px;padding:16px;flex-wrap:wrap}
.graph{flex:1 1 640px;min-width:0;overflow:auto;background:#fff;border:1px solid var(--line);border-radius:10px}
.graph svg{display:block;max-width:none}
.side{flex:0 1 360px;min-width:0}
.bar{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px}
button{font:inherit;border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:16px;
padding:3px 12px;cursor:pointer}
button.on{border-color:#1565c0;color:#1565c0;font-weight:600}
.card{background:var(--panel);border:1px solid var(--line);border-left-width:4px;border-radius:8px;padding:8px 10px;
margin-bottom:8px;cursor:pointer}
.card.supported{border-left-color:var(--green)}.card.contested{border-left-color:var(--amber)}
.card.contradicted{border-left-color:var(--red)}.card.unsupported{border-left-color:#8a8f98}
.card .v{font-size:12px;font-weight:600}.card ul{margin:4px 0 0 0;padding-left:18px;font-size:12.5px;color:var(--muted)}
.card li.against{color:var(--red)}
h1{font-size:17px;margin:0 0 4px}.muted{color:var(--muted);font-size:12.5px}
.dim{opacity:.13;transition:opacity .15s}.hide{display:none}
g.node{cursor:pointer}
g.node.pointed rect:first-of-type{stroke:#1565c0;stroke-width:4}
.card .note{color:#1565c0;font-size:12.5px;margin-top:4px}
</style>
<div class="wrap">
 <div class="graph" id="graph">__SVG__</div>
 <div class="side">
  <h1>__TITLE__</h1><div class="muted" id="head"></div>
  <div class="bar" id="bar" style="margin-top:10px">
   <button data-f="all" class="on">All</button><button data-f="contra">Only contradictions</button>
  </div>
  <div class="bar" id="agents"></div>
  <div id="cards"></div>
  <div class="muted">Click a box or a card: its evidence chain lights up. Click the empty space to clear.</div>
 </div>
</div>
<script>
const G = __DATA__;
const svg = document.querySelector('#graph svg');
const nodes = [...svg.querySelectorAll('g.node')], edges = [...svg.querySelectorAll('g.edge')];
document.getElementById('head').textContent = G.headline;
let focus = null, filter = 'all', agent = '';
function chain(id){ // everything upstream (its evidence) and downstream (what it backs) of id
  const keep = new Set([id]); let grew = true;
  const up = new Set([id]), down = new Set([id]);
  while (grew) { grew = false;
    for (const e of G.edges) {
      if (up.has(e.to) && !up.has(e.from)) { up.add(e.from); grew = true; }
      if (down.has(e.from) && !down.has(e.to)) { down.add(e.to); grew = true; }
    } }
  up.forEach(x => keep.add(x)); down.forEach(x => keep.add(x)); return keep;
}
function draw(){
  const keep = focus ? chain(focus) : null;
  const contra = new Set();
  for (const e of G.edges) if (e.effective === '-' || e.effective === '?') { contra.add(e.from); contra.add(e.to); }
  for (const n of nodes) { const id = n.dataset.id;
    let on = (!keep || keep.has(id)) && (filter === 'all' || contra.has(id)) && (!agent || n.dataset.owner === agent);
    n.classList.toggle('dim', !on); }
  for (const e of edges) { const f = e.dataset.from, t = e.dataset.to, s = e.dataset.sign;
    let on = (!keep || (keep.has(f) && keep.has(t))) && (filter === 'all' || s === '-' || s === '?');
    if (agent) on = on && [f, t].some(x => (G.nodes[x] || {}).owner === agent);
    e.classList.toggle('dim', !on); }
  for (const c of document.querySelectorAll('.card')) c.style.outline = c.dataset.id === focus ? '2px solid #1565c0' : '';
}
nodes.forEach(n => n.addEventListener('click', ev => { ev.stopPropagation(); focus = focus === n.dataset.id ? null : n.dataset.id; draw(); }));
svg.addEventListener('click', () => { focus = null; draw(); });
document.querySelectorAll('#bar button').forEach(b => b.onclick = () => {
  filter = b.dataset.f; document.querySelectorAll('#bar button').forEach(x => x.classList.toggle('on', x === b)); draw(); });
const owners = [...new Set(Object.values(G.nodes).map(n => n.owner).filter(Boolean))].sort();
const ab = document.getElementById('agents');
if (owners.length) { for (const o of ['', ...owners]) { const b = document.createElement('button');
  b.textContent = o || 'Every agent'; if (!o) b.classList.add('on');
  b.onclick = () => { agent = o; ab.querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b)); draw(); };
  ab.appendChild(b); } }
const W = {supported:'✓ supported', contested:'◐ contested', contradicted:'✗ contradicted', unsupported:'○ no evidence'};
const cards = document.getElementById('cards');
const order = {contradicted:0, contested:1, unsupported:2, supported:3};
for (const s of [...G.statements].sort((a, b) => order[a.verdict] - order[b.verdict])) {
  const d = document.createElement('div'); d.className = 'card ' + s.verdict; d.dataset.id = s.id;
  const li = (x, cls) => `<li class="${cls}">${x.why.replace(/[<&]/g, c => ({'<':'&lt;','&':'&amp;'}[c]))}</li>`;
  d.innerHTML = `<div><b>${s.id}</b> ${s.title.replace(/[<&]/g, c => ({'<':'&lt;','&':'&amp;'}[c]))}</div>
    <div class="v" style="color:${{supported:'#2e7d32',contested:'#e08a00',contradicted:'#c62828',unsupported:'#8a8f98'}[s.verdict]}">
    ${W[s.verdict]}${s.section ? ' · § ' + s.section : ''}${s.owner ? ' · ' + s.owner : ''}</div>
    <ul>${s.against.map(x => li(x, 'against')).join('')}${s.for.map(x => li(x, '')).join('')}</ul>` +
    (G.notes[s.id] || []).map(t => `<div class="note">✎ Claude: ${t.replace(/[<&]/g, c => ({'<':'&lt;','&':'&amp;'}[c]))}</div>`).join('');
  d.onclick = () => { focus = focus === s.id ? null : s.id; draw(); };
  cards.appendChild(d);
}
for (const n of nodes) n.classList.toggle('pointed', G.pointing.includes(n.dataset.id));
if (G.pointing.length) { const first = nodes.find(n => n.dataset.id === G.pointing[0]); if (first) first.scrollIntoView({block: 'center', inline: 'center'}); }
draw();
</script>
"""


def html(g: dict, title: str = "Evidence map") -> str:
    """A page of its own (no outside files): the graph, the statements by verdict, and the filters."""
    data = json.dumps({**{k: g[k] for k in ("headline", "nodes", "edges", "statements")},
                       "notes": g.get("notes", {}), "pointing": g.get("pointing", [])}, ensure_ascii=False)
    return (PAGE.replace("__TITLE__", escape(title)).replace("__SVG__", svg(g, title))
            .replace("__DATA__", data.replace("</", "<\\/")))


def standalone(g: dict, title: str = "Evidence map") -> str:
    return '<!doctype html>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width">\n' + html(g, title)
