"""`research-diff diff --narrate`: a plain-words summary of a research diff, written by your LLM (the one your Claude
Code uses, found as system-diff finds it) on top of the exact plan and the evidence; the pictures never depend on it.
Only the headline, the plan and the evidence verdicts are sent, never the files. RESEARCH_DIFF_LLM=off: none.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from . import evidence, objectives

SYSTEM = (
    "You explain to a researcher, or to the reviewers of their pull request, what an iteration did to their study. You "
    "are given an exact, machine-extracted diff of the research (hypotheses, experiments, results, findings, claims) "
    "and the evidence verdict of each claim of the paper. Write two parts, plain words, no headings: 1) two to four "
    "sentences on what changed and what it means for the paper, contradictions first; 2) up to four bullet points to "
    "check, each grounded in a line of the plan. Never mention a result, number or claim that is not given. If "
    "nothing changed, say so in one sentence.")


def narrate(root: Path, c) -> Optional[str]:
    if objectives.off():
        return None
    from system_diff.narrate import complete
    g = evidence.build(c.after, c.cfg)
    user = (f"Headline: {c.diff['headline']}\n\nPlan:\n{c.diff['plan']}\n\nEvidence now: {g['headline']}\n" +
            "\n".join(f"- {s['id']} {s['verdict']}: " + "; ".join(x["why"] for x in s["against"]) for s in
                      g["statements"]))
    got = complete(user, SYSTEM, root, {}, timeout=120, limit=3000)
    return f"{got[0]}\n\n(written by {got[1]})" if got else None
