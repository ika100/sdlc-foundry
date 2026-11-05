# ADR-083: A system ship lands each environment in one gitops PR

**Status:** Accepted (2026-11-05, spec 144)

## Context

[ADR-027](027-dev-follows-main-through-pin-prs.md) pins dev to every merge of a component's `main` through its own self-merging
`pin-dev` PR, and [ADR-042](042-product-ship-coordinates-repo-ships.md) made the system ship merge its gitops entry before any
component started. A system spec across the gitops repo and two components therefore gave dev three PRs (journey 2 of
2026-11-05: #12 entry, #13 and #14 `pin-dev`), each a CI round, a merge and an Argo CD sync, and with staging on
`after-dev-smoke` one staging PR per component as well. Spec 136 measured CI waits as the largest share of the journey's
waiting time, made of many rounds.

## Decision

1. **Inside a system ship, the system ship pins dev, in one PR.** The gitops entry's `compose/<spec>` PR stays open; the system
   ship pins each component build on it (`pin.py`) once the component merged and its `sha-<40>` image exists, and
   `cplat system ship land` merges it after the last component. Resources, configuration and builds reach dev together; Argo
   CD syncs once, and the system ship runs every dev smoke afterwards (the component ships do not).
2. **`pin-dev` yields to a marker, per commit.** A component ship of a system ship pushes `ship/<spec>/<component>-<sha7>`
   (a branch at the gitops-app's `main`) when its PR merged; `pin-dev.yml` opens no PR for a build with a marker. Every other
   merge to a component's `main` is pinned as ADR-027 says.
3. **Staging follows in one PR too** when its rule is `after-dev-smoke`, after every dev smoke of the spec passed; prod stays
   with `/instance:promote` ([ADR-041](041-staging-follows-green-dev-smoke.md)).
4. **All or nothing.** A component that escalates keeps the dev PR unmerged: dev never runs a partial spec, and landing one is
   the user's decision.
5. **Mode per run.** A gitops-app whose `pin-dev.yml` predates the marker keeps one PR per component, with one line saying so,
   until `/platform:update`.

## Consequences

- The journey's part 2 gives one dev PR besides its spec, plan and done PRs; the CI rounds and syncs drop accordingly.
- The component builds wait unmerged into dev until the slowest component of the spec has merged.
- `pin-dev.yml` reads the remote heads once per dispatch; the system ship deletes its markers after the merge.
