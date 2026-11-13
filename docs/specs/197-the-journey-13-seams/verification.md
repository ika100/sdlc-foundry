# Verification — 197 The journey 13 seams

**Result:** pass
**Commit:** 01974858 · **Base:** a7a5d005 · **Trace:** 8/8 criteria named by tests (missing: none)

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-197.1 | met | `tests/cplat/test_197_seams.py::test_the_reviewed_step_finds_the_testers_commit_ac_197_1` (en dash, hyphen, old form), `::test_another_specs_or_an_unnamed_acceptance_commit_is_refused_ac_197_1` (AC-008., AC-0071., unnamed) | `scripts/cplat/testreview.py:37` (`_acceptance`), `scripts/cplat/testreview.py:88` | Asserts exit 0, the exact reviewed subject and parent = previous HEAD; refusal asserts exit 1, the existing error text and an unchanged HEAD. `(?<![\w-])AC-<NNN>\.` guards the AC-0071 case. |
| AC-197.2 | met | `test_197_seams.py::test_a_deviation_naming_a_merged_task_is_recorded_on_the_target_ac_197_2`, `::test_a_chain_of_merges_resolves_to_the_last_task_ac_197_2`, `::test_an_id_that_is_no_plan_or_merged_task_still_warns_ac_197_2` | `scripts/cplat/runs_agents.py:462` (`_merged_into`), `:472` (`_resolve`), `:511` | Asserts task, tasks, note text, no WARNING, `complete is True` with no problems; chain resolves to t3; unknown id and chain ending outside the plan warn `malformed: deviation` and mark incomplete. `cplat plan merge` writes the event via `scripts/cplat/plancmd.py:148`. |
| AC-197.3 | met | `test_197_seams.py::test_the_grafana_helpers_follow_the_local_port_rule_ac_197_3`, `::test_a_local_environment_gets_the_grafana_url_line_ac_197_3` (real + dry run), `::test_the_grafana_url_follows_the_local_http_port_ac_197_3`, `::test_json_carries_the_grafana_url_ac_197_3` (real + dry run), `::test_a_second_identical_call_still_reports_the_url_ac_197_3`, `::test_a_non_local_environment_says_where_grafana_answers_ac_197_3`, `::test_a_given_host_decides_local_or_not_ac_197_3`, `::test_no_grafana_line_when_the_stack_is_turned_off_ac_197_3` (none, off) | `scripts/cplat/model.py:436` (`local_port`, shared with `_url`), `:442` (`grafana_url`), `scripts/cplat/systemset.py:134-141`, `:152`, `:170`, `:209` | Exact line `Grafana: http://grafana.localhost:8088/` and port 9090 via LOCAL_HTTP_PORT; JSON `grafana_url` URL / null; no line for none/off. |
| AC-197.4 | met | `test_197_seams.py::test_the_observability_cell_names_the_grafana_location_ac_197_4`, `::test_an_environment_without_ui_lgtm_has_no_grafana_location_ac_197_4`, `::test_the_table_prints_the_grafana_location_ac_197_4`; `tests/cplat/test_model_callers.py` (STATUS_RESOURCES) | `scripts/cplat/status.py:297-304`, `scripts/cplat/status.py:419-420` | JSON URL for the local env, null for the non-local one, no key for `ui: none`; table prints both locations. |
| AC-197.5 | met | `tests/cplat/test_197_release_version.py::test_the_documented_version_step_runs_on_a_dirty_release_branch_ac_197_5` (untracked + modified changelog) | `plugins/web/agents/release.md:64`, `:67`; `docs/rules/plugins/web/agents/release.yml` (R10) | Extracts and runs the step's line unchanged with the template's pinned pnpm on a `release/v0.3.0` branch; asserts exit 0, version, no tag, no new commit. Skips with a stated reason where pnpm cannot be fetched (A6). |
| AC-197.6 | met | `tests/cplat/test_197_test_limits.py::test_a_hung_test_fails_with_id_and_limit_and_the_others_run_ac_197_6`, `::test_the_shipped_limit_is_120_seconds_ac_197_6`, `::test_a_suite_without_a_hung_test_is_unchanged_ac_197_6`, `::test_the_timer_and_handler_are_restored_after_each_test_ac_197_6`, `::test_gate_sh_loads_the_pytest_plugin_through_the_environment_ac_197_6`, `::test_gate_sh_sets_the_pytest_plugin_without_old_values_ac_197_6`, `::test_gate_sh_leaves_pytest_alone_without_the_plugin_file_ac_197_6`, `::test_gate_sh_sets_the_junit_timeout_for_maven_ac_197_6` | `templates/service-python/scripts/pytest_limit/platform_test_limit.py:18`, `:54-70`; `templates/gitops-app/scripts/gate.sh:63-83` (+ synced copies); recipes `templates/{service-python,library-python}/devbox.json:16-18`, `templates/service-java/devbox.json.jinja:17-18` run through gate.sh | Python: setup/body/teardown hangs fail with test id and limit, neighbours pass, exit 1, clean suite unchanged. Java: the test proves the 120 s JUnit property reaches `MAVEN_ARGS` (Maven 3.9.16 pinned, reads it); the JUnit report itself rests on toolchain behaviour (see departure). |
| AC-197.7 | met | `test_197_test_limits.py::test_gate_sh_sets_the_go_package_timeout_ac_197_7`, `::test_gate_sh_adds_nothing_for_vitest_ac_197_7` | `templates/gitops-app/scripts/gate.sh:78-81`; `templates/service-go/devbox.json.jinja:16-17` run through gate.sh | `GOFLAGS=-timeout=5m` (appended to an existing GOFLAGS); the panic/test-name output and non-zero exit are go test's own behaviour (see departure). |
| AC-197.8 | met | `test_197_test_limits.py::test_the_limits_travel_in_platform_owned_files_only_ac_197_8` (4 templates), `::test_the_plugin_ships_in_both_python_templates_without_jinja_syntax_ac_197_8`, `::test_the_sync_script_covers_the_plugin_copy_ac_197_8`, `::test_gate_sh_keeps_a_limit_the_java_repo_sets_itself_ac_197_8` (5 places), `::test_gate_sh_keeps_a_go_timeout_the_repo_sets_ac_197_8`, `::test_a_test_with_a_timeout_marker_keeps_its_own_limit_ac_197_8`, `::test_a_handler_another_tool_owns_is_left_alone_ac_197_8`, `::test_a_repo_with_pytest_timeout_configured_keeps_it_ac_197_8` | `scripts/sync-template-copies.py:21-22`; `templates/gitops-app/scripts/gate.sh:72-75`, `:79`; `platform_test_limit.py:21-51` | Build files stay in `_skip_if_exists` and unchanged; gate.sh and the plugin are not skipped, so `/platform:update` carries them; a repo's own limit wins. The pytest-timeout case skips where pytest-timeout is not installed. |

