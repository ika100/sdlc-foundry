# Verification — 168 Agent rules state their reason and can retire

**Result:** pass
**Commit:** 86116baf · **Base:** 55b0eb69 · **Trace:** 8/8 criteria named by tests · **Cycle:** 3

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-168.1 | met | `tests/cplat/test_168_rules_check.py::test_a_rule_sentence_without_an_entry_fails_with_file_line_and_text_ac_168_1`, `::test_an_entry_whose_text_no_longer_occurs_is_stale_ac_168_1`, `::test_every_rule_word_makes_a_rule_sentence_ac_168_1`, `::test_two_entries_for_one_sentence_are_ambiguous_ac_168_1`, `::test_a_schema_violation_is_a_bad_entry_ac_168_1` | `scripts/cplat/rulescheck.py:157` (no-entry), `:160` (ambiguous), `:187` (stale), `scripts/cplat/promptrules.py:27` (rule words), `:205` (sentences) | Every rule word of the criterion is tested, as are file/line/text on both failure kinds and the gone-prompt case. |
| AC-168.2 | met | `test_168_rules_check.py::test_a_rule_without_a_reason_fails_with_file_and_line_ac_168_2`, `::test_each_reason_word_introduces_a_reason_ac_168_2`, `::test_a_reason_of_fewer_than_three_words_besides_references_is_short_ac_168_2`, `::test_three_words_besides_references_are_a_reason_ac_168_2` | `rulescheck.py:165-171`, `promptrules.py:46` (refs removed), `:225-243` | Covers the three classes, all four reason words, and refs `#n`/`spec n`/`ADR-n`/link targets. |
| AC-168.3 | met | `test_168_rules_check.py::test_a_practice_with_a_condition_clause_must_state_its_purpose_ac_168_3`, `::test_a_hard_rule_may_keep_a_condition_clause_ac_168_3` | `rulescheck.py:172-174` (checks the whole sentence `s.text`, not just the entry text), `promptrules.py:29,38` | The check is right: it refuses a condition clause in a practice and lets a hard rule keep one. **Cycle 2:** the seven brief-practice prompts were fixed (cd9036e8): `plugins/{svc-go,svc-java,web}/agents/{coder,tester}.md:12`, `plugins/shared/agents/quality.md:12`. The spec 100 pin moved to the frontmatter `description`. **Cycle 3:** `plugins/component/commands/set.md:19` now reads "When the user said not to merge, leave the PR open, so that the user keeps the last word on merging." (86116baf). It has no rule word and no condition clause, and it states its purpose. Its `not a rule` entry `set.yml` R7 is removed. `tests/cplat/test_142_expose_merge.py:11` pins the new wording and still asserts the AC-142.1 behaviour. **Re-scan:** all 28 remaining `not a rule` entries in `docs/rules/plugins/**` were read, together with the prompt line of each. Only two hold a condition word, and both describe something rather than instruct the agent: `web/agents/observability.md:14` describes a file in a table, and `system/agents/planner.md:30` describes what `plan-check` does. This list is complete. Every condition word (only, unless, except) is also a rule word (`promptrules.py:27`), so each sentence that holds one needs an entry, and `rules check` reports OK. That leaves only `hard` (allowed) and `not a rule` as ways past the condition check. |
| AC-168.4 | met | `test_168_rules_check.py::test_a_cplat_command_or_ci_job_is_an_enforcement_ac_168_4`, `::test_an_enforcement_that_names_no_command_or_job_is_bad_ac_168_4`, `::test_an_intentional_prose_rule_needs_three_words_ac_168_4`, `::test_at_most_twenty_distinct_hard_rules_ac_168_4`, `::test_a_hard_rule_repeated_in_several_prompts_counts_once_ac_168_4`; `test_168_rules_retired_register.py::test_the_register_holds_the_designed_hard_rules_ac_168_4` | `rulescheck.py:101-119`, `:229-231`, `promptrules.py:437-474` (cplat NOUNS/PLUMBING, workflow jobs incl. `.jinja`) | `docs/rules/register.yml` has the 13 designed keys, each with exactly one of `enforced_by` or `intentional_prose_rule`. |
| AC-168.5 | met | `test_168_rules_check.py::test_a_hard_rule_without_the_marker_fails_ac_168_5`, `::test_a_marker_on_a_rule_that_is_not_hard_fails_ac_168_5`, `::test_an_agent_or_command_without_the_statement_fails_ac_168_5`, `::test_a_changed_statement_is_no_statement_ac_168_5`, `::test_the_statement_may_wrap_lines_but_stands_once_ac_168_5` | `rulescheck.py:148-154` (marker), `:198-204` (statement), `promptrules.py:25` (STATEMENT) | Tombstones (`moved-to:`) are exempt from the statement, as design.md decides: they answer in one line and hold no rule. Acceptable. |
| AC-168.6 | met | `test_168_rules_retired_register.py::test_the_platform_repo_passes_the_rules_check_ac_168_6`, `::test_the_command_passes_on_the_platform_repo_ac_168_6`, `::test_the_prompts_are_not_larger_than_before_the_sweep_ac_168_6`, `::test_every_retired_entry_of_the_register_names_date_and_reason_ac_168_6`, `::test_the_platforms_ci_and_local_ci_run_the_rules_check_ac_168_6`, `::test_a_retired_entry_needs_date_reason_and_a_valid_enforcement_ac_168_6` | `rulescheck.py:175-186` (retired), `:232-234` (bytes), `.github/workflows/ci.yml:113-114`, `scripts/ci-local.sh:34-35` | Independently checked with `git ls-tree -l`: 345859 bytes at base 55b0eb69 (= `baseline.commit`) and 345670 at 86116baf (cycle 3; the same −189 delta that `git ls-tree -l` shows over `plugins/**/*.md`). 64 retired entries. Spot checks of svc coder/tester, shared security and component release found every removed rule sentence recorded as `retired`. |
| AC-168.7 | met | `test_168_rules_retire_gate.py::test_a_retirement_without_a_benchmark_fails_with_the_gate_failures_and_commands_ac_168_7`, `::test_a_removed_entry_or_a_deleted_register_file_needs_the_gate_ac_168_7`, `::test_a_passing_gate_still_needs_the_run_ids_on_the_retired_entry_ac_168_7`, `::test_fix_writes_the_run_ids_of_the_passing_gate_ac_168_7`, `::test_pr_check_runs_the_rule_and_prints_its_problems_ac_168_7` | `scripts/cplat/rules_retire.py:71-74` (changed set), `:107-148`, `scripts/cplat/evalgate.py:61-90` (`verdict_runs`), `scripts/cplat/house_rules.py:115-119` | The mechanism is complete. This PR's own 64 retired entries have no `benchmark_runs` yet: the plan's human step. `pr-check` fails on this branch until that step runs. |
| AC-168.8 | met | `test_168_retro_rules.py::test_an_enforced_rule_is_proposed_with_the_failures_of_its_check_in_the_covered_week_ac_168_8`, `::test_a_quiet_experience_rule_of_a_closed_issue_is_proposed_with_the_run_count_ac_168_8`, `::test_an_occurrence_of_the_cause_keeps_the_rule_ac_168_8`, `::test_at_most_three_entries_ranked_by_bytes_saved_ac_168_8`, `::test_no_candidate_and_no_register_say_none_this_week_ac_168_8`, `::test_the_report_stores_and_both_renderings_print_the_section_after_the_proposals_ac_168_8`, `::test_the_retro_adds_the_section_and_changes_no_prompt_or_register_file_ac_168_8` | `scripts/cplat/retro_rules.py:115-147`, `:150-165`, `scripts/cplat/retro.py:69-89`, `scripts/cplat/retro_report.py:502-504`, `scripts/cplat/retro_github.py:77-90` | The public rendering passes through `retro_report.leaks` (`retro.py:217`), as AC-090.11 requires. The section holds only platform paths, prompt text and counts. |

