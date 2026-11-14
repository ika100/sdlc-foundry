# Verification — 199 The journey 15 seams

**Result:** pass
**Commit:** 5d2c8c5c · **Base:** 95aac836 · **Trace:** 5/5 criteria named by tests

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-199.1 | met | `tests/cplat/test_199_ship_deploy.py::test_the_dev_smoke_runs_on_the_reported_port_and_is_recorded_ac_199_1`, `::test_staging_is_promoted_and_smoked_on_the_reported_port_ac_199_1`, `::test_a_passing_smoke_is_not_reported_as_not_run_ac_199_1` | `scripts/cplat/smoke.py:437`, `scripts/cplat/model.py:430`, `scripts/cplat/model.py:438-444`, `scripts/cplat/localport.py:64-71` | Fake docker reports 8089, environment answers only on 8089; tests assert the `smoke (dev) against http://shop-api.shop-dev.localhost:8089:` line, the recorded `outcome: passed` and `base_url`, the `pin-staging` dispatch and `promotion.staging.result == "promoted"`. |
| AC-199.2 | met | `tests/cplat/test_199_system_ship.py::test_land_smokes_dev_and_staging_on_the_reported_port_ac_199_2`, `::test_land_does_not_escalate_for_an_unreachable_environment_ac_199_2`, `::test_land_records_the_results_ac_199_2`, `::test_the_prod_evidence_shows_the_staging_smoke_without_a_warning_ac_199_2`, `::test_promote_smoke_runs_on_the_reported_port_and_records_ac_199_2`, `::test_the_promote_smoke_record_is_prod_evidence_ac_199_2` | `scripts/cplat/appship_joint.py:340`, `scripts/cplat/smoke.py:437`, `scripts/cplat/evidence.py:154` | Land smokes dev and staging of both components on 8089, records `passed` with the 8089 `base_url`, no escalation; promote `--smoke` runs on 8089 and records; the evidence summary has a passed staging entry carrying the port and no `WARNING` / "no staging smoke record" line. |
| AC-199.3 | met | `tests/cplat/test_199_grafana.py::test_system_set_names_grafana_on_the_reported_port_ac_199_3` (plain and `--dry-run`), `::test_system_set_json_carries_the_reported_port_ac_199_3`, `::test_a_second_identical_call_still_reports_the_port_ac_199_3`, `::test_system_set_follows_the_kube_context_of_its_repo_ac_199_3`, `::test_system_status_names_grafana_on_the_reported_port_ac_199_3`, `::test_the_status_table_prints_the_reported_port_ac_199_3` | `scripts/cplat/systemset.py:119,138,143`, `scripts/cplat/status.py:236,304`, `scripts/cplat/model.py:447-449` | Grafana line and `grafana_url` in `--json` of both commands are `http://grafana.localhost:8089/`; staging (non-local) stays `None`. |
| AC-199.4 | met | `tests/cplat/test_199_localport.py::test_the_reported_port_is_used_ac_199_4`, `::test_component_urls_and_grafana_carry_the_reported_port_ac_199_4`, `::test_local_http_port_wins_and_docker_is_not_asked_ac_199_4`, `::test_other_values_of_local_http_port_count_as_unset_ac_199_4`, `::test_no_answer_falls_back_to_8088_without_an_error_ac_199_4` (exit, no-container, empty, garbage, out-of-range, missing), `::test_a_non_local_environment_never_asks_docker_ac_199_4`, `::test_a_url_template_never_asks_docker_ac_199_4`, `::test_docker_port_parses_the_first_line_ac_199_4`, `::test_docker_port_without_docker_is_none_ac_199_4` | `scripts/cplat/model.py:438-444`, `scripts/cplat/localport.py:48-61` | Digit `LOCAL_HTTP_PORT` wins with zero docker calls; non-digit treated as unset; every no-answer case gives 8088 without raising; `https://` hosts and `url` templates never call docker. |
| AC-199.5 | met | `tests/cplat/test_199_localport.py::test_local_cluster_names_the_cluster_ac_199_5`, `::test_a_k3d_kube_context_names_the_cluster_ac_199_5`, `::test_the_kube_context_of_the_settings_file_names_the_cluster_ac_199_5`, `::test_the_kube_context_of_the_user_file_names_the_cluster_ac_199_5`, `::test_another_or_empty_context_falls_through_to_the_default_ac_199_5`, `::test_a_malformed_kube_context_setting_is_ignored_ac_199_5`, `::test_the_default_cluster_is_the_system_local_ac_199_5`, `::test_docker_is_asked_once_per_cluster_per_invocation_ac_199_5`, `::test_a_missing_answer_is_cached_too_ac_199_5`, `::test_the_next_invocation_asks_again_ac_199_5`, `::test_every_cplat_main_call_starts_with_an_empty_cache_ac_199_5`; `tests/cplat/test_199_system_ship.py::test_land_asks_docker_once_for_the_whole_invocation_ac_199_5` | `scripts/cplat/localport.py:34-45`, `scripts/cplat/localport.py:64-71`, `scripts/cplat/cplat.py:162` | Order LOCAL_CLUSTER, then `k3d-<name>` from `CPLAT_KUBE_CONTEXT` / project file / user file, then `<system>-local`; one docker call per cluster per invocation (a full `system ship land` included); `cplat.main` clears the cache. |

## Non-goals

- `cluster-up` port choice untouched (no change under `templates/` or the cluster scripts). ✔
- No discovery for kind / Docker Desktop / minikube: only `k3d-` contexts are used, others fall through (`localport.py:43`). ✔
- No recording for hand-run `--base-url` smoke. ✔
- Non-local URLs: `https://` branch and `url` templates never ask docker (`model.py:430-431`). ✔
- No template-owned layout change (header, footer, navigation); the site guide got one sentence in an existing step. ✔

## Deviations from the plan

- `scripts/cplat/evidence.py` changed (`_entry` adds `base_url`), though design.md "Contract" says no change in `evidence.py` is needed. Reason: the AC-199.2 evidence acceptance test asserts `str(PORT) in s.staging["base_url"]`, which the entry did not carry; the plan records it as task t5 ("found while building t2"). Acceptable: an additive field, no output wording changed, plan updated. Not fixed: design.md still says no change in `evidence.py` is needed; and the change was committed in the bookkeeping commit `5d2c8c5c chore(plan): ... t2, t3 done` rather than its own `feat` commit (a history-hygiene point, not a defect).
- All other changed files are in a task's `files`; every task (t1 to t5) is `done: true`. Test helpers `tests/cplat/docker199_support.py` and the `test_199_*` files come from the red-first acceptance commits, as expected.

## Contract

Matches design.md (`localport` API, `TIMEOUT_S = 5`, cache keyed by cluster, None cached, `docker_port` called through the module attribute, the conftest `no_real_docker_port` seam, `model.local_port/grafana_url/grafana_location` signatures), except the evidence point above. `localport.cluster` also catches `OSError` besides `PlatformError`: a harmless widening of the silent fallback (A3).

## Mutation check (report only)

Skipped: no mutation check for shape platform yet.
