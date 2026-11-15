---
spec_id: 202-a-waiting-session-makes-no-model-calls
title: A waiting session makes no model calls
status: done
priority: P1
shape: platform
tracks: [750]
---

# 202 — A waiting session makes no model calls

## Problem

On 2026-11-14 the dispatcher's land unit of spec 176 (PR #732) started `cplat component ship land` as a background task and ended its turn to wait. The Stop hook refused the stop (`waiting: cplat component ship land …`; "the wait above is still running", AC-171.8), and a refused stop starts a new turn at once. The session answered in one line and tried to stop again, about every 1.5 seconds: 921 model calls in 44 minutes, each rereading about 280k tokens of context. That is about 150M tokens, and the unit reached 806M before the usage limit stopped it (issue #750). `cplat dispatch pause` did not stop it, because a paused unit stops only at its next checkpoint and a looping session never reaches one. Nothing in the platform noticed that the session was calling the model without doing anything.

## Stories

As the platform owner running the dispatcher, I want a session that waits for a running `cplat` wait to make no model calls until the wait ends, and then to read the wait's result and go on, so that waiting costs no tokens.

As the platform owner, I want an unattended session that calls the model again and again without progress to be stopped within minutes, with the cause shown in `cplat dispatch inbox` and `status`, so that one defect cannot burn a day's tokens.

As the platform owner, I want `cplat dispatch pause` to reach every running unit at its next turn, so that pausing works even when a session never reaches a checkpoint.

**Repos:** sdlc-foundry (the platform: `cplat`, the Stop hook of the component and system plugins, `cplat headless` and the dispatcher; the behaviour reaches every repo that ships unattended).

## Acceptance criteria

Words used below. A **wait** is a `cplat` wait of ADR-082 that a session started in the run's checkout and that is still running (`cplat pr wait`, `cplat component ship land`, `cplat component ship wait`, `cplat system ship next --wait`, `cplat dispatch wait` and the others). An **idle call** is a model call of a session that runs no tool (for example a one-line answer to a refused stop). **Progress** is a new commit on the feature branch, a change of the run's phase or unit, or a model call that runs a tool.

Waiting costs no model calls.

