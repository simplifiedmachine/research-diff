"""`research-diff suggest`: your LLM proposes markers for notes and paper files that have none, as a patch.

It never writes a file. Every proposal is checked before it reaches the patch: the file is one it was shown, the line
exists, each new line reads as a marker in that file's own form (a Markdown definition or link line, a `% ` LaTeX
comment, a `# research-diff:` comment), and a new id is not one the research already uses. Apply the patch with
`git apply`, or edit it first, or drop it.

The LLM is the one your Claude Code uses (its settings, or ANTHROPIC_* in the environment), else an OpenAI-compatible
gateway exported in your shell (SYSTEM_DIFF_LLM_* or LLM_*), as system-diff's summary finds it. Only the files you
asked about are sent.
"""
from __future__ import annotations

import difflib
import json
import re
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from system_diff.extract import glob_rx
from system_diff.narrate import claude_llm, shell_llm
from system_diff.sources import git

from . import compare
from .extract import ATTR_RX, COMMENT_RX, _def_rx

SYSTEM = (
    "You add research markers to a researcher's own files so a tool can map their research. A marker is an id and a "
    "title: Q (question), H (hypothesis), E (experiment), R (result), F (finding), C (claim) and a number, e.g. 'H3: Warm-up removes "
    "the gap', followed by lines such as 'answers: Q1', 'tests: H2', 'of: E1', 'supports: H1', 'weakens: C1', 'contradicts: C2', 'relies "
    "on: H1, R2', 'status: open', 'metrics: acc=0.91'. In Markdown write them as headings or plain lines; in LaTeX as "
    "comments starting with '% '; in Python as '# research-diff: E2 tests H2'. Only mark what the text already says: "
    "never invent results, numbers or statuses. Reuse existing ids when the text is about them; new ids must not be in "
    "the list of existing ids. Answer with JSON only: {\"markers\": [{\"file\": path, \"after_line\": n, \"lines\": "
    "[...]}]}, where after_line is the line number the new lines go after (0 for the top)."
)


def _ask(s: Dict[str, Any], user: str, timeout: int = 120, system: str = "") -> str:
    system = system or SYSTEM
    if s.get("kind") == "openai":
        url, body = s["base_url"] + "/chat/completions", {"model": s["model"], "max_tokens": 4000,
                                                           "messages": [{"role": "system", "content": system},
                                                                        {"role": "user", "content": user}]}
        headers = {"content-type": "application/json", "authorization": "Bearer " + s["token"]}
    else:
        url, body = s["base_url"] + "/v1/messages", {"model": s["model"], "max_tokens": 4000, "system": system,
                                                      "messages": [{"role": "user", "content": user}]}
        headers = {"content-type": "application/json", "anthropic-version": "2023-06-01",
                   "authorization": "Bearer " + s["token"], "x-api-key": s["token"]}
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read())
    if s.get("kind") == "openai":
        return ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


def default_llm(root: Path) -> Optional[Callable[[str], str]]:
    s = claude_llm(root) or shell_llm()
    return (lambda user: _ask(s, user)) if s else None


def _valid(line: str, path: str, def_rx: re.Pattern) -> bool:
    if path.endswith(".tex"):
        body = line[1:].strip() if line.startswith("%") else None
        return bool(body) and bool(def_rx.match(body) or ATTR_RX.match(body))
    if path.endswith((".py", ".ipynb", ".yaml", ".yml", ".toml")):
        return bool(COMMENT_RX.search(line))
    return bool(def_rx.match(line) or ATTR_RX.match(line) or not line.strip())


