# Verification — 219 Website specs get a UX design step

**Result:** pass
**Base:** origin/main at 6c43d89c+ · **Trace:** 11/11 criteria named by tests (`tests/cplat/test_219_ux_design.py`, 30 tests)

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-219.1 | met | `test_only_web_nextjs_declares_the_ux_designer`, `test_a_flag_without_the_agent_fails_the_registry_check` | `shapes.yml` (`ux_designer: true` on web-nextjs), `scripts/shapes.py` `_ux_designer_errors` | `scripts/shapes.py check` passes. |
| AC-219.2 | met | `test_a_website_routes_the_ux_designer`, `test_other_shapes_route_no_ux_designer` (5 shapes) | `scripts/cplat/shapecmd.py` | A real `web-nextjs` render routes `ux-designer: web:ux-designer`. |
| AC-219.3 | met | `test_a_visible_criterion_needs_ux_and_names_the_word`, `test_a_visible_story_needs_ux`, `test_nothing_visible_needs_no_ux` | `scripts/cplat/spec_ux.py` `decide`, `VISIBLE` | Real render: `needed — a criterion or story names 'page'`. |
| AC-219.4 | met | `test_the_field_decides_over_the_criteria`, `test_an_unknown_field_value_fails_the_check` | `spec_ux.decide`, `spec_ux.field_errors` via `spec.check` | |
| AC-219.5 | met | `test_other_shapes_answer_none_whatever_the_field` (service-python, library-typescript, no shape) | `spec_ux.decide` | The platform repo: `none — platform has no UX design step`. |
| AC-219.6 | met | `test_a_current_ux_md_is_done_and_a_stale_one_is_needed` | `spec_ux.decide`, `_recorded_hash` | Real render: `done — ux.md matches the current criteria` after writing ux.md. |
| AC-219.7 | met | `test_a_complete_ux_md_passes_the_check`, `test_a_missing_section_fails_naming_it` (4), `test_an_unknown_or_withdrawn_criterion_fails` (2), `test_bad_front_matter_fails` | `spec_ux.file_errors` via `spec.check` | |
| AC-219.8 | met | `test_the_agent_reads_and_writes_but_runs_nothing`, `test_the_agent_names_the_ux_md_sections_and_passes_the_rules_check` | `plugins/web/agents/ux-designer.md`, `docs/rules/plugins/web/agents/ux-designer.yml` | opus; tools Read, Write, Glob, Grep. |
| AC-219.9 | met | `test_plan_asks_cplat_and_designs_before_the_architect` | `plugins/component/commands/plan.md` (step 2 UX design), `ship.md` (spawn record) | Structure only; behaviour is left to the eval gate (ADR-103). |
| AC-219.10 | met | `test_the_coder_brief_has_ux_and_the_reviewer_reads_ux_md` | `build.md` 2.3 `UX` field, `plugins/svc/agents/reviewer.md` inputs and step 5 | A gap is a deviation, not `not met` (A5). |
| AC-219.11 | met | `test_the_docs_name_the_step` | spec-format `SKILL.md` and `references/spec.md`, `plugins/web/README.md`, `docs/AGENTS.md`, ADR-126 | |

## Deviations

- `scripts/cplat/stages.py` (not in a task's files by name, inside t2's scope): the Plan stage explanation names the ux-designer. Acceptable.

## Checks

Full cplat suite before the final fixes: 13,056 passed, 17 failed: 15 were the prompt-size baseline (fixed by the
rebaseline), `test_spec_agents` (AGENTS.md row) and `test_476` (the agent named a cplat command) were fixed, and
`test_208_runtemp` passed on its own rerun. `devbox run quality`, `devbox run validate`, `cplat platform rules check`,
`cplat spec check 219` and `cplat spec trace 219` pass. Prompts: 387,135 → about 390,300 bytes (+~3.2 KB), raised through
`cplat platform rules rebaseline` after the quick-task and build benchmarks.
