# Verification — 180 Prompt checks test behaviour not sentences

**Result:** pass
**Commit:** 82de5d58 · **Base:** b4d184a4 · **Trace:** 7/7 criteria named by tests

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-180.1 | met | `tests/cplat/test_180_prompt_refs.py::test_a_link_to_a_missing_file_is_a_broken_link_with_line_and_target_ac_180_1`, `::test_an_anchor_must_match_a_heading_slug_of_the_target_ac_180_1`, `::test_a_cplat_command_that_is_not_offered_fails_ac_180_1`, `::test_a_slash_command_no_plugin_defines_fails_ac_180_1`, `::test_the_rules_check_reports_prompt_file_line_and_missing_target_ac_180_1`, `::test_a_prompt_with_all_targets_present_passes_the_check_ac_180_1` | `scripts/cplat/promptrefs.py:113` (targets), `:156` (problems), `:141` (cplat names); `scripts/cplat/rulescheck.py:148` (wired into the check) | Every kind is covered: missing file, missing anchor, unknown cplat noun and verb, unknown slash command. The tests assert the file, the line and the missing target in the message, and a clean pass when every target exists. |
| AC-180.2 | met | `tests/cplat/test_180_prompt_pins.py::test_a_literal_of_four_words_from_a_prompt_is_a_pin_ac_180_2`, `::test_whitespace_is_collapsed_and_implicit_concatenation_is_one_literal_ac_180_2`, `::test_a_marker_on_the_line_or_the_line_above_covers_the_pin_ac_180_2`, `::test_a_marker_two_lines_away_does_not_cover_the_pin_ac_180_2`, `::test_the_rules_check_reports_pins_and_markers_with_file_and_line_ac_180_2` | `scripts/cplat/promptpins.py:60` (scan), `:78` (4 words, collapsed substring), `:86` (marker on the line or the line above); `scripts/cplat/rulescheck.py:243`; `rulescheck.py:262` renders the literal | The tests assert the file, the line, the literal and a hint naming both structure and interface. They also check the 3-word reason, and that a marker on the line or the line above covers the pin while one two lines away does not. |
| AC-180.3 | met | `tests/cplat/test_180_prompt_pins.py::test_a_marker_with_fewer_than_three_words_fails_ac_180_3`, `::test_a_marker_on_a_line_without_a_prompt_literal_fails_ac_180_3`, `::test_the_rules_check_reports_pins_and_markers_with_file_and_line_ac_180_2` (names AC-180.3) | `scripts/cplat/promptpins.py:87` (short), `:94` (stray) | Through both the scan and `rules check`, the tests assert `short-interface` and `stray-interface` with the file and the line. |
| AC-180.4 | met | `tests/cplat/test_180_repo_rules.py::test_the_repo_rules_check_passes_and_reports_the_interface_pins_ac_180_4`, `::test_the_repo_rules_check_json_gives_targets_and_interface_pins_ac_180_4`, `::test_the_text_and_json_pin_counts_agree_ac_180_4`, `::test_spec_check_stays_green_ac_180_4`, `::test_every_criterion_id_tested_at_the_base_commit_is_still_tested_ac_180_4` | `scripts/cplat/rulescheck.py:260` (OK line with the interface pins), `:225` (counts); `.github/workflows/ci.yml:118` and `scripts/ci-local.sh:39` run the check in CI; `scripts/cplat/spec.py:426` (`trace`, used by the new test) | The cycle 1 TEST LOOSER finding is fixed. The new test (`test_180_repo_rules.py:46`) collects every criterion id that a file under `tests/` names at the base commit `b4d184a4` (`:50`). It then traces every active criterion of every spec with `spec.trace` and asserts that no id from that set now has zero test files (`:57`-`:59`). That is the clause "every criterion id of an earlier spec that had a test before the rewrite still has at least one test". Taking ids from all of `tests/` at the base gives a superset, so the check is stricter than the clause, not looser. CI checks out with `fetch-depth: 0` (`ci.yml:36`), so the base commit exists there and the assertion actually runs. The other clauses (the check passes, the pin count appears in text and `--json`, `spec check` is green) were already proven in cycle 1. |
| AC-180.5 | met | `tests/cplat/test_180_rules_rebaseline.py::test_a_passing_gate_raises_the_baseline_and_records_history_ac_180_5`, `::test_the_command_prints_the_old_and_new_count_ac_180_5`, `::test_the_module_api_takes_today_and_returns_the_outcome_ac_180_5`, `::test_a_second_raise_appends_the_newest_entry_last_ac_180_5`, `::test_the_register_loader_reads_the_history_ac_180_5` | `scripts/cplat/rules_rebaseline.py:89` (rebaseline), `:108` (gate), `:51` (line edits); `scripts/cplat/promptrules.py:455` (history validation) | The tests assert the baseline bytes, the HEAD commit, a history entry with exactly date, old, new, reason and run ids, the newest entry last, and the old and new count in the output. |
| AC-180.6 | met | `tests/cplat/test_180_rules_rebaseline.py::test_a_failing_gate_refuses_with_the_benchmark_command_ac_180_6`, `::test_a_failed_benchmark_refuses_ac_180_6`, `::test_a_dirty_tree_refuses_and_names_the_path_ac_180_6`, `::test_a_reason_under_three_words_refuses_ac_180_6`, `::test_prompts_within_the_baseline_need_nothing_ac_180_6` | `scripts/cplat/rules_rebaseline.py:100` (reason), `:102` (dirty), `:105` (nothing), `:112` (gate failures) | The tests check that the register is unchanged byte for byte. The dirty case is the exception: there the test checks only `prompt_bytes`, but any write changes that value, so an unchanged value proves nothing was written. In the "nothing" case the test also proves that the gate is not called. |
| AC-180.7 | met | `tests/cplat/test_180_rules_baseline_prcheck.py::test_a_raise_with_a_matching_history_entry_passes_and_shows_the_entry_ac_180_7`, `::test_a_hand_edit_without_a_history_entry_fails_naming_the_register_line_ac_180_7`, `::test_a_newest_entry_that_differs_from_the_baseline_fails_ac_180_7`, `::test_pr_check_shows_the_notes_in_json_and_the_ok_line_names_the_rule_ac_180_7`, `::test_pr_check_fails_a_hand_edited_raise_ac_180_7` | `scripts/cplat/rules_baseline.py:20`; `scripts/cplat/house_rules.py:122` (rule), `:159` (JSON notes), `:163` (text notes) | The tests assert the exact note, the messages and the register line. No test asserts the note in the text output, but `house_rules.py:163` prints it there and the JSON test shows its content. |

