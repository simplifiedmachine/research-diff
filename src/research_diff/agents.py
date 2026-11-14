"""Many agents on one study: a PLAN that splits the work by the research's own parts (one agent per paper section, per
hypothesis, or as the person says), CLAIMS so each agent keeps to its own nodes, and a BUS whose topics are node ids.

- Every agent owns nodes (the claims, findings, hypotheses, experiments it works on) and WATCHES the nodes its own rely
  on: the evidence upstream of what it owns.
- Every change to a node is published on that node's topic by the hooks, as it happens ("R2: gap 0.032 → 0.002");
  agents publish their own notes too. When one agent's result comes to contradict another agent's claim, the owner of
  the claim is told on its topic, first: the agents find out that they contradict each other while they work, not when
  the paper is read.
- Each agent's unread messages reach it with its next tool result of any kind (the PostToolUse hook), without waiting.

Who is who: Claude Code names a subagent by an id (`agent_id` in its hook events; the main conversation has none, "main"
here). The plan names agents by what they do ("results-writer"); an id is tied to a name when it claims or publishes
under it. A marker's own `by: <name>` line says who owns it, whatever the claims say.

Kept in .git/research-diff/agents.json (never committed).
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Dict, List, Optional

from . import store

FILE = "agents.json"
MAX_MESSAGES = 500


def state(root: Path) -> dict:
    s = store.read(root, FILE, None) or {}
    for k, v in (("plan", {}), ("claims", {}), ("ids", {}), ("messages", []), ("read", {})):
        s.setdefault(k, v)
    return s


def save(root: Path, s: dict) -> None:
    s["messages"] = s["messages"][-MAX_MESSAGES:]
    store.write(root, FILE, s)


def owners(root: Path) -> Dict[str, str]:
    try:
        return dict(state(root)["claims"])
    except Exception:  # noqa: BLE001 - no repository, unreadable state: no owners
        return {}


def name_of(root: Path, agent_id: str = "") -> str:
    if not agent_id or agent_id == "main":
        return "main"
    return state(root)["ids"].get(agent_id, agent_id)


def tie(root: Path, agent_id: str, name: str) -> None:
    if agent_id and agent_id != "main" and name:
        s = state(root)
        if s["ids"].get(agent_id) != name:
            s["ids"][agent_id] = name
            save(root, s)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:28] or "agent"


def owner_of(bp: dict, s: dict, nid: str) -> str:
    return (bp["nodes"].get(nid, {}).get("by") or s["claims"].get(nid) or "").strip()


def claim(root: Path, name: str, ids: List[str], agent_id: str = "", bp: Optional[dict] = None) -> dict:
    """Claim nodes for an agent. Nodes another agent owns are not taken: they are returned, with their owner."""
    s = state(root)
    taken, mine = [], []
    for nid in ids:
        other = owner_of(bp, s, nid) if bp else s["claims"].get(nid, "")
        if other and other != name:
            taken.append({"id": nid, "owner": other})
        else:
            s["claims"][nid] = name
            mine.append(nid)
    if agent_id:
        s["ids"][agent_id] = name
    save(root, s)
    return {"claimed": mine, "owned by others": taken}


def release(root: Path, name: str, ids: Optional[List[str]] = None) -> List[str]:
    s = state(root)
    gone = [k for k, v in s["claims"].items() if v == name and (ids is None or k in ids)]
    for k in gone:
        del s["claims"][k]
    save(root, s)
    return gone


def publish(root: Path, frm: str, topic: str, text: str, auto: bool = False) -> int:
    s = state(root)
    n = (s["messages"][-1]["n"] + 1) if s["messages"] else 1
    s["messages"].append({"n": n, "at": round(time.time(), 1), "from": frm, "topic": topic, "text": text[:600],
                          "auto": auto})
    save(root, s)
    return n


def _upstream(edges: List[dict], ids: List[str]) -> List[str]:
    into: Dict[str, List[str]] = {}
    for e in edges:
        into.setdefault(e["to"], []).append(e["from"])
    seen, todo = set(ids), list(ids)
    while todo:
        for src in into.get(todo.pop(), []):
            if src not in seen:
                seen.add(src)
                todo.append(src)
    return sorted(seen - set(ids))


def _downstream(edges: List[dict], ids: List[str]) -> List[str]:
    return _upstream([{"from": e["to"], "to": e["from"]} for e in edges], ids)


def remember(root: Path, graph: dict) -> None:
    """Keep who owns what and the evidence edges, so the hooks can route messages without reading the research."""
    s = state(root)
    known = {"owners": {k: n["owner"] for k, n in graph["nodes"].items() if n.get("owner")},
             "edges": [[e["from"], e["to"]] for e in graph["edges"]]}
    if s.get("graph") != known:
        s["graph"] = known
        save(root, s)


def _cached(s: dict) -> Optional[dict]:
    g = s.get("graph")
    if not g:
        return None
    return {"nodes": {k: {"owner": v} for k, v in g["owners"].items()},
            "edges": [{"from": a, "to": b} for a, b in g["edges"]]}


def subscriptions(root: Path, name: str, graph: Optional[dict] = None) -> List[str]:
    """The topics an agent hears: the nodes it owns, the ones its plan says it watches, and everything upstream of
    what it owns in the evidence graph (and, for evidence it owns, what relies on it)."""
    s = state(root)
    graph = graph or _cached(s)
    owned = sorted(k for k, v in s["claims"].items() if v == name)
    if graph:
        owned += [k for k, n in graph["nodes"].items() if n.get("owner") == name and k not in owned]
    plan = next((a for a in s["plan"].get("agents", []) if a["name"] == name), {})
    topics = set(owned) | set(plan.get("watches", [])) | {"*"}
    if graph:
        topics |= set(_upstream(graph["edges"], owned)) | set(_downstream(graph["edges"], owned))
    return sorted(topics)


def inbox(root: Path, name: str, graph: Optional[dict] = None, mark: bool = True) -> List[dict]:
    """Unread messages on the topics an agent hears, not its own; marked read unless `mark` is False."""
    s = state(root)
    topics = set(subscriptions(root, name, graph))
    seen = s["read"].get(name, 0)
    got = [m for m in s["messages"] if m["n"] > seen and m["from"] != name
           and (m["topic"] in topics or m["topic"] == name)]
    if mark and s["messages"]:
        s["read"][name] = s["messages"][-1]["n"]
        save(root, s)
    return got


def as_context(msgs: List[dict]) -> str:
    if not msgs:
        return ""
    lines = [f"- [{m['topic']}] {m['from']}: {m['text']}" for m in msgs[-12:]]
    more = f" ({len(msgs) - 12} older not shown)" if len(msgs) > 12 else ""
    return "research-diff bus, messages for you" + more + ":\n" + "\n".join(lines)


def after_change(root: Path, who: str, d: dict, graph: dict) -> List[int]:
    """Publish what a change did, on the topics of the nodes it touched: the hooks call this after each edit. A new
    contradiction goes to the contradicted node's topic, naming both owners."""
    remember(root, graph)
    out = []
    for c in d["changes"]:
        if c["entity"] == "contradiction" and c["op"] == "add":
            src, dst = c["id"].split(" → ")
            so, do = graph["nodes"].get(src, {}).get("owner", ""), graph["nodes"].get(dst, {}).get("owner", "")
            text = f"CONTRADICTION: {c['label']}" + (f" ({src} is {so}'s, {dst} is {do}'s)" if so and do and so != do
                                                     else "")
            out.append(publish(root, who, dst, text, auto=True))
        elif c["entity"] == "verdict":
            out.append(publish(root, who, c["id"], c["label"] + (": " + "; ".join(c["detail"]) if c["detail"] else ""),
                               auto=True))
        elif c["entity"] in ("status", "metric", "title") or (c["entity"] in ("claim", "finding", "hypothesis",
                                                                              "result", "experiment")):
            topic = c["id"].split(" ", 1)[0]
            out.append(publish(root, who, topic, c["label"] + (f" ({c['detail'][0]})" if c["detail"] else ""),
                               auto=True))
    return out


