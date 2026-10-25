---
spec_id: 099-token-usage-and-cost-are-measured-per
title: Token usage and cost are measured per run
status: draft
priority: P1
tracks: [140]
---

# 099 — Token usage and cost are measured per run

## Problem

Nobody can say what a delivery costs in tokens, or where those tokens go. In the 085–098 round we counted about 187M input tokens over 2,287 calls by hand from the transcripts. 42% of them went to coordination (the main session and the per-spec driver agents), and the average subagent call carried 71k tokens of context. The run records from spec 087 say how long each phase took but not what it consumed. So the cost-reduction work that follows (#141, #142, #144) has no baseline to beat and no way to show that a change helped. A run that fails cheaply must also not look like a cheap success.

## Stories

- As the platform owner, I want every run record to carry its token usage and estimated cost, broken down by phase, agent role and model, so that I can see where a delivery spends its tokens.
- As the platform owner, I want `cplat runs report` to show tokens and cost per successful delivery, with failed, escalated and gate-failed runs shown next to it, so that a cheaper number means a cheaper delivery and not a delivery that didn't happen.
- As the platform owner, I want `cplat runs usage` for one run or one raw session, so that I can look into a single expensive run.
- As the platform owner, I want a repeatable benchmark of a quick task, a build and a ship against fixed sample repos, so that I can compare platform versions on the same work.
- As a developer, I want usage measurement to store no prompts, code or secrets and never to cost me a run, so that turning it on is safe.

## Acceptance criteria

The usage section. At run end, the 087 run record gains a `usage` section with `totals` and the breakdowns `by_phase`, `by_role` and `by_model`. Each of them holds `calls`, `failed_calls`, `input`, `output`, `cache_read`, `cache_write` and `cost_usd`. Token counts are taken as the session transcripts report them. `cost_usd` is a number or `unknown`, and `totals` also holds `cost_complete` and `models_without_price`. Records without a `usage` section (older runs, or kinds that start no sessions) stay valid.

- **AC-099.1** Given a ship run whose sessions and subagents made 12 model calls, when its record is written, then `usage.totals.calls` is 12, the token fields are the sums over those calls, and the sums of `by_phase`, of `by_role` and of `by_model` each equal `totals`.
- **AC-099.2** Given a transcript in which one streamed message appears in 3 entries with the same message id, when usage is counted, then that message counts as one call, using the values from its last entry.
- **AC-099.3** Given a call made during a phase of the run (by its timestamp, between the phase's `started_at` and `ended_at`), then it counts under that phase in `by_phase`. A call made inside the run but outside every phase counts under `unphased`.
- **AC-099.4** Given calls from the main session and from subagents, then main-session calls count under role `main`, and each subagent's calls count under its agent type (for example `svc:coder`). A subagent with no agent type counts under `unknown`. The subagent's description is not stored.
- ~~**AC-099.5**~~ withdrawn 2026-10-25: replaced by AC-099.14, which splits shared main-session calls instead of giving each call to one run.
- **AC-099.6** Given a call whose model is `<synthetic>` (a failed or rate-limited call), then it counts in `failed_calls` and `calls` with its reported tokens. It does not show up as a model in `by_model`, adds no cost and does not make any cost `unknown`.
- **AC-099.7** Given the price table kept in the platform repo (per model: input, cache write, cache read and output in USD per million tokens, and the date the prices were taken), then each model's `cost_usd` is computed from that model's four counts and prices. For a model that is not in the table, that model's `cost_usd` is `unknown`, never 0. The totals then hold the sum of the known costs, with `cost_complete` set to `false` and the model listed in `models_without_price`. Every printed cost is labelled as an estimate and names the price table's date.
- **AC-099.8** Given a run whose transcripts are missing, unreadable or partly malformed, when its record is written, then the run's outcome, exit code and output are unchanged. The `usage` section counts what could be read and states `incomplete` with the reason (for example `transcript not found` or `3 malformed lines`). Usage collection adds at most 10 seconds to the run's end.
- **AC-099.9** Given transcripts that contain prompt text, tool inputs and outputs, file contents and a secret (for example `GH_TOKEN=ghp_abc123…`), when the record is written and `cplat runs usage` prints it, then neither the record nor the output contains any of them. Both hold only counts, costs, model names, role labels, phase names, run and session ids and timestamps.
- **AC-099.10** Given `cplat runs usage <run_id>`, then it prints the run's totals and its breakdown by phase, by role and by model. The output column is headed "output (as reported)", and the output says that output cost is a lower bound. Given `cplat runs usage --session <session_id>`, then it prints the same breakdown for that local session and its subagents, by role and by model, with no phase breakdown. `--json` prints the same as one JSON document and nothing else on standard output. An unknown run id, a run without usage, or a session with no transcript on this machine exits non-zero with a message naming which one it is.
- **AC-099.11** Given records with and without usage in the report window, when `cplat runs report` runs, then for each kind it shows the number of delivered runs (`outcome` `done` and no failed gate per AC-099.12) with total and median tokens and cost per delivered run. Next to that, in the same units, it shows the failed, escalated, abandoned and gate-failed runs, plus how many runs had no usage data. Benchmark runs are left out of all of these. `--json` adds this under the key `usage`, and the existing keys are unchanged.
- **AC-099.12** Given a ship or build run, when its record is written, then it states the result of the acceptance gate and of the security gate at run end, each `passed`, `failed` or `not run`. A run with `outcome` `done` and a gate at `failed` counts as gate-failed in AC-099.11, not as delivered.
- **AC-099.13** Given `cplat runs benchmark <quick-task|build|ship>`, when it runs, then it carries out that workflow's fixed task against the sdlc-test sample service repo at a pinned revision, headless (`quick-task`: one fixed small fix; `build` and `ship`: one fixed small spec). It appends one run record marked as a benchmark, naming the workflow, the task's version and the sample repo revision, with its `usage` section. `cplat runs report --benchmarks` shows, for each workflow and platform version, the number of benchmark runs with their median tokens and cost, and their outcomes. When the sample repo cannot be reached or the workflow name is unknown, the command exits non-zero, naming the problem, and writes no record.
- **AC-099.14** Given one main session that coordinates two runs whose time windows overlap, when both records are written, then:
  - each subagent's calls count only in the run it was spawned for, under its agent type;
  - each main-session call inside the overlap is split evenly across the two runs (calls, tokens and cost), under role `main (shared)`;
  - main-session calls outside the overlap count under `main` in the one run they fall in.

  The two records together hold every call of the session once, with nothing counted twice or left out.
- **AC-099.15** Given `cplat runs benchmark ship`, when the ship reaches the sample repo's dev environment or stops, then the sample repo is reset to the pinned revision. The next benchmark run starts from the same state, and the reset is noted in the benchmark's record. When the reset fails, the command exits non-zero, names the sample repo, and the record still gets written.

## Non-goals

- Context pruning or any other change that lowers token use; this spec only measures.
- Token or cost budgets and their enforcement (#144), no-progress breakers (#141), change-aware validation (#142).
- Exact billing: the user is on a subscription, so costs are estimates from the price table and are not reconciled with an invoice.
- Correcting the token counts the transcripts report (output is shown as reported, see AC-099.10).
- Storing prompts, tool inputs or outputs, source, transcripts or secrets anywhere (as in spec 087).
- Measuring commands that are not a 087 run kind (for example `/svc:spec` on its own), except through `cplat runs usage --session`.
- Keeping the price table current automatically.

## Open questions

- ~~Accept the transcripts' output tokens as reported?~~ Answered: yes. The column is headed "output (as reported)" and output cost is a lower bound; see AC-099.10.
- ~~How are shared calls attributed when one session drives overlapping runs?~~ Answered: a subagent's calls go to the run it was spawned for, and main-session calls in the overlap are split evenly under `main (shared)`; see AC-099.14 (replaces AC-099.5).
- ~~Store the subagent description?~~ Answered: no, the agent type only; see AC-099.4.
- ~~Separate cache write prices for the 5-minute and 1-hour cache?~~ Answered: no, one cache write price per model; see AC-099.7.
- ~~Confirm: an unpriced model leaves the known sum with `cost_complete: false`.~~ Answered: yes; see AC-099.7.
- ~~Confirm: usage collection adds at most 10 seconds.~~ Answered: yes; see AC-099.8.
- ~~Confirm: the record states the acceptance and security gate results.~~ Answered: yes; see AC-099.12.
- ~~Which sample repo and tasks make up the benchmark, and may `ship` merge?~~ Answered: the sdlc-test sample service repo with one fixed small fix and one fixed small spec. Ship merges and deploys to the sample's dev, then the repo is reset to the pinned revision; see AC-099.13 and AC-099.15.
- ~~Confirm the command names.~~ Answered: `cplat runs usage`, `cplat runs benchmark` and `cplat runs report --benchmarks`; see AC-099.10 and AC-099.13.

## Changelog

- 2026-10-25 created
- 2026-10-25 amended: folded in the user's answers. Output is labelled "as reported", and output cost is a lower bound. Only the agent type is stored as the role. There is one cache write price per model, and an unpriced model sets `cost_complete: false`. Collection takes at most 10 s, and the record gains gate results. The benchmark is defined on the sdlc-test sample service repo, with a reset after `ship` (AC-099.15). AC-099.5 is withdrawn in favour of AC-099.14, which splits shared main-session calls evenly under `main (shared)`.
