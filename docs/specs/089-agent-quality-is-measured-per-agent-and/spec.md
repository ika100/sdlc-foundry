---
spec_id: 089-agent-quality-is-measured-per-agent-and
title: Agent quality is measured per agent and shape
status: draft
priority: P1
---

# 089 — Agent quality is measured per agent and shape

Depends on 087 (the run record and the private run store). Spec 094 (re-plan on merge conflict) records its re-plans through this spec; spec 090 (weekly retro) turns its report into agent-prompt proposals.

## Problem

The platform owner changes agent prompts (architect, coder, tester, reviewer, ...) on gut feeling: the build escalations of #102–#132 were noticed by hand, and nobody can say whether `web:coder` needs more fix rounds than `svc-go:coder`, whether the architect's `files` lists are getting more accurate, or whether a prompt change made an agent better or worse. The build already sees every signal (an out-of-plan file, a merge conflict, a hand-back to a coder, a red CI round, a refused acceptance-test diff, a `not met` verdict) and throws it away when the session ends. Now that every run leaves a record (087), these signals can be kept per agent, shape and model, so agent quality becomes evidence the platform produces itself and the weekly retro (090) can propose prompt changes from it.

## Stories

As the platform owner, I want each build to record how well every agent did its part, so that I see which agent in which shape causes the most rework.

As the platform owner, I want to compare an agent's numbers before and after a platform release, so that I know whether a prompt change helped.

As the weekly retro (090), I want ranked agent metrics with example evidence, so that I can propose concrete prompt changes instead of guesses.

## Acceptance criteria

- **AC-089.1** Given a `/svc:build` run (alone, inside `/svc:ship`, or per repo inside `/app:build`), when it ends as done, escalated or interrupted, then its run record (087) holds an agent-metrics section with one entry per agent that took part, each keyed by agent as routed by the shape (`svc:coder`, `web:tester`, `svc:architect`, ...), the repo's shape (`none` for a repo without one) and the agent's model.
- **AC-089.2** Given a task branch merged in Phase 2, when its changes include files outside that task's `files` (new test helpers the coder reported excepted), then the architect's entry counts one out-of-plan event per such file and lists the task id and the path.
- **AC-089.3** Given a task branch whose merge conflicts with work already merged, when the build handles the conflict (escalation today, a re-plan once 094 ships), then the run record holds one plan-accuracy event of kind `merge-conflict` with: spec id, task id, the task id it collided with, the conflicting paths, the plan author's agent and model (the architect that wrote the plan), and an outcome: `re-planned` (the plan was amended and the task is re-running), `resolved` (the task re-ran on the amended plan and merged without conflict) or `escalated` (the build stopped for the user); the event's outcome is updated in place as it changes, so one conflict is one event.
- **AC-089.14** Given a build that amends its plan after a merge conflict (094), when the architect has written the amended plan, then the architect's entry counts one re-plan, linked to the `merge-conflict` event that caused it; the report (AC-089.11) shows merge conflicts and re-plans as separate columns, and the share of conflicts that ended `resolved`.
- **AC-089.4** Given a build that hands work back to a coder (a red gate after a merge, a failing test in Phase 2.5, a red `devbox run ci` round in Phase 3, a `not met` cycle in Phase 4), when the hand-back happens, then that coder's entry counts one fix round with its cause: `lint/type`, `test`, `ci` or `verification`.
- **AC-089.5** Given `cplat ship land` sees a red PR CI round, when it sends the logs to a coder, then that coder's entry counts one red-CI round; a rerun of a transient or stuck run (spec 079) is counted as a platform rerun in the record and never against an agent.
- **AC-089.6** Given the reviewer writes `verification.md`, when its first pass completes, then the entry of the coder of each task covering an affected criterion counts that criterion's finding by severity: `not met`, `partial`, or `deviation` (a deviation the reviewer judged not acceptable); findings of later review cycles are counted separately as `after fix`.
- **AC-089.7** Given `cplat spec test-diff` refuses a change to an acceptance test, when the refusal stops the build, then the entry of the agent whose change triggered it (the task's coder or the quality agent) counts one refused test diff with the test file.
- **AC-089.8** Given the tester's acceptance tests, when criteria are missing from the trace and go back to the tester, or a test fails for a reason other than missing behaviour, then the tester's entry counts one event per criterion or test, with the reason `untraced` or `wrong failure`.
- **AC-089.9** Given a run in which a metric was not observed (the phase never ran, or the run predates this spec), when the record is read, then that metric is "not measured" rather than 0, and the report leaves such runs out of that metric's average and shows `n/a` when no run measured it.
- **AC-089.10** Given recording an agent metric fails (malformed event, write error), when the build continues, then the run is neither stopped nor failed, and the record states that its agent metrics are incomplete.
- **AC-089.11** Given run records in the store, when the user runs `cplat runs report --agents`, then it prints one row per agent × shape × model for the last 30 days with the number of runs and per-run averages of each metric (out-of-plan files, merge conflicts, re-plans, fix rounds by cause, red-CI rounds, findings by severity, refused test diffs, tester events), sorted by total rework, worst first; rows with fewer than 5 runs are marked `few runs`. `--since <date>`, `--agent <name>` and `--shape <shape>` narrow it; `--json` prints the same rows as JSON.
- **AC-089.12** Given `cplat runs report --agents --by-version`, when it runs, then each row is split per platform version, so an agent's numbers before and after a release appear side by side.
- **AC-089.13** Given a report row, when it prints, then it lists up to 3 of the row's most frequent causes (for example the out-of-plan path patterns, the fix-round causes, the criteria most often `not met`), each with a link to one run record that shows it; all text taken from runs is redacted with the same redaction as `cplat feedback`.

## Non-goals

- Writing agent-prompt change proposals or ranking them: spec 090 does that from this report.
- Changing agent prompts automatically.
- Metrics for `/svc:quick-task`, `/svc:fix-bug`, `/svc:release`, `/gitops:*` and the `/app:spec|plan` agents (product-manager, planner).
- Judging the product-manager's specs (for example amendments after approval).
- Token cost and duration per agent (phase durations belong to 087).
- Comparing against an external benchmark; numbers are only compared with each other.

## Open questions

- Which "model" is the key: the alias declared by the agent's definition (`sonnet`, `opus`), or the full model id the session actually ran? (suggested: the declared alias, plus the full id when the orchestrator knows it; affects AC-089.1, AC-089.11)
- Confirm: reviewer findings use the severities `not met`, `partial` and `deviation` (unacceptable deviations only), since the reviewer has no other severity scale. (suggested: yes; affects AC-089.6)
- Confirm: red PR CI rounds count against the coder that fixes them, not against the quality or security agent. (suggested: yes, with the cause from the red check's name; affects AC-089.5)
- Confirm: the report's default window is the last 30 days and rows under 5 runs are marked `few runs`. (suggested: yes; affects AC-089.11)
- Should `/svc:quick-task` and `/svc:fix-bug` also record coder fix rounds now? (suggested: no, a later spec once build metrics prove useful; affects the Non-goals and a new criterion)

## Changelog

- 2026-10-23 created
- 2026-10-23 merge-conflict event fields and outcomes defined for spec 094 (AC-089.3), re-plan count added (AC-089.14)
