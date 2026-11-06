# Performance measurements

Every full run of the journey on [Watch a real run](https://ika100.github.io/sdlc-foundry/get-started/watch-a-run/) is measured the same way and recorded here: how long it took, how many tokens it used, how much of a person it needed, how good the result was, and what changed in the platform since the run before. The journey is always the same: an empty folder → a Python API in dev → Postgres and a Next.js web UI → staging, a release, prod with daily backups and a restore drill, in the public demo organisation [ika100-demo](https://github.com/ika100-demo). Its goal is 60 minutes ([spec 136](specs/136-the-whole-journey-fits-a-time-budget/spec.md)).

Add a row to every table below for each new journey (see [Recording a journey](#recording-a-journey)); never change the rows of an earlier one.

## The journeys

| # | Date | Platform | Demo repos | Driven by | Recording |
|---|---|---|---|---|---|
| 1 | 2026-11-05 | 5.8.0 → 5.8.2 (fixed during the run) | [taskboard-*](https://github.com/ika100-demo/taskboard-gitops) | a person, with pauses to fix the platform | parts 1–3 |
| 2 | 2026-11-05 | 5.8.3 → 5.9.0 (part 3 on 5.9.0) | [taskboard2-*](https://github.com/ika100-demo/taskboard2-gitops) | a person; Claude Code typed the sentences | one cast |
| 3 | 2026-11-05/06 | 5.10.0 | [taskboard3-*](https://github.com/ika100-demo/taskboard3-gitops) | unattended: Claude Code typed the sentences and took every suggested answer | one cast, shown on Watch a real run |
| 4 | 2026-11-06 | 5.11.0 | [taskboard4-*](https://github.com/ika100-demo/taskboard4-gitops) | unattended, like journey 3; Claude Code answered three stops with the agent's recommended option | one cast |

## Time

Minutes. *Working* is the wall clock minus pauses in which the platform itself was being fixed; CI rounds always count.

| # | Part 1 (budget 20) | Part 2 (budget 30) | Part 3 (budget 10) | Journey working (budget 60) | Wall clock |
|---|---|---|---|---|---|
| 1 | ≈ 100 | ≈ 62 | ≈ 80 | ≈ 240 | 405 |
| 2 | ≈ 70 (+ 20 blocked) | ≈ 85 | ≈ 60 | ≈ 215 (+ 20 blocked) | 267 |
| 3 | 70 | 102 | 81 | 256 | 256 |
| 4 | 31 | 77 | 56 (+ 88 blocked) | 164 (+ 88 blocked) | 254 |

**Where the wall clock went**, each minute counted once, agent work first (`scripts/journey/measure.py`):

| # | A person | Waiting, no agent working | Agents working | Subagents |
|---|---|---|---|---|
| 1 | 192 (47 %), most of it platform fixes between the parts | 71 (17 %) | 143 (35 %) | 43 |
| 2 | 46 (17 %): an upgrade and restart 26, a platform fix 12, answers 8 | 100 (37 %): CI 47, smoke 15, cluster 14, promotions 13, deploys 11 | 121 (45 %): model 76, commands and tests 45 | 38 |
| 3 | 17 (7 %): answers, and the gap until the next sentence | 94 (37 %): CI 40, deploys and Argo 34, promotions 15, cluster 3, smoke 2 | 145 (56 %): model 98, commands and tests 47 | 44 |
| 4 | 96 (38 %): 88 waiting for the go-ahead to merge prod (the driver's command was blocked by a permission check), answers and gaps 8 | 71 (28 %): CI 26, promotions 18, deploys and Argo 17, cluster 9, smoke 1 | 87 (34 %): model 80, commands and tests 7 | 41 |

**CI on GitHub** (the demo repos' Actions runs within the journey):

| # | Merged PRs | Actions runs | Failed runs | Run time | Queued | CI running during |
|---|---|---|---|---|---|---|
| 1 | 35 | 187 | 5 | 161 | 8 | 75 of 405 min |
| 2 | 34 | 187 | 3 | 167 | 16 | 93 of 267 min |
| 3 | 27 | 154 | 2 | 119 | 6 | 62 of 256 min |
| 4 | 29 | 155 | 0 | 117 | 9 | 65 of 254 min |

## Tokens

Summed over every API message of the recorded session, main thread and subagents, each message once. *Total* is input + cache writes + cache reads + output.

| # | Total | Cache reads | Cache writes | Output | Output by model (Opus / Sonnet / Haiku) | API calls |
|---|---|---|---|---|---|---|
| 1 | 88.2 M | 85.1 M | 2.57 M | 434 k | 338 k / 96 k / 0.3 k | 816 |
| 2 | 84.2 M | 82.1 M | 1.67 M | 402 k | 313 k / 89 k / 0.4 k | 743 |
| 3 | 90.5 M | 88.3 M | 1.77 M | 414 k | 314 k / 100 k / 0.3 k | 793 |
| 4 | 76.8 M | 74.6 M | 1.75 M | 377 k | 276 k / 102 k / – | 694 |

About 97 % of the tokens are cache reads: the context the agents read again on every turn. The number of turns, not the size of the answers, drives the usage.

Where the tokens went (main session / slice coordinators of `/system:ship` / specialist agents): journey 3 61.8 M in 302 calls / 21.8 M / 7.0 M; journey 4 54.8 M in 299 calls / 15.2 M / 6.7 M.

## A person's involvement

| # | Inputs typed | Questions answered | Stops for a platform defect | Minutes of a person (decisions only) |
|---|---|---|---|---|
| 1 | 24 | – | 6 | – |
| 2 | 13 | 8, all before the ships | 1 | 8 |
| 3 | 13 | 17, all with the suggested answer | 3 | 5 |
| 4 | 15 (12 sentences, 3 replies) | 7 rounds of questions, all with the suggested answer | 3, plus one permission block before prod | 2 |

## Quality

| # | Platform defects found | Acceptance criteria | Smoke at the end | Prod check | Restore drill |
|---|---|---|---|---|---|
| 1 | 7 (all fixed in 5.8.1–5.8.3) | 99 in 5 specs | green in dev, staging, prod | a false WARNING ([#457](https://github.com/ika100/sdlc-foundry/pull/457)) | passed |
| 2 | 2 (fixed in 5.9.0, 5.9.1) | 84 in 5 specs | green in dev, staging, prod | clean on the first try | passed |
| 3 | 15, filed as [#494](https://github.com/ika100/sdlc-foundry/issues/494)–[#508](https://github.com/ika100/sdlc-foundry/issues/508) | 68 in 4 specs (component route for part 1) | green in dev, staging, prod (API 5/5, web 2/2) | a warning (no staging smoke record, [#503](https://github.com/ika100/sdlc-foundry/issues/503)), cleared by a staging smoke | passed, after a manual backup ([#507](https://github.com/ika100/sdlc-foundry/issues/507)) |
| 4 | 5, filed as [#519](https://github.com/ika100/sdlc-foundry/issues/519)–[#523](https://github.com/ika100/sdlc-foundry/issues/523) | 65 in 4 specs | green in dev (API 5/5, web 4/4), staging (3/3, 3/3) and prod (the "Prod check" task created) | clean, no warning; no dev smoke record for the API's release commit ([#523](https://github.com/ika100/sdlc-foundry/issues/523)) | passed on the first try; the first backup ran by itself |

## What changed between the journeys

**Before journey 1 — 5.8.0.** The fixes from the first recorded demo (#408–#429), among them: cplat waits out GitHub's rate limit ([#436](https://github.com/ika100/sdlc-foundry/pull/436), spec 137), a ship restarts its branch from `main` after a squashed spec ([#437](https://github.com/ika100/sdlc-foundry/pull/437)), resuming an escalated ship keeps its PR ([#439](https://github.com/ika100/sdlc-foundry/pull/439)), a hand-run smoke counts as prod evidence ([#440](https://github.com/ika100/sdlc-foundry/pull/440)), the restore discard finishes under Argo CD ([#443](https://github.com/ika100/sdlc-foundry/pull/443)), and a release waits for the upgrade e2e once ([#401](https://github.com/ika100/sdlc-foundry/pull/401)).

**During journey 1 — 5.8.1 to 5.8.3**, the defects journey 1 found: an organisation `GITOPS_TOKEN` counts ([#448](https://github.com/ika100/sdlc-foundry/pull/448)); the dev smoke runs again after a deploy ([#450](https://github.com/ika100/sdlc-foundry/pull/450)); no second, empty PR on resume ([#453](https://github.com/ika100/sdlc-foundry/pull/453)); the reused spec draft PR is marked ready ([#454](https://github.com/ika100/sdlc-foundry/pull/454)); the secrets exclusion matches quoted values ([#455](https://github.com/ika100/sdlc-foundry/pull/455)); slim images take Debian security updates ([#456](https://github.com/ika100/sdlc-foundry/pull/456)); no false prod WARNING when staging runs the release commit ([#457](https://github.com/ika100/sdlc-foundry/pull/457)).

**Journey 1 → journey 2 — 5.9.0**, built from journey 1's measurements: a feature of one component takes the component route (spec 140, [#465](https://github.com/ika100/sdlc-foundry/pull/465)); an approved system plan asks no new questions (spec 141, [#463](https://github.com/ika100/sdlc-foundry/pull/463)); no avoidable stops (spec 142, [#466](https://github.com/ika100/sdlc-foundry/pull/466)); a pin PR whose CI never started is retried ([#464](https://github.com/ika100/sdlc-foundry/pull/464), found in journey 2).

**Journey 2 → journey 3 — 5.9.1 and 5.10.0.** 5.9.1, from journey 2: the Python release refreshes `uv.lock` ([#468](https://github.com/ika100/sdlc-foundry/pull/468)), a release tags only after `main` built the image ([#470](https://github.com/ika100/sdlc-foundry/pull/470)), a gitops PR survives a transient GitHub error ([#471](https://github.com/ika100/sdlc-foundry/pull/471)), Grafana answers at `grafana.localhost` ([#472](https://github.com/ika100/sdlc-foundry/pull/472)). 5.10.0, the stabilisation round: the coordinator waits with `cplat`, not hand-written loops (spec 143, [#490](https://github.com/ika100/sdlc-foundry/pull/490)); one gitops PR per environment for a system ship (spec 144, [#491](https://github.com/ika100/sdlc-foundry/pull/491)); a release tags the build staging tested (spec 138, [#486](https://github.com/ika100/sdlc-foundry/pull/486)); smoke tests that write data run only in dev (spec 145, [#487](https://github.com/ika100/sdlc-foundry/pull/487)); one owner per operator on the local cluster (spec 146, [#488](https://github.com/ika100/sdlc-foundry/pull/488)); a backup bucket needs no using component (spec 139, [#484](https://github.com/ika100/sdlc-foundry/pull/484)); journey run records (spec 136, [#489](https://github.com/ika100/sdlc-foundry/pull/489)); faster platform CI ([#482](https://github.com/ika100/sdlc-foundry/pull/482), [#483](https://github.com/ika100/sdlc-foundry/pull/483)) and the web e2e on a free port ([#485](https://github.com/ika100/sdlc-foundry/pull/485)).

Effect on journey 3: the cluster step went from 15 to 6 minutes and the release from 25 to 11, there were 7 fewer PRs and a third less CI time, and a person was needed for 5 minutes instead of 46. The wall clock barely moved (267 → 256): agent work grew by 24 minutes in three stops and in the coordinator polling its own background agents, and a flaky network cost about 15 minutes.

**Open after journey 3** (the input for the next version): [#494](https://github.com/ika100/sdlc-foundry/issues/494) a ship reuses the squash-merged spec branch (a regression of [#437](https://github.com/ika100/sdlc-foundry/pull/437)), [#495](https://github.com/ika100/sdlc-foundry/issues/495) a stale ruff cache, [#496](https://github.com/ika100/sdlc-foundry/issues/496) the coordinator polls background agents, [#497](https://github.com/ika100/sdlc-foundry/issues/497) the repo owner of `/component:new`, [#498](https://github.com/ika100/sdlc-foundry/issues/498) smoke criteria in a gitops spec, [#499](https://github.com/ika100/sdlc-foundry/issues/499) a leaking lock fixture, [#500](https://github.com/ika100/sdlc-foundry/issues/500) a transient push rejection escalates, [#501](https://github.com/ika100/sdlc-foundry/issues/501) parallel tasks run serially, [#502](https://github.com/ika100/sdlc-foundry/issues/502) `cplat deps patch` in a fresh repo, [#503](https://github.com/ika100/sdlc-foundry/issues/503) no staging smoke record, [#504](https://github.com/ika100/sdlc-foundry/issues/504) uncommitted operator files, [#505](https://github.com/ika100/sdlc-foundry/issues/505) two conflicting prod PRs, [#506](https://github.com/ika100/sdlc-foundry/issues/506) a red wait on a passing DNS error, [#507](https://github.com/ika100/sdlc-foundry/issues/507) the first backup fails, [#508](https://github.com/ika100/sdlc-foundry/issues/508) an OutOfSync operator; and [#510](https://github.com/ika100/sdlc-foundry/issues/510) `cplat pr wait` on a cancelled duplicate run.

**Journey 3 → journey 4 — 5.11.0**, the fixes for every journey 3 issue plus the cheap performance wins from its token analysis: a transient push rejection or DNS error is retried, and `cplat pr wait` ignores a cancelled duplicate run ([#512](https://github.com/ika100/sdlc-foundry/pull/512), #500 #506 #510); a ship starts from `main` after a squashed spec, the coordinator runs agents in the foreground instead of polling them, and parallel plan tasks really run in parallel ([#513](https://github.com/ika100/sdlc-foundry/pull/513), #494 #496 #501); the first backup waits for its bucket and the lgtm operator stays in sync ([#514](https://github.com/ika100/sdlc-foundry/pull/514), #507 #508); a staging promotion runs its smoke, operator files are committed, one prod PR carries several components, and `--system` sets the repo owner ([#515](https://github.com/ika100/sdlc-foundry/pull/515), #497 #503 #504 #505); ruff without a cache, scoped test runs that run only their targets, no smoke criteria in system specs and no leaking lock fixtures ([#516](https://github.com/ika100/sdlc-foundry/pull/516), #495 #498 #499 #502); command files a third smaller, with the details in `references/` read only when needed ([#517](https://github.com/ika100/sdlc-foundry/pull/517)).

Effect on journey 4: 164 working minutes instead of 256, and part 1 in 31 minutes instead of 70. Tokens fell by 15 % (90.5 → 76.8 M), most of it in the slice coordinators (21.8 → 15.2 M) and the main session (61.8 → 54.8 M). No Actions run failed, the prod check was clean on the first try, and the restore drill needed no manual backup. Three stops remained, each a new platform defect (below), and the go-ahead for the prod merge cost 88 minutes of wall clock because the driver's command was blocked by a permission check; with it the wall clock (254) equals journey 3's.

**Open after journey 4:** [#519](https://github.com/ika100/sdlc-foundry/issues/519) an import re-sort in the acceptance tests stops the ship, [#520](https://github.com/ika100/sdlc-foundry/issues/520) the template's metrics smoke test fails with two instances, [#521](https://github.com/ika100/sdlc-foundry/issues/521) a system ship cannot finish after a test-only smoke fix, [#522](https://github.com/ika100/sdlc-foundry/issues/522) agents run `bootstrap` for operators added after `cluster-up`, [#523](https://github.com/ika100/sdlc-foundry/issues/523) no dev smoke record for the release commit in the prod evidence.

## Recording a journey

Do this for every full journey, and add its rows here in the same PR that updates Watch a real run.

1. **Before:** release the platform, update the plugins, and pick new demo repo names (`taskboardN-*`; earlier repos stay as evidence). Start a journey record: `cplat platform runs journey begin`.
2. **During:** record the session with asciinema, one chapter marker per step; mark each stage with `cplat platform runs journey stage <id> start|end`, a person's decisions with `journey wait person add --minutes M` and every PR with `journey pr <url> --stage <id>`. Note every platform defect when it happens.
3. **After:** `cplat platform runs journey end --outcome done`, then measure:

   ```bash
   python3 scripts/journey/measure.py ~/.claude/projects/<dir>/<session-id> <start> <end> \
     ika100-demo/<system>-gitops ika100-demo/<system>-api ika100-demo/<system>-web
   ```

   It prints the wall-clock split (a person / waiting / agents), the tokens and the GitHub numbers used in the tables above. Take the per-part times from `cplat platform runs journey show`, count criteria in the demo repos' specs, and file every defect as an issue.
4. **Publish:** cut the cast with `scripts/journey/cut_cast.py <cast> <markers> <inputs> <out> <host> 0.016 2.5 2.0` (waits capped, host name blanked; check the output for tokens), update Watch a real run, and add a row to each table here plus a paragraph under [What changed between the journeys](#what-changed-between-the-journeys) with the PRs and issues of the versions in between.
