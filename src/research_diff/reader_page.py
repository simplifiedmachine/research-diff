"""The Read tab's page (served at /x/research/read, framed in the tab): the paper as text, its items marked, a panel
with each item's chain, its history and what the person can tell Claude or the agents. Self-contained: no
library, no request to anywhere but this engine, and every request relative to the page (the Studio frames it under
a path of its own).

What it gives the person, so they stay the one who knows the research while agents work on it: a card on hover for
anything marked, the whole chain behind it on a click (each step saying what it is and why it matters, its source a
click away), a trail back, the sections' state in the contents, filters that keep only what needs attention or what
changed since the checkpoint, and keys for all of it (Tab, Enter, Escape, j and k)."""
from __future__ import annotations

import json

# the dark colours, once: used when the system asks for dark (unless the person picked light) and when they pick dark
_DARK = """--bg:#10141b;--card:#171c25;--ink:#e3e8f0;--muted:#98a2b3;--line:#2b3340;--accent:#7aaaf7;--accbg:#1b2a44;
--ok:#56c78a;--okbg:#12301f;--bad:#ff8a80;--badbg:#3a1714;--warn:#f4b860;--warnbg:#3a2a10;--un:#9aa3b1;--unbg:#232a35;
--hl:#1a2232;--shadow:rgba(0,0,0,.5);color-scheme:dark"""

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Read</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#1c2230;--muted:#5b6577;--line:#dde2ea;--accent:#2457b8;--accbg:#e8effb;
--ok:#1d7a46;--okbg:#e5f4eb;--bad:#b42318;--badbg:#fdecea;--warn:#a15c00;--warnbg:#fff3df;--un:#6b7280;--unbg:#eef0f3;
--hl:#eef3fc;--shadow:rgba(16,24,40,.18);color-scheme:light;
--sans:-apple-system,"Segoe UI",Helvetica,Arial,sans-serif;--serif:Georgia,"Times New Roman",serif;
--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){__DARK__}}
:root[data-theme="dark"]{__DARK__}
*{box-sizing:border-box} [hidden]{display:none!important}
html,body{margin:0;height:100%;background:var(--bg);color:var(--ink);font:14px/1.5 var(--sans)}
body{display:flex;flex-direction:column;overflow:hidden}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
#bar{flex:none;z-index:5;display:flex;flex-wrap:wrap;gap:6px 8px;align-items:center;padding:8px 12px;
background:var(--card);border-bottom:1px solid var(--line)}
#counts{font-size:12px;color:var(--muted);flex-basis:100%;display:flex;flex-wrap:wrap;gap:2px 12px}
#counts b{color:var(--ink)} #counts .bad b{color:var(--bad)} #counts .warn b{color:var(--warn)}
.chip{border:1px solid var(--line);background:var(--bg);color:var(--ink);border-radius:999px;padding:3px 10px;
font:12px var(--sans);cursor:pointer;white-space:nowrap}
.chip[aria-pressed="true"]{border-color:var(--accent);color:var(--accent);background:var(--accbg);font-weight:600}
.chip .c{opacity:.75;margin-left:3px}
#q{flex:1;min-width:120px;max-width:280px;border:1px solid var(--line);border-radius:6px;padding:4px 8px;
background:var(--bg);color:var(--ink);font:13px var(--sans)}
#shown{font-size:12px;color:var(--muted)}
.spacer{flex:1}
button.act{border:0;border-radius:6px;padding:5px 10px;background:var(--accent);color:#fff;font:600 12px var(--sans);
cursor:pointer} button.act:disabled{opacity:.55;cursor:default}
button.ghost{background:transparent;color:var(--accent);border:1px solid var(--line)}
#tocBtn{display:none}
#wrap{flex:1;min-height:0;display:grid;grid-template-columns:220px minmax(0,1fr) 380px}
#toc{overflow:auto;border-right:1px solid var(--line);padding:8px 6px;font-size:13px}
#toc h2{font:600 11px var(--sans);text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin:4px 6px 6px}
#toc a{display:flex;gap:6px;align-items:baseline;padding:4px 6px;border-radius:6px;color:var(--ink);
text-decoration:none;border-left:3px solid transparent}
#toc a:hover{background:var(--card)} #toc a[aria-current="true"]{background:var(--accbg);border-left-color:var(--accent)}
#toc a.none{opacity:.4} #toc .t{flex:1;min-width:0;overflow-wrap:anywhere}
#toc .n{font-size:11px;color:var(--muted);white-space:nowrap} #toc .n .bad{color:var(--bad)} #toc .n .warn{color:var(--warn)}
#toc .chg{font:700 9px var(--sans);text-transform:uppercase;color:var(--warn);border:1px solid var(--warn);
border-radius:4px;padding:0 3px;align-self:center}
#toc .app{font-size:11px;color:var(--muted);margin:10px 6px 2px}
.dot{width:9px;height:9px;border-radius:50%;flex:none;background:var(--line);display:inline-block;align-self:center}
.dot.bad{background:var(--bad)} .dot.warn{background:var(--warn)} .dot.ok{background:var(--ok)}
#paper{overflow:auto;padding:14px 26px 80px;font:16px/1.65 var(--serif);position:relative}
#paper h2{font:600 19px var(--sans);margin:26px 0 8px;scroll-margin-top:8px}
#paper h3{font:600 15px var(--sans);margin:18px 0 6px} #paper h4{font:600 14px var(--sans);margin:14px 0 4px;color:var(--muted)}
#paper h2 .chip{margin-left:8px;vertical-align:middle}
.blk{scroll-margin:60px}
.para{margin:0 0 12px;padding:2px 8px;border-left:3px solid transparent;border-radius:4px;transition:background .12s}
.para.changed{border-left-color:var(--warn)} .blk.hl{background:var(--hl)} .blk.flash{animation:flash 1.2s}
@keyframes flash{0%{background:var(--accbg)}100%{background:transparent}}
.tag{font:600 10px var(--sans);text-transform:uppercase;letter-spacing:.04em;color:var(--warn);margin-right:6px}
.it{cursor:pointer;border-radius:4px}
.claim{font:600 11px var(--sans);padding:1px 6px;margin-right:6px;border:1px solid var(--line);background:var(--unbg);
color:var(--un);white-space:nowrap}
.claim.v-supported,.claim.v-holds{background:var(--okbg);color:var(--ok);border-color:transparent}
.claim.v-unsupported{background:transparent;color:var(--warn);border:1px dashed var(--warn)}
.claim.v-contradicted{background:var(--badbg);color:var(--bad);border-color:transparent}
.claim.v-contested{background:var(--warnbg);color:var(--warn);border-color:transparent}
.num{border-bottom:2px solid var(--un);padding:0 1px;border-radius:2px}
.num.ok{border-bottom-color:var(--ok)} .num.stale{border-bottom-color:var(--bad);background:var(--badbg)}
.num.unchecked{border-bottom-style:dotted}
.cite{font:12px var(--sans);color:var(--accent);padding:0 3px}
.ref{color:var(--accent);text-decoration:underline dotted;text-underline-offset:3px}
.m-sc{font-variant:small-caps} .m-link{text-decoration:underline} .m-note{color:var(--muted);font-size:.92em}
code.m-tt{font:.9em var(--mono)} .colored{font-weight:500}
.todo{background:var(--warnbg);outline:1px dashed var(--warn);border-radius:3px;padding:0 2px}
#paper h1.ptitle{font:700 22px/1.3 var(--sans);margin:6px 0 14px}
.para.display{text-align:center;font-style:italic}
.it.hov,.it.hot{outline:2px solid var(--accent);outline-offset:1px;background:var(--accbg)}
.num.stale.hov,.num.stale.hot{background:var(--badbg)}
.math{font-style:italic}
.float{margin:10px 0 16px;padding:10px 12px;border:1px solid var(--line);border-radius:8px;background:var(--card);
font:13px/1.5 var(--sans)} .float.hov,.float.hot{border-color:var(--accent);outline-offset:-1px}
.float .k{font-weight:700;margin-right:6px} .float.stale{border-left:4px solid var(--bad)}
.float figcaption{display:inline} .float .tw{overflow-x:auto;margin:8px 0 4px}
.float table{border-collapse:collapse;font:13px/1.4 var(--sans)}
.float th,.float td{padding:3px 9px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}
.float th{font-weight:600;border-bottom:2px solid var(--line)} .float tbody tr:last-child td{border-bottom:0}
img.fig{display:block;max-width:100%;max-height:360px;margin:8px auto;background:#fff;border-radius:4px}
img.step{display:block;max-width:100%;max-height:220px;margin:6px 0;background:#fff;border-radius:4px}
.float.changed{border-left:4px solid var(--warn)}
.sd{color:var(--muted);font-size:12px}
#loading,#failed,#nothing{font:14px/1.5 var(--sans);padding:30px 6px;color:var(--muted);max-width:560px}
.track{height:3px;background:var(--line);border-radius:2px;overflow:hidden;margin:10px 0}
.track i{display:block;height:100%;width:35%;background:var(--accent);border-radius:2px;animation:slide 1.3s ease-in-out infinite}
@keyframes slide{0%{transform:translateX(-100%)}100%{transform:translateX(300%)}}
#failed p{color:var(--bad)}
#panel{overflow:auto;border-left:1px solid var(--line);padding:12px 14px 40px;background:var(--card);font-size:13px}
#panel .top{display:flex;gap:6px;align-items:center;margin-bottom:6px}
#crumbs{flex:1;min-width:0;font-size:12px;color:var(--muted);display:flex;flex-wrap:wrap;gap:2px 4px;align-items:center}
#crumbs button{font:12px var(--sans);background:none;border:0;padding:0;color:var(--accent);cursor:pointer;
max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#crumbs [aria-current]{color:var(--ink);font-weight:600;max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
button.x{margin-left:auto;border:1px solid var(--line);background:var(--bg);color:var(--ink);border-radius:6px;
width:26px;height:26px;cursor:pointer;font:16px/1 var(--sans)}
#panel h1{font:600 16px var(--sans);margin:2px 0 4px;overflow-wrap:anywhere} #panel h1:focus{outline:none}
#panel .sum{color:var(--muted);margin:0 0 8px}
.badge{display:inline-block;font:600 11px var(--sans);border-radius:999px;padding:1px 8px;margin-left:6px;vertical-align:middle}
.badge.ok{background:var(--okbg);color:var(--ok)} .badge.stale{background:var(--badbg);color:var(--bad)}
.badge.mixed{background:var(--warnbg);color:var(--warn)} .badge.unchecked{background:var(--unbg);color:var(--un)}
ol.steps{list-style:none;margin:0;padding:0;counter-reset:s}
ol.steps>li{position:relative;padding:4px 0 10px 22px;border-left:2px solid var(--line);margin-left:7px}
ol.steps>li:last-child{border-left-color:transparent}
ol.steps>li::before{content:"";position:absolute;left:-7px;top:6px;width:12px;height:12px;border-radius:50%;
background:var(--card);border:2px solid var(--accent)} ol.steps>li.stale::before{border-color:var(--bad);background:var(--badbg)}
ol.steps>li.ok::before{border-color:var(--ok);background:var(--okbg)}
.kind{font:600 10px var(--sans);text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}
li.stale .kind{color:var(--bad)} li.ok .kind{color:var(--ok)}
.st{font-weight:600;overflow-wrap:anywhere} .why{color:var(--muted);font-size:12px;font-style:italic}
.links{display:flex;flex-wrap:wrap;gap:6px;margin-top:4px}
.links button,.links a,a.figlink{font:12px var(--sans);border:1px solid var(--line);background:var(--bg);color:var(--accent);
border-radius:5px;padding:2px 8px;cursor:pointer;text-decoration:none;display:inline-block}
.links button[aria-expanded="true"]{background:var(--accbg)}
details.preview{margin-top:8px;font-size:12px} details.preview summary{cursor:pointer;color:var(--muted)}
pre.msg{white-space:pre-wrap;overflow-wrap:anywhere;font:11.5px/1.45 var(--mono);background:var(--bg);
border:1px solid var(--line);border-radius:6px;padding:6px 8px;margin:6px 0 0;max-height:240px;overflow:auto}
pre.src{margin:6px 0 0;padding:6px 0;background:var(--bg);border:1px solid var(--line);border-radius:6px;
font:11.5px/1.45 var(--mono);overflow:auto;max-height:280px}
pre.msg{white-space:pre-wrap;overflow-wrap:anywhere;padding:6px 8px;max-height:220px} pre.src span{display:block;padding:0 8px;white-space:pre} pre.src span.here{background:var(--warnbg)}
pre.src i{color:var(--muted);font-style:normal;display:inline-block;width:3.4em;user-select:none}
.srcerr{color:var(--bad);font-size:12px;margin-top:4px}
h4.sub{font:600 12px var(--sans);text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin:16px 0 6px}
.hist{border-top:1px solid var(--line);padding:5px 0;font-size:12px} .hist b{font-weight:600}
label.lab{display:block;font-size:12px;color:var(--muted);margin-bottom:4px}
textarea{width:100%;min-height:58px;border:1px solid var(--line);border-radius:6px;padding:6px;background:var(--bg);
color:var(--ink);font:13px var(--sans);resize:vertical} .said{font-size:12px;min-height:16px;margin-top:4px}
.said.ok{color:var(--ok)} .said.bad{color:var(--bad)}
.empty{color:var(--muted);padding:24px 4px}
.keys{color:var(--muted);font-size:12px;margin-top:10px} kbd{font:11px var(--mono);border:1px solid var(--line);
border-bottom-width:2px;border-radius:4px;padding:0 4px;background:var(--bg)}
#tip{position:fixed;z-index:9;max-width:360px;background:var(--card);color:var(--ink);border:1px solid var(--line);
border-radius:8px;padding:8px 10px;font:12.5px/1.45 var(--sans);box-shadow:0 6px 24px var(--shadow);pointer-events:none}
#tip .pv{margin:4px 0 0;padding:0;list-style:none} #tip .pv li{color:var(--muted);font-size:12px;overflow:hidden;
text-overflow:ellipsis;white-space:nowrap} #tip .pv li::before{content:"→ "}
#tip .hint{margin-top:4px;font-size:11px;color:var(--accent)}
@media (max-width:1100px){#wrap{grid-template-columns:190px minmax(0,1fr) 330px}#paper{padding:12px 18px 80px}}
@media (max-width:900px){
#wrap{grid-template-columns:minmax(0,1fr)} #tocBtn{display:inline-block}
#toc{position:fixed;z-index:8;left:0;top:0;bottom:0;width:min(300px,85vw);background:var(--card);
box-shadow:0 0 30px var(--shadow);display:none} body.toc-open #toc{display:block}
#panel{position:fixed;z-index:7;left:0;right:0;bottom:0;max-height:72vh;border-left:0;border-top:1px solid var(--line);
border-radius:12px 12px 0 0;box-shadow:0 -6px 30px var(--shadow);display:none} body.panel-open #panel{display:block}
#paper{padding:10px 16px 80px}
#q{max-width:none}}
@media (prefers-reduced-motion:reduce){.track i,.blk.flash{animation:none}}
</style></head><body>
<div id="bar" role="toolbar" aria-label="Reading the paper">
<button class="chip" id="tocBtn" aria-controls="toc" aria-expanded="false">Sections</button>
<button class="chip" data-f="all" aria-pressed="true">All</button>
<button class="chip" data-f="attn" aria-pressed="false" title="Only stale numbers, contradicted or contested claims, stale tables and figures">Needs attention<span class="c"></span></button>
<button class="chip" data-f="changed" aria-pressed="false" title="Only what changed since the checkpoint (the last time it was marked as seen)">Changed since checkpoint<span class="c"></span></button>
<input id="q" type="search" placeholder="Find in the paper  ( / )" aria-label="Find in the paper">
<span id="shown" aria-live="polite"></span><span class="spacer"></span>
<button class="chip" id="theme" title="Light, dark or as the system says">Theme: auto</button>
<button class="act ghost" id="seen" title="Mark the research as seen (a checkpoint): what changes next is marked">Mark all as seen</button>
<div id="counts" aria-live="polite">Reading the paper…</div></div>
<div id="wrap"><nav id="toc" aria-label="Sections of the paper"><h2>Contents</h2><div id="tocList"></div></nav>
<main id="paper" aria-label="The paper" aria-busy="true"></main>
<aside id="panel" aria-label="What stands behind the item"><p class="empty">Click anything marked in the paper (a claim, a
number, a citation, a figure or a table) to see what stands behind it: the result it comes from, the script that makes
it, what supports or contradicts it, and who changed it.</p>
<p class="keys"><kbd>Tab</kbd> moves through what is marked, <kbd>Enter</kbd> opens it, <kbd>Esc</kbd> closes,
<kbd>j</kbd> / <kbd>k</kbd> go to the next / previous thing that needs attention or changed, <kbd>/</kbd> finds.</p></aside></div>
<div id="tip" role="tooltip" hidden></div>
<div id="say" class="sr" aria-live="assertive"></div>
<script>
const PART = __PART__;
const $ = id => document.getElementById(id);
const el = (t, cls, text) => { const e = document.createElement(t); if (cls) e.className = cls; if (text !== undefined && text !== null) e.textContent = text; return e; };
const qs = p => "part=" + encodeURIComponent(PART) + (p ? "&" + p : "");
const keep = { get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
               set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* no storage here */ } } };
