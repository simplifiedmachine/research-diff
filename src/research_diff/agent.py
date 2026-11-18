"""Claude Code: `research-diff hook`, which its hooks run, and `research-diff setup claude`, which wires them in with the
status line, a skill on when to show the research diff and the evidence, and the MCP server. The hooks never block
and never fail a turn; setup prints each change, and `--undo` takes it back.

  SessionStart      starts the web page; tells Claude where the evidence stands (contradictions first), the person's
                    objectives and the agents' plan
  UserPromptSubmit  keeps the working tree as the start of the turn and the request in the activity log; the
                    objectives; learning them again in the background when enough is new
  PostToolUse       notes what was read or edited, by which agent; after an edit or a command that changed the
                    research, publishes what it did on the bus (a contradiction to the owner of what it contradicts)
                    and says in one line when a statement's verdict moved; hands each agent its unread messages
  Stop              one line on what the research changed since the checkpoint; the turn into the history
  SubagentStop      what that agent's work did to the research, on the bus and into the history
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, List, Optional

from system_diff.sources import git

from . import activity, agents, compare, evidence, objectives, rank, store
from .compare import sync_trackers
from .diff import diff

NAME = "research-diff"
SKILL_MARK = "<!-- written by research-diff setup claude -->"
SKILL = f"""---
name: research-diff
description: Shows the person what an iteration did to their research (questions, hypotheses, experiments, results, findings, claims) and which evidence supports or contradicts each claim of the paper. Use after running an experiment, changing a hypothesis, notes, a config or the paper, before asking them to review, when they ask where the research stands, or when several agents work on one study.
---
{SKILL_MARK}

# Showing the research diff and the evidence

The research is described by markers in the repository's own files: `H2: title` with `status:`, `tests:`,
`supports:`, `weakens:`, `contradicts:`, `relies on:`, `supported by:`, `contradicted by:`, `expects:` and `by:` lines
in notes, `% C1: …` and `% F1: …` (claims and findings) in the paper, a `research:` block or a
`# research-diff: E5 tests H2` comment in experiment configs and scripts.

1. When you add an idea, an experiment, a finding or a claim, write its marker, so it is on the map. When a result
   speaks against a statement, say so with `contradicts:` or `weakens:`: never hide it.
2. After running an experiment, record what came out with the `log_result` tool, or as a results file the
   experiment's `research:` block names.
3. Call `research_diff` and tell the person, in two or three plain sentences built only from its plan, what changed.
   Contradictions first: a claim now contested or contradicted, the paper contradicting itself.
4. When they ask what supports a claim, or what contradicts the paper, call `research_evidence` (or `explain` for one
   node) and point them at the picture, the pane (`/research-diff`) or the web page.
5. For work across the study, `plan_agents` splits it into one agent per paper section or hypothesis; start one
   subagent per brief. Each agent claims its nodes, writes `by: <name>`, and reads the bus after each tool call.
6. When they say they have understood it, call `checkpoint`, so the next diff shows only what is new to them.

