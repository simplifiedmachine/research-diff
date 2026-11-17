"""AUTO-RESEARCH: the research loop run for you, iteration after iteration, while you watch it on the page.

    launch    each experiment of an iteration on a free GPU of your servers (`run:` beside its `results:` in its
              research block or marker: the command, from the repository's root)
    check     every running job, until it ends; its log's tail on the page
    collect   its results file back into the repository: the map, the evidence and the paper's number checks move
    improve   the iteration done, Claude (in your session) is asked to analyse what came out and submit the next
              iteration (the autoresearch_submit tool: what it changed and why, and the experiments to run)

until the TARGET holds (`E2.results acc > 0.88`, as `expects:` writes it), the iteration BUDGET is spent, or you pause
or stop it. Two halves, so that nothing is lost when the session goes:

- The RUNNER (`research-diff auto runner`, started by itself, detached) launches, checks and collects. It does not need
  your session: jobs on a server go on, and it finds them again by their pid when it starts again.
- The IMPROVE step needs Claude: an iteration that ended is handed to the session (the pane submits it as a prompt;
  the Stop hook keeps Claude on it; a session that comes back is told first thing), and it waits for one if none is
  open: when you reconnect, the loop goes on where it was.

PAUSE: no new launches and no new asks; running jobs go on and are collected. STOP: running jobs are killed.

SERVERS are yours: `local` (this machine) or an SSH host your keys already reach (ssh -o BatchMode=yes: no password is
ever asked or kept). Each has a working directory there, an optional setup command (`source ~/venv/bin/activate`), and
its GPUs (CUDA_VISIBLE_DEVICES, one job per GPU; none: CPU jobs, one at a time). The code goes there with rsync (the
working tree, without .git and what .gitignore leaves out). Kept in .git/research-diff/auto/: never committed.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shlex
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, List, Optional, Tuple

from . import store

DIR = "auto"
TICK = 10.0               # seconds between two looks of the runner
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=15"]
ACTIVE = ("running", "paused")
NAME_RX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,40}$")


# ── state ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def _home(root: Path) -> Path:
    d = store.home(root) / DIR
    (d / "logs").mkdir(parents=True, exist_ok=True)
    return d


def _read(root: Path, name: str, default: Any) -> Any:
    try:
        return json.loads((_home(root) / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(root: Path, name: str, data: Any) -> None:
    path = _home(root) / name
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def servers(root: Path) -> List[dict]:
    return _read(root, "servers.json", [])


def save_server(root: Path, name: str, host: str, workdir: str = "", gpus: Optional[List[int]] = None,
                setup: str = "", port: int = 0) -> dict:
    """Add or change a server. `host`: "local", or an SSH destination (user@host, or a Host of ~/.ssh/config)."""
    if not NAME_RX.match(name or ""):
        raise ValueError("a server's name is letters, digits, - _ and . (up to 40)")
    host = host.strip()
    if host != "local" and not re.match(r"^[A-Za-z0-9_.@:\[\]-]+$", host):
        raise ValueError("host: local, or user@host, or a Host of your ~/.ssh/config")
    s = {"name": name, "host": host, "workdir": workdir.strip() or ("" if host == "local" else "research-diff-runs"),
         "gpus": sorted({int(g) for g in (gpus or [])}), "setup": setup.strip(), "port": int(port or 0)}
    got = [x for x in servers(root) if x["name"] != name] + [s]
    _write(root, "servers.json", got)
    return s


def remove_server(root: Path, name: str) -> bool:
    got = servers(root)
    kept = [x for x in got if x["name"] != name]
    _write(root, "servers.json", kept)
    return len(kept) != len(got)


def campaign(root: Path) -> dict:
    return _read(root, "campaign.json", {})


def _save(root: Path, c: dict) -> None:
    c["updated"] = time.time()
    _write(root, "campaign.json", c)


def log(root: Path, c: dict, text: str) -> None:
    c.setdefault("events", []).append({"at": time.time(), "text": text[:400]})
    c["events"] = c["events"][-200:]


# ── servers: launch, check, kill, copy ─────────────────────────────────────────────────────────────────────────────

def _run(argv: List[str], timeout: float = 60, cwd: Optional[Path] = None) -> Tuple[int, str]:
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, cwd=cwd, stdin=subprocess.DEVNULL)
        return r.returncode, (r.stdout + r.stderr)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 255, f"{type(exc).__name__}: {exc}"


def _ssh(s: dict, command: str, timeout: float = 60) -> Tuple[int, str]:
    return _run(SSH + (["-p", str(s["port"])] if s.get("port") else []) + [s["host"], command], timeout)


def remote_dir(root: Path, s: dict) -> str:
    """Where the code runs: the repository itself for `local` (unless a workdir is given), else <workdir>/<repo>."""
    if s["host"] == "local":
        return str(Path(s["workdir"]).expanduser() / root.name) if s.get("workdir") else str(root)
    return f"{s['workdir'].rstrip('/')}/{root.name}"


def check_server(root: Path, s: dict) -> dict:
    """Can it be reached, and which GPUs does it have (nvidia-smi)? {"ok", "why", "gpus": [{index, name, used, total}]}"""
    probe = "nvidia-smi --query-gpu=index,name,memory.used,memory.total --format=csv,noheader,nounits 2>/dev/null; true"
    if s["host"] == "local":
        code, out = _run(["sh", "-c", probe], 20) if os.name != "nt" else (0, "")
    else:
        code, out = _ssh(s, probe, 25)
        if code != 0:
            return {"ok": False, "why": out.strip()[-300:] or f"ssh exited {code}", "gpus": []}
    gpus = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 4 and parts[0].isdigit():
            gpus.append({"index": int(parts[0]), "name": parts[1], "used": parts[2], "total": parts[3]})
    return {"ok": True, "why": "", "gpus": gpus}


def _sync_up(root: Path, s: dict) -> Tuple[bool, str]:
    """The working tree to the server (not for `local` in the repository itself)."""
    dest = remote_dir(root, s)
    if s["host"] == "local" and dest == str(root):
        return True, ""
    filt = ["--exclude", ".git", "--exclude", ".venv*", "--filter", ":- .gitignore"]
    if s["host"] == "local":
        Path(dest).mkdir(parents=True, exist_ok=True)
        code, out = _run(["rsync", "-a", *filt, f"{root}/", f"{dest}/"], 600)
    else:
        code, out = _ssh(s, f"mkdir -p {shlex.quote(dest)}", 30)
        if code == 0:
            ssh = " ".join(shlex.quote(a) for a in SSH + (["-p", str(s["port"])] if s.get("port") else []))
            code, out = _run(["rsync", "-az", "-e", ssh, *filt, f"{root}/", f"{s['host']}:{dest}/"], 1800)
    return code == 0, out.strip()[-300:]


def _launch(root: Path, s: dict, job: dict) -> Tuple[Optional[int], str]:
    """Start a job in a session of its own (setsid, where there is one: stop then ends all of it), detached from the
    connection, with its GPUs; its log and exit code beside the code. Its pid, or None and why."""
    dest = remote_dir(root, s)
    logs = ".research-diff-logs"
    gpus = ",".join(str(g) for g in job["gpus"])
    exit_file = f"{logs}/{job['id']}.exit"
    body = (f"{s['setup']} && " if s.get("setup") else "") + job["command"] + f"; echo $? > {exit_file}"
    script = (f"cd {shlex.quote(dest)} && mkdir -p {logs} && export CUDA_VISIBLE_DEVICES={shlex.quote(gpus)} "
              f"RESEARCH_DIFF_JOB={job['id']} && if command -v setsid >/dev/null 2>&1; then L=setsid; else L=nohup; fi; "
              f"$L sh -c {shlex.quote(body)} > {logs}/{job['id']}.log 2>&1 < /dev/null & echo $!")
    code, out = _run(["sh", "-c", script], 30) if s["host"] == "local" else _ssh(s, script, 40)
    pid = next((int(x) for x in out.split() if x.isdigit()), None)
    return (pid, "") if code == 0 and pid else (None, out.strip()[-300:] or f"exit {code}")


def _poll(root: Path, s: dict, job: dict) -> Optional[dict]:
    """{"alive", "exit" (None while it runs), "tail"}; None when the server cannot be reached now."""
    dest, logs = remote_dir(root, s), ".research-diff-logs"
    script = (f"cd {shlex.quote(dest)} 2>/dev/null; if kill -0 {int(job['pid'])} 2>/dev/null; then echo ALIVE; "
              f"else echo DONE; cat {logs}/{job['id']}.exit 2>/dev/null; fi; echo ---TAIL---; "
              f"tail -n 25 {logs}/{job['id']}.log 2>/dev/null")
    code, out = _run(["sh", "-c", script], 30) if s["host"] == "local" else _ssh(s, script, 40)
    if code != 0 and "---TAIL---" not in out:
        return None
    head, _, tail = out.partition("---TAIL---")
    words = head.split()
    alive = bool(words) and words[0] == "ALIVE"
    ex = int(words[1]) if not alive and len(words) > 1 and words[1].lstrip("-").isdigit() else None
    return {"alive": alive, "exit": ex if not alive else None, "tail": tail.strip()[-2000:]}


def _kill(root: Path, s: dict, job: dict) -> None:
    pid = int(job["pid"])     # its whole session (setsid made it a group): the training, not only its shell
    script = f"kill -TERM -{pid} 2>/dev/null || kill -TERM {pid} 2>/dev/null; true"
    _run(["sh", "-c", script], 20) if s["host"] == "local" else _ssh(s, script, 30)


def _fetch(root: Path, s: dict, paths: List[str]) -> Tuple[bool, str]:
    """The job's results files back into the repository."""
    dest = remote_dir(root, s)
    if s["host"] == "local" and dest == str(root):
        return True, ""
    bad = []
    for p in paths:
        local = root / p
        local.parent.mkdir(parents=True, exist_ok=True)
        if s["host"] == "local":
            try:
                shutil.copyfile(Path(dest) / p, local)
            except OSError as exc:
                bad.append(f"{p}: {exc}")
        else:
            ssh = " ".join(shlex.quote(a) for a in SSH + (["-p", str(s["port"])] if s.get("port") else []))
            code, out = _run(["rsync", "-az", "-e", ssh, f"{s['host']}:{dest}/{p}", str(local)], 300)
            if code != 0:
                bad.append(f"{p}: {out.strip()[-120:]}")
    return not bad, "; ".join(bad)


