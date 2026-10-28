# Verification — 120 Instances scale on load and queue depth

**Result:** fail. Two criteria are `partial`; both fixes are small. AC-120.24: `docs/DOMAIN-MODEL.md` describes `autoscaling` wrongly. AC-120.26: a `system.yaml` without `scale` whose `components` or `instances` is not a mapping now crashes the renderer, where it used to get 114's error. The other 26 active criteria are `met`. Their in-cluster parts are pending this PR's CI e2e job.
**Commit:** d1026bc · **Base:** 78ffff6 (`origin/main`, also the merge base) · **Trace:** 28/28 active criteria are named by tests. AC-120.1 to .28 appear in `tests/cplat/test_scale_120*.py`. AC-120.5, .6, .10 to .15, .17 to .20, .22, .23, .25 and .27 also appear in `tests/e2e/run.sh`.

**Test run.** These figures come from the orchestrator. I did not rerun them, because this review is read-only.
- Full suite: 5830 passed, 12 skipped.
- `scripts/ci-local.sh --render --site` passed.
- Pins were checked by the orchestrator:
  - `docker manifest inspect` finds the three `ghcr.io/kedacore/*:2.19.0` images and `registry.k8s.io/metrics-server/metrics-server:v0.9.0`.
  - The Deployment names of KEDA chart 2.19.0 (`keda-operator`, `keda-operator-metrics-apiserver`, `keda-admission-webhooks`) and the label `app.kubernetes.io/name=keda-operator` were read from the chart archive.

**Not run locally:** `tests/e2e/run.sh` (t12). The CI e2e workflow runs it on this PR. Until it is green, these are **pending CI, not passed**:
- AC-120.23 as a whole;
- the cluster halves of AC-120.5, .6, .10, .12 to .15, .17 to .20, .22, .25 and .27.

The e2e runs with `WITH_ARGO=0`, so no test exercises Argo CD itself. It does not exercise "stays Synced" (AC-120.19, .23) or the order in which the ApplicationSet and a component application pick up one commit (AC-120.20). The changelog line of 2026-10-28 accepts an emulation for this: the e2e applies the rendered Deployment with the live count, and the render tests check the ignore rule.

Line numbers refer to `templates/gitops-app/scripts/render.py` unless another file is named. Two copies are byte-identical to their originals (`cmp` at d1026bc):
- `templates/cluster-gitops/scripts/system_render.py` is a copy of `render.py`;
- `templates/cluster-gitops/scripts/local-cluster.sh` is a copy of `templates/gitops-app/scripts/local-cluster.sh`.

