---
description: "Change a component of the system in a gitops-app repo (one PR). Usage: /component:set <component> [--env K=V] [--expose [HOST]] [--uses postgres] [--replicas N] [--provides NAME[:TYPE]] [--consumes NAME] [--instance <env> --replicas N]"
---

Run the platform script inside the gitops-app repo. **Request:** $ARGUMENTS

`cplat` is on the Bash PATH while the shared plugin is enabled and runs the platform script at the version your plugins were installed from; one call per Bash invocation, from the repo root:

```bash
cplat component set <ARGS>
```

1. **Preview** with `--dry-run`; show it verbatim. Errors carry a `fix:` line (typical: component not found, dirty tree, an environment the component has no instance in) — show them and stop.
2. **Run** with `--pr`. Creating the branch and PR is what the user asked for; do not ask again.
3. **Merge an exposure** (spec 142): with `--expose` the user asked for the component to be reachable, which needs the merge, so run `cplat pr wait <pr-url> --merge` and do not ask again; unless the user said not to merge (then leave the PR open). Other changes: leave the PR for review unless the user asked to merge it.
4. **Report** the script's output, and for an exposure the URL once Argo synced it.

`set <component>` with `--env K=V`, `--expose [HOST]`, `--uses postgres` or `--replicas N` merges into the component's existing entry (other env variables stay) and re-renders. One component per `set`. `--instance <env> --replicas N` changes that instance only and writes `instances.<env>.replicas`; the component must already have an instance in `<env>`, and `--instance` takes nothing but `--replicas`. `--replicas` is refused on a component or instance that has a `scale` (the two exclude each other): the error names the key to remove. `scale` is edited in `system.yaml`; there are no scale flags. Typical wiring: `set todo-web --env TODO_API_URL=http://todo-api --expose todo-web`, `set todo-api --uses postgres` (after `/resource:add postgres`).

Rules: only `applications/` and `bootstrap/` change; never `kubectl apply`.

> If a step fails because a platform template, script or command misbehaves (not because of the user's code), stop, summarize it in two lines and offer `/issue:report` so the user can file it. Never file anything without their OK (only a `platform` escalation is filed by the platform itself, ADR-033).