Never report a result the plan does not show, and never mark a hypothesis supported or refuted without their say.
"""
SCOPES = ("user", "project", "local")
EVENTS = {"SessionStart": 10, "UserPromptSubmit": 10, "PostToolUse": 20, "Stop": 30, "SubagentStop": 30}
EDITS = ("Edit", "Write", "MultiEdit", "NotebookEdit")


def _is_repo(cwd: Path) -> bool:
    try:
        git("rev-parse", "--git-dir", cwd=cwd)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(data, indent=2) + "\n")


def _split(cmd: str) -> list:
    return shlex.split(cmd, posix=os.name != "nt")


def _claude(args: list) -> subprocess.CompletedProcess:
    return subprocess.run(["claude", *args], capture_output=True, text=True, timeout=60)


def hook_message(root: Path) -> Optional[str]:
    sync_trackers(root)   # runs logged to MLflow or W&B during the turn count too
    c = compare.compare(root, "checkpoint", ".")
    if not c.diff["changes"]:
        return None
    return f"Research diff since {c.base}: {c.diff['headline']} (`research-diff watch` shows the picture.)"


def _context(event: str, text: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}


def where_it_stands(root: Path) -> str:
    g, _bp, _cfg = compare.evidence_of(root)
    agents.remember(root, g)
    lines = [f"research-diff: {g['headline']}"]
    bad = [s for s in g["statements"] if s["verdict"] in ("contradicted", "contested")]
    for s in bad[:5]:
        lines.append(f"- {s['id']} is {s['verdict']}: " + "; ".join(x["why"] for x in s["against"][:2]))
    plan = agents.state(root)["plan"]
    if plan:
        lines.append(f"Agents' plan: {plan['task']} ({', '.join(a['name'] for a in plan['agents'])}).")
    obj = objectives.context(root)
    return "\n".join(lines + ([obj] if obj else []))


def after_change(root: Path, who: str) -> Optional[str]:
    """Compare the research with how the hooks last saw it; publish what changed; one line when it matters."""
    bp, cfg, _ = compare.read(root, ".")
    last = store.read(root, "last.json")
    if last is None:
        last, _c, _l = compare.read(root, "turn")
    store.write(root, "last.json", bp)
    d = diff(last, bp, cfg)
    if not d["changes"]:
        return None
    g = evidence.build(bp, cfg, agents.owners(root))
    agents.after_change(root, who, d, g)
    loud = [c for c in d["changes"] if c["entity"] in ("verdict", "contradiction") and c["op"] != "remove"]
    if not loud:
        return None
    return "Research evidence: " + "; ".join(c["label"] for c in loud[:3]) + \
        (f" (+{len(loud) - 3} more)" if len(loud) > 3 else "")


# ── the heavy part of each hook, off the hook's clock ──────────────────────────────────────────────────────────────
# A hook must answer in well under a second, whatever the repository's size (Claude Code gives up after its timeout,
# 10 s for a prompt). So a hook only notes what happened and hands the reading of the research to a worker of its own
# (`research-diff hook-bg EVENT`, detached), one per event at a time: a hook that comes while one works marks it to run
# again with the newest payload. What the worker finds for the chat (a verdict that moved) waits in notices.jsonl and
# comes with the next hook's answer. Tests and RESEARCH_DIFF_HOOK_SYNC=1 run it in the hook itself.

def _sync() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("RESEARCH_DIFF_HOOK_SYNC"))


def background(root: Path, event: str, payload: dict) -> None:
    store.write(root, f"bg-{event}.json", payload)
    if _sync():
        work(root, event)
        return
    pid_file = store.home(root) / f"bg-{event}.pid"
    try:
        pid = int(pid_file.read_text().strip() or 0)
    except (OSError, ValueError):
        pid = 0
    from .autoresearch import _alive
    if pid and _alive(pid) and time.time() - pid_file.stat().st_mtime < 600:
        (store.home(root) / f"bg-{event}.again").write_text("1")      # it runs: once more, with this payload
        return
    flags = {"start_new_session": True} if os.name != "nt" else {"creationflags": 0x08000000 | 0x00000200}
    try:
        subprocess.Popen([sys.executable, "-m", "research_diff", "--repo", str(root), "hook-bg", event],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=str(root),
                         **flags)
    except OSError:
        pass


def run_background(root: Path, event: str) -> int:
    """The worker: the event's work, again while hooks asked for it meanwhile."""
    home = store.home(root)
    pid_file, again = home / f"bg-{event}.pid", home / f"bg-{event}.again"
    pid_file.write_text(str(os.getpid()))
    try:
        while True:
            try:
                again.unlink()
            except OSError:
                pass
            work(root, event)
            if not again.exists():
                break
    finally:
        try:
            pid_file.unlink()
        except OSError:
            pass
    return 0


def notice(root: Path, text: str) -> None:
    store.append(root, "notices.jsonl", {"text": text})


def take_notices(root: Path) -> List[str]:
    got = [n["text"] for n in store.lines(root, "notices.jsonl")]
    if got:
        try:
            (store.home(root) / "notices.jsonl").unlink()
        except OSError:
            pass
    return got


def work(root: Path, event: str) -> None:
    """The heavy part of one hook. Never raises."""
    p = store.read(root, f"bg-{event}.json", {}) or {}
    try:
        if event == "prompt":
            compare.mark_turn(root)
            store.write(root, "last.json", compare.read(root, ".")[0])
        elif event == "tool":
            if p.get("tool") == "Bash":
                sync_trackers(root)
            said = after_change(root, p.get("who", "main"))
            if said:
                notice(root, said)
        elif event == "start":
            store.write(root, "stands.json", {"text": where_it_stands(root), "at": time.time()})
        elif event in ("stop", "substop"):
            _stop_work(root, p, subagent=event == "substop")
    except Exception:  # noqa: BLE001 - a worker that fails leaves the session as it was
        pass


