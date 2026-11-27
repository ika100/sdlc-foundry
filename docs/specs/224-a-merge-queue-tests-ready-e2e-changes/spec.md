---
spec_id: 224-a-merge-queue-tests-ready-e2e-changes
title: A merge queue tests ready e2e changes together
status: approved
priority: P1
shape: platform
---

# 224 — A merge queue tests ready e2e changes together

## Problem

In the platform repo every change merges alone, behind a machine-wide merge lock, and about 60 % of changes (179 of about 281 green runs, 2026-11-20 to 11-27) run the cluster e2e first: 26 min median, 41 min p90. Changes arrive in clusters: of 83 windows of 40 minutes, 51 had two or more merges and 3 had five. So each change in a cluster waits for the full e2e of every change before it. Before spec 220, land runs waited up to 182 minutes for the lock, PR #1016 lost the lock in four land runs in a row and escalated, and spec 220 itself escalated three times on conflicts that appeared while it waited. A waiting land run also holds one of the dispatcher's slots for that time. Spec 220 lets docs-only changes skip the wait, but it batches nothing (its non-goals). This spec tests the changes that need the e2e together, in one run, and lets an unattended run end once its change is queued. The original idea is #280 (closed when spec 220 merged).

## Stories

As someone shipping unattended, I want ready changes that need the cluster e2e tested together in one run, so that a cluster of changes waits for one e2e instead of one per change, and no change loses the lock again and again.

As someone shipping unattended, I want a fix or ship run to end when its change is green on its own checks and queued, so that its dispatcher slot is free and no conflict appears while it waits.

**Repos:** sdlc-foundry (the platform repo only; component repos keep today's land).

## Acceptance criteria

The entry gate.

- **AC-224.1** Given this spec is approved, when the dispatcher reads its backlog before the 7-day result of AC-220.9 is written into spec 220, then spec 224 is held as `blocked: waits for the AC-220.9 result`. It is released when that result shows a code land that waited more than 30 min for the merge lock, or by `cplat dispatch resume spec-224`; when the result shows none, the spec stays held and `cplat dispatch status` says so, for a person to abandon or resume.

Batches.

- **AC-224.2** Given a change in the platform repo whose own checks (the `ci` workflow, shape checks and template smoke tests) are green and whose e2e scope (`e2e-scope.py`) is `run=true`, when its land starts, then it joins the queue instead of taking the merge lock, and `cplat queue show` lists it with its PR, head commit and the time it joined.
- **AC-224.3** Given changes in the queue, when 3 are queued or the oldest has waited 30 minutes, then the queue builds one batch branch from main with the changes merged in queue order, runs the `e2e` and `e2e-upgrade` workflows once on it, and on green merges each change in queue order with `gh pr merge --squash --match-head-commit`, so main gets one commit per change. A change whose merge into the batch branch conflicts is left out of the batch and goes back to its run as a conflict.
- **AC-224.4** Given a batch whose e2e fails, when the failure is handled, then the batch runs once more. If it fails again, it is split into halves and each half is tested, until the one change is found that fails alone. That change leaves the queue and goes back to its run as a red check (with the failure summary of spec 108), and the other changes go on in a new batch. No change merges on a red batch.
- **AC-224.5** Given a change whose e2e scope is `run=false` (docs-only, spec 220), when it lands, then it does not join the queue and merges on its own as spec 220 defines, also while a batch is running.

The end of an unattended run.

- **AC-224.6** Given an unattended fix or ship run in the platform repo, when its change is queued (AC-224.2), then the run ends with the outcome `queued` and frees its dispatcher slot. When the queue merges the change, the platform posts the merge on the change's issue (the milestone comment of #853), and a change sent back by AC-224.3 or AC-224.4 starts a new fix round of its item.

Seeing the queue.

- **AC-224.7** Given a queue, when a person runs `cplat queue show` or `/platform:next`, then it prints one line per queued change (PR, title, waiting time) and, while a batch runs, the batch's changes and its e2e run link; a queued PR carries the label `queued`.

Measure.

- **AC-224.8** Given the run records of the first 14 days after the release that carries this spec, when the report is read, then the p90 of the land phase of code changes is under 40 min (62 min on 2026-11-27), no run escalated for not getting the merge lock or for a conflict that appeared while queued, main was never red after a batch merge, and there was at most 0.5 e2e runs per merged in-scope change. The result is written into this spec.

## Non-goals

- A queue for component, system or cluster repos: they keep today's land until this one is measured.
- GitHub's native merge queue: the repo is on GitHub Free without branch protection, so cplat decides what is green.
- Batching docs-only changes (spec 220 already lets them pass).
- Running the per-change checks (`ci`, shapes, smoke) only on the batch: they are cheap and specific to one change.
- A console view of the queue (terminal only).

## Assumptions

- **A1** The spec is written and approved now but built only after the AC-220.9 result shows waits that are still too long, because all the long waits above are from before spec 220 was live (decided by the user; other option: build now; affects AC-224.1).
- **A2** Only changes that need the e2e are batched; docs-only changes keep spec 220's lane (decided by the user; other options: batch everything, or keep one at a time with a fair order; affects AC-224.2, AC-224.5).
- **A3** A batch starts at 3 changes or 30 minutes after the oldest joined; a red batch reruns once, then is split, because real e2e failures are rare (1 in 300 runs) and transient ones are not (decided by the user; other options: split at once, or drop the newest change; affects AC-224.3, AC-224.4).
- **A4** An unattended run ends when its change is queued, in the platform repo only, and the merge is reported later on the issue (decided by the user on 2026-10-28 and again on 2026-11-27; other option: wait for the merge as today; affects AC-224.6).
- **A5** The batch branch is pushed to the repo as `queue/<n>` and deleted after the batch, and the e2e workflows run on it by `workflow_dispatch` (other option: a pull request per batch; affects AC-224.3).
- **A6** A threshold of 30 min of lock wait for a code land releases the entry gate (other option: any wait over 5 min; affects AC-224.1).

## Open questions

None.

## Changelog

- 2026-11-27 created (from the #280 exploration)
- 2026-11-27 priority P1 given by you
- 2026-11-27 approved
