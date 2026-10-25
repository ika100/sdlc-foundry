---
spec_id: 091-ship-checks-the-spec-in-dev-with-smoke
spec_hash: e7aac0176c41
summary: (smoke) criterion marker traced against a per-shape smoke tag; devbox run smoke (SMOKE_BASE_URL, one output contract)
  in every deployable template incl. standard Playwright for web; smoke.py runs it with retry/limit, record section and smoke
  issue; ship deploy runs smoke against the gitops-app's dev URL, escalates red as code, resumes smoke-only
tasks:
- id: t1
  title: (smoke) marker, smoke trace and per-shape smoke tags
  files: [scripts/cplat/spec.py, shapes.yml, scripts/shapes.py]
  covers: [AC-091.1, AC-091.5]
  parallel_safe: true
  depends_on: []
  done: true
- id: t2
  title: smoke module and cplat smoke CLI
  files: [scripts/cplat/smoke.py, scripts/cplat/cplat.py]
  covers: [AC-091.6, AC-091.7, AC-091.8, AC-091.9, AC-091.11, AC-091.14, AC-091.15]
  parallel_safe: true
  depends_on: [t1]
  done: true
- id: t3
  title: ship deploy runs smoke in dev, escalates red, resumes smoke-only
  files: [scripts/cplat/ship.py]
  covers: [AC-091.6, AC-091.7, AC-091.8, AC-091.9, AC-091.11, AC-091.12, AC-091.14, AC-091.15]
  parallel_safe: true
  depends_on: [t2]
  done: true
- id: t4
  title: service-python smoke recipe, pytest plugin and example test
  files: [templates/service-python/devbox.json, templates/service-python/scripts/smoke.sh, templates/service-python/scripts/smoke_pytest.py,
    templates/service-python/tests/test_smoke_health.py]
  covers: [AC-091.2, AC-091.3, AC-091.4]
  parallel_safe: true
  depends_on: []
  done: true
- id: t5
  title: service-java smoke recipe, summary program and example test
  files: [templates/service-java/devbox.json.jinja, templates/service-java/scripts/smoke.sh, templates/service-java/scripts/SmokeSummary.java,
    'templates/service-java/src/test/java/{{ package_path }}/SmokeHealthTest.java.jinja']
  covers: [AC-091.2, AC-091.3, AC-091.4]
  parallel_safe: true
  depends_on: []
  done: true
- id: t6
  title: service-go smoke recipe, summary program and example test
  files: [templates/service-go/devbox.json.jinja, templates/service-go/scripts/smoke.sh, templates/service-go/scripts/smoke-summary.go,
    templates/service-go/internal/server/smoke_test.go]
  covers: [AC-091.2, AC-091.3, AC-091.4]
  parallel_safe: true
  depends_on: []
  done: true
- id: t7
  title: web-nextjs standard Playwright scaffold and browser smoke recipe
  files: [templates/web-nextjs/copier.yml, templates/web-nextjs/devbox.json.jinja, templates/web-nextjs/package.json.jinja,
    templates/web-nextjs/playwright.config.ts.jinja, templates/web-nextjs/e2e/smoke.spec.ts.jinja, templates/web-nextjs/e2e/home.spec.ts.jinja,
    templates/web-nextjs/scripts/smoke.sh, templates/web-nextjs/scripts/smoke-summary.mjs, templates/web-nextjs/CLAUDE.md.jinja,
    templates/web-nextjs/app/page.tsx.jinja, templates/web-nextjs/tests/page.test.tsx.jinja, templates/web-nextjs/docs/adr/000-bootstrap.md.jinja]
  covers: [AC-091.2, AC-091.3, AC-091.4, AC-091.16]
  parallel_safe: true
  depends_on: []
  done: true
- id: t8
  title: update-service adds Playwright to web repos that opted out
  files: [scripts/cplat/update.py]
  covers: [AC-091.2, AC-091.16]
  parallel_safe: true
  depends_on: []
  done: true
- id: t9
  title: tester agents and spec format write smoke tests for (smoke) criteria
  files: [plugins/svc/agents/tester.md, plugins/svc-java/agents/tester.md, plugins/svc-go/agents/tester.md, plugins/web/agents/tester.md,
    plugins/svc/skills/spec-format/references/spec.md, plugins/svc/skills/spec-format/references/testing.md, plugins/svc/commands/build.md]
  covers: [AC-091.1, AC-091.5]
  parallel_safe: true
  depends_on: []
  done: true
