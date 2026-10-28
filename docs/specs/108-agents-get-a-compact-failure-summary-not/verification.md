# Verification — 108 Agents get a compact failure summary, not the full log

**Result:** pass
**Commit:** 5dc00f6 · **Base:** 04e74c1 · **Trace:** 11/11 criteria named by tests

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-108.1 | met | `tests/cplat/test_108_quiet.py::test_a_failing_command_prints_the_summary_with_the_log_path_and_passes_the_exit_code_ac_108_1`, `::test_the_exit_code_passes_through_unchanged_ac_108_1` (rc 2, 3, 127), `::test_an_unreadable_failure_still_prints_the_last_40_lines_ac_108_1`, `::test_a_succeeding_command_prints_what_spec_100_printed_ac_108_1` | `scripts/cplat/quiet.py:61-69` | The title keeps today's `FAILED (exit rc) ... (log: ...)` line, the header carries the log path, `return rc` is unchanged. The success test asserts byte-equal spec 100 output and no sidecar. |
| AC-108.2 | met | `tests/cplat/test_108_failsum_formats.py::test_a_failing_test_run_has_one_entry_per_test_and_no_noise_ac_108_2` (pytest long and `--tb=line`, surefire, go test, vitest), `::test_an_excerpt_has_at_most_ten_lines_ac_108_2`, `::test_every_failing_and_erroring_test_gets_its_own_entry_even_with_equal_messages_ac_108_2` | `scripts/cplat/failsum/python.py:51-110`, `failsum/java.py`, `failsum/go.py`, `failsum/web.py`; own-code paths at `failsum/core.py:98-122` | Each case checks the exact entry count, the test id, the own-code `file:line`, the type, a normalized message, excerpts of 10 lines or fewer, and that library frames, passing tests and progress output are absent. |
| AC-108.3 | met | `test_108_failsum_formats.py::test_a_failing_lint_type_or_build_run_has_one_entry_per_finding_ac_108_3` (17 formats), `::test_identical_findings_are_listed_once_with_a_count_ac_108_3`, `::test_a_finding_excerpt_is_the_code_frame_the_tool_printed_ac_108_3` | `failsum/core.py:189-208` (dedup), the parsers in `failsum/*.py` | `x3 (lines 9, 14)` is asserted byte-exact. Tests are never merged (`core.py:194`). |
| AC-108.4 | met | `test_108_failsum_formats.py::test_the_templates_formats_are_all_registered_ac_108_4`, `::test_the_test_tools_of_the_templates_are_recognized_ac_108_4`, `::test_the_lint_type_and_build_tools_of_the_templates_are_recognized_ac_108_4`, `::test_another_format_says_unknown_and_shows_the_last_40_lines_ac_108_4`, `::test_output_the_summary_cannot_read_is_never_an_empty_summary_ac_108_4`, `::test_the_cluster_gitops_template_is_outside_the_six_and_falls_back_ac_108_4` | `failsum/__init__.py:21` (registry), `failsum/core.py:280-283` (unknown: last 40 lines or `(no output)`), `core.py:214-217` (a broken parser degrades to unknown) | The 22 parser names match the design table. The cluster-gitops fallback follows the 2026-10-28 changelog reading. |
| AC-108.5 | met | `tests/cplat/test_108_failsum_core.py::test_every_failing_check_of_a_multi_check_run_has_its_own_header_ac_108_5`, `::test_the_last_check_always_appears_even_when_no_parser_reads_it_ac_108_5`, `::test_more_than_20_entries_show_20_then_the_exact_rest_and_the_log_path_ac_108_5`, `::test_exactly_20_entries_are_all_shown_ac_108_5`, `::test_a_summary_over_80_lines_shortens_excerpts_first_ac_108_5`, `::test_over_80_lines_with_no_excerpts_cuts_entries_but_never_a_check_or_its_count_ac_108_5` | `failsum/__init__.py:30-40` (segments; the last non-empty one is always kept), `failsum/core.py:258-305` (shortening order: excerpts, then tail, then shown entries) | `entries: <n>` and the `... <m> more entries not shown (log: …)` line are always rendered. CI checks are never filtered (`__init__.py:43-46`). |
| AC-108.6 | met | `test_108_failsum_core.py::test_the_same_log_twice_gives_byte_identical_summaries_ac_108_6`, `::test_the_summary_is_made_without_a_model_call_ac_108_6` | `failsum/core.py` (pure: no clock, no subprocess, no network) | The source scan bans `anthropic`, `subprocess`, `claude -p`, `requests` and `urllib.request` in the package. |
| AC-108.7 | met | `test_108_quiet.py::test_the_full_log_stays_on_the_machine_next_to_a_sidecar_with_the_printed_summary_ac_108_7`, `test_108_failsum_core.py::test_secrets_in_the_summary_are_redacted_but_the_log_path_is_not_ac_108_7`, `::test_agent_instructions_say_to_open_the_log_only_when_the_summary_is_not_enough_ac_108_7` (9 agents), `::test_the_briefs_hand_over_the_summary_and_the_log_path_ac_108_7` (build, fix, ship-land-red), `test_108_ship.py::test_red_ci_logs_and_summaries_never_reach_the_run_store_ac_108_7` | `failsum/core.py:258-264,308-327` (every line redacted except the log path), `quiet.py:57-66`, the agent and command `.md` files (t6) | No new run-record write. Spec 102's reason text keeps carrying 200 characters of the normalized message, as before (design, Risks). |
| AC-108.8 | met | `test_108_ship.py::test_a_red_check_is_saved_locally_and_the_brief_holds_its_summary_and_log_path_ac_108_8`, `::test_a_failed_check_that_is_not_an_actions_run_still_gets_a_header_ac_108_8`, `::test_the_pre_push_ci_failure_message_holds_the_summary_and_the_log_path_ac_108_8` | `scripts/cplat/ship.py:774-813` (`_ci_checks`, `red_summary`, `red`), `ship.py:410-423` (`run_ci`), `ship.py:628` (`_log_failed` reuse) | The saved log holds only that job's lines. The brief has no raw noise. Exactly one `--log-failed` fetch per round is asserted (`len(ci.views) == 1`). |
| AC-108.9 | met | `test_108_ship.py::test_budget_normalise_is_the_failsum_rule_ac_108_9`, `::test_a_given_normalized_text_is_the_failure_that_counts_for_no_progress_ac_108_9`, `::test_the_snapshot_excerpt_is_the_whole_summary_when_given_ac_108_9`, `::test_a_land_that_stops_for_no_progress_snapshots_the_summary_ac_108_9`, `::test_attempt_with_an_error_file_uses_the_sidecar_summary_ac_108_9`, `::test_attempt_with_an_error_file_without_a_sidecar_behaves_as_before_ac_108_9` | `scripts/cplat/budget.py:497,506-514,562-574,695-711`, `ship.py:850-858` | Two rounds with different timestamps stop as "no progress" on the summary's normalized message. The snapshot excerpt starts with the `RED:` title and holds the `== check:` header. |
| AC-108.10 | met | `test_108_failsum_core.py::test_summaries_are_on_without_a_setting_ac_108_10`, `::test_the_project_setting_turns_summaries_off_ac_108_10`, `::test_the_project_setting_on_keeps_summaries_on_ac_108_10`, `::test_an_invalid_setting_is_an_error_naming_the_value_ac_108_10`, `::test_the_personal_settings_file_is_not_read_for_this_key_ac_108_10`, `::test_summaries_off_prints_the_title_the_reason_and_the_last_40_lines_ac_108_10`; `test_108_quiet.py` (`--raw`, the setting, raw wins in the reason, invalid setting gives exit 2, on by default); `test_108_ship.py::test_with_summaries_off_the_red_lines_are_todays_plus_the_off_line_ac_108_10`, `::test_the_pre_push_ci_failure_with_summaries_off_says_so_ac_108_10` | `scripts/cplat/settings.py:172-186`, `quiet.py:37-52`, `failsum/core.py:330-332`, `ship.py:803-804` | `--raw` is consumed by cplat and never reaches the shell (`quiet.main(["test-fast","--raw"]) == 2`). |
| AC-108.11 | met | `tests/cplat/test_108_benchmark.py::test_the_fix_rounds_workflow_is_a_fixed_task_with_a_seed_ac_108_11`, `::test_the_seed_starts_a_finished_build_with_one_failing_test_and_one_lint_finding_ac_108_11`, `::test_two_passes_run_the_same_build_with_the_setting_added_in_the_second_ac_108_11`, `::test_both_passes_are_reported_and_recorded_ac_108_11`, `::test_equal_fix_rounds_are_no_failure_and_there_is_no_savings_target_ac_108_11`, `::test_the_exit_is_non_zero_only_for_the_three_conditions_and_the_record_is_written_ac_108_11`, `::test_the_arm_and_the_validation_comparison_are_refused_for_fix_rounds_ac_108_11`; seed evidence in `design.md` "Seed check (2026-10-28)" | `scripts/cplat/runs_bench.py:313-341,375-377,415-460,527-534`, `benchmark/tasks.json`, `benchmark/seeds/fix-rounds.json` | The tests prove the two passes, that only pass 2 adds the setting, the per-pass lines, the record, and the three exit conditions with no savings target. The seed test checks only the seed's shape. The rest comes from the manual check recorded in commit 5dc00f6, which this review did not rerun. The seed was applied to `ika100/todo-api@9cba320`, and devbox 0.17.5 gave: `test-fast` has exactly one failure (`tests/unit/test_validation.py::test_parse_id`), and `test_ac_901.py` passes; `lint` reports exactly one F401 (`os`); `typecheck` is clean; `cplat spec check` is OK; `spec hash 901` is `f7e886e34fd7`, the plan's hash. The failing test matches the seed's `parsed.version == 4` change in `parse_id`. |

