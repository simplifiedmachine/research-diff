---
name: research-diff-explain
description: Shows the person what supports and what contradicts each claim and finding of their paper, and what an iteration (an experiment run, a result logged, a paragraph rewritten) did to the research. Use after running an experiment or editing notes, configs or the paper, before asking them to review, when they ask whether a claim holds, or when several agents work on one study.
---

# The evidence and the research diff

1. After an iteration, call the `research_diff` MCP tool (base `turn` for this turn alone). Tell the person in two or
   three plain sentences, built only from its plan, what changed. Contradictions first: a claim now contested or
   contradicted, the paper contradicting itself, one agent's result against another agent's claim.
2. When they ask whether a claim holds, call `research_evidence` (the whole paper) or `explain` (one node) and answer
   from what it returns: the verdict, what backs it, what contradicts it and why. Point them at the Evidence tab of
   the pane (`/research-diff`) or the picture's path.
3. Write what you find as markers, so it is on the graph: `supports:`, `contradicts:`, `weakens:` on the evidence, or
   `supported by:`, `contradicted by:` under the claim; `expects: E1.results acc > 0.85` for a number a claim needs.
   Never leave a contradiction out because it is inconvenient.
4. For work across the study, `plan_agents` gives one brief per paper section or hypothesis: start one subagent per
   brief. Each agent `claim`s its nodes, writes `by: <name>`, `publish`es what it finds to the topic of the node it
   affects, and reads the bus that comes with its tool results.
5. When they say they have seen it, call `checkpoint`, so the next diff shows only what is new to them.

Never mention a result, number or claim that is not in what the tools return.
