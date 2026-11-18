"""research-diff on system-diff's workflow board (its Agents tab, and research-diff's own): auto-research's experiment
runs as steps (where each runs, its log), Claude's analysis of each iteration as a step that waits for that iteration's
runs, and the next iteration's runs waiting for the analysis; pause, resume and stop from the board; the agents Claude
can add to a research team from the chat; ready-made research workflows.

system-diff reads these from the extension module (system_diff_ext imports them): `workflow(ctx)`,
`workflow_action(ctx, id, action)`, `step_log(ctx, id)`, `WORKFLOW_KINDS`, `WORKFLOW_TEMPLATES`.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List

SHOWN = 3                   # the last iterations on the board
STALE = 24 * 3600           # a campaign that ended longer ago than this leaves the board
JOB_STATE = {"queued": "", "running": "running", "done": "done", "failed": "failed", "killed": "failed"}
PREFIX = "auto-"


def workflow(ctx) -> Dict[str, List[Dict[str, Any]]]:
    """Auto-research's steps and who waits for whom, for the board (nothing when no campaign ran lately)."""
    from . import autoresearch
    c = autoresearch.campaign(Path(ctx.root))
    if not c:
        return {"steps": [], "waits": []}
    live = c.get("state") in autoresearch.ACTIVE
    if not live and time.time() - float(c.get("updated") or c.get("created") or 0) > STALE:
        return {"steps": [], "waits": []}
    acts = ["pause", "stop"] if c.get("state") == "running" else ["resume", "stop"] if c.get("state") == "paused" else []
    steps: List[Dict[str, Any]] = []
    waits: List[Dict[str, str]] = []
    its = c.get("iterations") or []
    if c.get("ask") == "plan" and not its:
        steps.append({"id": PREFIX + "plan", "title": "Claude plans the first iteration", "kind": "agent",
                      "state": "running" if c.get("state") == "running" else "paused" if live else "",
                      "detail": str(c.get("goal") or "")[:200], "actions": acts})
    before = ""
    for it in its[-SHOWN:]:
        n = it.get("n")
        analysis = f"{PREFIX}analyse-{n}"
        for jid in it.get("jobs") or []:
            j = (c.get("jobs") or {}).get(jid) or {}
            sid = PREFIX + jid
            state = JOB_STATE.get(j.get("state"), "")
            if state == "" and c.get("state") == "paused":
                state = "paused"
            where = str(j.get("server") or "") + (f" GPU {','.join(map(str, j['gpus']))}" if j.get("gpus") else "")
            steps.append({"id": sid, "title": f"{j.get('experiment') or jid} · iteration {n}", "kind": "run",
                          "state": state, "detail": " · ".join(x for x in (where, str(j.get("why") or j.get("command")
                                                                                         or "")[:160]) if x),
                          "log": str(j.get("tail") or ""), "files": [str(f) for f in j.get("results") or []],
                          "actions": acts if live and state in ("", "running", "paused") else [],
                          "started": float(j.get("started") or 0), "finished": float(j.get("ended") or 0)})
            waits.append({"from": sid, "to": analysis, "why": "the analysis reads every run of the iteration"})
            if before:
                waits.append({"from": before, "to": sid, "why": "planned from the last iteration's analysis"})
        state = {"running": "", "analyse": "running" if c.get("state") == "running" else "paused" if live else "",
                 "analysed": "done"}.get(it.get("state"), "")
        steps.append({"id": analysis, "title": f"Claude analyses iteration {n}", "kind": "agent", "state": state,
                      "detail": str(it.get("analysis") or it.get("reason") or "")[:200],
                      "actions": acts if state in ("running", "paused") else [],
                      "started": float(it.get("ended") or 0), "finished": 0.0})
        before = analysis
    return {"steps": steps, "waits": waits}


def workflow_action(ctx, sid: str, action: str) -> Dict[str, Any]:
    """Pause, resume or stop from one of auto-research's steps: the whole campaign (its runs share the servers)."""
    from . import autoresearch
    if not str(sid).startswith(PREFIX):
        return {"ok": False, "said": f"no such step of research-diff's: {sid}"}
    if action not in ("pause", "resume", "stop"):
        return {"ok": False, "said": f"auto-research can be paused, resumed or stopped, not {action}"}
    try:
        c = autoresearch.control(Path(ctx.root), action)
    except ValueError as exc:
        return {"ok": False, "said": str(exc)}
    return {"ok": True, "said": f"auto-research is {c.get('state')} (the whole campaign: its runs share the servers)"}


