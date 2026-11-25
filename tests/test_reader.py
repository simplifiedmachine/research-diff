"""The Read tab's model (reader.py) on a paper shaped like a real conference paper: a style file and macros of its own,
run-in \\paragraph titles, lists, a table \\input from a file and one written inline, a figure made by a script, \\S\\ref,
citations from two .bib files, an appendix. The text is made up; the structure is what a real paper has."""
from __future__ import annotations

from pathlib import Path

import pytest

from research_diff import compare, reader

MAIN = r"""\documentclass{article}
% the workshop's style file
\usepackage{confstyle}
\usepackage{booktabs}
\newcommand{\TBD}{\textcolor{red}{\textsf{[TBD]}}}
\newcommand{\expected}[1]{\textcolor{blue}{#1}}
\newcommand{\method}{\textsc{Sieve}}
\conftitlerunning{Sorting Signals}
\begin{document}
\twocolumn[
  \conftitle{Sorting Signals: When Sensors Disagree}
  \confkeywords{sensors, fusion}
]
\begin{abstract}
Fusion models are ranked by one accuracy. Two score within a point on SensorBench~1, yet the robot driven by one stops on $31\%$ of clear paths and by the other on $12.5\%$.
\end{abstract}

\begin{figure}[t]
\centering
\includegraphics[width=\columnwidth]{figures/stops}
\caption{\textbf{Stop or go?} A scene from RoadSet \citep{lee2023road}; the 14 models split 6 to 8 (Appendix~\ref{app:judges}).}
\label{fig:stops}
\end{figure}

\section{Introduction}
\label{sec:intro}

A robot sees a shadow (Figure~\ref{fig:stops}). Two sensors disagree on what it is.

% C1: Fusion models with the same accuracy drive robots that stop differently
% relies on: E1
Fusion models are compared by one number. The robot whose model saw lidar labels stops on 31\% of clear paths (\S\ref{sec:lean}). Same score, different robot. % a private aside
%Nobody should read this line.

\paragraph{What is new.} Earlier work treated disagreement as noise \citep{kim2021, ortiz2022}. We take the opposite view.

\paragraph{Contributions.}
\begin{itemize}[leftmargin=1.2em]
\item \textbf{A test that keeps errors and disagreements apart.} (\S~\ref{sec:pairs}).
\item \textbf{Same score, opposite lean.} \method{} leans toward stopping.
\end{itemize}

\begin{comment}
An old draft paragraph, never shown.
\end{comment}

\section{Two Kinds of Scene}
\label{sec:pairs}

% C2: One label per sensor cannot tell disagreements from clear-cut scenes
% relies on: E1
\paragraph{Which labels to trust.} We asked Fuse-2.5-7B and two annotators (Table~\ref{tab:labels}). Both agree 48.2\% of the time.

\begin{table}[t]
\caption{\textbf{Labels hold.} Share of scenes, in $\%$.}
\label{tab:labels}
\centering
\small
\input{tables/labels.tex}
\end{table}

\section{Same Score, Opposite Lean}
\label{sec:lean}

\begin{table}[t]
% of: E1
\caption{\textbf{One fusion model on different data.} All in $\%$.}
\label{tab:suite}
\begin{tabular}{llrrc}
\toprule
Data & LR & SB1 & err. & lean \\
\midrule
Alpha & 3e-6 & $69.4$ & $8.1$ & $56.3$ \tiny{[$50$, $63$]} \\
Beta & 3e-6 & $70.1$ & $7.0$ & $34.5$ \tiny{[$29$, $41$]} \\
\bottomrule
\end{tabular}
\end{table}

% C3: Versions with the same score lean opposite ways
% relies on: E1
\paragraph{Two versions score within a point and lean opposite ways.} Table~\ref{tab:suite} compares them (rank correlations $-0.59$ and $-0.74$; $\alpha \leq 0.05$). \expected{We expect the gap to hold.} The last value is \TBD.

\begin{enumerate}
\item First, Alpha leans 56.3\% and Beta 35.2\%.
\item Second, R\&D costs 5\_000 units, ``quoted'' -- in full.
\end{enumerate}

\bibliography{refs,more}

\appendix
\section{Annotators as Judges}
\label{app:judges}
\paragraph{Querying.} One call per judgment.
\end{document}
"""

