---
spec_id: 172-builds-catch-problems-before-the-pull
title: Builds catch problems before the pull request
status: done
priority: P1
shape: platform
tracks: [628, 629, 630, 631, 632]
---

# 172 — Builds catch problems before the pull request

## Problem

Building specs 167 and 168 found five problems only at the pull request, in CI or in the review, although the build could have caught each one itself. `cplat spec test-diff` called the coders' own new unit tests changed acceptance tests because their docstrings named `AC-167.n`, and stopped the 167 build four times until someone removed the ids by hand (#628). Every parallel coder ran the whole `test-fast` suite (about 5 minutes) because `cplat quiet test-fast` takes no arguments; 13 sweep tasks of 168 and 8 tasks of 167 at once overloaded the machine and the orchestrator told coders to call pytest directly, against the shell rule (#629). Spec 167's new acceptance tests passed locally but failed about 1 run in 5 under parallel load, and a coder's unit test raced on the slower CI runner: one red CI round (#630). A coder merged another task's branch without sign-off, `cplat component build merge` took it, and only the DCO check of `cplat platform pr-check` found it at the PR: 67 commits rewritten (#631). Spec 168's review took three cycles because sweep agents classed instructing sentences with a condition clause as `not a rule`, so `cplat platform rules check` never applied AC-168.3 to them (#632).

## Stories

As someone shipping unattended, I want `test-diff` to judge only the tests the red-tests step froze, so that a coder's own unit test that names its criterion does not stop the run.

As a coder in a parallel batch, I want to run only my task's tests, so that parallel coders do not overload the machine and I never need a raw test command.

As someone shipping unattended, I want the build to run the new tests a few times under load before the PR, so that a flaky test is fixed by the tester and not first seen red in CI.

As a platform maintainer, I want an unsigned commit refused when its task branch is merged, so that the DCO check never fails at the PR.

As a platform maintainer, I want the rules check to catch an instruction hidden as `not a rule`, so that a condition list does not slip past AC-168.3.

## Acceptance criteria

- **AC-172.1** Given a `building` spec whose red-tests step committed acceptance test files (the commits from its first "acceptance tests for <spec id>" commit up to the frozen commit of spec 169), and later commits that add a new test file and add a test to an existing test file the red-tests step did not touch, both naming a criterion id of that spec, when `cplat spec test-diff <red>` runs without file arguments (also with `--task`), then neither file is reported; a change to a file the red-tests step committed (including its deletion) is still checked and reported as before.
- **AC-172.2** Given no "acceptance tests for <spec id>" commit of a `building` spec between the given base and HEAD, when `cplat spec test-diff <base>` runs, then it selects files as before this spec (changed test files naming a criterion of a `building` spec) and prints one line that it fell back to that selection.
- **AC-172.3** Given a repo whose `test-fast` script runs a test runner (the platform repo, the Python, Go, Java and web templates), when `cplat quiet test-fast -- <args>` runs, then the arguments reach the test runner unchanged and the output, log and flaky handling are as for `cplat quiet test-fast`; in the platform repo and the Python templates, `-- <test file>` runs only that file's tests and `-- -k <expr>` only the matching tests. Arguments for any other script, or arguments without `--`, are refused with the usage line and exit 2, as today.
- **AC-172.4** Given a coder prompt of build Phase 2, when it is written, then its `Commands` name `cplat quiet test-fast -- <the task's test files>`, the task's test files being the acceptance test files of its `covers` criteria from the trace plus the test files in its `files`, and its "Done when" runs that command, not the whole suite; the whole suite still runs once when all tasks are merged (build 2.5) and in Phase 3.
- **AC-172.5** Given `cplat quiet test-fast --repeat <n> -- <tests>` with n from 2 to 5, when it runs, then it starts n runs of those tests at the same time; all pass → exit 0; a test that failed in any run is run once more alone, and if it passes it is printed as `flaky under load: <test> (failed in <k> of <n> runs)`, recorded in the run record's `flaky_tests`, and the command exits 3 (never 0); a test that fails alone too, or a failure not attributable to named tests, prints the failure summary and exits 1. `--repeat` without tests after `--`, or n outside 2 to 5, is refused with exit 2.
- **AC-172.6** Given build Phase 2 with every acceptance test passing (2.5), when the build goes on, then before Phase 3 it runs `cplat quiet test-fast --repeat 3 --` on the spec's acceptance test files and the test files the build's tasks added or changed that `test-fast` runs; exit 1 sends the failing tests to a coder of a covering task as in 2.5; exit 3 sends each flaky test with the runs' failure output to the tester as a harness problem, which it fixes in the harness (fixtures, helpers, fakes, process clean-up) without changing an assertion, and the repeated run follows; a fix that needs a change to a frozen acceptance test file goes through the person's approval as today; tests still flaky after 2 such rounds escalate the build, naming each test.
- **AC-172.7** Given the platform repo and a task branch that brings in at least one commit (a merge commit included) without a `Signed-off-by` line, when `cplat component build merge <id> <task> <branch>` runs, then nothing is merged, the feature branch's HEAD and tree are unchanged, the task is neither set aside nor counted as a conflict, and the command exits non-zero (not 3 or 4) naming each such commit (short sha and subject) with the hint to rebase the branch with `--signoff` onto its merge base in the task's worktree; build Phase 2 then does that rebase and merges again without asking. In other repos the merge works as before.
- **AC-172.8** Given a rule register entry classed `not a rule` whose sentence contains a condition clause ("only when", "only if", "unless", "except") and reads as an instruction (it contains "you" or "your", or its first word, after list markers, emphasis, a leading label ending in a colon and a leading "If …," or "When …," clause, is a verb in the check's list of imperative verbs), when `cplat platform rules check` runs, then it fails with the file, the line, the text and the hint to class it `practice` and state its purpose; for example "Read the design only when the brief lacks a fact." and "Merge the pull request, unless the user said not to merge." fail, while "The check runs only when a spec is building." still passes as `not a rule`.

## Non-goals

- Changing when the acceptance tests freeze (spec 169) or what a tightening may change (spec 165).
- Repeating the whole suite, `test`, `ci` or the e2e (Playwright) tests under load; only the spec's acceptance tests and the build's changed test files repeat.
- Letting an agent change a frozen acceptance test to fix a flaky harness without the person's approval.
- Adding a sign-off to someone's commits inside `cplat component build merge`; the merge refuses and the build rebases in the task's worktree.
- A DCO requirement or merge check in generated repos, which require no sign-off today.
- A subset for the gitops shapes' `test-fast`, which renders manifests and runs no test runner.
- An override that lets a flagged `not a rule` entry stay; the sentence is re-classed or reworded.
- The unattended-run fixes of spec 171; the two specs are independent.

## Assumptions

- **A1** The frozen files are the test files the red-tests step committed, still limited to files that name a criterion of a `building` spec, so helpers and fixtures the tester committed stay open to harness fixes (other option: every file the red-tests step committed; affects AC-172.1, AC-172.6).
- **A2** Without a red-tests commit to read, `test-diff` falls back to today's selection and says so (other option: refuse; affects AC-172.2).
- **A3** Only `test-fast` accepts arguments, after `--`; every other script keeps refusing them (other option: every script; affects AC-172.3).
- **A4** The platform repo's `test-fast` runs only the given tests when arguments are given, instead of the whole test tree plus them (other option: append them to the whole run; affects AC-172.3).
- **A5** A coder's test files are its covered criteria's acceptance test files plus the test files in its `files`; the whole suite runs only at build 2.5 and in Phase 3 (other option: the coder also runs the whole suite once before it returns; affects AC-172.4).
- **A6** The load run starts 3 runs at the same time by default, 2 to 5 allowed, and is refused without named tests so it never repeats the whole suite (other option: 5 runs one after another; affects AC-172.5, AC-172.6).
- **A7** A flaky result under `--repeat` exits 3, unlike the single flake rerun of AC-165.7, which passes with exit 0, because the point is to fix it before CI (other option: exit 0 with a warning; affects AC-172.5).
- **A8** The load run sits between build 2.5 and Phase 3, at most 2 tester rounds, then the build escalates (other option: go on and list the flaky tests in the PR; affects AC-172.6).
- **A9** The tester fixes a flaky harness only in files that are not frozen; a fix that needs a frozen acceptance test goes to the person as today, since a timing fix in a frozen test can loosen it in a way the mechanical tightening check does not see (other option: accept it through the tightening check of AC-165.1; affects AC-172.6).
- **A10** The sign-off check in `build merge` applies only in the platform repo, the one repo whose PR checks require sign-off (other option: every repo; affects AC-172.7).
- **A11** `build merge` refuses an unsigned commit instead of adding the sign-off itself, and the build rebases with `--signoff` in the task's worktree (other option: the merge rebases with `--signoff` on its own; affects AC-172.7).
- **A12** "Reads as an instruction" is decided by "you"/"your" or a first word from a fixed list of imperative verbs kept with the check, so the result is deterministic (other option: flag every `not a rule` entry with a condition clause; affects AC-172.8).
- **A13** The new rules-check finding fails the check like the other findings (168, A5), and the register entries it flags on `main` are re-classed in the same change, so AC-168.6 keeps holding (other option: a warning only; affects AC-172.8).

## Open questions

None.

## Changelog

- 2026-11-10 created
- 2026-11-10 approved
- 2026-11-10 building
- 2026-11-10 done
