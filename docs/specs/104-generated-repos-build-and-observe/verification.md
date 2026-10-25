# Verification — 104 Generated repos build and observe reliably

**Result:** pass (cycle 2)
**Commit:** c700340 · **Base:** a55e858 (merge base with origin/main) · **Trace:** 10/10, `cplat spec trace 104` exits 0

Cycle 1 (38fb602) failed on AC-104.4, AC-104.9 and AC-104.10. The fixes are ea1bd29, d1d00b7 and c700340; the rows below are re-judged on c700340.

Acceptance tests are unchanged since the red commit 01d08fb (`git diff 01d08fb..HEAD -- tests/cplat templates/service-python/tests` is empty).

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-104.1 | met | `tests/cplat/test_generated_repos.py::test_python_dockerfile_installs_strictly`, `::test_python_rendered_dockerfile_is_strict` | `templates/service-python/Dockerfile:9-10,14` | `uv.lock` required (no `*`), `--locked`, no fallback. Checked by hand: with a real added dependency (`six>=1`) and no `uv lock`, `uv sync --locked --no-dev --no-install-project` stops with "The lockfile at `uv.lock` needs to be updated, but `--locked` was provided"; with a matching lock it exits 0 |
| AC-104.2 | met | `test_generated_repos.py::test_web_dockerfile_installs_strictly` | `templates/web-nextjs/Dockerfile.jinja:6-7` | checked pnpm@11.22.0 by hand on a minimal project: an added `is-odd 3.0.1` without relocking gives "specifiers in the lockfile don't match", exit 1 |
| AC-104.3 | met | `test_generated_repos.py::test_dockerfile_is_template_owned[service-python]`, `[web-nextjs]` | `templates/service-python/copier.yml:15-27`, `templates/web-nextjs/copier.yml:16-28` | no pattern there matches `Dockerfile`; CHANGELOG has the migration note |
| AC-104.4 | met | template `tests/test_smoke_metrics.py::test_requests_are_counted_in_metrics` (`@pytest.mark.smoke`), template `tests/test_metrics.py::test_added_endpoint_and_404_are_counted_with_duration`; trace via `tests/cplat/test_generated_smoke_104.py::test_template_smoke_test_reads_metrics_from_a_running_service` | `templates/service-python/src/{{ module_name }}/metrics.py:41-61`, `main.py:26`; `.github/workflows/ci.yml:246` expects `smoke: 2 passed` | the real evidence is the template smoke test. CI runs it against uvicorn, and so did I on c700340: `smoke: 2 passed, 0 failed, 0 skipped`. It asserts exact `http_requests_total` lines for `/health` 200 and `unmatched` 404 and no raw path. The platform file only checks the text of the template test (static), so it is trace plumbing rather than proof of behaviour. That is acceptable because CI line 246 fails if the smoke test is missing or red. Excluded when observability is off (`copier.yml:34`); the off render has no `test_smoke_metrics.py` |
| AC-104.5 | met | `test_metrics.py::test_variable_paths_count_under_one_route` | `metrics.py:35-38` (`scope["route"].path`, else `unmatched`) | asserts both `/items/123` and `/items/456` land on `/items/{id}`, no concrete-path label and no per-path 404 label |
| AC-104.6 | met | `test_metrics.py::test_unhandled_error_is_500_and_counted` | `metrics.py:50-57` (`status = 500`, `ERROR_COUNT.labels(error_type=type(exc).__name__)`, bare `raise`) | re-raise lets `ServerErrorMiddleware` answer 500; test asserts the 500 response, the count with `status_code="500"` and `application_errors_total{error_type="ValueError"}` +1 |
| AC-104.7 | met | `test_metrics.py::test_scraping_metrics_adds_nothing` | `metrics.py:47-48` | asserts the middleware records `/health` and that two scrapes leave every `http_request*` line unchanged |
| AC-104.8 | met | `test_generated_repos.py::test_main_registers_the_metrics_middleware_and_ping_does_not_count` | `main.py:46-49` (no hand-written count), `metrics.py:60-61,56` (all three metrics recorded) | |
| AC-104.9 | met | `test_generated_repos.py::test_observability_off_has_no_metrics_code`; CI step `Observability off renders and tests` (`ci.yml:224-233`) runs the off render's `tests/test_health.py` | `copier.yml:32-34` (`_exclude`), `main.py:5-27,50-57` | CI now renders off, checks there is no `metrics.py` and runs the health tests through `TestClient` (app import and `/health` 200). In cycle 1 I also ran it by hand under uvicorn: `/health` ok, `/metrics` 404 |
| AC-104.10 | met | `test_generated_repos.py::test_ci_checks_the_lockfile_mismatch_for_python`, `::test_ci_checks_the_lockfile_mismatch_for_web`, the AC-104.1/2 static tests, the template `test_metrics.py` run by the smoke job | `.github/workflows/ci.yml:212-222`, `:336-346` | the python step now adds the real `six>=1` and requires `needs to be updated` in the output. Checked by hand: that is exactly uv's `--locked` message, and an unrelated failure no longer passes. The web step requires `ERR_PNPM_OUTDATED_LOCKFILE`; I confirmed pnpm@11.22.0 (the CI version) prints it on a stale lock, exit 1. Added time: two renders, one `uv sync`, two fast-failing installs, under 2 minutes |

## Non-goals

No changes to `service-java`, `service-go`, the todo samples, dashboards, alert rules or tracing. `src/**` and `tests/**` stay in `_skip_if_exists`, so existing repos keep their own application code. ✔

## Deviations from the plan

- `templates/service-python/src/{{ module_name }}/logging_config.py` changed, but it is in no task's `files` (comment reworded so the off variant no longer says "prometheus", which the AC-104.9 test forbids). Acceptable.
- `copier.yml` `_exclude` also drops `tests/test_metrics.py` when observability is off. Acceptable and needed: that test imports `prometheus_client`. The design mentions only `metrics.py`.
- `import os` only with observability on, plus the blank-line changes in `main.py`. Acceptable and needed: in the off variant `os` was unused, which ruff rejects; the off render is ruff, format and mypy clean.
- Cycle 2: `templates/service-python/tests/test_smoke_metrics.py` and `tests/cplat/test_generated_smoke_104.py` are in no task's `files`. Acceptable: they are the fixes asked for in cycle 1. The rendered default service (on) is still ruff, format and mypy clean, and `pytest tests/ -p scripts.smoke_pytest` passes with the smoke tests skipped.
- All tasks `done: true`.

## Contract

Matches `design.md`: `http_requests_total{method, route, status_code}`, `http_request_duration_seconds{method, route}` (buckets unchanged), `application_errors_total{error_type}`, `route` = path template or `unmatched`, `/metrics` not recorded; Dockerfiles use `uv sync --locked` and `pnpm install --frozen-lockfile`. ✔ One extra thing the contract does not cover: a request to `/metrics/` (a redirect) is recorded as `unmatched` 307. Harmless.
