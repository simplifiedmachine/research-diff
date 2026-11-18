"""research-diff inside system-diff's engine, page and pane (system_diff_ext.py): its tabs drawn with
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
    assert [v[0] for v in extensions.views()] == ["research", "evidence", "paper", "check", "team", "auto", "timeline"]
    assert extensions.owner("evidence") is x and extensions.owner("check") is x
    labels = [v[1] for v in extensions.views()]
    if callable(getattr(extensions, "home", None)):      # system-diff folds its own tabs: the research ones take names
        assert labels == ["Now", "Evidence", "Paper", "Review", "Agents", "Auto-research", "History"]
    else:                                                # beside system-diff's own: no two tabs share a name
        assert labels == ["Research", "Evidence", "Paper", "Problems", "Team", "Auto-research", "Timeline"]


def test_the_evidence_tab_is_system_diffs_diagram_in_the_evidence_graphs_words(study):
    page = x.web(ctx(study, "evidence"))
    svg = page["diagram"]["svg"]
    assert svg.startswith("<svg") and 'class="sd-arch"' in svg                    # system-diff's renderer
    assert "contradicted" in svg and "contradicts" in svg
    assert page["diagram"]["files"]["b:C1"] == {"path": "paper/main.tex", "line": 7, "end": 10}   # a click opens it
    assert page["diagram"]["files"]["b:R2"]["path"] == "notes/results.md"          # a result in the notes, too
    assert set(page["diagram"]["enter"]).isdisjoint(page["diagram"]["files"])       # the rest zoom into their chain
    assert not any(s["kind"] == "frame" for s in page["sections"])                  # one graph: the diagram
    card = page["diagram"]["details"]["b:C1"]
    assert {"title", "headline", "how", "insights", "facts"} <= set(card)
    assert "The paper contradicts itself: C2 contradicts C1" in json.dumps(page["sections"])
    zoomed = x.web(ctx(study, "evidence", "C2"))
    assert "b:C2" in zoomed["diagram"]["files"] and "b:R2" not in zoomed["diagram"]["enter"]   # only C2's chain


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
    assert [n["id"] for n in overview["nav"]] == ["1_batch", "2_lr", "~one"]
    assert overview["diagram"]["enter"]["b:2_lr"] == {"view": "research", "part": "2_lr@"}
    one = x.state(ctx(repo, "evidence", "1_batch@", live=live))
    two = x.state(ctx(repo, "evidence", "2_lr@", live=live))
    assert one["graph"]["nodes"]["C1"]["title"] == "Small batches win"            # each study its own C1
    assert two["graph"]["nodes"]["C1"]["title"] == "Batch size does not matter"
    assert "C2" not in one["graph"]["nodes"] and two["graph"]["conflicts"]
    ev = x.web(ctx(repo, "evidence", "2_lr@", live=live))
    assert ev["diagram"]["files"]["b:C1"]["path"] == "2_lr/paper/main.tex"
    assert ev["diagram"]["files"]["b:R1"]["path"] == "2_lr/notes.md"
    zoom = x.web(ctx(repo, "evidence", "2_lr@C1", live=live))                      # a zoom keeps the study
    assert zoom["diagram"]["pick"] == "b:C1" and [n["active"] for n in zoom["nav"]] == [False, True, False]
    assert [n["active"] for n in ev["nav"]] == [False, True, False]
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


def test_the_paper_opens_in_system_diffs_viewer_by_sections(study):
    c = ctx(study, "paper")
    page = x.web(c)
    assert not any(s["kind"] == "frame" for s in page["sections"])
    secs = page["diagram"]["files"]
    assert {v["path"] for v in secs.values()} == {"paper/main.tex"}
    assert [v["line"] for v in secs.values()] == sorted(v["line"] for v in secs.values())
    got = x.outline(c, "paper/main.tex", (study / "paper/main.tex").read_text())
    names = [ch["name"] for ch in got["outline"]["chunks"]]
    assert "§ Results" in names and any(n.startswith("C1 ") for n in names)
    assert got["summary"]["state"] in ("off", "summarizing", "failed", "done")


def test_claude_can_name_research_blocks_and_find_their_source(study):
    c = ctx(study, "")
    assert x.resolve(c, "C1") == {"id": "C1", "file": "paper/main.tex:7"}
    assert x.resolve(c, "`b:C2`")["id"] == "C2" and x.resolve(c, "Z9") is None
    src = x.source(ctx(study, "", "C1"), "C1")
    assert src["files"] == [{"path": "paper/main.tex", "line": 7}] and "marker" in src["config"]["change"]


def test_numbered_paper_folders_are_studies_whatever_the_globs_say(repo, files):
    """The shape of a real repository: six numbered paper folders (one without a paper yet), a results folder by
    study, shared scripts, slides in another folder, and a research-diff.toml whose globs name paper 1 only."""
    files(repo, {
        "research-diff.toml": 'paper = ["1_tradeoff/paper/*.tex"]\nnotes = ["1_tradeoff/**/*.md"]\n',
        "1_tradeoff/paper/main.tex": "\\section{Results}\n\n% C1: Reward models trade off\n% relies on: R1\nYes.\n",
        "1_tradeoff/notes.md": "## R1: The lean spans 26 to 68%\n\nmetrics: lean=0.42\n",
        "2_behavioral/paper/main.tex": "\\section{Results}\n\n% C1: Behaviour drifts\nIt does.\n",
        "3_duration/paper/main.tex": "\\section{Intro}\n\n% C1: Durations matter\nThey do.\n",
        "4_quality/paper/main.tex": "\\section{Intro}\n\n% C1: Data quality\nYes.\n",
        "5_critical/paper/main.tex": "\\section{Intro}\n\n% C1: Critical periods\nYes.\n",
        "6_serving/survey/notes.md": "## R1: Latency doubles at 64 users\n\nmetrics: p99=2.1\n",
        "results/2_behavioral/notes.md": "## R1: Drift of 0.3\n\nmetrics: drift=0.3\nsupports: C1\n",
        "patent_presentations/deck.tex": "% C9: Not a study\n",
        "scripts/run.py": "print(1)\n",
    })
    live = engine_live(repo)
    overview = x.web(ctx(repo, "research", live=live))
    assert [n["id"] for n in overview["nav"]] == ["1_tradeoff", "2_behavioral", "3_duration", "4_quality",
                                                  "5_critical", "6_serving", "~one"]
    two = x.state(ctx(repo, "evidence", "2_behavioral@", live=live))
    assert two["graph"]["nodes"]["C1"]["title"] == "Behaviour drifts"          # read despite the paper-1-only globs
    assert two["graph"]["nodes"]["C1"]["verdict"] == "supported"               # results/2_behavioral/ is its own
    six = x.state(ctx(repo, "research", "6_serving@", live=live))
    assert "R1" in six["map"]["nodes"] and "C9" not in six["map"]["nodes"]


def test_the_person_can_read_the_repository_as_one_study_and_split_it_again(repo, files):
    files(repo, {"1_a/paper/main.tex": "% C1: One\n", "2_b/paper/main.tex": "% C1: Two\n"})
    live = engine_live(repo)
    nav = x.web(ctx(repo, "research", live=live))["nav"]
    assert [n["id"] for n in nav] == ["1_a", "2_b", "~one"]
    one = x.web(ctx(repo, "research", "~one@", live=live))                      # the switch, remembered
    assert [n["title"] for n in one["nav"]] == ["Split into 2 studies"]
    assert x.state(ctx(repo, "evidence", "", live=live))["studies"] == []
    x.web(ctx(repo, "research", "~split@", live=live))
    assert len(x.state(ctx(repo, "evidence", "", live=live))["studies"]) == 2
    files(repo, {"research-diff.toml": "studies = false\n"})                     # or for good, in the config
    assert x.state(ctx(repo, "evidence", "", live=engine_live(repo, "v2")))["studies"] == []


def test_a_research_repository_opens_on_research_with_the_system_tabs_folded(repo, files):
    assert x.home(ctx(repo, "")) == {"view": "research", "system": "collapsed"}     # a LaTeX paper, no software
    files(repo, {"pyproject.toml": "[project]\nname = 'app'\n"})                   # a software project with a paper
    assert x.home(ctx(repo, "")) is None
    files(repo, {"research-diff.toml": 'paper = ["paper/*.tex"]\n'})               # research-diff set up at the root
    assert x.home(ctx(repo, ""))["view"] == "research"
    files(repo, {"research-diff.toml": 'home = "system"\n'})                       # the person says otherwise
    assert x.home(ctx(repo, "")) is None


def test_review_lists_what_to_fix_worst_first_on_the_evidence_diagram(study):
    page = x.web(ctx(study, "check"))
    assert page["title"] == x.LABEL["check"] and page["headline"].split(":")[0].endswith("to fix")
    todo = next(s for s in page["sections"] if s["title"] == "To fix")["items"]
    assert todo[0]["text"] == "The paper contradicts itself: C2 against C1 (lr-agent's against batch-agent's)"
    c1 = [i for i in todo if i["text"].startswith("C1 ")]
    assert len(c1) == 1 and c1[0]["text"].endswith("what it relies on no longer holds")   # H1, which R2 contradicts
    assert "C2 contradicts C1" not in c1[0]["why"]                                  # said once, above
    assert any(i["text"].endswith("a number in the paper is out of date") for i in todo)   # 88.9% vs 0.874
    assert todo[-1]["text"].startswith("C2 ") and todo[-1]["text"].endswith("nothing backs it yet")
    assert {"b:C1", "b:C2"} <= set(page["diagram"]["files"])                       # each opens where it is written
    assert page["diagram"]["svg"].startswith("<svg")
    titles = [s["title"] for s in page["sections"]]
    assert "The paper's review" in titles and any(t.startswith("Exactly, since") for t in titles)
    now = x.web(ctx(study, "research"))                                             # Now keeps what is worth a look
    assert not any(s["title"].startswith("Exactly") for s in now["sections"])


def test_agents_shows_who_owns_what_and_lights_it(study):
    page = x.web(ctx(study, "team"))
    team = next(s for s in page["sections"] if s["title"] == "The research team")
    assert team["kind"] == "lanes"
    lanes = {l["name"]: l for l in team["items"]}
    assert set(lanes) == {"batch-agent", "lr-agent"}
    assert "b:C1" in lanes["batch-agent"]["blocks"] and "b:C2" in lanes["lr-agent"]["blocks"]
    assert page["diagram"]["lights"]["ag:batch-agent"] == lanes["batch-agent"]["blocks"]
    assert any(s["title"] == "Agents contradicting each other" for s in page["sections"])   # C2 (lr) against C1 (batch)
    assert page["headline"].startswith("2 agents")


def test_history_shows_each_commit_of_the_research_and_what_it_did(study, files):
    from conftest import git
    git(study, "add", "-A")
    git(study, "commit", "-q", "-m", "results and the second claim")
    page = x.web(ctx(study, "timeline"))
    boxes = [k for k in page["diagram"]["enter"]]
    assert len(boxes) == 2 and page["headline"].startswith("2 changes")             # both commits, newest first
    newest = page["diagram"]["details"][boxes[0]]
    assert "results and the second claim" in newest["title"]
    opened = x.web(ctx(study, "timeline", page["diagram"]["enter"][boxes[0]]["part"]))
    assert opened["headline"].endswith("results and the second claim")
    assert any(s["title"] == "What it got" for s in opened["sections"])
    assert "b:C2" in opened["diagram"]["files"]                                     # what it touched, as it stands


def test_auto_research_runs_are_steps_on_system_diffs_workflow_board(repo):
    from research_diff import autoresearch
    c = {"id": "c1", "goal": "acc above 0.9", "state": "running", "max_iterations": 3, "servers": ["local"],
         "created": 1.0, "events": [{"at": 2.0, "text": "j001 E1 launched on local GPU 0"}],
         "iterations": [{"n": 1, "reason": "the baseline", "jobs": ["j001", "j002"], "state": "analysed",
                         "analysis": "lr too high", "started": 1.0, "ended": 5.0},
                        {"n": 2, "reason": "lower lr", "jobs": ["j003"], "state": "running", "started": 6.0}],
         "jobs": {"j001": {"id": "j001", "experiment": "E1", "command": "python train.py", "state": "done",
                           "server": "local", "gpus": [0], "tail": "epoch 1\nacc 0.84", "results": ["out/e1.json"]},
                  "j002": {"id": "j002", "experiment": "E2", "command": "python train.py --b 512", "state": "failed",
                           "server": "local", "gpus": [1], "tail": "", "why": "exited 1", "results": []},
                  "j003": {"id": "j003", "experiment": "E1", "command": "python train.py --lr 0.01",
                           "state": "running", "server": "local", "gpus": [0], "tail": "epoch 1", "results": []}}}
    autoresearch._save(repo, c)
    got = x.workflow(ctx(repo, ""))
    steps = {s["id"]: s for s in got["steps"]}
    assert set(steps) == {"auto-j001", "auto-j002", "auto-analyse-1", "auto-j003", "auto-analyse-2"}
    assert (steps["auto-j001"]["state"], steps["auto-j002"]["state"], steps["auto-j003"]["state"]) == \
        ("done", "failed", "running")
    assert steps["auto-analyse-1"]["state"] == "done" and steps["auto-analyse-2"]["state"] == ""
    waits = {(w["from"], w["to"]) for w in got["waits"]}
    assert {("auto-j001", "auto-analyse-1"), ("auto-analyse-1", "auto-j003"), ("auto-j003", "auto-analyse-2")} <= waits
    assert steps["auto-j003"]["actions"] == ["pause", "stop"] and steps["auto-j001"]["actions"] == []
    log = x.step_log(ctx(repo, ""), "auto-j001")
    assert [e["text"] for e in log["entries"]][:2] == ["j001 E1 launched on local GPU 0", "python train.py"]
    assert "acc 0.84" in [e["text"] for e in log["entries"]]
    assert x.workflow_action(ctx(repo, ""), "auto-j003", "pause")["ok"]
    assert autoresearch.campaign(repo)["state"] == "paused"
    assert x.workflow(ctx(repo, ""))["steps"][-1]["actions"] == []                  # its analysis waits: no action
    assert not x.workflow_action(ctx(repo, ""), "auto-j003", "retry")["ok"]
    assert {k["kind"] for k in x.WORKFLOW_KINDS} >= {"experiment-runner", "contradiction-reviewer"}
    assert x.WORKFLOW_TEMPLATES[0]["agents"][1]["waits_for"] == ["experiment-runner"]


def test_the_pane_draws_the_research_tabs_too(study):
    for view in ("check", "team", "timeline"):
        got = x.pane(ctx(study, view))
        assert got["view"] == view and got["rows"], view
