---
spec_id: 200-a-component-ship-runs-in-its-own-session
title: A component ship runs in its own session
status: building
priority: P1
shape: platform
---

# 200 — A component ship runs in its own session

## Problem

When the person says "ship it" in an interactive session, `/component:ship` runs plan, red tests, batches, verification and land in that same long session, with all their subagents. Every turn rereads the session's large context. In journeys 11 to 16 the step "Ship the spec" cost 5.7 to 8.6 M of the main session's tokens (journey 16: 8.6 of 20.9 M). In part 2 of journey 16, a system ship ran each repo's ship in its own headless session (spec 155), and the whole two-repo ship cost the main session only 2.8 M. The round's goal is at most 34.7 M tokens per journey, and journey 16 used 35.0 M. Journey 16 also had a needless stop (J16-1). The API repo's land unit fixed a Linux-only CI failure in an agent-written test helper, then escalated to ask whether it could. A helper change that defines no test and changes no assertion is a tightening the run settles itself (AC-171.7), but that rule reaches only the build, not the CI fix rounds of later units.

## Stories

As someone shipping a spec from an interactive session, I want the ship to run in its own session and my session only to wait for it and relay its questions and report, so that the ship costs my session a few turns and not millions of tokens, and I see the same questions, PR, dev deploy and report as today.

As someone shipping unattended, I want a CI fix that only touches a test helper to be applied and recorded without a stop, so that the run stops only for a change to a test or an assertion.

**Repos:** sdlc-foundry (the platform: `cplat` and the component plugin; the behaviour reaches every component repo).

## Acceptance criteria

The hand-off.

- **AC-200.1** Given an interactive `/component:ship <spec>` (not under `cplat headless`, no `--unit`, no `--here`) whose `cplat component ship start` passes, when the ship starts, then one `cplat` call (`cplat component ship start <spec> --detach`, with `--no-merge` and `--full` passed through) starts `cplat headless "/component:ship <spec>"` in the same repo as its own detached process. That process gets the same preflight, run allowlist, budget, unit mode and resume behaviour as a headless ship started by hand. The call records the process id and the log path in the ship state, and prints `headless: pid <pid>, log <path>`. The headless run's usage is recorded as a child of the interactive session's run, so `cplat platform runs` counts each token once. The interactive session then starts no subagent and runs no plan, build, PR, land or deploy step itself. Refusals of `ship start` (unapproved spec, claimed issue, missing `GITOPS_TOKEN`) start no process and print the same hint as today.
- **AC-200.2** Given a run whose headless process is still alive, when `cplat component ship start <spec> --detach` runs again (a new session or a second "ship it"), then no second process starts, and it prints the existing `headless: pid <pid>, log <path>` line. Given `/component:ship <spec> --here`, `--unit <unit>`, or a `/component:ship` inside a `cplat headless` session, then nothing is handed off and the ship runs in that session as today. A test with a fake `headless` shows that a headless session never starts another process.

Waiting and the log.

- **AC-200.3** Given a ship run in a clone, when `cplat component ship wait [--repo DIR] [--phase P] [--timeout T]` (default 540) runs, then it prints one line with the time at each phase or unit change. It exits 0 when the run reaches phase `P` or a later one (plan, build, pr, land, deploy, done), or `done` when no phase is given. It exits 1 with a first line `ESCALATED:`, the reason, the cause, each question with its suggested answer, and the log path when the run is escalated. A call that reaches none of these ends no later than T plus 10 seconds after it started. If any phase, unit checkpoint or commit was new during the call, it exits 0 with exactly one line `WAIT: run still going, progress in the last <T>s; run the same wait again`. If nothing was new, it exits 2 with `TIMEOUT:`, the phase, how long the run has been in it, and the log path. A clone without a ship run makes it exit non-zero at once, saying so. (replaces AC-143.8)
- **AC-200.4** Given a handed-off run whose headless process ended while the run is neither done nor escalated (a crash, a killed process, a closed laptop), when `cplat component ship wait` sees it, then it exits 1 with a first line `ENDED: headless session ended in phase <phase>; log <path>`. The first time, `cplat component ship start <spec> --detach` resumes the run from disk in a new process. A second `ENDED:` in the same run escalates it with cause `environment`, naming the log path.

Escalations and the report.

