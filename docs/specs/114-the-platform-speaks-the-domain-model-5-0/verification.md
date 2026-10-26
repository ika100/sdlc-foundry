# Verification — 114 The platform speaks the domain model (5.0)

**Result:** pass
**Commit:** c13933c · **Base:** 53392ed · **Trace:** 67/67 criteria named by tests (`cplat spec trace 114`, nothing missing)

Test run (from QA): `tests/cplat` 3289 passed, 7 skipped (Kyverno CLI not installed); `scripts/ci-local.sh` green; site `npm test` and `npm run build` green. The end-to-end cluster test (`tests/e2e/run.sh`) was not run locally (needs docker/k3d); CI runs it.

Abbreviations: `R` = `tests/cplat/test_system_render_114.py`, `M` = `tests/cplat/test_system_model_114.py`, `N` = `tests/cplat/test_nouns_114.py`, `C` = `tests/cplat/test_commands_114.py`, `G` = `tests/cplat/test_migrate_114.py`, `P` = `tests/cplat/test_plugins_114.py`; `render.py` = `templates/gitops-app/scripts/render.py`; other code paths are under `scripts/cplat/` unless they say otherwise. "Same as 4.x" tests render the same system with the frozen 4.7 renderer (`scripts/cplat/assets/render_v4.py`, a byte-for-byte copy of `templates/gitops-app/scripts/render.py` at 53392ed; I checked this with `diff`) and compare every generated file.

