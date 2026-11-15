---
spec_id: 201-one-cluster-repo-places-environments-on
title: One cluster repo places environments on several clusters
status: draft
priority: P1
shape: platform
explored: true
---

# 201 — One cluster repo places environments on several clusters

## Problem

A cluster owner who wants dev and staging on a cluster that runs all the time on the laptop, and prod on a cluster in the house running the tagged versions, cannot set that up today. ADR-060 gives each cluster its own cluster repo, and a system runs all its environments on its one cluster: the system's root application syncs its whole `bootstrap/` folder, and the system repo sends every environment to one cluster. Two cluster repos would each define the operators, the secret store and the shared settings, so the two clusters drift apart without anyone seeing it. The `cplat` commands that act on an environment use one kube context, so a prod command can quietly run against the local cluster. This spec lets one cluster repo manage several clusters. Each cluster has its own directory for what is specific to it, and each environment of a system is assigned to one cluster. It replaces ADR-060's "one gitops repo per cluster" and its consequence "one system runs all its environments on its cluster", as the user decided. Upgrades reach the first cluster first and a later cluster only through a pull request opened by hand.

## Stories

- As a cluster owner, I want one cluster repo for my local and my home cluster, with the operators and shared settings defined once, so that both clusters run the same infrastructure and every difference is a visible, explicit exception.
- As a system owner, I want to run `todo`'s dev and staging on the local cluster and its prod on the home cluster, so that prod runs the released versions on hardware that stays up.
- As a cluster owner, I want an operator or platform upgrade to land on the local cluster first and on the home cluster only when I promote it, so that prod only gets what already ran on the local cluster.
- As a developer, I want every command that acts on an environment to go to the cluster that runs that environment, or to stop, so that a prod command never runs against the local cluster by accident.
- As a cluster owner, I want doctor to show where my clusters differ in Kubernetes, Argo CD and gateway, so that I see the differences the repo does not control.
- As the owner of an existing cluster repo or system repo, I want my repo to keep working unchanged after the platform update, so that I move to several clusters only when I choose to.

## Acceptance criteria

### Several clusters in one repo

- **AC-201.1** Given `cluster.yaml` with the keys of spec 125 (`cluster` and `owner` required, `server`, `org`, `operators`, `secretStore`, `systems`) and an optional list `clusters` of cluster names, each with its own directory in the repo for what is specific to that cluster, when `devbox run render` runs, then each listed cluster gets its own rendered tree for its own Argo CD. Every operator, the secret store and every other setting defined once in `cluster.yaml` appears the same in each cluster's tree. Any other key, a missing required key, a value of the wrong type, a cluster name that is not lowercase DNS-style (at most 40 characters) or is listed twice, a listed cluster without its directory, or a cluster directory whose cluster is not listed fails with one line naming it. `cluster.yaml` and the cluster directories are the only files edited by hand, and `devbox run render` with unchanged input changes no file. (replaces AC-125.2)
- **AC-201.2** Given a shared setting overridden in one cluster's directory (whether an operator is installed, the secret store, `server`), when `devbox run render` and `devbox run check` run, then only that cluster's tree differs, and both print one line per exception naming the cluster, the setting and both values. An override of anything that is not a shared setting fails naming it. The check of AC-125.10 runs per cluster: an operator that an environment assigned to a cluster needs but that cluster does not install fails with one line naming the system, the environment, the cluster and the operator.
- **AC-201.3** Given `systems: {<system>: {repo: <owner>/<name>, environments: {dev: local, staging: local, prod: home}}}`, when it is rendered, then cluster `local` gets one Argo CD application `system-<system>` in `argocd` that syncs only the system's dev and staging from that repo's `main`, cluster `home` gets one that syncs only its prod, and neither has a resources finalizer. A system without `environments` gets one application on the first listed cluster (the only cluster of a repo without `clusters`) that syncs the `bootstrap/` folder of that repo's `main`. A system name that is not lowercase DNS-style, two entries with the same repo, a repo outside `org`, an environment other than `dev`, `staging` or `prod`, or an environment assigned to a cluster that is not listed fails naming the entry. `devbox run check` fails naming the system and the environment when the system's `system.yaml` declares an environment that its `environments` leaves out. (replaces AC-125.5)
- **AC-201.4** Given a cluster repo without `clusters`, and system repos with no environment assignment, when each takes this platform release with `/platform:update` and renders, then no rendered file changes and bootstrap, check, doctor and the commands of AC-201.9 behave as before. Given a system assigned to more than one cluster whose `.copier-answers.yml` records an earlier platform release, when `devbox run check` runs, then it fails naming the system, its release and the step (`/platform:update` in `<repo>`), because only an updated system repo can run its environments on separate clusters.
- **AC-201.5** Given an environment that runs on cluster `local`, when a merged PR assigns it to `home`, then `local`'s Argo CD stops managing it and deletes nothing: its namespace, resources and data stay until a person deletes them. `home`'s Argo CD creates the environment with no data copied. `devbox run render` prints one line for each moved environment naming the system, the environment, both clusters and that its data stays on the old cluster.
- **AC-201.6** Given a cluster repo, when a person runs `KUBE_CONTEXT=<ctx> devbox run bootstrap [<cluster>]` once on a cluster with Argo CD, then it stores one Argo CD repository credential template for `https://github.com/<org>` (from `REPO_TOKEN`, read-only), applies that cluster's operators root, waits for the CRD of each operator that cluster installs (failing after 10 minutes naming the CRD and the application to inspect), and then applies that cluster's systems root. Running it again changes nothing that is in sync. The cluster name is optional only in a repo without `clusters`. A missing or unknown name in a repo with `clusters` fails listing the clusters, and a kube context whose Argo CD already runs another cluster's tree of this repo fails naming both clusters and changes nothing. `devbox run cluster-up [<cluster>]` builds the local cluster of AC-125.15 for the named cluster, by default the first listed one. From then on, systems and operators are added, upgraded and removed only through merged PRs to the cluster repo. (replaces AC-125.9)

