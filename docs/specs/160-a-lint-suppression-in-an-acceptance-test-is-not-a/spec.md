---
spec_id: 160-a-lint-suppression-in-an-acceptance-test-is-not-a
title: A lint suppression in an acceptance test is not a changed test
status: done
priority: P1
shape: platform
tracks: [570]
---

# 160 — A lint suppression in an acceptance test is not a changed test

## Problem

Acceptance tests are fixed once build Phase 1 committed them: `cplat spec test-diff` refuses any change except formatting, and the coder may not edit them. Phase 1 runs only `lint-fix`, which applies autofixes, so a linter finding that cannot be auto-fixed passes Phase 1. It then stops the first task whose `quality` gate runs, and the ship escalates with cause `decision` (#570). In the first system-ship benchmark run this happened in the Go worker: a `bodyclose` false positive in a test whose helper closes the body. It can happen in any shape, for example `# noqa` cases in Python or `eslint` rules in TypeScript.

Running the full `quality` gate at red time is no fix: the code under test does not exist yet, so type checks fail there for good reasons.

## Stories

As someone shipping unattended, I want a linter false positive in an acceptance test to be suppressed where it is, without asking me, so that a build does not stop on a finding that changes nothing the test checks.

## Acceptance criteria

- **AC-160.1** Given an acceptance test whose only change since the red commit is added linter-suppression comments, when `cplat spec test-diff` checks it, then the change is accepted as `lint suppression only`. The comments are `//nolint:<rule>` (Go), `# noqa: <code>` and `# type: ignore[<code>]` (Python), `// eslint-disable-next-line <rule>` (TypeScript and JavaScript), and `@SuppressWarnings("<name>")` (Java), each naming at least one rule.
- **AC-160.2** Given a change that adds a suppression comment and also changes code, a suppression without a rule (`//nolint`, `# noqa`, `# type: ignore`, `// eslint-disable-next-line` alone), or a file-wide suppression (`//nolint` on the package clause, `# ruff: noqa`, `/* eslint-disable */`), when test-diff checks it, then the change is refused as today.
- **AC-160.3** Given a build task whose `quality` gate fails only on findings in acceptance test files, when the coder handles it, then the coder adds the linter's own suppression comment, naming the rule, on the lines it names, with a reason after it where the linter allows one. The coder brief and the shape's coder agents say so, and the commit names the suppressed rules.
- **AC-160.4** Given the verification phase, when the reviewer reads the build, then every suppression added to an acceptance test after the red commit is listed in `verification.md` with its rule and line, so a suppression is visible in the PR.

## Non-goals

- Suppressions in production code: they stay the coder's ordinary choice under the quality gate.
- Linting acceptance tests at red time (Phase 1).
- Changing a linter's configuration (for example turning `bodyclose` off for tests).

## Assumptions

- **A1** Only line-level suppressions that name a rule are accepted, so a suppression never hides more than the one finding (other option: also file-wide ones; affects AC-160.1, AC-160.2).
- **A2** The coder suppresses without asking. The reviewer lists each suppression, so the person sees it in the PR (other option: escalate each suppression to the person; affects AC-160.3, AC-160.4).

## Open questions

## Changelog

- 2026-11-08 drafted from #570, found by the system-ship benchmark; approved by the user on 2026-11-08 (as 158; renumbered to 160, another session had merged a spec 158).
- 2026-11-09 building
- 2026-11-09 done
