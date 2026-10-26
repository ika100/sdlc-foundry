# Adding a new shape (template authoring guide)

A **shape** is a kind of repo the platform can bootstrap and operate: `service-python`, `library-python`, `web-nextjs`, `gitops-app`, `service-java`, `service-go`. This guide is the contract from [platform-vision §4.1](requirements/platform-vision.md) made concrete; `service-go` and `service-java` are the worked examples (copy their layout), and `web-nextjs` shows a non-Python JS stack. `uv run scripts/shapes.py check` (run in CI) enforces everything marked **[checked]** below.

Deliver all of it in one PR.

## 1. Registry entry — `shapes.yml` [checked]

Deployable shapes also need a `runtime:` block (port, probes, numeric `user`, `volumes`, `env`, `resources`): `/component:add` copies it into the component's entry in `system.yaml` (ADR-017). 
Add the shape (see [ADR-015](adr/015-shape-registry-as-code.md) for every field). Start with `status: planned` while the template is incomplete; switch to `stable` in the same PR that makes the check pass. `deployable: true` means `/component:new` adds the `deployable-service` topic. Add a row to the PRD §4 table (the check compares shape id, plugin and template).

## 2. Copier template — `templates/<id>/`

Required files [checked unless noted]:

| File | Notes |
|---|---|
| `copier.yml` | `_templates_suffix: .jinja` (see below), `_answers_file: .copier-answers.yml`, `_skip_if_exists` for project-owned files, `_tasks` for bootstrap (they are skipped in CI with `--skip-tasks`, so the rendered tree must already be valid) |
| `{{ _copier_conf.answers_file }}.jinja` | Copier's answers file — **load-bearing**: shape detection reads `_src_path` from it |
| `devbox.json[.jinja]` | The canonical recipes: `lint`, `lint-fix`, `quality`, `test`, `test-fast`, `security`; deployable shapes also `image-build`, `image-scan`, `deploy-check` (plus `dev`, `deploy`, `typecheck`, `audit`, `secrets-scan` by convention). Recipes wrap the language tools — agents never call them directly |
| `CLAUDE.md[.jinja]` | Shape-specific: recipe table, the "never call X directly" rule, a `### Spec first` section ([ADR-024](adr/024-spec-driven-bootstrap.md)), conventions, branch workflow **[checked]** |
| `devbox.json[.jinja]` `ci`, `.github/workflows/ci.yml`, `.claude/project-notes.md`, `CLAUDE.md[.jinja]` | Repo-owned companions ([spec 086](specs/086-repo-gates-survive-skeleton-updates/spec.md), [ADR-031](adr/031-repo-owned-companions-for-skeleton-files.md)): the `ci` recipe ends with the `ci-extra` step and no template defines a `ci-extra` recipe; `ci.yml` has a `ci-extra` job running `devbox run ci-extra`; an empty `.claude/project-notes.md` is in `_skip_if_exists`; `CLAUDE.md` has a `## Where your additions go` section and ends with the `@.claude/project-notes.md` import **[checked]** |
| `.github/ISSUE_TEMPLATE/{bug_report,feature_request,config}.yml` | Issue forms that apply the `triage` label and require the fields `/issue:triage` needs ([ADR-025](adr/025-issue-triage.md)); in `_skip_if_exists` **[checked]** |
| `docs/backlog.md`, `docs/plan/` | Seed for spec-driven development ([ADR-024](adr/024-spec-driven-bootstrap.md)): the backlog skeleton (all shapes except gitops-app) and the plan directory; both in `_skip_if_exists` **[checked]** |
| `.claude/settings.json[.jinja]` | Enables the shape's plugin **and `shared`** and, for shapes driven by `/svc:*`, **`svc`** ([ADR-013 amendment](adr/013-plugin-auto-enable.md)); pins the marketplace ref |
| `.github/workflows/ci.yml` | `quality`, `test`, `security`, `pr-title`, `branch-name`, and `docker` for deployable shapes |
| `Dockerfile` | Deployable shapes: multi-stage, non-root with a **numeric** `USER`, runs with a read-only root filesystem. **No `k8s/` directory** — the gitops-app repo generates manifests (ADR-017); `shapes.py check` fails if one appears |
| `docs/adr/000-bootstrap.md`, `docs/env-vars.md`, `README.md` | Project-owned after generation |

**Always re-templated vs project-owned.** Skeleton files (CI, devbox, Dockerfile, CLAUDE.md, lint config) are overwritten by `/platform:update`. Application files (`src/`, `app/`, `cmd/`, `internal/`, `tests/`, language manifests such as `go.mod`/`pom.xml`/`package.json` once created, `docs/adr/**`) go in `_skip_if_exists`.

