# Clusters

A cluster repo owns what several systems on one cluster share: the operators, External Secrets with the secret store, and the Kyverno engine. It also lists the systems that run there. See [the domain model](DOMAIN-MODEL.md) and [ADR-060](adr/060-a-cluster-repo-owns-shared-services.md).

## Create a cluster repo

1. Run `/cluster:new <name>`. It creates a private repo from the `cluster-gitops` shape. If you already know the cluster's properties, pass them: `--server <url>`, `--operators cloudnative-pg,external-secrets` and `--secret-store <name>`; the first commit then holds `cluster.yaml` with them and the rendered operator applications, and step 2 is only for later changes.
2. Edit `cluster.yaml`. List the operators the cluster installs (`operators: [cloudnative-pg, external-secrets]`); add `nack` if any system on the cluster runs an in-cluster broker (`type: broker`), since NACK creates its streams and consumers; add `keda` if any instance scales on a queue (`scale.on.consumes` or `scale.on.cache`); add `metrics-server` only on a cluster that serves no resource metrics, where `cpu` or `memory` scaling needs it (the system's `resource_metrics: install`); add `secretStore` only if you do not want the default `platform-secrets` store. Run `devbox run render` and commit the result under `cluster/`.
3. Let CI read the systems: `gh secret set SYSTEMS_TOKEN -R <org>/<name>`, a fine-grained token with Contents: read on the system repos.
4. Bootstrap once per cluster: `KUBE_CONTEXT=<ctx> REPO_TOKEN=<read-only token> devbox run bootstrap`. Locally, run `devbox run cluster-up`; it prints the `kubectl` and `k9s` commands to look at Argo CD.

## Install a system

1. Run `/cluster:add <owner>/<system-gitops-repo>` in the cluster repo (`--name` when the repo holds several systems). It adds the system to `cluster.yaml`, renders `cluster/systems/<system>.yaml` and opens a pull request.
2. In the system repo, set `operators: owner` in every environment of `system.yaml`, including one that runs nothing, then render. The system no longer renders `operators/`; the cluster provides them.
3. Merge the cluster PR. Argo CD syncs the system's `bootstrap/`. The CI check of the cluster repo names any operator the system still needs and any platform release mismatch.

To take a system away, run `/cluster:remove <system>`. Merging deletes nothing: the namespaces `<system>-dev`, `<system>-staging` and `<system>-prod`, the application `<system>-root` and everything it created, and all data stay until a human deletes them.

## Upgrading operators

An operator exists once per cluster, so its version moves once: a system's `/platform:update` moves it with dev's step, and the other environments on that cluster are checked by the smoke tests. In a cluster repo the operator list in `cluster.yaml` is the owner of that move; keep the cluster repo and its systems on the same platform release. `lgtm` is not a cluster-repo operator: a cluster repo never installs it. A system repo answers `property_operators: install` to have the platform render External Secrets, Kyverno and LGTM under its own `operators/` (new systems do), or `property_operators: owner` (older repos) when the cluster's owner installs them, as an environment with `operators: owner` does. See [UPGRADES.md](UPGRADES.md).

## Moving an existing cluster

A cluster whose owning system installed CloudNativePG through its own `operators/root.yaml` ([ADR-058](adr/058-pinned-versions-and-platform-installed-operators.md)) moves to a cluster repo in place. Do the steps in this order.

1. List every operator in the owning system's `operators/apps/` in `cluster.yaml` and check that the versions match: the cluster repo and the system must be on the same platform release, otherwise update the older one first.
2. Bootstrap the cluster repo (`devbox run bootstrap`). The applications `platform-operators` and `operator-cloudnative-pg` are taken over by the cluster repo under the same names. Nothing is reinstalled.
3. Set `operators: owner` in every environment of every system, and merge.
4. Run `/cluster:add` for each system. Its `<system>-root` application is adopted.
5. Check with `/platform:doctor`.

No CloudNativePG cluster restarts and no data is lost: the cluster repo renders the same application, with the same chart, release and namespace, so Argo CD sees no change to apply. None of these applications has a finalizer, so replacing their owner deletes nothing either.

## Several clusters

One cluster repo can manage several clusters, for example a local one for dev and staging and a home one for prod ([ADR-114](adr/114-one-cluster-repo-places-environments-on-several-clusters.md)). Each cluster keeps its own Argo CD that pulls from the repo. A repo without `clusters` and a system repo without `cluster` keys render as before.

### Add a second cluster

1. In `cluster.yaml`, add `clusters: [local, home]`. The order is the upgrade order: the first cluster takes each `/platform:update` directly, a later one follows through `/cluster:promote`.
2. Create `clusters/<name>/cluster.yaml` for every listed cluster. It holds only the exceptions to the shared settings (`operators: {<operator>: true|false}`, `secretStore`, `server`) and may be empty or only comments, because git cannot hold an empty directory. Any other directory under `clusters/` fails the render.
3. Run `devbox run render`. It writes one tree per cluster under `cluster/<name>/` and prints every exception (`EXCEPTION:` lines), every cluster that runs an older platform release than the first (`BEHIND:`) and every environment that moved (`MOVED:`). Commit the result.
4. Bootstrap each cluster by its name: `KUBE_CONTEXT=<ctx> REPO_TOKEN=<read-only token> devbox run bootstrap <name>`.
5. Run bootstrap again for the existing cluster right after the merge. Its roots move to `cluster/<first>/`; nothing is reinstalled.
6. Record the context names once per machine in `~/.config/sdlc-foundry/settings.yml`: `kube_contexts: {local: <ctx>, home: <ctx>}`. Names only; credentials stay in the kubeconfig.

### Assign environments

A system's environments run on the cluster it assigns them to. Do it in this order and merge after each step:

1. In the system repo, run `/platform:update`, set `environments.<env>.cluster` for all three environments of `system.yaml` (for example `dev: local`, `staging: local`, `prod: home`), render and merge. The render then writes one `ApplicationSet` per environment and `bootstrap/environments/<system>-<env>.yaml`, so a cluster can pick the environments it runs.
2. In the cluster repo, set `systems.<s>.environments` (`{dev: local, staging: local, prod: home}`), render and merge. Each cluster then runs only the applications of the environments assigned to it.

The order matters: a cluster that lists environments the system repo does not yet offer would select nothing. `devbox run check` in the cluster repo fails with a message when the two repos disagree, and the system repo's render fails when only some environments carry a `cluster` key. A system without `environments` stays on the first cluster as before.

### Promote an upgrade

![A platform update reaches the first cluster; a later cluster stays behind until /cluster:promote, gated on healthy operators and green smoke tests on the cluster before it](img/promotion-clusters.svg)

This promotion moves the platform release (operator pins and the rendered cluster infrastructure) from one cluster to the next. Component versions move through environments separately, with `/instance:promote` ([How it works](HOW-IT-WORKS.md#4-promote--instancepromote)).

The first cluster takes every `/platform:update`. A later cluster stays on the platform release it had, and `devbox run render` prints `BEHIND: cluster <c> runs platform <x>, cluster <first> runs <y>; promote it with /cluster:promote <c>`.

Run `/cluster:promote <name>` when the cluster before it has proven the release. It checks that every operator application of that cluster is `Synced Healthy` and that the smoke tests of every component in its environments pass (`--component-dir <component>=<dir>` names the checkouts). If a gate fails it prints `NOT PROMOTED:` and the reasons, and opens nothing. Otherwise it opens a pull request that pins the later cluster to the same release; `--dry-run` shows the result without opening it. After you merge, Argo CD on that cluster runs what the earlier one runs.

### Move an environment

Change the assignment in both repos: `environments.<env>.cluster` in `system.yaml` and `systems.<s>.environments` in the cluster repo, in the order of "Assign environments".

- The old cluster stops managing the environment and deletes nothing.
- The new cluster starts it empty. Nothing is copied.
- `devbox run render` prints `MOVED: <s> <env>: cluster <old> -> <new>; ...`.
- The old namespace and its data stay on the old cluster until a person deletes them: `kubectl --context <old> delete namespace <s>-<env>`.

Moving the data between clusters is not covered.

### Compare the clusters

`/platform:doctor` in the cluster repo reads each cluster through its context from `kube_contexts` (or `--context <name>=<ctx>`). It reports the Kubernetes, Argo CD and Gateway versions, the operators and the systems of every cluster, and warns with `clusters differ: ...` where the clusters do not match. These are cluster prerequisites; upgrade them outside the platform.
