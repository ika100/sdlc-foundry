# Verification — 093 Green dev smoke promotes to staging

**Result:** pass
**Commit:** df5c70c · **Base:** 2d6412f · **Trace:** 15/15 active criteria named by tests (AC-093.2 withdrawn); 106 tests in `tests/cplat/test_staging_093_*.py` pass (re-run by the reviewer); `devbox run ci-local` 1955 passed (orchestrator)

Test files: `ship` = `tests/cplat/test_staging_093_ship.py`, `setting` = `tests/cplat/test_staging_093_setting.py`, `evidence` = `tests/cplat/test_staging_093_evidence.py`.

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-093.1 | met | `ship::test_a_green_dev_smoke_dispatches_the_pin_and_reports_the_promotion_ac_093_1`, `ship::test_the_staging_window_is_fifteen_minutes_ac_093_1`, `ship::test_a_pin_that_does_not_land_in_fifteen_minutes_escalates_ac_093_1`, `ship::test_both_green_outcomes_promote_ac_093_1`, `setting::test_the_workflow_is_triggered_by_the_dispatch_and_named_for_ship_ac_093_1`, `setting::test_the_workflow_validates_its_inputs_and_pins_staging_ac_093_1` | `scripts/cplat/staging_deploy.py:111` (dispatch at :127, window at :172, `STAGING_WINDOW_S = 900` at :21), `scripts/cplat/ship.py:748`, `templates/gitops-app/.github/workflows/pin-staging.yml:43-116` (pin, CI, self-merge) | Tag is `st["deployed"]` (`sha-<40>`), the tag dev runs. The workflow is checked statically, as the design says. |
| AC-093.3 | met | `ship::test_a_red_dev_smoke_promotes_nothing_and_says_why_ac_093_3`, `ship::test_a_dev_smoke_that_was_not_run_promotes_nothing_ac_093_3`, `ship::test_the_record_says_skipped_with_the_reason_ac_093_3`, `ship::test_red_and_timed_out_dev_skip_with_dev_smoke_red_ac_093_3`, `ship::test_not_run_dev_skips_with_its_reason_ac_093_3` | `scripts/cplat/staging.py:156-159`, `scripts/cplat/ship.py:766` | A promotion starts only from `_smoke_finish` in ship, so a build merged outside ship is never promoted. |
| AC-093.4 | met | `ship::test_a_service_not_yet_in_staging_is_not_promoted_and_the_first_step_is_named_ac_093_4` | `scripts/cplat/staging.py:169-170` | |
| AC-093.5 | met | `ship::test_a_staging_that_runs_a_later_commit_is_left_alone_ac_093_5`, `ship::test_a_staging_that_already_runs_the_build_is_left_alone_ac_093_5`, `ship::test_a_staging_tag_of_seven_characters_resolves_to_the_build_ac_093_5`, `ship::test_a_release_tag_in_staging_resolves_through_the_tag_commit_ac_093_5`, `setting::test_a_newer_promotion_closes_the_older_open_ones_ac_093_5` | `scripts/cplat/staging.py:173-179`, `pin-staging.yml:71-74` | |
| AC-093.6 | met | `ship::test_a_failed_gitops_ci_leaves_staging_and_escalates_with_the_run_ac_093_6`, `ship::test_a_pr_closed_without_merging_escalates_ac_093_6`, three `ship::test_a_resume_…_ac_093_6`, `setting::test_a_red_ci_leaves_the_pr_open_with_a_comment_ac_093_6` | `scripts/cplat/staging_deploy.py:161-165`, `:248-268`, `pin-staging.yml:104-107` | |
| AC-093.7 | met | `setting::test_the_pr_says_it_is_automatic_and_names_what_changed_ac_093_7`, `ship::test_record_url_is_none_without_a_store_and_a_blob_link_with_one_ac_093_7` | `pin-staging.yml:59-70`, `scripts/cplat/staging.py:65-69` | A revert restores `<old>` because the PR changes only the overlay `newTag`. The record link is a predicted path; the design accepts this risk. |
| AC-093.8 | met | `ship::test_staging_is_smoked_against_its_published_url_ac_093_8`, `ship::test_staging_smoke_passed_on_retry_is_reported_like_dev_ac_093_8`, `ship::test_the_run_record_has_both_outcomes_and_the_promotion_ac_093_8`, `ship::test_the_state_and_describe_carry_the_staging_result_ac_093_8` | `scripts/cplat/staging_deploy.py:187-237`, `scripts/cplat/ship.py:734` (dev `image`/`at`), `scripts/cplat/ship.py:164-168` (describe) | Reuses `smoke.run_smoke(env="staging")`, so the retry and time limit match dev. |
| AC-093.9 | met | `ship::test_a_red_staging_smoke_escalates_as_code_and_keeps_the_build_ac_093_9`, `ship::test_the_staging_issue_follows_the_091_convention_ac_093_9`, `ship::test_an_open_issue_with_the_same_signature_gets_a_comment_ac_093_9`, `ship::test_resuming_after_a_red_staging_smoke_runs_the_staging_smoke_only_ac_093_9` | `scripts/cplat/staging_deploy.py:220-245` | Title, labels, signature (staging differs from dev), redaction and dedup are all asserted. Nothing is rolled back. |
| AC-093.10 | met | `ship::test_an_app_without_a_staging_host_is_also_not_run_ac_093_10`, `ship::test_a_service_without_a_staging_url_is_not_run_not_passed_and_not_escalated_ac_093_10` | `scripts/cplat/staging_deploy.py:213-215`, `:236-237` | See the harness-fix judgement below. |
| AC-093.11 | met | `evidence::test_the_summary_names_the_release_the_commits_and_both_smoke_outcomes_ac_093_11`, `evidence::test_open_issues_of_both_labels_are_counted_once_with_their_links_ac_093_11`, `evidence::test_a_dry_run_to_prod_shows_the_summary_before_the_report_ac_093_11`, `evidence::test_json_output_has_the_evidence_per_service_ac_093_11`, `evidence::test_a_release_pr_merge_is_looked_up_by_its_first_parent_ac_093_11` | `scripts/cplat/evidence.py:189-207`, `scripts/cplat/promote.py:143`, `:150-152`, `:177` | |
| AC-093.12 | met | `evidence::test_a_staging_that_runs_another_commit_warns_first_ac_093_12`, `evidence::test_a_red_staging_smoke_warns_ac_093_12`, `evidence::test_a_staging_smoke_that_was_not_run_warns_with_the_reason_ac_093_12`, `evidence::test_a_release_without_a_staging_record_warns_ac_093_12`, `evidence::test_the_pr_body_carries_the_summary_and_the_pr_is_still_opened_ac_093_12` | `scripts/cplat/evidence.py:210-221`, `:57-58` | Warns only and never blocks. |
| AC-093.13 | met | `setting::test_an_automatic_prod_in_app_yaml_is_rejected_ac_093_13`, `setting::test_an_automatic_prod_on_a_service_is_rejected_and_names_it_ac_093_13`, `setting::test_prod_manual_is_accepted_ac_093_13`, `setting::test_no_platform_workflow_pins_prod_ac_093_13` | `templates/gitops-app/scripts/render.py:381-397`, `:665` | |
| AC-093.14 | met | `setting::test_no_document_says_staging_is_never_auto_merged_ac_093_14`, `setting::test_the_documents_describe_automatic_staging_and_how_to_switch_it_off_ac_093_14`, `setting::test_the_promote_command_describes_the_prod_evidence_summary_ac_093_14` | `docs/HOW-IT-WORKS.md:75`, `docs/USER-JOURNEY.md`, `templates/gitops-app/CLAUDE.md.jinja`, `plugins/gitops/commands/promote.md`, `plugins/gitops/agents/deployment.md:101` | A grep of plugins/docs/site found no stale "staging is manual / never auto-merged" wording. |
| AC-093.15 | met | `setting::test_a_generated_gitops_app_has_staging_promotion_on_app_wide_ac_093_15`, `setting::test_app_yaml_is_project_owned_so_an_update_never_switches_it_on_ac_093_15`, `setting::test_effective_setting_is_the_entry_then_the_app_then_off_ac_093_15`, `ship::test_nothing_set_means_off_and_the_report_says_so_ac_093_15`, and the two override tests | `scripts/cplat/staging.py:48-54`, `:167-168`, `app.yaml.jinja` (`promotion: {staging: auto}`), `templates/gitops-app/copier.yml:25` (`_skip_if_exists`) | |
| AC-093.16 | met | `setting::test_the_adr_is_indexed_and_amends_adr_027_ac_093_16`, `setting::test_adr_027_links_to_the_new_adr_ac_093_16` | `docs/adr/041-staging-follows-green-dev-smoke.md`, `docs/adr/README.md:47`, `docs/adr/027-dev-follows-main-through-pin-prs.md:6,28` | |

