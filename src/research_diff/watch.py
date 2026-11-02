"""`research-diff watch`: a live page of what changed in the research since the checkpoint, with Mark as seen.
system-diff's watcher, pointed at the research map: the same page, the same token, one look at a time."""
from __future__ import annotations

import subprocess
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from system_diff import watch as base
from system_diff.compare import worktree_tree

from . import compare, graph


class Watcher(base.Watcher):
    def key(self) -> tuple:
        return worktree_tree(self.root), compare._rev(self.root, compare.CHECKPOINT_REF)

    def refresh(self) -> None:
        try:
            c = compare.compare(self.root, self.base, ".", self.config_path)
            new = {"headline": c.diff["headline"], "plan": c.diff["plan"],
                   "svg": graph.diff_svg(c.diff, c.before, c.after, c.cfg) or "",
                   "changes": len(c.diff["changes"]), "base": c.base, "error": ""}
        except (OSError, subprocess.CalledProcessError, ValueError, KeyError) as exc:
            new = {"error": f"{type(exc).__name__}: {exc}"}
        with self.lock:
            self.state.update(new, version=self.state["version"] + 1, at=time.strftime("%H:%M:%S"))

    def mark_seen(self) -> None:
        with self.busy:
            compare.checkpoint(self.root)
        self.tick(force=True)


PAGE = base.PAGE.replace("<title>System diff</title>", "<title>Research diff</title>").replace(
    "<h1>System diff</h1>", "<h1>Research diff</h1>")


def serve(root: Path, base_point: str = "checkpoint", port: int = 8766, config_path: Optional[str] = None,
          interval: float = 2.0, ready=None) -> None:
    w = Watcher(root, base_point, config_path, interval)
    handler = base.handler(w)
    handler.do_GET_base = handler.do_GET

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self._send(200, PAGE.replace("__TOKEN__", w.token).encode(), "text/html; charset=utf-8")
        return self.do_GET_base()

    handler.do_GET = do_GET
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=w.loop, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    if ready:
        ready(url, server, w)
    else:
        print(f"research-diff watch: {url} (Ctrl-C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        w.stop.set()
        server.server_close()
