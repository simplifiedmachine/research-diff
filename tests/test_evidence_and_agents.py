"""The evidence graph (what supports and what contradicts each statement of the paper), its pictures, and what is built
on it: worth a look, a team of agents with claims and a bus, the hooks, the views, history and objectives."""
from __future__ import annotations

import json

import pytest

from research_diff import agent, agents, compare, evgraph, evidence, history, objectives, page, rank
from research_diff.cli import main

STUDY = {
    "notes/results.md": ("## R2: Scaled LR closes the gap\n\nof: E1\nmetrics: gap=0.002\nsupports: H3\nweakens: H1\n"
                         "by: lr-agent\n\n## H3: Batch size stops mattering with a scaled LR\n\nanswers: Q1\nby: lr-agent\n"),
    "paper/main.tex": ("\\section{Results}\n\n% C1: Small batches win on small data\n% relies on: H1\n% by: batch-agent\n"
                       "Batch 32 wins \\cite{keskar2017,masters2018}.\n\n\\section{Discussion}\n\n"
                       "% C2: Batch size does not matter once the LR is scaled\n% supported by: R2\n% contradicts: C1\n"
                       "% by: lr-agent\nThe gap is an artefact.\n\n% F1: Batch 512 reaches 84.2\\%\n"
                       "% expects: E1.results acc.b512 > 0.85\nWe report it.\n"),
}


@pytest.fixture
def study(repo, files):
    files(repo, {**STUDY, "notes/ideas.md": (repo / "notes/ideas.md").read_text().replace("status: open", "status: supported", 1)})
    return repo


def graph_of(repo):
    return compare.evidence_of(repo)[0]


def test_each_statement_gets_a_verdict_with_what_supports_and_what_contradicts_it(study):
    g = graph_of(study)
    v = {s["id"]: s for s in g["statements"]}
    assert v["C2"]["verdict"] == "supported" and v["C2"]["section"] == "Discussion"
    assert v["C1"]["verdict"] == "contested" and v["C1"]["section"] == "Results"
    assert [x["why"] for x in v["C1"]["against"]] == ["C2 contradicts C1"]
    assert v["F1"]["verdict"] == "contradicted"                              # 0.842 is not > 0.85
    assert v["F1"]["against"][0]["why"] == "acc.b512 = 0.842, but F1 expects > 0.85"
    assert g["conflicts"] == [{"from": "C2", "to": "C1", "why": "C2 contradicts C1"}]
    assert [(c["from"], c["to"], c["owners"]) for c in g["cross_agent"]] == [("C2", "C1", ["lr-agent", "batch-agent"])]
    assert g["nodes"]["H1"]["verdict"] == "contested"                        # supported by its status, weakened by R2
    assert g["headline"] == "3 statements: 1 supported, 1 contested, 1 contradicted; C2 contradicts C1."


def test_a_refuted_hypothesis_breaks_the_support_it_gave_and_says_why(study, files):
    files(study, {"notes/ideas.md": (study / "notes/ideas.md").read_text().replace("status: supported", "status: refuted", 1)})
    g = graph_of(study)
    c1 = next(s for s in g["statements"] if s["id"] == "C1")
    assert c1["verdict"] == "contradicted"
    assert "C1 relies on H1, which is refuted" in [x["why"] for x in c1["against"]]
    assert any(e["from"] == "H1" and e["to"] == "C1" and e["effective"] == "?" for e in g["edges"])


def test_support_from_what_has_no_evidence_is_ungrounded(repo):
    g = graph_of(repo)                    # C1 relies on H1, which is open and has no evidence
    c1 = g["statements"][0]
    assert c1["verdict"] == "unsupported" and c1["for"][0]["effective"] == "o"
    assert "has no evidence yet" in c1["for"][0]["why"]


def test_the_pictures_are_deterministic_and_show_the_contradictions(study):
    g = graph_of(study)
    svg = evgraph.svg(g)
    assert svg == evgraph.svg(graph_of(study)) and svg.startswith("<svg")
    assert 'data-sign="-"' in svg and "§ Discussion" in svg and "lr-agent" in svg and "✗ contradicted" in svg
    html = evgraph.standalone(g)
    assert html.startswith("<!doctype html>") and "Only contradictions" in html and '"C2 contradicts C1"' in html
    mmd = evgraph.mermaid(g)
    assert mmd.startswith("flowchart LR") and "-->|contradicts|" in mmd and 'subgraph s1["§ Discussion"]' in mmd
    md = evidence.to_markdown(g)
    assert "**The paper contradicts itself:** C2 contradicts C1" in md


