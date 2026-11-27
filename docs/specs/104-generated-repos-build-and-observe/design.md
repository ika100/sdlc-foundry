# Design — 104 Generated repos build and observe reliably

AC-104.1 to AC-104.10 were built by plan.v1 (t1–t4, done). The amendment of 2026-11-27 (issue 965) adds AC-104.11 and
AC-104.12 and extends AC-104.2/AC-104.3 to `service-typescript`; its decisions are in the second half.

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

### Amendment: private packages (AC-104.11, AC-104.12, issue 965)

- **The token reaches the install as a BuildKit secret mounted as an environment variable** (AC-104.11). Both
  TypeScript Dockerfiles (`web-nextjs`, `service-typescript`) raise the frontend to `# syntax=docker/dockerfile:1.10`
  (the first version with `env=` on a secret mount) and install with
  `RUN --mount=type=secret,id=PACKAGES_READ_TOKEN,env=NODE_AUTH_TOKEN pnpm install --frozen-lockfile`. A secret mount
  exists only while that `RUN` runs: it is in no layer, no build argument (`ARG`/`--build-arg` are never used for it)
  and no history entry (history shows the command text, not the value). The mount is optional (BuildKit's default
  `required=false`), so a build without the secret runs the same install with no token. `env=` instead of reading
  `/run/secrets/...` in a shell keeps the install a single command with no `$(...)`, `||` or `2>/dev/null`, so the
  strict install of AC-104.2 stays recognisable.
- **The repo's `.npmrc` is copied into the deps stage** (`COPY package.json pnpm-lock.yaml pnpm-workspace.yaml* .npmrc* ./`):
  it holds the scope registry and `//npm.pkg.github.com/:_authToken=${NODE_AUTH_TOKEN}` (the consumer format of the
  library-typescript template), never a token. The runtime stage copies no `.npmrc` (`service-typescript` copies
  `package.json`, `node_modules`, `dist`; `web-nextjs` copies the standalone output), so no registry config lands in
  the image either. `.dockerignore` already lets `.npmrc` through.
- **CI passes the repository secret through `secret-envs`, never `secrets:`.** Both `docker/build-push-action` steps
  (build-try and build-retry) of the template `ci.yml` get `env: PACKAGES_READ_TOKEN: ${{ secrets.PACKAGES_READ_TOKEN }}`
  and `secret-envs: PACKAGES_READ_TOKEN=PACKAGES_READ_TOKEN`. The action rejects an empty value in `secrets:`
  (`KEY=` is "not a valid secret"), which would break every repo without the secret; `secret-envs` names the variable
  only, so an unset repository secret gives an empty token and a public-only repo builds unchanged, while a private
  dependency fails at the install with the registry's 401 (AC-104.11, last sentence).
- **CI's own install steps get the token too.** Each `devbox run install` step of the template `ci.yml` (quality,
  test, security, ci-extra) gets `env: NODE_AUTH_TOKEN: ${{ secrets.PACKAGES_READ_TOKEN }}`, so CI and the image install
  the same dependencies (story 3). Step-level, not workflow-level, so third-party actions never see it.
- **Local image builds pass it when the developer has it.** The `image-build` devbox recipe of both templates becomes
  `docker build --secret id=PACKAGES_READ_TOKEN,env=NODE_AUTH_TOKEN -t <project>:scan .`; with `NODE_AUTH_TOKEN` unset
  the optional secret is absent and the build is unchanged.
- **The strict install now covers `service-typescript`** (AC-104.2, AC-104.3): its Dockerfile already installs with
  `--frozen-lockfile` and is not in `_skip_if_exists`; the platform smoke job of the shape gets the same stale-lock step
  as `web-nextjs`.
- **Platform proof without a private package** (AC-104.10, AC-104.11; answered question: no real private build). The
  existing smoke jobs keep building the image without the secret (public dependencies, unchanged). The `web-nextjs` and
  `service-typescript` smoke jobs then rebuild once (cached, seconds) with a random marker as the secret
  (`docker build --secret id=PACKAGES_READ_TOKEN,env=MARKER`) and fail if the marker appears in
  `docker history --no-trunc`, `docker image inspect` or `docker export` of the image. Static checks of the rendered
  Dockerfile and `ci.yml` live in `tests/cplat/test_generated_repos.py`.
- **`/platform:doctor` reports the missing secret** (AC-104.12) from a new module `scripts/cplat/doctor_packages.py`,
  wired into `doctor.run_checks` next to `check_gitops_token`. It reads only files and `gh`: a repo with no private
  dependency gets no row at all. A missing secret is `FAIL` (the image build and CI of that repo cannot install), an
  unreadable secret list is `WARN`, like the GITOPS_TOKEN row.
