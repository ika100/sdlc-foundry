# Verification — 104 Generated repos build and observe reliably

**Result:** fail
**Commit:** 38fb602 · **Base:** a55e858 (merge base with origin/main) · **Trace:** 6/10 criteria named by tests in `tests/cplat`; AC-104.4 to AC-104.7 are named in the template's `tests/test_metrics.py`, which `cplat spec trace` does not scan; AC-104.4 is `(smoke)` and has no smoke-tagged test, so trace exits 1

Acceptance tests are unchanged since the red commit 01d08fb (`git diff 01d08fb..HEAD -- tests/cplat templates/service-python/tests` is empty).

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-104.1 | met | `tests/cplat/test_generated_repos.py::test_python_dockerfile_installs_strictly`, `::test_python_rendered_dockerfile_is_strict` | `templates/service-python/Dockerfile:9-10,14` | `uv.lock` required (no `*`), `--locked`, no fallback. Checked by hand: with a real added dependency (`six>=1`) and no `uv lock`, `uv sync --locked --no-dev --no-install-project` stops with "The lockfile at `uv.lock` needs to be updated, but `--locked` was provided"; with a matching lock it exits 0 |
| AC-104.2 | met | `test_generated_repos.py::test_web_dockerfile_installs_strictly` | `templates/web-nextjs/Dockerfile.jinja:6-7` | checked pnpm@11.22.0 by hand on a minimal project: an added `is-odd 3.0.1` without relocking gives "specifiers in the lockfile don't match", exit 1 |
| AC-104.3 | met | `test_generated_repos.py::test_dockerfile_is_template_owned[service-python]`, `[web-nextjs]` | `templates/service-python/copier.yml:15-27`, `templates/web-nextjs/copier.yml:16-28` | no pattern there matches `Dockerfile`; CHANGELOG has the migration note |
| AC-104.4 | partial | template `tests/test_metrics.py::test_added_endpoint_and_404_are_counted_with_duration` (in-process `TestClient`) | `templates/service-python/src/{{ module_name }}/metrics.py:41-61`, `main.py:26` | behaviour is right (rendered and run: 7 passed; my own probe shows `/items/{id}`, 422, 405, 403 and `unmatched` 404 all counted with method, route, status). But the criterion is marked `(smoke)` and no smoke-tagged test names it: `cplat spec trace 104` reports `MISS AC-104.4 smoke: no smoke-tagged test` and exits 1 (AC-091.1). Fix: add a smoke-tagged test that names AC-104.4 where trace finds it, or amend the spec to drop the marker (the platform repo has no deployed dev to smoke) and record it in the Changelog |
| AC-104.5 | met | `test_metrics.py::test_variable_paths_count_under_one_route` | `metrics.py:35-38` (`scope["route"].path`, else `unmatched`) | asserts both `/items/123` and `/items/456` land on `/items/{id}`, no concrete-path label and no per-path 404 label |
| AC-104.6 | met | `test_metrics.py::test_unhandled_error_is_500_and_counted` | `metrics.py:50-57` (`status = 500`, `ERROR_COUNT.labels(error_type=type(exc).__name__)`, bare `raise`) | re-raise lets `ServerErrorMiddleware` answer 500; test asserts the 500 response, the count with `status_code="500"` and `application_errors_total{error_type="ValueError"}` +1 |
| AC-104.7 | met | `test_metrics.py::test_scraping_metrics_adds_nothing` | `metrics.py:47-48` | asserts the middleware records `/health` and that two scrapes leave every `http_request*` line unchanged |
| AC-104.8 | met | `test_generated_repos.py::test_main_registers_the_metrics_middleware_and_ping_does_not_count` | `main.py:46-49` (no hand-written count), `metrics.py:60-61,56` (all three metrics recorded) | |
| AC-104.9 | partial | `test_generated_repos.py::test_observability_off_has_no_metrics_code` | `copier.yml:32-33` (`_exclude`), `main.py:5-27,50-57` | the test proves "no metrics code or dependency" (no `metrics.py`, no `prometheus` anywhere). Nothing automated proves "it starts and answers `/health`": CI renders only the default (observability on) service-python, and the platform test never imports or runs the off render. I rendered the off variant by hand: ruff, format, mypy clean, `tests/test_health.py` 3 passed, uvicorn answers `/health` `{"status":"ok"}` and `/metrics` 404. Fix: in the platform test, run the off render's `tests/test_health.py` (or at least compile `main.py`), or add an observability-off render to the smoke job |
| AC-104.10 | partial | `test_generated_repos.py::test_ci_checks_the_lockfile_mismatch_for_python`, `::test_ci_checks_the_lockfile_mismatch_for_web`, plus the AC-104.1/2 static tests and the template `test_metrics.py` run by the smoke job | `.github/workflows/ci.yml:212-221`, `:324-333` | the static tests do fail if the strict install is missing, and `test_metrics.py` runs in CI. The web step is sound (`is-odd 3.0.1` exists, so only `--frozen-lockfile` makes it fail). The python step is vacuous: `ci.yml:218` adds `httpx-stale-lock-check>=0`, a package that does not exist, so resolution fails ("requirements are unsatisfiable") whatever the flags; I checked that a plain `uv sync --no-dev --no-install-project` without `--locked` fails the same way (exit 1). The step would stay green if `--locked` stopped rejecting stale locks. Fix: add a real package (for example `"six>=1"`), then only the `--locked` check fails it. Time: three copier renders and two steps that fail in seconds (plus copying `node_modules`), well under 2 minutes |

## Non-goals

No changes to `service-java`, `service-go`, the todo samples, dashboards, alert rules or tracing. `src/**` and `tests/**` stay in `_skip_if_exists`, so existing repos keep their own application code. ✔

## Deviations from the plan

- `templates/service-python/src/{{ module_name }}/logging_config.py` changed, but it is in no task's `files` (comment reworded so the off variant no longer says "prometheus", which the AC-104.9 test forbids). Acceptable.
- `copier.yml` `_exclude` also drops `tests/test_metrics.py` when observability is off. Acceptable and needed: that test imports `prometheus_client`. The design mentions only `metrics.py`.
- `import os` only with observability on, plus the blank-line changes in `main.py`. Acceptable and needed: in the off variant `os` was unused, which ruff rejects; the off render is ruff, format and mypy clean.
- All tasks `done: true`.

## Contract

Matches `design.md`: `http_requests_total{method, route, status_code}`, `http_request_duration_seconds{method, route}` (buckets unchanged), `application_errors_total{error_type}`, `route` = path template or `unmatched`, `/metrics` not recorded; Dockerfiles use `uv sync --locked` and `pnpm install --frozen-lockfile`. ✔ One extra thing the contract does not cover: a request to `/metrics/` (a redirect) is recorded as `unmatched` 307. Harmless.
