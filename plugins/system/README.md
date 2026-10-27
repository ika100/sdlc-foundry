# system plugin

Spec-driven features across a system's components, run in its **`gitops-app`** repo ([ADR-026](../../docs/adr/026-feature-specs.md)): `/system:new` creates the system; `/system:spec` writes the system spec (criteria `AC-<NNN>.<n>`, your answers, your approval); `/system:plan` assigns every criterion to a component repo, in dependency order, with the contract between them ([ADR-011](../../docs/adr/011-multi-repo-plan-format.md)); `/system:ship` ships every repo unattended through its own `/component:ship`, in plan order ([ADR-042](../../docs/adr/042-product-ship-coordinates-repo-ships.md)).

## Agents

| Agent | Model | Purpose |
|---|---|---|
| `planner` | opus | Writes `docs/plan/<spec_id>.md`: criteria per repo, order, contract (ADR-011/026) |

## Commands

| Command | Purpose |
|---|---|
| `/system:new <manifest>` | Create a system from a manifest: the gitops-app repo with its `system.yaml` plus every component repo |
| `/system:status [--context C]` | One row per component, one column per environment: pinned version, CI state, Argo sync/health, then a Backups section |
| `/system:restore <env> [--backup <name\|latest>] [--replace] [--confirm prod]` | Restore an environment from a Velero backup |
| `/system:spec <desc>` · `approve <id>` · `--amend <id> <change>` | System spec in `docs/specs/<NNN>-<slug>/spec.md`; asks you its open questions and for approval |
| `/system:spec [--all\|show <id>\|done <id> <repo>\|abandon <id>]` | System specs and plan progress |
| `/system:plan <id>` | Planner, then `docs/plan/<spec_id>.md` validated by `plan-check` (every criterion assigned, topo order), then hand-off |
| `/system:ship <id> [--max N] [--context C]` | Unattended: spec and plan PR merged on green, then every repo through its own `/component:ship` in plan order, until `dev` runs every build with passing smoke |
