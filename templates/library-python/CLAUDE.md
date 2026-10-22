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
| `ci` | `quality` + `test` + `security`: the gates CI runs; run it before every push |

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

## Conventions

- Library, not a service — no HTTP entry point, no `/health` endpoint
- Public API in `src/{{ module_name }}/__init__.py`
- Tests in `tests/`, fixtures in `conftest.py`
- Branch naming: `feature/`, `fix/`, `chore/`, `docs/`, `refactor/`, `release/`
- Conventional commits in PR titles