def suggest(root: Path, files: List[str], ask: Callable[[str], str], config_path: Optional[str] = None) -> Dict[str, Any]:
    """{patch, accepted, refused}: the proposals that passed the checks as one unified diff, and why others did not."""
    bp, cfg, _ = compare.read(root, ".", config_path)
    def_rx = _def_rx(cfg["kinds"])
    texts = {f: (root / f).read_text(encoding="utf-8") for f in files if (root / f).is_file()}
    shown = "\n\n".join(f"=== {f}\n" + "\n".join(f"{i:4} {ln}" for i, ln in enumerate(t.splitlines(), 1))
                        for f, t in texts.items())
    user = (f"Existing ids: {', '.join(bp['nodes']) or 'none'}\n\nAdd markers to these files (line numbers on the "
            f"left are not part of the files):\n\n{shown[:60000]}")
    raw = ask(user)
    m = re.search(r"\{.*\}", raw, re.S)
    try:
        proposals = json.loads(m.group(0)).get("markers", []) if m else []
    except ValueError:
        proposals = []
    used = set(bp["nodes"])
    inserts: Dict[str, List[tuple]] = {}
    accepted, refused = [], []
    for p in proposals:
        f, at, lines = p.get("file"), p.get("after_line"), [str(x) for x in p.get("lines") or []]
        if f not in texts:
            refused.append(f"{f}: not one of the files it was shown")
            continue
        n = len(texts[f].splitlines())
        if not isinstance(at, int) or not 0 <= at <= n:
            refused.append(f"{f}: line {at} does not exist")
            continue
        bad = [ln for ln in lines if not _valid(ln, f, def_rx)]
        if bad or not lines:
            refused.append(f"{f}:{at}: not a marker: {bad[0] if bad else '(nothing)'}")
            continue
        new_ids = [d.group(1) for ln in lines if (d := def_rx.match(ln.lstrip('% ')))]
        clash = [i for i in new_ids if i in used]
        if clash:
            refused.append(f"{f}:{at}: {clash[0]} is already used")
            continue
        used |= set(new_ids)
        inserts.setdefault(f, []).append((at, lines))
        accepted.append(f"{f}:{at}: " + "; ".join(lines)[:120])
    patch = []
    for f, items in sorted(inserts.items()):
        old = texts[f].splitlines(keepends=True)
        new = list(old)
        for at, lines in sorted(items, key=lambda x: -x[0]):   # from the bottom, so line numbers hold
            new[at:at] = [ln + "\n" for ln in lines] + (["\n"] if f.endswith(".md") else [])
        patch += difflib.unified_diff(old, new, f"a/{f}", f"b/{f}")
    return {"patch": "".join(patch), "accepted": accepted, "refused": refused}


def untagged(root: Path, config_path: Optional[str] = None) -> List[str]:
    """Notes and paper files with no marker yet."""
    bp, cfg, _ = compare.read(root, ".", config_path)
    tagged = {f for n in bp["nodes"].values() for f in n["files"]}
    tracked = git("ls-files", cwd=root).splitlines()
    globs = [glob_rx(g) for g in cfg["notes"] + cfg["paper"]]
    skip = [glob_rx(g) for g in cfg.get("ignore", [])]
    return [f for f in tracked if any(r.match(f) for r in globs) and not any(r.match(f) for r in skip) and f not in tagged]


def run(root: Path, files: List[str], out: str = "", config_path: Optional[str] = None,
        ask: Optional[Callable[[str], str]] = None) -> int:
    files = files or untagged(root, config_path)
    if not files:
        print("every notes and paper file already has markers; name files to read them anyway")
        return 0
    ask = ask or default_llm(root)
    if ask is None:
        print("no LLM to ask: research-diff uses your Claude Code's settings or ANTHROPIC_*, else SYSTEM_DIFF_LLM_*")
        return 1
    got = suggest(root, files, ask, config_path)
    for line in got["refused"]:
        print(f"refused  {line}")
    if not got["patch"]:
        print("no marker to suggest")
        return 0
    path = Path(out) if out else Path(git("rev-parse", "--absolute-git-dir", cwd=root).strip()) / "research-diff" / "suggest.patch"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(got["patch"], encoding="utf-8", newline="\n")
    for line in got["accepted"]:
        print(f"proposed {line}")
    print(f"\nnothing was changed: read {path}, then `git apply {path}` to take it")
    return 0


LINK_SYSTEM = (
    "You review a research paper's evidence. You are given its statements (claims and findings, with their paragraph), "
    "its hypotheses, and its results with their numbers, each with an id. Find links the authors have not written: "
    "evidence that SUPPORTS a statement, and above all evidence or other statements that CONTRADICT or WEAKEN one "
    "(a number that says otherwise, a result against a hypothesis a claim relies on, two statements that cannot both "
    "hold). Only links the given text and numbers show; never invent. Answer with JSON only: {\"links\": [{\"from\": id, "
    "\"rel\": \"supports\"|\"contradicts\"|\"weakens\", \"to\": id, \"why\": one sentence}]}.")
REVERSE_WORD = {"supports": "supported by", "contradicts": "contradicted by", "weakens": "weakened by"}


def _paragraph(text: str, line: int) -> str:
    lines = text.splitlines()
    lo, hi = line - 1, line - 1
    while lo > 0 and lines[lo - 1].strip():
        lo -= 1
    while hi + 1 < len(lines) and lines[hi + 1].strip():
        hi += 1
    return " ".join(ln.strip() for ln in lines[lo:hi + 1] if not ln.lstrip().startswith("%"))[:1200]


