---
spec_id: 210-the-dispatcher-paces-work-by-the
title: The dispatcher budgets by plan limits or by cost
status: draft
priority: P1
shape: platform
---

# 210 — The dispatcher budgets by plan limits or by cost

## Problem

The dispatcher (spec 167) stops starting work at a daily token count. That count is a poor measure for both kinds of user. A Claude Max subscriber pays a flat price for a 5-hour window and a weekly allowance. The allowance left unused at the weekly reset is lost, and running into the 5-hour limit stalls every running unit. An API-key user pays per token, and cache reads make the token count swing widely: 856 M tokens were booked on 2026-11-14 and 2 M on 2026-11-12, so a token cap neither tracks money nor gets the most out of a subscription. Both users need a budget in the unit they actually pay in: the plan's percentages, or US dollars.

## Stories

- As a Claude Max subscriber, I want the dispatcher to pace work so that about 92 % of my weekly allowance is used by its reset without hitting the 5-hour limit, so that I get the most out of the subscription without stalls.
- As a subscriber, I want spare allowance in the last day before the weekly reset to go into useful lower-priority work, so that it does not expire unused.
- As an API-key user, I want a daily (and optionally monthly) cap in US dollars, so that unattended work never costs more than I set.
- As any user, I want `plan` and `status` to say which budget holds a start and why, and my existing policy to keep working, so that I can trust and steer the dispatcher.

## Acceptance criteria

Words used below. A **reading** is one record of the subscription's `five_hour` and `seven_day` used percentage (0–100) and reset time, together with when it was taken. The **weekly pace** is `weekly_target × elapsed share of the 7-day window × 100`, where the window starts 7 days before the `seven_day` reset. The **filler window** is the last 24 hours before the weekly reset. A **filler-only** item is a candidate that matches `budget.plan.filler_only`.

The policy and the plan.

- **AC-210.1** Given `.platform/dispatch.yml`, when any `cplat dispatch` command reads it, then `budget.mode` is `cost` (the default) or `plan`, and any other value fails naming the key and the allowed values. The keys are `slots`, `budget.mode`, `budget.usd_per_day`, `budget.usd_per_month`, `budget.tokens_per_day` (deprecated), `budget.per_unit`, `budget.plan.weekly_target` (0.50–1.00, default 0.92), `budget.plan.window_stop` (0.50–1.00, default 0.80), `budget.plan.filler_only` (default `[priority:P2, label:enhancement]`), `budget.plan.filler_tasks` (a list of `{name, command}`, default empty), `budget.plan.filler_drafts` (default `true`), `sources`, `ready`, `priority`, `gates.approve_specs`, `gates.merge` and `serialize`. An unknown key, or a value outside the allowed ones, fails naming the key and the allowed values. Given a repo without the file, `cplat dispatch start` and `resume` exit 1 naming the file and start nothing. Given mode `cost` with neither `budget.usd_per_day` nor `budget.tokens_per_day`, they exit 1 naming `budget.usd_per_day` and start nothing. Given mode `plan`, no USD or token key is required, and one that is set applies as an extra cap as in AC-210.3 and AC-210.4. A `budget.plan.*` key in mode `cost` fails naming the key and saying it needs `budget.mode: plan`. A `gates.merge` other than `green-ci`, a `gates.approve_specs` other than `human` or `self`, or a `serialize` without `merge`, is refused. (replaces AC-167.1)
- **AC-210.2** Given any repo, when `cplat dispatch plan [--json]` runs, then it prints the effective policy, marking the defaults (all defaults when there is no file). In mode `cost` without `budget.usd_per_day`, it shows the key as unset, with the USD cost of each of the last 7 days as a hint. In mode `plan`, the JSON has `plan` = `{"source": "reading"|"estimate"|"limit"|"unknown", "read_at", "five_hour": {"used", "resets_at", "stop"}, "seven_day": {"used", "resets_at", "pace", "target"}, "filler": true|false}`, and the text has one line such as `plan usage: 5h 83 % (stop 80 %, resets 15:45) · week 41 % (pace 46 %, target 92 %, resets Mon 00:00) · reading 4 min old`. In mode `cost`, `plan` is `null`, and `cost` = `{"day", "used_usd", "limit_usd", "month_used_usd", "month_limit_usd"}` with a text line `cost today: $<used> of $<limit>` (plus `this month: $<used> of $<limit>` when a monthly limit is set). It then lists every candidate once, in priority order, with its kind, its verdict (`ready` or `held: <reason>`), its mode and the slot it would take. GitHub, branches, worktrees and claims are the same before and after the command. `cplat dispatch status` shows the same `plan` or `cost` line and the same held reasons. (replaces AC-167.2)

