---
spec_id: 094-a-merge-conflict-re-plans-instead-of
title: A merge conflict re-plans instead of escalating
status: building
priority: P2
---

# 094 — A merge conflict re-plans instead of escalating

## Problem

`/svc:build` Phase 2 runs parallel coders in worktrees and merges their task branches one by one into the feature branch. When a merge conflicts, the build aborts the merge and stops for a person, even though the cause is always the same and known: the plan's `files` or `depends_on` were wrong. The fix is mechanical (correct the plan, run the task again on top of what was merged), yet today it costs an unattended run its whole remaining build and a person's time to re-plan by hand. The feedback-loops and autonomy round (specs 085–097) removes people from steps the platform can judge itself. This is one of those steps. Depends on 089, which records the conflict as a plan-accuracy event.

## Stories

As a contributor running `/svc:build` or `/svc:ship` unattended, I want a merge conflict between task branches to send the plan back to the architect and run the conflicting task again on top of the merged work, so that a wrong `files` list costs one extra coder pass, not a stopped build.

As the platform maintainer, I want every conflict and re-plan recorded against the plan, so that the architect's plan accuracy can be measured and improved (spec 089).

## Acceptance criteria

- **AC-094.1** Given a parallel batch whose task branch conflicts when merged into the feature branch, when the build hits the conflict, then the merge is aborted, the feature branch is exactly as it was before that merge (no conflict markers, no partial changes), and the build does not stop.
- **AC-094.2** Given a conflicting task branch in a batch, when the remaining branches of the same batch are merged, then each one that merges cleanly goes through the usual post-merge checks and is marked `done`, and every other conflicting branch of the batch is set aside the same way.
- **AC-094.3** Given one or more set-aside tasks after a batch, when the build re-plans, then the architect receives the plan, each conflicting task id, the task it collided with and the conflicting file paths, and returns a plan in which only the `files`, `depends_on` and `parallel_safe` of tasks that are not `done` changed (task ids, `covers`, `spec_hash`, the spec and every `done` task are unchanged).
- **AC-094.4** Given an amended plan, when the build continues, then `cplat spec check` passes on it, it is committed with a message naming the re-planned task ids and the conflicting files, and the schedule printed next shows the re-planned tasks after the tasks they now depend on.
- **AC-094.5** Given a re-planned task, when it runs again, then it starts from the feature branch with every already merged task in it, and its coder prompt contains the diff of its set-aside branch as reference; after it is merged and green, the set-aside branch and its worktree no longer exist.
- **AC-094.6** Given a task that was already re-planned once, when its branch conflicts again, then the build stops and escalates, and the message names the task, the conflicting files, the task it collided with both times and the re-plan commit.
- **AC-094.7** Given the architect answers a re-plan with blockers or with a plan that still fails `cplat spec check` after one retry, when the build reads the answer, then the build stops and escalates with the architect's blockers or the check errors, and the plan on the feature branch is the last valid one.
- **AC-094.8** Given a build in which at least one re-plan happened, when the Final Report is printed, then its Implementation row states the number of re-plans and, per re-planned task, the conflicting files and whether the re-run merged cleanly.
- **AC-094.9** Given a run record store configured (spec 087), when a conflict occurs, then the run's record gains one `merge-conflict` plan-accuracy event per conflicting task as AC-089.3 defines it (spec, task id, the task it collided with, the conflicting paths, the plan author's agent and model), with outcome `re-planned` once the amended plan is committed, updated in place to `resolved` when the re-run merges cleanly or `escalated` when the build stops; each amended plan counts one re-plan for the architect as AC-089.14 defines.
- **AC-094.10** Given no run record store is configured or it cannot be reached, when a conflict occurs, then the re-plan proceeds exactly as with a store (the record is buffered as spec 087 defines) and the build is not blocked.
- **AC-094.11** Given a build interrupted after a re-plan commit but before the re-planned task merged, when `/svc:build <id>` resumes, then it schedules from the amended plan, keeps every `done` task, and counts the earlier re-plan, so a further conflict of that task escalates as in AC-094.6.
- **AC-094.12** Given a conflict while merging, when the build handles it, then neither the orchestrator nor any agent edits conflicting hunks by hand; the only way forward is the amended plan and a fresh run of the task.
- **AC-094.13** Given a build that has already re-planned 3 times (counting re-plans before an interruption), when another task branch conflicts, then the build stops and escalates without a fourth re-plan, and the message says the cap of 3 re-plans per build was reached and lists the earlier re-plan commits.
- **AC-094.14** Given an attended (interactive) build, when a task branch conflicts, then the re-plan and the re-run happen without asking the user, exactly as in an unattended run, and the Final Report says that the plan was amended (AC-094.8).
- **AC-094.15** Given the platform's orchestration guide and the build command's rules, when a reader looks up merge conflicts, then both say a conflict is re-planned once per task (at most 3 re-plans per build), then escalated, and is never resolved by hand; neither still says that every conflict is escalated.

## Non-goals

- Resolving merge conflicts automatically (by an agent or a merge strategy); the "never resolve conflicts" rule stays.
- Conflicts outside Phase 2: a feature branch that conflicts with `main` at PR or land time, and conflicts in gitops tasks' repos.
- Re-planning for reasons other than a merge conflict (failing tests, a task that touched files outside its `files` without conflicting).
- Changing the spec or its criteria during a re-plan; a re-plan that would need that is a blocker (AC-094.7).
- Defining the plan-accuracy metric and its report; spec 089 owns them, this spec only emits the event.

## Open questions

- ~~Confirm: the re-plan limit is one per task, and is there a limit per build?~~ Answered: one re-plan per task (AC-094.6) plus a cap of 3 re-plans per build (AC-094.13).
- ~~Confirm: after a conflict the rest of the batch keeps merging?~~ Answered: yes, the rest of the batch keeps merging (AC-094.2).
- ~~Should the re-plan also run without asking in an attended build?~~ Answered: yes, always without asking, and the Final Report says so (AC-094.14, AC-094.8).
- ~~Confirm: the orchestration guide and build rules are reworded?~~ Answered: yes, "re-planned once, then escalated; never resolved by hand" (AC-094.15).

## Changelog

- 2026-10-23 created
- 2026-10-23 open questions answered: one re-plan per task and at most 3 per build (AC-094.13), the batch keeps merging, re-plans without asking in attended builds too (AC-094.14), guide and build rules reworded (AC-094.15); AC-094.9 clarified to reference 089's `merge-conflict` event (AC-089.3) and re-plan count (AC-089.14)
- 2026-10-23 approved
- 2026-10-24 building
