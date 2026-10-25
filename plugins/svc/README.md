# svc plugin

Orchestrators (`/svc:*`) and the shape-agnostic product-manager, architect and reviewer agents, plus the Python agents (coder, tester, migrations, observability, release, deployment). Commands detect the repo shape (`shapes.yml`) and route coder/tester/deployment/observability/release to the shape's plugin (`web`, `svc-java`, `svc-go`). Pair with the `shared` plugin for quality/security and the `service-python` Copier template for the canonical project skeleton.

## Agents

| Agent | Model | Purpose |
|---|---|---|
| `product-manager` | opus | Feature specs: stories, acceptance criteria `AC-<NNN>.<n>`, non-goals, open questions; folds triaged issues into specs |
| `architect` | opus | `design.md` + `plan.md` (tasks with `covers`), ADRs |
| `reviewer` | opus | Verifies a build against its spec, writes `verification.md` |
| `coder` | sonnet | Python implementation following the architect's plan |
| `tester` | sonnet | Acceptance tests from the spec first; pytest suite, coverage gate (≥80%), bandit |
| `migrations` | sonnet | Alembic migrations and seed scripts |
| `observability` | sonnet | structlog + Prometheus + OTel scaffolding, alerting rules |
| `release` | sonnet | Semver bump, CHANGELOG, release branch + PR |
| `deployment` | sonnet | Dockerfile and GHCR CI pipeline (image only) |

## Skills

| Skill | Purpose |
|---|---|
| `spec-format` | The formats of `docs/specs/<NNN>-<slug>/` (spec, design, plan, verification, test tagging); the agents read its references ([ADR-026](../../docs/adr/026-feature-specs.md)) |

## Commands

| Command | Purpose |
|---|---|
| `/svc:spec <desc>` | product-manager writes `docs/specs/<NNN>-<slug>/spec.md`; you answer its open questions; `--amend <id> <change>`, `approve <id>`, `--from-plan <plan> <repo-id>` |
| `/svc:plan <id>` | architect writes `design.md` + `plan.md` for an approved spec, checked by `cplat spec check` |
| `/svc:build <id>` | Failing acceptance tests first → parallel coders until green → quality ‖ tests ‖ security (fixable dependency CVEs are patched by `cplat deps patch`, spec 095) → reviewer verifies against the spec → image → PR. Resumable |
| `/svc:ship <id> [--no-merge]` | Unattended from an approved spec to `dev`: plan → build → PR (`cplat ship pr`) → merge only after every check passed (`cplat ship land`, CI fix loop) → wait for the pin PR and Argo (`cplat ship deploy`). Resumable; the shared plugin's Stop hook keeps the run going until it is done or escalated ([ADR-028](../../docs/adr/028-unattended-delivery-without-branch-protection.md)); the run is recorded in the run store (spec 087, `cplat runs report`) |
| `/svc:verify [<id>]` | Trace + reviewer against the spec; writes `verification.md`, changes no code |
| `/svc:specs [--all\|index\|migrate]` | Spec status with the next command; refresh the backlog table; migrate legacy `STORY-NNN` stories |
| `/svc:quick-task <desc>` | Lightweight, no spec: coder → quality → tester → PR (stops if the change alters a spec criterion) |
| `/svc:fix-bug <desc>` | Diagnose → fix → regression test → PR |
| `/svc:release` | Quality gate → test gate → security gate → version bump → tag → close issues |

quick-task, fix-bug and build end with `cplat pr open`, which commits (`-s`), pushes and opens the PR in one step (idempotent; the body goes to `.pr-body.md`). Agents get a compact brief (criteria, task, contract, tests, commands) and run green scripts through `cplat quiet <script>`, which prints one line on success and the tail plus the log path on failure (spec 100). With a criterion ending in `(smoke)`, `/svc:ship` runs the repo's `devbox run smoke` against dev after the deploy (spec 091; by hand: `cplat smoke run`), and with `promotion: {staging: auto}` in the gitops-app it promotes a green build to staging (spec 093).

## Coordinator model

Headless sessions (`cplat headless`, `cplat runs benchmark`) start the coordinator on **Sonnet** ([ADR-036](../../docs/adr/036-coordinator-model-default-and-settings.md)). Override per run with `cplat headless --model sonnet|opus|haiku`, or set `coordinator_model` in `.platform-settings.yml` (repo) or `~/.config/sdlc-foundry/settings.yml` (user), also per workflow. The agents in the table above keep their own model. `cplat runs benchmark <workflow> --model M --plugins <worktree>/plugins` measures a model or unreleased plugins (and their `cplat`) before a release.

## References

Rare branches of build, ship and quick-task live in `references/` and are read only when the branch is taken: `build-replan.md`, `build-resume.md`, `build-security-red.md`, `build-worktree-fallback.md`, `quick-task-on-main.md`, `ship-gitops.md`, `ship-land-red.md`.

## Hooks

- `SessionStart` runs `devbox run -- uv sync --all-extras` to keep the venv current (only when `pyproject.toml` exists).

## Dependencies

This plugin assumes:

1. **`shared` plugin is also enabled** (provides `quality` + `security` agents that several commands invoke).
2. **Project has a `devbox.json` with the canonical recipes** (`test`, `lint`, `quality`, `security`, `image-build`, …). Use the `service-python` Copier template to bootstrap a project with the right shape.
3. For the Python agents: a Python repo using `uv` and `pyproject.toml`. Other shapes use their own plugin's agents (this plugin must still be enabled for the orchestrators).

Enable both plugins via `.claude/settings.json`:

```json
{
  "enabledPlugins": {
    "svc@sdlc-foundry": true,
    "shared@sdlc-foundry": true
  }
}
```

## Bootstrap

```
/shared:new-service payments-api --description "Stripe webhooks → Postgres"
```