## Non-goals

- Templates and generated-repo instructions are untouched: no file under `templates/` changed. ✔
- No new enforcement was built for a prose hard rule. All 8 are `intentional_prose_rule`. ✔
- The retro does not retire anything automatically. The section is computed, and no prompt or register file is written (tested). ✔
- Nothing runs the benchmark in CI. The CI step runs only `rules check`. ✔
- "Procedure steps that are not rules are not rewritten": partly broken. To stay under the byte baseline, the sweep also trimmed text with no rule sentence in it. Examples: the component release Final Summary table became lines, and "0 not found" was dropped from the Phase 7 line. The svc tester lost its command table, including `devbox run bandit`. The svc coder lost two commit examples, and its dev-dependency row was merged. **Acceptable**: A8 forces trimming somewhere, no test or parser reads these texts (`git grep "Release Pipeline Complete"` finds no consumer), and the facts are still in `devbox.json` or the shell rule. Worth a glance from the maintainer.
- No template-owned layout is involved (no web UI in this change). ✔

## Deviations from the plan

- **Cycle 2, fixed:** the seven `not a rule` classifications of the brief practice (cd9036e8, see AC-168.3). Moving the pinned "only when the brief lacks" to the frontmatter `description` is **acceptable**. It matches the svc agents. The frontmatter is outside the scan by design, and the orchestrator reads the description, not the agent.
- **Cycle 3, fixed:** `plugins/component/commands/set.md:19` / `set.yml` R7 (86116baf, see AC-168.3). The spec 142 pin in `test_142_expose_merge.py` follows the new wording, and its assertion of the behaviour is unchanged in strength. **Acceptable.**
- `scripts/tombstones.py` and the 27 tombstone command files are in no task. "With Read and Glob only" was a rule sentence and became "With just Read and Glob", so tombstones need no register file. The app and gitops plugin versions were bumped for the same reason. **Acceptable.**
- `tests/cplat/test_ci_gates.py` is in no task. The spec 080 pin on build Phase 3's "only when …" conditions now pins the purposes ("so that every new internal has a unit test", "so that a changed Dockerfile is built and scanned"). AC-168.3 asks for exactly that rewrite, and the test still pins Phase 3's behaviour. **Acceptable.**
- `tests/cplat/test_retro_cli.py` is in no task. The allowed tracker calls now include `issue_states`, which is a read. AC-090.9 (no agent file, no PR) still holds. **Acceptable.**
- The three acceptance-test fixtures were corrected after the red commit (`git diff 624e54bb..HEAD -- tests/cplat/test_168_* rules_support.py`):
  - an `id` written bare, so that `line_of(…, "id: R1")` matches;
  - "today" added to the ENFORCED fixture, so that its byte order holds;
  - the AC-168.3 "only without when/if" test given an entry its sentence contains.

  No assertion was removed or loosened. **Acceptable.**