## AC-108.11 recheck (after 5dc00f6)

The first review rated AC-108.11 `partial`, because nothing showed that the seed starts the build with one failing test and one lint finding. Commit 5dc00f6 adds that evidence: a seed check against the pinned sample, recorded in `design.md` under "Seed check (2026-10-28)". The criterion is now `met`. The seed check is manual evidence: the acceptance test still checks only the seed's shape. If the sample pin or the seed changes, the check has to be repeated.

The full two-pass benchmark against GitHub does not need to run before merge. It is a measurement with no savings target, and the reporting and exit logic are proven through the same seams as specs 099, 103 and 107. Run it after release.

## Non-goals

- No model call: the package has no subprocess, network or model import, and `test_the_summary_is_made_without_a_model_call_ac_108_6` scans for them. ✔
- No failing check dropped: local logs always keep the last non-empty segment (`failsum/__init__.py:38`), and CI keeps every check in `failed`, including checks that are not GitHub Actions runs (`log: none`). The render never removes a header or its count. ✔
- Nothing goes to the run store: the CI logs and sidecars go to the `cplat quiet` log directory only; tested on `land`. ✔
- No gate changed: `run_ci` still raises on red, `validate.record_final_gate` is unchanged, `land` keeps its round counting and spec 102 rules, and no CI workflow changed. ✔
- Successful output unchanged: tested. ✔
- No new uploading or keeping of logs beyond the `cplat quiet` log directory. The saved CI logs live there too (design decision, AC-108.8). ✔

