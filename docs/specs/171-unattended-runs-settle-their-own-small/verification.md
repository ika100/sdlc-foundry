# Verification — 171 Unattended runs settle their own small problems

**Result:** pass
**Commit:** 49f07e8b · **Base:** 2e291843 · **Trace:** 10/10 criteria named by tests

Phase 3: `devbox run test-fast` 9073 passed, 12 skipped; `devbox run ci` OK; `cplat platform rules check` OK (prompts 345857 of
baseline 345859 bytes). SUPPRESSIONS: none. TIGHTENED: `tests/cplat/test_171_stop_hook.py`. `"escalated" not in w.state()` could
never hold because the key is always written as null, so the assertion now checks the value (`not w.state().get("escalated")`).
This is the only change to a `test_171_*` file since the red commit `9efede37`.

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-171.1 | met | `tests/cplat/test_171_preflight.py::test_a_file_without_the_two_minimum_rules_fails_the_preflight_naming_both`, `::test_a_missing_read_rule_is_the_only_rule_named`, `::test_a_missing_cplat_rule_is_the_only_rule_named`, `::test_only_allow_rules_of_the_committed_file_count`, `::test_the_repos_of_a_system_ship_are_checked_the_same_way`, `::test_an_unattended_run_without_an_allowlist_starts_no_session_and_costs_nothing` | `scripts/cplat/preflight.py:190` (`_no_allowlist`), `:81` (`read_matches`), `:19` (`MINIMUM`) | The headless test asserts exit 1, exactly one `preflight failed: no-repo-allowlist: Bash(cplat *) and Read(...)` line, no session, an `environment` escalation, 0 invocations, $0, and an unchanged settings file (AC-131.9). Empty, devbox-only, invalid JSON, user-layer-only and deny-only files are all refused. |
| AC-171.2 | met | `test_171_preflight.py::test_the_platform_settings_hold_every_rule_of_the_library_template[allow,ask]`, `::test_the_check_names_each_template_rule_the_platform_file_lacks`, `::test_the_check_passes_on_this_repository`, `::test_validate_and_ci_run_the_settings_check`, `::test_the_preflight_of_a_headless_ship_in_the_platform_repo_passes` | `.claude/settings.json` (85 allow, 11 ask, no plugin keys), `scripts/check-settings.py:45`, `devbox.json` `validate`, `scripts/ci-local.sh:34`, `.github/workflows/ci.yml:113` | The headless preflight test copies the real platform settings into the fake repo and shows no `preflight failed` line and one session. |
| AC-171.3 | met | `tests/cplat/test_171_land.py::test_a_failed_switch_to_main_after_the_merge_is_a_warning_and_the_land_succeeds[ship,pr]`, `::test_the_ship_records_the_merge_that_a_failed_cleanup_did_not_undo`, `::test_with_main_in_another_worktree_no_switch_is_tried_and_nothing_is_warned[ship,pr]`, `::test_a_failed_delete_of_the_remote_branch_is_a_warning_naming_the_step[ship,pr]`, `::test_a_pr_merged_before_the_land_ran_is_cleaned_up_with_warnings_too`, `::test_a_merge_refused_for_another_reason_says_so_and_never_blames_a_conflict[ship,pr]` | `scripts/cplat/land_merge.py:121` (`merge`, no `--delete-branch`), `:169`/`:191` (`cleanup`/`_local`, WARNING per step, skip when base is in another worktree), `scripts/cplat/ship.py:1233` (`_merged` records the merge before any local step), `ship.py:1112` (`CONFLICT_HINT` only on `merge_lock.Conflict`/`Unresolvable`) | Uses a real bare repo and a `gh` stub. The tests assert exit 0, one `WARNING: switching to main failed: <git error>` line, no "conflict" and no "ship escalate", phase `deploy` with `merge_sha`, and that the worktree's `main` is never moved. |
| AC-171.4 | met | `test_171_land.py::test_a_head_unknown_before_the_lock_is_read_and_guards_the_merge[ship,pr]`, `::test_a_commit_pushed_after_green_checks_is_not_merged_unchecked[ship,pr]`, `::test_the_checks_of_the_new_head_decide_and_a_red_one_merges_nothing[ship,pr]` | `scripts/cplat/merge_lock.py:135` (`_known` stores the read head), `land_merge.py:357-366` (`settle`: `--match-head-commit watch.head`, `head-moved` → `wait_green`, loop) | The first merge attempt carries the head the lock read. The tests check that every attempt is guarded, that the new head's checks come before its merge, and that a red new head merges nothing. |
| AC-171.5 | met | `test_171_land.py::test_local_commits_are_pushed_and_only_their_checks_are_judged`, `::test_the_local_checks_run_before_the_push_with_the_prs_own_title`, `::test_a_red_local_check_pushes_nothing_and_judges_no_checks`, `::test_a_refused_push_exits_1_naming_the_commits_and_the_fix_and_judges_no_checks`, `::test_a_branch_with_nothing_ahead_is_not_pushed_and_runs_no_local_check` | `scripts/cplat/ship.py:1115` (`push_ahead`, called first in `_land`) | The old head is red in the stub and is never polled. Covered: the exact `local commits not pushed: 2 commit(s) ahead of the PR head` error, a `fix:` naming `cplat component ship pr`, and no `pr create`. The resumed repo ship of a system ship goes through the same `_land`; no separate test. |
| AC-171.6 | met | `test_171_land.py::test_a_conflict_in_the_backlog_index_is_regenerated_committed_pushed_and_merged[ship,pr]`, `::test_the_hand_written_rest_of_the_backlog_is_merged_as_text[ship,pr]`, `::test_a_conflict_in_any_other_file_stops_and_leaves_no_half_merged_state[ship,pr × 2]`, `::test_a_conflict_in_the_hand_written_part_of_the_backlog_stops_too[ship,pr]`, `::test_after_three_regeneration_rounds_in_one_land_it_stops[ship,pr]` | `land_merge.py:38` (`GENERATED`), `:259` (`regenerate`: `--no-commit` merge, `merge-file` of the masked stages, `commit -s`, push without force, `merge --abort` on every refusal at `:310`), `:265` (round limit), `ship.py:1183` / `pr.py:113` (one `Rounds()` per land) | The tests assert a 2-parent merge commit with `Signed-off-by`, an ancestor push (no force), both spec rows and no conflict markers, the new head's checks before the merge, exactly 3 merge rounds and no fourth, and a clean checkout with no `MERGE_HEAD`. |
| AC-171.7 | met | `tests/cplat/test_171_test_helpers.py::test_a_changed_helper_is_named_a_test_helper_by_the_check`, `::test_a_changed_helper_is_a_test_helper_line_in_the_cli_output_and_exits_1`, `::test_a_helper_fix_is_recorded_without_asking_and_listed_in_the_pr`, `::test_a_helper_change_that_loses_an_assertion_or_a_criterion_id_is_refused`, `::test_the_build_tightens_a_test_helper_line_without_asking_the_person` | `scripts/cplat/spec.py:692` (helper label), `plugins/component/references/build-tighten.md:12-14`, `plugins/component/commands/build.md:66` | The PR "User decisions" block lists file, task and reason as "test tightened by an agent". See note N1 on the prompt wording. |
| AC-171.8 | met | `tests/cplat/test_171_stop_hook.py::test_a_running_wait_blocks_the_stop_holds_the_count_and_names_itself`, `::test_several_running_waits_are_named_together`, `::test_a_mark_of_a_process_that_is_gone_is_no_running_wait`, `::test_a_wait_of_another_checkout_does_not_hold_this_run`, `::test_a_recorded_wait_is_marked_while_its_body_runs`, `::test_pr_wait_marks_itself_while_it_runs[False,True]`, `::test_ship_land_marks_itself_while_it_runs`, `::test_a_running_wait_holds_the_product_ship_too` | `scripts/cplat/waits.py:81` (`running`), `:102` (`live`), `:137` (`record` marks itself: `system ship next --wait`, `dispatch wait`, `component ship wait`, env waits), `scripts/cplat/stopgate.py:84` (holds the count), `:66` (`wait_line`), `ship.py:1869`/`:1885`, `appship_state.py:386`/`:402`, `pr.py:156` | Four stops past the limit stay `1/2` with the exact first line. After the wait ends, the next stop escalates (AC-126.4/.5). `pr wait`'s own mark has an acceptance test (`test_pr_wait_marks_itself_while_it_runs`), contrary to the build note that it has none. |
| AC-171.9 | met | `tests/cplat/test_171_pr_check_tracks.py::test_a_body_in_the_git_dir_of_a_linked_worktree_is_read_where_the_other_commands_read_it`, `::test_a_body_file_that_does_not_exist_is_one_error_line`, `::test_a_body_file_that_is_a_directory_is_one_error_line`, `::test_a_body_file_that_cannot_be_read_is_one_error_line`, `::test_a_missing_body_file_in_a_linked_worktree_names_the_path_as_given` | `scripts/cplat/house_rules.py:149` (`core.git_path`, one `ERROR:` line, return 1), `:124` (`_read_reason`) | The tests run through `cplat.main` with `_file_crash` replaced by a recorder. The recorder stays empty, and the output is exactly one line. |
| AC-171.10 | met | `test_171_pr_check_tracks.py::test_every_tracked_issue_is_kept_once_in_the_order_given_and_claimed[7 cases]`, `::test_no_tracks_flag_keeps_no_tracks_and_claims_nothing`, `::test_no_other_command_keeps_only_the_last_tracks_flag` | `scripts/cplat/spec.py:1408` (`action="extend"`), `:1476` (`dict.fromkeys`) | Covers repeated, mixed, duplicate and eight-flag cases. Every value is claimed for `feature/<id>`. A static check confirms that every `--tracks` argument in `scripts/cplat` extends. |

