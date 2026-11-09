---
spec_id: 164-the-journey-7-findings
title: The journey 7 findings
status: approved
priority: P1
shape: platform
tracks: [596, 598, 599, 600]
---

# 164 — The journey 7 findings

## Problem

Journey 7 (2026-11-09, 5.14.0–5.14.2, [docs/PERFORMANCE.md](../../PERFORMANCE.md)) found four defects that cost a round each. After a prod merge, `/instance:promote` waited only for the named components, so the backups bucket the prod database archives to stayed unsynced and archiving failed with nobody told (#600). `devbox run pin -- dev <component> <tag>` in a gitops-app repo printed only the usage, because devbox 0.19 no longer appends a script's arguments (#599). The promotion to staging took main's head, which held only the release's changelog and version bump on top of v0.1.0; the release refused it as nothing new, so staging ran an image no release had and the prod PR got a digest mismatch (#598). When the person asked the system ship to tighten an acceptance test, the session changed it but did not record the approval, and the repo's build stopped on the change again (#596).

## Stories

As someone running a system unattended, I want these to resolve themselves, so that a prod merge, a pin, a staging promotion or my answer to a test question needs one round.

## Acceptance criteria

- **AC-164.1** Given a merged prod promotion, when `/instance:promote` waits, then it runs `cplat system wait --env prod --refresh` without naming components, so the databases and the buckets they back up to are waited for too; a wait that names components stays limited to their apps (spec 143).
- **AC-164.2** Given a gitops-app repo, when `devbox run pin -- dev <component> <tag>` runs, then `scripts/pin.py` gets the arguments (the recipe passes `"$@"`).
- **AC-164.3** Given a promotion to staging without `--sha`, when every commit of the component's main after its newest release tag is release bookkeeping (`chore(release): …`), then the release's own commit is pinned (`sha-<that commit>`) and the summary says why; any other commit after the tag, or `--sha`, pins as before.
- **AC-164.4** Given a system ship whose escalation the user answers by changing a repo's acceptance test, when the coordinator makes the change, then it records it as the user's approval with `cplat spec test-diff $RED --approve <file>... --reason '<the user's words>'` in the same step.

## Non-goals

- #595, a reviewer finding an acceptance test looser than its criterion: the agents may not change a frozen test without the user (`references/build-test-approval.md`), and whether they may tighten one by themselves is a decision for the user.
- #597, a joint dev PR that conflicts with gitops PRs merged meanwhile: rebuilding the compose branch from the current main (the plan's gitops operations and the pins again) is a design of its own.
- #582 and #583 (an e2e acceptance test frozen without having run, a flaky test outside the change): designs of their own.

## Assumptions

- **A1** The commit title `chore(release): …` marks release bookkeeping, as every release agent writes it (other option: compare the changed files; affects AC-164.3).

## Open questions

None.

## Changelog

- 2026-11-09 created from the journey 7 findings; approved with the recommended answers, as the user asked for this round ("do it autonomous").