Test files: `test_scale_120.py` (render) and `test_scale_120_cmds.py` (cmds). Fixtures are in `tests/cplat/scale_fixtures.py`.

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-120.1 | met | render: `test_a_full_scale_is_accepted_on_a_component_and_on_an_instance_ac_120_1`, the website test, `test_min_defaults_to_1_…`, `test_the_range_boundaries_are_accepted_ac_120_1`, `test_a_malformed_scale_fails_naming_the_key_and_the_range_ac_120_1` (parametrised), the four order tests, `test_on_is_required_even_though_the_spec_names_only_max_ac_120_1`, `test_an_unquoted_on_key_is_read_as_on_ac_120_1` | `render.py:715-752` (`check_scale`), `:704-712` (`scale_on_keys`), `:169-174` (key lists) | `on` is required (changelog reading). Every message starts with `components.<c>[.instances.<env>].scale`, so it names the component, the environment, the key and the range. |
| AC-120.2 | met | render: `test_a_component_scale_applies_to_every_instance_without_scale_or_replicas_ac_120_2`, `test_an_instance_scale_replaces_…`, `test_an_instance_replicas_runs_the_fixed_number_…`, `test_an_instance_scale_wins_over_a_component_replicas_ac_120_2`, the two `_eff` tests | `render.py:791-799` (own `scale`, else none with own `replicas`, else the component's), `:889-894` | An instance `scale` replaces the component's as a whole (`check_scale` of the instance's own mapping). |
| AC-120.3 | met | render: `test_scale_and_replicas_on_the_component_fail_naming_both_ac_120_3`, `…_on_one_instance_fail_naming_the_environment_ac_120_3`, the order test, `test_scale_on_the_component_with_replicas_on_an_instance_is_fine_ac_120_3` | `render.py:755`, `:793-794`, `:891-892` | |
| AC-120.4 | met | render: `test_an_invalid_trigger_fails_listing_the_four_forms_ac_120_4` (empty, two triggers, missing number, unknown key, not a mapping), `test_every_one_of_the_four_forms_is_accepted_ac_120_4`, the key-order test, the trigger-name test | `render.py:177-178` (`ON_FORMS`, `TRIGGER_FORMS`), `:731-736` | The form is decided by the set of keys. |
| AC-120.5 | met (cluster part pending CI) | cmds: the eight `component set` tests (own scale, inherited scale, no `--instance`, `--dry-run`, own replicas allowed, unscaled neighbour, component replicas with only an instance scaled, no crash), the plugin-doc and bump tests; e2e "component set e2e-worker --instance dev --replicas 2 is refused…" | `scripts/cplat/compose.py:267-281` | The check runs before any change. `--replicas 0` was already "nothing to change" before this spec (`compose.py:211`). |
| AC-120.6 | met (cluster part pending CI) | render: `test_a_cpu_or_memory_percent_out_of_range_fails_naming_the_range_ac_120_6`, `test_cpu_scale_renders_one_horizontal_pod_autoscaler_and_no_keda_object_ac_120_6`, the memory, boundary, replicas-min and label tests; e2e cpu step (`hpa.yaml`, no ScaledObject, `currentMetrics` within 120 s) | `render.py:739-742`, `:1634-1646` (`autoscaler_files`, HPA branch) | |
| AC-120.7 | met | render: `test_a_cpu_trigger_without_a_cpu_request_fails_naming_component_environment_and_request_ac_120_7`, the memory test, the instance-replaces-component test, the own-environment test, `test_a_queue_trigger_needs_no_request_ac_120_7` | `render.py:1357-1361` | Reads 114's effective `resources` (decision 14). |
| AC-120.8 | met | render: `test_min_zero_with_cpu_or_memory_fails_saying_a_queue_trigger_is_needed_ac_120_8`, the order test, `test_min_zero_with_a_queue_trigger_renders_a_deployment_at_zero_ac_120_8` | `render.py:750-751` | |
| AC-120.9 | met | render: `test_consumes_must_name_an_api_the_component_consumes_ac_120_9`, the listed-or-none test, `test_only_an_events_api_has_a_queue_ac_120_9`, `test_an_events_api_carried_by_no_broker_is_refused_ac_120_9`, the instance-path test, the `lag` test, `test_an_external_broker_cannot_be_a_trigger_ac_120_9`, the not-running-there test | `render.py:1312-1321`, `:1362-1367` (external broker, changelog reading) | |
| AC-120.10 | met (runtime pending CI) | render: `test_a_consumes_trigger_renders_a_scaledobject_on_the_durable_consumer_ac_120_10`, `test_the_trigger_names_the_consumer_and_the_stream_the_broker_creates_ac_120_10` (compared with 119's own `consumer-*`/`stream-*` documents), the endpoint, binding and string tests; e2e burst (100 messages, `.spec.replicas` 5 within 120 s, maximum 5) | `render.py:1648-1653` (`nats-jetstream`: `<app>-<b>.<app>-<env>.svc:8222`, `$G`, stream `<app>-<api>`, consumer `<c>`) | The endpoint is the nats chart's `fullnameOverride` `<app>-<b>` with the monitor port on the Service (`:2268`, `:2273`, `:2282`). Spec 119's users live in `authorization.users`, which is the global account `$G`. The e2e covers 100 → 5 and min 0, not 30 → 3 at `min: 1`; ceil(lag/10) is KEDA's AverageValue arithmetic. |
| AC-120.11 | met | render: `test_the_cache_must_be_a_cache_resource_ac_120_11` (amended in a4ec6ce, see below), `test_the_cache_must_be_listed_in_uses_ac_120_11`, the `length`, `list` and empty-list tests, the order test, the external-cache test | `render.py:1322-1328`, `:744-748` | |
| AC-120.12 | met (runtime pending CI) | render: `test_a_cache_trigger_renders_a_scaledobject_on_the_list_length_ac_120_12`, `test_the_list_and_length_are_the_declared_ones_ac_120_12`; e2e cache step (30 entries: 3 replicas within 120 s, never more over the next 30 s) | `render.py:1655-1658` | |
| AC-120.13 | met (cluster part pending CI) | render: `test_the_scaler_authenticates_with_the_secret_the_instance_reads_ac_120_13` (the same Secret the Deployment reads), the external-cache and resource-name tests, `test_a_broker_trigger_needs_no_credentials_and_renders_no_trigger_authentication_ac_120_13`, `test_no_credential_value_is_rendered_ac_120_13`; e2e: no password in the overlay or the live objects | `render.py:1659-1665` (`secretTargetRef` `host`, `port`, `password` of `<app>-<r>-app`) | The cache Secret's `host` is the full name `<n>.<ns>.svc` (`:2080`), so KEDA can resolve it from the `keda` namespace. The broker half rests on the changelog reading (unauthenticated monitoring endpoint). |
| AC-120.14 | met (runtime pending CI) | render: `test_the_queue_trigger_is_woken_by_one_item_and_polls_every_15_seconds_ac_120_14`; e2e wake step (`readyReplicas` ≥ 1 within 60 s of one message) | `render.py:1623`, `:1651`, `:1656` (`activation…` "0") | |
| AC-120.15 | met (runtime pending CI) | render: `test_the_timings_give_zero_replicas_five_to_seven_minutes_after_the_queue_empties_ac_120_15`, `test_the_scale_down_window_returns_to_min_within_five_to_seven_minutes_ac_120_15`, the wave test; e2e join (295 s ≤ Z − T ≤ 420 s, 5 s sampling) | `render.py:1623-1625`, `:1667-1675` | For `min` ≥ 1 the lower bound holds only under the 2026-10-28 reading. The e2e's 295 s floor leaves 5 s for its sampling. |
| AC-120.16 | met | render: the five derivation tests, `test_an_autoscaling_key_under_an_environment_is_an_unknown_key_ac_120_16`, the two `scaled_instances` tests; cmds: the model JSON, null, dataclass and agreement tests, the two `model show` environment-line tests | `render.py:1485-1486`; `scripts/cplat/model.py:682-685`, `:358`; `scripts/cplat/modelcmd.py:69` | |
| AC-120.17 | met (cluster part pending CI) | cmds: the nine local-cluster tests (KEDA install and waits, auto mode from the operator file, metrics-server, the k3s argument, the bounded metrics wait and warning, the default pins, the byte-equal copy, parsing), the doctor `resource metrics` tests; render: `test_the_render_half_of_the_local_cluster_files_exists_exactly_when_keda_is_derived_ac_120_17`; e2e cluster-up `WITH_KEDA=1`, APIService `Available`, HPA `currentMetrics` | `local-cluster.sh:164-180`, `:226-229`, `:504-541`, `:691-700`; `scripts/cplat/doctor.py:422-448` | See "To fix" 4 for `WITH_KEDA=1` with Argo CD and no `operators/apps/keda.yaml`. |
| AC-120.18 | met (cluster part pending CI) | cmds: `test_doctor_checks_an_owner_managed_environment_and_names_instances_and_version_ac_120_18` (missing, other version, ok, with `operators: owner`), the ok, missing, order and no-row tests; render: the owner tests of AC-120.27; e2e doctor step | `doctor.py:327`, `:402-406`, `:485` (suffix) | |
| AC-120.19 | met (Argo CD not exercised) | render: `test_the_environment_set_ignores_the_replica_count_of_scaled_deployments_ac_120_19`, the retry, HPA-only, components-order, no-Replace/PruneLast, first-sync `replicas: min` and unchanged-set tests; e2e sync emulation (`.spec.replicas` and `.metadata.generation` unchanged) | `render.py:2359-2364`, `:2376-2378`, `:1628-1631` | The same rule serves both autoscalers. A plain HPA and KEDA's generated `keda-hpa-<c>` both write `/spec/replicas` through the scale subresource, and KEDA writes 0 directly. All three are covered by the one name-scoped entry. KEDA's HPA has an ownerReference to the ScaledObject, so Argo CD does not treat it as extraneous. |
| AC-120.20 | met (Argo CD order not exercised) | render: `test_switching_from_replicas_to_scale_never_drops_below_the_new_min_ac_120_20`, `test_switching_back_to_replicas_removes_the_autoscaler_and_the_ignore_entry_ac_120_20`, the TriggerAuthentication, cpu↔queue and wave tests; e2e switch back (sampled every 2 s, never below 1, ends at 1, `keda-hpa-e2e-worker` gone) | `render.py:159-160` (`MANAGED_FILES`), `:1628-1631`, `:2359-2378` | **replicas → scale:** the Deployment and the ignore rule change in one commit. If the component application syncs before the ApplicationSet has the rule, the count is set once to the new `min`, never below it. Once the rule exists, the live count is kept. **First sync:** the Deployment is created at `min`. **scale → replicas:** the autoscaler object is pruned. If the old rule is still in force at that sync, the autoscaler's last count stays until self-heal applies the fixed number (design Risk 2). It cannot fall below the fixed number unless it was already lower: a queue worker at 0 stays at 0 until self-heal. **Request-serving components:** zero is impossible during a switch, because `min` ≥ 1 is enforced (AC-120.8, .28). |
| AC-120.21 | met | cmds: `test_a_scaled_instance_has_its_effective_scale_and_no_replicas_ac_120_21`, the inherited, replaced, unscaled, JSON-order, malformed, non-integer and external tests, the two `model show` instance-line tests | `model.py:485-503`, `:672-676`, `:346`; `modelcmd.py:48-60` | |
| AC-120.22 | met (cluster part pending CI) | cmds: the nine status tests (count, deployment read, text, unreachable `?`, failing read `?`, no context `?`, none read, `(0–5)`, unscaled cells unchanged); e2e status step | `scripts/cplat/status.py:168-176`, `:226-228`, `:354-357` | |
| AC-120.23 | met (pending CI) | render: `test_the_e2e_system_renders_the_scaled_consumer_and_its_ignore_rule_ac_120_23`; cmds: the 14 e2e-script tests, including `test_the_e2e_script_header_budgets_the_scaling_steps_and_the_job_gets_90_minutes_ac_120_23`; e2e steps | `tests/e2e/run.sh` (scaling block); `.github/workflows/e2e.yml:34` (90 minutes) | "Stays Synced" is shown by an unchanged count and generation (changelog reading). Every wait is bounded. The watcher has its own 600 s bound, and the join waits at most 650 s. |
| AC-120.24 | **partial** | cmds: `test_the_domain_model_has_a_scaling_section_with_one_example_per_trigger_form_ac_120_24`, `test_the_scaling_section_describes_the_rules_ac_120_24`, the keys-tables, docstring and journey/site/clusters tests | `docs/DOMAIN-MODEL.md:214-257`; `render.py:79-85` (docstring) | The four examples, the component default, whole replacement and exclusivity are right. **The derived `autoscaling` property is described wrongly** at `docs/DOMAIN-MODEL.md:256`: "it is true when an instance there is scaled. It is exposed in `/system:model` and `/system:status`". Three things are wrong there: the value is `keda` only for a queue trigger, else `null`; there is no `/system:model` (it is `cplat model show`); status does not show `autoscaling`. The test only checks for the words "autoscaling" and "derived", so it cannot catch this. Also wrong: `:252` says "the cluster repo declares" `resource_metrics`, but it is the gitops repo's `.copier-answers.yml`; `:255` gives "between 315 and 345 seconds", but design Timings gives 300–330 s to zero and up to 360 s to `min`. See "To fix" 1. |
| AC-120.25 | met (cluster part pending CI) | render: `test_keda_and_metrics_server_are_pinned_in_the_versions_table_ac_120_25`, `test_every_pin_is_an_exact_version_no_range_no_latest_ac_120_25`, the cluster-copy and operator-builder tests; cmds: the doctor version and order tests, the script-pins test, the cluster `--crds` and listing tests, the CHANGELOG test; e2e (pin 2.19.0 = the HelmChart version = the image tag) | `render.py:290-295` | The upgrade procedure belongs to spec 121 (a non-goal here), as in 115 to 119. |
| AC-120.26 | **partial** | render: `test_a_5x_system_without_scale_renders_byte_identically_to_before_ac_120_26` ×10 (digests committed in the red commit 27c3cf4 and unchanged since), `test_no_autoscaler_file_and_no_ignore_rule_appear_without_scale_ac_120_26`, the key-list, unknown-key, library/external and neighbour tests | `render.py:169-174`, `:1455` | Valid systems are byte-identical, and the key lists only gain `scale` at the end. **Regression:** `scale_on_keys` (`render.py:704-712`) runs at `:1455`, before 114's checks. It calls `(doc.get("components") or {}).values()` and `(c.get("instances") or {}).values()` without a type check. So `components: [api]` or `instances: [dev]` (no `scale` anywhere) now ends in an `AttributeError` traceback. Before this spec it failed with `components must be a mapping of names to components` (`:1467`) or `components.<c>.instances must be a mapping …` (`:764`). `main` only catches `RenderError` (`:2690`). No test covers it. See "To fix" 2. |
| AC-120.27 | met (cluster part pending CI) | render: `test_a_queue_instance_installs_keda_once_per_cluster_ac_120_27`, the several-environments, none-without-queue, all-owner, one-not-owner, metrics-server-only-for-install, metrics-not-into-owner and order tests; cmds: the cluster check, bootstrap and copier tests; e2e (`keda.yaml` appears, and goes in the clean-up) | `render.py:2538-2545` (`operator_files`); `templates/cluster-gitops/scripts/check.py:83-84`; `templates/cluster-gitops/scripts/render.py:268-269`; `templates/gitops-app/copier.yml:76-80`; `bootstrap.sh:28` | One file per repo means one application per cluster. `operators: owner` is honoured. The metrics source is declared through the answer, as the 2026-10-28 reading says. |
| AC-120.28 | met | render: `test_min_zero_is_refused_for_an_exposed_component_naming_the_host_ac_120_28`, the request-API (×3), together, instance-path, min-one-fine and events-provider tests | `render.py:1329-1338` | The check runs on every declared `scale`, so an inherited `min: 0` is caught where it is declared. |

## Non-goals

- Spec 114 is not amended (`docs/specs/114-*` is untouched). ✔
- No Resource scaling: `scale` is not in the resource key lists. ✔
- No cron, HTTP, Prometheus or combined triggers: `TRIGGER_FORMS` has four forms, and exactly one is allowed. ✔
- No vertical scaling and no node autoscaling. ✔
- `/component:set` has no scale flags; it only refuses `--replicas`. ✔
- `promote.py` is unchanged (not in the diff), so `/instance:promote` does not copy `scale`. ✔
- External components keep refusing `scale` with 069's text. ✔
- No KEDA upgrade procedure (spec 121). ✔
- No tuning keys: polling, cool-down and the window are constants (`render.py:1623-1625`). ✔

## Approved test changes

1. **526be84 (t13).** Every changed line carries `# spec 120`:
   - the instance key list in `test_system_render_114.py`;
   - `normalize_5` drops `autoscaling` and `scale` (`test_system_model_114.py`);
   - the `OPERATORS` order (`test_backup_117.py`);
   - `index("nack") == 7` (`test_broker_119.py`);
   - the e2e job's 90 minutes in `test_broker_119_cmds.py`. The plan's t13 `files` missed this one; it follows from t12's workflow change.
2. **a4ec6ce.**
   - The `caches: none` case of `test_the_cache_must_be_a_cache_resource_ac_120_11` now uses a component that uses an existing resource. Before, `validate_uses` failed first on the unknown `uses`. The same message is still asserted, so the test is not weaker.
   - New test `test_an_unquoted_on_key_is_read_as_on_ac_120_1`. It covers the renderer half of 231fc10 only (see "To fix" 3).

`git log origin/main..HEAD -- tests/` shows only these two commits, the red commit 27c3cf4 and the e2e d1026bc. The digests in `BEFORE_120` are unchanged since 27c3cf4.

## Deviations from the plan

1. **Doctor's multi-system prefix.** `_names` (`doctor.py:398-399`) prints `<system>/<c> (<env>)` when the repo holds more than one system. design.md shows only `<c> (<env>)`. Acceptable: with several systems the bare name would be ambiguous. Add a sentence to design.md's doctor contract.
2. **t12 "Done when"** asks for a local e2e pass recorded here. It was not run locally; the result is pending CI.
3. **t3 re-verification.** design.md records "Verified at plan time" for the images. The chart-archive check of the Deployment names and label was done at build, but design.md has no "Re-verified at build" line. Acceptable; add the line, as 117 did.
4. **Files outside every task's `files`:**
   - the planning artefacts: ADR-066, ADR-067, `docs/adr/README.md`, `docs/backlog.md`, spec, design, plan;
   - the red commit's `tests/cplat/scale_fixtures.py` and `test_scale_120*.py`;
   - `tests/cplat/test_broker_119_cmds.py` (item 1 above).

   Acceptable.
5. **Task status.** The plan has no `done` flags. Each of t1 to t13 has a commit: a6565d2 (+231fc10), a151eef, b693701, 766cfc8, 83348af, 9949cef, 9479266, 68d287e, dd95728, 8c33e8b, 79b55b7, d1026bc and 526be84.

## Design decisions taken by default (all 25 checked)

1. KEDA chart 2.19.0: `render.py:290-292`. ✔
2. Name-scoped `ignoreDifferences`, `RespectIgnoreDifferences=true` and `replicas: <min>`: `:2359-2378`, `:1628-1631`. ✔
3. `resource_metrics: provided | install`, default `provided`: `copier.yml:76-80`, `render.py:2541`, `doctor.py:383-390`. ✔
4. `on` is required: `:733-734`. ✔
5. Polling 15 s, cool-down 315 s, window 345 s, 100 % per 15 s: `:1623-1625`, `:1672-1674`. ✔
6. Lag is KEDA's `num_pending + num_ack_pending`: nothing is configured for it. ✔
7. An external broker is refused as a trigger: `:1362-1367`. ✔
8. No TriggerAuthentication for a broker trigger: `:1648-1653`. ✔
9. A cache trigger reads `host`, `port`, `password`, with `databaseIndex: "0"` and no TLS: `:1655-1665`. ✔ The TLS limit is a design Risk marked "documented", but DOMAIN-MODEL does not mention `rediss://` (see "To fix" 1).
10. Objects are named after the component, in its overlay: `:2490`. ✔
11. Wave 1 with `SkipDryRunOnMissingResource`, and retry with KEDA: `:1669`, `:2363-2364`. ✔
12. `component set --replicas` without `--instance` is refused while the component has `scale`: `compose.py:279-281`. ✔
13. AC-120.28 names `expose.host` or the component name: `:1331-1334`. ✔
14. 114's effective `resources`: `:1358`. ✔
15. metrics-server is in `kube-system` with `crd: None`; the cluster `--crds` skips it, and bootstrap falls through: `:293-295`, cluster `render.py:268`, `bootstrap.sh:28-29`. ✔
16. `scale` is last in both key lists: `:169-174`. ✔
17. Status shows `.spec.replicas`: `status.py:172`. ✔
18. Status text `replicas <n> (<min>–<max>)`; JSON `scale` only on scaled cells: `status.py:226-228`, `:354-357`. ✔
19. The model's `scale` has exactly `min`, `max`, `on`: `model.py:491`. ✔
20. k3s' own metrics-server by default; a new cluster is created without it when the metrics-server operator file exists: `local-cluster.sh:226-229`. ✔
21. A 120 s metrics wait that only warns: `local-cluster.sh:173-180`. ✔
22. e2e: `e2e-worker`, `jobs`, only the HPA applied for e2e-web, the scale-down wait overlapped with other steps, and 90 minutes. ✔
23. Plugins `component` 1.3.0, `system` 1.4.0, `platform` 1.2.0, in both places. ✔
24. Two ADRs (066, 067); the numbers are free on `origin/main`. ✔
25. `min` defaults to 1; `scale: null` is "not a mapping": `:717-718`, `:738`. ✔

## Contract

Matches `design.md` in these parts:
- the schema, every render error text and the check order;
- `_eff[env]["scale"]` and `cfg["autoscaling"]`;
- `scaled_instances`;
- `hpa.yaml`, `scaledobject.yaml` (both triggers) and `triggerauthentication.yaml`, with their key order;
- the ApplicationSet entries;
- the `OPERATORS` entries;
- `operator_files`;
- the copier question;
- the model and JSON keys;
- the `model show` texts;
- the status cell;
- the `component set` texts and hints;
- the doctor rows and fixes (plus the prefix in Deviation 1);
- `check.py`, `--crds`, `bootstrap.sh` and `local-cluster.sh`;
- the e2e outline (steps 1 to 9).

## To fix or confirm before the PR

1. **AC-120.24, `docs/DOMAIN-MODEL.md`.** Doc-only; it blocks the result.
   - `:256`: say that `autoscaling` is `keda` when an instance in the environment has a `consumes` or `cache` trigger, and `null` otherwise (also for cpu/memory). Say that it is shown by `cplat model show` (`--json`). Drop `/system:model` and the claim that `/system:status` shows it; status shows the replica count and bounds of a scaled instance.
   - `:252`: `resource_metrics` is the gitops repo's answer in `.copier-answers.yml`, not the cluster repo's.
   - `:255`: state the designed timings. Zero comes 300 to 330 s after the queue is empty. `min` ≥ 1 comes at most about 6 minutes after, and no earlier than 5 minutes when the last `min × lag` items are worked off within 30 s.
   - Add the two risks the design marks as "Documented": a cache trigger does not support TLS (`rediss://`), and Argo CD's label tracking would make KEDA's HPA look extraneous.
2. **AC-120.26, `render.py:704-712`.** In `scale_on_keys`, return when `doc.get("components")` is not a dict, and skip `instances` that are not a dict. 114's own checks then report the error as before. Add a render test, e.g. `components: [api]` and `instances: [dev]` fail with 114's texts. Run `scripts/sync-template-copies.py` afterwards.
3. **Model half of the unquoted `on:` fix (231fc10, `model.py:487-488`).** No test covers it, because a4ec6ce tests only the renderer. Add a model test: an unquoted `on:` gives `scale.on` and `autoscaling: keda` for a queue trigger.
4. **Confirm `WITH_KEDA=1` with Argo CD.** The spec's reading for AC-120.17 says that a local cluster whose KEDA environments are all `operators: owner` needs `WITH_KEDA=1`. With `WITH_ARGO=1` that flag installs nothing (`local-cluster.sh:504-505`), because KEDA then comes only from `operators/root.yaml`, which has no `keda.yaml` in that case:
   - without `operators/root.yaml`, the operators block is skipped and KEDA is silently missing;
   - with it, the script waits about 10 minutes for the CRD, then `rollout status` fails under `set -e`.

   NACK has the same pattern (pre-existing). Either install the HelmChart when `WITH_KEDA=1` and the operator file is missing, or narrow the reading to `WITH_ARGO=0`.
5. **Small items:**
   - The CHANGELOG writes `(<min>-<max>)` with a hyphen; status prints an en dash.
   - After the cpu step, e2e-web's dev Deployment keeps the count the HPA last chose (probably 1), because only the HPA is deleted. The later steps re-apply the Deployment on ship, so this is harmless. Re-applying its Deployment would make the clean-up exact.

RESULT: fail. AC-120.24 is partial (DOMAIN-MODEL describes `autoscaling` wrongly and names a command that does not exist). AC-120.26 is partial (`scale_on_keys` crashes on a non-mapping `components` or `instances` in a system without `scale`). Both fixes are small. After them, the result is pass on condition that the PR's CI e2e job is green before merge.

## After review (orchestrator)

- **895e8e7 — AC-120.26 regression fixed.** `scale_on_keys` now skips a non-mapping `components` or `instances`, so `components: [api]`
  and `instances: [dev]` fail with 114's own message again; a parametrised render test covers both.
- **AC-120.24 fixed.** DOMAIN-MODEL now says `autoscaling` is `keda` (queue trigger) or null, names `cplat model show`, says
  `/system:status` shows a scaled instance's replicas, places `resource_metrics` in the gitops repo's `.copier-answers.yml`, gives
  design.md's timings, and documents the two missing limits (no TLS for cache triggers; label-based Argo CD tracking).
- Also: a model test for the unquoted `on:` (tests/cplat/test_scale_120_model_on.py); cluster-up warns and skips instead of waiting
  ~10 minutes when KEDA or NACK is forced with Argo CD but its operator file is missing; the CHANGELOG's en dash; design.md notes the
  doctor's `<system>/` prefix and the build-time re-verification.
- Full suite after the fixes: 5833 passed, 12 skipped. The e2e is pending this PR's CI job.