## Non-goals

- No conflict in a hand-written file is resolved. `regenerate` aborts on any unmerged path that is not in `GENERATED` and on a
  conflict in the hand-written part of `docs/backlog.md` (`land_merge.py:297-305`).
- No rebase and no force push: the push at `land_merge.py:314` and `ship.py` `push_ahead` has no `--force`. `git reset --hard <pre>`
  is local only, after a refused push of the land's own commit. ✔
- Template allowlists are unchanged; no template file is in the diff. The preflight writes no settings, as the byte comparison
  in the AC-171.1 headless test shows. ✔
- The changelog is not regenerated: `GENERATED` holds only `docs/backlog.md`. No cross-machine lock was added. ✔
- Background subagents are not inspected by the hook; only `cplat` wait marks are. ✔
- No template-owned layout was touched (no web shape). ✔

## Deviations from the plan

- `.claude/settings.json` now commits the library template's 85 allow and 11 ask rules. This is what AC-171.2 and A1 ask for, and
  `scripts/check-settings.py` keeps the file in sync in validate and CI. Acceptable.
- Files changed outside every task's `files`:
  - `docs/adr/092-…`, `docs/adr/093-…` and `docs/adr/README.md`: written with the plan; design.md links them. Acceptable.
  - `tests/cplat/test_land_merge_unit.py`: new unit tests (t4). Acceptable.
  - `tests/cplat/test_pr_wait_superseded.py` (t9): the #221 conflict test now expects `land_merge.Unresolvable` instead of
    `ship.Conflicting`, because a land now tries regeneration first. The PR is still not merged. Acceptable.
  - `tests/cplat/dispatch_world.py` (t9): `push -u` so that the clone's `main` tracks origin, which the new `git pull --ff-only`
    cleanup needs. This is a fixture change, not an assertion change. Acceptable.
