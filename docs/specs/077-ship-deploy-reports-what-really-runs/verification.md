# Verification — 077 Ship deploy reports what really runs

**Result:** pass
**Base:** b1fb9a6 · **Trace:** 4/4 criteria named by tests · `scripts/ci-local.sh` green: 657 passed, 4 skipped (`pytest -n auto`)

| Criterion | Verdict | Tests |
|---|---|---|
| AC-077.1 | met | `tests/cplat/test_ship_checks.py::test_deploy_fails_at_once_on_a_red_pin_dev_run`, `tests/cplat/test_ship_checks.py::test_a_stuck_pin_dev_run_is_rerun_once`, `tests/cplat/test_ship_checks.py::test_pin_dev_names_its_run_for_deploy` |
| AC-077.2 | met | `tests/cplat/test_ship_checks.py::test_a_red_main_ci_fails_the_deploy_at_once`, `tests/cplat/test_ship_checks.py::test_no_pin_dev_run_after_a_green_main_names_the_token` |
| AC-077.3 | met | `tests/cplat/test_ship_checks.py::test_argo_old_image_is_waiting_not_healthy`, `tests/cplat/test_ship_checks.py::test_argo_revision_must_reach_the_gitops_merge` |
| AC-077.4 | met | `tests/cplat/test_ship_checks.py::test_ship_start_refuses_a_linked_repo_without_gitops_token`, `tests/cplat/test_ship_checks.py::test_templates_warn_when_the_token_is_missing` |

## Notes

Deviation: `ship deploy` no longer watches pin PR checks (they never exist); AC-072.5 is withdrawn in spec 072.

## Deviations from the plan

None; specs 077–084 were implemented in one change with the plans written alongside (all tasks done).
