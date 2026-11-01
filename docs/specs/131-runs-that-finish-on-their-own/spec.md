---
spec_id: 131-runs-that-finish-on-their-own
title: Runs that finish on their own
status: approved
priority: P1
shape: platform
tracks: [324]
---

# 131 — Runs that finish on their own

## Problem

Unattended delivery rarely finishes. Of 52 `ship` runs from 2026-10-24 to 2026-10-31, 16 were done (31%), ai-ops finished 0 of 20, and about half of the estimated agent spend went to runs that ended escalated or failed (roadmap #339, bet 1). The top causes are run plumbing, not code. A whole ship is one long session that the Stop hook holds until it gives up or makes no progress (10 and 4 escalations). Git and `gh` actions are refused because a non-interactive session cannot ask for approval (3 to 4, the W43 retro #207 proposal 1). The budget is a fixed $15, 180 minutes and 60 invocations whatever the plan size: it ran out once with 20 of 20 tasks done and only the review missing, and spec 128's build (8 tasks, 14 criteria) ran out before verification with green CI (#324). `cplat headless` (spec 070) already resumes a run in fresh sessions, but each session tries to finish the whole remaining run, so one hard step uses up the context, the stops and the budget of everything after it.

## Stories

- As a developer, I want an unattended ship to run as a sequence of small units, each in its own fresh session and each saved when it is done, so that a session that ends or fails loses at most one unit and the run continues where it stopped.
- As a developer, I want an unattended run to get exactly the git and `gh` permissions it needs before it starts, without anyone editing my settings, so that it never stops on an approval nobody can give, and so that anything it cannot be granted fails before it spends anything.
- As the platform owner, I want the default budget to grow with the size of the plan, and a run whose tasks are all done to finish its verification instead of escalating, so that a large spec is not stopped by a limit sized for a small one.
- As the platform maintainer reading the weekly retro, I want to see whether unattended ships now finish, so that I know whether bet 1 worked.

**Repos:** sdlc-foundry (the platform; the behaviour applies in every repo where `cplat headless` runs an unattended ship or build).

## Acceptance criteria

Words used below. A **unit** is one step of an unattended ship or build that gets its own session, in this order: **plan** (the plan exists and is checked), **red tests** (the failing acceptance tests are committed), one **task** unit per open task of the plan, in the order its dependencies allow, **verification** (the CI gate, the check against the spec and closing the spec), and **land** (PR, green CI, merge and, where the repo deploys, the pin of the deploy). A unit that is already complete when the run starts or resumes is skipped. The **supervisor** is `cplat headless` running such a run. A **checkpoint** is the saved end of a unit: its work committed on the feature branch (for a task, the commit that marks the task done in the plan) and the unit recorded as done in the run state, together with the commit it ended on.

The supervisor and its units.

- **AC-131.1** Given an approved spec with a plan of 3 open tasks, when the supervisor runs its unattended ship, then it starts 7 sessions one after the other (plan, red tests, the 3 tasks, verification, land), each session's prompt names its unit, and the run's summary log has one line per session naming the unit and how it ended.
- **AC-131.2** Given a unit session that reaches its unit's checkpoint, when it tries to stop, then the Stop hook lets it stop, and the supervisor starts the next unit in a new session. A session is never held to continue past its own unit.
- **AC-131.3** Given a unit session that ends before its checkpoint (it stops, its context fills up or it is killed), when the supervisor continues, then the next session starts the same unit from the last checkpoint, and no unit that has a checkpoint runs again unless its commit is no longer on the feature branch.
- **AC-131.4** Given the supervisor itself is interrupted (the machine sleeps, the process is killed) and the same command is started again, then it continues at the first unit without a checkpoint, and the budget's usage continues from where it stopped (AC-102.6).
- **AC-131.5** Given a unit whose sessions end 2 times in a row without its checkpoint and without a new commit on the feature branch, then no third session is started and the run escalates with the reason `no progress: unit <unit> after 2 sessions without a commit`, its cause chosen as in AC-126.7. A session that adds a commit without reaching the checkpoint resets the count; such a unit is bounded only by the budget.
- **AC-131.6** Given a run with more units than the default `--max-runs`, when the user did not pass `--max-runs`, then the session count does not stop the run before its last unit (the budget and AC-131.5 bound it); given `--max-runs`, then it applies as in AC-070.2.
- **AC-131.7** Given an unattended run in progress, when the user asks for the ship status, then it lists every unit with `done`, `running` or `open`, the number of sessions each unit used, and the commit of each checkpoint.
- **AC-131.19** Given a ship run started by platform 5.5 that is unfinished, not escalated and has no units in its run state, when the supervisor resumes it, then it derives the units from the run's phase and the plan's `done` flags (every unit before the phase and every task marked done counts as checkpointed at the feature branch's current commit), starts the first unfinished unit, and asks the user for nothing.

Permission preflight. The **run allowlist** is the set of actions the unattended command needs beyond file edits in the repo: create and switch to the spec's feature branch, commit with sign-off (`commit -s`), push the feature branch without force, open the PR (`gh pr create`), and merge only through the platform's land step, which merges after every check of the PR passed.

The covered commands are `/component:ship` and `/component:build` run by `cplat headless`, and `/system:ship` for each repo it drives.

- **AC-131.8** Given an unattended run of a covered command, when the supervisor starts, then before the first session it prints the run allowlist, and every session of the run is started with exactly that allowlist granted for that session (`--allowedTools`) in addition to the repo's committed allowlist.
- **AC-131.9** Given any preflight, whether it passes or fails, then no settings file (the repo's committed allowlist, local settings, user settings) is created or changed: each is byte for byte the same before and after the run.
- **AC-131.10** Given a session of an unattended run that tries a force push, a push to the default branch, a merge outside the land step, or a merge while a check of the PR is pending, failed or missing, then the action is refused; the run allowlist never contains these.
- **AC-131.11** Given an action of the run allowlist that cannot be granted, when the supervisor starts, then no session is started, the run ends with exit code 1 and one line `preflight failed: <category>: <detail>` naming the action and what to do, and the run is recorded as escalated with the cause `environment` and the reason `preflight failed: <category>`. The categories are `blocked-by-settings` (a deny or ask rule of any settings layer matches the action; the detail names the rule and its layer), `git-identity` (no author identity for a signed-off commit), `gh-auth` (`gh` is not logged in for the repo's host), `no-push-access` (the remote refuses pushes by this account), and `no-repo-allowlist` (the repo has no committed allowlist, as in AC-070.5).
- **AC-131.12** Given a preflight that fails, then the run's budget shows 0 invocations and $0 used, and no branch, commit or PR was created.

Budgets that scale with the plan. T is the number of open and done tasks in the plan and C the number of active criteria of the spec.

- **AC-131.13** Given an unattended ship or a build started without budget options, when its plan exists, then its default limits are cost `max(15, 10 + 1.5·T + 0.5·C)` USD, minutes `max(180, 60 + 15·T + 5·C)`, invocations `max(60, 20 + 5·T + C)` and CI reruns 6; for spec 128 (8 tasks, 14 criteria) that is $29, 250 minutes, 74 invocations and 6 reruns. A limit given as an option replaces its default, and a run covering several specs gets the sum of each spec's defaults (this replaces the multiplication of AC-102.1 for runs with a plan).
- **AC-131.14** Given a run that starts before its plan exists, when the plan unit reaches its checkpoint, then the limits are raised to the defaults of AC-131.13 (never lowered), the start output of the next session shows the new limits with `T` and `C`, and the run record notes the change as in AC-102.6.
- **AC-131.15** Given a run whose budget is used up in any limit while every task of the plan has a checkpoint and only verification is left, then instead of escalating it starts verification within a grace of 20% of each limit (at least $3, 30 minutes and 10 invocations), prints `budget grace: verification`, and records the grace and its use in the run's budget section. The grace is given once per run and never to an earlier unit or to land.
- **AC-131.16** Given a run in its grace whose grace is used up, then it escalates with the reason `budget exhausted: <limit> (grace used)`, and given any run in its grace, then no mandatory check is skipped or counted as passed (AC-102.8).
- **AC-131.17** Given a run tree in which subagents ran (coder, tester, reviewer), when the budget's cost is shown or checked, then it includes every subagent's cost; where a subagent's cost cannot be read, the cost is `unknown` as in AC-102.5, never a lower figure.

Success measure.

- **AC-131.18** Given the run records of the first 7 days after the release that ships this spec (`cplat platform runs report --since 7`), then at least 70% of unattended ship runs end `done`, less than 20% of the estimated spend of unattended ships is in runs that ended escalated or failed, no escalation names a git or `gh` action refused for lack of approval, and no run escalates on a budget limit with every task done and only verification left.

## Non-goals

- Batched decision escalations with a proposed answer in the inbox (#339 bet 1, fourth part): a follow-up spec.
- Writing, changing or adding to any settings file to grant permissions. The preflight grants per run and per session only; making a repo's committed allowlist fit unattended runs stays a template change.
- Running several task units in parallel in an unattended run; units run one session at a time.
- The attended `/component:build` and `/component:ship` in an interactive session: they keep today's flow (one session, parallel worktrees).
- Per-unit sessions for `/system:ship` in the repos it drives: a follow-up spec. In this spec `/system:ship` gets only the preflight (AC-131.8 to AC-131.12) and the scaled budgets (AC-131.13 to AC-131.17).
- Preflight for fleet commands.
- A grace for land or for any unit before verification.
- A supervisor that runs anywhere but on the user's machine (no server, queue or scheduler; scheduling stays as in spec 070).
- Changing the stop rules of spec 126 for attended runs, the equivalent-failure stop of AC-102.9 or the 3-fix-round escalation of `cplat ship`.
- Per-unit budgets; the budget stays one per run tree (spec 102).
- The test-diff approvals of #324 (second problem), the doubled CI runs of #322, buffered output of #335 and the launcher's checkout choice of #320.

## Open questions

- ~~Which budget formula, and how large is the grace?~~ Answered (user, 2026-11-01): cost `max(15, 10 + 1.5·T + 0.5·C)`, minutes `max(180, 60 + 15·T + 5·C)`, invocations `max(60, 20 + 5·T + C)`, reruns 6; a grace of 20% of each limit, at least $3, 30 minutes and 10 invocations, once, when only verification is left, see AC-131.13 and AC-131.15.
- ~~Must the ledger's missing subagent cost (#324) be fixed in this spec, before budgets scale?~~ Answered (user, 2026-11-01): yes, see AC-131.17.
- ~~Confirm: what a checkpoint is.~~ Answered (user, 2026-11-01): the unit's commit on the feature branch plus the unit recorded as done in the run state; it stops counting once that commit is gone from the branch, see AC-131.3 and AC-131.7.
- ~~Does the attended `/component:build` also use one session per task?~~ Answered (user, 2026-11-01): no, only unattended runs under `cplat headless`, see Non-goals.
- ~~Confirm: unattended task units run one after the other.~~ Answered (user, 2026-11-01): yes, without parallel worktree batches, see AC-131.1 and Non-goals.
- ~~Confirm: the unit list.~~ Answered (user, 2026-11-01): verification is the CI gate, the check against the spec, the image and closing the spec; land is PR, CI, merge and the deploy pin, see AC-131.1 and AC-131.15.
- ~~What happens to 5.5 ship runs still in flight?~~ Answered (user, 2026-11-01): their units are derived from the ship phase and the plan's `done` flags and the run continues at the first unfinished unit with nothing for the user to do, see AC-131.19.
- ~~How many sessions may a unit use before the run escalates?~~ Answered (user, 2026-11-01): 2 in a row without a commit; no cap while sessions add commits, the budget bounds it, see AC-131.5.
- ~~Confirm: `--max-runs` does not cap a unit run unless the user passes it.~~ Answered (user, 2026-11-01): yes, see AC-131.6.
- ~~Which commands does the preflight cover?~~ Answered (user, 2026-11-01): `/component:ship` and `/component:build` under `cplat headless`, and `/system:ship` for each repo it drives; fleet is not in this spec, see AC-131.8 and Non-goals.
- ~~Does `/system:ship` also get per-unit sessions?~~ Answered (user, 2026-11-01): no, only the preflight and scaled budgets; per-unit sessions for it are a follow-up spec, see Non-goals.
- ~~Confirm: the preflight categories.~~ Answered (user, 2026-11-01): `blocked-by-settings`, `git-identity`, `gh-auth`, `no-push-access`, `no-repo-allowlist`, recorded with cause `environment`, see AC-131.11.
- ~~Should the grace also cover land?~~ Answered (user, 2026-11-01): no, verification only, see AC-131.15 and Non-goals.
- ~~Confirm: the success measure.~~ Answered (user, 2026-11-01): at least 70% of unattended ships done and less than 20% of their spend in escalated or failed runs, over the first 7 days after release, see AC-131.18.

## Changelog

- 2026-11-01 created
- 2026-11-01 amended: folded in the user's answers (all suggested answers): budget formula and verification-only grace, subagent cost fixed in this spec, checkpoint definition, unattended-only and sequential task units, unit list, resume of 5.5 runs in flight (new AC-131.19), 2 sessions without a commit per unit, `--max-runs` uncapped by default, preflight scope including `/system:ship` (fleet out), no per-unit sessions for `/system:ship` (follow-up), preflight categories, success measure.
- 2026-11-01 approved
