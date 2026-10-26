# Verification — 112 Fast cplat test job: shared renders and sharding

**Result:** fail
**Commit:** e5df54a · **Base:** e3c3d54 (spec diff reviewed against merge base aea8114 after merging origin/main) · **Trace:** 15/15 criteria named by tests (`tests/cplat/test_fast_suite_112.py`)

The PR's own ci run (40319270163, head e5df54a) shows a real defect: shard 4/4 errored with
`shutil.Error ... shared-renders0/render-1/todo-gitops/.git/objects/maintenance.lock: No such file or directory`
in setup of `test_alerts_render.py::test_an_invalid_rule_fails_the_render_naming_the_rule_and_the_problem[rules1-...]`
(git 2.55 on the runner). The `git commit` in a shared build starts git's detached auto-maintenance. That process
keeps changing the shared source's `.git` while `SharedRenders.copy` runs `shutil.copytree` on it. So the shared render
does not "stay as rendered", and copying from it is a race that makes CI flaky. Before this change each test owned its
repo, so the background maintenance never raced with a copy.

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-112.1 | met | `test_shards_partition_the_suite_ac_112_10` (union line 348), `test_no_skip_xfail_or_deselect_is_added_by_the_new_support_code_ac_112_1` | `tests/cplat/sharding.py:63-70` (deselects only under `--shard`) | measurements.md: 2470 → 2511 ids, the diff is the 41 new tests, which the PR description names. The CI cover job says `OK: 2627 tests ran in exactly one of 4 shards` (= 2620 passed + 7 skipped after the merge). The migrated fixture diffs change no assertion. Fixture scope went from module to function in `fleet_world.py:29` and `test_generated_repos.py:30-42`, which isolates more, not less. One cosmetic change: the commit message of `app` in `test_staging_093_setting.py` went from "compose" to "service", and no test reads it. |
| AC-112.2 | not met | `test_every_test_gets_its_own_copy_and_the_render_stays_as_rendered_ac_112_2`, `test_copy_destination_rules_ac_112_2`, `test_new_service_gives_private_copies_of_one_render_ac_112_2`, `test_service_key_ac_112_2` | `tests/cplat/shared_render.py:54`, `tests/cplat/conftest.py:101-120`, `tests/cplat/test_gitops.py:38-50` | Copies are private, and the tests prove it for files, symlinks and `git add`. But the shared source is not stable: a detached `git maintenance` from the build's commit (`newsvc.py:209`, `test_gitops.py:116` via `composed_todo_api`) keeps writing to `<source>/.git` while `copytree` (`shared_render.py:54`) copies it. CI run 40319270163, shard 4/4, failed on this. **Fix hint:** turn off auto-maintenance/gc while a shared build runs, for example `GIT_CONFIG_COUNT`/`GIT_CONFIG_KEY_n`/`GIT_CONFIG_VALUE_n` with `maintenance.auto=false` and `gc.auto=0` in the build's environment, or `git config` on the source after the build plus waiting for maintenance. That keeps the content of the copied repo unchanged. Add a test that commits in a build and then copies many times. |
| AC-112.3 | met | `test_reverse_order_and_single_file_runs_need_no_shared_state_ac_112_3` (unit level) | `tests/cplat/shared_render.py:44-55` | The suite-level evidence is in measurements.md: the reverse run (pytest-reverse) passed, 2504 passed / 7 skipped, and each of the 101 files passed on its own. The acceptance test only checks the cache at unit level, so the measurement carries the criterion. |
| AC-112.4 | met | `test_render_subject_tests_still_render_from_the_template_ac_112_4`, `test_the_render_tests_of_the_smoke_091_file_keep_newsvc_main_ac_112_4`, `test_new_service_matches_what_newsvc_renders_ac_112_4`, `test_new_service_refuses_argv_it_cannot_share_ac_112_4` | `tests/cplat/test_smoke_091_templates.py:295-296` (still `newsvc.main`), `tests/cplat/shared_render.py:60-63` | `test_newsvc.py`, `test_java_database.py`, `test_ci_extra.py:232` and `test_spec_driven.py:300` still call `newsvc.main`. The equality test compares file lists only, not contents, which is weaker than "equivalent content" in the contract but enough here, because the build is `newsvc.main` itself (`conftest.py:112`). |
| AC-112.5 | met | `test_a_new_shared_renders_builds_again_never_reusing_an_earlier_run_ac_112_5`, `test_the_session_cache_lives_only_in_the_runs_basetemp_ac_112_5` | `tests/cplat/conftest.py:93-97` (`tmp_path_factory.mktemp`), `tests/cplat/test_generated_repos.py:27` | The build renders from `PLATFORM_ROOT/templates` in the working tree. ci.yml has no `actions/cache`. |
| AC-112.6 | met | `test_a_failed_render_errors_every_dependent_with_its_message_ac_112_6`, `test_systemexit_and_a_non_directory_result_are_failures_ac_112_6`, `test_render_failure_message_keeps_only_the_last_20_output_lines_ac_112_6` | `tests/cplat/shared_render.py:32-48`, `conftest.py:113-114` (non-zero exit is a failure) | Most dependents call it from a fixture, so they error in setup. Those that call `new_service` in the test body (`test_rename_migration.py:13`, `test_update_doctor.py:104,111,163,193,301`) are reported as *failed* rather than *error*, still with the render's message, and never pass or skip. That is acceptable. |
| AC-112.7 | met | `test_tests_that_only_need_a_rendered_repo_get_a_shared_copy_ac_112_7` | the migrated fixtures, see design "Modules" | measurements.md: setup 479.2 s → 211.4 s (44%, target ≤ 239.6 s), same machine and command. |
| AC-112.8 | met | `test_a_render_happens_once_per_key_and_process_ac_112_8`, `test_new_service_gives_private_copies_of_one_render_ac_112_2` (line 260) | `tests/cplat/shared_render.py:45-46` (`builds[key]` set before the build, line 30) | The gitops key is shared by `gitops_repo` and the inner build of `composed_todo_api`. |
| AC-112.9 | pending | `test_ci_runs_the_cplat_tests_in_four_shards_ac_112_10` (line 541, shards start right after `changes`) | `.github/workflows/ci.yml:139-160` | A post-merge human step by design (plan `human_steps`). The first sample, run 40319270163, had not finished when this was written (smoke-java/web jobs still running), and that run touches templates' smoke paths anyway. Not judged as failed. |
| AC-112.10 | met | `test_shards_partition_the_suite_ac_112_10`, `test_xdist_run_selects_and_reports_like_a_serial_one_ac_112_10`, `test_check_shards_*_ac_112_10` (8 tests), `test_ci_checks_shard_coverage_in_every_run_ac_112_10`, `test_ci_uploads_each_shard_report_even_when_the_shard_fails_ac_112_10` | `tests/cplat/sharding.py:58-71,108-130`, `scripts/check-shards.py:31-78`, `.github/workflows/ci.yml:142-182` | Live: 4 shard jobs ran, and the cover job printed `OK: 2627 tests ran in exactly one of 4 shards` even though shard 4 failed. |
| AC-112.11 | met | `test_a_new_test_file_lands_in_a_shard_without_any_list_ac_112_11` | `tests/cplat/sharding.py:63-65` (round-robin over sorted node ids) | ci.yml has no file list. |
| AC-112.12 | met | `test_shards_are_balanced_and_spread_each_file_ac_112_12` | `tests/cplat/sharding.py:65` | Pytest step times from run 40319270163: shard 1 63 s, shard 2 46 s, shard 3 35 s, shard 4 46 s. Average 47.5 s, slowest/average 1.33 (≤ 1.5), slowest 63 s (≤ 75 s). measurements.md still has the placeholder table. |
| AC-112.13 | met | `test_a_failing_test_fails_its_shard_and_is_named_but_not_the_others_ac_112_13`, `test_ci_failure_in_one_shard_does_not_cancel_the_others_ac_112_13` | `.github/workflows/ci.yml:144` (`fail-fast: false`), name at `ci.yml:139` | Proved live by run 40319270163: shard 4/4 failed, shards 1–3 ran to the end (657, 657, 655+2 skipped), and the log names the failing test. |
| AC-112.14 | met | `test_ci_success_needs_every_shard_result_ac_112_14` | `.github/workflows/ci.yml:598,606` | Static check. The `failure`/`cancelled` rule is unchanged, and skipped jobs count as passed. The live `ci-success` of run 40319270163 was still pending, and it should fail because of shard 4. |
| AC-112.15 | met | `test_without_shard_everything_runs_and_nothing_is_written_ac_112_15`, `test_shard_option_validation_ac_112_15`, `test_the_real_suite_conftest_offers_the_shard_options_ac_112_15`, `test_local_ci_runs_the_suite_unsharded_ac_112_15` | `tests/cplat/sharding.py:41-47` (no-op without `--shard`), `tests/cplat/conftest.py:8-17` | No new env var, marker or flag. The suite passed with `-n auto` locally (2620 passed / 7 skipped). |