def plan(root: Path, task: str, bp: dict, graph: dict, by: str = "section",
         agents: Optional[List[dict]] = None) -> dict:
    """Split the work into agents by the research's own parts and write each one's brief; the plan is saved and the
    nodes claimed. `by`: "section" (one agent per paper section: its claims and findings), "hypothesis" (one per
    hypothesis: it, the experiments testing it and their results), or `agents` given as [{"name", "ids"}]."""
    s = state(root)
    groups: List[dict] = []
    if agents:
        groups = [{"name": slug(a["name"]), "owns": list(a.get("ids", [])), "about": a.get("about", "")} for a in agents]
    elif by == "hypothesis":
        tests: Dict[str, List[str]] = {}
        for src, rel, dst in bp["links"]:
            if rel == "tests":
                tests.setdefault(dst, []).append(src)
        for nid, n in bp["nodes"].items():
            if n["kind"] != "hypothesis":
                continue
            exps = tests.get(nid, [])
            res = [k for k in bp["nodes"] for e in exps if k.startswith(e + ".")]
            res += [src for src, rel, dst in bp["links"] if rel == "of" and dst in exps and src not in res]
            groups.append({"name": slug(f"{nid}-{n['title'][:18]}"), "owns": [nid, *exps, *res],
                           "about": f"{nid}: {n['title']}"})
    else:
        secs: Dict[str, List[str]] = {}
        for nid, n in graph["nodes"].items():
            if n["role"] == "statement":
                secs.setdefault(n["section"] or "Paper", []).append(nid)
        for sec, ids in secs.items():
            groups.append({"name": slug(sec) + "-writer", "owns": ids, "about": f"the paper's {sec} section"})
    briefs = []
    for g in groups:
        g["watches"] = _upstream(graph["edges"], g["owns"])
        against = [x for st in graph["statements"] if st["id"] in g["owns"] for x in st["against"]]
        lines = [
            f"You are agent `{g['name']}`, one of a team working on this study ({task}).",
            f"You own: {', '.join(g['owns']) or 'nothing yet'}" + (f" ({g['about']})." if g["about"] else "."),
            f"Evidence your work relies on (others may own it): {', '.join(g['watches']) or 'none yet'}.",
        ]
        if against:
            lines.append("Open contradictions on what you own: " + "; ".join(x["why"] for x in against[:5]) + ".")
        lines += [
            f"Rules: write a `by: {g['name']}` line under every marker you add. Edit only what you own; call the "
            "`claim` tool before taking anything else. When a result of yours contradicts or weakens a node another "
            "agent owns, say so with a `contradicts:`/`weakens:` marker on your own node and `publish` it to that "
            "node's topic; never edit their claim yourself. Read what the bus tells you after each tool call and react "
            "to contradictions first. Record runs with `log_result` (agent: your name).",
        ]
        briefs.append({"name": g["name"], "owns": g["owns"], "watches": g["watches"], "brief": "\n".join(lines)})
    s["plan"] = {"task": task, "by": "agents" if agents else by, "at": round(time.time()), "agents": briefs}
    for b in briefs:
        for nid in b["owns"]:
            if not owner_of(bp, s, nid):
                s["claims"][nid] = b["name"]
    save(root, s)
    publish(root, "main", "*", f"Plan: {len(briefs)} agents for {task}: " + ", ".join(b["name"] for b in briefs),
            auto=True)
    return {"task": task, "agents": briefs,
            "how": "Start one subagent per agent with the Task tool, its brief as the prompt (add the task). They run "
                   "in parallel; the bus carries what each one changes to those whose work relies on it."}


def team(root: Path, graph: dict) -> List[dict]:
    """Every agent: what it owns, the verdicts of its statements, its unread count, and where it contradicts others."""
    s = state(root)
    names = [a["name"] for a in s["plan"].get("agents", [])]
    names += sorted({n["owner"] for n in graph["nodes"].values() if n["owner"]} - set(names))
    out = []
    for name in names:
        owned = [k for k, n in graph["nodes"].items() if n["owner"] == name]
        owned += [k for k, v in s["claims"].items() if v == name and k not in owned]
        verdicts: Dict[str, int] = {}
        for st in graph["statements"]:
            if st["id"] in owned:
                verdicts[st["verdict"]] = verdicts.get(st["verdict"], 0) + 1
        out.append({"name": name, "owns": owned, "verdicts": verdicts,
                    "unread": len(inbox(root, name, graph, mark=False)),
                    "contradicts": [c for c in graph["cross_agent"] if c["owners"][0] == name],
                    "contradicted_by": [c for c in graph["cross_agent"] if c["owners"][1] == name],
                    "ids": sorted(k for k, v in s["ids"].items() if v == name)})
    return out
