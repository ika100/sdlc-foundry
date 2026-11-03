---
spec_id: 133-build-prs-show-how-they-were-built
title: Build PRs show how they were built
status: done
priority: P2
shape: platform
tracks: [338]
---

# 133 — Build PRs show how they were built

## Problem

A build PR (`/component:build`, `/component:ship`) says what was built and verified, but not how the agent loop got there. In the
5.5.0 work (#328, #330) the parts a reviewer needs were scattered across commit messages, `verification.md` and one line of the PR
body: the user's decisions (answers, approved test changes, raised budgets), the hand-backs and fix rounds (which task went back to
which agent and why), the deviations the reviewer accepted, and how the run went (sequential fallback, re-plans, budget used against
the limit, wall time). The run already records most of this locally (agent events, gates, the budget ledger, test-diff refusals,
re-plans); nothing turns it into something a reviewer reads (#338). Related: #326 asks contributors how a PR was produced, so the
platform's own PRs should show it in a form a reviewer can check.

## Stories

As a reviewer of a build PR, I want a short, generated "How this was built" section in the PR body, so that I see where the user
decided, where work went back to an agent and which deviations were accepted, without reading every commit.

As a platform maintainer, I want that section written by `cplat` from the run's own records, so that it is the same in every repo and
cannot be embellished by the orchestrator.

As an operator without a run store (`CPLAT_RUNS_REPO` unset), I want the section anyway, from the records kept on my machine.

## Acceptance criteria

- **AC-133.1** Given a run id whose record is in progress or in the local buffer, when `cplat platform runs report --pr <run-id>`
  runs (with or without `CPLAT_RUNS_REPO`), then it exits 0 and prints one Markdown block that starts with the line
  `<!-- cplat:how-built -->`, then `<details><summary>How this was built</summary>`, and ends with `</details>` and
  `<!-- /cplat:how-built -->`; inside are, in this order, the headings `How it ran`, `User decisions`, `Hand-backs and fix rounds`
  and `Deviations the reviewer accepted`.
- **AC-133.2** Given a run id that is neither in progress nor in the local buffer, when `cplat platform runs report --pr <run-id>`
  runs, then it exits 1, prints nothing on stdout and names the run id with a hint on stderr; `--pr` together with `--agents`,
  `--benchmarks`, `--json`, `--since` or `--repo` is refused with exit 1 as well.
- **AC-133.3** Given a run, when the section is rendered, then `How it ran` names the run id and kind, the wall time (from the
  record's `started_at` to its `ended_at`, or to now while it runs, summed over the runs it resumes when their records are local, with
  the number of runs), whether the tasks ran in parallel batches or sequentially and why (from the run's `execution` record, else
  `not recorded`), the number of re-plans, the CI rounds and reruns, the recorded gates, and the agents that took part.
- **AC-133.4** Given a run whose tree has a budget ledger, when the section is rendered, then `How it ran` shows for each limit
  (minutes, invocations, reruns, cost) the amount used against the limit (`off` for no limit, `unknown` for a cost that cannot be
  read); without a ledger it shows `budget: not recorded`.
- **AC-133.5** Given a run, when the section is rendered, then `User decisions` lists: each budget limit changed when the run was
  started again (from, to); each escalation for a decision (cause `decision`) of the run and of the runs it resumes, with its reason;
  each test-diff refusal shown to the user (file, task, reason); each user-approved test change from the record's
  `approved_test_diffs` section when the record has one, else the line `user-approved test changes: not recorded (#324)`; and the
  number of answered open questions in the spec's `spec.md`. With none of these it says `none recorded`.
- **AC-133.6** Given a run, when the section is rendered, then `Hand-backs and fix rounds` has one line per recorded fix round (task,
  agent, cause), red CI round (checks, agent), reviewer finding (criterion or task, severity, cycle), tester hand-back (criterion or
  test, reason), merge conflict (task, the task it clashed with, outcome) and re-plan (task, agent); with none it says `none`.
- **AC-133.7** Given the run's spec has a `verification.md` with a `## Deviations from the plan` section, when the section is
  rendered, then `Deviations the reviewer accepted` lists each top-level item of it that calls itself acceptable or accepted and not
  `not acceptable`, shortened to its first sentence (at most 200 characters); without such items it says `none listed`, and without
  `verification.md` it says `no verification.md yet`.
- **AC-133.8** Given records that carry secrets, e-mail addresses or home-directory names in reasons, paths or check names, when the
  section is rendered, then every value from a record or file passes through the run records' redaction (`feedback.redact`) first;
  the section contains no prompts and no diffs, each list keeps at most 10 lines and then says `… and <n> more`.
- **AC-133.9** Given a build or ship run, when `cplat platform runs agent execution parallel|sequential [--reason <text>]` runs in its
  repo, then the run record gets the section `execution` = `{"mode": <mode>, "reason": <text or null>}` (the last call wins, exit 0
  always, as the other agent calls); `/component:build` records it after the worktree probe (`parallel` when the probe reports the
  feature head, `sequential` with the reason from the fallback reference otherwise).
- **AC-133.10** Given a checkout with a current run (the `cplat platform runs begin` pointer or the ship run, as
  `runs.current_run` finds it) whose spec is the PR's `--spec` (or either is unset), when `cplat pr open` runs, then it appends the
  AC-133.1 block to the PR body before `gh pr create`, both when it opens the PR and when it ends at a ready PR.
- **AC-133.11** Given a checkout without a current run, or a run for another spec, when `cplat pr open` runs, then the PR body is
  left byte for byte as it was; and when building the section fails, the body is left unchanged, the PR still opens, and the output has
  one extra line `note: how-this-was-built skipped: <why>`.
- **AC-133.12** Given a PR body that already contains a block from AC-133.1, when `cplat pr open` runs again, then the block is
  replaced, not added a second time.
- **AC-133.13** Given the docs, when a user reads `/platform:runs`, `/component:build` and the changelog, then `/platform:runs`
  names `cplat platform runs report --pr <run-id>`, `/component:build` names the `execution` call and says that `cplat pr open` adds
  the section, and the changelog has an entry for #338.

## Non-goals

- Reading a run from the run store: `--pr` reads the records on this machine (in progress and buffered), which is where `cplat pr
  open` runs.
- Prompts, the message flow between agents, per-task diffs or commit lists (the commits show those).
- Recording user-approved test changes (#324, a separate fix); this spec only reads that record when it exists.
- Changing what the orchestrator writes in the PR body; the section is added by `cplat`.
- Rendering the section for system ships (`/system:ship`) across several repos.

## Open questions

- ~~Should `--pr` fall back to the run store when the run is not local?~~ Answered (recommended default, 2026-11-03): no; the PR is
  opened on the machine that ran the build, where the record is in progress or buffered. See Non-goals.
- ~~Where in the body does the section go?~~ Answered (recommended default, 2026-11-03): at the end, collapsed, after the
  orchestrator's text and the WIP note. See AC-133.10.
- ~~How is the sequential fallback known, since no record holds it today?~~ Answered (recommended default, 2026-11-03): a new agent
  call `execution` records it; see AC-133.9.
- ~~What about user-approved test changes before #324 lands?~~ Answered (recommended default, 2026-11-03): read an
  `approved_test_diffs` section when present, else say it is not recorded; see AC-133.5. The section's shape is in design.md for #324.

## Changelog

- 2026-11-03 created
- 2026-11-03 approved
- 2026-11-03 building
- 2026-11-03 done
