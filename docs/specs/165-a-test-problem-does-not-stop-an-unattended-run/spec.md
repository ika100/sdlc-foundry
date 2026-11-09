---
spec_id: 165-a-test-problem-does-not-stop-an-unattended-run
title: A test problem does not stop an unattended run
status: approved
priority: P1
shape: platform
tracks: [595, 582, 583]
---

# 165 — A test problem does not stop an unattended run

## Problem

Since 5.14.3 most stops of an unattended build that need the person come from tests, not from the feature. Acceptance tests are fixed once build Phase 1 committed them, and only the person may approve a change (`references/build-test-approval.md`). Three cases stop a run although the obvious answer is known:

- The reviewer finds an acceptance test looser than its criterion: journey 7's AC-002.4 test checked two requests together under 10 s, the criterion says each answers 503 within 5 s. Nobody may tighten the test, so the system ship stopped (#595).
- An e2e acceptance test is frozen without ever having run. Phase 1 checks the red tests with `test-fast` only, which in a web repo runs Vitest, not Playwright; a Playwright test that cannot even start its server (a `NaN` port) was frozen and failed every time, and the run needed a person (#582).
- A flaky test outside the change fails once. The session cannot tell a flake from a regression and escalates; a 3.2 s run against a 3 s limit failed the eval gate once (#583).

## Stories

As someone shipping unattended, I want a test problem with an obvious answer resolved without me, and every such change listed where I review the work, so that a run stops only on decisions that are really mine.

## Acceptance criteria

- **AC-165.1** Given an acceptance test changed since the red commit, when `cplat spec test-diff <red> --tighten <file>... --reason '<why>'` runs, then each file is accepted and recorded only when its criterion ids are unchanged, no test of the red version is removed or newly skipped, and it has at least as many assertions as before; otherwise it is refused with the first reason and nothing is recorded for it.
- **AC-165.2** Given a recorded tightening, when `cplat spec test-diff <red>` checks the file again, then it passes as `tightened by an agent: <why>` while the content is unchanged; any later change is checked again as today.
- **AC-165.3** Given a recorded tightening, when the PR's "How this was built" block is written, then it lists the file, the task and the reason as a tightened test, apart from the changes the person approved.
- **AC-165.4** Given a reviewer verdict that a criterion is not met because its acceptance test is looser than the criterion as written, when the build handles it, then the tester (acceptance mode) tightens that test to the criterion and nothing else, `cplat spec test-diff $RED --tighten` records it with the reviewer's reason, a test that then fails goes to a coder as any not-met criterion, and the reviewer runs again; `verification.md` lists every tightened test. Loosening, deleting or skipping a test still needs the person.
- **AC-165.5** Given build Phase 1, when the trace names acceptance test files that `test-fast` does not run (Playwright specs under `e2e/` in a web repo), then they run once with `cplat quiet e2e`, and one that fails before any assertion about the missing behaviour (the server does not start, a harness error) goes back to the tester as a wrong failure before the tests are frozen.
- **AC-165.6** Given the web tester, when it writes a Playwright test, then it never starts the app inside a test: the server comes from `playwright.config`'s `webServer`, and a test varies the server's environment through `webServer.env` and a stub started there.
- **AC-165.7** Given `cplat quiet test-fast` fails only on test failures (pytest, Go, Surefire or Vitest, at most 5 tests), when it runs those tests again alone once (`devbox run test-fast -- <the tests>`) and they pass, then it exits 0, prints them as flaky, and records them in the run record's `flaky_tests`; any other failure, more tests, or a failing rerun keeps the first result.

## Non-goals

- Running a failing test at the base commit to find a failure that is already there (#583, option 2): a flake rerun covers the timing case seen; a test red on main is a fix of its own.
- An agent loosening, deleting or skipping an acceptance test: always the person's decision.
- A mechanical proof that a change makes a test stricter: the check refuses the obvious weakening (a removed test, fewer assertions, a new skip), and the PR lists every tightening for the person.
- Reruns for `test`, `ci` or e2e: their coverage thresholds and run time make a partial rerun wrong or slow.

## Assumptions

- **A1** Assertions are counted by pattern (`assert`, `expect(`, `assertThat(`, `assert*(`, `t.Error*`/`t.Fatal*`, `require.`/`assert.` calls); a test is found by its definition (`def test_…`, `it(…)`/`test(…)`, `func Test…`, an `@Test` method) (other option: per-language parsers; affects AC-165.1).
- **A2** Five failing tests is the limit for a flake rerun; more is not a flake (affects AC-165.7).

## Open questions

None.

## Changelog

- 2026-11-09 created from #595, #582 and #583 (#570 was fixed by spec 160); approved as the user asked ("go on, I follow your proposals"): agents may tighten a frozen acceptance test, every tightening is listed in the PR.
