---
spec_id: 194-a-system-ship-wait-returns-before-the
title: A system ship wait returns before the Bash limit
status: done
priority: P1
shape: platform
---

# 194 — A system ship wait returns before the Bash limit

## Problem

`cplat system ship next --wait` has a timeout of 540 seconds, but AC-148.7 starts that timeout again whenever a running repo reaches a new phase or commit, for up to six timeouts (about 54 minutes). Claude Code's Bash tool stops a foreground call after 10 minutes and moves it to the background. In journeys 11 and 12 the coordinator's wait was moved to the background this way. In journey 12 the coordinator then wrote `while pgrep -f 'system ship next --wait'; do sleep 5; done`. That loop matches its own shell and never ends, although the Stop hook had asked for a blocking read of the background task (finding J12-1). A wait that always returns inside one Bash call removes the background move and the loop it led to.

## Stories

As the `/system:ship` coordinator, I want each `next --wait` call to end within its timeout and tell me whether the repos are still making progress, so that I wait in the foreground with plain repeated calls and never need a background task or a polling loop.

As someone running a system ship unattended, I want a run whose repos keep making progress never escalated for slowness, and a run whose repos stall escalated as today, so that long builds finish and stuck ones stop.

**Repos:** sdlc-foundry (the platform: `cplat` and the system plugin).

## Acceptance criteria

- **AC-194.1** Given `cplat system ship next --wait --timeout T` (default 540) with at least one repo running and none finishing or escalating, when the call runs, then it ends no later than T plus one poll interval (10 seconds) after it started, whether or not a repo made progress, so the default call ends within 550 seconds. A repo whose ship ends or escalates during the call is still recorded and its action returned at the first poll after its result, as AC-186.1 says. (replaces AC-148.7)
- **AC-194.2** Given the same call, when at least one running repo made progress during it (a new phase, a new commit, or its session started again under AC-155.5) and the timeout runs out with the action still `wait`, then it prints the `wait` action as `next` prints it, followed by exactly one line `WAIT: repos still running, progress in the last <T>s; run the same wait again`, and exits 0. With `--json`, standard output holds only the action as `next --json` prints it, and the `WAIT:` line goes to standard error with the phase lines.
- **AC-194.3** Given the same call, when no running repo made progress for the whole call and the timeout runs out, then it prints today's `TIMEOUT: action still wait, no repo made progress for <T>s; running: …` line and `run the same wait again`, and exits 2.
- **AC-194.4** Given the `/system:ship` instructions, when they handle `next --wait`, then an action `wait` with exit 0 is run again as the same wait, and the run escalates with cause `environment` only after three `TIMEOUT:` results in a row: a `wait` result between them starts the count again. The changed rule has a rules-register entry (spec 168), and the instructions stay within their recorded size.

## Non-goals

- A limit on the total length of a system ship whose repos keep making progress. Each component ship has its own limits.
- Changing `cplat component ship wait`, `cplat system ship land` or any other wait's timeout.
- Capping a `--timeout` the caller passes above the Bash limit. The default and the instructions stay below it.
- Changing when `next --wait` returns `answer`, `start` or `escalate` (spec 186).

## Assumptions

- **A1** The deadline counts from the call's start and allows one poll interval of overrun, because a poll that has begun (including recording a finished repo) is completed (other option: a hard deadline that cuts a poll short; affects AC-194.1).
- **A2** A progress-ended call exits 0 and prints the `wait` action, so that the instructions' existing "go on with the printed action" rule runs it again without a new exit code (other option: a distinct exit code 3; affects AC-194.2, AC-194.4).
- **A3** The extra line starts with `WAIT:` and has the exact wording of AC-194.2, so that it reads like the other wait outcome lines (`REACHED:`, `TIMEOUT:`) (other option: no extra line, the action alone; affects AC-194.2).
- **A4** A repo session started again by AC-155.5 counts as progress, as it already restarts the timeout today (other option: only phase and commit count; affects AC-194.2, AC-194.3).
- **A5** The three-TIMEOUT escalation counts consecutive `TIMEOUT:` results only, so that a long build with occasional quiet stretches is not escalated (other option: three in the whole run; affects AC-194.4).

## Open questions

## Changelog

- 2026-11-13 created
- 2026-11-13 approved
- 2026-11-13 building
- 2026-11-13 done
