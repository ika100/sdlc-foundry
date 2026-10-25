# Verification — 090 A weekly retro proposes the next specs

**Result:** pass
**Commit:** 667ff4c · **Base:** 02ce991 (origin/main), red tests ed9204d · **Trace:** 14/14 criteria named by tests

Test run: `devbox run ci-local` 1572 passed (tester). Reviewer re-ran `test_retro_{cli,proposals,report,setup}.py` and
`test_runs.py`: 207 passed.

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-090.1 | met | `tests/cplat/test_retro_cli.py::test_retro_prints_the_report_of_the_last_complete_week_and_changes_nothing`, `::test_the_week_is_the_one_before_the_current_date_whatever_the_weekday`, `::test_a_week_that_is_not_complete_is_an_error`, `::test_out_writes_the_directory_and_removes_stale_proposals`; `test_retro_report.py::test_the_last_complete_week_before_today`, `::test_a_week_runs_from_monday_midnight_to_the_next_monday_midnight_utc` | `scripts/cplat/retro_report.py:36` (week), `:40` (bounds), `:99` (split); `scripts/cplat/retro.py:42`, `:91` (read only) | Test asserts no tracker write, no store put and unchanged store files. Stdout is `render_private` with a "Proposals: not generated" line, not `render_text` (see Deviations). |
| AC-090.2 | met | `test_retro_report.py::test_runs_per_kind_and_outcome_with_the_previous_week`, `::test_median_and_longest_duration_per_phase`, `::test_ci_rounds_and_reruns_in_total_and_per_run`, `::test_escalations_per_cause_and_reasons_ranked_by_runs_then_duration`, `::test_reruns_by_reason_and_by_check`, `::test_the_same_records_give_the_same_report_apart_from_the_timestamp`, `::test_the_text_shows_the_previous_value_next_to_every_figure`; `test_retro_cli.py::test_the_report_file_is_deterministic_apart_from_the_timestamp` | `retro_report.py:127` (runs), `:150` (phases), `:162` (CI), `:176` (escalations, rank key `:185`), `:193` (reruns) | Ranked escalation reasons show this week's run count and duration without a previous value. The cause totals do show one. The design specifies it this way (ranked reasons are covered-week only), so not blocking. |
| AC-090.3 | met | `test_retro_report.py::test_issues_filed_or_counted_again_in_the_week_are_listed_and_ranked`, `::test_issues_with_the_same_occurrences_are_sorted_by_number`, `::test_the_text_lists_the_issues_with_the_columns`; `test_retro_setup.py::test_auto_issues_are_read_with_their_comments_and_pull_requests_are_dropped`, `::test_a_failing_gh_call_is_a_tracker_error` | `retro_report.py:244` (signature `:25`, routed via `triage.DECISION_LABELS` `:261`, sort `:263`); `scripts/cplat/retro_github.py` | |
| AC-090.4 | met | `test_retro_report.py::test_one_row_per_agent_shape_model_with_the_089_metrics_of_both_weeks`, `::test_the_metrics_are_exactly_those_of_runs_report_agents`, `::test_unmeasured_metrics_print_n_a_and_few_runs_are_marked`, `::test_the_text_shows_the_previous_value_and_the_signed_difference` | `retro_report.py:275` (reuses `runs_report.aggregate_agents`), `:267` (diff), `:431` (cell, n/a), `:528` (few runs) | |
| AC-090.5 | met | `test_retro_report.py::test_a_week_without_records_is_stated_in_the_first_line_and_each_section_says_no_data`, `::test_records_without_agent_metrics_and_no_issues_name_only_those_sections`; `test_retro_cli.py::test_a_week_without_runs_still_produces_a_report`, `::test_a_failed_issue_read_is_an_error_not_no_data` | `retro_report.py:364` (no_data), `:447` (first line); `retro.py:79` (a failed issue read is an error, not "no data") | |
| AC-090.6 | met | `test_retro_cli.py::test_without_a_store_setting_the_retro_names_it_and_the_doctor_hint`, `::test_an_unreachable_store_names_the_repo_and_the_doctor_hint`, `::test_a_public_store_is_refused_with_the_visibility_hint`, `::test_a_store_that_cannot_be_read_names_the_error`, `::test_the_retro_and_doctor_give_the_same_store_hint` | `retro.py:57` (hint from `doctor.run_store_check`), `:72`; `scripts/cplat/doctor.py:216` | |
| AC-090.7 | met | `test_retro_proposals.py::test_a_proposal_without_evidence_is_refused_and_named`, `::test_a_proposal_that_breaks_the_format_is_refused`, `::test_at_most_five_specs_are_proposed`, `::test_each_proposal_renders_with_its_evidence_and_spec_command`; `test_retro_cli.py::test_a_proposal_without_evidence_is_refused_by_post_and_named_on_stderr`, `::test_at_most_five_specs_reach_the_issue` | `scripts/cplat/retro_proposals.py:118` (validate), `:68` (format), `:53` (evidence vs. `report["evidence"]`), `:141` (limit); `retro.py:179` (refused names on stderr) | |
| AC-090.8 | met | `test_retro_proposals.py::test_a_finding_an_open_spec_covers_is_named_as_an_amendment`, `::test_a_finding_an_open_issue_covers_is_named_as_see`, `::test_a_spec_that_does_not_exist_or_is_done_cannot_be_amended`, `::test_evidence_of_an_issue_turns_a_new_spec_into_see_issue`, `::test_a_spec_that_tracks_the_issue_wins_over_the_issue`; `test_retro_cli.py::test_a_proposal_that_names_an_open_issue_says_see_it` | `retro_proposals.py:83` (covers), `:212` (render "amends spec N" / "see #N"); `retro.py:81` (specs not done / superseded) | |
| AC-090.9 | met | `test_retro_proposals.py::test_a_prompt_proposal_names_agent_shape_metrics_and_change`, `::test_a_prompt_proposal_needs_a_metric_of_that_agent_from_the_report`, `::test_at_most_three_prompt_changes_are_proposed`; `test_retro_cli.py::test_at_most_three_prompt_proposals_and_no_agent_file_or_pull_request`, `::test_propose_runs_claude_headless_with_read_and_write_only_and_no_github_token` | `retro_proposals.py:147-171`; `retro.py:126-131` (Read,Write only; GitHub tokens removed from env) | |
| AC-090.10 | met | `test_retro_cli.py::test_post_creates_the_issue_with_the_retro_label_and_no_triage`, `::test_post_again_replaces_the_body_instead_of_creating_a_second_issue`, `::test_an_existing_closed_issue_of_the_week_is_edited_and_stays_closed`, `::test_nothing_is_written_when_the_report_cannot_be_built`; `test_retro_setup.py::test_create_makes_an_issue_with_the_retro_label_and_the_body_on_stdin`, `::test_create_makes_the_label_when_it_is_missing_and_tries_again` | `retro.py:208-216` | |
| AC-090.11 | met | `test_retro_cli.py::test_the_public_issue_has_no_private_name_and_the_store_has_the_full_report`, `::test_the_retro_index_keeps_other_weeks_and_replaces_this_one`, `::test_posted_text_from_the_agent_is_redacted_and_scrubbed`; `test_retro_report.py::test_the_public_body_has_no_private_name_and_uses_counts_and_placeholders`, `::test_a_kind_that_is_not_a_safe_token_never_appears_publicly` | `retro_report.py:440` (public placeholders `:495`, `:504`, repo list private only `:476`, scrub `:539`), `:392` (leaks); `retro.py:203` (leak check before any write), `:227-234` (store files and index) | Remaining risk: free text in the agent's proposals is checked only for repo, spec and store names plus redaction. A record reason that the agent copies word for word would not be caught. The prompt forbids it (`assets/retro-prompt.md`), as the design intends. |
| AC-090.12 | met | `test_retro_setup.py::test_the_workflow_runs_on_monday_0600_utc_on_the_self_hosted_runner`, `::test_the_workflow_runs_report_then_proposals_then_post_in_this_order`, `::test_a_failing_report_fails_the_run_and_skips_the_post_but_a_failing_proposal_step_does_not`, `::test_only_the_proposal_step_sees_the_claude_credential_and_it_sees_no_github_token`; `test_retro_cli.py::test_without_a_claude_credential_the_report_is_still_posted`, `::test_a_failed_proposal_step_still_posts_the_deterministic_report`, `::test_when_the_report_step_fails_nothing_is_created_or_changed` | `scripts/cplat/assets/workflows/cplat-retro.yml` (cron `0 6 * * 1`, `continue-on-error` only on install/propose); `retro.py:117` (propose always exits 0, writes `proposals.error`), `:182` | |
| AC-090.13 | met | `test_retro_cli.py::test_earlier_open_retro_issues_get_one_comment_with_the_link_and_are_closed`, `::test_a_second_post_does_not_comment_again`; `test_retro_setup.py::test_edit_comment_and_close_use_gh_issue_commands` | `retro.py:218-223` | The test covers closed, later-week and unlabelled issues being left untouched. |
| AC-090.14 | met | `test_retro_setup.py::test_init_of_a_new_store_adds_the_schedule`, `::test_init_of_an_existing_store_without_the_schedule_adds_only_it`, `::test_init_again_changes_nothing`, `::test_a_rejected_workflow_write_is_a_warning_with_the_scope_fix`, `::test_doctor_warns_naming_everything_that_is_missing`, `::test_doctor_names_only_the_missing_secret`, `::test_the_retro_check_is_part_of_doctor_and_never_fails_it` | `scripts/cplat/retro_setup.py` (`install_schedule`, `missing`); `scripts/cplat/runs.py:762`; `doctor.py:241` (`check_retro_schedule`), `:274` | |

