# svc plugin

The shape-agnostic product-manager, architect and reviewer agents, the Python agents (coder, tester, migrations, observability, release, deployment) and the `spec-format` skill. Since 5.0 the commands live in the noun plugins: `/component:*` runs the spec-driven pipeline on this plugin's agents and routes coder/tester/deployment/observability/release to the shape's plugin (`web`, `svc-java`, `svc-go`) by `shapes.yml`. Pair with the `shared` plugin for quality/security and the `service-python` Copier template for the canonical project skeleton.

## Agents

| Agent | Model | Purpose |
|---|---|---|
| `product-manager` | opus | Feature specs: stories, acceptance criteria `AC-<NNN>.<n>`, non-goals, open questions; folds triaged issues into specs |
| `architect` | opus | `design.md` + `plan.md` (tasks with `covers`), ADRs |
| `reviewer` | opus | Verifies a build against its spec, writes `verification.md` |
| `coder` | sonnet | Python implementation following the architect's plan |
| `tester` | sonnet | Acceptance tests from the spec first; pytest suite, coverage gate (>=80%), bandit |
| `migrations` | sonnet | Alembic migrations and seed scripts |
| `observability` | sonnet | structlog + Prometheus + OTel scaffolding, alerting rules |
| `release` | sonnet | Semver bump, CHANGELOG, release branch + PR |
| `deployment` | sonnet | Dockerfile and GHCR CI pipeline (image only) |

## Skills

| Skill | Purpose |
|---|---|
| `spec-format` | The formats of `docs/specs/<NNN>-<slug>/` (spec, design, plan, verification, test tagging); the agents read its references ([ADR-026](../../docs/adr/026-feature-specs.md)) |

## Commands moved in 5.0

This plugin ships no commands any more (the old `/svc:*` files are tombstones that point to the new place and are removed in 6.0). The pipeline is run with the `component` plugin:

| Pipeline step | Command |
|---|---|
| Spec, plan, build, verify | `/component:spec`, `/component:plan`, `/component:build`, `/component:verify` |
| Unattended spec to `dev` | `/component:ship <id> [--no-merge]` (the `shared` plugin's Stop hook keeps the run going, [ADR-028](../../docs/adr/028-unattended-delivery-without-branch-protection.md)) |
| Small change or bug without a spec | `/component:fix <desc>` |
| Release | `/component:release` |

Agents get a compact brief (criteria, task, contract, tests, commands) and run green scripts through `cplat quiet <script>`, which prints one line on success and the tail plus the log path on failure (spec 100). Fix rounds validate with `cplat validate run`; the final gate before the PR always runs `devbox run ci` in full (spec 103, [guide](../../docs/unattended-delivery.md#change-aware-validation-in-fix-rounds)).

## Coordinator model

Headless sessions (`cplat headless`, `cplat platform runs benchmark`) start the coordinator on **Sonnet** ([ADR-036](../../docs/adr/036-coordinator-model-default-and-settings.md)). Override per run with `cplat headless --model sonnet|opus|haiku`, or set `coordinator_model` in `.platform-settings.yml` (repo) or `~/.config/sdlc-foundry/settings.yml` (user). The agents in the table above keep their own model.

## References

Rare branches of the pipeline live in `references/` and are read only when the branch is taken: `build-replan.md`, `build-resume.md`, `build-security-red.md`, `build-worktree-fallback.md`, `quick-task-on-main.md`, `ship-gitops.md`, `ship-land-red.md`.

## Hooks

- `SessionStart` runs `devbox run -- uv sync --all-extras` to keep the venv current (only when `pyproject.toml` exists).

## Dependencies

This plugin assumes:

1. **`shared` and `component` plugins are also enabled** (`shared` provides `quality` + `security` agents, `component` the commands).
2. **Project has a `devbox.json` with the canonical recipes** (`test`, `lint`, `quality`, `security`, `image-build`, ...). Use the `service-python` Copier template to bootstrap a project with the right shape.
3. For the Python agents: a Python repo using `uv` and `pyproject.toml`. Other shapes use their own plugin's agents (this plugin must still be enabled for the orchestrating agents).

Enable them via `.claude/settings.json`:

```json
{
  "enabledPlugins": {
    "svc@sdlc-foundry": true,
    "component@sdlc-foundry": true,
    "shared@sdlc-foundry": true
  }
}
```

## Bootstrap

```
/component:new payments-api --type service --lang python --system acme/shop-gitops
```