# ── the campaign ───────────────────────────────────────────────────────────────────────────────────────────────────

def start(root: Path, goal: str, target: str = "", max_iterations: int = 5, server_names: Optional[List[str]] = None,
          experiments: Optional[List[str]] = None) -> dict:
    """Start a campaign (a running one is replaced only when stopped first). `experiments`: the first iteration's;
    none: Claude plans the first iteration from the goal."""
    c = campaign(root)
    if c.get("state") in ACTIVE:
        raise ValueError("auto-research is already on: pause, resume or stop it first")
    names = [s["name"] for s in servers(root)]
    use = [n for n in (server_names or names) if n in names]
    if not use:
        raise ValueError("add a server first (local, or an SSH host): research-diff auto server add NAME HOST")
    if target:
        from .extract import EXPECT_RX
        if not EXPECT_RX.match(target.strip()):
            raise ValueError("target: RESULT METRIC > NUMBER, e.g. E2.results acc.batch512 > 0.88")
    c = {"id": secrets.token_hex(4), "goal": goal.strip(), "target": target.strip(),
         "max_iterations": max(1, int(max_iterations)), "servers": use, "state": "running", "created": time.time(),
         "iterations": [], "jobs": {}, "events": []}
    log(root, c, f"started: {goal}")
    if experiments:
        submit(root, experiments=[{"experiment": e} for e in experiments], reason="the first iteration, as asked",
               c=c)
    else:
        c["ask"] = "plan"                 # Claude plans the first iteration
    _save(root, c)
    ensure_runner(root)
    handoff(root)
    return c


