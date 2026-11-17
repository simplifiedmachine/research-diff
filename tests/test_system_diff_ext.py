"""research-diff inside system-diff's engine, page and pane (system_diff_ext.py): its four tabs drawn with
system-diff's own diagrams, its pages under /x/research/, read from the engine's files once per version. Skipped where
the system-diff installed has no extensions (before 0.10)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

extensions = pytest.importorskip("system_diff.extensions")

from research_diff import system_diff_ext as x  # noqa: E402

STUDY = {
    "notes/results.md": "## R2: Scaled LR closes the gap\n\nof: E1\nmetrics: gap=0.002\nweakens: H1\nby: lr-agent\n",
    "paper/main.tex": ("\\begin{abstract}\nBatch 32 reaches 88.9\\% here.\n\\end{abstract}\n\n\\section{Results}\n\n"
                       "% C1: Small batches win on small data\n% relies on: H1\n% by: batch-agent\nBatch 32 wins.\n\n"
                       "% C2: Batch size does not matter\n% contradicts: C1\n% by: lr-agent\nIt does not.\n"),
}


@pytest.fixture
def study(repo, files):
    files(repo, STUDY)
    return repo


def ctx(root: Path, view: str, part: str = ""):
    return extensions.Context(root, view, part, 140, 0, None)


def test_it_is_found_as_system_diffs_extension(monkeypatch):
    monkeypatch.setattr(extensions, "_LOADED", [x])
    assert [v[0] for v in extensions.views()] == ["research", "evidence", "paper", "auto"]
    assert extensions.owner("evidence") is x


def test_the_evidence_tab_is_system_diffs_diagram_in_the_evidence_graphs_words(study):
    page = x.web(ctx(study, "evidence"))
    svg = page["diagram"]["svg"]
    assert svg.startswith("<svg") and 'class="sd-arch"' in svg                    # system-diff's renderer
    assert "contradicted" in svg and "contradicts" in svg
    assert "b:C1" in page["diagram"]["enter"] and page["diagram"]["enter"]["b:C1"] == {"view": "evidence", "part": "C1"}
    assert any(s["kind"] == "frame" and s["items"][0]["src"] == "/x/research/graph" for s in page["sections"])
    assert "The paper contradicts itself: C2 contradicts C1" in json.dumps(page["sections"])
    zoomed = x.web(ctx(study, "evidence", "C2"))
    assert "b:C2" in zoomed["diagram"]["enter"] and "b:R2" not in zoomed["diagram"]["enter"]   # only C2's chain


def test_the_pane_draws_boxes_and_lines(study):
    pane = x.pane(ctx(study, "evidence"))
    text = "\n".join("".join(r[0] for r in row) for row in pane["rows"])
    assert pane["view"] == "evidence" and any(b["id"] == "b:C1" for b in pane["blocks"])
    assert "┌" in text and "contradicts" in text
    research = x.pane(ctx(study, "research"))
    assert research["view"] == "research" and "WORTH A LOOK" in "\n".join("".join(r[0] for r in row)
                                                                          for row in research["rows"])
    paper = x.pane(ctx(study, "paper"))
    assert "§ RESULTS" in "\n".join("".join(r[0] for r in row) for row in paper["rows"])


def test_the_research_is_read_once_per_version(study, monkeypatch):
    from research_diff import compare
    first = x.state(ctx(study, "evidence"))
    calls = []
    monkeypatch.setattr(compare, "compare", lambda *a, **k: calls.append(a))
    assert x.state(ctx(study, "paper")) is first and calls == []                   # the same files: the same read


def test_its_own_pages_and_the_auto_research_controls(study):
    c = ctx(study, "")
    status, kind, body = x.route(c, "GET", "graph", {}, b"")
    assert status == 200 and b"Only contradictions" in body
    status, kind, body = x.route(c, "GET", "file", {"path": "paper/main.tex"}, b"")
    assert status == 200 and b'class="ln bad"' in body
    assert x.route(c, "GET", "file", {"path": "../etc/passwd"}, b"")[0] == 404
    assert b"/x/research/auto" in x.route(c, "GET", "auto", {}, b"")[2]
    got = x.route(c, "POST", "auto/server", {}, json.dumps({"name": "here", "host": "local"}).encode())
    assert got[0] == 200 and json.loads(got[2])["name"] == "here"
    assert x.route(c, "POST", "auto/start", {}, b'{"goal": ""}')[0] in (200, 400)
    assert x.route(c, "GET", "nothing", {}, b"")[0] == 404
    assert x.file_ok("paper/main.tex") and not x.file_ok(".env")
