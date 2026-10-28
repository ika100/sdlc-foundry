# Verification — 119 A message broker resource behind events APIs

**Result:** pass, on condition that this PR's CI e2e job is green before merge and that "To fix" items 1 and 2 (doc-only) are done. Every active criterion is `met`. The in-cluster parts are pending that job. Items 3 to 7 are risks to confirm or small hardening; none of them changes a verdict.
**Commit:** 2bfb40c · **Base:** 9434bf2 (`origin/main`, also the merge base) · **Trace:** 24/24 active criteria named by tests (AC-119.1 to .17 and .19 to .25 appear in `tests/cplat/test_broker_119*.py`; .4, .9 to .14, .16, .19 to .22 also in `tests/e2e/run.sh`). AC-119.18 is withdrawn.

**Test run.** These figures come from the orchestrator. I did not rerun them, because this review is read-only and runs no tests.
- Full suite: 5504 passed, 12 skipped. The skips include the planned-type parametrisations that t12 emptied on purpose (`@pytest.mark.parametrize("typ, spec", [])`).
- `scripts/ci-local.sh --render --site` passed. There was one rerun: `test_cluster_ports.py` is flaky under local load and is not related to this change.
- Pins were re-checked at build (t2). The Helm index was read in full: `nats` 2.15.1 and `nack` 0.35.0 (controller 0.24.0) are still the newest. The image digests of `nats:2.15.2-alpine` and `nats:2.14.9-alpine` have changed since design time, but the tags have not. The renderer pins tags, not digests, so the digests recorded in design.md are stale (see Deviation 3).

**Not run locally:** `tests/e2e/run.sh` (t11). The CI e2e workflow runs it on the PR, so the following are **pending CI, not passed**:
- AC-119.13 and AC-119.19 as a whole;
- the cluster halves of AC-119.4 (refused and allowed removal), .9 and .10 (`/jsz` subjects, 7 days, file storage, explicit ack, 30 s), .11 (Secrets with url, user and a 32-character password), .12 (Permissions Violation refusals), .14 (the stream and its messages stay after the render), .16 (`num_pending`, `num_ack_pending`), .20 (NACK 0.24.0 runs), .21 and .22 (doctor rows);
- the design's open runtime assumptions: NATS as non-root on a read-only root filesystem together with the reloader, both JetStream ack subject forms, and nats-py's `pull_subscribe_bind`/`fetch` working under the narrow rights.

The e2e runs with `WITH_ARGO=0`. The nested Argo CD `Application` becomes a k3s `HelmChart`, and the addon is applied with `kubectl`. So no test exercises Argo CD's sync of a broker: not the nested application, not `Delete=false`/`IgnoreExtraneous`, and not "shown as synced".

