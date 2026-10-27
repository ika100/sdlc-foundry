# Verification — 118 A cache resource compatible with Redis

**Result:** pass, on condition that this PR's CI e2e job is green before merge. Every active criterion is `met`. The in-cluster parts are pending that job. Four items are listed under "To fix or confirm before the PR". None of them changes a verdict.
**Commit:** d39251a · **Base:** 2780d9d (the merge base with `origin/main`; `origin/main` has since moved to 66ecc1c, see Deviation 5) · **Trace:** 19/19 active criteria named by tests (AC-118.1 to .8, .11, .13 to .15 and .17 to .23 appear in `tests/cplat/test_cache_118*.py`; .6, .7, .8, .11, .14, .15, .18, .19 and .23 also in `tests/e2e/run.sh`). AC-118.9, .10, .12 and .16 are withdrawn.

**Test run.** These figures come from the orchestrator. I did not rerun them, because this review is read-only and runs no tests.
- Full suite: 4858 passed, 8 skipped.
- `scripts/ci-local.sh --render --site` passed.
- Valkey pins re-checked at build: 8.1.11 and 9.1.3 are the newest patches (all 321 tags were read). The pinned ESO 2.12.0 CRD has `refreshPolicy: CreatedOnce`. Both images run as UID/GID 999 with workdir `/data` (read from the images).

**Not run locally:** `tests/e2e/run.sh` (t8). This machine has no k3d. The e2e workflow in CI runs it on the PR, so the following are **pending CI, not passed**:
- AC-118.15;
- the cluster halves of AC-118.6 (maxmemory, eviction, OOM under `noeviction`, no OOMKill at 64Mi), .7 (key survives a pod delete with persistence, empty without), .8, .11 (NOAUTH / WRONGPASS / PONG), .14 (no pod volume backup of `e2e-sessions-0`, the restore list), .18, .19 (password survives a restart, a re-apply and a force-sync) and .23 (doctor);
- the design's open runtime assumptions: Valkey on a read-only root filesystem without a volume, `valkey-cli -u`, and eviction within 64Mi.

