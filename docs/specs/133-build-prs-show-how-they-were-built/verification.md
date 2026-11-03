# Verification — 133 Build PRs show how they were built

**Result:** pass
**Commit:** 5fb0610 · **Base:** f7b85c3 · **Trace:** 13/13 criteria named by tests

Tests: `B` = `tests/cplat/test_runs_built_133.py` (red at 7078b10, unchanged since). `tests/cplat/test_pr_open.py`,
`test_runs_agents.py`, `test_runs_report.py` and `test_lean_prompts.py` stay green; full `tests/cplat` suite and `devbox run quality`
green locally. Manual run: `cplat platform runs report --pr <id>` for a run on spec 130 rendered its four accepted deviations from
`docs/specs/130-*/verification.md`.

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-133.1 | met | `B::test_report_pr_prints_the_marked_collapsed_block_with_four_headings_in_order_ac_133_1`, `B::test_report_pr_reads_a_finished_run_from_the_local_buffer_ac_133_1` | `scripts/cplat/runs_built.py:44` (`find`: active, else buffer), `:287` (`render`), `scripts/cplat/runs.py:871-877` | `CPLAT_RUNS_REPO` unset in both tests |
| AC-133.2 | met | `B::test_an_unknown_run_exits_1_with_nothing_on_stdout_ac_133_2`, `B::test_pr_cannot_be_combined_with_the_aggregate_options_ac_133_2` (5 combinations) | `runs_built.py:307-313`; `runs.py:872-874`; `--since` default is now `None` (30 applied in `_report`) | |
| AC-133.3 | met | `B::test_how_it_ran_names_run_kind_mode_replans_ci_gates_and_agents_ac_133_3`, `B::test_an_unrecorded_execution_mode_says_not_recorded_ac_133_3`, `B::test_wall_time_sums_the_runs_it_resumes_ac_133_3` | `runs_built.py:58` (`chain`), `:82-92`, `:259-273` | |
| AC-133.4 | met | `B::test_budget_shows_used_against_each_limit_ac_133_4`, `B::test_an_unreadable_cost_says_unknown_ac_133_4`, `B::test_without_a_ledger_the_budget_is_not_recorded_ac_133_4` | `runs_built.py:107-143` (ledger by `roots`, `budget.used_of`) | |
| AC-133.5 | met | `B::test_user_decisions_list_budget_changes_escalations_refusals_and_answers_ac_133_5`, `B::test_approved_test_diffs_are_listed_when_recorded_ac_133_5`, `B::test_no_decisions_says_none_recorded_ac_133_5` | `runs_built.py:215-239`, `:171` (`answered`) | The #324 hook reads `approved_test_diffs` (shape in design.md) |
| AC-133.6 | met | `B::test_hand_backs_list_every_kind_of_event_ac_133_6`, `B::test_no_hand_backs_says_none_ac_133_6` | `runs_built.py:241-258` | |
| AC-133.7 | met | `B::test_only_accepted_deviations_are_listed_by_their_first_sentence_ac_133_7`, `B::test_long_deviations_are_cut_to_200_characters_ac_133_7`, `B::test_deviations_without_items_or_file_ac_133_7` | `runs_built.py:182-203`, `:28` (200 characters) | |
| AC-133.8 | met | `B::test_values_are_redacted_and_lists_are_capped_ac_133_8`, `B::test_the_block_carries_no_prompts_or_diffs_ac_133_8` | `runs_built.py:28-31` (`feedback.redact` on every value), `:278-284` (10 lines) | Only the fields of design.md's Sources table are read |
| AC-133.9 | met | `B::test_the_execution_call_records_the_mode_ac_133_9` (2 cases), `B::test_the_last_execution_call_wins_and_a_bad_mode_records_nothing_ac_133_9`, `B::test_build_records_the_execution_after_the_worktree_probe_ac_133_9` | `scripts/cplat/runs_agents.py:529-541`, `:598-600`, `:637-638`; `plugins/component/commands/build.md:64`; `plugins/component/references/build-worktree-fallback.md:5-6` | |
| AC-133.10 | met | `B::test_pr_open_appends_the_block_when_the_checkout_has_a_run_ac_133_10` (opened and ready) | `scripts/cplat/pr_open.py:138-146`, `:184` (before commit and `gh pr create`); `runs_built.py:323-329` | |
| AC-133.11 | met | `B::test_pr_open_without_a_run_leaves_the_body_byte_for_byte_ac_133_11`, `B::test_pr_open_ignores_a_run_for_another_spec_ac_133_11`, `B::test_a_failing_section_leaves_the_body_and_opens_the_pr_with_a_note_ac_133_11` | `pr_open.py:142-146`; `runs_built.py:316-320` (`_same_spec` by leading number) | |
| AC-133.12 | met | `B::test_running_pr_open_again_replaces_the_block_ac_133_12` | `runs_built.py:332-336` | |
| AC-133.13 | met | `B::test_docs_name_the_report_the_execution_call_and_the_changelog_entry_ac_133_13` | `plugins/platform/commands/runs.md:13`; `build.md:64`, `:179`; `docs/CHANGELOG.md:11` | |

## Non-goals

No run-store read (`find` uses only `runs.active` and the local buffer). No prompts, diffs or commit lists. Nothing records
user-approved test changes (#324); only the `approved_test_diffs` section is read. The orchestrator's PR body text is unchanged.
`/system:ship` is untouched. ✔

## Deviations from the plan

- `docs/adr/079-…`, `docs/adr/README.md`, `docs/backlog.md` and the spec files were written with the plan. Acceptable.
- t1's commit also carries `runs_agents.execution` (t2's file); t2's commit carries the build.md and reference changes. Acceptable:
  same branch, both tasks done.
- `build.md` is capped by `test_lean_prompts` (under 19 912 bytes). To fit the two new sentences, three existing sentences of
  Phase 0/1 were shortened without changing what they ask (`--model-id` wording, the tester-misses flags). The file is 19 890 bytes,
  which leaves room for spec 131's +18 bytes. Acceptable.

## Contract

Matches `design.md`: markers, headings and their order, the `execution` and `approved_test_diffs` shapes, the `pr open` placement
after the WIP note. ✔