## system.yaml and rendering

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-114.1 | met | R `test_system_yaml_alone_renders_the_4x_paths_ac_114_1`, `test_a_new_gitops_app_has_system_yaml_and_no_old_files_ac_114_1` | `render.py:563` (`load_system`), `templates/gitops-app/applications/{{ app_name }}/system.yaml.jinja` (app.yaml/services.yaml jinja deleted) | the copier-rendered repo renders and passes `--check` |
| AC-114.2 | met | R `test_an_unknown_top_level_key_fails_…_ac_114_2`, `test_4x_keys_are_unknown_…`, `test_a_system_that_differs_from_the_directory_…`, `test_a_missing_system_fails_ac_114_2` | `render.py:107` (TOP_KEYS), `render.py:581-587` | |
| AC-114.3 | met | R `test_environments_must_be_dev_staging_prod_in_order_ac_114_3` (missing, extra, reordered, empty), `test_a_missing_environments_key_fails_ac_114_3` | `render.py:269` | |
| AC-114.4 | met | R `test_an_unknown_environment_key_fails_…_ac_114_4`, `test_4x_names_are_not_environment_keys_ac_114_4` | `render.py:108`, `render.py:278` | |
| AC-114.5 | met | R `test_host_placeholders_are_filled_in_and_the_httproute_is_the_4x_one_ac_114_5` (byte-identical to 4.x), `test_an_environment_without_host_exposes_nothing_…`, `test_4x_placeholders_in_host_fail_…`, `test_an_unknown_host_placeholder_fails_…` | `render.py:189-195`, `render.py:280` | |
| AC-114.6 | met | R `test_the_render_ignores_url_ac_114_6`; M `test_the_url_template_fills_host_component_system_and_env_ac_114_6`, `test_without_url_the_host_gives_the_4x_url_ac_114_6`, `test_dev_url_of_the_smoke_run_follows_system_yaml_ac_114_6`; N `test_the_url_of_any_environment_comes_from_the_linked_system_ac_114_6` | `model.py:252` (URL rule), `smoke.py:333` (`dev_url`, used by the ship deploy step and `instance verify`) | |
| AC-114.7 | met | R `test_policies_audit_enforce_off_equal_the_4x_modes_ac_114_7` (byte-identical), `test_an_absent_policy_is_audit_…_enforce_in_prod_…`, `test_an_unquoted_off_is_off_in_both_yaml_spellings_…`, `test_any_other_policy_fails_naming_the_three_values_…` | `render.py:124`, `render.py:284-290` | YAML 1.1 `off` handled as the design says |
| AC-114.8 | met | R `test_staging_accepts_…`, `test_staging_rejects_other_…`, `test_prod_only_accepts_manual_…`, `test_dev_accepts_no_promote_…`, `test_an_instance_promote_follows_the_same_rules_…`; N `test_staging_promotes_after_a_green_dev_smoke_per_the_promote_keys_ac_114_8` (env and instance value, instance wins) | `render.py:199-205`; `staging.py:150-153`; `model.py:245` | |
| AC-114.9 | met | R `test_observability_gives_the_collector_and_otel_variables_as_in_4x_ac_114_9` (byte-identical), `test_an_environment_without_observability_gets_neither_…`, `test_observability_is_validated_with_the_4x_checks_…` | `render.py:247`, `render.py:293`, `render.py:665-674`, `render.py:1026` | |
| AC-114.10 | met | N `test_each_environment_with_alerts_is_a_source_with_its_own_rules_and_endpoints_ac_114_10`, `test_collect_queries_each_source_with_its_own_rules_only_…`, `test_no_environment_with_observability_skips_the_app_…` | `alertsources.py:69` (EnvSource), `alertsources.py:218` (`load_app`), `alertsources.py:346` (`collect`) | issue filing (`alerts.poll`) is unchanged and covered by the ported 092 tests |
| AC-114.12 | met | R `test_all_4x_service_keys_plus_the_new_ones_render_as_in_4x_ac_114_12` (byte-identical), `test_4x_per_environment_keys_fail_naming_instances_…`, `test_an_unknown_component_key_fails_…`, `test_an_external_component_keeps_its_package_rule_…` | `render.py:114-117`, `render.py:432-470` | `metrics` kept as a key (design decision, needed for byte identity) |
| AC-114.13 | met | R `test_a_component_runs_exactly_where_it_has_an_instance_…`, `test_no_instances_means_dev_only_…`, `test_an_instance_key_that_is_not_an_environment_fails_…`, `test_instances_override_replicas_resources_and_merge_env_…`, `test_an_unknown_instance_key_fails_…` | `render.py:364-414` (`validate_instances`; env merge at `render.py:396`) | |
| AC-114.14 | met | R `test_a_library_renders_no_manifests_ac_114_14`, `test_a_library_with_instances_image_port_or_expose_fails_…` | `render.py:450-457`, `render.py:600` (libraries left out of `services`) | |
| AC-114.15 | met | R `test_uses_postgres_injects_the_operator_secret_as_in_4x_…` (byte-identical), `test_using_a_library_changes_no_manifest_…`, `test_uses_of_an_unknown_name_fails_listing_resources_and_libraries_…`, `test_uses_postgres_without_the_resource_fails_…` | `render.py:547-559`, `render.py:126-129` | |
| AC-114.16 | met | R `test_apis_provides_and_consumes_change_no_manifest_…`, `test_every_api_type_is_accepted_…`, `test_an_api_type_is_required_and_checked_…`, `test_providing_…`/`test_consuming_an_undeclared_api_fails_…`, `test_an_api_without_a_provider_fails_…`, `test_an_api_with_two_providers_fails_naming_them_…` | `render.py:494-508` | |
| AC-114.17 | met | R `test_secrets_render_as_in_4x_and_the_default_path_reads_the_4x_store_key_ac_114_17` (byte-identical), `test_4x_placeholders_in_a_secret_path_fail_…` | `render.py` secret checks (`validate_secrets`, `render.py:298`) | |
| AC-114.18 | met | R `test_an_instance_secret_replaces_the_declared_fields_in_that_environment_only_…`, `test_an_instance_secret_the_component_does_not_declare_fails_…` | `render.py:402-414` | |
| AC-114.19 | met | R `test_the_postgres_resource_renders_the_4x_cluster_…` (byte-identical), `test_the_resource_defaults_are_the_4x_defaults_…`, `test_the_resource_is_rendered_only_where_a_running_component_uses_it_…`, `test_another_resource_name_or_type_fails_…`, `test_a_resource_named_observability_points_to_the_environment_…`, `test_an_unknown_resource_key_fails_…` | `render.py:515-545` | approved test change (policy `off` on every env in the defaults test) — see Deviations |
| AC-114.20 | met | R `test_a_version_in_system_yaml_fails_…` (image tag, `tag`, `version`), `test_a_re_render_keeps_every_pinned_tag_…`, `test_a_dev_pin_changes_only_the_overlay_never_system_yaml_…` | `render.py:439-443`; `templates/gitops-app/scripts/pin.py` | |
| AC-114.21 | met | R `test_cluster_names_and_labels_are_the_4x_ones_ac_114_21` | `render.py:643`, `render.py:729`, `render.py:847`, `render.py:127-128` | approved test change (applicationset subset); the full 4.x/5.0 file equality in `same_as_4x` still covers every set |
| AC-114.22 | met | R `test_a_directory_with_old_files_writes_nothing_and_says_so_…` (6 combinations, with and without `--check`), `test_one_unmigrated_directory_stops_the_render_of_the_others_…` | `render.py:105`, `render.py:1086` | |
| AC-114.23 | met | N `test_unmigrated_repos_exit_1_with_the_one_message_ac_114_23` (status, api list, secret list, promote, component add/set/remove, resource add/remove, model show), `test_the_dev_url_in_an_unmigrated_gitops_app_fails_…`, `test_an_unmigrated_app_is_a_source_error_…`; M `test_load_dir_refuses_old_files_…`, `test_model_show_in_an_unmigrated_repo_…`, `test_load_remote_reads_system_yaml_and_refuses_services_yaml_…`, `test_build_takes_a_system_document_leniently_…` | `model.py:29`, `model.py:39`, `model.py:588`, `model.py:607`; `staging.py:125`, `smoke.py:343` (all read through `load_remote`) | ship deploy and staging promotion reach the old files only through `smoke.dev_url`/`staging._find`, both via `model.load_remote` |
| AC-114.57 | met | R `test_owner_is_a_required_non_empty_string_ac_114_57` (missing, empty, blank, number, list, mapping) | `render.py:588-589` | |
| AC-114.58 | met | R `test_the_valid_type_lang_pairs_render_…`, `test_another_pair_fails_listing_the_valid_ones_…`, `test_type_and_lang_are_required_…`, `test_a_shape_key_fails_…`; M `test_type_lang_pairs_come_from_the_registry_plus_service_unknown_…`, `test_a_4x_shape_maps_…`, `test_type_and_lang_map_back_…`, `test_the_renderers_pairs_equal_the_models_…`; C `test_an_invalid_pair_fails_…_ac_114_33` (`unknown` refused), `test_bad_system_manifests_fail_…_ac_114_34`, `test_system_new_dry_run_plans_system_yaml_and_the_pairs_ac_114_58` | `render.py:110-112`, `render.py:430-448`; `model.py:61`, `model.py:70`, `model.py:78`; `newsvc.py:49`; `newapp.py:72` | |
| AC-114.69 | met | M `test_the_system_environments_and_their_rules_come_from_system_yaml_…`, `test_components_apis_libraries_and_owner_…`, `test_instances_carry_tag_replicas_namespace_argo_url_and_promotion_…`, `test_instance_secrets_apply_the_instances_overrides_…`, `test_resource_instances_carry_the_sizing_with_replicas_…`, `test_the_json_is_schema_2_with_the_new_nouns_…`, `test_the_text_shows_owner_policy_promote_apis_and_replicas_…`, `test_schema_2_equals_4x_for_the_same_system_after_the_design_mapping_…` (runs the real 4.x `cplat` from commit 96dbdcf), `test_the_ac_113_13_guard_still_holds_for_the_5_0_modules_…` | `model.py:28`, `model.py:493` (`build`), `model.py:435` (overrides), `modelcmd.py` | 96dbdcf is an ancestor of the base, so the 4.x comparison runs and does not skip |
| AC-114.70 | met | R `test_the_renderer_and_the_model_agree_ac_114_70` (names the first difference); M `test_the_model_lists_the_instances_the_instance_keys_declare_…` | `render.py:103` (ENVS), `model.py:493` | |

