# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**{{ project_name }}** — {{ description }}

Owned by {{ owner_team }}. Python module: `{{ module_name }}`. Container image: `{{ docker_registry }}/{{ project_name }}`.

## Development Environment

This project uses [devbox](https://www.jetify.com/devbox) to manage the dev environment.

```bash
devbox shell       # enter the dev environment
devbox run test    # full pytest run with coverage
devbox run quality # ruff + mypy gate
```

Canonical `devbox run` scripts (configured in `devbox.json`):

| Script | Purpose |
|---|---|
| `test` | Full pytest run with coverage (`--cov={{ module_name }} --cov-report=term-missing`) |
| `test-fast` | Quick pytest run without coverage |
| `lint` | `ruff check` + `ruff format --check` |
| `lint-fix` | `ruff check --fix` + `ruff format` |
| `typecheck` | `mypy .` |
| `quality` | `lint` then `typecheck` — the gate CI runs |
| `audit` | `pip-audit --strict` |
| `secrets-scan` | `detect-secrets-hook` against `.secrets.baseline.json` |
| `bandit` | `bandit -r src/ -q` |
| `security` | `audit` + `secrets-scan` + `bandit` |
| `ci` | `quality` + `test` + `security`: the gates CI runs; run it before every push |
| `image-build` | Build local container image `{{ project_name }}:scan` |
| `image-scan` | `trivy image --severity CRITICAL,HIGH` against `{{ project_name }}:scan` |
{%- if needs_migrations %}
| `migrate` | `alembic upgrade head` |
| `migrate-new` | `alembic revision --autogenerate -m <msg>` |
| `migrate-down` | `alembic downgrade -1` |
| `migrate-status` | `alembic current` + `alembic history --verbose` |
{%- endif %}

**Rule for every agent (human, CI, and AI): never call `ruff`, `mypy`, `pytest`, `pip-audit`, `detect-secrets`, `trivy`,{% if needs_migrations %} `alembic`,{% endif %} `bandit`, `pip`, or `uv add` directly. Always go through `devbox run <script>`.**

## Claude Code agents

Agents and slash commands come from the [`ika100/sdlc-foundry`](https://github.com/ika100/sdlc-foundry) marketplace. The plugins are enabled in `.claude/settings.json`:

- `svc@sdlc-foundry` — multi-agent pipeline (product-manager, architect, coder, tester, migrations, observability, release, deployment)
- `shared@sdlc-foundry` — quality, security, and the `/shared:new-service` bootstrap command

Read the platform's `docs/AGENTS.md` for the full orchestration model.

### Common workflows

| Task | Command |
|---|---|
| Write a feature spec (first step) | `/svc:spec <description>` |
| Plan the approved spec | `/svc:plan <NNN>` |
| Build it: tests first, verified | `/svc:build <NNN>` |
| All of it unattended: build, PR, merge on green CI, dev | `/svc:ship <NNN>` (headless: `cplat headless "/svc:ship <NNN>"`) |
| Where specs stand | `/svc:specs` |
| Small change | `/svc:quick-task <description>` |
| Fix a bug | `/svc:fix-bug <description or error>` |
| Read-only quality + security audit | `/shared:check-quality` |
| Release | `/svc:release` |

### Spec first

A feature starts with a spec, not code ([ADR-026](https://github.com/ika100/sdlc-foundry/blob/main/docs/adr/026-feature-specs.md)): `/svc:spec <description>` writes `docs/specs/<NNN>-<slug>/spec.md` with acceptance criteria `AC-<NNN>.<n>` and asks you its open questions; approve it (`/svc:spec approve <NNN>`), plan it (`/svc:plan <NNN>`), then build it (`/svc:build <NNN>`): acceptance tests are written from the criteria first and fail, the code makes them pass, a reviewer checks the result against the spec, and the PR lists every criterion. Tests that name a criterion are the spec in code: never weaken them; change the spec instead (`/svc:spec --amend <NNN> <change>`). `/svc:specs` shows where each spec stands; `devbox run spec-check` validates every spec and traces built ones to their tests (also the warn-only `specs` CI workflow). Small changes (`/svc:quick-task`) and bug fixes (`/svc:fix-bug`) need no spec, but stop when they would change a criterion.

## Feature Branch Workflow

Branch prefixes: `feature/`, `fix/`, `chore/`, `docs/`, `refactor/`, `release/`. Slugs: lowercase, hyphens, ≤40 chars.

Main is protected. All changes via PR. Required CI checks: `quality`, `test`, `security`, `pr-title`, `docker`.

PR title format: `<type>(<optional-scope>): <description ≤72 chars>`. Valid types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `chore`, `ci`, `build`, `revert`.

## Conventions

- **Config:** read exclusively from environment variables
- **HTTP services:** expose `/health` and `/ready` endpoints
- **Logging:** structured JSON{% if needs_observability %} via structlog{% endif %}
- **Tests:** pytest, in `tests/`, fixtures in `conftest.py`
- **Docs:** feature specs in `docs/specs/` (index in `docs/backlog.md`), ADRs in `docs/adr/`

## Docker image pipeline

Whenever a `Dockerfile` exists, the CI workflow includes a `docker (build + push)` job that:

| Trigger | Tags pushed |
|---|---|
| PR | Build only — no push |
| Merge to `main` | `latest`, `sha-<short>` |
| Version tag `v1.2.3` | `1.2.3`, `1.2`, `1`, `latest`, `sha-<short>` |

Registry: `{{ docker_registry }}/{{ project_name }}`. Authentication via `GITHUB_TOKEN`.

## Deployment

This repo ships **only a container image**. Kubernetes manifests, environment wiring (e.g. `API_URL`), replicas, resources and exposure belong to the product's `gitops-app` repo (platform ADR-017): register the service with `/gitops:compose add {{ project_name }}` (needs the GitHub topic `deployable-service`, set by `/shared:new-service`), then `/gitops:promote {{ project_name }} <from> <to>`. Change how the service runs by editing its entry in that repo's `services.yaml`; change the port, probe paths or user in the Dockerfile/app and update the entry to match.
