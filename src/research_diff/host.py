"""Where research-diff lives: on its own (its own web page and pane), or MERGED into system-diff's engine, page and
pane as an extension (system_diff_ext.py), when a system-diff with extensions is installed beside it. Merged, there is
one engine, one port, one page and one pane: research-diff starts no server of its own, its pane steps aside, and
what auto-research asks of Claude goes through system-diff's pane (its Send to Claude queue).

RESEARCH_DIFF_STANDALONE=1 keeps research-diff on its own even then.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def merged() -> bool:
    if os.environ.get("RESEARCH_DIFF_STANDALONE", "").lower() in ("1", "yes", "true", "on"):
        return False
    try:
        from system_diff import extensions
    except ImportError:
        return False
    try:
        return any(getattr(e, "NAME", "") == "research" for e in extensions.load())
    except Exception:  # noqa: BLE001
        return False


def system_web(root: Path) -> str:
    """system-diff's page for this repository, when its engine answers as itself; "" otherwise."""
    import http.client
    try:
        from system_diff.sources import git_dir
        info = json.loads((git_dir(Path(root)) / "web.json").read_text(encoding="utf-8"))
        port = int(info.get("port") or 0)
    except (ImportError, OSError, ValueError, TypeError):
        return ""
    if not port:
        return ""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=0.4)
    try:
        conn.request("GET", "/whoami")
        r = conn.getresponse()
        who = json.loads(r.read(4096).decode("utf-8")) if r.status == 200 else {}
    except (OSError, ValueError, http.client.HTTPException):
        return ""
    finally:
        conn.close()
    return f"http://localhost:{port}/" if who.get("id") and who.get("id") == info.get("id") else ""


def deliver(root: Path, text: str) -> bool:
    """Hand `text` to the live session through system-diff's pane (its outbox); False when that cannot be done."""
    try:
        from system_diff.watch import outbox_put
        outbox_put(Path(root), text)
        return True
    except Exception:  # noqa: BLE001
        return False


def opens_on_view() -> bool:
    """Whether `system-diff watch` takes --view (0.11.0.dev12 and later): research-diff watch opens on research's Now."""
    import re
    try:
        import system_diff
        v = str(system_diff.__version__)
    except Exception:  # noqa: BLE001
        return False
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)(?:\.dev(\d+))?", v)
    if not m:
        return False
    release = tuple(int(x) for x in m.groups()[:3])
    dev = m.group(4)
    return release > (0, 11, 0) or (release == (0, 11, 0) and (dev is None or int(dev) >= 12))
