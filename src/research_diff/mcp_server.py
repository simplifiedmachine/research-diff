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
    "splits it into agents; each agent claims its nodes, publishes what it changes and reads its inbox. "
    "paper_outline shows the paper section by section with every number checked against the results, and "
    "review_paper where the paper contradicts itself: keep experiments, results and claims hand in hand. When "
    "explaining, point_to the nodes you name. When auto-research is on, autoresearch_status says what is asked of "
    "you: analyse each iteration and autoresearch_submit the next. Call checkpoint only when the person says they have understood the "
    "current state."
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


class _Named:
    """A server whose tools take a prefix: research-diff's tools inside system-diff's own MCP server are
    `research_explain`, `research_checkpoint`, ... beside system-diff's `explain`, `checkpoint`."""

    def __init__(self, server, prefix: str = ""):
        self._server, self._prefix = server, prefix

    def tool(self, **kw):
        def deco(fn):
            name = fn.__name__ if not self._prefix or fn.__name__.startswith(self._prefix) else self._prefix + fn.__name__
            return self._server.tool(name=name, **kw)(fn)
        return deco


def build() -> Server:
    """research-diff's own MCP server (`research-diff mcp`)."""
    server = Server("research-diff", instructions=INSTRUCTIONS)
    register(server)
    return server


