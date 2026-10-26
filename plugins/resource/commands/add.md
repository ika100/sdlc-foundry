---
description: "Declare the postgres database of the system in system.yaml. Usage: /resource:add postgres [--version N]"
---

Run the platform script inside the gitops-app repo. **Request:** $ARGUMENTS

```bash
cplat resource add <ARGS>
```

1. **Preview** with `--dry-run` and show it verbatim; errors carry a `fix:` line.
2. **Run** with `--pr` (one PR; the user asked for it, do not ask again).
3. **Next**: components opt in with `/component:set <component> --uses postgres`, which injects `DATABASE_URL` and `PG*`. The operator (CloudNativePG) must exist in the cluster; `devbox run cluster-up` installs it locally.

5.0 supports one database resource, named `postgres`. Observability is not a resource: it is set per environment under `environments.<env>.observability` in `system.yaml`, and every component then gets `OTEL_*` variables and a collector per environment. `resource add observability` exits 1 and says so; edit the file for it. Removing the resource never deletes the database; say so. No backups, PITR or pooling are provided (ADR-020).

> If a step fails because a platform template, script or command misbehaves (not because of the user's code), stop, summarize it in two lines and offer `/issue:report` so the user can file it. Never file anything without their OK.
