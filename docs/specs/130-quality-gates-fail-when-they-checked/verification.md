# Verification — 130 Quality gates fail when they checked nothing

**Result:** pass
**Commit:** c39b733 · **Base:** ed4fa3b6 · **Trace:** 16/16 criteria named by tests

Tests: `E` = `tests/cplat/test_130_empty_gates.py`, `G` = `tests/cplat/test_130_gate_sh.py` (stubs in `tests/cplat/gates130_support.py`).
Local CI (`devbox run ci`) green; acceptance tests unchanged since the red commit df0350f except ecacac4 (maintainer-approved: the
AC-130.5 package.json check also strips `{% %}` before `json.loads`; assertions unchanged).

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-130.1 | met | `E::test_a_covered_gate_that_checked_nothing_exits_non_zero_with_the_line_ac_130_1` (all 7 templates x every covered gate; `assert_red` requires the exact line and exactly one `checked nothing` line); `G::test_nothing_prints_the_line_to_stderr_and_exits_1_ac_130_1` (stderr equals the line, stdout empty, also under /bin/bash); `G::test_the_source_has_no_jinja_syntax…`, `G::test_every_template_carries_a_byte_identical_copy_ac_130_1`, `E::test_every_template_ships_gate_sh_byte_identical_to_the_source_ac_130_14` (rendered copy == source) | `templates/gitops-app/scripts/gate.sh:18-21`, `:94-97`, `:110`; `templates/gitops-app/scripts/render.py:3504-3508`; `templates/cluster-gitops/scripts/render.py:277` | No `{{`, `{%`, `{#` in gate.sh; 6 copies `cmp`-identical; kept by `scripts/sync-template-copies.py:20-23` |
| AC-130.2 | met | `E::test_pytest_exit_5_no_tests_collected_is_passed_through_with_the_line_ac_130_2` (code=5), `E::test_pytest_reporting_no_tests_with_exit_0_still_fails_ac_130_2`, `E::test_the_fix_names_adding_a_test_ac_130_2`, `E::test_test_and_test_fast_run_through_the_gate_helper_as_the_contract_says_ac_130_2` | `gate.sh:63-68` (`--junitxml` appended, exit 5 = no tests), `:96` (passes rc through); `templates/service-python/devbox.json:17-18`, `templates/library-python/devbox.json:16-17` | |
| AC-130.3 | met | `E::test_go_packages_without_test_functions_fail_with_the_line_ac_130_3` (stub prints both `[no test files]` and `[no tests to run]`), `E::test_go_recipes_run_verbose…`, `G::test_tests_counts_what_ran…[go-*]` | `gate.sh:76-81`; `templates/service-go/devbox.json.jinja:16-17` (`go test -v`) | real `go test` negative run only in PR CI (ci.yml:522) |
| AC-130.4 | met | `E::test_maven_without_test_methods_fails_with_the_line_ac_130_4`, `E::test_a_stale_surefire_report_does_not_count…`, `E::test_no_java_recipe_or_pom_skips_the_test_phase_ac_130_4`, `G::test_failsafe_reports_count_for_maven_ac_130_4` | `gate.sh:69-75` (removes stale reports, sums surefire+failsafe JUnit); `templates/service-java/devbox.json.jinja:17-18` (no `-DskipTests`) | real Maven negative run only in PR CI (ci.yml:594) |
| AC-130.5 | met | `E::test_a_web_repo_without_test_files_fails_with_the_line_ac_130_5` (nofiles + zero), `E::test_the_web_gate_asks_vitest_for_its_json_report_ac_130_5`, `E::test_no_web_script_or_config_passes_with_no_tests_ac_130_5`, `E::test_vitest_config_writes_the_json_report_only_under_the_gate_ac_130_5`, `G::test_a_cached_or_missing_vitest_report_counts_zero_ac_130_5` | `gate.sh:82-88`; `templates/web-nextjs/vitest.config.mts:7,16`; `templates/web-nextjs/devbox.json.jinja:17-18` | Vitest's own stderr is merged into stdout under the gate (plan t1 says so); the real "No test files found" text / JSON report is proven only by PR CI (ci.yml:431) |
| AC-130.6 | met | `E::test_a_run_where_every_collected_test_was_skipped_fails_ac_130_6` (5 templates x 2 gates), `E::test_some_skipped_tests_next_to_a_test_that_ran_still_pass_ac_130_6`, `G::test_tests_counts_what_ran…[*-skipped]` | `gate.sh:30-32` (tests − skipped), `:79` (only PASS/FAIL lines), `:86` (passed + failed only) | |
| AC-130.7 | met | `E::test_gitops_app_validate_with_zero_resources_fails_with_the_line_ac_130_7` (validate and test), `E::test_gitops_app_validate_fix_text_is_the_contract_ac_130_7`, `E::test_gitops_app_validate_counts_what_kubeconform_reports…`, `E::test_gitops_app_recipes_follow_the_contract_ac_130_7` | `templates/gitops-app/devbox.json:29` (`n` = `^kind:` lines of each kustomize build + kubeconform `Summary: N resource`; `n=0` → gate.sh line, exit 1, before `check-policies.sh`) | Happy path still runs render check, plan validate, label check, every kustomize build, every kubeconform file, check-policies. The `kubeconform -strict … ${SERVICE_CRD_SKIP:+-skip "$SERVICE_CRD_SKIP"} … -summary "$f"` text is contiguous and unchanged |
| AC-130.8 | met | `E::test_cluster_gitops_empty_build_keeps_failing_prints_the_summary_and_the_line_ac_130_8` (non-zero, `Summary: 0 resource` on stdout, the line), `E::test_cluster_gitops_validate_fix_text_is_the_contract_ac_130_8`, `E::test_cluster_gitops_invalid_resources_still_fail_without_the_empty_line_ac_130_8`, `E::test_cluster_gitops_recipes_follow_the_contract_ac_130_8` | `templates/cluster-gitops/devbox.json:23` | Exit (`rc=1`) and `cat "$dir/report"` unchanged; the #278 text `validate: kubeconform checked 0 resources` is replaced by the AC-130.1 line (design decision 8, matches the amended AC) |
| AC-130.9 | met | `E::test_gitops_app_render_check_without_a_system_fails_with_the_line_ac_130_9`, `E::test_cluster_gitops_render_check_comparing_zero_files_fails_with_the_line_ac_130_9` (both: line, no `OK: up to date`, for render-check and test-fast), `E::test_validate_names_itself_in_the_line_of_its_render_check_ac_130_9`, `E::test_gitops_app_validate_stops_at_its_first_failing_step_ac_130_9`, `E::test_render_check_of_a_fresh_render_still_says_up_to_date_ac_130_9` | `templates/gitops-app/scripts/render.py:3523-3527`, `:3579-3581` (+ identical `templates/cluster-gitops/scripts/system_render.py`); `templates/cluster-gitops/scripts/render.py:275-278`; `GATE_NAME=` in `templates/gitops-app/devbox.json:29,34` and `templates/cluster-gitops/devbox.json:23,28` | Write mode keeps `ERROR: no applications/*/system.yaml found` |
| AC-130.10 | met | `E::test_secrets_scan_with_nothing_to_scan_fails_and_never_runs_the_scanner_ac_130_10` (all 7), `E::test_secrets_scan_where_the_exclusions_leave_no_file_fails_ac_130_10`, `E::test_secrets_scan_fix_text_is_the_contract_ac_130_10`, `E::test_the_secrets_scan_recipe_keeps_the_scanner_flags_literally_ac_130_10`, `G::test_files_*` (incl. not-a-git-repo → git's exit 128, no line) | `gate.sh:102-111`; secrets-scan recipe in each `devbox.json[.jinja]` (service-python:27, library-python:25, service-go:25, service-java:26, web-nextjs:27, gitops-app:37, cluster-gitops:29) | Same pathspec as the scan |
| AC-130.11 | met | `E::test_composites_turn_red_when_their_gate_checked_nothing_ac_130_11` (ci, security for all 7; quality for gitops), `E::test_composites_chain_their_gates_with_and_and_nothing_swallows_a_failure_ac_130_11` | Composites unchanged and `&&`-chained (e.g. `templates/service-go/devbox.json.jinja:30`) | Design decision 9 |
| AC-130.12 | met | `E::test_a_covered_gate_with_input_passes_as_before_ac_130_12` (every template x gate), `E::test_a_failing_test_keeps_failing_without_the_empty_line_ac_130_12`, `E::test_a_broken_runner_is_not_reported_as_add_a_test_ac_130_12` (exit 3 kept, no line), `E::test_extra_arguments_reach_the_runner_unchanged…`, `E::test_each_test_running_template_ships_at_least_one_test_ac_130_12`, `E::test_secrets_scan_with_files_runs_the_scanner_and_passes_ac_130_10`, `G::test_temporary_files_are_removed_on_exit_ac_130_12`, `G::test_the_helper_runs_under_every_bash_the_platform_targets_ac_130_12` (/bin/bash 3.2 on macOS) | `gate.sh:91-99` | Real-runner positive runs: python verified locally; go, java, web, gitops `test-fast` run in PR CI (t4) |
| AC-130.13 | met | `E::test_no_environment_variable_makes_an_empty_gate_pass_ac_130_13` (15 candidate variables, 9 gate/template pairs), `E::test_no_recipe_argument_makes_an_empty_gate_pass_ac_130_13`, `E::test_no_recipe_contains_a_switch_that_skips_the_check_ac_130_13`, `G::test_no_environment_variable_changes_the_outcome_of_nothing_ac_130_13`, `G::test_no_argument_before_the_separator_is_an_opt_out_ac_130_13` | `gate.sh` reads only `TMPDIR` (temp dir) and overwrites `VITEST_GATE_REPORT` (`:83`); `GATE_NAME` in render.py only names the gate | Runner-side tricks (`MAVEN_ARGS=-DskipTests`, `GOFLAGS=-run=NONE`, `-p no:junitxml`) yield 0 counted and therefore fail |
| AC-130.14 | met | `E::test_the_coverage_table_names_exactly_the_templates_of_the_shape_registry_ac_130_14` (COVERED == shapes.yml templates == templates on disk), `E::test_every_covered_gate_is_a_recipe_of_the_rendered_template_ac_130_14`, `E::test_a_covered_gate_that_checked_nothing…` (renders each template, stub tools first on PATH) | `tests/cplat/gates130_support.py:32-35` (coverage table), `:202-213` (stubs) | |
| AC-130.15 | met | `E::test_the_guides_state_the_rule_and_point_to_the_platform_test_ac_130_15` (CONTRIBUTING.md, docs/templates.md) | `CONTRIBUTING.md:85`; `docs/templates.md:21` | |
| AC-130.16 | met | `E::test_the_files_that_change_are_platform_owned_so_an_update_applies_them_ac_130_16`, `E::test_the_changelog_lists_the_behaviour_change_with_symptom_and_fix_ac_130_16`, `E::test_the_release_is_a_minor_no_plugin_or_marketplace_major_bump_ac_130_16` | `docs/CHANGELOG.md:9` (under `[Unreleased]`, the next release 5.5.0) | Checked every `_skip_if_exists` by hand: none matches `devbox.json`, `scripts/gate.sh`, `scripts/render.py`, `scripts/system_render.py` or `vitest.config.mts` (cluster-gitops skips only `cluster/**`, `cluster.yaml`). The changelog names the symptom, the fixes, no opt-out, #285, `-v` for Go, gitops-app validate stopping early, and the `--reporter` caveat |

## Review points from the orchestrator

- **gate.sh.** Exactly one line on stderr from the helper (`G::test_nothing_prints…` asserts equality of stderr). Broken runner →
  runner's exit, no line (`gate.sh:99`; tests in both files with exit 3/4). No opt-out (above). Bash 3.2: only `local`, `PIPESTATUS`,
  `$(( ))`, heredoc; no `${#…}`, no arrays beyond `PIPESTATUS`, exercised under macOS /bin/bash. No Jinja tokens; 7 files byte-identical.
- **gitops-app validate.** Each step now ends in `|| exit 1`; on the happy path the same steps run in the same order as before.
  Kubeconform output is captured and printed after the run instead of streamed (cosmetic). Minor, not blocking: if kubeconform exited 0
  without a `Summary:` line, `$((n + ))` would be an arithmetic error; with `-summary` it always prints one.
- **cluster-gitops validate.** #278 exit and printed summary kept; message text replaced per design decision 8.
- **t4 workflow.** Each negative step asserts non-zero exit (`if sh -c …; then …; exit 1; fi`) and the exact line with `grep -Fx` on
  stderr (ci.yml:260, 431, 522, 594). Java negative runs on the first matrix entry only (`matrix.observability && !matrix.database`,
  ci.yml:595, matching `{observability: true, database: false}`). The service-python job keeps the spec 091 `SMOKE_BASE_URL is not set`
  assertion. Only the python jobs were run locally; go, java, web and gitops jobs are proven by the PR's CI, which must be green before
  merge.

## Non-goals

`lint`, `typecheck`, `audit` recipes unchanged in all 7 templates (the java `typecheck` keeps its own `-DskipTests`). No opt-out, no
minimum counts beyond "at least one", no test added to repos by `/platform:update`. ✔

## Deviations from the plan

- `templates/cluster-gitops/scripts/render.py:275`: the 0-files check runs before the drift check, design says after. Only differs
  when nothing renders but stale files exist (then the line instead of the drift list); still red with a fitting message. Acceptable.
- `scripts/sync-template-copies.py:22,27`: pairs whose source is missing are skipped silently (planned, for the sandbox tests); a deleted
  gate.sh source would also stop the copy check, but `G::test_every_template_carries_a_byte_identical_copy_ac_130_1` still catches that.
  Acceptable.
- `gate.sh:84` merges Vitest's stderr into stdout under the gate (plan t1 says "combined output for vitest"). Acceptable.
- Files outside every task's `files`: the acceptance tests and support module (tester, before t1), `docs/adr/074-…` (added with the
  plan, 713b93c), spec/plan/design. Acceptable. All five tasks `done: true`.

## Contract

Matches `design.md`: line format and the six fix texts, `gate.sh` subcommands, exits and per-runner counting, recipe texts
(`E::test_test_and_test_fast_run_through_the_gate_helper_as_the_contract_says_ac_130_2`, gitops/cluster recipe tests),
`GATE_NAME` default `render-check`, Vitest reporters only under `VITEST_GATE_REPORT`. ✔
