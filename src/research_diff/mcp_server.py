"""`research-diff mcp`: research-diff as an MCP server over stdio (extra: pip install "research-diff[mcp]").

research_map, research_diff, research_evidence and explain read; log_result writes a result marker into the research
log (a Markdown file in the repository, so it is on the map, in git, and in the next diff); checkpoint marks what the
person has understood. For teams of agents: plan_agents, claim, publish and inbox (agents.py). objectives lists, adds
and clears what the person optimises the study for."""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from system_diff.pictures import write_if_changed
from system_diff.sources import git, repo_root

from . import agents, evgraph, evidence, objectives
from . import compare as cmp
from . import graph

try:  # the MCP SDK's 2.x name; 1.x called it FastMCP
    from mcp.server.mcpserver import MCPServer as Server
except ImportError:  # pragma: no cover
    from mcp.server.fastmcp import FastMCP as Server

INSTRUCTIONS = (
    "research-diff keeps a map of this research: questions (Q), hypotheses (H), experiments (E), results (R), findings "
    "(F) and claims (C), from markers in the notes, configs, scripts and paper, and an evidence graph of which evidence "
    "supports or contradicts each claim and finding of the paper. After an iteration, call research_diff and tell the "
    "person what changed, from its plan only, contradictions first. research_evidence and explain say what backs or "
    "contradicts a statement. Record an experiment's outcome with log_result. For work across the study, plan_agents "
    "splits it into agents; each agent claims its nodes, publishes what it changes and reads its inbox. Call "
    "checkpoint only when the person says they have understood the current state."
)
LOG = "research/log.md"


def _out(root: Path) -> Path:
    d = Path(git("rev-parse", "--absolute-git-dir", cwd=root).strip()) / "research-diff" / "mcp"
    d.mkdir(parents=True, exist_ok=True)
    return d


def tool_map(root: Path, at: str = ".") -> Dict[str, Any]:
    bp, cfg, label = cmp.read(root, at)
    path = _out(root) / "research.svg"
    write_if_changed(path, graph.map_svg(bp, cfg))
    return {"of": label, "picture": str(path), "warnings": bp["warnings"],
            "nodes": [{"id": k, "kind": n["kind"], "title": n["title"], "status": n["status"], "metrics": n["metrics"]}
                      for k, n in bp["nodes"].items()],
            "links": [" ".join(x) for x in bp["links"]]}


def tool_diff(root: Path, base: str = "checkpoint", head: str = ".") -> Dict[str, Any]:
    if head == ".":
        cmp.sync_trackers(root)
    c = cmp.compare(root, base, head)
    svg = graph.diff_svg(c.diff, c.before, c.after, c.cfg)
    path = _out(root) / "diff.svg"
    if svg:
        write_if_changed(path, svg)
    elif path.is_file():
        path.unlink()
    return {"from": c.base, "headline": c.diff["headline"], "plan": c.diff["plan"], "changes": len(c.diff["changes"]),
            "warnings": c.diff["warnings"], "picture": str(path) if svg else None}


def tool_evidence(root: Path, at: str = ".") -> Dict[str, Any]:
    g, _bp, cfg = cmp.evidence_of(root, at)
    d = _out(root)
    write_if_changed(d / "evidence.svg", evgraph.svg(g))
    write_if_changed(d / "evidence.html", evgraph.standalone(g))
    return {"headline": g["headline"], "statements": [{k: s[k] for k in ("id", "title", "verdict", "section", "owner")}
                                                      | {"for": [x["why"] for x in s["for"]],
                                                         "against": [x["why"] for x in s["against"]]}
                                                      for s in g["statements"]],
            "the paper contradicts itself": [c["why"] for c in g["conflicts"]],
            "across agents": [f"{c['why']} ({c['owners'][0]} → {c['owners'][1]})" for c in g["cross_agent"]],
            "picture": str(d / "evidence.svg"), "page": str(d / "evidence.html"), "mermaid": evgraph.mermaid(g)}


def tool_explain(root: Path, node: str = "") -> Dict[str, Any]:
    from . import activity, history
    g, bp, _cfg = cmp.evidence_of(root)
    if not node:
        f = activity.focus(root, bp)
        node = f[0] if f else ""
    n = bp["nodes"].get(node)
    if not n:
        return {"error": f"{node or 'nothing'} is not on the map", "ids": list(bp["nodes"])}
    gn = g["nodes"].get(node, {})
    return {"id": node, "kind": n["kind"], "title": n["title"], "status": n["status"], "files": n["files"],
            "metrics": n["metrics"], "section": n.get("section", ""), "owner": gn.get("owner", ""),
            "verdict": gn.get("verdict", ""), "evidence": evidence.chain(g, node),
            "backs or contradicts": [e["why"] for e in g["edges"] if e["from"] == node],
            "links": [" ".join(x) for x in bp["links"] if node in (x[0], x[2])],
            "history": [e["headline"] for e in history.load(root, node, 5)]}


