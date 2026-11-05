# Verification — 146 One owner per operator on the local cluster

**Result:** pass
**Trace:** 5/5 criteria named by tests

Tests: `H` = `tests/cplat/test_425_operator_handover.py` (fake kubectl that keeps the cluster state in files). Full `tests/cplat`
green. Real-cluster run on 2026-11-05 on a throwaway k3d cluster (k3s v1.32.5+k3s1, Argo CD v3.4.12): External Secrets 2.12.0
and Kyverno 3.9.1 installed as HelmCharts with the YAML of `cluster-up`, two ExternalSecrets, one SecretStore, one
ClusterSecretStore and the rendered NamespacedValidatingPolicy; then `bootstrap` from this branch. Both HelmCharts, their install
objects and release secrets were gone, no `helm-delete-*` job or RemoveJob event, all 47 CRDs annotated keep, every count
unchanged, the same Deployments (same age) running, `operator-external-secrets` and `operator-kyverno` Synced/Healthy, Argo CD
self-healed a scaled Deployment, the ExternalSecrets kept syncing; a second run printed nothing. `operators/root.yaml` was
replaced by the two operator Applications there (the throwaway repo is not on GitHub).

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-146.1 | met | `H::test_a_helmchart_of_a_rendered_operator_is_handed_over_in_order`, `H::test_a_helmchart_of_an_operator_the_repo_does_not_render_is_kept` | `templates/gitops-app/scripts/operator-handover.sh:45-51` | real cluster: both operators handed over |
| AC-146.2 | met | `H::test_a_helmchart_of_a_rendered_operator_is_handed_over_in_order`, `H::test_the_handover_script_parses` | `operator-handover.sh:55-86` | order checked on the kubectl call log |
| AC-146.3 | met | `H::test_a_lost_resource_fails_loudly_naming_it` | `operator-handover.sh:87-104` | |
| AC-146.4 | met | `H::test_without_a_helmchart_nothing_changes`, `H::test_a_cluster_without_the_k3s_helm_controller_is_left_alone`, second run in the in-order test | `operator-handover.sh:32`, `:46`, `:79` | real cluster: second run silent |
| AC-146.5 | met | `H::test_cluster_up_and_bootstrap_hand_over_before_applying_operators_root`, `test_upgrade_121_ops.py::test_under_argo_cd_the_property_operators_come_from_operators_apps_ac_121_17` | `local-cluster.sh:720`, `bootstrap.sh:32` | cluster-up path not run on the real cluster (bootstrap was) |

## Non-goals

No per-operator owner choice; the CloudNativePG HelmChart path is unchanged; the cluster repo and LGTM are untouched.