- id: t10
  title: ship command, docs and the gitops-app urls key
  files: [plugins/svc/commands/ship.md, docs/CHANGELOG.md, docs/unattended-delivery.md, 'templates/gitops-app/applications/{{
      app_name }}/app.yaml.jinja', templates/gitops-app/scripts/render.py]
  covers: [AC-091.6, AC-091.9, AC-091.11, AC-091.12, AC-091.15]
  parallel_safe: true
  depends_on: []
  done: true
- id: t11
  title: smoke is a required deploy recipe; platform CI runs each template's smoke against its started image
  files: [scripts/shapes.py, .github/workflows/ci.yml]
  covers: [AC-091.2, AC-091.3, AC-091.4, AC-091.16]
  parallel_safe: true
  depends_on: [t1, t4, t5, t6, t7]
  done: true
---

The contract for every task is [design.md](design.md). ADR: [036](../../adr/036-smoke-tests-against-a-deployed-environment.md).
The result-line format of `devbox run smoke` (`PASS|FAIL|SKIP  <path>::<name>`, `smoke: <p> passed, <f> failed, <s> skipped`,
`0 smoke tests`) is shared by t2 and t4–t7: keep it byte-exact. No test may reach GitHub, a cluster or a real devbox:
`smoke.run_recipe`, `smoke.reachable`, `smoke.gh`, `smoke.sleep`, `smoke.monotonic`, `ship.gh` and the autoissue
tracker are the seams. No plugin or marketplace version bumps (the release does them).

## t1 — (smoke) marker, smoke trace and per-shape smoke tags

**Files:** scripts/cplat/spec.py, shapes.yml, scripts/shapes.py
**Covers:** AC-091.1, AC-091.5
**Goal:** a criterion line ending with `(smoke)` is a smoke criterion. Trace counts it only through a file that names
the id and matches the shape's smoke tag. See design.md "Spec marker".

**Implementation notes:**
- `AC` gains `smoke: bool`, detected on the matched bullet line with `\(smoke\)\s*$`. `Spec.smoke_acs()` lists the
  active ones.
- `smoke_tag(shape)` / `smoke_globs(shape)` read `shapes.yml`. With no shape, they use service-python's.
- `smoke_trace(root, spec, globs, tag)` reuses `trace`'s file walk and `_ignored`.
- `check()`: `AC-<id>: (smoke) needs a deployable shape (<shape> has no smoke tests)` when the effective shape has no
  `smoke_tag`.
- `trace` CLI:
  - `MISS <ac>  smoke: no smoke-tagged test`
  - `--json` gets `"smoke"` and `missing`
  - exit 1
- `ci_problems`: `"<ac> smoke: no smoke-tagged test"`.
- `shapes.yml`: `smoke_tag` for the four deployable shapes (single-quoted regexes of the design table), and
  `smoke_globs: ["e2e/**/*.ts"]` for web-nextjs.
- `shapes.py validate`: a deployable non-planned shape needs a `smoke_tag` that compiles. `smoke_globs`, if present,
  is a non-empty list of strings. Non-deployable shapes must not have one.
- Do not add the recipe requirement here (t11 does, once the templates have it).

**Done when:** the AC-091.1 trace and check tests pass, `uv run scripts/shapes.py check` passes, and `test_spec*.py`
stays green.

## t2 — smoke module and cplat smoke CLI

**Files:** scripts/cplat/smoke.py, scripts/cplat/cplat.py
**Covers:** AC-091.6, AC-091.7, AC-091.8, AC-091.9, AC-091.11, AC-091.14, AC-091.15
**Goal:** the shape-agnostic smoke runner of design.md "Python API", "Dev URL", "Issue" and "Run record section", plus
`cplat smoke run`. Specs 093 and 097 import it, so keep the names exactly.

**Implementation notes:**
- `run_recipe`:
  - runs `devbox run smoke` with `SMOKE_BASE_URL` in a new session
  - at `timeout`, kills the process group (`os.killpg`), giving `exit_code=None`
  - parses only the contract lines
  - a non-zero exit with no FAIL line adds `FAIL  (smoke recipe)`
