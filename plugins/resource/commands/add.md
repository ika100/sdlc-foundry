---
description: "Declare a resource of the system in system.yaml. Usage: /resource:add <name> --type database [--version N] [--external [--path P]] (postgres is a database)"
---

Run the platform script inside the gitops-app repo. **Request:** $ARGUMENTS

```bash
cplat resource add <ARGS>
```

1. **Preview** with `--dry-run` and show it verbatim; errors carry a `fix:` line.
2. **Run** with `--pr` (one PR; the user asked for it, do not ask again).
3. **Next**: components opt in with `/component:set <component> --uses <name>`, which injects `DATABASE_URL` and `PG*`. Relay the next steps `cplat` prints.

A resource has a name (lower-case letters, digits and `-`) and a type. The four types are `database`, `bucket`, `cache` and `broker`; only `database` is built. `bucket`, `cache` and `broker` exit 1 and name the spec that brings them (116, 118, 119). `/resource:add postgres` without `--type` still adds a database; any other name needs `--type`. A name that exists or is invalid changes nothing.

- **Prefix rule**: a component that uses two or more resources of one type gets that type's variables once per resource, prefixed with the upper-cased name (`ORDERS_DB_DATABASE_URL`, `USERS_DB_PGHOST`), and no unprefixed variable of that type.
- **`--version N`**: the supported database majors are 15, 16, 17 and 18; another major fails the render.
- **`--external [--path P]`**: the database is not run by the platform; its connection data comes from the secret store. Tell the user to put the keys `uri`, `host`, `port`, `dbname`, `user`, `password` in the store under the key `cplat` prints (default `<system>-<env>-<name>`, or `--path P`). It needs a secret store in the system.
- **Operator**: an in-cluster database needs CloudNativePG, which the platform installs through `operators/`. Apply `operators/root.yaml` once per cluster (`KUBE_CONTEXT=<ctx> devbox run bootstrap`; `devbox run cluster-up` does it locally). An environment that sets `operators: owner` must have the operator installed by its owner.

Observability is not a resource: it is set per environment under `environments.<env>.observability` in `system.yaml`; `resource add observability` exits 1 and says so. Removing a resource never deletes the database. No backups, PITR or pooling are provided (ADR-020).

> If a step fails because a platform template, script or command misbehaves (not because of the user's code), stop, summarize it in two lines and offer `/issue:report` so the user can file it. Never file anything without their OK.
