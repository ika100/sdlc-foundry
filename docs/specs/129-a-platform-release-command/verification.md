# Verification — 129 A platform release command

**Result:** pass
**Commit:** 77e1730 · **Base:** d2e0b3a · **Trace:** 21/21 criteria named by tests (`cplat spec trace`, missing: none)

Tests named below are in `tests/cplat/`; implementation paths are under `scripts/` unless stated. Acceptance tests and
`platrelease_world.py` are unchanged since the red commit 377d30a (`git diff 377d30a..HEAD -- tests/` touches only the
three older pins listed under Deviations).

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-129.1 | met | `test_platrelease_129_state.py::test_dry_run_prints_state_version_and_steps_and_creates_nothing`, `::test_dry_run_names_the_release_in_flight_and_starts_at_its_first_step`, `::test_dry_run_shows_the_open_pr_and_the_branch`, `::test_dry_run_is_reached_through_the_cplat_dispatcher` | `cplat/platrelease.py:192` (state block always printed), `:207` (dry run returns before any write); `cplat/platrelease_state.py:240` (steps), `:259` (render); `cplat/cplat.py:79` | Tests assert all six state lines, the version with its reason, steps 1–12, the in-flight start step, and no snapshot change, created PR, merge or gh write. The dry run fetches, which design.md allows. |
| AC-129.2 | met | `test_platrelease_129_state.py::test_a_minor_is_proposed_when_no_change_needs_a_major`, `::test_a_major_is_proposed_and_names_the_change`, `::test_a_failing_major_detection_stops_with_its_output`, `::test_release_check_needs_major_prints_nothing_without_a_major_change`, `::test_release_check_needs_major_fails_readably_for_an_unreadable_base` | `cplat/platrelease_state.py:197` (needs_major), `:204` (proposal); `release-check.py:110` (major_reasons), `:117`, `:133` (rows uses the same rule) | Asserts 5.5.0 versus 6.0.0, with the changes named in the reason, and the exact `needs-major --base v5.4.0` call under `sys.executable`. |
| AC-129.3 | met | `test_platrelease_129_state.py::test_a_valid_newer_version_replaces_the_proposal`, `::test_a_major_version_is_accepted_when_a_major_is_required`, `::test_a_version_that_is_not_semver_is_refused` (4 cases), `::test_a_version_that_is_not_newer_than_the_newest_tag_is_refused` (3 cases), `::test_a_non_major_version_is_refused_when_a_major_is_required_and_names_the_change` | `cplat/platrelease_state.py:215` (syntax, checked before fetch at `platrelease.py:177`), `:225` (newer, major) | Every refusal is checked with `no_writes`. |
| AC-129.4 | met | `test_platrelease_129_state.py::test_uncommitted_changes_stop_the_run_before_a_branch`, `::test_a_local_main_that_differs_from_origin_stops_the_run`, `::test_an_empty_unreleased_section_stops_the_run` | `cplat/platrelease.py:40` (preflight), called at `:203` only in `idle` and before `_prepare` at `:211` | The texts match the contract, and no release branch exists after the run. The extra DCO git-user check comes first, as the design says. |
| AC-129.5 | met | `test_platrelease_129_state.py::test_a_plugin_whose_versions_differ_is_named_and_nothing_is_edited`, `::test_a_version_mismatch_also_stops_a_release_in_flight` | `cplat/platrelease_changelog.py:56` (read-only); `cplat/platrelease.py:174` (first check of every run) | The tests assert both files are unchanged byte for byte, in a normal run and in a dry run. |
| AC-129.6 | met | `test_platrelease_129_prepare.py::test_the_changelog_moves_under_the_new_heading_on_a_release_branch`, `::test_no_other_file_changes_in_the_release`, `::test_the_date_is_the_date_of_the_run` | `cplat/platrelease_changelog.py:25` (move_unreleased); `cplat/platrelease.py:70`, `:83` | Checks the full file against the expected text, the empty `[Unreleased]` above the new heading, that only `docs/CHANGELOG.md` differs, and that the date comes from `today()`. |
| AC-129.7 | met | `test_platrelease_129_prepare.py::test_a_failing_check_prints_its_output_and_commits_and_pushes_nothing` (rows, validate) | `cplat/platrelease.py:59` (`_check` prints the output and raises), `:84`–`:85` before the commit at `:88` and the push at `:89` | Asserts the output and `<name> failed`, no commit ahead of main, no remote branch and no PR. |
| AC-129.8 | met | `test_platrelease_129_prepare.py::test_one_signed_commit_is_pushed_and_the_pr_is_opened`, `::test_the_pr_body_carries_no_changelog_text` | `cplat/platrelease.py:86`–`:95` (`git commit -s`, `push -u` with no force, `gh pr create`, `PR: <url>`) | Exactly one commit ahead, the subject, a `Signed-off-by:` trailer for the configured user, the PR base, head and title, and the printed URL. |
| AC-129.9 | met | `test_platrelease_129_prepare.py::test_the_wait_covers_every_check_including_the_upgrade_e2e`, `::test_a_cancelled_older_run_of_a_workflow_does_not_count_as_red`, `::test_a_green_pr_without_the_upgrade_e2e_is_not_mergeable` | `cplat/platrelease.py:101` (`pr.wait`, which judges only the newest run via `ship.CheckWatch._newest_runs`, `cplat/ship.py:562`), `:126`–`:130` (the e2e must pass) | See note (a) on `_wait_e2e`. |
| AC-129.10 | met | `test_platrelease_129_prepare.py::test_a_red_check_names_the_check_and_its_link_and_does_not_merge` (without and with `--confirm merge`) | `cplat/platrelease.py:103`–`:105` (`ship.red` lines, then `CI is red on <url>: not merged`) | The check name, its run link, the ERROR and `merges == []` are all asserted. |
| AC-129.11 | met | `test_platrelease_129_prepare.py::test_a_green_pr_stops_before_the_merge_with_the_continue_command`, `::test_only_the_confirmation_squash_merges_the_pr`, `::test_a_confirmation_is_refused_where_its_step_is_not_next` (4 cases) | `cplat/platrelease.py:131`–`:136` (merge stop), `:137` (squash merge with `--match-head-commit` through `pr.wait`), `:196`–`:199` (`--confirm` checked against the phase), `:218` (exit 3) | After the merge the run continues to the tag stop, not past it. |
| AC-129.12 | met | `test_platrelease_129_publish.py::test_the_wait_keeps_going_until_the_e2e_run_appears`, `::test_of_two_runs_only_the_newest_counts`, `::test_a_red_newest_run_stops_before_any_tag`, `::test_a_run_that_never_appears_fails_after_ten_minutes_without_a_tag` | `cplat/platrelease_publish.py:15` (APPEAR_WINDOW 600), `:19` (wait_for_run, newest by databaseId at `:31`), `:44`–`:52` | `APPEAR_WINDOW == 600`, the clock reaches at least 600 s before failing, the full merge sha is named, and there is no tag, no gate and no gh write. |
| AC-129.13 | met | `test_platrelease_129_publish.py::test_a_failing_gate_prints_its_output_and_tags_and_releases_nothing` | `cplat/platrelease_publish.py:55` (gate under `sys.executable`, output printed, `release-check gate failed`) | No tag on origin or locally, and no gh write. |
| AC-129.14 | met | `test_platrelease_129_publish.py::test_the_tag_stop_shows_what_it_will_publish_and_creates_nothing` | `cplat/platrelease_publish.py:71` (`_tag_stop`), `:134`–`:135` | The notes block is asserted verbatim. |
| AC-129.15 | met | `test_platrelease_129_publish.py::test_the_confirmation_tags_the_merge_commit_and_publishes_the_section_as_notes`, `::test_the_release_notes_are_taken_from_the_merge_commit` | `cplat/platrelease_publish.py:87` (`git tag -a`), `:93` (push of `refs/tags/vX` with no force), `:97`–`:105` (release with `--notes-file`, `--verify-tag`); `cplat/platrelease_changelog.py:40` | The tag is annotated (`cat-file -t` is `tag`) both locally and on origin, points at the merge sha, and the notes equal the section body read from the merge commit. |
| AC-129.16 | met | `test_platrelease_129_publish.py::test_a_green_release_guard_finishes_the_release_with_both_urls`, `::test_a_red_release_guard_exits_non_zero_and_leaves_tag_and_release`, `::test_a_red_release_guard_is_reported_again_on_a_rerun_without_touching_the_tag` | `cplat/platrelease_publish.py:108`–`:119`, `:142` (`RELEASED:` block); `cplat/platrelease_state.py:188` (guard-red phase); `cplat/platrelease.py:204` | Waits through empty run lists and ignores another tag's red run. On red the tag and release remain and nothing calls `release delete`. |
| AC-129.17 | met | `test_platrelease_129_state.py::test_a_release_branch_without_a_pr_continues_by_opening_the_pr`, `::test_an_open_release_pr_continues_by_waiting_for_ci`, `::test_a_merged_release_commit_without_a_tag_continues_with_the_upgrade_e2e`, `::test_a_tag_without_a_github_release_continues_by_creating_the_release`, `::test_a_tag_and_a_release_continue_with_the_release_guard` | `cplat/platrelease_state.py:124` (detect, no state file), `cplat/platrelease.py:210`–`:220`, `cplat/platrelease_publish.py:122` | All five resume points are covered, with no repeated prepare and no second commit. |
| AC-129.18 | met | `test_platrelease_129_state.py::test_a_version_naming_another_release_than_the_one_in_flight_is_refused` (branch, pr-open, merged), `::test_the_same_version_as_the_release_in_flight_is_accepted` | `cplat/platrelease_state.py:220` (check_in_flight), `cplat/platrelease.py:195` | Every refusal is checked with `no_writes`. |
| AC-129.19 | met | `test_platrelease_129_publish.py::test_a_tag_on_another_commit_stops_the_run_naming_both_commits` (without and with `--confirm tag`), `::test_a_local_tag_on_another_commit_is_never_moved`, `::test_a_local_tag_on_the_merge_commit_is_pushed_not_recreated` | `cplat/platrelease_state.py:167`–`:170` (detection), `cplat/platrelease_publish.py:77`–`:88` (origin and local check before `git tag`) | Searching every new module and the command for `--prune`, `-f`, `--force`, `-d`, `delete` and `+refs` finds nothing (see note c). |
| AC-129.20 | met | `test_platrelease_129_docs.py::test_the_platform_release_command_runs_cplat_with_its_arguments`, `::test_the_platform_release_command_asks_at_each_stop_and_continues_only_after_a_yes` | `plugins/platform/commands/release.md:16` (exit 3: ask, continue only on a yes), `:19` (never pass `--confirm` without a yes) | These are text tests, the right level for a slash command. The command also runs in the background as the design requires. |
| AC-129.21 | met | `test_platrelease_129_docs.py::test_the_component_release_refusal_names_the_platform_command`, `::test_contributing_names_the_command_as_the_release_procedure` | `plugins/component/commands/release.md:20` (inside the refusal block, before Phase 1); `CONTRIBUTING.md:94` | The existing sentences of the refusal stay, and the spec 123 tests stay green. |