def _stop_work(root: Path, p: dict, subagent: bool) -> None:
    from . import history
    who = p.get("who", "main")
    if not subagent:
        msg = hook_message(root)
        if msg:
            notice(root, msg)
    c = compare.compare(root, "turn", ".")
    if c.diff["changes"]:
        by = sorted(activity.edited_since(root, 0).keys())[-5:] if subagent else []
        from system_diff.compare import snapshot
        history.record(root, history.entry(c.diff, c.after, "turn", activity.last_request(root),
                                           by=[who] if subagent else by, base=compare.resolve(root, "turn")[0],
                                           head=snapshot(root)))
        paper_files = {x["path"] for x in c.after.get("paper", [])}
        began = (activity.requests(root, 1) or [{"at": 0}])[-1].get("at", 0)
        if not subagent and any(f in paper_files for fs in activity.edited_since(root, began).values() for f in fs):
            from . import review
            review.ensure(root)       # the paper changed this turn: read it against itself again
        if subagent:
            agents.publish(root, who, "*", f"finished: {c.diff['headline']}", auto=True)
    g = evidence.build(c.after, c.cfg, agents.owners(root))
    agents.remember(root, g)
    activity.write_state(root, headline=c.diff["headline"], evidence=g["headline"],
                         contradictions=sum(1 for e in g["edges"] if e["effective"] in ("-", "?")),
                         focus=list(activity.focus(root, c.after) or []),
                         worth=[x["title"] for x in rank.worth_a_look(c.diff, c.after, 2)])


# ── the hooks: each notes what happened, hands the reading on, and answers at once ─────────────────────────────────

def _with_notices(root: Path, out: dict) -> dict:
    said = take_notices(root)
    if said:
        out["systemMessage"] = " · ".join(said[-3:])
    return out


def on_tool(root: Path, p: dict) -> dict:
    tool, inp = p.get("tool_name", ""), p.get("tool_input") or {}
    agent_id = p.get("agent_id") or "main"
    who = agents.name_of(root, agent_id)
    path = inp.get("file_path") or inp.get("notebook_path") or ""
    rel = activity.relative(root, path) if path else ""
    if tool in EDITS and rel:
        activity.record(root, "edit", path=rel, agent=who)
    elif tool == "Read" and rel:
        activity.record(root, "read", path=rel, agent=who, line=inp.get("offset"))
    if tool in EDITS or tool == "Bash" or tool.startswith("mcp__research-diff"):
        background(root, "tool", {"tool": tool, "who": who})
    out = _with_notices(root, {})
    msgs = agents.inbox(root, who)
    if msgs:
        out.update(_context("PostToolUse", agents.as_context(msgs)))
    return out


def on_prompt(root: Path, p: dict) -> dict:
    from . import autoresearch
    activity.record(root, "prompt", text=(p.get("prompt") or "")[:2000])
    autoresearch.ensure_runner(root)
    if (p.get("prompt") or "").startswith("Auto-research goal:"):
        autoresearch.told(root)
    background(root, "prompt", {})
    objectives.ensure(root)
    ctx = objectives.context(root)
    msgs = agents.inbox(root, "main")
    if msgs:
        ctx = (ctx + "\n" if ctx else "") + agents.as_context(msgs)
    return _context("UserPromptSubmit", ctx) if ctx else {}


def on_start(root: Path, p: dict) -> dict:
    from .page import start_web
    start_web(root)
    from . import autoresearch
    autoresearch.ensure_runner(root)          # jobs went on while the session was away: follow them again
    background(root, "start", {})             # in tests, at once; else what the last session left is told now
    stands = (store.read(root, "stands.json", {}) or {}).get("text", "")
    ask = autoresearch.pending(root)
    if ask:
        autoresearch.told(root)
        stands += ("\n\n" if stands else "") + "Auto-research is on and waits for you (it went on while you were away):\n" + ask
    return _context("SessionStart", stands) if stands else {}


def on_stop(root: Path, p: dict, subagent: bool = False) -> dict:
    who = agents.name_of(root, p.get("agent_id") or "main") if subagent else "main"
    background(root, "substop" if subagent else "stop", {"who": who})
    out = _with_notices(root, {}) if not subagent else {}
    if not subagent:
        from . import autoresearch, chat
        chat.answered(root, p)
        objectives.ensure(root)
        ask = autoresearch.nudge(root)     # an iteration ended and waits for its analysis: keep Claude on it
        if ask:
            out.update(decision="block", reason=ask)
    return out


