---
description: "Add components to the system.yaml of a gitops-app repo, rendered into manifests in one PR. Usage: /component:add <component...> [--type T --lang L] [--env K=V] [--expose [HOST]] [--uses postgres] [--replicas N] [--generate|--secret NAME=KEY,KEY] [--from-k8s]"
---

Run the platform script inside the gitops-app repo. **Request:** $ARGUMENTS

`cplat` is on the Bash PATH while the shared plugin is enabled and runs the platform script at the version your plugins were installed from; one call per Bash invocation, from the repo root:

```bash
cplat component add <ARGS>
```

1. **Preview** with `--dry-run`; show it verbatim. Errors carry a `fix:` line (typical: repo missing the `deployable-service` topic, component not found, dirty tree) — show them and stop.
2. **Run** with `--pr` (one PR per invocation, however many components). Creating the branch and PR is what the user asked for; do not ask again.
3. **Report** the script's output. Remind the user of the two follow-ups in it: wire the new entry if the component needs it (`/component:set <component> --env … --expose …`), and that new components start in `dev` only (`instances: {dev: {}}`) — `/instance:promote` moves them on.

`add` writes `components.<name>` with `type`, `lang` and the `dev` instance; `--type`/`--lang` are only needed when the component's repo has no `.copier-answers.yml`. It refuses a component that is already there (use `/component:set`).

Migrating a component that still has `k8s/base` (platform v1)? Add `--from-k8s` to seed port, probes, env, replicas and resources from it; afterwards `/platform:update --migrate` removes the component's `k8s/` directory.

Secrets: `--generate NAME=KEY,KEY` makes External Secrets Operator create random values in the cluster (DB passwords, signing keys); `--secret NAME=KEY` declares values read from the secret store (set locally with `/instance:secret set <component>/<env> …`). Values never go to git.

Rules: only `applications/` and `bootstrap/` change; never `kubectl apply`; never add GitHub topics (report the missing one instead).

> If a step fails because a platform template, script or command misbehaves (not because of the user's code), stop, summarize it in two lines and offer `/issue:report` so the user can file it. Never file anything without their OK.
