# Verification — 206 Headless deny rules are checked before a session starts

**Result:** pass
**Commit:** c28d575c · **Base:** 88daccf6 · **Trace:** 7/7 criteria named by tests

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-206.1 | met | `tests/cplat/test_206_deny_rules.py::test_the_samples_are_the_ones_of_the_spec_ac_206_1`, `::test_no_generated_rule_refuses_a_command_the_run_needs_ac_206_7`, `::test_a_rule_that_refuses_a_needed_command_stops_the_run_ac_206_4` (component ship and `/system:ship`) | `scripts/cplat/denyrules.py:25`, `scripts/cplat/preflight.py:282-285`, `scripts/cplat/headless.py:514` | The sample is compared in full against a hand-written copy of the spec's text. `/component:build` is not run end to end, but it goes through the same `covered` path (`headless.py:475-481`, `:511-514`) and `branches_of` treats it the same as ship. |
| AC-206.2 | met | `::test_the_must_refuse_sample_is_the_one_of_the_spec_ac_206_2`, `::test_every_command_the_run_must_not_run_is_refused_ac_206_7`, `::test_a_missing_refusal_stops_the_run_ac_206_5` | `scripts/cplat/denyrules.py:35`, `:171-175` | |
| AC-206.3 | met | `::test_a_rule_matches_a_command_as_claude_code_does_ac_206_3` (26 cases: `*` across spaces, trailing ` *` and `:*` on the bare command, assignments, all five wrappers, `&&`/`\|\|`/`;`/`\|`, non-Bash rules) | `scripts/cplat/denyrules.py:54-132` | Matches the design contract: splitting is quote-aware and the stripped text is taken from the original by offset. |
| AC-206.4 | met | `::test_the_old_gh_api_rule_is_named_with_its_correction_ac_206_4`, `::test_where_no_single_rule_is_right_the_line_says_remove_the_rule_ac_206_4`, `::test_a_rule_that_refuses_a_needed_command_stops_the_run_ac_206_4`, `::test_the_correction_passes_the_whole_sample_ac_206_4`, `::test_a_rule_without_a_correction_gives_none_ac_206_4`, `::test_the_deny_check_runs_before_the_other_preflight_checks_ac_206_4` | `scripts/cplat/denyrules.py:137-170`, `scripts/cplat/preflight.py:284-285`, `scripts/cplat/headless.py:514-518` | Each test checks the exact line, exit 1, no session, 0 invocations and 0 cost (no model call), and the reason `preflight failed: deny-rules`. |
| AC-206.5 | met | `::test_a_missing_refusal_stops_the_run_ac_206_5`, `::test_a_missing_refusal_with_no_generated_rule_adds_the_command_itself_ac_206_5`, `::test_a_default_branch_a_rule_cannot_guard_stops_the_run_ac_206_5` (`*`, `(`, `)`, `,`, space, tab), `::test_the_unguardable_default_branch_wins_over_every_other_finding_ac_206_5` | `scripts/cplat/denyrules.py:163-164`, `:171-175` | |
| AC-206.6 | met | `::test_the_merge_rules_replace_the_loose_gh_api_rule_ac_206_6`, `::test_a_read_of_the_merge_state_is_not_refused_ac_206_6`, `::test_every_merge_command_is_still_refused_ac_206_6`, `tests/cplat/test_184_allowlist.py` (`REFUSED_BEFORE`) | `scripts/cplat/denyrules.py:18` | |
| AC-206.7 | met | `::test_no_generated_rule_refuses_a_command_the_run_needs_ac_206_7`, `::test_every_command_the_run_must_not_run_is_refused_ac_206_7` (4 defaults × 2 ship branches), `::test_the_whole_check_passes_for_the_generated_rules_ac_206_7`, `::test_an_over_matching_rule_fails_with_its_name_and_the_command_ac_206_7`, `::test_an_under_matching_set_fails_with_the_command_ac_206_7` | `scripts/cplat/denyrules.py:162-176` | The assertion messages name the rule and the command. |

## Non-goals

None of the non-goals is implemented. The rules do not allow a force push of the run branch: `test_every_command_the_run_must_not_run_is_refused_ac_206_7` covers `--force-with-lease`. The user's settings layers are not checked by the new code, and `git -C`/`sh -c` pushes are not guarded. The `gh api` rule is only narrowed (`denyrules.py:18`), so no new action is refused. No template layout changed.

## Deviations from the plan

None. Every changed file is in the `files` of a task, and t1, t2 and t3 are `done: true`. `preflight.matches` and `check_repo` are unchanged, as the design requires.

## Contract

Matches `design.md`: `preflight.refused_rules is denyrules.refused_rules`, `check(..., deny=None)` runs first, the order of the failures in `problem`, the order of the edits in `correction`, and the example lines (checked word for word by the AC-206.4 and AC-206.5 tests).

## Mutation check (report only)

Skipped: no mutation check for shape platform yet.
