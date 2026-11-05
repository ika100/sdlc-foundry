---
description: "Add components to the system.yaml of a gitops-app. Usage: /component:add <component...> [--env K=V] [--expose [HOST]] [--uses postgres] [--replicas N] [--generate|--secret NAME=KEY,KEY] [--provides NAME[:TYPE]] [--consumes NAME] [--from-k8s]"
---

Run the platform script inside the gitops-app repo. **Request:** $ARGUMENTS

`cplat` is on the Bash PATH while the shared plugin is enabled and runs the platform script at the version your plugins were installed from; one call per Bash invocation, its output read whole (never piped into `grep`, `head` or `tail`: its last lines carry the decisions and next steps; use `--json` where offered), from the repo root:

```bash
cplat component add <ARGS>
```

1. **Preview** with `--dry-run`; show it verbatim. Errors carry a `fix:` line (typical: repo missing the `deployable-service` topic, component not found, dirty tree) — show them and stop.
2. **Run** with `--pr` (one PR per invocation, however many components). Creating the branch and PR is what the user asked for; do not ask again.
3. **Merge an exposure** (spec 142): with `--expose` the user asked for the component to be reachable, which needs the merge, so run `cplat pr wait <pr-url> --merge` and do not ask again; unless the user said not to merge (then leave the PR open). Without an exposure leave the PR for review unless the user asked to merge it.
4. **Wait** once the PR is merged (spec 143): `cplat system wait --env dev <component…> --refresh` (new components start in `dev`), `--refresh` right after a merge you made (without it when the user merged). It prints a line each time an app's state changes and ends `READY:` (exit 0), `RED:` (exit 1: a sync error, a failed sync or `Degraded` at the new revision; show its lines and stop, nothing is retried or rolled back) or `TIMEOUT:` (exit 2: run the same wait again, the command it prints when Argo CD is behind on the revision, at most twice; after the third timeout escalate with cause `environment`: `cplat component ship escalate '<the TIMEOUT line>' --cause environment` inside a ship run, otherwise report the `TIMEOUT:` lines to the user as an environment problem). Never write a polling loop on `kubectl`, `gh` or `cplat`: the wait is the only way to wait.
5. **Report** the script's output, for an exposure the URL once the wait is `READY:`. Remind the user of the two follow-ups in the output: wire the new entry if the component needs it (`/component:set <component> --env … --expose …`), and that new components start in `dev` only (`instances: {dev: {}}`) — `/instance:promote` moves them on.

`add` writes `components.<name>` with `type`, `lang` and the `dev` instance; `--type`/`--lang` are only needed when the component's repo has no `.copier-answers.yml`. It refuses a component that is already there (use `/component:set`).

Migrating a component that still has `k8s/base` (platform v1)? Add `--from-k8s` to seed port, probes, env, replicas and resources from it; afterwards `/platform:update --migrate` removes the component's `k8s/` directory.

Secrets: `--generate NAME=KEY,KEY` makes the platform's credentials Job create random values in the cluster once per environment (DB passwords, signing keys; deleting the Secret makes a new value on the next sync); `--secret NAME=KEY` declares values read from the secret store (set locally with `/instance:secret set <component>/<env> …`). Values never go to git.

Rules: only `applications/` and `bootstrap/` change; never `kubectl apply`; never add GitHub topics (report the missing one instead).

> If a step fails because a platform template, script or command misbehaves (not because of the user's code), stop, summarize it in two lines and offer `/issue:report` so the user can file it. Never file anything without their OK (only a `platform` escalation is filed by the platform itself, ADR-033).
