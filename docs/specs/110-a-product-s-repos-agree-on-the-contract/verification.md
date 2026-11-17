# Verification — 110 A product's repos agree on the contract between them

**Result:** pass
**Commit:** 2c26d0a · **Base:** c6f4a95 · **Trace:** 11/11 criteria named by tests (`cplat spec trace --json`, nothing missing); `devbox run ci` green

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-110.1 | met | `tests/cplat/test_110_plan_check.py::test_a_missing_rules_part_is_refused_ac_110_1`, `::test_an_invalid_rule_is_refused_naming_it_ac_110_1` (16 cases: missing id/keys, no concrete value, unknown kind, foreign provider/consumer, each naming the rule), `::test_every_kind_with_a_concrete_value_passes_ac_110_1`, `::test_no_shared_rules_with_a_reason_passes_and_the_errors_may_stay_prose_ac_110_1`, `::test_rules_without_a_block_or_a_reason_are_refused_ac_110_1`, `::test_a_single_repo_plan_needs_no_rules_ac_110_1` | `templates/gitops-app/scripts/plan.py:207-322` (`parse_rules`), `:387-409` (`check_contract`) | exact design-1 messages asserted |
| AC-110.2 | met | `test_110_plan_check.py::test_an_incomplete_error_contract_is_refused_ac_110_2`, `::test_errors_without_a_yaml_block_are_refused_when_there_are_rules_ac_110_2`, `::test_a_rule_whose_violation_has_no_status_code_is_refused_ac_110_2`, `::test_a_status_on_every_rule_replaces_the_one_of_the_errors_block_ac_110_2` | `plan.py:324` (`parse_errors`), `:374-384` (`contract_findings`, status per rule) | |
| AC-110.3 | met | `test_110_plan_check.py::test_a_finished_plan_without_rules_warns_and_passes_ac_110_3` (completed, abandoned), `::test_an_active_plan_without_rules_still_fails_ac_110_3`, `::test_an_invalid_rule_in_a_finished_plan_is_a_warning_ac_110_3` | `plan.py:519-528` (finished-plan warning gains ``no `### Rules` ``) | |
| AC-110.4 | met | `test_110_copy.py::test_the_repo_gets_a_copy_marked_with_the_plan_and_the_commit_ac_110_4`, `::test_the_spec_lists_the_rules_in_its_system_context_ac_110_4`, `::test_a_repo_in_no_rule_gets_no_copy_and_a_stale_one_is_removed_ac_110_4`, `::test_a_contract_that_fails_plan_check_writes_no_spec_ac_110_4`; `test_110_plan_check.py::test_contract_prints_the_slice_*`; `test_110_prompts.py::test_spec_from_plan_tells_the_agent_about_the_copy_ac_110_4` | `scripts/cplat/contract_copy.py:19-79`, `scripts/cplat/spec.py:1024-1028,1052-1055`, `plan.py:543` (`contract_cmd`), `plugins/component/references/spec-from-plan.md:5` | plan id, gitops-app and 40-hex commit asserted; "Product context" = `## System context` (design decision) |
| AC-110.5 | met | `test_110_provider.py::test_the_cases_are_derived_from_the_provider_rules_of_the_copy_ac_110_5`, `::test_each_rule_is_sent_at_the_limit_past_it_and_with_every_allowed_value_ac_110_5`, `::test_the_values_of_every_kind_follow_the_table_ac_110_5`, `::test_a_limit_the_code_does_not_enforce_fails_naming_rule_field_expected_and_actual_ac_110_5`, `::test_every_rejection_has_the_status_and_error_body_of_the_contract_ac_110_5` | `templates/service-python/scripts/contract_pytest.py:88-130` (cases from copy), `:166-188` (status + body fields), `:191-223` (message) | |
| AC-110.6 | met | `test_110_consumer.py::test_the_cases_are_derived_from_the_consumer_rules_of_the_copy_ac_110_6`, `::test_a_front_end_that_accepts_what_the_contract_rejects_fails_naming_the_rule_ac_110_6`, `::test_a_front_end_that_rejects_what_the_contract_accepts_fails_naming_the_message_ac_110_6`, `::test_decimal_limits_use_the_step_of_the_copy_ac_110_6` | `templates/web-nextjs/lib/contract/engine.ts:125-186,226-245` | engine run by node against a fake form |
| AC-110.7 | met | `test_110_consumer.py::test_the_contract_error_response_must_show_its_message_at_the_field_ac_110_7`, `::test_an_unlisted_response_must_show_the_unlisted_message_ac_110_7`, `::test_the_unlisted_status_is_one_the_copy_does_not_use_ac_110_7` | `engine.ts:188-223` (response and unlisted cases), `:240` | |
| AC-110.8 | met | `test_110_provider.py::test_the_provider_check_is_part_of_the_repos_test_run_ac_110_8`, `::test_the_provider_check_needs_no_other_repo_and_no_network_ac_110_8`; `test_110_consumer.py::test_the_consumer_check_is_part_of_the_repos_vitest_run_ac_110_8`, `::test_the_consumer_check_needs_no_network_and_no_other_repo_ac_110_8` | `templates/service-python/devbox.json:17-18` (`-p scripts.contract_pytest`), `templates/service-python/tests/test_contract.py:13`, `templates/web-nextjs/tests/contract.test.ts` (in vitest `include`) | red PR follows from the existing `test` job running these recipes |
| AC-110.9 | met | `test_110_pins.py::test_a_copy_with_another_value_fails_naming_service_rule_and_both_values_ac_110_9`, `::test_the_consumer_copy_is_checked_too_ac_110_9`, `::test_a_difference_in_the_error_contract_fails_ac_110_9`, `::test_a_repo_with_no_copy_fails_when_the_plan_assigns_it_a_rule_ac_110_9`, `::test_a_repo_in_no_rule_is_not_checked_ac_110_9`, `::test_the_job_is_wired_into_the_gitops_app_ci_ac_110_9` | `templates/gitops-app/scripts/check-contract-pins.py:82-95,115-133,217-283`, `templates/gitops-app/.github/workflows/ci.yml:65-82` | fake GitHub API, real git base/pin commits |
| AC-110.10 | met | `test_110_copy.py::test_running_from_plan_again_updates_the_copy_to_the_new_values_ac_110_10`; `test_110_provider.py::test_a_changed_contract_fails_the_check_until_the_code_follows_ac_110_10`; `test_110_consumer.py::test_a_changed_contract_fails_the_check_until_the_code_follows_ac_110_10` | `contract_copy.py:47-56` (overwrite), `spec.py:1052` | 200 -> 120 end to end through `cplat spec new --from-plan` |
| AC-110.11 | met | `test_110_prompts.py::test_the_format_shows_the_rules_part_next_to_errors_and_timeouts_ac_110_11`, `::test_the_worked_example_has_a_title_maximum_and_status_allowed_values_ac_110_11`, `::test_the_machine_readable_error_contract_is_shown_ac_110_11`, `::test_the_worked_example_passes_plan_check_ac_110_11` (planner and ADR-011) | `plugins/system/agents/planner.md:38,79-115`, `docs/adr/011-multi-repo-plan-format.md:114` | |

