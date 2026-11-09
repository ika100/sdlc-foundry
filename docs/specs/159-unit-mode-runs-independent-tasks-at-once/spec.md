---
spec_id: 159-unit-mode-runs-independent-tasks-at-once
title: Unit mode runs independent tasks at once
status: done
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

- **AC-159.1** Given a unit-mode build whose plan has a batch of `parallel_safe` tasks with disjoint `files` in one level (as `cplat component build schedule` groups them), when its units are derived, then those tasks form one unit `batch:<id>,<id>…` of at most `--parallel N` tasks (default 3; 1 keeps one `task:` unit per task), and its one fresh session runs build Phase 2's parallel batch: one coder per task at once, as subagents in their own worktrees.
- **AC-159.2** Given a batch session whose coders finished, when it merges them, then each task's branch goes onto the feature branch through `cplat component build merge` (merged, set aside, or escalated, as in build Phase 2), one task at a time in the unit's order; the batch unit is done when every task of it is `done: true` in a commit.
- **AC-159.3** Given a task whose merge conflicts, when the merge is refused, then the existing rule applies: the task is re-planned once and rerun on the merged work (at most 3 re-plans per build), then the build escalates. No hunk is resolved by hand.
- **AC-159.4** Given a batch session that ends with some of its tasks done and others not, when the supervisor handles it, then the merged tasks stay done, the next session of the same unit runs only the open ones, and the unit's stall rule applies to the batch as a whole (a session that moved the feature head is progress).
- **AC-159.5** Given tasks that depend on each other, or units that are not tasks (plan, red-tests, verification, land), when they come next, then they run alone and in order, as today; a task starts only after every task it depends on is merged.
- **AC-159.6** Given a batch unit, when it runs, then it is one session and one invocation of the run's budget (spec 102), and its coders' tokens are recorded under that session, as for any subagent.
- **AC-159.7** Given a batch unit whose worktree probe fails, when its session runs, then it runs the tasks one after another as build Phase 2's fallback does, and the unit completes the same way.
- **AC-159.8** Given a repo whose plan has no `parallel_safe` tasks, or `--parallel 1`, when it builds, then its units, sessions, commits and result are the same as before this spec. Tests cover a batch of three independent tasks, the cap, a dependency chain, overlapping files and a partly done batch.

## Non-goals

- Running non-task units (plan, red-tests, verification, land) at once, or several units of one task.
- Parallel tasks in the interactive, non-unit build (it already batches in Phase 2).
- Changing how the architect marks tasks `parallel_safe`.

## Assumptions

- **A1** The default is 3 parallel task sessions, the same as `/system:ship --max`. With three repos at once a machine runs up to nine sessions at its peak, which is the reason for the cap (other option: 2; affects AC-159.1).
- **A2** Merges happen in the unit's order once every coder of the batch has finished, as in build Phase 2, so the feature branch's history does not depend on timing (other option: merge as they finish; affects AC-159.2).

## Open questions

## Changelog

- 2026-11-08 AC-159.1, .2, .4, .6, .7, .8 amended with the user's approval: one session per batch (build Phase 2's parallel batch) instead of one session per task in its own worktree, which would need the unit and ship state carried into each worktree.
- 2026-11-08 drafted after the first system-ship benchmark run (spec 155 branch) showed sequential task units; approved by the user on 2026-11-08 (as 157; renumbered to 159, another session had merged a spec 157).
- 2026-11-09 building
- 2026-11-09 done