- `docs/changelog.d/168-agent-rules-reasons.added.md`: **cycle 2, fixed.** It now says that the 13 rules never departed from are marked `**Hard rule:**`, each naming the `cplat` command or CI job that enforces it or why no tool can. This matches `docs/rules/register.yml`. **Acceptable.**
- `retro.py:69-75` now reads 28 days of records. The figures still use `_split` (current and previous week), but `records.malformed` now counts malformed lines over 28 days instead of 14. **Acceptable**, minor.
- `retro_rules.py:109,143`: `bytes` is the size of the first sentence an entry matches, while the design says "the matched sentences". It differs only when one entry text occurs in several sentences of a prompt. **Acceptable.**
- Human step not run yet: the two benchmarks and `pr-check --fix`, which writes `benchmark_runs` into the 64 retired entries. **Required before merge** (plan `human_steps`).
- Every task has `done: true`. Files outside every task, apart from those above, are design-phase files (ADR-091, `docs/adr/README.md`, design/plan/spec) and the red-commit acceptance tests: expected.

## Contract

`design.md` and the code match:
- the register schema and keys;
- every failure kind of the check table, with the text and JSON output shapes, `--only` and exit codes;
- `evalgate.verdict_runs`, the `rules` and `rules-retired` pr-check rules, the OK line and the `--fix` insertion;
- the retro section JSON and its rendering;
- `RetroTracker.issue_states`.

No exceptions remain (cycle 3: the last misclassified entry, `set.yml` R7, is gone). ✔

## Mutation check (report only)

Skipped: no mutation check for shape platform yet.
