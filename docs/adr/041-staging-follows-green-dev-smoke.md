# ADR-041 — Staging follows a green dev smoke; prod stays a manual promotion with evidence

**Status:** accepted (2026-10-25, spec 093)
**Amends:** [ADR-027](027-dev-follows-main-through-pin-prs.md) decision 4 (for `staging`)

## Context

ADR-027 decision 4 kept `staging` and `prod` on `/gitops:promote`: one reviewed PR each, never auto-merged. Since spec
091, every `cplat ship` run has the evidence a human would look for: CI is green, dev is healthy, and the smoke tests
pass against dev. Staging still waited for someone to notice. At prod time, the PR showed only a tag.

## Decision

- **Staging follows a green dev smoke.** After a dev smoke outcome of `passed` or `passed-on-retry` in `cplat ship
  deploy`, ship sends `repository_dispatch` `pin-staging` to the gitops-app. Its `pin-staging.yml` (a twin of
  `pin-dev.yml`) pins `sha-<40>` in the staging overlay, closes older automatic staging PRs, runs the app's CI and
  merges only on green.
  - A red CI leaves the PR open with a comment, and staging keeps its image.
  - Ship then waits for Argo, runs the same smoke tests against the staging URL, and records the outcome. A red outcome
    files the 088-style smoke issue and escalates. Nothing is rolled back: reverting the PR is the rollback.
- **Only builds with evidence move.** A red, timed-out or not-run dev smoke never promotes, and neither does a build
  merged outside ship. The first entry of a service into staging stays `/gitops:promote <svc> dev staging`. So does a
  service whose staging already runs a newer build.
- **The setting:** `promotion.staging: auto | manual` in `app.yaml`, overridable per service in `services.yaml`. Unset
  means `manual`. New gitops-apps are generated with `auto`. Existing ones stay `manual`, because `app.yaml` is
  project-owned.
- **Prod is never automatic.** `render.py` rejects any `promotion.prod` other than `manual`. No workflow or command pins
  or merges prod. `/gitops:promote … staging prod` shows an evidence summary from the run store, and puts it in the PR
  body: the release commit, what staging runs, the dev and staging smoke outcomes, and open `smoke-failure`/`alert`
  issues. Missing or red staging evidence gives a warning line and never blocks.

## Consequences

- `staging` runs the newest build that passed smoke, minutes after ship ends, without a human.
- A gitops-app needs `pin-staging.yml` (delivered by `/shared:update-service`). The user's gh token needs write access
  on the gitops-app, which ship already requires.
- Only the first linked gitops-app is promoted. Promoting several products together is spec 097's job.
- The prod evidence depends on run records (`CPLAT_RUNS_REPO`). Without them, the summary says `no record` and warns.
