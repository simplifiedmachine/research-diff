"""`research-diff watch`: the views in a browser, live, for a person to keep beside the editor while they, or a team
of agents, work: Now, Review (with the picture of what changed), Evidence (the interactive evidence graph), Agents,
History. It redraws when a file, the checkpoint, the agents' bus or the activity changes.

Local only: the server listens on 127.0.0.1. "Mark as seen" moves the checkpoint; "Send to Claude" appends what was
typed to .git/research-diff/outbox.jsonl, where the pane picks it up and submits it to the live session. Both need the
page's own token, and Send its own origin too, so no other web page open in the same browser can press them.
"""
from __future__ import annotations

import json
import os
import secrets
import subprocess
import threading
import time
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

from system_diff.compare import worktree_tree

from . import compare, evgraph, graph, page, store

TABS = [("now", "Now"), ("review", "Review"), ("evidence", "Evidence"), ("agents", "Agents"), ("history", "History")]
COLORS = {"accent": "var(--blue)", "good": "var(--green)", "attention": "var(--amber)", "removed": "var(--red)",
          "agent0": "#00838f", "agent1": "#8e24aa", "agent2": "#2e7d32", "agent3": "#b26a00", "agent4": "#1565c0"}


def rows_html(data: dict) -> str:
    out = []
    zoom = {b["y"]: b.get("enter", {}) for b in data["blocks"]}
    for y, row in enumerate(data["rows"]):
        spans = []
        for run in row:
            words = run[1].split()
            color = next((COLORS[w] for w in words if w in COLORS), "")
            css = (f"color:{color};" if color else "") + ("font-weight:600;" if {"bold", "title", "heading"} & set(words)
                                                          else "") + ("opacity:.65;" if "muted" in words else "")
            spans.append(f'<span style="{css}">{escape(run[0])}</span>' if css else escape(run[0]))
        act = zoom.get(y) or {}
        attr = f' data-zoom="{escape(act["zoom"])}"' if act.get("zoom") else \
            f' data-entry="{escape(act["entry"])}"' if act.get("entry") else ""
        cls = ' class="pick"' if attr else ""
        out.append(f"<div{cls}{attr}>{''.join(spans) or '&nbsp;'}</div>")
    return "\n".join(out)


