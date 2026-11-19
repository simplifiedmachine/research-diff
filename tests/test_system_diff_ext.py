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


@pytest.fixture
def no_system_list(monkeypatch):
    """A system-diff without a list of projects of its own: research-diff lists its studies."""
    monkeypatch.setattr(x, "_system_projects", lambda root: None)


def test_a_repository_with_several_papers_is_read_study_by_study(repo, files, no_system_list):
    files(repo, {
        "1_batch/paper/main.tex": "\\section{Results}\n\n% C1: Small batches win\n% relies on: R1\nYes.\n",
        "1_batch/notes.md": "## R1: Batch 32 beats 512\n\nmetrics: gap=0.03\n",
        "1_batch/train.py": "print('train')\n",
        "2_lr/paper/main.tex": ("\\section{Results}\n\n% C1: Batch size does not matter\n% relies on: R1\n"
                                "Indeed.\n\n% C2: Scaling closes the gap\n% contradicts: C1\nAlso.\n"),
        "2_lr/notes.md": "## R1: Scaled LR closes the gap\n\nmetrics: gap=0.002\n",
        "2_lr/sweep.yaml": "lr: [0.1, 0.4]\n",
    })
    live = engine_live(repo)
    now = x.web(ctx(repo, "research", live=live))
    assert [n["id"] for n in now["nav"]] == ["1_batch", "2_lr", "~one"]
    assert now["nav"][1]["target"] == {"view": "research", "part": "2_lr@", "scope": "2_lr"}
    assert now["diagram"]["title"] != "Studies" and now["title"].endswith("1 · batch")   # the first study, no list
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
    assert [s["title"] for s in page["sections"] if s["kind"] == "frame"] == ["The PDF"]   # the only frame
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


def test_studies_are_folders_with_a_paper_and_work_of_their_own_whatever_their_names(repo, files, no_system_list):
    """Found by what the folders hold, never by their names: a paper and work beside it (code or data). Slides, shared
    scripts and a paper alone are no study, and a study reads only its own files (and those at the top)."""
    files(repo, {
        "research-diff.toml": 'paper = ["tradeoff/paper/*.tex"]\nnotes = ["tradeoff/**/*.md"]\n',
        "tradeoff/paper/main.tex": "\\section{Results}\n\n% C1: Reward models trade off\n% relies on: R1\nYes.\n",
        "tradeoff/notes.md": "## R1: The lean spans 26 to 68%\n\nmetrics: lean=0.42\n",
        "tradeoff/experiments/run.py": "print('run')\n",
        "behavioral/paper/main.tex": "\\section{Results}\n\n% C1: Behaviour drifts\nIt does.\n",
        "behavioral/experiments/config.yaml": "lr: 0.1\n",
        "duration/paper/main.tex": "\\section{Intro}\n\n% C1: Durations matter\nThey do.\n",
        "duration/env.py": "print('env')\n",
        "serving/survey/survey.tex": "\\section{Intro}\n\n% C1: Latency doubles at 64 users\nIt does.\n",
        "serving/bench/load.py": "print('load')\n",
        "results/behavioral/notes.md": "## R1: Drift of 0.3\n\nmetrics: drift=0.3\nsupports: C1\n",
        "patent_presentations/deck.tex": "% C9: Not a study\n",            # slides: a paper, no work
        "scripts/run.py": "print(1)\n",                                       # work, no paper
        "drafts/paper/main.tex": "% C7: A draft\n",                           # a paper alone
    })
    live = engine_live(repo)
    now = x.web(ctx(repo, "research", live=live))
    assert [n["id"] for n in now["nav"]] == ["behavioral", "duration", "serving", "tradeoff", "~one"]
    two = x.state(ctx(repo, "evidence", "behavioral@", live=live))
    assert two["graph"]["nodes"]["C1"]["title"] == "Behaviour drifts"          # read despite the tradeoff-only globs
    assert two["graph"]["nodes"]["C1"]["verdict"] == "supported"               # results/behavioral/ is its own
    serving = x.state(ctx(repo, "research", "serving@", live=live))
    assert serving["graph"]["nodes"]["C1"]["title"] == "Latency doubles at 64 users"
    assert not {"C7", "C9"} & set(serving["map"]["nodes"])                     # not another folder's
    assert [f["path"] for f in serving["map"]["paper"]] == ["serving/survey/survey.tex"]


