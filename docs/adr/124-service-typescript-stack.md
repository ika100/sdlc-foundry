# ADR-124: `service-typescript` stack defaults

**Status:** Accepted
**Date:** 2026-11-21

## Context

Spec 214 adds a backend service shape in TypeScript (#716), so that a team with a `web-nextjs` website can write its
backend in the same language. Like `service-go` ([ADR-010](010-service-go-stack.md)) the shape needs one default per
axis, so that the Copier template and the agents of the new `svc-ts` plugin are unambiguous. The choices of framework,
database layer and plugin were made with the user; the rest follow the platform's other shapes.

## Decision

| Axis | Choice |
|---|---|
| Runtime | Node, the pinned Active LTS major (`node_major`, [ADR-005](005-node-version-policy.md)); ESM, compiled with `tsc` to `dist/`, run with plain `node` |
| Package manager | pnpm, pinned in `devbox.json` and `packageManager` ([ADR-003](003-web-package-manager.md)) |
| HTTP framework | **Fastify 5** |
| Logging | **pino**, one JSON object per line on stdout, `trace_id` and `span_id` added by a mixin inside an active span |
| Metrics | **prom-client**: Node default metrics plus `http_requests_total` and `http_request_duration_seconds` (method, route, status) on `/metrics` |
| Tracing | OpenTelemetry Node SDK (HTTP and `@fastify/otel` instrumentations), loaded with `node --import ./dist/telemetry.js`, exporting over OTLP only when `OTEL_EXPORTER_OTLP_ENDPOINT` is set |
| Database (opt-in) | **Drizzle ORM** on `pg`; SQL migrations in `drizzle/` written by drizzle-kit and applied at startup by Drizzle's migrator; connection from the postgres resource contract (`PG*`, [ADR-057](057-named-typed-resources-with-fixed-contracts.md)) |
| Tests | Vitest with v8 coverage (80 % gate); Testcontainers PostgreSQL for the database; smoke tests are Vitest tests named `@smoke` run against `SMOKE_BASE_URL` |
| Lint / types | ESLint (`typescript-eslint` recommended, type-aware) and `tsc --noEmit`, strict |
| Image | multi-stage; runtime **`gcr.io/distroless/nodejs<major>-debian13`**, production dependencies only, `USER 65532:65532`, no shell |
| Agents | a new plugin **`svc-ts`** (coder, tester, deployment, observability, release); `web` stays Next.js-only |

### Why these

- **Fastify** over NestJS: a small, fast core with schema-based validation and first-party OpenTelemetry support; NestJS
  adds a DI framework and decorators the agents would have to learn and every repo would carry. Express is in
  maintenance mode; Hono targets edge runtimes, which spec 214 leaves out.
- **Drizzle** over Prisma and TypeORM: the schema is TypeScript, migrations are plain SQL files a reviewer can read, and
  there is no generated client or query engine binary in the image.
- **pino** is Fastify's own logger, so request logs and application logs are one stream in one format.
- **The OpenTelemetry Node SDK** instead of `@vercel/otel`: the latter targets Next.js; a plain Node service needs the
  SDK, preloaded before the app so that the instrumentations patch `http` and Fastify.
- **Smoke tests in Vitest** instead of Playwright: a backend has no pages, and Vitest is already the test runner.
- **Migrations at startup**, as Flyway runs in the Java service: one image, no separate Job to order before the rollout.
- **Distroless Node, UID 65532** like the Go and Java images: no shell, a numeric user Kubernetes can verify.

## Consequences

- The shape's tooling (pnpm, Vitest, ESLint, `tsc`, `gate.sh`, `deps.sh`) matches `web-nextjs`, so the failure summaries,
  the dependency recipes and the gates treat both alike; the TypeScript library shape (spec 215) reuses it.
- `--lang typescript` alone still creates a website; a service needs `--type service --lang typescript`.
- Fastify and Drizzle are defaults, not limits: a repo may add plugins or another data layer, recorded in its own ADR.
