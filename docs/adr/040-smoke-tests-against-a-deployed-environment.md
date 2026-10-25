# ADR-040 — Smoke tests run against a deployed environment through one recipe and one output contract

**Status:** accepted (2026-10-24, spec 091)

## Context

`/svc:ship` ended when Argo CD reported dev healthy, which proves only that pods answer their probes. Specs 091 (dev),
093 (staging promotion) and 097 (app ship across repos) all need the same evidence: the spec's checkable behaviour
works in a running environment. That evidence must come out of four shapes with four test runners (pytest, JUnit,
`go test`, Playwright). Repos that were generated long ago must get it through `/shared:update-service`.

## Decision

- **Spec side:** a criterion whose bullet line ends with `(smoke)` is smoke-checkable. `cplat spec trace` requires a
  test file that names the id and carries the shape's smoke tag (`smoke_tag` regex in `shapes.yml`, searched in
  `smoke_globs`). The association is per file, not per test.
- **Repo side:** every deployable template has `devbox run smoke`, which runs the platform-owned `scripts/smoke.sh`.
  - It needs `SMOKE_BASE_URL`: without it, it exits 2 and runs nothing.
  - It runs only the smoke-tagged tests against that URL.
  - It prints `PASS|FAIL|SKIP  <path>::<name>` lines and one `smoke: <p> passed, <f> failed, <s> skipped` line (or
    `0 smoke tests`).
  - It exits 0 only when nothing failed.

  `test` and `ci` always run with an empty `SMOKE_BASE_URL`, and smoke tests skip themselves without one.
- **Platform side:** `scripts/cplat/smoke.py` is the only reader of that output. It owns the retry (once, after 30 s),
  the limit (600 s per attempt), the outcomes `passed | passed-on-retry | red | timed-out | not-run`, the run-record
  `smoke` section and the `smoke:` issue signature (kind of ADR-033, filed in the service repo). `not-run` never counts
  as passed.
- **Where the environment is:** the base URL comes from the linked gitops-app (`services.yaml` `expose:`,
  `app.yaml` `hosts.<env>` and the optional `urls.<env>`). An explicit `--base-url` overrides it. Before smoke runs,
  cplat checks that the URL answers at all. An unreachable URL is `not-run`, never red.
- **Red smoke in dev escalates as `code`** and is filed in the service repo. Nothing is rolled back.
- **Web smoke tests are Playwright tests**, and the Playwright scaffold is part of every web-nextjs repo.

## Consequences

- Specs 093 and 097 call `smoke.run_smoke()` / `cplat smoke run --base-url …` and reuse the record section and the
  signature unchanged.
- A new deployable shape must provide `smoke_tag`, a `smoke` recipe and a `scripts/smoke.sh` that prints the contract
  lines. `scripts/shapes.py check` enforces the recipe and the tag.
- The per-file association can be fooled by a smoke tag on another test in the same file. The tester agents write one
  smoke test per criterion in its own clearly named test.
- The first web smoke run on a machine downloads Chromium. `ci` stays browser-free.
- Smoke tests run against shared environments, so they must create their own uniquely named data and never touch data
  they did not create. This is a rule for the tester agents, not something the platform can check.
