# Verification — 145 Smoke tests that write run only in dev

**Result:** pass
**Trace:** 7/7 criteria named by tests

Tests: `R` = `tests/cplat/test_smoke_474_read_only.py`. Also run by hand: service-python rendered with copier, a `@pytest.mark.writes` smoke test added, the
service started with uvicorn; `devbox run smoke` with `SMOKE_READ_ONLY=1` passed 2 and skipped the writing test, in dev it
passed 3; `cplat instance verify prod --base-url …` exited 0 with the read-only line, `staging` with only the writing test
left printed `smoke not run: no read-only smoke test ran in staging …` and exited 3.

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-145.1 | met | `R::test_the_recipe_learns_the_environment_and_whether_it_may_write` (dev, staging, prod; the shell sets `SMOKE_READ_ONLY=1`), `R::test_read_only_mode_is_everything_but_dev` | `scripts/cplat/smoke.py:55-57` (`read_only`), `:190-195` (`run_recipe`), `:315`, `:328` | Every caller (ship deploy, staging, verify, upgrade verify) goes through `run_smoke` with its env |
| AC-145.2 | met | `R::test_a_read_only_run_with_a_passing_check_passes_and_says_read_only`, `R::test_the_recipe_learns_the_environment_and_whether_it_may_write` | `scripts/cplat/smoke.py:110-112`, `:137-138`, `:160` | |
| AC-145.3 | met | `R::test_outside_dev_a_run_that_checked_nothing_is_not_run_never_passed` (only writing tests; none), `R::test_in_dev_a_run_without_passing_tests_still_passes_as_before`, `R::test_instance_verify_prod_records_a_run_without_read_only_test_and_exits_3` | `scripts/cplat/smoke.py:60-63`, `:291-298` | Staging smoke treats `not-run` as before: no escalation, the reason in `Smoke (staging)` |
| AC-145.4 | met | `R::test_instance_verify_prod_records_a_run_without_read_only_test_and_exits_3`; `tests/cplat/test_verify_records_422.py` still passes | `scripts/cplat/smoke.py:519-521` | A named `--base-url` is still not recorded |
| AC-145.5 | met | `R::test_each_smoke_script_leaves_out_writing_tests_when_read_only` (4 shapes), `R::test_python_harness_skips_writing_tests_when_read_only`, `R::test_python_harness_runs_writing_tests_in_dev`, `R::test_the_writes_marker_is_registered_for_test_and_ci` | `templates/service-python/scripts/smoke_pytest.py`, `templates/*/scripts/smoke.sh` | Java, Go and web are checked statically; their array expansions work in bash 3.2 under `set -u` |
| AC-145.6 | met | `R::test_each_claude_md_documents_the_writing_mark_and_the_read_only_rule`, `R::test_the_sample_smoke_test_is_read_only_so_it_runs_everywhere` (4 shapes each) | `templates/*/CLAUDE.md*` "Smoke tests", the sample smoke tests | |
| AC-145.7 | met | `R::test_the_tester_agents_mark_writing_smoke_tests_and_keep_read_only_checks` (4 agents), `R::test_the_testing_reference_names_every_mark` | `plugins/{svc,svc-java,svc-go,web}/agents/tester.md` "Smoke criteria", `plugins/svc/skills/spec-format/references/testing.md` | |
