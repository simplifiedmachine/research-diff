"""Two points in the research's life, compared: a commit, the working tree (`.`, read as a snapshot that touches
nothing the person uses), the CHECKPOINT, the last state they marked as understood, or the TURN, the working tree as
it was when the person last sent their agent a prompt. research-diff keeps its own refs, apart from system-diff's, in
this clone only: a checkpoint per branch (refs/research-diff/checkpoints/<branch>) and the turn."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from system_diff.compare import snapshot
from system_diff.sources import GitSource, git

from . import config
from .diff import diff
from .extract import extract

CHECKPOINT_REF = "refs/research-diff/checkpoint"          # before checkpoints were per branch: still read
TURN_REF = "refs/research-diff/turn"
WORKTREE = (".", "worktree")


def _rev(root: Path, ref: str) -> Optional[str]:
    try:
        return git("rev-parse", "--verify", "-q", ref, cwd=root).strip() or None
    except subprocess.CalledProcessError:
        return None


def sync_trackers(root: Path, config_path: Optional[str] = None) -> Dict[str, Any]:
    """Copy the trackers' tagged runs into research/runs.json (see trackers.py); a no-op without tracker folders."""
    from .trackers import sync
    t = config.load(None, root, config_path)["trackers"]
    return sync(root, t.get("mlflow", "mlruns"), t.get("wandb", "wandb"))


def branch(root: Path) -> str:
    try:
        return git("symbolic-ref", "--short", "-q", "HEAD", cwd=root).strip() or "detached"
    except subprocess.CalledProcessError:
        return "detached"


def checkpoint_ref(root: Path) -> str:
    return f"refs/research-diff/checkpoints/{branch(root)}"


def checkpoint_sha(root: Path) -> Optional[str]:
    return _rev(root, checkpoint_ref(root)) or _rev(root, CHECKPOINT_REF)


def checkpoint(root: Path, ref: Optional[str] = None) -> str:
    sha = git("rev-parse", "--verify", f"{ref}^{{commit}}", cwd=root).strip() if ref else snapshot(root)
    git("update-ref", checkpoint_ref(root), sha, cwd=root)
    return sha


def mark_turn(root: Path) -> str:
    """The working tree as the person sends a prompt: what `--base turn` compares with."""
    sha = snapshot(root)
    git("update-ref", TURN_REF, sha, cwd=root)
    return sha


def resolve(root: Path, point: str) -> tuple:
    if point == "checkpoint":
        sha = checkpoint_sha(root)
        return (sha, "checkpoint") if sha else (_rev(root, "HEAD") or snapshot(root), "HEAD (no checkpoint yet)")
    if point == "turn":
        sha = _rev(root, TURN_REF)
        return (sha, "the start of this turn") if sha else resolve(root, "checkpoint")
    if point in WORKTREE:
        return snapshot(root), "working tree"
    return git("rev-parse", "--verify", f"{point}^{{commit}}", cwd=root).strip(), point


class WorkSource:
    """The working tree as it is on disk, read without a snapshot: the files git would add (tracked, and untracked
    but not ignored), listed by one `git ls-files`, and only the files asked for read. Nothing is hashed, so a
    repository with large data files costs no more than its research files do."""
    label = "working tree"

    def __init__(self, root: Path):
        self.root = Path(root)
        tracked = git("ls-files", "-z", "-c", "--recurse-submodules", cwd=self.root)   # submodules' files too
        others = git("ls-files", "-z", "-o", "--exclude-standard", cwd=self.root)
        self.files = sorted({f for f in (tracked + "\0" + others).split("\0") if f})

    def read(self, path: str) -> str:
        try:
            return (self.root / path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def read_many(self, paths) -> Dict[str, str]:
        return {p: self.read(p) for p in paths}


class CommitTree:
    """A commit of the repository with its git submodules' files at the commits it records (a GitSource lists a
    submodule as one entry: a paper kept in a submodule would be missing from every commit). Like GitSource: files,
    blobs, label, root, read_many, read."""

    def __init__(self, ref: str, root: Path):
        self.root = Path(root)
        top = GitSource(ref, self.root)
        self.label, self.ref = top.label, ref
        self._parts = [("", top)]
        for path, commit in sorted((getattr(top, "gitlinks", None) or {}).items()):
            sub = self.root / path
            if not (sub / ".git").exists():
                continue                       # not checked out here: nothing to read it from
            try:
                self._parts.append((path.strip("/") + "/", GitSource(commit, sub)))
            except Exception:  # noqa: BLE001 - that commit is not in the submodule's clone: left out
                continue
        links = set(getattr(top, "gitlinks", None) or {})
        self.files = sorted([f for f in top.files if f not in links] +
                            [pre + f for pre, src in self._parts[1:] for f in src.files])
        self.blobs = {pre + f: b for pre, src in self._parts for f, b in (getattr(src, "blobs", None) or {}).items()}

    def _part(self, path: str):
        for pre, src in reversed(self._parts):
            if not pre or path.startswith(pre):
                return pre, src
        return "", self._parts[0][1]

    def read_many(self, paths) -> Dict[str, str]:
        by: Dict[int, list] = {}
        for p in paths:
            pre, _src = self._part(p)
            by.setdefault(next(i for i, (q, _s) in enumerate(self._parts) if q == pre), []).append(p)
        out: Dict[str, str] = {}
        for i, ps in by.items():
            pre, src = self._parts[i]
            got = src.read_many([p[len(pre):] for p in ps])
            out.update({pre + k: v for k, v in got.items()})
        return out

    def read(self, path: str) -> str:
        return self.read_many([path]).get(path, "")


def read(root: Path, point: str = ".", config_path: Optional[str] = None) -> tuple:
    """(map, config, label) of one point. The working tree is read from disk (WorkSource): no snapshot."""
    if point in WORKTREE:
        src = WorkSource(root)
        cfg = config.load(src, root, config_path)
        bp = extract(src, cfg)
        bp["ref"] = "working tree"
        return bp, cfg, "working tree"
    sha, label = resolve(root, point)
    src = CommitTree(sha, root)          # with its submodules' files at the commits it records
    cfg = config.load(src, root, config_path)
    bp = extract(src, cfg)
    bp["ref"] = label if point in ("checkpoint", "turn") or point in WORKTREE else bp["ref"]
    return bp, cfg, label


@dataclass
class Comparison:
    diff: Dict[str, Any]
    before: Dict[str, Any]
    after: Dict[str, Any]
    cfg: Dict[str, Any]
    base: str


def compare(root: Path, base: str = "checkpoint", head: str = ".", config_path: Optional[str] = None) -> Comparison:
    b, cfg, _ = read(root, head, config_path)
    a_sha, a_label = resolve(root, base)
    a = extract(CommitTree(a_sha, root), cfg)   # one vocabulary for both sides: the head's
    if base in ("checkpoint", "turn") or base in WORKTREE:
        a["ref"] = a_label
    return Comparison(diff(a, b, cfg), a, b, cfg, a_label)


def evidence_of(root: Path, point: str = ".", config_path: Optional[str] = None) -> tuple:
    """(evidence graph, map, config) of one point, with the agents' claims as owners."""
    from . import agents, evidence
    bp, cfg, _ = read(root, point, config_path)
    return evidence.build(bp, cfg, agents.owners(root)), bp, cfg
