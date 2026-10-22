# Verification — 073 Secrets scan agrees locally and in CI

**Result:** pass
**Base:** 6197700 · **Trace:** 3/3 criteria named by tests · `pytest tests/cplat`: 612 passed, 4 skipped (`scripts/ci-local.sh` green)

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-073.1 | met | `tests/cplat/test_ci_gates.py::test_scanners_are_pinned_to_one_version_everywhere` | templates' devbox.json: `detect-secrets@1.5.0`, `trivy@0.74.0` | library-python has no trivy |
| AC-073.2 | met | `tests/cplat/test_ci_gates.py::test_baselines_keep_the_standard_filters_and_no_gibberish`, `::test_the_pragma_works_with_the_template_baseline` | regenerated `.secrets.baseline.json` in every template | the pragma test runs where detect-secrets is on PATH (passed locally against 1.5.0); the old baseline failed the same file |
| AC-073.3 | met | `tests/cplat/test_ci_gates.py::test_secrets_baseline_recipe_refreshes_with_fixed_flags` | `secrets-baseline` recipe, CLAUDE.md rows, security agent | found while fixing stock-manager: the hook re-adds the gibberish filter when it rewrites a baseline, so `secrets-scan` passes `--disable-filter` too; `scan --baseline` imports a broken baseline's filters, so the recipe regenerates one without `is_line_allowlisted` first |

## Non-goals

Other devbox packages stay `@latest`; the detectors are unchanged. ✔

## Deviations from the plan

None; specs 072–076 were implemented in one change with the plans written alongside (all tasks done).