- **AC-200.5** Given an `ESCALATED:` result with cause `decision` whose questions all have a suggested answer, and a person who said in this session to take suggested answers, when the interactive session handles it, then it resumes the run with `cplat component ship start <spec> --detach --answer '<the suggested answers>'`. Otherwise (no such instruction, or a question without a suggestion) it asks the person each question word for word and resumes the same way with their answer. In both cases the headless session's `ship start` prints `answer from the shipping session: <text>` and applies it as an answer from the system ship is applied today. Any other cause is shown to the person as today's escalation report, and nothing is resumed. The rule has a rules-register entry (spec 168) and the ship instructions stay within their recorded size.
- **AC-200.6** Given a handed-off run that reaches `done`, when the wait exits 0, then the interactive session prints the final report of today's in-session ship. It has the same rows (PR, merge, dev deploy, smoke and promotion lines, dependency bumps, the plan's human steps), built from `cplat component ship status` of the finished run. A test runs a finished fake run through both paths and shows that `cplat` gives the report the same data. While the run is unfinished, the Stop hook holds the interactive session with the next step `cplat component ship wait`, and a running wait counts as in AC-171.8.

A test-helper fix needs no stop (J16-1).

- **AC-200.7** Given any unit of a ship or build (the CI fix rounds of `land` and `pr`, and verification fix rounds included), when a fix changes, since the red commit, only test helpers that define no test, and removes or changes no test definition, assertion or criterion id, then the run records it with `cplat spec test-diff $RED --tighten <file> --task <task> --reason '<why>'` without escalating or asking. The run goes on (push, land), and the PR's "How this was built" block lists the file, the task and the reason, as AC-171.7 says. A fix that changes a test definition, an assertion or a criterion id is refused by the check and escalates with cause `decision` as a changed test, as today. A test with a fake land round that changes only a helper shows no escalation.

## Non-goals

- Changing what any unit does, the budget's size, the unit order or the land and deploy steps: the headless run is today's headless ship.
- Handing off `/component:build`, `/component:release` or any other command; `/system:ship` already runs repos in their own sessions (spec 155).
- Several ships of one clone at once: one clone, one ship (spec 155 Non-goals).
- Answering escalations of causes `code`, `environment`, `platform` or `unknown` on the person's behalf.
- Changing `cplat system ship next --wait` (spec 194) or any other wait.
- The journey's token and minute totals: they are the round's goal, measured in the next journey, not criteria of this spec.

## Assumptions

- **A1** The hand-off is a `--detach` flag of `cplat component ship start`, so that its refusals, claim and branch switch stay as they are (other option: a new `cplat component ship handoff` command; affects AC-200.1, AC-200.2, AC-200.4, AC-200.5).
- **A2** `/component:ship --here` keeps today's in-session ship; `--unit` and any session under `cplat headless` never hand off (other option: an environment variable or a repo setting; affects AC-200.2).
- **A3** The log goes to the repo's headless log folder, where `cplat headless` writes today. Its path is recorded in the ship state and printed by `ship start --detach`, by `cplat component ship status`, and by the `ESCALATED:`, `TIMEOUT:` and `ENDED:` lines of the wait (other option: only in `ship status`; affects AC-200.1, AC-200.3, AC-200.4).
- **A4** `cplat component ship wait` ends within its timeout and reports progress with exit 0 and a `WAIT:` line, matching `next --wait` in spec 194, so that a 40-minute ship is not escalated after three timeouts (AC-143.11) (other option: restart the timeout on progress, which outlasts the 10-minute Bash limit; affects AC-200.3).
- **A5** Progress for the wait is a new phase, a new unit checkpoint or a new commit on the feature branch (other option: phase only; affects AC-200.3).
- **A6** A process that ends early is resumed once, as AC-155.5 does for repo sessions, and the second end escalates with cause `environment` (other option: escalate at the first end; affects AC-200.4).
- **A7** The interactive session takes suggested answers only for cause `decision`, and only when the person said so in that session, as the system ship does (A2 of spec 186). Otherwise it asks (other option: always ask; affects AC-200.5).
- **A8** The resumed session's line reads `answer from the shipping session:` and the ship instructions treat it like `answer from the system ship:` (other option: one shared wording for both; affects AC-200.5).
- **A9** The headless run is a child run of the interactive session's run, as a repo session is a child of the system ship's run (AC-155.7) (other option: an independent run; affects AC-200.1).
- **A10** The test-helper rule reaches every unit through `cplat spec test-diff`'s existing `test helper (defines no test)` verdict, and the task named is the task whose files the fix touches (other option: a task named `ci-fix`; affects AC-200.7).

## Open questions

## Changelog

- 2026-11-14 created
- 2026-11-15 approved
- 2026-11-15 building