def control(root: Path, what: str) -> dict:
    """pause | resume | stop."""
    c = campaign(root)
    if not c:
        raise ValueError("no auto-research to " + what)
    if what == "pause" and c["state"] == "running":
        c["state"] = "paused"
        log(root, c, "paused: no new launches; running jobs go on")
    elif what == "resume" and c["state"] == "paused":
        c["state"] = "running"
        log(root, c, "resumed")
    elif what == "stop" and c["state"] in ACTIVE:
        c["state"] = "stopping"
        log(root, c, "stopping: running jobs are killed")
    else:
        raise ValueError(f"auto-research is {c['state']}: cannot {what}")
    _save(root, c)
    if what == "resume":
        ensure_runner(root)
    elif what == "stop":
        c = tick(root)                     # kill now, not at the runner's next look
    return c


def _command_of(bp: dict, exp: str) -> Tuple[str, List[str]]:
    n = bp["nodes"].get(exp, {})
    results = [r["files"][0] for k, r in bp["nodes"].items() if k == f"{exp}.results" and r["files"]]
    return n.get("run", ""), results


def submit(root: Path, experiments: List[dict], reason: str, analysis: str = "", c: Optional[dict] = None) -> dict:
    """The next iteration: [{"experiment": "E2", "command"?: override, "gpus"?: 1, "server"?: name}], with what was
    changed and why (`reason`) and what the last iteration showed (`analysis`)."""
    from . import compare
    own = c is None
    c = c if c is not None else campaign(root)
    if c.get("state") not in ACTIVE:
        raise ValueError("auto-research is not on")
    if c["iterations"] and c["iterations"][-1]["state"] == "running":
        raise ValueError("the current iteration is still running: wait for it to end")
    if len(c["iterations"]) >= c["max_iterations"]:
        raise ValueError(f"the budget of {c['max_iterations']} iterations is spent")
    bp = compare.read(root, ".")[0]
    jobs = []
    for e in experiments:
        exp = str(e.get("experiment", "")).strip()
        cmd, results = _command_of(bp, exp)
        cmd = str(e.get("command") or cmd).strip()
        if not cmd:
            raise ValueError(f"{exp or 'an experiment'} has no `run:` command (add one to its research block)")
        jid = f"j{len(c['jobs']) + len(jobs) + 1:03d}"
        jobs.append({"id": jid, "experiment": exp, "command": cmd, "results": e.get("results") or results,
                     "want_gpus": max(0, int(e.get("gpus", 1))), "server": e.get("server", ""), "state": "queued",
                     "gpus": [], "pid": None, "exit": None, "tail": "", "why": ""})
    if not jobs:
        raise ValueError("an iteration runs at least one experiment")
    if c["iterations"] and c["iterations"][-1]["state"] == "analyse":
        c["iterations"][-1].update(state="analysed", analysis=analysis.strip()[:2000])
    n = len(c["iterations"]) + 1
    c["iterations"].append({"n": n, "reason": reason.strip()[:2000], "analysis": "", "jobs": [j["id"] for j in jobs],
                            "state": "running", "started": time.time(), "ended": None, "told": False})
    for j in jobs:
        c["jobs"][j["id"]] = j
    c.pop("ask", None)
    log(root, c, f"iteration {n}: " + ", ".join(f"{j['experiment']}" for j in jobs) + (f" ({reason[:120]})" if reason else ""))
    if own:
        _save(root, c)
        ensure_runner(root)
    return c


