"""The paper as a PDF beside its sections: built with pdflatex in the background (with SyncTeX), kept outside the
repository (.git/research-diff-cache/pdf/), built again when a paper file changes, and turned to the page a section
is on (read from SyncTeX's own file: no program started for a click).

Nothing here is required: without pdflatex on the PATH the Paper tab says so and goes on without the PDF.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Dict, List, Tuple

TIMEOUT = 300.0
_LOCK = threading.Lock()
_JOBS: Dict[str, threading.Thread] = {}
_PAGES: Dict[str, tuple] = {}


def _dir(root: Path, main: str) -> Path:
    from . import store
    d = store.home(root).parent / "research-diff-cache" / "pdf" / hashlib.sha1(main.encode()).hexdigest()[:12]
    d.mkdir(parents=True, exist_ok=True)
    return d


def _stamp(root: Path, files: List[str]) -> str:
    h = hashlib.sha1()
    for f in sorted(files):
        try:
            st = os.stat(Path(root) / f)
            h.update(f"{f}:{st.st_size}:{st.st_mtime_ns}\n".encode())
        except OSError:
            h.update(f"{f}:-\n".encode())
    return h.hexdigest()


def find() -> Tuple[str, str]:
    """(program, kind) that builds the PDF: RESEARCH_DIFF_PDFLATEX, else pdflatex on the PATH, else where TeX Live,
    MiKTeX and MacTeX put it, else tectonic; ("", "") when there is none."""
    import glob
    said = os.environ.get("RESEARCH_DIFF_PDFLATEX", "").strip().strip('"')
    if said:
        return (said, "tectonic" if "tectonic" in Path(said).name.lower() else "pdflatex") if Path(said).is_file() \
            else ("", "")
    got = shutil.which("pdflatex")
    if got:
        return got, "pdflatex"
    home, local = os.environ.get("USERPROFILE", ""), os.environ.get("LOCALAPPDATA", "")
    places = [os.path.join(local, "Programs", "MiKTeX", "miktex", "bin", "x64", "pdflatex.exe"),
              os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "MiKTeX", "miktex", "bin", "x64",
                           "pdflatex.exe"),
              os.path.join(home, "AppData", "Local", "Programs", "MiKTeX", "miktex", "bin", "x64", "pdflatex.exe"),
              "/Library/TeX/texbin/pdflatex", "/usr/local/texlive/*/bin/*/pdflatex",
              r"C:\texlive\*\bin\win*\pdflatex.exe", r"C:\texlive\*\bin\windows\pdflatex.exe"]
    for pattern in places:
        for hit in sorted(glob.glob(pattern), reverse=True):
            if os.path.isfile(hit):
                return hit, "pdflatex"
    got = shutil.which("tectonic")
    return (got, "tectonic") if got else ("", "")


def status(root: Path, main: str) -> dict:
    try:
        return json.loads((_dir(root, main) / "status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_status(root: Path, main: str, **st) -> None:
    d = _dir(root, main)
    tmp = d / f".status.{os.getpid()}.tmp"
    tmp.write_text(json.dumps({**st, "at": time.time()}), encoding="utf-8")
    os.replace(tmp, d / "status.json")


def pdf_path(root: Path, main: str) -> Path:
    return _dir(root, main) / (Path(main).stem + ".pdf")


def ensure(root: Path, main: str, files: List[str], done=None) -> dict:
    """Build the PDF in the background unless it is current; the status ({"state": building|ready|failed|missing,
    "why"}) as it is now."""
    root = Path(root)
    exe, kind = find()
    if not exe:
        return {"state": "missing", "why": "No pdflatex found: not on this program's PATH, nor where MiKTeX or TeX Live "
                "install it. Set RESEARCH_DIFF_PDFLATEX to its full path (where.exe pdflatex in PowerShell shows it), "
                "or install tectonic, then start the page again."}
    stamp = _stamp(root, files)
    st = status(root, main)
    if st.get("stamp") == stamp and st.get("state") in ("ready", "failed"):
        return st
    key = f"{root}::{main}"
    with _LOCK:
        t = _JOBS.get(key)
        if t is not None and t.is_alive():
            return {**st, "state": "building"}

        def run() -> None:
            _write_status(root, main, state="building", stamp=stamp)
            src = root / main
            out = _dir(root, main)
            args = [exe, "--synctex", "--keep-logs", "--outdir", str(out), src.name] if kind == "tectonic" else \
                [exe, "-interaction=nonstopmode", "-halt-on-error", "-synctex=1", f"-output-directory={out}", src.name]
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            try:
                r = subprocess.run(args, cwd=src.parent, capture_output=True, text=True, errors="replace",
                                   timeout=TIMEOUT, creationflags=flags)
                ok = r.returncode == 0 and pdf_path(root, main).is_file()
                why = "" if ok else (r.stdout[-1500:] or r.stderr[-1500:] or f"pdflatex exited {r.returncode}")
            except subprocess.TimeoutExpired:
                ok, why = False, f"pdflatex took longer than {int(TIMEOUT)} s"
            except OSError as exc:
                ok, why = False, f"pdflatex could not start: {exc}"
            _write_status(root, main, state="ready" if ok else "failed", stamp=stamp, why=why)
            if done is not None:
                done()
        t = threading.Thread(target=run, name="research-diff pdflatex", daemon=True)
        _JOBS[key] = t
        t.start()
    return {"state": "building", "why": ""}


def _synctex(root: Path, main: str) -> Dict[str, List[Tuple[int, int]]]:
    """{input file (resolved): [(line, page)]} from SyncTeX's file, read once per build."""
    f = _dir(root, main) / (Path(main).stem + ".synctex.gz")
    try:
        mt = f.stat().st_mtime_ns
    except OSError:
        return {}
    key = str(f)
    got = _PAGES.get(key)
    if got and got[0] == mt:
        return got[1]
    inputs: Dict[str, str] = {}
    out: Dict[str, List[Tuple[int, int]]] = {}
    page = 0
    try:
        with gzip.open(f, "rt", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.startswith("Input:"):
                    _k, tag, path = line.rstrip("\n").split(":", 2)
                    inputs[tag] = os.path.normcase(os.path.abspath(os.path.join(Path(root / main).parent, path)))
                elif line.startswith("{"):
                    try:
                        page = int(line[1:].strip())
                    except ValueError:
                        pass
                elif page and line[:1] in "[(hvxkg$" and "," in line and ":" in line:
                    try:
                        tag, rest = line[1:].split(",", 1)
                        ln = int(rest.split(":", 1)[0])
                    except ValueError:
                        continue
                    if tag in inputs:
                        out.setdefault(inputs[tag], []).append((ln, page))
    except (OSError, EOFError):
        return {}
    for k in out:
        out[k].sort()
    _PAGES[key] = (mt, out)
    return out


def page_of(root: Path, main: str, path: str, line: int) -> int:
    """The PDF page a line of a paper file is on (the nearest line at or after it that SyncTeX knows), else 1."""
    lines = _synctex(Path(root), main).get(os.path.normcase(os.path.abspath(Path(root) / path)), [])
    after = [p for ln, p in lines if ln >= line]
    before = [p for ln, p in lines if ln < line]
    return after[0] if after else (before[-1] if before else 1)


def page_html(src: str, state: dict) -> str:
    """The frame the Paper tab shows: the PDF at its page, or what the build is doing."""
    import html
    if state.get("state") == "ready":
        return (f'<!doctype html><meta charset="utf-8"><style>html,body{{margin:0;height:100%}}iframe{{border:0;'
                f'width:100%;height:100%}}</style><iframe src="{html.escape(src)}" title="The paper as a PDF"></iframe>')
    words = {"building": "Building the PDF with pdflatex… this page shows it when it is ready.",
             "failed": "pdflatex could not build the PDF:", "missing": "No PDF yet: research-diff found no pdflatex."}
    return ('<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="5">'
            '<body style="font:14px system-ui;padding:16px;color:#556">'
            f'<p>{html.escape(words.get(state.get("state"), "No PDF yet."))}</p>'
            f'<pre style="white-space:pre-wrap;font-size:12px">{html.escape(state.get("why") or "")}</pre></body>')
