# ADR-089: Every merge into main holds the repo merge lock

**Status:** Accepted (2026-11-09, spec 167)
**Amended by:** spec 198 ([design](../specs/198-a-platform-release-holds-main-through/design.md)), spec 220 ([design](../specs/220-a-docs-only-land-does-not-wait-for-a/design.md))
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

**Release hold (spec 198).** A platform release holds `main` of its repo from its first check until the tag is pushed.
The hold is a file beside the lock (`<owner>__<name>.release-hold.json`), not the lock itself, because a release outlives
any `flock`: it exits at its confirmation stops. `held()` checks the file inside the lock; a merge that meets a hold of
another process lets go of the lock, waits for the hold outside it, untimed (the wait does not count against its
timeout), and then takes the lock again. The release's own process passes. At a confirmation stop the hold is kept for 2
hours and then expires; a hold whose process is gone is dropped by whoever checks it. The hold is machine-local, like the lock.

**Catch-up claim and fast lane (spec 220).** The lock has two parts: the `flock` (the merge step) and a catch-up claim, a
JSON record beside it (`<owner>__<name>.merge-claim.json`) written only while holding the flock. An in-scope land (its
change is inside the e2e scope) that waits on the checks of its updated head writes the claim and lets go of the flock for
the wait, then takes the flock back for its merge. A land that meets a live claim of another process queues when it is in
scope, undecidable or a RELEASE land; a land outside the e2e scope takes the fast lane and merges at once. The merge step
stays exclusive, because every merge still happens under the one flock. When everything new in the base since the head
whose e2e ran is outside the e2e scope (judged by `scripts/e2e-scope.py` of the current base), the green e2e is kept: the
land does not wait for the e2e of the new head and cancels its runs after the merge. The release hold is checked again when
a claiming land takes the flock back, so a release is never blocked by a land that waits for it. At most three catch-up
rounds per land claim; a repo without an e2e workflow that runs `scripts/e2e-scope.py` behaves as before.

## Consequences

- No pull request lands on a `main` its checks did not see; merges in one repo happen one at a time on the machine,
  with or without the dispatcher.
- A merge that waits for the lock past its timeout ends with a retryable error, never as a red check or an escalation.
- A second machine merging the same repo is not covered; that needs a lock on GitHub and is out of scope.
- A release no longer restarts because `main` moved through a cplat merge; merges by hand or from another machine are not held.
- A behind branch costs one more CI run; that is the price of testing what lands.
- A docs land no longer queues behind a code PR's cluster e2e; it merges while that PR waits on its checks.
- A land's merge may contain out-of-scope commits that its e2e did not see; they are outside the e2e scope by the same script that gates the e2e.