## Non-goals

No Pact/broker, no service-java/service-go or library-python contract check, no OpenAPI check, no pattern/format checking (only six kinds accepted, `pattern` refused), no per-run plan fetch in component repos, no change to the todo sample repos, no code generation. No template-owned layout (header, footer, navigation) changed. ✔

## Deviations from the plan

- `templates/gitops-app/devbox.json`: `contract-pins` is chained into the `ci` recipe (6bd159a), while t5's note said "not in `ci`". Acceptable: the script passes with nothing to check when the base ref is missing (`check-contract-pins.py:84-86`). Note for the PR: a local `devbox run ci` on a branch that changes a pin, with `origin/main` fetched and no `SERVICE_REPOS_READ_TOKEN`, fails with the "needs the secret" line, so the CLAUDE.md row's "a local run ... passes with nothing to check" holds only when there is no base ref.
- `contractCases(dir = ".")` reads `<dir>/contract/*.json` (repo root) instead of t4's `dir = "contract"`; design 5 leaves the default open, and the tests ask for the repo root. Acceptable.
- `check-contract-pins.py` prints three lines design 6 does not list (a tag that names no commit, no `repo:` in system.yaml, a copy it cannot read). These are extra failure messages, not changes to the contract. Acceptable.
- Edits to other specs' tests, outside every task's `files` except `test_plan.py` (t1). Each is acceptable and goes in the PR body:
  - `tests/cplat/test_130_empty_gates.py` (spec 130): the expected service-python `test`/`test-fast` recipes gain `-p scripts.contract_pytest`, which AC-110.8 requires.
  - `tests/cplat/test_172_quiet.py` (spec 172): strips `-p scripts.contract_pytest` along with the smoke plugin before it runs the recipe's runner. Same assertion.
  - `tests/cplat/test_179_plan.py` (spec 179): the shared `CONTRACT` fixture's consumer is renamed to a repo that this plan has, so the plan stays valid under spec 110.
  - `tests/cplat/test_plan.py` (specs 053/061, in t1): `CONTRACT` gains a valid `### Rules` and `errors:` block, so the existing tests still test what they tested.
  - `tests/cplat/test_service_crds.py` (spec 098): `secrets.SERVICE_REPOS_READ_TOKEN` count 1 -> 2 and job set + `contract-pins`. AC-098.13 still holds: the token only reads service repos and is redacted (`test_110_pins.py::test_a_pinned_copy_that_matches_the_plan_passes_ac_110_9` asserts it is never printed). AC-098.17 still holds: a PR that changes no pin passes the new job.
- `templates/service-python/CLAUDE.md` wording (6821c05) and `plugins/system/agents/planner.md` wording are within t3/t6 files.
- All tasks `done: true`. Contract otherwise matches `design.md`.

## Contract

Matches `design.md` sections 1-6, apart from the deviations above. ✔

## Tightened acceptance tests

No criterion test was tightened. One helper changed after the freeze, recorded with `cplat spec test-diff --tighten`:

| File | Reason | Asserts the criterion as written |
|---|---|---|
| `tests/cplat/test_110_provider.py` (`engine()`, a276f85) | the fastapi stub has no `__spec__`, so a second `find_spec` raised ValueError; the stub is now skipped when fastapi is already in `sys.modules` | yes: no assertion changed |

## Unresolved test-review findings

None (`c4fffb9`: 7 findings, resolved in `9668191`).

## Mutation check (report only)

Skipped: no mutation check for shape unknown yet.
