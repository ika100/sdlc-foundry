# svc-dotnet plugin

Agents for **.NET service repos** — the `service-dotnet` shape (ASP.NET Core minimal APIs on .NET, [ADR-127](../../docs/adr/127-service-dotnet-stack.md)). Used by the `/component:*` orchestrators, which route to `svc-dotnet:<role>` when the detected shape is `service-dotnet`. Pair with `svc` (product-manager, architect, reviewer), `shared` (quality/security) and the `service-dotnet` Copier template.

## Agents

| Agent | Model | Purpose |
|---|---|---|
| `coder` | sonnet | C# with nullable on, minimal API routes with input checks, `[LoggerMessage]` logging, EF Core migrations, following the architect's plan |
| `tester` | sonnet | xUnit v3 through `WebApplicationFactory` (`TestApp.Create()`), Testcontainers for PostgreSQL, smoke tests of category `smoke`, coverage |
| `deployment` | sonnet | chiseled ASP.NET Core Dockerfile, GHCR CI (image only) |
| `observability` | sonnet | prometheus-net metrics, OpenTelemetry .NET SDK, trace ids in the JSON log lines |
| `release` | sonnet | CHANGELOG in a PR after the tag (no version file: the image tag is the version) |

## Dependencies

1. `svc` and `shared` plugins enabled (the template's `.claude/settings.json` enables all three).
2. Project has a `devbox.json` with the canonical recipes (`install`, `dev`, `test`, `test-fast`, `lint`, `lint-fix`, `typecheck`, `quality`, `audit`, `security`, `smoke`, `image-build`, `image-scan`). Bootstrap with `/component:new <name> <description> --type service --lang csharp`.

All agents invoke `devbox run <recipe>` — never `dotnet` directly.
