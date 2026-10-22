# Verification — 078 One image tag format: the full commit sha

**Result:** pass
**Base:** b1fb9a6 · **Trace:** 3/3 criteria named by tests · `scripts/ci-local.sh` green: 657 passed, 4 skipped (`pytest -n auto`)

| Criterion | Verdict | Tests |
|---|---|---|
| AC-078.1 | met | `tests/cplat/test_tags_and_wait.py::test_service_ci_publishes_and_dispatches_the_full_sha` |
| AC-078.2 | met | `tests/cplat/test_tags_and_wait.py::test_pin_dev_accepts_both_formats_and_keeps_the_short_branch`, `tests/cplat/test_tags_and_wait.py::test_pin_accepts_the_full_sha`, `tests/cplat/test_tags_and_wait.py::test_promote_pins_the_full_sha_and_falls_back_to_the_short_one` |
| AC-078.3 | met | `tests/cplat/test_tags_and_wait.py::test_the_decision_is_recorded` |

## Notes

Existing pins stay `sha-<7>` until each service's next build; stock-manager's own CI is moved in its own PR.

## Deviations from the plan

None; specs 077–084 were implemented in one change with the plans written alongside (all tasks done).
