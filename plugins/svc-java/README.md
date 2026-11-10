# svc-java plugin

Agents for **Java service repos** — the `service-java` shape (Spring Boot 3.x, JDK 21, Maven). Used by the `/svc:*` orchestrators (which route to `svc-java:<role>` when the detected shape is `service-java`). Pair with `svc` (orchestrators, product-manager, architect), `shared` (quality/security) and the `service-java` Copier template.

## Agents

| Agent | Model | Purpose |
|---|---|---|
| `coder` | sonnet | Spring Boot 3 / Java 21 implementation following the architect's plan |
| `tester` | sonnet | JUnit 5 + Spring Boot Test, Testcontainers, JaCoCo 80% gate |
| `deployment` | sonnet | Distroless Java Dockerfile, GHCR CI (image only) |
| `observability` | sonnet | Actuator + Micrometer Prometheus + OTel Java agent, alerts |
| `release` | sonnet | Semver bump of `pom.xml` (`versions:set`), CHANGELOG, release branch + PR |

## Dependencies

1. `svc` and `shared` plugins enabled (the template's `.claude/settings.json` enables all three).
2. Project has a `devbox.json` with the canonical recipes (`dev`, `test`, `test-fast`, `lint`, `lint-fix`, `typecheck`, `quality`, `audit`, `security`, `image-build`, `image-scan`). Bootstrap with `/component:new <name> <description> --lang java`.

All agents invoke `devbox run <recipe>` — never `mvn`/`java` directly.
