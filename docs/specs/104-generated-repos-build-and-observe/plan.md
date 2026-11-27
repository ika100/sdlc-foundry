---
spec_id: 104-generated-repos-build-and-observe
shape: platform
spec_hash: 43389dad6c91
summary: Amendment (issue 965) - PACKAGES_READ_TOKEN as an env-mounted BuildKit secret in the web-nextjs and service-typescript image builds and CI, a cached marker build proving no token in the image, and a /platform:doctor row for the missing secret; AC-104.1 to .10 stay built by plan.v1
tasks:
  - id: t1
    title: web-nextjs - secret-mounted strict install, .npmrc in the deps stage, CI and image-build pass the token
    files: [templates/web-nextjs/Dockerfile.jinja, templates/web-nextjs/.github/workflows/ci.yml, templates/web-nextjs/devbox.json.jinja, templates/web-nextjs/CLAUDE.md.jinja]
    covers: [AC-104.2, AC-104.3, AC-104.11]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: service-typescript - secret-mounted strict install, .npmrc in the deps stage, CI and image-build pass the token
    files: [templates/service-typescript/Dockerfile.jinja, templates/service-typescript/.github/workflows/ci.yml, templates/service-typescript/devbox.json.jinja, templates/service-typescript/CLAUDE.md.jinja]
    covers: [AC-104.2, AC-104.3, AC-104.11]
    parallel_safe: true
    depends_on: []
  - id: t3
    title: doctor row for a missing PACKAGES_READ_TOKEN when .npmrc or pyproject.toml reads private packages
    files: [scripts/cplat/doctor_packages.py, scripts/cplat/doctor.py]
    covers: [AC-104.12]
    parallel_safe: true
    depends_on: []
  - id: t4
    title: Platform smoke jobs - service-typescript stale-lock step and the marker-secret build of both TypeScript images
    files: [.github/workflows/ci.yml]
    covers: [AC-104.1, AC-104.2, AC-104.4, AC-104.5, AC-104.6, AC-104.7, AC-104.8, AC-104.9, AC-104.10, AC-104.11]
    parallel_safe: true
    depends_on: []
  - id: t5
    title: ADR-125 point 5, the library-typescript consumer note and the changelog fragment
    files: [docs/adr/125-library-releases-publish-to-github-on-the-tag.md, templates/library-typescript/CLAUDE.md.jinja, docs/changelog.d/104-private-packages-in-image-builds.added.md]
    covers: [AC-104.11, AC-104.12]
    parallel_safe: true
    depends_on: []
---

# Plan — 104 Generated repos build and observe reliably (amendment, issue 965)

Design: [design.md](design.md), section "Amendment: private packages" and the contract. The first build (plan.v1.md,
t1–t4) made AC-104.1 to AC-104.10 true; this plan adds AC-104.11 and AC-104.12 and extends AC-104.2/AC-104.3 to
`service-typescript`. The built criteria are carried on t4, whose file (the platform CI) runs their checks: t4 must
keep every existing spec-104 step and the full `tests/cplat/test_generated_repos.py` and template
`tests/test_metrics.py` green. Red tests first (the testers extend `tests/cplat/test_generated_repos.py` and add the
doctor tests), then t1–t5 in parallel, one level.

## t1 — web-nextjs: secret-mounted strict install, .npmrc, CI and image-build pass the token

**Files:** templates/web-nextjs/Dockerfile.jinja, templates/web-nextjs/.github/workflows/ci.yml, templates/web-nextjs/devbox.json.jinja, templates/web-nextjs/CLAUDE.md.jinja
**Covers:** AC-104.2, AC-104.3, AC-104.11
**Goal:** a generated web-nextjs repo installs a private package of its owner in the image build when CI or the
developer passes `PACKAGES_READ_TOKEN` as a build secret, without the token in any layer, build argument or history,
and builds unchanged without it.

**Implementation notes:**
- Dockerfile line 1 `# syntax=docker/dockerfile:1.10`; deps stage exactly as in the design contract (`.npmrc*` in the
  COPY, `RUN --mount=type=secret,id=PACKAGES_READ_TOKEN,env=NODE_AUTH_TOKEN pnpm install --frozen-lockfile`).
- Runtime stage unchanged: no `.npmrc`, no token variable.
- `ci.yml` (copied verbatim, not Jinja): both build-push-action steps get the step `env` and `secret-envs` of the
  contract; each `devbox run install` step gets `NODE_AUTH_TOKEN: ${{ secrets.PACKAGES_READ_TOKEN }}`. No `secrets:`
  input, no workflow- or job-level token env.
- `devbox.json.jinja` `image-build`: add `--secret id=PACKAGES_READ_TOKEN,env=NODE_AUTH_TOKEN`; check by hand that
  `docker build` with `NODE_AUTH_TOKEN` unset still succeeds on the rendered repo.
- `CLAUDE.md.jinja`, section "Docker image pipeline": one or two sentences: a private `@<owner>` package needs the
  library's `.npmrc` lines and the repository secret `PACKAGES_READ_TOKEN`; CI passes it to the install and the image
  build, locally `export NODE_AUTH_TOKEN=$(gh auth token)` before `devbox run image-build`.

**Done when:** the AC-104.2, AC-104.3 and AC-104.11 tests of `tests/cplat/test_generated_repos.py` for web-nextjs pass,
and the web-nextjs smoke job's image still builds and starts.

## t2 — service-typescript: secret-mounted strict install, .npmrc, CI and image-build pass the token