def test_a_new_contradiction_is_first_worth_a_look(repo, files):
    files(repo, {"paper/more.tex": "% C2: Batch size never matters\n% contradicts: C1\n"})
    c = compare.compare(repo, "HEAD", ".")
    worth = rank.worth_a_look(c.diff, c.after)
    assert worth[0]["title"] == "The paper contradicts itself: C2 contradicts C1"
    assert "1 new contradiction (C2 contradicts C1)" in c.diff["headline"]


def test_a_plan_splits_the_paper_by_section_and_the_bus_tells_the_owner_of_a_contradicted_claim(study):
    g, bp, cfg = compare.evidence_of(study)
    plan = agents.plan(study, "write the paper", bp, g)
    assert [a["name"] for a in plan["agents"]] == ["results-writer", "discussion-writer"]
    assert plan["agents"][0]["owns"] == ["C1"] and "C2 contradicts C1" in plan["agents"][0]["brief"]
    assert agents.claim(study, "results-writer", ["C2"], bp=bp)["owned by others"] == [{"id": "C2", "owner": "lr-agent"}]
    agents.inbox(study, "batch-agent", g)                                  # read what came so far
    d = {"changes": [{"op": "add", "entity": "contradiction", "id": "R2 → C1", "label": "R2 contradicts C1",
                      "detail": [], "impact": []}]}
    agents.after_change(study, "lr-agent", d, g)
    got = agents.inbox(study, "batch-agent", g)
    assert [m["text"] for m in got] == ["CONTRADICTION: R2 contradicts C1 (R2 is lr-agent's, C1 is batch-agent's)"]
    assert agents.inbox(study, "batch-agent", g) == []                     # read once
    assert not any("CONTRADICTION" in m["text"] for m in agents.inbox(study, "lr-agent", g))   # not its own


def test_the_hooks_follow_each_agent_and_hand_it_the_contradictions_of_the_others(study, files):
    said = []

    def hook(payload):
        said.clear()
        agent.run_hook(json.dumps({"cwd": str(study), **payload}), said.append)
        return json.loads(said[0]) if said else {}

    hook({"hook_event_name": "UserPromptSubmit", "prompt": "run the LR ablation"})
    assert compare._rev(study, compare.TURN_REF)
    agents.tie(study, "a1", "lr-agent")
    agents.tie(study, "a2", "batch-agent")
    files(study, {"notes/r4.md": "## R4: Batch 32 loses with a long schedule\n\ncontradicts: C1\nby: lr-agent\n"})
    out = hook({"hook_event_name": "PostToolUse", "tool_name": "Write", "agent_id": "a1",
                "tool_input": {"file_path": str(study / "notes/r4.md")}})
    assert "R4 contradicts C1" in out["systemMessage"]
    out = hook({"hook_event_name": "PostToolUse", "tool_name": "Read", "agent_id": "a2",
                "tool_input": {"file_path": str(study / "paper/main.tex")}})
    assert "CONTRADICTION: R4 contradicts C1" in out["hookSpecificOutput"]["additionalContext"]
    out = hook({"hook_event_name": "Stop"})
    assert "R4" in out["systemMessage"]
    e = history.load(study)[-1]
    assert e["request"] == "run the LR ablation" and "R4" in e["ids"]
    assert history.load(study, "R4") and not history.load(study, "Q9")
    out = hook({"hook_event_name": "SessionStart"})
    assert "C1 is contested" in out["hookSpecificOutput"]["additionalContext"]


def test_every_view_is_a_page_the_pane_can_draw(study):
    for view in page.VIEWS:
        d = page.show(study, view, "", 100)
        assert d["protocol"] == 2 and d["rows"] and all(len(r[0]) <= 100 for row in d["rows"] for r in row)
    ev = page.show(study, "evidence", "", 120)
    assert "b:C1" in ev["lights"] and any("C2 contradicts C1" in r[0] for row in ev["rows"] for r in row)
    zoom = page.as_text(page.show(study, "now", "C1", 120))
    assert "ITS EVIDENCE" in zoom and "C2 contradicts C1" in zoom
    from research_diff import statusline
    assert "contradiction" in "\n".join(statusline.lines(study))