def register(target, prefix: str = ""):
    """Every research-diff tool, on `target`: its own server, or system-diff's (system_diff_ext.mcp, prefixed)."""
    server = _Named(target, prefix)

    @_read_only(server)
    def research_map(at: str = ".") -> Dict[str, Any]:
        """Every question, hypothesis, experiment, result and claim, their statuses, metrics and links, the open
        warnings, and the picture's path. `at`: a commit, or "." for the working tree."""
        return tool_map(repo_root(), at)

    @_read_only(server)
    def research_diff(base: str = "checkpoint", head: str = ".") -> Dict[str, Any]:
        """What changed in the research from `base` ("checkpoint": what the person last marked as understood) to
        `head` ("." the working tree): one sentence, the exact plan, new warnings and the picture's path."""
        return tool_diff(repo_root(), base, head)

    @_read_only(server)
    def research_evidence(at: str = ".") -> Dict[str, Any]:
        """The evidence graph: every claim and finding of the paper with its verdict (supported, contested,
        contradicted, unsupported), what supports it and what contradicts it, where the paper contradicts itself and
        where one agent's work contradicts another's; the picture's and the interactive page's paths, and Mermaid."""
        return tool_evidence(repo_root(), at)

    @_read_only(server)
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

    @_read_only(server)
    def paper_outline(path: str = "") -> Dict[str, Any]:
        """The paper (or a notes file; empty: the first paper file) section by section: each section's statements
        with their verdicts, its tables and figures, every number it prints checked against the results (✓ matches,
        ✗ stale, with why), and your LLM's summary of the section when one is kept (✦). Use it to check that the
        experiments, results and claims of the paper go hand in hand, and before editing a section."""
        from . import paperview
        root = repo_root()
        g, bp, _cfg = cmp.evidence_of(root)
        files = paperview.research_files(bp)
        path = path or (files[0] if files else "")
        if path not in files:
            return {"error": f"{path or 'no file'} is not a research file", "files": files}
        o = paperview.outline(root, path, bp, g)
        o.pop("lines", None)
        for c in o["chunks"]:
            c.pop("text", None)
        return o

    @server.tool()
    def review_paper(run: bool = False) -> Dict[str, Any]:
        """The LLM review of the paper against itself and its results: where one section contradicts another, where
        text and numbers disagree, where a claim says more than its evidence; every quote checked against the paper.
        `run`: review now (slow: it asks an LLM) instead of returning the last review. Fix what it finds in the paper
        or record it as `contradicts:` markers; do not dismiss a finding without saying why."""
        from . import review
        root = repo_root()
        return review.run(root) if run else (review.current(root) or {"findings": [], "why": "no review yet"})

    @server.tool()
    def point_to(ids: List[str], note: str = "") -> Dict[str, Any]:
        """Point at nodes of the research (claims, findings, results, tables, `tab:main`) on the person's
        research-diff web page: they light up in its evidence graph at once. Use it whenever you explain where the
        research or the paper stands, as you name each node. At most 12; each call replaces the last."""
        from . import chat
        rec = chat.point(repo_root(), ids, note)
        return {"pointing_at": rec["ids"], "shown": "the research-diff web page lights these now"}

    @server.tool()
    def note(node: str, text: str) -> Dict[str, Any]:
        """Keep a short finding (at most ~300 characters) beside one node, shown on its card and when the person
        zooms in on it: a weakness of a claim, a check still to run, a number to update in the paper."""
        from . import chat
        root = repo_root()
        if node not in cmp.read(root, ".")[0]["nodes"]:
            return {"error": f"{node} is not on the map"}
        return chat.add_note(root, node, text)

    @_read_only(server)
    def saved_agents() -> Dict[str, Any]:
        """The subagents saved for this project (.claude/agents) and for the person (~/.claude/agents), with how
        often each role was planned and finished; and the roles worth keeping that are not saved yet (they came back,
        or a standing role such as a reviewer or tester finished its work). Start a saved one by its name."""
        root = repo_root()
        return {"saved": agents.library(root), "worth keeping": agents.worth_keeping(root)}

    @server.tool()
    def save_agent(name: str, description: str, prompt: str, tools: str = "", model: str = "",
                   scope: str = "project") -> Dict[str, Any]:
        """Save an agent as a Claude Code subagent, so later sessions and teams reuse it: when its role is not a
        one-off (saved_agents lists those worth keeping) or the person asks. `description` says when to use it;
        `prompt` is its standing instructions (general, not this task's details); `tools` e.g. "Read, Grep, Bash";
        `scope` "project" (.claude/agents, shared through git) or "user". Tell the person what you saved."""
        try:
            return agents.save_agent(repo_root(), name, description, prompt, tools, model, scope)
        except ValueError as exc:
            return {"error": str(exc)}

    @_read_only(server)
    def autoresearch_status() -> Dict[str, Any]:
        """Auto-research: the campaign (goal, target, budget, state), each iteration's experiments on the servers'
        GPUs with their state and the tail of their logs, and what is asked of you now (`pending`)."""
        from . import autoresearch as ar
        root = repo_root()
        st = ar.status(root)
        return {"text": ar.as_text(root), "pending": st["pending"], "state": st["campaign"].get("state", "off"),
                "servers": [s["name"] for s in st["servers"]], "runner": st["runner"]}

    @server.tool()
    def autoresearch_submit(experiments: List[Dict[str, Any]], reason: str, analysis: str = "") -> Dict[str, Any]:
        """The next auto-research iteration, after you made the changes it needs (configs, code): `experiments`
        [{"experiment": "E2", "command"?: overrides its `run:`, "gpus"?: how many (default 1), "server"?: a name}];
        `reason`: what you changed and why; `analysis`: what the last iteration's results showed (numbers, verdicts,
        contradictions). The runner launches them on free GPUs and asks you again when they end."""
        from . import autoresearch as ar
        root = repo_root()
        try:
            c = ar.submit(root, experiments, reason, analysis)
        except ValueError as exc:
            return {"error": str(exc)}
        return {"iteration": len(c["iterations"]), "jobs": c["iterations"][-1]["jobs"],
                "left": c["max_iterations"] - len(c["iterations"])}

    @server.tool()
    def autoresearch_finish(summary: str) -> Dict[str, Any]:
        """End auto-research: the goal is met, or it cannot be from here. `summary`: what was found, with the numbers,
        and what the paper should now say."""
        from . import autoresearch as ar
        try:
            ar.finish(repo_root(), summary)
        except ValueError as exc:
            return {"error": str(exc)}
        return {"done": True}

    @server.tool()
    def autoresearch_control(action: str) -> Dict[str, Any]:
        """pause, resume or stop auto-research: ONLY when the person asks for it."""
        from . import autoresearch as ar
        try:
            c = ar.control(repo_root(), action)
        except ValueError as exc:
            return {"error": str(exc)}
        return {"state": c["state"]}

    return target


def _read_only(server):
    """@server.tool(), marked as only reading (permission modes can run it without asking); plain with an MCP SDK too
    old for annotations."""
    try:
        from mcp.types import ToolAnnotations
        hints = ToolAnnotations.model_validate({"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True,
                                                "openWorldHint": False})
        return server.tool(annotations=hints)
    except (ImportError, TypeError):
        return server.tool()


def main() -> None:
    build().run("stdio")
