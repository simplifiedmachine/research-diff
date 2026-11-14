"""`research-diff tui`: the pane's views in a terminal of their own, for a tab beside Claude Code. It paints the very page
the pane paints (page.show), with the same keys: n r e a h switch views, ↑ ↓ pick, Enter zooms in, b back, f follow,
x clears an objective, q quits. It redraws every few seconds.

Standard library only: ANSI on the alternate screen; keys from termios on POSIX and msvcrt on Windows.
"""
from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path
from typing import List, Optional

from . import objectives, page

KEYS = {"n": "now", "r": "review", "e": "evidence", "a": "agents", "h": "history"}
CODES = {"accent": "34", "good": "32", "attention": "33", "removed": "31", "muted": "2", "heading": "2;1", "bold": "1",
         "agent0": "36", "agent1": "35", "agent2": "32", "agent3": "33", "agent4": "34"}


def render(data: dict, sel: int, top: int, rows: int, cols: int) -> List[str]:
    picked = data["blocks"][sel] if data["blocks"] and 0 <= sel < len(data["blocks"]) else None
    lit = set(data["lights"].get(picked["id"], [])) if picked else set()
    out = []
    for y, row in enumerate(data["rows"][top: top + rows], top):
        line, used = "", 0
        for run in row:
            text = run[0][: max(0, cols - used)]
            used += len(text)
            ids = set((run[2] if len(run) > 2 else "").split())
            codes = [CODES[w] for w in run[1].split() if w in CODES]
            if picked and (y == picked["y"] or ids & lit):
                codes = ["7" if y == picked["y"] else "1", "34"]
            line += f"\x1b[{';'.join(codes)}m{text}\x1b[0m" if codes else text
        out.append(line)
    return out


def _keys():
    if os.name == "nt":
        import msvcrt

        def read(timeout: float) -> Optional[str]:
            end = time.time() + timeout
            while time.time() < end:
                if msvcrt.kbhit():
                    c = msvcrt.getwch()
                    if c in ("\x00", "\xe0"):
                        return {"H": "up", "P": "down"}.get(msvcrt.getwch(), "")
                    return {"\r": "enter"}.get(c, c)
                time.sleep(0.05)
            return None
        return read, lambda: None
    import select
    import termios
    import tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    tty.setcbreak(fd)

    def read(timeout: float) -> Optional[str]:
        r, _, _ = select.select([sys.stdin], [], [], timeout)
        if not r:
            return None
        c = os.read(fd, 1).decode(errors="ignore")
        if c == "\x1b":
            seq = os.read(fd, 2).decode(errors="ignore") if select.select([sys.stdin], [], [], 0.02)[0] else ""
            return {"[A": "up", "[B": "down", "[5": "pageup", "[6": "pagedown"}.get(seq, "esc")
        return {"\n": "enter", "\r": "enter"}.get(c, c)
    return read, lambda: termios.tcsetattr(fd, termios.TCSADRAIN, old)


def main(root: Path, config_path: Optional[str] = None) -> int:
    if not sys.stdin.isatty():
        print(page.as_text(page.show(root, "now", "", 100, config_path=config_path)))
        return 0
    read, restore = _keys()
    view, part, back, sel, top, data, at = "now", "", [], 0, 0, None, 0.0
    sys.stdout.write("\x1b[?1049h\x1b[?25l")
    try:
        while True:
            cols, rows = shutil.get_terminal_size((100, 30))
            if data is None or time.time() - at > 3:
                data = page.show(root, view, part, cols - 1, config_path=config_path)
                data.pop("send", None)
                at = time.time()
                sel = min(sel, max(0, len(data["blocks"]) - 1))
            tabs = "  ".join(f"\x1b[1;34m[{k}] {v.title()}\x1b[0m" if v == view else f"\x1b[2m[{k}] {v.title()}\x1b[0m"
                             for k, v in KEYS.items())
            body = render(data, sel, top, rows - 3, cols - 1)
            sys.stdout.write("\x1b[H\x1b[2J" + tabs + (f"   \x1b[2m{part}\x1b[0m" if part else "") + "\n\n" +
                             "\n".join(body) + f"\x1b[{rows};1H\x1b[2m↑↓ pick · ↵ zoom · b back · f follow · "
                             "x clear objective · q quit\x1b[0m")
            sys.stdout.flush()
            k = read(1.0)
            if k is None:
                continue
            blocks = data["blocks"]
            if k in ("q", "esc", "\x03"):
                return 0
            if k in KEYS:
                view, part, top, sel, data = KEYS[k], "", 0, 0, None
            elif k in ("up", "down") and blocks:
                sel = max(0, min(len(blocks) - 1, sel + (1 if k == "down" else -1)))
                y = blocks[sel]["y"]
                if y < top or y >= top + rows - 4:
                    top = max(0, y - (rows - 4) // 3)
            elif k in ("pageup", "pagedown"):
                top = max(0, top + (rows - 4) * (1 if k == "pagedown" else -1))
            elif k == "enter" and blocks:
                act = blocks[sel].get("enter") or {}
                if act.get("zoom") or act.get("entry"):
                    back.append((view, part))
                    view, part = ("now", act["zoom"]) if act.get("zoom") else ("history", "#" + act["entry"])
                    top, sel, data = 0, 0, None
            elif k == "b" and back:
                (view, part), top, sel, data = back.pop(), 0, 0, None
            elif k == "f":
                view, part, back, top, sel, data = "now", "", [], 0, 0, None
            elif k == "x" and blocks:
                act = (blocks[sel].get("on") or {}).get("x") or {}
                if act.get("clear_objective"):
                    objectives.clear(root, act["clear_objective"])
                    data = None
    finally:
        restore()
        sys.stdout.write("\x1b[?25h\x1b[?1049l")
        sys.stdout.flush()
