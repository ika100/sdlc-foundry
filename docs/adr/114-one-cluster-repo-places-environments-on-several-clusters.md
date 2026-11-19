# ADR-114: One cluster repo places environments on several clusters

**Status:** Proposed (2026-11-15)
**Replaces:** [ADR-060](060-a-cluster-repo-owns-shared-services.md) decision 1 ("one gitops repo per cluster") and its consequence "one system runs all its environments on its cluster"; [ADR-068](068-resource-and-operator-upgrades-roll-through-environments-in-verified-steps.md) decision 7 for systems spread over clusters. Spec 201.

## Context

ADR-060 gave each cluster its own cluster repo, and a system ran every environment on that one cluster: its `system-<system>` application synced the whole `bootstrap/` folder of the system repo. A person who wants dev and staging on a laptop cluster and prod on an always-on home cluster would need two cluster repos. Each would define the operators, the secret store and the shared settings, so the two clusters drift apart without anyone seeing it. The `cplat` commands that act on an environment use one kube context, so a prod command could run against the laptop cluster. A home cluster cannot reach a cluster on a laptop, so one Argo CD that deploys to both (a hub) is not an option.

## Decision

1. **One cluster repo may list several clusters** (`clusters: [local, home]` in `cluster.yaml`). Each listed cluster has a directory `clusters/<name>/` with an optional `cluster.yaml` of explicit exceptions (whether an operator is installed, the secret store, `server`). Everything else is defined once. `devbox run render` writes one tree per cluster (`cluster/<name>/`), and each cluster's own Argo CD pulls only its tree. A repo without `clusters` is the one-cluster case and renders `cluster/` exactly as before.
2. **The cluster repo assigns each environment of a system to a cluster** (`systems.<s>.environments: {dev: local, staging: local, prod: home}`). The system repo states the same assignment in `system.yaml` (`environments.<env>.cluster`), and the cluster check fails when the two differ. When that key is set, the system repo also renders one root application per environment (`bootstrap/environments/<system>-<env>.yaml`, with a resources finalizer) over that environment's ApplicationSets. The cluster's `system-<s>` application (no finalizer) selects the environments of its cluster from that folder, so an environment that leaves a cluster is pruned there: its Argo CD objects go, and its workloads, namespace and data stay.
3. **The order of `clusters` is the upgrade order.** `/platform:update` moves only the first cluster. Every later cluster keeps its tree byte for byte: its release is pinned in `clusters/<name>/release.yaml`, and it is rendered by that release's renderer, kept in `.platform/releases/<release>/`. `/cluster:promote <name>` opens the one PR that moves a cluster to the release of the cluster listed before it, only after that cluster's operators are healthy and the smoke tests of its component instances are green. No ship, update or autonomy engine opens it.
4. **A command finds the cluster of an environment** through the system's `environments.<env>.cluster` and a personal record of kube context names (`kube_contexts: {<cluster>: <context>}` in the settings files; names only, never credentials). For a system spread over clusters it never falls back to the current context. A system on one cluster keeps today's choice of context.

## Consequences

- An environment runs on the cluster its system assigns it to. Moving one is a reviewed PR in both repos. The old cluster keeps its data until a person deletes it, and nothing is copied.
- A later cluster can run an older platform release for as long as nobody promotes it. Render and check say so on every run, and the repo keeps that release's renderer until no cluster uses it.
- The renderer of a release must keep the `--render-cluster` interface (JSON in, files out; `version: 1`), because a later release calls it for a cluster that is behind.
- ADR-068's order applies across clusters: an operator pin moves on the first cluster with that cluster's environments and reaches a later cluster only through promotion.
- A system repo has to take this release before its environments can be split over clusters. The cluster check names the system, its release and `/platform:update`.