## Non-goals

- Prompts were not reworded: `plugins/` and `.claude-plugin/` are unchanged in `b4d184a4..HEAD`. ✔
- No template or generated-repo tests were touched. ✔
- The benchmark does not run in CI: `rebaseline` reads local run records (`rules_rebaseline.py:108`). ✔
- The baseline is never lowered: when the prompts are not larger than the baseline, `rebaseline` returns "nothing" (`rules_rebaseline.py:105`). ✔
- The pin scan reads only `*.py` (`promptpins.py:68`). ✔
- No template-owned layout is affected, since this is the platform repo.

## Deviations from the plan

- `docs/specs/127-*/spec.md` and `docs/specs/185-*/spec.md` changed outside every task. They came from the merge of `main` (#674, commit 6009667a), not from the build. Acceptable.
- t10 changed no prompt, because the targets check found nothing to fix in `plugins/`. Acceptable: the plan allows "none reported, no change".
- t7's "Done when" relies on `cplat spec check` to report a criterion that lost its last test, but `spec check` does not trace criteria. The tightened AC-180.4 test (commit 82de5d58) now covers that clause. Acceptable.
- Every task is `done: true`. Every other touched file is in a task's `files`: `chain_support.py` is covered by t9's `*_support.py`, `structure.py` by t1 and `test_168_rules_retire_gate.py` by t6.

## Contract

Matches `design.md`, with these small differences, all acceptable:

- `rules_baseline.check` takes `notes` as optional.
- `rebaseline` prints a refusal to stderr; the design does not say which stream.
- The `rules_baseline.py:5` docstring cites the design path `180-prompt-checks-test-behaviour-not-t`, which is a typo.

## Tightened acceptance tests

| File | Reason | Asserts the criterion as written |
|---|---|---|
| `tests/cplat/test_180_repo_rules.py` (commit 82de5d58) | Cycle 1 TEST LOOSER on AC-180.4: no test checked that criteria with a test before the rewrite still have one. Added `test_every_criterion_id_tested_at_the_base_commit_is_still_tested_ac_180_4`, recorded with `cplat spec test-diff --tighten`. | Yes. It compares the ids tested at `b4d184a4` with the ids `spec.trace` finds now. Nothing was loosened: the commit adds 21 lines and removes none. |

## Frozen-test change (approved)

`tests/cplat/test_180_rules_baseline_prcheck.py` (commit 0c5a6f2d) changed only its setup: `--allow-empty` in `commit`, and `reg()` now keeps the demo hard table. No assertion changed, so it still asserts AC-180.7 as written.

## Observations (no verdict impact)

- The pin guard covers only literals of 4 or more words, so shorter prompt phrases can still be pinned, for example `"do not tag"` and `"at most twice"` in `test_143_waits_docs.py:64,74`. That stays within the spec's threshold.
- The build added about 90 `# interface:` markers. In a sample, most name output that cplat prints or reads, as the spec intends. A few cover guide or prompt wording, for example `test_backup_117_cmds.py:770` and `test_143_waits_docs.py:72`.
- In the new AC-180.4 test, the skip `if s.id == "180"` (`test_180_repo_rules.py:55`) never matches, because `Spec.id` is the full directory name (`spec.py:134`). So spec 180 is checked like the others. This is harmless: no file under `tests/` named an AC-180 id at the base, so none of its ids can be reported. Cosmetic.
- When the base commit is missing (a shallow clone), the new test passes without checking anything (`:47`-`:49`). A `pytest.skip` would make that visible. CI fetches the full history, so the assertion runs there.

## Mutation check (report only)

Skipped: no mutation check for shape platform yet.
