---
spec_id: 169-the-acceptance-tests-freeze-when-the-red-tests
title: The acceptance tests freeze when the red-tests unit ends
status: done
priority: P1
shape: platform
tracks: []
---

# 169 — The acceptance tests freeze when the red-tests unit ends

## Problem

In journey 8 the web repo's red-tests session committed its acceptance tests, then fixed them in a second commit before any code existed: the tests now import the page and route modules dynamically, so `next build` type-checks. The unit runner recorded the red-tests unit as done at that second commit. The build's later sessions take `$RED` from the last commit named 'acceptance tests for', the first one, so `cplat spec test-diff` called the session's own fix a changed acceptance test and the system ship stopped for a person, who could only approve it. Later the reviewer's tightening of the same repo (two new tests for the 5-second limit, each naming AC-001.5 or AC-001.6) was refused as `criterion ids changed: []`: the check counted how often each id appears, so a new test that names its criterion looked like a change, and the run asked the person again. After each approval `cplat system ship next --wait` read the web clone a few seconds after the new session started and reported the old escalation again, so the supervising session waited on the repo by hand.

## Stories

As someone shipping unattended, I want the acceptance tests to freeze when the session that writes them is done, so that a fix to the tests before any code exists does not stop the run.

## Acceptance criteria

- **AC-169.1** Given `<git dir>/cplat-units.json` records the `red-tests` unit done at a commit that descends from the given base and that HEAD descends from, when `cplat spec test-diff <base>` runs (also with `--approve` or `--tighten`), then it compares against that commit and prints that it did; a test changed after it is still flagged.
- **AC-169.2** Given no units file, a `red-tests` unit that is not done, or a recorded commit that is not between the base and HEAD, when `cplat spec test-diff <base>` runs, then the given base holds, as before.
- **AC-169.3** Given a tightening that adds a test naming a criterion the file already covers, when `cplat spec test-diff --tighten` checks it, then it is accepted; a criterion id added or dropped is still refused.
- **AC-169.4** Given a repo of a system ship whose clone holds the escalation of its run before, when `cplat system ship repo start` starts its session again and `cplat system ship next --wait` reads the clone before the session resumed, then that escalation, saved before the session started, is not reported; once the session ends, an escalation counts again.

## Non-goals

- Changing the prompts' `RED=` line: the units file is where the runner records when the tests froze, so the check reads it there.

## Assumptions

- **A1** The red-tests unit writes only tests, so every change it commits belongs to the frozen tests (affects AC-169.1).

## Open questions

None.

## Changelog

- 2026-11-10 created from journey 8 (finding F1); self-approved under the standing order to fix what a journey finds.
- 2026-11-10 done
