---
description: "Change one environment of the system in a gitops-app repo (promote rule, policy, host, operators; system.yaml, rendered manifests, one PR). Usage: /system:set --env <env> [--promote <rule>] [--policy <policy>] [--host <host>] [--operators owner|install]"
---

Run the platform script inside the gitops-app repo. **Request:** $ARGUMENTS

`cplat` is on the Bash PATH while the shared plugin is enabled and runs the platform script at the version your plugins were installed from; one call per Bash invocation, from the repo root:

```bash
cplat system set <ARGS>
```

1. **Preview** with `--dry-run`; show it verbatim. Errors name the key (`environments.<env>.<key>`) and the allowed values — show them and stop.
2. **Run** with `--pr`. Creating the branch and PR is what the user asked for; do not ask again.
3. **Report** the script's output.

`--env <env>` names one environment of the system and at least one of `--promote`, `--policy`, `--host` or `--operators` is needed. `--promote` takes `after-dev-smoke` or `manual` on staging, only `manual` on prod and nothing on dev. `--policy` takes `audit`, `enforce` or `off`. `--host` is a host template with the placeholders `{component}`, `{system}` and `{env}`. `--operators owner` hands the environment's operators to a cluster repo (`environments.<env>.operators: owner`, what `/cluster:add` asks for); `--operators install` removes the key, so the system installs them itself. Only that environment's keys change; comments and order in `system.yaml` stay.

Rules: only `applications/` and `bootstrap/` change; never `kubectl apply`.

> If a step fails because a platform template, script or command misbehaves (not because of the user's code), stop, summarize it in two lines and offer `/issue:report` so the user can file it. Never file anything without their OK.
