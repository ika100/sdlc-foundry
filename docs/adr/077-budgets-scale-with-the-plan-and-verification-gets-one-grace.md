# ADR-077: Run budgets scale with the plan, and verification gets one grace

**Status:** Accepted (2026-11-03)
**Amends:** [ADR-043](043-one-budget-per-run-tree.md) (fixed per-ship defaults multiplied by the ship count); spec 131

## Context

The budget of ADR-043 was $15, 180 minutes, 60 invocations and 6 CI reruns per ship, whatever the size of the plan. It
once ran out with 20 of 20 tasks done and only the review missing. Spec 128's build (8 tasks, 14 criteria) ran out before
verification with green CI. The ledger also undercounted: a budget check read the session transcripts with a 3 s limit
and reported a partial sum without the subagents (#324).

## Decision

1. **Default limits follow the plan.** For T tasks and C active criteria they are:
   - cost `max(15, 10 + 1.5·T + 0.5·C)`;
   - minutes `max(180, 60 + 15·T + 5·C)`;
   - invocations `max(60, 20 + 5·T + C)`;
   - reruns 6.

   A `budget:` value in the settings files replaces the floor, and an option replaces the limit.
2. **One part per spec.** The ledger keeps a part per spec of the run tree, and the limits are their sum. A run that
   starts before its plan exists starts with the floors. When the plan is checked, its part is raised to the formula.
   Limits are never lowered, and every raise is noted in the ledger's changes. A product ship adds a placeholder part
   per repo, which the repo's plan later replaces.
3. **One grace, for verification only.** If a limit is used up while every task is done and only verification is left,
   verification starts within a grace of 20 % of each limit (at least $3, 30 minutes and 10 invocations). The grace is
   given once per run and never to an earlier unit or to land. If the grace is used up as well, the run escalates with
   `budget exhausted: <limit> (grace used)`. The grace never skips or passes a mandatory check.
4. **Cost is never lower than spent.** An incomplete transcript read is an `unknown` cost, not a partial sum. Unchanged
   transcript files are cached, so a budget check reads every subagent's cost.

## Consequences

- Large plans get room in proportion to their size. Small ones keep the old floor.
- A run with all its work done is verified instead of escalated, at a bounded extra cost.
- An `unknown` cost is not checked against the cost limit (AC-102.5). The other limits still bound the run.

## Not included

- Per-unit budgets: the budget stays one per run tree.
- A grace for land or for any unit before verification.
