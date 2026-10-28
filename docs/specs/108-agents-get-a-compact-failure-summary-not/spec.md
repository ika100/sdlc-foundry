---
spec_id: 108-agents-get-a-compact-failure-summary-not
title: Agents get a compact failure summary, not the full log
status: done
priority: P2
tracks: [139]
---

# 108 — Agents get a compact failure summary, not the full log

## Problem

When a test, lint, type check or build fails during `/component:build` or a ship fix round, the agent that has to fix it reads raw output. `cplat quiet` (spec 100, AC-100.12) already keeps successes to one line, but a failure prints the last 40 lines and the log path, and the agent instructions say to read that log. So the agent often reads the whole log, with progress bars, passing tests, stack frames from libraries and repeated warnings, and it does so again in every fix round. A CI failure in ship is handed over the same way. Most of these tokens carry nothing the fix needs: which check failed, which tests or which file and line, the error, and a few lines around it. A deterministic step can pull those out, with no model involved, while the full log stays on disk for the cases where the summary is not enough. Spec 099 can measure the saving. Part of #139.

## Stories

- As a developer, I want the fixing agent to get a short, structured summary of what failed, so that each fix round costs fewer tokens.
- As a developer, I want the full log to stay available to the agent on demand, so that a summary never hides what a fix needs.
- As the platform owner, I want the summary to come from fixed rules and never drop a failing check, so that a cheaper fix round never misses a failure.
- As the platform owner, I want the saving measured against today's behaviour with the benchmark, so that the change is kept only if it helps.

## Acceptance criteria

The scope. A summary is made for every failing command that `cplat quiet` runs (lint, unit tests, type check, acceptance tests, build) in build Phase 3 and in ship's fix rounds, and for every failing CI check that a ship fix round hands to an agent. A summary has a header (check, command, exit code, log path) and, per failure, an entry: the test id or `file:line`, the rule or error type, the normalized message (normalized as in spec 102: timestamps, paths, ids and line numbers removed) and an excerpt.

- **AC-108.1** Given a command run through `cplat quiet` that fails, when it ends, then it prints the summary instead of the last 40 lines, with the log path in the header, and the exit code of the command passes through unchanged. Given the command succeeds, then the output is the same as today (AC-100.12).
- **AC-108.2** Given a failing test run in a recognized format, then the summary has one entry per failing or erroring test, with the test id, the `file:line` of the failure in the repo's own code, the error type, the normalized message and an excerpt of at most 10 lines. Passing tests, progress output and stack frames outside the repo's code are not in the summary.
- **AC-108.3** Given failing lint, type check or build output in a recognized format, then the summary has one entry per finding, with `file:line`, the rule or error code and the message, and identical findings are listed once with a count.
- **AC-108.4** Recognized formats are the default test, lint, type check and image build tools of the six templates (service-python, library-python, service-java, service-go, web-nextjs, gitops-app). Given output in another format, or output the summary step cannot read, then the summary says `format: unknown` and shows the last 40 lines, as today. A summary is never empty for a failed command.
- **AC-108.5** Given a command that runs several checks (for example `devbox run ci`) and more than one fails, then every failing check appears in the summary with its own header. Given more than 20 entries for one check, then the first 20 are shown, followed by the exact number of entries left out and the log path. Given the summary would exceed 80 lines, then excerpts are shortened first; a failing check or its entry count is never dropped.
- **AC-108.6** Given the same log twice, when it is summarized, then the summary is byte-for-byte identical. The summary is made by fixed rules in `cplat`, with no model call.
- **AC-108.7** Given a summarized failure, then the full log stays on the machine at the path in the header, and the agent brief and agent instructions say to open it only when the summary is not enough. Secrets in the summary are redacted as in spec 087. Neither the summary nor the log goes to the run store.
- **AC-108.8** Given a ship fix round started by a failing CI check, when the fixing agent is briefed, then the failing check's log is saved on the machine, and the brief holds the summary of it and the log path, not the raw CI log.
- **AC-108.9** Given a failure that counts toward the no-progress stop (AC-102.9) or is written to a recovery snapshot (AC-102.10), then the normalized message there is the one in the summary, and the snapshot's excerpt is the summary.
- **AC-108.10** Given a project with no setting for summaries, then summaries are on. Given the project setting turns summaries off, or `cplat quiet` is run with `--raw`, then failures are reported as today (the last 40 lines and the log path), and the output says that summaries are off.
- **AC-108.11** Given `cplat runs benchmark` (spec 099) for a new fixed benchmark task, added by this spec, that starts with one failing test and one lint finding, when it runs once with summaries and once with them off (AC-108.10), then it reports for both runs the outcome, the number of fix rounds, the tokens and cost of the fixing agents' calls and the run total, and writes them into the benchmark's record. There is no savings target: it exits non-zero only if the run with summaries is not done, a gate fails, or it needs more fix rounds than the run without (as in AC-103.11).

## Non-goals

- Summarizing with a model, or letting an agent decide what goes into the summary.
- Budgets, stopping and no-progress logic: spec 102. This spec only supplies the normalized message.
- Choosing which checks run: spec 103. Changing the checks, the CI of the pull request or any gate.
- Leaving a failing check out of the summary to save tokens.
- Summarizing successful output, which stays as spec 100 left it.
- Uploading, sharing or keeping logs beyond what `cplat quiet` keeps today.

## Open questions

- ~~What are the size limits of a summary?~~ Answered: at most 20 entries per check, 10 excerpt lines per entry, 80 lines in total, see AC-108.2 and AC-108.5.
- ~~Which tool formats must be recognized in the first version?~~ Answered: the default test, lint, type check and image build tools of the six templates, everything else falls back to the last 40 lines, see AC-108.4.
- ~~Are CI failures in ship fix rounds in scope, or only local commands?~~ Answered: both, see AC-108.8.
- ~~How are summaries turned off, and are they on by default?~~ Answered: on by default, off with a project setting and a `--raw` flag on `cplat quiet`, see AC-108.10 and AC-108.11.
- ~~Does the benchmark need a savings target?~~ Answered: no, the numbers are reported and the run with summaries must not need more fix rounds, as in AC-103.11, see AC-108.11.
- ~~Confirm: the benchmark gets a new fixed task that starts with a failing test and a lint finding.~~ Answered: yes, a new fixed benchmark task, see AC-108.11.

## Changelog

- 2026-10-25 created
- 2026-10-25 open questions answered (suggested answers)
- 2026-10-25 approved
- 2026-10-28 editorial: `/svc:build` is `/component:build` since 5.0; reading: the cluster-gitops template (new in 5.x) is outside AC-108.4's six and falls back to the last 40 lines
- 2026-10-28 building
- 2026-10-28 done
