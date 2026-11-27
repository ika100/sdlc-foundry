# Verification — 223 Change quality: fix causes and attempts to done

**Result:** pass
**Commit:** 7cf4a503 · **Base:** b5592fa1 (d7b9424~1) · **Trace:** 9/9 criteria named by tests

Test run (orchestrator summary): test-fast 1533 passed, 1 skipped; the spec's tests green 3 times in a row; `devbox run ci` green; no acceptance test changed after the freeze.

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-223.1 | met | `tests/cplat/test_223_fix_causes.py::test_a_fixed_fragment_without_a_valid_cause_line_is_one_error_ac_223_1`, `::test_pr_check_prints_one_error_line_for_it_ac_223_1`, `::test_added_and_changed_fragments_need_no_cause_line_ac_223_1`, `::test_a_fragment_already_on_the_base_is_never_checked_ac_223_1`, `::test_ci_fragment_check_fails_a_fixed_fragment_without_cause_ac_223_1`, `::test_parse_cause_refuses_other_forms_ac_223_1` | `scripts/cplat/fixcause.py:18-57` (FORM, CAUSE_LINE, `form_error`), `scripts/cplat/house_rules.py:71-80,123-124` (only added fragments), `scripts/release-check.py:181-196,330`, `.github/workflows/ci.yml:179-182` | Tests assert exactly one `ERROR:` line, the fragment name and the full expected form, for pr-check and for the CI check (`FAILED: 1 problem(s)`, exit 1); added/changed fragments and fragments already on the base pass. |
| AC-223.2 | met | `test_223_fix_causes.py::test_a_pr_that_is_not_merged_is_an_error_ac_223_2` (404 and `merged_at` null), `::test_a_tag_that_does_not_exist_is_an_error_ac_223_2`, `::test_a_merged_pr_and_an_existing_tag_pass_ac_223_2`, `::test_unreachable_github_is_one_warning_and_no_failure_ac_223_2`, `::test_unreachable_github_for_a_tag_is_a_warning_too_ac_223_2`, `::test_verify_returns_errors_and_warnings_ac_223_2` | `scripts/cplat/fixcause.py:106-129` (`verify`), `scripts/cplat/house_rules.py:81-94` (slug, WARNING notes) | Unreachable test asserts rc 0, exactly one `WARNING:` line naming #812 and no `ERROR:` line. CI check makes no gh call (`test_ci_fragment_check_passes_a_valid_cause_without_network_ac_223_1`), as A3 states. |
| AC-223.3 | met | `test_223_fix_causes.py::test_the_released_entry_keeps_the_cause_line_ac_223_3` | `scripts/cplat/platrelease_changelog.py` unchanged (assemble copies the body); `fixcause.entries` `scripts/cplat/fixcause.py:60-71` | Asserts the released `### Fixed` entry's last line is `Caused by: #812` after `move_unreleased`. |
| AC-223.4 | met | `tests/cplat/test_223_change_quality.py::test_one_row_per_release_with_the_fixes_it_caused_ac_223_4`, `::test_same_release_fix_is_caught_before_release_and_the_rest_is_counted_apart_ac_223_4`, `::test_the_change_failure_rate_over_all_and_over_minor_releases_ac_223_4`, `::test_an_unreleased_fixed_fragment_is_a_carrier_too_ac_223_4`, `::test_a_version_without_a_heading_is_an_error_ac_223_4` | `scripts/cplat/changequality.py:63-158` (attribution rules, rate), `:166-189` (text), `scripts/cplat/changequality_sources.py:341-358` (PR to release) | Asserts `5.30.0: 2, carried by 5.30.1`, `caught before release: 1`, `change-failure rate: 1 of 3 releases (33%)` and the minor/major rate `1 of 2 (50%)`; `none` listed apart. The fixture holds both a no-cause entry and an `unknown` entry, so it asserts `unattributed: 2`: the spec's rule (no cause line or `unknown`) applied to one more entry, not a looser assertion. |
| AC-223.5 | met | `test_223_change_quality.py::test_the_row_shows_carriers_stopped_journeys_and_affected_repos_ac_223_5`, `::test_the_json_blast_radius_ac_223_5`, `::test_an_unreleased_fragment_id_names_a_stopped_journey_without_a_link_ac_223_5`, `::test_an_unreadable_fleet_is_unknown_never_zero_ac_223_5`, `::test_the_fleet_is_read_only_when_a_release_caused_a_fix_ac_223_5` | `scripts/cplat/changequality.py:55-60,133-144`, `scripts/cplat/changequality_sources.py:361-425` (journeys, fleet stamp history, `FleetUnknown`) | Fleet fixture covers held / never held / not platform / skipped-over versions (`repos: 1 (o/a)`); journey 13 (not stopped) excluded, 14 included, fragment id 812 matches journey 16; an unreadable fleet gives `repos: unknown` and `"unknown"` in JSON, never 0. |
| AC-223.6 | met | `test_223_change_quality.py::test_json_is_one_document_with_the_contract_keys_ac_223_6`, `::test_outside_the_platform_repo_it_names_the_platform_repo_ac_223_6` | `scripts/cplat/changequality.py:148-158,200-227`, `scripts/cplat/cplat.py:42,101` | Whole stdout parses as JSON with exactly the seven top-level keys; release rows carry the five named keys (plus `date`, `affected_reason` from design.md); outside the platform repo rc 1, empty stdout, `ika100/sdlc-foundry` on stderr. |
| AC-223.7 | met | `tests/cplat/test_223_chains.py::test_a_chain_shows_attempts_cost_and_the_share_outside_the_success_ac_223_7`, `::test_the_json_item_of_the_chain_ac_223_7`, `::test_a_child_record_adds_its_cost_once_and_is_no_attempt_ac_223_7`, `::test_a_failed_attempt_is_counted_apart_ac_223_7`, `::test_the_same_spec_in_two_repos_is_two_chains_ac_223_7`; `tests/cplat/test_runs_report_unclassified.py::test_the_json_report_has_the_unclassified_key` | `scripts/cplat/runs_chains.py:15-80` (key, cost, attempts, family of the successful run), `:120-138` (text), `scripts/cplat/runs_report.py:266-268,465-466` | Fixture is the spec's $4.00 escalated, $1.50 abandoned, $2.00 done; asserts 3 attempts, 1 escalation, 1 abandon, 0 failed, `attempts to done: 3`, `chain cost $7.50`, `successful run $2.00`, `73%`; a child with $1.00 adds once (8.5, 3.0, 65%) and is no attempt; a headless record is no part of the chain (A8). |
| AC-223.8 | met | `test_223_chains.py::test_the_text_summary_per_delivered_item_ac_223_8`, `::test_the_json_chains_summary_and_the_old_keys_ac_223_8`; `tests/cplat/test_runs_report.py::test_json_output_has_stable_keys_and_nothing_else_on_stdout` | `scripts/cplat/runs_chains.py:83-105,132-136` | Asserts done 2 / not done 2, median attempts 2, cost per delivered $5.25 next to median successful $2.50, open spend $2.00, in text and JSON; the exact existing key order with `chains` appended. |
| AC-223.9 | met | `test_223_chains.py::test_an_unreadable_cost_is_unknown_never_zero_ac_223_9`, `::test_a_chain_begun_before_the_window_is_partial_ac_223_9`, `::test_records_without_spec_or_issue_are_unchained_ac_223_9` | `scripts/cplat/runs_chains.py:27-38` (unknown cost), `:79` (partial), `:85-95` (unchained, `cost_per_delivered` only over complete chains), `:126` (`>= $X +unknown`) | Asserts `chain cost >= $1.20 +unknown`, no `$0.00`, `cost_per_delivered` null; `partial` only for the chain begun before the window; `unchained: 2` with no chain. |