Mode `cost`.

- **AC-210.3** Given mode `cost` and `budget.usd_per_day: 5`, when a cycle runs, then it adds up the USD cost of every unit, priced from its token usage with the platform's price table, and of the dispatcher's own agent calls since local midnight (an agent call's reported cost when the call reports one). Once the sum reaches $5.00, no unit starts and no agent call is made, running units continue within their own budgets (spec 102), `cplat needs` gets one `budget` entry per day, and starts continue after midnight on their own. Given `budget.usd_per_month: 100`, the same holds for the sum since the first day of the local month, with one `budget` entry per month, and starts continue on the 1st. While a unit's usage is unknown, or its model has no price in the table, no new unit starts, and `status` names that unit. (replaces AC-167.10)
- **AC-210.4** Given mode `cost` with `budget.tokens_per_day` and no `budget.usd_per_day`, when a cycle runs, then the daily token cap applies as before this spec: starts stop at that many tokens since local midnight, with one `budget` entry per day. `plan` and `status` print the warning `budget.tokens_per_day is deprecated: set budget.usd_per_day (cost today: $<n>)`. Given both keys, both caps apply, and the first one reached holds starts.

Mode `plan`.

- **AC-210.5** Given the sensor installed with `cplat dispatch sensor install`, when an interactive Claude Code session passes status line input containing `rate_limits.five_hour` and `rate_limits.seven_day`, then a reading with both windows and the current time is recorded, and `plan` shows it. Input without `rate_limits`, or with only one window, leaves the missing window's last reading in place. Given a status line command the user had configured before the install, its output is printed unchanged after the install. `cplat dispatch sensor remove` restores the earlier configuration. A test feeds fixture status line inputs, with no subscription and no network.
- **AC-210.6** Given mode `plan` and a reading of `five_hour` 83 % with `window_stop` 0.80, when a cycle runs, then no unit starts and no agent call is made, running units continue to their end, and `plan` and `status` show `held: plan-window 83 % ≥ 80 %`. Given 79 %, the 5-hour window holds nothing. Given a `seven_day` reading at an elapsed share of 50 % with `weekly_target` 0.92 (pace 46 %): at 50 % used, no unit starts, with `held: ahead of weekly pace (50 % used, pace 46 %)`; at 43 % used (5 points or less behind), at most 1 unit runs at a time; at 30 % used, units start up to `slots`. At or above 92 % used, no unit starts, with `held: weekly target reached`.
- **AC-210.7** Given mode `plan` and a newest reading older than 30 minutes, when a cycle runs, then it estimates each window as that reading plus the dispatcher's tokens booked since then, divided by the tokens per percentage point calibrated from readings of the last 7 days (with readings of 40 % at 10:00 and 42 % at 11:00 and 20 M tokens booked between them, 15 M tokens booked after 11:00 give 43.5 %). A window whose reset time has passed counts from 0 %. `plan` shows `source: estimate`. Given no reading at all, or a stale reading without a calibration (fewer than two readings in one window with booked tokens between them), no unit starts, `plan` and `status` show `held: plan usage unknown (install the sensor and open an interactive session)`, and `cplat needs` gets one `budget` entry per day.
- **AC-210.8** Given mode `plan` and a unit whose session ended with the usage-limit message (`You've hit your session limit · resets 3:45pm`, `You've hit your weekly limit · resets Mon 12:00am`, or any other limit message spec 184 recognises), when the next cycle runs, then no unit starts and no agent call is made until that reset time, even if a later reading or estimate is lower. `plan` shows `source: limit` and `held: usage limit until <local time>`. A limit message without a reset time holds starts for 60 minutes. Usage credits are never used to continue: the hold applies whether or not credits are switched on.
- **AC-210.9** Given mode `plan`, when a filler-only candidate is judged outside the filler window, then it is held as `held: filler only`. Given the filler window, a weekly reading or estimate below the target, no other limit of AC-210.6 to AC-210.8 holding, and no regular candidate ready, when a cycle has a free slot, then it starts, in this order: filler-only candidates (in priority order); each `budget.plan.filler_tasks` entry, at most once per weekly window, as a unit running its command in its own worktree; and, with `filler_drafts: true`, one draft unit per proposal of the latest `Weekly retro` issue that no spec or open pull request answers yet, at most 3 per weekly window. A draft unit opens a pull request with a draft spec that tracks the retro issue and leaves it open. The dispatcher never approves it, even with `gates.approve_specs: self`. `plan` shows `filler: true` and marks each filler start `(filler)`.

Choosing the mode.

- **AC-210.10** Given any repo, when `cplat dispatch status` or `plan` runs, then the mode is the one the policy states (or `cost` by default) and never changes on its own. When a reading from the last 7 days exists and the mode is `cost`, they print one line `hint: subscription usage readings found; budget.mode: plan paces by your plan's limits`. When `ANTHROPIC_API_KEY` is set, no reading exists and the mode is `plan`, they print `hint: an API key and no subscription readings; budget.mode: cost caps spending in USD`. The policy file is never changed by either command.

## Non-goals

- Reading the plan's limits in tokens, or the state of usage credits: neither is published nor readable by a program.
- Sensing a separate weekly model limit (such as Fable's) other than through its limit message: the status line input exposes only `five_hour` and `seven_day`.
- Stopping or pausing running units for budget reasons. Pause stays as in AC-202.7.
- Changing per-unit budgets (spec 102, AC-131.13) or the price table (spec 099).
- A filler queue in mode `cost`.
- Pacing across several machines: readings and the ledger are per machine.

## Assumptions

- **A1** Two modes, `plan` and `cost`, chosen explicitly in the policy. `cost` is the default (decided in explore, revised 2026-11-17 by the user; other option: `tokens` stays the default; affects AC-210.1, AC-210.10).
- **A2** `budget.tokens_per_day` keeps working in mode `cost` as a deprecated alias with a warning, so existing policies do not break (decided in explore; other option: refuse it; affects AC-210.1, AC-210.4).
- **A3** The weekly target is 92 % of the weekly limit by its reset, and no new unit starts at or above 80 % of the 5-hour window. Running units always finish (decided in explore; affects AC-210.1, AC-210.6).
- **A4** The pace bands: ahead of pace means no starts, 0–5 points behind means at most 1 running unit, more than 5 points behind means up to `slots`. `slots` stays the maximum (other option: scale the slots linearly with the distance to the pace; affects AC-210.6).
- **A5** A reading older than 30 minutes is stale. The estimate uses the dispatcher's own ledger, calibrated as the median tokens per percentage point over reading pairs of the last 7 days, and sees no manual work done between readings (other option: 15 or 60 minutes; affects AC-210.7).
- **A6** With no reading, or a stale reading without a calibration, plan mode holds starts instead of guessing (other option: refuse `start`; affects AC-210.7).
- **A7** The sensor is installed only by an explicit command. It keeps an existing status line's output, and `sensor remove` restores it (other option: install it on `dispatch start`; affects AC-210.5).
- **A8** Only usage-limit messages are trusted for limits the reading does not show (Fable's weekly limit). A message without a reset time holds starts for 60 minutes (other option: the 184 backoff steps; affects AC-210.8).
- **A9** The filler work covers P2 specs and triaged enhancements held back, benchmark and mutation runs (spec 107 part 2), an autonomous journey and spec drafts from the latest retro's proposals, never approvals (decided in explore). Benchmarks and journeys are named commands in `budget.plan.filler_tasks`, run at most once per weekly window, with the default list empty, because their commands differ per machine (other option: built-in tasks; affects AC-210.9).
- **A10** Filler only starts when no regular candidate is ready. Drafts are limited to 3 per weekly window, and their pull requests stay open for the user (other option: no limit, merge as drafts; affects AC-210.9).
- **A11** The monthly USD cap counts from the 1st of the local month. A model missing from the price table makes the usage unknown and holds starts (other option: count it as $0; affects AC-210.3).
- **A12** In mode `plan`, the keys `budget.usd_per_day`, `budget.usd_per_month` and `budget.tokens_per_day` are optional. When set, they apply as extra caps, as in AC-210.3 and AC-210.4 (other option: refuse them in mode `plan`; affects AC-210.1).
- **A13** The mode is never switched on its own. `status` and `plan` only print a hint: readings found means subscription, an API key without readings means API (decided by the user; affects AC-210.10).
- **A14** In mode `plan`, usage credits are never spent on purpose: after a limit message, nothing starts until that limit's reset (decided by the user; affects AC-210.8).

## Notes for the architect

- The sensor is a status line command the platform provides. It writes the latest `rate_limits` with a timestamp to a state file in the platform's user state directory. `rate_limits` appears only for Pro/Max subscribers and only after the first API response, each window may be absent, and a window is dropped once its `resets_at` passes. `claude -p` exposes no rate-limit fields, so readings come only from interactive sessions.
- The limit message is already detected by `cplat headless` (spec 184). The dispatcher needs that unit's reset time.
- Pricing: the existing price table of spec 099 for units, and `total_cost_usd` of `claude -p --output-format json` for agent calls.

## Open questions

## Changelog

- 2026-11-17 created
