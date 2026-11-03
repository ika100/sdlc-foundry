---
spec_id: 134-a-pr-runs-only-the-e2e-it-needs
title: A pull request runs only the e2e it needs, and that e2e runs in parallel parts
status: done
priority: P1
shape: platform
tracks: [281]
---

# 134 — A pull request runs only the e2e it needs, and that e2e runs in parallel parts

## Problem

The cluster e2e (`.github/workflows/e2e.yml`) and the upgrade e2e (`.github/workflows/e2e-upgrade.yml`) are the slowest checks of the
platform repo by far, and a pull request waits for both before it merges (#281). Measured on 2026-11-03 from the GitHub API (job and
step `started_at`/`completed_at` of the last 10 successful runs of each workflow, all on GitHub-hosted `ubuntu-latest` runners, queueing
under a minute):

| Workflow / job | Runs | Median | Min | Max |
|---|---|---|---|---|
| e2e / `e2e (render → build → k3d → Gateway)` | 10 | 2458 s (41 min) | 2351 s | 2561 s |
| e2e / `e2e cluster (two systems, one operator)` | 10 | 135 s | 122 s | 159 s |
| e2e-upgrade / `does this change need the upgrade e2e` | 10 | 11 s | 7 s | 19 s |
| e2e-upgrade / `e2e upgrade (previous release → candidate)` | 10 | 2170 s (36 min) | 2075 s | 2187 s |
| ci (for comparison) | | 3-4 min | | |

Runs: e2e 41653547696, 41652571891, 41645483831, 41633284255, 41629451430, 41623859222, 41623419485, 41623110895, 41621699020,
41435528321; e2e-upgrade 41660534491, 41653547634, 41653373482, 41652787075, 41652571882, 41651578500, 41647452729, 41647445422,
41645484091, 41639027339.

Checkout, uv, Java and the k3d install take under 10 s together: all the time is inside `tests/e2e/run.sh`. Its `==>` step markers
(timestamps of the job log, median of 4 PR runs) split the 2400 s like this:

