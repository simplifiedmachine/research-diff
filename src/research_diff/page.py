"""The views, as PAGES: rows of (text, style, ids) runs, the blocks among them a person can pick, and what each block
lights when picked. The same page is painted by the pane beside the chat in Claude Code (mods/research-diff, through
`research-diff panel --protocol 2`), by the terminal view (`research-diff tui`), and as text (`research-diff show`).

  now       what Claude is doing and on which node; the evidence at a glance, worst first; WORTH A LOOK, ranked by
            consequence; your objectives; or, zoomed in on a node, its evidence chain and its history
  review    everything since your checkpoint, exactly
  evidence  every statement of the paper by section, with what supports it and what contradicts it
  paper     the paper as written, section by section: its statements, tables and figures, every number it prints
            checked against the results, a summary of each section by your LLM (✦), and the LLM's review
  agents    the team: what each agent owns, its verdicts, where it contradicts another agent, and the bus
  history   how the research got here: what you asked, what it got
  auto      auto-research: the campaign (goal, target, budget), each iteration's experiments on your servers' GPUs,
            their state and logs, Claude's analysis and what it changed

Styles are words: accent (blue: where Claude is, what you picked), attention (yellow: contested, needs you), good
(green: supported, new), removed (red: contradicted, taken away), muted, heading, bold, title, agent0..agent4.
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional

from . import activity, agents, compare, evidence, history, objectives, rank, store
from .evidence import WORD

VIEWS = ("now", "review", "evidence", "paper", "agents", "history", "auto")
STYLE = {"supported": "good", "contested": "attention", "contradicted": "removed bold", "unsupported": "muted",
         "holds": "muted"}
ICON = {"supported": "✓", "contested": "◐", "contradicted": "✗", "unsupported": "○", "holds": "·"}
EFF = {"+": ("✓", "good"), "~": ("◐", "attention"), "-": ("✗", "removed"), "?": ("✗", "removed"), "0": ("·", "muted"),
       "o": ("○", "muted")}
ORDER = {"contradicted": 0, "contested": 1, "unsupported": 2, "supported": 3}


class Page:
    def __init__(self, view: str, part: str, width: int):
        self.view, self.part, self.width = view, part, max(40, width)
        self.rows: List[list] = []
        self.blocks: List[dict] = []
        self.lights: Dict[str, List[str]] = {}
        self.details: Dict[str, list] = {}
        self.pick = ""

    def row(self, *runs) -> int:
        out, used = [], 0
        for r in runs:
            if not r or not r[0]:
                continue
            text = r[0][: max(0, self.width - used)]
            if not text:
                break
            out.append([text, r[1]] + ([r[2]] if len(r) > 2 and r[2] else []))
            used += len(text)
        self.rows.append(out)
        return len(self.rows) - 1

    def blank(self) -> None:
        if self.rows and self.rows[-1]:
            self.rows.append([])

    def heading(self, text: str, extra: str = "") -> None:
        self.blank()
        self.row((text.upper(), "heading"), ("  " + extra if extra else "", "muted"))

    def block(self, bid: str, y: int, enter: Optional[dict] = None, on: Optional[dict] = None,
              lights: Optional[List[str]] = None, h: int = 1) -> None:
        b = {"id": bid, "x": 0, "y": y, "w": self.width, "h": h}
        if enter:
            b["enter"] = enter
        if on:
            b["on"] = on
        self.blocks.append(b)
        if lights:
            self.lights[bid] = lights
        if not self.pick:
            self.pick = bid

    def data(self) -> dict:
        return {"protocol": 2, "view": self.view, "part": self.part, "width": self.width,
                "wide": max([sum(len(r[0]) for r in row) for row in self.rows] + [self.width]),
                "rows": self.rows, "blocks": self.blocks, "lights": self.lights, "details": self.details,
                "pick": self.pick}


def look(root: Path, base: str = "checkpoint", config_path: Optional[str] = None) -> dict:
    """Everything the views draw from, read once."""
    c = compare.compare(root, base, ".", config_path)
    owners = agents.owners(root)
    g = evidence.build(c.after, c.cfg, owners)
    objs = objectives.current(root)
    from . import chat, review
    rv = review.current(root)
    worth = sorted(review.worth(rv) + rank.worth_a_look(c.diff, c.after, 6, objs), key=lambda x: -x["score"])[:7]
    return {"cmp": c, "map": c.after, "graph": g, "objectives": objs, "review": rv, "worth": worth,
            "focus": activity.focus(root, c.after), "request": activity.last_request(root), "root": root,
            "notes": chat.notes_by_node(root), "pointing": chat.pointing(root)}


def _title(L: dict, nid: str, n: int = 60) -> str:
    node = L["map"]["nodes"].get(nid) or L["graph"]["nodes"].get(nid) or {}
    t = node.get("title", "")
    return t if len(t) <= n else t[: n - 1] + "…"


def _statement_row(p: Page, L: dict, s: dict, pad: str = "") -> int:
    v = s["verdict"]
    return p.row((pad + f"{ICON[v]} ", STYLE[v], f"b:{s['id']}"), (s["id"] + " ", "bold title", f"b:{s['id']}"),
                 (f"{WORD[v]:<13}", STYLE[v]), (_title(L, s["id"], 70), ""),
                 (f"  · {s['owner']}" if s["owner"] else "", "muted"))


def _evidence_rows(p: Page, s: dict, pad: str = "    ") -> List[str]:
    ids = []
    for x in s["against"] + s["for"]:
        icon, style = EFF.get(x["effective"], ("·", "muted"))
        rid = f"e:{s['id']}:{x['from']}:{x['kind']}"
        p.row((pad + icon + " ", style, rid), (f"{x['from']:<12}", "bold", rid), (x["why"], style if x["effective"]
                                                                                    in ("-", "?") else "muted", rid))
        ids.append(rid)
    if not ids:
        p.row((pad + "○ nothing backs it yet: add `relies on:`, `supported by:` or `expects:`", "muted"))
    return ids


def view_now(L: dict, p: Page) -> None:
    g, f = L["graph"], L["focus"]
    if f:
        nid, how, who = f
        p.row(("● ", "accent"), (f"{'Claude' if who == 'main' else who} is {how} ", "accent"),
              (nid, "accent bold"), ("  " + _title(L, nid), ""))
    else:
        p.row(("○ Nothing on the map is being worked on right now", "muted"))
    if L["request"]:
        p.row(("  You asked: ", "muted"), (f"“{L['request'][:200]}”", ""))
    if p.part and not p.part.startswith("#"):
        return view_zoom(L, p, p.part)
    p.heading("Evidence", g["headline"])
    for c in g["conflicts"]:
        y = p.row(("  ✗ The paper contradicts itself: ", "removed bold"), (c["why"], "removed"))
        p.block(f"x:{c['from']}>{c['to']}", y, {"zoom": c["to"]})
    for s in sorted(g["statements"], key=lambda s: (ORDER[s["verdict"]], s["file"], s["line"])):
        y = _statement_row(p, L, s, "  ")
        p.block(f"b:{s['id']}", y, {"zoom": s["id"]})
        if s["verdict"] in ("contradicted", "contested"):
            p.row(("      ", ""), (s["against"][0]["why"], "removed"))
    p.heading("Worth a look", f"since {L['cmp'].base}: {L['cmp'].diff['headline']}")
    if not L["worth"]:
        p.row(("  Nothing new of consequence since your checkpoint.", "muted"))
    for i, it in enumerate(L["worth"], 1):
        style = "removed" if it["score"] >= 80 else "attention" if it["score"] >= 45 else ""
        y = p.row((f"  {i}. ", "muted"), (it["title"], style + " bold"))
        p.block(f"w:{i}", y, {"zoom": it["ids"][0]} if it["ids"] else None)
        if it["why"]:
            p.row(("     " + it["why"], "muted"))
        if it.get("objective"):
            p.row(("     touches your objective: " + it["objective"], "good"))
    if L["objectives"]:
        p.heading("Your objectives", "x on one clears it")
        for o in L["objectives"]:
            y = p.row(("  ◆ ", "good"), (o["text"], ""), (f"  ({o['by']})", "muted"))
            p.block(f"o:{o['id']}", y, on={"x": {"clear_objective": o["id"]}})


def view_zoom(L: dict, p: Page, nid: str) -> None:
    g = L["graph"]
    node = L["map"]["nodes"].get(nid) or g["nodes"].get(nid)
    if not node:
        p.row((f"  {nid} is not on the map any more.", "muted"))
        return
    gn = g["nodes"].get(nid, {})
    v = gn.get("verdict", "")
    p.heading(f"{nid}", f"{node.get('kind', '')} · {(node.get('files') or [gn.get('file', '')])[0]}")
    p.row(("  " + node.get("title", ""), "bold"))
    if v:
        p.row(("  " + ICON[v] + " " + WORD[v], STYLE[v]), (f"  · § {gn['section']}" if gn.get("section") else "", "muted"),
              (f"  · owned by {gn['owner']}" if gn.get("owner") else "", "muted"))
    for k, val in list(node.get("metrics", {}).items())[:8]:
        p.row((f"    {k} = {val:.4g}", "muted"))
    st = next((s for s in g["statements"] if s["id"] == nid), None)
    p.heading("Its evidence")
    if st:
        _evidence_rows(p, st)
    lines = evidence.chain(g, nid)
    if lines and not st:
        for ln in lines[:30]:
            p.row(("  " + ln, "removed" if ln.lstrip().startswith("✗") else "muted"))
    elif st:
        deeper = [ln for ln in lines if ln.startswith("    ")]
        if deeper:
            p.heading("Behind that")
            for ln in deeper[:20]:
                p.row(("  " + ln, "removed" if ln.lstrip().startswith("✗") else "muted"))
    used = [e["to"] for e in g["edges"] if e["from"] == nid]
    if used:
        p.heading("What it backs or contradicts")
        for e in g["edges"]:
            if e["from"] == nid:
                icon, style = EFF[e["effective"]]
                y = p.row((f"  {icon} ", style), (e["to"] + " ", "bold"), (e["why"], "muted"))
                p.block(f"b:{e['to']}", y, {"zoom": e["to"]})
    notes = L["notes"].get(nid, [])
    if notes:
        p.heading("Claude's notes")
        for n in notes[-5:]:
            p.row(("  ✎ ", "accent"), (n["text"], ""))
    past = history.load(L["root"], nid, 5)
    if past:
        p.heading("Its history", "h shows all")
        for e in reversed(past):
            p.row(("  " + time.strftime("%m-%d %H:%M", time.localtime(e["at"])) + "  ", "muted"),
                  (e["headline"][:140], ""))


def view_review(L: dict, p: Page) -> None:
    c = L["cmp"]
    p.row(("Since ", "muted"), (c.base, "bold"), (": ", "muted"), (c.diff["headline"], ""))
    p.row(("  Mark it as seen (`research-diff checkpoint`, or the web page's button) to see only what comes next.",
           "muted"))
    p.blank()
    sym_style = {"+": "good", "~": "attention", "-": "removed"}
    for line in c.diff["plan"].splitlines():
        s = line[:1]
        if s in sym_style:
            ids = [w for w in line.split()[2:3]]
            y = p.row((line, sym_style[s]))
            nid = ids[0] if ids else ""
            if nid and nid[:1].isupper() and nid[1:2].isdigit():
                p.block(f"r:{len(p.blocks)}", y, {"zoom": nid.split(" ")[0].rstrip(":")})
        else:
            p.row((line, "muted"))


def view_evidence(L: dict, p: Page) -> None:
    g = L["graph"]
    p.row((g["headline"], "bold"))
    for c in g["conflicts"]:
        p.row(("✗ The paper contradicts itself: ", "removed bold"), (c["why"], "removed"))
    for c in g["cross_agent"]:
        p.row(("⚑ Across agents: ", "attention bold"), (f"{c['why']} ({c['owners'][0]} → {c['owners'][1]})", "attention"))
    by_sec: Dict[str, List[dict]] = {}
    for s in g["statements"]:
        by_sec.setdefault(s["section"], []).append(s)
    for sec, stmts in by_sec.items():
        p.heading("§ " + (sec or "Paper"))
        for s in stmts:
            y = _statement_row(p, L, s, "  ")
            ids = _evidence_rows(p, s, "      ")
            p.block(f"b:{s['id']}", y, {"zoom": s["id"]}, lights=ids)
    p.blank()
    p.row(("✓ supports  ◐ from a contested source  ○ ungrounded  ✗ contradicts (or a broken support)  · void", "muted"))


def view_paper(L: dict, p: Page) -> None:
    """The paper as written, section by section, beside its evidence."""
    from . import paperview, review
    bp, g = L["map"], L["graph"]
    files = [x["path"] for x in bp.get("paper", [])]
    if not files:
        p.row(("No paper yet: research-diff reads the files the `paper` globs of research-diff.toml name "
               "(LaTeX or Markdown).", "muted"))
    for path in files:
        o = paperview.outline(L["root"], path, bp, g)
        s = o.get("summary") or {}
        y = p.row(("▤ ", "accent"), (path, "bold"), ("  ✦ summarised" if s else "  (summarising: ✦ appears when ready)"
                                                     if paperview.start(L["root"], path) else "", "muted"))
        p.block(f"f:{path}", y, {"file": path})
        if s.get("file"):
            p.row(("  ✦ " + s["file"], "muted"))
        for c in o["chunks"]:
            bad = [n for n in c["numbers"] if n["sign"] == "-"]
            ok = sum(1 for n in c["numbers"] if n["sign"] == "+")
            p.heading("§ " + c["title"], f"lines {c['line']}-{c['end']}" + (f" · ✓ {ok} number{'s' if ok != 1 else ''} "
                                                                            "match the results" if ok else ""))
            cs = (s.get("sections") or {}).get(c["title"], {})
            for k, label in (("says", "says"), ("claims", "claims"), ("watch", "watch")):
                if cs.get(k):
                    p.row((f"  ✦ {label}: ", "attention" if k == "watch" else "muted"), (cs[k], ""))
            for st in c["statements"]:
                v = st["verdict"] or "unsupported"
                y = p.row(("  " + ICON.get(v, "·") + " ", STYLE.get(v, "muted"), f"b:{st['id']}"),
                          (st["id"] + " ", "bold title", f"b:{st['id']}"), (st["title"][:90], ""))
                p.block(f"b:{st['id']}", y, {"zoom": st["id"]})
            for f in c["floats"]:
                v = f["verdict"] or "holds"
                y = p.row(("  ▦ " if f["kind"] == "table" else "  ◫ ", STYLE.get(v, "muted")), (f["label"] + " ", "bold"),
                          (f["caption"][:80], "muted"), (f"  {WORD.get(v, '')}" if v not in ("holds",) else "", STYLE.get(v, "")))
                p.block(f"b:{f['label']}", y, {"zoom": f["label"]})
            for n in bad:
                p.row(("  ✗ ", "removed"), (f"line {n['line']}: {n['why']}", "removed"))
    rv = L["review"]
    p.heading("Review", review.headline(rv) or "none yet: `research-diff review` asks your LLM to read the paper "
                                                  "against itself and its results")
    for f in rv.get("findings", []):
        y = p.row(("  ✦ ", "removed" if f["kind"] == "contradiction" else "attention"),
                  (f["kind"] + (f" ({' vs '.join(f['sections'])})" if f["sections"] else "") + ": ", "bold"),
                  (f["why"], ""))
        if f["ids"]:
            p.block(f"v:{len(p.blocks)}", y, {"zoom": f["ids"][0]})
        for q in f["quotes"][:2]:
            p.row(("      “" + q + "”", "muted"))


def view_auto(L: dict, p: Page) -> None:
    from . import autoresearch as ar
    root = L["root"]
    c = ar.campaign(root)
    ss = ar.servers(root)
    p.row(("Servers: ", "muted"), (", ".join(f"{s['name']} ({s['host']}, " + (f"GPU {','.join(map(str, s['gpus']))}"
                                                                             if s["gpus"] else "CPU") + ")"
                                             for s in ss) or "none yet", ""))
    if not c:
        p.row(("Auto-research is off. On the web page (Auto-research tab), or: research-diff auto server add NAME "
               "local|HOST --gpus 0,1, then research-diff auto start \"GOAL\" --target 'E1.results acc > 0.9'.", "muted"))
        return
    style = {"running": "good", "paused": "attention", "stopping": "removed", "stopped": "muted", "done": "good"}
    p.row(("● " if c["state"] == "running" else "‖ " if c["state"] == "paused" else "■ ", style.get(c["state"], "")),
          (f"Auto-research {c['state']}: ", style.get(c["state"], "") + " bold"), (c["goal"], "bold"))
    p.row((f"  target {c['target'] or 'none'} · iteration {len(c['iterations'])} of {c['max_iterations']} · "
           f"runner {'on' if ar.runner_alive(root) else 'off (starts by itself)'}", "muted"))
    if c.get("summary"):
        p.row(("  " + c["summary"], "good"))
    jstyle = {"done": "good", "failed": "removed", "running": "accent", "queued": "muted", "killed": "muted"}
    for it in reversed(c["iterations"]):
        p.heading(f"Iteration {it['n']}", it["state"] + (f": {it['reason'][:120]}" if it["reason"] else ""))
        if it.get("analysis"):
            p.row(("  analysis: ", "muted"), (it["analysis"][:240], ""))
        for k in it["jobs"]:
            j = c["jobs"][k]
            y = p.row((f"  {j['id']} ", "muted"), (f"{j['experiment']:<8}", "bold"), (f"{j['state']:<8}", jstyle.get(j["state"], "")),
                      (f" {j['server'] or ''}" + (f" GPU {','.join(map(str, j['gpus']))}" if j["gpus"] else ""), "muted"),
                      (f"  {j['why']}" if j["why"] else "", "removed" if j["state"] == "failed" else "muted"))
            if j["experiment"]:
                p.block(f"j:{k}", y, {"zoom": j["experiment"]})
            if j["state"] in ("running", "failed") and j["tail"]:
                for line in j["tail"].splitlines()[-3:]:
                    p.row(("      " + line[:150], "muted"))
    if c.get("events"):
        p.heading("What happened")
        for e in reversed(c["events"][-8:]):
            p.row((time.strftime("  %H:%M ", time.localtime(e["at"])), "muted"), (e["text"], ""))


def view_agents(L: dict, p: Page) -> None:
    root, g = L["root"], L["graph"]
    s = agents.state(root)
    t = agents.team(root, g)
    if s["plan"]:
        p.row(("Plan: ", "muted"), (s["plan"]["task"][:160], "bold"),
              (f"  ({len(s['plan']['agents'])} agents, by {s['plan']['by']})", "muted"))
    if not t:
        p.row(("No agents yet. Ask Claude to plan a team (the `plan_agents` tool), or write `by: <agent>` under the "
               "markers each agent owns.", "muted"))
    for i, a in enumerate(t):
        colour = f"agent{i % 5}"
        p.blank()
        v = "  ".join(f"{ICON[k]}{n}" for k, n in sorted(a["verdicts"].items(), key=lambda kv: ORDER[kv[0]]))
        y = p.row(("● ", colour), (a["name"], colour + " bold"), (f"  {v}" if v else "", ""),
                  (f"   ✉ {a['unread']} unread" if a["unread"] else "", "attention"))
        p.block(f"a:{a['name']}", y, {"zoom": a["owns"][0]} if a["owns"] else None,
                lights=[f"b:{x}" for x in a["owns"]])
        p.row(("   owns ", "muted"), (", ".join(a["owns"][:14]) + (" …" if len(a["owns"]) > 14 else ""), ""))
        for c in a["contradicts"]:
            p.row(("   ✗ its ", "removed"), (c["why"], "removed"), (f"  → {c['owners'][1]}'s", "muted"))
        for c in a["contradicted_by"]:
            p.row(("   ✗ contradicted: ", "removed"), (c["why"], "removed"), (f"  ← {c['owners'][0]}'s", "muted"))
    msgs = s["messages"][-12:]
    if msgs:
        p.heading("The bus", "what each agent changed, on the topics of the nodes it touched")
        for m in reversed(msgs):
            style = "removed" if m["text"].startswith("CONTRADICTION") else "muted" if m.get("auto") else ""
            p.row((time.strftime("  %H:%M ", time.localtime(m["at"])), "muted"), (f"[{m['topic']}] ", "bold"),
                  (f"{m['from']}: ", "accent"), (m["text"], style))


def view_history(L: dict, p: Page) -> None:
    root = L["root"]
    part = p.part
    if part.startswith("#") or "#" in part:
        eid = part.split("#", 1)[1]
        e = next((x for x in history.load(root) if x["id"] == eid), None)
        if e:
            p.row(("You asked: " if e.get("request") else "", "muted"), (e.get("request") or e.get("message") or "", "bold"))
            p.row(("→ it got: ", "muted"), (e["headline"], ""))
            for x in e["items"]:
                y = p.row(("  · ", "muted"), (x["title"], "bold"), (("  " + x["why"]) if x["why"] else "", "muted"))
                if x["ids"]:
                    p.block(f"h:{len(p.blocks)}", y, {"zoom": x["ids"][0]})
            return
    entries = history.load(root, part)
    p.row((f"History of {part}" if part else "How the research got here", "bold"),
          ("  newest first; ↵ on one shows it", "muted"))
    if not entries:
        p.row((history.text([]), "muted"))
    for e in reversed(entries[-40:]):
        p.blank()
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(e["at"]))
        head = f"You asked: “{e['request'][:120]}”" if e.get("request") else \
            f"{e['commit']}: {e['message'][:120]}" if e.get("commit") else "A change no request explains"
        y = p.row((when + "  ", "muted"), (head, "bold"), (f"  [{', '.join(e['by'])}]" if e.get("by") else "", "accent"))
        p.block(f"e:{e['id']}", y, {"entry": e["id"]})
        p.row(("    → ", "muted"), (e["headline"][:220], ""))


def show(root: Path, view: str = "now", part: str = "", width: int = 100, base: str = "checkpoint",
         config_path: Optional[str] = None, deliver: bool = False) -> dict:
    """The page of one view. `deliver`: the pane is asking: it takes what waits to be submitted to the session (what
    was typed on the web page, and auto-research's ask when an iteration ended), once."""
    L = look(root, base, config_path)
    p = Page(view if view in VIEWS else "now", part, width)
    {"now": view_now, "review": view_review, "evidence": view_evidence, "paper": view_paper, "auto": view_auto,
     "agents": view_agents,
     "history": view_history}[p.view](L, p)
    data = p.data()
    from . import host
    data["merged"] = host.merged()                # its tabs are in system-diff's pane and page
    data["web"] = host.system_web(root) if data["merged"] else web_url(root)
    data["research"] = bool(L["map"]["nodes"])    # the pane opens by itself only where there is research
    data["send"] = take_outbox(root) if deliver else []
    if deliver:
        from . import autoresearch
        autoresearch.ensure_runner(root)      # the pane is open: the session is here, the runner should be too
        if not data["web"]:
            start_web(root)                   # and the web page: the pane shows its address once it answers
        ask = autoresearch.untold(root)
        if ask:
            c = autoresearch.campaign(root)
            data["send"].append({"id": f"auto-{c['id']}-{len(c['iterations'])}-{c.get('ask', '')}", "text": ask})
            autoresearch.told(root)
    activity.write_state(root, headline=L["cmp"].diff["headline"], evidence=L["graph"]["headline"],
                         worth=[w["title"] for w in L["worth"][:2]], focus=list(L["focus"] or []),
                         contradictions=sum(1 for e in L["graph"]["edges"] if e["effective"] in ("-", "?")))
    return data


def take_outbox(root: Path) -> List[dict]:
    """What was typed in the web page's Send to Claude box, handed over once."""
    path = store.home(root) / "outbox.jsonl"
    try:
        got = store.lines(root, "outbox.jsonl")
        path.unlink()
    except OSError:
        return []
    for x in got:   # what the session is about to be asked: its answer is kept for the page (chat.answered)
        store.append(root, "delivered.jsonl", {"id": x.get("id"), "text": x.get("text", "")})
    return [{"id": str(x.get("id")), "text": str(x.get("text", ""))} for x in got if x.get("text")]


def web_url(root: Path) -> str:
    """This repository's web page, when its server answers as itself (GET /whoami gives web.json's id: not another
    program, or another repository's engine, that took the port since)."""
    import http.client
    import json as _json
    w = store.read(root, "web.json", {}) or {}
    port = w.get("port")
    if not port:
        return ""
    conn = http.client.HTTPConnection("127.0.0.1", int(port), timeout=0.4)
    try:
        conn.request("GET", "/whoami")
        r = conn.getresponse()
        info = _json.loads(r.read(4096).decode("utf-8")) if r.status == 200 else {}
    except (OSError, ValueError, http.client.HTTPException):
        return ""
    finally:
        conn.close()
    return f"http://localhost:{port}/" if info.get("id") and info.get("id") == w.get("id") else ""


def as_text(data: dict, color: bool = False) -> str:
    codes = {"accent": "34", "good": "32", "attention": "33", "removed": "31", "muted": "2", "heading": "2;1",
             "bold": "1", "agent0": "36", "agent1": "35", "agent2": "32", "agent3": "33", "agent4": "34"}
    out = []
    for row in data["rows"]:
        line = ""
        for run in row:
            if color:
                cs = [codes[w] for w in run[1].split() if w in codes]
                line += f"\x1b[{';'.join(cs)}m{run[0]}\x1b[0m" if cs else run[0]
            else:
                line += run[0]
        out.append(line)
    return "\n".join(out)


def start_web(root: Path) -> None:
    """The web page's server, detached, unless one answers already (or one was started a moment ago). Never in tests:
    a server they started would outlive them."""
    import os
    import sys
    import time as _time
    if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get("RESEARCH_DIFF_WEB_IN_TESTS"):
        return
    from . import host
    if host.merged():                 # system-diff's engine serves research-diff's tabs: no server of its own
        return
    if os.environ.get("RESEARCH_DIFF_WEB", "").lower() in ("off", "0", "no") or web_url(root):
        return
    mark = store.home(root) / "web.starting"
    try:
        if _time.time() - mark.stat().st_mtime < 20:
            return
    except OSError:
        pass
    mark.write_text(str(_time.time()))
    flags = {"start_new_session": True} if os.name != "nt" else {"creationflags": 0x08000000 | 0x00000200}
    try:
        subprocess.Popen([sys.executable, "-m", "research_diff", "--repo", str(root), "watch", "--port", "0",
                          "--quiet"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         cwd=str(root), **flags)
    except OSError:
        pass