- **No new ADR.** The secret name and who passes it are ADR-125 point 5; this spec only makes the consuming templates
  do what point 5 said they did not do yet. Point 5's last sentence is updated to say so instead of a new ADR.

## Contract

```
service-python metrics (observability on):
  http_requests_total{method, route, status_code}            counter
  http_request_duration_seconds{method, route}               histogram (buckets unchanged)
  application_errors_total{error_type}                        counter
  route = matched path template | "unmatched"; /metrics never recorded
Dockerfile:  uv sync --locked ...           web Dockerfile:  pnpm install --frozen-lockfile
```

### TypeScript Dockerfiles (`web-nextjs`, `service-typescript`; AC-104.2, AC-104.11)

```
line 1:     # syntax=docker/dockerfile:1.10
deps stage: COPY package.json pnpm-lock.yaml pnpm-workspace.yaml* .npmrc* ./
            RUN --mount=type=secret,id=PACKAGES_READ_TOKEN,env=NODE_AUTH_TOKEN pnpm install --frozen-lockfile
```

- Exactly one `pnpm install` line in the file, and it is the one above; no `||`, `2>/dev/null`, `ARG` or `--build-arg`
  mentioning the token anywhere; `pnpm-lock.yaml` stays without `*`.
- The runtime stage has no `COPY` of `.npmrc` and no `PACKAGES_READ_TOKEN` / `NODE_AUTH_TOKEN`.

### Template `ci.yml` (`web-nextjs`, `service-typescript`)

```
docker job, steps build-try and build-retry (docker/build-push-action):
  env:   PACKAGES_READ_TOKEN: ${{ secrets.PACKAGES_READ_TOKEN }}
  with:  secret-envs: PACKAGES_READ_TOKEN=PACKAGES_READ_TOKEN      # no `secrets:` input, no `build-args:` with the token
quality, test, security, ci-extra jobs, step `devbox run install`:
  env:   NODE_AUTH_TOKEN: ${{ secrets.PACKAGES_READ_TOKEN }}
no workflow-level or job-level env carries PACKAGES_READ_TOKEN or NODE_AUTH_TOKEN
```

Template `devbox.json.jinja`: `"image-build": "docker build --secret id=PACKAGES_READ_TOKEN,env=NODE_AUTH_TOKEN -t {{ project_name }}:scan ."`.

### `/platform:doctor` row (AC-104.12)

`scripts/cplat/doctor_packages.py`:

```python
def private_package_sources(repo: Path, owner: str) -> list[str]: ...   # what needs the token, in order; [] = none
def check_packages_token(repo: Path) -> list[dict]: ...                  # [] | one doctor.check(...) row
```

Triggers (`owner` = the owner part of `ship.service_slug(repo)`, compared case-insensitively):

1. **npm**: `repo/.npmrc` has a line `@<owner>:registry=https://npm.pkg.github.com` (optional trailing `/`,
   whitespace around `=` allowed, `#`/`;` comment lines ignored). Source string: `@<owner> packages from npm.pkg.github.com`.
2. **Python**: `repo/pyproject.toml` contains a URL `https://github.com/<o>/<r>/releases/download/...` and
   `gh api repos/<o>/<r> --jq .private` prints `true` or fails (a repo this login cannot read is private to it).
   Source string: `wheels of <o>/<r> (private release assets)`, one per distinct repo, in file order. A public repo's
   release assets need no token and add nothing.

Rows (`name` = `secret PACKAGES_READ_TOKEN`; `<slug>` = `ship.service_slug(repo)`; `<sources>` = the source strings
joined with `, `):

| Situation | Row |
|---|---|
| no trigger, or `gh` not installed | none (the function returns `[]`) |
| trigger, secret in `ship.secret_names(repo)` (repo or organization) | `OK`, detail `set: CI and the image build can read <sources>` |
| trigger, `ship.secret_names(repo)` is `None` | `WARN`, detail `could not be read with this gh login`, fix as below |
| trigger, secret missing | `FAIL`, detail `not set: CI and the image build cannot install <sources>`, fix as below |

Fix: `create a token that can read <what>, then: gh secret set PACKAGES_READ_TOKEN -R <slug>`, where `<what>` is
`packages (classic token, read:packages)` for the npm trigger, `<o>/<r>[, ...] (fine-grained: Contents read)` for the
Python trigger, and both joined with ` and ` when both apply. The command `gh secret set PACKAGES_READ_TOKEN -R <slug>`
appears verbatim in every non-OK row.