## Readings recorded in design.md

- **`ci` is split at devbox's `Info: Running script` markers, and the last non-empty segment is the one that failed.** This holds for templates that chain `ci` with `&&`. A passing segment that still prints findings shows up as an extra check. That over-reports, it never drops a check. Acceptable.
- **Messages also mask every remaining number as `<n>`** (`failsum/core.py:46-48`). This goes beyond "normalized as in spec 102". Since 5dc00f6, the design's `<message>` line names `failsum.message` and states the consequence: `expected 204, got 200` and `expected 204, got 500` count as the same failure for the no-progress stop. Spec 102 also compares the failing names and counts, so this is acceptable.
- **Redaction covers everything except the log path.** This keeps the path usable by an agent's Read tool. Acceptable.
- **The `failure_summary` setting is read from the project file only.** The spec says "project setting". Acceptable.
- **The benchmark task is a build whose implementation is already done.** This is reasonable, but it depends on the seed being right (see AC-108.11).
- **cluster-gitops falls back to `format: unknown`** (spec changelog 2026-10-28). Tested. Acceptable.

## Build-time changes judged

- **200b795 (the bandit test).** Correct. AC-108.7 requires redaction everywhere in the summary, including the unknown-format tail, so expecting `hunter2` contradicted the spec. The new assertion still proves that the tail is shown (it contains the rule id). This is the only change to a red acceptance test (`git diff 86f78e7..HEAD -- tests/`), and no existing test was changed on the branch.
- **4869655 (the prompt size).** Nothing a coordinator needs was lost:
  - `build.md` Phase 3 step 2 still hands over "the summary and log path `cplat quiet` printed (log only if the summary is not enough)". "Brief headings as in 2.3" points to `build.md:66-68`, which lists `Criteria`, `Task`, `Contract`, `Tests` and `Commands` with their content.
  - `fix.md` lost its separate instruction bullet. The brief bullet now says "give the agent the printed summary and log path (log if not enough)", and the coder agent's own shell rule carries the full instruction.
  - Both files still pass the AC-108.7 brief test.
