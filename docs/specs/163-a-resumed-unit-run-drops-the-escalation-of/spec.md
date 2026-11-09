---
spec_id: 163-a-resumed-unit-run-drops-the-escalation-of
title: A resumed unit run drops the escalation of the run before
status: done
priority: P1
shape: platform
tracks: [591]
---

# 163 — A resumed unit run drops the escalation of the run before

## Problem

A unit-mode run (spec 131) that escalates writes the reason into `.git/cplat-units.json`. When `cplat headless` is started again, it resumes at the first open unit but keeps that entry, and the supervisor reads it after the next session as a new escalation. Each resume then gets one unit done and stops with the old reason (#591, found by journey 7: after the #588 fix every repo session stopped again with "no progress: unit plan …"). The ship state already drops its escalation on a re-run (`cplat ship`: "a re-run after an escalation resumes where it stopped").

## Stories

As someone resuming an escalated run, I want it to go on until it is done or escalates again, so that one fix and one restart are enough.

## Acceptance criteria

- **AC-163.1** Given a units file with an escalation from an earlier run, when `cplat headless` starts the same command again, then the escalation is dropped and the run goes through every unit left.
- **AC-163.2** Given a resumed run, when a session of it escalates, then the run stops with that new reason, as before.

## Non-goals

- Changing when a run escalates (stall limit, causes).
- The ship state, which already drops its escalation on a re-run.

## Assumptions

- **A1** Starting the command again is the person's (or the system ship's) decision to resume, so the old escalation is not kept as a stop (other option: keep it until a unit makes progress; affects AC-163.1).

## Open questions

None.

## Changelog

- 2026-11-09 building
- 2026-11-09 done
