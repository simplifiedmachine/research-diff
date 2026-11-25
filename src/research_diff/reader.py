"""The Read tab's model: the paper as text you read, every item in it known and linked.

Each paragraph of the paper (followed through its \\input files) becomes readable text whose items are marked: the
claims and findings its markers define, every number the paper prints (matched to its result, or stale), every
\\ref, \\cite, figure and table. An item opens its chain, from the paper down to what stands behind it:

    number   -> the result it was checked against (the full value, the file and the line of the key)
             -> the experiment that result is of (its config, its `run:` command) -> the script that writes it
    claim    -> what supports and contradicts it, each opening in turn; its owner; its history
    figure   -> its image file -> the script that makes it        table -> its file -> the script that writes it
    cite     -> the bibliography entry                              ref   -> what it points at

The text reads as the PDF does: the paper's own macros expanded (\\newcommand, \\def), run-in \\paragraph titles bold at
the start of their paragraph, lists as list items, math as readable symbols, a table's cells as rows, \\ref as the
number LaTeX prints, \\cite as author and year; comments, the preamble and commented-out environments never shown.
Every decimal or percentage the paper prints, in a paragraph or a table, is an item: ok or stale when a result covers
it (the check the research made for that line, or the same comparison made here), unchecked when none does.

"Changed since the checkpoint" (the paragraphs whose text is not as it was when you last marked the research seen)
keeps the person informed of what agents changed, without asking anything of them.
"""
from __future__ import annotations

import bisect
import hashlib
import posixpath
import re
import unicodedata
from pathlib import Path, PureWindowsPath
from typing import Any, Dict, List, Optional, Tuple

from . import paper

SCRIPT_EXT = (".py", ".ipynb", ".sh", ".r", ".R", ".jl", ".m")
SCRIPT_MAX = 1_000_000
IMAGE_EXT = (".pdf", ".png", ".jpg", ".jpeg", ".svg", ".eps", ".pgf", ".gif", ".webp")
BIB_MAX = 24
BINARY_EXT = (".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".pt", ".pth", ".ckpt", ".npy", ".npz", ".pkl",
              ".parquet", ".h5", ".zip", ".gz")

# a number the paper prints, not part of a name (Model-2.5-7B, GPT-4, v1.2)
NUM_RX = re.compile(r"(?<![\w.\\])(?<!\w-)(?:(?<![-\w])-)?\d+(?:\.\d+)?(?:\s*\\?%)?(?![\w]|\.\d)")
SPECIAL_RX = re.compile(r"\\|\$|(?<![\w.\\])(?:(?<!-)-)?\d")
CMD_AT = re.compile(r"\\([a-zA-Z@]+)\*?|\\(.)", re.S)
CITE = {"cite", "citep", "citet", "citealp", "citealt", "citeauthor", "citeyear", "citeyearpar", "parencite",
        "textcite", "autocite", "footcite", "nocite", "Citep", "Citet"}
REF = {"ref", "cref", "Cref", "autoref", "eqref", "nameref", "pageref", "vref", "Vref", "subref"}
TEXT_CMDS = {"textbf": "b", "bfseries": "", "textit": "i", "emph": "i", "textsl": "i", "texttt": "tt", "textsc": "sc",
             "underline": "u", "uline": "u", "footnote": "note", "textsf": "", "textrm": "", "textup": "",
             "textmd": "", "textnormal": "", "text": "", "mbox": "", "hbox": "", "hl": "", "textsuperscript": "",
             "textsubscript": "", "tiny": "", "scriptsize": "", "footnotesize": "", "small": "", "normalsize": "",
             "large": "", "Large": "", "LARGE": "", "huge": "", "Huge": "", "enquote": "", "mathrm": "",
             "ensuremath": "", "makecell": "", "shortstack": "", "centerline": "", "uppercase": "", "MakeUppercase": ""}
DROP_ARGS = {"label": 1, "vspace": 1, "hspace": 1, "includegraphics": 1, "input": 1, "include": 1, "cmidrule": 1,
             "cline": 1, "bibliography": 1, "bibliographystyle": 1, "addbibresource": 1, "setlength": 2,
             "addtolength": 2, "phantom": 1, "hphantom": 1, "vphantom": 1, "color": 1, "rowcolor": 1,
             "cellcolor": 1, "columncolor": 1, "definecolor": 3, "rule": 2, "resizebox": 2, "scalebox": 1,
             "raisebox": 1, "newcommand": 2, "renewcommand": 2, "usepackage": 1, "documentclass": 1, "caption": 1,
             "thanks": 1, "graphicspath": 1, "pagestyle": 1, "thispagestyle": 1, "setcounter": 2, "fontsize": 2,
             "multicolumn": 2, "multirow": 2, "url": 0}
SYMBOLS = {"S": "§", "P": "¶", "ldots": "…", "dots": "…", "textellipsis": "…", "textendash": "–", "textemdash": "—",
           "textasciitilde": "~", "textbackslash": "\\", "textbar": "|", "textless": "<", "textgreater": ">",
           "textdegree": "°", "copyright": "©", "texttrademark": "™", "dag": "†", "ddag": "‡", "checkmark": "✓",
           "cmark": "✓", "xmark": "✗", "times": "×", "textpm": "±", "pm": "±", "eg": "e.g.", "ie": "i.e.",
           "etal": "et al.", "LaTeX": "LaTeX", "TeX": "TeX", "quad": " ", "qquad": " ", "newline": " ",
           "linebreak": " ", "par": " ", "textquotedblleft": "“", "textquotedblright": "”", "slash": "/",
           "ss": "ß", "o": "ø", "O": "Ø", "aa": "å", "ae": "æ", "l": "ł", "i": "ı", "euro": "€", "textsection": "§",
           "bullet": "•", "textbullet": "•", "rightarrow": "→", "to": "→", "approx": "≈", "sim": "∼"}
ESCAPES = {"%": "%", "&": "&", "_": "_", "#": "#", "$": "$", "{": "{", "}": "}", ",": " ", ";": " ", ":": " ",
           "!": "", " ": " ", "-": "", "/": "", "\\": " ", "@": ""}
ACCENTS = {"'": "\u0301", "`": "\u0300", "^": "\u0302", '"': "\u0308", "~": "\u0303", "=": "\u0304", ".": "\u0307",
           "c": "\u0327", "v": "\u030c", "u": "\u0306", "H": "\u030b", "k": "\u0328", "r": "\u030a"}
GREEK = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi pi rho sigma tau upsilon phi chi " \
        "psi omega".split()
MATH_SYM = {**{g: chr(0x3B1 + i + (1 if i >= 17 else 0)) for i, g in enumerate(GREEK)},
            **{g.title(): chr(0x391 + i + (1 if i >= 17 else 0)) for i, g in enumerate(GREEK)},
            "varepsilon": "ε", "vartheta": "ϑ", "varphi": "φ", "varrho": "ϱ", "varsigma": "ς", "leq": "≤", "le": "≤",
            "geq": "≥", "ge": "≥", "neq": "≠", "ne": "≠", "approx": "≈", "sim": "∼", "simeq": "≃", "times": "×",
            "cdot": "·", "pm": "±", "mp": "∓", "to": "→", "rightarrow": "→", "leftarrow": "←", "Rightarrow": "⇒",
            "Leftrightarrow": "⇔", "mapsto": "↦", "infty": "∞", "in": "∈", "notin": "∉", "subset": "⊂",
            "subseteq": "⊆", "cup": "∪", "cap": "∩", "sum": "∑", "prod": "∏", "int": "∫", "partial": "∂",
            "nabla": "∇", "forall": "∀", "exists": "∃", "ell": "ℓ", "mid": "|", "ll": "≪", "gg": "≫",
            "propto": "∝", "equiv": "≡", "ldots": "…", "cdots": "⋯", "dots": "…", "top": "⊤", "circ": "∘",
            "star": "⋆", "prime": "′", "emptyset": "∅", "varnothing": "∅", "neg": "¬", "land": "∧", "lor": "∨",
            "langle": "⟨", "rangle": "⟩", "lvert": "|", "rvert": "|", "vert": "|", "Vert": "‖", "%": "%",
            "log": "log", "exp": "exp", "min": "min", "max": "max", "arg": "arg", "argmin": "argmin",
            "argmax": "argmax", "sup": "sup", "inf": "inf", "lim": "lim", "det": "det", "sin": "sin", "cos": "cos",
            "tanh": "tanh", "Pr": "Pr", "uparrow": "↑", "downarrow": "↓", "checkmark": "✓", "dagger": "†",
            "ast": "∗", "setminus": "∖", "perp": "⊥", "wedge": "∧", "vee": "∨", "oplus": "⊕", "otimes": "⊗"}
MATH_FONT = {"mathrm", "mathbf", "mathit", "mathsf", "mathtt", "text", "textrm", "textbf", "textit", "operatorname",
             "mathcal", "boldsymbol", "bm", "mathbb", "mathfrak", "mathscr", "hat", "bar", "tilde", "widehat",
             "widetilde", "overline", "vec", "dot", "ddot", "mbox", "emph", "textsc"}
