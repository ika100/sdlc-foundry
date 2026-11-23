---
spec_id: 218-a-net-service-shape
title: A .NET service shape
status: done
priority: P1
shape: platform
tracks: [719]
---

# 218 — A .NET service shape

## Problem

A team that builds on .NET cannot use the platform for its backend (#719): the service shapes are Python, Java, Go and
TypeScript. .NET has a large enterprise audience, similar to Java's, and such a team today either switches language or
builds outside the platform, without its specs, gates, image pipeline and promotion. A .NET library shape (#720) waits
for this one, because it settles the .NET tooling and the agents.

## Stories

- As a developer, I want `/component:new <name> --type service --lang csharp` to create an ASP.NET Core service, so
  that my team builds its backend in the language it knows.
- As a developer, I want that service to carry the same guarantees as the other service shapes (recipes, gates, image,
  health, metrics, traces, logs, smoke tests, hardened CI), so that it can be added to a system and promoted like any
  other component.
- As a developer whose service stores data, I want PostgreSQL support with migrations and tests against a real
  database, so that `--uses postgres` works without wiring it by hand.
- As the platform owner, I want the agents for the shape in their own plugin, so that each plugin's agents know one
  toolchain.

## Acceptance criteria

- **AC-218.1** Given the shape registry, when it is read, then it holds a `service-dotnet` entry (plugin `svc-dotnet`,
  template `service-dotnet`, deployable, language `csharp`, runtime port 8080, probes `/health` and `/ready`, metrics
  `/metrics`, a numeric non-root user, test globs that find C# tests), `scripts/shapes.py check` passes, the (type,
  lang) pair `service/csharp` resolves to it, and `--lang csharp` alone means `service/csharp`.
- **AC-218.2** Given `cplat component new <name> <description> --type service --lang csharp`, when it runs, then it
  renders `templates/service-dotnet` into a repo whose `.copier-answers.yml` names that template, whose C# namespace is
  the PascalCase project name, and `scripts/detect-shape.sh` resolves the repo to `service-dotnet` both from the answers
  file and by sniffing a `*.csproj` or `*.slnx`/`*.sln` at the root or one level below together with a `Dockerfile`.
- **AC-218.3** Given a fresh render with the defaults, when `devbox run ci` runs, then quality (`dotnet format
  --verify-no-changes` and the build with the analyzers, warnings as errors), the tests (xUnit with an 80 % line coverage
  gate) and security (trivy over the lock files + detect-secrets) pass, and the template's `devbox.json` pins the .NET
  SDK and has the canonical recipes (`install`, `lint`, `lint-fix`, `typecheck`, `quality`, `test`, `test-fast`,
  `security`, `secrets-baseline`, `ci` ending in `ci-extra`, `smoke`, `image-build`, `image-scan`, `deps-findings`,
  `deps-bump`, `spec-check`), with `test` and `test-fast` going through `scripts/gate.sh` with a `dotnet` runner so that a
  run of 0 tests fails.
- **AC-218.4** Given the rendered service running, when it is called, then `/health` and `/ready` answer 200 with JSON,
  `/ready` answers 503 while a readiness check fails, `/metrics` answers Prometheus text holding the process metrics and
  an HTTP request counter and duration histogram labelled by method, route and status, every log line is one JSON object
  on stdout carrying `trace_id` and `span_id` inside an active span, and traces are exported over OTLP only when
  `OTEL_EXPORTER_OTLP_ENDPOINT` is set; with `needs_observability=false` the metrics endpoint and the OpenTelemetry and
  Prometheus packages are absent.
- **AC-218.5** Given the rendered Dockerfile, when the image is built and started with a read-only root filesystem,
  then it is a multi-stage build whose runtime stage is the chiseled ASP.NET Core image of the pinned major
  (`dotnet_major`, equal in the target framework, `devbox.json`, `global.json` and the Dockerfile), runs as a numeric
  non-root user, has no shell, and answers `/health` on port 8080.
- **AC-218.6** Given the rendered `.github/workflows/ci.yml`, when it is read, then it has the job set of the other
  service templates (`quality`, `test`, `security`, `ci-extra`, `pr-title`, `branch-name`, `docker`, `release-image`,
  `docker-publish`, `pin-dev` after `docker-publish`), every action pinned by commit SHA, least-privilege permissions,
  and the registry's `ci_checks` are job names in it.
- **AC-218.7** Given `devbox run smoke`, when it runs, then it exits 2 without `SMOKE_BASE_URL`; with it, it runs the
  tests of category `smoke` against the base URL and prints `PASS|FAIL|SKIP  <path>::<name>` lines (the path of the test
  file) and `smoke: <p> passed, <f> failed, <s> skipped`; with `SMOKE_READ_ONLY=1` tests that also carry category
  `writes` are not run; the template ships one read-only smoke test of `/health` that `devbox run test` skips without a
  base URL, and the registry's `smoke_tag` matches it.
- **AC-218.8** Given a render with `needs_database=true`, when it is built and tested, then it has EF Core with Npgsql,
  the `AppDbContext` in `Data/`, migrations in `Data/Migrations/` generated by `devbox run migrate-new` (dotnet-ef as a
  local tool) and applied at startup after the server listens, connection settings from the platform's postgres
  contract (`PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`), a readiness probe that answers 503 until the
  migrations are applied and while the database is unreachable, a `db-up` recipe, and an integration test against
  PostgreSQL in Testcontainers that `devbox run test` runs; without it none of these files or packages are present.
- **AC-218.9** Given the `svc-dotnet` plugin, when it is installed, then it has the agents `coder`, `tester`,
  `deployment`, `observability` and `release` with frontmatter (`name`, `description`, `tools`, `model`), a
  SessionStart devbox hook, a README, matching versions in its `plugin.json` and `marketplace.json`, the template's
  `.claude/settings.json` enables `svc-dotnet`, `svc` and `shared`, `cplat shape` in a rendered repo routes `coder` to
  `svc-dotnet:coder` and `architect` to `svc:architect`, and `cplat platform rules check` passes.
- **AC-218.10** Given the platform's shape-wide tooling, when it handles a `service-dotnet` repo, then it is covered like
  `service-typescript`: the repository CI smoke-tests the template (render, install, quality, test, the 0-tests gate,
  image build and start, the smoke runner, the database and observability variants) and actionlint checks its
  workflow; `gate.sh` stays a copy of the gitops-app source; dependency findings and bumps (`deps_parse` with trivy,
  `deps-bump` through `Directory.Packages.props`), failure summaries (`dotnet build` and `dotnet test`), the build-test
  globs, the template image scan, the template pin bump, the stage list and the system's creation order know the shape.
- **AC-218.11** Given the platform docs, when a reader looks for the shapes, then `docs/templates.md`, the site's shapes
  page, the PRD shape table, `CLAUDE.md`'s layout and `docs/AGENTS.md` name `service-dotnet` and `svc-dotnet`, and an
  ADR records the stack (minimal APIs, EF Core, prometheus-net, OpenTelemetry, xUnit, chiseled image).

## Non-goals

- A .NET library shape (#720), which reuses this shape's tooling.
- Legacy .NET Framework 4.x, Windows containers and IIS.
- Controllers/MVC, Razor or Blazor as template options; other ORMs (Dapper) as options.
- Microsoft.Testing.Platform as the test runner (xUnit runs on VSTest here).
- The consumer contract check of spec 110 for this shape (the Go, Java and TypeScript services do not have it either).
- Multi-project solutions beyond the service and its test project.

## Assumptions

- **A1** The language value is `csharp`, and `--lang csharp` alone means a service (other option: `dotnet`; affects
  AC-218.1, AC-218.2).
- **A2** .NET 10 LTS is the pinned major, the devbox SDK `dotnet-sdk_10` at an exact version (other option: .NET 11,
  which is not LTS; affects AC-218.3, AC-218.5).
- **A3** ASP.NET Core minimal APIs (other option: controllers; affects AC-218.4).
- **A4** EF Core with Npgsql for the database, migrations applied at startup after the server listens, as the TypeScript
  service does (other option: Dapper with a SQL migration tool; affects AC-218.8).
- **A5** The agents live in a new `svc-dotnet` plugin, version 0.1.0 (affects AC-218.9).
- **A6** `/metrics` comes from prometheus-net (other option: the OpenTelemetry Prometheus exporter, still a pre-release;
  affects AC-218.4).
- **A7** The dependency audit and findings use trivy over the `packages.lock.json` files, like `service-java` (other
  option: `dotnet list package --vulnerable`; affects AC-218.3, AC-218.10).
- **A8** xUnit v3 runs on VSTest (`xunit.v3.mtp-off`), so `--filter`, the TRX logger, the hang timeout and coverlet work
  as the gate and the smoke runner need (other option: Microsoft.Testing.Platform; affects AC-218.3, AC-218.7).
- **A9** The runtime image is `aspnet:<major>.0-noble-chiseled` running as UID 65532, the platform's non-root user (other
  option: the image's own `app` user 1654; affects AC-218.5).
- **A10** `needs_database` defaults to false and `needs_observability` to true, as in the other service shapes (affects
  AC-218.4, AC-218.8).

## Open questions

none

## Changelog

- 2026-11-22 created
- 2026-11-22 approved
- 2026-11-22 building
- 2026-11-22 done