## Non-goals

- No cause lines for component repos or issues: the rule lives in the platform's `house_rules` fragment rule and `release-check.py` only. ✔
- No backfill: `docs/CHANGELOG.md` is unchanged on the branch; old entries count as `unattributed`. ✔
- No chains or change-failure rate in the weekly retro: no `retro*` module changed. ✔
- No revert, block or hold by change-failure rate: change-quality only reports. ✔
- No classification of why a fix was needed: only the cause link is parsed. ✔
- No template-owned layout change (no template, header, footer or navigation touched). ✔

## Deviations from the plan

- `docs/adr/132-fix-entries-name-their-cause.md`, `docs/adr/README.md`: in no task's `files`, but design.md asks for this ADR (renumbered from 131, taken on another branch); acceptable.
- `tests/cplat/cq223_world.py`: the fake `gh` script is wrapped in `waiting.with_prelude` (test harness, ADR-097); no assertion changed; acceptable.
- `tests/cplat/test_runs_report.py:143`, `tests/cplat/test_runs_report_unclassified.py:93`: existing tests pinning the top-level key order now include the appended `chains` key, which AC-223.8 requires; acceptable.
- Every task has `done: true`; no `ux.md` (platform CLI only).

## Contract

Matches `design.md`: messages, cause regex, `release-check.py fragments` output, change-quality text and JSON keys, `chains` JSON (including `unchained`, which design.md defines for AC-223.9) and text lines. ✔

## Mutation check (report only)

Skipped: no mutation check for shape platform yet.
