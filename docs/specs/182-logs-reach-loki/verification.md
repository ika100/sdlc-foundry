# Verification — 182 Logs reach Loki

**Result:** pass
**Commit:** 861be25b · **Base:** c5777d8b · **Trace:** 6/6 criteria named by tests · **Cycle:** 2 (cycle 1 failed on AC-182.1, AC-182.2, AC-182.6 and `update.py` `_lost`)

**Open risk: the cluster test was read here, never run.** `tests/e2e/run.sh` could not run in this environment, so its steps for AC-182.1 to
AC-182.5 were checked by reading the script. Its test-fast proxy (`tests/cplat/test_e2e_logs_182.py`) checks only the script's text.
It is also unverified whether the `grafana/otel-lgtm` image provisions the Tempo `tracesToLogsV2` and the Loki `derivedFields`
`trace_id` link that AC-182.2 needs. If it does not, the new check (`run.sh:535-556`) fails the first real run with a message naming the
missing link. Plan t7 then calls for a BLOCKER, not a change to the shared stack (non-goal). The e2e job must be green in CI before merge.
Verdicts below marked "by reading" depend on that run.

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-182.1 | met | `tests/cplat/test_log_tailer_182.py::test_a_line_arrives_with_the_four_resource_labels_ac_182_1` (253), `::test_a_json_level_becomes_the_severity_ac_182_1` (296), `::test_a_line_that_is_not_a_json_object_arrives_as_plain_text_ac_182_1` (307), `::test_every_pod_of_the_namespace_is_collected_under_its_workload_name_ac_182_1` (315), `::test_a_reconnect_does_not_duplicate_lines_ac_182_1` (325), `::test_the_shipped_timing_defaults_deliver_a_line_well_within_60_seconds_ac_182_1` (392, tightened); `tests/cplat/test_logs_render_182.py::test_the_tailer_environment_names_its_namespace_pod_environment_system_and_target_ac_182_1` (120); `tests/e2e/run.sh:523-526` (by reading) | `templates/gitops-app/scripts/render.py:2913` (`to_record`), `:2938` (`workload`), `:3015` (`attributes`), `:2875-2880` (poll 5 s, flush 1 s, reconnect 2 s, look-back 60 s), `:3359-3362` (the rendered env sets no timing override) | Cycle-1 TEST LOOSER resolved. The new test pins poll + reconnect + flush ≤ 30 s and a look-back ≥ 60 s. It also checks that the rendered container sets neither `TAILER_POLL_SECONDS` nor `TAILER_FLUSH_SECONDS`. That check is meaningful: the env is written as `{"name": "TAILER_…"}` at `render.py:3359`. So a slow default or override now fails. The collector batch and Loki ingest add time outside the tailer, which only the cluster test covers. |
| AC-182.2 | met (by reading) | `test_log_tailer_182.py::test_a_valid_trace_and_span_id_become_the_records_trace_context_ac_182_2` (334), `::test_upper_case_hex_ids_are_lower_cased_ac_182_2` (339), `::test_an_invalid_or_all_zero_trace_id_is_not_carried_and_a_span_id_needs_a_trace_id_ac_182_2` (344), `::test_to_record_maps_level_and_trace_context_ac_182_2` (367); `tests/cplat/test_e2e_logs_182.py::test_the_script_checks_the_grafana_link_between_trace_and_logs_ac_182_2` (48, tightened); `tests/e2e/run.sh:525` (Loki `\| trace_id=`), `:528-534` (Tempo `/api/traces/<id>`), `:535-556` (Grafana `/api/datasources`: Tempo `tracesToLogsV2`, Loki `derivedFields` with `trace_id`) | `render.py:2929-2935`; `templates/service-java/.../InfoController.java.jinja:25`; `run.sh:485-487` (Grafana 3000 port-forward) | Cycle-1 TEST LOOSER resolved: the cluster test now asserts both Grafana links and fails naming the missing one. It checks that `tracesToLogsV2` is present (truthy), not that `filterByTraceID` is set or which `datasourceUid` it points to. That is acceptable for "shows that entry under logs for this span". Whether otel-lgtm provisions the links is the open risk above. |
| AC-182.3 | met | `test_logs_render_182.py::test_the_role_reads_only_pods_and_pod_logs_ac_182_3` (72), `::test_the_role_binding_binds_the_service_account_in_its_own_namespace_ac_182_3` (79), `::test_no_cluster_wide_role_no_daemon_set_no_host_path_ac_182_3` (86), `::test_the_tailer_container_is_unprivileged_and_reads_only_what_it_needs_ac_182_3` (107), `::test_the_collector_container_is_unchanged_and_only_the_tailer_mounts_the_token_ac_182_3` (130), `::test_the_guard_rail_policy_admits_the_tailer_image_in_enforce_ac_182_3` (152); `test_e2e_logs_182.py::test_the_script_proves_the_collectors_permission_is_limited_to_its_namespace_ac_182_3` (60); `run.sh:561-571` (by reading) | `render.py:3357-3370` (user 65534, read-only root FS, drop ALL, no privilege escalation), `:3381` (SA, no automount), `:3390-3395` (Role, RoleBinding), `:1853` (registry) | Unchanged since cycle 1. The refusal in another namespace (`auth can-i` = no in e2e-staging and kube-system) is proven only in the cluster. |
| AC-182.4 | met | `test_logs_render_182.py::test_the_render_with_observability_off_is_byte_identical_to_the_render_before_this_change_ac_182_4` (184, compares against the baseline render.py), `::test_without_observability_nothing_about_log_collection_is_rendered_ac_182_4` (172), `::test_the_collector_tailer_never_collects_its_own_pod_ac_182_4` (204); `test_log_tailer_182.py::test_the_collector_pods_and_the_tailers_own_pod_are_never_read_ac_182_4` (352), `::test_the_tailer_prints_no_log_content_ac_182_4` (360); `run.sh:557-559` | `render.py:3027` (skip on the collector label or `TAILER_POD`), `:1852-1853` (registry only with observability) | Unchanged since cycle 1. |
| AC-182.5 | met (by reading) | `test_e2e_logs_182.py::test_dev_runs_with_the_lgtm_log_backend_ac_182_5` (19), `::test_the_script_asks_loki_for_the_components_line_by_service_and_namespace_ac_182_5` (23), `::test_the_script_waits_at_most_120_seconds_for_the_line_ac_182_5` (30), `::test_the_failure_messages_name_the_missing_label_or_line_ac_182_5` (37) | `run.sh:179` (`ui: lgtm`), `:501-515` (`loki_wait 120` on `{service_name="e2e-api", k8s_namespace_name="e2e-dev"}`; failures name "no stream for service_name=e2e-api" or "no line 'info requested' within 120 s") | Not run here (see the open risk). The logic is sound: a fresh traceparent, the port-forward PID killed in `cleanup` (`run.sh:106`), no `pgrep -f`. |
| AC-182.6 | met | Python (runs in test-fast): `tests/cplat/test_log_trace_templates_182.py::test_python_log_lines_inside_a_span_carry_the_span_ids_ac_182_6` (71), `::test_python_log_lines_outside_a_span_carry_neither_id_ac_182_6` (86). Go, Java and Next.js (tightened, structural): `::test_go_wires_trace_id_from_the_32_hex_group_and_span_id_from_the_16_hex_group_ac_182_6` (154), `::test_go_own_behaviour_test_pins_both_ids_and_their_absence_ac_182_6` (164), `::test_java_own_behaviour_test_pins_both_ids_and_their_absence_ac_182_6` (173), `::test_java_agent_is_attached_with_observability_and_logs_through_the_json_encoder_ac_182_6` (182), `::test_nextjs_wires_trace_id_to_the_span_trace_id_and_span_id_to_the_span_span_id_ac_182_6` (189), `::test_nextjs_own_behaviour_test_pins_both_ids_and_their_absence_ac_182_6` (196). Behaviour tests that run them in the platform's CI: `templates/service-go/internal/server/tracelog_test.go` (`go test`, `.github/workflows/ci.yml:499` matrix with observability on), `templates/service-java/src/test/java/{{ package_path }}/LogFormatTest.java.jinja` (`mvn verify`, `ci.yml:574,576`), `templates/web-nextjs/tests/logger.test.ts` (vitest, smoke job; `needs_observability` defaults to true) | `templates/service-python/src/{{ module_name }}/logging_config.py:17`, `main.py:30`; `templates/service-go/internal/server/tracelog.go:58`; `templates/service-java/src/main/resources/application.yml.jinja:49`; `templates/web-nextjs/lib/logger.ts:10` | Cycle-1 TEST LOOSER resolved. test-fast now pins the wiring: the 32-hex group goes to `trace_id` and the 16-hex group to `span_id`, not swapped, and ids are added only for a valid context. It also pins that each template's own behaviour test compares both ids for equality and checks they are absent outside a span. Those behaviour tests run in the platform's CI smoke jobs, so the platform suite fails when an id is missing or differs. Remaining gaps, both acceptable: (a) the template-owned tests do not name AC-182.6, so the trace sees only the structural tests; (b) Java simulates the agent's MDC instead of running the agent, and the structural test pins that the agent is attached (`Dockerfile.jinja`). |