- `run_smoke` steps:
  1. recipe check
  2. reachability check (`probe`)
  3. attempt 1
  4. `sleep(30)` and attempt 2 when attempt 1 failed and was not timed out
  5. outcome

  Durations come from `monotonic()`. `tail` is the last 60 non-empty lines of the counting attempt, through
  `feedback.redact`.
- `criteria` comes from `specmod.smoke_trace` plus the path before `::` of each id.
- `dev_url`:
  - `gh api` reads `contents` (raw) through the module seam `gh(args) -> (code, out)`
  - YAML through `yaml.safe_load`
  - every failure gives a reason, never an exception
- `row()`, `lines()` and `section()` give exactly the strings and keys of the design.
- `issue_draft` / `file_issue`:
  - the signature over `(service_slug, "dev", "\n".join(sorted(failing)))`
  - `names={}`
  - the `Smoke` section
  - `autoissue.file(draft, run_id=...)`
  - `try/except` maps an exception to `issue: not filed: <type>: <msg>`
- CLI as in "`cplat smoke` CLI":
  - exits 0 / 1 / 3
  - `--json`
  - no filing
- `cplat.py`: `"smoke": "smoke"` in `COMMANDS`, plus the usage line in the docstring.

**Done when:** at module level, with fake `run_recipe`, `reachable`, `gh` and clock, the acceptance tests pass for:
- the retry (AC-091.7)
- the timeout (AC-091.8)
- the tail and redaction (AC-091.9)
- the not-run reasons from `dev_url` and `run_smoke` (AC-091.11)
- the signature, title, labels and body of the draft with a fake tracker (AC-091.14)
- `section()`, `row()` and `ok` (AC-091.15)
- the dev URL from fake gitops files, and the `cplat smoke run` exit codes

## t3 — ship deploy runs smoke in dev, escalates red, resumes smoke-only

**Files:** scripts/cplat/ship.py
**Covers:** AC-091.6, AC-091.7, AC-091.8, AC-091.9, AC-091.11, AC-091.12, AC-091.14, AC-091.15
**Goal:** `cplat ship deploy` ends with smoke as in design.md "Deploy output".

**Implementation notes:**
- `deploy(..., base_url=None)` and the CLI flag `--base-url`.
- After the last `_healthy`, set `st["deployed"]` and save. Then:
  - no context → not-run
  - else `dev_url` (or `base_url`) → not-run reason, or
    `smoke.run_smoke(repo, url, spec=sp, probe=<liveness from shapes.yml runtime>)`
- The early "not linked" and "library" `_done` paths also record a not-run smoke (reasons of the design table).
  Their existing first line stays.
- `_smoke_finish(repo, st, result, lines)`, in this order:
  1. on red / timed-out: `smoke.file_issue(...)` with the image `st["deployed"]` and `st["run_id"]`
  2. `runs.set_section(rid, "smoke", result.section(filed))`
  3. `st["smoke"] = {...}`
  4. green or not-run → `_done`. Red → `escalate(repo, "smoke red in dev: <n> failing (<spec>)", "code",
     report=lines)`, the escalated line, return `False`.

  The `Smoke (dev): …` line comes last before the human steps.
- Resume: at the top of `deploy`, if `st.get("deployed")` and `st.get("smoke", {}).get("outcome")` is in
  `{"red", "timed-out"}`, print the resuming line and run only the smoke step.
- `describe()` adds `  smoke: <row>`.
- Recording errors never change the deploy result: wrap them as `save_state` does.

**Done when:**
- The AC-091.6, .9, .11, .12, .14 and .15 acceptance tests pass through `ship.main([... "deploy" ...])`, with fake
  `gh`/kubectl, fake `smoke.run_recipe` and `reachable`, and a fake autoissue tracker:
  - pass → done
  - pass on retry
  - red → exit 1, escalated with cause `code`, issue lines, nothing rolled back
  - every not-run reason → done, not escalated
  - resume → smoke only, no pin calls
  - the record `smoke` section
- `test_ship*.py` and the 087/088 ship tests stay green.

## t4 — service-python smoke recipe, pytest plugin and example test

**Files:** templates/service-python/devbox.json, templates/service-python/scripts/smoke.sh, templates/service-python/scripts/smoke_pytest.py, templates/service-python/tests/test_smoke_health.py
**Covers:** AC-091.2, AC-091.3, AC-091.4
**Goal:** `devbox run smoke` for service-python per design.md "`devbox run smoke`".

