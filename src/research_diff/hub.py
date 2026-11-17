"""One address for every web page on this machine, system-diff's and research-diff's: research-diff's engines join
system-diff's registry of running engines (system-diff 0.9's hub.py), so each page shows one tab per project and per
tool, and the first engine from port 8765, whichever tool it is, lists them all at /projects/page.

The registry is a folder of this user's (SYSTEM_DIFF_ENGINES, else %LOCALAPPDATA%\\system-diff\\engines on Windows,
~/Library/Application Support/system-diff/engines on macOS, $XDG_STATE_HOME or ~/.local/state/system-diff/engines
elsewhere), one file per engine, written as system-diff writes it:

    {"root", "name", "branch", "url", "port", "pid", "id", "version", "started", "app": "research-diff"}

never its token. Both tools take ports from the same range (8765-8774), so the hub is found the same way by both.

Compatibility: system-diff's hub keeps an entry only while its port answers GET /whoami with {"app": "system-diff",
"id"}: research-diff answers that too, with "tool": "research-diff" beside it. Its tab is named "<project> · research".
"""
from __future__ import annotations

import http.client
import json
import os
import socket
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

FIRST, LAST = 8765, 8774
ENV = "SYSTEM_DIFF_ENGINES"
ENTRY_MAX = 16 * 1024
SUFFIX = " · research"