BB = {"R": "ℝ", "N": "ℕ", "Z": "ℤ", "Q": "ℚ", "C": "ℂ", "E": "𝔼", "P": "ℙ"}
SUP = str.maketrans("0123456789+-=()ni", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱ")
SUB = str.maketrans("0123456789+-=()", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎")
LISTS = {"itemize": "itemize", "enumerate": "enumerate", "description": "description", "compactitem": "itemize",
         "compactenum": "enumerate", "inparaenum": "enumerate"}
DISPLAY = {"equation", "align", "gather", "multline", "eqnarray", "displaymath", "flalign", "alignat", "math"}
EQ_BEGIN_RX = re.compile(r"\\begin\{(equation|align|gather|multline|eqnarray|flalign|alignat)(\*?)\}")
ONE_NUMBER = {"equation", "multline"}
TABULAR = {"tabular", "tabularx", "tabular*", "tabulary", "longtable", "supertabular"}
HIDE = {"comment", "verbatim", "lstlisting", "minted", "tikzpicture", "algorithm", "algorithmic", "algorithm2e",
        "filecontents", "pgfpicture", "forest"}
THEOREMS = {"theorem", "lemma", "proposition", "corollary", "definition", "remark", "example", "proof",
            "assumption", "hypothesis", "conjecture", "observation", "claim", "fact", "note", "question"}
RULES_RX = re.compile(r"\\(?:toprule|midrule|bottomrule|hline|specialrule|addlinespace|morecmidrules|endhead|endfirsthead"
                      r"|endfoot|endlastfoot)\b(?:\[[^\]]*\])?(?:\{[^}]*\}){0,3}|\\c(?:mid)?(?:line|rule)(?:\([^)]*\))?"
                      r"(?:\[[^\]]*\])?\{[^}]*\}")
MACRO_DEF_RX = re.compile(r"\\(?:re|provide)?newcommand\*?\s*\{?\s*\\([a-zA-Z@]+)\s*\}?\s*(?:\[(\d)\])?\s*(\[[^\]]*\])?"
                          r"\s*(?=\{)|\\(?:def|gdef|DeclareRobustCommand\*?)\s*\{?\\([a-zA-Z@]+)\}?((?:#\d)*)\s*(?=\{)")
TITLE_RX = re.compile(r"\\(?:title|[a-z]*title)\s*(?:\[[^\]]*\])?\s*\{")


def _tid(*parts: Any) -> str:
    return hashlib.sha1("\0".join(map(str, parts)).encode()).hexdigest()[:12]


def inside(root: Path, path: str) -> Optional[Path]:
    """The file a repository path names, when it is inside the repository: not absolute, no drive, no way out by
    '..' or by a symbolic link, never in .git. None otherwise."""
    p = str(path or "").replace("\\", "/")
    if not p or PureWindowsPath(p).drive or PureWindowsPath(p).root or p.startswith("/") or \
            ".git" in p.split("/") or ".." in p.split("/"):
        return None
    try:
        top = Path(root).resolve()
        got = (top / p).resolve()
        got.relative_to(top)
    except (OSError, ValueError, RuntimeError):
        return None
    return got


def _text(root: Path, path: str) -> str:
    p = inside(root, path)
    if p is None:
        return ""
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


# ── LaTeX, read ─────────────────────────────────────────────────────────────────────────────────────────────────────

def _group(s: str, i: int) -> Tuple[str, int]:
    """The braced group at s[i] (after spaces): (its content, the index after it). A group that does not close on
    this text runs to its end. Not a group: one token (a command or a character), or ("", i)."""
    n = len(s)
    while i < n and s[i] in " \t\n":
        i += 1
    if i >= n:
        return "", i
    if s[i] == "{":
        depth = 0
        for j in range(i, n):
            c = s[j]
            if c == "\\":
                continue
            if c == "{" and (j == 0 or s[j - 1] != "\\"):
                depth += 1
            elif c == "}" and s[j - 1] != "\\":
                depth -= 1
                if depth == 0:
                    return s[i + 1:j], j + 1
        return s[i + 1:], n
    if s[i] == "\\":
        m = CMD_AT.match(s, i)
        return (m.group(0), m.end()) if m else ("", i + 1)      # a lone backslash at the end of the text
    if s[i] in "}[]":
        return "", i
    return s[i], i + 1


def _opt(s: str, i: int) -> Tuple[str, int]:
    """An optional [argument] at s[i] (after spaces): (its content, the index after it), or ("", i)."""
    j = i
    while j < len(s) and s[j] in " \t":
        j += 1
    if j >= len(s) or s[j] != "[":
        return "", i
    depth = 0
    for k in range(j, len(s)):
        if s[k] == "[":
            depth += 1
        elif s[k] == "]":
            depth -= 1
            if depth == 0:
                return s[j + 1:k], k + 1
    return s[j + 1:], len(s)


def _chars(s: str) -> str:
    """Plain text between commands: TeX's ligatures and quotes, ties as spaces, braces dropped."""
    s = s.replace("---", "—").replace("--", "–").replace("``", "“").replace("''", "”").replace("`", "‘")
    return s.replace("~", " ").replace("{", "").replace("}", "").replace("\t", " ")


def _accent(acc: str, ch: str) -> str:
    return unicodedata.normalize("NFC", ch + ACCENTS[acc]) if ch else ""


def math_text(m: str) -> str:
    """Inline math as readable text: α ≤ 0.05, x², a/b, ℝ."""
    out: List[str] = []
    i, n = 0, len(m)
    while i < n:
        c = m[i]
        if c == "\\":
            cm = CMD_AT.match(m, i)
            if cm is None:                    # a lone backslash at the end (`x \`, a trimmed control space)
                i += 1
                continue
            name, one = cm.group(1), cm.group(2)
            i = cm.end()
            if one is not None:
                out.append({"%": "%", ",": " ", ";": " ", ":": " ", "!": "", " ": " ", "{": "{", "}": "}", "|": "‖",
                            "\\": " ", "_": "_", "&": "&", "#": "#", "$": "$"}.get(one, ""))
            elif name in ("frac", "dfrac", "tfrac", "cfrac", "binom"):
                a, i = _group(m, i)
                b, i = _group(m, i)
                a, b = math_text(a), math_text(b)
                wrap = (lambda x: x if len(x) <= 1 or re.fullmatch(r"[\w.]+", x) else f"({x})")
                out.append(f"{wrap(a)}/{wrap(b)}" if name != "binom" else f"C({a}, {b})")
            elif name == "sqrt":
                _o, i = _opt(m, i)
                a, i = _group(m, i)
                a = math_text(a)
                out.append("√" + (a if len(a) <= 1 else f"({a})"))
            elif name in MATH_FONT:
                a, i = _group(m, i)
                a = math_text(a)
                out.append(BB.get(a, a) if name == "mathbb" else a)
            elif name in ("left", "right", "big", "Big", "bigg", "Bigg", "bigl", "bigr", "Bigl", "Bigr", "middle"):
                continue
            elif name in MATH_SYM:
                out.append(MATH_SYM[name] + (" " if name.isalpha() and len(MATH_SYM[name]) > 1 else ""))
            elif name in SYMBOLS:
                out.append(SYMBOLS[name])
            elif name in DROP_ARGS:
                for _k in range(DROP_ARGS[name]):
                    _a, i = _group(m, i)
            continue
        if c in "^_":
            a, i = _group(m, i + 1)
            a = math_text(a)
            table, plain_ = (SUP, "^") if c == "^" else (SUB, "_")
            fits = a and all(ch in "0123456789+-=()" + ("ni" if c == "^" else "") for ch in a)
            out.append(a.translate(table) if fits else plain_ + (a if len(a) <= 1 else f"({a})"))
            continue
        if c in "{}":
            i += 1
            continue
        if c == "~":
            out.append(" ")
            i += 1
            continue
        out.append(c)
        i += 1
    return re.sub(r"\s+", " ", "".join(out)).strip()


def _short_authors(author: str) -> str:
    names = [a.strip() for a in re.split(r"\s+and\s+", author) if a.strip()]
    last = [(a.split(",")[0] if "," in a else a.split()[-1]).strip() for a in names if a.split()]
    if not last:
        return ""
    if last[-1].lower() == "others":
        return last[0] + " et al."
    return last[0] if len(last) == 1 else f"{last[0]} & {last[1]}" if len(last) == 2 else last[0] + " et al."


def bib_entries(text: str) -> Dict[str, dict]:
    """The entries of a .bib file: {key: {"type", "line", fields…}}, fields with nested braces read whole."""
    out: Dict[str, dict] = {}
    for m in re.finditer(r"@(\w+)\s*([{(])\s*([^,\s{}()]+)\s*,", text):
        kind = m.group(1).lower()
        if kind in ("comment", "string", "preamble"):
            continue
        close = "}" if m.group(2) == "{" else ")"
        depth, j = 1, m.end()
        while j < len(text) and depth:
            if text[j] == m.group(2) and m.group(2) == "{":
                depth += 1
            elif text[j] == close:
                depth -= 1
            j += 1
        body = text[m.end():j - 1]
        e: Dict[str, Any] = {"type": kind, "line": text[:m.start()].count("\n") + 1}
        k = 0
        while k < len(body):
            f = re.compile(r"\s*,?\s*([\w-]+)\s*=\s*").match(body, k)
            if not f:
                break
            k = f.end()
            if k < len(body) and body[k] == "{":
                val, k = _group(body, k)
            elif k < len(body) and body[k] == '"':
                end = body.find('"', k + 1)
                end = len(body) if end < 0 else end
                val, k = body[k + 1:end], end + 1
            else:
                v = re.compile(r"[^,]*").match(body, k)
                val, k = v.group(0), v.end()
            e[f.group(1).lower()] = re.sub(r"\s+", " ", _chars(re.sub(r"\\([&%_#$])", r"\1", val))).strip()
        out.setdefault(m.group(3), e)
    return out


class Model:
    """The paper read for one study: blocks in reading order, and the items in them."""

    def __init__(self, S: dict):
        from . import paperdiagram
        from .extract import _def_rx
        self.S, self.root = S, Path(S["root"])
        self.bp, self.g = S["map"], S["graph"]
        self.files = [x["path"] for x in self.bp.get("paper", [])]
        self.lay = paperdiagram.layout(self.root, self.files) if self.files else {"boxes": [], "docs": [],
                                                                                   "other": [], "parsed": {}}
        self.def_rx = _def_rx({"Q": "question", "H": "hypothesis", "E": "experiment", "R": "result", "F": "finding",
                               "C": "claim"})
        self.items: Dict[str, dict] = {}
        self.checks: Dict[Tuple[str, int], List[dict]] = {}
        for c in self.bp.get("checks", []):
            self.checks.setdefault((c.get("file", ""), int(c.get("line") or 0)), []).append(c)
        for i in self.bp.get("issues", []):
            self.checks.setdefault((i.get("file", ""), int(i.get("line") or 0)), []).append({**i, "sign": "-"})
        self._lines: Dict[str, List[str]] = {}
        self._hid: Dict[str, set] = {}
        self._pools: Dict[tuple, tuple] = {}
        self._k: Dict[Tuple[str, int], int] = {}
        self.title = ""
        self._tracked: Optional[List[str]] = None
        self._numbered: Dict[Tuple[str, int], str] = {}      # a heading's number, by its file and line
        self.macros = self._macros()
        self._macro_rx = re.compile(r"\\(" + "|".join(sorted(map(re.escape, self.macros), key=len, reverse=True))
                                    + r")(?![a-zA-Z@])") if self.macros else None
        self.bib = self._bib()
        self.labels = self._labels()
        self._changed = self._changed_lines()
        self.sections = self._sections()

    def lines(self, f: str) -> List[str]:
        if f not in self._lines:
            self._lines[f] = _text(self.root, f).splitlines()
        return self._lines[f]

    # ── what the paper defines: its macros, its bibliography, its labels ────────────────────────────────────────────
    def _macros(self) -> Dict[str, Tuple[int, Optional[str], str]]:
        """{name: (arguments, the first one's default or None, body)} from \\newcommand and \\def in the paper."""
        out: Dict[str, Tuple[int, Optional[str], str]] = {}
        for f in self.files:
            text = "\n".join(paper.COMMENT_RX.sub("", ln) for ln in self.lines(f))
            for m in MACRO_DEF_RX.finditer(text):
                name = m.group(1) or m.group(4)
                if name in TEXT_CMDS or name in CITE or name in REF or name in SYMBOLS or name in DROP_ARGS:
                    continue
                nargs = int(m.group(2) or 0) if m.group(1) else len(m.group(5) or "") // 2
                default = m.group(3)[1:-1] if m.group(1) and m.group(3) else None
                body, _e = _group(text, m.end())
                if "\\begin" in body or "newcommand" in body or ("\\" + name) in body:
                    continue
                out.setdefault(name, (nargs, default, body))
            if not self.title:
                for m in TITLE_RX.finditer(text):
                    if re.search(r"running|short|subtitle", text[m.start():m.end()]):
                        continue
                    t, _e = _group(text, m.end() - 1)
                    self.title = re.sub(r"\s+", " ", _chars(re.sub(r"\\[a-zA-Z]+\*?|\\\\", " ", t))).strip()
                    if self.title:
                        break
        return out

    def expand(self, s: str) -> str:
        """The paper's own macros expanded in a line of its text (a few rounds: a macro may use another)."""
        if self._macro_rx is None or "\\" not in s:
            return s
        for _round in range(4):
            out, pos, hit = [], 0, False
            for m in self._macro_rx.finditer(s):
                if m.start() < pos:
                    continue
                nargs, default, body = self.macros[m.group(1)]
                i = m.end()
                args = []
                for k in range(nargs):
                    if k == 0 and default is not None:
                        a, j = _opt(s, i)
                        args.append(a if j != i else default)
                        i = j
                        continue
                    a, i = _group(s, i)
                    args.append(a)
                if nargs == 0 and s.startswith("{}", i):
                    i += 2
                text = body
                for k, a in enumerate(args, 1):
                    text = text.replace(f"#{k}", a)
                out.append(s[pos:m.start()] + text + (" " if nargs == 0 and i < len(s) and s[i:i + 1].isalpha() and
                                                      text[-1:].isalpha() else ""))
                pos, hit = i, True
            if not hit:
                return s
            s = "".join(out) + s[pos:]
        return s

    def tracked(self) -> List[str]:
        """The repository's files (tracked, or untracked and not ignored), listed once."""
        if self._tracked is None:
            try:
                from .compare import WorkSource
                self._tracked = WorkSource(self.root).files
            except Exception:  # noqa: BLE001 - not a git repository: no files to look among
                self._tracked = []
        return self._tracked

    def _bib(self) -> Dict[str, dict]:
        """Every entry of the paper's .bib files: the ones its \\bibliography names, then any the study keeps in its
        paper's folders (the folder itself when the paper is at the repository's top), never another study's."""
        from . import studies
        names: List[str] = []
        for f in self.files:
            for m in re.finditer(r"\\(?:bibliography|addbibresource)\s*(?:\[[^\]]*\])?\{([^}]*)\}",
                                 "\n".join(paper.COMMENT_RX.sub("", ln) for ln in self.lines(f))):
                for b in m.group(1).split(","):
                    b = b.strip()
                    if b:
                        p = posixpath.normpath(posixpath.join(posixpath.dirname(f), b if b.endswith(".bib")
                                                              else b + ".bib"))
                        if p.startswith(("../", "/")) or p == ".." or inside(self.root, p) is None:
                            continue                  # outside the repository: never read
                        if p not in names:
                            names.append(p)
        sc = studies.scope(self.S.get("studies") or [], self.S.get("study") or "")
        bibs = [x for x in self.tracked() if x.endswith(".bib") and (sc is None or studies.of_study(x, sc[0]))
                and not any(part.startswith(".") for part in x.split("/")[:-1])]
        for d in sorted({posixpath.dirname(f) for f in self.files}):
            found = [x for x in bibs if (posixpath.dirname(x) == d if not d else x.startswith(d + "/"))][:BIB_MAX]
            names += [p for p in found if p not in names]
        out: Dict[str, dict] = {}
        for p in names[:BIB_MAX * 2]:
            text = _text(self.root, p)
            for k, e in bib_entries(text).items():
                out.setdefault(k, {**e, "file": p})
        return out

    def _labels(self) -> Dict[str, dict]:
        """{label: {"kind", "n", "title", "file", "line"}}: what each \\label names and the number LaTeX gives it —
        sections 1, 1.2 (A, A.1 in the appendix), figures and tables counted apart, equations in order."""
        out: Dict[str, dict] = {}
        sec = [0, 0, 0]
        counts = {"figure": 0, "table": 0, "equation": 0}
        appendix = False
        for b in self.lay["boxes"]:
            if b.appendix and not appendix:
                appendix, sec = True, [0, 0, 0]
            for f, lo, hi in b.ranges:
                parsed = self.lay["parsed"].get(f) or {}
                heads = {s["line"]: s for s in parsed.get("sections", [])}
                floats = [x for x in parsed.get("floats", []) if lo <= x["line"] <= hi]
                last: Optional[dict] = None
                lines = self.lines(f)
                eq: Optional[Tuple[str, bool]] = None      # the numbered-math environment open, and whether starred
                rows: List[Tuple[int, str]] = []
                for i in range(lo, min(hi, len(lines)) + 1):
                    body = paper.COMMENT_RX.sub("", lines[i - 1])
                    h = heads.get(i)
                    m = paper.SECTION_RX.search(body)
                    if h and m and 1 <= h["level"] <= 3:
                        lv = h["level"] - 1
                        if "*" not in body[m.start():m.start() + len(m.group(1)) + 2]:
                            sec[lv] += 1
                            sec[lv + 1:] = [0] * (2 - lv)
                            first = chr(64 + sec[0]) if appendix and 0 < sec[0] <= 26 else str(sec[0])
                            n = ".".join([first] + [str(x) for x in sec[1:lv + 1]])
                        else:
                            n = ""
                        self._numbered[(f, i)] = n
                        last = {"kind": "appendix" if appendix and lv == 0 else "section", "n": n,
                                "title": h["title"], "file": f, "line": i}
                    fl = next((x for x in floats if x["line"] <= i <= (x.get("end") or x["line"])), None)
                    if fl and i == fl["line"]:
                        counts[fl["kind"]] = counts.get(fl["kind"], 0) + 1
                    rest = body
                    if eq is None and not fl:
                        b = EQ_BEGIN_RX.search(body)
                        if b:
                            eq, rows, rest = (b.group(1), bool(b.group(2))), [], body[b.end():]
                    if eq is not None:
                        e = re.search(r"\\end\{" + eq[0] + r"\*?\}", rest)
                        rows.append((i, rest[:e.start()] if e else rest))
                        if e:
                            self._equations(f, eq, rows, counts, out)
                            eq = None
                        continue
                    for lab in paper.LABEL_RX.findall(body):
                        if fl:
                            out.setdefault(lab, {"kind": fl["kind"], "n": str(counts[fl["kind"]]),
                                                 "title": (fl.get("caption") or "")[:120], "file": f,
                                                 "line": fl["line"]})
                        elif last:
                            out.setdefault(lab, dict(last))
        return out

    @staticmethod
    def _equations(f: str, env: Tuple[str, bool], got: List[Tuple[int, str]], counts: dict, out: dict) -> None:
        """Number one displayed-math environment as LaTeX does: equation and multline once, align, gather and
        eqnarray once per row (rows split at \\\\), never when starred, \\nonumber or \\notag; each \\label takes
        the number of its own row."""
        name, starred = env
        rows: List[List[Tuple[int, str]]] = [[]]
        for ln, s in got:
            parts = re.split(r"(?<!\\)\\\\(?:\[[^\]]*\])?", s) if name not in ONE_NUMBER else [s]
            for k, part in enumerate(parts):
                if k:
                    rows.append([])
                rows[-1].append((ln, part))
        if name in ONE_NUMBER:
            rows = [[x for r in rows for x in r]]
        for row in rows:
            text = " ".join(s for _ln, s in row)
            if not text.strip() and row is rows[-1] and len(rows) > 1:
                continue                          # a trailing \\ before \end: no row of its own
            n = ""
            if not starred and not re.search(r"\\(?:nonumber|notag)\b", text):
                counts["equation"] += 1
                n = str(counts["equation"])
            for ln, s in row:
                for lab in paper.LABEL_RX.findall(s):
                    out.setdefault(lab, {"kind": "equation", "n": n, "title": "", "file": f, "line": ln})

    def _hidden(self, f: str) -> set:
        """The lines of a file the reader never shows: its preamble, what follows \\end{document}, commented-out and
        verbatim environments, \\iffalse … \\fi."""
        if f in self._hid:
            return self._hid[f]
        out: set = set()
        lines = self.lines(f)
        bodies = [paper.COMMENT_RX.sub("", ln) for ln in lines]
        doc = next((i for i, b in enumerate(bodies, 1) if "\\begin{document}" in b), 0)
        out |= set(range(1, doc + 1))
        end = next((i for i, b in enumerate(bodies, 1) if "\\end{document}" in b), 0)
        if end:
            out |= set(range(end, len(lines) + 1))
        hide, iffalse = None, 0
        for i, b in enumerate(bodies, 1):
            if hide is None:
                m = re.search(r"\\begin\{(\w+)\*?\}", b)
                if m and m.group(1) in HIDE:
                    hide = m.group(1)
                if re.search(r"\\iffalse\b", b):
                    iffalse += 1
            if hide is not None or iffalse:
                out.add(i)
            if hide is not None and re.search(r"\\end\{" + hide + r"\*?\}", lines[i - 1] if hide == "comment"
                                              else b):
                hide = None
            if iffalse and re.search(r"\\fi\b", b) and not re.search(r"\\iffalse\b", b):
                iffalse -= 1
        self._hid[f] = out
        return out

    # ── what changed since the checkpoint ────────────────────────────────────────────────────────────────────────
    def _changed_lines(self) -> Dict[str, set]:
        """{file: lines whose text is not in the checkpoint's version of the file}."""
        out: Dict[str, set] = {}
        try:
            from . import compare
            sha, _label = compare.resolve(self.root, "checkpoint")
            old_tree = compare.CommitTree(sha, self.root)
            olds = old_tree.read_many([f for f in self.files if f in set(old_tree.files)])
        except Exception:  # noqa: BLE001 - no checkpoint to compare with: nothing is marked
            return out
        for f in self.files:
            old = {ln.strip() for ln in (olds.get(f) or "").splitlines() if ln.strip()}
            new = self.lines(f)
            out[f] = {i for i, ln in enumerate(new, 1) if ln.strip() and ln.strip() not in old}
        return out

    def _is_changed(self, f: str, lo: int, hi: int) -> bool:
        ch = self._changed.get(f, set())
        return bool(ch) and any(i in ch for i in range(lo, hi + 1))

    # ── the text, block by block ────────────────────────────────────────────────────────────────────────────────
    def _sections(self) -> List[dict]:
        out = []
        for b in self.lay["boxes"]:
            blocks: List[dict] = []
            spans: List[list] = []
            for f, lo, hi in b.ranges:        # a heading splits the box's lines: read them as one text again
                if spans and spans[-1][0] == f and lo <= spans[-1][2] + 1:
                    spans[-1][2] = max(spans[-1][2], hi)
                else:
                    spans.append([f, lo, hi])
            for f, lo, hi in spans:
                self._range(f, lo, hi, b, blocks)
            for t in b.tables:                # an \input'ed table not read where it stands: a block of its own
                if not any(t in (blk.get("inputs") or []) for blk in blocks):
                    blocks.append(self._table_file(t))
            if not blocks:                    # a preamble and nothing else: nothing to read
                continue
            bad = sum(1 for blk in blocks if blk["kind"] == "para" for tk in blk["tokens"] if tk.get("state") == "stale")
            bad += sum(blk.get("stale", 0) for blk in blocks if blk["kind"] == "float")
            changed = sum(1 for blk in blocks if blk.get("changed"))
            out.append({"id": b.id, "title": b.title, "file": b.file, "line": b.line, "blocks": blocks,
                        "stale": bad, "changed": changed, "appendix": b.appendix,
                        "n": (self._head_n(b.file, b.line) or "")})
        return out

    def _head_n(self, f: str, line: int) -> str:
        return self._numbered.get((f, line), "")

    def _structural(self, body: str) -> bool:
        """A line of commands alone, none of them text (\\centering, \\label{…}, \\maketitle, \\conftitle{…}, ``]``):
        nothing the reader shows."""
        s = body.strip()
        i = 0
        while i < len(s):
            while i < len(s) and s[i] in " \t[]{}":
                i += 1
            if i >= len(s):
                return True
            m = CMD_AT.match(s, i)
            if not m or m.group(1) is None:
                return False
            name = m.group(1)
            if name in TEXT_CMDS or name in SYMBOLS or name in CITE or name in REF or name in (
                    "textcolor", "href", "url", "item", "begin", "end", "input", "include", "caption", "S"):
                return False
            i = m.end()
            while True:
                _o, j = _opt(s, i)
                if j != i:
                    i = j
                    continue
                k = i
                while k < len(s) and s[k] in " \t":
                    k += 1
                if k < len(s) and s[k] == "{":
                    _a, i = _group(s, k)
                    continue
                break
        return True

    def _range(self, f: str, lo: int, hi: int, box, out: List[dict]) -> None:
        """The blocks of some lines of a paper file, in order: headings, paragraphs (a run-in title, a list item, a
        theorem), displayed math, figures and tables."""
        lines = self.lines(f)
        tex = f.endswith(".tex")
        hidden = self._hidden(f) if tex else set()
        parsed = self.lay["parsed"].get(f) or {}
        heads = {s["line"]: s for s in parsed.get("sections", []) if lo <= s["line"] <= hi}
        floats = {x["line"]: x for x in parsed.get("floats", []) if lo <= x["line"] <= hi}
        lists: List[list] = []
        cur: Optional[dict] = None
        section = next((s["title"] for s in reversed(parsed.get("sections", [])) if s["line"] <= lo), "")

        def start(i: int, **kw) -> dict:
            nonlocal cur
            cur = {"lo": i, "hi": i, "lines": [], "markers": [], "runin": "", "item": "", "list": "", "depth": 0,
                   "no_check": False, **kw}
            return cur

        def close() -> None:
            nonlocal cur
            if cur is not None:
                blk = self._para(f, cur, section)
                if blk["tokens"] or blk["claims"]:
                    out.append(blk)
            cur = None

        i = lo
        last = min(hi, len(lines))
        while i <= last:
            raw = lines[i - 1]
            if i in hidden:
                i += 1
                continue
            if i in floats:
                close()
                out.append(self._float(f, floats[i], box))
                i = max(i, floats[i].get("end") or i) + 1
                continue
            if tex:
                cm = paper.COMMENT_RX.search(raw)
                comment = cm.group(0)[1:].strip() if cm else ""
                body = self.expand(paper.COMMENT_RX.sub("", raw))
            else:                             # a Markdown paper: `## C1: …` and `relies on: …` lines are its markers
                comment = raw if (self.def_rx.match(raw) or paper._attr(raw)) else ""
                body = "" if comment else raw
            if not raw.strip():
                close()
                i += 1
                continue
            mk = self.def_rx.match(comment) if comment else None
            if mk or "research-diff: no-check" in comment:
                here = cur if cur is not None else start(i)
                if mk:
                    here["markers"].append(mk.group(1))
                here["no_check"] = here["no_check"] or "research-diff: no-check" in comment
                here["hi"] = i
            if not body.strip():
                i += 1
                continue
            h = heads.get(i)
            if h:
                m = paper.SECTION_RX.search(body)
                rest = body[m.end():] if m else re.sub(r"^.*?\\begin\{abstract\}", "", body) if tex else ""
                if h["level"] >= 4:           # a run-in title: its paragraph's first words, in bold
                    if cur is None or cur["lines"] or cur["item"]:
                        close()
                        start(i)
                    cur["runin"], cur["hi"] = h["title"], i
                    if rest.strip() and not self._structural(rest):
                        cur["lines"].append((i, rest))
                else:
                    close()
                    section = h["title"]
                    out.append({"kind": "head", "level": h["level"], "text": h["title"], "file": f, "line": i,
                                "n": self._head_n(f, i)})
                    if rest.strip() and not self._structural(rest):
                        start(i)["lines"].append((i, rest))
                i += 1
                continue
            dm = re.match(r"\s*(\\\[|\$\$)", body) if tex else None
            if dm:                            # \[ … \] or $$ … $$: displayed math, read on to its close
                close()
                closer = "\\]" if dm.group(1) == "\\[" else "$$"
                j, got = i, []
                while j <= last:
                    piece = body if j == i else self.expand(paper.COMMENT_RX.sub("", lines[j - 1]))
                    got.append((j, piece))
                    if piece.find(closer, dm.end() if j == i else 0) >= 0:
                        break
                    j += 1
                out.append(self._display(f, got, section))
                i = j + 1
                continue
            b = re.match(r"\s*\\begin\{(\w+\*?)\}", body)
            if b:
                env = b.group(1)
                base = env.rstrip("*")
                rest = body[b.end():]
                if base in DISPLAY:
                    close()
                    j, got = i, []
                    while j <= last:
                        piece = self.expand(paper.COMMENT_RX.sub("", lines[j - 1]))
                        got.append((j, piece))
                        if re.search(r"\\end\{" + re.escape(env) + r"\}", piece) or (j > i and re.search(
                                r"\\end\{" + base, piece)):
                            break
                        j += 1
                    out.append(self._display(f, got, section))
                    i = j + 1
                    continue
                if env in TABULAR or base in TABULAR:
                    close()
                    j = i
                    while j <= last and not re.search(r"\\end\{" + re.escape(env) + r"\}", lines[j - 1]):
                        j += 1
                    out.append(self._loose_table(f, i, min(j, last), section))
                    i = j + 1
                    continue
                close()
                if base in LISTS:
                    lists.append([LISTS[base], 0])
                    _o, k = _opt(rest, 0)
                    body = rest[k:]
                elif base in THEOREMS:
                    name, k = _opt(rest, 0)
                    start(i, runin=base.title() + (f" ({self._plain(name)})" if name else "") + ".")
                    body = rest[k:]
                else:
                    _o, k = _opt(rest, 0)
                    body = rest[k:]
                if not body.strip() or self._structural(body):
                    i += 1
                    continue
            e = re.match(r"\s*\\end\{(\w+)\*?\}", body)
            if e:
                close()
                if LISTS.get(e.group(1)) and lists:
                    lists.pop()
                i += 1
                continue
            it = re.match(r"\s*\\item\b\s*", body)
            if it:
                close()
                label, k = _opt(body, it.end())
                kind = lists[-1][0] if lists else "itemize"
                if lists:
                    lists[-1][1] += 1
                n = lists[-1][1] if lists else 1
                mark = "" if kind == "description" else f"{n}. " if kind == "enumerate" else "• "
                start(i, item=mark, list=kind, depth=max(1, len(lists)), n=n,
                      runin=self._plain(label) if kind == "description" and label else "")
                body = body[k:]
                if not body.strip():
                    i += 1
                    continue
            inp = paper_input(body)
            if inp:
                t = next((x for x in box.tables if _same_file(x, inp)), None)
                if t:
                    close()
                    out.append(self._table_file(t))
                    i += 1
                    continue
            if self._structural(body):
                t = TITLE_RX.search(body)
                if t and not re.search(r"running|short|subtitle", t.group(0)):
                    close()
                    out.append({"kind": "head", "level": 0, "text": self._plain(_group(body, t.end() - 1)[0]),
                                "file": f, "line": i, "n": ""})
                i += 1
                continue
            if cur is None:
                start(i)
            cur["lines"].append((i, body))
            cur["hi"] = i
            i += 1
        close()

    def _plain(self, s: str) -> str:
        return "".join(t["s"] for t in self._walk(self.expand(s), "", 0, {"no_check": True}) if "s" in t).strip()

    def _ctx(self, markers: List[str], refs: List[str], section: str, f: str, line: int, no_check: bool) -> dict:
        nodes = self.bp.get("nodes", {})
        owners = [m for m in markers if m in nodes and nodes[m].get("kind") in ("claim", "finding")]
        return {"kind": "para", "owners": owners, "refs": refs, "no_check": no_check,
                "target": owners[0] if owners else f"§{section or 'Paper'}:{line}"}

    def _para(self, f: str, cur: dict, section: str) -> dict:
        lo, hi = cur["lo"], cur["hi"]
        refs = [r.strip() for _ln, s in cur["lines"] for rs in paper.REF_RX.findall(s) for r in rs.split(",")]
        ctx = self._ctx(cur["markers"], refs, section, f, lo, cur["no_check"])
        toks: List[dict] = []
        if cur["item"]:
            toks.append({"t": "text", "s": cur["item"], "mark": "item"})
        if cur["runin"]:
            toks.append({"t": "text", "s": cur["runin"].rstrip() + " ", "mark": "runin"})
        text, at = _joined(cur["lines"])     # one text: math, a citation or a group may run on past a line's end
        toks += self._walk(text, f, at, ctx)
        claims = []
        for nid in cur["markers"]:
            n = self.g["nodes"].get(nid, {})
            self.items.setdefault(nid, {"kind": "node", "id": nid, "file": f, "line": lo})
            claims.append({"id": nid, "verdict": n.get("verdict", ""), "title": n.get("title", ""),
                           "owner": n.get("owner", "")})
        toks = _merge(toks)
        blk = {"kind": "para", "file": f, "line": lo, "end": hi, "tokens": toks, "claims": claims,
               "changed": self._is_changed(f, lo, hi), "section": section}
        todo = sum(1 for t in toks if _placeholder(t))
        if todo:
            blk["todo"] = todo
        if cur["list"]:
            blk.update(list=cur["list"], depth=cur["depth"], n=cur.get("n", 1))
        if cur["runin"]:
            blk["runin"] = cur["runin"]
        return blk

    def _display(self, f: str, got: List[Tuple[int, str]], section: str) -> dict:
        """Displayed math (equation, align, \\[ … \\]): one readable line, its numbers items."""
        ctx = self._ctx([], [], section, f, got[0][0], False)
        toks: List[dict] = []
        for ln, s in got:
            s = re.sub(r"\\(?:begin|end)\{[^}]*\}(?:\{[^}]*\})?|\\label\{[^}]*\}|\\nonumber|\\notag|&|\\\[|\\\]|\$\$",
                       " ", s)
            s = s.replace("\\\\", " ")
            if s.strip():
                toks += self._math(s, f, ln, ctx)
        return {"kind": "para", "file": f, "line": got[0][0], "end": got[-1][0], "tokens": _merge(toks),
                "claims": [], "changed": self._is_changed(f, got[0][0], got[-1][0]), "section": section,
                "display": True}

    # ── one line of text, its items marked ──────────────────────────────────────────────────────────────────────
    def _walk(self, s: str, f: str, ln, ctx: dict, mark: str = "", color: str = "") -> List[dict]:
        """Some text of the paper as tokens. `ln` is its line, or, for text joined from several lines, a function
        from a place in it to the line that place is on."""
        out: List[dict] = []
        at = ln if callable(ln) else (lambda _p, _l=ln: _l)

        def sub(k: int):
            return lambda p: at(k + p)

        def text(x: str) -> None:
            if x:
                t = {"t": "text", "s": x}
                if mark:
                    t["mark"] = mark
                if color:
                    t["color"] = color
                out.append(t)

        i, n = 0, len(s)
        while i < n:
            m = SPECIAL_RX.search(s, i)
            if not m:
                text(_chars(s[i:]))
                break
            text(_chars(s[i:m.start()]))
            i = m.start()
            c = s[i]
            if c == "$":
                if s.startswith("$$", i):
                    j = s.find("$$", i + 2)
                    body, i = (s[i + 2:j], j + 2) if j >= 0 else (s[i + 2:], n)
                else:
                    j = i + 1
                    while j < n and not (s[j] == "$" and s[j - 1] != "\\"):
                        j += 1
                    body, i = s[i + 1:j], min(j + 1, n)
                out += self._math(body, f, sub(m.start() + (2 if s.startswith("$$", m.start()) else 1)), ctx)
                continue
            if c != "\\":                     # a number
                nm = NUM_RX.match(s, i)
                if not nm:
                    d = re.compile(r"-?\d+").match(s, i)
                    text(d.group(0))
                    i = d.end()
                    continue
                out.append(self._number(nm.group(0), f, at(i), ctx))
                i = nm.end()
                continue
            cm = CMD_AT.match(s, i)
            if cm is None:                    # a lone backslash at the end ("e.g.\ " once trailing spaces are trimmed)
                text(" ")
                i += 1
                continue
            name, one = cm.group(1), cm.group(2)
            i = cm.end()
            if one is not None:
                if one in ACCENTS and one not in ("c", "v", "u", "H", "k", "r"):
                    a, i = _group(s, i)
                    text(_accent(one, a[:1]) + a[1:])
                elif one in "()[]":
                    close = "\\)" if one == "(" else "\\]" if one == "[" else ""
                    if not close:
                        continue
                    j = s.find(close, i)
                    body, k, i = (s[i:j], i, j + 2) if j >= 0 else (s[i:], i, n)
                    out += self._math(body, f, sub(k), ctx)
                else:
                    text(ESCAPES.get(one, ""))
                continue
            if name in CITE:
                while True:
                    _o, j = _opt(s, i)
                    if j == i:
                        break
                    i = j
                k = _body_at(s, i)
                keys, i = _group(s, i)
                if name == "nocite":
                    continue
                for key in [x.strip() for x in keys.split(",") if x.strip()]:
                    out.append(self._cite(key, f, at(k + max(0, keys.find(key))), name))
                continue
            if name in REF:
                k = _body_at(s, i)
                keys, i = _group(s, i)
                for key in [x.strip() for x in keys.split(",") if x.strip()]:
                    out.append(self._ref(key, f, at(k + max(0, keys.find(key))), name))
                continue
            if name in ("textcolor", "colorbox"):
                _o, i = _opt(s, i)
                col, i = _group(s, i)
                k = _body_at(s, i)
                body, i = _group(s, i)
                out += self._walk(body, f, sub(k), ctx, mark, col.strip() or color)
                continue
            if name in ACCENTS and len(name) == 1:
                a, i = _group(s, i)
                text(_accent(name, a[:1]) + a[1:])
                continue
            if name == "href":
                _u, i = _group(s, i)
                k = _body_at(s, i)
                body, i = _group(s, i)
                out += self._walk(body, f, sub(k), ctx, mark or "link", color)
                continue
            if name == "url":
                body, i = _group(s, i)
                text(body)
                continue
            if name in ("multicolumn", "multirow"):
                _a, i = _group(s, i)
                _o, i = _opt(s, i)
                _b, i = _group(s, i)
                k = _body_at(s, i)
                body, i = _group(s, i)
                out += self._walk(body, f, sub(k), ctx, mark, color)
                continue
            if name in TEXT_CMDS:
                k = i
                while k < n and s[k] in " \t":
                    k += 1
                if k < n and s[k] == "{":
                    body, i = _group(s, k)
                    style = TEXT_CMDS[name] or mark
                    if name == "footnote":
                        text(" (")
                    out += self._walk(body, f, sub(k + 1), ctx, style, color)
                    if name == "footnote":
                        text(")")
                continue
            if name in SYMBOLS:
                text(SYMBOLS[name])
                if s.startswith("{}", i):
                    i += 2
                continue
            if name in DROP_ARGS:
                while True:
                    _o, j = _opt(s, i)
                    if j == i:
                        break
                    i = j
                if name == "cmidrule" and s.startswith("(", i):
                    i = s.find(")", i) + 1 or n
                for _k in range(DROP_ARGS[name]):
                    _a, i = _group(s, i)
                continue
            if name in ("begin", "end"):
                env, i = _group(s, i)
                if env.rstrip("*") in TABULAR:
                    _o, i = _opt(s, i)
                    _a, i = _group(s, i)
                continue
            if name == "item":
                _o, i = _opt(s, i)
                text("• ")
                continue
            while True:                       # any other command: dropped, its arguments read as text
                _o, j = _opt(s, i)
                if j == i:
                    break
                i = j
        return out

    def _math(self, body: str, f: str, ln, ctx: dict) -> List[dict]:
        """Inline math: readable symbols; a number in it (24\\%, -0.59, 0.05) an item like any other. `ln` as for
        _walk: the line, or where each place of the body is."""
        txt = math_text(body)
        if not txt:
            return []
        at = ln if callable(ln) else (lambda _p, _l=ln: _l)
        out: List[dict] = []
        pos, seen = 0, 0
        for m in NUM_RX.finditer(txt):
            s = m.group(0)
            k = body.find(s.rstrip("%").lstrip("-"), seen)      # where the number stands in the source: its line
            seen = k + 1 if k >= 0 else seen
            line = at(max(k, 0))
            if "." not in s and "%" not in s and self._check_for(f, line, _num(s, line)) is None:
                continue
            if txt[pos:m.start()].strip():
                out.append({"t": "math", "s": txt[pos:m.start()].strip()})
            out.append(self._number(s, f, line, ctx))
            pos = m.end()
        if txt[pos:].strip():
            out.append({"t": "math", "s": txt[pos:].strip()})
        if len(out) > 1 or (out and out[0]["t"] == "num"):
            # a number with its sign or unit (−0.59, 24%, 0.5 ± 0.1) reads as text around the item
            out = [{"t": "text", "s": " " + t["s"] + " "} if t["t"] == "math" and len(t["s"]) <= 2 and
                   not re.search(r"\w", t["s"]) else t for t in out]
        return out

    def _cite(self, key: str, f: str, ln: int, how: str) -> dict:
        iid = "cite:" + key
        it = self.items.setdefault(iid, {"kind": "cite", "key": key, "file": f, "line": ln, "places": []})
        if f and (f, ln) not in it["places"]:
            it["places"].append((f, ln))
        e = self.bib.get(key)
        say = key
        if e:
            who = _short_authors(e.get("author") or e.get("editor") or "")
            year = re.sub(r"\D", "", e.get("year", ""))[:4]
            say = (f"{who} {year}".strip() if how != "citeauthor" else who) or key
        return {"t": "cite", "s": say, "key": key, "id": iid, "at": f"{f}:{ln}"}

    def _ref(self, key: str, f: str, ln: int, how: str) -> dict:
        iid = "ref:" + key
        it = self.items.setdefault(iid, {"kind": "ref", "key": key, "file": f, "line": ln, "places": []})
        if f and (f, ln) not in it["places"]:
            it["places"].append((f, ln))
        lab = self.labels.get(key)
        say = key
        if lab:
            n = lab["n"] or key
            word = {"section": "Section", "appendix": "Appendix", "figure": "Figure", "table": "Table",
                    "equation": "Equation"}.get(lab["kind"], "")
            if how == "nameref":
                say = lab["title"] or n
            elif how == "eqref":
                say = f"({n})"
            elif how in ("cref", "Cref", "autoref", "vref", "Vref") and word:
                say = f"{word if how != 'cref' else word.lower()} {n}" if how != "autoref" else f"{word} {n}"
            elif how != "pageref":
                say = n
        return {"t": "ref", "s": say, "key": key, "id": iid, "at": f"{f}:{ln}"}

    # ── numbers ─────────────────────────────────────────────────────────────────────────────────────────────────
    def _number(self, raw: str, f: str, ln: int, ctx: dict) -> dict:
        val = raw.replace("\\%", "%").replace(" ", "")
        num = _num(val, ln)
        hit = self._check_for(f, ln, num)
        if hit is None and not ctx.get("no_check") and ("." in val or "%" in val):
            hit = self._judge(f, ln, num, ctx)
        if hit is None and "." not in val and "%" not in val:
            return {"t": "text", "s": val}
        self._k[(f, ln)] = self._k.get((f, ln), 0) + 1
        iid = f"num:{f}:{ln}:{self._k[(f, ln)]}"
        state = "unchecked" if hit is None else "ok" if hit.get("sign") == "+" else "stale"
        self.items[iid] = {"kind": "number", "file": f, "line": ln, "says": val, "check": hit}
        return {"t": "num", "s": val, "id": iid, "state": state}

    def _check_for(self, f: str, ln: int, num: dict) -> Optional[dict]:
        """The check the research made for this number: on its line, printed as it is (87.4%, 87.4) or of the same
        value and unit."""
        cands = self.checks.get((f, ln), [])
        best = None
        for c in cands:
            p = _printed(c)
            if not p:
                continue
            if p == num["raw"]:
                return c
            try:
                same = abs(float(p.rstrip("%")) - num["value"]) < 1e-12 and p.endswith("%") == num["pct"]
            except ValueError:
                same = False
            if same and best is None:
                best = c
        return best

    def _pool(self, ctx: dict) -> Tuple[list, float]:
        """The results a number in this context is compared with, and how near counts as the same quantity — as the
        research's own check (paper.check) chooses them."""
        key = (ctx.get("kind"), tuple(ctx.get("owners") or ()), tuple(ctx.get("refs") or ()), ctx.get("label", ""),
               bool(ctx.get("loose")))
        if key in self._pools:
            return self._pools[key]
        nodes = self.bp.get("nodes", {})
        links = [tuple(x) for x in self.bp.get("links", [])]
        pool: list = []
        near = paper.NEAR
        if ctx.get("kind") == "float":
            lab = ctx.get("label") or ""
            src = [t for s, r, t in links if s == lab and r == "of"]
            ids = [x for t in src for x in paper._results_of(t, nodes, links)]
            if not ids:
                ids = sorted({c["from"] for c in self.bp.get("checks", []) if c.get("to") == lab and c.get("from")})
            pool = paper._pool(ids, nodes)
        else:
            for nid in ctx.get("owners") or []:
                rest = paper.upstream(nid, nodes, links + [(r, "shows", nid) for r in ctx.get("refs") or []
                                                           if r in nodes])
                pool += [p for p in paper._pool(rest, nodes) if p not in pool]
        if not pool and (ctx.get("kind") != "float" or ctx.get("loose")):
            pool = paper._pool([k for k, n in nodes.items() if n.get("kind") == "result" or "." in k], nodes)
            near = paper.NEAR_UNMARKED
        self._pools[key] = (pool, near)
        return pool, near

    def _judge(self, f: str, ln: int, num: dict, ctx: dict) -> Optional[dict]:
        """The comparison the research's check makes, for a number it did not record (a second number matching the
        same result, a number on a run-in title's line, a table cell)."""
        pool, near = self._pool(ctx)
        if not pool:
            return None
        how, hit = paper.compare_number(num, pool, near)
        target = ctx.get("target") or ctx.get("label") or "the paper"
        if how == "match":
            return {"from": hit[0], "metric": hit[1], "value": hit[2], "to": target, "sign": "+", "file": f,
                    "line": ln, "says": num["raw"],
                    "why": f"{num['raw']} in {target} matches {hit[0]} {hit[1]} = {hit[2]:g}"}
        if how == "stale":
            form = min(paper._forms(hit[2], num), key=lambda x: abs(x - num["value"]))
            printed = f"{form:.{num['decimals']}f}" + ("%" if num["pct"] else "")
            return {"from": hit[0], "metric": hit[1], "value": hit[2], "to": target, "sign": "-", "file": f,
                    "line": ln, "says": num["raw"],
                    "why": f"{target} says {num['raw']} ({f}:{ln}), but {hit[0]} {hit[1]} is {hit[2]:.6g}"
                           + (f", {printed} at the digits printed" if printed.rstrip("%") != f"{hit[2]:.6g}" else "")}
        return None

    # ── figures and tables ──────────────────────────────────────────────────────────────────────────────────────
    def _rows(self, f: str, got: List[Tuple[int, str]], ctx: dict) -> List[dict]:
        """A tabular's rows: {"line", "head", "cells": [tokens]}; the rows above \\midrule are its header."""
        rows: List[dict] = []
        cells: List[List[dict]] = [[]]
        row_line = 0
        any_rule = False

        def end_row() -> None:
            nonlocal cells, row_line
            if any(c for c in cells):
                rows.append({"line": row_line, "head": False, "cells": [_merge(c) for c in cells]})
            cells, row_line = [[]], 0

        for ln, s in got:
            s = self.expand(paper.COMMENT_RX.sub("", s))
            if re.search(r"\\midrule|\\hline", s) and rows and not any_rule and not any(c for c in cells):
                any_rule = True
                for r in rows:
                    r["head"] = True
            s = RULES_RX.sub(" ", s)
            s = re.sub(r"\\(?:begin|end)\{(?:tabular\*?|tabularx|tabulary|longtable)\}(?:\{[^}]*\}|\[[^\]]*\])*"
                       r"(?:\{(?:[^{}]|\{[^{}]*\})*\})?", " ", s)
            for k, part in enumerate(re.split(r"(?<!\\)\\\\(?:\[[^\]]*\])?", s)):
                if k:
                    end_row()
                for j, cell in enumerate(re.split(r"(?<!\\)&", part)):
                    if j:
                        cells.append([])
                    if cell.strip():
                        row_line = row_line or ln
                        cells[-1] += self._walk(cell, f, ln, ctx)
        end_row()
        if any_rule:
            first = next((k for k, r in enumerate(rows) if not r["head"]), len(rows))
            for r in rows[first:]:
                r["head"] = False
        return rows

    @staticmethod
    def _row_counts(rows: List[dict]) -> Tuple[int, int, List[str]]:
        st = [t for r in rows for c in r["cells"] for t in c if t.get("t") == "num"]
        return (sum(1 for t in st if t["state"] == "ok"), sum(1 for t in st if t["state"] == "stale"),
                [t["id"] for t in st])

    def _float(self, f: str, x: dict, box) -> dict:
        lab = x.get("label") or ""
        iid = ("fig:" if x["kind"] == "figure" else "tab:") + (lab or f"{f}:{x['line']}")
        lines = self.lines(f)
        lo, hi = x["line"], x.get("end") or x["line"]
        body = [(i, lines[i - 1]) for i in range(lo, min(hi, len(lines)) + 1)]
        ctx = {"kind": "float", "label": lab, "target": lab or f"{x['kind']} at {f}:{lo}",
               "no_check": bool(x.get("no_check"))}
        inputs, rows, tab, cap_toks = [], [], [], []
        cap_at = 0
        k = 0
        while k < len(body):
            ln, raw = body[k]
            s = self.expand(paper.COMMENT_RX.sub("", raw))
            for m in re.finditer(r"\\(?:input|include)\s*\{([^}]+)\}", s):
                hit = next((t for t in box.tables if _same_file(t, m.group(1))), None)
                if hit:
                    inputs.append(hit)
                    tl = self.lines(hit)
                    rows += self._rows(hit, [(i, t) for i, t in enumerate(tl, 1) if i not in self._hidden_table(hit)],
                                       {**ctx, "loose": True})
            if re.search(r"\\begin\{(?:tabular\*?|tabularx|tabulary|longtable)\}", s):
                tab = []
                while k < len(body):
                    tab.append(body[k])
                    if re.search(r"\\end\{(?:tabular\*?|tabularx|tabulary|longtable)\}", body[k][1]):
                        break
                    k += 1
                rows += self._rows(f, tab, ctx)
                k += 1
                continue
            c = s.find("\\caption")
            if c >= 0 and not cap_at:
                cap_at = ln
                text = s[c + len("\\caption"):]
                j = k
                while text.count("{") - text.count("\\{") > text.count("}") - text.count("\\}") and j + 1 < len(body):
                    j += 1
                    text += " " + self.expand(paper.COMMENT_RX.sub("", body[j][1]))
                _o, p = _opt(text, 0)
                cap, _e = _group(text, p)
                cap_toks = self._walk(cap, f, ln, {**ctx, "no_check": True})
                k = j + 1
                continue
            k += 1
        cap_toks = _merge(cap_toks)
        caption = re.sub(r"\s+", " ", "".join(t["s"] if t["t"] != "cite" else f"[{t['s']}]" for t in cap_toks))
        caption = caption.strip()[:600] or (x.get("caption") or "")[:600]
        ok, stale, nums = self._row_counts(rows)
        checks = [self.items[n]["check"] for n in nums if self.items[n].get("check")]
        if not rows:                          # no cells read: the research's own checks of it
            checks = [c for c in self.bp.get("checks", []) if c.get("to") == lab and lab] + \
                [c for t in inputs for (cf, _l), cs in self.checks.items() if cf == t for c in cs]
            ok = sum(1 for c in checks if c.get("sign") == "+")
            stale = sum(1 for c in checks if c.get("sign") == "-")
        lab_n = (self.labels.get(lab) or {}).get("n", "")
        image = _find_file(self.S, x["graphics"], f, IMAGE_EXT, self.tracked()) if x.get("graphics") else ""
        self.items[iid] = {"kind": x["kind"], "label": lab, "file": f, "line": x["line"], "end": x.get("end"),
                           "graphics": x.get("graphics", ""), "inputs": inputs, "checks": checks, "n": lab_n,
                           "caption": caption}
        return {"kind": "float", "float": x["kind"], "id": iid, "label": lab, "n": lab_n, "file": f,
                "line": x["line"], "end": hi, "caption": caption, "tokens": cap_toks, "rows": rows,
                "graphics": x.get("graphics", ""), "image": image, "inputs": inputs, "stale": stale, "ok": ok,
                "changed": self._is_changed(f, lo, hi) or any(self._changed.get(t) for t in inputs)}

    def _hidden_table(self, t: str) -> set:
        return self._hidden(t) if any("\\begin{document}" in ln for ln in self.lines(t)) else set()

    def _loose_table(self, f: str, lo: int, hi: int, section: str) -> dict:
        """A tabular outside any float: a table block where it stands."""
        lines = self.lines(f)
        rows = self._rows(f, [(i, lines[i - 1]) for i in range(lo, hi + 1)],
                          {"kind": "float", "label": "", "loose": True, "target": f"§{section or 'Paper'}:{lo}"})
        ok, stale, nums = self._row_counts(rows)
        iid = f"tab:{f}:{lo}"
        self.items[iid] = {"kind": "table", "label": "", "file": f, "line": lo, "end": hi, "graphics": "",
                           "inputs": [], "checks": [self.items[n]["check"] for n in nums if self.items[n]["check"]]}
        return {"kind": "float", "float": "table", "id": iid, "label": "", "n": "", "file": f, "line": lo, "end": hi,
                "caption": "", "tokens": [], "rows": rows, "graphics": "", "inputs": [], "stale": stale, "ok": ok,
                "changed": self._is_changed(f, lo, hi)}

    def _table_file(self, t: str) -> dict:
        iid = "tab:" + t
        tl = self.lines(t)
        rows = self._rows(t, [(i, s) for i, s in enumerate(tl, 1) if i not in self._hidden_table(t)],
                          {"kind": "float", "label": "", "loose": True, "target": posixpath.basename(t)})
        ok, stale, nums = self._row_counts(rows)
        checks = [self.items[n]["check"] for n in nums if self.items[n]["check"]]
        if not rows:
            checks = [c for (cf, _l), cs in self.checks.items() if cf == t for c in cs]
            ok = sum(1 for c in checks if c.get("sign") == "+")
            stale = sum(1 for c in checks if c.get("sign") == "-")
        self.items[iid] = {"kind": "table", "label": "", "file": t, "line": 1, "graphics": "", "inputs": [t],
                           "checks": checks}
        return {"kind": "float", "float": "table", "id": iid, "label": "", "n": "", "file": t, "line": 1,
                "caption": posixpath.basename(t), "tokens": [], "rows": rows, "graphics": "", "inputs": [t],
                "stale": stale, "ok": ok, "changed": bool(self._changed.get(t))}

    # ── the page's data ──────────────────────────────────────────────────────────────────────────────────────────
    def data(self) -> dict:
        nodes = self.bp.get("nodes", {})
        # the claims and findings the research defines (the paper's chips); not the stand-ins the evidence graph makes
        # for an unmarked paragraph with a stale number, which are counted as stale numbers
        st = [x for x in self.g["statements"] if (nodes.get(x["id"]) or {}).get("kind") in ("claim", "finding")]
        base = self.S["cmp"].base if self.S.get("cmp") else ""
        return {"title": self.bp.get("title") or self.title, "files": self.files, "sections": self.sections,
                "counts": {"claims": len(st), "stale": sum(s["stale"] for s in self.sections),
                           "changed": sum(s["changed"] for s in self.sections),
                           "todo": sum(b.get("todo", 0) for s in self.sections for b in s["blocks"]),
                           "contradicted": sum(1 for x in st if x["verdict"] == "contradicted"),
                           "contested": sum(1 for x in st if x["verdict"] == "contested")},
                "base": base, "checkpoint": self._checkpoint()}

    def _checkpoint(self) -> dict:
        """What "changed" compares with, in words: the checkpoint and when it was set, or that there is none yet."""
        try:
            from . import compare
            sha = compare.checkpoint_sha(self.root)
            if not sha:
                return {"set": False, "at": 0}
            when = compare.git("show", "-s", "--format=%ct", sha, cwd=self.root).strip()
            return {"set": True, "at": int(when or 0)}
        except Exception:  # noqa: BLE001 - no git: nothing to say
            return {"set": False, "at": 0}


PLACEHOLDER_RX = re.compile(r"\b(?:TODO|TBD|TBA|FIXME|XXX)\b|\?\?\?")


def _placeholder(t: dict) -> bool:
    """Text the paper marks as not done: red text, or a TODO, TBD, FIXME, XXX, ??? (a placeholder, not a claim)."""
    if t.get("t") != "text":
        return False
    for tk in t.get("color", "").lower().split("!"):
        if tk.strip() in ("red", "magenta", "orange", "purple", "brickred", "redorange", "darkred"):
            return True
    return bool(PLACEHOLDER_RX.search(t.get("s", "")))


def _joined(lines: List[Tuple[int, str]]):
    """A paragraph's lines as one text, and a function from a place in that text to the line it is on."""
    starts: List[int] = []
    pos = 0
    for _ln, s in lines:
        starts.append(pos)
        pos += len(s) + 1
    nums = [ln for ln, _s in lines]

    def at(p: int) -> int:
        return nums[max(0, bisect.bisect_right(starts, p) - 1)] if nums else 0
    return "\n".join(s for _ln, s in lines), at


def _body_at(s: str, i: int) -> int:
    """Where the content of the group _group(s, i) reads starts."""
    while i < len(s) and s[i] in " \t\n":
        i += 1
    return i + 1 if i < len(s) and s[i] == "{" else i


def paper_input(s: str) -> str:
    m = re.search(r"\\(?:input|include)\s*\{([^}]+)\}", s)
    return m.group(1).strip() if m else ""


def _same_file(path: str, named: str) -> bool:
    """Whether an \\input names this file (with or without .tex, relative to wherever)."""
    n = named.strip().lstrip("./")
    n = n[:-4] if n.endswith(".tex") else n
    p = posixpath.splitext(path)[0]
    return p == n or p.endswith("/" + n)


def _num(val: str, ln: int) -> dict:
    """A printed number as the research's check reads it (paper.numbers)."""
    val = val.replace("\\%", "%").replace(" ", "")
    pct = val.endswith("%")
    raw = val.rstrip("%")
    return {"value": float(raw), "decimals": len(raw.split(".")[1]) if "." in raw else 0, "pct": pct,
            "raw": raw + ("%" if pct else ""), "line": ln}


def _printed(c: dict) -> str:
    """How the paper prints the number a check is of: its `says`, else read from its sentence."""
    if c.get("says"):
        return str(c["says"]).replace("\\%", "%").replace(" ", "")
    why = str(c.get("why", ""))
    m = re.match(r"(-?[\d.]+%?) in ", why) if c.get("sign") == "+" else re.search(r" says (-?[\d.]+%?) \(", why)
    return m.group(1) if m else ""


def _merge(toks: List[dict]) -> List[dict]:
    """Adjacent text of the same style as one run; spaces collapsed; empty runs dropped."""
    merged: List[dict] = []
    for t in toks:
        if t["t"] == "text":
            t = {**t, "s": re.sub(r"\s+", " ", t["s"])}
            if merged and merged[-1]["t"] == "text" and merged[-1].get("mark") == t.get("mark") and \
                    merged[-1].get("color") == t.get("color"):
                merged[-1]["s"] = re.sub(r"\s+", " ", merged[-1]["s"] + t["s"])
                continue
        merged.append(t)
    out = [t for t in merged if t["t"] != "text" or t["s"].strip() or (t is not merged[0] and t is not merged[-1])]
    if out and out[0]["t"] == "text" and not out[0].get("mark"):
        out[0]["s"] = out[0]["s"].lstrip()
    if out and out[-1]["t"] == "text":
        out[-1]["s"] = out[-1]["s"].rstrip()
    return [t for t in out if t["t"] != "text" or t["s"]]


# ── an item's chain ──────────────────────────────────────────────────────────────────────────────────────────────

def _key_line(text: str, metric: str) -> int:
    """The line of a results file where a metric's last key is written."""
    last = metric.split(".")[-1]
    for i, ln in enumerate(text.splitlines(), 1):
        if f'"{last}"' in ln or re.match(rf"\s*{re.escape(last)}\s*[:=,]", ln):
            return i
    return 1


class Provenance:
    """Which script writes which file (a results file, a figure, a table): read from the scripts' own text."""

    def __init__(self, S: dict, src=None):
        from . import studies
        self.root = Path(S["root"])
        sid = S.get("study") or ""
        found = S.get("studies") or []
        sc = studies.scope(found, sid) if sid else None
        files = getattr(src, "files", None)
        if files is None:
            try:
                from .compare import WorkSource
                files = WorkSource(self.root).files
            except Exception:  # noqa: BLE001
                files = []
        self.scripts = [f for f in files if f.endswith(SCRIPT_EXT) and (sc is None or studies.of_study(f, sc[0]))]
        self._texts: Dict[str, str] = {}

    def _read(self, f: str) -> str:
        if f not in self._texts:
            try:
                p = inside(self.root, f)
                self._texts[f] = p.read_text(encoding="utf-8", errors="replace") \
                    if p is not None and p.stat().st_size <= SCRIPT_MAX else ""
            except OSError:
                self._texts[f] = ""
        return self._texts[f]

    def writers(self, path: str, most: int = 4) -> List[Tuple[str, int, str]]:
        """The scripts that name this file (its name, or its name without the extension): (script, line, how), how
        being "writes" when that line writes it (open(…, "w"), savefig, to_csv, dump, > …), "reads" when it plainly
        reads it, else "names". The scripts that write it come first."""
        name = posixpath.basename(path)
        stem = posixpath.splitext(name)[0]
        out = []
        for f in self.scripts:
            text = self._read(f)
            if name not in text and (len(stem) < 4 or stem not in text):
                continue
            hits = [(i, ln) for i, ln in enumerate(text.splitlines(), 1)
                    if name in ln or (len(stem) >= 4 and re.search(r"\b" + re.escape(stem) + r"\b", ln))]
            if not hits:
                continue
            got = [(i, _how(ln, name)) for i, ln in hits]
            i, how = next(((i, h) for i, h in got if h == "writes"), None) or \
                next(((i, h) for i, h in got if h == "reads"), None) or got[0]
            out.append((f, i, how))
        out.sort(key=lambda x: ("writes", "names", "reads").index(x[2]))
        return out[:most]


WRITE_RX = re.compile(r"open\([^)]*,\s*(?:mode\s*=\s*)?['\"][^'\"]*[wax]|savefig|\.to_(?:csv|json|parquet|pickle|excel|latex"
                      r"|markdown|feather|hdf)\b|\bjson\.dump\(|\bpickle\.dump\(|\byaml\.(?:safe_)?dump\(|write_text|"
                      r"write_bytes|\.tofile\(|\bnp\.save(?:txt|z)?\(|\btorch\.save\(|\bimwrite\(|\bimsave\(|\.save\(|"
                      r"\bwrite\.(?:csv|table)\(|\bggsave\(|--out(?:put)?(?:[-_]\w+)?[= ]")
READ_RX = re.compile(r"open\([^)]*,\s*(?:mode\s*=\s*)?['\"]r|open\([^,()]*\)|\bjson\.load\(|\bpickle\.load\(|\byaml\.(?:safe_)?"
                     r"load\(|read_(?:csv|json|parquet|pickle|excel|text|bytes|table)\b|\bnp\.load(?:txt)?\(|"
                     r"\btorch\.load\(|\bimread\(")


def _how(line: str, name: str = "") -> str:
    """How a script's line uses the file it names: "writes", "reads" or "names" (it cannot tell)."""
    if WRITE_RX.search(line) or (name and re.search(r"(?:>>?|\btee\s+(?:-a\s+)?)\s*['\"]?\S*" + re.escape(name), line)):
        return "writes"
    if READ_RX.search(line):
        return "reads"
    return "names"


def _script_steps(prov: "Provenance", path: str, made: str = "Written by") -> List[dict]:
    """The scripts that name a file, each said for what its line does with it."""
    out = []
    for f, ln, how in prov.writers(path):
        if how == "writes":
            out.append(_step(f"{made} {f}", "the script that writes it", f, ln))
        elif how == "reads":
            out.append(_step(f"Read by {f}", "a script that reads it (it does not make it)", f, ln))
        else:
            out.append(_step(f"Names it: {f}", "a script that names the file (whether it writes or reads it is not "
                                               "clear from that line)", f, ln))
    return out


def _step(title: str, detail: str = "", file: str = "", line: int = 0, item: str = "", state: str = "",
          url: str = "", go: bool = False) -> dict:
    """One step of a chain. `url`: a web page to open (the cited paper); `go`: the place in the paper it names is one
    the reading view can scroll to (a section, a figure, an equation)."""
    out = {"title": title, "detail": detail, "file": file, "line": line, "item": item, "state": state}
    if url and re.match(r"https?://", url):
        out["url"] = url
    if go:
        out["go"] = True
    return out


def _why(c: dict) -> str:
    """A check's reason in a reader's words: what the paper prints, where, and what the result says."""
    raw, f, ln = _printed(c), str(c.get("file") or ""), c.get("line")
    rid, metric, val = c.get("from"), c.get("metric"), c.get("value")
    where = f" in {posixpath.basename(f)} line {ln}" if f and ln else ""
    if raw and rid and metric and isinstance(val, (int, float)) and not isinstance(val, bool):
        if c.get("sign") == "+":
            return f"Printed {raw}{where}; {rid} {metric} is {val:.6g}, which it matches."
        num = _num(raw, int(ln or 0))
        form = min(paper._forms(val, num), key=lambda x: abs(x - num["value"]))
        printed = f"{form:.{num['decimals']}f}" + ("%" if num["pct"] else "")
        return f"Printed {raw}{where}; {rid} {metric} is {val:.6g}" + \
            (f" ({printed} at the digits printed)" if printed.rstrip("%") != f"{val:.6g}" else "") + "."
    why = str(c.get("why", ""))
    # the research's own check: "<target> says 83.0 (file:line), but R m is v[, p at the digits printed]" or
    # "87.4% in <target> matches R m = v"
    m = re.match(r".*? says (\S+) \(([^()]*?):(\d+)\), but (\S+) (\S+) is (\S+?)(?:, (\S+) at the digits printed)?$",
                 why)
    if m:
        return f"Printed {m.group(1)} in {posixpath.basename(m.group(2))} line {m.group(3)}; {m.group(4)} " \
               f"{m.group(5)} is {m.group(6)}" + (f" ({m.group(7)} at the digits printed)" if m.group(7) else "") + "."
    m = re.match(r"(\S+) in .*? matches (\S+) (\S+) = (\S+)$", why)
    if m:
        return f"Printed {m.group(1)}{where}; {m.group(2)} {m.group(3)} is {m.group(4)}, which it matches."
    why = re.sub(r"§Paper:\d+", "the paper", why)
    return re.sub(r"§([^:§()]+):\d+", r"§ \1", why)


def _number_item(model: "Model", c: dict) -> str:
    """The number item a check is of: the cell or the word the paper prints, by its file, line and printed form."""
    p = _printed(c)
    for k, it in model.items.items():
        if it.get("kind") == "number" and it.get("file") == c.get("file") and it.get("line") == c.get("line") and \
                str(it.get("says", "")).replace("\\%", "%") == p:
            return k
    return ""


def chain(S: dict, model: Model, iid: str, prov: Provenance, at: str = "") -> dict:
    """{"title", "kind", "state", "summary", "steps": [step], "history": [...], "actions": [...]} for one item; `at`
    ("file:line") the place of the citation or reference the person clicked, when the paper has it more than once.
    A number whose experiment has a command also says what a rerun would run: "rerun": {"of", "run"}."""
    g, bp = S["graph"], S["map"]
    it = model.items.get(iid) or ({"kind": "node", "id": iid} if iid in bp["nodes"] or iid in g["nodes"] else None)
    if it is None:
        return {"title": iid, "kind": "", "state": "", "summary": "Not found in this study.", "steps": [],
                "history": [], "actions": []}
    kind = it["kind"]
    steps: List[dict] = []
    actions = ["ask", "guide"]
    if kind == "number":
        c = it.get("check")
        steps.append(_step(f"Printed: {it['says']}", "where the paper says it", it["file"], it["line"]))
        if c is None:
            return {"title": it["says"], "kind": "number", "state": "unchecked", "steps": steps, "actions": actions,
                    "history": [], "summary": "No result in the research has a value this close; it is not checked "
                                              "(an id with numbers near it, or a `results:` file, would check it)."}
        rid = str(c.get("from") or "")
        metric = str(c.get("metric") or "")
        if not metric:
            m = re.search(r" (\S+) (?:=|is) ", str(c.get("why", "")))
            metric = m.group(1) if m else ""
        val = (bp["nodes"].get(rid) or {}).get("metrics", {}).get(metric) if metric else None
        steps += _result_steps(S, rid, metric, val, prov)
        state = "ok" if c.get("sign") == "+" else "stale"
        exp = next((s["item"] for s in steps if s["title"].startswith("Experiment ") and s.get("item")), "")
        run = next((s["title"][5:] for s in steps if s["title"].startswith("Run: ")), "")
        out = {"title": f"{it['says']} in {posixpath.basename(it['file'])}", "kind": "number", "state": state,
               "summary": _why(c), "steps": steps, "history": _history(S, rid),
               "actions": actions + (["rerun"] if exp and run else [])}
        if exp and run:
            out["rerun"] = {"of": exp, "run": run}
        return out
    if kind in ("figure", "table"):
        name = f"{kind.title()} {it.get('n') or it.get('label') or ''}".strip()
        steps.append(_step(name + (f" ({it['label']})" if it.get("n") and it.get("label") else ""),
                           (it.get("caption") or "in the paper")[:200], it["file"], it["line"]))
        if it.get("graphics"):
            gfile = _find_file(S, it["graphics"], it["file"], IMAGE_EXT)
            steps.append(_step("Image: " + (gfile or it["graphics"]), "the file the figure shows" if gfile else
                               "no file of this name in the repository", gfile or "", 1 if gfile else 0))
            steps += _script_steps(prov, gfile or it["graphics"], "Made by")
        for t in it.get("inputs") or []:
            steps.append(_step("Table file: " + t, "what the table prints", t, 1))
            steps += _script_steps(prov, t)
        nums = it.get("checks") or []
        stale = [c for c in nums if c.get("sign") == "-"]
        for c in stale[:8]:
            steps.append(_step("✗ " + _printed(c), _why(c), str(c.get("file", "")), int(c.get("line") or 0),
                               item=_number_item(model, c), state="stale"))
        of = [t for s, r, t in bp.get("links", []) if s == it.get("label") and r == "of"]
        if not of:
            of = sorted({str(c.get("from")).split(".")[0] for c in nums if c.get("from")})
        for e in of:
            if e in bp["nodes"]:
                steps.append(_step(f"Of {e}: {(bp['nodes'].get(e) or {}).get('title', '')}", "the results it prints",
                                   item=e))
        return {"title": name if it.get("n") else f"{kind.title()} {it.get('label') or posixpath.basename(it['file'])}",
                "kind": kind, "state": "stale" if stale else "ok" if nums else "", "steps": steps, "actions": actions,
                "summary": f"{len(nums) - len(stale)} numbers match their results, {len(stale)} stale"
                if nums else "Its numbers are not checked against any result.", "history": []}
    if kind == "cite":
        e = model.bib.get(it["key"])
        steps += _places(it, at, "Cited")
        if e:
            venue = e.get("journal") or e.get("booktitle") or e.get("publisher") or e.get("howpublished") or ""
            steps.append(_step(e.get("title") or it["key"],
                               " · ".join(x for x in (e.get("author", "")[:160], f"{venue} {e.get('year', '')}".strip())
                                          if x),
                               e["file"], e["line"]))
            if e.get("doi") or e.get("url"):
                link = e.get("url") or "https://doi.org/" + e["doi"].strip()
                steps.append(_step(link, "where to read it", url=link))
        users = [nid for nid, n in bp["nodes"].items() if it["key"] in (n.get("sources") or [])]
        for nid in users[:6]:
            steps.append(_step(f"Backs {nid}", (g["nodes"].get(nid) or {}).get("title", ""), item=nid))
        return {"title": (e.get("title") if e else "") or it["key"], "kind": "cite", "state": "", "steps": steps,
                "actions": actions, "history": [],
                "summary": (f"{e.get('author', '')[:120]} ({e.get('year', '')})" if e else
                            "Not found in the paper's .bib files.")}
    if kind == "ref":
        target = it["key"]
        lab = model.labels.get(target)
        steps += _places(it, at, "Referred to")
        hit = next((k for k in model.items if k.endswith(":" + target) and not k.startswith(("ref:", "cite:"))), None)
        printed = target
        if lab:
            word = {"section": "Section", "appendix": "Appendix", "figure": "Figure", "table": "Table",
                    "equation": "Equation"}.get(lab["kind"], lab["kind"].title())
            printed = f"{word} {lab['n']}".strip() if lab["n"] else f"{word} {target}"
            title = (model.items.get(hit) or {}).get("caption") or lab.get("title") or ""
            steps.insert(1, _step(printed + (f": {title[:160]}" if title else ""), "what it points at",
                                  lab["file"], lab["line"], item=hit or "", go=True))
        elif hit:
            steps.insert(1, _step("Open it", "", item=hit))
        return {"title": printed, "kind": "ref", "state": "", "steps": steps, "actions": ["ask", "guide"],
                "history": [], "summary": (f"A cross-reference to {printed[:1].lower() + printed[1:]} ({target})"
                                           if lab else "A cross-reference to a label the paper does not define")}
    return _node_chain(S, it.get("id") or iid, prov)


def _places(it: dict, at: str, verb: str) -> List[dict]:
    """Where a citation or reference stands: the place clicked first ("Cited here"), then the others."""
    places = list(it.get("places") or [(it["file"], it["line"])])
    here = next((p for p in places if f"{p[0]}:{p[1]}" == at), places[0])
    out = [_step(f"{verb} here: {it['key']}", "where the paper says it", here[0], here[1])]
    for f, ln in [p for p in places if p != here][:6]:
        out.append(_step(f"Also {verb.lower()} at {posixpath.basename(f)}:{ln}", "another place the paper says it",
                         f, ln))
    return out


def _find_file(S: dict, name: str, near: str, prefer: Tuple[str, ...] = (), files: Optional[List[str]] = None) -> str:
    """The repository's file a path in the paper names (\\includegraphics{figures/x} -> paper/figures/x.pdf):
    the same path from the paper's folder or under it, a file of a preferred kind first."""
    if files is None:
        try:
            from .compare import WorkSource
            files = WorkSource(Path(S["root"])).files
        except Exception:  # noqa: BLE001
            return ""
    base = posixpath.dirname(near)
    want = name.strip().lstrip("./").replace("\\", "/")
    stem, ext = posixpath.splitext(want)
    if ext.lower() not in IMAGE_EXT + SCRIPT_EXT + (".tex", ".csv", ".json", ".yaml", ".yml", ".toml", ".txt"):
        stem, ext = want, ""
    cands = [f for f in files if (posixpath.splitext(f)[0] == stem or posixpath.splitext(f)[0].endswith("/" + stem))
             and (not ext or f.endswith(ext))]
    cands.sort(key=lambda f: (bool(prefer) and not f.lower().endswith(prefer), not f.startswith(base + "/")
                              if base else False, len(f)))
    return cands[0] if cands else ""


def _result_steps(S: dict, rid: str, metric: str, val, prov: Provenance) -> List[dict]:
    bp, g = S["map"], S["graph"]
    n = bp["nodes"].get(rid) or {}
    steps = []
    rfile = next((f for f in n.get("files", []) if not f.endswith((".md", ".tex"))), "") or \
        (n.get("files") or [""])[0]
    line = _key_line(_text(S["root"], rfile), metric) if rfile and metric else int(n.get("line") or 1)
    full = f" = {val!r}" if val is not None else ""
    steps.append(_step(f"Result {rid}: {metric}{full}", n.get("title") or "the number it was checked against",
                       rfile, line, item=rid if rid in g["nodes"] else ""))
    exp = rid.split(".")[0] if "." in rid else next((t for s, r, t in bp.get("links", []) if s == rid and r == "of"),
                                                     "")
    if exp and exp in bp["nodes"]:
        e = bp["nodes"][exp]
        cfg = next((f for f in e.get("files", []) if f.endswith((".yaml", ".yml", ".json", ".toml"))), "")
        steps.append(_step(f"Experiment {exp}: {e.get('title', '')}", "what the result is of",
                           cfg or (e.get("files") or [""])[0], int(e.get("line") or 1), item=exp))
        if e.get("run"):
            steps.append(_step("Run: " + e["run"], "its command (auto-research launches it)"))
            m = re.search(r"([\w./\\-]+\.(?:py|sh|ipynb|R|jl))", e["run"])
            if m:
                steps.append(_step("Script: " + m.group(1), "what the command runs", _find_file(S, m.group(1),
                                                                                              cfg) or "", 1))
    if rfile and not rfile.endswith((".md", ".tex")):
        steps += _script_steps(prov, rfile)
    return steps


def _node_chain(S: dict, nid: str, prov: Provenance) -> dict:
    g, bp = S["graph"], S["map"]
    n = g["nodes"].get(nid) or {}
    b = bp["nodes"].get(nid) or {}
    st = next((s for s in g["statements"] if s["id"] == nid), None)
    steps = []
    f = (b.get("files") or [""])[0]
    steps.append(_step(f"{nid}: {b.get('title') or n.get('title', '')}", n.get("kind") or b.get("kind", ""), f,
                       int(b.get("line") or n.get("line") or 0)))
    if st:
        for x in st["against"]:
            steps.append(_step("✗ " + x["why"], "against it", item=x["from"] if x["from"] in g["nodes"] else "",
                               state="stale"))
        for x in st["for"]:
            steps.append(_step("✓ " + x["why"], "for it", item=x["from"] if x["from"] in g["nodes"] else "",
                               state="ok" if x["effective"] in ("+", "~") else ""))
        for s, r, t in bp.get("links", []):   # what the claim itself says of others: what it rests on, argues against
            if s == nid:
                steps.append(_step(f"{nid} {r} {t}", (g["nodes"].get(t) or bp["nodes"].get(t) or {}).get("title", ""),
                                   item=t if t in g["nodes"] or t in bp["nodes"] else ""))
    else:
        if b.get("metrics"):
            for k, v in list(b["metrics"].items())[:10]:
                steps.append(_step(f"{k} = {v!r}", "a number it holds"))
        for s, r, t in bp.get("links", []):
            if s == nid:
                steps.append(_step(f"{r} {t}", (g["nodes"].get(t) or {}).get("title", ""), item=t))
        if b.get("run"):
            steps.append(_step("Run: " + b["run"], "its command"))
        for rf in [x for x in b.get("files", []) if not x.endswith((".md", ".tex"))][:2]:
            steps += _script_steps(prov, rf)
    owner = n.get("owner") or ""
    verdict = n.get("verdict", "")
    rerun = nid[:1] == "E" and bool(b.get("run"))
    actions = ["ask", "guide"] + (["rerun"] if rerun else [])
    return {**({"rerun": {"of": nid, "run": b["run"]}} if rerun else {}),
            "title": f"{nid} · {b.get('title') or n.get('title', '')}", "kind": n.get("kind") or b.get("kind", ""),
            "state": {"supported": "ok", "contradicted": "stale", "contested": "mixed"}.get(verdict, ""),
            "summary": (f"{verdict}" + (f" · owned by {owner}" if owner else "")) if verdict else
            (f"owned by {owner}" if owner else ""), "steps": steps, "history": _history(S, nid), "actions": actions}


def _history(S: dict, nid: str) -> List[dict]:
    """What changed this item, newest first: the commits and turns that touched it, and what agents said about it."""
    out = []
    if not nid:
        return out
    try:
        from . import history
        for e in reversed(history.load(Path(S["root"]), nid, 8)):
            out.append({"at": e.get("at", 0), "who": ", ".join(e.get("by") or []) or (e.get("commit") or ""),
                        "what": e.get("request") or e.get("message") or "", "got": e.get("headline", "")})
    except Exception:  # noqa: BLE001
        pass
    try:
        from . import agents
        for m in reversed(agents.state(Path(S["root"]))["messages"][-200:]):
            if m.get("topic") == nid or nid in str(m.get("text", "")):
                out.append({"at": m.get("at", 0), "who": m.get("from", ""), "what": str(m.get("text", ""))[:300],
                            "got": ""})
    except Exception:  # noqa: BLE001
        pass
    return sorted(out, key=lambda x: -float(x["at"] or 0))[:12]


def source(root: Path, path: str, line: int, around: int = 10) -> dict:
    """Some lines of a file around one, for the panel's preview: only those lines are read (a results file of
    gigabytes costs no more than a short one), and a binary file (an image, a checkpoint) shows none."""
    out: Dict[str, Any] = {"path": path, "line": line, "lo": max(1, line - around), "lines": []}
    p = inside(Path(root), path)
    if p is None:
        return out
    try:
        with p.open("rb") as fh:
            if path.lower().endswith(BINARY_EXT) or b"\0" in fh.read(8192):
                return {**out, "binary": True}
            fh.seek(0)
            for i, raw in enumerate(fh, 1):
                if i > line + around:
                    break
                if i >= out["lo"]:
                    out["lines"].append(raw[:2000].decode("utf-8", errors="replace").rstrip("\r\n"))
    except OSError:
        pass
    return out