def step_log(ctx, sid: str) -> Dict[str, Any]:
    """One step's story for the board's pop-up: a run's events, its command and its log; an analysis's reason and
    what it found."""
    from . import autoresearch
    c = autoresearch.campaign(Path(ctx.root))
    sid = str(sid)
    if sid.startswith(PREFIX + "analyse-"):
        n = sid.rsplit("-", 1)[-1]
        it = next((x for x in c.get("iterations") or [] if str(x.get("n")) == n), {})
        entries = [{"at": float(it.get("started") or 0), "kind": "prompt",
                    "text": "What this iteration changed, and why: " + str(it.get("reason") or "(not said)")}]
        if it.get("analysis"):
            entries.append({"at": float(it.get("ended") or 0), "kind": "text", "text": str(it["analysis"])})
        return {"entries": entries, "about": f"Iteration {n} of: {c.get('goal', '')}"}
    if sid == PREFIX + "plan":
        return {"entries": [{"at": float(c.get("created") or 0), "kind": "prompt", "text": str(c.get("goal") or "")}],
                "about": "Claude plans the first iteration from the goal"}
    jid = sid[len(PREFIX):]
    j = (c.get("jobs") or {}).get(jid)
    if not j:
        return {"entries": [{"at": time.time(), "kind": "text", "text": f"no run {jid} in the campaign"}], "about": ""}
    entries = [{"at": float(e.get("at") or 0), "kind": "text", "text": str(e.get("text") or "")}
               for e in c.get("events") or [] if str(e.get("text") or "").startswith(jid + " ")]
    entries.append({"at": float(j.get("started") or 0), "kind": "tool", "name": "run", "text": str(j.get("command"))})
    entries += [{"at": float(j.get("ended") or 0), "kind": "text", "text": line}
                for line in str(j.get("tail") or "").splitlines()[-200:] if line.strip()]
    return {"entries": entries, "about": f"{j.get('experiment')} on {j.get('server') or 'a server'}: "
                                         f"{j.get('command')}" + (f" ({j['why']})" if j.get("why") else "")}


# Agents Claude can add to a research team from the chat (system-diff's add_agent).
WORKFLOW_KINDS = [
    {"kind": "experiment-runner", "title": "Experiment runner",
     "brief": "Runs the experiments it is given (each one's `run:` command), checks its results file is written, and "
              "logs the numbers with log_result. It does not edit the paper."},
    {"kind": "results-analyst", "title": "Results analyst",
     "brief": "Reads the new results and writes under each which hypotheses and claims it supports, weakens or "
              "contradicts (supports: / weakens: / contradicts:), and what is worth running next."},
    {"kind": "section-writer", "title": "Section writer",
     "brief": "Writes or updates one section of the paper from the evidence: each claim with its marker and what backs "
              "it (relies on: / supported by:), numbers copied from the results files, nothing the evidence does not "
              "show."},
    {"kind": "contradiction-reviewer", "title": "Contradiction reviewer",
     "brief": "Checks the paper against itself and its results (research_evidence, review_paper): claims that "
              "contradict each other across sections, numbers out of date, claims bigger than their evidence; fixes "
              "or flags each, with the file and line."},
]

# Ready-made research workflows, offered beside the saved ones where research-diff applies.
WORKFLOW_TEMPLATES = [
    {"name": "experiments-then-paper",
     "description": "Run the experiments in parallel, analyse what came out, update the sections the results touch, "
                    "then check the paper against itself and its results.",
     "agents": [
         {"name": "experiment-runner", "area": "the experiments the task names: run each, log its results"},
         {"name": "results-analyst", "area": "what the new results support, weaken or contradict",
          "waits_for": ["experiment-runner"]},
         {"name": "section-writer", "area": "the paper's sections the new results touch",
          "waits_for": ["results-analyst"]},
         {"name": "contradiction-reviewer", "area": "the whole paper, against itself and its results",
          "waits_for": ["section-writer"]}],
     "steps": [], "waits": []},
    {"name": "review-the-paper",
     "description": "Before sending the paper: find claims that contradict each other, numbers out of date and claims "
                    "bigger than their evidence, then fix them section by section.",
     "agents": [
         {"name": "contradiction-reviewer", "area": "the whole paper, against itself and its results"},
         {"name": "section-writer", "area": "the sections the review flags", "waits_for": ["contradiction-reviewer"]}],
     "steps": [], "waits": []},
]
