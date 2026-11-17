"""research-diff: your research as a map (questions, hypotheses, experiments, results, findings, claims), the evidence
graph of what supports and what contradicts each claim of the paper, and what each iteration changed.

    research-diff map  [--at REF|.] [--out DIR] [--check]            -> research.json, research.svg
    research-diff evidence [--at REF|.] [--out DIR] [--check]        -> evidence.svg, .html, .mmd, .json, .md
    research-diff diff [--base checkpoint|turn|REF] [--head .|REF] [--out DIR] [--narrate]
                                                                     -> diff.json, diff.svg, plan.txt, headline.txt
    research-diff show [ID] [--view now|review|evidence|agents|history]  -> the pane's views, in any terminal
    research-diff tui                                                -> the same, live, in a terminal of its own
    research-diff watch                                              -> the same, live, in a browser
    research-diff hub                                                -> one address for every project, both tools
    research-diff outline FILE [--summarize]                         -> a paper or notes file, section by section
    research-diff review [--patch]                                   -> your LLM reads the paper against itself
    research-diff history [--node ID] [--commits N]                  -> what you asked, what the research got
    research-diff history compare A B                                -> what changed between two points of it
    research-diff auto [start GOAL|pause|resume|stop|server add NAME HOST|server check NAME] -> auto-research
    research-diff agents [plan TASK|claim NAME IDS|publish NAME TOPIC TEXT|inbox NAME|release NAME]
    research-diff objectives [add TEXT|clear ID|restore ID|learn]    -> what you optimise the study for
    research-diff comment [--base REF]                               -> a pull request's research diff, in Markdown
    research-diff sync                                               -> MLflow / W&B runs into research/runs.json
    research-diff suggest [FILE...] [--links]                        -> your LLM proposes markers or links, as a patch
    research-diff checkpoint [--ref REF]                             -> mark what you have understood
    research-diff readme [--check]                                   -> the README's generated research section
    research-diff doctor                                             -> why it is quiet, slow or wrong here
    research-diff setup claude [--scope user|project|local] [--undo] -> hooks, status line, skill, MCP server
    research-diff hook | mcp | panel | statusline                    -> what Claude Code runs

`.` is the working tree, untracked files included, read without touching your index, HEAD or branches.
`checkpoint` is what you last marked as understood (HEAD until you mark something); `turn`, the working tree as it was
when you last sent your agent a prompt.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from system_diff.pictures import write_if_changed
from system_diff.sources import repo_root

from . import __version__, compare, graph, readme
from .diff import PLURAL


def _write(path: Path, text: str, check: bool) -> bool:
    if check:
        return not path.is_file() or path.read_text(encoding="utf-8") != text
    write_if_changed(path, text)
    return False


def _map(args, root: Path) -> int:
    bp, cfg, label = compare.read(root, args.at, args.config)
    out = Path(args.out)
    if not args.check:
        out.mkdir(parents=True, exist_ok=True)
    stale = _write(out / "research.json", json.dumps(bp, indent=1, ensure_ascii=False) + "\n", args.check)
    stale |= _write(out / "research.svg", graph.map_svg(bp, cfg), args.check)
    if args.check:
        print(f"research map {'is out of date' if stale else 'is current'}: {out}/research.svg")
        return 1 if stale else 0
    kinds = {}
    for n in bp["nodes"].values():
        kinds[n["kind"]] = kinds.get(n["kind"], 0) + 1
    print(f"research map of {label}: " + ", ".join(f"{v} {k if v == 1 else PLURAL.get(k, k + 's')}" for k, v in kinds.items())
          + f", {len(bp['warnings'])} warnings -> {out}/research.svg")
    return 0


def _evidence(args, root: Path) -> int:
    from . import evgraph, evidence
    g, _bp, _cfg = compare.evidence_of(root, args.at, args.config)
    out = Path(args.out)
    if not args.check:
        out.mkdir(parents=True, exist_ok=True)
    files = {"evidence.svg": evgraph.svg(g), "evidence.html": evgraph.standalone(g), "evidence.mmd": evgraph.mermaid(g),
             "evidence.json": json.dumps(g, indent=1, ensure_ascii=False) + "\n",
             "evidence.md": evidence.to_markdown(g) + "\n"}
    stale = False
    for name, text in files.items():
        stale |= _write(out / name, text, args.check)
    if args.check:
        print(f"evidence graph {'is out of date' if stale else 'is current'}: {out}/evidence.svg")
        return 1 if stale else 0
    print(g["headline"])
    for s in g["statements"]:
        if s["verdict"] in ("contradicted", "contested"):
            print(f"  {s['verdict']:12} {s['id']}: " + "; ".join(x["why"] for x in s["against"]))
    print(f"-> {out}/evidence.svg, evidence.html (interactive), evidence.mmd (Mermaid), evidence.md")
    return 1 if args.strict and any(s["verdict"] in ("contradicted", "contested") for s in g["statements"]) else 0


def _diff(args, root: Path) -> int:
    c = compare.compare(root, args.base, args.head, args.config)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, text in (("diff.json", json.dumps(c.diff, indent=1, ensure_ascii=False)), ("plan.txt", c.diff["plan"]),
                       ("headline.txt", c.diff["headline"])):
        (out / name).write_text(text + "\n", encoding="utf-8", newline="\n")
    svg = graph.diff_svg(c.diff, c.before, c.after, c.cfg)
    if svg:
        write_if_changed(out / "diff.svg", svg)
    elif (out / "diff.svg").is_file():
        (out / "diff.svg").unlink()
    print(c.diff["headline"])
    if args.narrate:
        from . import narrate
        said = narrate.narrate(root, c)
        if said:
            (out / "summary.md").write_text(said + "\n", encoding="utf-8", newline="\n")
            print("\n" + said)
        else:
            print("\n(no LLM answered: no summary)")
    return 0


def _comment(args, root: Path) -> int:
    from . import evgraph, evidence, rank
    c = compare.compare(root, args.base, args.head, args.config)
    g_before = evidence.build(c.before, c.cfg)
    g = evidence.build(c.after, c.cfg)
    worth = rank.worth_a_look(c.diff, c.after, 6)
    lines = ["<!-- research-diff -->", "### Research diff", "", f"**{c.diff['headline']}**", ""]
    if worth:
        lines += ["**Worth a look**", ""] + [f"{i}. **{w['title']}**" + (f" — {w['why']}" if w["why"] else "")
                                            for i, w in enumerate(worth, 1)] + [""]
    lines += ["### Evidence", "", evidence.to_markdown(g), ""]
    if g_before["headline"] != g["headline"]:
        lines += [f"Before: {g_before['headline']}", ""]
    lines += ["<details><summary>The evidence graph</summary>", "", "```mermaid", evgraph.mermaid(g).rstrip(), "```",
              "", "</details>", "", "<details><summary>The exact plan</summary>", "", "```", c.diff["plan"], "```", "",
              "</details>"]
    text = "\n".join(lines) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(text)
    return 0


def _agents(args, root: Path) -> int:
    from . import agents
    a = args.rest
    if a and a[0] == "plan":
        g, bp, _ = compare.evidence_of(root, ".", args.config)
        got = agents.plan(root, " ".join(a[1:]) or "the study", bp, g, args.by)
        for x in got["agents"]:
            print(f"── {x['name']}\n{x['brief']}\n")
        return 0
    if a and a[0] == "claim" and len(a) >= 3:
        bp, _cfg, _ = compare.read(root, ".", args.config)
        print(json.dumps(agents.claim(root, a[1], a[2:], bp=bp)))
        return 0
    if a and a[0] == "release" and len(a) >= 2:
        print("released " + ", ".join(agents.release(root, a[1], a[2:] or None)))
        return 0
    if a and a[0] == "publish" and len(a) >= 4:
        print(f"message {agents.publish(root, a[1], a[2], ' '.join(a[3:]))}")
        return 0
    if a and a[0] == "inbox" and len(a) >= 2:
        g, _bp, _ = compare.evidence_of(root, ".", args.config)
        print(agents.as_context(agents.inbox(root, a[1], g)) or "no unread messages")
        return 0
    from . import page
    print(page.as_text(page.show(root, "agents", "", 110, config_path=args.config), sys.stdout.isatty()))
    return 0


def _objectives(args, root: Path) -> int:
    from . import objectives
    a = args.rest
    if a and a[0] == "add":
        print(json.dumps(objectives.add(root, " ".join(a[1:]))))
    elif a and a[0] in ("clear", "restore") and len(a) == 2:
        ok = getattr(objectives, a[0])(root, a[1])
        print(f"{a[0]}ed {a[1]}" if ok else f"no objective {a[1]} to {a[0]}")
    elif a and a[0] == "learn":
        got = objectives.learn(root)
        if not args.quiet:
            print("\n".join(f"- {o['text']}" for o in got) or "nothing learned")
    else:
        got = objectives.current(root)
        print("\n".join(f"{o['id']}: {o['text']} ({o['by']}" + (f"; “{o['evidence'][0]}”" if o["evidence"] else "")
                        + ")" for o in got) or "no objectives yet: research-diff objectives add TEXT, or keep "
                                               "asking Claude and they are learned from your requests")
    return 0


def _auto(args, root: Path) -> int:
    from . import autoresearch as ar
    a = args.rest
    try:
        if a[:1] == ["runner"]:
            ar.run_forever(root)
            return 0
        if a[:2] == ["server", "add"] and len(a) == 4:
            gpus = [int(g) for g in args.gpus.split(",") if g.strip()]
            print(json.dumps(ar.save_server(root, a[2], a[3], args.workdir, gpus, args.setup, args.port)))
            return 0
        if a[:2] == ["server", "rm"] and len(a) == 3:
            print("removed" if ar.remove_server(root, a[2]) else f"no server {a[2]}")
            return 0
        if a[:2] == ["server", "check"] and len(a) == 3:
            s = next((x for x in ar.servers(root) if x["name"] == a[2]), None)
            print(json.dumps(ar.check_server(root, s)) if s else f"no server {a[2]}")
            return 0
        if a[:2] == ["server", "list"]:
            print(json.dumps(ar.servers(root), indent=1))
            return 0
        if a[:1] == ["start"] and len(a) >= 2:
            ar.start(root, " ".join(a[1:]), args.target, args.max,
                     [x for x in args.servers.split(",") if x] or None, [x for x in args.exp.split(",") if x] or None)
        elif a[:1] and a[0] in ("pause", "resume", "stop"):
            ar.control(root, a[0])
        elif a and a[0] != "status":
            print("research-diff auto: start GOAL | pause | resume | stop | status | server add NAME HOST", file=sys.stderr)
            return 2
    except ValueError as exc:
        print(f"research-diff auto: {exc}", file=sys.stderr)
        return 1
    print(ar.as_text(root))
    return 0


def store_path(root: Path, name: str) -> Path:
    from . import store
    return store.home(root) / name


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="research-diff", description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog="\n".join(__doc__.split("\n")[2:]))
    ap.add_argument("--version", action="version", version=f"research-diff {__version__}")
    ap.add_argument("--repo", help="the repository (default: the one holding the current directory)")
    ap.add_argument("--config", help="a TOML or JSON config (default: research-diff.toml or [tool.research-diff])")
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("map", help="the research as it is: research.json and research.svg")
    m.add_argument("--at", default=".", help="a commit, or . for the working tree (default)")
    m.add_argument("--out", default=".")
    m.add_argument("--check", action="store_true", help="write nothing; exit 1 if the files are out of date")
    e = sub.add_parser("evidence", help="what supports and what contradicts each claim and finding of the paper")
    e.add_argument("--at", default=".")
    e.add_argument("--out", default=".")
    e.add_argument("--check", action="store_true", help="write nothing; exit 1 if the files are out of date")
    e.add_argument("--strict", action="store_true", help="exit 1 when a statement is contradicted or contested")
    d = sub.add_parser("diff", help="what an iteration changed")
    d.add_argument("--base", default="checkpoint", help="a commit, checkpoint (default), or turn")
    d.add_argument("--head", default=".", help="a commit, or . for the working tree (default)")
    d.add_argument("--out", default=".")
    d.add_argument("--narrate", action="store_true", help="add a plain-words summary from your LLM")
    sh = sub.add_parser("show", help="the pane's views as text: now, review, evidence, agents, history")
    sh.add_argument("part", nargs="?", default="", help="a node to zoom in on")
    sh.add_argument("--view", default="", choices=["", "now", "review", "evidence", "agents", "history"])
    sh.add_argument("--width", type=int, default=0)
    sh.add_argument("--base", default="checkpoint")
    t = sub.add_parser("tui", help="the views, live, in a terminal of their own")
    t.add_argument("--command", action="store_true", help="print how to start it, as JSON (for the pane)")
    pn = sub.add_parser("panel", help="what the pane beside the chat draws, as JSON")
    pn.add_argument("--protocol", type=int, default=2)
    pn.add_argument("--view", default="now")
    pn.add_argument("--part", default="")
    pn.add_argument("--width", type=int, default=100)
    pn.add_argument("--zoom", type=int, default=-1)
    pn.add_argument("--since", type=int, default=-1)
    pn.add_argument("--base", default="checkpoint")
    sub.add_parser("statusline", help="what Claude Code's status line runs")
    h = sub.add_parser("history", help="how the research got here: what you asked, what it got")
    h.add_argument("rest", nargs="*", help="compare A B: two history entries (their ids) or git refs")
    h.add_argument("--node", default="")
    h.add_argument("--commits", type=int, default=0, help="also read the last N commits")
    ag = sub.add_parser("agents", help="a team of agents: plan, claim, publish, inbox, release (no argument: the team)")
    ag.add_argument("rest", nargs="*")
    ag.add_argument("--by", default="section", choices=["section", "hypothesis"])
    ob = sub.add_parser("objectives", help="what you optimise the study for: add, clear, restore, learn")
    ob.add_argument("rest", nargs="*")
    ob.add_argument("--quiet", action="store_true")
    cm = sub.add_parser("comment", help="the research diff and evidence of a branch, as a pull-request comment")
    cm.add_argument("--base", default="origin/main")
    cm.add_argument("--head", default=".")
    cm.add_argument("--out", default="")
    sub.add_parser("sync", help="copy MLflow and W&B runs tagged with an experiment id into research/runs.json")
    sg = sub.add_parser("suggest", help="your LLM proposes markers for untagged files, as a patch you apply or not")
    sg.add_argument("files", nargs="*", help="files to read (default: notes and paper files with no marker)")
    sg.add_argument("--links", action="store_true", help="propose supports/contradicts links between existing nodes")
    sg.add_argument("--out", default="", help="where to write the patch (default .git/research-diff/suggest.patch)")
    c = sub.add_parser("checkpoint", help="mark what you have understood")
    c.add_argument("--ref", help="a commit to mark instead of the working tree")
    w = sub.add_parser("watch", help="a live local page of the views")
    w.add_argument("--base", default="checkpoint")
    w.add_argument("--port", type=int, default=0, help="default: the first free from 8765, shared with system-diff")
    w.add_argument("--interval", type=float, default=2.0)
    w.add_argument("--quiet", action="store_true")
    r = sub.add_parser("readme", help="rewrite the README's research section")
    r.add_argument("--check", action="store_true")
    sub.add_parser("doctor", help="why research-diff is quiet, slow or wrong here")
    sub.add_parser("hub", help="the address that lists every project of system-diff and research-diff")
    au = sub.add_parser("auto", help="auto-research: launch, check, collect and improve experiments on your servers")
    au.add_argument("rest", nargs="*", help="start GOAL | pause | resume | stop | status | runner | "
                                            "server add NAME HOST | server rm NAME | server check NAME | server list")
    au.add_argument("--target", default="", help="when to stop: RESULT METRIC > NUMBER")
    au.add_argument("--max", type=int, default=5, help="the iteration budget")
    au.add_argument("--servers", default="", help="names, comma-separated (default: all)")
    au.add_argument("--exp", default="", help="the first iteration's experiments (default: Claude plans it)")
    au.add_argument("--workdir", default="")
    au.add_argument("--gpus", default="", help="GPU indices, e.g. 0,1,2,3")
    au.add_argument("--setup", default="", help="run before each job, e.g. 'source ~/venv/bin/activate'")
    au.add_argument("--port", type=int, default=0)
    ol = sub.add_parser("outline", help="a paper or notes file, section by section, its numbers checked")
    ol.add_argument("path")
    ol.add_argument("--summarize", action="store_true", help="and your LLM's summary of each section (kept)")
    ol.add_argument("--quiet", action="store_true")
    rv = sub.add_parser("review", help="your LLM reads the paper against itself and its results")
    rv.add_argument("--patch", action="store_true", help="write contradictions between statements as a links patch")
    rv.add_argument("--show", action="store_true", help="the last review, without asking again")
    rv.add_argument("--quiet", action="store_true")
    st = sub.add_parser("setup", help="wire research-diff into an AI coding tool")
    st.add_argument("tool", choices=["claude"])
    st.add_argument("--scope", default="user", choices=["user", "project", "local"])
    st.add_argument("--undo", action="store_true")
    st.add_argument("--no-status-line", action="store_true")
    sub.add_parser("hook", help="what Claude Code's hooks run")
    sub.add_parser("mcp", help="the MCP server over stdio (needs the [mcp] extra)")
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    args = parser().parse_args(argv)
    root = repo_root(Path(args.repo) if args.repo else None)
    if args.cmd == "map":
        return _map(args, root)
    if args.cmd == "evidence":
        return _evidence(args, root)
    if args.cmd == "diff":
        return _diff(args, root)
    if args.cmd == "comment":
        return _comment(args, root)
    if args.cmd in ("show", "panel"):
        from . import page
        if args.cmd == "panel":
            data = page.show(root, args.view, args.part, args.width, args.base, args.config, deliver=True)
            sys.stdout.write(json.dumps(data, ensure_ascii=False))
            return 0
        import shutil
        width = args.width or min(shutil.get_terminal_size((110, 30)).columns, 160)
        view = args.view or ("now" if args.part else "evidence")
        print(page.as_text(page.show(root, view, args.part, width, args.base, args.config), sys.stdout.isatty()))
        return 0
    if args.cmd == "tui":
        if args.command:
            print(json.dumps({"argv": ["research-diff", "tui"], "line": "research-diff tui"}))
            return 0
        from . import tui
        return tui.main(root, args.config)
    if args.cmd == "statusline":
        from . import statusline
        return statusline.main(sys.stdin.read() if not sys.stdin.isatty() else "")
    if args.cmd == "history":
        from . import history
        if args.rest[:1] == ["compare"] and len(args.rest) == 3:
            c = history.compare_points(root, args.rest[1], args.rest[2])
            print(c.diff["headline"] + "\n\n" + c.diff["plan"])
            return 0
        if args.commits:
            history.commits(root, args.commits)
        print(history.text(history.load(root, args.node)))
        return 0
    if args.cmd == "agents":
        return _agents(args, root)
    if args.cmd == "objectives":
        return _objectives(args, root)
    if args.cmd == "auto":
        return _auto(args, root)
    if args.cmd == "hub":
        from . import hub
        port = hub.find_hub()
        print(f"http://localhost:{port}/projects/page" if port else
              "no engine runs: start one with research-diff watch (or open Claude Code with the plugin)")
        return 0
    if args.cmd == "outline":
        from . import paperview
        g, bp, _cfg = compare.evidence_of(root, ".", args.config)
        if args.summarize:
            got = paperview.summarize(root, args.path, bp, g, wait=True)
            if args.quiet:
                return 0 if got["state"] == "done" else 1
            if got["state"] != "done":
                print(f"no summary: {got.get('why', got['state'])}")
        print(paperview.as_text(paperview.outline(root, args.path, bp, g)))
        return 0
    if args.cmd == "review":
        from . import review
        r = review.current(root) if args.show else review.run(root, args.config)
        if not args.quiet:
            print(review.as_text(r))
        if args.patch:
            from . import suggest
            bp = compare.read(root, ".", args.config)[0]
            links = review.links_from(r, bp)
            got = suggest.links(root, lambda _u: json.dumps({"links": links}), args.config) if links else None
            if got and got["patch"]:
                out = store_path(root, "review.patch")
                out.write_text(got["patch"], encoding="utf-8", newline="\n")
                print(f"\nlinks for the contradictions: read {out}, then `git apply {out}`")
        return 0
    if args.cmd == "doctor":
        from . import doctor
        return doctor.main(root, args.config or "")
    if args.cmd == "sync":
        got = compare.sync_trackers(root, args.config)
        print(f"{got['runs']} tracker runs" + (" written to research/runs.json" if got["written"] else ", nothing changed"))
        return 0
    if args.cmd == "suggest":
        from . import suggest
        if args.links:
            return suggest.run_links(root, args.out, args.config)
        return suggest.run(root, args.files, args.out, args.config)
    if args.cmd == "checkpoint":
        sha = compare.checkpoint(root, args.ref)
        print(f"checkpoint: {args.ref or 'the working tree'} ({sha[:9]}) is what you have understood")
        return 0
    if args.cmd == "readme":
        return readme.run(root, args.config, args.check)
    if args.cmd == "watch":
        from . import watch
        watch.serve(root, args.base, args.port, args.config, args.interval, quiet=args.quiet)
        return 0
    if args.cmd == "setup":
        from . import agent
        return agent.setup_claude(root, args.scope, args.undo, status_line=not args.no_status_line)
    if args.cmd == "hook":
        from . import agent
        return agent.run_hook(sys.stdin.read() if not sys.stdin.isatty() else "")
    if args.cmd == "mcp":
        try:
            from . import mcp_server
        except ImportError:
            print('research-diff: the MCP server needs its extra: pip install "research-diff[mcp]"', file=sys.stderr)
            return 1
        mcp_server.main()
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
