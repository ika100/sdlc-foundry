# svc-ts plugin

Agents for **TypeScript service repos** — the `service-typescript` shape (Fastify on Node, [ADR-124](../../docs/adr/124-service-typescript-stack.md)). Used by the `/component:*` orchestrators, which route to `svc-ts:<role>` when the detected shape is `service-typescript`. Pair with `svc` (product-manager, architect, reviewer), `shared` (quality/security) and the `service-typescript` Copier template. Next.js websites use the `web` plugin instead.

## Agents

| Agent | Model | Purpose |
|---|---|---|
| `coder` | sonnet | Strict TypeScript, Fastify routes with JSON schemas, pino logging, Drizzle migrations, following the architect's plan |
| `tester` | sonnet | Vitest through `app.inject`, Testcontainers for PostgreSQL, `@smoke` tests in `tests/smoke/`, coverage |
| `deployment` | sonnet | distroless Node Dockerfile (production dependencies only), GHCR CI (image only) |
| `observability` | sonnet | prom-client metrics, OpenTelemetry Node SDK, pino trace ids |
| `release` | sonnet | CHANGELOG + next development version in `package.json`, in a PR after the tag |

## Dependencies

1. `svc` and `shared` plugins enabled (the template's `.claude/settings.json` enables all three).
2. Project has a `devbox.json` with the canonical recipes (`dev`, `test`, `test-fast`, `lint`, `lint-fix`, `typecheck`, `quality`, `audit`, `security`, `smoke`, `image-build`, `image-scan`). Bootstrap with `/component:new <name> <description> --type service --lang typescript`.

All agents invoke `devbox run <recipe>` — never `pnpm`/`node`/`vitest` directly.
