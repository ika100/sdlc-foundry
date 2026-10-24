---
spec_id: 089-agent-quality-is-measured-per-agent-and
title: Agent quality is measured per agent and shape
status: building
priority: P1
---

# 089 — Agent quality is measured per agent and shape

Depends on 087 (the run record and the private run store). Spec 094 (re-plan on merge conflict) records its conflicts and re-plans through this spec; spec 090 (weekly retro) turns its report into agent-prompt proposals.

## Problem

The platform owner changes agent prompts (architect, coder, tester, reviewer, ...) on gut feeling: the build escalations of #102–#132 were noticed by hand, and nobody can say whether `web:coder` needs more fix rounds than `svc-go:coder`, whether the architect's `files` lists are getting more accurate, or whether a prompt change made an agent better or worse. The build already sees every signal (an out-of-plan file, a merge conflict, a hand-back to a coder, a red CI round, a refused acceptance-test diff, a `not met` verdict) and throws it away when the session ends. Now that every run leaves a record (087), these signals can be kept per agent, shape and model, so agent quality becomes evidence the platform produces itself and the weekly retro (090) can propose prompt changes from it.

## Stories

As the platform owner, I want each build to record how well every agent did its part, so that I see which agent in which shape causes the most rework.

As the platform owner, I want to compare an agent's numbers before and after a platform release, so that I know whether a prompt change helped.

As the weekly retro (090), I want ranked agent metrics with example evidence, so that I can propose concrete prompt changes instead of guesses.

## Acceptance criteria

The record contract. This spec adds two sections to the 087 run record (`build` record, or the `ship` record when the build runs inside a ship; readers that don't know them ignore them):
`agents` (list of entries, one per agent × shape × model that took part: `agent` as routed by the shape, e.g. `svc:coder`; `shape`, `none` for a repo without one; `model`, the alias the agent's definition declares, e.g. `sonnet`; `model_id`, the full model id when the orchestrator knows it, else `null`; and the entry's counted events) and `replans` (list of re-plans, see AC-089.14). Like every 087 event, these may be updated in place until the record is written at run end.

- **AC-089.1** Given a `/svc:build` run (alone, inside `/svc:ship`, or per repo inside `/app:build`), when it ends with any 087 `outcome` (`done`, `escalated`, `failed` or `abandoned`), then its run record holds an `agents` section with one entry per agent × shape × model that took part, carrying `agent`, `shape`, `model` and `model_id` as defined above.
- **AC-089.2** Given a task branch merged in Phase 2, when its changes include files outside that task's `files` (new test helpers the coder reported excepted), then the architect's entry counts one out-of-plan event per such file and lists the task id and the path.
- **AC-089.3** Given a task branch whose merge conflicts with work already merged, when the build handles the conflict (escalation today, a re-plan once 094 ships), then the architect's entry holds one plan-accuracy event of kind `merge-conflict` with: spec id, task id, the task id it collided with, the conflicting paths, the plan author's `agent`, `model` and `model_id` (the architect that wrote the plan), and an `outcome`: `re-planned` (the plan was amended and the task is re-running), `resolved` (the task re-ran on the amended plan and merged without conflict) or `escalated` (the build stopped for the user); the event's outcome is updated in place as it changes, so one conflict is one event.
- **AC-089.4** Given a build that hands work back to a coder (a red gate after a merge, a failing test in Phase 2.5, a red `devbox run ci` round in Phase 3, a `not met` cycle in Phase 4), when the hand-back happens, then that coder's entry counts one fix round with its cause: `lint/type`, `test`, `ci` or `verification`.
- **AC-089.5** Given `cplat ship land` sees a red PR CI round, when it sends the logs to a coder, then that coder's entry (never the quality or security agent's) counts one red-CI round with the red check's name as its cause; a rerun of a stale, stuck or transient run (087 `reruns`) is never counted against an agent.
- **AC-089.6** Given the reviewer writes `verification.md`, when its first pass completes, then the entry of the coder of each task covering an affected criterion counts that criterion's finding by severity: `not met`, `partial`, or `deviation` (only deviations the reviewer judged not acceptable); findings of later review cycles are counted separately as `after fix`.
- **AC-089.7** Given `cplat spec test-diff` refuses a change to an acceptance test, when the refusal stops the build, then the entry of the agent whose change triggered it (the task's coder or the quality agent) counts one refused test diff with the test file.
- **AC-089.8** Given the tester's acceptance tests, when criteria are missing from the trace and go back to the tester, or a test fails for a reason other than missing behaviour, then the tester's entry counts one event per criterion or test, with the reason `untraced` or `wrong failure`.
- **AC-089.9** Given a run in which a metric was not observed (the phase never ran, or the run predates this spec), when the record is read, then that metric is "not measured" rather than 0, and the report leaves such runs out of that metric's average and shows `n/a` when no run measured it.
- **AC-089.10** Given recording an agent metric fails (malformed event, write error), when the build continues, then the run is neither stopped nor failed, and the record states that its agent metrics are incomplete.
- **AC-089.11** Given run records in the store, when the user runs `cplat runs report --agents`, then it prints one row per agent × shape × model for the last 30 days with the number of runs and per-run averages of each metric (out-of-plan files, merge conflicts, re-plans, fix rounds by cause, red-CI rounds, findings by severity, refused test diffs, tester events), sorted by total rework, worst first; rows with fewer than 5 runs are marked `few runs`. `--since <days>`, `--repo <owner/name>` (as in 087), `--agent <name>` and `--shape <shape>` narrow it; `--json` prints the same rows as one JSON document and nothing else on standard output.
- **AC-089.12** Given `cplat runs report --agents --by-version`, when it runs, then each row is split per `platform_version`, so an agent's numbers before and after a release appear side by side.
- **AC-089.13** Given a report row, when it prints, then it lists up to 3 of the row's most frequent causes (for example the out-of-plan path patterns, the fix-round causes, the criteria most often `not met`), each with the `run_id` of one record that shows it; all text taken from runs is redacted with the same redaction as `cplat feedback`.
- **AC-089.14** Given a build that amends its plan after a merge conflict (094), when the architect has written the amended plan, then the record's `replans` section gets one entry (spec id, task id, the architect's `agent`, `model` and `model_id`, and a link to the `merge-conflict` event that caused it) and the architect's entry counts one re-plan; the report (AC-089.11) shows merge conflicts and re-plans as separate columns, and the share of conflicts that ended `resolved`.