### Notes for the orchestrator

**(a) `_wait_e2e` pre-poll** (`cplat/platrelease.py:108`–`:120`, called at `:126` before `pr.wait`). It polls `ship.checks`
while the upgrade e2e is pending and nothing is failing. It decides nothing: it returns as soon as any check fails or the
e2e is no longer pending, and `pr.wait` then judges every check with the newest-run rule (`ship.py:562`). The red/green
verdict and the merge decision stay entirely with `pr.wait`, so AC-129.9 and AC-129.10 are not weakened (the AC-129.10
test runs through this path with a failing `quality` check and a pending e2e). Side effects, all minor:

1. It reads unfiltered checks (no head-sha or newest-run filter). The worst case is an early return or a longer wait, never a wrong verdict.
2. While it polls, `CheckWatch` cannot heal the e2e: a run stuck in the queue is not cancelled and rerun, and the poll ends at `--timeout` with exit 1 and nothing merged.
3. The pre-poll and `pr.wait` each get a full `--timeout`, so the CI phase can take up to twice `--timeout`.

The contract does not mention this step. It is acceptable, but design.md should record it, or it should be dropped if
`pr.wait` alone is enough.

**(b) Behaviours beyond the contract.** All are acceptable and all fail closed:

- A tag already on origin on the merge commit means the push is skipped (`platrelease_publish.py:84`). It is idempotent and never moves a tag.
- When the guard never appears, the run fails with "no run started within 10 minutes" (`:116`), as AC-129.16's "as in AC-129.12" implies.
- A guard still running at `--timeout` is an error (`:118`), and a rerun resumes in `guarding`.
- A merge commit with no `## [X]` section stops before the tag stop (`:63`–`:68`, called at `:135`). This is a useful safety check.
- When a release is merged and a leftover `release/` branch of another version exists, the merged release wins (`platrelease_state.py:161` comes before `:164`). This matches the "first match wins" table. The design lists only PR+merged and PR+branch as conflicts. Cosmetic issue: the state block then shows the leftover branch name.

