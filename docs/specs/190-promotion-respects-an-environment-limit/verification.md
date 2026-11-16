# Verification — 190 Promotion respects an environment limit in the spec

**Result:** pass
**Commit:** a4a905c · **Base:** 8c10675 · **Trace:** 7/7 criteria named by tests

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-190.1 | met | `tests/cplat/test_190_environment_limit.py::test_an_unknown_environment_is_an_error_naming_spec_and_value`, `::test_an_empty_or_malformed_list_is_an_error_naming_the_spec`, `::test_the_field_is_checked_for_every_status`, `::test_a_valid_field_passes_and_no_field_limits_nothing`, `::test_a_spec_without_the_field_shows_no_limit_line` | `scripts/cplat/envlimit.py:40` (`field_errors`), `scripts/cplat/spec.py:288` (before the superseded early return at :308) | rc 1, spec id and bad value asserted; empty, `null` and string give the `non-empty list` error with `(got …)`; no field passes check and shows no limit |
| AC-190.2 | met | `test_190_environment_limit.py::test_a_limited_target_is_refused_and_changes_nothing`, `::test_a_limited_target_with_pr_opens_no_pr`, `::test_prod_is_limited_too_and_all_is_checked`, `::test_only_a_building_or_done_spec_limits`, `::test_one_line_per_limiting_spec_and_one_fix_naming_both`, `::test_the_dry_run_shows_refused_lines_and_a_fix_line_and_exits_1`, `::test_the_dry_run_json_lists_the_limits_and_exits_1`, `::test_a_spec_allowing_the_target_does_not_limit_it`, `::test_a_spec_without_the_field_limits_nothing` | `scripts/cplat/promote.py:293-306`, `scripts/cplat/envlimit.py:59` (`limit_of`, LIMITING), `:96` (`refusal_line`), `:100` (`fix_text`) | exact refusal line asserted per spec, exit 1, repo unchanged, no PR; fix names `--amend 042`/`--amend 051` and `--accept-environment-limit`; dry run `REFUSED: <line>` + `fix:`, exit 1; refusal comes before `require_clean` (:309) |
| AC-190.3 | met | `test_190_environment_limit.py::test_the_override_proceeds_and_records_the_reason`, `::test_the_override_puts_the_line_in_the_pr_body`, `::test_the_override_in_a_dry_run_shows_the_accepted_line_and_exits_0`, `::test_one_flag_covers_every_limiting_spec`, `::test_a_short_reason_is_refused_before_anything_is_read`, `::test_other_sentence_ends_are_accepted`, `::test_a_short_reason_with_a_limit_changes_nothing` | `scripts/cplat/promote.py:281-283` (reason check before the repo is read at :289), `:307`, `:328`, `:410`, `:417-418` (PR body), `scripts/cplat/envlimit.py:106` | exact `environment limit accepted: <spec_id> (<envs>): <reason>` in output and PR body; short-reason refusal proven against a non-existent repo |
| AC-190.4 | met | `tests/cplat/test_190_automatic_staging.py::test_a_limiting_spec_stops_the_staging_pin_and_is_not_red`, `::test_the_staging_decision_names_the_limit`, `::test_an_unreadable_listed_spec_stops_the_pin_failing_closed`, `::test_a_draft_spec_does_not_stop_the_pin`, `::test_the_system_ship_promotes_no_component_to_a_limited_staging`, `::test_the_system_ship_still_promotes_when_the_spec_allows_staging` | `scripts/cplat/staging.py:178-181`, `scripts/cplat/appship_joint.py:505`, `:511-513`, `scripts/cplat/envlimit.py:110` | no dispatch / no staging PR, deploy rc 0, phase done, not escalated. The printed row is the spec-093 row `Promotion (staging): not promoted: environment limit <id> allows <envs>`, not the literal `staging: not promoted: …` of the criterion; design.md (Decisions) records this, and tests assert the reason substring (see Deviations) |
| AC-190.5 | met | `test_190_environment_limit.py::test_show_prints_the_limit_line`, `::test_show_json_carries_the_environments`, `::test_list_json_rows_carry_the_environments`, `::test_approve_prints_the_limit_line`, `::test_approve_json_carries_status_and_environments`, `::test_approve_without_the_field_prints_no_limit_line`; `test_190_prompts_benchmark.py::test_the_approval_summary_shows_the_limit_through_cplat_spec_show[component|system]` | `scripts/cplat/spec.py:1188`, `:1639-1645` (approve), `:1648-1661` (show), `scripts/cplat/envlimit.py:116`; `plugins/component/commands/spec.md:74`, `plugins/system/commands/spec.md:48` | exact line `Environment limit: dev (promotion to staging, prod is refused)` asserted; `--json` `environments` asserted |
| AC-190.6 | met | `test_190_prompts_benchmark.py::test_the_product_manager_names_the_limit_and_writes_the_field`, `::test_the_spec_format_documents_the_field`, `::test_the_task_asks_for_a_change_in_every_environment`, `::test_a_spec_that_limits_an_environment_fails_naming_the_spec_and_the_set`, `::test_a_suggested_answer_that_limits_fails_with_the_bullet`, `::test_an_assumption_that_limits_fails`, `::test_result_hands_the_spec_workflow_to_the_check` (+4 more) | `plugins/svc/agents/product-manager.md:27` (rule 3b), `plugins/svc/skills/spec-format/references/spec.md:14`, `scripts/cplat/runs_bench.py:93`, `:119`, `:451`, `scripts/cplat/benchmark/tasks.json` (`spec-environments`) | prompt checked by structure (docs/rules/README.md); the benchmark case and its result check exist and are tested; no live benchmark run result was supplied to this review |
| AC-190.7 | met | `test_190_prompts_benchmark.py::test_the_docs_state_rule_refusal_dry_run_and_override[promote|guide]`, `::test_the_override_is_a_hard_rule_of_a_person` | `plugins/instance/commands/promote.md:27`, `site/src/content/docs/scenarios/promote-safely.md` (section "When a spec limits the environments"), `docs/unattended-delivery.md` (Deploy gate) | rule, refusal, dry run, override and person-only hard rule are all stated |