- **AC-202.1** Given the owning session of an unfinished ship run (`/component:ship` or `/system:ship`, interactive or under `cplat headless`) that tries to stop while a wait runs, when the Stop hook judges the stop, then it lets the session stop, as it does for a running background agent, and prints one line `ship <spec>: waiting for <command> in phase <phase>`. It leaves the count of stops without progress unchanged and escalates nothing. Once no wait runs, stops count as in AC-126.4 and AC-126.5. A test that replays the 2026-11-14 case (a background `ship land` that runs 60 seconds and a session that tries to stop) shows exactly one stop and no blocked stop while land runs. (replaces AC-171.8)
- **AC-202.2** Given an interactive session whose stop was let through by AC-202.1, when the wait ends, then the session's next turn starts from the wait's result (its exit code and output) and goes on as the instructions say for that result (the next phase, the unit's checkpoint, or the escalation the wait printed). Between the stop and the end of the wait the session makes no model call.
- **AC-202.3** Given a session under `cplat headless` whose process ends while a wait it started runs, then the wait keeps running to its end and records its exit code and last 20 lines of output. `cplat headless` makes no model call and starts no session until the wait has ended. Then, within 30 seconds, it starts the next session of the same unit, and that session's start output names the wait and its recorded result. Such a session end never counts as a session without progress (AC-080.2, AC-131.5). A wait still running 120 minutes after its session ended is stopped, and the run escalates with cause `environment` and the reason `wait <command> still running after 120 min`. A wait that ended without a recorded result (it was killed) lets the next session start at once with the line `wait <command> ended without a result`.

A guard against looping sessions.

- **AC-202.4** Given a session under `cplat headless` (every dispatcher unit runs under it), when it makes `loop_calls` idle calls (default 10) within `loop_minutes` minutes (default 5) with no progress in that window, then `cplat headless` ends the session within 30 seconds, starts no new session, and escalates the run with cause `platform` and the reason `looping: <n> model calls in <m> min without progress in phase <phase>`, followed by up to 200 characters of the session's last message (secrets redacted as in spec 087). It then exits 1. A test with a fake session that answers every refused stop in one line, every 1.5 seconds, shows the session ended after its 10th idle call. A fake session that runs a tool in every call for 15 minutes is never stopped by the guard.
- **AC-202.5** Given `.platform/dispatch.yml` with `guard.loop_calls` (an integer from 3 to 100) and `guard.loop_minutes` (an integer from 1 to 60), when the dispatcher starts a unit, then the unit's `cplat headless` uses those values. `cplat headless --loop-guard <calls>/<minutes>` sets them for a run started by hand, and without either the defaults of AC-202.4 apply. `cplat dispatch plan` shows the effective values, with defaults marked as such. A value outside the range, or another key under `guard`, is refused by every `cplat dispatch` command, which names the key and the allowed values, and `cplat headless` refuses a bad `--loop-guard` the same way, starting nothing.
- **AC-202.6** Given a unit escalated by the guard (AC-202.4), when the dispatcher sees it, then it handles it as an escalation of AC-167.8: it releases the claim, labels the item `needs-decision` with a comment giving the reason, and refills the slot. `cplat dispatch inbox` and `cplat needs --json` list an `escalation` entry with cause `platform` and the `looping: …` reason. `cplat dispatch status` shows the unit as `escalated: looping` with the reason, and `cplat dispatch report` counts it under escalated. The tokens the unit used up to the stop count toward the day's budget (AC-167.10).

Pause reaches a running session.

- **AC-202.7** Steering takes effect within one cycle and is recorded in the dispatcher's state, so it survives a restart:
  - `cplat dispatch pause`: no unit starts. Each running unit's session is let stop by the Stop hook the next time it tries to stop, even before its checkpoint, and its `cplat headless` starts no further session. A turn that is running tools is not interrupted. A wait the unit started runs to its end and its result is recorded (AC-202.3). The unit shows as `paused` in `status`, with its phase and last checkpoint, and `cplat dispatch resume` continues it from its last checkpoint (AC-131.3). A test with a fake session looping as in AC-202.4 shows it ended at its next stop after the pause.
  - `pause --drain`: no unit starts, and running units finish.
  - `cplat dispatch resume`: starts are allowed again, and paused units continue.
  - `cplat dispatch slots <N>`: the slot count changes. A lower N never stops a running unit; it lets units finish until N is reached.

  `cplat dispatch status [--json]` lists the slots (unit, kind, phase, since, tokens used), the queue in order, the held items with reasons, pause state and today's tokens of the limit. `cplat dispatch wait [--timeout S]` (default 540 s, ADR-082) exits 0 when no unit runs and nothing ready is queued, 1 with a first line `ESCALATED:` or `RED:` when a unit escalates or a merge check fails, and 2 with `TIMEOUT:` and the running units. `cplat dispatch report [--since D]` lists per day what was delivered, escalated and held, and the tokens used. (replaces AC-167.11)

## Non-goals

- Changing the budgets themselves (spec 102, AC-131.13, `budget.*` of the dispatcher) or what counts against them.
- Any web console UI: the person reads the escalation in terminal output (`cplat dispatch inbox`, `status`, `cplat needs`) only.
- Changing what `cplat component ship land` or any other wait does, or their own timeouts.
- Guarding interactive sessions outside `cplat headless` against loops; the person sees those, and AC-202.1 removes the known cause.
- Judging progress with a model; progress and idle calls come from fixed rules.

## Assumptions

- **A1** The Stop hook lets a waiting session stop (the wait's end wakes it, or `cplat headless` starts the next session), instead of the wait running in the foreground with its own timeout (other option: the unit instructions run every wait in the foreground, bounded by the wait's timeout; affects AC-202.1, AC-202.2, AC-202.3).
- **A2** A wait outlives the end of its headless session and records its result for the next session, and `cplat headless` waits up to 120 minutes for it before escalating with cause `environment` (other option: no limit except the budget; affects AC-202.3).
- **A3** An idle call is a model call that runs no tool, and progress is a new commit, a phase or unit change, or a call that runs a tool (other option: count every model call and only commits and phase changes as progress; affects AC-202.4).
- **A4** The guard's default is 10 idle calls within 5 minutes; the 2026-11-14 loop would have stopped after about 15 seconds instead of 44 minutes (other option: 20 within 10 minutes; affects AC-202.4, AC-202.5).
- **A5** The guard stops and escalates the unit rather than pausing it, so the slot is freed and the item goes to the person as `needs-decision` (other option: pause the unit and keep the slot; affects AC-202.4, AC-202.6).
- **A6** A looping session is a platform defect, so its escalation has cause `platform` and gets the platform's deduplicated automatic issue (spec 088) (other option: choose the cause as in AC-126.7; affects AC-202.4, AC-202.6).
- **A7** The threshold lives in `.platform/dispatch.yml` as `guard.loop_calls` and `guard.loop_minutes`, with `cplat headless --loop-guard <calls>/<minutes>` for runs started by hand (other option: a key in `.platform-settings.yml` read by both; affects AC-202.5).
- **A8** Pause lets each unit session stop at its next stop attempt and never kills a turn that is running tools; the unit later resumes from its last checkpoint, so work since then may be redone (other option: end the session process at once; affects AC-202.7).

## Open questions

## Changelog

- 2026-11-15 created
- 2026-11-15 approved
- 2026-11-15 building
- 2026-11-15 done