| Phase of `tests/e2e/run.sh` | Median | Needed by |
|---|---|---|
| cluster up: k3d, Gateway, 10 operators installed one after the other | 237 s | every scenario |
| build and push the images (Java service, website, NATS probe, worker) | 113 s | every scenario |
| apply guard rails, Postgres, the bucket store, OTel collector, the manifests | 183 s | every scenario |
| render, probes, generated secrets, OTel and Kyverno checks | 103 s | every scenario |
| bucket checks (read/write, versioning, the store's pods deleted, resync) | 158 s | bucket |
| external database and bucket (ExternalSecret without and with the key) | 37 s | every scenario (e2e-web waits for the Secret) |
| caches (declare, apply, password, eviction, persistence) | 108 s | caches, scaling, backups |
| broker (apply, Secrets, delivery, refusals, doctor, removal) | 88 s | broker, scaling |
| scaling without the scale-down wait | 217 s | scaling |
| scaling: the scale-down to zero (the 5-minute KEDA floor of AC-120.15) | 343 s | scaling |
| ship: verify dev, promote to staging, the staging bucket | 196 s | ship |
| backups: apply the operators' objects, the bucket and the Schedule | 188 s | backups |
| database backup, point in time, switch, discard | 257 s | backups |
| environment backup and restore | 229 s | backups |

The upgrade e2e spends 645 s applying its three environments and 600 s on the first backups; it is one scenario on one cluster.

Two things make this expensive beyond the run time itself:

1. **Most pull requests do not need the cluster e2e.** Its path filter includes all of `scripts/cplat/**`, `shapes.yml` and all of
   `templates/gitops-app/**`, so a change to `retro.py`, `platrelease.py` or a workflow file that the template only copies starts a
   41-minute run. Of the last 40 merged pull requests, 23 started it.
2. **The upgrade e2e decides against the latest release tag, not against the pull request.** `release-check.py needs-upgrade-e2e`
   compares the candidate with the last tag, so once one change since the release touched a versions row or an upgrade file, every later
   pull request runs the 36-minute upgrade e2e, even a docs change. Of the last 40 commits on main, 21 ran it; 8 changed something the
   upgrade e2e tests.

Where the time cannot be removed it can run side by side: the scaling scenario (560 s, most of it a fixed 5-minute wait) and the backup
scenario (674 s) need only the shared setup, the caches and (for scaling) the broker, not each other or the ship steps.

## Stories

As a platform maintainer, I want a pull request that cannot affect the cluster path to skip the cluster e2e, so that it merges after
the 3-4 minute ci instead of 41 minutes.

As a platform maintainer, I want the upgrade e2e to run on a pull request only when that pull request changes what it tests, so that
one versions change after a release does not cost every later pull request 36 minutes.

As a platform maintainer, I want the cluster e2e that a pull request does need to run its independent scenarios in parallel jobs, so
that it takes well under 30 minutes instead of 41.

As a platform maintainer, I want the nightly run and the release pull request to keep running every e2e scenario, so that narrowing the
pull request runs never lets a release go out untested.

## Acceptance criteria

- **AC-134.1** Given `.github/workflows/e2e.yml`, when it is read, then its `pull_request` trigger has no `paths` filter, a job
  `decide` (name `does this change need the cluster e2e`, timeout 2 minutes, full history checked out) runs
  `scripts/e2e-scope.py --base <the pull request's base commit>` and writes its `run=true|false` line to `$GITHUB_OUTPUT`, and every
  other job needs `decide` and runs only when its output is `true` or the event is `schedule` or `workflow_dispatch`.
- **AC-134.2** Given a change set between a base commit and `HEAD`, when `scripts/e2e-scope.py --base REF` runs, then it prints
  `run=true` if a changed path is one of: `templates/gitops-app/**` or `templates/cluster-gitops/**` except files under their `.github/`
  directory and Markdown files that do not end in `.jinja`; `templates/*/Dockerfile*`; `tests/e2e/run.sh`; `tests/e2e/cluster.sh`;
  `.github/workflows/e2e.yml`; `scripts/e2e-scope.py`; `shapes.yml`; a module or package of `scripts/cplat` in the exercised set of
  AC-134.3; a file under `scripts/cplat` that is not Python and not inside a package outside that set. It also prints `run=true` when
  the change adds a release heading `## [X.Y.Z]` to `docs/CHANGELOG.md` (the release pull request). Otherwise it prints `run=false`.
  For every changed path that triggers, it prints one line `trigger: <path>` to stderr.
- **AC-134.3** Given `tests/e2e/run.sh` and `tests/e2e/cluster.sh`, when `scripts/e2e-scope.py` computes the exercised set, then the
  set holds `cplat`, every module that a `$cplat <noun> <verb>` or `$cplat <plumbing>` call in those scripts resolves to through
  `scripts/cplat/cplat.py`'s `NOUNS` and `PLUMBING` tables, every `scripts/cplat` module that their embedded Python imports, and the
  transitive closure of these over every `import` and `from … import` statement in the modules (module level and inside functions);
  the set is computed from the files at `HEAD`, never from a hand-kept list, and `scripts/e2e-scope.py --list` prints it one name per
  line.
- **AC-134.4** Given a pull request, when `e2e-upgrade.yml`'s `decide` job runs `release-check.py needs-upgrade-e2e`, then it compares
  against the pull request's base commit (`--base`), so the upgrade e2e runs only when the pull request itself changes a versions row,
  an upgrade e2e file or adds a release heading; on `push` to main, `schedule` and `workflow_dispatch` the decision keeps comparing
  against the latest release tag as before (the release gate of AC-121.24 is unchanged).
- **AC-134.5** Given `tests/e2e/run.sh`, when the environment variable `E2E_PART` is unset or `all`, then it runs every step in
  today's order; when it is `core`, `scaling` or `backups`, then it runs the shared setup (system, cluster up, images, addons,
  manifests, probes, secrets, OTel, Kyverno, the external database and bucket, the caches) and only that part's own steps: `core` the
  bucket checks, the broker and the ship steps; `scaling` the broker with the scaling steps inside it; `backups` the backup and restore
  steps. Every step of `all` runs in at least one of the three parts, a step name is printed with `skip [<part>]` when a part leaves it
  out, and any other value of `E2E_PART` fails before the cluster starts.
