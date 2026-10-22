# Verification — 071 Adopt an existing repo

**Result:** pass
**Base:** decbfbc · **Trace:** 4/4 criteria named by tests · `pytest tests/cplat`: 563 passed, 3 skipped

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-071.1 | met | `tests/cplat/test_adopt.py::test_adopt_adds_what_is_missing_and_never_overwrites` | `scripts/cplat/adopt.py plan_files(), execute()` |  |
| AC-071.2 | met | `tests/cplat/test_adopt.py::test_adopt_adds_what_is_missing_and_never_overwrites` | `adopt.py merge_devbox(), merge_gitignore()` |  |
| AC-071.3 | met | `tests/cplat/test_adopt.py::test_an_adopted_repo_is_a_platform_repo` | `adopt.py answers_for(), execute()` |  |
| AC-071.4 | met | `tests/cplat/test_adopt.py::test_dry_run_changes_nothing, ::test_adopt_refuses_repos_that_already_have_answers, ::test_adopt_refuses_an_unknown_shape` | `adopt.py resolve()` |  |

## Non-goals

The repo's code layout is not changed. ✔

## Deviations from the plan

None; the specs were implemented in one change with the plan written alongside (all tasks done).
