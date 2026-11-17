"""Pages that serve both research-diff's own web page and the system-diff extension (research-diff inside
system-diff's page, framed under /x/research/): the Auto-research controls, and a research file opened
as its outline beside its text."""

from html import escape

AUTO_PAGE = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Auto-research</title>
<style>
:root{--bg:#f6f8fa;--panel:#fff;--ink:#1f2328;--muted:#57606a;--line:#d0d7de;--blue:#1565c0;--green:#2e7d32;
--amber:#b26a00;--red:#c62828;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--bg:#0d1117;--panel:#161b22;--ink:#e6edf3;--muted:#8d96a0;--line:#30363d;
--blue:#58a6ff;--green:#3fb950;--amber:#d29922;--red:#f85149;color-scheme:dark}}
body{margin:0;padding:12px 16px;background:var(--bg);color:var(--ink);font:14px/1.5 -apple-system,Segoe UI,Helvetica,Arial,sans-serif}
button{font:inherit;border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:16px;padding:3px 12px;cursor:pointer}
.muted{color:var(--muted);font-size:12px}
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
<div id="root"></div>
<script>
const TOKEN = "__TOKEN__", BASE = "__BASE__";
const esc = s => String(s).replace(/[<&>"]/g, c => ({'<':'&lt;','&':'&amp;','>':'&gt;','"':'&quot;'}[c]));
async function post(path, body) {
  const r = await fetch(path, {method: 'POST', headers: {'x-token': TOKEN, 'content-type': 'application/json'},
    body: JSON.stringify(body || {})});
  const d = await r.json().catch(() => ({})); if (!r.ok) throw new Error(d.error || r.status); return d;
}
let stopArmed = false, checks = {};
async function autoView(el) {
  const d = await (await fetch(BASE + '/status')).json(), c = d.campaign || {}, on = ['running', 'paused', 'stopping'].includes(c.state);
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
  el.innerHTML = html + '</div>';
  const err = m => { const x = document.getElementById('a_err'); if (x) x.textContent = m; };
  const add = document.getElementById('addsrv');
  add.onsubmit = async e => { e.preventDefault(); const v = id => document.getElementById(id).value;
    try { await post(BASE + '/server', {name: v('s_name'), host: v('s_host'), port: v('s_port'), workdir: v('s_dir'),
      gpus: v('s_gpus'), setup: v('s_setup')}); await autoView(el); } catch (x) { alert_(x); } };
  const alert_ = x => { const b = document.createElement('div'); b.className = 'err'; b.textContent = String(x.message || x); add.after(b); };
  for (const b of el.querySelectorAll('[data-rm]')) b.onclick = async () => { await post(BASE + '/server/remove', {name: b.dataset.rm}); autoView(el); };
  for (const b of el.querySelectorAll('[data-check]')) b.onclick = async () => { b.textContent = 'Checking…';
    const r = await post(BASE + '/server/check', {name: b.dataset.check});
    checks[b.dataset.check] = r.ok ? `<span class="s-running">reachable</span>${r.gpus.length ? ' · ' + r.gpus.map(g => `GPU ${g.index} ${esc(g.name)} (${g.used}/${g.total} MiB)`).join(', ') +
      ` <button data-use="${esc(b.dataset.check)}" data-g="${r.gpus.map(g => g.index).join(',')}">Use these GPUs</button>` : ' · no GPU found (CPU jobs)'}`
      : `<span class="err">${esc(r.why)}</span>`;
    autoView(el); };
  for (const b of el.querySelectorAll('[data-use]')) b.onclick = async () => { const s = d.servers.find(x => x.name === b.dataset.use);
    await post(BASE + '/server', {...s, gpus: b.dataset.g}); delete checks[s.name]; autoView(el); };
  const st = document.getElementById('start');
  if (st) st.onsubmit = async e => { e.preventDefault();
    try { await post(BASE + '/start', {goal: document.getElementById('a_goal').value, target: document.getElementById('a_target').value,
      max_iterations: +document.getElementById('a_max').value, servers: [...el.querySelectorAll('[name=srv]:checked')].map(x => x.value),
      experiments: [...el.querySelectorAll('[name=exp]:checked')].map(x => x.value)}); autoView(el); } catch (x) { err(x.message); } };
  for (const b of el.querySelectorAll('[data-ctl]')) b.onclick = async () => {
    if (b.dataset.ctl === 'stop' && !stopArmed) { stopArmed = true; return autoView(el); }
    stopArmed = false; try { await post(BASE + '/control', {action: b.dataset.ctl}); } catch (x) { err(x.message); } autoView(el); };
}
const root = document.getElementById('root');
autoView(root);
setInterval(() => { if (!document.hidden && !(document.activeElement && document.activeElement.closest('form'))) autoView(root); }, 4000);
</script>
"""


def auto_page(base: str, token: str = "") -> str:
    """The Auto-research controls; `base` where their JSON is (GET <base>/status, POST <base>/<action>)."""
    return AUTO_PAGE.replace("__TOKEN__", token).replace("__BASE__", base)


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


FILE_PAGE = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>__TITLE__</title>
<style>
:root{--bg:#f6f8fa;--panel:#fff;--ink:#1f2328;--muted:#57606a;--line:#d0d7de;--blue:#1565c0;--green:#2e7d32;
--amber:#b26a00;--red:#c62828;--redbg:#fdecea;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--bg:#0d1117;--panel:#161b22;--ink:#e6edf3;--muted:#8d96a0;--line:#30363d;
--blue:#58a6ff;--green:#3fb950;--amber:#d29922;--red:#f85149;--redbg:#3a1618;color-scheme:dark}}
body{margin:0;padding:12px 16px;background:var(--bg);color:var(--ink);font:14px/1.5 -apple-system,Segoe UI,Helvetica,Arial,sans-serif}
h2{font-size:15px;margin:0 0 6px}.muted{color:var(--muted);font-size:12px}
.file{display:flex;gap:14px;flex-wrap:wrap}.outline{flex:0 1 420px;min-width:0}.src{flex:1 1 560px;min-width:0;
.ln{white-space:pre;padding:0 10px}.ln .n{display:inline-block;width:3.5em;color:var(--muted);user-select:none}
.ln.bad{background:var(--redbg)}.ln.mark{background:rgba(21,101,192,.08)}.ln.ok{box-shadow:inset 3px 0 var(--green)}
.ln.flash{outline:2px solid var(--blue)}
.chunk{border-left:2px solid var(--line);padding:4px 0 8px 10px;margin-bottom:8px;cursor:pointer}
.sum{color:var(--muted);font-size:13px}.watch{color:var(--amber);font-size:13px}.bad{color:var(--red);font-size:13px}
.st{font-size:13px}.st i{font-style:normal;font-size:11.5px;color:var(--muted)}
.v-contradicted b{color:var(--red)}.v-contested b{color:var(--amber)}.v-supported b{color:var(--green)}
</style>
__BODY__
<script>
for (const el of document.querySelectorAll('.outline [data-line]')) el.onclick = e => { e.stopPropagation();
  const t = document.getElementById('L' + el.dataset.line); if (t) { t.scrollIntoView({block: 'center'});
  t.classList.add('flash'); setTimeout(() => t.classList.remove('flash'), 1200); } };
if (__WAIT__) setTimeout(() => location.reload(), 4000);
</script>
"""


def file_page(o: dict, state: dict) -> str:
    """A research file as a page of its own: its outline (✦ summaries) beside its text."""
    return (FILE_PAGE.replace("__TITLE__", escape(o.get("path", ""))).replace("__BODY__", file_html(o, state))
            .replace("__WAIT__", "true" if state.get("state") == "summarizing" else "false"))
