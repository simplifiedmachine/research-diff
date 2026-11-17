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


def file_html(o: dict, state: dict) -> str:
    """One research file: its outline (with the LLM's summary of each section, ✦) beside its text, the lines a number
    check found stale in red, the markers' lines lit."""
    if o.get("error"):
        return f"<p>{escape(o['error'])}</p>"
    s = o.get("summary") or {}
    bad = {n["line"]: n["why"] for c in o["chunks"] for n in c["numbers"] if n["sign"] == "-"}
    good = {n["line"] for c in o["chunks"] for n in c["numbers"] if n["sign"] == "+"}
    marked = {st["line"] for c in o["chunks"] for st in c["statements"]} | \
        {f["line"] for c in o["chunks"] for f in c["floats"]}
    say = {"done": "", "summarizing": "✦ Your LLM is summarising each section…", "off": "✦ " + state.get("why", ""),
           "failed": "✦ No summary: " + state.get("why", "")}.get(state.get("state", ""), "")
    left = [f"<h2>{escape(o['path'])}</h2>",
            f'<p class="sum">✦ {escape(s["file"])}</p>' if s.get("file") else f'<p class="muted">{escape(say)}</p>']
    for c in o["chunks"]:
        cs = (s.get("sections") or {}).get(c["title"], {})
        left.append(f'<div class="chunk" data-line="{c["line"]}"><b>{"&nbsp;" * 2 * (c["level"] - 1)}§ '
                    f'{escape(c["title"])}</b> <span class="muted">{c["line"]}–{c["end"]}</span>')
        for k in ("says", "claims", "watch"):
            if cs.get(k):
                left.append(f'<div class="{"watch" if k == "watch" else "sum"}">✦ {k}: {escape(cs[k])}</div>')
        for st in c["statements"]:
            left.append(f'<div class="st v-{st["verdict"] or "unsupported"}" data-line="{st["line"]}">'
                        f'<b>{escape(st["id"])}</b> {escape(st["title"][:90])} <i>{escape(st["verdict"])}</i></div>')
        for f in c["floats"]:
            left.append(f'<div class="st v-{f["verdict"] or "holds"}" data-line="{f["line"]}"><b>{escape(f["label"])}'
                        f'</b> {escape(f["caption"][:90])}</div>')
        for n in c["numbers"]:
            if n["sign"] == "-":
                left.append(f'<div class="bad" data-line="{n["line"]}">✗ {escape(n["why"])}</div>')
        left.append("</div>")
    right = []
    for i, line in enumerate(o["lines"], 1):
        cls = "bad" if i in bad else "mark" if i in marked else "ok" if i in good else ""
        tip = f' title="{escape(bad[i])}"' if i in bad else ""
        right.append(f'<div id="L{i}" class="ln {cls}"{tip}><span class="n">{i}</span>{escape(line) or " "}</div>')
    return f'<div class="file"><div class="outline">{"".join(left)}</div><div class="src">{"".join(right)}</div></div>'


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
  if (view === 'auto' && !part) { frame.innerHTML = ''; pic.innerHTML = ''; rows.style.whiteSpace = 'normal';
    await autoView(rows); return; }
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
async function post(path, body) {
  const r = await fetch(path, {method: 'POST', headers: {'x-token': TOKEN, 'content-type': 'application/json'},
    body: JSON.stringify(body || {})});
  const d = await r.json().catch(() => ({})); if (!r.ok) throw new Error(d.error || r.status); return d;
}
let stopArmed = false, checks = {};
async function autoView(el) {
  const d = await (await fetch('/auto')).json(), c = d.campaign || {}, on = ['running', 'paused', 'stopping'].includes(c.state);
  const srv = d.servers.map(s => `<tr><td><b>${esc(s.name)}</b></td><td>${esc(s.host)}</td><td>${esc(s.workdir || '(the repository)')}</td>
    <td>${s.gpus.length ? 'GPU ' + s.gpus.join(',') : 'CPU'}</td><td>${esc(s.setup || '')}</td>
    <td><button data-check="${esc(s.name)}">Check</button> <button data-rm="${esc(s.name)}">Remove</button>
    <div>${checks[s.name] || ''}</div></td></tr>`).join('');
  const exps = d.experiments.map(x => `<label><input type="checkbox" name="exp" value="${esc(x.id)}" ${x.run ? '' : 'disabled'}>
    ${esc(x.id)} ${esc(x.title)}${x.run ? '' : ' (no run:)'}</label>`).join(' ');
  let html = `<div class="ar"><div class="card"><h3>Servers</h3><div class="tbl"><table class="jobs"><tr><th>Name</th><th>Host</th>
    <th>Working directory</th><th>GPUs</th><th>Setup</th><th></th></tr>${srv || '<tr><td colspan="6" class="muted">None yet: add this machine (host: local) or an SSH host your keys reach.</td></tr>'}</table></div>
    <form id="addsrv" class="grid" style="margin-top:8px"><label>Name<input id="s_name" required placeholder="lab-gpu"></label>
    <label>Host<input id="s_host" required placeholder="local or user@host"></label><label>Port<input id="s_port" size="4" placeholder="22"></label>
    <label>Working directory<input id="s_dir" placeholder="~/runs"></label><label>GPUs<input id="s_gpus" size="8" placeholder="0,1,2,3"></label>
    <label>Setup<input id="s_setup" placeholder="source ~/venv/bin/activate"></label><button>Add server</button></form>
    <div class="muted">No password is asked or kept: an SSH host must already let your keys in (ssh -o BatchMode=yes).</div></div>`;
  if (!on) {
    html += `<div class="card"><h3>Start auto-research</h3>${c.state ? `<p class="muted">Last: <span class="badge s-${c.state}">${c.state}</span> ${esc(c.goal)}${c.summary ? ' — ' + esc(c.summary) : ''}</p>` : ''}
      <form id="start" class="grid"><label style="flex:1 1 100%">Goal<textarea id="a_goal" rows="2" required placeholder="Find out whether the gap closes with the learning rate scaled, and make the paper say so"></textarea></label>
      <label>Target (optional)<input id="a_target" size="34" placeholder="E2.results acc.batch512 > 0.88"></label>
      <label>Iterations<input id="a_max" type="number" min="1" value="5" style="width:5em"></label>
      <div style="flex:1 1 100%" class="muted">Servers: ${d.servers.map(s => `<label><input type="checkbox" name="srv" value="${esc(s.name)}" checked> ${esc(s.name)}</label>`).join(' ') || 'add one first'}</div>
      <div style="flex:1 1 100%" class="muted">First iteration (none ticked: Claude plans it): ${exps || 'no experiment yet'}</div>
      <button>Start</button></form><div class="err" id="a_err"></div></div>`;
  } else {
    html += `<div class="card"><h3><span class="badge s-${c.state}">${c.state}</span> ${esc(c.goal)}</h3>
      <div class="muted">target ${esc(c.target || 'none')} · iteration ${c.iterations.length} of ${c.max_iterations} · servers ${esc(c.servers.join(', '))} · runner ${d.runner ? 'on' : 'off (it starts by itself)'}</div>
      <div class="grid" style="margin-top:8px">${c.state === 'running' ? '<button data-ctl="pause">Pause</button>' : ''}
      ${c.state === 'paused' ? '<button data-ctl="resume">Resume</button>' : ''}
      <button data-ctl="stop" id="stopbtn">${stopArmed ? 'Confirm: stop and kill the running jobs' : 'Stop'}</button></div>
      ${d.pending ? `<p class="muted" style="margin-bottom:2px">Waiting for Claude${d.pending_told ? ' (handed to the session)' : ''}:</p><div class="ask">${esc(d.pending)}</div>` : ''}
      <div class="err" id="a_err"></div></div>`;
  }
  for (const it of (c.iterations || []).slice().reverse()) {
    const jobs = it.jobs.map(k => c.jobs[k]).map(j => `<tr><td>${j.id}</td><td><a href="#" data-zoom="${esc(j.experiment)}">${esc(j.experiment)}</a></td>
      <td class="s-${j.state}">${j.state}</td><td>${esc(j.server || '')}${j.gpus.length ? ' · GPU ' + j.gpus.join(',') : ''}</td>
      <td>${j.started ? Math.round(((j.ended || Date.now() / 1000) - j.started) / 60) + ' min' : ''}</td><td>${esc(j.why || '')}</td></tr>
      ${j.tail && (j.state === 'running' || j.state === 'failed') ? `<tr><td colspan="6"><pre class="tail">${esc(j.tail)}</pre></td></tr>` : ''}`).join('');
    html += `<div class="card"><h3>Iteration ${it.n} <span class="badge s-${it.state === 'analyse' ? 'paused' : it.state === 'running' ? 'running' : 'stopped'}">${it.state}</span></h3>
      ${it.reason ? `<div><b>Why:</b> ${esc(it.reason)}</div>` : ''}${it.analysis ? `<div><b>Claude's analysis:</b> ${esc(it.analysis)}</div>` : ''}
      <div class="tbl"><table class="jobs"><tr><th>Job</th><th>Experiment</th><th>State</th><th>Where</th><th>Time</th><th></th></tr>${jobs}</table></div></div>`;
  }
  if (c.events && c.events.length) html += `<div class="card"><h3>What happened</h3>${c.events.slice(-12).reverse().map(e =>
    `<div class="muted">${new Date(e.at * 1000).toLocaleTimeString()} · ${esc(e.text)}</div>`).join('')}</div>`;
  el.innerHTML = html + '</div>'; wire(el);
  const err = m => { const x = document.getElementById('a_err'); if (x) x.textContent = m; };
  const add = document.getElementById('addsrv');
  add.onsubmit = async e => { e.preventDefault(); const v = id => document.getElementById(id).value;
    try { await post('/auto/server', {name: v('s_name'), host: v('s_host'), port: v('s_port'), workdir: v('s_dir'),
      gpus: v('s_gpus'), setup: v('s_setup')}); await autoView(el); } catch (x) { alert_(x); } };
  const alert_ = x => { const b = document.createElement('div'); b.className = 'err'; b.textContent = String(x.message || x); add.after(b); };
  for (const b of el.querySelectorAll('[data-rm]')) b.onclick = async () => { await post('/auto/server/remove', {name: b.dataset.rm}); autoView(el); };
  for (const b of el.querySelectorAll('[data-check]')) b.onclick = async () => { b.textContent = 'Checking…';
    const r = await post('/auto/server/check', {name: b.dataset.check});
    checks[b.dataset.check] = r.ok ? `<span class="s-running">reachable</span>${r.gpus.length ? ' · ' + r.gpus.map(g => `GPU ${g.index} ${esc(g.name)} (${g.used}/${g.total} MiB)`).join(', ') +
      ` <button data-use="${esc(b.dataset.check)}" data-g="${r.gpus.map(g => g.index).join(',')}">Use these GPUs</button>` : ' · no GPU found (CPU jobs)'}`
      : `<span class="err">${esc(r.why)}</span>`;
    autoView(el); };
  for (const b of el.querySelectorAll('[data-use]')) b.onclick = async () => { const s = d.servers.find(x => x.name === b.dataset.use);
    await post('/auto/server', {...s, gpus: b.dataset.g}); delete checks[s.name]; autoView(el); };
  const st = document.getElementById('start');
  if (st) st.onsubmit = async e => { e.preventDefault();
    try { await post('/auto/start', {goal: document.getElementById('a_goal').value, target: document.getElementById('a_target').value,
      max_iterations: +document.getElementById('a_max').value, servers: [...el.querySelectorAll('[name=srv]:checked')].map(x => x.value),
      experiments: [...el.querySelectorAll('[name=exp]:checked')].map(x => x.value)}); autoView(el); } catch (x) { err(x.message); } };
  for (const b of el.querySelectorAll('[data-ctl]')) b.onclick = async () => {
    if (b.dataset.ctl === 'stop' && !stopArmed) { stopArmed = true; return autoView(el); }
    stopArmed = false; try { await post('/auto/control', {action: b.dataset.ctl}); } catch (x) { err(x.message); } autoView(el); };
}
setInterval(() => { if (view === 'auto' && !part && !file && !document.hidden && !document.activeElement.closest('form')) load(); }, 4000);
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
            self.tick()
            autoresearch.ensure_runner(self.root)     # the engine keeps the runner going while it is on
            self.stop.wait(self.interval)

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
        from . import autoresearch as ar
        st = ar.status(self.root)
        bp = compare.read(self.root, ".", self.config_path)[0]
        c = st["campaign"]
        it = c["iterations"][-1] if c.get("iterations") else {}
        return {**st, "pending_told": bool(it.get("told") or c.get("ask_told")),
                "experiments": [{"id": k, "title": n["title"], "run": n.get("run", "")} for k, n in bp["nodes"].items()
                                if n["kind"] == "experiment"]}

    def auto_post(self, path: str, d: dict) -> dict:
        """The Auto-research tab's buttons: a server added, checked or removed; start; pause, resume or stop."""
        from . import autoresearch as ar
        if path == "/auto/server":
            gpus = d.get("gpus", [])
            gpus = [int(g) for g in (gpus.split(",") if isinstance(gpus, str) else gpus) if str(g).strip()]
            return ar.save_server(self.root, str(d.get("name", "")), str(d.get("host", "")), str(d.get("workdir", "")),
                                  gpus, str(d.get("setup", "")), int(d.get("port") or 0))
        if path == "/auto/server/remove":
            return {"removed": ar.remove_server(self.root, str(d.get("name", "")))}
        if path == "/auto/server/check":
            s = next((x for x in ar.servers(self.root) if x["name"] == d.get("name")), None)
            if s is None:
                raise ValueError("no such server")
            return ar.check_server(self.root, s)
        if path == "/auto/start":
            c = ar.start(self.root, str(d.get("goal", "")), str(d.get("target", "")), int(d.get("max_iterations") or 5),
                         list(d.get("servers") or []) or None, list(d.get("experiments") or []) or None)
            return {"state": c["state"]}
        if path == "/auto/control":
            return {"state": ar.control(self.root, str(d.get("action", "")))["state"]}
        raise ValueError("unknown action")

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
                if u.path == "/auto":
                    return self._send(200, json.dumps(w.auto()).encode())
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
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}/"
    store.write(root, "web.json", {"port": port, "pid": os.getpid(), "id": w.ident})
    entry = hub.register(root, url, port, w.ident, __version__)
    threading.Thread(target=w.loop, daemon=True).start()
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