## Commands grouped by noun

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-114.26 | met | N `test_a_4x_name_exits_2_with_one_line_naming_the_new_form_ac_114_26` (all 17 names, module never called), `test_promote_is_instance_promote_in_the_spec_example_…` | `cplat.py:71-77`, `cplat.py:104-106` | |
| AC-114.27 | met | P `test_the_tombstone_table_has_the_27_commands_of_4_7_…`, `test_every_old_command_is_a_tombstone_that_runs_nothing_…` (Read/Glob only, no `$ARGUMENTS`, no Bash, both one-line answers), `test_tombstones_check_is_clean_…` | `scripts/tombstones.py:19`; `scripts/ci-local.sh` (`tombstones.py check`); `plugins/{svc,shared,app,gitops}/commands/*.md` | runs no script by construction (allowed-tools `Read, Glob`) |
| AC-114.28 | met | C `test_promote_to_staging_adds_the_instance_and_pins_the_source_image_…`, `test_promote_to_prod_pins_the_release_whose_digest_staging_verified_…`, `test_promote_all_takes_every_component_with_a_source_instance_…`, `test_promote_pr_is_one_pull_request_…`; P `test_usage_lines_name_their_arguments_ac_114_28`, `test_instance_promote_keeps_the_production_gate_…` | `promote.py:121-169` | the spec-106 digest path itself is covered by the ported `test_promote_digest.py` |
| AC-114.29 | met | C `test_promote_refuses_and_changes_nothing_ac_114_29` (no `--to`, positional `<from> <to>`, `--to dev`, unknown env, missing source instance, library), `test_a_dry_run_refuses_the_same_way_…` | `promote.py:125`, `promote.py:128`, `promote.py:130`, `promote.py:169` | |
| AC-114.30 | met | N `test_instance_secret_set_writes_the_instances_store_key_…` (prod override path), `test_instance_secret_list_shows_each_instance_with_the_new_hint_…`, `test_instance_secret_set_refuses_undeclared_and_generated_secrets_…`; P `test_instance_secret_set_and_list_…` | `secret.py:48-92` (`secret.py:86` refusal) | |
| AC-114.31 | met | N `test_instance_verify_defaults_to_dev_and_resolves_any_environment_from_the_system_…`, `test_noun_verb_runs_the_module_of_the_4x_command_ac_114_60[instance verify]`; P `test_instance_verify_runs_the_components_smoke_tests_…` | `cplat.py:59` (`instance verify` → `smoke run`), `smoke.py:413-415` | digest record unchanged in `smoke.run_smoke` |
| AC-114.32 | met | N `test_system_status_is_a_component_by_environment_table_…`, `test_system_status_json_…`, `test_system_status_without_components_points_to_component_add_…` | `status.py:84-105`, `status.py:132-137` | |
| AC-114.33 | met | C `test_component_new_maps_the_pair_to_its_template_…` (default service/python and partial flags), `test_an_invalid_pair_fails_listing_the_valid_ones_…`, `test_the_4x_flags_fail_naming_their_replacement_…`, `test_component_new_system_writes_the_link_file_…` (shape id kept in `.copier-answers.yml`) | `newsvc.py:35-98` | `argparse` prog still `cplat new-service`, see Deviations |
| AC-114.34 | met | C `test_system_new_creates_the_gitops_app_with_system_yaml_and_every_component_…`, `test_bad_system_manifests_fail_before_anything_happens_…` | `newapp.py:22-72` | |
| AC-114.35 | met | C `test_component_add_writes_a_type_lang_entry_with_a_dev_instance_and_renders_…` (comments kept), `test_component_add_takes_type_and_lang_…`, `test_component_add_from_k8s_seeds_the_entry_…`, `test_component_set_edits_env_expose_uses_and_replicas_…`, `test_component_set_instance_replicas_writes_the_instances_key_…`, `test_component_set_instance_errors_change_nothing_…`, `test_component_remove_…`, `test_component_add_pr_uses_the_component_branch_and_title_…`, `test_the_4x_compose_flags_are_gone_…` | `compose.py:35`, `compose.py:111-122`, `compose.py:175-218` | |
| AC-114.36 | met | C `test_resource_add_postgres_declares_the_default_database_…`, `test_resource_add_postgres_takes_a_version_…`, `test_resource_add_observability_changes_nothing_…`, `test_resource_add_another_name_is_refused_…`, `test_resource_remove_refuses_while_used_then_removes_…`, `test_resource_add_pr_uses_the_resource_branch_…`, `test_there_is_no_resource_list_…` | `addon.py:15`, `addon.py:36`, `addon.py:39` | approved test change (commits between steps) — see Deviations |
| AC-114.38 | met | N `test_the_run_modules_never_print_a_4x_command_ac_114_38` (ship, appship*, budget), `test_the_stop_hooks_run_the_5_0_gates_…` | `plugins/shared/hooks/hooks.json` (Stop: `component ship gate`, `system ship gate`); `ship.py` (10× `/component:ship`), `appship.py` (5× `/system:ship`); `staging_deploy.py:79,256` | approved test change (forbid `app-ship gate` only) |
| AC-114.39 | met | N `test_doctor_warns_while_the_old_plugins_are_enabled_…`, `test_doctor_warns_while_the_old_files_exist_…`, `test_doctor_is_quiet_on_a_migrated_repo_…` | `doctor.py:163`, `doctor.py:166` | |
| AC-114.59 | met | P `test_exactly_the_30_working_commands_exist_ac_114_59`, `test_the_marketplace_lists_the_noun_plugins_…`, `test_every_working_command_has_a_usage_line_and_runs_the_5_0_form_…` | `plugins/{system,component,api,resource,instance,issue,platform}/commands/`; `.claude-plugin/marketplace.json` | no `plugins/api/commands/check.md` |
| AC-114.60 | met | N `test_noun_verb_runs_the_module_of_the_4x_command_ac_114_60` (22 routes), `test_plumbing_commands_keep_their_names_…`, `test_a_noun_without_a_known_verb_prints_its_verbs_and_exits_2_…`, `test_help_lists_every_noun_line_…` | `cplat.py:54-67`, `cplat.py:110-119` | |
| AC-114.61 | met | N `test_api_list_prints_type_provider_and_consumers_…`, `test_api_list_json_…`, `test_api_list_without_apis_says_so_and_exits_0_…`, `test_api_list_in_an_unmigrated_repo_exits_1_…`; P `test_api_list_command_…` | `apilist.py:12-27` | |
| AC-114.62 | met | P `test_component_fix_is_the_quick_task_pipeline_for_changes_and_bugs_ac_114_62` | `plugins/component/commands/fix.md` (coder → quality → tester, stops on a criterion change); no `fix-bug.md`/`quick-task.md` working command | prompt-level criterion; the test checks the prompt text |
| AC-114.63 | met | P `test_component_check_is_read_only_quality_and_security_ac_114_63` | `plugins/component/commands/check.md` | prompt-level criterion |
| AC-114.64 | met | P `test_component_spec_dispatches_on_its_first_argument_…`, `test_system_spec_dispatches_on_its_first_argument_…` | `plugins/component/commands/spec.md`, `plugins/system/commands/spec.md` (dispatch table, section 0) | prompt-level criterion |
| AC-114.65 | met | P `test_dropped_or_merged_commands_name_their_replacement_ac_114_65` (all eight cases) | `scripts/tombstones.py:19` | |