### Pitfalls found while building the Go, Java and web shapes

- **Use `_templates_suffix: .jinja`** for non-Python shapes. Without it every file is rendered and anything with `{{ }}` (GitHub Actions `${{ }}`, Argo `{{name}}`, JSX, Go templates) needs escaping. With it, only `*.jinja` files render; filenames and directory names always render (so `src/main/java/{{ package_path }}/` works).
- **Question order matters.** A default that references another question (`github.com/{{ github_org }}/…`) sees an empty value if that question comes later in `copier.yml`.
- **Derive, don't ask:** use `when: false` questions for computed values (`package_name`, `package_path`).
- **Ship lockfiles that make the CI render valid** when the toolchain cannot resolve them offline (Go: pre-resolved `go.mod`/`go.sum`, conditional on optional features; pnpm: `pnpm-workspace.yaml` with `allowBuilds`). Verify with the toolchain's own "tidy"/"frozen" command that the shipped files produce no diff.
- **Optional features:** gate files with `_exclude` entries like `"{% if not needs_x %}path{% endif %}"` — the pattern must match the *rendered* path, i.e. without the `.jinja` suffix.
- **Do not trust a render you have not run.** Run the recipes (`quality`, `test`, build) on a rendered project for *every* optional-feature combination; the template tests found lint failures, coverage-gate failures and Spring test-slice quirks that reading the files did not.
- **macOS:** `devbox run` that calls another `devbox run` breaks under `/tmp` (symlink to `/private/tmp` changes the generated script path mid-run: `pecheck: command not found`). Verify in `/private/tmp/...` or your home directory; it is not a template bug.

## 3. Plugin — `plugins/<plugin>/` (new or existing)

[checked for non-gitops plugins: agents exist] Agents: at minimum `coder` and `tester`; deployable shapes also `deployment`, `observability`, `release`. A new plugin needs `.claude-plugin/plugin.json`, an entry in `.claude-plugin/marketplace.json` with the **same version** (CI compares), a `README.md`, and `hooks/hooks.json` if the repo needs a SessionStart step. Rules every agent follows:

- Everything goes through `devbox run <recipe>`; one-off tool calls use `devbox run -- <tool> …`.
- `coder` writes the shape's idioms and never edits lock/format config by hand; `tester` never fixes bugs; `deployment` owns the image (Dockerfile, CI docker job, smoke start) and never writes manifests; `observability` verifies-then-extends the scaffolding the template ships.
- The `release` agent differs only in how the version is bumped ([ADR-012](adr/012-per-plugin-release-agent.md)).

The `/svc:*` orchestrators route to `<plugin>:<role>` through `cplat shape` (`scripts/cplat/shapecmd.py`, driven by `shapes.yml`); nothing in `svc` needs editing for a new backend shape.

## 4. Detection [checked]

- `scripts/detect-shape.sh`: add a `templates/<id>` case (primary) and a sniff rule positioned so it stays unambiguous ([ADR-008](adr/008-shape-detection.md)).
- `scripts/test-detect-shape.sh`: add a sniff fixture; the copier-answers fixtures iterate `shapes.yml` automatically.

## 5. CI and docs

- `.github/workflows/ci.yml`: a `smoke-test-<id>` job that renders the template (`--skip-tasks`, plus the optional-feature variants) and runs the real build/test/lint with the toolchain.
- `devbox.json` (platform): a `smoke-<id>` recipe, added to `smoke`.
- The shape's own workflows: every job `runs-on: ${{ vars.CI_RUNNER || 'ubuntu-latest' }}`, the devbox install step guarded with `if: runner.environment == 'github-hosted'`, and a `docker` matrix that `vars.CI_DOCKER_MATRIX` can replace ([self-hosted runners](self-hosted-runners.md), checked by `tests/cplat/test_ci_templates.py`).
- Docs: `docs/AGENTS.md` (agents + model rationale), `docs/ADOPTING.md` (migration section), README tables, `docs/CHANGELOG.md`, and an ADR for any decision the PRD left open (stack choices).

## 6. Keeping dependency pins current

Dependabot cannot read `*.jinja` manifests, so the `bump-template-pins` workflow (Mondays, or run it by hand) does it: `scripts/bump_template_pins.py` renders `service-java`, `web-nextjs` and `service-go`, lets Maven / npm-check-updates / Go bump the rendered manifest (minor and patch only), copies each changed line back into the template when it is literal and unique, and re-renders to verify. The resulting pull request runs the normal smoke tests. To cover a new shape, add an entry to `UPDATERS` in the script. Setup: a repository secret `BUMP_TOKEN` (fine-grained, Contents + Pull requests write) makes CI start for the bot's pull request; without it the PR says to close and reopen it.