def run_hook(stdin_text: str, emit: Callable[[str], None] = print) -> int:
    try:
        payload = json.loads(stdin_text) if stdin_text.strip() else {}
    except ValueError:
        payload = {}
    cwd = Path(payload.get("cwd") or os.getcwd())
    if not _is_repo(cwd):
        return 0
    try:
        root = Path(git("rev-parse", "--show-toplevel", cwd=cwd).strip())
        event = payload.get("hook_event_name") or "Stop"
        out = {"SessionStart": on_start, "UserPromptSubmit": on_prompt, "PostToolUse": on_tool,
               "Stop": on_stop}.get(event, lambda r, p: on_stop(r, p, subagent=True) if event == "SubagentStop"
                                    else {})(root, payload)
    except (OSError, subprocess.CalledProcessError, ValueError, KeyError):
        return 0
    if out:
        emit(json.dumps(out))
    return 0


def command() -> str:
    if shutil.which(NAME):
        return NAME
    exe = sys.executable
    return f'"{exe}" -m research_diff' if " " in exe else f"{exe} -m research_diff"


def _paths(scope: str, root: Path) -> tuple:
    home = Path.home() / ".claude"
    settings = {"user": home / "settings.json", "project": root / ".claude" / "settings.json",
                "local": root / ".claude" / "settings.local.json"}[scope]
    return settings, (home / "skills" if scope == "user" else root / ".claude" / "skills") / NAME / "SKILL.md"


def _ours(entry: dict) -> bool:
    return any(c in h.get("command", "") for h in entry.get("hooks", []) for c in ("research-diff hook", "research_diff hook"))


def setup_claude(root: Path, scope: str = "user", undo: bool = False, out: Callable[[str], None] = print,
                 status_line: bool = True) -> int:
    settings_path, skill_path = _paths(scope, root)
    settings = _load(settings_path)
    hooks = settings.setdefault("hooks", {})
    has_claude = shutil.which("claude") is not None
    if undo:
        removed = []
        for ev in list(hooks):
            kept = [e for e in hooks[ev] if not _ours(e)]
            if len(kept) != len(hooks[ev]):
                removed.append(ev)
            if kept:
                hooks[ev] = kept
            else:
                del hooks[ev]
        if not hooks:
            del settings["hooks"]
        if "research" in json.dumps(settings.get("statusLine", {})):
            del settings["statusLine"]
            removed.append("statusLine")
        if removed:
            _save(settings_path, settings)
            out(f"removed {', '.join(removed)} from {settings_path}")
        if skill_path.is_file() and SKILL_MARK in skill_path.read_text(encoding="utf-8"):
            skill_path.unlink()
            if not any(skill_path.parent.iterdir()):
                skill_path.parent.rmdir()
            out(f"removed the skill {skill_path}")
        if has_claude and _claude(["mcp", "get", NAME]).returncode == 0:
            got = _claude(["mcp", "remove", NAME, "--scope", scope])
            out("removed the MCP server" if got.returncode == 0 else f"could not remove the MCP server: {got.stderr.strip()[:200]}")
        return 0
    added = []
    for ev, timeout in EVENTS.items():
        lst = hooks.setdefault(ev, [])
        if not any(_ours(e) for e in lst):
            lst.append({"hooks": [{"type": "command", "command": f"{command()} hook", "timeout": timeout}]})
            added.append(ev)
    if status_line and "statusLine" not in settings:
        settings["statusLine"] = {"type": "command", "command": f"{command()} statusline"}
        added.append("statusLine")
    if added:
        _save(settings_path, settings)
        out(f"added {', '.join(added)} to {settings_path}: one line on what changed in the research and its evidence, "
            "the agents' messages, the status line")
    else:
        out(f"the hooks are already in {settings_path}")
    if skill_path.is_file() and SKILL_MARK not in skill_path.read_text(encoding="utf-8"):
        out(f"left {skill_path} alone: someone else wrote it")
    elif not (skill_path.is_file() and skill_path.read_text(encoding="utf-8") == SKILL):
        skill_path.parent.mkdir(parents=True, exist_ok=True)
        with open(skill_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(SKILL)
        out(f"wrote the skill {skill_path}")
    if not has_claude:
        out("`claude` is not on PATH, so the MCP server was not registered; run setup again where it is")
        return 0
    try:
        import mcp  # noqa: F401
    except ImportError:
        out('the MCP server needs its extra: pip install "research-diff[mcp]", then run setup again')
        return 0
    if _claude(["mcp", "get", NAME]).returncode == 0:
        out("the MCP server is already registered")
    else:
        got = _claude(["mcp", "add", "--scope", scope, "--transport", "stdio", NAME, "--", *_split(command()), "mcp"])
        out(f"registered the MCP server ({scope} scope)" if got.returncode == 0
            else f"could not register the MCP server: {(got.stderr or got.stdout).strip()[:200]}")
    return 0
