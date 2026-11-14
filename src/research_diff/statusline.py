"""`research-diff statusline`: what Claude Code's status line runs. Up to two rows: what the agent is working on and the
evidence at a glance (contradictions in red), and the thing most worth a look since the checkpoint.

Made from what the hooks and the views last wrote (.git/research-diff/state.json): it reads no file of the research, so
it stays fast (Claude Code runs it after every message). Prints nothing outside a repository.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import List

from system_diff.sources import git

from . import activity

RED, YEL, BLUE, DIM, OFF = "\x1b[31m", "\x1b[33m", "\x1b[34m", "\x1b[2m", "\x1b[0m"


def lines(root: Path) -> List[str]:
    s = activity.read_state(root)
    if not s:
        return []
    out = []
    f = s.get("focus") or []
    head = f"{BLUE}● {f[2] if f[2] != 'main' else 'Claude'} {f[1]} {f[0]}{OFF} · " if len(f) == 3 else ""
    ev = s.get("evidence", "")
    n = s.get("contradictions", 0)
    out.append(head + (f"{RED}✗ {n} contradiction{'' if n == 1 else 's'}{OFF} · " if n else "") + f"{DIM}{ev}{OFF}")
    if s.get("worth"):
        out.append(f"{YEL}⚑ {s['worth'][0]}{OFF}")
    return out


def main(stdin_text: str = "") -> int:
    try:
        data = json.loads(stdin_text) if stdin_text.strip() else {}
    except ValueError:
        data = {}
    cwd = Path((data.get("workspace") or {}).get("current_dir") or data.get("cwd") or os.getcwd())
    try:
        root = Path(git("rev-parse", "--show-toplevel", cwd=cwd).strip())
        print("\n".join(lines(root)))
    except (OSError, subprocess.CalledProcessError):
        pass
    return 0