let DATA = null, FILTER = "all", CRUMBS = [], ORIGIN = null, SECS = [], OPENSEQ = 0;
const ITEMS = new Map(), DONE = new Map();
const EMPTY = $("panel").innerHTML;
const say = t => { $("say").textContent = ""; setTimeout(() => { $("say").textContent = t; }, 30); };

// ---- talking to the engine: every path relative to this page ----
async function getJSON(u, opts) {
  let r, j = null;
  try { r = await fetch(u, Object.assign({ cache: "no-store" }, opts || {})); }
  catch (e) { throw new Error("the research-diff engine did not answer (is it still running?)"); }
  try { j = await r.json(); } catch (e) { j = null; }
  if (!r.ok) throw new Error((j && j.error) || "the engine answered " + r.status);
  if (j === null) throw new Error("the engine's answer could not be read");
  return j;
}
const post = body => getJSON("read/act?" + qs(), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
const key = (id, at) => at ? id + "@" + at : id;
function item(id, at) {          // one request per item (and per place, for a citation or reference used more than once), kept
  const k = key(id, at);
  if (!ITEMS.has(k)) {
    const p = getJSON("read/item?" + qs("id=" + encodeURIComponent(id) + (at ? "&at=" + encodeURIComponent(at) : "")));
    ITEMS.set(k, p);
    p.then(d => DONE.set(k, d), () => ITEMS.delete(k));
  }
  return ITEMS.get(k);
}

// ---- loading, and failing in words ----
let WAIT = 0;
function waiting() {
  const pap = $("paper"), box = el("div"); box.id = "loading"; box.setAttribute("role", "status");
  const t = el("div", null, "Reading the paper…"), bar = el("div", "track"); bar.append(el("i"));
  box.append(t, bar, el("div", "sd", "Its sections, the numbers it prints and the claims they carry, checked against the results."));
  pap.replaceChildren(box); pap.setAttribute("aria-busy", "true");
  const t0 = Date.now(); clearInterval(WAIT);
  WAIT = setInterval(() => { const s = Math.round((Date.now() - t0) / 1000);
    t.textContent = "Reading the paper… " + s + "s" + (s > 6 ? " (a long paper takes a while the first time)" : ""); }, 1000);
}
function failed(where, msg, retry) {
  clearInterval(WAIT);
  const box = el("div"); box.id = "failed"; box.setAttribute("role", "alert");
  box.append(el("p", null, where + ": " + msg + "."));
  const b = el("button", "act", "Try again"); b.onclick = retry; box.append(b);
  $("paper").replaceChildren(box); $("paper").setAttribute("aria-busy", "false");
  $("counts").textContent = "The paper could not be read.";
  b.focus();
}
async function load(quiet) {
  if (!quiet) waiting();
  let d;
  try { d = await getJSON("read/data?" + qs()); }
  catch (e) { if (quiet) { say("Could not read the paper again: " + e.message); return; } failed("Could not read the paper", e.message, () => load()); return; }
  clearInterval(WAIT);
  const top = $("paper").scrollTop;
  DATA = d; ITEMS.clear(); DONE.clear();
  counts(); render(); applyFilter();
  $("paper").setAttribute("aria-busy", "false");
  if (quiet) $("paper").scrollTop = top;
  watchPdf();
}
const plural = (n, one, many) => n + " " + (n === 1 ? one : many || one + "s");
function since() {               // what "changed" compares with, in words
  const cp = DATA.checkpoint || {};
  if (cp.set) return "since you marked it seen" + (cp.at ? " (" + new Date(cp.at * 1000).toLocaleString() + ")" : "");
  return "since the last commit (no checkpoint yet: “Mark all as seen” sets one)";
}
function counts() {
  const c = DATA.counts, box = $("counts"); box.replaceChildren();
  const one = (n, one_, many, cls) => { const s = el("span", n ? cls || "" : ""); s.append(el("b", null, String(n)), " " + (n === 1 ? one_ : many)); box.append(s); };
  one(c.claims, "claim", "claims"); one(c.contradicted, "contradicted", "contradicted", "bad"); one(c.contested, "contested", "contested", "warn");
  one(c.stale, "stale number", "stale numbers", "bad");
  if (c.todo) one(c.todo, "placeholder (a TODO, red text)", "placeholders (TODO, red text)", "warn");
  one(c.changed, "paragraph changed " + since(), "paragraphs changed " + since(), "warn");
  const p = el("span", "pdf"); box.append(p); pdfText();
}
function pdfText() {
  const p = $("counts").querySelector(".pdf"); if (!p || !DATA.pdf) return;
  const s = DATA.pdf.state;
  p.textContent = s === "ready" ? "PDF ready" : s === "building" ? "building the PDF…" : s === "failed" ? "the PDF did not build" :
    "no pdflatex: install MiKTeX or TeX Live for the PDF";
  if (s === "failed" && DATA.pdf.why) p.title = DATA.pdf.why;
}
let PDFT = 0;
function watchPdf() {            // while the PDF builds, ask again now and then; the text stays as it is
  clearTimeout(PDFT);
  if (!DATA.pdf || DATA.pdf.state !== "building") return;
  PDFT = setTimeout(async () => {
    try { const d = await getJSON("read/data?" + qs()); DATA.pdf = d.pdf; pdfText(); pdfButtons(); } catch (e) { /* the next try */ }
    watchPdf();
  }, 5000);
}
function pdfButtons() {
  if (!DATA.pdf || DATA.pdf.state !== "ready") return;
  for (const S of SECS) {
    if (S.h.querySelector(".chip")) continue;
    const s = S.s, b = el("button", "chip", "PDF ›"); b.title = "This section in the PDF (a new tab)";
    b.setAttribute("aria-label", "Open " + s.title + " in the PDF");
    b.onclick = () => window.open("pdf?" + new URLSearchParams({ main: DATA.pdf.main, file: s.file, line: s.line }), "_blank");
    S.h.append(b);
  }
}

// ---- the paper ----
const VERDICT = { supported: "supported", holds: "holds", contradicted: "contradicted", contested: "contested",
  unsupported: "no evidence yet" };
const VSYM = { supported: " ✓", holds: " ✓", contradicted: " ✗", contested: " ?", unsupported: " –" };
const NUMSTATE = { ok: "matches its result", stale: "stale: no longer matches its result", unchecked: "not checked against a result" };
function bad(c) { return c.verdict === "contradicted" || c.verdict === "contested"; }
function render() {
  const pap = $("paper"), toc = $("tocList"); pap.replaceChildren(); toc.replaceChildren(); SECS = [];
  if (!DATA.sections.length) {
    const n = el("div"); n.id = "nothing";
    n.append(el("p", null, "No paper in this study yet."), el("p", "sd", "A LaTeX file with \\section headings (or a research-diff.toml naming the paper) is read here."));
    pap.append(n); return;
  }
  let nattn = 0, nchg = 0, inApp = false;
  if (DATA.title) pap.append(el("h1", "ptitle", DATA.title));
  const isTitle = b => b.kind === "head" && b.level === 0;
  for (const s of DATA.sections) {
    if (s.blocks.every(isTitle)) continue;           // a front matter holding only the title: shown above
    const sec = el("section"); sec.setAttribute("aria-labelledby", s.id);
    const h = el("h2", null, (s.n ? s.n + " " : s.appendix ? "Appendix · " : "") + s.title); h.id = s.id;
    h.dataset.file = s.file; h.dataset.line = s.line; sec.append(h);
    const S = { s, sec, h, blocks: [], subs: [], a: null, contested: 0, contradicted: 0 };
    let sub = null;
    for (const b of s.blocks) {
      if (b.kind === "head") {
        if (isTitle(b) && b.text === DATA.title) continue;
        if (b.level > 1 || b.text !== s.title) { sub = { el: el(b.level >= 3 ? "h4" : "h3", null, (b.n ? b.n + " " : "") + b.text), any: false };
          sub.el.dataset.file = b.file; sub.el.dataset.line = b.line; S.subs.push(sub); sec.append(sub.el); }
        continue;
      }
      const node = b.kind === "float" ? floatBlock(b) : para(b);
      const attn = b.kind === "float" ? b.stale > 0 : (b.tokens.some(t => t.state === "stale") || b.claims.some(bad) || !!b.todo);
      if (b.kind === "para") for (const c of b.claims) { if (c.verdict === "contested") S.contested++; if (c.verdict === "contradicted") S.contradicted++; }
      nattn += attn ? 1 : 0; nchg += b.changed ? 1 : 0;
      S.blocks.push({ node, attn, changed: !!b.changed, sub, text: node.textContent.toLowerCase() });
      sec.append(node);
    }
    pap.append(sec);
    if (s.appendix && !inApp) { inApp = true; toc.append(el("div", "app", "Appendix")); }
    const a = el("a"); a.href = "#" + s.id;
    const state = s.stale || S.contradicted ? "bad" : S.contested ? "warn" : s.blocks.some(b => b.kind === "para" && b.claims.length) ? "ok" : "";
    a.append(el("span", "dot " + state), el("span", "t", (s.n ? s.n + " " : "") + s.title));
    if (s.changed) { const m = el("span", "chg", "new"); m.title = s.changed + " changed since the checkpoint"; a.append(m); }
    const n = el("span", "n");
    if (s.stale) n.append(el("span", "bad", "✗" + s.stale + " "));
    if (S.contradicted + S.contested) n.append(el("span", "warn", "?" + (S.contradicted + S.contested)));
    a.append(n);
    a.setAttribute("aria-label", s.title + ": " + [s.stale ? plural(s.stale, "stale number") : "", S.contradicted ? plural(S.contradicted, "contradicted claim") : "",
      S.contested ? plural(S.contested, "contested claim") : "", s.changed ? s.changed + " changed since the checkpoint" : ""].filter(Boolean).join(", ") || s.title);
    a.onclick = e => { e.preventDefault(); document.body.classList.remove("toc-open"); $("tocBtn").setAttribute("aria-expanded", "false");
      h.scrollIntoView({ block: "start" }); h.setAttribute("tabindex", "-1"); h.focus({ preventScroll: true }); };
    toc.append(a); S.a = a; S.n = n; SECS.push(S);
  }
  document.querySelector('.chip[data-f="attn"] .c').textContent = " " + nattn;
  document.querySelector('.chip[data-f="changed"] .c').textContent = " " + nchg;
  pdfButtons(); spy();
}
function mark(node, id, label) {
  node.dataset.id = id; node.tabIndex = 0; node.setAttribute("role", "button"); node.setAttribute("aria-label", label);
  node.classList.add("it");
}
// the paper's own styling: run-in titles and bold, italics, code, links; its colours (red for what is not done yet)
const MARKTAG = { runin: "b", b: "b", i: "i", tt: "code", u: "u" };
const COLOURS = { red: "var(--bad)", blue: "var(--accent)", green: "var(--ok)", orange: "var(--warn)", magenta: "var(--bad)" };
const REDS = new Set(["red", "magenta", "orange", "purple", "brickred", "redorange", "darkred"]);
const isTodo = t => (t.color || "").toLowerCase().split("!").some(x => REDS.has(x.trim())) || /\b(TODO|TBD|TBA|FIXME|XXX)\b|\?\?\?/.test(t.s);
function tokens(p, toks) {      // a run of the paper's tokens, each item marked: used by paragraphs, captions and table cells
  for (const t of toks) {
    if (t.t === "text") {
      const todo = isTodo(t);
      if (!t.mark && !t.color && !todo) { p.append(t.s); continue; }
      const e = el(MARKTAG[t.mark] || "span", t.mark ? "m-" + t.mark : null, t.s);
      if (t.color) { const c = t.color.toLowerCase().split("!")[0].trim();
        const css = COLOURS[c] || (window.CSS && CSS.supports("color", c) ? c : "");
        if (css) e.style.color = css; e.classList.add("colored"); e.title = "In " + t.color + " in the source"; }
      if (todo) { e.classList.add("todo", "attn"); e.tabIndex = -1; e.title = "A placeholder: not finished text"; }
      p.append(e); continue;
    }
    if (t.t === "math") { p.append(el("span", "math", t.s)); continue; }
    if (t.t === "num") { const s = el("span", "num " + t.state + (t.state === "stale" ? " attn" : ""), t.s); mark(s, t.id, "Number " + t.s + ", " + (NUMSTATE[t.state] || t.state)); p.append(s); continue; }
    if (t.t !== "cite" && t.t !== "ref") { if (t.s) p.append(t.s); continue; }
    const s = el("span", t.t, t.t === "cite" ? "[" + t.s + "]" : t.s);
    if (t.at) s.dataset.at = t.at;
    mark(s, t.id, t.t === "cite" ? "Citation " + t.s : "Reference to " + t.s + " (" + t.key + ")"); p.append(s);
  }
}
function para(b) {
  const p = el("p", "para blk" + (b.changed ? " changed" : "") + (b.display ? " display" : "")); p.dataset.file = b.file; p.dataset.line = b.line;
  p.dataset.end = b.end || b.line; p.tabIndex = -1;
  if (b.depth) p.style.marginLeft = (1.4 * b.depth) + "em";
  p.title = b.file + ":" + b.line + (b.changed ? " · changed since the checkpoint" : "");
  if (b.changed) p.append(el("span", "tag", "changed"));
  for (const c of b.claims) {
    const s = el("span", "claim v-" + (c.verdict || "none") + (bad(c) ? " attn" : ""), c.id + (VSYM[c.verdict] || ""));
    mark(s, c.id, "Claim " + c.id + (c.title ? ": " + c.title : "") + (c.verdict ? ", " + (VERDICT[c.verdict] || c.verdict) : ", no verdict yet"));
    p.append(s);
  }
  tokens(p, b.tokens);
  return p;
}
const RASTER = /\.(png|jpe?g|gif|webp)$/i;
const fileUrl = f => "read/file?" + qs("path=" + encodeURIComponent(f));
function floatBlock(b) {
  const rows = b.rows || [];
  const d = el("figure", "float blk" + (b.stale ? " stale" + (rows.length ? "" : " attn") : "") + (b.changed ? " changed" : ""));
  d.dataset.file = b.file; d.dataset.line = b.line; d.dataset.end = b.end || b.line; d.tabIndex = -1; d.style.margin = "10px 0 16px";
  const name = (b.float === "figure" ? "Figure" : "Table") + (b.n ? " " + b.n : "");
  const cap = el("figcaption"), k = el("span", "k", name);
  if (b.label) k.title = b.label;
  mark(k, b.id, name + (b.label ? " (" + b.label + ")" : "") + (b.caption ? ": " + b.caption.slice(0, 80) : "") + (b.stale ? ", " + plural(b.stale, "stale number") : ""));
  cap.append(k);
  if (b.tokens && b.tokens.length) tokens(cap, b.tokens); else cap.append(b.caption || "");
  if (b.float !== "figure") d.append(cap);
  if (b.image && RASTER.test(b.image)) { const img = el("img", "fig"); img.src = fileUrl(b.image); img.loading = "lazy"; img.alt = name + (b.caption ? ": " + b.caption : ""); d.append(img); }
  else if (b.image && /\.pdf$/i.test(b.image)) { const a = el("a", "figlink", "Open the figure (" + b.image.split("/").pop() + ") ›"); a.href = fileUrl(b.image); a.target = "_blank"; a.rel = "noopener"; d.append(a, " "); }
  if (rows.length) {
    const wrap = el("div", "tw"), tb = el("table"); let head = null, body = null;
    for (const r of rows) {
      const tr = el("tr");
      for (const c of r.cells) { const td = el(r.head ? "th" : "td"); if (r.head) td.scope = "col"; tokens(td, c); tr.append(td); }
      if (r.head) { if (!head) { head = el("thead"); tb.append(head); } head.append(tr); }
      else { if (!body) { body = el("tbody"); tb.append(body); } body.append(tr); }
    }
    wrap.append(tb); d.append(wrap);
  }
  if (b.float === "figure") d.append(cap);
  const meta = [b.ok ? "✓ " + plural(b.ok, "number matches", "numbers match") : "", b.stale ? "✗ " + b.stale + " stale" : "", b.changed ? "changed since the checkpoint" : "",
                b.graphics && !b.image ? "image " + b.graphics + " (no such file)" : "", (b.inputs || []).join(", ")].filter(Boolean).join(" · ");
  if (meta) d.append(el("div", "sd", meta));
  return d;
}

// ---- filters and finding: what does not match is hidden, and counted ----
function applyFilter() {
  if (!SECS.length) { $("shown").textContent = ""; return; }
  const needle = $("q").value.trim().toLowerCase(), on = FILTER !== "all" || !!needle;
  let shown = 0, total = 0;
  for (const S of SECS) {
    let any = 0; for (const sub of S.subs) sub.any = false;
    for (const b of S.blocks) {
      total++;
      const ok = (FILTER === "all" || (FILTER === "attn" && b.attn) || (FILTER === "changed" && b.changed)) && (!needle || b.text.includes(needle));
      b.node.hidden = !ok; if (ok) { shown++; any++; if (b.sub) b.sub.any = true; }
    }
    for (const sub of S.subs) sub.el.hidden = on && !sub.any;
    S.sec.hidden = on && !any; S.a.classList.toggle("none", on && !any);
  }
  let none = $("nomatch");
  if (on && !shown) {
    if (!none) { none = el("p", "empty"); none.id = "nomatch"; $("paper").prepend(none); }
    none.textContent = needle ? "Nothing in the paper matches “" + $("q").value.trim() + "”" + (FILTER !== "all" ? " under this filter." : ".")
      : FILTER === "attn" ? "Nothing needs attention: every checked number matches and no claim is contradicted or contested." : "Nothing changed since the checkpoint.";
  } else if (none) none.remove();
  $("shown").textContent = on ? "Showing " + shown + " of " + total : "";
  spy();
}
for (const b of document.querySelectorAll(".chip[data-f]")) b.onclick = () => {
  FILTER = b.dataset.f; document.querySelectorAll(".chip[data-f]").forEach(x => x.setAttribute("aria-pressed", String(x === b)));
  if (DATA) { applyFilter(); $("paper").scrollTop = 0; }
};
let QT = 0; $("q").oninput = () => { clearTimeout(QT); QT = setTimeout(() => DATA && applyFilter(), 150); };

// ---- the contents: the section in view ----
let SPY = 0;
function spy() {
  cancelAnimationFrame(SPY);
  SPY = requestAnimationFrame(() => {
    const top = $("paper").getBoundingClientRect().top + 60; let cur = null;
    for (const S of SECS) { if (S.sec.hidden) continue; if (S.h.getBoundingClientRect().top <= top) cur = S; else break; }
    cur = cur || SECS.find(S => !S.sec.hidden);
    for (const S of SECS) { if (S === cur) { if (S.a.getAttribute("aria-current") !== "true") { S.a.setAttribute("aria-current", "true"); S.a.scrollIntoView({ block: "nearest" }); } } else S.a.removeAttribute("aria-current"); }
  });
}
$("paper").addEventListener("scroll", spy, { passive: true });
$("tocBtn").onclick = () => { const o = document.body.classList.toggle("toc-open"); $("tocBtn").setAttribute("aria-expanded", String(o)); if (o) { const a = $("tocList").querySelector("a"); if (a) a.focus(); } };

// ---- hover (or focus): highlight the item and its paragraph, a card at once ----
let HOV = null, HOVT = 0;
function enter(t) {
  if (HOV === t) return; leave(); HOV = t;
  t.classList.add("hov"); const blk = t.closest(".blk"); if (blk) blk.classList.add("hl");
  const id = t.dataset.id, at = t.dataset.at || ""; clearTimeout(HOVT);
  if (DONE.has(key(id, at))) { card(t, DONE.get(key(id, at))); return; }
  card(t, null);
  HOVT = setTimeout(() => item(id, at).then(d => { if (HOV === t) card(t, d); }, () => { if (HOV === t) card(t, null, true); }), 120);
}
function leave() {
  clearTimeout(HOVT); const t = HOV; HOV = null; $("tip").hidden = true;
  if (!t) return; t.classList.remove("hov"); t.removeAttribute("aria-describedby");
  const blk = t.closest(".blk"); if (blk) blk.classList.remove("hl");
}
function card(t, d, broke) {
  const tip = $("tip"); tip.replaceChildren();
  if (d) {
    const b = el("b", null, d.title); tip.append(b);
    if (d.state) tip.append(el("span", "badge " + d.state, STATEWORD[d.state] || d.state));
    if (d.summary) tip.append(el("div", "sd", d.summary.length > 220 ? d.summary.slice(0, 220) + "…" : d.summary));
    const steps = (d.steps || []).slice(1, 4);
    if (steps.length) { const ul = el("ul", "pv"); for (const s of steps) ul.append(el("li", null, s.title)); tip.append(ul); }
  } else {
    tip.append(el("b", null, t.getAttribute("aria-label")));
    tip.append(el("div", "sd", broke ? "Could not read what stands behind it (click to try again)" : "Reading what stands behind it…"));
  }
  tip.append(el("div", "hint", "Click or Enter: the whole chain behind it"));
  t.setAttribute("aria-describedby", "tip"); tip.hidden = false;
  const r = t.getBoundingClientRect(), w = tip.offsetWidth, h = tip.offsetHeight;
  tip.style.left = Math.max(8, Math.min(r.left, innerWidth - w - 8)) + "px";
  tip.style.top = (r.bottom + 8 + h > innerHeight && r.top - h - 8 > 0 ? r.top - h - 8 : r.bottom + 6) + "px";
}
const PAP = $("paper");
PAP.addEventListener("mouseover", e => { const t = e.target.closest(".it"); if (t) enter(t); else if (HOV && !HOV.contains(e.target)) leave(); });
PAP.addEventListener("mouseleave", () => { if (HOV && document.activeElement !== HOV) leave(); });
PAP.addEventListener("focusin", e => { const t = e.target.closest(".it"); if (t) enter(t); });
PAP.addEventListener("focusout", e => { if (HOV && e.target === HOV) leave(); });
PAP.addEventListener("scroll", () => { if (HOV && document.activeElement !== HOV) leave(); }, { passive: true });
PAP.addEventListener("click", e => { const t = e.target.closest(".it"); if (t) fromPaper(t); });
PAP.addEventListener("keydown", e => { const t = e.target.closest && e.target.closest(".it");
  if (t && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); fromPaper(t); } });
