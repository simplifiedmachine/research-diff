"""A paper's structure, for the Read tab and the file viewer's outline: a paper of any length, readable. One box per top-level section (\\section, or \\chapter where the paper
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
    from .extract import _def_rx
    rx = _def_rx({"Q": "question", "H": "hypothesis", "E": "experiment", "R": "result", "F": "finding",
                  "C": "claim"})
    parsed = {f: paper.read(t, f, rx) for f, t in texts.items()}     # its markers too (% C1: …)
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
