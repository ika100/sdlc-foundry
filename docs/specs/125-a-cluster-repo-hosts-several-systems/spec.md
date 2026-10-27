---
spec_id: 125-a-cluster-repo-hosts-several-systems
title: A cluster repo hosts several systems on shared operators
status: done
priority: P1
---

# 125 — A cluster repo hosts several systems on shared operators

## Problem

Several systems (for example `todo`, `ai-ops` and `stock-manager`) usually run on one cluster and share what is installed once per cluster: the operators their resources need (CloudNativePG, SeaweedFS and the ones specs 117–121 add), External Secrets with the cluster's secret store, and the Kyverno engine. The platform has no place for this. Since spec 115 (ADR-058) each system's gitops repo renders an `operators/` folder for the cluster it deploys to, so on a shared cluster one system has to own the operators for everyone and every other system sets `operators: owner`. That owner is arbitrary: removing or moving it silently stops operator upgrades for the others, the versions installed follow whichever platform release that one system is on, and External Secrets and Kyverno have no owner at all (`cluster-up` installs them locally, real clusters by hand). Installing a system on a cluster is also a manual step per system (`devbox run bootstrap` in its repo), with repo credentials set by hand per repo.

This spec adds a **cluster repo**: a gitops repo per cluster, made from a new template, that owns what the cluster shares and lists the systems it runs. Installing a system becomes a reviewed PR to the cluster repo. Only the cluster itself is bootstrapped by hand, once. It ships as a 5.x minor release: no system repo has to change unless it moves onto a cluster repo, and a system's rendered tree does not change.

## Stories

- As a cluster owner, I want one repo that installs and upgrades the operators, the secret store and the Kyverno engine for my cluster, so that no single system owns them for the others.
- As a cluster owner, I want to install a system on my cluster by adding it to the cluster repo in a PR, so that there is no manual bootstrap per system and every installed system is reviewed and recorded.
- As a cluster owner, I want CI to fail when a registered system needs an operator the cluster does not install, or would install operators itself, so that problems show up before a merge and not as a failed sync.
- As a system owner, I want my system to keep working unchanged when it moves from owning the operators to a cluster repo, so that the move reinstalls nothing and loses no data.
- As a developer, I want to start the whole cluster with all its systems on my machine, so that I can try them together.

## Acceptance criteria

### The cluster repo

- **AC-125.1** Given `/cluster:new <name> [--org <owner>] [--public]`, when it runs, then it creates the repo `<owner>/<name>` (private unless `--public`) from the template `templates/cluster-gitops` with a `cluster.yaml` that names the cluster and its owner and lists no systems; the shape registry lists the shape `cluster-gitops` with the plugin `cluster`, and `scripts/shapes.py check` passes. An existing repo of that name, or a name that is not lowercase DNS-style (at most 40 characters), changes nothing and fails naming the reason.
- **AC-125.2** Given `cluster.yaml` with the keys `cluster` (required), `owner` (required, non-empty), `server` (default `https://kubernetes.default.svc`), `org` (the GitHub owner Argo CD reads repos from), `operators` (a list), `secretStore` and `systems`, when it is rendered with `devbox run render`, then any other key, a missing required key or a value of the wrong type fails with one line naming the key; the file is the only file edited by hand, and `devbox run render` with an unchanged `cluster.yaml` changes no file.
- **AC-125.3** Given `operators: [...]`, when it is rendered, then each name must be an operator in the platform's versions table (ADR-058: `cloudnative-pg`, `seaweedfs` and those later specs add) or `external-secrets` or `kyverno`, which this spec adds to that table with exact chart versions; an unknown name fails listing the allowed names. Each listed operator is rendered as one Argo CD application `operator-<name>` in `argocd`, pinned exactly to the table's chart version, with the same source, release name and target namespace as the system-rendered `operators/apps/<name>.yaml` of ADR-058, and with no resources finalizer. An unlisted operator gets no application.
- **AC-125.4** Given `external-secrets` in `operators` and `secretStore` (`name`, default `platform-secrets`, and `provider`, an External Secrets provider block; default: the Kubernetes provider reading the `secrets-store` namespace, as `cluster-up` sets it up locally), when it is rendered, then the cluster gets the `ClusterSecretStore` of that name with that provider; `secretStore` without `external-secrets` in `operators` fails naming both keys.
- **AC-125.5** Given `systems: {<system>: {repo: <owner>/<name>}}`, when it is rendered, then each system gets one Argo CD application `system-<system>` in `argocd` that syncs the `bootstrap/` folder of that repo's `main` (the system's root application), with no resources finalizer; a system name that is not lowercase DNS-style, two entries with the same repo, or a repo outside `org` fails naming the entry.
- **AC-125.6** Given a rendered cluster repo, when it is laid out, then the operator applications and the secret store live under `cluster/operators/` with their root `cluster/operators-root.yaml`, the system applications under `cluster/systems/` with their root `cluster/systems-root.yaml`, and a cluster without systems or without operators still renders both roots (an empty folder holds a `.gitkeep`); the operators root is the Argo CD application `platform-operators`, the same name the system-rendered `operators/root.yaml` uses.