## Non-goals

- Templates push no logs over OTLP. Python's `FastAPIInstrumentor` creates spans only, and logs still go to stdout. ✔
- service-go gets no tracing library: `tracelog.go` parses `traceparent` with the standard library, and `go.mod` is unchanged. ✔
- No platform namespace and no node is collected: the tailer lists only `TAILER_NAMESPACE` (`render.py:3027`), and the Role is namespaced. ✔
- The shared Grafana stack is unchanged. run.sh port-forwards the pod (now also Grafana's 3000) and only reads `/api/datasources`. It changes no Service and no data source. ✔
- Guard-rail policy rules are unchanged. The per-environment `registries` variable gains the pinned tailer image, which the contract specifies. ✔
- No retention, dashboards, alerts or sampling were added. No site and no template-owned layout (header, footer, navigation) changed. ✔

## Deviations from the plan

- **`scripts/cplat/update.py` is in no task's `files`.** All its changes are acceptable.
  - The migration proof (`_without_log_tailer`, used at `update.py:593-594`) drops the tailer's four files and the changed `collector.yaml` and `kustomization.yaml` whole. **Acceptable:** a 4.7 system with observability gains the tailer by design, and AC-182.4 promises identity only with observability off.
  - The `_lost` check (`update.py:1012`) was fixed in 861be25b, resolving the cycle-1 not-acceptable item. With `only_added_parts=True`, `collector.yaml` and `kustomization.yaml` stay compared; `_tailer_parts_out` (`update.py:497-508`) strips only what the tailer adds:
    - the `log-tailer` container;
    - the `tailer` and `sa-token` volumes;
    - `checksum/tailer`;
    - `serviceAccountName` and `automountServiceAccountToken`;
    - the four new kustomization entries.

    `tests/cplat/test_update_lost.py::test_a_local_change_to_the_observability_collector_is_still_lost` shows that a local `replicas: 3` is still reported. `::test_only_the_tailer_added_to_the_collector_is_not_lost` shows that the tailer's addition alone is not. **Acceptable.**
  - Minor: a file that fails to parse keeps its raw bytes (`update.py:524-525`), which errs toward reporting.
- **Older acceptance tests of other specs, recorded here as the orchestrator asked.**
  - The byte-identity tests for AC-114.40 and AC-115.6 now filter through `_without_log_tailer` in migration mode, so they skip the collector Deployment and the observability kustomization:
    - `tests/cplat/test_migrate_114.py:304`;
    - `tests/cplat/test_resources_115.py:156`;
    - `tests/cplat/test_resources_115_cmds.py:426-427`;
    - `tests/cplat/test_system_render_114.py:59`.
  - The 118/119/120 goldens were re-recorded in bd635583: `test_cache_118.py`, `test_broker_119.py`, `test_scale_120.py` (full5 and rich5, 79 files = 67 + 12 tailer files). Those fixtures have observability on.
  - **Acceptable:** design.md covers the observability-on output changing on purpose, and AC-182.4's byte-identity with observability off is proven separately (`test_logs_render_182.py:184`).
  - Residual: these older tests no longer guard the collector Deployment against unrelated changes. That job now falls to `test_logs_render_182.py:130` (the collector container unchanged).
- The design's "Decisions taken during the ship" allow the updates to `test_addons.py`, `test_policies.py` and `test_system_render_114.py`. ✔
- All 8 tasks are `done: true`. Apart from the above, the changed files match the tasks' `files`. `templates/cluster-gitops/scripts/system_render.py` is byte-equal to `render.py` (`cmp`).

## Contract

Matches design.md. One wording point is unchanged from cycle 1: the design says `kustomization.yaml` "lists all eight files", but it lists the other seven. That is the only meaningful reading, and `test_logs_render_182.py:59` asserts it. `run.sh` adds a Grafana port (3000) and a data-source read that the design's cluster-test list did not name. That is an acceptable addition for AC-182.2: it is read-only and changes no stack.

## Tightened acceptance tests

| File | Reason | Now asserts the criterion as written |
|---|---|---|
| `tests/cplat/test_log_tailer_182.py` | AC-182.1: nothing pinned the 60 s limit, because tests ran with `TAILER_POLL_SECONDS=0.2` (cycle 1) | yes. It pins the shipped poll + reconnect + flush ≤ 30 s and look-back ≥ 60 s, and checks the render sets no override. Delivery inside the collector and Loki stays with the cluster test. |
| `tests/cplat/test_e2e_logs_182.py` | AC-182.2: nothing checked the Grafana trace↔log link (cycle 1) | yes, as far as a test-fast proxy of a shell script can: it requires run.sh to read `/api/datasources` and check `tracesToLogsV2` and `derivedFields`/`trace_id`. The behaviour itself depends on the e2e run (open risk). |
| `tests/cplat/test_log_trace_templates_182.py` | AC-182.6: the Go, Java and Next.js tests were source greps that would pass with swapped or wrong ids (cycle 1) | yes. Wiring is pinned against swapping, and each template's own behaviour test (run in the platform CI smoke jobs) is pinned to compare both ids and check they are absent. Python runs behaviourally in test-fast. |

## Mutation check (report only)

Skipped: no mutation check for shape platform yet.
