# Design — 104 Generated repos build and observe reliably

## Decisions

- **Strict installs, no fallback** (AC-104.1, AC-104.2). `templates/service-python/Dockerfile` copies
  `pyproject.toml uv.lock` (the lock is required, no `*`) and runs `uv sync --locked --no-dev --no-install-project`,
  then `uv sync --locked --no-dev`. `--locked` fails when the lock does not satisfy `pyproject.toml`; `--frozen` did
  not check that, and the `|| uv sync` fallback re-resolved silently. `templates/web-nextjs/Dockerfile.jinja` copies
  `package.json pnpm-lock.yaml` and runs `pnpm install --frozen-lockfile`, without `2>/dev/null || pnpm install`.
- **The Dockerfile stays template-owned** (AC-104.3): it is not in `_skip_if_exists` of either template (checked by a
  test), so `/shared:update-service` brings the strict install. The CHANGELOG tells repos with an out-of-date lock to
  run `uv lock` / `pnpm install` once before updating.
- **One recording middleware** (AC-104.4 to AC-104.8) in `src/<module>/metrics.py`: `MetricsMiddleware`
  (Starlette `BaseHTTPMiddleware`) records `http_requests_total{method, route, status_code}` and
  `http_request_duration_seconds{method, route}` for every request. `route` is the matched route's path template
  (`request.scope["route"].path`, so `/items/{id}`); a request no route matched records `route="unmatched"`
  (AC-104.5). The label name changes from `endpoint` to `route`; the CHANGELOG says so (dashboards that used
  `endpoint` must follow). An exception that reaches the middleware records status `500`, increments
  `application_errors_total{error_type=<exception class name>}` and re-raises so FastAPI answers 500 (AC-104.6).
  Requests to `/metrics` are not recorded (AC-104.7). `/ping` loses its hand-written count (AC-104.8), and every
  declared metric is recorded by the middleware.
- **Observability off** (AC-104.9): `metrics.py`, the middleware registration, `/metrics` and the
  `prometheus-client` dependency are left out when `needs_observability` is false. `metrics.py` moves to
  `_exclude` (`{% if not needs_observability %}src/{{ module_name }}/metrics.py{% endif %}`) instead of rendering a
  comment-only file.
- **Platform tests** (AC-104.10): `tests/cplat/test_generated_repos.py` renders `service-python` (observability on and
  off) and `web-nextjs` with copier, like `test_ci_templates.py`, and checks the strict install lines, the
  `_skip_if_exists` lists, the middleware wiring and the off case (no `prometheus` anywhere). The behaviour of
  AC-104.4 to AC-104.7 is tested inside the template (`templates/service-python/tests/test_metrics.py`, with
  FastAPI's `TestClient`), which the existing `smoke-test Copier templates` CI job already runs through
  `devbox run quality`/`test`; it adds seconds, not minutes. The lockfile mismatch of AC-104.1 is exercised in that
  job by one extra step: add a dependency to the rendered `pyproject.toml` without locking and assert
  `uv sync --locked --no-dev --no-install-project` exits non-zero (no Docker build needed; the Dockerfile runs that
  exact command). The web job gets the same step with `pnpm install --frozen-lockfile`. Both steps together stay well
  under the 2-minute cap.

## Contract

```
service-python metrics (observability on):
  http_requests_total{method, route, status_code}            counter
  http_request_duration_seconds{method, route}               histogram (buckets unchanged)
  application_errors_total{error_type}                        counter
  route = matched path template | "unmatched"; /metrics never recorded
Dockerfile:  uv sync --locked ...           web Dockerfile:  pnpm install --frozen-lockfile
```