LABELS = r"""\begin{tabular}{lr}
\toprule
Kind & Share \\
\midrule
Agree & $48.2$ \\
Split & $51.9$ \\
\bottomrule
\end{tabular}
"""

SHAPE = {
    "paper/main.tex": MAIN,
    "paper/tables/labels.tex": LABELS,
    "paper/refs.bib": ("@inproceedings{lee2023road,\n  title = {{RoadSet}: Scenes from the Road},\n"
                       "  author = {Lee, Ana and Park, Jun},\n  booktitle = {Proc. of Roads},\n  year = {2023}}\n\n"
                       "@article{kim2021,\n  title = \"Noise in Fusion\",\n  author = {Kim, Bo},\n"
                       "  journal = {Sensors},\n  year = 2021,\n}\n"),
    "paper/more.bib": ("@misc{ortiz2022,\n    title={Disagreement as Signal},\n    author={Ortiz, Eva},\n"
                       "    year={2022}\n    }\n"),
    "paper/figures/stops.pdf": "%PDF-1.4 stand-in\n",
    "configs/e1.yaml": ("lr: 3.0e-6\nresearch:\n  id: E1\n  title: Fusion on two data sets\n"
                        "  results: ../out/e1.json\n  run: python scripts/train.py --config configs/e1.yaml\n"),
    "out/e1.json": ('{"stop": {"lidar": 0.31, "camera": 0.125}, "agree": 0.482, "split": 0.519,\n'
                    ' "lean": {"alpha": 0.563, "beta": 0.352}, "sb1": {"alpha": 69.4, "beta": 70.1},\n'
                    ' "err": {"alpha": 8.1, "beta": 7.0}, "rank": {"a": -0.59, "b": -0.74}}\n'),
    "scripts/train.py": "import json\njson.dump({}, open('out/e1.json', 'w'))\n",
    "scripts/plot.py": "import matplotlib\n\nplt.savefig('paper/figures/stops.pdf')\n",
}


def state(root: Path) -> dict:
    """A study read as the Read tab reads it (without system-diff's engine)."""
    bp = compare.read(root, ".")[0]
    g = compare.evidence_of(root, ".")[0]
    return {"root": root, "map": bp, "graph": g, "cmp": None}


@pytest.fixture
def shaped(repo, files):
    from conftest import git
    files(repo, SHAPE)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "the paper")
    S = state(repo)
    return S, reader.Model(S)


def _paras(m: reader.Model) -> list:
    return [b for s in m.sections for b in s["blocks"] if b["kind"] == "para"]


def _plain(b: dict) -> str:
    return "".join(f"[{t['s']}]" if t["t"] == "cite" else t["s"] for t in b["tokens"])


def _num(m: reader.Model, says: str, line: int) -> dict:
    return next(t for s in m.sections for b in s["blocks"]
                for t in (b.get("tokens") or []) + [t for r in b.get("rows") or [] for c in r["cells"] for t in c]
                if t.get("t") == "num" and t["s"] == says and t["id"].startswith(f"num:paper/main.tex:{line}:"))