## Non-goals

No code writes specs, starts builds, routes the issue through triage, files a proposal as its own issue, edits agent
files or opens pull requests. The only tracker calls are `auto_issues`, `open_issues`, `retro_issues`, `create`,
`edit_body`, `comment` and `close`, which the AC-090.9 CLI test asserts. No consumer-repo retro, no notification channel
and no charts. ✔

## Deviations from the plan

- **Harness fix in the acceptance tests** (`fdb2c52`, `tests/cplat/test_retro_setup.py:71`, `s is not prop` changed to
  `s != prop`). `steps()` re-parses the YAML on every call, so the identity check was always true. That made the
  assertion apply to the proposal step itself, and no correct workflow could pass. The intent is unchanged: no other
  step may see the Claude credential. The workflow has no two identical steps, so comparing by value excludes only the
  proposal step. Acceptable.
- **Report-mode stdout** (`retro.py:93`) prints `render_private` with
  `Proposals: not generated (no proposal step ran)`. The design asks for `render_text`. The output is local and private,
  and AC-090.1 only asks that the report is printed and nothing is written. The CLI test expects this output.
  Acceptable. The "not generated" line is slightly misleading in a report-only run.
- **ADR number** renumbered from 036 to 039 because of a merge collision. `docs/adr/039-…` and `docs/adr/README.md` are in
  no task's `files`. Acceptable, since the plan names the ADR. Cosmetic: the link text at `plan.md:75` still says `[036]`.
- **Leak error text** (`retro.py:205`) reads "would name N private name(s); nothing was posted", not the design's exact
  string. It still gives the count without the names. Acceptable.
- Every other changed file is in a task's `files`. All 8 tasks are `done: true`.

## Contract

Matches `design.md`: CLI commands and exit codes, store error messages and hints, report keys and evidence index,
proposal validation order and refusal lines, post order (every read and the leak check happen before the first GitHub
write), the retro issue's title, label and editing, the earlier-issue comment and close, the store files and index,
the workflow asset, `install_schedule` and `missing` lines, and the doctor fix strings. The only exceptions are the
deviations above. ✔
