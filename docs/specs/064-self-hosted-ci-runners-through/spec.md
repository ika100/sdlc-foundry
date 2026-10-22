---
spec_id: 064-self-hosted-ci-runners-through
title: Self-hosted CI runners through repository variables
status: done
priority: P1
---

# 064 — Self-hosted CI runners through repository variables

## Problem

Every template workflow hard-codes `runs-on: ubuntu-latest` and installs Nix and devbox in every job. When GitHub-hosted runners are not available (ika100: blocked by a billing lock), the only way to run CI is to edit the generated workflows: point them at self-hosted runners and replace the devbox install, which fails in runner containers without systemd. `/shared:update-service` then overwrites those edits. stock-manager-gitops did exactly that on 2026-10-21 to run its CI on Actions Runner Controller (ARC) runners in the lan cluster.

## Stories

- As a repository owner, I want to move my repository's CI to self-hosted runners without editing generated workflows, so that template updates keep working.
- As a repository owner, I want to know what a self-hosted runner image and an ARC setup need, so that the first setup does not take a day of trial and error.

## Acceptance criteria

- **AC-064.1** Given any template's workflows (`ci.yml`, `specs.yml`, gitops-app `pin-dev.yml`), when they render, then every job that ran on `ubuntu-latest` runs on `${{ vars.CI_RUNNER || 'ubuntu-latest' }}`, so a repository without the variable behaves as before.
- **AC-064.2** Given a job with the `devbox-install-action` step, when it runs on a self-hosted runner, then the step is skipped (`if: runner.environment == 'github-hosted'`) and the job uses the devbox of the runner image.
- **AC-064.3** Given a service shape's `docker` job, when the repository variable `CI_DOCKER_MATRIX` holds a JSON matrix, then that matrix replaces the default architecture matrix (amd64, plus native arm64 on `main` and tags); without it the default stays.
- **AC-064.4** Given `docs/self-hosted-runners.md`, when an owner reads it, then it names both variables with examples, what a runner image needs (devbox with single-user Nix, xz, gh, Docker for `docker` jobs and `services:`), a reference image, and the ARC lessons: per-repository scale sets on personal accounts, unique scale-set names, the credential, cache volumes for `/nix`, Docker and `/tmp`, and the isolation trade-off of shared caches.
- **AC-064.5** Given a service shape's `docker` job, when it runs on a self-hosted runner, then the build neither reads nor writes the GitHub Actions cache (`cache-from`/`cache-to` only when `runner.environment == 'github-hosted'`): exporting every layer (`mode=max`) over the site's uplink took 4–6 minutes per build on the lan runners and once hung; GitHub-hosted runners keep the cache.

## Non-goals

- Generating ARC manifests or a runner image from the gitops-app template.
- Choosing runners per job.

## Open questions

## Changelog

- 2026-10-21 created from the stock-manager-gitops ARC setup (stock-manager-gitops #20–#28)
- 2026-10-21 approved
- 2026-10-21 building
- 2026-10-21 done
- 2026-10-22 amended: AC-064.5, no GitHub Actions cache for image builds on self-hosted runners (ai-ops #20 on lan-ai-ops)
