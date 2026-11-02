"""research-diff: your research as a map (questions, hypotheses, experiments, results, claims), and what each iteration
changed in it.

    research-diff map  [--at REF|.] [--out DIR] [--check]           -> research.json, research.svg
    research-diff diff [--base checkpoint|REF] [--head .|REF] [--out DIR]
                                                                    -> diff.json, diff.svg, plan.txt, headline.txt
    research-diff sync                                              -> MLflow / W&B runs into research/runs.json
    research-diff suggest [FILE...]                                 -> your LLM proposes markers, as a patch
    research-diff checkpoint [--ref REF]                            -> mark what you have understood
    research-diff watch [--port 8766]                               -> a live page of the diff since then
    research-diff readme [--check]                                  -> the README's generated research map
    research-diff setup claude [--scope user|project|local] [--undo] -> the hook, a skill and the MCP server
    research-diff hook | mcp                                        -> what Claude Code runs

`.` is the working tree, untracked files included, read without touching your index, HEAD or branches.
`checkpoint` is what you last marked as understood (HEAD until you mark something).
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
    return 0


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
    d = sub.add_parser("diff", help="what an iteration changed")
    d.add_argument("--base", default="checkpoint", help="a commit, or checkpoint (default)")
    d.add_argument("--head", default=".", help="a commit, or . for the working tree (default)")
    d.add_argument("--out", default=".")
    sub.add_parser("sync", help="copy MLflow and W&B runs tagged with an experiment id into research/runs.json")
    sg = sub.add_parser("suggest", help="your LLM proposes markers for untagged files, as a patch you apply or not")
    sg.add_argument("files", nargs="*", help="files to read (default: notes and paper files with no marker)")
    sg.add_argument("--out", default="", help="where to write the patch (default .git/research-diff/suggest.patch)")
    c = sub.add_parser("checkpoint", help="mark what you have understood")
    c.add_argument("--ref", help="a commit to mark instead of the working tree")
    w = sub.add_parser("watch", help="a live local page of the diff since the checkpoint")
    w.add_argument("--base", default="checkpoint")
    w.add_argument("--port", type=int, default=8766)
    w.add_argument("--interval", type=float, default=2.0)
    r = sub.add_parser("readme", help="rewrite the README's research-map section")
    r.add_argument("--check", action="store_true")
    st = sub.add_parser("setup", help="wire research-diff into an AI coding tool")
    st.add_argument("tool", choices=["claude"])
    st.add_argument("--scope", default="user", choices=["user", "project", "local"])
    st.add_argument("--undo", action="store_true")
    sub.add_parser("hook", help="what Claude Code's Stop hook runs")
    sub.add_parser("mcp", help="the MCP server over stdio (needs the [mcp] extra)")
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    args = parser().parse_args(argv)
    root = repo_root(Path(args.repo) if args.repo else None)
    if args.cmd == "map":
        return _map(args, root)
    if args.cmd == "diff":
        return _diff(args, root)
    if args.cmd == "sync":
        got = compare.sync_trackers(root, args.config)
        print(f"{got['runs']} tracker runs" + (" written to research/runs.json" if got["written"] else ", nothing changed"))
        return 0
    if args.cmd == "suggest":
        from . import suggest
        return suggest.run(root, args.files, args.out, args.config)
    if args.cmd == "checkpoint":
        sha = compare.checkpoint(root, args.ref)
        print(f"checkpoint: {args.ref or 'the working tree'} ({sha[:9]}) is what you have understood")
        return 0
    if args.cmd == "readme":
        return readme.run(root, args.config, args.check)
    if args.cmd == "watch":
        from . import watch
        watch.serve(root, args.base, args.port, args.config, args.interval)
        return 0
    if args.cmd == "setup":
        from . import agent
        return agent.setup_claude(root, args.scope, args.undo)
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
