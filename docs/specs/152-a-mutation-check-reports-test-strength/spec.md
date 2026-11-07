---
spec_id: 152-a-mutation-check-reports-test-strength
title: A mutation check reports how strong the acceptance tests are
status: approved
priority: P2
shape: platform
---

# 152 — A mutation check reports how strong the acceptance tests are

## Problem

A build is done when every criterion is named by a test and the tests pass (`cplat spec trace`, the reviewer). Nothing measures whether those tests would notice the code being wrong. Spec 147 cut the repo criteria of a system ship from 42 to 13, and spec 149 lets the product-manager decide defaults, so fewer and broader criteria now carry the same feature; a weak test would pass silently. Mutation testing (changing the code in small ways and checking that a test fails) is the established measure of test strength, and it is cheap when it only mutates the lines a build changed.

## Stories

As someone reading a build's verification, I want to see how many small faults in the changed code the acceptance tests catch, and which ones they miss, so that I know how far "all criteria have passing tests" can be trusted.

## Acceptance criteria

- **AC-152.1** Given a Python component repo (service-python, library-python) on a feature branch, when `cplat spec mutate <id> [--base REF] [--max N]` runs, then it mutates only lines of `src/**/*.py` changed since REF, one mutation at a time (a comparison or boolean operator flipped, `not` dropped, a True/False or number changed, a returned value replaced by None), at most N (default 20) spread over the changed lines, runs the tests that name the spec's criteria once per mutant, and reports the mutants, the caught ones, the score and every survivor as `file:line mutation`; the source is restored after each mutant.
- **AC-152.2** Given `--write`, when the check ran, then the result is the `## Mutation check (report only)` section of the spec's `verification.md`, replaced (never duplicated) on a second run.
- **AC-152.3** Given `/component:build`, when Phase 4's reviewer finished, then `cplat spec mutate <id> --write` runs before verification.md is committed, and nothing stops on its score; another shape, a spec without criterion-named tests or no changed source line is reported as skipped, and tests that fail before any mutation are a setup error.

## Non-goals

- No gate: the score is reported, never enforced, in this spec.
- No other languages yet (Go, Java and TypeScript follow once the Python numbers are known).
- No mutation of test files or of unchanged code.

## Open questions

- ~~Report or gate?~~ Answered (recommended, self-approved for the 5.13 round on 2026-11-07): report only; a threshold needs data first.
- ~~How many mutants?~~ Answered: at most 20 per build, a few minutes for a small change.

## Changelog

- 2026-11-07 created from the strategy after journey 5 (item B3, "mutation check on the acceptance tests"); approved with the recommended answers, as the user asked for this round.
