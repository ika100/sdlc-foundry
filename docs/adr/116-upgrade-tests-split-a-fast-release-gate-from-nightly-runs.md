# ADR-116: Upgrade tests split a fast release gate from nightly runs

**Status:** Accepted (2026-11-17)
**Builds on:** [ADR-069](069-one-versions-table-pins-everything-and-every-release-proves-the-upgrade.md) (every release proves the upgrade from the previous one; this ADR amends how), [ADR-068](068-resource-and-operator-upgrades-roll-through-environments-in-verified-steps.md), spec 191

## Context

The upgrade end-to-end test ran the platform update and the Postgres 16 to 17 major upgrade in one job, and a release waited for all of it:
22 to 25 minutes on every release. It also proved only the jump from the previous release, while a system that skips releases
meets every change between its release and the candidate. Most breakage of an in-place update is visible in the rendered manifests
(a changed selector, a removed object) long before a cluster is needed.

## Decision

A release waits for the upgrade render check and the platform update e2e from the previous release; the oldest-release cluster run and the Postgres major drill run nightly and on the changes that touch them.

1. **The render check is part of the release gate** (`upgrade render check`, seconds, no cluster). It compares, from the previous and the oldest supported release, the render of the from-release's own system with the same system after the candidate's `/platform:update`, and fails on changes Kubernetes cannot apply in place or that lose data. A deliberate breaking change is accepted by a changelog line `Upgrade step: <Kind> <field>: <what the system owner does>`.
2. **The gate requires two checks:** `upgrade render check` and `e2e upgrade (previous release → candidate)`. Each is checked on its own: green on the SHA, else green on a same-tree head of its pull request.
3. **The drill has its own workflow** (`e2e-upgrade-drill.yml`), because `cplat platform release` waits for the whole `e2e-upgrade.yml` run on the merge commit; a drill in that workflow would put its 25 minutes back into the release. It repeats the platform update part, because CI jobs run on separate runners.
4. **The oldest-release job stays in `e2e-upgrade.yml`**, gated to schedule and dispatch, where the release (which waits on `--event push` runs only) never meets it. Oldest is the newest `vX.0.*` of the candidate's major; it is skipped (and passes) when there is none or it is the previous release. It does the platform update part only.

## Consequences

- A release no longer waits for the drill or the oldest-release cluster run; the previous-release job has a 45 minute limit and runs the platform update part only.
- The oldest-release cluster run is nightly and not gating: a break of a skip path is visible within a day, and gating it would add 15 to 20 minutes to every release.
- A breaking change that is deliberate needs an `Upgrade step:` line in a changelog fragment, which doubles as the instruction owners read when they jump releases.
- A break found only by the nightly runs or the drill is found after the merge; a maintainer starts them by hand with `gh workflow run` before a risky release.
- A later change must keep the gate's two required names in step with the workflows' job names.

## Not included

- Argo CD in the upgrade test.
- Upgrading Java, Go or web components in it.
- Downgrade testing.