- **AC-134.6** Given `.github/workflows/e2e.yml`, when the event is `pull_request`, then the e2e job is a matrix over `part: [core,
  scaling, backups]` with `fail-fast: false`, each matrix job named `e2e <part> (render → build → k3d → Gateway)` and passing
  `E2E_PART=<part>`; when the event is `schedule` or `workflow_dispatch`, then it is one job with `part: all` and the 90-minute
  timeout; the `e2e-cluster` job is unchanged apart from needing `decide`.
- **AC-134.7** Given the pull request that ships this spec (it changes `tests/e2e/run.sh`, so its e2e runs), when its e2e workflow
  runs green, then the decide job plus the longest part job (each from its start to its end, without the time a job waits for a free
  runner) take at most 1620 s (27 minutes; the measured median of the single job is 2458 s), and the before/after timings (per part,
  the queue time of each job and the time from the first job's start to the last job's end) are reported in the pull request and in
  `verification.md`.
- **AC-134.8** Given the last 40 merged pull requests before this spec (the files each changed), when the rule of AC-134.2 is applied
  to them, then fewer of them start the cluster e2e than the old path filter started (23), and the count is recorded in
  `verification.md`.
- **AC-134.9** Given the contributing guide, when a contributor reads its CI section, then it states which changes run the cluster e2e
  on a pull request (AC-134.2), that the scenario runs in three parallel parts on a pull request and as one job nightly, that the
  upgrade e2e decides on the pull request's own diff, and how to run a single part locally (`E2E_PART=<part> bash tests/e2e/run.sh`);
  ADR-080 records the decision and the changelog lists the change under `[Unreleased]`.

## Non-goals

- A merge queue or batching of pull requests (#280).
- Making the upgrade e2e itself faster (its three environments and first backups); only when it runs on a pull request changes.
- Self-hosted runners, a registry mirror, a prepared k3d node image or cached images: the measurement shows the build at 113 s and
  cluster up at 237 s of 2458 s, the runners are GitHub-hosted and ephemeral (a cache would be uploaded and downloaded each run), so
  they are not the largest safe cut.
- Installing the operators in parallel inside `templates/gitops-app/scripts/local-cluster.sh` (a change to what every generated repo
  runs, for about 2 minutes per part).
- Shortening the 5-minute scale-down floor that AC-120.15 asserts.
- Changing what any e2e step checks.

## Open questions

- ~~Should the nightly run use the parallel parts too?~~ Answered (recommended default, 2026-11-03): no; the nightly run stays one job
  with `E2E_PART=all`, so the scenarios still run once in sequence on one cluster and catch interactions between them; see AC-134.6.
- ~~Should the release pull request run `all` instead of the parts?~~ Answered (recommended default, 2026-11-03): the parts; together
  they run every step (AC-134.5), the nightly run covers the sequence, and the release command waits for the e2e like for every check
  of the release pull request, so the cluster e2e stays a hard gate before the tag; see AC-134.2.
- ~~Should the exercised cplat modules follow only module-level imports (smaller set) or every import?~~ Answered (recommended
  default, 2026-11-03): every import (the safe side); on the last 40 merged pull requests both select the same pull requests; see AC-134.3.
- ~~Should template workflow files and Markdown be left out of the template rule the user agreed on (`templates/gitops-app/**`)?~~
  Answered (recommended default, 2026-11-03): yes for files the e2e never renders or runs (non-`.jinja` files under the templates'
  `.github/` and non-`.jinja` Markdown); copier copies them verbatim and the ci smoke jobs cover them; see AC-134.2.

## Changelog

- 2026-11-03 created
- 2026-11-03 approved
- 2026-11-03 building
- 2026-11-03 done
- 2026-11-03 amended: AC-134.7 measures the jobs without the time they wait for a free runner (the first run waited 253 s for one while other pull requests held the account's runners); the first-start-to-last-end time is still reported
- 2026-11-03 draft
- 2026-11-03 approved (the plan is unchanged; its spec_hash is refreshed)
- 2026-11-03 building
- 2026-11-03 done