def finish(root: Path, summary: str) -> dict:
    """Claude ends the campaign: the goal is met, or it cannot be from here (say which, and why)."""
    c = campaign(root)
    if c.get("state") not in ACTIVE:
        raise ValueError("auto-research is not on")
    c["state"] = "done"
    c["summary"] = summary.strip()[:2000]
    if c["iterations"] and c["iterations"][-1]["state"] == "analyse":
        c["iterations"][-1]["state"] = "analysed"
    log(root, c, "done: " + summary[:200])
    _save(root, c)
    return c


def _free_gpus(c: dict, s: dict) -> List[int]:
    busy = {g for j in c["jobs"].values() if j["server"] == s["name"] and j["state"] in ("running",) for g in j["gpus"]}
    return [g for g in s["gpus"] if g not in busy]


def _cpu_busy(c: dict, s: dict) -> bool:
    return any(j["server"] == s["name"] and j["state"] == "running" and not j["gpus"] for j in c["jobs"].values())


def target_met(root: Path, c: dict) -> Optional[bool]:
    if not c.get("target"):
        return None
    from . import compare
    from .extract import check_expect
    bp = compare.read(root, ".")[0]
    return not check_expect("target", c["target"], bp["nodes"])


def tick(root: Path) -> dict:
    """One look of the runner: collect what ended, launch what can start, move the iteration on. Never raises."""
    c = campaign(root)
    if not c or c.get("state") in ("stopped", "done", None):
        return c
    by_name = {s["name"]: s for s in servers(root)}
    try:
        for j in c["jobs"].values():
            if j["state"] != "running":
                continue
            s = by_name.get(j["server"])
            if s is None:
                j.update(state="failed", why=f"server {j['server']} was removed")
                continue
            if c["state"] == "stopping":
                _kill(root, s, j)
                j.update(state="killed", ended=time.time())
                continue
            got = _poll(root, s, j)
            if got is None:
                j["why"] = "the server cannot be reached now: checked again later"
                continue
            j["tail"] = got["tail"]
            if not got["alive"]:
                ok, why = _fetch(root, s, j["results"]) if got["exit"] == 0 else (False, "")
                j.update(state="done" if got["exit"] == 0 and ok else "failed", exit=got["exit"], ended=time.time(),
                         why=why if got["exit"] == 0 else f"exited {got['exit']}")
                log(root, c, f"{j['id']} {j['experiment']} on {j['server']}: {j['state']}"
                    + (f" ({j['why']})" if j["why"] else ""))
        if c["state"] == "stopping":
            for j in c["jobs"].values():
                if j["state"] == "queued":
                    j["state"] = "killed"
            c["state"] = "stopped"
            log(root, c, "stopped")
            _save(root, c)
            return c
        if c["state"] == "running":
            synced: set = set()
            for j in c["jobs"].values():
                if j["state"] != "queued":
                    continue
                for name in ([j["server"]] if j["server"] else c["servers"]):
                    s = by_name.get(name)
                    if s is None:
                        continue
                    free = _free_gpus(c, s)
                    want = j["want_gpus"] if s["gpus"] else 0      # a server with no GPUs: a CPU job
                    if want and len(free) < want:
                        j["why"] = "waiting for a free GPU"
                        continue
                    if not want and _cpu_busy(c, s):
                        j["why"] = "waiting for the CPU job before it"
                        continue
                    if name not in synced:
                        ok, why = _sync_up(root, s)
                        if not ok:
                            j["why"] = f"copying the code to {name} failed: {why}"
                            continue
                        synced.add(name)
                    j.update(server=name, gpus=free[:want])
                    pid, why = _launch(root, s, j)
                    if pid:
                        j.update(state="running", pid=pid, started=time.time(), why="")
                        log(root, c, f"{j['id']} {j['experiment']} launched on {name}"
                            + (f" GPU {','.join(map(str, j['gpus']))}" if j["gpus"] else ""))
                    else:
                        j.update(state="failed", why=f"launch on {name} failed: {why}")
                    break
        it = c["iterations"][-1] if c["iterations"] else None
        if it and it["state"] == "running" and all(c["jobs"][k]["state"] in ("done", "failed", "killed")
                                                    for k in it["jobs"]):
            it.update(state="analyse", ended=time.time())
            met = target_met(root, c)
            if met:
                c["state"] = "done"
                c["summary"] = f"the target holds: {c['target']}"
                it["state"] = "analysed"
                log(root, c, f"iteration {it['n']} ended: the target holds ({c['target']})")
            elif len(c["iterations"]) >= c["max_iterations"]:
                log(root, c, f"iteration {it['n']} ended: the budget is spent; one last analysis")
            else:
                log(root, c, f"iteration {it['n']} ended: Claude analyses it and improves the experiments")
    except Exception as exc:  # noqa: BLE001 - the runner goes on: what failed is on the page
        log(root, c, f"runner: {type(exc).__name__}: {str(exc)[:200]}")
    _save(root, c)
    return c


