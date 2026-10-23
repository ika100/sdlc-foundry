---
spec_id: 094-a-merge-conflict-re-plans-instead-of
title: A merge conflict re-plans instead of escalating
status: draft
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
- **AC-094.9** Given a run record store configured (spec 087), when a conflict occurs, then the run's record gains one plan-accuracy event per conflicting task with the spec, the task id, the task it collided with, the conflicting file paths, the agent and model that wrote the plan, and the outcome (`re-planned`, `resolved` or `escalated`), in the form spec 089 defines.
- **AC-094.10** Given no run record store is configured or it cannot be reached, when a conflict occurs, then the re-plan proceeds exactly as with a store (the record is buffered or skipped as spec 087 defines) and the build is not blocked.
- **AC-094.11** Given a build interrupted after a re-plan commit but before the re-planned task merged, when `/svc:build <id>` resumes, then it schedules from the amended plan, keeps every `done` task, and counts the earlier re-plan, so a further conflict of that task escalates as in AC-094.6.
- **AC-094.12** Given a conflict while merging, when the build handles it, then neither the orchestrator nor any agent edits conflicting hunks by hand; the only way forward is the amended plan and a fresh run of the task.

## Non-goals

- Resolving merge conflicts automatically (by an agent or a merge strategy); the "never resolve conflicts" rule stays.
- Conflicts outside Phase 2: a feature branch that conflicts with `main` at PR or land time, and conflicts in gitops tasks' repos.
- Re-planning for reasons other than a merge conflict (failing tests, a task that touched files outside its `files` without conflicting).
- Changing the spec or its criteria during a re-plan; a re-plan that would need that is a blocker (AC-094.7).
- Defining the plan-accuracy metric and its report; spec 089 owns them, this spec only emits the event.

## Open questions

- Confirm: the re-plan limit is one per task (a task that conflicts again after its re-plan escalates) and there is no separate limit per build. (suggested: yes, plus a cap of 3 re-plans per build, after which the next conflict escalates, so a plan that is wrong everywhere does not loop through the architect; affects AC-094.6, new criterion for the cap)
- Confirm: after a conflict the rest of the batch keeps merging, rather than the whole batch being set aside. (suggested: keep merging, since clean merges are kept work and the re-plan sees the real state; affects AC-094.2)
- Should the re-plan also run in an attended (interactive) build without asking, or only in unattended runs? (suggested: always, without asking, and say so in the Final Report; the plan change is visible in its own commit and reversible; affects AC-094.1, AC-094.3)
- The platform's orchestration guide and the build rules currently say "merge conflicts are escalated, never auto-resolved". Confirm they are reworded to "re-planned once, then escalated; never resolved by hand" as part of this spec. (suggested: yes; affects AC-094.12)

## Changelog

- 2026-10-23 created
