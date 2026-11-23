# Design — 218 A .NET service shape

The stack decisions are [ADR-127](../../adr/127-service-dotnet-stack.md); this page is how they land in the template, the
plugin and the platform.

## Decisions

- **One template, two switches.** `templates/service-dotnet` renders only `*.jinja` files (GitHub's `${{ }}` stays
  literal). The C# namespace is the PascalCase project name (`namespace`, a computed Copier value: `orders-api` →
  `OrdersApi`), which also names `src/<Namespace>/`, `tests/<Namespace>.Tests/` and `<Namespace>.slnx`.
  `needs_observability` (default on) adds `HttpMetrics.cs`, `Telemetry.cs`, `MetricsTests.cs` and their packages;
  `needs_database` (default off, as in Java and TypeScript) adds `Data/`, `DatabaseTests.cs`, `.config/dotnet-tools.json`
  (dotnet-ef), the EF Core packages and the `db-up` and `migrate-new` recipes. `_exclude` removes the files of a switch
  that is off.
- **`ServiceApp.Build` builds, `Program.cs` runs.** `Program` is public, so the tests start the service in memory through
  `WebApplicationFactory<Program>` (`TestApp.Create()`), which also lets a test add or remove health checks.
- **Probes are health checks.** `/health` runs no check; `/ready` runs the checks tagged `ServiceApp.ReadyTag` and answers
  503 `{"status":"unavailable"}` when one is unhealthy. The health check service's own error log per failed probe is
  filtered out, because the probe answers every few seconds.
- **Migrations after listen (AC-218.8).** `DatabaseMigrator` is a `BackgroundService` that yields first, so the host
  starts Kestrel, then migrates with up to 30 attempts 2 s apart. The `migrations` check is unhealthy until they are
  applied and `AddDbContextCheck` while the database does not answer; a migration that fails for good sets exit code 1
  and stops the host. EF Core's connection error log is filtered out, because the migrator logs each retry. A
  design-time factory lets `dotnet ef` build the context without starting the service.
- **Logs.** The console logger with `JsonLineFormatter`: `time`, `level` (as a word), `msg`, `logger`, the template's
  fields, and `trace_id`/`span_id` of `Activity.Current`; relaxed JSON escaping so that `+` and quotes stay readable.
- **Metrics.** prometheus-net's default registry (process and .NET metrics) plus a middleware after `UseRouting` that
  labels `http_requests_total` and `http_request_duration_seconds` by method, the endpoint's route pattern
  (`unmatched` without one) and status.
- **Build settings.** `Directory.Build.props` (target framework, nullable, warnings as errors, analyzers
  latest-recommended, code style in the build, invariant globalization, lock files, NuGet audit as warnings),
  `Directory.Packages.props` (central versions, transitive pinning) and `.editorconfig` (style rules; underscores allowed
  in test names). `global.json` pins the SDK major with `latestFeature` roll-forward.
- **Tests and the gate.** xUnit v3 through `xunit.v3.mtp-off`, so `dotnet test` stays on VSTest. `gate.sh` gains a
  `dotnet` runner: it appends `--logger trx` and `--results-directory`, counts `passed + failed` of the TRX `Counters`,
  and adds `--blame-hang-timeout 120s --blame-hang-dump-type none` unless the command sets a hang option. `test`
  collects coverage with coverlet.msbuild (`Threshold=80`, line).
- **Smoke (AC-218.7).** `scripts/smoke.sh` runs `dotnet test --filter Category=smoke` (`Category=smoke&Category!=writes`
  under `SMOKE_READ_ONLY=1`) with a TRX logger; `scripts/smoke-summary.sh` (bash and awk, no runtime of its own) reads
  outcomes from `UnitTestResult` and classes from `TestMethod`, and finds the test file that declares the class, so the
  id is `<path>::<method>` as `cplat smoke` maps it to criteria. The example test calls `Assert.SkipWhen` without a base
  URL, so the unit run skips it.
- **Security.** `scripts/deps.sh`: `audit` and `findings` run trivy over the lock files (bin/ and obj/ skipped);
  `bump <package> <version>` sets or adds the `PackageVersion` and runs `dotnet restore --force-evaluate`, then checks
  that no lock file resolves the package below the version. `cplat deps` reads it with the trivy parser,
  `declared()` reads the `PackageVersion` ids, and `deps_parse.dep_files()` expands the shape's lock-file glob.
- **Image (AC-218.5).** The builder stage runs on `$BUILDPLATFORM` (framework-dependent output is portable): locked
  restore of the service project, then `dotnet publish`. The runtime is `aspnet:<major>.0-noble-chiseled` with the
  publish output, `ASPNETCORE_HTTP_PORTS` emptied (the service binds `PORT`), `DOTNET_EnableDiagnostics=0` for the
  read-only root and `USER 65532:65532`. No `HEALTHCHECK`: there is no shell or curl, the cluster probes the endpoints.
- **Registry and routing.** The `shapes.yml` entry's `default_stack.language: csharp` and plugin `svc-dotnet` make the
  pair `service/csharp`; `newsvc.LANG_DEFAULT_TYPE` maps a lone `csharp` to `service`. The gitops-app renderer's
  `VALID_PAIRS` and the plan checker's `SHAPES` get the pair and the id; `system_render.py` is resynced.
- **Detection.** `detect-shape.sh` maps the template path, and sniffs `*.sln`, `*.slnx`, `*.csproj` or `*/*.csproj` with
  a `Dockerfile` after the Go check; a project without a Dockerfile stays unresolved for a later library shape.
- **Platform tooling.** `buildtests` filters `dotnet test` by the classes of the selected test files
  (`FullyQualifiedName~.<Class>.`) and refuses `--load` like Java (shared `bin/`/`obj/`); `failsum` gains a `dotnet-test`
  and an `msbuild` parser; `template-lint.py` runs `dotnet format` and reads its diagnostics; `bump_template_pins.py`
  restores the render and moves each `PackageVersion` to its newest minor through `dotnet list package --outdated
  --highest-minor` (`scripts/dotnet_bump_minor.py`); `comprelease.next_dev` returns none (the image tag is the
  version).
- **The plugin.** `plugins/svc-dotnet` mirrors `svc-ts` (coder, tester, deployment, observability) and `svc-go`
  (release without a version file), with a SessionStart hook that restores the packages when `obj/` is missing. The
  prompts add about 25 kB, so the byte baseline is raised through `cplat platform rules rebaseline` after the two
  benchmarks.

## Contract

- `cplat component new <name> <description…> --type service --lang csharp` (or `--lang csharp`) renders
  `templates/service-dotnet`.
- `cplat shape` in such a repo: `shape: service-dotnet`, `coder|tester|deployment|observability|release →
  svc-dotnet:<role>`, `product-manager|architect|reviewer → svc:<role>`.
- Template recipes: as in AC-218.3; `test`/`test-fast`: `SMOKE_BASE_URL= bash scripts/gate.sh tests <gate> dotnet --
  dotnet test …`.
- Runtime: port 8080, `/health`, `/ready`, `/metrics`, user 65532, env `PORT`, `LOG_LEVEL`, `OTEL_*`, and `PG*` with a
  database.