## Harness fix after red (df5c70c)

- **AC-093.1 "no run store":** the shared fixture sets `CPLAT_RUNS_REPO`, so the test that asserts an empty record link contradicted the next test, which asserts a link. Unsetting the variable in that one test is a fixture correction. It does not weaken the criterion. Acceptable.
- **AC-093.10 unexposed service:** `expose` is not set per environment, so a service that is not exposed has no dev URL either. Its dev smoke is not run, and AC-093.3 then applies: nothing is promoted. The criterion's actual requirements still hold and are asserted: never counted as passed, not escalated, and the run ends. The exact `Smoke (staging): not run: no staging URL for <svc>` line is still asserted in `test_an_app_without_a_staging_host_is_also_not_run_ac_093_10`, which covers the case where dev has a URL and staging does not. Acceptable.

## Non-goals

- No automatic prod promotion: `render.py:390-392` rejects it, and `pin-staging.yml` only runs `pin.py staging`. ✔
- No automatic rollback: a red staging smoke escalates and keeps the build (`staging_deploy.py:241-243`). ✔
- No scheduled or runner-side smoke, no promotion of builds merged outside ship, no first entry into staging, no multi-service unit (only the first linked app is promoted, `staging_deploy.py:119-120`), no time window. ✔

## Deviations from the plan and the design

