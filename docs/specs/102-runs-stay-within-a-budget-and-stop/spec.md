---
spec_id: 102-runs-stay-within-a-budget-and-stop
title: Runs stay within a budget and stop repeating failures
status: done
priority: P1
tracks: [141, 144]
---

# 102 — Runs stay within a budget and stop repeating failures

## Problem

Spec 099 measures what a run costs, but nothing stops a run that overspends. A quick task costs about $0.08 to $0.16 and a build about $1.0 to $1.3, yet one unmetered round of ten specs cost about $105, and nobody noticed until it was over. Today's limits only cover pieces: `cplat headless` has `--max-runs` and `--max-minutes` and stops after two idle sessions (spec 080), and `cplat ship` escalates after 3 fix rounds. Each nested run (headless, ship, build, product ship) starts with fresh limits, so the limits add up instead of holding. A run can also repeat an equivalent failure with slightly different wording and spend tokens each time, and a resumed run may redo stages that already passed. The platform owner needs one budget that holds across nested runs and a stop for failures that make no progress.

## Stories

- As the platform owner, I want every run tree to share one budget of time, agent invocations, CI reruns and estimated cost, so that an unattended delivery cannot overspend whatever fails inside it.
- As the platform owner, I want a run that hits a limit to stop at a safe point and say why, so that I can raise the limit and resume instead of starting over.
- As a developer, I want a run to stop when it repeats the same failure without progress, so that it escalates early instead of burning tokens on attempts that won't change anything.
- As a developer, I want a resumed run to continue from the stages that are still verified, so that an interruption does not make me pay for completed work twice.

## Acceptance criteria

The budget. A budget has four limits: wall-clock minutes, agent invocations (sessions and subagents), CI reruns, and estimated cost in USD (from the usage of spec 099). The budget belongs to the outermost run (`cplat headless`, a product ship, or a ship or build started by hand). Every run it starts is part of the same run tree. The no-progress limit has its own criteria below.

- **AC-102.1** Budgets are on by default. Given a run started without budget options, when it starts, then the default limits apply and the start output shows all four limits. For one ship (or a build started by hand) the defaults are 180 minutes, 60 agent invocations, 6 CI reruns and $15. A headless run or a product ship that covers several ships gets the ship defaults times the number of specs or repos it covers (a round of 10 specs: 1800 minutes, 600 invocations, 60 reruns, $150). Given options for any limit, then those values apply instead. A limit set to `off` is not enforced and is shown as `off`.
- **AC-102.2** Given a headless run that starts a ship run, which starts a build and a CI wait, when they run, then they all count against the same budget and none of them starts with fresh limits. Given a product ship that drives ships in several repos, then they share the product ship's budget.
- **AC-102.3** Given the budget of a run tree is used up in one limit, when the run next reaches a safe point (before a new session, subagent or CI rerun starts, and at the end of a phase), then it starts no new work, escalates with the reason `budget exhausted: <limit>`, and the working state stays resumable. Work already running is not killed.
- **AC-102.4** Given a run stopped by AC-102.3, then its run record (spec 087) holds a `budget` section with the four limits, the usage at the stop, the limit that was reached, and the phase it stopped in. The stop counts as an escalation with the cause `decision` (the user must raise a limit or change the plan), and the run's `outcome` is never `done`.
- **AC-102.5** Given a run tree whose cost is `unknown` or incomplete (`cost_complete` false, spec 099), then the cost limit cannot be checked: the output and the record show the cost as `unknown`, not as 0, and the time, invocation and rerun limits are still enforced.
- **AC-102.6** Given an escalated run is started again for the same spec (spec 087 `resumes`), when it runs, then its usage and its limits continue from the earlier run and nothing resets. A limit changes only when the user passes a new value, and the record notes the change.
- **AC-102.7** Given `cplat headless` with `--max-runs` and `--max-minutes`, then those limits stay and apply together with the budget. The first limit reached stops the loop, a budget stop is reported with the stop reason `budget`, and the exit code is 1. Starting the same work through `cplat headless`, a product ship or a nested build does not escape the budget.
- **AC-102.8** Given a run that hits a budget limit, then no mandatory check (acceptance, security, CI) is skipped or counted as passed because of it. The run ends escalated with those checks reported as `not run`.

