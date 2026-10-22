# Claude Code Multi-Agent Setup

This document describes the orchestration model used by the `svc`, `web`, `svc-java`, `svc-go`, `gitops`, `app` and `shared` plugins. Read this first when adding or modifying agents.

---

## Golden rule: everything goes through `devbox run`

Every agent — human, CI, or AI — runs shell commands via `devbox run <script>`. The canonical recipes (`test`, `test-fast`, `lint`, `lint-fix`, `typecheck`, `quality`, `security`, `image-build`, `image-scan`, `deploy-check`, … — the same names in every shape, wrapping that shape's tools) are defined once in `devbox.json` and reused everywhere. Each shape's Copier template ships the full canonical set; consumer repos start with that and add project-specific recipes as needed.

If a recipe is missing, **add it to `devbox.json` and commit** — never run an ad-hoc `pip install`, `uv add`, `pnpm add`, `go get`, `mvn …`, `pytest …`, `ruff …`, or similar (one-off tool calls go through `devbox run -- <tool> …`). This keeps the dev shell, CI pipeline, and agents producing identical results.

### SessionStart hooks

The `svc`, `web`, `svc-java`, `svc-go`, `gitops` and `shared` plugins ship a `hooks/hooks.json` with a `SessionStart` hook that:

- **Warns if `devbox` is missing from `PATH`** and prints the install command: `curl -fsSL https://get.jetify.com/devbox/install.sh | bash`. The hook exits 0 — it never blocks the session.
- **Runs `devbox install` (idempotent)** if a `devbox.json` is present in the working directory, so the dev environment is ready before any agent touches it. The `svc` hook additionally runs `uv sync --all-extras` for Python repos (when `pyproject.toml` exists); `web` runs `devbox run install` when `node_modules/` is missing.

A consumer repo that installs any of these plugins is therefore devbox-aware out of the box; a repo with no `devbox.json` sees the hook as a silent no-op.

### Stop hook (shared plugin)

While a `/svc:ship` run is unfinished, the shared plugin's `Stop` hook keeps the session going (spec 066, [ADR-028](adr/028-unattended-delivery-without-branch-protection.md)). It looks for `<git dir>/cplat-ship.json` in shell first, so sessions without a run never start Python. With a run it calls `cplat ship gate`, which blocks the stop with the next step, and in the build phase the untraced criteria and the red `devbox run test-fast` output. It lets the session stop when the run is done, when the orchestrator escalated (`cplat ship escalate '<reason>'`: merge conflict, a changed acceptance test, a CRITICAL finding, a decision the spec does not answer, the user asked to stop), or after 8 blocked stops in a row (recorded as the escalation).

---

## Permissions allowlist

Each consumer repo ships a `.claude/settings.json` (templated by Copier) with a committed allowlist that pre-approves the safe, frequent operations the pipeline needs — so `/svc:build` and `/svc:quick-task` don't pause for permission prompts mid-flight.

**Auto-allowed (in every template; the Python-only `uv`/`python` entries exist only in the Python templates, `pnpm add`/`pnpm remove` prompt in the web template):**
- Every `devbox run <recipe>` (the canonical entry point)
- Read-only git (`status`, `diff`, `log`, `show`, …)
- Local-only git writes (`add`, `commit -m`, `merge --no-ff`, `worktree add/remove`, `branch -d`, `stash`, `tag -a`)
- Read-only inspection (`ls`, `find`, `grep`, `rg`, `jq`, `cat`, `head`, `tail`, `kubectl get/describe/logs/diff`, `kubectl apply --dry-run=*`)
- Pushing to non-main feature/fix/chore/docs/refactor/release branches and version tags
- Read-only `gh` (`pr view`, `issue list`, `run view`, …) and pre-approved `gh pr merge --merge release/*`

**Always prompts (explicitly listed in `ask`):**
- Anything that touches a remote: `git push origin main`, `git pull`, `gh pr create`, `gh release *`, `docker push`
- Anything destructive: `git reset`, `git clean`, `git rebase`, `git branch -D`, `git checkout --`, `git commit --amend`
- Cluster writes: `kubectl delete`, `kubectl rollout restart/undo` (live `kubectl apply` also prompts — it's covered by default since only `--dry-run=*` is allowlisted)
- Out-of-band installs: `pip install`, `uv add`, `uv remove` (Python) / `pnpm add`, `pnpm remove` (web)

**Pre-approved by the `shared` plugin specifically:**
- `gh repo create * --private *`, `gh repo edit * --add-topic *`, `git clone --depth 1 *`, `uv run * shapes.py *` and `copier copy *` so `/shared:new-service` and `/shared:update-service` can run without mid-flight prompts.

---

## How commands run the platform script

Commands never contain logic that can be code: they call `cplat <command>` and relay its output. `cplat` is the shared plugin's `bin/cplat` launcher, on the Bash PATH while the plugin is enabled. It runs `scripts/cplat` from the installed marketplace checkout, so commands use the platform version the plugins were installed from, offline; `$CPLAT_PLATFORM` (a local checkout) and `$CPLAT_REF` (a tag) override it, and only a missing checkout makes it fetch `main`. `/shared:doctor` reports the source.

---

## Shapes and agent dispatch

Every `/svc:*` command starts by detecting the repo's **shape** (`.copier-answers.yml`, falling back to file sniffing) and looks it up in `shapes.yml`. Coder, tester, deployment, observability and release agents are then spawned from the plugin that owns the shape (`web:coder`, `svc-java:tester`, `svc-go:release`, …; `svc:*` for Python); product-manager and architect (`svc`) and quality and security (`shared`) are shared by all shapes. `gitops-app` repos do not use `/svc:spec`, `/svc:plan` or `/svc:build`; they use `/gitops:compose`, `/gitops:promote` and `/app:spec|plan|build|specs` (`cplat shape` prints the routing). The multi-repo flow: `/app:spec` (product spec, approved) → `/app:plan` (criteria per repo, contract) → `/app:build` runs `/svc:spec --from-plan <plan> <repo-id>`, `/svc:plan`, `/svc:build` in each ready repo in parallel → you merge → `/gitops:promote`.

---

## Parallel implementation via git worktrees

`/svc:build` Phase 2 fans coder agents out in parallel using the Agent tool's `isolation: "worktree"` mode. Each parallel coder works in its own git worktree on its own branch; the orchestrator merges branches back onto the base branch sequentially with a quality gate between each merge.

Worktrees must start at the **feature branch**, where the spec, the plan and the red acceptance tests are: every template sets `worktree.baseRef: "head"` in `.claude/settings.json` (Claude Code's default branches from `main`), and the probe before the first batch checks the worktree's HEAD; on a mismatch the build runs sequentially and says why.

The flow only works when the architect's plan is machine-readable. `docs/specs/<id>/plan.md` starts with a YAML metadata block (exact format: `plugins/svc/skills/spec-format/references/plan.md`; `cplat spec check` validates it):

```yaml
---
spec_id: <NNN>-<slug>
shape: <shape-id>      # service-python | web-nextjs | service-java | service-go | …
spec_hash: <from cplat spec hash>   # the plan is invalid once the criteria change
tasks:
  - id: t1
    title: ...
    files: [<paths the task will touch>]
    covers: [AC-<NNN>.1]           # every active criterion is covered by some task
    parallel_safe: true
    depends_on: []
    # done: true                   # written by the build as tasks merge; a re-run resumes
---
```

The orchestrator:

1. **Topologically sorts** tasks by `depends_on`.
2. At each dependency level, **greedily groups `parallel_safe: true` tasks into batches** whose `files` sets are disjoint.
3. For each batch ≥ 2: spawns one coder per task **in one assistant turn** (multiple Agent tool calls in parallel), each in its own worktree. Each coder commits inside its worktree before returning.
4. **Merges sequentially** back onto the base branch with `git merge --no-ff`. After each merge: `devbox run lint-fix`, then `cplat spec test-diff <red commit>` (acceptance tests may only be reformatted), `devbox run quality` and `devbox run test-fast`. On failure, hand back to that task's coder for lint/type fixes only. Each merged task is marked `done` in the plan.
5. Cleans up worktrees and branches as it merges.

**Merge conflicts are escalated, never auto-resolved.** A conflict means the architect's `files` declarations were inaccurate — the fix is to update the plan, not to paper over it.

---

## Feature branch and PR lifecycle

Both `/svc:quick-task` and `/svc:build` include:

- **Phase 0** (pre-flight): if on `main`, create `feature/<slug>` branch before any work starts.
- **Final PR phase**: after all quality/test/security gates pass, push the branch and open a PR. Both push and PR creation are in the `ask` permission list — user must confirm.

`/svc:ship` goes further without asking (spec 067): `cplat ship pr` pushes only the spec's feature branch and opens the PR, `cplat ship land` merges it after every reported check passed (never with a pending, failed or missing check), and `cplat ship deploy` waits for the gitops-app's pin PR. None of it needs branch protection or auto-merge, which private repos on GitHub Free lack ([ADR-028](adr/028-unattended-delivery-without-branch-protection.md)); the gitops-app's `pin-dev` workflow merges pin PRs the same way (spec 065).

### Automatic issue linking and closing

The PR phase explicitly scans for GitHub issue references — `#NNN` patterns — in:
- The task/feature description (`$ARGUMENTS`)
- The last 10–20 commit messages on the branch
- the spec's `tracks:` issues (`build` only)

Each candidate issue is verified via `gh issue view` to confirm it is `OPEN`. Live `Closes #NNN` lines (not HTML comments) are injected into the PR body. When the PR merges into `main`, GitHub automatically closes each linked issue.

The `/svc:release` pipeline adds a second safety net: **Phase 7** scans all commits included in the release (since the previous tag) for `#NNN` references and calls `gh issue close` on any that are still open, with a comment linking to the release version.

---

## Overview

```
/svc:spec   ──►  product-manager  ──►  your answers to its open questions  ──►  your approval
                    │
                    ▼
               docs/specs/<NNN>-<slug>/spec.md   (criteria AC-<NNN>.<n>, non-goals)

/svc:plan   ──►  architect  ──►  design.md (contract) + plan.md (tasks covering every criterion; cplat spec check)

/svc:build  ──►  tester (acceptance mode) ──► coders ║parallel║ ──► merge+quality ──► quality ‖ tester ‖ security ──► reviewer ──► deployment ──► PR
                       │                         │ (1 worktree per task)                │                              │              │
                       ▼                         ▼                                      ▼                              ▼              ▼
                failing tests per AC     code until they pass                 lint, coverage, CVEs            verification.md   Dockerfile image

/svc:verify ──►  cplat spec trace + reviewer (no code changes)

/svc:ship   ──►  [plan] ──► [build Phases 0–6] ──► cplat ship pr ──► cplat ship land ──► cplat ship deploy
                                                                         │  red: logs → coder → push │  pin PR merged,
                                                                         │  (max 3 rounds)           │  Argo healthy
                                                                         └── merge only when every check passed (no branch protection needed)
                 Stop hook: no stop until done or `cplat ship escalate`; `cplat headless` resumes it in fresh sessions

/svc:fix-bug       ──►  coder (diagnose) ──►  coder (fix) ──►  tester (verify)
                                  └──────────── loop (max 3) ──────────────┘

/shared:check-quality ──►  quality + security (parallel, read-only)

/svc:release       ──►  quality gate ──►  tester gate ──►  security gate ──►  release agent
                                                                                  │
                                                                                  ▼
                                                                          changelog + tag + PR

/gitops:promote <svc...> <from> <to>   ──►  cplat promote  ──►  PR (Argo reconciles on merge)
/gitops:compose add|remove <svc...>    ──►  cplat compose  ──►  PR (services.yaml + generated ApplicationSets)
/app:spec <desc> → /app:plan <id>      ──►  product-manager ──► planner ──►  docs/specs/<id>/ + docs/plan/<id>.md
/app:build <id>                        ──►  one agent per ready repo: /svc:spec --from-plan → /svc:plan → /svc:build  ──►  PRs
```

---

## Agents by plugin

### `svc` plugin

| Agent | Model | Job |
|---|---|---|
| `product-manager` | opus | Specs (`docs/specs/<id>/spec.md`): stories, acceptance criteria `AC-<NNN>.<n>`, non-goals, open questions for the user; folds triaged issues into specs |
| `architect` | opus | `design.md` (decisions, contract), `plan.md` (tasks with `files`, `covers`, `parallel_safe`, `depends_on`), ADRs |
| `reviewer` | opus | Checks a build against its spec (criteria, non-goals, plan, contract); writes `verification.md`; read-only on code |
| `coder` | sonnet | Python implementation; done when the acceptance tests of its task pass |
| `tester` | sonnet | Acceptance tests from the spec before the code; pytest, coverage, bandit |
| `migrations` | sonnet | Alembic migrations |
| `observability` | sonnet | structlog + Prometheus + OTel scaffolding |
| `release` | sonnet | Semver, CHANGELOG, release branch + PR |
| `deployment` | sonnet | Dockerfile and GHCR CI (image only — manifests live in the gitops-app repo, ADR-017) |

Orchestrators dispatch `coder`, `tester`, `deployment`, `observability` and `release` to the plugin that owns the repo's shape (`<plugin>:<role>`; `cplat shape` prints the routing); for `service-python` / `library-python` that is `svc`. `product-manager`, `architect`, `reviewer`, `quality` and `security` are shape-agnostic.

The spec formats (`spec.md`, `design.md`, `plan.md`, `verification.md`, test tagging) live in one place, the `svc:spec-format` skill (`plugins/svc/skills/spec-format/`). Agents read its reference files through `${CLAUDE_PLUGIN_ROOT}` instead of restating them; testers in other plugins carry only their language's tagging idiom ([ADR-026](adr/026-feature-specs.md)).

### `web` plugin (`web-nextjs`)

| Agent | Model | Job |
|---|---|---|
| `coder` | sonnet | App Router + strict TypeScript; sonnet is enough for pattern-driven UI/route work |
| `tester` | sonnet | Vitest + Testing Library, Playwright when enabled |
| `deployment` | sonnet | Standalone-output Dockerfile and CI (image only) |
| `observability` | sonnet | `/api/metrics`, OpenTelemetry instrumentation, alerts |
| `release` | sonnet | `package.json` version, CHANGELOG, release PR |

### `svc-java` plugin (`service-java`)

| Agent | Model | Job |
|---|---|---|
| `coder` | sonnet | Spring Boot 3 / Java 21 implementation |
| `tester` | sonnet | JUnit 5 + Spring Boot Test, JaCoCo gate |
| `deployment` | sonnet | Distroless Java image, JVM-aware probes |
| `observability` | sonnet | Actuator + Micrometer + OTel agent |
| `release` | sonnet | `pom.xml` version via `versions:set` |

### `svc-go` plugin (`service-go`)

| Agent | Model | Job |
|---|---|---|
| `coder` | sonnet | Idiomatic Go (chi, slog) |
| `tester` | sonnet | stdlib `testing` + httptest, race detector |
| `deployment` | sonnet | distroless/static image, ldflags version |
| `observability` | sonnet | slog + Prometheus client_golang |
| `release` | sonnet | CHANGELOG + PR; version is the git tag |

### `gitops` plugin

| Agent | Model | Job |
|---|---|---|
| `deployment` | sonnet | ArgoCD ApplicationSet, cluster add-ons, overrides (platform GitOps repo) |

`/gitops:promote`, `/gitops:compose`, `/gitops:addon` and `/gitops:secret` have no agent: they run `cplat promote|compose|addon|secret` and relay its output.

### `app` plugin

| Agent | Model | Job |
|---|---|---|
| `planner` | opus | Multi-repo plan (`docs/plan/<slug>.md`, ADR-011): which repos change, in what order, with paste-ready prompts. opus because decomposition across repos is the hard judgement call |

### `shared` plugin

| Agent | Model | Job |
|---|---|---|
| `quality` | sonnet | Runs `devbox run quality` for the repo's shape (ruff + mypy, ESLint + tsc, Spotless + Checkstyle, golangci-lint, kustomize/kubeconform, …) |
| `security` | sonnet | Runs `devbox run security` (pip-audit/pnpm audit/OWASP DC/govulncheck + detect-secrets) and trivy on images |

---

## File conventions in consumer repos

| Path | Purpose |
|---|---|
| `docs/specs/<NNN>-<slug>/` | Feature specs: `spec.md`, `design.md`, `plan.md`, `verification.md` ([ADR-026](adr/026-feature-specs.md)) |
| `docs/backlog.md` | One-line index of the specs (generated table) plus your own notes |
| `docs/plan/<slug>.md` (gitops-app repo) | Multi-repo plans (ADR-011) |
| `docs/adr/<nnn>-<title>.md` | Architecture decision records |
| `docs/env-vars.md` | Required environment variables |
| `docs/security/scan-<date>.md` | Security scan reports |
| `docs/migrations/runbook.md` | Migration runbook |
| `applications/<app>/services.yaml` (gitops-app repo) | How each service runs; the manifests under `overlays/` are generated from it |
| `migrations/` | Alembic migration scripts |
| `tests/` | pytest test suite |
| `.github/workflows/` | CI/CD pipelines |
| `pyproject.toml` | Python project config |
| `.pre-commit-config.yaml` | Pre-commit hooks |
| `CHANGELOG.md` | Release changelog |

---

## Model selection convention

- `model: opus` — agents whose primary output is *decisions* downstream agents consume (`product-manager`, `architect`, `app:planner`) or that judge the result (`reviewer`). One bad plan poisons the whole run, so the reasoning headroom pays for itself.
- `model: sonnet` — execution agents (everything else).

When adding a new agent that needs to run shell commands, copy the **devbox rule** from `coder.md` or `quality.md` into the system prompt so the new agent inherits the same convention: shell only via `devbox run <script>`, recipes pinned in `devbox.json`.
