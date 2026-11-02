"""`research-diff mcp`: research-diff as an MCP server over stdio (extra: pip install "research-diff[mcp]").

research_map and research_diff read; log_result writes a result marker into the research log (a Markdown file in the
repository, so it is on the map, in git, and in the next diff); checkpoint marks what the person has understood."""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from system_diff.pictures import write_if_changed
from system_diff.sources import git, repo_root

from . import compare as cmp
from . import graph

try:  # the MCP SDK's 2.x name; 1.x called it FastMCP
    from mcp.server.mcpserver import MCPServer as Server
except ImportError:  # pragma: no cover
    from mcp.server.fastmcp import FastMCP as Server

INSTRUCTIONS = (
    "research-diff keeps a map of this research: questions (Q), hypotheses (H), experiments (E), results (R) and claims "
    "(C), from markers in the notes, configs, scripts and paper. After an iteration, call research_diff and tell the "
    "person what changed, from its plan only. Record an experiment's outcome with log_result. Call checkpoint only "
    "when the person says they have understood the current state."
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
    c = cmp.compare(root, base, head)
    svg = graph.diff_svg(c.diff, c.before, c.after, c.cfg)
    path = _out(root) / "diff.svg"
    if svg:
        write_if_changed(path, svg)
    elif path.is_file():
        path.unlink()
    return {"from": c.base, "headline": c.diff["headline"], "plan": c.diff["plan"], "changes": len(c.diff["changes"]),
            "warnings": c.diff["warnings"], "picture": str(path) if svg else None}


def tool_log(root: Path, experiment: str, metrics: Dict[str, float], title: str = "", supports: List[str] = (),
             weakens: List[str] = (), note: str = "", log: str = LOG) -> Dict[str, Any]:
    bp, _cfg, _ = cmp.read(root, ".")
    taken = [int(m.group(1)) for k in bp["nodes"] for m in [re.match(r"R(\d+)$", k)] if m]
    rid = f"R{max(taken, default=0) + 1}"
    lines = [f"## {rid}: {title or 'a run of ' + experiment} ({time.strftime('%Y-%m-%d')})", "", f"of: {experiment}",
             "metrics: " + ", ".join(f"{k}={v:g}" for k, v in metrics.items())]
    lines += [f"supports: {', '.join(supports)}"] if supports else []
    lines += [f"weakens: {', '.join(weakens)}"] if weakens else []
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
    def log_result(experiment: str, metrics: Dict[str, float], title: str = "", supports: Optional[List[str]] = None,
                   weakens: Optional[List[str]] = None, note: str = "") -> Dict[str, Any]:
        """Record what an experiment produced, as a result marker in research/log.md: its metrics, and the hypotheses
        or claims it supports or weakens. Only for a run that actually happened."""
        return tool_log(repo_root(), experiment, metrics, title, supports or [], weakens or [], note)

    @server.tool()
    def checkpoint(ref: str = "") -> Dict[str, Any]:
        """Mark the working tree (or `ref`) as understood by the person. Only when they say so."""
        sha = cmp.checkpoint(repo_root(), ref or None)
        return {"checkpoint": sha[:9]}

    return server


def main() -> None:
    build().run("stdio")
