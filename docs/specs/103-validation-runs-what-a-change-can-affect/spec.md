---
spec_id: 103-validation-runs-what-a-change-can-affect
title: Validation runs what a change can affect
status: done
priority: P1
tracks: [142]
---

# 103 — Validation runs what a change can affect

## Problem

Every fix round of a build or ship runs the whole validation (lint, tests, acceptance, security, image build) again, even when the change since the last green run is one line in one file. That wastes minutes and tokens: after a red check, the agent fixes one thing and everything reruns (spec 080 already spawns only the agent of a red gate, but the gates themselves still run in full). Letting the agent decide that a change is low risk is not an answer, because a wrong guess skips the check that would have caught a regression or a vulnerability. The platform owner needs the platform to decide, from the diff and fixed rules, which checks a change can affect, to reuse evidence that is still valid, and to show what it skipped and why, without ever running fewer checks than a change requires.

## Stories

- As a developer, I want a fix round to rerun only the checks the change can affect, so that a one-line fix does not cost a full validation.
- As the platform owner, I want the mandatory checks for risky changes to be independent of what an agent says about the risk, so that saving time never weakens a gate.
- As the platform owner, I want to see for every run which checks ran, were reused or were skipped, and by which rule, so that I can trust the savings and find a rule that skipped too much.

## Acceptance criteria

The scope. Change-aware selection applies to the checks a build or ship runs on its own while it works (the loop of build Phase 3 and of ship's fix rounds). It does not apply to the final gate (AC-103.8). A check is one of: lint, unit tests, acceptance tests, security scan, image build, or another check the repo's `devbox run ci` runs.

- **AC-103.1** Given a diff, when the validation plan is made, then it lists every check of the repo as `run`, `reused` or `skipped`, each with the rule that decided it and a short reason, and the rules are deterministic: the same diff and repo state give the same plan.
- **AC-103.2** The mapping of files to components, criteria and tests comes from what the repo already declares in its specs and its test layout. Given a changed file that belongs to a component with acceptance criteria and tests the repo declares, then the plan runs at least the tests of those criteria plus the unit tests of that component. Given a change that only touches documentation files, then the plan skips the tests and still runs lint.
- **AC-103.3** Given a change to any of: a Dockerfile, a dependency manifest or lock file, a CI workflow, a secrets or auth configuration, a spec or an acceptance test, then the plan runs the full test suite and the security scan, whatever else it says and whatever risk anyone reports. The same holds for these categories per shape: for a service, a changed API contract or database migration; for a gitops-app, any change under the environment manifests; for a web repo, a changed route or build configuration.
- **AC-103.4** Given a changed file that no rule or declaration covers, an unreadable diff, or missing mapping data, then the plan runs the repo's full default set, with the reason `no rule`. Selection never skips a check for lack of information.
- **AC-103.5** Given a risk level that an agent reports for a change, then it can only add checks to the plan. It never removes a check that a rule requires, and the plan notes that it was ignored. Where impact is ambiguous, a model may only propose extra checks, never a skip.
- **AC-103.6** Given a check that passed earlier, when its inputs (the source files it reads, the configuration, the dependency lock files, the tool versions and the check's command) are byte-for-byte unchanged, then its earlier result is `reused`, with the run it comes from. Reused evidence is kept on the machine that produced it and is never shared or uploaded. Given any of those inputs changed, or a result that was failed, skipped, missing or unreadable, then the check runs and the old result is not a pass.
- **AC-103.7** Given a finished run, then the output and the run record (spec 087) hold a `validation` section with, for each check, `run`, `reused` or `skipped`, the rule and the reason, and counts for each. The section holds no logs. `cplat runs report` shows these counts per rule.
- **AC-103.8** Given a build or ship that marks a pull request ready or lands it, then the repo's full required set has passed on exactly that HEAD, either by a run now or by reused evidence that AC-103.6 accepts. The CI of the pull request runs the whole `devbox run ci` as today, and nothing in this spec shortens it.
- **AC-103.9** Selection is on by default for the loop of build and of ship's fix rounds. Given `--full` on a build or ship, or the repo opting out in its settings, then the plan runs every check and the output says why.
- **AC-103.10** Given a check that was `skipped` or `reused` in the loop and then fails in the final gate or in CI, when the run ends, then its record counts one `miss` for the rule that decided it, and `cplat runs report` shows misses per rule next to the counts of AC-103.7.
- **AC-103.11** Given `cplat runs benchmark` (spec 099) for the fixed tasks, when it runs with change-aware validation on and again with it off, then it reports both runs' duration, tokens and cost, and the checks that ran in each. It exits non-zero if any check that a rule requires did not run or pass in the change-aware run, and it writes the result into the benchmark's record. There is no savings target; the numbers are reported.

## Non-goals

- A full code intelligence or dependency graph (issue #139). This spec uses the mapping the repo declares and what the diff shows, and uses richer impact data only when it is available.
- Removing, weakening or shortening any check, or changing the CI of the pull request (spec 074, spec 075).
- Choosing agents or models per task, budgets and stopping repeated failures (spec 102), measuring usage (spec 099).
- Sharing evidence between machines or a remote cache.
- Skipping checks in the final gate or in the security and acceptance gates of specs 068 and 081.

## Open questions

- ~~Is selection limited to the inner loop, with the final gate and the pull request's CI always running everything?~~ Answered: yes, see AC-103.8.
- ~~Which more categories are mandatory per shape, beyond AC-103.3?~~ Answered: service: a changed API contract or database migration; gitops-app: any change under the environment manifests; web: a changed route or build configuration, see AC-103.3.
- ~~Is selection on by default?~~ Answered: yes for build and ship fix rounds, with `--full` as the way out, see AC-103.9.
- ~~Where does the mapping of files to components, criteria and tests come from?~~ Answered: what the repo already declares in its specs and test layout; an unmapped file falls back to the full set, see AC-103.2 and AC-103.4.
- ~~Does the benchmark need a savings target?~~ Answered: no, only the coverage check, and the numbers are reported, see AC-103.11.
- ~~Confirm: reused evidence stays on one machine and is not shared.~~ Answered: yes, see AC-103.6.

## Changelog

- 2026-10-25 created
- 2026-10-25 amended: folded in the user's answers (per-shape mandatory categories, default on, mapping source, no savings target, local evidence).
- 2026-10-25 approved
- 2026-10-28 building
- 2026-10-28 done