## Changes to the acceptance tests after the red commit (both approved by the user)

- **68c55c9**: removes only the body of `test_a_fresh_web_repo_has_the_playwright_scaffold_by_default_ac_091_16` from the
  AC-112.7 "no `newsvc.main`" check, by an exact top-level `def` match. It also fixes the AC-112.4 body slice to end at the
  next top-level statement. The exclusion is one named function, and AC-112.4 still requires `newsvc.main` in that body.
  It resolves a real contradiction between the two criteria. **Not weakened.** (The only other `newsvc.main` in that file is
  the import, line 23, which the check does not match.)
- **e5df54a**: `--shard VALUE` → `--shard=VALUE` in `test_shard_option_validation_ac_112_15`. The same six bad values, the
  same exit code 4 and the same message are asserted. Only the argv spelling changed, so that argparse on Python < 3.14
  does not read `-1/4` as an option. **Not weakened.**

Remaining weaknesses in the acceptance file (not caused by the changes above):
- Line 508: `assert code == 1 and "... (4 vs 3)" in out or "(3 vs 4)" in out`. Operator precedence lets the `or` branch
  pass without checking `code`. The implementation is right (`check-shards.py:40-42`), so the impact is small.
- Line 548 asserts `" -x" not in` the whole `platform-tests` step text. That forced the unrelated edit
  `tar -xzf` → `tar xzf` (see Deviations).

