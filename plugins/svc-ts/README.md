# svc-ts plugin

Agents for **TypeScript service and library repos** — the `service-typescript` shape (Fastify on Node, [ADR-124](../../docs/adr/124-service-typescript-stack.md)) and the `library-typescript` shape (an ESM npm package published to GitHub Packages on the release tag, [ADR-125](../../docs/adr/125-library-releases-publish-to-github-on-the-tag.md)). Used by the `/component:*` orchestrators, which route to `svc-ts:<role>` when the detected shape is one of them. Pair with `svc` (product-manager, architect, reviewer), `shared` (quality/security) and the `service-typescript` or `library-typescript` Copier template. Next.js websites use the `web` plugin instead.

## Agents

| Agent | Model | Purpose |
|---|---|---|
| `coder` | sonnet | Strict TypeScript, Fastify routes with JSON schemas, pino logging, Drizzle migrations, following the architect's plan |
| `tester` | sonnet | Vitest through `app.inject`, Testcontainers for PostgreSQL, `@smoke` tests in `tests/smoke/`, coverage |
| `deployment` | sonnet | distroless Node Dockerfile (production dependencies only), GHCR CI (image only) |
| `observability` | sonnet | prom-client metrics, OpenTelemetry Node SDK, pino trace ids |
| `release` | sonnet | CHANGELOG + next development version in `package.json` (a library: CHANGELOG only, its version is the tag), in a PR after the tag |

## Dependencies

1. `svc` and `shared` plugins enabled (the template's `.claude/settings.json` enables all three).
2. Project has a `devbox.json` with the canonical recipes (`dev`, `test`, `test-fast`, `lint`, `lint-fix`, `typecheck`, `quality`, `audit`, `security`, `smoke`, `image-build`, `image-scan`). Bootstrap with `/component:new <name> <description> --type service --lang typescript` (a library: `--type library --lang typescript`; it has no `dev`, `smoke` or image recipes, and a `publish` recipe instead).

All agents invoke `devbox run <recipe>` — never `pnpm`/`node`/`vitest` directly.
