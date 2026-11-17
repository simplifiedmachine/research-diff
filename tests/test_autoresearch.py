"""Auto-research: experiments launched on a server's GPUs, checked, their results collected, each iteration handed to
Claude to analyse and improve, until the target holds or the budget is spent; pause, resume and stop; the session
carried on by the hooks and the pane; the web page's tab."""
from __future__ import annotations

import json
import os
import sys
import time

import pytest

from research_diff import agent, autoresearch as ar, compare, page

pytestmark = pytest.mark.skipif(os.name == "nt", reason="jobs run through a POSIX shell (servers are Linux)")
PY = sys.executable


def run_cmd(acc: float, sleep: float = 0.2) -> str:
    return (f"{PY} -c \"import json,time; time.sleep({sleep}); "
            f"json.dump({{'acc': {{'b32': {acc}, 'b512': 0.842}}}}, open('out/e1.json','w')); print('epoch 1 done')\"")


@pytest.fixture
def lab(repo, files):
    cfg = (repo / "configs/e1.yaml").read_text().replace("  results:", f"  run: {run_cmd(0.91)}\n  results:")
    files(repo, {"configs/e1.yaml": cfg})
    ar.save_server(repo, "here", "local")
    return repo


def until(root, done, most=40):
    for _ in range(most):
        c = ar.tick(root)
        if done(c):
            return c
        time.sleep(0.25)
    raise AssertionError(ar.as_text(root))


def test_servers_are_checked_before_they_are_kept(lab):
    with pytest.raises(ValueError):
        ar.save_server(lab, "bad name!", "local")
    with pytest.raises(ValueError):
        ar.save_server(lab, "x", "host; rm -rf /")
    s = ar.save_server(lab, "gpu1", "me@lab.example", "~/runs", [3, 1, 1], "source ~/venv/bin/activate", 2222)
    assert s["gpus"] == [1, 3] and s["port"] == 2222
    assert ar.check_server(lab, ar.servers(lab)[0]) == {"ok": True, "why": "", "gpus": []}
    assert ar.remove_server(lab, "gpu1") and [x["name"] for x in ar.servers(lab)] == ["here"]


def test_an_iteration_runs_collects_its_results_and_hands_claude_the_analysis(lab):
    assert compare.read(lab, ".")[0]["nodes"]["E1"]["run"] == run_cmd(0.91)
    ar.start(lab, "beat 0.95 with batch 32", target="E1.results acc.b32 > 0.95", max_iterations=3, experiments=["E1"])
    c = until(lab, lambda c: c["iterations"][-1]["state"] == "analyse")
    j = c["jobs"]["j001"]
    assert j["state"] == "done" and j["exit"] == 0 and "epoch 1 done" in j["tail"]
    assert compare.read(lab, ".")[0]["nodes"]["E1.results"]["metrics"]["acc.b32"] == 0.91     # collected
    ask = ar.pending(lab)
    assert "Iteration 1 ended: E1 done" in ask and "autoresearch_submit" in ask
    sent = page.show(lab, "auto", "", 100, deliver=True)["send"]          # the pane submits it to the session, once
    assert [x["text"] for x in sent] == [ask] and page.show(lab, "auto", "", 100, deliver=True)["send"] == []
    assert "ITERATION 1" in page.as_text(page.show(lab, "auto", "", 120))
    out = []
    for _ in range(3):                    # the Stop hook keeps Claude on it, twice at most
        agent.run_hook(json.dumps({"cwd": str(lab), "hook_event_name": "Stop"}), out.append)
    blocked = [json.loads(x) for x in out if '"decision"' in x]
    assert len(blocked) == 2 and blocked[0]["reason"] == ask
    cfg = (lab / "configs/e1.yaml").read_text().replace(run_cmd(0.91), run_cmd(0.97))
    (lab / "configs/e1.yaml").write_text(cfg)
    ar.submit(lab, [{"experiment": "E1"}], reason="a longer schedule", analysis="0.91: short of 0.95")
    c = until(lab, lambda c: c["state"] != "running")
    assert c["state"] == "done" and c["summary"] == "the target holds: E1.results acc.b32 > 0.95"
    assert c["iterations"][0]["analysis"] == "0.91: short of 0.95" and ar.pending(lab) is None