def test_the_paper_reads_as_its_pdf(shaped):
    S, m = shaped
    d = m.data()
    assert d["title"] == "Sorting Signals: When Sensors Disagree"
    text = " ".join(_plain(b) for b in _paras(m))
    for hidden in ("confstyle", "newcommand", "a private aside", "Nobody should read", "old draft", "leftmargin",
                   "\\", "%Nobody", "refs,more", "sensors, fusion"):
        assert hidden not in text                                            # preamble, comments, commented-out
    assert "R&D costs 5_000 units, “quoted” – in full." in text            # escapes, quotes, dashes
    tbd = next(t for b in _paras(m) for t in b["tokens"] if t["s"] == "[TBD]")
    assert tbd.get("color") == "red"                                        # \TBD, the paper's own macro
    assert any(t.get("color") == "blue" and "We expect the gap to hold." in t["s"]
               for b in _paras(m) for t in b["tokens"])                     # \expected{…}
    assert "Sieve leans toward stopping" in text                            # \method{}
    new = next(b for b in _paras(m) if b.get("runin") == "What is new.")
    assert new["tokens"][0] == {"t": "text", "s": "What is new. ", "mark": "runin"}
    assert "Earlier work treated disagreement as noise" in _plain(new)      # the run-in's own text, not lost
    trust = next(b for b in _paras(m) if b.get("runin") == "Which labels to trust.")
    assert [c["id"] for c in trust["claims"]] == ["C2"]                     # its marker above the \paragraph
    items = [b for b in _paras(m) if b.get("list")]
    assert [(b["list"], b["tokens"][0]["s"]) for b in items] == [("itemize", "• "), ("itemize", "• "),
                                                                 ("enumerate", "1. "), ("enumerate", "2. ")]
    assert items[0]["tokens"][1] == {"t": "text", "s": "A test that keeps errors and disagreements apart.",
                                     "mark": "b"}
    refs = {t["key"]: t["s"] for b in _paras(m) for t in b["tokens"] if t["t"] == "ref"}
    assert refs == {"fig:stops": "1", "sec:lean": "3", "sec:pairs": "2", "tab:labels": "1", "tab:suite": "2"}
    assert "(§3)" in text and "(§ 2)" in text                               # \S\ref, \S~\ref
    cites = [(t["key"], t["s"]) for b in _paras(m) for t in b["tokens"] if t["t"] == "cite"]
    assert cites == [("kim2021", "Kim 2021"), ("ortiz2022", "Ortiz 2022")]  # \citep with two keys, two .bib files
    assert any(t["t"] == "math" and t["s"] == "α ≤" for b in _paras(m) for t in b["tokens"])
    heads = {s["title"]: (s["n"], s["appendix"]) for s in m.sections}
    assert heads["Same Score, Opposite Lean"] == ("3", False) and heads["Annotators as Judges"] == ("A", True)
    fig = next(b for s in m.sections for b in s["blocks"] if b.get("float") == "figure")
    assert fig["caption"] == "Stop or go? A scene from RoadSet [Lee & Park 2023]; the 14 models split 6 to 8 " \
                             "(Appendix A)."


def test_every_number_the_paper_prints_is_an_item_with_its_state(shaped):
    S, m = shaped
    assert _num(m, "31%", 15)["state"] == "ok" and _num(m, "12.5%", 15)["state"] == "ok"     # inside $…$
    assert _num(m, "31%", 32)["state"] == "ok"
    assert _num(m, "48.2%", 52)["state"] == "ok"                     # on a run-in title's line
    assert _num(m, "56.3%", 84)["state"] == "ok"
    assert _num(m, "35.2%", 84)["state"] == "ok"                     # a second number matching the same result
    assert _num(m, "-0.59", 81)["state"] == "ok" and _num(m, "0.05", 81)["state"] == "unchecked"
    trust = next(b for b in _paras(m) if b.get("runin") == "Which labels to trust.")
    assert "Fuse-2.5-7B" in _plain(trust) and not any(t["s"] == "2.5" for t in trust["tokens"])   # a name
    assert not any(t["t"] == "num" and t["s"] in ("14", "6", "8") for b in _paras(m) for t in b["tokens"])
    suite = next(b for s in m.sections for b in s["blocks"] if b.get("label") == "tab:suite")
    rows = [["".join(t["s"] for t in c) for c in r["cells"]] for r in suite["rows"]]
    assert rows == [["Data", "LR", "SB1", "err.", "lean"], ["Alpha", "3e-6", "69.4", "8.1", "56.3 [50, 63]"],
                    ["Beta", "3e-6", "70.1", "7.0", "34.5 [29, 41]"]]
    assert [r["head"] for r in suite["rows"]] == [True, False, False]
    states = {t["s"]: t["state"] for r in suite["rows"] for c in r["cells"] for t in c if t["t"] == "num"}
    assert states == {"69.4": "ok", "8.1": "ok", "56.3": "ok", "70.1": "ok", "7.0": "ok", "34.5": "stale"}
    assert (suite["ok"], suite["stale"]) == (5, 1)
    labels = next(b for s in m.sections for b in s["blocks"] if b.get("label") == "tab:labels")
    assert labels["inputs"] == ["paper/tables/labels.tex"]
    assert [[t["s"] for c in r["cells"] for t in c if t["t"] == "num"] for r in labels["rows"]] == [[], ["48.2"],
                                                                                                  ["51.9"]]
    assert (labels["ok"], labels["stale"]) == (2, 0)
    sec = next(s for s in m.sections if s["title"] == "Same Score, Opposite Lean")
    assert sec["stale"] == 1


