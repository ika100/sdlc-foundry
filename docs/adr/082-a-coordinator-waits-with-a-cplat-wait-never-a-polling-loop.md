# ADR-082: A coordinator waits with a cplat wait, never a polling loop

**Status:** Accepted (2026-11-05, spec 143)

## Context

In the journeys of 2026-11-05 the coordinator wrote its own polling loops whenever a command left it to wait: on
`cplat component ship status` of other clones, on `kubectl get applications`, on a deployment's image, on `curl` and on
`gh pr view` (#475). The loops slept 10–15 s, started again after every 10-minute tool limit, counted `Synced Healthy` on the
old revision as done, and said nothing when Argo CD had not picked up a merge yet (#264). Spec 136 ranks these waits fifth among
the cost drivers, about 10 minutes per journey. `cplat pr wait` (spec 079) had already solved the same problem for CI.

## Decision

1. **Every wait a command needs is a `cplat` command**: `cplat pr wait` (a PR's CI), `cplat system wait --env` (an
   environment runs `main` of the gitops repo: revision, `Synced`/`Healthy`, the pinned image), `cplat cluster wait` (the cluster
   repo's roots), `cplat component ship wait` (a ship run in a clone), `cplat system ship next --wait` (the system ship's next
   action) and `cplat component release wait` (`main`'s `ci` run on the commit to tag).
2. **One contract for all of them.** Exit 0 reached, 1 red (or escalated), 2 timeout; a line only when something changes; the
   result block starts with a word (`READY:`, `GREEN:`, `REACHED:`, `RED:`, `ESCALATED:`, `TIMEOUT:`); a default timeout of 540 s,
   so one wait fits in one tool call.
3. **The command decides, the wait reports.** A command runs the same wait again on exit 2, at most twice, and then escalates
   with cause `environment`; it passes `--refresh` right after a merge it made, and the timeout prints the command with
   `--refresh` when Argo CD is behind. Nothing is retried or rolled back by a wait.
4. **A wait asks GitHub at most once** (one `git fetch` for the head of `main`); everything else comes from the cluster and the run
   state. Its minutes count toward the run it runs in (`waiting_s`, `waits`), or it records its own `wait` run.
5. **Command and agent files never contain a shell loop with `sleep` that polls `kubectl`, `gh` or `cplat`**;
   `tests/cplat/test_143_waits_docs.py` fails on one.

## Consequences

- A new wait a command needs is added to `cplat` with the same exit codes and output, not written into the command text.
- The waits share `scripts/cplat/waits.py` (clock, exit codes, run record); `envwait.py` and `shipwait.py` hold the new ones.
- `cplat component ship deploy`, `cplat resource upgrade --wait` and `cplat pr wait` keep what they wait for.