## Migration

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-114.40 | met | G `test_render_v4_is_the_4_7_renderer_verbatim_…`, `test_migrate_writes_system_yaml_and_deletes_the_old_files_…`, `test_the_rendered_tree_is_byte_identical_to_what_4_7_rendered_…` (>50 files, a real 4.x repo built from 96dbdcf), `test_the_report_proves_the_identity_…`, `test_migrate_commits_the_migration_with_the_update_…` | `update.py:443-466` (`reference_render`, `apply_systems`), `update.py:583-631` | |
| AC-114.41 | met | G `test_the_47_files_convert_to_the_system_document_…` (equals FULL5), `test_hosts_urls_and_placeholders_…`, `test_policies_become_a_lowercase_policy_…`, `test_promotion_becomes_the_staging_promote_key_…`, `test_observability_becomes_the_same_mapping_…`, `test_postgres_becomes_a_database_resource_…`, `test_a_service_becomes_a_component_…`, `test_a_scalar_replicas_value_stays_…`, `test_secret_path_placeholders_are_converted_…` | `migrate5.py:25`, `migrate5.py:36-166`, `migrate5.py:207` | approved test change (one policy expectation corrected to the 4.x default) |
| AC-114.42 | met | G `test_a_key_without_a_5_0_place_is_a_problem_naming_it_…` (10 cases), `test_a_missing_owner_is_a_problem_…`, `test_unconvertible_keys_stop_the_migration_and_leave_everything_…`, `test_a_render_that_differs_by_a_byte_rolls_everything_back_…` (head, branch, tree unchanged; file listed `(changed)`) | `update.py:415-436`, `update.py:464`, `update.py:472-482` (rollback) | |
| AC-114.43 | met | G `test_a_dry_run_prints_the_plan_and_changes_nothing_ac_114_43` | `update.py:487-500`, `update.py:733-734` | |
| AC-114.44 | met | G `test_update_without_migrate_refuses_naming_the_flag_…`, `test_migrate_on_a_migrated_repo_reports_already_migrated_…` | `update.py:58-61`, `update.py:609`, `update.py:632-633` | |
| AC-114.45 | met | G `test_merge_settings_switches_the_plugins_and_keeps_the_repos_own_…`, `test_merge_settings_reports_nothing_…`, `test_merge_settings_file_writes_the_merged_plugins_…`, `test_the_templates_enable_the_5_0_noun_plugins_…` (all six templates), `test_migrate_switches_the_plugins_and_reports_each_entry_…`, `test_a_component_repo_enables_the_component_plugins_…` | `settingsmerge.py:15`, `settingsmerge.py:68-79`; `update.py:670-671`; `templates/*/.claude/settings.json*` | |
| AC-114.46 | met | G `test_a_component_repo_gets_the_template_and_the_plugin_switch_only_ac_114_46` (no system.yaml, code and README untouched, shape id kept) | `update.py:587` (system steps only for `gitops-app`), `update.py:621-623` | |
| AC-114.47 | met | G `test_the_v1_to_v2_step_is_part_of_the_same_migration_ac_114_47` | `update.py:618-620` | the report line names the 4.x `compose add`, see Deviations |
| AC-114.48 | met | G `test_dump_starts_with_the_generated_header_and_round_trips_…`, `test_has_comments_sees_comments_in_either_old_file_…`, `test_migrate_writes_the_header_and_drops_the_comments_and_says_so_…` | `migrate5.py:15-20`, `migrate5.py:256-264`; `update.py:628` | |
| AC-114.49 | met | G `test_the_fleet_migrates_a_component_repo_and_merges_it_ac_114_49`, `test_a_failed_migration_is_a_failed_row_without_a_pr_…`, `test_the_dry_run_announces_the_migration_…`; (gitops-app path in `…_ac_114_68`) | `fleet_pr.py:242` (`--migrate`), `fleet.py:172` | approved test change (real v4 baseline) |
| AC-114.67 | met | G `test_the_owner_is_written_and_the_shapes_map_ac_114_67`, `test_gateway_secret_store_and_registries_become_top_level_keys_…` | `update.py:395-401` (`_owner`: `github_org`, else origin), `migrate5.py:95-96`, `migrate5.py:207`, `migrate5.py:244-248` | |
| AC-114.68 | met | G `test_the_fleet_migrates_a_gitops_app_and_merges_the_proved_pr_ac_114_68` (no label, squash-merged on green), `test_a_major_version_still_waits_for_a_person_when_it_is_not_the_migration_…` | `fleet_pr.py:90-104`, `fleet_pr.py:19` (LABEL) | label + comment on the unproved path is the unchanged spec-096 behaviour |

