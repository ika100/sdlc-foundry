# ADR-060: A cluster repo owns what a cluster shares and lists the systems it runs

**Status:** Accepted (2026-10-27)
**Builds on:** [ADR-017](017-gitops-owns-manifests.md) (the gitops repo owns every manifest), [ADR-018](018-secrets-with-external-secrets-operator.md), [ADR-022](022-kyverno-policies.md), [ADR-058](058-pinned-versions-and-platform-installed-operators.md) (amends its consequence for shared clusters), spec 125

## Context

Since ADR-058 each system's gitops repo renders `operators/` for the cluster it deploys to. On a cluster shared by several systems, one of them has to own the operators for all, and every other system sets `operators: owner`. Which system owns them is arbitrary. Removing or moving it stops operator upgrades for the others, the installed versions follow that one system's platform release, and External Secrets with its `ClusterSecretStore` and the Kyverno engine have no owner at all: `cluster-up` installs them locally, and on real clusters a person installs them by hand. Each system is also bootstrapped by hand, with its repo credentials set by hand.

## Decision

1. **One gitops repo per cluster, from the template `templates/cluster-gitops`** (shape `cluster-gitops`, plugin `cluster`). Its only hand-edited file is `cluster.yaml`. `devbox run render` derives `cluster/` from it.
2. **The cluster repo owns the cluster's shared services:** the operators it lists by name (each one exactly pinned from the platform's versions table, which now includes `external-secrets` and `kyverno`), the `ClusterSecretStore`, one Argo CD repository credential template for the GitHub owner, and one root application per registered system. Argo CD, the Gateway provider and the cluster itself stay prerequisites. Kyverno policies stay per system and environment (ADR-022).
3. **The cluster lists its systems.** Installing a system is a reviewed PR that adds `systems.<system>: {repo: <owner>/<repo>}`. The rendered `system-<system>` application syncs the `bootstrap/` folder of that repo's `main`. Removing the entry deletes nothing in the cluster: no application of the cluster repo carries a resources finalizer.
4. **Operators are listed, not derived.** `cluster.yaml` names its operators explicitly. `devbox run check`, also a CI job, reads every registered system's `system.yaml` and fails when a system needs an operator the cluster does not list, or when an environment would install operators itself (it lacks `operators: owner`).
5. **The versions table is not copied.** The cluster template links to the system template's renderer (`scripts/system_render.py` is a symlink to `templates/gitops-app/scripts/render.py`; Copier copies its content), so a cluster repo pins exactly what a system repo of the same release pins, and it reads `system.yaml` with the same rules. An operator application is built by one function of that renderer for both repo kinds.
6. **Takeover keeps the names.** The cluster repo renders the operators root as `platform-operators` and each operator as `operator-<name>`, the names ADR-058 uses. On a cluster whose operators a system installed, applying the cluster repo's root takes over the same Argo CD applications in place. The operator is not reinstalled.
7. **Only the cluster is bootstrapped by hand, once** (`KUBE_CONTEXT=<ctx> devbox run bootstrap` in the cluster repo). It applies the operators root, waits for each listed operator's CRD, then applies the systems root. From then on, operators and systems change only through merged PRs.

## Consequences

- ADR-058's consequence "a cluster shared by several gitops repos must let one of them install the operators" now reads: a shared cluster gets a cluster repo. Every system registered there sets `operators: owner` in every environment. A system that does not use a cluster repo keeps ADR-058 unchanged, and its rendered tree is unchanged.
- Operator upgrades follow the cluster repo's platform release (`/platform:update` in the cluster repo), not a system's. The check warns when a registered system is on another release.
- One system runs all its environments on its cluster. Spreading environments over clusters and managing several clusters from one Argo CD are left to later specs.
- Removing a system from a cluster leaves its namespaces, resources and data in place until a person deletes them.
- The cluster repo's `cluster-up` runs the system template's `local-cluster.sh` in a cluster-only mode (`WITH_SYSTEM=0`), so the local cluster is built the same way for both repo kinds.