def test_the_person_can_read_the_repository_as_one_study_and_split_it_again(repo, files, no_system_list):
    files(repo, {"1_a/paper/main.tex": "% C1: One\n", "1_a/run.py": "print(1)\n",
                 "2_b/paper/main.tex": "% C1: Two\n", "2_b/run.py": "print(2)\n"})
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


def test_the_study_follows_the_project_picked_in_system_diffs_own_list(repo, files, monkeypatch):
    """Where system-diff's list already offers the studies' folders, there is one list: its pick (which stays from
    tab to tab) is the study; a study named in the page's part still wins."""
    files(repo, {"a/paper/main.tex": "% C1: Alpha\n", "a/run.py": "print(1)\n",
                 "b/paper/main.tex": "% C1: Beta\n", "b/run.py": "print(2)\n"})
    live = engine_live(repo)
    monkeypatch.setattr(x, "_system_projects", lambda root: ["a", "b"])
    monkeypatch.setattr(x, "_scope", lambda c: "b/paper")                       # a folder inside study b
    page = x.web(ctx(repo, "paper", live=live))
    assert "nav" not in page                                                     # one list: system-diff's
    assert x.state(ctx(repo, "evidence", "", live=live))["graph"]["nodes"]["C1"]["title"] == "Beta"
    assert x.state(ctx(repo, "evidence", "a@", live=live))["graph"]["nodes"]["C1"]["title"] == "Alpha"
    assert [p["path"] for p in x.projects(ctx(repo, "", live=live))] == ["a", "b"]   # for system-diff's own list
    monkeypatch.setattr(x, "_system_projects", lambda root: "one")              # shown as one project there
    assert x.state(ctx(repo, "evidence", "", live=engine_live(repo, "v2")))["studies"] == []


def test_files_without_research_are_read_once(repo, files):
    """Logs and outputs are read once: a file that held no research is not read again until it changes."""
    from research_diff import compare, config, extract as ex, scan
    files(repo, {f"results/log{i}.json": '{"loss": %d}' % i for i in range(30)})
    files(repo, {"configs/e3.yaml": "research:\n  id: E3\n  tests: [H1]\n"})

    class Counting(compare.WorkSource):
        asked: list = []

        def read_many(self, paths):
            paths = list(paths)
            Counting.asked += paths
            return super().read_many(paths)
    scan.forget(repo)
    src = Counting(repo)
    cfg = config.load(src, repo)
    first = ex.extract(src, cfg)
    assert sum(p.startswith("results/log") for p in Counting.asked) == 30 and "E3" in first["nodes"]
    Counting.asked = []
    again = ex.extract(Counting(repo), cfg)
    assert not any(p.startswith("results/log") for p in Counting.asked)         # known to hold nothing
    assert "configs/e3.yaml" in Counting.asked and "E3" in again["nodes"]       # research is read every time
    files(repo, {"results/log3.json": '{"research": {"id": "E9", "tests": ["H2"]}}'})
    Counting.asked = []
    changed = ex.extract(Counting(repo), cfg)
    assert [p for p in Counting.asked if p.startswith("results/log")] == ["results/log3.json"]
    assert "E9" in changed["nodes"]


def _two_studies(repo, files):
    files(repo, {"a/paper/main.tex": "\\section{R}\n\n% C1: Alpha\n% relies on: R1\nYes.\n", "a/run.py": "print(1)\n",
                 "a/notes.md": "## R1: Alpha holds\n\nmetrics: acc=0.9\n",
                 "b/paper/main.tex": "% C1: Beta\n", "b/run.py": "print(2)\n"})


def test_a_study_is_read_again_only_when_its_own_files_change(repo, files, no_system_list, monkeypatch):
    from research_diff import extract as ex
    _two_studies(repo, files)
    x.state(ctx(repo, "evidence", "a@", live=engine_live(repo, "v1")))
    x.state(ctx(repo, "evidence", "b@", live=engine_live(repo, "v1")))
    calls = []
    real = ex.extract
    monkeypatch.setattr(ex, "extract", lambda *a, **k: calls.append(a[2][0] if a[2] else "") or real(*a, **k))
    files(repo, {"b/run.py": "print(3)\n"})                                      # study b changes, a does not
    x.state(ctx(repo, "evidence", "a@", live=engine_live(repo, "v2")))
    assert calls == []
    x.state(ctx(repo, "evidence", "b@", live=engine_live(repo, "v2")))
    assert calls == ["b"]
    assert x.progress_text(repo, "a") == "ready · 1 claim, all supported"
    assert x.progress_text(repo, "b") == "ready · 1 with nothing behind it"


