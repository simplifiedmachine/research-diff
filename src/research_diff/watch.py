"""`research-diff watch`: the views in a browser, live, for a person to keep beside the editor while they, or a team
of agents, work: Now, Review (with the picture of what changed), Evidence (the interactive evidence graph), Paper
(the paper section by section, each file opened as an outline with your LLM's summary of each section), Agents,
History. It redraws when a file, the checkpoint, the agents' bus or the activity changes, shows Claude's answers to
what was asked here, and lights up what Claude points at (the point_to tool) in the evidence graph.

One address for both tools: each engine joins system-diff's registry of running engines (hub.py) and takes the first
free port from 8765, so the page shows a tab per project and per tool (system-diff's and research-diff's), and the
first engine lists them all at /projects/page.

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

from . import __version__, chat, compare, evgraph, graph, hub, page, paperview, store
from .webparts import file_html

IDLE = 8 * 3600           # an engine with no look and no change for this long stops (the pane starts it again)
TABS = [("now", "Now"), ("review", "Review"), ("evidence", "Evidence"), ("paper", "Paper"), ("auto", "Auto-research"),
        ("agents", "Agents"), ("history", "History")]
COLORS = {"accent": "var(--blue)", "good": "var(--green)", "attention": "var(--amber)", "removed": "var(--red)",
          "agent0": "#00838f", "agent1": "#8e24aa", "agent2": "#2e7d32", "agent3": "#b26a00", "agent4": "#1565c0"}


def rows_html(data: dict) -> str:
    out = []
    acts = {b["y"]: b.get("enter", {}) for b in data["blocks"]}
    for y, row in enumerate(data["rows"]):
        spans = []
        for run in row:
            words = run[1].split()
            color = next((COLORS[w] for w in words if w in COLORS), "")
            css = (f"color:{color};" if color else "") + ("font-weight:600;" if {"bold", "title", "heading"} & set(words)
                                                          else "") + ("opacity:.65;" if "muted" in words else "")
            spans.append(f'<span style="{css}">{escape(run[0])}</span>' if css else escape(run[0]))
        act = acts.get(y) or {}
        attr = "".join(f' data-{k}="{escape(str(act[k]))}"' for k in ("zoom", "entry", "file") if act.get(k))
        cls = ' class="pick"' if attr else ""
        out.append(f"<div{cls}{attr}>{''.join(spans) or '&nbsp;'}</div>")
    return "\n".join(out)


PAGE = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Research diff</title>
<style>
:root{--bg:#f6f8fa;--panel:#fff;--ink:#1f2328;--muted:#57606a;--line:#d0d7de;--blue:#1565c0;--green:#2e7d32;
--amber:#b26a00;--red:#c62828;--redbg:#fdecea;--hl:#fff8c5;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--bg:#0d1117;--panel:#161b22;--ink:#e6edf3;--muted:#8d96a0;--line:#30363d;
--blue:#58a6ff;--green:#3fb950;--amber:#d29922;--red:#f85149;--redbg:#3a1618;--hl:#3a3410;color-scheme:dark}}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 -apple-system,Segoe UI,Helvetica,Arial,sans-serif}
header{display:flex;gap:6px;align-items:center;padding:10px 16px;border-bottom:1px solid var(--line);flex-wrap:wrap;
background:var(--panel);position:sticky;top:0;z-index:2}
header h1{font-size:15px;margin:0 12px 0 0}
#projects{display:flex;gap:6px;flex-wrap:wrap;padding:6px 16px;font-size:12.5px;border-bottom:1px solid var(--line)}
#projects a{color:var(--muted);text-decoration:none;border:1px solid var(--line);border-radius:12px;padding:1px 9px}
#projects a.cur{color:var(--blue);border-color:var(--blue);font-weight:600}
button{font:inherit;border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:16px;
padding:3px 12px;cursor:pointer}
button.on{border-color:var(--blue);color:var(--blue);font-weight:600}
main{padding:12px 16px}
#rows{font:13px/1.55 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;white-space:pre;overflow-x:auto}
#rows .pick{cursor:pointer}#rows .pick:hover{background:rgba(127,127,127,.12)}
#pic{overflow:auto;margin-bottom:12px}
iframe{width:100%;height:calc(100vh - 110px);border:0}
#point{display:none;background:var(--hl);border:1px solid var(--line);border-radius:8px;padding:6px 10px;margin-bottom:10px}
#talk{margin-top:18px;border-top:1px solid var(--line);padding-top:10px}
#talk .q{color:var(--muted);font-size:12.5px;margin-top:10px}#talk .a{white-space:pre-wrap;background:var(--panel);
border:1px solid var(--line);border-radius:8px;padding:8px 10px}
.send{display:flex;gap:8px;margin-left:auto}.send input{font:inherit;min-width:220px;padding:3px 8px;
border:1px solid var(--line);border-radius:6px;background:var(--panel);color:var(--ink)}
.muted{color:var(--muted);font-size:12px}
.file{display:flex;gap:14px;flex-wrap:wrap}.outline{flex:0 1 420px;min-width:0}.src{flex:1 1 560px;min-width:0;
overflow-x:auto;font:12.5px/1.5 ui-monospace,Menlo,Consolas,monospace;background:var(--panel);border:1px solid var(--line);
border-radius:8px;padding:6px 0}
.ln{white-space:pre;padding:0 10px}.ln .n{display:inline-block;width:3.5em;color:var(--muted);user-select:none}
.ln.bad{background:var(--redbg)}.ln.mark{background:rgba(21,101,192,.08)}.ln.ok{box-shadow:inset 3px 0 var(--green)}
.ln.flash{outline:2px solid var(--blue)}
.chunk{border-left:2px solid var(--line);padding:4px 0 8px 10px;margin-bottom:8px;cursor:pointer}
.sum{color:var(--muted);font-size:13px}.watch{color:var(--amber);font-size:13px}.bad{color:var(--red);font-size:13px}
.st{font-size:13px}.st i{font-style:normal;font-size:11.5px;color:var(--muted)}
.v-contradicted b{color:var(--red)}.v-contested b{color:var(--amber)}.v-supported b{color:var(--green)}
.ar{display:grid;gap:14px;max-width:1100px}.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;
padding:12px 14px}.card h3{margin:0 0 8px;font-size:14px}.grid{display:flex;gap:8px;flex-wrap:wrap;align-items:end}
.grid label{display:grid;gap:2px;font-size:12px;color:var(--muted)}.grid input,.grid textarea{font:inherit;color:var(--ink);
background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:4px 8px;min-width:0}
.badge{font-size:12px;font-weight:700;border-radius:10px;padding:1px 9px;border:1px solid currentColor}
.s-running{color:var(--green)}.s-paused{color:var(--amber)}.s-stopping,.s-failed{color:var(--red)}.s-done{color:var(--green)}
.s-stopped,.s-queued,.s-killed{color:var(--muted)}
table.jobs{border-collapse:collapse;width:100%;font-size:13px}table.jobs td,table.jobs th{text-align:left;padding:3px 8px;
border-bottom:1px solid var(--line)}.tbl{overflow-x:auto}pre.tail{margin:4px 0;max-height:180px;overflow:auto;font-size:12px;
background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:6px}
.ask{border-left:3px solid var(--blue);padding:6px 10px;background:var(--bg);white-space:pre-wrap;font-size:13px}
.err{color:var(--red);font-size:13px}
</style>
<header><h1>Research diff</h1><span id="tabs"></span><button id="back" hidden>← Back</button>
<button id="mark" title="Mark everything shown as understood: the next diff starts here">Mark as seen</button>
<span class="muted" id="at"></span>
<form class="send" id="send"><input id="say" placeholder="Ask Claude about the research…"><button>Send</button></form></header>
<div id="projects"></div>
<main><div id="point"></div><div id="pic"></div><div id="rows"></div><div id="frame"></div><div id="talk"></div></main>
<script>
const TOKEN = "__TOKEN__", TABS = __TABS__;
let view = (location.hash.slice(1) || 'now').replace(/^view=/, ''), part = '', version = -1, trail = [], file = '';
const tabs = document.getElementById('tabs');
for (const [id, label] of TABS) { const b = document.createElement('button'); b.textContent = label; b.dataset.v = id;
  b.onclick = () => { view = id; part = ''; file = ''; trail = []; location.hash = id; load(); }; tabs.appendChild(b); }
const esc = s => String(s).replace(/[<&>]/g, c => ({'<':'&lt;','&':'&amp;','>':'&gt;'}[c]));
function wire(root) {
  for (const el of root.querySelectorAll('[data-zoom]')) el.onclick = () => { trail.push([view, part, file]); view = 'now'; part = el.dataset.zoom; file = ''; load(); };
  for (const el of root.querySelectorAll('[data-entry]')) el.onclick = () => { trail.push([view, part, file]); part = '#' + el.dataset.entry; load(); };
  for (const el of root.querySelectorAll('[data-file]')) el.onclick = () => { trail.push([view, part, file]); file = el.dataset.file; load(); };
}
async function load() {
  for (const b of tabs.children) b.classList.toggle('on', b.dataset.v === view);
  document.getElementById('back').hidden = !trail.length;
  const frame = document.getElementById('frame'), rows = document.getElementById('rows'), pic = document.getElementById('pic');
  if (file) {
    frame.innerHTML = ''; pic.innerHTML = '';
    const d = await (await fetch('/file?path=' + encodeURIComponent(file))).json();
    rows.style.whiteSpace = 'normal'; rows.innerHTML = d.html;
    for (const el of rows.querySelectorAll('.outline [data-line]')) el.onclick = e => { e.stopPropagation();
      const t = document.getElementById('L' + el.dataset.line); if (t) { t.scrollIntoView({block: 'center'});
      t.classList.add('flash'); setTimeout(() => t.classList.remove('flash'), 1200); } };
    if (d.state === 'summarizing') setTimeout(() => { if (file) load(); }, 4000);
    return;
  }
  rows.style.whiteSpace = '';
  if (view === 'auto' && !part) { rows.innerHTML = ''; pic.innerHTML = '';
    if (!frame.firstChild || !frame.firstChild.src.endsWith('/auto/page')) frame.innerHTML = '<iframe src="/auto/page"></iframe>';
    return; }
  if (view === 'evidence' && !part) {
    rows.innerHTML = ''; pic.innerHTML = '';
    if (!frame.firstChild) frame.innerHTML = '<iframe src="/evidence"></iframe>'; else frame.firstChild.contentWindow.location.reload();
    return;
  }
  frame.innerHTML = '';
  const d = await (await fetch(`/view?v=${view}&part=${encodeURIComponent(part)}`)).json();
  rows.innerHTML = d.html; pic.innerHTML = d.picture || ''; wire(rows);
}
async function side() {
  const d = await (await fetch('/talk')).json();
  const pt = document.getElementById('point');
  pt.style.display = d.pointing.ids && d.pointing.ids.length ? 'block' : 'none';
  pt.innerHTML = '<b>Claude is pointing at</b> ' + (d.pointing.ids || []).map(i => `<a href="#" data-zoom="${esc(i)}">${esc(i)}</a>`).join(', ') +
    (d.pointing.note ? ' — ' + esc(d.pointing.note) : ''); wire(pt);
  document.getElementById('talk').innerHTML = d.answers.length ? '<b>Asked and answered</b>' + d.answers.slice().reverse().map(a =>
    `<div class="q">${a.web ? 'You asked here' : 'You asked'}: ${esc(a.prompt)}</div><div class="a">${esc(a.text)}</div>`).join('') : '';
  const p = await (await fetch('/projects')).json(), bar = document.getElementById('projects');
  bar.style.display = p.projects.length > 1 ? 'flex' : 'none';
  bar.innerHTML = p.projects.map(x => `<a class="${x.current ? 'cur' : ''}" href="${x.current ? '#' : href(x.port)}">${esc(x.name)}</a>`).join('') +
    (p.hub ? ` <a href="${href(p.hub)}projects/page">all projects</a>` : '');
}
function href(port){const m=location.hostname.match(/^(.*-)(\\d+)(\\..+)$/);
  if(!location.port&&m)return location.protocol+"//"+m[1]+port+m[3]+"/";return location.protocol+"//"+location.hostname+":"+port+"/";}
document.getElementById('back').onclick = () => { [view, part, file] = trail.pop(); load(); };
document.getElementById('mark').onclick = async () => { await fetch('/mark', {method: 'POST', headers: {'x-token': TOKEN}}); };
document.getElementById('send').onsubmit = async e => { e.preventDefault(); const t = document.getElementById('say');
  if (!t.value.trim()) return; await fetch('/send', {method: 'POST', headers: {'x-token': TOKEN, 'content-type': 'application/json'},
  body: JSON.stringify({text: t.value})}); t.value = ''; t.placeholder = 'Sent: the pane hands it to Claude; the answer appears below'; };
async function poll() {
  try { const r = await fetch('/version'); const d = await r.json();
    document.getElementById('at').textContent = d.error ? d.error : 'updated ' + d.at;
    if (d.version !== version) { version = d.version; await load(); await side(); } } catch (e) {}
  setTimeout(poll, 1500);
}
poll();
</script>
"""


