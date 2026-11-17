# ADR-009: `service-java` stack defaults

**Status:** Accepted
**Date:** 2026-05-22

## Context

The `service-java` shape is one of two case studies validating the §4.1 add-a-shape contract from the platform vision PRD. It needs concrete defaults across four axes — build tool, container image, observability, and code style — so the Copier template and the `svc-java` plugin's agents are unambiguous. These decisions cluster into one ADR rather than four because they together define the shape's identity.

## Decision

The `service-java` template ships with:

| Axis | Choice |
|---|---|
| Language / runtime | JDK 21 LTS (pinned per [ADR-005](005-node-version-policy.md)-style policy) |
| Framework | Spring Boot 3.x |
| Build tool | **Maven** |
| Container image base | **`gcr.io/distroless/java21-debian12:nonroot`** |
| Observability | **Spring Boot Actuator + Micrometer (Prometheus registry) + OpenTelemetry Java agent (`-javaagent`)** |
| Code style | **Spotless + google-java-format**, with a minimal Checkstyle config for what the formatter doesn't enforce |

### Build tool — Maven (chosen over Gradle)

- Maven's POM is declarative XML — easier for the `coder` agent to read, parse, and edit safely than a Kotlin/Groovy build script.
- Spring Boot has first-class Maven support; `spring-boot-maven-plugin` covers run, repackage, and image build.
- Lower cognitive load for human contributors who haven't worked with Gradle Kotlin DSL.
- Trade-off accepted: slower full builds than Gradle for large projects, more verbose POMs. For service-shaped repos (one module, modest dependency count) the gap is negligible.

### Container image — Distroless JRE 21

- ~250MB image; no shell; non-root by default.
- Matches the `service-go` `distroless/static-nonroot` choice — uniform security posture across backend shapes.
- GraalVM native image rejected as default: longer build times, reflection requires explicit config (Spring AOT helps but still friction), harder debugging. May become an opt-in mode later for cold-start-sensitive services.

### Observability — Actuator + Micrometer + OTel agent

- Actuator exposes `/actuator/health`, `/actuator/health/readiness`, `/actuator/info`, `/actuator/prometheus`.
- Micrometer's Prometheus registry feeds the `/actuator/prometheus` endpoint.
- OpenTelemetry Java agent (attached via `-javaagent` in the Dockerfile entrypoint) gives distributed tracing with zero code changes.
- Most idiomatic Spring Boot setup; new contributors find documentation instantly.

### Code style — Spotless + google-java-format

- `mvn spotless:apply` runs in `devbox run lint-fix`; `mvn spotless:check` runs in `devbox run lint` and CI.
- google-java-format is the most widely adopted Java style — agents trained on public code produce conformant output.
- Minimal Checkstyle config catches things the formatter doesn't (unused imports, naming, javadoc presence on public APIs).

## Devbox recipes (canonical)

The template ships `devbox.json` with at least:

| Recipe | Wraps |
|---|---|
| `test` | `mvn -B verify` |
| `test-fast` | `mvn -B test` |
| `lint` | `mvn -B spotless:check checkstyle:check` |
| `lint-fix` | `mvn -B spotless:apply` |
| `quality` | `lint` then `verify` |
| `audit` | `mvn -B org.owasp:dependency-check-maven:check` |
| `image-build` | `mvn -B spring-boot:build-image -Dspring-boot.build-image.imageName=<name>:scan` |
| `image-scan` | `trivy image --severity CRITICAL,HIGH <name>:scan` |
| `dev` | `mvn -B spring-boot:run` |
| `deploy` | `kubectl apply -k k8s/overlays/local/` |

## Consequences

- The `svc-java` plugin's `coder` agent generates Spring Boot 3.x code, edits POMs via clearly-bounded XML manipulation (or `maven` plugin commands), and always invokes `devbox run` — never raw `mvn`.
- The `tester` agent writes JUnit 5 + Spring Boot Test, uses Testcontainers when integration tests need real dependencies, and reads coverage from JaCoCo (configured in the POM).
- The `deployment` agent's Dockerfile is a multi-stage build: Maven build stage (`maven:3.9-eclipse-temurin-21`) → distroless runtime stage with the `-javaagent` line.
- Re-evaluate Maven vs Gradle if the platform ever needs multi-module composite builds or build-time AOT (GraalVM native) becomes a default goal.

## References