- **Release-merge evidence rule** (`evidence.py:90-101`): the orchestrator took this design decision over from the architect, and design.md records it. When a merge commit changes only release files, the evidence comes from its first parent, and the summary says so. Acceptable.
- **`staging.py` has its own file-read helpers on the `staging.gh` seam** (`staging.py:74-97`) instead of reusing `smoke._read`/`_app_dirs` (plan t3). This keeps the design rule that `gh` goes through `staging.gh`. Acceptable.
- **The no-workflow skip reason names the app directory** (`staging.py:181`), not the gitops-app slug the design table gives. This is cosmetic and the instruction to run `/shared:update-service` is intact. Acceptable.
- **Files outside every task's `files`:** `docs/ARCHITECTURE.md`, `docs/CHANGELOG.md`, `docs/unattended-delivery.md`, `plugins/svc/commands/ship.md`, `site/src/content/docs/scenarios/promote-safely.md`. These are doc updates that serve AC-093.14 (t8's list is truncated in plan.md). Acceptable.
- **Minor, non-blocking observations:**
  - `resume` builds the PR branch from `service_name(repo)` (`staging_deploy.py:254`), while `promote` builds it from the services.yaml name. This only matters if the two names differ.
  - The red-dev-smoke report places the `Promotion (staging)` row after the escalation line, not at the end (`ship.py:766-772`).
  - A window that runs out during the Argo wait reports `<svc>-staging is <health>`, not the "within 15 minutes" message.
- All 9 tasks are `done: true`.

## Contract

The implementation matches `design.md`:
- `Decision` and its check order;
- the dispatch payload;
- the workflow branch, title, body, supersede and red-CI comment;
- the escalation strings;
- the `st["staging"]` state;
- the run-record `smoke.staging` and `promotion` sections;
- the `Evidence` lines and warning order;
- the `render.py` messages.

The only exception is the cosmetic no-workflow reason noted above. ✔