function fromPaper(t) {
  document.querySelectorAll(".it.hot").forEach(x => x.classList.remove("hot")); t.classList.add("hot");
  ORIGIN = t; leave(); show(t.dataset.id, "new", t.dataset.at || "");
}

// ---- the panel: the chain, step by step ----
const STATEWORD = { ok: "matches", stale: "stale", mixed: "contested", unchecked: "not checked" };
const PLAIN = new Set(["where the paper says it", "in the paper", "the file the figure shows", "the script that names it",
  "what the table prints", "what the result is of", "its command (auto-research launches it)", "what the command runs", "where",
  "its command", "for it", "against it", "a number it holds", "the number it was checked against",
  "what it points at", "another place the paper says it", "where to read it"]);
function what(s, i) {           // [what the step is, why it matters to someone judging the paper]
  const t = s.title, d = s.detail || "";
  if (t.startsWith("Printed: ")) return ["In the paper", "The value a reader sees; it is only as good as the result below it."];
  if (t.startsWith("Result ")) return ["Result", s.state === "stale" ? "The number the paper is checked against: it no longer says what the paper prints." : "The number the paper is checked against; when it changes, the paper goes stale."];
  if (t.startsWith("Experiment ")) return ["Experiment", "What produced the result: its settings decide the number."];
  if (t.startsWith("Run: ")) return ["Command", "How the result is made again; auto-research or an agent runs exactly this."];
  if (t.startsWith("Script: ")) return ["Script", "The code that computes it: read it to judge the method, not only the number."];
  if (t.startsWith("Written by ") || t.startsWith("Made by ")) return ["Script", "The code that writes this file: change it and the paper's number moves."];
  if (t.startsWith("Image: ")) return ["Image file", "What the figure shows; it is redrawn only when its script runs again."];
  if (t.startsWith("Table file: ")) return ["Table file", "The numbers the table prints, as a file of their own."];
  if (t.startsWith("Cited here: ")) return ["Citation", "The place you clicked: where the paper leans on outside work."];
  if (t.startsWith("Also cited at ")) return ["Also cited", "Another place the paper leans on the same work."];
  if (t.startsWith("Referred to here: ")) return ["Cross-reference", "The place you clicked."];
  if (t.startsWith("Also referred to at ")) return ["Also referred to", "Another place the paper points at the same thing."];
  if (d === "what it points at") return ["What it points at", "Go to it to read what the paper sends the reader to."];
  if (s.url) return ["The cited work", "Read the source itself: what the paper says it says should be there."];
  if (t.startsWith("Read by ")) return ["Script that reads it", "It uses the file; it does not make it. The code that writes it, if found, is above."];
  if (t.startsWith("Names it: ")) return ["Script naming it", "It mentions the file; open it to see whether it makes it."];
  const rel = /^\S+ (relies on|contradicts|weakens|supports|answers|tests|shows|of) \S+/.exec(t);
  if (rel && i > 0) return [rel[1] === "contradicts" || rel[1] === "weakens" ? "Argues against" : "Rests on",
    rel[1] === "contradicts" || rel[1] === "weakens" ? "What this claim argues against: if it holds, that one is in doubt." : "What this claim says it rests on: if that falls, so does this."];
  if (t.startsWith("Cited: ")) return ["Citation", "Where the paper leans on outside work."];
  if (t.startsWith("Backs ")) return ["Claim it backs", "What would weaken if this source were wrong or misread."];
  if (t.startsWith("Refers to ")) return ["Cross-reference", ""];
  if (t === "Open it") return ["Its target", ""];
  if (t.startsWith("Of ")) return ["Results it prints", "Where the table's numbers come from."];
  if (t.startsWith("✗ ")) return d === "against it" ? ["Against", "Evidence that contradicts it: the reason to look before an agent builds on it."]
    : ["Stale number", "Printed in the table, no longer what its result says."];
  if (t.startsWith("✓ ")) return ["For", "Evidence that supports it."];
  if (/^(Figure|Table)\b/.test(t) && i === 0) return ["In the paper", ""];
  if (/^\S+ = /.test(t)) return ["Number it holds", ""];
  if (i === 0) return ["The item", ""];
  return ["Link", ""];
}
function panelTop(pan) {
  const top = el("div", "top");
  const nav = el("nav"); nav.id = "crumbs"; nav.setAttribute("aria-label", "Trail");
  if (CRUMBS.length > 1) {
    const back = el("button", null, "‹ Back"); back.onclick = () => { CRUMBS.pop(); const c = CRUMBS[CRUMBS.length - 1]; show(c.id, "crumb", c.at); }; nav.append(back, " · ");
    CRUMBS.forEach((x, i) => {
      if (i) nav.append(" › ");
      if (i === CRUMBS.length - 1) { const c = el("span", null, x.title); c.setAttribute("aria-current", "page"); c.title = x.title; nav.append(c); return; }
      const b = el("button", null, x.title); b.title = x.title; b.onclick = () => { CRUMBS = CRUMBS.slice(0, i + 1); show(x.id, "crumb", x.at); }; nav.append(b);
    });
  }
  const x = el("button", "x", "×"); x.setAttribute("aria-label", "Close the details (Escape)"); x.onclick = closePanel;
  top.append(nav, x); pan.append(top);
}
async function show(id, mode, at) {
  at = at || "";
  const seq = ++OPENSEQ, pan = $("panel"); document.body.classList.add("panel-open");
  if (!DONE.has(key(id, at))) { pan.replaceChildren(); panelTop(pan); const w = el("div", "empty"); w.setAttribute("role", "status");
    w.append("Reading what stands behind it…", el("div", "track")); w.lastChild.append(el("i")); pan.append(w); }
  let d;
  try { d = await item(id, at); }
  catch (e) {
    if (seq !== OPENSEQ) return;
    pan.replaceChildren(); panelTop(pan);
    const box = el("div"); box.setAttribute("role", "alert");
    box.append(el("p", "said bad", "Could not read what stands behind " + id + ": " + e.message + "."));
    const b = el("button", "act", "Try again"); b.onclick = () => show(id, mode, at); box.append(b); pan.append(box); return;
  }
  if (seq !== OPENSEQ) return;
  if (mode === "new") CRUMBS = [{ id, at, title: d.title }];
  else if (mode === "push") { if (!CRUMBS.length || CRUMBS[CRUMBS.length - 1].id !== id) CRUMBS.push({ id, at, title: d.title }); }
  paint(id, d, at);
}
function flash(node) {           // bring a place of the paper into view, showing it whatever the filter
  const blk = node.closest(".blk") || node;
  if (node.closest("[hidden]")) { FILTER = "all"; $("q").value = ""; document.querySelectorAll(".chip[data-f]").forEach(x => x.setAttribute("aria-pressed", String(x.dataset.f === "all"))); applyFilter(); }
  node.scrollIntoView({ block: "center" });
  blk.classList.remove("flash"); void blk.offsetWidth; blk.classList.add("flash");
  if (node.tabIndex < 0 && !node.hasAttribute("tabindex")) node.setAttribute("tabindex", "-1");
  node.focus({ preventScroll: true });
}
function placeOf(file, line) {   // the heading or block of the paper that holds a file's line (a section, a figure, an equation)
  let best = null, span = Infinity;
  for (const n of PAP.querySelectorAll("[data-file]")) {
    if (n.dataset.file !== file) continue;
    const lo = +n.dataset.line, hi = +(n.dataset.end || n.dataset.line);
    if (lo <= line && line <= hi && hi - lo < span) { best = n; span = hi - lo; }
  }
  return best;
}
const BINARY = /\.(pdf|png|jpe?g|gif|webp|svg|eps|pt|pth|ckpt|npy|npz|pkl|parquet|h5|zip|gz)$/i;
function paint(id, d, at) {
  const pan = $("panel"); pan.replaceChildren(); pan.scrollTop = 0; panelTop(pan);
  const h = el("h1", null, d.title); h.tabIndex = -1;
  if (d.state) h.append(el("span", "badge " + d.state, STATEWORD[d.state] || d.state));
  pan.append(h);
  if (d.summary) pan.append(el("p", "sum", d.summary));
  const sel = '.it[data-id="' + CSS.escape(id) + '"]';
  const inPaper = (at && PAP.querySelector(sel + '[data-at="' + CSS.escape(at) + '"]')) || PAP.querySelector(sel);
  const row0 = el("div", "links");
  if (inPaper) { const b = el("button", null, "Show it in the paper"); b.onclick = () => {
    document.querySelectorAll(".it.hot").forEach(x => x.classList.remove("hot")); inPaper.classList.add("hot"); flash(inPaper); }; row0.append(b); }
  if (row0.childNodes.length) pan.append(row0);
  if (d.steps && d.steps.length) {
    pan.append(el("h4", "sub", "What stands behind it"));
    const ol = el("ol", "steps"); ol.setAttribute("aria-label", "The chain behind " + d.title);
    d.steps.forEach((s, i) => {
      const [kind, why] = what(s, i), li = el("li", s.state || "");
      li.append(el("div", "kind", kind + (s.state === "stale" ? " · does not hold" : s.state === "ok" ? " · holds" : "")), el("div", "st", s.title));
      if (s.detail && !PLAIN.has(s.detail)) li.append(el("div", "sd", s.detail));
      if (why) li.append(el("div", "why", why));
      if (s.file && RASTER.test(s.file)) { const img = el("img", "step"); img.src = fileUrl(s.file); img.loading = "lazy"; img.alt = s.title; li.append(img); }
      const links = el("div", "links");
      if (s.url) { const a = el("a", null, "Open the paper ›"); a.href = s.url; a.target = "_blank"; a.rel = "noopener noreferrer"; a.title = s.url; links.append(a); }
      if (s.go && s.file) { const target = placeOf(s.file, s.line || 1);
        if (target) { const b = el("button", null, "Go to it in the paper"); b.onclick = () => flash(target); links.append(b); } }
      if (s.file && BINARY.test(s.file)) {
        if (/\.(pdf|png|jpe?g|gif|webp)$/i.test(s.file)) { const a = el("a", null, "Open " + s.file.split("/").pop() + " ›"); a.href = fileUrl(s.file); a.target = "_blank"; a.rel = "noopener"; links.append(a); }
      } else if (s.file) { const b = el("button", null, "Source: " + s.file.split("/").pop() + (s.line ? ":" + s.line : "")); b.title = s.file + (s.line ? ":" + s.line : "");
        b.setAttribute("aria-expanded", "false"); b.onclick = () => source(li, s.file, s.line || 1, b); links.append(b); }
      if (s.item && s.item !== id) { const b = el("button", null, "Open " + s.item + " ›"); b.title = "What stands behind " + s.item; b.onclick = () => show(s.item, "push"); links.append(b); }
      if (links.childNodes.length) li.append(links);
      ol.append(li);
    });
    pan.append(ol);
  } else pan.append(el("p", "sd", "Nothing in the research stands behind it yet."));
  if (d.history && d.history.length) {
    pan.append(el("h4", "sub", "What changed it"));
    for (const x of d.history) { const r = el("div", "hist"); r.append(el("b", null, new Date(x.at * 1000).toLocaleString() + (x.who ? " · " + x.who : "")), el("div", null, x.what)); if (x.got) r.append(el("div", "sd", x.got)); pan.append(r); }
  }
  const acts = d.actions || [], says = d.say || {};
  if (acts.length) {
    pan.append(el("h4", "sub", "Steer"));
    const lab = el("label", "lab", "What you want Claude or the agents to know or do about this"); lab.htmlFor = "steer";
    const ta = el("textarea"); ta.id = "steer"; ta.placeholder = "e.g. check the seed before trusting this number";
    const row = el("div", "links"), said = el("div", "said"); said.setAttribute("role", "status");
    // what a button sends, shown before it is sent: the part quoted from the repository, then the person's words
    const full = a => { const s = says[a]; if (!s) return ""; const w = ta.value.trim() || s[1] || ""; return s[0] + (w ? "\n\n" + w : ""); };
    const prev = el("details", "preview"), sum = el("summary", null, "What Ask Claude sends"), pre = el("pre", "src msg");
    prev.append(sum, pre);
    const showMsg = a => { sum.textContent = a === "rerun" ? "What the rerun request sends" : "What Ask Claude sends"; pre.textContent = full(a); prev.dataset.a = a; };
    ta.addEventListener("input", () => { if (prev.dataset.a) showMsg(prev.dataset.a); });
    const act = (a, label, title) => { const b = el("button", "act", label); if (title) b.title = title;
      b.onfocus = b.onmouseenter = () => { if (says[a]) showMsg(a); };
      b.onclick = async () => {
      b.disabled = true; said.className = "said"; said.textContent = "Sending…";
      try { const j = await post({ action: a, id, at, text: ta.value }); said.className = "said " + (j.ok ? "ok" : "bad"); said.textContent = j.said || j.error || ""; if (j.ok) ta.value = ""; }
      catch (e) { said.className = "said bad"; said.textContent = "Not sent: " + e.message; }
      b.disabled = false; }; row.append(b); };
    if (acts.includes("ask")) act("ask", "Ask Claude", "Sends the text below to Claude's session");
    if (acts.includes("guide")) act("guide", "Tell the agents", "Puts what you write on the agents' bus");
    const r = d.rerun;
    if (acts.includes("rerun") && r) act("rerun", "Ask Claude to rerun " + r.of, "Claude is asked to run: " + r.run);
    pan.append(lab, ta, row);
    if (acts.includes("rerun") && r) { const c = el("div", "sd"); c.append("Rerun runs ", el("code", "m-tt", r.run), " (from " + r.of + "'s config)"); pan.append(c); }
    if (says.ask || says.rerun) { showMsg(says.ask ? "ask" : "rerun"); pan.append(prev); }
    pan.append(said);
  }
  h.focus({ preventScroll: true });
}
async function source(li, file, line, btn) {
  const old = li.querySelector("pre.src,.srcerr"); if (old) { old.remove(); btn.setAttribute("aria-expanded", "false"); return; }
  btn.setAttribute("aria-expanded", "true"); const label = btn.textContent; btn.textContent = "Reading " + file.split("/").pop() + "…";
  try {
    const s = await getJSON("read/source?" + qs("path=" + encodeURIComponent(file) + "&line=" + line));
    if (s.binary) { li.append(el("div", "srcerr", file + " is not text: nothing to show as lines.")); btn.textContent = label; return; }
    const pre = el("pre", "src"); pre.tabIndex = 0; pre.setAttribute("aria-label", file + " around line " + s.line);
    s.lines.forEach((t, i) => { const n = s.lo + i, sp = el("span", n === s.line ? "here" : ""); sp.append(el("i", null, String(n)), t); pre.append(sp); });
    li.append(pre); const here = pre.querySelector(".here"); if (here) pre.scrollTop = here.offsetTop - 40;
  } catch (e) { li.append(el("div", "srcerr", "Could not show " + file + ": " + e.message)); }
  btn.textContent = label;
}
function closePanel() {
  OPENSEQ++; CRUMBS = []; document.body.classList.remove("panel-open"); $("panel").innerHTML = EMPTY;
  document.querySelectorAll(".it.hot").forEach(x => x.classList.remove("hot"));
  if (ORIGIN && document.contains(ORIGIN)) ORIGIN.focus({ preventScroll: true }); ORIGIN = null;
}

