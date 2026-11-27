# ADR-127: `service-dotnet` stack defaults

**Status:** Accepted
**Date:** 2026-11-22

## Context

Spec 218 adds a backend service shape in C# on .NET (#719), so that a team on .NET can build its services on the
platform. Like `service-go` ([ADR-010](010-service-go-stack.md)) and `service-typescript`
([ADR-124](124-service-typescript-stack.md)) the shape needs one default per axis, so that the Copier template and the
agents of the new `svc-dotnet` plugin are unambiguous. The user asked for an unattended run; the choices below are the
defaults proposed with the issue, recorded as the spec's assumptions.

## Decision

| Axis | Choice |
|---|---|
| Runtime | .NET, the pinned LTS major (`dotnet_major`, today 10; [ADR-005](005-node-version-policy.md)'s one-pinned-LTS policy), SDK `dotnet-sdk_<major>` through devbox; target framework `net<major>.0` |
| Language value | `--lang csharp` (the language, like `python`, `java`, `go`, `typescript`; not the runtime) |
| HTTP | **ASP.NET Core minimal APIs** on Kestrel, port 8080; no controllers or MVC |
| Build settings | `Directory.Build.props`: nullable on, warnings are errors, `AnalysisLevel` latest-recommended, code style enforced in the build, invariant globalization; central package versions (`Directory.Packages.props`, transitive pinning) and `packages.lock.json` restored in locked mode |
| Logging | the console logger with a JSON-line formatter: `time`, `level`, `msg`, `logger`, the message-template fields, `trace_id` and `span_id` of the current `Activity` |
| Metrics | **prometheus-net**: .NET and process metrics plus `http_requests_total` and `http_request_duration_seconds` (method, route, status) on `/metrics` |
| Tracing | OpenTelemetry .NET SDK (ASP.NET Core and HttpClient instrumentation, Npgsql with a database), OTLP export only when `OTEL_EXPORTER_OTLP_ENDPOINT` is set |
| Probes | ASP.NET Core health checks: `/health` runs none, `/ready` runs the checks tagged `ready` |
| Database (opt-in) | **EF Core with Npgsql**; migrations by `dotnet ef` (a local tool) applied at startup after the server listens; connection from the postgres resource contract (`PG*`, [ADR-057](057-named-typed-resources-with-fixed-contracts.md)) |
| Tests | **xUnit v3** on VSTest (`xunit.v3.mtp-off`), `WebApplicationFactory` in memory, coverlet with an 80 % line gate, Testcontainers PostgreSQL; smoke tests are tests of category `smoke` run against `SMOKE_BASE_URL` |
| Quality | `dotnet format --verify-no-changes` and the build with the analyzers |
| Security | trivy over the lock files (HIGH or CRITICAL fail), detect-secrets, the image scan |
| Image | multi-stage, built on the build platform (framework-dependent output); runtime **`mcr.microsoft.com/dotnet/aspnet:<major>.0-noble-chiseled`**, `USER 65532:65532`, no shell, diagnostics IPC off for a read-only root filesystem |
| Agents | a new plugin **`svc-dotnet`** (coder, tester, deployment, observability, release) |

### Why these

- **Minimal APIs** over controllers: the smallest ASP.NET Core surface, the one Microsoft's templates lead with, and no
  MVC conventions for the agents to follow.
- **EF Core** over Dapper: migrations are generated from the model and versioned in the repo, as Flyway and drizzle-kit
  do in the other shapes; Npgsql is the PostgreSQL provider Microsoft documents.
- **prometheus-net** for `/metrics`: the OpenTelemetry Prometheus exporter for ASP.NET Core is still a pre-release;
  prometheus-net is stable and gives the same metric names as the other shapes.
- **trivy over the lock files** instead of `dotnet list package --vulnerable`: the same scanner and report format as
  `service-java`, so `cplat deps` reads both with one parser, and the lock files cover the transitive packages.
- **xUnit v3 on VSTest**: `dotnet test` keeps `--filter`, the TRX logger, `--blame-hang-timeout` and coverlet, which the
  gate, the smoke runner and the coverage gate use; Microsoft.Testing.Platform is a later switch.
- **Size (#1057)**: the image is about 133 MB unpacked on amd64 (141 MB on arm64), 60 MB to pull; the chiseled base image is about 125 MB of it.
  Trimming a self-contained publish cuts it to about 50 MB but reports over 100 trim warnings (EF Core, Npgsql, the
  shared framework's MVC parts), so it is not used. The CI smoke job fails a variant over 150,000,000 bytes.
- **Chiseled image, UID 65532**: no shell or package manager, like distroless; the platform's numeric non-root user of
  the Go, Java and TypeScript images instead of the image's own `app` user (1654).

## Consequences

- `gate.sh` gains a `dotnet` runner (TRX counters, `--blame-hang-timeout 120s` unless the repo sets one).
- `cplat deps` bumps a NuGet package by its `PackageVersion` in `Directory.Packages.props` (a transitive one gets an
  entry; central transitive pinning) and the lock files; the dependency files of the shape are found by glob.
- The defaults are not limits: a repo may add controllers, another data layer or Microsoft.Testing.Platform, recorded in
  its own ADR.