### Installing a system

- **AC-125.7** Given `/cluster:add <owner>/<repo> [--name <system>]` in a cluster repo, when it runs, then it reads the system name from the repo's `applications/<system>/system.yaml` on `main` (or uses `--name`), adds the entry to `systems`, renders and opens one PR; a repo that is not a system's gitops repo (no `system.yaml`), cannot be read, or is already listed changes nothing and fails naming the reason.
- **AC-125.8** Given `/cluster:remove <system>`, when it runs, then it removes the entry and its rendered application in one PR and prints that the system's namespaces, resources and data stay in the cluster until a human deletes them; the system application has no resources finalizer, so merging the PR deletes nothing in the cluster. An unknown name fails listing the registered systems.
- **AC-125.9** Given a cluster repo, when `KUBE_CONTEXT=<ctx> devbox run bootstrap` runs once by a human on a cluster with Argo CD, then it stores one Argo CD repository credential template for `https://github.com/<org>` (from `REPO_TOKEN`, read-only), applies `cluster/operators-root.yaml`, waits for the CRD of each listed operator (failing after 10 minutes naming the CRD and the application to inspect), and then applies `cluster/systems-root.yaml`; running it again changes nothing that is in sync. From then on, systems and operators are added, upgraded and removed only through merged PRs to the cluster repo.

### Checks

- **AC-125.10** Given `devbox run check` (also a CI job of the cluster repo, reading the systems with a read-only token), when it runs, then for every registered system it reads `system.yaml` from the system repo's `main`, works out the operators the system needs (an in-cluster resource instance of a type in the platform's `OPERATOR_OF_TYPE`; `external-secrets` when any component declares `secrets`, `secretRefs` or the system has an external resource; `kyverno` when an environment has `policy`), and fails with one line per gap naming the system, the environment and the missing operator.
- **AC-125.11** Given a registered system with an environment that does not set `operators: owner`, when the check runs, then it fails naming the system, the environment and the edit (`environments.<env>.operators: owner` in `<repo>`), because the system would install operators itself; a system repo that cannot be read fails naming the repo and the token it needs.
- **AC-125.12** Given a registered system whose `.copier-answers.yml` records a platform release other than the cluster repo's, when the check runs, then it prints a warning naming the system and both releases but does not fail; given all systems pass, it prints one line per system with its name, repo and needed operators, and exits 0.
- **AC-125.13** Given `/platform:doctor` in a cluster repo with a kube context, when it runs, then for each listed operator it shows the installed and the expected (table) version and warns when one is missing or differs, and it shows each registered system's application with its sync and health state.

### Moving an existing cluster