**Implementation notes:**
- `scripts/smoke.sh`:
  - `set -euo pipefail`
  - the `SMOKE_BASE_URL` guard (exit 2, the exact message)
  - then `uv run python -m pytest tests/ -p scripts.smoke_pytest -m smoke --smoke-report --no-cov -p no:cacheprovider`
- `scripts/smoke_pytest.py` (pytest plugin, mypy-strict clean, ruff clean):
  - registers the `smoke` marker
  - a `smoke_base_url` fixture: skips when the URL is empty, otherwise returns it without the trailing `/`
  - `pytest_collection_modifyitems` skips `smoke` items without a URL, with the reason `SMOKE_BASE_URL not set`
  - `--smoke-report` prints the result lines and the summary, or `0 smoke tests`. A setup error counts as FAIL.
  - exit status 5 → 0
- `devbox.json`:
  - `"smoke": "bash scripts/smoke.sh"`
  - `test` / `test-fast` prefixed `SMOKE_BASE_URL= ` and switched to `uv run python -m pytest … -p scripts.smoke_pytest`
    (keep `--cov={{ module_name }}`)
- `tests/test_smoke_health.py`: one `@pytest.mark.smoke` test, `httpx.get(f"{smoke_base_url}/health")` → 200
  `{"status": "ok"}`.
- `ci` is unchanged (it calls `test`).

**Done when:**
- The rendered template's `devbox.json` has the recipes of the design.
- Run with the platform's pytest against a local `http.server`, `scripts/smoke_pytest.py` prints the contract lines:
  pass, fail, `0 smoke tests`, the guard.
- `uv run pytest` in a rendered repo reports the example as skipped (AC-091.2–.4 template tests).

## t5 — service-java smoke recipe, summary program and example test

**Files:** templates/service-java/devbox.json.jinja, templates/service-java/scripts/smoke.sh, templates/service-java/scripts/SmokeSummary.java, templates/service-java/src/test/java/{{ package_path }}/SmokeHealthTest.java.jinja
**Covers:** AC-091.2, AC-091.3, AC-091.4
**Goal:** `devbox run smoke` for service-java per the design.

**Implementation notes:**
- `scripts/smoke.sh`:
  - the guard
  - `mvn -B -q test -Dgroups=smoke -Dsurefire.failIfNoSpecifiedTests=false -Djacoco.skip=true`, keeping its exit
    code without stopping
  - then `java scripts/SmokeSummary.java target/surefire-reports "$mvn_exit"`
- `SmokeSummary.java` (single-file, JDK only):
  - reads the `TEST-*.xml` files
  - prints `PASS|FAIL|SKIP  src/test/java/<pkg dirs>/<Class>.java::<method>` and the summary, or `0 smoke tests`
  - no reports and a non-zero mvn exit → `FAIL  (smoke recipe)`
  - exit 0 only when nothing failed
- Spotless and Checkstyle must stay green: check whether they cover `scripts/`; if they do, keep the file compliant.
- `SmokeHealthTest`:
  - `@Tag("smoke")`, `@EnabledIfEnvironmentVariable(named = "SMOKE_BASE_URL", matches = ".+")`
  - `HttpClient` GET `<url>/actuator/health/liveness` → 200 containing `UP`
  - no Spring context
  - Checkstyle-clean
- `devbox.json.jinja`: `"smoke": "bash scripts/smoke.sh"`, and `test` / `test-fast` prefixed `SMOKE_BASE_URL= `.

**Done when:** the rendered template contains the recipe and files, the template acceptance tests (static) pass, and
the JaCoCo gate still holds in `mvn -B verify`: the example test is skipped there and counts no lines.

## t6 — service-go smoke recipe, summary program and example test

**Files:** templates/service-go/devbox.json.jinja, templates/service-go/scripts/smoke.sh, templates/service-go/scripts/smoke-summary.go, templates/service-go/internal/server/smoke_test.go
**Covers:** AC-091.2, AC-091.3, AC-091.4
**Goal:** `devbox run smoke` for service-go per the design.

**Implementation notes:**
- `scripts/smoke.sh`: the guard, then
  `set -o pipefail; go test -count=1 -json -run '^TestSmoke' ./... | go run scripts/smoke-summary.go`.
  The summary's exit code decides.
