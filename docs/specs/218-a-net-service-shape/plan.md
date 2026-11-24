---
spec_id: 218-a-net-service-shape
shape: platform
spec_hash: 0c71de8723ce
summary: "A service-dotnet template (ASP.NET Core minimal APIs, JSON log lines, prometheus-net, OpenTelemetry, optional EF Core/PostgreSQL), a svc-dotnet plugin, a dotnet runner in gate.sh, the registry entry and every shape-wide tool and CI job that names the shapes"
tasks:
  - id: t1
    title: "The service-dotnet template, the gate.sh dotnet runner and the stack ADR"
    files: [templates/service-dotnet/, templates/gitops-app/scripts/gate.sh, scripts/sync-template-copies.py, docs/adr/127-service-dotnet-stack.md, docs/adr/README.md]
    covers: [AC-218.3, AC-218.4, AC-218.5, AC-218.6, AC-218.7, AC-218.8, AC-218.11]
    parallel_safe: false
    depends_on: []
    done: true
  - id: t2
    title: "The svc-dotnet plugin, its rule register files, the registry entry and detection"
    files: [plugins/svc-dotnet/, docs/rules/plugins/svc-dotnet/, docs/rules/register.yml, .claude-plugin/marketplace.json, shapes.yml, scripts/detect-shape.sh, scripts/test-detect-shape.sh, docs/requirements/platform-vision.md]
    covers: [AC-218.1, AC-218.2, AC-218.9]
    parallel_safe: false
    depends_on: [t1]
    done: true
  - id: t3
    title: "Shape-wide tooling, the gitops-app pair, platform CI"
    files: [scripts/cplat/deps_parse.py, scripts/cplat/deps.py, scripts/cplat/buildtests.py, scripts/cplat/failsum/, scripts/cplat/newapp.py, scripts/cplat/newsvc.py, scripts/cplat/stages.py, scripts/cplat/cplat.py, scripts/bump_template_pins.py, scripts/dotnet_bump_minor.py, scripts/template-image-scan.py, scripts/template-lint.py, scripts/ci-local.sh, templates/gitops-app/scripts/render.py, templates/gitops-app/scripts/plan.py, templates/cluster-gitops/scripts/system_render.py, .github/workflows/ci.yml, .github/image-scan-accepted.yml, .github/dependabot.yml, devbox.json, plugins/system/commands/new.md, plugins/component/commands/new.md]
    covers: [AC-218.1, AC-218.10]
    parallel_safe: false
    depends_on: [t2]
    done: true
  - id: t4
    title: "Acceptance tests, shape tables of the existing tests, docs, versions and changelog"
    files: [tests/cplat/test_218_service_dotnet.py, tests/cplat/, docs/templates.md, docs/AGENTS.md, docs/ADOPTING.md, docs/ARCHITECTURE.md, docs/USER-JOURNEY.md, CLAUDE.md, site/src/content/docs/concepts/shapes.md, plugins/svc/, plugins/component/, plugins/system/, docs/changelog.d/]
    covers: [AC-218.1, AC-218.2, AC-218.3, AC-218.4, AC-218.5, AC-218.6, AC-218.7, AC-218.8, AC-218.9, AC-218.10, AC-218.11]
    parallel_safe: false
    depends_on: [t3]
    done: true
---

# Plan — 218 A .NET service shape

The contract is [design.md](design.md). t1 builds and proves the template by rendering every variant, restoring, linting,
building with the analyzers, testing with coverage, auditing, building the image and running it read-only (with and
without PostgreSQL); t2 adds the plugin and makes the registry and detection know the shape; t3 makes every tool that
names shapes know it; t4 adds the shape to the parametrized tests of the existing contracts and writes the acceptance
tests of this spec.

## t1 — The template, the gate runner and the stack ADR

**Covers:** AC-218.3–AC-218.8, AC-218.11 · **Goal:** a render of each of the four variants passes install, lint,
typecheck, test (80 % lines), audit and secrets-scan, builds an image that starts read-only and passes the smoke runner.

## t2 — Plugin, registry, detection

**Covers:** AC-218.1, AC-218.2, AC-218.9 · **Goal:** `shapes.py check`, `test-detect-shape.sh` and `cplat platform rules
check` pass; `cplat shape` routes to `svc-dotnet`.

## t3 — Shape-wide tooling and CI

**Covers:** AC-218.1, AC-218.10 · **Goal:** the tooling of AC-218.10 names the shape; the platform CI runs the four
template variants on a change of the template.

## t4 — Tests, docs, versions

**Covers:** every criterion · **Goal:** the full cplat suite passes with the shape in its tables.
