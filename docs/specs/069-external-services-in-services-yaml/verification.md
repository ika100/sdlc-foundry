# Verification — 069 External services in services.yaml

**Result:** pass
**Base:** decbfbc · **Trace:** 4/4 criteria named by tests · `pytest tests/cplat`: 563 passed, 3 skipped

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-069.1 | met | `tests/cplat/test_gitops.py::test_an_external_kustomize_package_is_wired_and_pinned_like_a_service` | `templates/gitops-app/scripts/render.py external_files(), render_app()` |  |
| AC-069.2 | met | `tests/cplat/test_gitops.py::test_an_external_helm_chart_gets_an_argo_application_with_the_pinned_tag` | `render.py external_files(), deep_merge(), set_path()` |  |
| AC-069.3 | met | `tests/cplat/test_gitops.py::test_pin_and_promote_move_external_services, ::test_status_reads_the_pin_of_external_services` | `templates/gitops-app/scripts/pin.py (re-render); promote and status unchanged` |  |
| AC-069.4 | met | `tests/cplat/test_gitops.py::test_external_entries_are_validated` | `render.py validate_external()` |  |

## Non-goals

No native CronJob/PVC generation; guard rails unchanged. ✔

## Deviations from the plan

None; the specs were implemented in one change with the plan written alongside (all tasks done).
