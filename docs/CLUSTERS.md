# Clusters

A cluster repo owns what several systems on one cluster share: the operators, External Secrets with the secret store, and the Kyverno engine. It also lists the systems that run there. See [the domain model](DOMAIN-MODEL.md) and [ADR-060](adr/060-a-cluster-repo-owns-shared-services.md).

## Create a cluster repo

1. Run `/cluster:new <name>`. It creates a private repo from the `cluster-gitops` shape.
2. Edit `cluster.yaml`. List the operators the cluster installs (`operators: [cloudnative-pg, external-secrets]`); add `nack` if any system on the cluster runs an in-cluster broker (`type: broker`), since NACK creates its streams and consumers; add `keda` if any instance scales on a queue (`scale.on.consumes` or `scale.on.cache`); add `metrics-server` only on a cluster that serves no resource metrics, where `cpu` or `memory` scaling needs it (the system's `resource_metrics: install`); add `secretStore` only if you do not want the default `platform-secrets` store. Run `devbox run render` and commit the result under `cluster/`.
3. Let CI read the systems: `gh secret set SYSTEMS_TOKEN -R <org>/<name>`, a fine-grained token with Contents: read on the system repos.
4. Bootstrap once per cluster: `KUBE_CONTEXT=<ctx> REPO_TOKEN=<read-only token> devbox run bootstrap`. Locally, run `devbox run cluster-up`; it prints the `kubectl` and `k9s` commands to look at Argo CD.

## Install a system

1. Run `/cluster:add <owner>/<system-gitops-repo>` in the cluster repo (`--name` when the repo holds several systems). It adds the system to `cluster.yaml`, renders `cluster/systems/<system>.yaml` and opens a pull request.
2. In the system repo, set `operators: owner` in every environment of `system.yaml`, including one that runs nothing, then render. The system no longer renders `operators/`; the cluster provides them.
3. Merge the cluster PR. Argo CD syncs the system's `bootstrap/`. The CI check of the cluster repo names any operator the system still needs and any platform release mismatch.

To take a system away, run `/cluster:remove <system>`. Merging deletes nothing: the namespaces `<system>-dev`, `<system>-staging` and `<system>-prod`, the application `<system>-root` and everything it created, and all data stay until a human deletes them.

## Moving an existing cluster

A cluster whose owning system installed CloudNativePG through its own `operators/root.yaml` ([ADR-058](adr/058-pinned-versions-and-platform-installed-operators.md)) moves to a cluster repo in place. Do the steps in this order.

1. List every operator in the owning system's `operators/apps/` in `cluster.yaml` and check that the versions match: the cluster repo and the system must be on the same platform release, otherwise update the older one first.
2. Bootstrap the cluster repo (`devbox run bootstrap`). The applications `platform-operators` and `operator-cloudnative-pg` are taken over by the cluster repo under the same names. Nothing is reinstalled.
3. Set `operators: owner` in every environment of every system, and merge.
4. Run `/cluster:add` for each system. Its `<system>-root` application is adopted.
5. Check with `/platform:doctor`.

No CloudNativePG cluster restarts and no data is lost: the cluster repo renders the same application, with the same chart, release and namespace, so Argo CD sees no change to apply. None of these applications has a finalizer, so replacing their owner deletes nothing either.
