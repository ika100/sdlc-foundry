---
spec_id: 211-local-tests-run-what-a-change-can-affect
title: Local tests run what a change can affect
status: approved
priority: P1
shape: platform
---

# 211 — Local tests run what a change can affect

## Problem

A local run of the platform's own tests (`devbox run test-fast` without arguments) runs the whole cplat suite: 12,409 tests in 7 min 41 s on 2026-11-20, five times the 2,468 tests that spec 112 measured, and close to the 9-minute limit of `cplat quiet test-fast` (ADR-108). A build or ship of a platform spec runs it several times: at the red-tests check, after the coders, in each verification fix round, and once more in `scripts/ci-local.sh` before the push. Most of those runs follow a change to a handful of files that a few dozen test files can see. Every pull request still runs the whole suite in CI, so the local runs inside the loop repeat work that CI does anyway. A selection by file names (spec 103) does not fit this repo: 233 of the 520 test files run cplat as a subprocess, and 192 read prompts, templates or docs, so neither the import graph nor a name convention shows which tests a change can reach. The platform developer needs local runs that run only the tests a change can affect, decided from what the tests actually touched, and that fall back to the whole suite whenever the platform cannot tell.

## Stories

- As a platform developer, I want `devbox run test-fast` to run only the test files my change can affect, so that a fix round costs seconds instead of minutes.
- As the platform owner, I want the selection to come from what each test read and ran in a recorded full run, and to fall back to the whole suite whenever that record cannot answer, so that a faster local run never hides a broken test.
- As the platform owner, I want CI to keep running every test on every pull request, so that the merge gate does not depend on the selection.
- As a platform developer, I want every run to say what it selected and why, and one flag that runs everything, so that I can trust the selection and step around it.

## Acceptance criteria

- **AC-211.1** Given a usable dependency map (AC-211.6) and a change that no full-run rule of AC-211.3 matches, when `devbox run test-fast` runs without arguments, then pytest runs exactly these test files of `tests/cplat`: the changed and new test files, the test files that failed in the recorded run, and every test file whose recorded dependencies (AC-211.2) include a changed, added or removed file; and the run prints one line with the number of selected test files out of all, the map's commit, and that `devbox run test-fast --full` runs every test.
- **AC-211.2** Given a full run of the cplat tests that records a map, when a test file's dependencies are read from that map, then they hold every repo file that (a) the test file imports, directly or through the modules it imports; (b) the test file, a fixture it uses (of any scope, also when another test file set the fixture up first) or a shared render it copies (spec 112, also when another test built it) opened, listed the directory of, or passed as a subprocess argument (a directory argument counts for every file below it); or (c) a cplat process started from that test, fixture or render, directly or by another process, imported, opened or listed.
- **AC-211.3** Given a run of `devbox run test-fast` without arguments, when one of these holds, then it runs the whole suite, records a new map, and prints the reason: there is no usable map; a changed file is one of the suite's shared files (`tests/cplat/conftest.py` and the modules it imports, the plugins it loads, `tests/cplat/pytest.ini`, `requirements-test.txt`, the selector and the trace module); a changed code or configuration file (`.py`, `.sh`, `.jinja`, `.yml`, `.yaml`, `.json`, `.toml`, `.ini`, `.cfg`, or a file without an extension) is a dependency of no test file in the map; or the selection holds more than half of the test files.
- **AC-211.4** Given the platform repo, when `devbox run test-fast --full` or `devbox run test` runs, then every cplat test runs and a new map is recorded; and `devbox run test-fast <args>` with test files, node ids or pytest options runs exactly what it runs today (AC-172.3), selects nothing and records nothing.
- **AC-211.5** Given `scripts/ci-local.sh`, when it runs without `--full`, then its cplat test step runs the selection of AC-211.1 and AC-211.3 and says so; with `--full`, alone or together with `--site` or `--render` in any order, it runs every cplat test; its other steps are unchanged.
- **AC-211.6** Given the maps recorded in a clone, when a run selects, then the changed files are the difference between the map's commit and the working tree (committed, staged, unstaged and untracked files, plus the files that were uncommitted when the map was recorded); the maps are shared by every worktree of the clone; the run uses the map with the fewest changed files and ignores a map whose commit the clone does not have or that cannot be read; at most 5 maps are kept; and two runs that record at the same time leave readable maps.
- **AC-211.7** Given the CI test jobs and a plain `pytest tests/cplat` (with or without `-n auto` or `--shard`), when they run, then every test runs as before, no map or trace file is written, and no environment variable is added to the tests.
- **AC-211.8** Given a full run that records a map and one without recording, on the same machine and commit, when their wall times are compared, then the recording run takes at most 15 % longer; and in the recorded map, the median cplat module under `scripts/cplat/` is a dependency of at most 20 % of the test files; both numbers are recorded in the pull request.
- **AC-211.9** Given three single changes, each run on its own: a raised exception at the start of the main function of a cplat command module, a broken helper in a module that other cplat modules import, and a changed line in an agent prompt that a test checks, when the whole suite and the selection run for each, then every test file that fails in the whole suite is in the selection; the three results are recorded in the pull request.

## Non-goals

- CI: its test jobs and shards keep running every test (decided with the user).
- Selection below the level of a test file (single tests inside a file).
- The test setups of generated repos (the templates' own `test` and `test-fast` recipes) and spec 103's `cplat validate` rules.
- Making the whole suite itself faster, for example by running cplat in-process instead of as a subprocess (a later spec).
- The e2e tests (`tests/e2e/`) and the documentation site's tests.

## Assumptions

- **A1** `devbox run test-fast` without arguments selects; `devbox run test-fast --full` and `devbox run test` run everything (decided with the user; affects AC-211.1, AC-211.4).
- **A2** `scripts/ci-local.sh` selects by default and runs everything with `--full` (decided with the user; affects AC-211.5).
- **A3** A map is recorded only by a full run started through `test-fast` or `ci-local.sh`; a selected run does not change any map, so a map's dependencies always describe one tree (other option: selected runs refresh the rows of the tests they ran; affects AC-211.3, AC-211.6).
- **A4** The maps live in a folder of the clone's git common directory, so every worktree can use a map another worktree recorded and nothing appears in `git status` (other option: one map per worktree; affects AC-211.6).
- **A5** Subprocesses are traced only when they are cplat itself; another program started from a test (git, copier, a bash script, a repo script) counts through its arguments: the files and directories of the repo it is given (other option: trace every Python subprocess; affects AC-211.2).
- **A6** The trace variable does not start with `CPLAT_`, because the suite removes every `CPLAT_` variable before each test (other option: set it after that fixture; affects AC-211.2).
- **A7** A file that the map ties to no test and that is not code or configuration (for example a Markdown page, an image, a spec) selects nothing (other option: any unknown file runs everything; affects AC-211.3).

## Open questions

none

## Changelog

- 2026-11-20 created
- 2026-11-20 priority P1 proposed: P1: normal bug or feature
- 2026-11-20 approved
