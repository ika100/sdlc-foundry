---
spec_id: 136-the-whole-journey-fits-a-time-budget
title: The whole journey fits a time budget
status: done
priority: P1
shape: platform
---

# 136 — The whole journey fits a time budget

## Problem

The 2026-11-04 demo recording (sdlc-foundry 5.7.0, three parts: empty folder → a feature in dev; database and web UI across three repos; staging, release, prod with backups) took about 3 h 15 of working time with the waits cut, and about 9 h 15 of wall clock (BASELINES.md, parts 1 and 2; BASELINES.md (part 3, PR #413)). Users expect the whole journey to take no more than an hour, and the first part, from an empty folder to a feature in dev, about 20 minutes. More than half the working time came from defects found in the run. Without them the journey would still take about 90 minutes: agent work about 35–40, CI about 25–30 (31 PRs, mostly one after another), and images, pins, Argo, smoke and the cluster about 15–20. Wall clock was mostly GitHub's GraphQL limit (#409) and decisions waiting for a person. Nothing today measures the journey as a whole or per stage, so no release can show whether it got faster or slower, and nobody can say which fix saves the most time. Specs 087, 099 and 102 measure single runs and cap their spending, not the journey.

## Stories

- As a new user, I want to get from an empty folder to my first feature running in dev in about 20 minutes, so that I can judge the platform in one sitting.
- As a user, I want the whole journey to prod, backups included, to take no more than an hour of platform time, so that delivering a feature does not take an afternoon.
- As the platform owner, I want every journey run to record the time of every stage, so that I can compare platform versions on the same work and see which stage is over its budget.
- As the platform owner, I want stages that go over budget to show up in the report, ranked by the minutes they lose, so that the next work goes where it saves the most time.

## Known time sinks

The issues found in the 2026-11-04 recording, ranked by the working time each one cost (estimated per full journey). Each is fixed as a separate issue, not inside this spec. Together they are why the journey cannot finish within its budgets yet. The fixes are ordered by measured saving: the ranking below until the first measured journeys exist, then the overrun ranking of AC-136.8.

| Rank | Issue | What happens | Est. saving |
|---|---|---|---|
| 1 | #421 | The web-nextjs runtime image ships npm with a vulnerable undici, so every web release is blocked | ≈ 30 min (a release fix round) |
| 2 | #418, #414 | A backup bucket exists only where a component uses it; plan-check knows only postgres and rejects an empty gitops list | ≈ 20 min (spec and plan reworked) |
| 3 | #408 | Resuming an escalated ship loses its merged PR | ≈ 10–15 min |
| 4 | #425 | `cluster-up` and the operators install External Secrets twice | ≈ 10 min |
| 5 | #424 | `restore --discard` waits for an Argo sync that cannot happen (prune off) | ≈ 10 min |
| 6 | #410 | The spec PR's squash merge makes the feature PR conflict on its spec | ≈ 4 min per ship (≈ 10 per journey) |
| 7 | #422 | Instance verify is not recorded, so the prod gate always warns and a person must decide | ≈ 5 min + a decision wait |
| 8 | #426 | The release procedure builds a new commit instead of the tested one | ≈ 5 min + an extra build |
| 9 | #427 | No command for observability and backups | ≈ 5 min, extra PRs |
| 10 | #420 | Generated checksum and credential lines trip detect-secrets | ≈ 3 min per occurrence (2 seen) |
| 11 | #423 | `platform update --verify` clones branch 0.1.0 instead of tag v0.1.0 | ≈ 3 min |
| 12 | #419 | `cluster-up` prints `:default` instead of the port | ≈ 2 min |
| 13 | #428 | An agent rule contradicts auto-filed issues | ≈ 1 min |
| — | #415, #416, #417, #429 | Correctness, safety or display | no time saving |
| wall clock | #409 | The console and the CI waits use up the account's GraphQL limit, and cplat stops instead of waiting | the largest wall-clock sink (≈ 83 min in part 2 alone) |

Already fixed: #412 (the bucket race, ≈ 40 min in part 3). State on 2026-11-05: fixed and released in 5.8.0–5.9.0:
#408, #409, #410, #414, #415, #416, #417, #419, #420, #421, #422, #423, #424, #428, #429. Open: #418 (spec 139, draft),
#425, #426 (spec 138, draft), #427 (a new command, out of scope).

## Measured on 2026-11-05

Two full journeys were recorded in the `ika100-demo` organisation on platform 5.8.x (journey 1) and 5.8.3 → 5.9.0 (journey
2), with the same three parts and scripted answers. Working time includes CI waits and excludes the pauses for platform
fixes.

| Part | Budget | Journey 1 | Journey 2 |
|---|---|---|---|
| 1 — system, cluster, spec, ship | 20 | ≈ 100 min | ≈ 91 min (20 of them a blocked pin PR) |
| 2 — web UI, system spec, ship | 30 | ≈ 62 min | ≈ 84 min |
| 3 — hosts, release, prod, restore | 10 | ≈ 80 min | ≈ 59 min |
| Journey | 60 (interim 90) | ≈ 240 min | ≈ 234 min |

Journey 1 stopped for six platform defects (all fixed the same day: #448, #450, #453, #454, #455, #457); journey 2 for one
(#464) and one template defect (#468), and asked no question during its ships. Fewer stops did not shorten the journey: the
remaining time is in the ships themselves. The cost drivers, ranked by measured minutes in journey 2:

| Rank | Driver | Measured | What it is made of |
|---|---|---|---|
| 1 | The system route for a feature of one repo | part 1 ship ≈ 65 min (component route on 2026-11-03: 17) | system spec, plan PR, a second spec for the repo, a sub-agent, more CI rounds; spec 140 (5.9.0) routes such a feature to `/component:ship` |
| 2 | A two-repo system ship | 72 min | per repo: architect, acceptance tests, coder rounds, quality, review, PR CI, dev pin, smoke; the two repos ran in parallel but the longer one sets the time |
| 3 | The release of two components | 25 min | release PRs (a lock-file fix round), tag before the image existed (rerun), a staging round for the release builds; spec 138 decides the order |
| 4 | CI rounds per PR | 3–6 min each, about 25 PRs per journey | gitops CI, component CI, pin PRs; AC-136.12 caps the PRs at 15, AC-136.13 the gitops CI at 2 min |
| 5 | Coordinator waits written by the agent | about 10 min per journey | hand-written polling loops on `ship status` and Argo, one that never polled |
| 6 | Cluster creation and the first operator installs | ≈ 8 min | `cluster-up`, CloudNativePG, SeaweedFS, the backup plugin |

Where the wall clock of journey 2 went (08:30–12:57 UTC, 267 min). Each minute is counted once, from the session
transcript (main thread and 38 subagents, every tool call classified by its command) and from the GitHub Actions runs of
the three repos:

| Share | Minutes | What |
|---|---|---|
| Waiting for a person | 46 (17 %) | 26 min an upgrade and restart of the session, 12 min a platform fix (the blocked pin PR), 8 min answers; near 0 in a normal run |
| Waiting, no agent working | ≈ 100 (37 %) | CI checks and merges 47, smoke tests 15, Argo sync and cluster 14, promotion and restore commands 13, dev deploy 11 |
| Agents working | ≈ 121 (45 %) | model work 76, local commands and tests 45 (parallel subagents not summed) |

GitHub's own numbers for the same window: 187 Actions runs, 167 min of run time summed, 16 min in queues; a gitops run
takes ≈ 1 min, a component run 2.3–2.5 min. CI was running during only 93 of the 267 minutes. The CI waits are not slow
runs but many rounds one after another (34 PRs, each push → checks → merge, often a pin PR and an Argo sync after it) and
the polling intervals of the waits. So the two levers are of a similar size: fewer rounds (AC-136.11, AC-136.12,
AC-136.16) and less agent work per feature (the component route of spec 140 for one repo).

The measured gains of the fixes so far: hosts, observability and the staging promotion in one round (9 min against ≈ 16);
the web repo created and added to the system in one round (6 min); restore and discard without a hang (10 min against a
timeout); the prod gate clean on the first try.

## Acceptance criteria

**The journey.** The journey is the three parts of the demo, done with a fixed script: part 1 creates a system with one Python service and ships one spec, the tasks endpoint, to dev; part 2 adds a Postgres database and a Next.js web UI through one system spec shipped across three repos to dev; part 3 promotes to staging, releases, and deploys to prod with backups turned on and one restore checked. The scripted answers, specs and feature size stay the same between runs; changing them makes a new task version.

**Scope after the 2026-11-05 cut.** This spec measures the journey (AC-136.1–AC-136.3, AC-136.8); cutting its rounds (was AC-136.11) moves to spec 144. A journey is run by hand or by the coordinator with the fixed script; the command that runs it headless, cleanup, interventions, the release and retro hooks, the PR and CI limits and the method checks move to a later spec (see Later).

**Stages and budgets.** Each stage starts when its first command starts and ends when its last result is in. Stages that run at the same time (the cluster while the spec is written, repos built in parallel) overlap. A part's time is its critical path: from its first stage start to its last stage end, not the sum of its stages. Budgets are in working time (see Time below). The part and journey budgets are the binding targets; the stage budgets guide where the time goes. In part 1 the stage budgets add up to 22 min, so scaffold's first CI runs while the spec is written, which brings the critical path to 20. "Today" is the 2026-11-04 recording without its defects (BASELINES.md, parts 1 and 2; BASELINES.md (part 3, PR #413)).

| Part | Stage | What it covers | Budget (min) | Today (min) |
|---|---|---|---|---|
| 1, 2 | scaffold | system and repos created (part 2: the web component added), first CI green (the CI runs alongside spec) | 2 | 3 |
| 1 | cluster | local cluster up the first time with the system synced (runs alongside spec) | 2 | 2 |
| 1, 2 | spec | spec with its questions, agent time: component spec / system spec | 3 / 5 | 4 / 9 |
| 1, 2 | plan | plan written and checked: component / system | 2 / 3 | 1–4 |
| 1, 2 | build | red acceptance tests, code, review of the longest repo (repos run in parallel): component / system | 10 / 12 | 13 / 16 |
| 1, 2 | PR + CI | PR CI, merge, `main` CI with the image | 3 | 4 |
| 1, 2 | deploy dev | pin, Argo sync, dev smoke | 2 | 3 |
| 3 | environment settings | hosts, policy, observability, backups, in 1 PR | 2 | 6 (4 PRs) |
| 3 | staging to prod | staging promotion and verify, release, prod with backups and a restore drill | 8 | ≈ 15 |

| Part | Budget (min) | Interim, after the known time sinks are fixed | Stretch |
|---|---|---|---|
| 1: empty folder → the feature in dev | 20 | ≈ 26 | ≈ 17 |
| 2: database and web UI in dev | 30 | ≈ 35–40 | ≈ 25 |
| 3: staging, release, prod with backups and drill | 10 | ≈ 25 | ≈ 10 |
| **journey** | **60** | **≤ 90** | **≈ 50** |

The floor, without dropping any step of the method: agent work for two features is at least ≈ 25–30 min, the journey needs at least ≈ 12–15 PRs at ≈ 1 min of CI each, and deploys and smoke take ≈ 8–10 min. The 60-minute budget leaves little room above that floor, so every extra round shows.

**Time.** Working time is wall clock minus the time spent waiting for a person: from a question, an approval request (including the plan approval of spec 135) or a decision request being shown until it is answered. Person-wait is recorded on its own. External waits (GitHub rate limits, runner queues, image registry) are part of working time and are also reported on their own. Wall clock and working time are always reported side by side; today wall clock is dominated by #409 and by decisions waiting for a person.

- **AC-136.1** Given a journey run, when it ends or stops, then its record (spec 087) holds one entry per stage from the table above, each with its part, start, end, wall-clock minutes, working minutes, person-wait minutes, external-wait minutes, budget, the number of PRs it opened, and its extra rounds (fix rounds, CI reruns, escalations, resumed sessions, a reworked spec or plan) each with a cause. Each part and the whole journey get the same time fields. A stage that never started is listed as `not run`, never as 0 minutes.
- **AC-136.2** Given two stages that overlap, when the part's time is computed, then it is the span from the part's first stage start to its last stage end minus person waits inside that span, and it is less than the sum of its stages by the overlap.
- **AC-136.3** Given a stage that waited 10 minutes for a person to answer a question and 5 minutes for a GitHub rate limit, when its time is recorded, then person-wait is 10, external-wait is 5, wall-clock minutes include both, and working minutes exclude the 10 and include the 5.
- ~~**AC-136.4**~~ withdrawn 2026-11-05: moves to a later spec (stabilization cut); the text is kept under Later.
- ~~**AC-136.5**~~ withdrawn 2026-11-05: moves to a later spec (stabilization cut); the text is kept under Later.
- ~~**AC-136.6**~~ withdrawn 2026-11-05: moves to a later spec (stabilization cut); the text is kept under Later.
- ~~**AC-136.7**~~ withdrawn 2026-11-05: moves to a later spec (stabilization cut); the text is kept under Later.
- **AC-136.8** Given journey run records (AC-136.1), when `cplat runs report --benchmarks` runs, then for each platform version and coordinator model it shows per stage, per part and for the journey the median working time and the median wall clock of the done runs as two separate columns, the budget, the overrun in working minutes, the median person-wait, the median external wait and the median PR count, with the previous platform version's median next to it. The stages are ranked by median overrun in minutes, largest first. `--json` holds the same under the key `journey`, and the existing keys are unchanged.
- ~~**AC-136.9**~~ withdrawn 2026-11-05: moves to a later spec (stabilization cut); the text is kept under Later.
- ~~**AC-136.10**~~ withdrawn 2026-11-05: moves to a later spec (stabilization cut); the text is kept under Later.
- ~~**AC-136.11**~~ withdrawn 2026-11-05: moves to spec 144 (one gitops PR per environment); the text is kept under Later.
- ~~**AC-136.12**~~ withdrawn 2026-11-05: moves to a later spec (stabilization cut); the text is kept under Later.
- ~~**AC-136.13**~~ withdrawn 2026-11-05: moves to a later spec (stabilization cut); the text is kept under Later.
- ~~**AC-136.14**~~ withdrawn 2026-11-05: moves to a later spec (stabilization cut); the text is kept under Later.
- ~~**AC-136.15**~~ withdrawn 2026-11-05: moves to a later spec (stabilization cut); the text is kept under Later.
- ~~**AC-136.16**~~ withdrawn 2026-11-05: moves to a later spec (stabilization cut); the text is kept under Later.

## Non-goals

- Saving time by skipping the method: no dropping red-tests-first, review, the security gate, staging, staging verify or the required approvals.
- Fixing the issues in "Known time sinks" inside this spec; each is its own fix, ordered by measured saving.
- Making a budget overrun a hard failure, a CI gate or a release blocker; overruns warn, rank and feed the retro.
- Stopping a run at a stage time limit; run-tree limits stay as spec 102 defines them (its 180-minute ship default is a ceiling, not this spec's target).
- Cost and token budgets (specs 099, 102); this spec measures time.
- Shortening the time a person takes to answer; person-wait is recorded, not budgeted.
- Choosing a faster or cheaper model for an agent to meet a stage budget without a measured benefit at equal quality (spec 100).
- The platform repo's own CI time (spec 084).
- The headless journey benchmark command and everything listed under Later; they go into a follow-up spec once the platform is stable.
- Changing the size of the journey's feature to fit the budget; the tasks endpoint of part 1 and the part 2 system spec are fixed.

## Later

Cut on 2026-11-05 for the stabilization phase. These criteria go into a follow-up spec (the journey benchmark), which gives them new ids; they are not built from this spec.

- (was AC-136.4) Given `cplat runs benchmark journey`, when it runs, then it carries out the scripted journey headless with real agent sessions (no recorded or stubbed model answers) against a freshly created demo system at a pinned task version, answers every question from the script, and appends one benchmark record (spec 099 AC-099.13) naming the task version, the platform version and the coordinator model. The demo system's repos are public repos under a dedicated demo owner and use GitHub-hosted runners; the local cluster runs on the machine that runs the command. `--runs <n>` (default 1) runs the journey n times in a row with one record per run. `--part 1`, `--part 2` or `--part 3` runs one part; parts 2 and 3 start from the end state of the part before, which the command creates first when it is missing.
- (was AC-136.5) Given a journey benchmark that ends, stops or is interrupted, then the demo repos and the local cluster it created are removed, and the removal is noted in its record. When removal fails, the command exits non-zero naming what is left over, and the record is still written. When the GitHub owner for the demo cannot be reached or lacks permission, the command exits non-zero naming the problem before it creates anything, and writes no record.
- (was AC-136.6) Given a journey benchmark that reaches prod with a checked restore, when it ends, then it exits 0 even if stages went over budget. For every stage, part or journey over budget (working minutes against the tables above), the output prints its name, its budget, its working time and the overrun in minutes, and the record marks it `over_budget`. The output also states the journey's working time and wall clock against the target (60), the interim goal (90) and the stretch (50). A benchmark that does not reach the end exits non-zero and names the stage it stopped in. A budget overrun never stops the run, fails CI or blocks a release.
- (was AC-136.7) Given a journey benchmark in which any stage needed a person beyond the scripted answers (an unscripted question, a gate warning that has to be decided, such as #422, or a manual fix, such as resuming after #408), then the record lists each intervention with its stage, and the run counts as `needed a person` in the report, not as a within-budget run.
- (was AC-136.9) Given `cplat runs report --benchmarks --markdown`, then it prints the journey table in the format of `docs/BASELINES.md` (stage, working time, wall clock, budget, what made the difference) for the latest platform version, from the median of its done runs. Given a minor release candidate, the release procedure runs the full journey benchmark 3 times (more runs can be started on demand). When the release is made and journey benchmark records for its version exist, it writes this table into `docs/BASELINES.md`; when none exist, it says so in one line and goes on without waiting for one.
- (was AC-136.10) Given ordinary ship and product-ship runs (not benchmarks) in the covered week, when their records are written, then their stages carry the same time fields as AC-136.1. When the weekly retro (spec 090) is built, then its report has a "Journey time" section with the latest benchmark's overruns and the ordinary runs' median stage times against the budgets, and a stage over budget counts as evidence for a retro proposal (AC-090.7).
- (was AC-136.11, moves to spec 144) Given a journey run, when the gitops changes of one spec are promoted to one environment (pins, configuration and resource changes together), then they land in one gitops PR for that environment, not one per repo or per kind of change. Given a part 2 journey, then the gitops repo gets at most one PR per environment for the system spec, besides the spec and plan PRs. An environment's settings (hosts, policy, observability, backups) land in 1 PR, not 4 as on 2026-11-04 (#427).
- (was AC-136.12) Given the whole journey benchmark, then it opens at most 15 PRs across all demo repos (2026-11-04: 31), and the record and the report show the count per part.
- (was AC-136.13) Given a gitops PR in the benchmark, when its CI runs, then all its checks are green within a median of 2 minutes from the push over the benchmark's gitops PRs, and the checks share their setup instead of each preparing its own.
- (was AC-136.14) Given the benchmark's PRs for a spec (its spec PR, then its feature PR), then the feature PR merges without a conflict on the spec's files (#410) and without a fix round caused by the platform's own generated content (#420); such a round, when it happens, is listed as an extra round with the cause `platform`.
- (was AC-136.15) Given a journey benchmark record, then it states for every built spec whether the acceptance tests were red before the code, whether review ran, and whether staging was verified before prod. A run where any of them is `no` or `not run` is never shown as within budget, whatever its time.
- (was AC-136.16) Given a part 3 journey, when the staging promotion is prepared, then the gitops changes for prod are prepared in the same run, so no new agent session starts between staging verify and the prod PR. The prod PR opens only after staging verify has passed and then still waits at the prod gate. Given staging verify fails, then no prod PR is opened and the run names the failing check.

## Open questions

- ~~Is the time a person needs to answer excluded from the budgets and only recorded on its own?~~ Answered: yes, budgets are working time, person-wait is recorded on its own, and wall clock is reported beside it; see Time, AC-136.1, AC-136.3, AC-136.8.
- ~~Do external waits such as GitHub's GraphQL limit (#409) count against the budgets?~~ Answered: yes, they count and are also shown on their own; see Time, AC-136.3, AC-136.8.
- ~~Must the 20-minute part 1 budget hold with real agent work, not stubbed answers?~~ Answered: yes, real agent sessions, feature fixed to the tasks endpoint; see AC-136.4.
- ~~Confirm the stage list and the budgets per stage.~~ Answered: the user's stage budgets, part budgets (20, 30, 10; journey 60), interim goal (90) and stretch (50), see the tables and AC-136.6.
- ~~Part 1's stage budgets add up to 22 min, the part target is 20: which one gives way?~~ Answered: the part target is binding and the stage budgets guide; scaffold's first CI runs while the spec is written; see Stages and budgets.
- ~~Part 3: 10 or 15 min?~~ Answered: 10; see the part table.
- ~~Where does the benchmark run?~~ Answered: a dedicated demo owner, public repos on GitHub-hosted runners, the local cluster on the machine running the command; see AC-136.4.
- ~~How often does the journey benchmark run, and over how many runs is the median taken?~~ Answered: 3 full runs per minor release candidate plus on demand, the median counts; see AC-136.4, AC-136.8, AC-136.9.
- ~~Should a release require a fresh journey benchmark?~~ Answered: no; it writes the BASELINES table when a benchmark for its version exists and does not wait for one; see AC-136.9.
- ~~May staging and prod gitops changes be prepared together?~~ Answered: yes, in the same run; the prod PR opens only after staging verify passes and still waits at the prod gate; see AC-136.16.
- ~~Confirm the PR limit.~~ Answered: at most 15 PRs for the whole journey; see AC-136.12.
- ~~Confirm the gitops CI target.~~ Answered: median 2 minutes from push to all green; see AC-136.13.
- ~~Confirm: an overrun warns and never fails a run, CI or a release.~~ Answered: yes, it warns in output, record, report and retro; see AC-136.6, AC-136.10.
- ~~Does spec 135's plan approval count as person-wait?~~ Answered: yes; see Time.

## Changelog

- 2026-11-04 created
- 2026-11-04 amended: the user's budgets folded in (stage budgets with today's values, parts 20 / 30 / 10, journey 60, interim 90, stretch 50, the floor); working time and wall clock reported separately (AC-136.1, AC-136.3, AC-136.6, AC-136.8, AC-136.9); environment settings in 1 PR (AC-136.11).
- 2026-11-04 amended: all open questions answered as suggested; part targets binding and stage budgets guiding, part 3 at 10 min, external waits counted, plan approval as person-wait, the benchmark's owner, runners, cluster and `--runs` (AC-136.4), 3 runs per minor release candidate and the BASELINES table written without waiting (AC-136.9); new AC-136.16 prepares staging and prod gitops changes in one run.
- 2026-11-05 amended: the state of the 2026-11-04 time sinks, and a section with the times and cost drivers measured in two full journeys (no change to the criteria)
- 2026-11-05 amended: where the wall clock of journey 2 went (person, waiting, agent work) and GitHub's CI numbers (no change to the criteria)
- 2026-11-05 amended: cut to measurement and fewer rounds (stabilization); the benchmark command moves to a later spec
- 2026-11-05 approved by the user
- 2026-11-05 building
- 2026-11-05 amended: AC-136.11 withdrawn by the user's decision; one gitops PR per environment moves to its own spec 144 (measurement in design.md § AC-136.11)
- 2026-11-05 done