PAGE = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Research diff</title>
<style>
:root{--bg:#f6f8fa;--panel:#fff;--ink:#1f2328;--muted:#57606a;--line:#d0d7de;--blue:#1565c0;--green:#2e7d32;
--amber:#b26a00;--red:#c62828;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--bg:#0d1117;--panel:#161b22;--ink:#e6edf3;--muted:#8d96a0;--line:#30363d;
--blue:#58a6ff;--green:#3fb950;--amber:#d29922;--red:#f85149;color-scheme:dark}}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 -apple-system,Segoe UI,Helvetica,Arial,sans-serif}
header{display:flex;gap:6px;align-items:center;padding:10px 16px;border-bottom:1px solid var(--line);flex-wrap:wrap;
background:var(--panel);position:sticky;top:0}
header h1{font-size:15px;margin:0 12px 0 0}
button{font:inherit;border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:16px;
padding:3px 12px;cursor:pointer}
button.on{border-color:var(--blue);color:var(--blue);font-weight:600}
main{padding:12px 16px}
#rows{font:13px/1.55 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;white-space:pre;overflow-x:auto}
#rows .pick{cursor:pointer}#rows .pick:hover{background:rgba(127,127,127,.12)}
#pic{overflow:auto;margin-bottom:12px}#pic img,#pic svg{max-width:none}
iframe{width:100%;height:calc(100vh - 70px);border:0}
.send{display:flex;gap:8px;margin-left:auto}.send input{font:inherit;min-width:220px;padding:3px 8px;
border:1px solid var(--line);border-radius:6px;background:var(--panel);color:var(--ink)}
.muted{color:var(--muted);font-size:12px}
</style>
<header><h1>Research diff</h1><span id="tabs"></span><button id="back" hidden>← Back</button>
<button id="mark" title="Mark everything shown as understood: the next diff starts here">Mark as seen</button>
<span class="muted" id="at"></span>
<form class="send" id="send"><input id="say" placeholder="Send to Claude…"><button>Send</button></form></header>
<main><div id="pic"></div><div id="rows"></div><div id="frame"></div></main>
<script>
const TOKEN = "__TOKEN__", TABS = __TABS__;
let view = location.hash.slice(1) || 'now', part = '', version = -1, trail = [];
const tabs = document.getElementById('tabs');
for (const [id, label] of TABS) { const b = document.createElement('button'); b.textContent = label; b.dataset.v = id;
  b.onclick = () => { view = id; part = ''; trail = []; location.hash = id; load(); }; tabs.appendChild(b); }
async function load() {
  for (const b of tabs.children) b.classList.toggle('on', b.dataset.v === view);
  document.getElementById('back').hidden = !trail.length;
  const frame = document.getElementById('frame'), rows = document.getElementById('rows'), pic = document.getElementById('pic');
  if (view === 'evidence' && !part) {
    rows.innerHTML = ''; pic.innerHTML = '';
    if (!frame.firstChild) frame.innerHTML = '<iframe src="/evidence"></iframe>'; else frame.firstChild.src = '/evidence';
    return;
  }
  frame.innerHTML = '';
  const r = await fetch(`/view?v=${view}&part=${encodeURIComponent(part)}`); const d = await r.json();
  rows.innerHTML = d.html; pic.innerHTML = d.picture || '';
  for (const el of rows.querySelectorAll('[data-zoom]')) el.onclick = () => { trail.push([view, part]); view = 'now'; part = el.dataset.zoom; load(); };
  for (const el of rows.querySelectorAll('[data-entry]')) el.onclick = () => { trail.push([view, part]); part = '#' + el.dataset.entry; load(); };
}
document.getElementById('back').onclick = () => { [view, part] = trail.pop(); load(); };
document.getElementById('mark').onclick = async () => { await fetch('/mark', {method: 'POST', headers: {'x-token': TOKEN}}); };
document.getElementById('send').onsubmit = async e => { e.preventDefault(); const t = document.getElementById('say');
  if (!t.value.trim()) return; await fetch('/send', {method: 'POST', headers: {'x-token': TOKEN, 'content-type': 'application/json'},
  body: JSON.stringify({text: t.value})}); t.value = ''; t.placeholder = 'Sent: the pane hands it to Claude'; };
async function poll() {
  try { const r = await fetch('/version'); const d = await r.json();
    document.getElementById('at').textContent = d.error ? d.error : 'updated ' + d.at;
    if (d.version !== version) { version = d.version; await load(); } } catch (e) {}
  setTimeout(poll, 1500);
}
poll();
</script>
"""


class Watcher:
    def __init__(self, root: Path, base: str, config_path: Optional[str], interval: float):
        self.root, self.base, self.config_path, self.interval = root, base, config_path, interval
        self.token = secrets.token_urlsafe(16)
        self.version, self.at, self.error, self.last_key = 0, "", "", None
        self.stop = threading.Event()
        self.lock = threading.Lock()

    def key(self) -> tuple:
        h = store.home(self.root)
        mt = tuple((h / n).stat().st_mtime if (h / n).exists() else 0 for n in ("agents.json", "activity.jsonl",
                                                                                 "objectives.json", "history.jsonl"))
        return worktree_tree(self.root), compare.checkpoint_sha(self.root), mt

    def tick(self, force: bool = False) -> None:
        try:
            k = self.key()
            self.error = ""
        except (OSError, subprocess.CalledProcessError, ValueError) as exc:
            self.error = f"{type(exc).__name__}: {exc}"[:200]
            return
        if force or k != self.last_key:
            with self.lock:
                self.last_key = k
                self.version += 1
                self.at = time.strftime("%H:%M:%S")

    def loop(self) -> None:
        while not self.stop.is_set():
            self.tick()
            self.stop.wait(self.interval)

    def view(self, v: str, part: str) -> dict:
        data = page.show(self.root, v, part, 160, self.base, self.config_path)
        data.pop("send", None)   # the pane takes those, not this page
        pic = ""
        if v == "review":
            c = compare.compare(self.root, self.base, ".", self.config_path)
            pic = graph.diff_svg(c.diff, c.before, c.after, c.cfg) or ""
        return {"html": rows_html(data), "picture": pic}

    def evidence(self) -> str:
        g, _bp, cfg = compare.evidence_of(self.root, ".", self.config_path)
        return evgraph.standalone(g)


def handler(w: Watcher):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # quiet
            pass

        def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
            self.send_response(code)
            self.send_header("content-type", ctype)
            self.send_header("cache-control", "no-store")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            try:
                if u.path in ("/", "/index.html"):
                    body = PAGE.replace("__TOKEN__", w.token).replace("__TABS__", json.dumps(TABS))
                    return self._send(200, body.encode(), "text/html; charset=utf-8")
                if u.path == "/version":
                    return self._send(200, json.dumps({"version": w.version, "at": w.at, "error": w.error}).encode())
                if u.path == "/view":
                    got = w.view(q.get("v", ["now"])[0], q.get("part", [""])[0])
                    return self._send(200, json.dumps(got).encode())
                if u.path == "/evidence":
                    return self._send(200, w.evidence().encode(), "text/html; charset=utf-8")
            except (OSError, subprocess.CalledProcessError, ValueError, KeyError) as exc:
                return self._send(500, json.dumps({"html": escape(f"{type(exc).__name__}: {exc}")}).encode())
            return self._send(404, b"{}")

        def do_POST(self):
            if self.headers.get("x-token") != w.token:
                return self._send(403, b'{"error": "token"}')
            body = self.rfile.read(int(self.headers.get("content-length") or 0) or 0)
            if self.path == "/mark":
                compare.checkpoint(w.root)
                w.tick(force=True)
                return self._send(200, b"{}")
            if self.path == "/send":
                origin = self.headers.get("origin", "")
                host = self.headers.get("host", "")
                if origin and origin not in (f"http://{host}",):
                    return self._send(403, b'{"error": "origin"}')
                try:
                    text = str(json.loads(body or b"{}").get("text", "")).strip()[:4000]
                except ValueError:
                    text = ""
                if text:
                    store.append(w.root, "outbox.jsonl", {"id": secrets.token_hex(6), "text": text})
                return self._send(200, b"{}")
            return self._send(404, b"{}")
    return H


def serve(root: Path, base_point: str = "checkpoint", port: int = 8766, config_path: Optional[str] = None,
          interval: float = 2.0, ready=None, quiet: bool = False) -> None:
    w = Watcher(root, base_point, config_path, interval)
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), handler(w))
    except OSError:
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler(w))   # taken: any free port
    store.write(root, "web.json", {"port": server.server_address[1], "pid": os.getpid()})
    threading.Thread(target=w.loop, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    if ready:
        ready(url, server, w)
    elif not quiet:
        print(f"research-diff watch: {url} (Ctrl-C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        w.stop.set()
        server.server_close()
