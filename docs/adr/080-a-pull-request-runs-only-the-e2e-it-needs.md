# ADR-080: A pull request runs only the e2e it needs, in parallel parts

**Status:** Accepted (2026-11-03, spec 134)

## Context

The cluster e2e took a median 2458 s (41 min) and the upgrade e2e 2170 s (36 min) per run (10 runs each, measured 2026-11-03), against
3-4 minutes for ci, and a pull request waits for both before it merges (#281). The cluster e2e started on every change under
`scripts/cplat/**` and `templates/gitops-app/**`, including modules and files the e2e never runs; the upgrade e2e compared against the
latest release tag, so after one versions change every later pull request ran it. Inside the run, the scaling scenario (560 s, most of
it the 5-minute scale-down floor) and the backup scenario (674 s) share only the setup with the rest.

## Decision

1. **On a pull request the cluster e2e runs only for changes it exercises.** A `decide` job runs `scripts/e2e-scope.py` against the pull
   request's base: the gitops-app and cluster-gitops templates (not their copied `.github/` files or Markdown), the templates'
   Dockerfiles, the e2e scripts and workflow, `shapes.yml`, and the `scripts/cplat` modules the e2e scripts call or import, closed over
   every import. The module set is computed from the code at HEAD, never kept by hand.
2. **The release pull request and the nightly run always run it.** A change that adds a release heading to the changelog runs the
   cluster e2e, so the release command (which waits for every check of the release pull request) cannot tag without it. The nightly
   schedule keeps running everything.
3. **On a pull request the scenario runs as three parallel parts.** `tests/e2e/run.sh` takes `E2E_PART` (`core`, `scaling`, `backups`;
   default `all`): every part runs the shared setup and its own steps, and together they run every step. Nightly and manual runs use
   `all`, one job, the old order, so interactions between scenarios are still tested once a day.
4. **The upgrade e2e decides on the pull request's own diff.** On `pull_request` its `decide` job passes the base commit; push to main,
   schedule and dispatch keep the tag as base, so the release gate of spec 121 is unchanged.

## Consequences

- Most pull requests skip both long e2e runs; a regression in a path the rule does not cover is found by the nightly run or the
  release pull request, not by the pull request that caused it.
- A pull request that does run the cluster e2e uses three runners for about 25 minutes instead of one for 41.
- A new step in `run.sh` belongs to the shared setup or to a part guard; a new `$cplat` call or import in the e2e scripts widens the
  trigger set by itself.
- Faster runs (self-hosted runners, image caches, parallel operator installs, a faster upgrade e2e) remain possible later; they were
  not the largest safe cut by the measurement.
