"""A research project's state as one JSON-able dict, read from markers in its own files.

THE MARKERS. One grammar, wherever it is written:

    H2: A larger batch helps on small datasets        <- a definition: an id (Q, H, E, R or C and a number) and a title
    answers: Q1                                       <- links, on the lines right after it
    status: supported

In Markdown the definition may be a heading or a list item. In LaTeX it goes in a comment (`% C1: …`), and the claim's
paragraph gives its sources (`\\cite{…}`). In a script, notebook or config it is a comment: `# research-diff: E5 tests
H2`. A YAML/JSON/TOML config may instead carry a `research:` block: `{id: E5, tests: [H2], results: out/e5.json}`;
the results file (JSON or CSV) becomes the result `E5.results` with its numbers as metrics.

The map is built from markers only, so the same files give the same map. `research-diff suggest` asks an LLM to
propose markers for what is untagged; it never writes them.
"""
from __future__ import annotations

import csv
import io
import json
import re
import tomllib
from collections import defaultdict
from pathlib import PurePosixPath
from typing import Any, Dict, Iterable, List, Optional, Tuple

from system_diff.config import segment_rx
from system_diff.extract import glob_rx

RELS = {"answers": "answers", "tests": "tests", "of": "of", "supports": "supports", "weakens": "weakens",
        "relies on": "relies on", "relies": "relies on", "depends on": "relies on", "based on": "relies on"}
ATTRS = ("status", "metrics", "results", "sources", "source")
KEYS = "|".join(sorted(list(RELS) + list(ATTRS), key=len, reverse=True))
ATTR_RX = re.compile(rf"^\s*(?:[-*+]\s+)?\**({KEYS})\**\s*:\s*(.+?)\s*$", re.I)
COMMENT_RX = re.compile(r"(?:#|//|%)\s*research-diff:\s*(.+)$", re.M)
CITE_RX = re.compile(r"\\(?:cite[pt]?|citeauthor|citeyear)\*?(?:\[[^\]]*\])*\{([^}]+)\}")
NUM_RX = re.compile(r"^-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?$")


def _def_rx(kinds: Dict[str, str]) -> re.Pattern:
    letters = "".join(sorted(kinds))
    return re.compile(rf"^\s*(?:#+\s*|[-*+]\s+|>\s*)*\**([{letters}]\d+[a-z]?)\**\s*[:.)\u2014-]\s*(.+?)\s*$")


def _ids(text: str, kinds: Dict[str, str]) -> List[str]:
    letters = "".join(sorted(kinds))
    return re.findall(rf"\b([{letters}]\d+[a-z]?(?:\.results)?)\b", text)


def _metrics(text: str) -> Dict[str, float]:
    out = {}
    for part in re.split(r"[,;]", text):
        if "=" in part or ":" in part:
            k, v = re.split(r"[=:]", part, maxsplit=1)
            v = v.strip().rstrip("%")
            if NUM_RX.match(v):
                out[k.strip()] = float(v)
    return out


class Model:
    """Nodes, links and warnings as they are read; first definition names a node, later ones add to it."""

    def __init__(self, kinds: Dict[str, str]):
        self.kinds = kinds
        self.nodes: Dict[str, dict] = {}
        self.links: set = set()

    def node(self, nid: str, title: str = "", where: str = "") -> dict:
        kind = "result" if nid.endswith(".results") else self.kinds.get(nid[0], "note")
        n = self.nodes.setdefault(nid, {"kind": kind, "title": "", "status": "", "files": [], "metrics": {},
                                        "sources": []})
        if title and not n["title"]:
            n["title"] = title
        if where and where not in n["files"]:
            n["files"].append(where)
        return n

    def attr(self, nid: str, key: str, value: str, where: str) -> None:
        key = key.lower()
        n = self.node(nid, where=where)
        if key in RELS:
            for target in _ids(value, self.kinds):
                self.links.add((nid, RELS[key], target))
        elif key == "status":
            n["status"] = value.strip().lower().rstrip(".")
        elif key == "metrics":
            n["metrics"].update(_metrics(value))
        elif key in ("sources", "source"):
            n["sources"] = sorted(set(n["sources"]) | {s.strip() for s in re.split(r"[,;]", value) if s.strip()})