**(c) AC-129.19.** No new module or command file deletes, moves or force-pushes a tag, or uses `--prune` or `-f`:
`fetch` is `git fetch origin --tags` and `git fetch origin main` (`platrelease_state.py:70`–`:72`), and the pushes are `push -u origin
release/X` (`platrelease.py:89`) and `push origin refs/tags/vX` (`platrelease_publish.py:93`). The only deletion
anywhere on the path is the existing `gh pr merge --squash --delete-branch` in `pr.py:100`, which deletes the release
branch, not a tag.

Edge case, not a criterion failure: if a local `vX` and the origin `vX` point at different commits, `git fetch origin --tags`
refuses to clobber the local tag, and the run exits 1 with git's message ("would clobber existing tag") instead of the
contract's "tag vX is on …, not on …" text. Nothing is moved.

## Non-goals

- No plugin or marketplace version is bumped by code: `plugin_mismatches` only reads (`platrelease_changelog.py:56`). The 1.4.0 and 1.5.3 bumps are the plan's t6 doc work. ✔
- Component repos: `/component:release` changes only by the added refusal line. ✔
- There are no changelog fragments. ✔
- No issue is closed: the PR body is the fixed two-line text (`platrelease.py:90`), asserted by a test. ✔
- No tag is deleted or moved after a red guard. ✔