def test_a_number_finds_its_check_by_line_and_printed_form(shaped):
    S, m = shaped
    m.checks = {("p.tex", 3): [{"sign": "+", "from": "R1", "why": "87.4% in C1 matches R1 acc = 0.874"},
                               {"sign": "-", "from": "R1", "why": "C1 says 0.5 (p.tex:3), but R1 x is 0.61"}],
                ("p.tex", 4): [{"sign": "-", "says": "86.1\\%", "why": "§Results:4 says 86.1% …"}]}
    num = reader._num
    assert m._check_for("p.tex", 3, num("87.4\\%", 3))["sign"] == "+"
    assert m._check_for("p.tex", 3, num("7.4%", 3)) is None                # not a part of another number
    assert m._check_for("p.tex", 3, num("87.4", 3)) is None                # 87.4 is not 87.4%
    assert m._check_for("p.tex", 3, num("0.50", 3))["sign"] == "-"         # the same value, printed otherwise
    assert m._check_for("p.tex", 4, num("86.1%", 4))["sign"] == "-"
    assert m._check_for("p.tex", 5, num("87.4%", 5)) is None               # another line


def test_each_item_opens_its_chain(shaped):
    S, m = shaped
    prov = reader.Provenance(S)
    stale = _num(m, "34.5", 74)
    c = reader.chain(S, m, stale["id"], prov)
    assert c["state"] == "stale" and c["steps"][0]["title"] == "Printed: 34.5"
    titles = [st["title"] for st in c["steps"]]
    assert "Result E1.results: lean.beta = 0.352" in titles
    assert any(st["title"].startswith("Experiment E1") and st["file"] == "configs/e1.yaml" for st in c["steps"])
    assert any(st["title"] == "Script: scripts/train.py" and st["file"] == "scripts/train.py" for st in c["steps"])
    assert "rerun" in c["actions"]
    again = reader.chain(S, m, _num(m, "35.2%", 84)["id"], prov)          # a match the research's check left out
    assert again["state"] == "ok" and "Result E1.results: lean.beta = 0.352" in [s["title"] for s in again["steps"]]
    fig = reader.chain(S, m, "fig:fig:stops", prov)
    assert fig["title"] == "Figure 1"
    assert [(s["title"], s["file"]) for s in fig["steps"][1:]] == [
        ("Image: paper/figures/stops.pdf", "paper/figures/stops.pdf"), ("Made by scripts/plot.py", "scripts/plot.py")]
    tab = reader.chain(S, m, "tab:tab:suite", prov)
    assert tab["state"] == "stale" and tab["title"] == "Table 2"
    assert any(s["title"] == "✗ 34.5" and s["line"] == 74 for s in tab["steps"])
    assert any(s["item"] == "E1" for s in tab["steps"])
    for key, where, title in (("lee2023road", "paper/refs.bib", "RoadSet: Scenes from the Road"),
                              ("kim2021", "paper/refs.bib", "Noise in Fusion"),
                              ("ortiz2022", "paper/more.bib", "Disagreement as Signal")):
        cite = reader.chain(S, m, "cite:" + key, prov)
        assert cite["title"] == title and cite["steps"][1]["file"] == where
    assert reader.chain(S, m, "cite:lee2023road", prov)["steps"][1]["detail"] == \
        "Lee, Ana and Park, Jun · Proc. of Roads 2023"
    ref = reader.chain(S, m, "ref:sec:lean", prov)
    assert ref["steps"][1]["title"] == "Section 3: Same Score, Opposite Lean" and ref["steps"][1]["line"] == 62
    to_fig = reader.chain(S, m, "ref:fig:stops", prov)
    assert to_fig["steps"][1]["item"] == "fig:fig:stops"                   # the figure, not the reference itself


