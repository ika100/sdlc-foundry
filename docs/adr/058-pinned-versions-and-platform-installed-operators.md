# ADR-058: Images and operators are pinned exactly per release; the platform installs the operators a cluster needs as Argo CD applications

**Status:** Accepted (2026-10-26)
**Builds on:** [ADR-017](017-gitops-owns-manifests.md) (the gitops repo owns every manifest), [ADR-020](020-addons-contract.md) (operators were cluster prerequisites), [ADR-054](054-five-zero-interface-and-proved-migration.md), spec 115; extended by spec 121

## Context

5.0 renders the database image as a major-only tag (`postgresql:17`), so every pull can bring a different minor version. Operators are installed only on the local cluster, by `cluster-up`, at versions from environment variables. On real clusters, the docs left them to the cluster owner. The 5.x series adds more resources and more operators, and the user decided that the platform installs what a cluster needs, unless the owner opts out.

## Decision

1. **One versions table per platform release, in the renderer** (`templates/gitops-app/scripts/render.py`: `POSTGRES_IMAGES`, `OPERATORS`). Every image and chart the renderer writes comes from it, as a full version (an image may add a digest). It is never a major-only or floating tag. The table ships with the renderer that uses it, so a gitops repo renders what its platform release pinned. `cplat` reads the platform's copy when it needs the expected versions (`/platform:doctor`). Spec 121 adds the other rows, the CLI and the upgrade rules.
2. **Operators are Argo CD applications that the renderer writes once per cluster, only when needed.** They live outside every system's tree, in `operators/`: `operators/apps/<operator>.yaml` (the pinned chart) and `operators/root.yaml` (an Argo application that syncs `operators/apps`). Today the cluster is the repo's `cluster_server`, and every environment deploys there. An operator is rendered when an environment that is not opted out needs it (CloudNativePG: an in-cluster database instance). Without any, `operators/` does not exist.
3. **`environments.<env>.operators: owner` opts an environment out.** The platform installs and upgrades nothing for it, and `/platform:doctor` compares the installed version with the table's for each operator that environment needs.
4. **Operator applications carry no resources finalizer.** Removing one from git (the last database is gone) stops Argo from managing it but never deletes the operator or its CRDs, so no custom resource and no data is cascaded away.
5. **A human applies `operators/root.yaml` once per cluster**, before the system roots, exactly as with `bootstrap/` (`devbox run bootstrap`, and `devbox run cluster-up` locally). Its applications then follow git.

## Consequences

- Each system's tree (`applications/<system>/`, `bootstrap/<system>-root.yaml`) stays byte-identical for a 5.0 `system.yaml`, except the pinned database image. The operator files are cluster-level.
- A cluster shared by several gitops repos must let one of them install the operators. The others set `operators: owner` in every environment.
- An existing 5.0 cluster whose owner installed CloudNativePG by hand must set `operators: owner` before applying `operators/root.yaml`, or skip that file.
- The local cluster with Argo CD no longer installs CloudNativePG through k3s. Argo CD installs it from `operators/`. Without Argo CD (the platform's end-to-end test), `cluster-up` installs the chart version that `operators/apps/cloudnative-pg.yaml` pins.
