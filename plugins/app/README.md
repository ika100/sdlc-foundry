# app plugin

Spec-driven features across a product's repos, run in its **`gitops-app`** repo ([ADR-026](../../docs/adr/026-feature-specs.md)): `/app:spec` writes the product spec (criteria `AC-<NNN>.<n>`, your answers, your approval); `/app:plan` assigns every criterion to a component repo, in dependency order, with the contract between them ([ADR-011](../../docs/adr/011-multi-repo-plan-format.md)); `/app:build` builds every ready repo in parallel, each through its own spec slice (`/svc:spec --from-plan` → `/svc:plan` → `/svc:build`), and stops at open PRs ([ADR-023](../../docs/adr/023-parallel-plan-execution.md)).

## Agents

| Agent | Model | Purpose |
|---|---|---|
| `planner` | opus | Writes `docs/plan/<spec_id>.md`: criteria per repo, order, contract (ADR-011/026) |

## Commands

| Command | Purpose |
|---|---|
| `/app:spec <desc>` · `approve <id>` · `--amend <id> <change>` | Product spec in `docs/specs/<NNN>-<slug>/spec.md`; asks you its open questions and for approval |
| `/app:plan <id>` | Planner → `docs/plan/<spec_id>.md`, validated by `plan-check` (every criterion assigned, topo order) → hand-off |
| `/app:ship <id> [--max N] [--context C]` | Unattended `/app:build`: spec/plan PR merged on green, then every repo through its own `/svc:ship` in plan order, merges on green checks, until `dev` runs every build with passing smoke ([ADR-042](../../docs/adr/042-product-ship-coordinates-repo-ships.md)) |
| `/app:build <id> [--max N]` | Wave by wave: one agent per ready repo **in parallel**, each through its own spec slice; PRs opened, merges only on your word |
| `/app:specs [--all\|show\|done\|abandon]` | Product specs and plan progress |

**Gates of `/app:ship`.** A repo starts only when every repo it depends on passed its gate: a service exposed in `dev` needs its merged build Synced/Healthy and smoke `passed` or `passed on retry` (smoke `not run` never passes); a service not exposed in `dev` needs Argo Synced/Healthy for its merged build; a library its merged PR. The gitops-app's PRs merge one at a time in plan order. A repo that escalates stops its dependents only; resume with `/app:ship <spec>`. Needs a kube context for the product's cluster. `/app:build` stays the attended flow that stops at open PRs.

## Dependencies

- `svc` (product-manager agent, `/svc:spec --from-plan`, `/svc:plan`, `/svc:build`), `shared`, `gitops` — all enabled in the `gitops-app` template's `.claude/settings.json`.
- The repo's `scripts/plan.py` and `devbox run plan-check` (shipped by the `gitops-app` template) do validation and lifecycle edits.

## Not yet

Automatic merging and image pinning (always a human step); `/app:release` (PRD C4, P2).
