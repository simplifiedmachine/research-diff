"""The Paper tab: a paper of any length, readable. One box per top-level section (\\section, or \\chapter where the paper
has chapters); its subsections and run-in paragraphs fold inside it as a count and show when the person zooms into it
(the page's part "sec:<box>"). The files a section \\input's (tables, mostly) belong to that section: a chip "tables 11",
not a box each. Files no paper file inputs and that hold no sections are one box: "Other files".

Status is form, not lines of text: the box's colour is its worst (a stale number or a contradicted claim: red; a
contested claim or a change since the checkpoint: amber; claims supported and numbers matching: green), and its chips
count claims (✓ ◐ ✗), numbers (✓ ✗) and tables. How much a box says follows the page's zoom: outline (the sections
alone), compact (their chips), detailed (their parts listed too); auto opens a paper with more than AUTO_OUTLINE
headings at outline. "Needs attention" comes first, above the diagram: the sections with stale numbers or contested
and contradicted claims, worst first. A section with nothing to fix stays quiet.
"""
from __future__ import annotations

import posixpath
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import paper

INPUT_RX = re.compile(r"\\(?:input|include|subfile)\s*\{([^}]+)\}")
APPENDIX_RX = re.compile(r"\\appendix\b|\\begin\{appendices\}")
PER_COLUMN = 8             # boxes in one column before the next
AUTO_OUTLINE = 25          # headings: more than this opens at outline
LISTED = 6                 # parts listed inside a box at the detailed zoom
DETAILED, COMPACT, OUTLINE = 0, 1, 2