- `scripts/smoke-summary.go`:
  - `//go:build ignore`, stdlib only
  - reads the `test2json` events
  - reports top-level tests only, mapping the import path to the dir through `go.mod`'s `module` line, and the test
    to its file by `func <Name>(`
  - a package `fail` without tests → `FAIL  <dir>::(build)`
  - `0 smoke tests` when there are none
- `internal/server/smoke_test.go`: `TestSmokeHealth`:
  - `t.Skip` when `SMOKE_BASE_URL` is empty
  - `http.Get(<url>/health)` → 200
  - gofmt and golangci-lint clean
- `devbox.json.jinja`: `"smoke": "bash scripts/smoke.sh"`, and `test` / `test-fast` prefixed `SMOKE_BASE_URL= `.
- Check that the `_templates_suffix` and `_exclude` of `copier.yml` render the new files: non-`.jinja` files are
  copied verbatim.

**Done when:** the rendered template contains the recipe and files, `go vet ./...` and `go build ./...` ignore
`scripts/`, and the template acceptance tests (static) pass.

## t7 — web-nextjs standard Playwright scaffold and browser smoke recipe

**Files:** templates/web-nextjs/copier.yml, templates/web-nextjs/devbox.json.jinja, templates/web-nextjs/package.json.jinja, templates/web-nextjs/playwright.config.ts.jinja, templates/web-nextjs/e2e/smoke.spec.ts.jinja, templates/web-nextjs/e2e/home.spec.ts.jinja, templates/web-nextjs/scripts/smoke.sh, templates/web-nextjs/scripts/smoke-summary.mjs, templates/web-nextjs/CLAUDE.md.jinja, templates/web-nextjs/app/page.tsx.jinja, templates/web-nextjs/tests/page.test.tsx.jinja, templates/web-nextjs/docs/adr/000-bootstrap.md.jinja
**Covers:** AC-091.2, AC-091.3, AC-091.4, AC-091.16
**Goal:** every web-nextjs repo has the Playwright scaffold. Its smoke tests are `@smoke` Playwright tests run by
`devbox run smoke`.

