# ADR-069: One versions table pins everything, and every release proves the upgrade from the previous one

**Status:** Accepted (2026-10-28)
**Builds on:** [ADR-058](058-pinned-versions-and-platform-installed-operators.md) (the versions table in the renderer), [ADR-060](060-a-cluster-repo-owns-shared-services.md) (cluster repos share the table through a copy), spec 121; the rollout side is the companion ADR [068](068-resource-and-operator-upgrades-roll-through-environments-in-verified-steps.md)

## Context

ADR-058 put the database image and the operator charts into a table in `render.py`. Other references stayed outside it: the local cluster
script installed Argo CD from `stable` and took operator versions from environment variables, the images carried tags without digests,
and CloudNativePG stopped publishing the plain `<major>.<minor>` tags the table used. Nothing showed that a cluster set up by one release
still works after the next, and the CHANGELOG did not say which pins moved.

## Decision

1. **Every image and chart the platform renders or installs comes from the table** in `templates/gitops-app/scripts/render.py`: engine
   images per major (`<repository>:<exact tag>@sha256:<digest>`), the NATS chart, the collector, LGTM, the Velero plugin, Argo CD, k3s,
   the Gateway API manifest, and each operator chart with its app version and the CRD versions it serves. `versions_table()` is the one
   reader; `cplat platform versions`, doctor, the local cluster script (`render.py --versions-env`) and the checks use it.
2. **A pin check in CI** fails on any reference outside the table, an image without a digest, a floating tag and a chart without an exact
   version, naming the file and the reference.
3. **Releases list and classify their pin changes.** The CHANGELOG section of a release lists every changed row with old and new value and
   marks major moves; a major operator move, a dropped CRD version or a dropped resource major is refused unless the release is a new
   major platform version.
4. **Every release candidate passes an upgrade end-to-end test** from the previous release (the first time from the latest 5.0.x, with its
   floating references resolved and recorded): data written before must read back after the platform update and a database major upgrade
   through dev, staging and prod, with a refused upgrade without a recent backup and a forced failed verification on the way. It runs in
   its own workflow; the release procedure tags only a commit with a green run, and a tag-push check turns red otherwise. No automation
   tags, publishes or deletes.
5. **Environment-property operators are platform-installed on request.** External Secrets, Kyverno and LGTM are rendered under
   `operators/` only for repos that answer `property_operators: install` (new systems), because clusters set up before have them
   installed by hand.

## Consequences

- A new pin is one edit of the table, visible in the CHANGELOG and proven by the upgrade test before the tag.
- Engine image references in every rendered tree changed once (exact tags and digests); nothing else changed for existing systems.
- Local clusters warn when an environment variable overrides a pinned version.
- The upgrade test needs the previous release's tag and about 40 minutes of a runner per release candidate.

## Not included

- Pinning component images (they stay in the overlays) or the base images of component Dockerfiles.
- A per-system choice of minor versions: the release decides them.
