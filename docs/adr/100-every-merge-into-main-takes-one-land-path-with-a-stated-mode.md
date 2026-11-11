# ADR-100: Every merge into main takes one land path with a stated mode

**Status:** Accepted (2026-11-10, spec 178)
**Builds on:** [ADR-092](092-a-land-settles-what-has-an-obvious-answer.md) (the landing rules), [ADR-089](089-every-merge-into-main-holds-the-repo-merge-lock.md) (the repo merge lock)

## Context

Five commands merge a pull request into `main`: `cplat component ship land`, `cplat pr wait --merge`, the dispatcher's
land of a unit, `cplat platform release --confirm merge` and `cplat spec land`. During the 5.17.0 release `main` moved;
the release went through the catch-up of ADR-092, so `main` was merged into `release/5.17.0` and the released tree no
longer matched the changelog section and the benchmarked plugins. The land then merged at once, before the new head's
required check had finished, and GitHub refused (#648). A refusal ended the land with an error, although the only thing
to do was to wait.

## Decision

1. **One path, one mode per command.** Every merge into `main` goes through `land_merge.wait_green` and
   `land_merge.settle` with a `land_merge.Mode`. `CATCH_UP` (ship land, pr wait --merge, dispatch land, spec land)
   brings a branch behind its base up to date as ADR-092 says. `RELEASE` (platform release) never changes the branch:
   a branch behind its base, or one that conflicts with it, raises `land_merge.BaseMoved`, and the release stops with
   `main moved: start the release again`. Nothing rebuilds a release branch automatically.
2. **After the land changed the head, it merges only on the new head's finished checks.** Whenever the land itself
   moved the head (catch-up, a regenerated generated file, pushed local commits), it waits until GitHub shows the new
   head and until every expected check of that head has concluded green. The expected checks are the required checks
   GitHub names (`gh pr checks --required`) plus every check that passed on the head before the change; a missing one
   counts as pending.
3. **A refused merge is a wait, bounded.** A merge GitHub refuses because a required check is pending or the head moved
   sends the land back to waiting for the checks of the current head, still inside the merge lock. The third refusal in
   one land ends it with `merge refused 3 times: <GitHub's last reason>`. Any other refusal fails at once as before.

## Consequences

- A landing fix is made once in `land_merge` and reaches every command; a new command that merges into `main` picks a
  mode and calls the same two functions.
- A release whose base moved costs a new release run (close the PR, delete the branch, run it again), never a release
  of a tree nobody checked.
- The merges into gitops repositories (`ship.merge_gitops`, `appship_merge`) are not merges into the service's `main`
  and keep their own path.

## Not included

- Rebuilding a release branch on a moved `main`, rebasing, force-pushing.
- A merge lock across machines (spec 167).