def test_latex_pieces_read_plainly():
    assert reader.math_text(r"\frac{a}{b} + x^{2} \in \mathbb{R}, \alpha_{t} \leq 0.05") == "a/b + x² ∈ ℝ, α_t ≤ 0.05"
    entries = reader.bib_entries("@article{k1,\n title = {{BERT}: Deep {T}ransformers},\n author = \"A and B\","
                                 "\n year = 2019}\n@comment{x, y}\n")
    assert entries["k1"]["title"] == "BERT: Deep Transformers" and entries["k1"]["year"] == "2019"
    assert reader._short_authors("Lee, Ana and Park, Jun and others") == "Lee et al."


def test_macros_with_arguments_and_defaults_expand(repo, files):
    files(repo, {"paper/main.tex": "\\documentclass{article}\n\\newcommand{\\gain}[2][pts]{+#2 #1}\n"
                                   "\\def\\ours{\\textbf{Ours}}\n\\begin{document}\n\\section{Results}\n\n"
                                   "\\ours{} gains \\gain{4.6} and \\gain[\\%]{3}.\n\\end{document}\n"})
    m = reader.Model(state(repo))
    para = _paras(m)[0]
    assert _plain(para) == "Ours gains +4.6 pts and +3%."
    assert para["tokens"][0] == {"t": "text", "s": "Ours", "mark": "b"}
    assert [(x["title"], x["n"]) for x in m.sections] == [("Results", "1")]      # numbered without a \label


def _one_section(repo, files, body: str, extra: dict = None) -> reader.Model:
    files(repo, {"paper/main.tex": "\\documentclass{article}\n\\begin{document}\n\\section{Results}\n\n" + body +
                 "\n\\end{document}\n", **(extra or {})})
    return reader.Model(state(repo))


def test_a_line_ending_in_a_lone_backslash_reads(repo, files):
    m = _one_section(repo, files, "Some methods, and more e.g.\\\n\nNext paragraph.\n")
    assert [_plain(b) for b in _paras(m)][:2] == ["Some methods, and more e.g.", "Next paragraph."]
    assert reader.math_text("x \\") == "x" and reader.math_text("a^\\") == "a^"


def test_math_citations_and_groups_run_on_past_a_line_break(repo, files):
    m = _one_section(repo, files, "We set the rate to $\\alpha\n= 0.05$ and see that it works well 12.5\\% of the "
                                  "time.\n\nAs before \\citep{kim2021,\nortiz2022}, \\textbf{bold\nwrap} here.\n\n"
                                  "\\[\n  x = y + 1\n\\]\n",
                     {"paper/refs.bib": SHAPE["paper/refs.bib"], "paper/more.bib": SHAPE["paper/more.bib"]})
    first, second, display = _paras(m)[:3]
    kinds = [(t["t"], t["s"]) for t in first["tokens"]]
    assert ("math", "α =") in kinds or ("math", "α") in kinds
    assert ("text", " and see that it works well ") in kinds and ("num", "12.5%") in kinds
    assert not any(t == "math" and "works" in s for t, s in kinds)
    assert [t["key"] for t in second["tokens"] if t["t"] == "cite"] == ["kim2021", "ortiz2022"]
    assert [t["line"] for t in (m.items["cite:kim2021"], m.items["cite:ortiz2022"])] == [8, 9]
    assert any(t["t"] == "text" and t["s"].strip() == "bold wrap" and t.get("mark") == "b" for t in second["tokens"])
    assert display.get("display") and "x = y + 1" in _plain(display)


def test_equations_are_numbered_as_latex_numbers_them(repo, files):
    m = _one_section(repo, files, "\\begin{equation}\na = 1\n\\end{equation}\n\\begin{equation*}\nb = 2\n"
                                  "\\end{equation*}\n\\begin{align}\nc &= 3 \\\\\nd &= 4 \\nonumber \\\\\ne &= 5 "
                                  "\\label{eq:e}\n\\end{align}\n\\begin{equation}\n\\label{eq:loss}\nL = 0\n"
                                  "\\end{equation}\n")
    assert (m.labels["eq:e"]["n"], m.labels["eq:loss"]["n"]) == ("3", "4")


