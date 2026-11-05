---
spec_id: 146-one-owner-per-operator-on-the-local-cluster
title: One owner per operator on the local cluster
status: done
priority: P1
shape: platform
tracks: [425]
---

# 146 — One owner per operator on the local cluster

## Problem

A local cluster made by an older `devbox run cluster-up` runs External Secrets and Kyverno as k3s HelmCharts
(`kube-system/external-secrets`, `kube-system/kyverno`). When the gitops repo later renders `operators/apps/<op>.yaml`
(`property_operators: install`), Argo CD installs the same release from `operators/` as well
([ADR-058](../../adr/058-pinned-versions-and-platform-installed-operators.md): a local cluster with Argo CD gets
its operators from `operators/`). `cluster-up` said it "kept" the HelmChart but still applied `operators/root.yaml` when another
operator was rendered, and `bootstrap` (also run by the ship flow after a merged `operators/` change, spec 142) applied it
without looking. Then the k3s Helm controller and Argo CD both manage the same objects and CRDs (#425).

## Stories

- As someone running a system on a local cluster, I want each operator managed by exactly one installer, so a change to
  `operators/` never produces two competing installs.
- As the owner of that cluster, I want the switch to Argo CD to keep every CRD and every resource that uses one.

## Acceptance criteria

- **AC-146.1** Given a cluster with the k3s HelmChart `kube-system/<op>` (`external-secrets` or `kyverno`) and a repo that
  renders `operators/apps/<op>.yaml`, when `scripts/operator-handover.sh` runs, then that operator is handed over to Argo CD;
  an operator that has a HelmChart but no `operators/apps/<op>.yaml` stays on its HelmChart, with one line saying so.
- **AC-146.2** Given a handover, then it runs these steps in this order, printing one line per step: (1) annotate the
  release's CRDs `helm.sh/resource-policy=keep`; (2) annotate the HelmChart `helmcharts.helm.cattle.io/unmanaged=true` and
  remove its finalizer `wrangler.cattle.io/on-helm-chart-remove`, so deleting it runs no `helm uninstall`; (3) delete the
  HelmChart (failing when an uninstall job `helm-delete-<op>` exists), the Helm release secrets of `<op>` in its namespace and
  the controller's install objects; (4) apply `operators/root.yaml`; (5) compare the counts.
- **AC-146.3** Given a handover, when the count of the release's CRDs, of ExternalSecrets, ClusterSecretStores and
  SecretStores (External Secrets) or of Kyverno policies differs from the count before step 1, then the script exits 1 and
  names each changed count with its value before and after.
- **AC-146.4** Given a cluster without the HelmChart CRD, or without a HelmChart for either operator (a fresh cluster, or a
  second run after a handover), when the script runs, then it prints nothing and changes nothing.
- **AC-146.5** Given `cluster-up` or `bootstrap` on a repo with `operators/root.yaml`, when it applies the operators, then it
  runs the handover first; `cluster-up` no longer keeps an External Secrets or Kyverno HelmChart for an operator the repo
  renders.

## Non-goals

- Choosing the owner per operator (`owner` for one operator, `install` for another; option B of #425).
- The CloudNativePG HelmChart of an older cluster-up: it is still kept and `operators/root.yaml` is not applied then.
- The cluster repo (`templates/cluster-gitops`): its `cluster-up` installs neither operator.
- LGTM: its plain manifests have no second manager; Argo CD adopts them.

## Changelog

- 2026-11-05 created (fix for #425)
- 2026-11-05 approved
- 2026-11-05 building
- 2026-11-05 done
