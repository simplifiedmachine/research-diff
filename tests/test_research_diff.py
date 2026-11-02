"""research-diff on the project of conftest.py: the markers, the map, the diff, the checkpoint, the agent tools."""
from __future__ import annotations

import json

import pytest

from research_diff import agent, compare, graph
from research_diff.cli import main


def test_the_map_reads_every_kind_of_marker(repo):
    bp, cfg, _ = compare.read(repo, "HEAD")
    n = bp["nodes"]
    assert list(n) == ["Q1", "H1", "H2", "E1", "E1.results", "E2", "C1"]          # ordered by kind, then number
    assert n["H1"]["status"] == "open" and n["E2"]["status"] == "running"          # a script's comment
    assert n["E1.results"]["metrics"] == {"acc.b32": 0.874, "acc.b512": 0.842}     # booleans are not metrics
    assert n["C1"]["sources"] == ["keskar2017", "masters2018"]                    # the claim's paragraph
    assert ["E1", "tests", "H1"] in bp["links"] and ["E2", "tests", "H2"] in bp["links"]
    assert bp["warnings"] == []
    assert graph.map_svg(bp, cfg).startswith("<svg") and "Small batches win" in graph.map_svg(bp, cfg)


def test_the_diff_says_what_the_iteration_did(repo, files):
    files(repo, {"out/e1.json": '{"acc": {"b32": 0.881, "b512": 0.842}}\n',
                 "notes/ideas.md": (repo / "notes/ideas.md").read_text().replace("status: open", "status: refuted"),
                 "notes/h3.md": "## H3: Width matters more than batch\n\nanswers: Q1\n"})
    d = compare.compare(repo, "HEAD", ".").diff
    assert d["headline"] == ("Adds 1 hypothesis (H3); H1: open → refuted; E1.results acc.b32: 0.874 → 0.881 (+0.007 "
                             "(+0.8%)); 1 new link; 2 new warnings (C1 relies on H1, which is refuted…).")
    assert "~ status H1 — H1: open → refuted   [refuted]" in d["plan"]
    assert "+ warning H3 is open and no experiment tests it   [new-warning]" in d["plan"]


def test_the_checkpoint_keeps_only_what_came_after_it(repo, files):
    files(repo, {"notes/h3.md": "## H3: Width matters\n"})
    assert compare.compare(repo).diff["changes"]                       # since HEAD, before any checkpoint
    compare.checkpoint(repo)
    assert compare.compare(repo).diff["changes"] == []
    files(repo, {"notes/h4.md": "## H4: Depth matters\n"})
    assert [c["id"] for c in compare.compare(repo).diff["changes"] if c["op"] == "add"][0] == "H4"


def test_the_hook_says_one_line_and_never_fails(repo, files, tmp_path):
    said = []
    assert agent.run_hook(json.dumps({"cwd": str(repo)}), said.append) == 0 and said == []
    files(repo, {"notes/h3.md": "## H3: Width matters\n"})
    agent.run_hook(json.dumps({"cwd": str(repo)}), said.append)
    assert "Adds 1 hypothesis (H3)" in json.loads(said[0])["systemMessage"]
    assert agent.run_hook(json.dumps({"cwd": str(tmp_path)}), said.append) == 0 and len(said) == 1


def test_a_logged_result_is_on_the_map_and_in_the_next_diff(repo, monkeypatch):
    pytest.importorskip("mcp")
    import asyncio

    from research_diff import mcp_server
    monkeypatch.chdir(repo)
    assert {t.name for t in asyncio.run(mcp_server.build().list_tools())} == {
        "research_map", "research_diff", "log_result", "checkpoint"}
    got = mcp_server.tool_log(repo, "E1", {"acc": 0.9}, "Batch 32 again", supports=["H1"])
    assert got == {"recorded": "R1", "in": "research/log.md"}
    d = mcp_server.tool_diff(repo, "HEAD")
    assert "R1" in d["headline"] and "+ link R1 supports H1" in d["plan"]
    assert mcp_server.tool_log(repo, "E1", {"acc": 0.91})["recorded"] == "R2"


def test_setup_wires_the_hook_and_the_skill_and_undo_takes_them_back(repo, tmp_path, monkeypatch):
    home = tmp_path / "home"
    for var in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(var, str(home))
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    agent.setup_claude(repo, "user", out=lambda s: None)
    settings = json.loads((home / ".claude" / "settings.json").read_text())
    assert settings["hooks"]["Stop"][0]["hooks"][0]["command"].endswith("-m research_diff hook")
    assert (home / ".claude" / "skills" / "research-diff" / "SKILL.md").is_file()
    agent.setup_claude(repo, "user", undo=True, out=lambda s: None)
    assert json.loads((home / ".claude" / "settings.json").read_text()) == {}


def test_the_command_line_map_check_and_diff(repo, tmp_path, capsys):
    out = tmp_path / "o"
    assert main(["--repo", str(repo), "map", "--out", str(out)]) == 0
    assert main(["--repo", str(repo), "map", "--out", str(out), "--check"]) == 0
    assert main(["--repo", str(repo), "diff", "--base", "HEAD", "--out", str(out)]) == 0
    assert "No change to the research." in capsys.readouterr().out