def test_bibliographies_stay_in_the_study_and_the_repository(repo, files, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "private.bib").write_text("@misc{secret1, title={Private}}\n")
    files(repo, {"main.tex": "\\documentclass{article}\n\\begin{document}\n\\section{A}\n\nAs in \\cite{smith} and "
                             "\\cite{venvkey}.\n\\bibliography{../outside/private,refs}\n\\end{document}\n",
                 "refs.bib": "@misc{mine, title={Mine}}\n",
                 ".venv/lib/x.bib": "@misc{venvkey, title={Vendored}}\n"})
    m = reader.Model(state(repo))
    assert "mine" in m.bib and "secret1" not in m.bib and "venvkey" not in m.bib
    assert reader.inside(repo, "../outside/private.bib") is None and reader.inside(repo, "C:/x.bib") is None
    assert reader.inside(repo, ".git/config") is None and reader.inside(repo, "refs.bib") is not None


def test_a_script_that_reads_a_file_is_not_said_to_write_it(shaped):
    S, m = shaped
    from conftest import write
    write(S["root"], {"scripts/report.py": "import json\nd = json.load(open('out/e1.json'))\n"})
    prov = reader.Provenance(S)
    assert [(f, how) for f, _ln, how in prov.writers("out/e1.json")] == [("scripts/train.py", "writes"),
                                                                        ("scripts/report.py", "reads")]
    steps = [s["title"] for s in reader._script_steps(prov, "out/e1.json")]
    assert steps == ["Written by scripts/train.py", "Read by scripts/report.py"]


def test_citations_and_references_open_where_they_were_clicked(repo, files):
    m = _one_section(repo, files, "\\label{sec:r}\nFirst \\cite{k} (\\S\\ref{sec:r}).\n\nAgain \\cite{k} and "
                                  "\\ref{sec:r}.\n\\bibliography{refs}\n",
                     {"paper/refs.bib": "@misc{k, title={K}, author={A, B}, year={2020}}\n"})
    S = state(repo)
    prov = reader.Provenance(S)
    toks = [t for b in _paras(m) for t in b["tokens"] if t["t"] in ("cite", "ref")]
    assert [t["at"] for t in toks] == ["paper/main.tex:6"] * 2 + ["paper/main.tex:8"] * 2
    ref = reader.chain(S, m, "ref:sec:r", prov, "paper/main.tex:8")
    assert ref["title"] == "Section 1" and ref["steps"][0]["line"] == 8
    assert ref["steps"][0]["title"] == "Referred to here: sec:r" and ref["steps"][1]["go"]
    assert ref["steps"][1]["title"] == "Section 1: Results" and ref["steps"][1]["line"] == 3
    assert ref["steps"][2]["title"] == "Also referred to at main.tex:6" and ref["actions"] == ["ask", "guide"]
    cite = reader.chain(S, m, "cite:k", prov, "paper/main.tex:8")
    assert (cite["steps"][0]["title"], cite["steps"][0]["line"]) == ("Cited here: k", 8)
    assert reader.chain(S, m, "cite:k", prov)["steps"][0]["line"] == 6


def test_a_cited_paper_with_a_link_opens(repo, files):
    m = _one_section(repo, files, "As in \\cite{k}.\n\\bibliography{refs}\n",
                     {"paper/refs.bib": "@article{k, title={K}, author={A, B}, year={2020}, doi={10.1/x}}\n"})
    c = reader.chain(state(repo), m, "cite:k", reader.Provenance(state(repo)))
    link = next(s for s in c["steps"] if s.get("url"))
    assert link["url"] == "https://doi.org/10.1/x"


def test_a_tables_stale_number_opens_its_own_chain(shaped):
    S, m = shaped
    tab = reader.chain(S, m, "tab:tab:suite", reader.Provenance(S))
    stale = next(s for s in tab["steps"] if s["title"] == "✗ 34.5")
    assert stale["item"].startswith("num:paper/main.tex:74:") and "§" not in stale["detail"]
    assert stale["detail"].startswith("Printed 34.5 in main.tex line 74; E1")