def engines_dir(env=os.environ, platform: str = sys.platform) -> Optional[Path]:
    if env.get(ENV):
        return Path(env[ENV])
    if env.get("PYTEST_CURRENT_TEST"):
        return None
    if platform.startswith("win"):
        base = Path(env.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(env.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return base / "system-diff" / "engines"


def free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if os.name != "nt":
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def first_free() -> int:
    """The first free port of the shared range, else 0 (any)."""
    return next((p for p in range(FIRST, LAST + 1) if free(p)), 0)


def whoami_answer(ident: str) -> Dict[str, Any]:
    return {"app": "system-diff", "tool": "research-diff", "id": ident, "pid": os.getpid()}


def register(root: Path, url: str, port: int, ident: str, version: str, folder: Optional[Path] = None) -> Optional[Path]:
    folder = folder if folder is not None else engines_dir()
    if folder is None or not ident or not all(c in "0123456789abcdef" for c in ident):
        return None
    try:
        from .compare import branch
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        entry = {"root": str(root), "name": Path(root).name + SUFFIX, "branch": branch(Path(root)), "url": url,
                 "port": port, "pid": os.getpid(), "id": ident, "version": version, "started": round(time.time(), 3),
                 "app": "research-diff"}
        f = folder / f"{ident}.json"
        tmp = folder / f".{ident}.{os.getpid()}.tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(json.dumps(entry, ensure_ascii=False))
        os.replace(tmp, f)
        return f
    except OSError:
        return None


def unregister(f: Optional[Path]) -> None:
    if f is not None:
        try:
            f.unlink()
        except OSError:
            pass


def whoami(port: int, timeout: float = 0.6) -> Any:
    """GET /whoami: its JSON when a system-diff or research-diff engine answers there; False when nothing does or it is
    another program; None when it did not answer in time (busy: still there)."""
    if free(port):
        return False
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.request("GET", "/whoami", headers={"Accept": "application/json"})
        r = conn.getresponse()
        body = r.read(4096)
        if r.status != 200:
            return False
        info = json.loads(body.decode("utf-8"))
        return info if isinstance(info, dict) and info.get("app") == "system-diff" else False
    except (socket.timeout, TimeoutError):
        return None
    except (OSError, ValueError, UnicodeDecodeError, http.client.HTTPException):
        return False
    finally:
        conn.close()


def projects(self_id: str = "", folder: Optional[Path] = None, timeout: float = 0.6) -> List[Dict[str, Any]]:
    """The running engines of both tools, each with "tool" and "current" (the engine asking). A file whose engine is
    gone is left for system-diff's hub to remove (or removed here when its port answers nothing)."""
    folder = folder if folder is not None else engines_dir()
    if folder is None or not folder.is_dir():
        return []
    out = []
    for f in sorted(folder.glob("*.json")):
        try:
            if os.name != "nt" and f.stat().st_uid != os.getuid():
                continue
            raw = f.read_bytes()
            if len(raw) > ENTRY_MAX:
                continue
            e = json.loads(raw.decode("utf-8"))
            port = int(e["port"])
        except (OSError, ValueError, KeyError, TypeError, UnicodeDecodeError):
            continue
        if f.stem != e.get("id"):
            continue
        mine = e["id"] == self_id
        info = {"tool": "research-diff"} if mine else whoami(port, timeout)
        if info is False:
            try:
                f.unlink()
            except OSError:
                pass
            continue
        tool = (info or {}).get("tool") or e.get("app") or "system-diff"
        out.append({"name": str(e.get("name") or ""), "root": str(e.get("root") or ""), "branch": str(e.get("branch") or ""),
                    "port": port, "url": str(e.get("url") or f"http://127.0.0.1:{port}/"), "tool": tool,
                    "current": mine})
    out.sort(key=lambda e: (e["root"], e["tool"], e["port"]))
    return out


def find_hub(timeout: float = 0.6) -> Optional[int]:
    """The first engine of either tool from 8765 that serves the project list."""
    for port in range(FIRST, LAST + 1):
        if free(port) or not isinstance(whoami(port, timeout), dict):
            continue
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
        try:
            conn.request("GET", "/projects/page", headers={"Host": f"localhost:{port}"})
            r = conn.getresponse()
            r.read()
            if r.status == 200:
                return port
        except (OSError, http.client.HTTPException):
            pass
        finally:
            conn.close()
    return None


HUB_PAGE = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Your projects</title>
<style>:root{--bg:#f6f8fa;--card:#fff;--ink:#1f2328;--muted:#57606a;--line:#d0d7de;--blue:#1565c0;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--bg:#0d1117;--card:#161b22;--ink:#e6edf3;--muted:#8d96a0;--line:#30363d;
--blue:#58a6ff;color-scheme:dark}}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 -apple-system,Segoe UI,Helvetica,Arial,sans-serif}
main{max-width:860px;margin:0 auto;padding:24px 16px;display:grid;gap:12px}h1{font-size:18px;margin:0}
.sub{color:var(--muted);margin:0}ul{list-style:none;margin:0;padding:0;display:grid;gap:10px}
li{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 16px}
a{color:var(--ink);font-weight:600;text-decoration:none}a:hover{color:var(--blue)}
.tool{font-size:12px;border:1px solid var(--line);border-radius:10px;padding:1px 8px;margin-left:8px;color:var(--muted)}
.where{color:var(--muted);font:12px ui-monospace,Menlo,Consolas,monospace}</style>
<main><h1>Your projects</h1><p class="sub">Every system-diff and research-diff page running on this machine.</p>
<ul id="list"></ul></main>
<script>
function href(port){const m=location.hostname.match(/^(.*-)(\\d+)(\\..+)$/);
 if(!location.port&&m)return location.protocol+"//"+m[1]+port+m[3]+"/";return location.protocol+"//"+location.hostname+":"+port+"/";}
async function load(){const r=await fetch("/projects",{cache:"no-store"});const d=await r.json();const ul=document.getElementById("list");
 ul.replaceChildren(...(d.projects.length?d.projects.map(p=>{const li=document.createElement("li");const a=document.createElement("a");
 a.href=href(p.port);a.textContent=p.name;const t=document.createElement("span");t.className="tool";t.textContent=p.tool;
 const w=document.createElement("div");w.className="where";w.textContent=p.root+(p.branch?" · "+p.branch:"")+" · port "+p.port;
 li.append(a,t,w);return li;}):[Object.assign(document.createElement("li"),{textContent:"Nothing is running."})]));}
load();setInterval(load,3000);
</script>"""