### Upgrades reach one cluster at a time

- **AC-201.7** Given clusters `local` then `home` on the same platform release, when `/platform:update` brings a release that changes the operator pins or the rendered cluster infrastructure and its PR merges, then only the first listed cluster (`local`) takes the change; every other cluster's tree stays byte for byte as it was. `devbox run render` and `devbox run check` print one line per cluster that is behind, naming the cluster, its release and the first cluster's release, and exit 0.
- **AC-201.8** Given `home` behind `local`, when a person runs `/cluster:promote home`, then it opens one PR that moves `home`'s tree to exactly what `local` runs and changes nothing else. No PR is opened, with a message naming what is missing, when `local`'s operators are not healthy or the smoke tests of a component instance on `local` are not green (AC-121.20). When `home` already runs what `local` runs, no PR is opened and the command says so. A cluster is promoted only to what the cluster listed before it runs, and no ship, update or autonomy engine opens this PR.

### Commands find the cluster

- **AC-201.9** Given a system whose environments run on more than one cluster, when a command that acts on one environment (`cplat system wait --env`, `cplat component ship deploy`, `cplat instance verify`, `cplat resource backup|restore|query|upgrade`, `cplat system restore`) runs without `--context`, then it uses the kube context of the cluster that runs that environment. When it cannot tell that cluster or cannot reach it, it exits non-zero before acting, naming the environment, the cluster and how to set its context, and never uses the current kube context. `cplat system status` reads each environment from its own cluster and shows an environment whose cluster it cannot tell or reach as `unreachable: <cluster>`, with a non-zero exit. `--context C` uses `C`. In a cluster repo with `clusters`, `cplat cluster wait` takes the cluster's name and waits on that cluster's root application, failing in the same way without it.

### Doctor compares the clusters

- **AC-201.10** Given a cluster repo with `clusters` and a kube context for each cluster, when `/platform:doctor` runs, then for each cluster it shows the Kubernetes version, the Argo CD version, the gateway (Gateway API provider and version) and the checks of AC-125.13. For each of the three that differs between clusters, it prints one warning naming the item and each cluster's value. A cluster it cannot reach is one warning naming the cluster and the context it tried, and the other clusters are still shown and compared.

### Proof and delivery

- **AC-201.11** Given the platform's end-to-end test, when it runs, then it renders one cluster repo with two clusters on two k3d clusters and one system with dev and staging on the first and prod on the second, and bootstraps each. Each cluster's Argo CD runs only the applications of the environments assigned to it, both clusters run the same operator versions, dev runs a `sha-` image tag and prod runs the semver tag pinned for prod.
- **AC-201.12** Given this release, when it is published, then `docs/DOMAIN-MODEL.md` says that an environment runs on the cluster its system assigns it to, and the cluster guide describes adding a second cluster, assigning environments, promoting an upgrade and moving an environment (AC-201.5). An ADR replaces ADR-060's "one gitops repo per cluster" and its consequence "one system runs all its environments on its cluster", and ADR-068's decision 7 for systems spread over clusters. `docs/CHANGELOG.md` lists the change in a minor section not marked BREAKING, and every changed plugin is versioned in its manifest and the marketplace.

## Non-goals

