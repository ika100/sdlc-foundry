---
spec_id: 146-one-owner-per-operator-on-the-local-cluster
shape: platform
spec_hash: 5bd31da13231
summary: "New templates/gitops-app/scripts/operator-handover.sh hands External Secrets and Kyverno HelmCharts of an older cluster-up over to Argo CD (keep-annotate CRDs, unmanaged + finalizer removal, delete HelmChart, release secrets and install objects, apply operators/root.yaml, compare counts); local-cluster.sh and bootstrap.sh call it before applying operators/root.yaml; the cluster-gitops copy is kept by sync-template-copies.py"
tasks:
  - id: t1
    title: operator-handover.sh and its tests
    files: [templates/gitops-app/scripts/operator-handover.sh, tests/cplat/test_425_operator_handover.py]
    covers: [AC-146.1, AC-146.2, AC-146.3, AC-146.4]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: cluster-up and bootstrap call the handover; the cluster-gitops copy; changelog fragment
    files: [templates/gitops-app/scripts/local-cluster.sh, templates/gitops-app/scripts/bootstrap.sh, templates/cluster-gitops/scripts/local-cluster.sh, templates/cluster-gitops/scripts/operator-handover.sh, scripts/sync-template-copies.py, tests/cplat/test_142_bootstrap_ff.py, tests/cplat/test_upgrade_121_ops.py, docs/changelog.d/425-operator-handover.fixed.md]
    covers: [AC-146.5]
    parallel_safe: false
    depends_on: [t1]
    done: true
---

# Plan — 146 One owner per operator on the local cluster

A fix plan: one script, two callers. The helm-controller behaviour it relies on (k3s v1.32.5+k3s1 ships helm-controller
v0.16.10): the finalizer is `wrangler.cattle.io/` + `on-helm-chart-remove`; wrangler re-adds it while the object is not being
deleted unless the scoped handler skips the chart, which `helmcharts.helm.cattle.io/unmanaged` makes it do; without the
finalizer, deleting the chart runs no `OnRemove` and so no `helm-delete-<op>` job.
