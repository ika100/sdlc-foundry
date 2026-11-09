---
description: "Change one environment of the system (promote rule, policy, host, operators) in one PR. Usage: /system:set --env <env> [--promote <rule>] [--policy <policy>] [--host <host>] [--operators owner|install]"
---

Run the platform script inside the gitops-app repo. **Request:** $ARGUMENTS

A rule marked **Hard rule:** is never departed from. Any other rule is a practice: where its stated purpose does not apply, depart from it and name each departure and its reason in one line of your report.

Run `cplat` from the repo root, one call per Bash invocation. Read `cplat`'s output whole, never through `grep`, `head` or `tail`, because its last lines carry the decisions and fixes; use `--json` where offered.

```bash
cplat system set <ARGS>
```

1. **Preview** with `--dry-run`; show it verbatim. Errors name the key (`environments.<env>.<key>`) and the allowed values — show them and stop.
2. **Run** with `--pr`. Creating the branch and PR is what the user asked for, so ask nothing more.
3. **Report** the script's output.
4. **Wait** once the PR is merged (the user decides the merge; on their request `cplat pr wait <pr> --merge`): `cplat system wait --env <env> --refresh`, with `--refresh` right after a merge you made. It prints a line each time an app's state changes and ends `READY:` (exit 0), `RED:` (exit 1: a sync error or `Degraded` at the new revision; show its lines and stop) or `TIMEOUT:` (exit 2: run the same wait again, at most twice; after the third timeout escalate with cause `environment`: `cplat component ship escalate '<the TIMEOUT line>' --cause environment` inside a ship run, otherwise report the `TIMEOUT:` lines to the user as an environment problem). Never write a polling loop on `kubectl`, `gh` or `cplat`, because the wait already polls and ends in `READY:`, `RED:` or `TIMEOUT:`.

`--env <env>` plus at least one of `--promote`, `--policy`, `--host` or `--operators`. `--promote` takes `after-dev-smoke` or `manual` on staging, only `manual` on prod and nothing on dev. `--policy` takes `audit`, `enforce` or `off`. `--host` is a host template with the placeholders `{component}`, `{system}` and `{env}`. `--operators owner` hands the environment's operators to a cluster repo; `--operators install` removes the key, so the system installs them itself.

Only `applications/` and `bootstrap/` change, because Argo CD reads the cluster state from there. **Hard rule:** never `kubectl apply`, because a manual apply drifts the cluster from git.

> If a platform template, script or command misbehaves (not the user's code), stop, summarize it in two lines and offer `/issue:report`. **Hard rule:** never file an issue without the user's OK, because the platform repository is public; a `platform` escalation is the one issue the platform files itself (ADR-033).