## Deviations from the plan

- `tests/cplat/test_scale_120_cmds.py` (AC-120.5) and `tests/cplat/test_upgrade_121_ops.py` (AC-121.6) are in no task's `files`. They relax the platform plugin pin from `== 1.3.0` to `>= 1.3.0` because t6 bumps it to 1.4.0, matching how those tests already treat component and system. The maintainer approved it (commit 77e1730). Acceptable.
- `docs/adr/073-….md`, `design.md`, `plan.md` and `spec.md` (status `building`) are spec artifacts written before the build. Acceptable.
- `tests/cplat/platrelease_world.py` and `test_platrelease_129_*.py` are the acceptance tests from the red commit and have not been edited since. ✔
- All six tasks are `done: true`. Every other changed file is in its task's `files`. ✔

## Contract

The build matches `design.md` on these points:

- CLI flags and defaults.
- Exit codes 0, 1, 2 and 3.
- Phase table and first steps.
- Order of checks 1–6.
- Step texts.
- `CONFIRM:` blocks.
- Error texts.
- `gh` and `git` calls, and the test seams (`run_check`, `today`, `ship.*`, `APPEAR_WINDOW`).

Differences:

- The `_wait_e2e` pre-poll (note a). Record it in the design or remove it.
- The extra behaviours in note (b). They are additive and fail closed.
- Detection wording "several release branches" / "several release PRs" ("naming them", as the contract asks).
- `guard-red` has no step list (its first step is 13, so the list is empty). This is consistent with the phase being terminal.
