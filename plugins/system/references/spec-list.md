# System spec: list and track

Read from `/system:spec` with no argument, `--all`, `show <id>`, `done <id> <repo-id>` or `abandon <id>`. System specs and their multi-repo plans ([ADR-011](../../../docs/adr/011-multi-repo-plan-format.md)); `scripts/plan.py` is needed (else `/platform:update`).

| Arguments | Run |
|---|---|
| *(none)* / `--all` | `cplat spec list [--all]`, then `devbox run -- uv run scripts/plan.py list [--all]` |
| `show <id>` | `devbox run -- uv run scripts/plan.py show <spec_id>` |
| `done <id> <repo-id>` | `devbox run -- uv run scripts/plan.py done <spec_id> <repo-id>`; when the plan reports `completed`, also `spec set-status <spec_id> done` and `spec index` |
| `abandon <id>` | ask for confirmation, then `devbox run -- uv run scripts/plan.py abandon <spec_id>` and `spec set-status <spec_id> superseded --reason "abandoned"` |

Print every output verbatim. After a state change run `devbox run plan-check` and offer to commit the plan and spec (`docs(plan): <spec_id> <new status>`); never push without confirmation, because a push publishes the branch.
