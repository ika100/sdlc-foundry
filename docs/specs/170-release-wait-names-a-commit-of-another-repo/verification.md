# Verification — 170 Release wait names a commit of another repo

**Result:** pass

| Criterion | Evidence |
|---|---|
| AC-170.1 | `tests/cplat/test_143_release_wait.py::test_a_commit_of_another_repo_says_so_at_once_ac_170_1` |
| AC-170.2 | `tests/cplat/test_143_release_wait.py::test_a_network_error_on_the_commit_check_keeps_waiting_ac_170_2` |

Found during journey 8 (#614), fixed by #615.
