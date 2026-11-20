# Verification — 209 Inline scripts add no uv environment per worktree

**Result:** pass
**Commit:** 00ea4f28 · **Base:** e642dd43 · **Trace:** 7/7 criteria named by tests (`tests/cplat/test_209_uv_script.py`)

Scope: spec 209's own commits (`git log --grep 209`). The branch base also carries other specs' files (190, 191, 198, 126, the e2e upgrade drill, `cplat.py`); those are not judged here.

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-209.1 | met | `test_five_new_worktrees_add_no_script_environment_and_the_main_checkout_adds_none_after_removal_ac_209_1`, `test_a_staging_worktree_removed_and_added_again_adds_no_environment_ac_209_1`, `test_the_launcher_in_new_worktrees_of_the_platform_repo_adds_no_environment_ac_209_1`, `test_the_render_sites_run_script_cmd_ac_209_1`, `test_the_joint_pr_devbox_call_goes_through_the_helper_ac_209_1`, `test_cplat_call_sites_no_longer_run_scripts_with_uv_run_ac_209_1`, `test_script_cmd_builds_the_helper_argv_ac_209_1` | `scripts/uv-script.sh:22-36`, `scripts/cplat/uvscript.py:8-13`, `scripts/cplat/gitops.py:77`, `scripts/cplat/update.py:600,714`, `scripts/cplat/clusterrepo.py:210,234`, `scripts/cplat/appship.py:318`, `scripts/cplat/appship_joint.py:165`, `plugins/shared/bin/cplat:50-52` | 5 real worktrees: env count equals the count after the first main run (1); after removal the main run adds none; staging removed/re-added adds none; the launcher in 3 platform worktrees adds none. cplat sites are proven to start `script_cmd` argv (captured), and the helper is proven to add nothing. |
| AC-209.2 | met | `test_gitops_app_recipes_in_new_worktrees_add_no_script_environment_ac_209_2`, `test_cluster_gitops_recipes_in_new_worktrees_add_no_script_environment_ac_209_2`, `test_no_template_recipe_or_script_starts_an_inline_script_with_uv_run_ac_209_2[gitops-app,cluster-gitops]`, `test_the_gitops_app_has_a_plan_recipe_through_the_helper_ac_209_2`, `test_the_helper_runs_in_the_cluster_scripts_with_quiet_ac_209_2` | `templates/gitops-app/devbox.json:18,23-28,30,35`, `templates/cluster-gitops/devbox.json:17-19,22,23,28`, `templates/cluster-gitops/scripts/bootstrap.sh:45,60`, `templates/cluster-gitops/scripts/cluster-up.sh:11,24,39` | All eight named recipes run once in main then in 3 new worktrees; count unchanged. `validate`/`cluster-down` are covered by the static no-bare-`uv run` check. `spec-check`/`alert-poll` run `cplat.py` from a per-ref cache path (`spec-check.sh:9`), not per worktree, so they add none either (design, Decisions). |
| AC-209.3 | met | `test_the_platform_recipes_inline_script_calls_in_new_worktrees_add_no_script_environment_ac_209_3`, `test_no_platform_recipe_or_script_starts_an_inline_script_with_uv_run_ac_209_3` | `devbox.json:21,25,27,34`, `scripts/ci-local.sh:24,39`, `scripts/test-plan.sh:8`, `scripts/test-detect-shape.sh:21` | `validate`, `shapes-check`, `quality` inline-script segments run in 3 worktrees with no new env. |
| AC-209.4 | met | `test_update_from_the_previous_release_replaces_no_recipe_and_brings_the_helper_ac_209_4[gitops-app,cluster-gitops]` | `scripts/cplat/update.py:156` (`merge_devbox`), `templates/*/scripts/uv-script.sh` (not in `_skip_if_exists`/`_exclude` of either `copier.yml`) | Merge from the last release tag's devbox.json: `replaced == []`, merged recipes equal the new template's, and the helper ships as a plain template file, so copier delivers it as new. AC-209.2's behaviour then applies to the merged recipes. |
| AC-209.5 | met | `test_a_changed_dependency_list_runs_with_its_own_environment_and_adds_one_ac_209_5` | `scripts/uv-script.sh:32-35` (`--with-requirements <script>`) | The changed worktree prints 2.0, all others 1.0, across 3 rounds and new worktrees; env count 1..2. |
| AC-209.6 | met | `test_three_runs_at_once_succeed_with_the_same_output_and_add_one_environment_ac_209_6` | `scripts/uv-script.sh:32-35` | Cold cache, 3 concurrent worktree runs: same exit code and stdout as a run alone; env count ≤ 1. |
| AC-209.7 | met | `test_the_helper_passes_arguments_exit_code_output_cwd_and_the_scripts_own_path_ac_209_7`, `test_the_helper_gives_the_same_result_as_uv_run_for_a_script_with_a_block_ac_209_7`, `test_a_script_without_a_block_and_the_quiet_flag_still_run_ac_209_7`, `test_the_helper_runs_under_the_system_bash_with_a_missing_script_failing_like_uv_ac_209_7`, `test_the_github_actions_workflows_do_not_use_the_helper_ac_209_7`, `test_the_system_prompts_call_the_plan_recipe_ac_209_7` | `scripts/uv-script.sh:14-36` (`exec`, script run from its own path and cwd), `plugins/system/commands/plan.md:23,32`, `plugins/system/references/spec-list.md:7-10` | Helper vs. direct `uv run`: equal exit code (0, 3), stdout, script stderr and written file; args with spaces, stdin, `__file__`, cwd preserved; plain script and `--quiet` branch; `/bin/bash` 3.2. Workflows unchanged; CI that calls recipes gets the proven-equal behaviour. |

## Non-goals

- No change to hand-typed `uv run` behaviour; no cache pruning code; no change to the test entry points (`test-fast` keeps `uv run --with-requirements requirements-test.txt`, `devbox.json:31`); service-python, library-python, service-java, service-go and web-nextjs untouched; no cache-size limit. ✔
- No template-owned layout change (header, footer, navigation). ✔

## Deviations from the plan

- `scripts/cplat/console/preview.py:194` changed, in no task's `files` (commit 70aa7426): strips a subprocess's own `ERROR:` prefix after the failed-command wrapper, since the wrapper now names the helper command. Display-only parsing; acceptable.
- `docs/adr/117-uv-script-runner.md` and its README row were added in the plan commit (4a155033), not in a task; the design names it. Acceptable.
- All tasks t1–t4 `done: true`. Contract matches `design.md` (helper argv, `script_cmd` signature, call-site table, launcher fallback, recipe list, new `plan` recipe). ✔

## Test changes since red

- `tests/cplat/test_209_uv_script.py` (commit 12cd4ae5, user-approved): `bare_uv_runs` ignores `"$dir/scripts/cplat/cplat.py"` from the per-ref platform cache (`spec-check.sh`, `alert-poll.sh`), as design.md scopes it. The exemption is narrow (that exact path prefix) and matches the design; it does not loosen AC-209.2, whose behavioural recipe test is unchanged.

## Mutation check (report only)

Skipped: no mutation check for shape platform yet.
