# svc-java plugin

Agents for **Java service and library repos** — the `service-java` shape (Spring Boot 4.x, JDK 21, Maven) and the `library-java` shape (a plain Maven jar published to GitHub Packages on the release tag, [ADR-125](../../docs/adr/125-library-releases-publish-to-github-on-the-tag.md)). Used by the `/svc:*` orchestrators (which route to `svc-java:<role>` when the detected shape is `service-java` or `library-java`). Pair with `svc` (orchestrators, product-manager, architect), `shared` (quality/security) and the `service-java` or `library-java` Copier template. A library uses `coder`, `tester` and `release` only.

## Agents

| Agent | Model | Purpose |
|---|---|---|
| `coder` | sonnet | Spring Boot 4 / Java 21 implementation following the architect's plan |
| `tester` | sonnet | JUnit 5 + Spring Boot Test, Testcontainers, JaCoCo 80% gate |
| `deployment` | sonnet | Distroless Java Dockerfile, GHCR CI (image only) |
| `observability` | sonnet | Actuator + Micrometer Prometheus + OTel Java agent, alerts |
| `release` | sonnet | Next development version of `pom.xml` (`versions:set`; a library: none, the tag is its version), CHANGELOG, release branch + PR |

## Dependencies

1. `svc` and `shared` plugins enabled (the template's `.claude/settings.json` enables all three).
2. Project has a `devbox.json` with the canonical recipes (`dev`, `test`, `test-fast`, `lint`, `lint-fix`, `typecheck`, `quality`, `audit`, `security`, `image-build`, `image-scan`). Bootstrap with `/component:new <name> <description> --lang java` (a library: `--type library --lang java`, without the image recipes).

All agents invoke `devbox run <recipe>` — never `mvn`/`java` directly.
