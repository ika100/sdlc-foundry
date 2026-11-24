# Verification — 222 The UX step is measured on website plans

**Result:** pass
**Base:** origin/main at b91e30ac+ · **Trace:** 11/11 criteria named by tests (`tests/cplat/test_222_ux_measured.py`, `tests/cplat/fixtures/ux_cases.json`)

| Criterion | Result | Evidence |
|---|---|---|
| AC-222.1 | met | `test_the_ux_plan_workflow_plans_spec_902_on_the_web_component_ac_222_1`, `test_a_sample_component_that_is_not_in_system_ship_is_refused_ac_222_1`; `runs_bench.sample_of`, `benchmark/tasks.json`, `benchmark/spec-902.md` |
| AC-222.2 | met | `test_the_clone_is_the_system_ship_one_from_dir_env_or_state_dir_ac_222_2`, `test_a_missing_clone_is_refused_with_its_folder_ac_222_2`, `test_an_untrusted_clone_is_refused_ac_222_2`; `runs_bench.clone_of` |
| AC-222.3 | met | the five `…_ac_222_3` tests; `runs_bench.ux_planned` |
| AC-222.4 | met | `test_a_ux_plan_run_writes_a_benchmark_record_and_resets_the_sample_ac_222_4`; the real run below |
| AC-222.5 | met | `test_the_build_benchmark_spec_gets_no_ux_step_ac_222_5` |
| AC-222.6 | met | `test_without_a_ux_change_the_gate_selects_the_defaults_ac_222_6`; `evalgate.selected` |
| AC-222.7 | met | `test_a_web_prompt_also_asks_for_ux_plan_ac_222_7`, `test_the_ux_rule_alone_asks_only_for_ux_plan_ac_222_7`, `test_named_workflows_win_and_rebaseline_keeps_its_two_ac_222_7` |
| AC-222.8 | met | `test_widened_words_count_as_visible_ac_222_8` (20 cases); `spec_ux.VISIBLE`, `spec_ux.ACTING` |
| AC-222.9 | met | `test_vetoed_phrases_do_not_count_but_another_word_does_ac_222_9` (14 cases); `spec_ux.NOT_VISIBLE` |
| AC-222.10 | met | `test_every_labelled_case_gets_its_label_ac_222_10` (41 cases), `test_the_cases_name_their_source_and_cover_both_labels_ac_222_10`, `test_the_field_keeps_its_answer_whatever_the_criteria_ac_222_10` |
| AC-222.11 | met | `test_the_docs_name_the_workflow_and_the_rule_ac_222_11`; `benchmark/README.md` (## ux-plan), `cplat spec ux --help` |

Non-goals respected: no prompt changed (`cplat platform rules check`: 415,222 bytes against 415,271, unchanged), no system-spec, console or default-benchmark change; `rules_rebaseline.WORKFLOWS` is still `quick-task`, `build`.

## The measured run

`cplat platform runs benchmark ux-plan --plugins plugins --dir ~/Dev/bench-files` on `ika100-demo/bench-files-web@37d26bd`, plugins `2faaa7d`, coordinator Sonnet: run `20261124T082841Z-ec0181a0`, outcome **done**, reset done.

| Role | Model | Calls | Tokens | Est. USD |
|---|---|---|---|---|
| coordinator | sonnet | 9 | 199,137 | 0.10 |
| web:ux-designer | opus | 5 | 68,045 | 0.21 |
| svc:architect | opus | 8 | 185,900 | 0.38 |
| total | | 22 | 454,882 | 0.69 |

Wall clock 4 min 3 s (session 3 min 50 s). The result check passed: `ux.md` on `feature/902-…` with Flows, Screens (header, status page with an ASCII wireframe), States and Accessibility, every criterion referenced; `cplat spec ux` `done`; `spec check` clean; `design.md` names `ux.md` and follows it (a client-side check so the first check has the loading state ux.md allows). No defect in the ux-designer prompt, so it is unchanged. One run only: the 1.5× gate limit applies from the next release's runs on.

## Checks

- `devbox run test-fast` over the full `tests/cplat` suite: 13,741 passed, 15 skipped (`/tmp/t222-full.log`).
- `devbox run quality`, `devbox run validate`: pass. `cplat platform rules check`: OK. `cplat spec trace 222`: 11/11. No workflow file changed, so the action pins are untouched.
