"""A small research project, committed once: a question, two hypotheses, an experiment with a results file, a result
note and a claim in the paper."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

FILES = {
    "notes/ideas.md": ("## Q1: Does batch size matter on small data?\n\n## H1: Small batches generalise better\n\n"
                       "answers: Q1\nstatus: open\n\n## H2: Warm-up removes the gap\n\nanswers: Q1\n"),
    "configs/e1.yaml": "lr: 0.1\nresearch:\n  id: E1\n  title: Batch 32 vs 512\n  tests: [H1]\n  results: ../out/e1.json\n",
    "out/e1.json": '{"acc": {"b32": 0.874, "b512": 0.842}, "converged": true}\n',
    "train.py": "# research-diff: E2 tests H2\n# research-diff: status: running\nprint('train')\n",
    "paper/main.tex": ("\\section{Results}\n\n% C1: Small batches win on small data\n% relies on: H1\n"
                       "Batch 32 wins \\cite{keskar2017,masters2018}.\n"),
}


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args], cwd=repo, check=True,
                          capture_output=True, text=True).stdout


def write(repo: Path, files: dict) -> None:
    for name, text in files.items():
        p = repo / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "study"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    write(r, FILES)
    git(r, "add", "-A")
    git(r, "commit", "-q", "-m", "first")
    return r


@pytest.fixture
def files():
    return write
