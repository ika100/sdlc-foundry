---
spec_id: 208-test-runs-leave-the-developer-s-disk-as
title: Test runs leave the developer's disk as they found it
status: draft
priority: P1
shape: platform
tracks: [810, 811]
explored: true
---

# 208 — Test runs leave the developer's disk as they found it

## Problem

Every run of the platform's test suite fills the developer's disk and never gives the space back. The cplat tests run inline scripts through uv in a fresh temporary repo per test, directly and through cplat itself, and uv keeps one script environment per path in the developer's own uv cache: 26,315 environments (about 33 GB) piled up in one day, and the cache once grew to about 460 GB and filled the disk to 99% (#810). pytest also leaves the temporary directories of every run behind: 20 runs held 35 GB (#811). The suite runs many times a day, by hand, in `ci-local` and in the unattended build and ship loop, so a full disk stops all work on the machine. A test run should leave the developer's machine as it found it.

## Stories

- As a platform developer, I want a test run to leave my uv cache untouched, so that running the suite all day never fills my disk.
- As a platform developer, I want a passing test run to clean up after itself, so that I never have to delete test leftovers by hand.
- As a platform developer, I want a failing test run to keep the files of its failed tests for a while, so that I can look at what went wrong.
- As someone running several worktrees or dispatcher slots at once, I want parallel test runs to stay out of each other's way, so that one run's cleanup never breaks another run.

## Acceptance criteria

- **AC-208.1** Given the developer's uv cache before a run of the cplat tests through any of their entry points (`devbox run test-fast` with or without arguments, `scripts/ci-local.sh`, the CI test shards, and a plain serial or `-n auto` run of the suite), when the run ends, passing or failing, then the cache has the same entries as before (none added, changed or removed), and every inline-script environment the run created, whether a test ran the script itself or through cplat, lies in a uv cache that belongs to that run only.
- **AC-208.2** Given a run of one of the e2e test scripts, when it ends, passing or failing, then the developer's uv cache has the same entries as before, and the uv cache the script used for its own inline-script runs is gone.
- **AC-208.3** Given a run of the cplat tests in which every test passes, when it ends, then nothing it created under the user's pytest temp root (`pytest-of-<user>` in the system temp directory) remains, including its own uv cache and its shared renders, and the leftovers of earlier runs are untouched except as AC-208.5 says.
- **AC-208.4** Given a run of the cplat tests in which some tests fail (in setup, call or teardown, including a test stopped by the per-test timeout), when it ends, then the temp directories of exactly the failed tests remain, each named so that the test id can be recognised, and the temp directories of its passed tests, its own uv cache and its shared renders are gone.
- **AC-208.5** Given the leftovers of 3 earlier failing runs under the user's pytest temp root, when a fourth run fails, then the leftovers of the oldest of the four are removed and those of the 3 most recent failing runs remain; there are never leftovers of more than 3 runs.
- **AC-208.6** Given two runs of the cplat tests that overlap in time on one machine (two worktrees or dispatcher slots), when one of them ends, passing or failing, then its cleanup removes none of the other run's files, and the other run's result is the same as when it runs alone.
- **AC-208.7** Given a full local `devbox run test-fast` on the same machine before and after this change, when the wall times are compared, then the run after the change takes at most 10% longer; both numbers are recorded in the pull request.

## Non-goals

- cplat's own `uv run` of inline scripts in real worktrees and dispatcher slots: it keeps using the developer's uv cache as today (decided in explore).
- Removing leftovers already on disk from runs before this change, in the uv cache or in the pytest temp root.
- The test setups of generated repos (the templates' own `test` and `test-fast` recipes).
- Caching environments, renders or test results between runs.
- Limiting the size of the developer's uv cache in general.

## Assumptions

- **A1** The run's uv cache lives inside the run's own directory under the user's pytest temp root, so the cleanup of AC-208.3 and AC-208.4 removes it with the rest (other option: a separate per-run cache directory elsewhere, removed on its own; affects AC-208.1, AC-208.3, AC-208.4).
- **A2** Scope is the test entry points only; cplat's own inline-script runs outside tests are unchanged (affects AC-208.1, AC-208.2) (decided in explore).
- **A3** A failing run keeps only the failed tests' directories; its uv cache and shared renders are removed too, because they are large and the failed test's own directory holds what is needed to debug (other option: keep the whole run directory of a failing run; affects AC-208.4).
- **A4** The limit of 3 counts failing runs, the only ones that leave anything behind; passing runs in between do not push a failure's leftovers out (other option: the last 3 runs of any result; affects AC-208.5).
- **A5** A run that is interrupted (Ctrl-C, or `cplat quiet test-fast` giving up after 9 minutes under ADR-108) counts as a failing run for AC-208.4 and AC-208.5, and still leaves the developer's uv cache unchanged (other option: an interrupted run leaves everything for the next run to clean; affects AC-208.1, AC-208.4, AC-208.5).
- **A6** A developer who sets their own uv cache location gets the same guarantee for that location (other option: only the default location is protected; affects AC-208.1, AC-208.2).
- ~~**A7** The run's uv cache starts empty, so inline-script dependencies are fetched once per run as uv does today on a cold cache; network access during tests stays as it is (other option: seed the run cache from the developer's cache without writing to it; affects AC-208.1, AC-208.7).~~ Revised 2026-11-18: the cold cache cost about 60 s per full run and broke AC-208.7; see A10.
- **A8** The time budget is at most 10% longer wall time for a full local run, in line with ADR-108's bounded test time (other option: 5%, or no time criterion; affects AC-208.7).
- **A9** No new environment variable, flag or setup step is needed to run the suite (AC-112.15 stays true) (other option: an opt-in variable; affects AC-208.1).
- **A10** The run's uv cache is seeded from a persistent test-only wheel cache that lies outside the developer's uv cache (in the user's own cache directory, in a folder of the platform's own), so inline-script dependencies are downloaded once per machine and not again on every run; the developer's uv cache stays untouched (AC-208.1 unchanged). The persistent cache holds only downloaded wheels and source archives: a run never writes script environments into it, and only new wheel and archive entries flow back to it after a run. It is bounded: when it exceeds 2 GB at the start of a run, it is emptied and refilled by that run. Two overlapping runs may read and fill it at the same time without breaking each other, and a missing or emptied persistent cache only makes a run slower, never failing (other option: the run's uv cache starts empty and fetches every dependency once per run, as before this revision; affects AC-208.1, AC-208.6, AC-208.7).
- **A11** The run's own directory (its uv cache, shared renders and passed tests' directories) is removed after pytest has printed its summary, by a detached background process, so the removal does not count toward the run's wall time for AC-208.7 and the run's exit code is already set when it starts. A run counts as clean for AC-208.3 and AC-208.4 once that background removal has completed; a test of those criteria waits for it. The removal deletes only the directory of the run that started it, so it never touches the directories of an overlapping run or of the failing runs AC-208.5 keeps, and AC-208.5 counts a passing run whose removal is still in progress as no failing run (other option: remove the run directory in the foreground before the run ends, which measured about 75 s per full run; affects AC-208.3, AC-208.4, AC-208.5, AC-208.6, AC-208.7).

## Open questions

none

## Changelog

- 2026-11-17 created
- 2026-11-17 approved
- 2026-11-17 building
- 2026-11-18 draft: amend: A7 seeds the run's uv cache from a persistent test wheel cache; run dir removed in the background (AC-208.7 measured +28%)