def handoff(root: Path) -> bool:
    """Merged into system-diff: hand a waiting ask to the session through system-diff's pane, once."""
    from . import host
    ask = untold(root)
    if not ask or not host.merged() or not host.deliver(root, ask):
        return False
    told(root)
    return True


def pending(root: Path) -> Optional[str]:
    """What the session should do now, as a prompt; None when nothing waits for Claude."""
    c = campaign(root)
    if c.get("state") != "running":
        return None
    goal = f"Auto-research goal: {c['goal']}" + (f" (target: {c['target']})" if c.get("target") else "")
    left = c["max_iterations"] - len(c["iterations"])
    if c.get("ask") == "plan":
        return (f"{goal}. Plan the first iteration: read the research map and the paper (research_evidence, "
                "paper_outline), make the changes the experiments need, then call autoresearch_submit with the "
                f"experiments to run and why. Budget: {left} iterations.")
    it = c["iterations"][-1] if c["iterations"] else None
    if not it or it["state"] != "analyse":
        return None
    jobs = [c["jobs"][k] for k in it["jobs"]]
    said = "; ".join(f"{j['experiment']} {j['state']}" + (f" ({j['why']})" if j["why"] else "") for j in jobs)
    tail = "\n".join(f"--- {j['id']} {j['experiment']} (last lines of its log):\n{j['tail'][-600:]}"
                     for j in jobs if j["state"] == "failed" and j["tail"])
    last = left <= 0
    return (f"{goal}. Iteration {it['n']} ended: {said}. Call research_diff (base turn or checkpoint) and "
            "research_evidence to see what the results changed: numbers, verdicts, contradictions, the paper's "
            "number checks. " + ("The budget is spent: call autoresearch_finish with what was found."
                                 if last else
                                 "Then improve the experiments (configs, code, the next settings to try) and call "
                                 "autoresearch_submit with your analysis of this iteration, what you changed and "
                                 "why, and the experiments to run next; or autoresearch_finish when the goal is met "
                                 "or cannot be.") + (f"\n{tail}" if tail else ""))