**Implementation notes:**
- `copier.yml`:
  - remove the two `needs_e2e` `_exclude` lines
  - keep `needs_e2e` as a hidden question (`when: false`, help: "ignored since spec 091: the Playwright scaffold is
    standard"), so old answers files and `--data needs_e2e=…` still work
  - update the header comment
- Remove every `{% if needs_e2e %}` from `package.json.jinja`, `devbox.json.jinja`, `CLAUDE.md.jinja`,
  `app/page.tsx.jinja` and `000-bootstrap.md.jinja`: the e2e parts are always on. Adjust `tests/page.test.tsx.jinja`
  only if it asserts the changed page text.
- `playwright.config.ts.jinja`: `baseURL` from `SMOKE_BASE_URL`, falling back to localhost. `webServer` only without
  `SMOKE_BASE_URL`.
- `e2e/home.spec.ts.jinja`: the former contents of `smoke.spec.ts.jinja`. `e2e/smoke.spec.ts.jinja`: one `@smoke`
  root-page test with `test.skip(!process.env.SMOKE_BASE_URL, …)`.
- `scripts/smoke.sh`:
  - the guard
  - `pnpm exec playwright install chromium`
  - `PLAYWRIGHT_JSON_OUTPUT_NAME=<mktemp> pnpm exec playwright test --grep @smoke --pass-with-no-tests --reporter=list,json`
  - `node scripts/smoke-summary.mjs <json> <exit>`
- `scripts/smoke-summary.mjs` (no deps, ESLint-clean): walks `suites[].specs[].tests[].results`, prints
  `PASS|FAIL|SKIP  e2e/<file>::<title>` and the summary, or `0 smoke tests`.
- `devbox.json.jinja`:
  - `"smoke": "bash scripts/smoke.sh"`
  - `"e2e": "pnpm exec playwright install chromium && SMOKE_BASE_URL= pnpm exec playwright test"`
  - `test` / `test-fast` prefixed `SMOKE_BASE_URL= `
  - `ci` downloads no browser

**Done when:** a default render (no `needs_e2e`) has `e2e/`, `playwright.config.ts`, `@playwright/test` and the
recipes, and so does a render with `needs_e2e=false`. vitest still only includes `tests/**`. The template acceptance
tests (static) pass.

## t8 — update-service adds Playwright to web repos that opted out

**Files:** scripts/cplat/update.py
**Covers:** AC-091.2, AC-091.16
**Goal:** a web-nextjs repo generated with `needs_e2e=false` gets a working scaffold from `/shared:update-service`
(design.md "Updated repos").

**Implementation notes:**
- In `_finish`, before the `changed` listing, when `req["shape"] == "web-nextjs"`, call
  `ensure_playwright(repo, template_pkg)`. `template_pkg` is the template's rendered `package.json.jinja` version of
  `@playwright/test`, read with a regex.
  - If neither `dependencies` nor `devDependencies` has `@playwright/test`, add it to `devDependencies`. Use
    `json.loads`, then `json.dumps(indent=2)` plus a trailing newline, keeping the key order.
  - Add `"e2e": "playwright test"` to `scripts` when it is missing.
  - `r.did` gets `added @playwright/test to package.json (spec 091: browser smoke tests)`.
- Then `run(["devbox", "run", "--", "pnpm", "install", "--lockfile-only"], check=False, timeout=600)`. On failure,
  or when devbox is missing (`PlatformError`), add the next step
  `refresh the lockfile: devbox run -- pnpm install, then commit pnpm-lock.yaml`. The seam is `update.run`, so tests
  replace it.
- `package.json` stays out of `lost`/`modified` noise: it is an addition, not a replaced customisation.
- `drop_new_project_owned_files` keeps dropping a new `e2e/smoke.spec.ts` in an existing repo. That is correct: an
  updated repo prints `0 smoke tests` until it has its own.

**Done when:** the AC-091.16 / AC-091.2 update tests pass. Updating a repo rendered with `needs_e2e=false` adds
`playwright.config.ts`, the `smoke` recipe, `scripts/smoke.sh` and `@playwright/test`. A repo that already has the
dependency is left byte-identical in `package.json`. `test_update*.py` stays green.

## t9 — tester agents and spec format write smoke tests for (smoke) criteria

**Files:** plugins/svc/agents/tester.md, plugins/svc-java/agents/tester.md, plugins/svc-go/agents/tester.md, plugins/web/agents/tester.md, plugins/svc/skills/spec-format/references/spec.md, plugins/svc/skills/spec-format/references/testing.md, plugins/svc/commands/build.md
**Covers:** AC-091.1, AC-091.5
**Goal:** spec authors know the marker, and the testers write, for each `(smoke)` criterion, a smoke-tagged test that
uses only the base URL and is repeatable against a shared environment.

**Implementation notes:**
- `spec.md` reference: the `(smoke)` marker. It goes at the end of the criterion's bullet line, only for behaviour
  observable through the service's public URL, and only for deployable shapes.
- `testing.md`: the per-shape smoke test pattern of design.md (tag, base URL helper, skip rule). The rules: reach the
  service only through the base URL; create your own data with unique names (`smoke-<uuid>`); never change or delete
  data you did not create; one smoke test per criterion in its own clearly named test, in a file that names the id.
- Each tester agent: a short "Smoke criteria" section with its shape's exact pattern (python: `@pytest.mark.smoke` +
  `smoke_base_url`; java: `@Tag("smoke")` + `@EnabledIfEnvironmentVariable`; go: `TestSmoke…` + `t.Skip`; web:
  Playwright in `e2e/` with `@smoke` + `test.skip`). Remove the web tester's `needs_e2e` opt-in wording.
- `build.md` Phase 1: for `(smoke)` criteria, tell the tester to write the smoke test as well. `cplat spec trace` must
  not print `smoke: no smoke-tagged test` before coding starts.
- Agent descriptions stay at most 260 characters (`shapes.py check_front_matter`).

**Done when:** `uv run scripts/shapes.py check` and the Markdown link check pass, and each tester agent names its
shape's smoke tag exactly as `shapes.yml` matches it.

## t10 — ship command, docs and the gitops-app urls key

**Files:** plugins/svc/commands/ship.md, docs/CHANGELOG.md, docs/unattended-delivery.md, templates/gitops-app/applications/{{ app_name }}/app.yaml.jinja, templates/gitops-app/scripts/render.py
**Covers:** AC-091.6, AC-091.9, AC-091.11, AC-091.12, AC-091.15
**Goal:** the orchestrator knows that deploy ends with smoke and escalates red smoke itself. The final report has the
`Smoke (dev)` row. Users learn how the dev URL is found.

