---
spec_id: 111-unattended-runs-spend-turns-only-on-judgement
title: Unattended runs spend turns only on judgement
status: approved
priority: P2
tracks: [139]
---

# 111 — Unattended runs spend turns only on judgement

## Problem

The 4.7.0 benchmarks (docs/BASELINES.md) show where an unattended run's money goes. The coordinator is 50–60% of a ship ($0.60–0.99 of $1.20–1.60): 40–55 calls, each re-reading 50–60k tokens of context, many of them only to call the next deterministic `cplat ship` step and read its output. Every headless session also starts by writing about 30k tokens of context, part of which is the user's personal MCP servers and claude.ai connectors (mail, calendar, drive, home automation, browser). An unattended run never needs those, and they are a risk in a run nobody watches. And `/svc:quick-task` costs $0.15 or $0.30 for the same one-file change depending on whether the coordinator happens to make the change itself or spawns coder, quality and tester; nothing decides which is allowed.

## Stories

- As the platform owner, I want the deterministic part of a ship to run as code, so that I pay for coordinator turns only where a judgement is needed.
- As the platform owner, I want unattended sessions to load only the repo's own tools, so that they start cheaper and cannot reach my personal accounts.
- As a developer, I want a trivial quick-task to take a cheap path only when a rule says it is trivial, so that cost is predictable and the quality and test gates still run.

## Acceptance criteria

Each part is measured against the 4.7.0 baseline before it is kept (AC-111.10).

Ship without coordinator turns between deterministic steps:

- **AC-111.1** Given a ship run whose PR is open, when the coordinator runs `cplat ship continue`, then cplat runs `land` and then `deploy` in one command, without returning to the coordinator in between, and stops at the first point that needs judgement: a red check that needs a fix round, an escalation, or done. Its output names that point and the next step in the same form as the single steps do today.
- **AC-111.2** Given `cplat ship continue`, then every rule of the single steps still holds: merge only on green (ADR-028), the budget safe points of spec 102, the CI rerun rules, the deploy gate of spec 105, and the run record of spec 087. The single steps `land` and `deploy` keep working unchanged.
- **AC-111.3** Given `/svc:ship`, when the PR is open, then the command text uses `cplat ship continue` and calls `land` or `deploy` on their own only to resume after a fix round.

Headless sessions load only the repo's own tools:

- **AC-111.4** Given `cplat headless` or `cplat runs benchmark`, when it starts a Claude Code session, then the session loads MCP servers only from the repo's `.mcp.json` (none when there is none), with `--strict-mcp-config`, and claude.ai connectors are off (`disableClaudeAiConnectors`). The user's own MCP servers and connectors are not available in the session.
- **AC-111.5** Given a repo whose workflow needs a server that is not in its `.mcp.json`, when that need is declared in `.platform-settings.yml` (`headless: {mcp_config: <file>}`), then that file is loaded as well; nothing else is.
- **AC-111.6** Given an interactive session (no `cplat headless`), then nothing changes: the restriction applies only to sessions cplat starts.

A trivial quick-task path decided by a rule:

- **AC-111.7** Given `/svc:quick-task`, when the coordinator has made a change itself, then `cplat quick-task inline-check` decides whether that is allowed: the diff touches at most one source file and at most one test file, at most 60 changed lines, and no dependency manifest, lock file, CI workflow, Dockerfile, settings file or spec. Exit 0 allows the inline path; otherwise it exits 1 naming the rule that failed, and the change goes through coder → quality → tester as today.
- **AC-111.8** Given the inline path, then quality (`cplat quiet quality`) and the tests (`cplat quiet test-fast`) still run and must be green before `cplat pr open`, and the PR body says the change was made inline and why the check allowed it.
- **AC-111.9** Given a quick-task that started inline and fails `inline-check` or a gate, then the run switches to the agent path for the rest of the task and does not try the inline path again.

Measurement:

- **AC-111.10** Given each of the three parts, when it is built, then it is benchmarked with the worktree's plugins (`--plugins`): the ship part with 2 ship runs, the session part with 1 quick-task and 2 builds, the quick-task part with 2 quick-tasks, on the sample at the 4.7.0 pin. A part is kept only if its median cost is below the 4.7.0 baseline (quick-task $0.30, build $1.31, ship $1.40) and every run still ends done with a PR and green gates; otherwise it is reverted and the record says why. The results go into the spec folder's `benchmarks.md` and docs/BASELINES.md.

## Non-goals

- Choosing models per agent (an architect on Sonnet for small specs); that trades quality for cost and needs its own spec with a quality check.
- Shrinking the command files further (spec 100 showed that lever is small).
- Changing what a coder, tester or reviewer does, or any gate.
- Restricting MCP servers in interactive sessions.

## Open questions

- ~~Should `cplat ship continue` run through `deploy`, or stop after `land`?~~ Answered: through `deploy`, stopping at the first judgement point, see AC-111.1.
- ~~Are the inline limits right: one source file, one test file, 60 changed lines?~~ Answered: yes, see AC-111.7.
- ~~Should headless sessions keep the repo's `.mcp.json` servers?~~ Answered: yes, see AC-111.4.
- ~~Is the extra MCP config of AC-111.5 needed now?~~ Answered: yes, build it now, see AC-111.5.
- ~~Is the keep-or-revert rule of AC-111.10 right, with these run counts?~~ Answered: yes; more runs only if a result lies within the baseline's spread, see AC-111.10.

## Changelog

- 2026-10-26 created
- 2026-10-26 amended: folded in the user's answers (all as suggested).
- 2026-10-26 approved
