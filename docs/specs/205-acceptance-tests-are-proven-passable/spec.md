---
spec_id: 205-acceptance-tests-are-proven-passable
title: Acceptance tests are proven passable before they freeze
status: approved
priority: P1
shape: platform
---

# 205 — Acceptance tests are proven passable before they freeze

## Problem

In week 46, 63 unattended runs stopped for a decision (12 the week before). Most of them stopped on a frozen acceptance test, not on the feature. In some, the test could never pass as written, because of an error in the test itself (a contradictory fixture, a helper that raises, a type error). In others, an edit that touched no assertion (a comment, a docstring, an import) still counted as a changed test. Today build Phase 1 checks only that the new tests fail. Whether a test fails because the behaviour is missing or because the test is broken is left to the orchestrator's reading, so a test that errors in its own helper is frozen as "red". Example (2026-11-17): spec 157's red-tests unit froze tests whose helper `make_repo` created a directory without its parents, while three tests passed nested paths. The coder may not edit a frozen test, so a person had to approve a one-word fix with `cplat spec test-diff --approve`. On the comparison side, `cplat spec test-diff` already ignores formatting, re-sorted imports (#519) and named lint suppressions (spec 160). In Python a changed docstring or an added or removed import is still refused, and in every other language so is a changed comment. Each such case waits until a session records it with `--tighten` (AC-179.4), or until a person approves it.

## Stories

As someone shipping unattended, I want an acceptance test that errors in its own code sent back to the tester before the tests freeze, so that every frozen test can pass once the feature exists and no person has to approve a fix to a test bug.

As someone shipping unattended, I want an edit to a frozen test that changes no assertion (a comment, a docstring, an import) accepted by `cplat spec test-diff` on its own, so that such an edit never stops a run.

**Repos:** sdlc-foundry (the platform; the behaviour reaches every component repo through `cplat` and the build command).

## Acceptance criteria

Edits that change no assertion.

- **AC-205.1** Given a frozen acceptance test file (any language `cplat spec test-diff` judges) whose only differences from the frozen commit are line or block comments added, changed or removed, when `cplat spec test-diff <red>` runs, then the file passes with the line `no assertion changed: comments` and the command exits 0, with no `--tighten` or `--approve` recorded. Comment markers inside a string literal are not comments: changing `"http://a"` to `"http://b"` is still refused.
- **AC-205.2** Given a frozen Python acceptance test whose only differences are module, class or function docstrings and `import` / `from … import` statements added, removed or reordered at any level (comments too), when `cplat spec test-diff <red>` runs, then it passes with `no assertion changed: <kinds>`, naming each kind found (`comments`, `docstrings`, `imports`). A changed string that is not a docstring, a changed `importlib.import_module(…)` or `__import__(…)` call, or any other changed statement is refused as before.
- **AC-205.3** Given a frozen TypeScript/JavaScript, Go or Java acceptance test whose only differences are static import declarations and comments (`import … from '…'` and `import '…'`; Go `import "…"` lines and `import ( … )` blocks; Java `import …;` lines), when `cplat spec test-diff <red>` runs, then it passes with `no assertion changed: <kinds>`. A changed dynamic `import(…)` or `require(…)` call is refused as before.
- **AC-205.4** Given a change that AC-205.1 to AC-205.3 would accept but that also changes any other line, or that adds, drops or changes a criterion id inside a comment, docstring or import, when `cplat spec test-diff <red>` runs, then the file is refused with the same first reason as before this spec, and the existing type-only, helper and tightening paths (AC-179.4, AC-171.7, AC-165.1) apply unchanged.

Red tests that fail for the right reason.

- **AC-205.5** Given test files in a repo whose `test-fast` runs pytest, when `cplat quiet test-fast --red -- <test files>` runs, then it prints one line per test in those files, giving its class and, for a failure, the exception's last line. The classes are: `missing behaviour` for a failed assertion, a `NotImplementedError`, an `ImportError` or `ModuleNotFoundError` naming a module whose top-level name is the repo's own code (the project's package name, or a module or package under the repo root or `src/`), an `AttributeError` naming a module outside the shape's test globs, or an exception raised in a frame of non-test code; `test error` for a collection error, an error in fixture setup, an `ImportError` or `ModuleNotFoundError` naming any other module outside the test globs (when its top-level package cannot be found at all, the line is `<pkg> is not installed: add it to the dev dependencies`), or any other exception whose innermost frame is in a test file, a `conftest.py` or a test helper (for example a `FileNotFoundError` from a helper's directory creation, or a `TypeError` from calling a helper with wrong arguments); `passes` for a test that passes. The command exits 0 only when every test is `missing behaviour`, 1 otherwise, and 2 with the usage line in a repo whose `test-fast` does not run pytest.
- **AC-205.6** Given build Phase 1 (the `red-tests` unit) in a repo that AC-205.5 covers, when the tester has committed the acceptance tests, then the build runs the check of AC-205.5 on the trace's test files. It sends each `test error` and `passes` line back to the tester, which changes only the tests named, and records each one as `cplat platform runs agent tester --wrong-failure <test>`. The check runs again after every tester round, the test-review fix round of AC-179.6 included. The tests freeze (AC-169.1) only at a commit where the check exits 0. If tests are still not `missing behaviour` after 2 tester rounds, the build escalates with cause `code` before any coder runs, naming each test, its class and its exception line.
- **AC-205.7** Given a frozen acceptance test that fails after the production code of its criterion is merged, with an exception whose innermost frame is in a test file, `conftest.py` or test helper (not an assertion), when the build handles it (build 2.5 or a task's test run), then the tester (acceptance mode) gets that test and the exception as a harness fix, with no person asked. The tester changes only test code and records the change with `cplat spec test-diff $RED --tighten <file> --task <task> --reason '<test>: <exception line>'`, and the PR's "How this was built" block lists it with the tightened tests (AC-165.3). A fix that the check of AC-179.4 or AC-171.7 refuses (a changed assertion line, test definition, criterion id or an added skip) goes to the person as today.
- **AC-205.8** Given a spec that was amended after an earlier build (its Changelog has a `done` line before the amendment), when build Phase 1 runs the check of AC-205.6, then only the tests that trace to a criterion that is new or whose text changed since the spec's last `done` commit are judged, and each of them must be `missing behaviour`. Every other test of the trace must pass and is printed as `passes (not judged: <criterion> unchanged)`. The check exits 0 when every judged test is `missing behaviour` and every unjudged test passes. An unjudged test that fails is printed as `regression`, is not sent to the tester, and makes the build escalate with cause `code` before any coder runs, naming the test and its exception line. A spec built for the first time is checked as in AC-205.6, with every test judged (#1094).

## Non-goals

- Proving passability by writing a throwaway implementation of the design before the freeze: the classification of AC-205.5 and the existing test review (AC-179.5) catch broken tests without a second implementation in each build.
- Mechanical classification for Go, Surefire (Java) and Vitest runners: those repos keep today's Phase 1 check (the orchestrator sends back a test "erroring for another reason") and the e2e check of AC-165.5.
- Accepting other changes without a record: type annotations, casts, fixture data and helper logic keep the recorded `--tighten` path (AC-179.4, AC-171.7), because they can change what a test checks.
- Changing what a tightening may change (spec 165), when the tests freeze (spec 169), or the flaky-test handling (spec 172).
- Letting a coder edit a frozen acceptance test: the tester makes the harness fix of AC-205.7.

## Assumptions

- **A1** Only comments, Python docstrings and static imports pass without a record. Type annotations and casts keep the AC-179.4 path, which the session records with `--tighten` (other option: also accept every type-only change without a record; affects AC-205.1, AC-205.2, AC-205.3).
- **A2** An edit accepted as `no assertion changed` is printed by `cplat spec test-diff` but not listed in the PR, like a formatting change (other option: list it in "How this was built"; affects AC-205.1, AC-205.2, AC-205.3).
- **A3** Mechanical classification covers pytest only (the platform repo and the Python templates, where the W46 stops and the spec 157 case happened); other runners are a follow-up (other option: Vitest, Go and Surefire in this spec too; affects AC-205.5, AC-205.6).
- **A4** "Proven passable" means each red test fails only because the behaviour is missing (AC-205.5), together with the existing test review against the contract (AC-179.5). The tester writes no stub implementation (other option: the tester writes a throwaway stub of the contract and shows each test passes against it; affects AC-205.5, AC-205.6).
- **A5** A failure counts as `missing behaviour` when it is an assertion failure, a `NotImplementedError`, an import error naming the repo's own code, an attribute error naming a non-test module, or an exception raised in non-test code; a missing third-party or standard-library module is a `test error`, so an environment problem never passes as proof (#956); everything raised in test code, at collection or in fixture setup is a `test error` (other option: only assertion failures count as `missing behaviour`; affects AC-205.5).
- **A6** A red test that already passes is sent back like a test error, because it proves nothing about the missing behaviour. For an amended spec this holds only for the tests of new or changed criteria (AC-205.8), because the tests of criteria that are already built are meant to pass (other option: report it and freeze anyway; affects AC-205.5, AC-205.6, AC-205.8).
- **A7** The tester gets at most 2 rounds for wrong failures, then the build escalates with cause `code` before Phase 2. A test known to be broken is never frozen, because it would stop the run later at a higher cost (other option: freeze after 1 round and list the broken tests in the PR; affects AC-205.6).
- **A8** The red check is a `--red` mode of `cplat quiet test-fast`, so its output, log and quiet handling match the other test runs (other option: a separate `cplat spec red-check` command; affects AC-205.5).
- **A9** Priority stays P1: the platform stays usable, because a person can answer each stop (other option: P0 as the retro marked it; affects none).
- **A10** A test is judged by the criteria it traces to: new or changed since the last `done` commit of the spec, compared by the criterion's text. Which test files changed is not used, because a change to an old test file would pull its old tests back in (decided by the user; other option: judge the test files that differ from the previous build; affects AC-205.8).
- **A11** The unjudged tests are run too, and one that fails blocks the build as a `regression`, because the amendment must not break behaviour that is already built (decided by the user; other option: run only the judged tests; affects AC-205.8).

## Open questions

None.

## Changelog

- 2026-11-17 created
- 2026-11-17 approved
- 2026-11-18 building
- 2026-11-20 done
- 2026-11-23 amended (#956, decided by the user): an import error is `missing behaviour` only when it names the repo's own code; a missing third-party package is a `test error` that names the dev dependency to add (AC-205.5, A5)
- 2026-11-27 amended (#1094, decided by the user): an amended spec's red check judges only the tests of new or changed criteria; the other tests must pass, and a failing one escalates as a regression (AC-205.8, A6, A10, A11)
- 2026-11-27 approved; the old plan is plan.v1.md
