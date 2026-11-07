---
spec_id: 154-the-journey-6-findings
title: The journey 6 findings
status: approved
priority: P1
shape: platform
tracks: [557, 558, 559, 560]
---

# 154 — The journey 6 findings

## Problem

Journey 6 (2026-11-07, 5.13.0, [docs/PERFORMANCE.md](../../PERFORMANCE.md)) ran without a stop, but four findings cost time. The release of 5.13.0 failed its tag step once because `scripts/release-check.py gate` read GitHub during a network drop and called the unreadable answer "no green upgrade e2e" (#557): its calls bypass the retry of spec 148. A deploy wait started before the automatic pin PR merged kept waiting for the image the pin had replaced, because Argo CD's newer revision was unknown to the clone (#558). The restore drill right after go-live was refused with "outside the restore points: earliest none" and no word about what to do (#559). The system plan gave one repo 14 criteria (#560), above the 3 to 8 that spec 147 aims at.

## Stories

As someone running a journey unattended, I want each of these to resolve itself or say exactly what to do, so that the next run does not spend a second round on them.

## Acceptance criteria

- **AC-154.1** Given `scripts/release-check.py gate <sha>`, when a GitHub read fails on a dropped network, then it is retried as in `core.run` (spec 148); an answer it still cannot read ends with "cannot read the check runs … run the gate again", never with "no green upgrade e2e".
- **AC-154.2** Given `cplat system wait`, when Argo CD reports a revision the clone does not know (a pin PR merged after the wait started), then the wait fetches `main` once and reads that revision's pin, so a newer build of the component counts.
- **AC-154.3** Given `/resource:restore <db> --env <env> --to <time|latest>`, when no backup has completed yet or the time is after the latest restore point, then the refusal says so and its hint names `/resource:backup <db> --env <env>`.
- **AC-154.4** Given a system plan whose component repo slice lists more than 12 criteria, when its plan check runs, then it refuses the slice unless the slice says why in `criteria_why:`; the planner guidance says to merge criteria one test covers.

## Non-goals

- The sequential coders of #560: in a system ship the per-repo ship runs from the gitops session, so a coder's worktree belongs to the gitops repo and the build falls back to sequential coders. Fixing it means running the per-repo ships in their own clones (for example with `cplat headless`); that is a design change for the next round.

## Open questions

- ~~Refuse or warn above 12 repo criteria?~~ Answered (recommended, self-approved for the 5.13 fix round on 2026-11-07): refuse, with `criteria_why:` as the way to keep more; `cplat spec check` keeps warning on component specs.

## Changelog

- 2026-11-07 created from the journey 6 findings; approved with the recommended answers, as the user asked for this round.
