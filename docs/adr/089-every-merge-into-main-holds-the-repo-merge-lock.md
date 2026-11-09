# ADR-089: Every merge into main holds the repo merge lock

**Status:** Accepted (2026-11-09, spec 167)
**Builds on:** [ADR-042](042-product-ship-coordinates-repo-ships.md) (the gitops merge slot), spec 079 (`cplat pr wait --merge`), spec 072 (`ship land`)

## Context

Branch protection and auto-merge are not available on GitHub Free, so the platform merges in code: `cplat component ship
land` and `cplat pr wait --merge` squash-merge once every check is green. Two such merges at the same moment (two
dispatcher units, or a unit and a manual session) both merge on a green that was computed against an old `main`; the
second change was never tested on top of the first. The gitops merge slot of ADR-042 solves this only for a system
ship's gitops repo, and only across the checkouts of one clone.

## Decision

Every merge into the default branch that cplat makes holds a machine-wide lock per repository:
an exclusive `flock` on `${XDG_STATE_HOME}/sdlc-foundry/locks/<owner>__<name>.merge.lock`, keyed by the origin slug
so that every clone and worktree of the repo on the machine shares it. Inside the lock the merge checks whether the
pull request's head is behind the default branch; if so it updates the branch with `gh pr update-branch` (a merge
commit, never a force push), waits for every check of the new head, and merges with `--match-head-commit`. A conflict
is a human decision, as before. A repo that lists `e2e` under `serialize` in `.platform/dispatch.yml` holds the lock for
the whole land phase (the check wait through the merge), because its e2e job runs on a single self-hosted runner.

## Consequences

- No pull request lands on a `main` its checks did not see; merges in one repo happen one at a time on the machine,
  with or without the dispatcher.
- A merge that waits for the lock past its timeout ends with a retryable error, never as a red check or an escalation.
- A second machine merging the same repo is not covered; that needs a lock on GitHub and is out of scope.
- A behind branch costs one more CI run; that is the price of testing what lands.