**Implementation notes:**
- `ship.md` Phase deploy:
  - after health, deploy runs `devbox run smoke` against the dev URL (pass `--base-url` only when the user named one)
  - red smoke → deploy has already escalated (cause `code`) and filed the issue: report its lines and stop. Never call
    `cplat ship escalate` for it.
  - resume reruns smoke only
- `ship.md` Finish: add the row `| Smoke (dev) | <the `Smoke (dev):` value from deploy> |`. When smoke did not run,
  list the unchecked `(smoke)` criteria. Replace "Next: check the feature in dev" with: "Next: promote with
  /gitops:promote …" when smoke passed, or "Next: check the unchecked criteria in dev by hand; …" when it did not run.
- `docs/unattended-delivery.md`: a "Smoke in dev" section after the auto-filed issues section, covering:
  - the marker
  - the recipe and `SMOKE_BASE_URL`
  - the retry and the limit
  - the not-run reasons
  - the issue in the service repo
  - the record section
  - `cplat smoke run`
  - the dev URL resolution (`expose`, `hosts.dev`, `urls.dev`, `LOCAL_HTTP_PORT`)
- `docs/CHANGELOG.md` `[Unreleased]`: one bullet, **Feature (091): ship checks the spec in dev with smoke tests**. It
  names:
  - `(smoke)`
  - `devbox run smoke` in every deployable template
  - the standard Playwright scaffold (web)
  - `cplat smoke run`
  - the deploy behaviour (retry, 600 s, escalation `code`, `smoke-failure` issue, resume)
  - the record section
  - ADR-036
  - migration: run `/shared:update-service`, then `cplat triage setup-labels` if `smoke-failure` is missing
- `app.yaml.jinja`: a commented `urls:` block explaining `{host}`. `render.py` docstring: `urls:` is read by
  `cplat smoke`, not by render. Check that render ignores unknown `app.yaml` keys; if it validates keys, allow `urls`.

**Done when:** `devbox run validate`, the Markdown link check and the gitops-app render check pass, and ship.md's
report template has the `Smoke (dev)` row.

## t11 — smoke is a required deploy recipe; platform CI runs each template's smoke against its started image

**Files:** scripts/shapes.py, .github/workflows/ci.yml
**Covers:** AC-091.2, AC-091.3, AC-091.4, AC-091.16
**Goal:** the registry check keeps every deployable template's `smoke` recipe in place. The platform CI runs the real
runner of each shape against a running instance, which `tests/cplat` cannot do.

**Implementation notes:**
- `shapes.py`: `DEPLOY_RECIPES` gains `"smoke"`. Deployable non-gitops templates must ship `scripts/smoke.sh`.
- `ci.yml`, in each template job (these are platform jobs, not template files, so no Jinja escaping):
  - **service-python:** after the existing steps:
    - `bash scripts/smoke.sh` with no URL → exit 2 and the message names `SMOKE_BASE_URL`
    - start `uv run uvicorn test_svc.main:app --port 18080 &`, wait for `/health`, then
      `SMOKE_BASE_URL=http://127.0.0.1:18080 bash scripts/smoke.sh` → `smoke: 1 passed, 0 failed, 0 skipped`
    - `uv run pytest` shows the example skipped
  - **service-go and service-java:** in the "image builds and starts" step, after health, run
    `SMOKE_BASE_URL=http://localhost:8080 bash scripts/smoke.sh` and grep the summary line. The step's `exit 0` must
    move after it.
  - **web-nextjs:**
    - flip `test ! -e /tmp/test-web/e2e` to `test -f /tmp/test-web/e2e/smoke.spec.ts` and `test -f
      playwright.config.ts`
    - after the container is up, run `SMOKE_BASE_URL=http://localhost:3000 bash scripts/smoke.sh` (it installs
      Chromium)
    - the variant job drops `needs_e2e=true` and keeps its other assertions
- Keep the jobs' `if:` filters and pinned actions unchanged (`scripts/pin-actions.py --check`).

**Done when:** `uv run scripts/shapes.py check` passes with the templates of t4–t7, `python3 scripts/pin-actions.py
--check` passes, and the template jobs are green on the PR.
