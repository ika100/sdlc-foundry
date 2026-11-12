---
spec_id: 185-a-hung-test-fails-fast-and-names-itself
title: A hung test fails fast and names itself
status: approved
priority: P1
shape: platform
---

# 185 — A hung test fails fast and names itself

## Problem

On 2026-11-11 spec 184 made a session that ends within 60 seconds with no output a usage-limit pause (AC-184.2), which sleeps 5 to 60 minutes in real time. 16 older `cplat` tests used a silent fast fake `claude`, so they now slept, and `cplat quiet test-fast` hung for over 2.5 hours at about 95 %. The verification session's background commands are cut after about 10 minutes and the suite's output is buffered. The session saw "no output" three times and could not tell slow from stuck. Nothing in the suite stops a test that hangs or sleeps, and nothing names it. The hang was not even new: the 184 escalation at 20:19 had already named it, and a decision ("older silent fakes print a line") was recorded in the spec's design. That decision never became a plan task, so nobody did it. Spec 178 forbade fixed sleeps by a static check (AC-178.6), but a sleep inside the code under test, reached through a fake, passes that check. And nobody can see whether the suite gets slower, because CI keeps no test times.

## Stories

As the platform maintainer running the suite (or an agent verifying a build), I want a hung or sleeping test to fail within minutes and name itself, so that a hang costs one short red run instead of hours of waiting.

As an unattended ship, I want a decision taken on an escalation to become a plan task before the ship goes on, so that the decision is carried out and not only recorded.

As the platform maintainer, I want each CI run to record the suite time and the slowest tests, and the weekly retro to show the trend, so that a slower suite is visible before it costs a ship.

**Repos:** sdlc-foundry (the platform; `cplat quiet` and the ship prompts reach every component and system repo).

## Acceptance criteria

A hung test fails and names itself.

- **AC-185.1** Given a test of the `cplat` suite whose setup, call or teardown runs longer than 120 seconds, when the suite runs (`devbox run test-fast`, `pytest tests/cplat` with or without `-n auto` as in AC-112.15, a CI shard, or `scripts/ci-local.sh`), then that test is reported failed with its test id, the limit of 120 seconds and the stack where it was stopped. The other tests still run and report, and the run exits non-zero.
- **AC-185.2** Given the repository, then `requirements-test.in` lists exactly the five top-level packages pytest, pytest-xdist, pytest-timeout, pyyaml and ruamel.yaml, unpinned, and `requirements-test.txt` pins each of them and each of their dependencies to an exact version, compiled from it by `uv pip compile`. The check of AC-127.5 fails on pytest-timeout installed without that file, as it does for the other four. (replaces AC-127.4)
- **AC-185.3** Given a test of the `cplat` suite whose own process (the test, its fixtures and the threads they start) calls a real sleep that would take that test's total real sleep time over 1 second, when the sleep is called, then it does not sleep. The test fails at once with `real sleep of <s> s at <file>:<line> takes this test over 1 s; wait for an event or a file, or use the fake clock`, even if its assertions would pass. Sleeps of at most 1 second in total, sleeps on the fake clock, and sleeps inside fake programs that run as separate processes (the marked ones of AC-178.6) do not fail a test.
- **AC-185.4** Given `cplat quiet test-fast` (with or without test arguments, and each run of `--repeat`) in a repo whose test-fast runs pytest, when the run has not ended 9 minutes after it started, then `cplat quiet` stops it and every process it started. It prints `FAILED (gave up after 9 min): devbox run test-fast (log: <path>)`, then one line `still running: <test id>` for each test that started and did not finish (at most 20, then `... and <n> more`), and exits 124. It does not run the flaky rerun of AC-165.7. A run that ends within 9 minutes prints and exits as before.
- **AC-185.5** Given `cplat quiet test-fast` in a repo whose test-fast does not run pytest, when the run has not ended after 9 minutes, then it stops the run and every process it started as in AC-185.4, prints the same first line followed by `still running: not reported by this test runner`, and exits 124.

A decision becomes a task.

