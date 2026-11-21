---
spec_id: 214-a-typescript-service-shape
shape: platform
spec_hash: 132f05643552
summary: "A service-typescript template (Fastify, pino, prom-client, OpenTelemetry, optional Drizzle/PostgreSQL), a svc-ts plugin, the registry entry and every shape-wide tool and CI job that names the shapes"
tasks:
  - id: t1
    title: "The service-typescript template and the stack ADR"
    files: [templates/service-typescript/, docs/adr/124-service-typescript-stack.md, docs/adr/README.md]
    covers: [AC-214.3, AC-214.4, AC-214.5, AC-214.6, AC-214.7, AC-214.8, AC-214.11]
    parallel_safe: false
    depends_on: []
    done: true
  - id: t2
    title: "The svc-ts plugin, its rule register files, the registry entry and detection"
    files: [plugins/svc-ts/, docs/rules/plugins/svc-ts/, .claude-plugin/marketplace.json, shapes.yml, scripts/detect-shape.sh, scripts/test-detect-shape.sh, docs/requirements/platform-vision.md, scripts/sync-template-copies.py]
    covers: [AC-214.1, AC-214.2, AC-214.9]
    parallel_safe: false
    depends_on: [t1]
    done: true
  - id: t3
    title: "Shape-wide tooling, the gitops-app pair, platform CI"
    files: [scripts/cplat/deps_parse.py, scripts/cplat/buildtests.py, scripts/cplat/comprelease.py, scripts/cplat/newapp.py, scripts/cplat/newsvc.py, scripts/cplat/stages.py, scripts/bump_template_pins.py, scripts/template-image-scan.py, scripts/template-lint.py, scripts/ci-local.sh, templates/gitops-app/scripts/render.py, templates/gitops-app/scripts/plan.py, templates/cluster-gitops/scripts/system_render.py, .github/workflows/ci.yml, .github/workflows/template-image-scan.yml, .github/image-scan-accepted.yml, .github/dependabot.yml, devbox.json, plugins/system/commands/new.md]
    covers: [AC-214.1, AC-214.10]
    parallel_safe: false
    depends_on: [t2]
    done: true
  - id: t4
    title: "Acceptance tests, shape tables of the existing tests, docs, versions and changelog"
    files: [tests/cplat/test_214_service_typescript.py, tests/cplat/, docs/templates.md, docs/AGENTS.md, docs/ADOPTING.md, docs/ARCHITECTURE.md, docs/USER-JOURNEY.md, CLAUDE.md, site/src/content/docs/concepts/shapes.md, plugins/svc/, plugins/component/, plugins/system/, docs/changelog.d/]
    covers: [AC-214.1, AC-214.2, AC-214.3, AC-214.4, AC-214.5, AC-214.6, AC-214.7, AC-214.8, AC-214.9, AC-214.10, AC-214.11]
    parallel_safe: false
    depends_on: [t3]
    done: true
---

# Plan — 214 A TypeScript service shape

The contract is [design.md](design.md). t1 builds and proves the template by rendering every variant, installing,
linting, type-checking, testing with coverage, building the image and running it (with and without PostgreSQL); t2 adds
the plugin and makes the registry and detection know the shape; t3 makes every tool that names shapes know it; t4 adds
the shape to the parametrized tests of the existing contracts (gates, smoke, CI, image, deps, stages) and writes the
acceptance tests of this spec.

## t1 — The template and the stack ADR

**Covers:** AC-214.3–AC-214.8, AC-214.11 · **Goal:** a render of each of the four variants passes `devbox run ci`, builds
an image that starts read-only and passes the smoke runner.

## t2 — Plugin, registry, detection

**Covers:** AC-214.1, AC-214.2, AC-214.9 · **Goal:** `shapes.py check`, `test-detect-shape.sh` and `cplat platform rules
check` pass; `cplat shape` routes to `svc-ts`.

## t3 — Shape-wide tooling and CI

**Covers:** AC-214.1, AC-214.10 · **Goal:** the tooling of AC-214.10 names the shape; the platform CI runs the four
template variants on a change of the template.

## t4 — Tests, docs, versions

**Covers:** every criterion · **Goal:** the full cplat suite passes with the shape in its tables.
