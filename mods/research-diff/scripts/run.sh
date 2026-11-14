#!/bin/sh
# Runs `research-diff <args>` for the plugin's hooks and MCP server: the project's own virtualenv first (a project that
# develops research-diff, or pins it), then research-diff on PATH (pip or pipx), then any Python that has it. Where none
# is installed it does nothing and succeeds, so a session in a project without research-diff is never held up.
dir="${CLAUDE_PROJECT_DIR:-$PWD}"
for py in "$dir/.venv/bin/python" "$dir/.venv/Scripts/python.exe"; do
  if [ -x "$py" ] && "$py" -c "import research_diff" >/dev/null 2>&1; then exec "$py" -m research_diff "$@"; fi
done
if command -v research-diff >/dev/null 2>&1; then exec research-diff "$@"; fi
for py in python3 python py; do
  if command -v "$py" >/dev/null 2>&1 && "$py" -c "import research_diff" >/dev/null 2>&1; then exec "$py" -m research_diff "$@"; fi
done
if [ "$1" = "hook" ]; then cat >/dev/null; exit 0; fi   # a hook's input, read and let go: the session goes on
# anything else (the MCP server, the pane) is told, and fails, so the pane tries its other ways
echo 'research-diff: not found by the launcher: pip install "research-diff[mcp]"' >&2
exit 127
