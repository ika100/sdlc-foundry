# Verification — 187 Settings agents edited by hand have a command

**Commit:** 5658929a · **Base:** de072da0 · **Trace:** 8/8 criteria named by tests (`tests/cplat/test_settings_commands_187.py`)

Second pass. Test run (Phase 3 summary, not re-run here because the review is read-only): `devbox run ci` was green before the fixes; test-fast is running again now. Since the first pass (f6e2baf4) only `plugins/resource/commands/add.md`, `plugins/resource/commands/backup.md` and the test file changed; no code changed, so the code line references below still hold.

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-187.1 | met | `test_lgtm_creates_the_observability_block_and_renders_ac_187_1`, `test_lgtm_keeps_the_other_observability_keys_ac_187_1`, `test_dry_run_prints_the_change_and_writes_nothing_ac_187_1`, `test_pr_opens_one_pull_request_with_only_generated_changes_ac_187_1` | `scripts/cplat/systemset.py:132-188` (`wanted`, will_do, write via `add_key`, render, did) | Block created as `{ui: lgtm}`, `alerts` kept, `render.py --check` passes, dry run leaves every file byte-equal, one PR on `system/set-dev` that holds only `system.yaml` and generated files. |
| AC-187.2 | met | `test_none_sets_ui_and_keeps_the_other_keys_ac_187_2`, `test_off_removes_the_block_when_only_ui_is_in_it_ac_187_2`, `test_off_with_other_keys_exits_1_names_them_and_changes_nothing_ac_187_2` | `scripts/cplat/systemset.py:58-68` (`check_observability`), `:172-175` (pop) | The fixture has only one key besides `ui` (`alerts`), so "names each key" is tested with one key. The code joins every key (`:66-68`). |
| AC-187.3 | met | `test_an_unknown_value_names_the_key_and_the_allowed_values_ac_187_3`, `test_lgtm_with_export_to_is_refused_ac_187_3` | `scripts/cplat/systemset.py:58-65` | Tightened: the exportTo test now also asserts the conflict text "ui lgtm and exportTo exclude each other" (`:64`), along with the key, exit 1 and unchanged files. |
| AC-187.4 | met | `test_to_sets_the_backup_with_the_defaults_ac_187_4`, `test_schedule_and_retention_are_stored_ac_187_4`, `test_setting_a_backup_takes_none_in_the_cluster_ac_187_4`, `test_backup_dry_run_prints_the_three_values_and_writes_nothing_ac_187_4`, `test_backup_pr_opens_one_pull_request_with_only_generated_changes_ac_187_4` | `scripts/cplat/dbbackup.py:61-62` (dispatch), `scripts/cplat/dbbackupset.py:92-153` (merge, will_do, write `:120-133`, render, PR) | Defaults `0 3 * * *` and `30d`, key order to/schedule/retention, render check passes, `kube.calls == []`, dry run byte-equal, one PR on `resource/backup-…`. |
| AC-187.5 | met | `test_only_the_given_values_change_ac_187_5`, `test_off_removes_the_backup_and_says_the_bucket_keeps_the_backups_ac_187_5` | `scripts/cplat/dbbackupset.py:124-127` (only the given keys), `:112-118` (`--off` deletes the key and any parents left empty), `:144` (kept line) | |
| AC-187.6 | met | `test_a_target_that_is_not_a_bucket_lists_the_buckets_ac_187_6`, `test_an_unknown_bucket_is_refused_ac_187_6`, `test_a_resource_that_is_not_a_database_is_refused_ac_187_6`, `test_an_external_database_is_refused_ac_187_6`, `test_an_unknown_environment_is_refused_ac_187_6`, `test_a_schedule_that_is_not_five_field_cron_is_refused_ac_187_6`, `test_a_retention_that_is_not_n_days_or_weeks_is_refused_ac_187_6`, `test_schedule_without_to_on_an_instance_without_backup_is_refused_ac_187_6`, `test_off_without_a_backup_is_refused_ac_187_6`, `test_off_with_another_option_is_refused_ac_187_6`, `test_a_failed_render_restores_the_files_ac_187_6` | `scripts/cplat/dbbackupset.py:55-86` (checks 1-9; external check `:69-70`), `:135-140` (restore and hint) | Tightened: `refused()` now asserts each case's key (`…backup.to`, `.schedule`, `.retention`, `…backup`, `resources.backups`, `resources.orders-db.instances.prod`, `environments.qa`), `fix:`, exit 1, unchanged files, and the listed buckets or environments. The render-failure test now asserts the key from the render's message and a `fix:` line. The external case asserts "provider", not the whole quoted phrase. Together with the key and `fix:` that is enough, and the code holds the exact phrase (`:69`). |
| AC-187.7 | met | `test_without_setting_options_the_system_file_is_untouched_ac_187_7`, `test_without_setting_options_dry_run_and_pr_are_refused_ac_187_7`; on-demand behaviour as AC-117.31/.32 define it: `tests/cplat/test_backup_117_restore.py::test_a_completed_backup_prints_its_time_and_exits_0_ac_117_31` and the tests after it, `tests/cplat/test_backup_117_fixes.py::test_resource_backup_creates_the_same_plugin_backup_as_before_ac_117_31` | `scripts/cplat/dbbackup.py:61-66` (dispatches only when a setting option is given; the on-demand path below is unchanged) | The criterion points to AC-117.31/.32, and their unchanged tests show the backup is taken through the same entry point. The 187 test checks that nothing changes in git. |
| AC-187.8 | met | `test_resource_backup_usage_line_names_the_setting_options_ac_187_8`, `test_system_set_usage_line_names_the_observability_option_ac_187_8`, `test_resource_add_points_to_resource_backup_ac_187_8` | `plugins/resource/commands/add.md:27`, `plugins/resource/commands/backup.md:2`, `plugins/system/commands/set.md:2` | Tightened: asserts "PITR and pooling are not provided", and the negative check `\bno backups\b` now matches the old sentence "No backups, PITR or pooling are provided". `/resource:backup` and `--to <bucket>` are still checked as two separate substrings; acceptable, because the prompt holds the full form `/resource:backup <db> --env <env> --to <bucket>` (`add.md:27`). |

