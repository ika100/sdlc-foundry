---
description: "Move one environment of a database or cache to a new major, one PR per environment, then verify it. Usage: /resource:upgrade <name> --to <major> [--env <env>]"
---

Run the platform script inside the gitops-app repo. **Request:** $ARGUMENTS

```bash
cplat resource upgrade <ARGS> --pr --wait
```

Relay the output verbatim; errors carry a `fix:` line.

1. **Preview** with `--dry-run` (add it in place of `--pr --wait`) and show it verbatim.
2. **Run** it. Each run upgrades **one environment** in **one PR**: without `--env` that is dev, then `--env staging`, then `--env prod`. Staging starts only after dev is verified and prod always by hand. With `promote: after-dev-smoke` the staging step starts by itself after a verified dev step. When every environment is on the new major, the per-environment `version` entries fold into the resource's `version`.
3. **Explain the backup rule.** A database major step needs a successful backup from the last 60 minutes in that environment. If it refuses, run `/resource:backup <db> --env <env>` and try again. Caches and brokers have no backup; buckets have no version and are refused.
4. **After the merge** the platform waits for the resource to be healthy at the new version, then runs the smoke tests of every instance that uses it, and records the result. `cplat resource upgrade <name> --verify --env <env>` repeats the check.
5. **On a failure** the command exits 1 and no later environment moves. The output names the failed check and the last backup time; for a database it names `/resource:restore <db> --env <env> --to <time|latest>`, which a person starts.

> If a step fails because a platform template, script or command misbehaves (not because of the user's code), stop, summarize it in two lines and offer `/issue:report` so the user can file it. Never file anything without their OK.
