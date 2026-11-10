# svc-go plugin

Agents for **Go service repos** — the `service-go` shape. Used by the `/svc:*` orchestrators (which route to `svc-go:<role>` when the detected shape is `service-go`). Pair with `svc` (orchestrators, product-manager, architect), `shared` (quality/security) and the `service-go` Copier template.

## Agents

| Agent | Model | Purpose |
|---|---|---|
| `coder` | sonnet | Idiomatic Go (chi, slog) following the architect's plan |
| `tester` | sonnet | stdlib `testing` + `httptest`, race detector, coverage |
| `deployment` | sonnet | distroless/static Dockerfile with ldflags version, GHCR CI (image only) |
| `observability` | sonnet | slog logging, Prometheus metrics, alerts |
| `release` | sonnet | CHANGELOG + release PR; the version is the git tag (no version file — ADR-012) |

## Dependencies

1. `svc` and `shared` plugins enabled (the template's `.claude/settings.json` enables all three).
2. Project has a `devbox.json` with the canonical recipes (`dev`, `test`, `test-fast`, `lint`, `lint-fix`, `typecheck`, `quality`, `audit`, `security`, `image-build`, `image-scan`). Bootstrap with `/component:new <name> <description> --lang go`.

All agents invoke `devbox run <recipe>` — never `go`/`golangci-lint` directly.
