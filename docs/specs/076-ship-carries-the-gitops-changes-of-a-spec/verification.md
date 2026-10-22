# Verification — 076 Ship carries the gitops changes of a spec

**Result:** pass
**Base:** 6197700 · **Trace:** 6/6 criteria named by tests · `pytest tests/cplat`: 612 passed, 4 skipped (`scripts/ci-local.sh` green)

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-076.1 | met | `tests/cplat/test_ship_checks.py::test_spec_check_validates_gitops_tasks` | `spec.py _gitops_task_errors()`, `human_steps` check |  |
| AC-076.2 | met | `tests/cplat/test_ship_checks.py::test_gitops_prepare_and_pr_open_a_draft_pr` | `ship.py gitops_prepare()`, `gitops_pr()`, `cplat ship gitops` | the checkout lives next to the run state in the git common dir |
| AC-076.3 | met | `tests/cplat/test_ship_checks.py::test_land_merges_before_merge_gitops_prs_first_and_stops_on_red`, `::test_a_missing_gitops_pr_blocks_the_pr` | `merge_gitops(…, 'before-merge')` in `land()`; `open_pr()` refuses missing gitops PRs |  |
| AC-076.4 | met | `tests/cplat/test_ship_checks.py::test_deploy_merges_after_release_prs_and_waits_for_every_named_app`, `::test_a_sync_error_in_a_named_app_stops_the_deploy` | `deploy()`, `_healthy()`, `argo_health()` (conditions `*Error`, failed operations) | `<service>-dev` is checked healthy before the after-release PRs merge, then again with the named apps |
| AC-076.5 | met | `tests/cplat/test_ship_checks.py::test_deploy_merges_after_release_prs_and_waits_for_every_named_app` | `_done()` appends the checklist |  |
| AC-076.6 | met | `tests/cplat/test_ship_checks.py::test_architect_and_plan_command_plan_gitops_tasks_with_expand_contract` | architect agent, `/svc:plan`, plan reference |  |

## Non-goals

CRD validation from the service branch is a follow-up issue; `/svc:build` alone keeps reporting gitops needs. ✔

## Deviations from the plan

None; specs 072–076 were implemented in one change with the plans written alongside (all tasks done).
