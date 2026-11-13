# Verification — 195 A restored copy is checked without kubectl

**Result:** pass
**Commit:** b3cf3b81 · **Base:** 75da00d2 · **Trace:** 5/5 criteria named by tests

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-195.1 | met | `tests/cplat/test_195_resource_query.py::test_query_prints_a_plain_table_and_the_row_count_ac_195_1`, `::test_query_json_has_exactly_instance_columns_rows_truncated_ac_195_1`, `::test_query_shows_at_most_1000_rows_and_says_so_ac_195_1`, `::test_exactly_1000_rows_are_not_truncated_ac_195_1`, `::test_the_statement_goes_into_the_pod_in_one_exec_with_the_password_on_stdin_ac_195_1` | `scripts/cplat/dbquery.py:154` (CSV, 1000-row cap), `:182` (table, `<n> rows`, `truncated at 1000 rows`), `:245` (JSON with exactly the four keys), `scripts/cplat/cplat.py:86` (route) | The tests assert the exact header/row/`2 rows` lines, the JSON object, 1000 rows plus the truncation line with exit 0, and no truncation at exactly 1000. |
| AC-195.2 | met | `::test_copy_runs_against_the_generation_instance_and_names_it_ac_195_2`, `::test_copy_json_names_the_copy_instance_ac_195_2`, `::test_copy_of_a_previous_generation_is_labelled_previous_ac_195_2`, `::test_without_copy_the_active_generation_is_queried_after_a_switch_ac_195_2`; `tests/e2e/run.sh:2341` | `scripts/cplat/dbquery.py:206-217` (target instance and role), `:183` (`on <instance> (<role>) in <env>`) | The exec goes to the pod `shop-orders-db-g1-1`, and the output names the instance in both text and JSON. The e2e run reads row A on `e2e-postgres-g1` and rows A and B on the active instance. |
| AC-195.3 | met | `::test_a_write_is_refused_by_the_database_and_exits_1_with_its_error_ac_195_3`, `::test_a_write_to_a_copy_is_refused_the_same_way_ac_195_3`, `::test_prod_needs_no_confirmation_for_a_query_ac_195_3`, `::test_more_than_one_statement_is_refused_before_anything_is_sent_ac_195_3`, `::test_count_statements_…_ac_195_3`; `tests/e2e/run.sh:2347-2349` | `scripts/cplat/dbquery.py:24-26` (`BEGIN TRANSACTION READ ONLY`, `ON_ERROR_STOP`), `:172` (read-only error mapping), `:134-138` (one statement), no `--confirm` in `build_parser` `:33` | The unit tests fake the database error. The e2e run proves on PostgreSQL that the database refuses an INSERT, that the output says `read-only`, and that the table still holds `A,B`. A function that writes inside a SELECT is covered by the read-only transaction (A2), not by its own test. |
| AC-195.4 | met | `::test_an_external_database_is_refused_ac_195_4`, `::test_an_environment_without_an_instance_is_refused_ac_195_4`, `::test_a_copy_that_does_not_exist_lists_the_existing_copies_ac_195_4`, `::test_a_copy_without_any_copies_says_none_ac_195_4`, `::test_an_sql_error_prints_the_database_error_and_exits_1_ac_195_4`, `::test_a_query_over_60_seconds_is_reported_as_cancelled_ac_195_4`, `::test_a_kubectl_timeout_is_reported_as_cancelled_too_ac_195_4` (and the env, type, not-ready, secret and state-file cases) | `scripts/cplat/dbquery.py:117-141` (checks 1–6c), `:210-216` (6d copy list or none), `:220-236` (checks 7–8), `:162-175` (timeout, SQL error, no-ERROR mapping), `:26` (`statement_timeout 60s`) | The `refused` helper asserts exit 1, empty stdout, `ERROR:` and `fix:`, an unchanged tree, no kube writes and, for the checks that run before the database, no exec. |
| AC-195.5 | met | `::test_restore_prints_the_query_command_as_the_check_step_ac_195_5`, `::test_no_output_of_a_restore_names_kubectl_ac_195_5`, `::test_a_dry_run_and_the_json_report_of_a_restore_name_no_kubectl_ac_195_5`; `tests/cplat/test_backup_117_restore.py:233-234`; `tests/e2e/run.sh:2334-2335` | `scripts/cplat/dbrestore.py:399` (check line), `:330` (`else applied directly`) | The exact line `check it: /resource:query orders-db --env dev --copy g1 "SELECT …"` is asserted, and `kubectl` is absent from text, dry-run and JSON output. |

## Non-goals

- No write mode, interactive session, file import/export or multi-statement script support: multi-statement input is refused (`dbquery.py:137`). ✔
- Only database resources: caches, buckets and brokers are refused (`dbquery.py:124`). ✔
- `/resource:restore` gained no `--check` option. ✔
- No template-owned layout changed. `templates/gitops-app/CLAUDE.md.jinja` gains one task-table row, as plan t3 asks; no header, footer or navigation changed. ✔

## Deviations from the plan

- Every task is `done: true`, and every touched spec-195 file is in a task's `files`. The 194/148 files in the diff come from the merge of main and are not part of this build.
- `docs/rules/plugins/resource/commands/restore.yml` is listed in t3 but unchanged. Acceptable: no rule sentence of `restore.md` changed.
- `register.yml` raised the prompt baseline by 1081 bytes through `rebaseline`, with benchmark runs recorded, as t3 allows. Commit b3cf3b81 then shortened the `query.md` description to stay under it after the merge of main. Acceptable.
- Test fixture fix in `test_195_resource_query.py` (the previous g1 copy gets `from.server`), approved by the user. The assertions are unchanged. Acceptable.

## Contract

The build matches `design.md`:
- The checks run in the specified order, with their messages and fixes, and no kubectl call happens before check 7.
- There is one `backupstate.kubectl` exec, with `POD_SCRIPT`, the password on stdin and `timeout=90`.
- Errors are mapped to the four specified cases.
- The text and JSON output match the specified formats.
- The `count_statements` lexer is implemented as specified.
- The restore lines match the contract.

## Mutation check (report only)

Skipped: no mutation check for shape platform yet.