def test_the_checkpoint_read_back_from_disk_gives_the_same_diff(repo, files, no_system_list):
    _two_studies(repo, files)
    first = x.state(ctx(repo, "check", "a@", live=engine_live(repo, "v1")))
    x._BASE.clear()
    x._STATE.clear()
    again = x.state(ctx(repo, "check", "a@", live=engine_live(repo, "v1")))      # its base from the file
    assert again["cmp"].diff["changes"] == first["cmp"].diff["changes"]
    assert again["cmp"].diff["headline"] == first["cmp"].diff["headline"]


def test_every_study_is_read_in_the_background_with_its_progress(repo, files, no_system_list, monkeypatch):
    _two_studies(repo, files)
    monkeypatch.setenv("RESEARCH_DIFF_WARM", "on")
    page = x.web(ctx(repo, "research", "a@", live=engine_live(repo, "w1")))
    x._WORKERS[str(repo)].join(30)
    assert x.progress_text(repo, "b").startswith(("ready", "no claims"))           # read without being opened
    rows = {n["id"]: n["sub"] for n in page["nav"] if not n["id"].startswith("~")}
    assert rows["a"].startswith("ready")                                            # each row says what it holds
    assert [p["why"] for p in x.projects(ctx(repo, "", live=engine_live(repo, "w1")))][0].startswith("ready")
    assert x.progress(ctx(repo, "paper", "b@", live=engine_live(repo, "w1"))) == ""          # read: nothing under way
    x._note(repo, "b", stage="reading files", done=40, total=100)
    assert x.progress(ctx(repo, "paper", "b@", live=engine_live(repo, "w1"))) == "reading files 40% · 40 of 100 files"


def _long_paper(repo, files):
    """4 sections, 5 subsections each, 11 tables \\input from them; a table and a claim with stale numbers."""
    tex = ["\\documentclass{article}", "\\begin{document}"]
    k = 0
    for i in range(4):
        tex += [f"\\section{{Part {i}}}", ""]
        for j in range(5):
            tex += [f"\\subsection{{Topic {i}.{j}}}", "", f"Words about {i}.{j}.", ""]
        for _ in range(3 if i < 3 else 2):
            k += 1
            tex += [f"\\input{{tables/t{k}}}", ""]
    tex[tex.index("\\section{Part 2}") + 2:tex.index("\\section{Part 2}") + 2] = [
        "% C1: Small batches win", "% relies on: E1", "Batch 32 reaches 86.1\\% here.", ""]
    tex += ["\\end{document}", ""]
    tables = {f"paper/tables/t{n}.tex": f"\\begin{{tabular}}{{lr}}\nb32 & {87.4 if n != 5 else 86.9}\\% \\\\\n"
              "\\end{tabular}\n" for n in range(1, 12)}
    files(repo, {"paper/main.tex": "\n".join(tex), **tables,
                 "paper/notes-figure.tex": "A loose file no section inputs.\n"})


def test_a_long_paper_is_drawn_by_its_sections(repo, files):
    _long_paper(repo, files)
    page = x.web(extensions.Context(repo, "paper", "", 140, 1, None))              # compact
    boxes = [k for k in page["diagram"]["details"]]
    assert len([b for b in boxes if b != "b:other"]) == 4 and "b:other" in boxes   # 4 sections, plus Other files
    svg = page["diagram"]["svg"]
    assert "Topic 0.1" not in svg and "tables 3" in svg                             # parts fold, tables are a chip
    part2 = next(k for k, d in page["diagram"]["details"].items() if d["title"] == "§ Part 2")
    assert page["diagram"]["enter"][part2]["view"] == "paper"
    need = next(sec for sec in page["sections"] if sec["title"] == "Needs attention")["items"]
    assert need[0]["text"].startswith("§ Part 2")                                   # worst first: the stale claim
    detailed = x.web(extensions.Context(repo, "paper", "", 140, 0, None))
    assert "Topic 0.1" in detailed["diagram"]["svg"]                                # detailed lists the parts
    outline = x.web(extensions.Context(repo, "paper", "", 140, 2, None))
    assert "tables 3" not in outline["diagram"]["svg"]                              # outline: the sections alone
    opened = x.web(extensions.Context(repo, "paper", page["diagram"]["enter"][part2]["part"], 140, 1, None))
    titles = [d["title"] for d in opened["diagram"]["details"].values()]
    assert [t for t in titles if t.startswith("Topic")] == [f"Topic 2.{j}" for j in range(5)]
    assert {"paper/tables/t7.tex", "paper/tables/t8.tex", "paper/tables/t9.tex"} <= set(titles)
    assert all(f["path"].startswith("paper/") for f in opened["diagram"]["files"].values())   # each opens its file