## Release, docs and agents

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-114.50 | met | P `test_the_marketplace_and_the_manifests_agree_ac_114_50`, `test_the_release_is_5_0_0_or_later_…`, `test_the_gitops_app_shape_belongs_to_the_system_plugin_…` | `.claude-plugin/marketplace.json` (nouns 1.0.0, svc 4.0.0, shared 1.0.0, app 2.0.0, gitops 2.0.0), `docs/CHANGELOG.md:9` (`[5.0.0]`), `shapes.yml` | the `v5.0.0` tag is made at release, after merge |
| AC-114.51 | met | P `test_the_changelog_has_the_old_to_new_table_and_the_migration_steps_ac_114_51` | `docs/CHANGELOG.md:9-93` | |
| AC-114.52 | met | P `test_no_prompt_command_doc_or_site_page_names_a_4x_thing_ac_114_52` | word sweep over plugins, templates, docs, site (see diff stat) | approved test change (`product-manager`, `product` inside slugs/file names) |
| AC-114.53 | met | P `test_the_command_reference_is_grouped_by_noun_without_tombstones_ac_114_53` (ran the generator: `site/node_modules` is present) | `site/scripts/generate-reference.mjs:18-37` | |
| AC-114.54 | met | P `test_the_status_says_5_0_is_current_ac_114_54`, `test_adopting_has_the_migration_section_…` | `docs/DOMAIN-MODEL.md:5`, `docs/DOMAIN-MODEL.md:78`, `docs/ADOPTING.md:165` | |
| AC-114.55 | met | P `test_every_template_names_the_5_0_spec_command_ac_114_55`, `test_the_shape_registry_check_passes_with_the_5_0_rule_…` | `scripts/shapes.py:205-206`; `templates/*/CLAUDE.md*` | |
| AC-114.56 | met | P `test_the_e2e_script_uses_only_5_0_names_and_a_system_yaml_ac_114_56` | `tests/e2e/run.sh:46-236` (`system new`, `spec new/approve`, `component ship start`, `instance verify dev`, `instance promote e2e-api --to staging`, `instance verify staging`, `component ship finish`) | static check passes; the cluster run itself is in CI only (not run locally) |
| AC-114.66 | met | P `test_shared_holds_the_launcher_hooks_and_two_agents_only_…`, `test_the_planner_moved_to_system_and_the_v1_agent_is_gone_…`, `test_app_and_gitops_hold_only_tombstones_…`, `test_the_changelog_says_app_and_gitops_leave_in_6_0_…` | `plugins/system/agents/planner.md` (moved), `plugins/gitops/agents/deployment.md` and `plugins/gitops/hooks/hooks.json` deleted, `docs/CHANGELOG.md:13` | |
| AC-114.71 | met | P `test_the_full_example_uses_the_final_schema_ac_114_71`, `test_the_command_tables_list_api_list_check_and_fix_…` | `docs/DOMAIN-MODEL.md:78` (example), `docs/DOMAIN-MODEL.md:150` (command tables) | |