Departure: AC-197.6 (Java) and AC-197.7 are judged `met` though the tests stop at the environment gate.sh hands the runner, not a real Maven/Go run, because the remaining outcome is the documented behaviour of the pinned toolchains (Maven 3.9 `MAVEN_ARGS`, Surefire user-property propagation, JUnit `timeout.default`; `go test` honouring `-timeout` in GOFLAGS), and a real hung-test run would cost minutes per test.

## Non-goals

No change to the tester prompts, `units.py`, `testdiff_select.py` or `spec.py`; no re-plan deviation handling; no public Grafana or credentials; no other shape's release agent; `web-nextjs/scripts/gate.sh` changed only as a synced copy and adds nothing for vitest; no stray-process handling. No template-owned layout (header, footer, navigation) touched. ✔

## Deviations from the plan

- `tests/cplat/test_model_callers.py` changed though in no task's `files`: its STATUS_RESOURCES expectation now carries the AC-197.4 `grafana_url` cells (and an observability cell for prod, which now has `ui: lgtm`); acceptable, the expected consequence of AC-197.4.
- `tests/cplat/test_197_release_version.py` changed after the freeze (shim fakes take the shared AC-178.5 prelude, same assertions), with user approval; acceptable.
- `plugins/web/agents/release.md` lost three clauses to stay inside the byte budget ("prepend above the previous entry", the one-off recipe sentence, "pnpm's lock file does not record it"); acceptable per the plan's t4 notes; `cplat platform rules check` is green per Phase 3.
- All tasks `done: true`; every other touched file lies in a task's `files`.

## Contract

Matches `design.md` (`_acceptance` subject rule, merge resolution and note text, `GRAFANA_HOST`/`GRAFANA_ELSEWHERE`/`local_port`/`grafana_url`/`grafana_location`, the `grafana_url` JSON key presence rules, the gate.sh table, plugin message `Timeout (>120s): <nodeid> ran past the per-test limit of 120 s`). ✔

## Unresolved test-review findings

None (3 findings raised, all resolved).

## Mutation check (report only)

Skipped: no mutation check for shape platform yet.