Line numbers refer to `templates/gitops-app/scripts/render.py` unless another file is named. `templates/cluster-gitops/scripts/system_render.py` is byte-identical to it, and so is the cluster-gitops `local-cluster.sh` copy (`cmp` at 2bfb40c). Test files: `tests/cplat/test_broker_119.py` (render) and `tests/cplat/test_broker_119_cmds.py` (cmds). Fixtures are in `tests/cplat/broker_fixtures.py`.

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-119.1 | met | render: `test_a_broker_with_all_its_keys_is_accepted_ac_119_1`, `test_an_unknown_broker_key_fails_naming_resource_key_and_allowed_keys_ac_119_1`, the unknown top-level/instance key tests (`versioning`, `persistence`, `backup`, `maxmemoryPolicy`; `version`, `backup`, `bogus`), the external-sizing tests (including the order before the unknown-key check), `test_one_server_per_environment_where_a_running_component_uses_the_broker_ac_119_1`, `test_an_unused_broker_renders_no_objects_ac_119_1`, `test_the_server_gets_the_replicas_and_storage_of_the_environment_ac_119_1`, the remote-path `{component}` tests | `render.py:180-182` (key lists), `:972-1019` (validation), `:1072-1075` (effective values), `:2051-2052` (JetStream file store, `pvc.size`) | JetStream is on (`jetstream.enabled`) with file storage and no memory store. |
| AC-119.2 | met (runtime half not exercised) | render: `test_one_and_three_replicas_are_accepted_ac_119_2`, `test_any_other_replica_count_fails_saying_a_broker_runs_with_1_or_3_replicas_ac_119_2` (bools, 0, 2, 4, strings), the instance and order tests, `test_a_default_broker_runs_one_replica_and_its_streams_one_ac_119_2`, `test_three_replicas_cluster_the_server_and_keep_every_stream_on_three_ac_119_2`, `test_replicas_follow_the_environment_ac_119_2` | `render.py:928-929`, `:2051` (`cluster: {enabled: true, replicas: 3}`), `:2078` (stream `replicas`) | "Stopping one pod loses no acknowledged message" is the NATS R3 guarantee. No test stops a pod of a 3-replica broker, because the laptop e2e runs 1 replica, as the spec allows. |
| AC-119.3 | met | render: `test_the_effective_values_default_to_2_15_one_replica_1gi_and_no_resources_ac_119_3`, the instance→resource→default test, the float/string version test, `test_a_default_broker_uses_the_pinned_server_1gi_and_the_default_requests_and_limits_ac_119_3`, `test_an_unsupported_version_fails_listing_the_supported_ones_ac_119_3`, the storage and resources tests, `test_each_minor_line_runs_its_pinned_release_ac_119_3`; cmds: the two model sizing tests | `render.py:919-934` (`check_broker`), `:185` (`BROKER_DEFAULT_RESOURCES`), `:2041`, `:2057` (`resources or BROKER_DEFAULT_RESOURCES`); `scripts/cplat/model.py:537` | |
| AC-119.4 | met (cluster part pending CI) | cmds: the add tests (entry `{type: broker}`, string `version`, int `replicas`, external with and without `--path`, the next steps, `--pr` branch and title, the errors that change nothing, help texts, store keys mirroring the renderer), the remove tests (bound APIs named, `--dry-run`, only that broker's APIs, implicit binding counted, the bound check before `still used by`, the in-cluster/external/mixed `will_do`, unbound remove renders), `test_the_resource_plugin_docs_describe_the_broker_ac_119_4`; e2e: "resource remove bus is refused…", "…succeeds once nothing is bound" | `scripts/cplat/addon.py:72-94` (checks), `:132-137` (entry), `:101-108` + `:150-153` (refusal), `:161-165` (`will_do`), `:214` (next steps) | The command is right, but its doc `plugins/resource/commands/add.md` is wrong in four places (see "To fix" 1). |
| AC-119.5 | met | render: `test_an_explicit_broker_is_accepted_ac_119_5`, `test_a_broker_that_is_no_resource_fails_naming_the_api_and_the_brokers_ac_119_5`, `test_a_resource_of_another_type_is_no_broker_ac_119_5`, `…_the_choices_read_none_ac_119_5`, `…_list_every_broker_in_resource_order_ac_119_5`, the not-a-string test, the DNS-label test, `test_every_bound_api_gets_its_stream_in_the_chosen_broker_ac_119_5` | `render.py:1108-1131` (`bind_events`), `:1120` | |
| AC-119.6 | met (as clarified 2026-10-28) | render: `test_an_events_api_without_broker_uses_the_only_broker_ac_119_6`, `test_several_brokers_without_a_choice_fail_listing_them_ac_119_6`, `test_an_events_api_with_no_broker_stays_unbound_and_prints_a_note_ac_119_6` (exit 0, the exact note, no variables, no stream), the apis-order, `--check`, no-note and system-order tests | `render.py:1121-1124`, `:2331` (`UNBOUND_NOTE`), `:2334-2338`, `:2486` | The note text names the API and `/resource:add <name> --type broker`, in write mode and with `--check`. This path keeps the 5.0 files byte-identical (AC-119.24); only stdout gains the note. |
| AC-119.7 | met | render: `test_a_provider_and_a_consumer_use_the_broker_without_listing_it_ac_119_7`, `test_the_effective_uses_of_a_service_end_with_the_brokers_of_its_apis_ac_119_7`, `test_listing_the_broker_changes_nothing_for_a_participant_ac_119_7`, `test_a_component_that_lists_a_broker_without_an_api_fails_ac_119_7`, the other-broker, two-brokers-order and does-not-move tests | `render.py:1134-1141` (`effective_uses`), `:1189-1193` (refusal), `:1317` (services carry the effective `uses`) | |
| AC-119.8 | met | render: `test_broker_on_a_non_events_api_fails_naming_the_api_ac_119_8`, `test_the_broker_key_check_comes_before_the_resources_are_read_ac_119_8`, `test_unknown_api_keys_name_the_allowed_ones_per_type_ac_119_8` | `render.py:813-818` | 114's `(allowed: type)` text is unchanged for non-events APIs. |
| AC-119.9 | met (cluster part pending CI) | render: `test_the_stream_is_the_designed_document_in_every_environment_ac_119_9`, `test_a_stream_captures_exactly_its_subjects_and_keeps_messages_for_7_days_ac_119_9`, the one-stream-per-API and unique-name tests; cmds: `test_the_e2e_script_proves_the_stream_and_consumer_settings_ac_119_9`; e2e `/jsz` (`subjects`, `max_age` 604800 s, `file`) | `render.py:2073-2079` | `maxAge: 168h`, retention `limits`, discard `old`. |
| AC-119.10 | met (cluster part pending CI) | render: `test_a_consumer_is_the_designed_document_ac_119_10`, `test_each_consuming_component_has_its_own_consumer_and_a_provider_has_none_ac_119_10`, `test_a_consuming_component_without_an_instance_has_no_consumer_there_ac_119_10`, the pull/deliver-all test, the external-component test; e2e `/jsz` and the Consumer object (`e2e-web explicit 30s`) | `render.py:2080-2087` (`users` are filtered by `env in envs_of(s)` at `:2009`) | Redelivery after 30 s relies on the server. The e2e proves acknowledged messages are not redelivered, but not that an unacknowledged one is redelivered (not required by AC-119.19). |
| AC-119.11 | met (cluster part pending CI) | render: the TYPES contract, the three variables from the component's own Secret, `secretKeyRef` form, `EVENTS_*` and the consumer name, sort order, upper-case `-`→`_`, two APIs with one inbox prefix, non-participants get nothing, prefix rule with two brokers, a Secret per component and environment, generator/admin documents, names stable across sizing, no password in the tree, env clashes (×6), consumer-only clash, Secret and object clashes, libraries and external components get nothing; e2e (url, user, 32 characters, the two passwords differ) | `render.py:221-222`, `:1466` (`<app>-<broker>-<component>-app`), `:1471-1483` (`events_env`), `:2030` (per-component ExternalSecret), `:1093-1131`, `:1179-1210` | |
| AC-119.12 | met (cluster part pending CI) | render: `test_the_server_is_the_designed_document_with_one_user_per_component_ac_119_12`, `test_the_provider_may_publish_on_its_subjects_and_a_consumer_only_through_its_consumer_ac_119_12` (exact allow lists), `test_a_component_outside_an_api_has_no_right_to_its_subjects_ac_119_12` (subscribe only `_INBOX.<c>.>`), the admin, per-environment users, own-Secret, dash and Account tests; e2e: e2e-web refused publishing on `e2e.orders.created` and subscribing to `e2e.orders.>`; e2e-api refused subscribing to `e2e.audit.>` and publishing on `e2e.audit.x`; refused publishes store nothing (`/jsz` counts) | `render.py:2028-2038` | Rights checked by hand: a user can publish only on its own APIs' subjects and on its own consumer's `INFO`/`MSG.NEXT`/`ACK` subjects. It can subscribe only to `_INBOX.<c>.>`. Component names are DNS labels (no dots or underscores), so one inbox prefix cannot cover another, `_nack` cannot clash, and `USER_<C>_PASSWORD` is unique per component. Nobody can request another consumer's messages or publish into another user's inbox. |
| AC-119.13 | met (pending CI) | cmds: `test_the_e2e_script_delivers_one_message_within_30_seconds_ac_119_13`, `…_published_while_the_consumer_was_stopped_ac_119_13`, `…_an_acknowledged_message_is_not_delivered_again_ac_119_13`; e2e steps "e2e-api publishes m1…", "…m2 and m3 while no consumer runs…", "e2e-web fetches m2 and m3…" | — (a runtime criterion) | The probes use the components' rendered variables and the docs example's calls. The 30 s measure includes the start of the second probe pod, so it is stricter than the criterion. |
| AC-119.14 | met (cluster part pending CI) | render: `test_streams_and_consumers_never_get_deleted_by_a_sync_ac_119_14` (`preventDelete`, `Delete=false`, `IgnoreExtraneous`, addon set `prune: false`), the removed-consumer, lost-instance, removed-API and unused-broker note tests, `--check`, no note when unchanged, foreign files kept, names read from the stale files; cmds: the docs and backup-guide tests; e2e: the render prints the three retired names and `/jsz` still shows `e2e-orders` with 3 messages | `render.py:2071-2072`, `:2079`, `:2087`, `:2330`, `:2358-2380`, `:2419-2420`, `:2162-2166` (addon set prune false) | Addon Applications have no `resources-finalizer`, so a removed broker directory orphans its objects; nothing cascades. The e2e's "stream stays" check does not exercise `preventDelete`, because no Stream object is deleted before `/jsz` is read (see "To fix" 5). The DOMAIN-MODEL advice to delete a stream with `kubectl delete` is wrong (see "To fix" 2). |
| AC-119.15 | met | cmds: `test_broker_instances_carry_address_monitoring_users_and_streams_ac_119_15` (the whole broker dict), the consumers-with-an-instance test, the model JSON test (`schema` 2, `broker` only on brokers and events APIs), the three model text tests, implicit `uses` and `used_by`, the only-broker-or-none test, `test_the_renderer_and_the_model_agree_on_broker_instances_ac_119_15`, the four `/api:list` tests | `scripts/cplat/model.py:576-590`, `:626-638`, `:663-676`; `scripts/cplat/modelcmd.py:74-83`; `scripts/cplat/apilist.py:20-28` | |
| AC-119.16 | met (cluster part pending CI) | render: `test_the_server_exposes_the_monitoring_port_on_the_cluster_ip_service_ac_119_16`, `test_nothing_exposes_the_broker_outside_the_cluster_ac_119_16`; e2e: `/jsz` `state.messages`, `num_pending` 2 → 0, `num_ack_pending` 0 | `render.py:2054`, `:2062` (`service.ports.monitor.enabled`) | ADR-065 says spec 120 reads the endpoint "authenticated with the component's own Secret". The endpoint is unauthenticated (design decision 17), so the ADR should be corrected (see "To fix" 6). |
| AC-119.17 | met | render: `test_an_external_instance_renders_no_server_and_one_secret_per_component_ac_119_17`, the same-variables, store-path, path-without-`{component}`, no-addon-no-operator, external-component and no-instance tests, and the three external-note tests plus the note order; cmds: the external model and text tests, the docs test | `render.py:1045-1046` (store key with `{component}`), `:1600` (115's shared Secret skipped), `:1621-1645` (`broker_secrets`), `:2340-2355` (notes) | The platform creates no stream or consumer on an external broker. |
| AC-119.19 | met (pending CI) | cmds: `test_the_e2e_script_declares_a_broker_with_two_events_apis_ac_119_19`, `test_the_e2e_script_header_budgets_the_broker_steps_and_the_job_gets_75_minutes_ac_119_19`, `test_cluster_up_forces_nack_only_when_asked_and_defaults_to_the_operator_file_ac_119_19` | `tests/e2e/run.sh` (broker steps, `WITH_NACK=1`); `.github/workflows/e2e.yml:34` (75 minutes) | Every wait in the broker steps is bounded: deletes use `--timeout=60s` or `120s`, polls are capped, and each failure ends in `nfail`. A finalizer that hangs therefore fails within about 2 minutes and cannot use up the 75-minute job. |
| AC-119.20 | met | render: `test_the_nats_pins_are_exact_in_the_versions_table_ac_119_20`, `test_the_nack_operator_is_pinned_exactly_ac_119_20`, `test_no_floating_tag_is_rendered_ac_119_20`, `test_the_nack_application_pins_the_chart_exactly_ac_119_20`; e2e checks the pins and the running NACK tag | `render.py:238-242`, `:273-274` | Upgrade order and downgrade refusal belong to spec 121 (not built), as in 115 to 118; DOMAIN-MODEL notes that a downgrade is not refused yet. |
| AC-119.21 | met (Argo half untested) | render: `test_the_server_is_an_argo_application_of_the_official_chart_ac_119_21`, `test_the_directory_declares_every_object_and_the_kustomization_lists_them_sorted_ac_119_21`, `test_the_streams_and_consumers_are_ordered_by_sync_waves_after_the_account_ac_119_21`, `test_every_broker_object_carries_the_name_label_ac_119_21`; e2e: the objects become Ready | `render.py:1999-2089` (`broker_files`) | "Argo CD shows them as synced" is not exercised, because the e2e uses no Argo CD (as for 118). |
| AC-119.22 | met (cluster part pending CI) | render: one-application-per-cluster, order after the other operators, the cluster copy knows nack, only-external/unused gets none, one environment is enough; cmds: the doctor rows (ok, missing, differing, not running, statefulset query, none without kubectl or for external), bootstrap CRD, cluster-up, byte-equal script copy, cluster repo `check.py`; e2e doctor rows | `render.py:273-277`; `scripts/cplat/doctor.py:325`, `:332-372`; `templates/gitops-app/scripts/bootstrap.sh:27`; `local-cluster.sh:130-142`, `:443-462`, `:609-612`; `templates/cluster-gitops/scripts/check.py:73` | |
| AC-119.23 | met | render: `test_operators_owner_in_every_broker_environment_installs_nothing_ac_119_23`, `test_nack_stays_while_another_environment_still_needs_it_ac_119_23`, `test_owner_managed_environments_render_the_same_broker_ac_119_23`; cmds: `test_doctor_checks_owner_managed_environments_too_ac_119_23`, the no-row test, the external cluster-check test | `OPERATOR_OF_TYPE` (`render.py:277`) through the generic `operator_files`; `doctor.py:325` | |
| AC-119.24 | met | render: `test_a_5x_system_without_a_broker_renders_byte_identically_to_before_ac_119_24` ×6 (digests committed in the red commit fe5cb58, before any renderer change, and unchanged since), `test_a_system_with_events_apis_and_no_broker_equals_the_5_0_render_ac_119_24` ×2 (compared with the 5.0 renderer), `test_an_unused_broker_changes_nothing_in_the_tree_ac_119_24`, `test_a_broker_changes_only_the_files_it_owns_ac_119_24` | `render.py:2169-2170` (`retry` only with a broker), `:1475-1476` (an unbound API gives nothing), `:1600` | `docs/specs/114-*` is untouched. |
| AC-119.25 | met | cmds: `test_the_domain_model_documents_the_broker_and_its_environment_contract_ac_119_25`, `test_the_domain_model_has_exactly_the_one_python_example_ac_119_25` (equal to design.md's connecting block), `test_no_template_ships_publisher_or_subscriber_code_ac_119_25`, `test_the_user_journey_and_the_site_describe_the_broker_ac_119_25` | `docs/DOMAIN-MODEL.md:176-207` | |

## Non-goals

- No broker other than NATS: `NATS_*` only, and an external broker is NATS. ✔
- No publisher or subscriber code in the templates (the test scans `templates/`). ✔
- No event schemas. ✔
- No request/reply, plain subjects, KV or object store: users get no rights beyond their API subjects, their consumer and their inbox. ✔
- One provider per API (114's check is unchanged); no per-API retention or delivery keys (`apis.<a>` takes only `type` and `broker`). ✔
- Backups: `backup_files` is unchanged. Broker objects carry `app.kubernetes.io/name: <name>` and the chart's `app.kubernetes.io/instance: <system>-<name>`. Neither matches 117's `NotIn` lists (`[to, *caches]`, `[<system>-<to>]`, `render.py:1930-1931`), because resource names are unique. So broker volumes stay in the environment backup, and 117's cache exclusions are unchanged. `envrestore` finds the StatefulSet's tracking application through `status.resources` (`scripts/cplat/envrestore.py:66-77`), so the nested `…-nats` application is paused too. No render test asserts that the Schedule still selects a broker (optional, see "To fix" 7). ✔
- No consumer scaling (spec 120) and no upgrade procedure (spec 121). ✔
- Spec 114 is not amended. ✔
- No shared broker between systems, no NATS accounts beyond NACK's `Account` object, no leaf nodes. ✔
- No off-the-shelf components. ✔

## Approved test changes

1. **138fcfe (t12).** Every changed line in the 115 to 118 test files carries `# spec 119`:
   - `PLANNED_TYPES == {}`;
   - the planned-type parametrisations are emptied, and pytest skips them;
   - `nack` is appended to the operators list;
   - the `--version … database or broker only` text;
   - the `--type` help;
   - `resource` 1.5.0;
   - a broker that used to be refused now renders (and writes no addon path while it is unused).

   These are exactly the changes plan t12 lists.
2. **a352438 with efbf54d.** The example test now reads design.md's python block that contains `nats.connect`, instead of the first block, which is the `TYPES` snippet. efbf54d put the nats-py example into DOMAIN-MODEL, where the TYPES snippet had been copied by mistake. The test is not weaker: it still compares the docs example with the design's exactly and requires exactly one Python block in DOMAIN-MODEL.
3. **36668bd.** In the no-password regex, `\s*` crossed into the next key. It now matches values on the key's own line, which is still the intended assertion.
4. **2be3ea0, new `tests/cplat/test_cluster_check_cache.py`.** It covers the spec 118 gap that `check.py` now closes: an in-cluster cache needs `external-secrets`. This is an addition, not a change to an existing test.

`git log origin/main..HEAD -- tests/` shows only these commits, the red commit fe5cb58 and the e2e (35ed01f).

## Deviations from the plan

1. **`templates/cluster-gitops/scripts/check.py` also asks for `external-secrets` for an in-cluster cache** (spec 118's gap) and has its own test file. The file is t8's, but the cache rule is outside 119's scope. Acceptable: it is a correct fix, and it is tested.
2. **NATS_PASSWORD validation order (96dd2ac).** `validate_env_vars` skips `NATS_PASSWORD` (`render.py:633`), and `validate_uses` checks it after the broker clash (`:1210`), so a clash names the broker. The literal-secret refusal still happens without a broker, because services always have at least one `_eff` environment (`validate_instances` defaults to dev). Two small text effects remain:
   - an instance-level `NATS_PASSWORD` now fails as `components.<c>: env NATS_PASSWORD looks like a secret…` instead of `components.<c>.instances.<env>: …`;
   - a component-level literal that an instance overrides with an empty value is no longer refused.

   Acceptable. The value still never reaches git silently in the normal case, but this is a 5.0 message text that changed without being listed in design.md.
3. **design.md "Verified on 2026-10-27, re-verify at build"** was not updated. The orchestrator re-verified (full Helm index; tags unchanged, digests changed), but the design still records the old digests and says that only the first 100,000 characters of the index were read. Acceptable; adding a "Re-verified at build" line, as 117 did, would be better.
4. **Design Risks marked "Documented" are not in the user docs:**
   - NACK's legacy mode recreates a stream deleted by hand only when its object changes or NACK restarts;
   - a live file-system backup may catch a torn JetStream block.

   DOMAIN-MODEL covers the restart on a new user, the 1→3 switch, `storage` and downgrades. Not required by any criterion.
5. **The kubeconform risk** (design: "if the catalog lags NACK v0.24.0, the build adds the three kinds to the skip list") was not checked. The gitops-app `validate` script runs `kubeconform -strict` on `addons/*/*/[cs]*.yaml`, which includes `stream-*` and `consumer-*`. Neither the e2e nor `ci-local.sh` runs it. See "To fix" 4.
6. **Task status.** The plan's front matter has no `done` flags. t1 to t12 each have a commit: 1ea6fac, 4ed5499, 96dd2ac (+2bfb40c docstring), 29e977f, bc3268a, 13cd6f0, 088f0e9, 2be3ea0, 867aaaf, 26ef853 (+efbf54d), 35ed01f and 138fcfe.
7. **Files outside every task's `files`:** the planning artefacts (ADR-065, `docs/adr/README.md`, `docs/backlog.md`, spec, design, plan), `tests/cplat/broker_fixtures.py` and the two `test_broker_119*.py` files from the red commit, and `tests/cplat/test_cluster_check_cache.py`. Acceptable.

## Design decisions taken by default (all 26 checked)

1. No broker means an unbound API and a note: `render.py:1121-1124`, `:2331`; spec changelog line added. ✔
2. Nested Argo `Application` of the official chart: `:2043-2065`. ✔
3. NACK legacy mode, no values, one `Account` per instance: `:273-274` (no `values`), `:2066-2070`. ✔
4. `_INBOX.<c>` and `NATS_INBOX_PREFIX`: `:2037`, `:1483`. ✔
5. Passwords as container variables: `:2036-2038` with `<< $USER_<C>_PASSWORD >>`. ✔ (see "To fix" 3 on restarts)
6. `_nack` with Secret `<n>-nack`: `:2024-2027`. ✔
7. `version` is a minor-line string, and a float is read as its text: `:921-924`. ✔
8. Requests 100m CPU and 256Mi, memory limit 512Mi: `:185`. ✔
9. Pull consumers, deliver `all`, `maxDeliver: -1`, no consumer `replicas`: `:2086-2087`. ✔
10. Streams: file storage, `limits`, discard `old`, `168h`, replicas = broker replicas: `:2078-2079`. ✔
11. `preventDelete`, `Delete=false`, `IgnoreExtraneous`; notes from stale files: `:2071-2072`, `:2358`. ✔
12. Store key `{system}-{env}-{resource}-{component}`; keys `url`, `user`, `password`: `:1045`, `:1643`. ✔
13. External components count on the broker side (user, Secret, consumer), get no variables and get no ExternalSecret on an external broker: `:2009`, `:1632`. ✔
14. Broker variables follow the declared resources' variables, whatever `uses` says: `:1134-1141`. ✔
15. `EVENTS_*` and `NATS_INBOX_PREFIX` are literals in the sorted block: `:1496` (deployment `env_vars`). ✔
16. Hardened pods, `natsBox` off: `:2039-2063`. ✔
17. Monitoring 8222 on the ClusterIP Service, unauthenticated: `:2054`, `:2062`. ✔ (the ADR text contradicts it, see "To fix" 6)
18. Broker data in the environment backup, `backup_files` unchanged. ✔
19. `compose.py` unchanged (not in the diff). ✔
20. A bound API needs a DNS-label name: `:1125-1127`. ✔
21. Both ack forms: `:2035`. ✔
22. Reloader on: `:2058`. ✔ (its effect may be cancelled by the chart's config checksum, see "To fix" 3)
23. The addon set retries with a broker: `:2169-2170`. ✔
24. e2e second API `audit` and a nats-py 2.16.0 probe: `run.sh`. ✔
25. The e2e unbinds and deletes the broker after its steps. ✔
26. `resource` 1.5.0 and `api` 1.1.0 in both `plugin.json` and `marketplace.json`. ✔

## Contract

Matches `design.md`:
- the schema and every render error text and its order;
- the renderer API (`cfg["resources"][b]["envs"]`, `cfg["events"]`, effective `uses`);
- the generator, user and admin ExternalSecrets, `server.yaml`, `account.yaml`, `stream-*`, `consumer-*.*` and the kustomization (whole-document equality in the tests);
- the per-component Secret and variables;
- the external ExternalSecret;
- the three note forms and their order;
- `stale_paths`' broker pattern;
- the versions table;
- the `cplat resource` texts, the model and JSON keys, `model show`, `/api:list`, the doctor rows, `check.py`, `bootstrap.sh` and `local-cluster.sh`;
- the e2e outline.

`addon.TYPE_KEYS["broker"]` matches `TYPES["broker"]["keys"]`.

## To fix or confirm before the PR

1. **`plugins/resource/commands/add.md`, the Broker bullet (line 21), contradicts `cplat` and the renderer.** An agent following it will pass flags that fail, or tell users wrong facts:
   - "`--version V` is the NATS version (default `2.14.9`)". The versions are `2.14` or `2.15`, and the default is `2.15`. `--version 2.14.9` fails with `version '2.14.9' is not a supported broker version (2.14, 2.15)` (`addon.py:87-88`).
   - "`--storage S` the JetStream volume (default `10Gi`)". `--storage` is bucket-only: `cplat resource add bus --type broker --storage 5Gi` exits 1 with `--storage and --versioning apply to --type bucket only` (`addon.py:76-77`). The broker default is `1Gi`, set in system.yaml.
   - "With `--external` the store holds the keys `url`, `user`, `password`, `inboxPrefix`". There is no `inboxPrefix` key; the keys are `url`, `user`, `password` (`TYPES["broker"]`, `addon.py:31`).
   - "`cplat` prints the streams and consumers the owner must create". The render prints them; `cplat` only says to look at the render output.

   Two smaller errors: the same bullet says the `EVENTS_*` variables come "from its own Secret" (they are literals), and step 3 says components opt in to a broker with `--uses` (they do not).

   Doc-only. `test_the_resource_plugin_docs_describe_the_broker_ac_119_4` only checks for needles, so it does not catch this. The CHANGELOG entry repeats the "from their own Secret" wording for `NATS_INBOX_PREFIX` and `EVENTS_*`.
2. **`docs/DOMAIN-MODEL.md:205` (Removal) says to delete a stream or consumer with `kubectl delete stream.jetstream.nats.io` / `consumer.jetstream.nats.io`.** With `preventDelete: true` (`render.py:2079`, `:2087`), deleting the Kubernetes object removes only the declaration: NACK leaves the stream and its messages on the server. That is the whole point of AC-119.14. A user following the doc will believe the stream is gone. Say that `nats stream rm` / `nats consumer rm` is the only way to delete one, and that deleting the object only stops NACK from managing it. Doc-only.
3. **Confirm whether a rights-only change restarts the broker.** ADR-065 (Consequences) and design Risk 2 say rights-only changes are hot-reloaded by the reloader. As far as I remember, the official `nats` chart 1.x/2.x sets `podTemplate.configChecksumAnnotation: true` by default, which puts a hash of the ConfigMap on the pod template. I could not read the chart offline, so this is unverified. If that is right, any change to `config.merge.authorization` rolls the StatefulSet. That includes a component starting to consume or provide another API, or an API being added or removed. With 1 replica, every such render then means a short broker outage, not just "adding a component". No data is lost: the volume and the streams stay, and no criterion is broken.
   - Action: read `values.yaml` at the `nats-2.15.1` tag.
   - If the flag exists, either set `podTemplate: {configChecksumAnnotation: false}` in `server.yaml`, so that the reloader handles config changes while new users still roll through their new variable, or correct ADR-065, design.md and the DOMAIN-MODEL "Limits" sentence to say that any change of the broker's users or rights restarts its pods.
   - Separately, the DOMAIN-MODEL "Limits" sentence already tells users that a new component user restarts the broker. That restart is the accepted cost of decision 5.
4. **Confirm `devbox run validate` on a generated repo with a broker.** `kubeconform -strict` against the Datree catalog for `jetstream.nats.io/v1beta2` `Stream`/`Consumer` must accept `preventDelete`, `account`, `maxDeliver` and the others. A stale catalog schema would fail every gitops-app repo's quality job once a broker is added. A missing schema is fine (`-ignore-missing-schemas`). Neither unit tests, `ci-local.sh` nor the e2e run this check. If it fails, add the kinds to `SERVICE_CRD_SKIP` as the design's Risk says, and note it in the CHANGELOG.
5. **Optional, a stronger e2e for AC-119.14.** In the removal step, the "stream stays" check reads `/jsz` while the Stream object still exists (`kubectl` apply, no prune), so it does not prove `preventDelete`. Read `/jsz` once more after `kc delete streams.jetstream.nats.io/e2e-orders` and before the HelmChart is deleted, and expect `S.e2e-orders.messages=3`. That proves NACK keeps the stream when its object goes, which is the path a human or Argo deletion takes. It costs one `jsz_wait`.
6. **ADR-065, Consequences:** it says spec 120 reads the monitoring endpoint "authenticated with the component's own Secret". The endpoint is unauthenticated (design decision 17, DOMAIN-MODEL, `render.py:2054`). Correct the ADR.
7. **Optional hardening:**
   - `doctor.check_brokers` (`doctor.py:355`) does `images[ri.sizing.get("version", "2.15")]` on the lenient model. A system.yaml with an unsupported broker version, such as `"2.16"` or a YAML `2.10`, raises `KeyError` and crashes `/platform:doctor` whenever `kubectl` is on PATH. Use `.get()` and emit a WARN row. Also, `_nats_expected()` loads `render.py` on every doctor run with `kubectl`, even without a broker; it could load lazily.
   - A render test that the spec 117 Schedule still selects a broker's objects would lock in design decision 18 (the `NotIn` lists do not name it).

Also add a "Re-verified at build" line to design.md (Deviation 3).

RESULT: pass, on condition that the PR's CI e2e job, which runs `tests/e2e/run.sh` for AC-119.13 and .19 and the cluster halves of .4, .9 to .12, .14, .16 and .20 to .22, is green before merge, and that "To fix" items 1 and 2 (doc-only) are done. Items 3 and 4 are risks to confirm; neither breaks a criterion.

## After review (orchestrator)

- Confirmed: the nats 2.15.1 chart's `podTemplate.configChecksumAnnotation` defaults to `false` and server.yaml does not set it, so
  rights changes hot-reload; adding or removing a component restarts the pods once (decision 5). ADR-065 now says both.
- Confirmed: the rendered `stream-*` and `consumer-*` documents validate against the datreeio catalog's NACK schemas (strict, no
  additional properties); `account.yaml` is outside the validate glob (the catalog's Account schema has no `user`).
- Fixed (commit after this report): add.md's broker facts, the CHANGELOG's EVENTS_* wording, DOMAIN-MODEL's deletion advice and two
  documented limits, ADR-065's monitoring text, doctor's KeyError on an unsupported version (new test
  `tests/cplat/test_doctor_broker_version.py`), and an e2e check that the stream keeps its messages after its Stream object is deleted.
- Full suite after the fixes: 5505 passed, 12 skipped. The e2e is pending this PR's CI job.