def nudge(root: Path, most: int = 2) -> Optional[str]:
    """For the Stop hook: the ask, when one waits and Claude has not been held on it `most` times for this iteration
    already (then the turn may end: the pane, or the next session, asks again)."""
    ask = pending(root)
    if not ask:
        return None
    c = campaign(root)
    key = f"{len(c['iterations'])}-{c.get('ask', '')}"
    held = c.setdefault("held", {})
    if held.get(key, 0) >= most:
        return None
    held[key] = held.get(key, 0) + 1
    _save(root, c)
    told(root)
    return ask


def told(root: Path) -> None:
    """The pending ask reached the session (it is not handed again)."""
    c = campaign(root)
    if c.get("iterations") and c["iterations"][-1]["state"] == "analyse":
        c["iterations"][-1]["told"] = True
    if c.get("ask") == "plan":
        c["ask_told"] = True
    _save(root, c)


def untold(root: Path) -> Optional[str]:
    """The pending ask, if it has not been handed to a session yet (for the pane to submit, once)."""
    c = campaign(root)
    it = c["iterations"][-1] if c.get("iterations") else None
    if (c.get("ask") == "plan" and not c.get("ask_told")) or (it and it["state"] == "analyse" and not it["told"]):
        return pending(root)
    return None


# ── the runner process ─────────────────────────────────────────────────────────────────────────────────────────────

def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def runner_alive(root: Path) -> bool:
    got = _read(root, "runner.json", {})
    return bool(got) and _alive(int(got.get("pid", 0))) and time.time() - got.get("beat", 0) < 5 * TICK + 30


