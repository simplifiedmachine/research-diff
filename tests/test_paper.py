"""The paper as written, hand in hand with its experiments and results: sections, tables and figures, every number
checked against the results; the file view with the LLM's summaries; the LLM's review; Claude's answers and pointing on
the web page; one hub address shared with system-diff; history between any two points."""
from __future__ import annotations

import json

import pytest

from research_diff import chat, compare, hub, paperview, review
from research_diff.cli import main

PAPER = r"""\begin{abstract}
Batch 32 reaches 88.9\% against 84.2\% for batch 512.
\end{abstract}

\section{Results}

\begin{table}[t]
  % of: E1
  \begin{tabular}{lc} 32 & 87.4 \\ 512 & 84.2 \\ \end{tabular}
  \caption{Accuracy, learning rate fixed}
  \label{tab:main}
\end{table}

% C1: Small batches win on small data
% relies on: H1
Batch 32 reaches 87.4\% (Table~\ref{tab:main}); see also Figure~\ref{fig:missing}.

\section{Conclusion}

% C2: Small batches win by over 4 points
% relies on: E1
Batch 32 is 4.6\% ahead and reaches 86.1\%.
"""


@pytest.fixture
def study(repo, files):
    files(repo, {"out/e1.json": '{"acc": {"b32": 0.874, "b512": 0.842}}\n', "paper/main.tex": PAPER})
    return repo


def test_every_number_the_paper_prints_is_checked_against_its_results(study):
    bp = compare.read(study, ".")[0]
    assert bp["nodes"]["tab:main"]["kind"] == "table" and ["tab:main", "shows", "C1"] in bp["links"]
    checks = {(c["from"], c["to"], c["sign"]) for c in bp["checks"]}
    assert ("E1.results", "tab:main", "+") in checks and ("E1.results", "C1", "+") in checks
    stale = [c["why"] for c in bp["checks"] if c["sign"] == "-"]
    assert stale == ["C2 says 86.1% (paper/main.tex:22), but E1.results acc.b32 is 0.874"]
    assert [i["why"] for i in bp["issues"]] == [
        "§Abstract:2 says 88.9% (paper/main.tex:2), but E1.results acc.b32 is 0.874"]
    assert "paper/main.tex:16 refers to fig:missing, which the paper does not define" in bp["warnings"]
    assert [s["title"] for s in bp["paper"][0]["sections"]] == ["Abstract", "Results", "Conclusion"]


def test_a_paragraph_that_contradicts_the_results_is_a_red_box_of_its_section(study):
    g = compare.evidence_of(study)[0]
    v = {s["id"]: s for s in g["statements"]}
    assert v["§Abstract:2"]["verdict"] == "contested" and v["§Abstract:2"]["section"] == "Abstract"
    assert v["C2"]["verdict"] == "contested"
    assert v["C1"]["verdict"] == "supported"
    assert any(x["kind"] == "shows" for x in v["C1"]["for"])


def test_the_file_view_outlines_the_paper_and_keeps_the_llms_summary_by_version(study, monkeypatch):
    g, bp, _ = compare.evidence_of(study)
    o = paperview.outline(study, "paper/main.tex", bp, g)
    assert [c["title"] for c in o["chunks"]] == ["Abstract", "Results", "Conclusion"]
    assert [st["id"] for st in o["chunks"][1]["statements"]] == ["C1"]
    assert o["chunks"][1]["floats"][0]["label"] == "tab:main"
    assert any(n["sign"] == "-" for n in o["chunks"][0]["numbers"])
    asked = []

    def fake(user, system):
        asked.append(user)
        return json.dumps({"file": "Small batches win.", "sections": {
            "Results": {"says": "Batch 32 wins.", "claims": "87.4%", "watch": ""},
            "Invented": {"says": "x"}}})
    monkeypatch.setattr(paperview, "ASK", fake)
    got = paperview.summarize(study, "paper/main.tex", bp, g, wait=True)
    assert got["state"] == "done" and list(got["sections"]) == ["Results"] and "### Abstract" in asked[0]
    assert paperview.summarize(study, "paper/main.tex", bp, g, wait=True)["state"] == "done" and len(asked) == 1
    assert "✦ says: Batch 32 wins." in paperview.as_text(paperview.outline(study, "paper/main.tex", bp, g))