**Files:** templates/service-typescript/Dockerfile.jinja, templates/service-typescript/.github/workflows/ci.yml, templates/service-typescript/devbox.json.jinja, templates/service-typescript/CLAUDE.md.jinja
**Covers:** AC-104.2, AC-104.3, AC-104.11
**Goal:** the same as t1 for service-typescript.

**Implementation notes:**
- Same Dockerfile, `ci.yml`, `devbox.json.jinja` and `CLAUDE.md.jinja` changes as t1 (the two `ci.yml` files are
  identical today; keep them identical).
- The `builder` stage is `FROM deps`, so `pnpm build && pnpm prune --prod --ignore-scripts` runs without the token;
  `pnpm prune` does not fetch, so it needs none. The runtime stage copies only `package.json`, `node_modules`, `dist`
  (and `drizzle`): no `.npmrc`.
- The Dockerfile stays out of `_skip_if_exists` (AC-104.3; already true, do not change `copier.yml`).

**Done when:** the AC-104.2, AC-104.3 and AC-104.11 tests of `tests/cplat/test_generated_repos.py` for
service-typescript pass, and the service-typescript smoke job's image still builds within its size budget.

## t3 — doctor row for a missing PACKAGES_READ_TOKEN

**Files:** scripts/cplat/doctor_packages.py, scripts/cplat/doctor.py
**Covers:** AC-104.12
**Goal:** `/platform:doctor` in a repo whose `.npmrc` points the owner's scope at `npm.pkg.github.com`, or whose
`pyproject.toml` reads release-asset wheels of a private repo, reports a missing `PACKAGES_READ_TOKEN` with the
command that sets it; any other repo gets no row.

**Implementation notes:**
- New module `doctor_packages.py` with `private_package_sources(repo, owner)` and `check_packages_token(repo)`,
  triggers, rows, details and fix exactly as in the design contract.
- Use `ship.service_slug`, `ship.secret_names` (repo and organization secrets) and `ship.gh` for
  `gh api repos/<o>/<r> --jq .private`; return `[]` when `gh` is not on PATH (like `check_gitops_token`).
- Build rows with `doctor.check` and the `OK`/`WARN`/`FAIL` constants; import them inside the function so
  `doctor.py` importing the module creates no cycle.
- `doctor.run_checks`: add `*doctor_packages.check_packages_token(repo)` right after `*check_gitops_token(repo)`.
- Read the Python trigger from the file text with one regex; no `tomllib` parse needed.

**Done when:** the AC-104.12 doctor tests pass (npm trigger, private and public Python release assets, no trigger, set,
unreadable list) and `devbox run test-fast` is green.

## t4 — Platform smoke jobs: service-typescript stale lock and the marker-secret build

**Files:** .github/workflows/ci.yml
**Covers:** AC-104.1, AC-104.2, AC-104.4, AC-104.5, AC-104.6, AC-104.7, AC-104.8, AC-104.9, AC-104.10, AC-104.11
**Goal:** the platform's CI proves the strict install for service-typescript and that a token passed as the build
secret ends up nowhere in either TypeScript image, while every check of the first build (AC-104.1, AC-104.4 to
AC-104.10) stays in place.

**Implementation notes:**
- `smoke-test-service-typescript`: a step "Strict install rejects a stale lock" like the web job's (copy the render,
  add `is-odd@3.0.1` to `dependencies` without locking, `pnpm install --frozen-lockfile` must fail with
  `ERR_PNPM_OUTDATED_LOCKFILE`); only in the `{observability: true, database: false}` entry.
- `smoke-test-web-nextjs` and that same service-typescript entry: after the existing image step,
  `MARKER="spec104-$(openssl rand -hex 12)"`, `docker build --secret id=PACKAGES_READ_TOKEN,env=MARKER -t smoke:<x>-secret .`
  (cached, seconds), then fail if `grep -F "$MARKER"` matches `docker history --no-trunc`, `docker image inspect` or
  `docker export` of a container created from it.
- Keep the existing builds without a secret (public dependencies build unchanged) and every existing spec-104 step
  (Python and web stale-lock steps, template metrics tests, observability-off variants) unchanged.
- The added steps run on cached layers; together they stay far under the 2-minute cap of AC-104.10.

**Done when:** `tests/cplat/test_generated_repos.py` passes in full (including its AC-104.10 checks of this file) and
the two smoke jobs pass on the PR.

## t5 — ADR-125 point 5, the library-typescript consumer note and the changelog fragment

**Files:** docs/adr/125-library-releases-publish-to-github-on-the-tag.md, templates/library-typescript/CLAUDE.md.jinja, docs/changelog.d/104-private-packages-in-image-builds.added.md
**Covers:** AC-104.11, AC-104.12
**Goal:** the docs say what the templates now do.

**Implementation notes:**
- ADR-125 Decision point 5: replace "consuming templates do not generate the wiring yet" with: the `web-nextjs` and
  `service-typescript` templates pass `PACKAGES_READ_TOKEN` to CI's install steps and as a BuildKit secret to the image
  build, and `/platform:doctor` reports it missing (spec 104).
- `library-typescript/CLAUDE.md.jinja`, consumer step 2: a `web-nextjs` or `service-typescript` consumer's CI and image
  build pass the secret already; only `gh secret set PACKAGES_READ_TOKEN -R <consumer>` is needed.
- Changelog fragment (format in `docs/changelog.d/README.md`): private GitHub Packages dependencies install in image
  builds of web-nextjs and service-typescript (`PACKAGES_READ_TOKEN` as a build secret, Dockerfile frontend 1.10),
  `/platform:doctor` reports the missing secret; repos pick it up with `/shared:update-service`.

**Done when:** `cplat platform pr-check` reports the fragment valid and `scripts/check-links.py` passes.
