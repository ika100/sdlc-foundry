---
spec_id: 100-leaner-runs-cheaper-coordinator-fewer
title: 'Leaner runs: cheaper coordinator, fewer turns, smaller context'
status: done
priority: P1
tracks: [139]
---

# 100 — Leaner runs: cheaper coordinator, fewer turns, smaller context

## Problem

Headless runs cost more than the work needs. In the spec-099 benchmark `quick-task` on platform 4.5.0 (run 20261025T113632Z-73dcf110) the run finished with a real PR in 2m41s, 22 calls, 674,791 tokens, est. $0.48. The coordinator (the main session, on Opus because headless sessions start on the user's default model) made 14 of those calls and cost $0.36, 75% of the total, while coder, tester and quality agents already run on Sonnet. The previous delivery round averaged 71k context per subagent call, spec.md was read 220 times, and the command prompts (build about 20 KB, ship about 10 KB, quick-task about 8 KB) ride along on every coordinator turn. Spec 099 made this measurable, so each saving can now be proven. Part of #139.

## Stories

As a platform user running headless, I want the coordinator to run on a cheaper model by default, so that a run costs less without my changing anything.

As a platform user, I want deterministic multi-command steps to be one command, so that the coordinator spends fewer turns on them.

As a platform user, I want agents to get the facts they need in their brief and quiet tool output, so that each agent call carries less context.

As a platform maintainer, I want rarely used branches of the big commands out of the default prompt, so that every coordinator turn is smaller.

As a platform maintainer, I want each step measured with the benchmark and rolled back if it hurts the outcome, so that savings never cost quality.

## Acceptance criteria

Step 1: cheaper coordinator

- **AC-100.1** Given a headless run started without a model option or setting, when the coordinator session starts, then it runs on Sonnet.
- **AC-100.2** Given `cplat headless --model <model>`, when the run starts, then the coordinator runs on that model, and `opus` is accepted.
- **AC-100.3** Given a project setting and a user setting for the coordinator model and no flag, when a run starts, then the project setting wins over the user setting; given the `--model` flag, it wins over both.
- **AC-100.4** Given a project setting with a per-workflow map (for example `build: opus`), when that workflow runs headless without a flag, then its coordinator runs on the mapped model while other workflows use the general setting or the default.
- **AC-100.5** Given a model name other than `sonnet`, `opus` or `haiku` in the flag or a setting, when the run is requested, then it is refused before anything starts, with a message naming these three values.
- **AC-100.6** Given any coordinator model, when the architect, reviewer or product-manager agent runs, then it uses its own configured model, unchanged.

Step 2: fewer coordinator turns

- **AC-100.7** Given finished, gated work at the end of quick-task, fix-bug or build, when the coordinator runs the finishing step, then a single `cplat` command commits, pushes and opens the PR, and the coordinator makes one tool call for it.
- **AC-100.8** Given that command fails part-way (nothing to commit, push rejected, PR already open), when it stops, then it reports which part succeeded and which failed, makes no partial duplicate (no second commit, no second PR), and exits non-zero.
- **AC-100.9** Given any other deterministic multi-command step that this step turns into one command, when it runs, then it has the same observable result as the separate commands and has automated tests.

Step 3: compact briefs, quiet output

- **AC-100.10** Given an orchestrator briefing the coder, tester or quality agent, when it writes the brief, then the brief contains the acceptance criteria, file paths and facts that agent needs, so the agent does not need to read spec.md, plan.md or design.md to start.
- **AC-100.11** Given the reviewer agent, when it is briefed, then it still reads the full spec.
- **AC-100.12** Given test and tool commands in an agent brief, when they succeed, then their output is quiet by default (for pytest, `-q --tb=line`); when they fail, the full log is available to the agent.

Step 4: shorter command prompts

- **AC-100.13** Given build, ship and quick-task, when a run takes the normal path, then the rarely needed branches (resume, conflicts, special cases) are not in the prompt it loads, and each of those prompts is smaller than before on the normal path (no numeric target).
- **AC-100.14** Given a run that takes one of those branches, when it reaches it, then it reads the matching reference file and behaves as before the move.

Acceptance by benchmark

- **AC-100.15** Given the pinned `quick-task` sample, when `cplat runs benchmark` runs after all four steps, then the run is done, a PR is opened, all gates pass, and the estimated cost is at most $0.30.
- **AC-100.16** Given the `build` benchmark (plan and build of the fixed spec 900), when it runs after all four steps, then the run is done, a PR is opened, all gates pass, the reviewer passes, and the estimated cost is at least 30% below the build baseline recorded in this spec.
- **AC-100.17** Given each step delivered on its own, when its quick-task and build benchmarks run, then the run ids and estimated costs are recorded in the verification, and a step that lowers cost but fails a gate or changes the outcome is rolled back and not accepted.

Baselines (platform 4.5.0, installed svc 3.4.0, sample `ika100/todo-api`, prices of 2026-10-25):
- `quick-task` v2 @ `17eb5e4`: run `20261025T113632Z-73dcf110`, done, 22 calls, 674,791 tokens, **$0.48** est. (coordinator 14 calls, $0.36).
- `build` v3 @ `ef04f90`: run `20261025T123218Z-f4e36dbe`, done, 81 calls, 2,617,700 tokens, **$1.64** est. (plan $0.48, build $1.17; coordinator 49 calls, $1.03; Opus $1.41, Sonnet $0.24). Superseded by the v4 baseline below.
- `build` **v4** @ `ef04f90` (spec 900 v4 states AC-900.2 unambiguously; same worktree plugins as the step runs, coordinator `--model opus`): runs `20261025T133329Z-d19e689b` $1.75 and `20261025T135136Z-d3ddd653` $2.12, both done with a PR and both gates passed: median **$1.94**. The build target of AC-100.16 is therefore at most **$1.36**.

## Non-goals

- Budgets and enforcement (#144).
- No-progress breakers (#141).
- Change-aware validation (#142).
- Changing gate strictness.
- Removing agents.

## Open questions

- ~~Default coordinator model?~~ Answered: Sonnet, see AC-100.1.
- ~~Which setting holds the model and per-workflow override?~~ Answered: project setting with optional per-workflow map beats user setting; flag beats both, see AC-100.3, AC-100.4.
- ~~Accepted model names?~~ Answered: sonnet, opus, haiku, see AC-100.5.
- ~~Size target for command prompts?~~ Answered: none, they only must shrink, see AC-100.13.

## Changelog

- 2026-10-25 created
- 2026-10-25 amended: open questions answered and folded into AC-100.3, AC-100.4, AC-100.5, AC-100.13
- 2026-10-25 approved
- 2026-10-25 building
- 2026-10-25 draft: amend: build baseline moves to spec 900 v4 (median of two Opus runs)
- 2026-10-25 approved
- 2026-10-25 building
- 2026-10-25 done