// ---- keys ----
function jump(dir) {
  const stops = [...PAP.querySelectorAll(".attn, .blk.changed")].filter(x => !x.closest("[hidden]"));
  if (!stops.length) { say(FILTER === "all" ? "Nothing needs attention or changed." : "Nothing more under this filter."); return; }
  const cur = PAP.contains(document.activeElement) ? document.activeElement : null; let next;
  if (cur) {
    const after = x => !!(cur.compareDocumentPosition(x) & Node.DOCUMENT_POSITION_FOLLOWING);   // what it holds comes after it
    next = dir > 0 ? stops.find(after) : [...stops].reverse().find(x => x !== cur && !after(x));
  } else {
    const top = PAP.getBoundingClientRect().top;
    next = dir > 0 ? stops.find(x => x.getBoundingClientRect().top > top + 4) : [...stops].reverse().find(x => x.getBoundingClientRect().top < top - 4);
  }
  if (!next) { say(dir > 0 ? "That was the last one." : "That was the first one."); return; }
  next.scrollIntoView({ block: "center" }); next.focus({ preventScroll: true });
  const blk = next.closest(".blk"); if (blk && !next.classList.contains("it")) { blk.classList.remove("flash"); void blk.offsetWidth; blk.classList.add("flash"); say("A paragraph changed since the checkpoint"); }
}
addEventListener("keydown", e => {
  const typing = e.target.closest && e.target.closest("input,textarea,select,[contenteditable]");
  if (e.key === "Escape") {
    if (e.target === $("q") && $("q").value) { $("q").value = ""; applyFilter(); return; }
    if (document.body.classList.contains("toc-open")) { document.body.classList.remove("toc-open"); $("tocBtn").setAttribute("aria-expanded", "false"); $("tocBtn").focus(); return; }
    if (!$("tip").hidden && HOV) { leave(); return; }
    if (CRUMBS.length || document.body.classList.contains("panel-open")) closePanel();
    return;
  }
  if (typing || e.ctrlKey || e.metaKey || e.altKey || !DATA) return;
  if (e.key === "j") { e.preventDefault(); jump(1); }
  else if (e.key === "k") { e.preventDefault(); jump(-1); }
  else if (e.key === "/") { e.preventDefault(); $("q").focus(); }
});