- **t5, `c["_log_failed"]` on the check dict.** Acceptable. The dicts come fresh from `checks()` on every poll, so one round's log never serves the next. Only check names reach the ship state, the run record or the `pr wait` section (`pr.py:88-97`, `validate.record_ci_red`), so the log text is never persisted. Checks of runs that were already healed have no `_log_failed` and are fetched in `_ci_checks` (`ship.py:786-787`).
- **`cplat validate run` raises PlatformError on an invalid setting** (`validate.py:441`) before any check runs. Acceptable. AC-108.10 does not demand an exit code, and exit 2 is `cplat quiet`'s contract (the design, `cplat quiet` section). The same read in `ship.run_ci` and `red_summary` happens after CI is red, so an invalid value there would replace the red message with the settings error. That is low risk, because `cplat quiet` stops on the same value earlier in the build. Open follow-up (not blocking): read the setting before CI runs.

## Deviations from the plan

- **`scripts/cplat/cplat.py` (t4) and the `scripts/cplat/pr.py` docstring (t5)** were missed at first and fixed in 5dc00f6: the help line is now `cplat quiet [--raw] <script>` with the summary wording, and the docstring says exit 1 is red with a summary of each red check and its saved log path. Resolved.
- **`build.md` Phase 2 step 3 (`cplat validate run`) was not given the "with the summary" wording.** `validate run` itself now prints the summary, so the coder gets it as "the output". Acceptable.
- **`ship.run_ci` with summaries off** prints the last 40 lines including blank ones; before, it printed the last 40 non-empty lines. A cosmetic difference from "as today". Acceptable.
- **No acceptance test covers `cplat validate run`'s summary output.** It is outside AC-108.1, which is about `cplat quiet`. Its failure path runs in `tests/cplat/test_validate.py::test_a_red_run_leaves_no_passing_evidence`. Acceptable; an open follow-up (not blocking) is to add a test for it.
- Every task's `files` cover the changed files, apart from the docs and spec files of the spec itself (`docs/specs/108-*`, `docs/backlog.md`, the ADR), which are expected.

## Contract

The code matches `design.md`:

- limits and constants (`failsum/core.py:15-20`);
- the header and entry render;
- the shortening order;
- the `failsum` API (adding `message` and `FuncParser` is harmless);
- the settings function;
- `red_summary` / `red`;
- `attempt(normalized=)`, `snapshot(summary=)`, `escalate(summary=)`;
- the sidecar format;
- the benchmark task, the record key `summary_compare`, the output lines and the exit rule.

Since 5dc00f6 the design also describes the number masking, and the `cplat.py` usage line is updated.
