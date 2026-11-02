"""Claude Code: `research-diff hook`, run by its Stop hook after every turn, and `research-diff setup claude`, which adds
the hook, a skill on when to show the research diff, and the MCP server. The hook never blocks and never fails a turn;
setup prints each change, and `--undo` takes it back."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional

from system_diff.agent import _claude, _is_repo, _load, _save, _split
from system_diff.sources import git

from .compare import compare, sync_trackers

NAME = "research-diff"
SKILL_MARK = "<!-- written by research-diff setup claude -->"
SKILL = f"""---
name: research-diff
description: Shows the person what an iteration did to their research (questions, hypotheses, experiments, results, claims). Use after running an experiment, changing a hypothesis, notes, a config or the paper, before asking them to review, or when they ask where the research stands.
---
{SKILL_MARK}

# Showing the research diff

The research is described by markers in the repository's own files: `H2: title` with `status:`, `tests:`,
`supports:`, `weakens:`, `relies on:` lines in notes, `% C1: …` in the paper, a `research:` block or a
`# research-diff: E5 tests H2` comment in experiment configs and scripts.

1. When you add an idea, an experiment or a claim, write its marker, so it is on the map.
2. After running an experiment, record what came out with the `log_result` tool (the metrics, and which hypothesis it
   supports or weakens), or as a results file the experiment's `research:` block names.
3. Call `research_diff` and tell the person, in two or three plain sentences built only from its plan, what changed:
   statuses that moved, numbers that changed, new warnings (a claim relying on a refuted hypothesis, an open hypothesis
   no experiment tests).
4. Point them at the picture, or at `research-diff watch` for a live page.
5. When they say they have understood it, call `checkpoint`, so the next diff shows only what is new to them.

Never report a result the plan does not show, and never mark a hypothesis supported or refuted without their say.
"""
SCOPES = ("user", "project", "local")


def hook_message(root: Path) -> Optional[str]:
    sync_trackers(root)   # runs logged to MLflow or W&B during the turn count too
    c = compare(root, "checkpoint", ".")
    if not c.diff["changes"]:
        return None
    return f"Research diff since {c.base}: {c.diff['headline']} (`research-diff watch` shows the picture.)"


def run_hook(stdin_text: str, emit: Callable[[str], None] = print) -> int:
    try:
        payload = json.loads(stdin_text) if stdin_text.strip() else {}
    except ValueError:
        payload = {}
    cwd = Path(payload.get("cwd") or os.getcwd())
    if not _is_repo(cwd):
        return 0
    try:
        message = hook_message(Path(git("rev-parse", "--show-toplevel", cwd=cwd).strip()))
    except (OSError, subprocess.CalledProcessError, ValueError, KeyError):
        return 0
    if message:
        emit(json.dumps({"systemMessage": message}))
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


def setup_claude(root: Path, scope: str = "user", undo: bool = False, out: Callable[[str], None] = print) -> int:
    settings_path, skill_path = _paths(scope, root)
    settings = _load(settings_path)
    stop = settings.setdefault("hooks", {}).setdefault("Stop", [])
    ours = [e for e in stop if _ours(e)]
    has_claude = shutil.which("claude") is not None
    if undo:
        if ours:
            settings["hooks"]["Stop"] = [e for e in stop if not _ours(e)]
            if not settings["hooks"]["Stop"]:
                del settings["hooks"]["Stop"]
            if not settings["hooks"]:
                del settings["hooks"]
            _save(settings_path, settings)
            out(f"removed the Stop hook from {settings_path}")
        if skill_path.is_file() and SKILL_MARK in skill_path.read_text(encoding="utf-8"):
            skill_path.unlink()
            if not any(skill_path.parent.iterdir()):
                skill_path.parent.rmdir()
            out(f"removed the skill {skill_path}")
        if has_claude and _claude(["mcp", "get", NAME]).returncode == 0:
            got = _claude(["mcp", "remove", NAME, "--scope", scope])
            out("removed the MCP server" if got.returncode == 0 else f"could not remove the MCP server: {got.stderr.strip()[:200]}")
        return 0
    if ours:
        out(f"the Stop hook is already in {settings_path}")
    else:
        stop.append({"hooks": [{"type": "command", "command": f"{command()} hook", "timeout": 30}]})
        _save(settings_path, settings)
        out(f"added a Stop hook to {settings_path}: after each turn, one line on what changed in the research")
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