def read_lines(m: Model, lines: Iterable[str], where: str, def_rx: re.Pattern) -> List[Tuple[str, int, int]]:
    """Definitions and their attribute lines. Returns (id, first line, last line) of each definition."""
    found: List[Tuple[str, int, int]] = []
    current: Optional[str] = None
    for i, line in enumerate(lines, 1):
        if not line.strip():
            continue  # a heading is usually followed by a blank line before its `status:` and links
        d = def_rx.match(line)
        a = ATTR_RX.match(line)
        if d and not a:
            current = d.group(1)
            m.node(current, d.group(2).strip(" *"), where)
            found.append((current, i, i))
        elif a and current:
            m.attr(current, a.group(1), a.group(2), where)
            found[-1] = (found[-1][0], found[-1][1], i)
        elif line.lstrip().startswith("#") and current:
            current = None   # a new heading ends the definition's attributes
    return found


def read_comment(m: Model, text: str, where: str, def_rx: re.Pattern) -> None:
    """`research-diff: E5 tests H2` / `research-diff: E5: title` / `research-diff: status: done` in a comment."""
    last: Optional[str] = None
    for body in COMMENT_RX.findall(text):
        d = def_rx.match(body)
        rel = re.match(rf"^([A-Za-z]\d+[a-z]?)\s+({'|'.join(RELS)})\s+(.+)$", body.strip(), re.I)
        if rel:
            last = rel.group(1)
            m.node(last, where=where)
            m.attr(last, rel.group(2), rel.group(3), where)
        elif d:
            last = d.group(1)
            m.node(last, d.group(2), where)
        elif last:
            a = ATTR_RX.match(body)
            if a:
                m.attr(last, a.group(1), a.group(2), where)


def _mini_yaml_block(text: str) -> Optional[dict]:
    """The `research:` block of a YAML file: one level of `key: value` (lists as [a, b] or `- a` lines)."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^(\s*)research\s*:\s*$", line)
        if not m:
            continue
        indent, out, key = len(m.group(1)), {}, None
        for nxt in lines[i + 1:]:
            if not nxt.strip() or nxt.lstrip().startswith("#"):
                continue
            ind = len(nxt) - len(nxt.lstrip())
            if ind <= indent:
                break
            item = re.match(r"^\s*-\s*(.+)$", nxt)
            kv = re.match(r"^\s*([A-Za-z_ ]+?)\s*:\s*(.*)$", nxt)
            if item and key:
                out.setdefault(key, [])
                if isinstance(out[key], list):
                    out[key].append(item.group(1).strip().strip("'\""))
            elif kv:
                key, val = kv.group(1).strip(), kv.group(2).strip()
                if val.startswith("[") and val.endswith("]"):
                    out[key] = [x.strip().strip("'\"") for x in val[1:-1].split(",") if x.strip()]
                elif val:
                    out[key] = val.strip("'\"")
        return out
    return None


def config_block(text: str, path: str) -> Optional[dict]:
    try:
        if path.endswith(".json"):
            data = json.loads(text)
            return data.get("research") if isinstance(data, dict) and isinstance(data.get("research"), dict) else None
        if path.endswith(".toml"):
            data = tomllib.loads(text)
            return data.get("research") if isinstance(data.get("research"), dict) else None
    except (ValueError, tomllib.TOMLDecodeError):
        return None
    return _mini_yaml_block(text)


def read_results(text: str, path: str) -> Dict[str, float]:
    """The numbers of a results file: a JSON object (nested keys joined by '.') or a CSV's last row."""
    out: Dict[str, float] = {}
    if path.endswith(".json"):
        try:
            data = json.loads(text)
        except ValueError:
            return {}

        def walk(prefix: str, v: Any) -> None:
            if isinstance(v, bool):
                return
            if isinstance(v, (int, float)):
                out[prefix] = float(v)
            elif isinstance(v, dict):
                for k, x in v.items():
                    walk(f"{prefix}.{k}" if prefix else str(k), x)
        walk("", data)
    elif path.endswith((".csv", ".tsv")):
        rows = list(csv.DictReader(io.StringIO(text), delimiter="\t" if path.endswith(".tsv") else ","))
        for k, v in (rows[-1] if rows else {}).items():
            if k and v and NUM_RX.match(v.strip()):
                out[k.strip()] = float(v)
    return out


def _resolve(base: str, ref: str, files: set) -> Optional[str]:
    for cand in (str(PurePosixPath(base).parent / ref), ref):
        norm = str(PurePosixPath(cand))
        parts: List[str] = []
        for p in norm.split("/"):
            if p == "..":
                if parts:
                    parts.pop()
            elif p and p != ".":
                parts.append(p)
        joined = "/".join(parts)
        if joined in files:
            return joined
    return None


