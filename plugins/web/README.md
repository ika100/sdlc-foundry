# web plugin

Agents for **Next.js (App Router) web repos** — the `web-nextjs` shape. Used by the `/svc:*` orchestrators (which route to `web:<role>` when the detected shape is `web-nextjs`). Pair with `svc` (orchestrators, product-manager, architect), `shared` (quality/security) and the `web-nextjs` Copier template.

## Agents

| Agent | Model | Purpose |
|---|---|---|
| `coder` | sonnet | TypeScript / App Router implementation following the architect's plan |
| `tester` | sonnet | Vitest + Testing Library, Playwright when enabled, coverage gate |
| `deployment` | sonnet | Standalone-output Dockerfile, GHCR CI pipeline (image only) |
| `observability` | sonnet | `/api/metrics`, OpenTelemetry (`instrumentation.ts`), alerts |
| `release` | sonnet | Semver bump of `package.json`, CHANGELOG, release branch + PR |

## Hooks

- `SessionStart` runs `devbox run install` (`pnpm install --frozen-lockfile`) when `node_modules/` is missing.

## Dependencies

1. `svc` and `shared` plugins enabled (the web template's `.claude/settings.json` enables all three).
2. Project has a `devbox.json` with the canonical recipes (`install`, `dev`, `test`, `test-fast`, `lint`, `lint-fix`, `typecheck`, `quality`, `audit`, `security`, `image-build`, `image-scan`). Bootstrap with `/component:new <name> <description> --type website`.

All agents invoke `devbox run <recipe>` — never `pnpm`/`npx`/`node` directly.
