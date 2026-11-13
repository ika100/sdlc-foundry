# Verification — 188 Explore a feature before its spec is written

**Result:** pass
**Commit:** 989541af · **Base:** 8cbe0b87 (`01b455fb^`) · **Trace:** 12/12 criteria named by tests (`devbox run test-fast`: 10139 passed, 12 skipped, 1 failed: `test_smoke_091_run.py::test_a_run_that_does_not_finish_is_stopped_and_red_ac_091_8`, a timing test outside spec 188 that passes alone; `cplat spec check 188`: OK)

Range judged: the squash merge #687 (01b455fb) plus the follow-ups 32a81c2c, 0aafe8eb, 989541af (the `explore-stop` eval that answers the earlier AC-188.1 finding). 90a57617 is the earlier verification, replaced by this file.

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-188.1 | met | `tests/cplat/test_188_prompts.py::test_the_explore_commands_allow_read_tools_and_read_only_git_only_ac_188_1`; `tests/cplat/test_188_explore_stop.py` (6 tests: the task asks for a write and a commit and then stop; an unchanged clone passes; a dirty tree, a new commit or a new PR fails and is named; a failing `git status` fails; the component plugin is loaded; refused without `--plugins`) | `plugins/component/commands/explore.md:3,6`, `plugins/system/commands/explore.md:3,6`; `scripts/cplat/runs_bench.py:80-104` (`_head`, `snapshot` stores HEAD, `unchanged`), `:446` (snapshot before the session), `:450-453`; `scripts/cplat/benchmark/tasks.json` `explore-stop` | First half: the `allowed-tools` set is exactly the list, and it has no Write, Edit or NotebookEdit. Second half: the eval passes only when `git status --porcelain` is empty and HEAD and the newest PR are unchanged, which is the stated outcome. The tests fake the session, because a model run cannot run in the suite. The real-run result goes to the runs store, not the repo. The message of 989541af says the first real run was invalid because the plugin was missing. Recommendation: record one passing real `explore-stop` run before release. |
| AC-188.2 | met | `tests/cplat/test_188_explore_context.py` (10 tests: keys and exact values; matching on criteria text and tracks, withdrawn excluded; empty lists; whole words, rank, cap 10; `#<n>`; empty topic gives exit 2, empty stdout and the exact usage line; gh failure gives a warning and exit 0; text mode; gitops-app `components`/`resources`/`apis`; several systems need `--system`) | `scripts/cplat/explore.py:42-51` (words, rank), `:67-87` (specs, adrs), `:89` (issues), `:109-119` (system part), `:122-139` (context), `:163-168` (usage, exit 2); `scripts/cplat/cplat.py:52,96` | |
| AC-188.3 | met | `test_188_prompts.py::test_the_running_list_and_the_three_ways_out_ac_188_3`, `::test_the_decline_rule_names_the_command_that_does_it_ac_188_3`, `::test_the_explore_commands_send_the_other_shape_away_ac_188_3` | `plugins/component/commands/explore.md:20-32`, `plugins/system/commands/explore.md:20-32` | Prompt behaviour is checked through structure tests, the platform norm (spec 180). In `/system:explore:32`, "implement" falls under the general decline rule plus `/system:spec`. |
| AC-188.4 | met | `test_188_prompts.py::test_spec_it_hands_over_labelled_decisions_in_a_decided_block_ac_188_4`, `::test_the_spec_commands_read_a_decided_block_and_create_an_explored_spec_ac_188_4` | `plugins/component/commands/explore.md:36`, `plugins/system/commands/explore.md:36`, `plugins/component/commands/spec.md:34,36`, `plugins/system/commands/spec.md:33-34` | |
| AC-188.5 | met | `test_188_prompts.py::test_the_product_manager_maps_each_decision_kind_ac_188_5`, `::test_the_spec_format_and_the_architect_know_notes_and_departures_ac_188_5`; `test_188_spec_cli.py::test_a_notes_for_the_architect_section_passes_check_ac_188_5`, `::test_notes_bullets_are_no_criteria_and_outside_the_hash_ac_188_5` | `plugins/svc/agents/product-manager.md:26`, `plugins/svc/agents/architect.md` (Notes / "Departs from note"), `plugins/svc/skills/spec-format/references/spec.md`, `references/design.md` | `active_acs()` and `ac_hash()` are the same with and without a Notes section. |
| AC-188.6 | met | `test_188_prompts.py::test_a_contradicting_decision_becomes_an_open_question_ac_188_6` | `plugins/svc/agents/product-manager.md:26`, `plugins/component/commands/spec.md:36`, `plugins/system/commands/spec.md:34`, `scripts/cplat/explore.py:77-87` (ADR status) | |
| AC-188.7 | met | `test_188_spec_cli.py::test_new_explored_sets_the_front_matter_key_ac_188_7`, `::test_explored_is_not_allowed_with_from_plan_ac_188_7`, `::test_list_json_reports_explored_for_every_spec_ac_188_7`, `::test_check_rejects_an_explored_that_is_not_a_boolean_ac_188_7` | `scripts/cplat/spec.py:285-286,893-894,1165,1254,1493,1551-1552,1566` | |
| AC-188.8 | met | `tests/cplat/test_188_retro.py` (9 tests: counts and means; null group; no release; kill rule by count, by mean, before the due date; exact render lines including the kill text; placement after "Rules to retire"; end to end through `cplat platform retro`) | `scripts/cplat/retro_explore.py:19-95`, `scripts/cplat/retro.py:91-93`, `scripts/cplat/retro_report.py:416-417,507-509` | It only reports. The fragment `662-explore-before-the-spec.added.md` names `/component:explore`, which is how the retro finds the release date. |
| AC-188.9 | met | `test_188_prompts.py::test_too_ambiguous_a_request_recommends_explore_ac_188_9`; `test_188_spec_cli.py::test_discard_removes_a_never_committed_draft_ac_188_9`, `::test_discard_releases_the_claims_on_the_tracked_issues_ac_188_9`, `::test_discard_refuses_a_committed_or_a_non_draft_spec_ac_188_9` | `plugins/svc/agents/product-manager.md:25`, `plugins/component/commands/spec.md:56`, `plugins/system/commands/spec.md:44`, `scripts/cplat/spec_discard.py:16-30` | |
| AC-188.10 | met | `test_188_prompts.py::test_triage_offers_needs_exploring_next_to_spec_fix_and_reply_ac_188_10` | `plugins/issue/commands/triage.md:33,52` | No `apply` and no label change, so the issue keeps `triage`. |
| AC-188.11 | met | `test_188_prompts.py::test_no_unattended_prompt_or_run_allowlist_names_explore_ac_188_11`, `::test_the_unattended_agents_never_name_explore_ac_188_11`, `::test_the_explore_commands_say_only_a_person_starts_them_ac_188_11` | `plugins/component/commands/explore.md:12`, `plugins/system/commands/explore.md:12` | The new `explore-stop` benchmark starts `/component:explore` headless. It is a person-started eval of the read-only promise, not an unattended delivery run (ship, build, dispatcher, journey), so it does not conflict. |
| AC-188.12 | met | `test_188_prompts.py::test_rules_check_passes_with_the_explore_prompts_ac_188_12`, `::test_the_explore_prompts_have_register_files_ac_188_12` | `docs/rules/plugins/{component,system}/commands/explore.yml`, `docs/rules/register.yml:5-12` (baseline raise with a `history` entry and its reason) | |

