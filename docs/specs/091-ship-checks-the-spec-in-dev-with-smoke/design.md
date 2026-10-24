# Design — 091 Ship checks the spec in dev with smoke tests

Specs 093 (staging auto-promotion) and 097 (app ship) build on the interfaces below: the marker, the recipe, the
output lines, `smoke.run_smoke()`, `cplat smoke run`, the record section and the issue signature. Change them only
with a new spec. ADR: [034](../../adr/034-smoke-tests-against-a-deployed-environment.md).

## Decisions

- **One output contract for every shape, one parser in cplat.** Each deployable template ships a platform-owned
  `scripts/smoke.sh` (outside every `_skip_if_exists` path, so `/shared:update-service` delivers and refreshes it).
  It runs the shape's own test runner and prints the result lines of the Contract. `cplat` never reads runner
  formats: it reads only those lines, so `smoke.py` has no per-shape code.
- **Smoke tests live with the other tests and are selected by a tag.** The tag is per shape in `shapes.yml`
  (`smoke_tag`, a regex), and so is where trace looks for it (`smoke_globs`). A test counts as smoke-tagged for a
  criterion when one file both names the id and matches the tag (file level, like trace today). A per-test
  association would need a parser per language. The tester rule (one smoke test per file that names the id, AC-091.5)
  closes the gap in practice.
- **`test` and `ci` never reach a deployment.** Their recipes run with `SMOKE_BASE_URL=` (empty), whatever the shell
  says, and every smoke test skips itself without a base URL (it is reported as skipped, AC-091.4). Only `smoke` passes
  the URL through.
- **The dev URL is computed from the linked gitops-app, not configured in the service.** It is read through `gh api`
  from the gitops-app repo's `services.yaml` (`expose:`) and `app.yaml` (`hosts.dev`, and an optional new `urls.dev`).
  These are the same values `render.py` turns into the HTTPRoute. `cplat ship deploy --base-url` overrides it.
- **Before smoke runs, cplat checks that the dev URL is reachable.** It sends one GET to `<url><liveness probe>`. A
  connection error (DNS, refused, TLS, 10 s timeout) means `not-run: dev URL <url> is not reachable: <error>`. Any HTTP
  status means reachable. Without this check, a wrong port on a local cluster would look like red code and file a
  misleading issue. This is the "cannot reach a confirmed dev build" family of AC-091.11. It is not escalated.
- **Deploy escalates red smoke itself** (cause `code`). It files the smoke issue first, then calls
  `ship.escalate(...)`, because `escalate` ends the run record and `runs.filed` only writes to an active record (as in
  088). The orchestrator only reports. It never calls `cplat ship escalate` again for red smoke.
- **Resume runs smoke only** (AC-091.12). The state keeps `deployed` and `smoke.outcome`. On a later `cplat ship deploy`
  whose state has `deployed` set and outcome `red` or `timed-out`, deploy skips the pin wait, the health checks and the
  gitops merges, and goes straight to smoke against the dev URL.
- **Timing:** 600 s per attempt. A failed first attempt (at least one FAIL, or a recipe that failed without result
  lines) is retried once after 30 s. A timed-out attempt is not retried and is red at once with `timed out after 600s`.
- **Web smoke runs in Playwright, always** (AC-091.16). The Playwright scaffold becomes standard: `needs_e2e` stays in
  `copier.yml` only as a hidden, ignored question (`when: false`), so existing answers files still apply. `ci` does not
  download browsers: `@playwright/test` is only an npm package. `smoke` and `e2e` run
  `playwright install chromium` first.

## Modules