def test_the_live_page_shows_the_change_and_mark_as_seen_clears_it(repo, files):
    from research_diff import watch
    files(repo, {"notes/h3.md": "## H3: Width matters\n"})
    w = watch.Watcher(repo, interval=60)
    w.tick()
    assert "H3" in w.snapshot_state()["headline"] and w.snapshot_state()["svg"].startswith("<svg")
    w.mark_seen()
    assert w.snapshot_state()["changes"] == 0
    assert "Research diff" in watch.PAGE


def test_tracker_runs_tagged_with_an_experiment_become_its_results(repo, files):
    files(repo, {
        "mlruns/1/abcdef1234567890/meta.yaml": "run_id: abcdef1234567890\n",
        "mlruns/1/abcdef1234567890/tags/research-diff.experiment": "E1",
        "mlruns/1/abcdef1234567890/tags/mlflow.runName": "lr-sweep-3",
        "mlruns/1/abcdef1234567890/metrics/acc": "1 0.80 0\n2 0.86 1\n",
        "mlruns/1/0000untagged/meta.yaml": "run_id: 0000untagged\n",
        "wandb/run-20261102_101010-zz9y8x7w/files/config.yaml": "research_id:\n  desc: null\n  value: E2\n",
        "wandb/run-20261102_101010-zz9y8x7w/files/wandb-summary.json": '{"loss": 0.31, "_step": 40, "done": true}',
    })
    assert compare.sync_trackers(repo) == {"runs": 2, "written": True}
    assert compare.sync_trackers(repo)["written"] is False                    # unchanged runs: the file stays
    n = compare.read(repo, ".")[0]["nodes"]
    assert n["E1.mlflow.abcdef12"] == {**n["E1.mlflow.abcdef12"], "title": "lr-sweep-3", "metrics": {"acc": 0.86}}
    assert n["E2.wandb.zz9y8x7w"]["metrics"] == {"loss": 0.31}
    assert "E1.mlflow.abcdef12" in compare.compare(repo, "HEAD", ".").diff["headline"]


def test_suggest_proposes_checked_markers_as_a_patch_and_changes_nothing(repo, files, tmp_path):
    from research_diff import suggest
    files(repo, {"notes/plan.md": "# Next\n\nMaybe the gap comes from the optimiser, not the batch.\n"})
    import subprocess
    subprocess.run(["git", "add", "notes/plan.md"], cwd=repo, check=True)
    assert suggest.untagged(repo) == ["notes/plan.md"]

    def fake_llm(user):
        assert "notes/plan.md" in user and "Existing ids: Q1, H1" in user
        return json.dumps({"markers": [
            {"file": "notes/plan.md", "after_line": 2, "lines": ["## H3: The gap comes from the optimiser", "answers: Q1"]},
            {"file": "notes/plan.md", "after_line": 2, "lines": ["## H1: Already taken"]},
            {"file": "notes/elsewhere.md", "after_line": 1, "lines": ["## H9: x"]},
            {"file": "notes/plan.md", "after_line": 99, "lines": ["## H8: x"]},
            {"file": "notes/plan.md", "after_line": 1, "lines": ["just prose"]}]})

    before = (repo / "notes/plan.md").read_text()
    got = suggest.suggest(repo, ["notes/plan.md"], fake_llm)
    assert (repo / "notes/plan.md").read_text() == before                      # nothing written
    assert "+## H3: The gap comes from the optimiser" in got["patch"] and "+answers: Q1" in got["patch"]
    assert [r.split(": ", 1)[1] for r in got["refused"]] == [
        "H1 is already used", "not one of the files it was shown", "line 99 does not exist", "not a marker: just prose"]
    out = tmp_path / "s.patch"
    assert suggest.run(repo, ["notes/plan.md"], str(out), ask=fake_llm) == 0
    subprocess.run(["git", "apply", str(out)], cwd=repo, check=True)            # the patch applies as it is
    assert "H3" in compare.read(repo, ".")[0]["nodes"]


def test_a_claim_warns_when_a_result_stops_meeting_what_it_expects(repo, files):
    tex = (repo / "paper/main.tex").read_text().replace("% relies on: H1\n", "% relies on: H1\n% expects: E1.results acc.b32 > 0.86\n")
    files(repo, {"paper/main.tex": tex})
    assert compare.read(repo, ".")[0]["warnings"] == []                       # 0.874 > 0.86
    files(repo, {"out/e1.json": '{"acc": {"b32": 0.851, "b512": 0.842}}\n'})
    d = compare.compare(repo, "HEAD", ".").diff
    assert "C1 expects E1.results acc.b32 > 0.86, but it is 0.851" in d["warnings"]
    assert "1 new warning (C1 expects E1.results acc.b32 > 0.86, but it is 0.851)" in d["headline"]
