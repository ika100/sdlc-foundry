# Verification — 147 The system plan writes the repo specs

**Result:** pass

| Criterion | Evidence |
|---|---|
| AC-147.1 | `plugins/system/agents/planner.md` step 3 and the plan format (`criteria:`, 3 to 8, each `(system AC-<NNN>.<n>)`); journey 5's plan `ika100-demo/taskboard5-gitops` `docs/plan/001-persistent-tasks-and-web-task-board.md` lists 6 criteria for the API and 7 for the web UI. |
| AC-147.2 | `templates/gitops-app/scripts/plan.py` `check_criteria`; `tests/cplat/test_plan.py::test_a_plan_with_repo_criteria_passes_ac_147_2`, `::test_repo_criteria_must_cover_their_slice_ac_147_2`. |
| AC-147.3 | `scripts/cplat/spec.py` `new_from_plan`; `tests/cplat/test_spec.py::test_a_plan_with_repo_criteria_gives_a_spec_ready_to_approve_ac_147_3`; journey 5's repo specs (`taskboard5-api` 002, `taskboard5-web` 001) say "created from the system plan, with its criteria (spec 147)". |
| AC-147.4 | `plugins/component/references/spec-from-plan.md` step 2 and the per-repo prompt in `plugins/system/commands/ship.md`; journey 5's system ship approved both repo specs without a product-manager. |
| AC-147.5 | `tests/cplat/test_plan.py::test_a_plan_without_repo_criteria_stays_valid_ac_147_5`; the product-manager flow of `spec-from-plan.md` is kept for such plans. |
| AC-147.6 | `scripts/cplat/spec.py` `size_warning`; `tests/cplat/test_spec.py::test_more_than_twelve_criteria_warn_but_pass_ac_147_6`; product-manager rule 4. |
| AC-147.7 | Journey 5 (2026-11-06), step "Plan and ship it to dev": the only product-manager runs of the journey are at 17:49 Z (the component spec, step 3) and 19:48 Z (the system spec, step 6, before the ship started at 19:53 Z); no repo-spec question was asked; 43 minutes, 20.4 M tokens, 13 repo criteria, recorded in `docs/PERFORMANCE.md` next to journey 4's 65 minutes, 38.3 M tokens and 42 criteria. |
