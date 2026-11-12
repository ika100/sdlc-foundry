# Verification — 188 Explore a feature before its spec is written

**Result:** fail
**Commit:** 01b455fb · **Base:** 8d4b1607 · **Trace:** 12/12 criteria named by tests (`devbox run test-fast`: 10132 passed, 12 skipped, 0 failed; `cplat spec check 188`: OK)

Only the spec-188 commit (#687) was judged; #696 and #650 in the same range were left out.

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-188.1 | not met | `tests/cplat/test_188_prompts.py::test_the_explore_commands_allow_read_tools_and_read_only_git_only_ac_188_1`, `::test_the_explore_commands_say_they_write_nothing_ac_188_1` | `plugins/component/commands/explore.md:3,6`, `plugins/system/commands/explore.md:3,6` | TEST LOOSER. The first half is proved: the `allowed-tools` set is exactly the list and has no Write, Edit or NotebookEdit. The second half ("a whole session that ends in stop leaves the working tree and the branch's commits as they were") has no test. The test file's docstring says it cannot run here, and the second test only checks that the words write, edit, commit and nothing appear in the prompt. design.md (Decisions, first bullet) names "the eval of a stop session" as the behavioural proof, because `allowed-tools` pre-approves tools and does not remove the others. No such eval was added (no explore scenario under `scripts/cplat/benchmark/`). The code looks right. |
| AC-188.2 | met | `tests/cplat/test_188_explore_context.py` (all 10 tests: keys, criteria/tracks matching, withdrawn excluded, empty lists, whole words + rank + cap 10, `#<n>`, empty topic exit 2 + exact usage line, gh failure, text mode, gitops-app keys, several systems) | `scripts/cplat/explore.py:122-139` (context), `:163-171` (usage/exit 2), `:109-119` (system part), `scripts/cplat/cplat.py` `PLUMBING["explore"]` | |
| AC-188.3 | met | `test_188_prompts.py::test_the_running_list_and_the_three_ways_out_ac_188_3`, `::test_the_decline_rule_names_the_command_that_does_it_ac_188_3`, `::test_the_explore_commands_send_the_other_shape_away_ac_188_3` | `plugins/component/commands/explore.md:20-32`, `plugins/system/commands/explore.md:20-32` | Remark: `/system:explore:32` maps "writing the spec" and "plan, design, library" to commands. The case "implement" is covered only by the general rule "decline work that is not exploring, name the command". Behaviour is a prompt, and the structure tests are the platform's norm (spec 180). |
| AC-188.4 | met | `test_188_prompts.py::test_spec_it_hands_over_labelled_decisions_in_a_decided_block_ac_188_4`, `::test_the_spec_commands_read_a_decided_block_and_create_an_explored_spec_ac_188_4` | `plugins/component/commands/explore.md:36`, `plugins/system/commands/explore.md:36`, `plugins/component/commands/spec.md:34,36`, `plugins/system/commands/spec.md:33-34` | |
| AC-188.5 | met | `test_188_prompts.py::test_the_product_manager_maps_each_decision_kind_ac_188_5`, `::test_the_spec_format_and_the_architect_know_notes_and_departures_ac_188_5`; `test_188_spec_cli.py::test_a_notes_for_the_architect_section_passes_check_ac_188_5`, `::test_notes_bullets_are_no_criteria_and_outside_the_hash_ac_188_5` | `plugins/svc/agents/product-manager.md:26`, `plugins/svc/agents/architect.md:22`, `plugins/svc/skills/spec-format/references/spec.md` (Notes section + rule), `references/design.md:34` | `spec check` and `ac_hash` read only `## Acceptance criteria`. The test shows that an AC-shaped bullet in Notes is not counted. |
| AC-188.6 | met | `test_188_prompts.py::test_a_contradicting_decision_becomes_an_open_question_ac_188_6` | `plugins/svc/agents/product-manager.md:26`, `plugins/component/commands/spec.md:36`, `plugins/system/commands/spec.md:34`, `scripts/cplat/explore.py:85` (ADR status) | |
| AC-188.7 | met | `test_188_spec_cli.py::test_new_explored_sets_the_front_matter_key_ac_188_7`, `::test_explored_is_not_allowed_with_from_plan_ac_188_7`, `::test_list_json_reports_explored_for_every_spec_ac_188_7`, `::test_check_rejects_an_explored_that_is_not_a_boolean_ac_188_7` | `scripts/cplat/spec.py:894`, `:1165`, `broken_summary`, `:286`, `:1552`; spec commands pass `--explored` (`plugins/component/commands/spec.md:34`) | |
| AC-188.8 | met | `tests/cplat/test_188_retro.py` (9 tests: means and counts, null group, no release, kill rule by count, by mean, before due date, render lines incl. exact kill text, report placement, end to end through `cplat platform retro`) | `scripts/cplat/retro_explore.py:19-95`, `scripts/cplat/retro.py:89-91`, `scripts/cplat/retro_report.py:416-417,507-509` | Read-only: the section holds counts only. The changelog fragment contains `/component:explore`, which dates the release. |
| AC-188.9 | met | `test_188_prompts.py::test_too_ambiguous_a_request_recommends_explore_ac_188_9`; `test_188_spec_cli.py::test_discard_*_ac_188_9` (3) | `plugins/svc/agents/product-manager.md:25`, `plugins/component/commands/spec.md:56`, `plugins/system/commands/spec.md:44`, `scripts/cplat/spec_discard.py:16-30`, `scripts/cplat/spec.py:1599` | |
| AC-188.10 | met | `test_188_prompts.py::test_triage_offers_needs_exploring_next_to_spec_fix_and_reply_ac_188_10` | `plugins/issue/commands/triage.md:33,52` | No `apply` and no label change, so the issue keeps `triage`. |
| AC-188.11 | met | `test_188_prompts.py::test_no_unattended_prompt_or_run_allowlist_names_explore_ac_188_11`, `::test_the_unattended_agents_never_name_explore_ac_188_11`, `::test_the_explore_commands_say_only_a_person_starts_them_ac_188_11` | `plugins/component/commands/explore.md:12`, `plugins/system/commands/explore.md:12` | A repo-wide `git grep` confirms it. Explore names appear only in the explore commands, the spec commands, triage, READMEs, AGENTS.md, the ADR, the rules files, `cplat.py`/`explore.py`/`retro_explore.py` and the tests. No ship, build, dispatcher, journey or headless file names them, and no unattended flow runs the spec commands. |
| AC-188.12 | met | `test_188_prompts.py::test_rules_check_passes_with_the_explore_prompts_ac_188_12`, `::test_the_explore_prompts_have_register_files_ac_188_12` | `docs/rules/plugins/{component,system}/commands/explore.yml`, `docs/rules/register.yml` baseline 345859 → 355920 with `history` entry (reason + two benchmark runs) | The history entry is the trace that `rules rebaseline` writes, and `pr-check` checks it. |

## Non-goals

- Explore writes and commits nothing. Its tool list grants no write tool, and there is no decisions file and no resume from disk. ✔
- No library or build-approach choice: hints are non-binding, and the architect names each departure. ✔
- No unattended start (AC-188.11 evidence). ✔
- The retro only reports the kill rule and changes nothing (`retro_explore.py`). ✔
- `cplat spec discard` deletes files, but only in the person-run spec command, and only a never-committed draft (`spec_discard.py:18-24`). Not an explore write. ✔
- No template-owned layout (header, footer, navigation) changed. ✔

## Deviations from the plan

- **t11 has no `done:` flag**, although its work is in the commit (the baseline was raised with a history entry). Acceptable as bookkeeping; set `done: true`.
- **ADR is 107**, not the 104 in t10's `files`. Acceptable: the plan allows the number `cplat adr add` hands out.
- **Rules files planned but untouched:** `docs/rules/plugins/{component,system}/commands/spec.yml` (t5) and `references/spec.yml` (t6) were not changed. Acceptable because `cplat platform rules check` passes over all prompts (AC-188.12 test).
- **Plugin versions:** only `issue` was bumped (1.2.0 → 1.3.0). component 1.19.0, system 1.18.0 and svc 4.11.0 were already at t9's targets on the base, in the same unreleased cycle. Acceptable.
- **`tests/cplat/test_183_prompts.py`:** the size helper of another spec's acceptance test was loosened. It now allows prompt bytes up to the register's raised baseline. Acceptable: a raise is only possible through the gated `rules rebaseline` that `pr-check` checks. Named here because it relaxes a frozen test.
- **`tests/cplat/test_plugins_114.py`** (command count 41 → 43, `explore` added) and **`test_149_decide_by_default.py`** (only an `# interface:` mark) were changed. Acceptable, both follow from the new commands and the rules check.
- **`cplat spec new --tracks` parsing changed** (`scripts/cplat/spec.py` near `:1557`). `type=int` was dropped; leading digits are now issue numbers, and the words after them join the title. This is not in design.md. Acceptable as a usability fix within t2's file. Side effect: a non-numeric `--tracks` value now silently becomes title text.
- **The `retro_explore.section` dict carries an extra `until` key** that the contract does not define. Additive and acceptable.

## Contract

Matches `design.md` for `cplat explore context` (keys, matching, usage line, exit codes, gh warning, gitops-app keys, `--system` error), the `cplat spec` additions, the `DECIDED:` block, the triage route and the retro section. Two exceptions: the extra `until` key and the `--tracks` parsing noted above.

## Suppressions in acceptance tests

none

## Tightened acceptance tests

none

## Unresolved test-review findings

none
