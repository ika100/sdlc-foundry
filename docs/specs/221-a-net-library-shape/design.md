# Design — 221 A .NET library shape

The tooling is the `service-dotnet` template's ([ADR-127](../../adr/127-service-dotnet-stack.md)); publishing follows
[ADR-125](../../adr/125-library-releases-publish-to-github-on-the-tag.md) with the registry `github-nuget`; the layout of
the shape mirrors `library-java` (spec 217) and `library-typescript` (spec 215). No new ADR: every decision below applies
one of these.

## Decisions

- **The service template minus the service.** `templates/library-dotnet` renders only `*.jinja` files and keeps the
  service's SDK pin (`dotnet_major`, `dotnet_sdk_version`, `global.json`), `Directory.Build.props` (warnings as errors,
  analyzers, lock files, NuGet audit as a finding), central package management, `.editorconfig`, xUnit v3 + coverlet with
  the 80 % line gate, the trivy `audit` over the lock files, detect-secrets, `gate.sh` and `deps.sh` (synced copies of the
  service's, `sync-template-copies.py`) and the `specs` workflow. It drops ASP.NET Core, the observability and database
  switches, the Dockerfile, the smoke runner and every image, `dev` and `start` recipe and CI job. One sample class
  (`Greetings.Greet`) and its test keep the coverage gate meaningful. `InvariantGlobalization` stays out: a library must not
  decide its consumer's globalization.
- **The package.** `src/<Namespace>/<Namespace>.csproj` (`Microsoft.NET.Sdk`) with `IsPackable`, `PackageId` = the
  namespace, `Version` `0.0.0-dev`, `Description`, `Authors`, `RepositoryUrl`/`PackageProjectUrl` on the GitHub repo,
  `PackageReadmeFile` = the repo's `README.md` (packed), and `PackageLicenseExpression` left to the owner. The test project
  sets `IsPackable` false. The solution (`.slnx`) holds both.
- **The tag is the version (A3).** `comprelease.next_dev` returns `None` for a shape it does not list, so
  `/component:release` writes only the CHANGELOG; the `svc-dotnet` release agent skips the version file when it is `none`.
  `publish.sh` reads the project's `Version` and `PackageId` with `dotnet msbuild -getProperty`, decides the version the
  commit builds (the tag's when `HEAD` is the tagged commit and `git status --porcelain` is empty, otherwise the project's)
  and fails with the ADR-125 message before any build when it is not the tag's. It then runs `dotnet pack -c Release
  --no-restore -p:Version=X.Y.Z -o <tmp>` (the project file is never edited) after a locked restore, and checks that
  `<PackageId>.X.Y.Z.nupkg` was written. Tests are skipped (A6).
- **Upload.** The registry is `https://nuget.pkg.github.com/<owner>/index.json`, `<owner>` from `GITHUB_REPOSITORY_OWNER`
  (CI) or the template's `github_org`. A temporary directory holds a `nuget.config` with the source `github` and its
  credentials (`GITHUB_ACTOR` or `x-access-token`, `GH_TOKEN`), removed by a trap; `dotnet nuget push --source github
  --api-key "$GH_TOKEN" --skip-duplicate` runs from that directory, so the token is never written to the repo. An output
  naming a conflict or an existing version means a rerun of the same tag, and the script exits 0 saying so (A5).
- **Dry run.** `--dry-run` checks and packs, then prints `publish: would publish <nupkg> as <PackageId> X.Y.Z to <registry>`
  without a token or a registry call.
- **CI.** The template workflow is `library-java`'s with the `service-dotnet` job names (`quality (dotnet format +
  analyzers)`, `test (xunit + coverage)`, `security (trivy + detect-secrets)`, `ci-extra`), each running `devbox run
  install` first, and the ADR-125 `publish` job (`fetch-depth: 0`, `packages: write` only there, `GH_TOKEN` from
  `GITHUB_TOKEN`).
- **Detection (A7).** `detect-shape.sh` keeps the answers-file rule and adds: a `.sln`, `.slnx`, `.csproj` at the root or a
  `.csproj` one level down without a `Dockerfile` is `library-dotnet` (with one it stays `service-dotnet`).
- **Shape-wide lists.** Every list that names `service-dotnet` for the build (test-fast globs and the class filter in
  `buildtests`, `deps_parse` tool and lock files, the template lint step, the gates130 stub `dotnet`) and every list that
  names the other libraries (`newsvc` pairs, gitops-app valid pairs and plan shapes, the template allowlist count, the
  template pin bump, dependabot, the render loop of `ci-local.sh`) gains `library-dotnet`.
- **Platform CI.** A `smoke-test-library-dotnet` job renders the template, checks the detection, runs `devbox run ci`,
  tags the commit with `git update-ref` and runs `publish --dry-run`, then checks the version failure for a tag on another
  commit; the change filter, the actionlint render list and `ci-success` include it. A `smoke-dotnet-lib` devbox script
  does the same locally.