// ---- the rest of the bar ----
const THEMES = ["auto", "light", "dark"];
function theme(t) { if (t === "auto") document.documentElement.removeAttribute("data-theme"); else document.documentElement.setAttribute("data-theme", t);
  $("theme").textContent = "Theme: " + t; $("theme").setAttribute("aria-label", "Theme: " + t + " (change)"); }
theme(THEMES.includes(keep.get("rd-read-theme")) ? keep.get("rd-read-theme") : "auto");
$("theme").onclick = () => { const cur = document.documentElement.getAttribute("data-theme") || "auto", t = THEMES[(THEMES.indexOf(cur) + 1) % 3]; theme(t); keep.set("rd-read-theme", t); };
$("seen").onclick = async () => {
  const b = $("seen"); b.disabled = true;
  try { const j = await post({ action: "seen" }); say(j.said || ""); b.textContent = "Marked as seen"; setTimeout(() => load(true), 600); }
  catch (e) { say("Not marked: " + e.message); b.textContent = "Not marked: try again"; }
  setTimeout(() => { b.disabled = false; b.textContent = "Mark all as seen"; }, 2500);
};
addEventListener("resize", () => { if (HOV) leave(); });
load();
</script></body></html>
""".replace("__DARK__", _DARK)


def page(part: str) -> str:
    return PAGE.replace("__PART__", json.dumps(part or "").replace("</", "<\\/"))