def _text(root: Path, path: str) -> str:
    try:
        return (Path(root) / path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _resolve(target: str, here: str, files: set) -> Optional[str]:
    """The paper file an \\input names: relative to the file that inputs it, else to the folder of a paper's root."""
    t = target.strip().replace("\\", "/")
    names = [t] if t.endswith(".tex") else [t + ".tex", t]
    for base in (posixpath.dirname(here), ""):
        for n in names:
            p = posixpath.normpath(posixpath.join(base, n)) if base else posixpath.normpath(n)
            if p in files:
                return p
    for n in names:                           # inputs are often relative to the main file's folder: any one that ends so
        hit = [f for f in files if f.endswith("/" + n.lstrip("./"))]
        if len(hit) == 1:
            return hit[0]
    return None


class Box:
    def __init__(self, bid: str, title: str, file: str, line: int):
        self.id, self.title, self.file, self.line = bid, title, file, line
        self.ranges: List[Tuple[str, int, int]] = []
        self.parts: List[dict] = []          # the headings inside: {"title", "level", "file", "line"}
        self.tables: List[str] = []          # files it \input's that hold no sections
        self.end = line
        self.appendix = False

    def holds(self, f: str, line: int) -> bool:
        return f in self.tables or any(f == rf and lo <= line <= hi for rf, lo, hi in self.ranges)


def layout(root: Path, files: List[str]) -> dict:
    """{"boxes": [Box], "other": [paths], "headings": n, "docs": [paths]}: the paper files read as documents, each
    \\input followed where it stands."""
    fs = set(files)
    texts = {f: _text(root, f) for f in files}
    parsed = {f: paper.read(t, f) for f, t in texts.items()}
    inputs: Dict[str, List[Tuple[int, str]]] = {}
    for f, t in texts.items():
        for i, line in enumerate(t.splitlines(), 1):
            body = paper.COMMENT_RX.sub("", line)
            for m in INPUT_RX.finditer(body):
                target = _resolve(m.group(1), f, fs)
                if target and target != f:
                    inputs.setdefault(f, []).append((i, target))
    inputted = {t for got in inputs.values() for _l, t in got}

    def sectioned(f: str, seen: frozenset = frozenset()) -> bool:
        if f in seen:
            return False
        return bool(parsed[f]["sections"]) or any(sectioned(t, seen | {f}) for _l, t in inputs.get(f, []))

    docs = [f for f in files if f not in inputted and (sectioned(f) or "\\documentclass" in texts[f])]
    other = [f for f in files if f not in inputted and f not in docs]

    def flatten(f: str, seen: frozenset) -> list:
        out, pos = [], 1
        n = len(texts[f].splitlines())
        evs = sorted([(s["line"], 1, "head", s) for s in parsed[f]["sections"]] +
                     [(ln, 0, "input", t) for ln, t in inputs.get(f, [])] +
                     [(i, 0, "appendix", None) for i, ln in enumerate(texts[f].splitlines(), 1)
                      if APPENDIX_RX.search(paper.COMMENT_RX.sub("", ln))], key=lambda e: (e[0], e[1]))
        for line, _o, kind, what in evs:
            if kind == "appendix":
                out.append(("appendix",))
                continue
            if kind == "head":
                if line - 1 >= pos:
                    out.append(("text", f, pos, line - 1))
                out.append(("head", f, line, what["level"], what["title"]))
                pos = line
            else:
                out.append(("text", f, pos, line))
                pos = line + 1
                if what in seen:
                    continue
                out += flatten(what, seen | {what}) if sectioned(what) else [("table", what)]
        if n >= pos:
            out.append(("text", f, pos, n))
        return out

    boxes: List[Box] = []
    headings = 0
    for d in docs:
        evs = flatten(d, frozenset({d}))
        levels = [e[3] for e in evs if e[0] == "head"]
        headings += len(levels)
        top = min(levels) if levels else 1
        cur: Optional[Box] = None
        appendix = False
        for e in evs:
            if e[0] == "appendix":
                appendix = True
                continue
            if e[0] == "head" and e[3] <= top:
                cur = Box(f"sec:{e[1]}:{e[2]}", e[4] or "(untitled)", e[1], e[2])
                cur.appendix = appendix
                boxes.append(cur)
                continue
            if cur is None:                   # before the first section: the preamble, the title, the abstract
                cur = Box(f"sec:{d}:1", "Front matter", d, 1)
                boxes.append(cur)
            if e[0] == "head":
                cur.parts.append({"title": e[4] or "(untitled)", "level": e[3], "file": e[1], "line": e[2]})
            elif e[0] == "text":
                cur.ranges.append((e[1], e[2], e[3]))
                if e[1] == cur.file:
                    cur.end = max(cur.end, e[3])
            else:
                cur.tables.append(e[1])
    return {"boxes": boxes, "other": other, "headings": headings, "docs": docs, "parsed": parsed}


def _stats(S: dict, box_holds, touched: set) -> dict:
    """What a box holds: its statements and their verdicts, its numbers checked, whether it changed."""
    bp, g = S["map"], S["graph"]
    papers = {p["path"] for p in bp.get("paper", [])}
    st = []
    for nid, n in bp["nodes"].items():
        line = n.get("line")
        if not line or n.get("kind") in ("table", "figure"):
            continue
        f = next((x for x in n.get("files", []) if x in papers), None)
        if f and box_holds(f, int(line)):
            st.append((nid, (g["nodes"].get(nid) or {}).get("verdict", "")))
    nums = [c for c in bp.get("checks", []) if c.get("file") and box_holds(c["file"], int(c.get("line") or 0))]
    nums += [{**i, "sign": "-"} for i in bp.get("issues", []) if box_holds(i["file"], int(i.get("line") or 0))]
    v = {k: sum(1 for _n, x in st if x == k) for k in ("supported", "contested", "contradicted", "unsupported")}
    stale = [c for c in nums if c.get("sign") == "-"]
    ok = sum(1 for c in nums if c.get("sign") == "+")
    changed = bool(touched & {nid for nid, _v in st})
    status = "removed" if stale or v["contradicted"] else "changed" if v["contested"] or changed else \
        "added" if v["supported"] or ok else "same"
    return {"statements": st, "verdicts": v, "stale": stale, "ok": ok, "changed": changed, "status": status,
            "score": len(stale) + 5 * v["contradicted"] + 2 * v["contested"]}


def _chips(x: dict, tables: int = 0) -> List[str]:
    v = x["verdicts"]
    claims = " ".join(f"{s} {v[k]}" for s, k in (("✓", "supported"), ("◐", "contested"), ("✗", "contradicted"),
                                                  ("○", "unsupported")) if v[k])
    out = []
    if claims:
        out.append("claims " + claims)
    if x["ok"] or x["stale"]:
        out.append("numbers" + (f" ✓ {x['ok']}" if x["ok"] else "") + (f" ✗ {len(x['stale'])} stale" if x["stale"]
                                                                        else ""))
    if tables:
        out.append(f"tables {tables}")
    if x["changed"]:
        out.append("~ changed since the checkpoint")
    return out


def _level(zoom: int, headings: int) -> int:
    if zoom in (DETAILED, COMPACT, OUTLINE):
        return zoom
    return OUTLINE if headings > AUTO_OUTLINE else COMPACT


def _attention(items: List[Tuple[str, str, dict, str]]) -> List[dict]:
    """The boxes with something to fix, worst first: stale numbers, contradicted and contested claims."""
    out = []
    for bid, title, x, where in sorted(items, key=lambda t: -t[2]["score"]):
        if not x["score"]:
            continue
        v = x["verdicts"]
        said = [f"{len(x['stale'])} number{'' if len(x['stale']) == 1 else 's'} stale" if x["stale"] else "",
                f"{v['contradicted']} claim{'' if v['contradicted'] == 1 else 's'} contradicted"
                if v["contradicted"] else "",
                f"{v['contested']} contested" if v["contested"] else ""]
        last = sum(1 for c in x["stale"] if c.get("last_digit"))
        if last:
            said.append(f"{last} only in the last digit")
        why = "; ".join(c["why"] for c in x["stale"][:2]) or ", ".join(
            nid for nid, verdict in x["statements"] if verdict in ("contradicted", "contested"))
        out.append({"sign": "✗" if x["stale"] or v["contradicted"] else "◐",
                    "status": "removed" if x["stale"] or v["contradicted"] else "changed",
                    "text": f"{title}: " + ", ".join(s for s in said if s) + (f" ({where})" if where else ""),
                    "why": why, "id": "b:" + bid})
    return out


def view(S: dict, part: str, zoom: int, part_of, summary_of, label: str, svg) -> dict:
    """The Paper tab's page: {"title", "headline", "diagram", "sections"}. `part_of(node)` makes a part in the
    study; `summary_of(path)` the LLM's section summaries of a file; `svg(model, title)` draws."""
    from .history import touched as touched_ids
    root = S["root"]
    files = [x["path"] for x in S["map"].get("paper", [])]
    if not files:
        return {"title": label, "headline": "No paper yet", "diagram": {}, "sections": [
            {"title": "No paper yet", "aside": "", "kind": "lines", "items": [
                {"text": "research-diff reads the LaTeX files of the study (and what the `paper` globs of "
                         "research-diff.toml name).", "style": "muted"}]}]}
    lay = layout(root, files)
    touched = set(touched_ids(S["cmp"].diff))
    level = _level(zoom, lay["headings"])
    want = part[len("sec:"):] if part.startswith("sec:") else ""
    box = next((b for b in lay["boxes"] if b.id == want), None)
    if box is not None:
        return _zoomed(S, lay, box, touched, level, label, svg, part_of)
    nodes, where, details, enter, attention = [], {}, {}, {}, []
    stale_all = 0
    for b in lay["boxes"]:
        x = _stats(S, b.holds, touched)
        if b.title == "Front matter" and not x["statements"] and not x["ok"] and not x["stale"] and not b.tables:
            continue
        stale_all += len(x["stale"])
        lines = [] if level == OUTLINE else [{"text": c, "status": x["status"] if i == 0 else "same"}
                                             for i, c in enumerate(_chips(x, len(b.tables)))]
        if level == DETAILED and b.parts:      # one line: the renderer shows a few lines a box
            lines.insert(0, {"text": " · ".join(p["title"][:40] for p in b.parts[:LISTED]) +
                             (f" · +{len(b.parts) - LISTED}" if len(b.parts) > LISTED else ""), "status": "same"})
        sub = " · ".join(s for s in (f"{len(b.parts)} part{'' if len(b.parts) == 1 else 's'}" if b.parts else "",
                                     f"{len(b.tables)} table file{'' if len(b.tables) == 1 else 's'}"
                                     if b.tables else "") if s) or f"lines {b.line}-{b.end}"
        base = ("Appendix" if b.appendix else "Paper") + ("" if len(lay["docs"]) == 1 else
                                                          f" · {posixpath.basename(b.file)}")
        n_in = sum(1 for n in nodes if n["col"].startswith(base))
        col = base if n_in < PER_COLUMN else f"{base} ({n_in // PER_COLUMN + 1})"
        nodes.append({"id": b.id, "col": col, "title": "§ " + b.title[:80], "sub": sub, "status": x["status"],
                      "type": "component", "lines": lines})
        if b.parts or b.tables:
            enter["b:" + b.id] = {"view": "paper", "part": part_of("sec:" + b.id)}
        else:
            where["b:" + b.id] = {"path": b.file, "line": b.line, "end": b.end}
        said = (summary_of(b.file) or {}).get(b.title) or {}
        details["b:" + b.id] = {
            "title": "§ " + b.title,
            "headline": said.get("says") or f"{len(x['statements'])} statements · {x['ok'] + len(x['stale'])} numbers",
            "how": [y for y in (said.get("claims"),) if y],
            "insights": [y for y in (said.get("watch"),) if y] + [c["why"] for c in x["stale"][:3]],
            "facts": [f for f in (
                {"title": "Statements", "summary": ", ".join(n for n, _v in x["statements"][:8]) or "none",
                 "items": [f"{n} {v or ''}".strip() for n, v in x["statements"]]},
                {"title": "Parts", "summary": str(len(b.parts)), "items": [p["title"] for p in b.parts]}
                if b.parts else None,
                {"title": "Tables", "summary": str(len(b.tables)), "items": b.tables} if b.tables else None) if f],
            "inside": "Click to see its parts" if b.id in {k[2:] for k in enter} else f"Click to open it in {b.file}"}
        attention.append((b.id, "§ " + b.title, x, ""))
    if lay["other"]:
        x = _stats(S, lambda f, ln: f in lay["other"], touched)
        stale_all += len(x["stale"])
        nodes.append({"id": "other", "col": "Other files", "title": "Other files", "type": "component",
                      "sub": f"{len(lay['other'])} file{'' if len(lay['other']) == 1 else 's'} no section inputs",
                      "status": x["status"], "lines": [] if level == OUTLINE else
                      [{"text": c, "status": "same"} for c in _chips(x)]})
        enter["b:other"] = {"view": "paper", "part": part_of("sec:other")}
        details["b:other"] = {"title": "Other files", "headline": "Paper files no section \\input's",
                              "how": lay["other"][:12], "insights": [c["why"] for c in x["stale"][:3]], "facts": [],
                              "inside": "Click to list them"}
        attention.append(("other", "Other files", x, ""))
    cols = list(dict.fromkeys(n["col"] for n in nodes))
    model = {"nodes": nodes, "edges": [], "columns": [(c, c) for c in cols]}
    need = _attention(attention)
    sections = [{"title": "Needs attention", "aside": "worst first · hover one to see its section",
                 "kind": "notes", "items": need}] if need else []
    head = f"{len([n for n in nodes if n['id'] != 'other'])} sections · {len(files)} paper file" + \
        ("" if len(files) == 1 else "s") + (f" · ✗ {stale_all} stale number{'' if stale_all == 1 else 's'}"
                                            if stale_all else "")
    zoom_word = ["detailed", "compact", "outline"][level]
    diagram = {"svg": svg(model, "Paper"), "title": "The paper, section by section",
               "aside": f"{zoom_word} · click a section for its parts, or to open it", "lights": {},
               "details": details, "enter": enter, "files": where, "pick": ""} if nodes else {}
    return {"title": label, "headline": head, "diagram": diagram, "sections": sections, "level": zoom_word,
            "pdf": {"main": lay["docs"][0], "file": lay["docs"][0], "line": 1} if lay["docs"] else None}


def _zoomed(S, lay, box: Box, touched, level, label, svg, part_of) -> dict:
    """One section opened: its parts (the next level of headings, the deeper ones folded in), and the files it inputs."""
    bid = box.id
    parts = [p for p in box.parts if p["level"] == min(q["level"] for q in box.parts)] if box.parts else []
    nodes, where, details, attention = [], {}, {}, []
    for k, p in enumerate(parts):
        nxt = parts[k + 1] if k + 1 < len(parts) else None
        hi = (nxt["line"] - 1) if nxt and nxt["file"] == p["file"] else max(
            (h for f, _lo, h in box.ranges if f == p["file"]), default=p["line"])
        inner = [q for q in box.parts if q["file"] == p["file"] and p["line"] < q["line"] <= hi]

        def holds(f, ln, p=p, hi=hi):
            return f == p["file"] and p["line"] <= ln <= hi
        x = _stats(S, holds, touched)
        pid = f"{bid}#{k}"
        nodes.append({"id": pid, "col": "Parts", "title": p["title"][:80], "type": "component",
                      "sub": f"{len(inner)} inside" if inner else f"lines {p['line']}-{hi}", "status": x["status"],
                      "lines": [{"text": c, "status": "same"} for c in _chips(x)]})
        where["b:" + pid] = {"path": p["file"], "line": p["line"], "end": hi}
        details["b:" + pid] = {"title": p["title"], "headline": f"{len(x['statements'])} statements · "
                               f"{x['ok'] + len(x['stale'])} numbers", "how": [q["title"] for q in inner[:8]],
                               "insights": [c["why"] for c in x["stale"][:3]], "facts": [],
                               "inside": f"Click to open it in {p['file']}"}
        attention.append((pid, p["title"], x, ""))
    tables = box.tables if bid != "other" else lay["other"]
    for k, t in enumerate(tables):
        x = _stats(S, lambda f, ln, t=t: f == t, touched)
        tid = f"{bid}@{k}"
        nodes.append({"id": tid, "col": "Tables and other inputs" if bid != "other" else "Other files",
                      "title": posixpath.basename(t), "type": "store", "sub": t, "status": x["status"],
                      "lines": [{"text": c, "status": "same"} for c in _chips(x)]})
        where["b:" + tid] = {"path": t, "line": 1, "end": 1}
        details["b:" + tid] = {"title": t, "headline": f"{x['ok']} numbers match, {len(x['stale'])} stale",
                               "how": [], "insights": [c["why"] for c in x["stale"][:4]], "facts": [],
                               "inside": f"Click to open {t}"}
        attention.append((tid, posixpath.basename(t), x, t))
    if box.ranges and bid != "other":         # the section itself, to open where it starts
        x = _stats(S, box.holds, touched)
        nodes.insert(0, {"id": bid + "#self", "col": "Parts", "title": "§ " + box.title[:80], "type": "component",
                         "sub": f"the whole section · {box.file}", "status": x["status"],
                         "lines": [{"text": c, "status": "same"} for c in _chips(x, len(box.tables))]})
        where["b:" + bid + "#self"] = {"path": box.file, "line": box.line, "end": box.end}
        details["b:" + bid + "#self"] = {"title": "§ " + box.title, "headline": "The whole section", "how": [],
                                         "insights": [], "facts": [], "inside": f"Click to open it in {box.file}"}
    cols = list(dict.fromkeys(n["col"] for n in nodes))
    model = {"nodes": nodes, "edges": [], "columns": [(c, c) for c in cols]}
    need = _attention(attention)
    title = "Other files" if bid == "other" else "§ " + box.title
    main = next((d for d in lay["docs"] if d == box.file), lay["docs"][0] if lay["docs"] else None)
    return {"pdf": {"main": main, "file": box.file, "line": box.line} if main and bid != "other" else None,
            "title": label, "headline": f"{title}: {len(parts)} part{'' if len(parts) == 1 else 's'}, "
                                        f"{len(tables)} input{'' if len(tables) == 1 else 's'}",
            "diagram": {"svg": svg(model, title), "title": title, "aside": "click one to open it · Back for the paper",
                        "lights": {}, "details": details, "enter": {}, "files": where, "pick": ""} if nodes else {},
            "sections": [{"title": "Needs attention", "aside": "worst first", "kind": "notes", "items": need}]
            if need else []}

