# ADR-027: dev follows main through pin PRs

**Status:** Accepted
**Date:** 2026-10-09
**Amends:** [ADR-023](023-parallel-plan-execution.md) (pinning stays human, except for `dev`), [ADR-017](017-gitops-owns-manifests.md)
**Amended by:** [ADR-041](041-staging-follows-green-dev-smoke.md) (decision 4, for staging)

## Context

`dev` pinned every service to `:latest` with `imagePullPolicy: Always`, and the docs and agents claimed it picked up every new image. It did not: a moving tag gives Argo CD nothing to sync, so a new image only ran after a manual `kubectl rollout restart`. In end-to-end run 2 (2026-10-09) both merged repos of a feature kept running the old code until the operator restarted them ([run log](../e2e/2026-10-09-todo-second-feature.md), finding 3). The repo also didn't show which build `dev` runs, which `/shared:status` and rollbacks need. `staging` and `prod` don't have the problem: `render.py` forbids `latest` there, and promotions pin immutable tags.

## Options

1. **Pin PRs (chosen).** On every merge, the service's CI asks the gitops-app (via `repository_dispatch`) to pin `dev` to `sha-<7>`. The gitops-app opens the PR, and it merges itself once CI passes.
2. **Argo CD Image Updater.** It watches GHCR and writes the pin back to git. No token in service repos, but every cluster needs one more component with write access to the gitops repo, and the local cluster too.
3. **Restart on a new digest.** Keep `latest` and restart the Deployment on a new digest. The simplest, but the running build isn't visible in git and can't be rolled back by a revert.

## Decision

1. **Service CI** (all four deployable templates) gets a `pin-dev` job after `docker-publish`, on `main` only. It sends `repository_dispatch` `pin-dev` with `{service, tag: sha-<7>}` to every repo in `.platform-app.yml`, using the secret `GITOPS_TOKEN`: a fine-grained token with *Contents: read and write* on the gitops-app repo. Without the file or the token, the job prints a notice and passes. It is not a required check.
2. **The gitops-app** has `scripts/pin.py <env> <service> <tag>` (immutable tags only) and `.github/workflows/pin-dev.yml`:
   - it pins `dev` on `pin/dev-<service>-<sha7>` and opens the PR with `GITHUB_TOKEN`, closing older pin PRs of the service;
   - it starts `ci.yml` with `workflow_dispatch`, because PRs made with `GITHUB_TOKEN` trigger no workflows;
   - it enables auto-merge (squash).

   Branch protection (spec 054, required checks, no review) decides the merge. A red CI leaves the PR open and `dev` on the old image.
3. **New repos:** `/shared:new-service --gitops` turns on `allow_auto_merge` and lets Actions create PRs. A linked service, and `/shared:new-app` for all its components, prints the one manual step: create the token, then `gh secret set GITOPS_TOKEN`. `/shared:update-service` names the same step when the job first arrives.
4. **Promotion is unchanged:** `staging` and `prod` move only through `/gitops:promote`, one reviewed PR each, never auto-merged. Amended by ADR-041: staging now follows a green dev smoke; prod is unchanged.

## Consequences

- `dev` runs what was merged within minutes, and the pin is git history: revert the pin PR to roll back.
- **The cost:** one secret per service repo, a token that expires and has to be renewed, and an auto-merge setting on the gitops repo. Without the token nothing breaks; `dev` simply stays where it was, and the CI notice says why.
- **Untested here:** whether check runs started by `workflow_dispatch` satisfy branch protection for a PR opened by `GITHUB_TOKEN` depends on GitHub, not this repository. The next end-to-end run checks it on ika100/todo (spec 062, verification).