def test_the_review_keeps_only_findings_whose_quotes_are_in_the_paper(study, monkeypatch, tmp_path):
    answer = {"findings": [
        {"kind": "contradiction", "sections": ["Abstract", "Conclusion"], "quotes": ["Batch 32 reaches 88.9%",
                                                                                  "reaches 86.1%"],
         "ids": ["C1", "C2"], "why": "The abstract and the conclusion give different accuracies."},
        {"kind": "overclaim", "sections": ["Results"], "quotes": ["never written anywhere"], "ids": [], "why": "x"},
        {"kind": "contradiction", "sections": ["Nowhere"], "quotes": ["Batch 32"], "ids": [], "why": "y"}]}
    monkeypatch.setattr(review, "ASK", lambda u, s: json.dumps(answer))
    r = review.run(study)
    assert [f["why"] for f in r["findings"]] == ["The abstract and the conclusion give different accuracies."]
    assert review.current(study)["stale"] is False
    assert review.links_from(r, compare.read(study, ".")[0]) == [
        {"from": "C2", "rel": "contradicts", "to": "C1", "why": "The abstract and the conclusion give different accuracies."}]
    (study / "paper/main.tex").write_text(PAPER + "\nMore.\n", encoding="utf-8")
    assert review.current(study)["stale"] is True and review.worth(review.current(study)) == []


def test_claude_s_answers_pointing_and_notes_are_kept_for_the_page(study, tmp_path):
    from research_diff import activity, agent, evgraph, page
    activity.record(study, "prompt", text="does C2 hold?")
    assert chat.answered(study, {"last_assistant_message": "No: C2's 86.1% is stale. api_key=abc123"})
    a = chat.answers(study)[-1]
    assert a["prompt"] == "does C2 hold?" and "abc123" not in a["text"]
    chat.point(study, ["C2", "E1.results"], "the stale number")
    chat.add_note(study, "C2", "86.1% is from an old run")
    g = compare.evidence_of(study)[0]
    g["notes"] = {k: [n["text"] for n in v] for k, v in chat.notes_by_node(study).items()}
    g["pointing"] = chat.pointing(study)["ids"]
    html = evgraph.standalone(g)
    assert '"pointing": ["C2", "E1.results"]' in html and "86.1% is from an old run" in html
    assert "86.1% is from an old run" in page.as_text(page.show(study, "now", "C2", 120))
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("\n".join(json.dumps(x) for x in [
        {"type": "user", "message": {"content": "check the paper"}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Reading it."}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "The abstract is stale."}]}}]))
    assert chat.transcript_answer(str(transcript)) == "The abstract is stale."
    assert agent.run_hook(json.dumps({"cwd": str(study), "hook_event_name": "Stop",
                                      "transcript_path": str(transcript)}), lambda s: None) == 0
    assert chat.answers(study)[-1]["text"] == "The abstract is stale."


def test_the_web_page_joins_system_diffs_hub_and_opens_the_paper(study, tmp_path, monkeypatch):
    import threading
    import urllib.request
    from research_diff import watch
    monkeypatch.setenv("SYSTEM_DIFF_ENGINES", str(tmp_path / "engines"))
    got, ready = {}, threading.Event()

    def on_ready(url, server, w):
        got.update(url=url, server=server, w=w)
        ready.set()
    threading.Thread(target=watch.serve, args=(study, "checkpoint", 0), kwargs={"ready": on_ready}, daemon=True).start()
    assert ready.wait(10)
    url = got["url"]
    read = lambda path: urllib.request.urlopen(url + path, timeout=10).read().decode()  # noqa: E731
    who = json.loads(read("whoami"))
    assert who["app"] == "system-diff" and who["tool"] == "research-diff"          # system-diff's hub keeps it
    entry = json.loads(next((tmp_path / "engines").glob("*.json")).read_text(encoding="utf-8"))
    assert entry["name"] == "study · research" and entry["id"] == who["id"]
    projects = json.loads(read("projects"))["projects"]
    assert [(p["name"], p["tool"], p["current"]) for p in projects] == [("study · research", "research-diff", True)]
    assert hub.find_hub() == int(url.rsplit(":", 1)[1].strip("/")) or hub.find_hub() is not None
    assert "Your projects" in read("projects/page")
    f = json.loads(read("file?path=paper/main.tex"))
    assert 'class="ln bad"' in f["html"] and "tab:main" in f["html"]
    assert "Only the research" in json.loads(read("file?path=../../etc/passwd"))["html"]
    assert "Paper" in read("") and "§ RESULTS" in json.loads(read("view?v=paper"))["html"]
    got["server"].shutdown()


def test_history_compares_any_two_points(study, capsys):
    import subprocess
    subprocess.run(["git", "add", "-A"], cwd=study, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-qm", "paper"], cwd=study, check=True)
    assert main(["--repo", str(study), "history", "compare", "HEAD~1", "HEAD"]) == 0
    out = capsys.readouterr().out
    assert "2 claims" in out or "C2" in out
    assert main(["--repo", str(study), "outline", "paper/main.tex"]) == 0
    assert "✗ line 22" in capsys.readouterr().out