## Non-goals

- Prose limits: only `environments:` is read (`envlimit.allowed`, `envlimit.py:50`). ✔
- No per-environment resource, exposure or secret limits and no post-deploy check. ✔
- No automatic removal of a limit. Widening is `/system:spec --amend` (`fix_text`). ✔
- Digest rule, prod evidence and production confirmation unchanged. The promote.md digest paragraph was only shortened in wording, and the code paths at `promote.py:278-280` are untouched. ✔
- No template-owned layout changes. ✔

## Deviations from the plan

- `plugins/component/commands/spec.md` changed but `plugins/component/.claude-plugin/plugin.json` and its `marketplace.json` entry were **not bumped**. t4 lists both files, and CLAUDE.md says to "bump versions in both places". **Not acceptable**: bump component (minor) before the PR (`cplat platform pr-check` checks plugin versions).
- t4 listed `docs/rules/plugins/{svc/skills/spec-format/references/spec,component/commands/spec,system/commands/spec}.yml`. They are unchanged. This is acceptable if `cplat platform rules check` passes, because the new sentences there are a field comment and summary instructions. Confirm in CI.
- AC-190.4 output prefix: the criterion's literal text `staging: not promoted: environment limit …` is printed as the existing spec-093 row `Promotion (staging): not promoted: environment limit …` (system ship: `Promotion (staging) <repo>: not promoted: …`). design.md records this so that all skip reasons read alike. Acceptable as a contract decision, though it differs from the spec's wording. An amendment to the spec text would align them.
- `site/src/content/docs/scenarios/promote-safely.md` sample `fix:` line does not match the real `fix_text` output. The sample omits `/system:spec --amend 042` and `--accept-environment-limit "<reason>"`. Acceptable (illustrative), but should be aligned.
- `scripts/cplat/runs_bench.py` fix a4a905c (`model.ENVIRONMENTS` instead of a hard-coded list) is inside t5's files. Acceptable.
- Every task is `done: true`. Contract matches design.md otherwise (lines, flag, JSON keys, `show`/`approve --json`).

## Contract

Matches `design.md` (envlimit public interface and exact lines, `--accept-environment-limit` message and hint, `data.environment_limits`, `spec show`/`approve --json`, benchmark `environments_kept`). ✔

## Test notes

- `test_190_automatic_staging.py::test_a_spec_allowing_staging_does_not_stop_the_pin` asserts `"environment limit" not in lines_of(capsys)`. That is a list-membership test, so it is always true. The `len(dispatches) == 1` assertion carries the test.

## Mutation check (report only)

Skipped: no mutation check for shape platform yet.
