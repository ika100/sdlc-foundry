---
title: "Run your systems on your own cluster"
description: "One cluster repo installs the shared operators once and lists the systems that run there."
---

**Situation.** `shop` and `todo` both run on the same cluster at home. Each system would install its own operators (CloudNativePG, External Secrets, the policy engine), and the two copies would drift. You want one place that owns the cluster's shared parts and says which systems run there.

## Steps

Create the cluster repo once:

```text
/cluster:new home --server https://192.168.1.20:6443 --operators cloudnative-pg,external-secrets
```

Give its CI read access to the system repos (`gh secret set SYSTEMS_TOKEN -R acme/home`, a fine-grained token with Contents: read), then bootstrap the cluster once from the new repo:

```bash
KUBE_CONTEXT=home REPO_TOKEN=<read-only token> devbox run bootstrap
```

Install each system, in the cluster repo:

```text
/cluster:add acme/shop
/cluster:add acme/todo
```

In each system's GitOps repo, set `operators: owner` on every environment in `system.yaml` and render, so the system stops installing its own operators. Merge the system's pull request, then the cluster's.

## What you get

- One repo, `cluster.yaml`, that lists the operators, the secret store and the systems of the cluster. Every change to them is a pull request.
- One Argo CD application per system. Each system keeps its namespaces (`shop-dev`, `shop-staging`, `shop-prod`), so its manifests stay the same whether it shares a cluster or has its own.
- The cluster repo's CI check names any operator a system needs that the cluster does not install, and any platform release mismatch between the cluster repo and a system.
- `/cluster:remove todo` takes a system off the list in one pull request. Nothing in the cluster is deleted: its namespaces and data stay until a person removes them.

## Check it

`/platform:doctor` in the cluster repo shows the operators and the systems the cluster runs. `/system:status` in a system repo still shows that system's versions and health per environment.

An existing cluster whose operators came from one of its systems moves to a cluster repo in place, without restarting a database: see [Moving an existing cluster](/sdlc-foundry/guides/clusters/#moving-an-existing-cluster).

## Limits to know

All environments of a system run on the cluster that hosts it. Kubernetes, Argo CD and the Gateway provider are prerequisites of the cluster; the platform reports them but does not install or upgrade them. Details are in [Clusters shared by several systems](/sdlc-foundry/guides/clusters/).
