---
spec_id: 159-unit-mode-runs-independent-tasks-at-once
title: Unit mode runs independent tasks at once
status: approved
priority: P1
shape: platform
tracks: [560]
---

# 159 — Unit mode runs independent tasks at once

## Problem

Unit mode (spec 131) runs a build as one fresh session per unit, and the supervisor always takes the first open unit (`units.next_open`). The tasks of a plan therefore run one after another, even when the plan marks them `parallel_safe` and `cplat component build schedule` puts them in one batch. The non-unit build (`build.md` Phase 2) runs such a batch at once in git worktrees, but unattended runs, and since spec 155 every repo of a system ship, use unit mode.

The first `system-ship` benchmark run (spec 156) showed this: `bench-files-api` ran tasks t1, t2 and t3, all `parallel_safe` with no dependencies between them, as three sessions in a row, never more than one subagent at once. The repo took 17.4 minutes, 13 of them agent time. The effect holds for any repo whose plan has independent tasks, in any shape.

## Stories

As someone shipping a spec unattended, I want the independent tasks of a build to run at the same time, as the plan allows, so that a build takes about as long as its longest chain of tasks rather than the sum of all of them.

## Acceptance criteria

- **AC-159.1** Given a unit-mode build whose next batch in `cplat component build schedule` has several open task units, when the supervisor starts them, then it runs up to `--parallel N` of them at once (default 3; 1 keeps today's order), each as its own fresh session in its own git worktree on its own branch from the feature head.
- **AC-159.2** Given a task session in a worktree that reached its checkpoint (the task's commit), when the supervisor merges it, then the task's branch goes onto the feature branch through `cplat component build merge` (merged, set aside, or escalated, as in build Phase 2), one task at a time in the schedule's order. The worktree and branch are removed after a merge.
- **AC-159.3** Given a task whose merge conflicts, when the merge is refused, then the existing rule applies: the task is re-planned once and rerun on the merged work (at most 3 re-plans per build), then the build escalates. No hunk is resolved by hand.
- **AC-159.4** Given a batch where some tasks end without a checkpoint, when the supervisor handles them, then each such task follows the existing stall rule of unit mode on its own (another session, then the escalation). The other tasks' merges are kept.
- **AC-159.5** Given tasks that depend on each other, or units that are not tasks (plan, red-tests, verification, land), when they come next, then they run alone and in order, as today; a task starts only after every task it depends on is merged.
- **AC-159.6** Given parallel sessions, when they run, then each counts as one invocation of the run's budget (spec 102) and is recorded as its own session, so the budget, the run record and the token count stay right. A used-up budget starts no new session; running ones finish.
- **AC-159.7** Given the worktrees of a batch, when the build is resumed after a crash, then a task whose branch carries its checkpoint is merged without a new session, and a stale worktree is removed and its task rerun.
- **AC-159.8** Given a repo whose plan has no `parallel_safe` tasks, or `--parallel 1`, when it builds, then the sessions, commits and result are the same as before this spec. Tests cover a batch of three independent tasks, a dependency chain, a conflict and a stall within a batch.

## Non-goals

- Running non-task units (plan, red-tests, verification, land) at once, or several units of one task.
- Parallel tasks in the interactive, non-unit build (it already batches in Phase 2).
- Changing how the architect marks tasks `parallel_safe`.

## Assumptions

- **A1** The default is 3 parallel task sessions, the same as `/system:ship --max`. With three repos at once a machine runs up to nine sessions at its peak, which is the reason for the cap (other option: 2; affects AC-159.1).
- **A2** Merges happen in the schedule's order once every task of the batch has ended, not as soon as each one ends, so the feature branch's history does not depend on timing (other option: merge as they finish; affects AC-159.2).

## Open questions

## Changelog

- 2026-11-08 drafted after the first system-ship benchmark run (spec 155 branch) showed sequential task units; approved by the user on 2026-11-08 (as 157; renumbered to 159, another session had merged a spec 157).
