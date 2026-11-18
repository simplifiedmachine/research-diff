"""A research file opened for reading: the paper (or a notes file, a config, a script) as an OUTLINE, one chunk per
section, each with its statements and their verdicts, its tables and figures, every number it prints checked against
the results (✓ matches, ✗ stale), and a plain-words SUMMARY of the section by the person's own LLM.

    outline(root, path, bp, graph)   the chunks, from the file as it is on disk (cheap; no LLM)
    summarize(root, path, ...)       the summary: kept by the file's blob id, so each version is summarised once; made
                                     in the background the first time the file is opened (`wait=True`: now)

The text goes to the LLM the person already uses (narrate.complete: their Claude Code gateway, a shell setting, or
the `claude` CLI); never with RESEARCH_DIFF_LLM=off. Summaries are marked ✦ wherever they are shown.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

from . import objectives, paper, store

ASK: Optional[Callable[[str, str], Optional[str]]] = None   # tests stand in for the LLM here
SEND_MAX = 60000
SYSTEM = ("You summarise a researcher's own paper (or notes) for them, section by section, so they can check that "
          "experiments, results and claims hang together. Be short, concrete and plain: say what each section "
          "actually claims and on what evidence, and name any tension with other sections or with the numbers. "
          "Answer with JSON only.")
_JOBS: Dict[str, float] = {}
_LOCK = threading.Lock()


def blob_id(data: bytes) -> str:
    h = hashlib.sha1()
    h.update(b"blob %d\0" % len(data))
    h.update(data)
    return h.hexdigest()


def outline(root: Path, path: str, bp: dict, graph: Optional[dict] = None) -> dict:
    full = Path(root) / path
    try:
        text = full.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {"path": path, "error": f"{path} cannot be read", "chunks": [], "lines": []}
    from .extract import _def_rx
    kinds = {k: v for k, v in (("Q", "question"), ("H", "hypothesis"), ("E", "experiment"), ("R", "result"),
                                ("F", "finding"), ("C", "claim"))}
    lines = text.splitlines()
    verdict = {k: n["verdict"] for k, n in (graph or {}).get("nodes", {}).items()}
    if path.endswith((".tex", ".md", ".markdown")):
        p = paper.read(text, path, _def_rx(kinds))
        secs = p["sections"] or [{"title": Path(path).name, "level": 1, "line": 1, "end": len(lines)}]
        if secs[0]["line"] > 1:
            secs = [{"title": "(before the first section)", "level": 1, "line": 1, "end": secs[0]["line"] - 1}] + secs
    else:
        p, secs = {"floats": []}, [{"title": Path(path).name, "level": 1, "line": 1, "end": len(lines)}]
    marks = [(n.get("line", 0), nid) for nid, n in bp["nodes"].items() if path in n["files"] and n.get("line")
             and n["kind"] not in ("table", "figure")]
    checks = [c for c in bp.get("checks", []) if c.get("file") == path] + \
             [{**i, "sign": "-", "to": i["node"]} for i in bp.get("issues", []) if i["file"] == path]
    chunks = []
    for s in secs:
        lo, hi = s["line"], s.get("end", len(lines))
        inside = lambda ln: lo <= ln <= hi  # noqa: E731
        chunks.append({
            "title": s["title"], "level": s["level"], "line": lo, "end": hi,
            "statements": [{"id": nid, "title": bp["nodes"][nid]["title"], "kind": bp["nodes"][nid]["kind"],
                            "verdict": verdict.get(nid, ""), "line": ln} for ln, nid in sorted(marks) if inside(ln)],
            "floats": [{"label": f["label"], "kind": f["kind"], "caption": f.get("caption", ""), "line": f["line"],
                        "verdict": verdict.get(f["label"], "")} for f in p["floats"] if inside(f["line"])],
            "numbers": [{"line": c["line"], "sign": c["sign"], "why": c["why"]} for c in checks if inside(c["line"])],
            "text": paper.plain("\n".join(lines[lo - 1:hi]))[:4000],
        })
    blob = blob_id(text.encode("utf-8"))
    return {"path": path, "blob": blob, "chunks": chunks, "lines": lines, "summary": summary(root, blob)}


def _file(root: Path, blob: str) -> Path:
    d = store.home(root) / "summaries"
    d.mkdir(exist_ok=True)
    return d / f"{blob}.json"


def summary(root: Path, blob: str) -> Optional[dict]:
    try:
        return json.loads(_file(root, blob).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def prompt(path: str, chunks: List[dict]) -> str:
    titles = [c["title"] for c in chunks]
    body = "\n\n".join(f"### {c['title']}\n{c['text']}" for c in chunks)[:SEND_MAX]
    return (f"File: {path}\nReturn JSON: {{\"file\": \"2-3 sentences: what this document argues and on what "
            "evidence\", \"sections\": {\"<title>\": {\"says\": \"what the section says (one sentence)\", "
            "\"claims\": \"the claims it makes, with their numbers (one sentence; empty if none)\", \"watch\": "
            "\"a tension with another section or the numbers, an overclaim, or a claim with no evidence; empty if "
            f"none\"}}}}. Use exactly these titles as keys: {json.dumps(titles)}\n\n{body}")


def _norm(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", paper.plain(title).lower()).strip()


WHY: Dict[str, str] = {}


def parse(answer: str, chunks: List[dict], by: str) -> Optional[dict]:
    """The summary in the answer, its sections matched to the file's (titles compared loosely: case, punctuation,
    LaTeX); None, with the reason in WHY["last"], when it has none."""
    m = re.search(r"\{.*\}", answer or "", re.S)
    if not m:
        WHY["last"] = "its answer was not JSON" + (" (it was cut off)" if (answer or "").count("{") else "")
        return None
    try:
        data = json.loads(m.group(0))
    except ValueError as exc:
        WHY["last"] = f"its answer was not valid JSON ({str(exc)[:80]}); it may have been cut off"
        return None
    by_norm = {_norm(c["title"]): c["title"] for c in chunks}
    given = data.get("sections") or {}
    if isinstance(given, list):         # [{"title": ..., "says": ...}] instead of {title: {...}}
        given = {str(x.get("title", "")): x for x in given if isinstance(x, dict)}
    secs = {}
    for t, v in given.items():
        title = by_norm.get(_norm(str(t)))
        if title and isinstance(v, dict):
            secs[title] = {k: str(v.get(k, ""))[:400] for k in ("says", "claims", "watch")}
    if not secs:
        WHY["last"] = "its answer named none of this file's sections" + \
            (f" (it named: {', '.join(list(map(str, given))[:4])})" if given else "")
        return None
    return {"file": str(data.get("file", ""))[:800], "sections": secs, "by": by, "at": time.time()}


def _ask(root: Path, user: str) -> Optional[tuple]:
    if ASK is not None:
        got = ASK(user, SYSTEM)
        return (got, "test") if got else None
    if objectives.off() or os.environ.get("PYTEST_CURRENT_TEST"):
        return None
    from system_diff import narrate
    got = narrate.complete(user, SYSTEM, root, {}, timeout=240, limit=80000)
    if not got:
        said = (getattr(narrate, "LAST_ERROR", None) or [""])[0]
        WHY["last"] = said.removeprefix("system-diff: ") if said else \
            "no LLM answered from here (research-diff asks Claude Code's gateway, one set in your shell, or the " \
            "`claude` CLI)"
    return got


def _why_file(root: Path, blob: str) -> Path:
    return _file(root, blob).with_suffix(".why")


def failed_why(root: Path, blob: str) -> str:
    try:
        return _why_file(root, blob).read_text(encoding="utf-8")
    except OSError:
        return ""


def summarize(root: Path, path: str, bp: dict, graph: Optional[dict] = None, wait: bool = False) -> dict:
    """{"state": "done", ...the summary} | {"state": "summarizing"} | {"state": "off"|"failed", "why"}."""
    o = outline(root, path, bp, graph)
    if o.get("error"):
        return {"state": "failed", "why": o["error"]}
    if o["summary"]:
        return {"state": "done", **o["summary"]}
    if ASK is None and (objectives.off() or os.environ.get("PYTEST_CURRENT_TEST")):
        return {"state": "off", "why": "no LLM may be asked (RESEARCH_DIFF_LLM=off)"}
    with _LOCK:
        if _JOBS.get(o["blob"], 0) > 0 and not wait:
            return {"state": "summarizing"}
        if _JOBS.get(o["blob"], 0) < 0 and time.time() + _JOBS[o["blob"]] < 300 and not wait:
            return {"state": "failed", "why": (failed_why(root, o["blob"]) or "the LLM gave no usable answer")
                    + "; tried again in a few minutes"}
        _JOBS[o["blob"]] = time.time()

    def job() -> bool:
        ok = False
        WHY.pop("last", None)
        try:
            got = _ask(root, prompt(path, o["chunks"]))
            parsed = parse(got[0], o["chunks"], got[1]) if got else None
            if parsed:
                parsed["path"] = path
                f = _file(root, o["blob"])
                f.write_text(json.dumps(parsed, ensure_ascii=False), encoding="utf-8")
                ok = True
        except Exception as exc:  # noqa: BLE001 - a summary is a convenience: keep why it failed
            WHY["last"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        finally:
            if not ok:
                try:
                    _why_file(root, o["blob"]).write_text(WHY.get("last") or "the LLM gave no usable answer",
                                                         encoding="utf-8")
                except OSError:
                    pass
            with _LOCK:
                _JOBS[o["blob"]] = 0 if ok else -time.time()
        return ok
    if wait:
        return {"state": "done", **summary(root, o["blob"])} if job() else \
            {"state": "failed", "why": failed_why(root, o["blob"]) or "the LLM gave no usable answer"}
    threading.Thread(target=job, daemon=True, name="research-diff-summary").start()
    return {"state": "summarizing"}


def research_files(bp: dict) -> List[str]:
    """Every file a marker is in, the paper first."""
    files: List[str] = []
    for p in bp.get("paper", []):
        files.append(p["path"])
    for n in bp["nodes"].values():
        for f in n["files"]:
            if f not in files:
                files.append(f)
    return files


def as_text(o: dict) -> str:
    out = [o["path"]]
    s = o.get("summary") or {}
    if s.get("file"):
        out.append(f"  ✦ {s['file']}")
    for c in o["chunks"]:
        out.append(f"\n{'#' * c['level']} {c['title']}  (lines {c['line']}-{c['end']})")
        cs = (s.get("sections") or {}).get(c["title"], {})
        for k in ("says", "claims", "watch"):
            if cs.get(k):
                out.append(f"  ✦ {k}: {cs[k]}")
        for st in c["statements"]:
            out.append(f"  {st['id']} [{st['verdict'] or st['kind']}] {st['title']}")
        for f in c["floats"]:
            out.append(f"  {f['label']} [{f['kind']}{', ' + f['verdict'] if f['verdict'] else ''}] {f['caption']}")
        for n in c["numbers"]:
            out.append(f"  {'✓' if n['sign'] == '+' else '✗'} line {n['line']}: {n['why']}")
    return "\n".join(out)


def start(root: Path, path: str) -> bool:
    """Summarise a file in a process of its own (the pane's look is a short-lived process), once per version; True
    while one is being made, False when none can be (no LLM) or it is made."""
    import subprocess
    import sys
    if ASK is None and (objectives.off() or os.environ.get("PYTEST_CURRENT_TEST")):
        return False
    try:
        blob = blob_id((Path(root) / path).read_bytes())
    except OSError:
        return False
    if summary(root, blob):
        return False
    mark = store.home(root) / "summaries" / f"{blob}.asked"
    mark.parent.mkdir(exist_ok=True)
    if mark.exists() and time.time() - mark.stat().st_mtime < 300:
        return True
    mark.write_text(str(time.time()))
    flags = {"start_new_session": True} if os.name != "nt" else {"creationflags": 0x08000000 | 0x00000200}
    try:
        subprocess.Popen([sys.executable, "-m", "research_diff", "--repo", str(root), "outline", path, "--summarize",
                          "--quiet"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         **flags)
    except OSError:
        return False
    return True