## Non-goals

- Nothing in the cluster is renamed: every "same as 4.x" test compares the full generated tree byte for byte, and the migration proves the same on a real 4.x repo. ✔
- Shape ids, `.copier-answers.yml` (`app_name`, `_src_path`) and `applications/` are unchanged (`shapes.yml` only changes `gitops-app.plugin` to `system`). ✔
- No aliases: every 4.x `cplat` name exits 2 without importing its module, and every old slash command is a tombstone. ✔
- No `/api:check` or `cplat api check` (`api` has only `list`); no resource list (`resource list` exits 2). ✔
- One database resource only; no environments beyond dev/staging/prod; no per-environment `gateway`/`secretStore`/`registries` (not environment keys). ✔
- No versions in `system.yaml` (render refuses them). ✔
- History is not rewritten: CHANGELOG has additions only, `docs/adr/` gets only ADR-054 and its index row, `docs/specs/` changes only spec 114. ✔
- No separate fix-bug pipeline. ✔

## Deviations from the plan

- **All 38 tasks are `done: true`.**
- **Files outside every task's `files`:** ADR-054 and the spec's own `spec.md`/`design.md`/`plan.md` (expected); `templates/*/docs/adr/000-bootstrap.md*` and `templates/*/docs/env-vars.md*` (5.0 words for AC-114.52); the acceptance tests and `system_fixtures.py` (red commit); a dozen ported tests (`test_autoissue.py`, `test_drift.py`, `test_spec.py`, `test_runs_report*.py`, …) under the t38 port. All acceptable.
- **Changes to acceptance tests after the red commit** (`git diff b6c204f..HEAD`). I checked each one against the spec and design. None weakens a criterion:
  - AC-114.19 defaults test sets `policy: off` on every environment. 4.x without `policies:` renders no policy, but an absent 5.0 policy means audit (AC-114.7). Without this change the test contradicted AC-114.7. Acceptable.
  - AC-114.21: the ApplicationSet assertion is now a superset check. `same_as_4x` still requires every file to be equal. Acceptable.
  - AC-114.41: `{"dev": "Off", "prod": "Audit"}` now expects prod `audit`. The old expectation `enforce` contradicted the explicit 4.x value. Acceptable.
  - AC-114.52: `product-manager` and `product` inside slugs and file names are allowed. These are agent and file names, not model nouns. Acceptable.
  - AC-114.38: the test now forbids only `app-ship gate`. The state-file name `cplat-app-ship.json` stays internal per the design. Acceptable.
  - AC-114.36: the test commits between steps because the 4.x clean-tree rule still holds. Its assertions are stricter (each step's rc is now checked). Acceptable.
  - `build_old_component` and the fleet tests now render from `V4_REF` / a real v4 baseline. This makes the "4.x repo" really 4.x. Acceptable.
- **Contract differences (not covered by a criterion; non-blocking, worth a small follow-up):**
  - `newsvc.py:54` keeps `prog="cplat new-service"` and `fleet.py:64` keeps `prog="cplat fleet"`. The design says each module's `prog` is its 5.0 form (`cplat component new`, `cplat platform fleet`). `cplat component new --help` therefore prints a 4.x usage line.
  - Some user-facing hints still name 4.x commands or nouns:
    - `compose.py:156`: `/shared:new-service`
    - `promote.py:87`: `/svc:release`
    - `update.py:550`: `/shared:report-issue`
    - `update.py:620`: `` `compose add <service> --from-k8s` ``
    - `update.py:515`: "the product's gitops-app repo"
  - AC-114.52's scope (prompts, commands, skills, templates, docs, site) and AC-114.38's scope (ship messages) do not include these `cplat` outputs, so no criterion fails. They go against the story "the same nouns everywhere" and should be fixed.
- **Not proven locally:** the e2e cluster run (AC-114.56) and the `v5.0.0` tag (AC-114.50) happen in CI and at release.

## Contract

The build matches `design.md`:
- render error texts and key tables
- model schema 2
- `cplat` noun table and moved-name line
- migration steps, report and rollback
- `enabledPlugins` merge
- fleet merge rule
- tombstone format
- plugin versions

The only exceptions are the two `argparse` `prog` names listed above. ✔