Line numbers refer to `templates/gitops-app/scripts/render.py` unless another file is named. `templates/cluster-gitops/scripts/system_render.py` is byte-identical to it (`cmp` at d39251a). Test files: `tests/cplat/test_cache_118.py` (render) and `tests/cplat/test_cache_118_cmds.py` (cmds). Fixtures are in `tests/cplat/cache_fixtures.py`.

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-118.1 | met | cmds: `test_add_a_cache_declares_it_without_sizing_and_renders_ac_118_1` (entry `== {"type": "cache"}`, comments kept, render check passes); `test_a_cache_added_by_the_command_renders_its_objects_once_used_ac_118_1`; both external entry tests; the next-steps tests; `test_add_pr_uses_the_resource_branch_and_title_for_a_cache_ac_118_1`; `test_add_cache_errors_change_nothing_and_name_the_reason_ac_118_1` (4 cases); `test_add_a_cache_is_no_longer_refused_as_not_available_ac_118_1` | `scripts/cplat/addon.py:19` (`PLANNED_TYPES`), `:108-109` (entry), `:171-172` (next step) | |
| AC-118.2 | met | render: `test_a_cache_with_all_its_keys_is_accepted_ac_118_2`, `test_an_unknown_cache_key_fails_naming_resource_key_and_allowed_keys_ac_118_2`, `test_other_unknown_top_level_keys_fail_ac_118_2` ×3, `test_an_unknown_instance_key_fails_ac_118_2`, `test_version_is_not_an_instance_key_ac_118_2`, `test_instances_must_be_a_mapping_ac_118_2`, the external-sizing tests (×4, ×5, the order before the unknown-key check, an inherited `external`) | `render.py:155-157` (key lists), `:755-787` (key and external-sizing checks), `:791-796` | |
| AC-118.3 | met | render: `test_the_effective_values_default_to_valkey_9_256mi_allkeys_lru_no_persistence_ac_118_3` (the whole renderer-API dict), `test_the_effective_values_follow_instance_then_resource_then_default_ac_118_3`, `test_a_default_cache_renders_one_valkey_node_with_the_defaults_ac_118_3`, `test_the_defaults_in_the_statefulset_are_256mi_allkeys_lru_and_no_volume_ac_118_3`; cmds: the three model tests and `test_the_renderer_and_the_model_agree_on_cache_instances_ac_118_3` | `render.py:836-844` (defaults, `replicas: 1` at `:1500`); `scripts/cplat/model.py:509-522`, `:594` | |
| AC-118.4 | met | render: `test_an_unsupported_version_fails_ac_118_4` (7, 10, `latest`, 9.1, `"7"`, 0), the memory tests (13 bad, 9 good, instance), the policy tests (5 bad, all 8 good, instance), the persistence tests (6 bad, instance), the storage tests (6 bad, instance, size before rule), the three storage-needs-persistence tests, including the dev/staging/prod order | `render.py:682-717` (`quantity_bytes`, `check_cache`), `:812-813` | Every case fails through `fail()` before anything is written. The memory minimum of 64Mi is design decision 1. |
| AC-118.5 | met | render: `test_type_redis_or_valkey_fails_naming_cache_ac_118_5` ×2, `test_a_used_redis_or_valkey_resource_fails_the_same_way_and_writes_nothing_ac_118_5` ×2, `test_the_redis_text_replaces_the_types_line_ac_118_5` | `render.py:747-748` | The text is exact, backticks included. |
| AC-118.6 | met (cluster part pending CI) | render: `test_maxmemory_is_80_percent_of_the_memory_limit_floored_ac_118_6` (8 cases: 256Mi→214748364, 64Mi→53687091, 1Gi, 0.5Gi, 100M, an integer, 2G, 65536Ki), `test_the_container_has_a_memory_limit_equal_to_its_request_and_no_cpu_limit_ac_118_6`, `test_the_sized_statefulset_is_exactly_the_designed_document_ac_118_6`, `test_memory_and_policy_are_set_per_environment_ac_118_6`; cmds: `test_the_e2e_script_proves_maxmemory_policy_and_eviction_ac_118_6`; `run.sh` (cstep "filling ratelimit past maxmemory…") | `render.py:841` (`quantity_bytes(memory) * 4 // 5`), `:1482-1483`, `:1491` | The arithmetic is exact. `Fraction` avoids float error and `int()` floors. Eviction without OOMKill, and OOM under `noeviction`, are runtime behaviour; the e2e checks both (`evicted_keys > 0`, `DBSIZE < 1200`, `restartCount 0`, no `OOMKilled`, an `OOM` reply). |
| AC-118.7 | met (cluster part pending CI) | render: `test_persistence_false_renders_no_volume_at_all_ac_118_7`, `test_persistence_true_renders_the_aof_args_a_mount_and_a_1gi_claim_by_default_ac_118_7`, `test_the_storage_size_is_taken_from_the_instance_then_the_resource_ac_118_7`, `test_persistence_can_differ_per_environment_ac_118_7`, `test_rdb_snapshots_are_off_in_both_modes_ac_118_7`, `test_a_change_of_the_volume_recreates_the_statefulset_ac_118_7`; cmds: `test_the_e2e_script_proves_persistence_across_a_pod_restart_ac_118_7`; `run.sh` (cstep "delete both pods…") | `render.py:1482-1486` (`--save ""`, `--appendonly`, `--appendfsync everysec`), `:1507-1511` (mount and claim only with persistence) | With `persistence: false` there is no Kubernetes volume. Under containerd, the image's `VOLUME /data` becomes a per-container scratch directory. That is not a volume in the criterion's sense, and nothing is written there because AOF and RDB are off. |
| AC-118.8 | met (cluster part pending CI) | render: `test_a_cache_directory_has_exactly_the_five_designed_files_ac_118_8`, `test_the_only_service_is_a_clusterip_on_6379_ac_118_8` (no `LoadBalancer`, `NodePort`, `HTTPRoute`, `Ingress`, `hostPort`, `hostNetwork`), `test_no_route_or_gateway_object_names_the_cache_ac_118_8`, `test_the_cache_serves_on_the_redis_port_inside_the_cluster_ac_118_8`; cmds: `test_the_e2e_script_proves_the_cache_is_not_exposed_ac_118_8` | `render.py:1524-1527`, `:1491` | |
| AC-118.11 | met (cluster part pending CI) | render: `test_valkey_requires_the_password_from_the_secret_ac_118_11`, `test_the_probes_authenticate_with_the_password_ac_118_11`, `test_the_container_is_hardened_like_the_guard_rails_demand_ac_118_11`; cmds: `test_the_e2e_script_proves_auth_ac_118_11`; `run.sh` (NOAUTH / WRONGPASS / PONG) | `render.py:1482` (`--requirepass $(VALKEY_PASSWORD)`), `:1490` (env from `<n>-app`/`password`) | |
| AC-118.13 | met | cmds: `test_remove_of_a_used_cache_names_every_user_and_changes_nothing_ac_118_13` (`sessions is still used by api, web`, the file tree is unchanged), the `--dry-run` variant, the in-cluster, external and mixed `will_do` texts, the unused-remove test, `test_remove_of_a_cache_directory_goes_when_it_is_unused_ac_118_13` | `scripts/cplat/addon.py:124` (refusal), `:127-138` | |
| AC-118.14 | met (cluster part pending CI) | render: `test_every_cache_object_carries_the_name_label_ac_118_14` (the StatefulSet, pod template, claim template, Service, generator, ExternalSecret and Secret template), `test_the_schedule_leaves_out_every_cache_by_name_used_or_not_ac_118_14`, `test_no_cache_object_pod_or_volume_is_selected_by_the_schedule_with_or_without_persistence_ac_118_14`, `test_the_schedule_still_selects_other_objects_ac_118_14`, `test_a_cache_adds_no_backup_object_ac_118_14`; cmds: the two doc tests and the e2e text test; `run.sh` (Schedule NotIn, no `podvolumebackups` of `e2e-sessions-0`/`e2e-ratelimit-0`, the restore refusal does not list `data-e2e-sessions-0`) | `render.py:1478-1479` (labels `L`/`S`, fresh dicts), `:1556`, `:1590` (`NotIn [to, *caches]`); `docs/BACKUP-AND-RESTORE.md` (cache row) | Pods, PVCs (through `volumeClaimTemplates[].metadata.labels`), the Secret (through `target.template.metadata.labels`), the ExternalSecret, the generator, the Service and the StatefulSet all carry `app.kubernetes.io/name: <cache>`. The StatefulSet's ControllerRevisions and the Service's Endpoints and EndpointSlices inherit it. The e2e adds a positive check (`e2e-files-0` is in the PVB list), so the absence check is not vacuous. |
| AC-118.15 | met (pending CI) | cmds: the three `test_the_e2e_script_*_ac_118_15` text tests; `run.sh` (cstep "declare…", "the component SETs a key and GETs…", "platform doctor names no cache…") | — (a test-only criterion) | The probe pod carries e2e-web's own `valueFrom` entries, so the value really travels through the component's `SESSIONS_REDIS_URL`. No cluster-up flag is added. |
| AC-118.17 | met | render: `test_the_valkey_pins_are_exact_per_major_ac_118_17`, `test_the_statefulset_runs_the_pinned_release_of_its_major_ac_118_17` ×2, `test_no_floating_tag_is_rendered_ac_118_17`, `test_a_version_change_changes_only_the_statefulset_image_ac_118_17` | `render.py:206-209` (`VALKEY_IMAGES`), `:1489` | The order through the environments and the downgrade refusal belong to spec 121 (status `approved`, not built), as in 115 and 116 and as design.md says. The spec's Non-goals exclude the upgrade procedure. A downgrade is not refused yet; the design's Risks note this. |
| AC-118.18 | met (cluster part pending CI) | render: `test_the_cache_type_contract_is_in_the_renderer_ac_118_18`, `test_one_cache_gives_the_four_variables_in_table_order_ac_118_18`, `test_the_variables_are_secret_key_references_in_the_designed_form_ac_118_18`, `test_the_variables_come_after_the_literal_env_ac_118_18`, the next-to-a-database-and-bucket, two-caches, upper-case prefix and two-caches-plus-database tests, `test_a_second_component_with_one_cache_keeps_bare_names_and_shares_the_secret_ac_118_18`, the env clash test ×4, `test_the_url_names_database_zero_and_the_secret_is_the_same_in_every_environment_ac_118_18`; cmds: the compose prefix-note tests ×3, `test_the_uses_help_names_the_cache_variables_ac_118_18` | `render.py:193-194` (`TYPES["cache"]`), `addon_env` at `:1163` (unchanged), `:1520-1522` (url with `/0`); `scripts/cplat/compose.py:33`, `:291` | |
| AC-118.19 | met (cluster part pending CI) | render: `test_the_password_generator_is_the_designed_document_ac_118_19` (length 32, `symbols: 0`), `test_the_externalsecret_creates_the_secret_once_with_the_four_keys_ac_118_19` (`CreatedOnce`), `test_no_password_value_appears_in_the_rendered_tree_ac_118_19`, `test_renders_keep_the_same_secret_name_keys_and_documents_ac_118_19` (a version, memory or persistence change leaves the generator, ExternalSecret and Service byte-identical), `test_an_environment_has_its_own_host_but_the_same_generator_ac_118_19`; cmds: the e2e text test; `run.sh` (32 characters, the designed url, unchanged after a pod delete, a re-apply and a force-sync) | `render.py:1513-1523` | The password is letters and digits only (`symbols: 0`), so it is safe in `redis://:<pw>@…` without encoding. Replacing the StatefulSet does not touch the ExternalSecret or its Secret. |
| AC-118.20 | met | render: `test_an_external_instance_renders_no_valkey_and_the_four_key_externalsecret_ac_118_20`, `test_the_external_store_path_follows_the_default_and_remote_overrides_ac_118_20`, `test_an_external_cache_gives_the_same_variables_as_an_in_cluster_one_ac_118_20`, `test_an_external_everywhere_cache_renders_no_addon_and_no_operator_ac_118_20`, `test_the_external_secret_has_no_template_so_a_rediss_url_is_passed_unchanged_ac_118_20`, `test_an_external_cache_needs_the_secret_store_ac_118_20` | `render.py:193` (keys), `external_secrets` at `:1278` (unchanged, reads `TYPES`), `:826-834` | No template, so a `rediss://` value is copied as stored. Design decision 16 skips an external cache in the e2e. |
| AC-118.21 | met | cmds: `test_the_domain_model_guide_documents_the_cache_type_ac_118_21`, `test_the_domain_model_guide_lists_the_four_secret_keys_and_the_external_store_keys_ac_118_21`, `test_the_user_journey_and_the_site_describe_the_cache_ac_118_21`, `test_the_resource_plugin_docs_describe_the_cache_ac_118_21` | `docs/DOMAIN-MODEL.md` (keys table rows, the `type: cache` bullet: Redis protocol, Valkey and the licence reason, not `redis`, keys and defaults, the four variables and the `<NAME>_` prefix, `<system>-<name>-app` and its keys as the contract for spec 120); `plugins/resource/commands/add.md`; `site/.../concepts/addons.md`; `docs/USER-JOURNEY.md` | Every required item is there. One defect, see "To fix" 1: `add.md` says "`--version` 8 or 9" for a cache, but `cplat` refuses `--version` for a cache. |
| AC-118.22 | met | render: `test_cache_is_no_longer_a_planned_type_and_broker_still_is_ac_118_22`, `test_the_broker_keeps_its_message_ac_118_22`, `test_every_other_type_is_refused_with_the_same_message_ac_118_22` ×4, `test_the_database_and_bucket_texts_are_unchanged_ac_118_22`, both clash tests, `test_a_5x_system_without_a_cache_renders_byte_identically_to_before_ac_118_22` ×3, `test_an_unused_cache_changes_nothing_in_the_tree_ac_118_22`; cmds: `test_add_of_redis_or_valkey_keeps_114s_message_and_adds_the_cache_hint_ac_118_22` ×2, the broker and unknown-type tests, the CHANGELOG and plugin version tests | `render.py:148`, `:869` (`CACHE_SUFFIXES`); `scripts/cplat/addon.py:59-61` | The byte-identical digests were committed in the red commit 3ffc419, before any renderer change, and have not changed since. `docs/specs/114-*` is untouched. |
| AC-118.23 | met (cluster part pending CI) | render: `test_a_cache_renders_only_plain_kinds_and_external_secrets_objects_ac_118_23`, `test_a_cache_adds_no_operator_with_or_without_operators_owner_ac_118_23` ×2, `test_owner_managed_environments_still_render_the_same_cache_ac_118_23`, `test_a_cache_next_to_a_database_leaves_the_operators_as_they_were_ac_118_23`, `test_the_cache_is_an_element_of_the_environments_addon_set_ac_118_23`, `test_an_environment_without_a_running_user_gets_no_cache_ac_118_23`; cmds: the three doctor tests, `test_cluster_up_and_bootstrap_have_no_cache_step_ac_118_23`, the ADR test; `run.sh` (`operators/` unchanged, doctor) | `render.py:1665-1666` (dispatch to `cache_files`); `OPERATOR_OF_TYPE` has no `cache` | |