- [platform-vision.md §4, §11.8](../requirements/platform-vision.md)
- [ADR-008](008-shape-detection.md) — sniffing fallback uses `pom.xml` to detect this shape

## Amendment (implementation, phase 6)

Verified against a rendered project with real Maven/JDK runs; differences from the text above:

- **`image-build` uses `docker build`** (the template's multi-stage Dockerfile: Maven builder → distroless java21 with the `-javaagent`), not `spring-boot:build-image` — the "Consequences" section requires that Dockerfile, and it keeps every shape's `image-build` identical. Buildpacks are not used.
- **`quality` = `lint` + `typecheck`** (`mvn -DskipTests compile test-compile`); the test run, including the **JaCoCo 80% line gate** (`Application.class` excluded), is `devbox run test` (`mvn verify`), matching the other shapes where `quality` does not run tests.
- **Actuator probes** (`/actuator/health/liveness`, `/actuator/health/readiness`) replace `/health` + `/ready` for this shape; Kubernetes probes and the agents use them.
- The **OpenTelemetry agent is baked in but disabled** (`OTEL_SDK_DISABLED=true`) until an environment sets it to `false` and provides `OTEL_EXPORTER_OTLP_ENDPOINT`.
- `audit` (OWASP Dependency-Check) needs an `NVD_API_KEY` to be practical; CI reads it from a repository secret. This recipe was **not** executed during template verification (it downloads the full NVD database).

## Amendment (found by the todo-app end-to-end test)

- `devbox run audit` no longer fails when `NVD_API_KEY` is unset: an empty key made OWASP Dependency-Check abort with "Invalid API Key" in CI. With a key it runs Dependency-Check as before; without one it runs `trivy fs` (HIGH/CRITICAL, `--exit-code 1`). Accepted risks live in a project-owned `.trivyignore`.
- A fresh Spring Boot 3.5.16 project failed that audit on day one: Tomcat 10.1.55 and Jackson 2.21.4 (BOM-managed) have fixed releases, so `pom.xml` overrides `tomcat.version` (10.1.60) and `jackson-bom.version` (2.21.7); the Spring Framework 6.2 XsltView CVE-2026-47884 is fixed only in Spring 7 / Boot 4 and is listed in `.trivyignore` with its rationale. Remove overrides as the parent catches up; revisit the ignore when moving to Boot 4.

## Amendment (Spring Boot 4 and distroless debian13, spec 204)

**Date:** 2026-11-17. Supersedes the Framework and Container image base rows of the table above.

### Context

The platform's template image scan (spec 189) found four CRITICAL vulnerabilities in the service-java image: two in
spring-webmvc 6.2.x (CVE-2026-47884, CVE-2026-47890), fixed only in Spring Framework 7.0.9 and so only reachable through
Spring Boot 4; libbrotli1 (CVE-2026-111497) and zlib1g (CVE-2023-45853, "won't fix" in Debian 12) in the distroless debian12
base. Accepting them only postponed the scan failure.

### Decision

- **Framework: Spring Boot 4.x**, the newest GA patch whose BOM manages Spring Framework 7.0.9 or newer. The template uses the
  Boot 4 module starters (`spring-boot-starter-webmvc`, `-webmvc-test`, `-flyway`) and Testcontainers 2, and carries no
  version overrides the BOM already covers (the Tomcat 10.1 and Jackson 2 overrides are gone).
- **Container image base: `gcr.io/distroless/java<jdk>-debian13:nonroot`**: still distroless (no shell, `java` entrypoint,
  numeric user 65532), on the Debian release web-nextjs already uses (spec 189). If no distroless Java image on debian13 exists
  for a JDK, the base stays on the refreshed debian12 image and the zlib finding stays accepted; a base with a shell is not an
  option.
- The upgrade reaches new renders. `pom.xml` and `src/**` stay project-owned, so existing repos keep their Spring Boot 3
  build until they migrate by hand (steps in the release notes of spec 204); the runtime base reaches them through
  `/platform:update`, and the platform CI proves that a repo rendered at v5.23.3 still builds and runs on it.

### Consequences

- The `svc-java` agents write Spring Boot 4.x code: Jackson 3 (`tools.jackson`) is the default JSON stack, test slices come
  from the `*-test` starters.
- The service-java entries leave the accepted-finding list (`.github/image-scan-accepted.yml`); a new CRITICAL in the image
  fails the scan again instead of being accepted by default.
- A `java_version` answer without a distroless debian13 image fails the image build; the default (21) is covered.
