---
spec_id: 209-inline-scripts-add-no-uv-environment-per
title: Inline scripts add no uv environment per worktree
status: done
priority: P2
shape: platform
explored: true
---

# 209 — Inline scripts add no uv environment per worktree

## Problem

uv keeps one script environment per script path in the developer's uv cache, and never removes it. Outside the tests, which spec 208 covers, cplat and the devbox recipes of the gitops-app and cluster-gitops templates run inline scripts in throwaway worktrees all day: one worktree per dispatcher unit, the `compose/<spec>` entry and the recreated staging worktree of every system ship, and the build worktrees that run `devbox run render`. Each new worktree adds about 1.2 MB per script it runs, about 5 MB for a ship that touches 3 to 5 scripts. With tens of units a day that comes to several GB a month that nobody gets back. The leak is slow, but it never stops, and it fills the disk of every machine that runs the platform unattended.

## Stories

- As a developer who runs the dispatcher and system ships, I want cplat's script runs in new worktrees to add nothing to my uv cache, so that my disk does not fill up a little more every week.
- As the owner of a gitops-app or cluster repo, I want the devbox recipes to behave the same in every worktree, so that builds and ships in worktrees leave no environments behind.
- As the owner of a generated repo, I want to get the fix through `/platform:update`, so that I never have to edit a recipe by hand.

## Acceptance criteria

- **AC-209.1** Given a repo whose inline scripts have each run once on the machine, when cplat runs those scripts in 5 new worktrees of that repo (dispatcher units, `compose/<spec>` ship entries, a staging worktree that is removed and added again), then the developer's uv cache has the same number of script environments as before, and after the worktrees are removed the scripts still run in the main checkout without adding one.
- **AC-209.2** Given a repo generated from the gitops-app or the cluster-gitops template, when each devbox recipe that runs an inline script (among them `render`, `render-check`, `test-fast`, `check`, `pin`, `plan-check`, `service-crds`, `upgrade-check`) runs in 3 new worktrees after one run in the main checkout, then the developer's uv cache has the same number of script environments as after the run in the main checkout.
- **AC-209.3** Given the platform repo, when its own devbox recipes that run inline scripts (among them `validate`, `shapes-check` and `quality`) run in 3 new worktrees after one run in the main checkout, then the developer's uv cache gains no script environment.
- **AC-209.4** Given a gitops-app repo and a cluster-gitops repo generated with the release before this change, when `/platform:update` brings them to the release with it, then AC-209.2 holds for them with no edit by hand.
- **AC-209.5** Given an inline script whose dependency list a worktree changes (a dependency added or a version changed), when the script runs in that worktree and the unchanged script runs in another worktree, then each runs with its own dependency list, and the developer's uv cache holds at most one environment for each of the two dependency lists, however often and in however many worktrees either runs.
- **AC-209.6** Given 3 worktrees of one repo, when they run the same inline script at the same moment (3 dispatcher slots), then all 3 runs succeed with the same output and exit code as a run on its own, and the developer's uv cache gains at most one environment for that script.
- **AC-209.7** Given any inline script run through cplat or a template or platform recipe, when it runs after this change in the main checkout, in a worktree and in the generated repos' GitHub Actions CI, then its output, written files and exit code are the same as before the change.

## Non-goals

- A developer typing `uv run scripts/<script>.py` by hand in a worktree, outside cplat and the devbox recipes: it keeps uv's behaviour of one environment per path.
- Removing environments already leaked before this change, or old environments left after a script's dependencies changed.
- The test entry points of the platform repo: spec 208 covers them, and spec 208 stays as approved (decided in explore).
- Inline scripts of other templates (service-python, library-python, service-java, service-go, web-nextjs): their recipes run project tools, not inline scripts.
- Limiting the size of the developer's uv cache in general.

## Assumptions

- **A1** A new spec, separate from spec 208, which stays approved as is; spec 208's non-goal (cplat's own `uv run` of inline scripts outside tests) is this spec's topic (affects AC-209.1–AC-209.7) (decided in explore).
- **A2** "One inline script" means one script of one repo, counted over the repo's main checkout and all its worktrees; two separate clones of the same repo may each have their own environment (other option: one environment per script across all clones; affects AC-209.1, AC-209.2, AC-209.3).
- **A3** A script's environments are counted per dependency list: a changed dependency list may add one new environment, and the old one may stay until the developer prunes the cache (other option: the old one is removed on the next run; affects AC-209.5).
- **A4** The platform repo's own recipes that run inline scripts are in scope, because dispatcher units run them in worktrees of the platform repo too (other option: only cplat and the two gitops templates; affects AC-209.3).
- **A5** Platform commands and agent prompts that tell an agent to run an inline script (for example the cluster add command's render call) do so through a devbox recipe or cplat, so they get the same guarantee (other option: leave prompts as they are; affects AC-209.1, AC-209.2).
- **A6** A developer who sets their own uv cache location gets the same guarantee for that location, as in spec 208 (other option: only the default location; affects AC-209.1–AC-209.3, AC-209.5, AC-209.6).
- **A7** Generated repos get the change with the next template release through `/platform:update`; no migration step or new setting is needed (other option: a manual step in the changelog; affects AC-209.4).
- **A8** Priority P2: a slow leak, no data loss and nothing stops working today (other option: P1; affects none).
- **A9** Not every inline script depends only on pyyaml (the gitops-app's service CRD check also needs jsonschema); the guarantee holds per script whatever its dependencies are (affects AC-209.2, AC-209.5).

## Notes for the architect

- The uv mechanism (shared environment, fixed script location, a lock or index of dependency lists, …) is your call; only the counts and unchanged results above are the contract.
- Verified in explore with uv 0.13.7 and 0.11.14: a script run twice from one path reuses one environment even after its content changes; a copy at another path gets a second one.

## Open questions

none

## Changelog

- 2026-11-17 created
- 2026-11-17 approved
- 2026-11-17 building
- 2026-11-17 done