- `test_tags_and_wait.py::test_a_merge_that_landed_but_failed_locally_counts_as_merged`: the plan says this test asserts a
  `WARNING:` line. It does not:
  - Its PR slug (`acme/other`) skips the local steps.
  - Its fake remote-delete error contains "does not exist", so no warning is printed.
  - It asserts only `merged … (squash)` and the absence of the #371 line.

  Acceptable, because the AC-171.3 acceptance tests prove the WARNING lines through both entries, but the test is weaker than
  the plan describes.
- t9: `pr wait` without `--merge` keeps `ship.wait_checks` and never regenerates. A plain wait must not change the branch, and
  AC-171.6 is about landing only. Acceptable.
- t10:
  - The register files `docs/rules/plugins/component/{commands/build.yml,references/build-tighten.yml}` listed in the task are
    unchanged. `cplat platform rules check` passes, so the new sentence apparently needed no entry. Acceptable.
  - The two prompts together grew by 148 bytes (16945 → 17093: `build.md` −172, `build-tighten.md` +320). The plan asked that
    they not grow. The repository-wide byte baseline still holds (345857 of 345859), and that is the plan's done criterion.
    Acceptable, but note it for the next prompt round.
  - The five phrases t10 first cut were restored in `49f07e8b`, and the new section was shortened instead. Acceptable.
- MergeFailed hint of `pr wait`: "read the error, then run the merge again", where design.md says "run the wait again". This is
  wording only, and it does not mention conflicts. Acceptable.
- Every task has `done: true`.

## Notes

- **N1 (minor, prompt wording):** `build.md:66` puts the helper branch in parentheses ahead of "stop and show the user the file and
  the reason". A reader could take it as "read `build-tighten.md`, then still ask". `build-tighten.md:14` is clear ("without
  asking"), and the acceptance test pins that line. Separately, `build-tighten.md` describes the CLI line as `test helper (defines
  no test): <file>`, but `test-diff` prints `<file>: changed — test helper (defines no test): <reason>`. Neither blocks AC-171.7;
  worth tightening in a later prompt pass.

## Contract

Matches design.md: the `land_merge` API, the merge argv without `--delete-branch`, the cleanup WARNING format and the
other-worktree skip, the `_known` head guard, the regeneration steps and messages, `push_ahead` messages and hint, the mark file
format and `stopgate.check(..., waiting=)` order, the pr-check error line, and `--tracks` extend with de-duplication. The only
difference is the `pr wait` MergeFailed hint wording noted above. ✔

## Mutation check (report only)

Skipped: no mutation check for shape platform yet.