- **AC-185.6** Given the component and system ship prompts, when `cplat platform rules check` runs, then each prompt states, with a reason clause, that a decision taken on an escalation that needs code, test or document work becomes a task in the spec's plan before the ship goes on. Each sentence has a register entry classed `practice` with source spec 185, the check passes, and the total size of the plugin prompts is not above the recorded baseline (spec 180).

The suite's time is measured.

- **AC-185.7** Given a CI run that runs the `cplat` shards, when a shard ends (green or red), then its shard report holds the shard's pytest wall time in seconds and its 15 slowest tests, each with its id and its seconds (setup, call and teardown together). The job that checks the shards' coverage prints `suite time: <sum> s over 4 shards (slowest shard <n> s)` and the 15 slowest tests of the whole run, one per line. On a push to `main` it keeps these numbers as an artifact for 35 days. A shard report without the new fields still passes the coverage check of AC-112.10.
- **AC-185.8** Given the weekly retro (spec 090), when its report is built, then it has a section "Test suite time". For the retro week and each of the 3 weeks before it, the section shows the number of `main` CI runs with timing data, their median suite time and their median slowest-shard time. It also lists the 15 slowest tests of the retro week by their median seconds over that week's runs, each with the number of runs. A week without data shows `no data`. Timing data that cannot be read gives `not available: <reason>` and does not fail the retro.

## Non-goals

- Running the whole suite after each build batch (it would add 30 to 40 minutes per ship).
- A suite-time ratchet that fails a slower change, and safety checks for pull requests that speed up the suite; these come later, with the data of AC-185.7 and AC-185.8.
- Per-test limits or sleep checks for the test suites of generated repos, the template smoke jobs or the e2e cluster test.
- Streaming progress from `cplat quiet` while the suite runs; it stays quiet and ends within its limit instead.
- A `cplat` check that enforces the decision rule of AC-185.6 (spec 168 Non-goals: new enforcement is a follow-up spec).
- Repeating spec 178: its static check for fixed sleeps (AC-178.6) and its stress runs (AC-178.5) stay as they are.

## Assumptions

- **A1** The per-test limit is 120 seconds for every test, with no per-test override, because the slowest shard takes at most 75 seconds (AC-112.12) and the seam test at most 120 (AC-178.7) (other option: a marker that raises one test's limit with a reason; affects AC-185.1).
- **A2** The sleep limit counts the total real sleep time of one test, not a single call, and fails at the sleep call that would cross it, so that a 5-minute pause fails at once (other option: fail only a single sleep over 1 s, judged after the test; affects AC-185.3).
- **A3** Real sleeps inside fake programs that run as separate processes are not counted, because AC-178.6 already allows them with a marker (other option: count them too; affects AC-185.3).
- **A4** `cplat quiet test-fast` gives up after a fixed 9 minutes, below the about 10 minutes after which a session's background command is cut, with no setting per repo (other option: 20 minutes, or a repo setting; affects AC-185.4, AC-185.5).
- **A5** The wall-time limit applies to `cplat quiet test-fast` in every repo shape, and tests are named only where pytest runs; elsewhere the output says they are not reported (other option: the limit only in the platform repo; affects AC-185.4, AC-185.5).
- **A6** A run that gives up exits 124, the exit code of `timeout`, and lists at most 20 running tests (other option: exit 1; affects AC-185.4, AC-185.5).
- **A7** The decision rule goes into the component and system ship prompts as a `practice` with source spec 185, since no issue tracks it and an `experience` rule needs one (other option: `experience` with a new issue; affects AC-185.6).
- **A8** The trend uses CI runs of pushes to `main` only, kept as an artifact for 35 days, which covers the retro's 4 weeks; pull-request runs keep their shard reports for 1 day, as today (other option: pull-request runs too; affects AC-185.7, AC-185.8).
- **A9** The retro reads the timing artifacts of the public platform repo through the GitHub access it already has, with no new secret or permission (other option: CI writes the numbers into the run store, which needs a write secret in CI; affects AC-185.8).
- **A10** "Suite time" is the sum of the 4 shards' pytest wall times, shown next to the slowest shard's time (other option: the slowest shard only; affects AC-185.7, AC-185.8).

## Open questions

None.

## Changelog

- 2026-11-12 created
- 2026-11-12 approved