## Non-goals

- No file under `templates/` changed. ✔
- No test selection by diff, and no test is skipped or deselected outside `--shard`. ✔
- e2e workflow, smoke jobs, CodeQL and site unchanged (the only edits in ci.yml are in `platform-tests`, the new
  `platform-tests-cover` and `ci-success.needs`). ✔
- No cross-run caching: no `actions/cache`, and the cache lives under `basetemp` (`conftest.py:96`). Shard artifacts carry
  only reports, with `retention-days: 1`. ✔
- No test rewritten except in how it gets its repos. ✔

## Isolation of a copied render

- `.copier-answers.yml`: `_src_path` is rewritten to `gh:ika100/sdlc-foundry/templates/<t>` (`newsvc.py:193`). Nothing
  depends on the destination. The direct copier renders in `test_generated_repos.py` record the platform's template
  path, not the destination, as before.
- `.git`: a plain `git init` plus a commit leaves no absolute path in `.git/config`, and `--skip-tasks` runs no bootstrap
  tasks. `newsvc` resolves `target` (`newsvc.py:87`) only for the render. ✔
- **Not isolated:** the background git maintenance started in the shared source (AC-112.2 above).
- Risk (no failure seen): a shared build runs inside the first test that asks for it, under that test's monkeypatches.
  The migrated fixtures patch nothing that `newsvc` reads before they call `new_service`. `composed_todo_api` patches
  `compose.gh`/`promote.gh` only inside `MonkeyPatch.context()`.

## Deviations from the plan

- `.github/workflows/ci.yml:132,156`: `tar -xzf` → `tar xzf` in the Kyverno install steps (one in the
  `validate-shapes` job, one in `platform-tests`). It is in task t5's file but is not part of the contract. It was
  made only to satisfy the overbroad `" -x"` assertion. GNU tar treats both the same. Acceptable, but the assertion
  should be narrowed to the pytest step.
- Plan task `m1` has no `done: true`, and measurements.md still shows placeholder rows for AC-112.12 and the AC-112.9
  first sample. The numbers are in this report. Not acceptable as final: fill them in before shipping.
- The PR description quotes the pre-merge numbers (2504 passed, 2511 ids). After merging main it is 2620 + 7. Update it.
- `tests/cplat/test_ci_templates.py` still renders with copier per test (`_render`, line 37) and is not in the design's
  module list. Acceptable, because AC-112.7 is met on the numbers.

## Contract

Mostly matches `design.md`: the `SharedRenders`/`RenderFailed`/`service_key` signatures and messages, the `--shard`/
`--shard-report` options and `UsageError` texts, the report JSON, the `check-shards.py` messages and exit codes, the ci job
names, `needs`/`if`, the artifact settings and the order of `ci-success.needs`. One deviation:
- The design says "the terminal header shows `shard I/N: <kept> of <collected> tests`". It comes from
  `pytest_report_collectionfinish` (`sharding.py:74-78`), which shows it in serial runs (the test checks this), but the
  xdist controller does not collect, so the CI shard logs have no such line. This is minor and no criterion depends on it.

## Bug report for the coder

AC-112.2: `SharedRenders.copy` copies a source repo whose `.git` is still being changed by git's detached
auto-maintenance, which a shared build's `git commit` starts. CI run 40319270163, job "cplat unit + integration tests
(shard 4/4)":
`shutil.Error: [('.../shared-renders0/render-1/todo-gitops/.git/objects/maintenance.lock', ..., "[Errno 2] No such file or directory")]`.
Make shared builds run with auto-maintenance and auto-gc off (for example `GIT_CONFIG_COUNT=2`,
`maintenance.auto=false`, `gc.auto=0` in the environment while `build()` runs, in `shared_render.py:_build` or the
`new_service`/`composed_todo_api` builds). Add a regression test that commits during a build and copies the result
many times.