No-progress. Two failures are equivalent when they come from the same stage or command and have the same normalized error text (timestamps, paths, ids and line numbers removed). Progress means that a check that was failing now passes, or that fewer checks fail than before.

- **AC-102.9** Given a stage that fails and is retried (a fix round, a rerun or a resumed session), when it has failed with equivalent errors 2 times in a row with no progress between the attempts (so a third attempt is not made), then the run makes no further attempt and escalates with the reason `no progress: <stage>`, naming the stage, the number of attempts and the normalized error. Given an attempt that shows progress, or a failure that is not equivalent, then the count starts again.
- **AC-102.10** Given a run that stops or is interrupted at a failing stage, then a recovery snapshot is saved next to the run's local state. It holds the failing stage, an excerpt of the failure (secrets redacted as in spec 087), the changed files, the ids of the acceptance criteria concerned, and the earlier attempts (count and normalized error). It holds no prompts and no full logs, and it is not written to the run store.
- **AC-102.11** Given a resumed run with a recovery snapshot, when it starts, then it skips every stage whose passing result was recorded for the current HEAD and the current inputs of that stage, and it starts with the failing stage, giving the snapshot as context. A stage whose HEAD or inputs have changed since its passing result runs again.
- **AC-102.12** Given a stage whose result is missing, skipped, stale (recorded for another HEAD) or unreadable, when a run resumes or decides whether it is done, then the stage counts as not passed and runs again. A skipped check is never read as a pass.

## Non-goals

- Pruning or shortening the context sent to models; this spec stops spending, it does not make a call cheaper.
- Measuring usage and prices: spec 099 (and the live export of spec 101). This spec only reads them.
- Choosing which checks to run for a change: spec 103.
- A budget service, queue, database or new agent.
- Weakening or skipping tests, security gates or required approvals to save budget or to break a loop.
- Estimating cost in USD for a model without a price (cost stays `unknown`).
- A benchmark that proves a bounded worst case (time and calls) for a failing run (#144's last criterion); a follow-up spec can add it on top of `cplat runs benchmark`.
- Limits per stage (#144's optional per-stage limits); this spec has run-tree limits only, a follow-up spec can add stage limits to the same ledger.
- Replacing the existing 3-fix-round escalation of `cplat ship` or the two-idle-session stop of `cplat headless` (spec 080); they stay as additional stops.

## Open questions

- ~~What are the default limits for one ship?~~ Answered: 180 minutes, 60 agent invocations, 6 CI reruns, $15, see AC-102.1.
- ~~What are the defaults for a headless run or a product ship that covers several ships?~~ Answered: the ship defaults times the number of specs or repos it covers, see AC-102.1 and AC-102.2.
- ~~Which escalation cause does a budget stop get?~~ Answered: `decision`, see AC-102.4.
- ~~How many equivalent failures without progress are allowed before the run stops?~~ Answered: 2 in a row; the third attempt is not made, see AC-102.9.
- ~~Is the budget on by default?~~ Answered: yes, with the limits above and `off` per limit as the way out, see AC-102.1.
- ~~Confirm: a budget stop happens at a safe point and never kills a running session.~~ Answered: yes, see AC-102.3.
- ~~Confirm: the recovery snapshot stays local and out of the private run store.~~ Answered: yes, see AC-102.10.

## Changelog

- 2026-10-25 created
- 2026-10-25 amended: folded in the user's answers (default limits, multiplied limits for multi-spec runs, cause `decision`, stop after 2 equivalent failures, on by default).
- 2026-10-25 approved
- 2026-10-28 building
- 2026-10-28 done
