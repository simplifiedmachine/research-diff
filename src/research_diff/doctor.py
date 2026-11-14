"""`research-diff doctor`: why research-diff is quiet, slow or wrong here. It times one read of the research, counts
what each kind of file gives, and checks the wiring: the hooks, the status line, the MCP server, the plugin, the web
page, the LLM and the trackers. It changes nothing. Paste its output into an issue, or to Claude.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import List

from . import __version__, compare, config, page, store
from .extract import glob_rx


def report(root: Path, config_path: str = "") -> List[str]:
    out = [f"research-diff {__version__} · Python {platform.python_version()} · {platform.system()} {platform.release()}",
           f"repository: {root}"]
    try:
        import system_diff
        out.append(f"system-diff {getattr(system_diff, '__version__', '?')} (pictures, git reading)")
    except ImportError:
        out.append("✗ system-diff is not installed: pip install system-diff")
    t = time.time()
    try:
        bp, cfg, label = compare.read(root, ".", config_path or None)
    except Exception as exc:  # noqa: BLE001
        out.append(f"✗ reading the research failed: {type(exc).__name__}: {exc}")
        return out
    took = time.time() - t
    out.append(f"{'✓' if took < 2 else '!'} one read of the working tree: {took:.2f}s")
    files = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=root, capture_output=True,
                           text=True).stdout.splitlines()
    for key in ("notes", "configs", "scripts", "paper"):
        hit = [f for f in files if any(glob_rx(g).match(f) for g in cfg[key])]
        with_marker = {f for n in bp["nodes"].values() for f in n["files"]} & set(hit)
        out.append(f"  {key:8} {len(hit):4} files match {cfg[key]}, {len(with_marker)} with markers")
    kinds = {}
    for n in bp["nodes"].values():
        kinds[n["kind"]] = kinds.get(n["kind"], 0) + 1
    from .diff import PLURAL
    out.append("  nodes: " + (", ".join(f"{v} {k if v == 1 else PLURAL.get(k, k + 's')}" for k, v in kinds.items()) or "none: write a marker, or run "
                              "`research-diff suggest`"))
    from . import evidence
    g = evidence.build(bp, cfg)
    out.append(f"  evidence: {g['headline']}")
    found = next((n for n in (config.FILE, "pyproject.toml") if (root / n).is_file()), "")
    out.append(f"  config: {config_path or found or 'defaults (no research-diff.toml)'}")
    home = Path.home() / ".claude"
    for scope, path in (("user", home / "settings.json"), ("project", root / ".claude" / "settings.json"),
                        ("local", root / ".claude" / "settings.local.json")):
        try:
            s = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        events = sorted(k for k, v in s.get("hooks", {}).items() if "research" in json.dumps(v))
        if events:
            out.append(f"✓ hooks ({scope}): {', '.join(events)}")
        if "research" in json.dumps(s.get("statusLine", {})):
            out.append(f"✓ status line ({scope})")
    plugin = list((home / "plugins").glob("**/research-diff/**/register.tsx")) if (home / "plugins").is_dir() else []
    out.append("✓ the pane plugin is installed" if plugin else
               "· the pane plugin is not installed (/plugin marketplace add simplifiedmachine/research-diff)")
    if shutil.which("claude"):
        got = subprocess.run(["claude", "mcp", "get", "research-diff"], capture_output=True, text=True)
        out.append("✓ MCP server registered" if got.returncode == 0 else "· MCP server not registered "
                   "(research-diff setup claude)")
    else:
        out.append("· `claude` is not on PATH")
    try:
        import mcp  # noqa: F401
        out.append("✓ the [mcp] extra is installed")
    except ImportError:
        out.append('· the [mcp] extra is not installed: pip install "research-diff[mcp]"')
    url = page.web_url(root)
    out.append(f"✓ web page: {url}" if url else "· the web page is not running (research-diff watch)")
    acts = store.lines(root, "activity.jsonl", 5)
    out.append(f"✓ the hooks recorded {len(acts)}+ events, last {time.ctime(acts[-1]['at'])}" if acts
               else "· the hooks have recorded nothing yet")
    try:
        from system_diff.narrate import configured
        llm = configured(root)
    except Exception:  # noqa: BLE001
        llm = False
    off = os.environ.get("RESEARCH_DIFF_LLM", "") == "off"
    out.append("· LLM features off (RESEARCH_DIFF_LLM=off)" if off else
               "✓ an LLM is reachable for objectives, suggest and narrate" if llm else
               "· no LLM found for objectives, suggest and narrate (optional)")
    for name, folder in cfg["trackers"].items():
        if (root / folder).is_dir():
            out.append(f"✓ {name} runs in {folder}/ (research-diff sync)")
    for w in bp["warnings"][:5]:
        out.append(f"  warning: {w}")
    out.append(f"python: {sys.executable}")
    return out


def main(root: Path, config_path: str = "") -> int:
    print("\n".join(report(root, config_path)))
    return 0