FAKE_PDFLATEX = r"""#!/usr/bin/env python3
import gzip, os, sys
out = [a.split("=", 1)[1] for a in sys.argv if a.startswith("-output-directory=")][0]
src = sys.argv[-1]
stem = os.path.splitext(src)[0]
open(os.path.join(out, stem + ".pdf"), "wb").write(b"%PDF-1.4 fake")
with gzip.open(os.path.join(out, stem + ".synctex.gz"), "wt") as f:
    f.write("SyncTeX Version:1\nInput:1:./" + src + "\nContent:\n{1\n(1,1:0,0:0,0,0\n}1\n{2\n(1,40:0,0:0,0,0\n}2\n")
"""


@pytest.mark.skipif(__import__("os").name == "nt", reason="the stand-in pdflatex is a script with a #! line")
def test_the_paper_tab_shows_the_pdf_turned_to_the_section(repo, files, monkeypatch, tmp_path):
    import os
    import stat
    from research_diff import pdf
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    exe = bin_ / "pdflatex"
    exe.write_text(FAKE_PDFLATEX)
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_}{os.pathsep}" + os.environ["PATH"])
    tex = ["\\documentclass{article}", "\\begin{document}"] + ["\\section{One}", "", "a", "", "b"] + [""] * 30 + \
        ["\\section{Two}", "\\subsection{Two.a}", "", "c", "\\end{document}"]
    files(repo, {"paper/main.tex": "\n".join(tex)})
    page = x.web(extensions.Context(repo, "paper", "", 140, 1, None))
    frame = next(s for s in page["sections"] if s["title"] == "The PDF")
    for t in list(pdf._JOBS.values()):
        t.join(30)
    assert pdf.status(repo, "paper/main.tex")["state"] == "ready"
    two = next(k for k, d in page["diagram"]["details"].items() if d["title"] == "§ Two")
    opened = x.web(extensions.Context(repo, "paper", page["diagram"]["enter"][two]["part"], 140, 1, None))
    src = next(s for s in opened["sections"] if s["title"] == "The PDF")["items"][0]["src"]
    assert frame["kind"] == "frame" and src.startswith("/x/research/pdf?") and "line=38" in src
    from urllib.parse import parse_qsl, urlsplit
    q = dict(parse_qsl(urlsplit(src).query))
    status, kind, body = x.route(ctx(repo, ""), "GET", "pdf", q, b"")
    assert status == 200 and b"#page=2" in body                                    # section Two is on page 2
    status, kind, body = x.route(ctx(repo, ""), "GET", "pdf/file", {"main": "paper/main.tex"}, b"")
    assert status == 200 and kind == "application/pdf" and body.startswith(b"%PDF")
    assert x.route(ctx(repo, ""), "GET", "pdf/file", {"main": "../etc/passwd"}, b"")[0] == 404


def test_the_pdf_builder_is_found_where_tex_installs_it(monkeypatch, tmp_path):
    from research_diff import pdf
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("RESEARCH_DIFF_PDFLATEX", "")
    monkeypatch.setattr(pdf.shutil, "which", lambda name: None)
    monkeypatch.setattr("glob.glob", lambda pattern: [])
    assert pdf.find() == ("", "")
    exe = tmp_path / "pdflatex.exe"
    exe.write_text("")
    monkeypatch.setenv("RESEARCH_DIFF_PDFLATEX", str(exe))                       # named exactly
    assert pdf.find() == (str(exe), "pdflatex")
    monkeypatch.setenv("RESEARCH_DIFF_PDFLATEX", "")
    monkeypatch.setattr("glob.glob", lambda pattern: [str(exe)] if "MiKTeX" in pattern else [])
    assert pdf.find() == (str(exe), "pdflatex")                                  # where MiKTeX puts it