def test_the_command_line_writes_the_evidence_and_can_fail_on_contradictions(study, tmp_path, capsys):
    out = tmp_path / "ev"
    assert main(["--repo", str(study), "evidence", "--out", str(out)]) == 0
    assert {p.name for p in out.iterdir()} == {"evidence.svg", "evidence.html", "evidence.mmd", "evidence.json",
                                               "evidence.md"}
    assert main(["--repo", str(study), "evidence", "--out", str(out), "--check"]) == 0
    assert main(["--repo", str(study), "evidence", "--out", str(out), "--strict"]) == 1
    capsys.readouterr()
    assert main(["--repo", str(study), "comment", "--base", "HEAD"]) == 0
    text = capsys.readouterr().out
    assert "### Research diff" in text and "```mermaid" in text and "The paper contradicts itself" in text
    assert main(["--repo", str(study), "panel", "--view", "agents", "--width", "80"]) == 0
    assert json.loads(capsys.readouterr().out)["view"] == "agents"


def test_objectives_keep_only_what_the_persons_own_words_show(repo):
    from research_diff import activity
    for t in ("use three seeds for every number", "again, three seeds please", "plot it"):
        activity.record(repo, "prompt", text=t)
    answer = json.dumps({"objectives": [{"text": "Report three seeds", "evidence": ["three seeds"]},
                                        {"text": "Invented", "evidence": ["never said this"]}]})
    got = objectives.learn(repo, ask=lambda user, system: answer)
    assert [o["text"] for o in got] == ["Report three seeds"]
    oid = objectives.current(repo)[0]["id"]
    assert "Report three seeds" in objectives.context(repo)
    assert objectives.clear(repo, oid) and objectives.current(repo) == []
    assert objectives.restore(repo, oid) and len(objectives.current(repo)) == 1


def test_suggested_links_go_under_the_target_and_are_checked(study, tmp_path):
    import subprocess
    from research_diff import suggest

    def fake(user):
        assert "[C1] claim" in user and "Batch 32 wins" in user
        return json.dumps({"links": [{"from": "R2", "rel": "contradicts", "to": "C1", "why": "gap 0.002"},
                                     {"from": "C2", "rel": "contradicts", "to": "C1", "why": "already there"},
                                     {"from": "R9", "rel": "supports", "to": "C1", "why": "no such node"}]})
    got = suggest.links(study, fake)
    assert "+% contradicted by: R2" in got["patch"]
    assert [r.split(": ", 1)[1] for r in got["refused"]] == ["already written",
                                                             "not two nodes of the map and supports/contradicts/weakens"]
    p = tmp_path / "l.patch"
    p.write_text(got["patch"], encoding="utf-8", newline="\n")
    subprocess.run(["git", "apply", str(p)], cwd=study, check=True)
    assert ["R2", "contradicts", "C1"] in compare.read(study, ".")[0]["links"]


def test_agents_that_are_not_one_off_are_suggested_saved_and_reused(study, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    g, bp, cfg = compare.evidence_of(study)
    agents.plan(study, "write the paper", bp, g)
    assert agents.worth_keeping(study) == []                                  # once: maybe a one-off
    agents.note_use(study, "results-writer", finished=True)
    keep = {k["name"]: k["why"] for k in agents.worth_keeping(study)}
    assert "results-writer" in keep and "standing role" in keep["results-writer"]
    got = agents.save_agent(study, "results-writer", "Writes the Results section from the evidence",
                            "You write a paper's Results section. Every number comes from a results file.",
                            tools="Read, Edit, Grep")
    text = (study / ".claude" / "agents" / "results-writer.md").read_text()
    assert got["scope"] == "project" and text.startswith("---\nname: results-writer\ndescription: Writes")
    assert "tools: Read, Edit, Grep" in text
    assert [a["name"] for a in agents.library(study)] == ["results-writer"]
    assert "results-writer" not in {k["name"] for k in agents.worth_keeping(study)}
    plan = agents.plan(study, "revise the paper", bp, g)
    assert "start it as `results-writer`" in plan["agents"][0]["brief"]
    (study / ".claude" / "agents" / "mine.md").write_text("---\nname: mine\n---\nhand written\n")
    with pytest.raises(ValueError):
        agents.save_agent(study, "mine", "x", "y")                             # never over a file it did not write