def test_pause_launches_nothing_resume_goes_on_and_stop_kills(lab):
    ar.start(lab, "g", max_iterations=2, experiments=["E1"])
    ar.control(lab, "pause")
    ar.tick(lab)
    assert ar.campaign(lab)["jobs"]["j001"]["state"] == "queued"
    with pytest.raises(ValueError):
        ar.control(lab, "pause")
    ar.control(lab, "resume")
    until(lab, lambda c: c["iterations"][-1]["state"] == "analyse")
    ar.submit(lab, [{"experiment": "E1", "command": "sleep 60"}], reason="wait")
    c = until(lab, lambda c: c["jobs"]["j002"]["state"] == "running")
    pid = c["jobs"]["j002"]["pid"]
    ar.control(lab, "stop")
    c = ar.campaign(lab)
    assert c["state"] == "stopped" and c["jobs"]["j002"]["state"] == "killed"
    time.sleep(0.5)
    with pytest.raises(OSError):
        os.kill(pid, 0)


def test_claude_plans_the_first_iteration_and_a_returning_session_is_told(lab):
    ar.start(lab, "find out whether batch size matters")
    ask = ar.pending(lab)
    assert ask.startswith("Auto-research goal: find out whether batch size matters. Plan the first iteration")
    out = []
    agent.run_hook(json.dumps({"cwd": str(lab), "hook_event_name": "SessionStart"}), out.append)
    assert "Plan the first iteration" in json.loads(out[0])["hookSpecificOutput"]["additionalContext"]
    with pytest.raises(ValueError):
        ar.submit(lab, [{"experiment": "Q1"}], reason="x")          # no run: command
    ar.submit(lab, [{"experiment": "E1"}], reason="start with the baseline")
    assert ar.campaign(lab)["iterations"][0]["jobs"] == ["j001"]


def test_an_ssh_server_gets_the_code_by_rsync_and_jobs_on_its_gpus(lab, monkeypatch):
    calls = []

    def fake(argv, timeout=60, cwd=None):
        calls.append(argv)
        return 0, "4242\n" if "echo $!" in argv[-1] else ""
    monkeypatch.setattr(ar, "_run", fake)
    s = ar.save_server(lab, "lab", "me@gpu.example", "~/runs", [0, 1], "source ~/venv/bin/activate")
    ar.start(lab, "g", max_iterations=1, server_names=["lab"], experiments=["E1"])
    c = ar.tick(lab)
    assert c["jobs"]["j001"]["state"] == "running" and c["jobs"]["j001"]["gpus"] == [0]
    rsync = next(a for a in calls if a[0] == "rsync")
    assert rsync[-1] == "me@gpu.example:~/runs/study/" and "--exclude" in rsync
    launch = calls[-1][-1]
    assert calls[-1][0] == "ssh" and "CUDA_VISIBLE_DEVICES=0" in launch and "setsid" in launch
    assert "source ~/venv/bin/activate &&" in launch
    assert s["workdir"] == "~/runs"


def test_the_web_tab_adds_servers_and_starts_pauses_and_stops(lab):
    import threading
    import urllib.request
    from research_diff import watch
    got, ready = {}, threading.Event()
    threading.Thread(target=watch.serve, args=(lab, "checkpoint", 0),
                     kwargs={"ready": lambda u, s, w: (got.update(url=u, server=s, w=w), ready.set())},
                     daemon=True).start()
    assert ready.wait(10)

    def post(path, body):
        req = urllib.request.Request(got["url"] + path, method="POST", data=json.dumps(body).encode(),
                                     headers={"x-token": got["w"].token, "content-type": "application/json"})
        return json.loads(urllib.request.urlopen(req, timeout=10).read())
    assert post("auto/server", {"name": "box", "host": "local", "gpus": "0,1"})["gpus"] == [0, 1]
    assert post("auto/start", {"goal": "g", "max_iterations": 2, "servers": ["here"], "experiments": ["E1"]}) == \
        {"state": "running"}
    assert post("auto/control", {"action": "pause"}) == {"state": "paused"}
    d = json.loads(urllib.request.urlopen(got["url"] + "auto", timeout=10).read())
    assert d["campaign"]["state"] == "paused" and {x["name"] for x in d["servers"]} == {"here", "box"}
    assert [x["id"] for x in d["experiments"] if x["run"]] == ["E1"]
    assert post("auto/control", {"action": "stop"}) == {"state": "stopped"}
    assert "Auto-research" in urllib.request.urlopen(got["url"], timeout=10).read().decode()
    got["server"].shutdown()