| Module / file | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/spec.py` | `(smoke)` marker on criteria, `Spec.smoke_acs()`, `smoke_trace()`, trace/ci/check messages | changed |
| `shapes.yml`, `scripts/shapes.py` | `smoke_tag` / `smoke_globs` per deployable shape; `smoke` becomes a required deploy recipe | changed |
| `scripts/cplat/smoke.py` | dev URL, reachability, recipe run, retry, timeout, parsing, criteria, record section, issue draft, `cplat smoke` CLI | new |
| `scripts/cplat/ship.py` | deploy runs smoke after health, escalates red, resumes smoke-only, state and `describe()` | changed |
| `scripts/cplat/update.py` | web-nextjs: adds `@playwright/test` to a project-owned `package.json`, refreshes the lockfile | changed |
| `templates/<shape>/scripts/smoke.sh` + helper | guard, runner, result lines (per deployable shape) | new |
| `templates/<shape>/devbox.json(.jinja)` | `smoke` recipe; `test`/`ci` run with an empty `SMOKE_BASE_URL` | changed |
| `templates/gitops-app/.../app.yaml.jinja` | documents the optional `urls:` map | changed |

## Contract

### Spec marker (AC-091.1, AC-091.5)

A criterion is smoke-checkable when its **bullet line** (the line matching `AC_LINE`) ends with `(smoke)`, followed
only by optional whitespace. Sub-bullets do not count. Example:
`- **AC-007.2** Given …, when …, then the alert list shows it. (smoke)`

- `spec.AC` gains `smoke: bool`. `Spec.smoke_acs() -> list[str]` lists the active criteria with the marker, in order.
- `cplat spec check` accepts the marker on active criteria. A marker on a withdrawn criterion is ignored. A marker in
  a spec whose shape has no `smoke_tag` (library-python, gitops-app) is an error:
  `AC-<id>: (smoke) needs a deployable shape (<shape> has no smoke tests)`. A spec without a shape (the platform
  repo) uses the repo's shape. If that is none, it uses service-python's tag.
- `spec.smoke_tag(shape) -> re.Pattern | None` and `spec.smoke_globs(shape) -> list[str]` (default: `test_globs`).
- `spec.smoke_trace(root, spec, globs, tag) -> dict[str, list[str]]`: for each smoke criterion, the files under
  `globs` that name the id (same `(?!\d)` rule) **and** match `tag`.
- `cplat spec trace <spec>`: a smoke criterion with no such file prints
  `MISS AC-<id>  smoke: no smoke-tagged test` (even when non-smoke tests name it) and the command exits 1.
  `--json` adds `"smoke": {<ac>: [files]}`, and the criterion is listed in `missing`.
- `cplat spec ci`: the same criterion gives `"<ac> smoke: no smoke-tagged test"` for building/done specs.

| shape | `smoke_tag` (regex) | `smoke_globs` | how a smoke test looks | skips itself when `SMOKE_BASE_URL` is empty |
|---|---|---|---|---|
| service-python | `pytest\.mark\.smoke\b` | test_globs | `@pytest.mark.smoke` + fixture `smoke_base_url` | the `smoke_base_url` fixture and the plugin skip it |
| service-java | `@Tag\(\s*"smoke"\s*\)` | test_globs | `@Tag("smoke")` + `@EnabledIfEnvironmentVariable(named = "SMOKE_BASE_URL", matches = ".+")`, `java.net.http.HttpClient` | the JUnit condition |
| service-go | `func\s+TestSmoke\w*\s*\(` | test_globs | top-level `func TestSmoke<Name>(t *testing.T)` | first line `if os.Getenv("SMOKE_BASE_URL") == "" { t.Skip("SMOKE_BASE_URL not set") }` |
| web-nextjs | `@smoke\b` | `["e2e/**/*.ts"]` | Playwright test in `e2e/` with `@smoke` in its title or `{ tag: "@smoke" }` | `test.skip(!process.env.SMOKE_BASE_URL, "SMOKE_BASE_URL not set")` |

A smoke test reaches the service only through the base URL (no app import, no test client, no database). It creates
its data with unique names (for example a `smoke-<uuid>` prefix), never changes or deletes data it did not create, and
asserts only on its own data (AC-091.5).

### `devbox run smoke` (AC-091.2, AC-091.3, AC-091.4)

Recipe in every deployable template: `"smoke": "bash scripts/smoke.sh"`.

1. Empty or unset `SMOKE_BASE_URL` → no test runs. It prints this to stderr and exits **2**:
   `ERROR: SMOKE_BASE_URL is not set: devbox run smoke runs the smoke tests against a running deployment, e.g. SMOKE_BASE_URL=https://<host> devbox run smoke`
2. Otherwise it runs only the smoke-tagged tests against the URL (trailing `/` removed), then prints, on stdout:
   - one line per test, in run order: `PASS  <id>`, `FAIL  <id>` or `SKIP  <id>` (the result, two spaces, the id)
   - then exactly one summary line: `smoke: <p> passed, <f> failed, <s> skipped`
   - or, with no smoke-tagged test, the single line `0 smoke tests` (exit 0)
3. `<id>` is `<path>::<name>`, where `<path>` is the test file relative to the repo root.
   - python: the pytest nodeid
   - java: `src/test/java/<package as dirs>/<Class>.java::<method>`
   - go: `<dir>/<file>_test.go::<TestName>`, top-level tests only
   - web: `e2e/<file>.ts::<title>`
4. Exit 0 only when `f == 0` and the runner itself succeeded. A runner that fails without result lines (compile
   error, browser missing) prints `FAIL  (smoke recipe)` and the runner's error, and exits 1.

Each shape's runner (output passes through to stdout, the result lines come last):

| shape | runner | result lines from |
|---|---|---|
| service-python | `uv run python -m pytest tests/ -p scripts.smoke_pytest -m smoke --smoke-report --no-cov -p no:cacheprovider` | `scripts/smoke_pytest.py`: a pytest plugin that registers the `smoke` marker, provides the `smoke_base_url` fixture, skips `smoke` items without a URL, prints the lines with `--smoke-report`, and turns "no tests collected" (5) into 0. It is typed strictly (`mypy .` checks it). |
| service-java | `mvn -B -q test -Dgroups=smoke -Dsurefire.failIfNoSpecifiedTests=false -Djacoco.skip=true` | `java scripts/SmokeSummary.java target/surefire-reports` (single-file Java program) |
| service-go | `go test -count=1 -json -run '^TestSmoke' ./...` piped to `go run scripts/smoke-summary.go` | `scripts/smoke-summary.go` (`//go:build ignore`). It reads the module path from `go.mod` and finds each test's file by `func <Name>(` in the package dir. A package build failure gives `FAIL  <dir>::(build)`. |
| web-nextjs | `pnpm exec playwright install chromium`, then `pnpm exec playwright test --grep @smoke --pass-with-no-tests --reporter=list,json` (JSON to a `mktemp` file via `PLAYWRIGHT_JSON_OUTPUT_NAME`) | `node scripts/smoke-summary.mjs <json>` |

The `test` (and so `ci`) recipes become:
- python: `SMOKE_BASE_URL= uv run python -m pytest tests/ -p scripts.smoke_pytest --cov=…`; `test-fast` likewise.
- java: `SMOKE_BASE_URL= mvn -B verify`.
- go: `SMOKE_BASE_URL= go test -race -cover ./...`.
- web: `SMOKE_BASE_URL= pnpm test`; `e2e`: `pnpm exec playwright install chromium && SMOKE_BASE_URL= pnpm exec playwright test`.

Example smoke test in each fresh skeleton (project-owned paths; a fresh repo has one, an updated repo gets none and
prints `0 smoke tests`):
- `tests/test_smoke_health.py`: GET `/health` returns 200 `{"status": "ok"}`.
- `src/test/java/<pkg>/SmokeHealthTest.java`: GET `/actuator/health/liveness` returns 200 with `UP`.
- `internal/server/smoke_test.go` `TestSmokeHealth`: GET `/health` returns 200.
- `e2e/smoke.spec.ts` `the root page loads at the base URL @smoke`: `/` shows a level-1 heading. The former local
  e2e checks move to `e2e/home.spec.ts`.

web-nextjs `playwright.config.ts`: `baseURL` is `process.env.SMOKE_BASE_URL || "http://localhost:<port>"`, and
`webServer` is only set when `SMOKE_BASE_URL` is empty. `package.json` always has `@playwright/test` and the `e2e`
script.

### Updated repos (AC-091.2, AC-091.16)

- `scripts/smoke.sh`, its helper and the recipes arrive through the normal update: the devbox merge keeps the
  template's version of a recipe.
- web-nextjs only, in `update.py` after copier:
  - if the project's `package.json` has no `@playwright/test` in `dependencies` or `devDependencies`, add the
    template's version to `devDependencies`. Keep the key order and 2-space indentation, and write
    `did: added @playwright/test to package.json (spec 091: browser smoke tests)`.
  - then run `devbox run -- pnpm install --lockfile-only` (timeout 600 s). On failure, add the next step
    `refresh the lockfile: devbox run -- pnpm install, then commit pnpm-lock.yaml`.
  - `playwright.config.ts` is not project-owned, so it arrives. The former `needs_e2e: false` answer no longer
    excludes it.

### Dev URL (AC-091.6, AC-091.11)

`smoke.dev_url(repo, apps, service, *, env="dev") -> tuple[str | None, str | None]` returns `(url, None)` or
`(None, reason)`. `apps` are the linked gitops-app slugs (`ship.gitops_apps`). For each slug, in order:

1. `gh api repos/<slug>/contents/applications` lists the app directories `<a>`.
2. `applications/<a>/services.yaml`: the entry whose `repo` equals the service slug, or else whose `name` equals the
   service name.
   - no entry → next app
   - an entry without `expose:`, or whose `environments` (default `[dev]`) lacks `dev` → reason
     `<service> has no dev URL (not exposed in dev)`
3. `applications/<a>/app.yaml`:
   - `hosts.dev` missing → the same reason
   - otherwise `host = hosts.dev.format(service=expose.host or name, app=a, env="dev")`
4. `url`:
   - `app.yaml` `urls.dev` (a template with `{host}`), formatted, when present
   - else `http://<host>:<port>` for a host ending in `.localhost`, with `<port>` = `$LOCAL_HTTP_PORT` when numeric,
     else 8088
   - else `https://<host>`

No app has the service → `<service> has no dev URL (not in the linked gitops-app)`. `app.yaml.jinja` documents
`urls:` as commented-out lines. `render.py` ignores the key.

### Python API (`scripts/cplat/smoke.py`, for 093 and 097)

```python
OUTCOMES = ("passed", "passed-on-retry", "red", "timed-out", "not-run")
LIMIT_S, RETRY_DELAY_S, TAIL_LINES = 600, 30, 60

@dataclass
class SmokeResult:
    env: str                      # "dev" (093: "staging")
    outcome: str                  # one of OUTCOMES
    base_url: str | None
    passed: int; failed: int; skipped: int
    tests: list[dict]             # [{"id": str, "result": "passed"|"failed"|"skipped"}] of the attempt that counts
    failing: list[str]            # sorted ids of failing tests; ["(timed out)"] for timed-out
    flaky: list[str]              # ids that failed on the first attempt of a passed-on-retry run
    retried: bool
    duration_s: float             # wall time of all attempts, including the retry wait
    reason: str | None            # not-run reason, or "timed out after 600s"
    tail: str                     # last 60 lines of the counting attempt, redacted (feedback.redact); "" when passed
    criteria: dict[str, str]      # (smoke) criterion -> "passed" | "failed" | "unchecked"
    @property
    def ok(self) -> bool          # passed or passed-on-retry; never true for not-run
    def row(self, issue: str | None = None) -> str
    def lines(self) -> list[str]
    def section(self, filed: dict | None = None) -> dict

def run_recipe(repo: Path, base_url: str, timeout: float) -> Attempt          # seam: tests replace it
def has_recipe(repo: Path) -> bool                                            # devbox.json defines "smoke"
def reachable(url: str, timeout: float = 10.0) -> str | None                  # seam; None or the error text
def dev_url(repo: Path, apps: list[str], service: str, *, env: str = "dev") -> tuple[str | None, str | None]
def not_run(env: str, reason: str, smoke_acs: list[str]) -> SmokeResult
def run_smoke(repo: Path, base_url: str, *, env: str = "dev", spec: "specmod.Spec | None" = None,
              timeout: float = LIMIT_S, retry_delay: float = RETRY_DELAY_S, retry: bool = True,
              probe: str | None = None) -> SmokeResult
def issue_draft(result: SmokeResult, *, service_slug: str, spec_id: str | None, image: str | None,
                run_id: str | None, shape: str) -> autoissue.Draft
def file_issue(result: SmokeResult, **draft_kw) -> autoissue.Outcome          # never raises
def main(argv: list[str]) -> int                                              # `cplat smoke`
```

`Attempt` holds `exit_code: int | None` (None = timed out), `tests: list[tuple[str, str]]`, the three counts,
`output: str` and `duration_s: float`.

- `run_recipe` runs `devbox run smoke` in `repo` with `SMOKE_BASE_URL=<url>`. It uses its own process group: at the
  limit the whole group is killed. It parses the result lines.
- `run_smoke` steps:
  1. no recipe → not-run `the repo has no smoke recipe (update it with /shared:update-service)`
  2. `probe` (the shape's liveness path) given and `reachable(base_url + probe)` fails → not-run
     `dev URL <url> is not reachable: <error>`
  3. attempt 1
  4. if it failed and was not timed out: `sleep(retry_delay)`, then attempt 2
  5. map to the outcome
- Sleep and clock go through `smoke.sleep` / `smoke.monotonic` (seams).
- `criteria`: for each `spec.smoke_acs()`, take the files from `smoke_trace`.
  - `failed`: a FAIL id has its path in those files
  - `passed`: at least one PASS id does and none fails
  - `unchecked`: otherwise, and always for not-run
- It never raises for a failing or missing runner: those are outcomes.

### `cplat smoke` CLI

`cplat smoke run [--env dev] [--base-url URL] [--spec <spec>] [--timeout 600] [--no-retry] [--json]`, in a service repo.

- Without `--base-url`, it resolves the URL with `dev_url` (only `--env dev` resolves; others need `--base-url`).
- It prints `lines()`, or `{"smoke": section(), "tests": tests}` with `--json`.
- Exit codes: 0 for passed or passed-on-retry, 1 for red or timed-out, 3 for not-run.
- It files no issue and touches no ship state. Filing belongs to the caller (deploy, 093).

### Deploy output (AC-091.6–AC-091.9, AC-091.11)

`cplat ship deploy` gains `--base-url URL` (overrides `dev_url`). After `<service>-dev` and every gitops app are
Synced/Healthy, it sets `st["deployed"] = "sha-<40>"` and runs smoke. Its lines:

```
smoke (dev) against <url>:
PASS  tests/test_smoke_health.py::test_health_answers_at_the_base_url
FAIL  tests/test_alerts.py::test_ac_007_2_alert_list_shows_the_new_rule
smoke: 1 passed, 1 failed, 0 skipped
retried after 30s: <n> failing again                       (only after a retry)
criterion AC-007.2 (smoke): failed                         (one line per (smoke) criterion of the spec)
failing: tests/test_alerts.py::test_ac_007_2_alert_list_shows_the_new_rule
--- smoke output (last 60 lines, secrets redacted) ---
<tail>
issue: <url> new | +1 | not filed: <reason> …               (autoissue Outcome.lines)
ship <spec>: escalated (smoke red in dev: 1 failing (<spec_id>)); dev keeps running sha-<40>. Resume with /svc:ship <spec>
Smoke (dev): red (1 failing, issue <url>)
```

- Passed: no `failing`/tail lines, `Smoke (dev): <p>/<total> passed`, exit 0, phase `done`.
- Passed on retry: `Smoke (dev): passed on retry`, exit 0.
- Red or timed-out: exit 1, the state is escalated with cause `code`, and nothing is rolled back.
- Timed-out: `timed out after 600s` replaces the summary, and the reason reads `smoke red in dev: 1 failing (<spec_id>)`.

`<total>` = passed + failed + skipped. The issue part of the red row is `issue <url>`, or `issue not filed: <reason>`
when filing returned `pending` or `off`.

Not run: the lines are `smoke not run: <reason>`, then `unchecked (smoke) criteria: <ids>` (or `none`), then
`Smoke (dev): not run: <reason>`. Deploy finishes `done` (exit 0), with no escalation. The reasons:

| case | reason |
|---|---|
| no `--context` | `no kube context, so Argo health was not checked (pass --context <kube-context>)` |
| not exposed | from `dev_url` |
| not linked (the early `_done`) | `the repo is not linked to a gitops-app` |
| no recipe / unreachable | from `run_smoke` |
| library | `not deployable (library)` |

Resume: with `st["deployed"]` set and `st["smoke"]["outcome"]` in `red`/`timed-out`, deploy prints
`resuming: smoke only, against what dev runs now` and runs only the smoke step. The `--context` check is not
repeated, because dev was confirmed before.

State: `st["smoke"] = {"outcome", "row", "signature", "url"}`. `describe()` prints `  smoke: <row>`.

### Issue (AC-091.14)

`issue_draft` gives an `autoissue.Draft` with:
- `kind="smoke"`, `repo=<service slug>`, `command="cplat ship deploy"`, `phase="deploy"`, `shape` from the stamp
- `names={}`: the spec id and the repo stay readable in the service's own repo. Secrets are still redacted by
  `scrub`.
- `signature = autoissue.signature("smoke", service_slug, "dev", "\n".join(sorted(failing)))`, so the volatile parts
  are normalised away as in 088
- `reason = "Smoke red in dev: " + ", ".join(failing)` (the title becomes `[auto] Smoke red in dev: …`, at most 100
  characters, 088's rule)
- `evidence = tail` (at most 60 lines)
- `sections=[("Smoke", "- spec: <spec_id>\n- image: <sha-40>\n- environment: dev\n- base URL: <url>\n- failing tests:\n  - <id>…")]`
- `run_id`

Labels come from autoissue: `triage`, `auto-filed`, `smoke-failure`. `file_issue` calls
`autoissue.file(draft, run_id=rid)` (088's dedupe, the closed and `wontfix` rule, the cap, pending retry,
`runs.filed`) and never raises. An exception becomes `Outcome`-like lines `issue: not filed: <type>: <msg>`.

### Run record section (AC-091.15)

`runs.set_section(run_id, "smoke", result.section(filed))`, written before `_done` / `escalate` ends the record:

```json
{"env": "dev", "outcome": "red", "base_url": "http://api.shop-dev.localhost:8088",
 "passed": 1, "failed": 1, "skipped": 0, "total": 2, "duration_s": 71.4, "retried": true,
 "flaky": [], "reason": null, "criteria": {"AC-007.2": "failed"},
 "failing": ["tests/test_alerts.py::test_ac_007_2_alert_list_shows_the_new_rule"],
 "filed": {"signature": "smoke:0123456789abcdef", "url": "https://github.com/o/r/issues/7", "result": "new"}}
```

- `filed` is `null` when nothing was filed. `result` is one of `new` / `+1` / `suppressed` / `pending` / `off`, as in
  088's `filed`. The filing itself also lands in the record's `filed` list through `autoissue.file`.
- For not-run, the counts are 0, `reason` is set and every criterion is `unchecked`.
- `passed-on-retry` lists the first attempt's failing ids in `flaky`.
- `not-run` is never `passed`: `SmokeResult.ok` is false, the row says `not run: …`, and 093 must treat it as not
  green.

## Risks

- **File-level tag association** can count a smoke tag of another test in the same file. The tester rule and
  `smoke: no smoke-tagged test` cover the common mistake; the ADR records the limit.
- **A local cluster on a non-default port**: set `LOCAL_HTTP_PORT` or `urls.dev`. Otherwise the reachability check
  gives a clear not-run, never a false red.
- **Browser download in `smoke`** (web) costs time on the first run on a machine. It is cached in
  `~/.cache/ms-playwright`, and `ci` is unaffected.
- **pnpm lockfile on update**: `--lockfile-only` needs the registry. If that fails, the update says how to refresh the
  lockfile, and the repo's `ci` (`--frozen-lockfile`) fails until then.
- **Tests:** `tests/cplat` cannot run Maven, Go or Playwright. Acceptance tests render the templates (copier, `slow`)
  and check files and recipes statically. They can run `scripts/smoke_pytest.py` with the platform's pytest against
  a local `http.server`, and they drive `smoke.run_smoke` / `ship.deploy` through the seams (`run_recipe`,
  `reachable`, `smoke.gh`, `ship.gh`, `sleep`, the autoissue fake tracker). The real runners of all four shapes are
  exercised by the platform CI template jobs, which start the image and run `scripts/smoke.sh` against it (plan t11).