def extract(source, cfg: Dict[str, Any]) -> dict:
    """The research map of one source (a commit, a snapshot of the working tree, or a folder)."""
    kinds = cfg["kinds"]
    def_rx = _def_rx(kinds)
    skip = segment_rx(cfg["skip"])
    ignore = [glob_rx(p) for p in cfg.get("ignore", [])]
    files = [f for f in source.files if not skip.search(f) and not any(r.match(f) for r in ignore)]
    fileset = set(source.files)
    pick = lambda globs: [f for f in files if any(glob_rx(g).match(f) for g in globs)]  # noqa: E731
    m = Model(kinds)
    warnings: List[str] = []

    for f, text in source.read_many(pick(cfg["notes"])).items():
        read_lines(m, text.splitlines(), f, def_rx)
    for f, text in source.read_many(pick(cfg["paper"])).items():
        lines = text.splitlines()
        comments = [(re.search(r"(?<!\\)%(.*)$", ln) or [None, ""])[1] for ln in lines]
        for nid, first, last in read_lines(m, comments, f, def_rx):
            # A claim's sources: the citations of the paragraph its marker sits in.
            lo = first
            while lo > 1 and lines[lo - 2].strip():
                lo -= 1
            hi = last
            while hi < len(lines) and lines[hi].strip():
                hi += 1
            cites = {k.strip() for ln in lines[lo - 1:hi] for ks in CITE_RX.findall(ln) for k in ks.split(",")}
            if cites:
                n = m.node(nid)
                n["sources"] = sorted(set(n["sources"]) | cites)
    for f, text in source.read_many(pick(cfg["scripts"]) + pick(cfg["configs"])).items():
        read_comment(m, text, f, def_rx)
        block = config_block(text, f) if f in pick(cfg["configs"]) else None
        if not block or not block.get("id"):
            continue
        nid = str(block["id"])
        m.node(nid, str(block.get("title") or ""), f)
        for key in ("tests", "answers", "relies on", "supports", "weakens"):
            val = block.get(key) or block.get(key.replace(" ", "_"))
            if val:
                m.attr(nid, key, ", ".join(val) if isinstance(val, list) else str(val), f)
        if block.get("status"):
            m.attr(nid, "status", str(block["status"]), f)
        for ref in ([block["results"]] if isinstance(block.get("results"), str) else block.get("results") or []):
            path = _resolve(f, ref, fileset)
            if path is None:
                warnings.append(f"{nid}: results file {ref} is not in the repository")
                continue
            r = m.node(f"{nid}.results", "", path)   # its box shows the file under the id
            r["metrics"].update(read_results(source.read(path), path))
            m.links.add((f"{nid}.results", "of", nid))

    nodes = m.nodes
    for src, rel, dst in sorted(m.links):
        if dst not in nodes:
            warnings.append(f"{src} {rel} {dst}, which is not defined anywhere")
    by = defaultdict(list)
    for src, rel, dst in m.links:
        by[(rel, dst)].append(src)
        by[(src, rel)].append(dst)
    for nid, n in sorted(nodes.items()):
        if n["kind"] == "experiment" and not by[(nid, "tests")]:
            warnings.append(f"{nid} tests no hypothesis")
        if n["kind"] == "hypothesis" and not by[("tests", nid)] and n["status"] in ("", "open"):
            warnings.append(f"{nid} is open and no experiment tests it")
        if n["kind"] == "claim":
            basis = by[(nid, "relies on")] + by[("supports", nid)]
            if not basis:
                warnings.append(f"{nid} relies on nothing: no result or hypothesis backs it")
            for b in by[(nid, "relies on")]:
                if nodes.get(b, {}).get("status") == "refuted":
                    warnings.append(f"{nid} relies on {b}, which is refuted")
            for w in by[("weakens", nid)]:
                warnings.append(f"{nid} is weakened by {w}")
    return {"ref": source.label, "nodes": {k: nodes[k] for k in sorted(nodes, key=_order)},
            "links": [list(x) for x in sorted(m.links)], "warnings": sorted(set(warnings))}


def _order(nid: str) -> tuple:
    m = re.match(r"([A-Za-z])(\d+)([a-z]?)(.*)", nid)
    return ("QHERC".find(m.group(1)), int(m.group(2)), m.group(3), m.group(4)) if m else (9, 0, "", nid)
