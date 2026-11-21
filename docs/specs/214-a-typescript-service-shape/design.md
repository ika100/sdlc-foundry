# Design — 214 A TypeScript service shape

The stack decisions are [ADR-124](../../adr/124-service-typescript-stack.md); this page is how they land in the template,
the plugin and the platform.

## Decisions

- **One template, two switches.** `templates/service-typescript` renders only `*.jinja` files (GitHub's `${{ }}` stays
  literal). `needs_observability` (default on) adds `src/metrics.ts`, `src/telemetry.ts`, the OpenTelemetry and
  prom-client packages and the `--import ./dist/telemetry.js` of the image; `needs_database` (default off, as in Java)
  adds `src/db/`, `drizzle/`, `drizzle.config.ts`, `tests/db.test.ts`, the `db-up` and `migrate-new` recipes, and the
  `drizzle/` copy in the image. `_exclude` removes the files of a switch that is off, so a render never carries dead code.
- **`src/app.ts` builds, `src/server.ts` starts.** `buildApp({ logger, ready, metrics })` returns the Fastify instance
  without a socket, so tests use `app.inject` and the server only adds `listen`, signals and (with a database) the
  migrations. `/health` answers while the process runs; `/ready` asks `ready()` and answers 503 `{status: unavailable}`
  when it is false.
- **Migrations after listen (AC-214.8).** The server listens first, then runs Drizzle's migrator with up to 30 attempts
  2 s apart; `/ready` is false until they are applied and while `select 1` fails. Liveness therefore answers while the
  database starts (a migration before listen let the kubelet kill a pod that only waited), and a lost database turns
  readiness off instead of crashing: the pool has an `error` listener, because pg emits an error for an idle connection
  the server closed and an unhandled one ends the process.
- **Metrics per app.** `createMetrics()` makes its own registry, so tests can build several apps; the `onResponse` hook
  labels by `request.routeOptions.url` (the route pattern, `unmatched` for 404s), never the raw URL.
- **Logs.** pino with `messageKey: "msg"`, ISO `time`, the level as a word, no `pid`/`hostname`, and (with observability)
  a mixin that adds `trace_id`/`span_id` of the active span. The server passes it to Fastify as `loggerInstance`, so
  request logs and app logs are one format.
- **Smoke (AC-214.7).** `scripts/smoke.sh` runs `vitest run --config vitest.smoke.config.mts` (only `tests/smoke/`) with
  `--testNamePattern @smoke`, or `^(?!.*@writes).*@smoke` under `SMOKE_READ_ONLY=1`, and a JSON report that
  `scripts/smoke-summary.mjs` turns into the contract lines, listing only the tests the pattern selects (Vitest reports
  the filtered ones as skipped; they are not results). The example test is inside `describe.skipIf(!base)`, so the unit
  run (`SMOKE_BASE_URL=` in `test`) skips it.
- **Tooling shared with `web-nextjs`.** pnpm 11.22.0 (`packageManager` = devbox pin), `scripts/gate.sh` (byte copy of the
  gitops-app source, kept by `sync-template-copies.py`), `scripts/deps.sh` and `deps-override.mjs`, `spec-check.sh`, the
  CI workflow (job names `quality (eslint + tsc)`, `test (vitest + coverage)`, `security (pnpm audit + detect-secrets)`),
  and the detect-secrets baseline. `pnpm-workspace.yaml` allows esbuild's build script (tsx, drizzle-kit) and denies the
  optional ones of protobufjs, ssh2 and cpu-features, because pnpm 11 fails an install on an unreviewed build script.
- **Lint and types.** `tsconfig.json` (strict, NodeNext, `noEmit`, covers `src`, `tests` and the configs) is the type
  gate; `tsconfig.build.json` emits `src` to `dist`. ESLint is `typescript-eslint`'s type-checked recommended set.
- **Image (AC-214.5).** `deps` (install with the lock) → `builder` (`tsc`, then `pnpm prune --prod --ignore-scripts`) →
  `gcr.io/distroless/nodejs<major>-debian13` with `package.json`, `node_modules`, `dist` (and `drizzle/`), root-owned,
  `USER 65532:65532`, a `HEALTHCHECK` on `/health` through node's `fetch`.
- **Registry and routing.** The `shapes.yml` entry's `default_stack.language: typescript` and plugin `svc-ts` (not `web`)
  make the model's pair `service/typescript`; `newsvc.valid_pairs` orders it after `service/go`. `LANG_DEFAULT_TYPE`
  keeps `typescript → website`, so `--lang typescript` alone is unchanged. The gitops-app renderer's `VALID_PAIRS` and the
  plan checker's `SHAPES` (template copies, not the registry) get the pair and the id; `system_render.py` is resynced.
- **Detection.** `detect-shape.sh` maps the template path and sniffs `"fastify":` in `package.json` after the Next.js
  check, so a Next.js app that also lists Fastify stays a website.
- **The plugin.** `plugins/svc-ts` mirrors `svc-go`: five agents adapted from the `web` agents (the rules that carry over
  keep their register entries' wording and class), the SessionStart hook of `web` (install `node_modules` when missing),
  version 0.1.0, depending on `shared`. The prompts add about 24 kB, so the byte baseline is raised through
  `cplat platform rules rebaseline` after the two benchmarks, as the register requires.

## Contract

- `cplat component new <name> <description…> --type service --lang typescript` renders `templates/service-typescript`.
- `cplat shape` in such a repo: `shape: service-typescript`, `coder|tester|deployment|observability|release →
  svc-ts:<role>`, `product-manager|architect|reviewer → svc:<role>`.
- Template recipes: as in AC-214.3; `test`/`test-fast`: `SMOKE_BASE_URL= bash scripts/gate.sh tests <gate> vitest -- pnpm
  test|test:fast "$@"`.
- Runtime: port 8080, `/health`, `/ready`, `/metrics`, user 65532, env `PORT`, `LOG_LEVEL`, `OTEL_*`, and `PG*` with a
  database.