- **AC-125.14** Given a cluster where a system's `operators/root.yaml` installed CloudNativePG (ADR-058), when that system sets `operators: owner` in every environment and the cluster repo (listing `cloudnative-pg`) is bootstrapped, then the application `platform-operators` and the application `operator-cloudnative-pg` are taken over by the cluster repo under the same names; the operator is not uninstalled or reinstalled, no CloudNativePG cluster restarts, and no data is lost. `docs/` describes these steps in order.

### Local and end-to-end

- **AC-125.15** Given a cluster repo, when `devbox run cluster-up` runs, then it creates (or reuses) the local k3d cluster `<cluster>-local` with Argo CD and the Gateway API exactly as a system's `cluster-up` does, gives Argo CD the user's `gh` token for `org` and the cluster a GHCR pull secret, runs the bootstrap of AC-125.9 against it and prints each registered system's exposed URLs; `devbox run cluster-down` removes it.
- **AC-125.16** Given the platform's end-to-end test, when it runs, then it renders a cluster repo listing `cloudnative-pg` and `external-secrets` with two systems that each have an in-cluster database, applies the operators once and both systems' rendered manifests to one k3d cluster, and both databases become ready with exactly one CloudNativePG operator Deployment in the cluster.

### Delivery

- **AC-125.17** Given the template `templates/cluster-gitops`, when it is copied with defaults, then the result passes its own `devbox run render` (no changes), `devbox run check` with no systems, and the repo checks of the template's CI (manifests build with kustomize and pass kubeconform); `/platform:update` and `/platform:fleet update` update a cluster repo like any other repo built from the platform.
- **AC-125.18** Given this release, when it is published, then `docs/DOMAIN-MODEL.md` adds the Cluster (the place systems run, with its shared operators and secret store), a guide describes creating a cluster repo, installing a system and moving an existing cluster (AC-125.14), an ADR records that a cluster repo owns the cluster's shared services and lists its systems (amending ADR-058's consequence for shared clusters), `docs/CHANGELOG.md` lists the change in a minor section not marked BREAKING, and the new `cluster` plugin and every changed plugin are versioned in their manifest and the marketplace.

## Non-goals

- Spreading one system's environments over several clusters (dev and staging on one, prod on another); a registered system runs all its environments on that cluster. A follow-up spec.
- Installing or upgrading Argo CD or the Gateway provider; both stay cluster prerequisites, as do the cluster itself and its nodes.
- Kyverno policies: they stay per system and per environment (ADR-022); the cluster repo installs only the engine.
- Deriving the operator list from the systems automatically; `cluster.yaml` lists operators explicitly and the check finds gaps.
- Changing a system's rendered tree, `system.yaml` keys or the system-rendered `operators/` (ADR-058) for systems that do not use a cluster repo.
- Registering a system on a cluster from `/system:new`, and opening PRs in a system repo from the cluster repo (the check names the edit instead).
- Multi-cluster management from one Argo CD (a hub cluster).
- Deleting a removed system's namespaces or data.

## Open questions

- ~~When does this ship relative to specs 116–121?~~ Answered: now, as an additive 5.x minor; later operators join the shared versions table and the cluster repo lists them by name.
- ~~What does the cluster repo own?~~ Answered: operators, External Secrets with the `ClusterSecretStore`, the Kyverno engine, Argo CD repo credentials for the org, and the registered systems' root applications. Argo CD and the Gateway stay prerequisites; Kyverno policies stay per system. See AC-125.3–AC-125.5, AC-125.9.
- ~~Does the cluster derive its operators from the systems or list them?~~ Answered: it lists them; a check fails on gaps. See AC-125.3, AC-125.10.
- ~~Can one system's environments be spread over several clusters?~~ Answered: not in this spec. See Non-goals.
- ~~Does the cluster list its systems, or does each system name its cluster?~~ Answered: the cluster lists its systems; installing a system is a PR to the cluster repo. See AC-125.5, AC-125.7.

## Changelog

- 2026-10-27 created; open questions answered up front by the user
- 2026-10-27 approved
- 2026-10-27 building
- 2026-10-27 done
