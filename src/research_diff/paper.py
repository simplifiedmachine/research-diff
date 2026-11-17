"""The paper as it is written, read so that its experiments, results and claims go hand in hand: its SECTIONS, its
PARAGRAPHS (with the markers, `\\ref`s and numbers in each), its TABLES and FIGURES (label, caption, numbers in the
cells, the graphics file), and a check of EVERY NUMBER the paper prints against the results it rests on.

    read(text, path, def_rx)  {"path", "sections", "paragraphs", "floats"} of one LaTeX or Markdown file
    check(papers, nodes, links) (checks, issues): what each number says about the claims and tables it is in

A table or figure with a `\\label` is a node of the research (its id is the label, `tab:main`), drawn as evidence:
- a comment inside it says where its numbers come from: `% of: E1` (else: the result whose metrics its numbers match);
- a statement whose paragraph `\\ref`s it is SHOWN by it (a support, as long as the table holds).

A number in the paper is checked against the metrics of the evidence the statement (or table) rests on, read as the
paper prints them (0.874 or 87.4%, at the decimals shown):
- it MATCHES a metric: a support ("87.4% matches E1.results acc.batch32 = 0.874");
- it is NEAR one but not it: a STALE NUMBER, a contradiction ("C1 says 87.9%, but E1.results acc.batch32 is 0.874");
  a paragraph with no marker (an abstract restating a result) is checked against every result, more strictly.
Only numbers with a decimal point or a percent sign are read: counts, years and batch sizes are not results.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

LABEL_RX = re.compile(r"\\label\{([^}]+)\}")
REF_RX = re.compile(r"\\(?:[cC]|auto|eq|name|page)?ref\*?\{([^}]+)\}")
GRAPHICS_RX = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}")
BEGIN_RX = re.compile(r"\\begin\{(table|figure)\*?\}")
END_RX = re.compile(r"\\end\{(table|figure)\*?\}")
SECTION_RX = re.compile(r"\\(part|chapter|section|subsection|subsubsection|paragraph)\*?(?:\[[^\]]*\])?\{([^}]*)\}")
LEVEL = {"part": 0, "chapter": 0, "section": 1, "subsection": 2, "subsubsection": 3, "paragraph": 4}
ABSTRACT_RX = re.compile(r"\\begin\{abstract\}")
NUMBER_RX = re.compile(r"(?<![\w.\\])(-?\d+\.\d+|-?\d+)(\s*\\?%)?(?!\w|\.\d)")
COMMENT_RX = re.compile(r"(?<!\\)%.*$")
NEAR = 0.05          # within 5%: the same quantity, printed from another run
NEAR_UNMARKED = 0.02  # a paragraph with no marker is checked against every result: closer only


def _caption(text: str) -> str:
    i = text.find("\\caption")
    if i < 0:
        return ""
    j = text.find("{", i)
    depth, out = 0, []
    for ch in text[j:]:
        if ch == "{":
            depth += 1
            if depth == 1:
                continue
        elif ch == "}":
            depth -= 1
            if depth == 0:
                break
        out.append(ch)
    return plain("".join(out))


def plain(tex: str) -> str:
    """LaTeX to readable text, roughly: commands dropped, their arguments kept."""
    t = re.sub(r"\\cite[pt]?\*?(?:\[[^\]]*\])*\{([^}]*)\}", lambda m: "[" + m.group(1).replace(",", ", ") + "]", tex)
    t = re.sub(r"\\(?:[cC]|auto)?ref\*?\{([^}]*)\}", r"\1", t)
    t = re.sub(r"\\label\{[^}]*\}", "", t)
    t = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?", "", t).replace("\\%", "%")
    return re.sub(r"\s+", " ", t.replace("{", "").replace("}", "").replace("~", " ")).strip()


def numbers(text: str, line: int) -> List[dict]:
    out = []
    for m in NUMBER_RX.finditer(text):
        raw, pct = m.group(1), bool(m.group(2))
        if "." not in raw and not pct:
            continue
        out.append({"value": float(raw), "decimals": len(raw.split(".")[1]) if "." in raw else 0, "pct": pct,
                    "raw": raw + ("%" if pct else ""), "line": line})
    return out


def read(text: str, path: str, def_rx: Optional[re.Pattern] = None) -> dict:
    """The structure of one paper file. Line numbers count from 1."""
    tex = path.endswith(".tex")
    lines = text.splitlines()
    sections: List[dict] = []
    paragraphs: List[dict] = []
    floats: List[dict] = []
    section = ""
    cur: Optional[dict] = None
    fl: Optional[dict] = None

    def close() -> None:
        nonlocal cur
        if cur is not None and (cur["text"].strip() or cur["markers"]):
            paragraphs.append(cur)
        cur = None

    for i, line in enumerate(lines, 1):
        body = COMMENT_RX.sub("", line) if tex else line
        comment = (COMMENT_RX.search(line).group(0)[1:].strip() if tex and COMMENT_RX.search(line) else "")
        if tex and BEGIN_RX.search(body):
            close()
            fl = {"kind": BEGIN_RX.search(body).group(1), "line": i, "end": i, "section": section, "body": [],
                  "comments": [], "numbers": [], "label": "", "graphics": ""}
        if fl is not None:
            fl["body"].append(body)
            if comment:
                fl["comments"].append(comment)
                if "research-diff: no-check" in comment:
                    fl["no_check"] = True
            fl["numbers"] += numbers(re.sub(r"\\label\{[^}]*\}|\\caption", "", body), i) \
                if "\\caption" not in body else []
            if END_RX.search(body):
                whole = "\n".join(fl["body"])
                fl["end"] = i
                fl["label"] = (LABEL_RX.search(whole) or [None, ""])[1]
                fl["caption"] = _caption(whole)
                fl["graphics"] = (GRAPHICS_RX.search(whole) or [None, ""])[1]
                del fl["body"]
                floats.append(fl)
                fl = None
            continue
        head = SECTION_RX.search(body) if tex else None
        md_head = (not tex) and re.match(r"^(#+)\s+(.*)$", line)
        if md_head and def_rx is not None and def_rx.match(line):
            md_head = None    # `## C1: …` is a statement, not a section
        if head or md_head or (tex and ABSTRACT_RX.search(body)):
            close()
            if head:
                title, level = plain(head.group(2)), LEVEL[head.group(1)]
            elif md_head:
                title, level = md_head.group(2).strip(), len(md_head.group(1))
            else:
                title, level = "Abstract", 1
            section = title
            sections.append({"title": title, "level": level, "line": i})
            continue
        if not line.strip():
            close()
            continue
        if cur is None:
            cur = {"line": i, "end": i, "section": section, "text": "", "markers": [], "refs": [], "numbers": []}
        if "research-diff: no-check" in (comment if tex else line):
            cur["no_check"] = True
        cur["end"] = i
        src = comment if tex else line
        if def_rx is not None and src:
            d = def_rx.match(src)
            if d:
                cur["markers"].append(d.group(1))
        if tex and re.fullmatch(r"\s*\\(begin|end)\{(abstract|document)\}.*", body):
            continue
        if body.strip() and not (not tex and def_rx is not None and (def_rx.match(line) or _attr(line))):
            cur["text"] += body.strip() + " "
            here = [r.strip() for rs in REF_RX.findall(body) for r in rs.split(",")]
            cur["refs"] += here
            cur.setdefault("ref_at", {}).update({r: i for r in here})
            cur["numbers"] += numbers(re.sub(r"\\(?:cite[pt]?|ref|cref|Cref|autoref|label)\*?\{[^}]*\}", "", body), i)
    close()
    for k, s in enumerate(sections):
        s["end"] = (sections[k + 1]["line"] - 1) if k + 1 < len(sections) else len(lines)
    return {"path": path, "sections": sections, "paragraphs": paragraphs, "floats": floats}


def _attr(line: str) -> bool:
    from .extract import ATTR_RX
    return bool(ATTR_RX.match(line))


def _forms(metric: float, num: dict) -> List[float]:
    """The ways a metric may be printed: as it is, or as a percentage (0.874 -> 87.4)."""
    out = [metric]
    if abs(metric) <= 1.0 and (num["pct"] or abs(num["value"]) > 1.0):
        out.append(metric * 100)
    return out


def _say(num: dict) -> str:
    return num["raw"]


def _decimals(x: float) -> int:
    """The decimals a stored number carries (0.59 -> 2, 0.8734 -> 4): its own precision."""
    t = repr(float(x))
    if "e" in t or "E" in t:
        return 12
    return len(t.split(".")[1].rstrip("0")) if "." in t else 0


def compare_number(num: dict, pool: List[Tuple[str, str, float]], near: float) -> Tuple[str, Optional[tuple]]:
    """("match", (node, metric, value)) | ("stale", nearest) | ("none", None). Two numbers match when they agree at
    the coarser of their two precisions: 58.7% is 0.59 kept with two decimals, not a stale 0.59."""
    best, gap = None, None
    for nid, key, val in pool:
        for f in _forms(val, num):
            dec = _decimals(val) - (2 if f is not val and f != val else 0)
            unit = 0.5 * 10 ** -min(num["decimals"], max(dec, 0)) + 1e-9
            d = abs(f - num["value"])
            if d <= unit:
                return "match", (nid, key, val)
            rel = d / max(abs(f), 1e-9)
            if rel <= near and (gap is None or rel < gap):
                best, gap = (nid, key, val), rel
    return ("stale", best) if best else ("none", None)


def _pool(ids: List[str], nodes: Dict[str, dict]) -> List[Tuple[str, str, float]]:
    out = []
    for nid in ids:
        for k, v in nodes.get(nid, {}).get("metrics", {}).items():
            out.append((nid, k, v))
    return out


def _results_of(nid: str, nodes: Dict[str, dict], links: List[tuple]) -> List[str]:
    """A node with numbers, or an experiment: its results (E1.results, its runs, results `of` it)."""
    if nodes.get(nid, {}).get("metrics"):
        return [nid]
    got = [k for k in nodes if k.startswith(nid + ".")]
    got += [s for s, r, t in links if r == "of" and t == nid and s not in got]
    return [g for g in got if nodes.get(g, {}).get("metrics")]


def upstream(nid: str, nodes: Dict[str, dict], links: List[tuple], depth: int = 4) -> List[str]:
    """The evidence a node rests on, by its links (supports, relies on, shows, of)."""
    into: Dict[str, List[str]] = {}
    for s, r, t in links:
        if r in ("supports", "shows"):
            into.setdefault(t, []).append(s)
        elif r in ("relies on", "of"):        # a table `of` E1 prints E1's numbers
            into.setdefault(s, []).append(t)
    seen, todo = {nid}, [(nid, 0)]
    while todo:
        x, d = todo.pop()
        if d >= depth:
            continue
        for y in into.get(x, []):
            if y not in seen:
                seen.add(y)
                todo.append((y, d + 1))
    out: List[str] = []
    for x in sorted(seen - {nid}):
        out += [r for r in _results_of(x, nodes, links) if r not in out]
    return out


def check(papers: List[dict], nodes: Dict[str, dict], links: List[tuple]) -> Tuple[List[dict], List[dict]]:
    """(checks, issues). A check is an evidence edge from a number: {"from", "to", "sign", "why", "file", "line"}; an
    issue is a stale number in a paragraph with no marker: {"file", "line", "section", "says", "why", "from"}."""
    every = _pool([k for k, n in nodes.items() if n["kind"] in ("result",) or "." in k], nodes)
    checks: Dict[tuple, dict] = {}
    issues: List[dict] = []

    def judge(target: str, nums: List[dict], pool: List[tuple], near: float, where: str, section: str,
              text: str = "") -> None:
        for num in nums:
            how, hit = compare_number(num, pool, near)
            if how == "match":
                checks.setdefault((hit[0], target, "+"), {
                    "from": hit[0], "to": target, "sign": "+", "file": where, "line": num["line"],
                    "why": f"{_say(num)} in {target} matches {hit[0]} {hit[1]} = {hit[2]:g}"})
            elif how == "stale":
                why = f"{target} says {_say(num)} ({where}:{num['line']}), but {hit[0]} {hit[1]} is {hit[2]:g}"
                if target.startswith("§"):
                    issues.append({"node": target, "file": where, "line": num["line"], "section": section,
                                   "says": _say(num), "from": hit[0], "metric": hit[1], "value": hit[2], "why": why,
                                   "text": text})
                else:
                    checks[(hit[0], target, "-", num["line"])] = {"from": hit[0], "to": target, "sign": "-",
                                                                  "file": where, "line": num["line"], "why": why}

    for p in papers:
        for fl in p["floats"]:
            lab = fl["label"]
            if not lab or lab not in nodes:
                continue
            src = [t for s, r, t in links if s == lab and r == "of"]
            pool = _pool([x for t in src for x in _results_of(t, nodes, links)], nodes)
            if not pool:     # no `of:`: the result whose numbers it prints
                scores = {}
                for nid, key, val in every:
                    for num in fl["numbers"]:
                        if compare_number(num, [(nid, key, val)], 0)[0] == "match":
                            scores[nid] = scores.get(nid, 0) + 1
                best = sorted((-v, k) for k, v in scores.items() if v >= 2)
                pool = _pool([best[0][1]], nodes) if best else []
            judge(lab, [] if fl.get("no_check") else fl["numbers"], pool, NEAR, p["path"], fl["section"])
        for para in p["paragraphs"]:
            if not para["numbers"] or para.get("no_check"):
                continue
            owners = [m for m in para["markers"] if m in nodes and nodes[m]["kind"] in ("claim", "finding")]
            if owners:
                for nid in owners:
                    rest = upstream(nid, nodes, links + [(r, "shows", nid) for r in para["refs"] if r in nodes])
                    pool = _pool(rest, nodes)
                    judge(nid, para["numbers"], pool or every, NEAR if pool else NEAR_UNMARKED, p["path"],
                          para["section"])
            else:
                judge(f"§{para['section'] or 'Paper'}:{para['line']}", para["numbers"], every, NEAR_UNMARKED,
                      p["path"], para["section"], plain(para["text"])[:160])
    return list(checks.values()), issues