- One Argo CD deploying to several clusters (a hub): each cluster keeps its own Argo CD that pulls from the repo, because the home cluster cannot reach a cluster on a laptop.
- Modelling the cluster's shared infrastructure (#268) and cluster observability (#265); doctor's comparison of AC-201.10 is the only addition.
- Copying an environment's data from one cluster to another, including a manual procedure for it in the cluster guide (a later spec), and moving `ai-ops` and `stock-manager` onto several clusters; they follow later, without losing data.
- Changing the branch the gitops repos use (`main`) or the image versions (sha builds in dev and staging, semver tags at release for prod).
- The cluster workflow gaps of #264.
- Installing or upgrading Kubernetes, Argo CD or the Gateway provider; they stay cluster prerequisites, and doctor only reports them.
- Environments other than `dev`, `staging` and `prod`, and one environment spread over two clusters.

## Assumptions

- **A1** Clusters are listed under a key `clusters` in `cluster.yaml`, and a system's assignment under `systems.<system>.environments` (other option: a separate file per cluster that lists its environments; affects AC-201.1, AC-201.3).
- **A2** The order of `clusters` is the upgrade order: the first listed cluster takes updates, and each later cluster is promoted to what the one before it runs (other option: an explicit `promoteFrom` per cluster; affects AC-201.7, AC-201.8).
- **A3** A per-cluster exception may override whether an operator is installed, the secret store and `server`. Operator versions differ only while a cluster waits for promotion (other option: version pins per cluster too; affects AC-201.2, AC-201.7).
- **A4** In a repo with `clusters`, a system without `environments` runs all its environments on the first listed cluster (other option: render fails until the system is assigned; affects AC-201.3).
- **A5** A system with `environments` assigns every environment its `system.yaml` declares, and `devbox run check` fails on a missing one (other option: unassigned environments go to the first cluster; affects AC-201.3).
- **A6** Promotion is the command `/cluster:promote <cluster>` and is gated as AC-121.20 states (other option: editing the cluster's pinned release by hand in a PR; affects AC-201.8).
- **A7** A cluster behind the first one is a warning in render and check, not a failure (other option: check fails after a number of days; affects AC-201.7).
- **A8** The record of which kube context reaches which cluster holds only a context name, never credentials; credentials stay in the user's kubeconfig (other option: none; affects AC-201.9, AC-201.10).
- **A9** `cplat system status` shows the reachable environments and marks the others `unreachable: <cluster>` instead of stopping (other option: stop like the single-environment commands; affects AC-201.9).
- **A10** Doctor compares Kubernetes and Argo CD on major.minor; patch versions are shown but not warned about (other option: exact versions; affects AC-201.10).
- **A11** In a one-cluster repo or for a system on one cluster, the commands keep today's choice of kube context (AC-143.6, AC-199.5); the rule against falling back applies only to systems spread over clusters (other option: no fallback anywhere, a breaking change; affects AC-201.4, AC-201.9).
- **A12** Gitops repos stay on `main`, and image versions stay as today: sha builds in dev and staging, semver tags at release for prod (affects AC-201.11) (decided in explore).
- **A13** Operators and shared settings are defined once for all clusters; a difference between clusters is an explicit per-cluster exception (affects AC-201.1, AC-201.2) (decided in explore).
- **A14** Shared-infrastructure modelling (#268) and cluster observability (#265) are out of scope; the only addition is doctor's comparison of Kubernetes version, Argo CD version and gateway (affects AC-201.10) (decided in explore).
- **A15** Existing one-cluster repos keep working unchanged: a repo without a cluster list is the one-cluster case, a system without an environment assignment runs all its environments there, and a system is split across clusters only after its own repo took the platform update (affects AC-201.3, AC-201.4) (decided in explore).

## Notes for the architect

- The first user is `todo`; `ai-ops` and `stock-manager` migrate later, without losing data.
- Where the cluster directories live, how a system's `bootstrap/` is split per environment, and where the cluster-to-kube-context record is kept are yours to decide. A system repo's command has to learn which cluster runs an environment (AC-201.9) without the cluster repo storing credentials (A8).
- Today `templates/gitops-app` uses one `cluster_server` answer as the destination of every environment. With one Argo CD per cluster pulling from the repo, every destination can stay in-cluster.
- Keeping a later cluster's tree at the old release (AC-201.7) means rendering it with that release's pins, not today's.

## Open questions

- ~~When `todo`'s prod moves from the local cluster to the home cluster, does its existing data go along? (suggested: no: prod starts empty on home and the old data stays on the local cluster until a person deletes it, as AC-201.5 states; other options: the guide describes a backup on local and a restore on home by hand, or a criterion that moves the data with `cplat system restore`; affects AC-201.5, AC-201.12)~~ Answered 2026-11-15: no. The new cluster starts the environment without data and the old data stays on the old cluster until a person deletes it (AC-201.5); moving data between clusters is a later spec and the guide describes no manual procedure for it (Non-goals).

## Changelog

- 2026-11-15 created
- 2026-11-15 amended: open question on moving data answered (no data moves; old data stays on the old cluster until a person deletes it, AC-201.5); non-goal now also excludes a manual data-copy procedure in the guide; criteria unchanged