def tool_log(root: Path, experiment: str, metrics: Dict[str, float], title: str = "", supports: List[str] = (),
             weakens: List[str] = (), note: str = "", log: str = LOG, contradicts: List[str] = (),
             agent: str = "") -> Dict[str, Any]:
    bp, _cfg, _ = cmp.read(root, ".")
    taken = [int(m.group(1)) for k in bp["nodes"] for m in [re.match(r"R(\d+)$", k)] if m]
    rid = f"R{max(taken, default=0) + 1}"
    lines = [f"## {rid}: {title or 'a run of ' + experiment} ({time.strftime('%Y-%m-%d')})", "", f"of: {experiment}",
             "metrics: " + ", ".join(f"{k}={v:g}" for k, v in metrics.items())]
    lines += [f"supports: {', '.join(supports)}"] if supports else []
    lines += [f"weakens: {', '.join(weakens)}"] if weakens else []
    lines += [f"contradicts: {', '.join(contradicts)}"] if contradicts else []
    lines += [f"by: {agent}"] if agent else []
    lines += ["", note] if note else []
    path = root / log
    path.parent.mkdir(parents=True, exist_ok=True)
    before = path.read_text(encoding="utf-8") if path.is_file() else "# Research log\n\nResults, newest last. Written by research-diff's log_result.\n"
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(before.rstrip("\n") + "\n\n" + "\n".join(lines) + "\n")
    return {"recorded": rid, "in": log}


def build() -> Server:
    server = Server("research-diff", instructions=INSTRUCTIONS)

    @server.tool()
    def research_map(at: str = ".") -> Dict[str, Any]:
        """Every question, hypothesis, experiment, result and claim, their statuses, metrics and links, the open
        warnings, and the picture's path. `at`: a commit, or "." for the working tree."""
        return tool_map(repo_root(), at)

    @server.tool()
    def research_diff(base: str = "checkpoint", head: str = ".") -> Dict[str, Any]:
        """What changed in the research from `base` ("checkpoint": what the person last marked as understood) to
        `head` ("." the working tree): one sentence, the exact plan, new warnings and the picture's path."""
        return tool_diff(repo_root(), base, head)

    @server.tool()
    def research_evidence(at: str = ".") -> Dict[str, Any]:
        """The evidence graph: every claim and finding of the paper with its verdict (supported, contested,
        contradicted, unsupported), what supports it and what contradicts it, where the paper contradicts itself and
        where one agent's work contradicts another's; the picture's and the interactive page's paths, and Mermaid."""
        return tool_evidence(repo_root(), at)

    @server.tool()
    def explain(node: str = "") -> Dict[str, Any]:
        """One node (empty: the one being worked on): what it is, its verdict, its evidence chain down to the numbers,
        what it backs or contradicts, and its history."""
        return tool_explain(repo_root(), node)

    @server.tool()
    def log_result(experiment: str, metrics: Dict[str, float], title: str = "", supports: Optional[List[str]] = None,
                   weakens: Optional[List[str]] = None, note: str = "", contradicts: Optional[List[str]] = None,
                   agent: str = "") -> Dict[str, Any]:
        """Record what an experiment produced, as a result marker in research/log.md: its metrics, and the hypotheses,
        findings or claims it supports, weakens or contradicts; `agent`: who ran it. Only for a run that actually
        happened. Report a contradiction as one: never leave it out."""
        return tool_log(repo_root(), experiment, metrics, title, supports or [], weakens or [], note,
                        contradicts=contradicts or [], agent=agent)

    @server.tool()
    def plan_agents(task: str, by: str = "section", team: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Split work across the study into a team of agents, one per paper section (by="section"), per hypothesis
        (by="hypothesis"), or as given (team=[{"name", "ids", "about"}]). Each gets a brief: what it owns, the
        evidence it relies on, the open contradictions on its nodes, and the rules. Start one subagent per brief."""
        root = repo_root()
        g, bp, _cfg = cmp.evidence_of(root)
        return agents.plan(root, task, bp, g, by, team)

    @server.tool()
    def claim(name: str, ids: List[str]) -> Dict[str, Any]:
        """Claim nodes for agent `name` before working on them. Nodes another agent owns are not taken: ask it on the
        bus (publish to the node's topic) instead."""
        root = repo_root()
        bp, _cfg, _ = cmp.read(root, ".")
        return agents.claim(root, name, ids, bp=bp)

    @server.tool()
    def publish(name: str, topic: str, text: str) -> Dict[str, Any]:
        """Tell the agents that rely on a node (`topic`: its id, an agent's name, or "*" for everyone) what you did or
        found, e.g. that your result contradicts their claim."""
        return {"message": agents.publish(repo_root(), name, topic, text)}

    @server.tool()
    def inbox(name: str) -> Dict[str, Any]:
        """Agent `name`'s unread messages on the topics it hears (the nodes it owns and the evidence they rely on)."""
        root = repo_root()
        g, _bp, _cfg = cmp.evidence_of(root)
        return {"messages": agents.inbox(root, name, g)}

    @server.tool()
    def research_objectives(add: str = "", clear: str = "") -> Dict[str, Any]:
        """What the person optimises this study for (learned from their requests, or added by them). `add` one they
        state; `clear` one by id only when they say it is wrong."""
        root = repo_root()
        if add:
            objectives.add(root, add)
        if clear:
            objectives.clear(root, clear)
        return {"objectives": objectives.current(root)}

    @server.tool()
    def checkpoint(ref: str = "") -> Dict[str, Any]:
        """Mark the working tree (or `ref`) as understood by the person. Only when they say so."""
        sha = cmp.checkpoint(repo_root(), ref or None)
        return {"checkpoint": sha[:9]}

    return server


def main() -> None:
    build().run("stdio")
