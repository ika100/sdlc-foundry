# Design — 215 A TypeScript library shape

The tooling is the `service-typescript` template's ([ADR-124](../../adr/124-service-typescript-stack.md)); publishing follows
[ADR-125](../../adr/125-library-releases-publish-to-github-on-the-tag.md). This page is how the two meet in a library.

## Decisions

- **The service template minus the service.** `templates/library-typescript` renders only `*.jinja` files and keeps the
  service's pnpm pin, NodeNext ESM, `tsconfig.json` (type check) + `tsconfig.build.json` (build), ESLint, Vitest with the
  80 % gate, `gate.sh` (a synced copy), `deps.sh`, detect-secrets and the `specs` workflow. It drops Fastify, pino,
  OpenTelemetry, the database switch, the Dockerfile, the smoke runner and every image recipe and CI job. One sample module
  (`src/index.ts`, `greet`) and its test keep the coverage gate meaningful on a fresh render.
- **The package.** `@<github_org | lower>/<project_name>` (npm scopes are lowercase), `"type": "module"`, one `exports["."]`
  entry with `types` and `import`, `files: ["dist"]`, `repository` (GitHub Packages links the package to the repo by it) and
  `publishConfig.registry`. The build adds `declaration` and `declarationMap`. No CommonJS output.
- **The tag is the version (A2).** `package.json` holds `0.0.0-dev.0` and is never bumped: `comprelease.next_dev` returns
  `None` for the shape, so `/component:release` writes only the CHANGELOG, as for `library-python`. `publish.sh` first
  decides the version the commit builds: the tag's when `HEAD` is the tagged commit and `git status --porcelain` is empty,
  otherwise the `package.json` version, and fails with the ADR-125 message when it is not the tag's. It then builds, copies
  `package.json` aside, sets the version with `npm pkg set`, packs with `pnpm pack --pack-destination .pack`, restores
  `package.json` (a trap restores it on failure too), and reads the packed `package/package.json` back as a second check.
- **Upload.** A temporary npm user config holds `//npm.pkg.github.com/:_authToken=${NODE_AUTH_TOKEN}` and the scope's
  registry, so no `.npmrc` is written to the repo. `npm view <name>@<version>` first: a version already in the registry is
  a rerun of the same tag, and the script exits 0 saying so (A4); otherwise `npm publish <tarball>`.
- **Dry run.** Everything up to the upload, then one line `publish: would publish <tarball> as <name>@<version> to
  <registry>`; no network call and no token needed.
- **CI.** The library-python job set with the service-typescript job names: `quality`, `test`, `security`, `ci-extra`,
  `pr-title` and `publish` (`packages: write` next to `contents: read`, the only write permission; `fetch-depth: 0` so the
  tag is in the checkout; `devbox run install` before the recipe).
- **Detection.** A `package.json` with neither `next` nor `fastify` is a TypeScript library, but only after the Java, Go
  and Python manifests were checked, so a repo that keeps a `package.json` for tooling keeps its shape.
- **Agents.** The `svc-ts` plugin serves both shapes. Only the release agent changes: `VERSION_FILE`/`NEXT_DEV` may be
  `none`, and step 3 is skipped then (net fewer prompt bytes).

## Seams for the tests

`tests/cplat/test_215_library_typescript.py`: the registry, `shapes.publish_errors`, `newsvc`, `comprelease`, `deps_parse`,
`buildtests` in-process; a copier render (shared per process) for files, CI and the guide; the real `detect-shape.sh`; the
real `publish.sh` with real `node`, `git` and `tar` and fake `pnpm`/`npm` (`waiting.with_prelude`). The real toolchain
(install, ESLint, `tsc`, Vitest coverage, `pnpm pack`) runs in the platform CI job `smoke-test-library-typescript`.
