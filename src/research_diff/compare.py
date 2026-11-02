"""Two points in the research's life, compared: a commit, the working tree (`.`, read as a snapshot that touches
nothing the person uses), or the CHECKPOINT, the last state they marked as understood. research-diff keeps its own
checkpoint (refs/research-diff/checkpoint), apart from system-diff's, in this clone only."""
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

CHECKPOINT_REF = "refs/research-diff/checkpoint"
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


def checkpoint(root: Path, ref: Optional[str] = None) -> str:
    sha = git("rev-parse", "--verify", f"{ref}^{{commit}}", cwd=root).strip() if ref else snapshot(root)
    git("update-ref", CHECKPOINT_REF, sha, cwd=root)
    return sha


def resolve(root: Path, point: str) -> tuple:
    if point == "checkpoint":
        sha = _rev(root, CHECKPOINT_REF)
        return (sha, "checkpoint") if sha else (_rev(root, "HEAD") or snapshot(root), "HEAD (no checkpoint yet)")
    if point in WORKTREE:
        return snapshot(root), "working tree"
    return git("rev-parse", "--verify", f"{point}^{{commit}}", cwd=root).strip(), point


def read(root: Path, point: str = ".", config_path: Optional[str] = None) -> tuple:
    """(map, config, label) of one point."""
    sha, label = resolve(root, point)
    src = GitSource(sha, root)
    cfg = config.load(src, root, config_path)
    bp = extract(src, cfg)
    bp["ref"] = label if point == "checkpoint" or point in WORKTREE else bp["ref"]
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
    a = extract(GitSource(a_sha, root), cfg)   # one vocabulary for both sides: the head's
    if base == "checkpoint" or base in WORKTREE:
        a["ref"] = a_label
    return Comparison(diff(a, b), a, b, cfg, a_label)