## Non-goals

No command for `environments.<env>.backup`. No command for `exportTo`, `headersSecret`, `alerts`, `rules`, `queryURL` or `alertmanagerURL`. No `/resource:set`. One environment per run. No template-owned layout change. ✔

## Deviations from the plan

- `plugins/resource/commands/add.md`: the five facts dropped in the first pass are back. These are the name rule ("A name that exists or is invalid changes nothing"), `--type redis`/`valkey` → `cache`, the `rediss://` hint for TLS, "client libraries … use unchanged", and "the render prints the streams and consumers the owner creates". The other changes only tighten wording; the prefix-rule example is shortened to one variable. Acceptable. The three prompts total 11030 bytes, against 11047 at base, so they did not grow.
- `plugins/resource/commands/backup.md`: steps 1 and 2 are now separate list items. ✔ The old step 2 ("scheduled backups and continuous archiving come from `backup:` in `system.yaml`") is replaced by the setting mode, and "errors carry a `fix:` line" is dropped. Acceptable: the command now sets `backup:` itself, and the closing line still says to read the output whole.
- Rules register: only `docs/rules/plugins/resource/commands/backup.yml` changed (new R3). `add.yml` and `set.yml` are in t3's files but unchanged; acceptable, because no new rule sentence was added to those prompts.
- Every touched file is in some task's `files`; t1-t3 are `done: true`. ✔
- The test file changed after the freeze twice: a setup-only fix that the user approved, and the tightening below. Acceptable.

## Contract

Matches `design.md`: the messages and `fix:` hints of checks 1-10 and of `check_observability`, the write rules (double-quoted schedule, removal of parents left empty), the output and JSON keys, the PR branch and titles. ✔

## Tightened acceptance tests

| File | Reason | Asserts the criterion as written |
|---|---|---|
| `tests/cplat/test_settings_commands_187.py` | AC-187.3: the exportTo refusal must name the conflict; AC-187.6: every refusal must name the key and carry `fix:` (render failure included); AC-187.8: "PITR and pooling are not provided" must be present and the old "No backups, …" sentence absent | yes (AC-187.3, AC-187.6, AC-187.8). Assertions were only added, none removed. |

**Result:** pass