## Non-goals

- No HA: `replicas: 1` (`render.py:1500`); no Sentinel, cluster mode or sharding. ✔
- No Redis and no Redis/Valkey choice: `type: redis`/`valkey` is refused (`render.py:747`). ✔
- No cache backup, restore or copy between environments: caches are excluded by name, and no new backup object is rendered. ✔
- No per-component isolation: one Secret, database `0`. ✔
- No TLS in the cluster and no password rotation: `CreatedOnce`. ✔
- No modules, and no server settings beyond AC-118.2: the args are exactly port, password, maxmemory, policy, save, dir and AOF. ✔
- Not exposed: ClusterIP only. ✔
- No off-the-shelf components, no scaling (spec 120), no upgrade procedure (spec 121). ✔

## Approved test changes

1. **cfc4691 (t9).** Every changed line carries `# spec 118`. Only the lines named in plan t9 changed:
   - `test_resources_115.py`: the planned-type parametrisation and `PLANNED_TYPES`;
   - `test_resources_115_cmds.py`: the parametrisation;
   - `test_bucket_116.py`: `PLANNED_TYPES` and the parametrisation;
   - `test_bucket_116_cmds.py`: the parametrisation and the `--uses` help (now design.md's text);
   - `test_backup_117_cmds.py`: `resource` 1.4.0.
2. **cf5e1f0.** Six slips in `test_cache_118.py`. Each changed line carries a `# spec 118 slip` comment, and none weakens what the criterion asks:
   - `load_system(...)["cfg"]` is the real API.
   - The environment-order slip (×2): `sorted(...) == sorted(ENVS)`, and both sides of the version-change comparison are sorted.
   - The AC-118.8 route test skips the cache's own addon directories in every environment, not only dev. The Service in them is the cache's own, and `test_the_only_service_is_a_clusterip_on_6379_ac_118_8` still checks it.
   - The file count is per environment (`× len(ENVS)`).
   - `backup_system(uses_ratelimit=True)`: an unused cache renders nothing, so the test now uses `ratelimit` in order to have its objects to inspect. The NotIn test still uses the variant where `ratelimit` is unused, so "used or not" is still covered.

`git diff 3ffc419 HEAD -- tests/` shows only these two commits and the e2e (t8).

## Deviations from the plan

1. **41f8fbf (outside the plan's exact text, inside t6's files).** The plan's `add.md` description dropped "(postgres is a database)", which AC-114.28's test needs. The fix restores it. The description is 213 characters, under 260. Acceptable.
2. **t8 "done when: passes on a local machine".** Replaced by the CI e2e job, as for 115 to 117. Acceptable only once that job is green.
3. **design.md's "Verified … re-verify at build"** was not updated. The orchestrator re-verified at build (all 321 tags, ESO `CreatedOnce`, UID 999 and `/data`), but design.md still says that only about 60 tags were listed. Acceptable; adding a "Re-verified at build" line as 117 did would be better.
4. **Design Risks marked "Documented" are not in the user docs.** Three risks are affected:
   - The AOF-rewrite fork headroom ("give persistent caches more `memory`").
   - The downgrade crash-loop with persistence ("documented next to `version`").
   - That growing `storage` does not resize the volume. Only ADR-064 mentions this; DOMAIN-MODEL, `add.md` and the site do not.
   This is not required by any criterion. See "To fix" 2.
5. **Base.** The branch is on 2780d9d. `origin/main` is at 66ecc1c (#256 deps, #257 release 5.2.0, #258 the domain model). 5.2.0 moved the 117 entry out of `[Unreleased]`, and #258 changed `docs/DOMAIN-MODEL.md`. A merge is needed before the PR, with likely conflicts in `docs/CHANGELOG.md` and `docs/DOMAIN-MODEL.md`. The `resource` plugin on main is still 1.3.0, so 1.4.0 stands. ADR-064 is free on main.
6. **Task status.** The plan's front matter has no `done` flags. t1 to t9 each have a commit: a73a44a, 82c0450, 137fe86, ef84cac, b5a8b8c, 423a340, 5900f6e, d39251a and cfc4691.
7. **Files outside every task's `files`:** only the planning artefacts (`docs/adr/063-*`, `docs/adr/README.md`, `docs/backlog.md`, the spec, design and plan) and `tests/cplat/cache_fixtures.py` and the two `test_cache_118*.py` files from the red commit. Acceptable.

## Design decisions taken by default (all 17 checked)

1. Memory at least 64Mi: `CACHE_MEMORY_MIN` (`:165`, `:700`). ✔
2. Quantities: plain, binary and decimal suffixes, fractions, no milli and no exponent (`QUANTITY` `:162`); floored (`:687`). ✔
3. 32 letters and digits, `CreatedOnce`: `:1515`, `:1518`. ✔
4. `host` is `<n>.<ns>.svc`: `:1521`. ✔
5. One ClusterIP Service, also `serviceName`, and no headless Service: `:1500`, `:1526`. ✔
6. No volume without persistence (not an `emptyDir`): `:1507`. ✔
7. RDB off in both modes, AOF `everysec`: `:1483-1486`. ✔
8. `Force=true,Replace=true`: `:1530`. ✔ (but see "To fix" 3 on its reach)
9. Memory request = limit, CPU request 50m, no CPU limit: `:1492`. ✔
10. UID 999, read-only root filesystem, `drop: [ALL]`, RuntimeDefault, no token, `command: [valkey-server]`: `:1489`, `:1496-1497`, `:1502-1504`. ✔
11. No sizing flags on add; `--version` stays database-only (cmds test, 4 cases). ✔
12. The redis/valkey hint keeps 114's message: `addon.py:59-61`. ✔
13. Removing a cache keeps its objects: addon set `prune: false` (`render.py:1730`). ✔
14. Pins are tags without digest; version moves wait for 121. ✔
15. Clash suffixes `-app` and `-password`: `:158`, `:869`. ✔
16. No external-cache e2e step. ✔
17. The `--uses` help and the prefix note name caches: `compose.py:33`, `:291`. ✔

## Contract

Matches `design.md`:
- The schema, every render error text and their order (`check_cache` runs the version first, then the four value checks per `<where>`, then the two `storage needs persistence` checks, instances in `ENVS` order before the resource).
- The renderer API dict (the full dict is asserted).
- The four documents, with key order, labels, wave and both persistence variants (full-document equality in the tests), and the kustomization.
- `TYPES["cache"]`, `VALKEY_IMAGES`, the external ExternalSecret.
- The `cplat resource` texts, the model sizing and text, the compose help and note.
- No change to status, doctor, `local-cluster.sh`, `bootstrap.sh`, `operators/` or Kyverno.

`addon.py:26-30` `TYPE_KEYS` mirrors `render.py`'s `TYPES[...]["keys"]`, as plan t4 asks. It matches today for all three types, but no test ties the two together, and it has no `broker` entry (see "To fix" 4).

## To fix or confirm before the PR

1. **`plugins/resource/commands/add.md`, Cache bullet: "run as Valkey (`--version` 8 or 9, default 9)".** `cplat resource add x --type cache --version 9` exits 1 with `--version applies to --type database only` (design decision 11; asserted by `test_add_cache_errors_change_nothing_and_name_the_reason_ac_118_1`). An agent that follows the command doc will pass the flag and fail. Write "`version: 8` or `9` in system.yaml (default 9)" instead. Doc-only.
2. **Document the three risks that design.md marks "Documented"** (Deviation 4), next to the cache keys in DOMAIN-MODEL and/or `add.md`, or remove the "Documented" claims from design.md. One sentence each.
3. **Confirm the reach of `Force=true,Replace=true`.** The addon ApplicationSet syncs with `automated: {prune: false, selfHeal: true}` and no `ApplyOutOfSyncOnly` (`render.py:1730`). By default, an Argo CD sync applies every resource of the Application. So any sync of `addon-<cache>-<env>` deletes and recreates the StatefulSet, not just a change of `persistence` or `storage` as ADR-064's Consequences say. That includes a platform update that changes only the Service's or the ExternalSecret's document, and a manual sync. Each such sync empties a cache that has no persistence.
   - No criterion is broken: the Secret and the password survive, and the PVC is kept.
   - But the ADR and design understate the effect. The e2e applies addons with `kubectl apply -k`, so it never exercises Argo's replace. The case where Argo's diff of a replaced StatefulSet (no last-applied annotation, `volumeClaimTemplates` defaults) leaves it permanently OutOfSync is also untested. Combined with `selfHeal`, that would recreate the pod in a loop.
   - Suggested action: at least correct ADR-064 and design.md to say "every sync of the cache's Application recreates the StatefulSet". Ideally, check one Argo-synced cache on a real cluster before 5.x users rely on it.
4. **Optional:** add a unit test asserting `addon.TYPE_KEYS[t] == ", ".join(render.TYPES[t]["keys"])` for every built type. Spec 119 must add `broker` there, or `resource add --type broker --external` will raise `KeyError`. Also optional: the `plugins/resource/README.md` sentence reads "The types `database` (…) and `bucket` (…) and `cache` (…) are built", which should be "`database` (…), `bucket` (…) and `cache` (…)".

Also merge `origin/main` (Deviation 5) and rerun the suite before opening the PR.

RESULT: pass, on condition that the PR's CI e2e job, which runs `tests/e2e/run.sh` for AC-118.15 and the cluster halves of AC-118.6, .7, .8, .11, .14, .18, .19 and .23, is green before merge, and that "To fix" items 1 and 2 (doc-only) are done. Item 3 is a risk to confirm, not a criterion failure.

## After review (orchestrator)

- **e9eb37d — design decision 8 changed.** The review's item 3 is accepted: with `Force=true,Replace=true` Argo CD would delete and
  recreate the cache's StatefulSet on every sync of `addon-<cache>-<env>` (every resource is applied on a sync), emptying caches
  without persistence on unrelated updates and risking a replace loop under self-heal. The StatefulSet now carries no sync option; a
  `persistence`/`storage` change stops at the immutable `volumeClaimTemplates` and takes one documented
  `kubectl delete statefulsets.apps <system>-<name> -n <system>-<env> --cascade=orphan` plus a sync. AC-118.7 does not ask for an
  automatic recreate. Test change: `test_a_change_of_the_volume_recreates_the_statefulset_ac_118_7` became
  `test_a_sync_never_replaces_the_statefulset_ac_118_7` (asserts no annotation), and the fixture's StatefulSet drops the annotation.
- Items 1 and 2: add.md names `version` in system.yaml; DOMAIN-MODEL documents the AOF-rewrite headroom, the downgrade crash-loop and
  that a larger `storage` does not resize the volume, with the orphan-delete step. Item 4: a new test ties `addon.TYPE_KEYS` to the
  renderer's `TYPES` (spec 119 must add `broker` to both); the README grammar is fixed.
- Full suite after the fix: 4859 passed, 8 skipped. The e2e is pending this PR's CI job.
