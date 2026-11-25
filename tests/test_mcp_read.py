"""The Read tab's picture for agents (mcp_server: read_item, needs_attention, what_changed_in_paper): the same items,
ids and chains the person reads, so the person and the agents share one understanding of the paper."""
from __future__ import annotations

import asyncio

import pytest
from conftest import git

from research_diff import mcp_server as m

PAPER = {
    "paper/main.tex": ("\\section{Results}\n\n"
                       "% C1: Small batches win on small data\n% relies on: E1\n% by: batch-agent\n"
                       "Batch 32 reaches 86.1\\% here \\cite{keskar2017}.\n\n"
                       "% C2: Batch size does not matter\n% contradicts: C1\n% by: lr-agent\nIt does not.\n"),
}


@pytest.fixture
def paper(repo, files):
    files(repo, PAPER)
    return repo


def test_an_item_reads_as_its_chain_down_to_the_files(paper):
    c1 = m.tool_read_item(paper, "C1")
    assert c1["title"].startswith("C1") and c1["state"] == "mixed"                  # E1 for it, C2 against it
    assert "C2 contradicts C1" in c1["text"] and "paper/main.tex:" in c1["text"]
    att = m.tool_needs_attention(paper)
    num = next(x for x in att["items"] if x["why"] == "stale number")
    assert num["says"] == "86.1%" and num["where"] == "paper/main.tex:6"
    got = m.tool_read_item(paper, num["id"])                    # number -> result -> experiment, each with file:line
    assert got["kind"] == "number" and got["state"] == "stale"
    assert "Printed: 86.1%" in got["text"] and "acc.b32 = 0.874" in got["text"]
    assert any(st.get("file") == "configs/e1.yaml" for st in got["steps"])
    assert m.tool_read_item(paper, "paper/main.tex:6")["items here"] == [num["id"], "cite:keskar2017"]   # a place: what it prints
    assert m.tool_read_item(paper, "C9")["text"].endswith("Not found in this study.")


def test_what_needs_attention_comes_worst_first(paper):
    git(paper, "add", "-A")
    git(paper, "commit", "-q", "-m", "the paper")
    m.cmp.checkpoint(paper)
    text = (paper / "paper/main.tex").read_text().replace("It does not.", "It does not, an agent wrote.")
    (paper / "paper/main.tex").write_text(text)
    att = m.tool_needs_attention(paper)
    whys = [x["why"] for x in att["items"]]
    assert whys == sorted(whys, key=["stale number", "contradicted claim", "contested claim",
                                     "changed since the checkpoint"].index)
    assert {"stale number", "contested claim", "changed since the checkpoint"} <= set(whys)
    changed = [x for x in att["items"] if x["why"] == "changed since the checkpoint"]
    assert [x["id"] for x in changed] == ["C2"] and changed[0]["where"].startswith("paper/main.tex:")
    assert "an agent wrote" in changed[0]["says"] and att["counts"]["changed since the checkpoint"] == 1


def test_what_changed_in_the_paper_is_said_with_its_text(paper):
    git(paper, "add", "-A")
    git(paper, "commit", "-q", "-m", "the paper")
    m.cmp.checkpoint(paper)
    assert m.tool_what_changed_in_paper(paper)["paragraphs"] == []
    text = (paper / "paper/main.tex").read_text().replace("It does not.", "It does not, an agent wrote.")
    (paper / "paper/main.tex").write_text(text)
    got = m.tool_what_changed_in_paper(paper)
    assert [p["items"] for p in got["paragraphs"]] == [["C2"]]
    assert got["paragraphs"][0]["section"] == "Results" and "an agent wrote" in got["paragraphs"][0]["text"]
    assert "paper/main.tex:" in got["text"] and "an agent wrote" in got["text"]


def test_the_tools_are_registered_read_only(paper, monkeypatch):
    pytest.importorskip("mcp")
    monkeypatch.chdir(paper)
    server = m.build()
    tools = {t.name: t for t in asyncio.run(server.list_tools())}
    for name in ("read_item", "needs_attention", "what_changed_in_paper"):
        ann = tools[name].annotations
        assert ann is None or ann.model_dump(by_alias=True).get("readOnlyHint")
    out = asyncio.run(server.call_tool("read_item", {"id": "C1"}))
    assert "C2 contradicts C1" in str(out)


def test_the_read_tools_reuse_the_tabs_model(paper, monkeypatch):
    from research_diff import reader
    made = []
    real = reader.Model.__init__
    monkeypatch.setattr(reader.Model, "__init__", lambda self, S: made.append(1) or real(self, S))
    m._reading(paper)
    m._reading(paper)
    assert len(made) == 1