class Watcher:
    def __init__(self, root: Path, base: str, config_path: Optional[str], interval: float):
        self.root, self.base, self.config_path, self.interval = root, base, config_path, interval
        self.token = secrets.token_urlsafe(16)
        self.ident = secrets.token_hex(8)
        self.version, self.at, self.error, self.last_key = 0, "", "", None
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.seen = time.time()          # the last request or change: an engine nobody uses goes away
        self.server = None

    def key(self) -> tuple:
        h = store.home(self.root)
        names = ("agents.json", "activity.jsonl", "objectives.json", "history.jsonl", "answers.jsonl", "pointing.json",
                 "notes.json", "review.json", "auto/campaign.json", "auto/servers.json")
        mt = tuple((h / n).stat().st_mtime if (h / n).exists() else 0 for n in names)
        summ = h / "summaries"
        mt += (summ.stat().st_mtime if summ.exists() else 0,)
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
        from . import autoresearch
        while not self.stop.is_set():
            before = self.version
            self.tick()
            if self.version != before:
                self.seen = time.time()
            autoresearch.ensure_runner(self.root)     # the engine keeps the runner going while it is on
            if self.gone():
                self.stop.set()
                if self.server is not None:
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            self.stop.wait(self.interval)

    def gone(self) -> bool:
        """Time to go: the repository is gone, another engine serves it now, or nothing happened for IDLE seconds."""
        if not (self.root / ".git").exists():
            return True
        mine = (store.read(self.root, "web.json", {}) or {}).get("id")
        if mine and mine != self.ident:
            return True
        return time.time() - self.seen > IDLE

    def view(self, v: str, part: str) -> dict:
        data = page.show(self.root, v, part, 160, self.base, self.config_path)
        pic = ""
        if v == "review":
            c = compare.compare(self.root, self.base, ".", self.config_path)
            pic = graph.diff_svg(c.diff, c.before, c.after, c.cfg) or ""
        return {"html": rows_html(data), "picture": pic}

    def file(self, path: str) -> dict:
        path = path.replace("\\", "/").lstrip("/")
        g, bp, _cfg = compare.evidence_of(self.root, ".", self.config_path)
        if ".." in path.split("/") or path not in paperview.research_files(bp):
            return {"html": "<p>Only the research's own files (the paper, notes, configs and scripts with markers) "
                            "open here.</p>", "state": ""}
        state = paperview.summarize(self.root, path, bp, g)   # in the background, the first time
        return {"html": file_html(paperview.outline(self.root, path, bp, g), state), "state": state["state"]}

    def evidence(self) -> str:
        g, _bp, _cfg = compare.evidence_of(self.root, ".", self.config_path)
        g["notes"] = {k: [n["text"] for n in v] for k, v in chat.notes_by_node(self.root).items()}
        g["pointing"] = chat.pointing(self.root).get("ids", [])
        return evgraph.standalone(g)

    def auto(self) -> dict:
        from . import autoresearch
        return autoresearch.web_status(self.root, self.config_path)

    def auto_post(self, path: str, d: dict) -> dict:
        from . import autoresearch
        return autoresearch.web_action(self.root, path[len("/auto/"):], d)

    def talk(self) -> dict:
        return {"answers": chat.answers(self.root, 5), "pointing": chat.pointing(self.root)}


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
            if u.path != "/whoami":
                w.seen = time.time()
            q = parse_qs(u.query)
            try:
                if u.path in ("/", "/index.html"):
                    body = PAGE.replace("__TOKEN__", w.token).replace("__TABS__", json.dumps(TABS))
                    return self._send(200, body.encode(), "text/html; charset=utf-8")
                if u.path == "/whoami":     # in system-diff's own words, so its hub keeps this engine's tab
                    return self._send(200, json.dumps(hub.whoami_answer(w.ident)).encode())
                if u.path == "/moved":
                    return self._send(200, b"{}")
                if u.path == "/projects":
                    return self._send(200, json.dumps({"projects": hub.projects(w.ident), "hub": hub.find_hub(0.3)})
                                      .encode())
                if u.path == "/projects/page":
                    return self._send(200, hub.HUB_PAGE.encode(), "text/html; charset=utf-8")
                if u.path == "/version":
                    return self._send(200, json.dumps({"version": w.version, "at": w.at, "error": w.error}).encode())
                if u.path == "/view":
                    got = w.view(q.get("v", ["now"])[0], q.get("part", [""])[0])
                    return self._send(200, json.dumps(got).encode())
                if u.path == "/file":
                    return self._send(200, json.dumps(w.file(q.get("path", [""])[0])).encode())
                if u.path in ("/auto", "/auto/status"):
                    return self._send(200, json.dumps(w.auto()).encode())
                if u.path == "/auto/page":
                    from . import webparts
                    return self._send(200, webparts.auto_page("/auto", w.token).encode(), "text/html; charset=utf-8")
                if u.path == "/talk":
                    return self._send(200, json.dumps(w.talk()).encode())
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
            if self.path.startswith("/auto/"):
                origin = self.headers.get("origin", "")
                if origin and origin != f"http://{self.headers.get('host', '')}":
                    return self._send(403, b'{"error": "origin"}')
                try:
                    got = w.auto_post(self.path, json.loads(body or b"{}"))
                except ValueError as exc:
                    return self._send(400, json.dumps({"error": str(exc)}).encode())
                w.tick(force=True)
                return self._send(200, json.dumps(got).encode())
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


def serve(root: Path, base_point: str = "checkpoint", port: int = 0, config_path: Optional[str] = None,
          interval: float = 2.0, ready=None, quiet: bool = False) -> None:
    """`port` 0: the first free one from 8765, shared with system-diff's engines (hub.py)."""
    w = Watcher(root, base_point, config_path, interval)
    server = None
    for p in ([port] if port else []) + [hub.first_free(), 0]:
        try:
            server = ThreadingHTTPServer(("127.0.0.1", p), handler(w))
            break
        except OSError:
            continue
    w.server = server
    port = server.server_address[1]
    url = f"http://localhost:{port}/"
    store.write(root, "web.json", {"port": port, "pid": os.getpid(), "id": w.ident})
    entry = hub.register(root, url, port, w.ident, __version__)
    threading.Thread(target=w.loop, daemon=True).start()
    if threading.current_thread() is threading.main_thread():   # `kill`: stop as Ctrl-C does, leaving no entry
        import signal
        signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown, daemon=True).start())
    if ready:
        ready(url, server, w)
    elif not quiet:
        print(f"research-diff watch: {url} (Ctrl-C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        hub.unregister(entry)
        w.stop.set()
        server.server_close()