## Non-goals

- Writing agent-prompt change proposals or ranking them: spec 090 does that from this report.
- Changing agent prompts automatically.
- Metrics for `/svc:quick-task`, `/svc:fix-bug`, `/svc:release`, `/gitops:*` and the `/app:spec|plan` agents (product-manager, planner); quick-task and fix-bug may follow in a later spec once build metrics prove useful.
- Judging the product-manager's specs (for example amendments after approval).
- Token cost and duration per agent (phase durations belong to 087).
- Comparing against an external benchmark; numbers are only compared with each other.

## Open questions

- ~~Which "model" is the key?~~ Answered: the declared alias, plus the full model id when the orchestrator knows it; see the record contract and AC-089.1.
- ~~Confirm: reviewer severities `not met`, `partial`, `deviation`.~~ Answered: yes, unacceptable deviations only; see AC-089.6.
- ~~Confirm: red PR CI rounds count against the coder that fixes them.~~ Answered: yes, with the red check's name as cause; see AC-089.5.
- ~~Confirm: 30-day default window, `few runs` under 5 runs.~~ Answered: yes; see AC-089.11.
- ~~Should `/svc:quick-task` and `/svc:fix-bug` also record coder fix rounds now?~~ Answered: no, a later spec; see Non-goals.

## Changelog

- 2026-10-23 created
- 2026-10-23 merge-conflict event fields and outcomes defined for spec 094 (AC-089.3), re-plan count added (AC-089.14)
- 2026-10-23 amended: open questions answered (model alias plus full id, severities, red-CI attribution, 30-day window, quick-task/fix-bug out); aligned with the 087 record contract (`agents` and `replans` sections, outcomes, `--since <days>`, `--repo`, `run_id` links)
- 2026-10-23 approved
- 2026-10-24 building
