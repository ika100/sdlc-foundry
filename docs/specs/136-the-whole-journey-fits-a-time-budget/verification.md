# Verification — 136 The whole journey fits a time budget

**Result:** pass
**Commit:** e0feb810 · **Base:** d83a9d43 · **Trace:** 4/4 active criteria named by tests · **Tests:**
`pytest tests/cplat -q -n auto` 7739 passed, 12 skipped; `devbox run validate` and `devbox run quality` green · **Cycle:** 2 (cycle 1 failed on AC-136.11, since withdrawn)

All four active criteria (AC-136.1, AC-136.2, AC-136.3, AC-136.8) are met. AC-136.11 was withdrawn on 2026-11-05 by the
user's decision and moved to spec 144; cycle 1 had judged it not met (not built), see History.

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-136.1 | met | `tests/cplat/test_136_journey_record.py::test_a_finished_journey_lists_every_stage_with_its_time_fields_prs_and_rounds_ac_136_1`, `::test_every_stage_carries_the_budget_of_the_spec_table_ac_136_1`, `::test_parts_and_the_journey_get_the_same_time_fields_ac_136_1`, `::test_a_stage_that_never_started_is_not_run_never_zero_minutes_ac_136_1`, `::test_a_journey_that_stops_keeps_its_open_stage_as_stopped_at_the_end_ac_136_1`, `::test_every_extra_round_has_a_kind_and_a_cause_ac_136_1`, `::test_journey_verbs_need_an_open_journey_and_only_one_is_open_ac_136_1`, `::test_show_prints_the_stages_so_far_ac_136_1` | `scripts/cplat/runs_journey.py:27-36` (stage table, budgets, round kinds), `:116-161` (`compute`: one entry per stage with part, start, end, the four minute fields, budget, PRs, extra rounds; parts and `total` with the same fields; `not run` with null times), `:198-345` (the verbs; `end` writes the section through `runs.finish`), `scripts/cplat/runs.py:968-970` (dispatch) | "When it ends or stops": `end --outcome escalated\|failed\|abandoned` writes the record too, and a stage still open is `stopped` at the journey's end. Causes are the run-record causes. |
| AC-136.2 | met | `test_136_journey_record.py::test_a_part_is_the_span_of_overlapping_stages_and_less_than_their_sum_by_the_overlap_ac_136_2`, `::test_a_part_subtracts_the_person_waits_inside_its_span_once_ac_136_2` | `scripts/cplat/runs_journey.py:140-151` (`group`: span from the first start to the last end, person waits inside the span once, `stages_sum_minutes`, `overlap_minutes`), `:60-95` (interval union, difference, overlap) | Three stages of 3, 2 and 4 min that overlap give a part of 6 = 9 − 3. A person wait inside two stages is counted in both stages and once in the part. |
| AC-136.3 | met | `test_136_journey_record.py::test_a_person_wait_is_left_out_of_working_time_and_an_external_wait_is_kept_ac_136_3` (the spec's 10 + 5 case), `::test_a_wait_measured_afterwards_is_added_with_its_minutes_ac_136_3`, `::test_a_minute_that_is_both_waits_counts_as_person_wait_only_ac_136_3`, `::test_a_github_rate_limit_wait_of_cplat_is_an_external_wait_of_the_open_journey_ac_136_3`, `::test_a_rate_limit_wait_without_a_journey_changes_nothing_ac_136_3` | `scripts/cplat/runs_journey.py:102-107` (`_times`: wall includes both waits, working excludes person only, external minus person), `:244-271` (`wait start\|end\|add`), `:348-361` (`note_external_wait`), `scripts/cplat/core.py:53-58,91` (the rate-limit hook) | The hook never raises or prints; without an open journey it does nothing. |
| AC-136.8 | met | `tests/cplat/test_136_journey_report.py::test_per_stage_the_median_working_and_wall_of_done_runs_with_budget_overrun_and_waits_ac_136_8`, `::test_parts_and_the_whole_journey_get_the_same_columns_ac_136_8`, `::test_stages_are_ranked_by_median_overrun_largest_first_ac_136_8`, `::test_the_previous_platform_versions_median_stands_next_to_it_ac_136_8`, `::test_each_coordinator_model_is_its_own_group_ac_136_8`, `::test_a_stage_that_did_not_run_is_left_out_of_its_median_ac_136_8`, `::test_the_existing_keys_are_unchanged_and_journey_is_added_ac_136_8`, `::test_the_text_report_has_the_journey_table_with_working_and_wall_columns_ac_136_8`, `::test_no_journey_record_says_so_ac_136_8`, `::test_a_recorded_journey_shows_up_in_the_report_ac_136_8` | `scripts/cplat/runs_journey_report.py:50-108` (medians over done runs, overrun, previous version by numeric compare per model, ranking), `:115-133` (text), `scripts/cplat/runs_usage_report.py:145,167` (key `journey` after the existing keys; text after the benchmark lines) | The existing benchmark tests (`test_runs_usage_bench.py`, `test_bench_arms.py`) pass unchanged. Text groups are newest version first (design). |

## Non-goals

- No budget overrun fails anything: the report shows and ranks overruns, `journey end` exits 0 whatever the times. ✔
- No stage time limit stops a run; spec 102's run-tree limits are untouched. ✔
- No cost or token budget was added; a live journey's record carries the usual `usage` section (spec 099). ✔
- Person-wait is recorded, not budgeted. ✔
- No headless journey benchmark command, cleanup, interventions, release or retro hook (the Later section). ✔
- The platform repo's CI is untouched. ✔

## Deviations from the plan

- **D1: acceptable.** A follow-up commit (e0feb810) shows still-running stages as `open` in `journey show` and makes a
  `begin --at` (a reconstructed journey) claim no Claude Code session, so its `usage` is not the measuring session's. Both are
  in design.md.
- **D2: acceptable.** The design change "newest platform version first" in the text report was made while t3 was built, so
  the first block is the latest version's.
- **D3: resolved.** t6 (AC-136.11) was removed from the plan when the criterion moved to spec 144.
- No acceptance test changed after the red commit 7118b9c6.

## History

- Cycle 1 (d0e8a1e2): fail. AC-136.11 not met: not built, measured in design § AC-136.11 (journey 2: three dev PRs for
  system spec 002 where one is allowed, four for the part 3 environment settings).
- Cycle 2: pass. The user withdrew AC-136.11 on 2026-11-05 and moved it to spec 144; no code changed between the cycles.