## Non-goals

- Explore writes and commits nothing: no write tool is granted, and there is no decisions file and no resume from disk. The `explore-stop` eval now checks this on a real session. ✔
- No library or build-approach choice: hints are non-binding, and the architect names each departure. ✔
- No start from unattended delivery runs (AC-188.11). ✔
- The retro only reports the kill rule (`retro_explore.py`). ✔
- `cplat spec discard` deletes only a never-committed draft (`spec_discard.py:16-30`), and only from the person-run spec command. ✔
- No template-owned layout (header, footer, navigation) changed. ✔

## Deviations from the plan

- `scripts/cplat/runs_bench.py`, `scripts/cplat/runs.py`, `scripts/cplat/benchmark/tasks.json`, `tests/cplat/test_188_explore_stop.py` and `docs/changelog.d/662-explore-stop-eval.added.md` are in no task's `files`. Acceptable: they add the "stop session" eval that design.md (Decisions, first bullet) names as the behavioural proof of AC-188.1.
- t11 has no `done:` flag, although its work is in the merge (baseline raised with a history entry). Acceptable as bookkeeping; set `done: true`.
- The ADR is 107, not 104. Acceptable: t10 allows the number `cplat adr add` hands out.
- Planned rules files `docs/rules/plugins/{component,system}/commands/spec.yml` and `references/spec.yml` were not touched. Acceptable: `cplat platform rules check` passes over all prompts.
- Plugin versions: only `issue` was bumped (1.2.0 → 1.3.0). component 1.19.0, system and svc were already at t9's targets on the base, in the same unreleased cycle. Acceptable.
- `tests/cplat/test_183_prompts.py`: the size helper of another spec's frozen test now allows bytes up to the gated, raised baseline. Acceptable, because a raise is only possible through `rules rebaseline`, which `pr-check` checks.
- `test_plugins_114.py` (command count 41 → 43) and `test_149_decide_by_default.py` (an `# interface:` mark) follow from the new commands. Acceptable.
- `cplat spec new --tracks` parsing changed (`type=int` dropped; words after the digits join the title). This is not in design.md. Acceptable within t2's file. Side effect: a non-numeric `--tracks` value silently becomes title text.
- `retro_explore.section` carries an extra `until` key. Additive; acceptable.

## Contract

Matches `design.md` for `cplat explore context`, the `cplat spec` additions, the `DECIDED:` block, the explore conversation, the triage route and the retro section. Exceptions: the extra `until` key and the `--tracks` parsing above.

## Suppressions in acceptance tests

none

## Tightened acceptance tests

none

## Unresolved test-review findings

none
