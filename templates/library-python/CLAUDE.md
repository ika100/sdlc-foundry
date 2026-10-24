# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**{{ project_name }}** — {{ description }}

Owned by {{ owner_team }}. Python module: `{{ module_name }}`. Distributed as a wheel via internal index (no Docker image, no deployment).

## Development Environment

```bash
devbox shell        # enter the dev environment
devbox run quality  # ruff + mypy
devbox run test     # pytest with coverage
```

Canonical `devbox run` scripts:

| Script | Purpose |
|---|---|
| `test` | pytest with coverage (`--cov={{ module_name }}`) |
| `test-fast` | quick pytest |
| `lint` | `ruff check` + `ruff format --check` |
| `lint-fix` | `ruff check --fix` + `ruff format` |
| `quality` | lint + typecheck |
| `audit` | pip-audit |
| `secrets-scan` | detect-secrets |
| `bandit` | bandit |
| `security` | audit + secrets-scan + bandit |
| `secrets-baseline` | refresh `.secrets.baseline.json` with fixed flags (never run `detect-secrets scan` by hand) |
| `ci` | `quality` + `test` + `security`: the gates CI runs, then `ci-extra` when your repo defines it; run it before every push |

**Rule for every agent: never call `ruff`, `mypy`, `pytest`, `pip`, or `uv add` directly. Always `devbox run <script>`.**

## Claude Code agents

Plugins enabled in `.claude/settings.json`:

- `svc@sdlc-foundry` — coder, architect, tester, quality gate
- `shared@sdlc-foundry` — quality + security agents

Library repos don't need the `deployment` agent (no Dockerfile, no k8s) — leave those plugin commands unused.

Common workflows:

| Task | Command |
|---|---|
| Small change | `/svc:quick-task <description>` |
| Write a feature spec (first step) | `/svc:spec <description>` |
| Plan the approved spec | `/svc:plan <NNN>` |
| Build it: tests first, verified | `/svc:build <NNN>` |
| All of it unattended: build, PR, merge on green CI, dev | `/svc:ship <NNN>` (headless: `cplat headless "/svc:ship <NNN>"`) |
| Where specs stand | `/svc:specs` |
| Release | `/svc:release` |
| Quality + security audit | `/shared:check-quality` |

### Spec first

A feature starts with a spec, not code ([ADR-026](https://github.com/ika100/sdlc-foundry/blob/main/docs/adr/026-feature-specs.md)): `/svc:spec <description>` writes `docs/specs/<NNN>-<slug>/spec.md` with acceptance criteria `AC-<NNN>.<n>` and asks you its open questions; approve it (`/svc:spec approve <NNN>`), plan it (`/svc:plan <NNN>`), then build it (`/svc:build <NNN>`): acceptance tests are written from the criteria first and fail, the code makes them pass, a reviewer checks the result against the spec, and the PR lists every criterion. Tests that name a criterion are the spec in code: never weaken them; change the spec instead (`/svc:spec --amend <NNN> <change>`). `/svc:specs` shows where each spec stands; `devbox run spec-check` validates every spec and traces built ones to their tests (also the warn-only `specs` CI workflow). Small changes (`/svc:quick-task`) and bug fixes (`/svc:fix-bug`) need no spec, but stop when they would change a criterion.

## Where your additions go

Updates (`/shared:update-service`) overwrite the skeleton files below. Put your own work next to them, where an update keeps it:

| Updates overwrite | Your additions go in |
|---|---|
| the template's recipes in `devbox.json` (including `ci`) | gates: the `ci-extra` recipe (`devbox run ci` and the `ci-extra` CI check run it); other tools: recipes of your own in `devbox.json` (kept) |
| `.github/workflows/ci.yml` | a workflow file of your own in `.github/workflows/` |
| `.claude/settings.json` | your own permission entries (allow, ask, deny) in it; they are kept |
| `CLAUDE.md` | `.claude/project-notes.md` |
| other skeleton files (Dockerfile, lint config ...) | nowhere: propose the change to the platform (`/shared:report-issue`) |

## Conventions

- Library, not a service — no HTTP entry point, no `/health` endpoint
- Public API in `src/{{ module_name }}/__init__.py`
- Tests in `tests/`, fixtures in `conftest.py`
- Branch naming: `feature/`, `fix/`, `chore/`, `docs/`, `refactor/`, `release/`
- Conventional commits in PR titles

## Project notes

Project-specific guidance for Claude Code goes in `.claude/project-notes.md`, which is loaded below and never changed by updates.

@.claude/project-notes.md