def links(root: Path, ask: Callable[[str], str], config_path: Optional[str] = None) -> Dict[str, Any]:
    """{patch, accepted, refused}: links the LLM proposes between existing nodes, written under the TARGET's marker in
    its reverse form (`% contradicted by: R4` under C1), checked: both ids exist, the link is new, the target's marker
    is in a notes or paper file."""
    from . import evidence
    bp, cfg, _ = compare.read(root, ".", config_path)
    g = evidence.build(bp, cfg)
    texts: Dict[str, str] = {}
    shown = []
    for nid, n in bp["nodes"].items():
        f = (n["files"] or [""])[0]
        if f and f not in texts and (root / f).is_file():
            texts[f] = (root / f).read_text(encoding="utf-8")
        if n["kind"] in ("claim", "finding"):
            para = _paragraph(texts.get(f, ""), n.get("line", 1)) if f.endswith(".tex") else ""
            shown.append(f"[{nid}] {n['kind']} ({g['nodes'].get(nid, {}).get('verdict', '')}): {n['title']}. {para}")
        elif n["kind"] in ("hypothesis", "result"):
            nums = ", ".join(f"{k}={v:g}" for k, v in list(n["metrics"].items())[:8])
            shown.append(f"[{nid}] {n['kind']} ({n['status'] or 'no status'}): {n['title']} {nums}".rstrip())
    have = {tuple(x) for x in bp["links"]}
    user = "Existing links:\n" + "\n".join(" ".join(x) for x in sorted(have)) + "\n\nNodes:\n" + "\n".join(shown)
    raw = ask(user)
    m = re.search(r"\{.*\}", raw or "", re.S)
    try:
        proposals = json.loads(m.group(0)).get("links", []) if m else []
    except ValueError:
        proposals = []
    inserts: Dict[str, List[tuple]] = {}
    accepted, refused = [], []
    for p in proposals:
        s, rel, t, why = str(p.get("from", "")), str(p.get("rel", "")), str(p.get("to", "")), str(p.get("why", ""))
        if s not in bp["nodes"] or t not in bp["nodes"] or s == t or rel not in REVERSE_WORD:
            refused.append(f"{s} {rel} {t}: not two nodes of the map and supports/contradicts/weakens")
            continue
        if (s, rel, t) in have:
            refused.append(f"{s} {rel} {t}: already written")
            continue
        f = next((x for x in bp["nodes"][t]["files"] if x.endswith((".md", ".tex"))), "")
        if not f or f not in texts:
            refused.append(f"{s} {rel} {t}: {t}'s marker is not in a notes or paper file")
            continue
        lines = texts[f].splitlines()
        at = bp["nodes"][t].get("line", 0)
        while at < len(lines) and ATTR_RX.match(lines[at].lstrip("% ") if f.endswith(".tex") else lines[at]):
            at += 1
        new = ("% " if f.endswith(".tex") else "") + f"{REVERSE_WORD[rel]}: {s}"
        inserts.setdefault(f, []).append((at, [new]))
        have.add((s, rel, t))
        accepted.append(f"{s} {rel} {t} ({f}:{at}): {why}"[:240])
    patch = []
    for f, items in sorted(inserts.items()):
        old = texts[f].splitlines(keepends=True)
        new_lines = list(old)
        for at, ls in sorted(items, key=lambda x: -x[0]):
            new_lines[at:at] = [ln + "\n" for ln in ls]
        patch += difflib.unified_diff(old, new_lines, f"a/{f}", f"b/{f}")
    return {"patch": "".join(patch), "accepted": accepted, "refused": refused}


def run_links(root: Path, out: str = "", config_path: Optional[str] = None,
              ask: Optional[Callable[[str], str]] = None) -> int:
    if ask is None:
        s = claude_llm(root) or shell_llm()
        ask = (lambda user: _ask(s, user, system=LINK_SYSTEM)) if s else None
    if ask is None:
        print("no LLM to ask: research-diff uses your Claude Code's settings or ANTHROPIC_*, else SYSTEM_DIFF_LLM_*")
        return 1
    got = links(root, ask, config_path)
    for line in got["refused"]:
        print(f"refused  {line}")
    if not got["patch"]:
        print("no new link to suggest")
        return 0
    path = Path(out) if out else Path(git("rev-parse", "--absolute-git-dir", cwd=root).strip()) / "research-diff" / "links.patch"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(got["patch"], encoding="utf-8", newline="\n")
    for line in got["accepted"]:
        print(f"proposed {line}")
    print(f"\nnothing was changed: read {path}, then `git apply {path}` to take it")
    return 0