def ensure_runner(root: Path) -> bool:
    """Start the runner (detached) when a campaign is on and none runs. Cheap; never raises."""
    try:
        if campaign(root).get("state") not in ("running", "paused", "stopping") or runner_alive(root):
            return False
        if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get("RESEARCH_DIFF_RUNNER"):
            return False
        flags = {"start_new_session": True} if os.name != "nt" else {"creationflags": 0x08000000 | 0x00000200}
        subprocess.Popen([sys.executable, "-m", "research_diff", "--repo", str(root), "auto", "runner"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         cwd=str(root), **flags)
        return True
    except Exception:  # noqa: BLE001
        return False


def run_forever(root: Path, every: float = TICK) -> None:
    """The runner: a look every few seconds while the campaign is on; gone once it is stopped or done."""
    if runner_alive(root):
        return
    stop = {"now": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(now=True))
    while not stop["now"]:
        _write(root, "runner.json", {"pid": os.getpid(), "beat": time.time()})
        c = tick(root)
        handoff(root)
        if not c or c.get("state") in ("stopped", "done"):
            break
        time.sleep(every)
    try:
        (_home(root) / "runner.json").unlink()
    except OSError:
        pass


def status(root: Path) -> dict:
    c = campaign(root)
    return {"campaign": c, "servers": servers(root), "runner": runner_alive(root), "pending": pending(root)}


def as_text(root: Path) -> str:
    c = campaign(root)
    if not c:
        return ("Auto-research is off. Add a server (research-diff auto server add NAME local|HOST --gpus 0,1) and "
                "start it: research-diff auto start \"GOAL\" [--target 'E1.results acc > 0.9'].")
    out = [f"Auto-research {c['state']}: {c['goal']}" + (f"  (target {c['target']})" if c.get("target") else ""),
           f"  iterations {len(c['iterations'])}/{c['max_iterations']} · servers {', '.join(c['servers'])} · runner "
           f"{'on' if runner_alive(root) else 'off'}"]
    for it in c["iterations"]:
        out.append(f"\n  iteration {it['n']} [{it['state']}]" + (f": {it['reason']}" if it["reason"] else ""))
        if it.get("analysis"):
            out.append(f"    analysis: {it['analysis']}")
        for k in it["jobs"]:
            j = c["jobs"][k]
            out.append(f"    {j['id']} {j['experiment']:<6} {j['state']:<8} {j['server'] or '-'}"
                       + (f" GPU {','.join(map(str, j['gpus']))}" if j["gpus"] else "") + (f"  {j['why']}" if j["why"] else ""))
    if c.get("summary"):
        out.append(f"\n  {c['summary']}")
    return "\n".join(out)


# ── the web page's controls (research-diff's own page, and system-diff's under /x/research/auto) ───────────────────

def web_status(root: Path, config_path: Optional[str] = None) -> dict:
    from . import compare
    st = status(root)
    bp = compare.read(root, ".", config_path)[0]
    c = st["campaign"]
    it = c["iterations"][-1] if c.get("iterations") else {}
    return {**st, "pending_told": bool(it.get("told") or c.get("ask_told")),
            "experiments": [{"id": k, "title": n["title"], "run": n.get("run", "")} for k, n in bp["nodes"].items()
                            if n["kind"] == "experiment"]}


def web_action(root: Path, action: str, d: dict) -> dict:
    """server | server/remove | server/check | start | control, with the page's form as `d`."""
    if action == "server":
        gpus = d.get("gpus", [])
        gpus = [int(g) for g in (gpus.split(",") if isinstance(gpus, str) else gpus) if str(g).strip()]
        return save_server(root, str(d.get("name", "")), str(d.get("host", "")), str(d.get("workdir", "")), gpus,
                           str(d.get("setup", "")), int(d.get("port") or 0))
    if action == "server/remove":
        return {"removed": remove_server(root, str(d.get("name", "")))}
    if action == "server/check":
        s = next((x for x in servers(root) if x["name"] == d.get("name")), None)
        if s is None:
            raise ValueError("no such server")
        return check_server(root, s)
    if action == "start":
        c = start(root, str(d.get("goal", "")), str(d.get("target", "")), int(d.get("max_iterations") or 5),
                  list(d.get("servers") or []) or None, list(d.get("experiments") or []) or None)
        return {"state": c["state"]}
    if action == "control":
        return {"state": control(root, str(d.get("action", "")))["state"]}
    raise ValueError("unknown action")
