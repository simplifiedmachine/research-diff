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


def ctx(root: Path, view: str, part: str = "", live=None):
    return extensions.Context(root, view, part, 140, 0, live)


def engine_live(root: Path, identity: str = "v1"):
    """What system-diff's engine hands an extension: its working tree's files, and a key for them."""
    import types
    from research_diff import compare
    return types.SimpleNamespace(source=compare.WorkSource(root), identity=identity)


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
    assert not any(s["kind"] == "frame" for s in page["sections"])                  # one graph: the diagram
    card = page["diagram"]["details"]["b:C1"]
    assert {"title", "headline", "how", "insights", "facts"} <= set(card)
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
    import research_diff.extract as ex
    live = engine_live(study)
    first = x.state(ctx(study, "evidence", live=live))
    calls = []
    real = ex.extract
    monkeypatch.setattr(ex, "extract", lambda *a, **k: calls.append(a) or real(*a, **k))
    again = x.state(ctx(study, "paper", live=live))
    assert again["graph"] is first["graph"] and calls == []                         # the same files: the same read


def test_a_repository_with_several_papers_is_read_study_by_study(repo, files):
    files(repo, {
        "1_batch/paper/main.tex": "\\section{Results}\n\n% C1: Small batches win\n% relies on: R1\nYes.\n",
        "1_batch/notes.md": "## R1: Batch 32 beats 512\n\nmetrics: gap=0.03\n",
        "2_lr/paper/main.tex": ("\\section{Results}\n\n% C1: Batch size does not matter\n% relies on: R1\n"
                                "Indeed.\n\n% C2: Scaling closes the gap\n% contradicts: C1\nAlso.\n"),
        "2_lr/notes.md": "## R1: Scaled LR closes the gap\n\nmetrics: gap=0.002\n",
    })
    live = engine_live(repo)
    overview = x.web(ctx(repo, "research", live=live))
    assert [n["id"] for n in overview["nav"]] == ["1_batch", "2_lr"]
    assert overview["diagram"]["enter"]["b:2_lr"] == {"view": "research", "part": "2_lr@"}
    one = x.state(ctx(repo, "evidence", "1_batch@", live=live))
    two = x.state(ctx(repo, "evidence", "2_lr@", live=live))
    assert one["graph"]["nodes"]["C1"]["title"] == "Small batches win"            # each study its own C1
    assert two["graph"]["nodes"]["C1"]["title"] == "Batch size does not matter"
    assert "C2" not in one["graph"]["nodes"] and two["graph"]["conflicts"]
    ev = x.web(ctx(repo, "evidence", "2_lr@", live=live))
    assert ev["diagram"]["enter"]["b:C1"] == {"view": "evidence", "part": "2_lr@C1"}
    assert [n["active"] for n in ev["nav"]] == [False, True]
    card = ev["diagram"]["details"]["b:C1"]
    assert card["headline"].startswith("This claim") and any(f["title"] == "Against it" for f in card["facts"])
    assert any("cannot both stand" in i for i in card["insights"])
    pane = x.pane(ctx(repo, "research", live=live))
    assert {b["id"] for b in pane["blocks"]} >= {"b:1_batch", "b:2_lr"}


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
