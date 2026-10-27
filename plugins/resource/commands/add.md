---
description: "Declare a resource of the system in system.yaml. Usage: /resource:add <name> --type database|bucket|cache [--version N] [--storage S] [--versioning] [--external [--path P]] (postgres is a database)"
---

Run the platform script inside the gitops-app repo. **Request:** $ARGUMENTS

```bash
cplat resource add <ARGS>
```

1. **Preview** with `--dry-run` and show it verbatim; errors carry a `fix:` line.
2. **Run** with `--pr` (one PR; the user asked for it, do not ask again).
3. **Next**: components opt in with `/component:set <component> --uses <name>`, which injects `DATABASE_URL` and `PG*` (a database), `S3_*` and `AWS_*` (a bucket) or `REDIS_*` (a cache). Relay the next steps `cplat` prints.

A resource has a name (lower-case letters, digits and `-`) and a type. The four types are `database`, `bucket`, `cache` and `broker`; `database`, `bucket` and `cache` are built. `broker` exits 1 and names the spec that brings it (119). `/resource:add postgres` without `--type` still adds a database; any other name needs `--type`. A name that exists or is invalid changes nothing.

- **Prefix rule**: a component that uses two or more resources of one type gets that type's variables once per resource, prefixed with the upper-cased name (`ORDERS_DB_DATABASE_URL`, `USERS_DB_PGHOST`), and no unprefixed variable of that type.
- **`--version N`**: the supported database majors are 15, 16, 17 and 18; another major fails the render.
- **Bucket**: eight variables per used bucket: `S3_ENDPOINT`, `S3_BUCKET`, `S3_REGION`, `S3_FORCE_PATH_STYLE`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `AWS_ENDPOINT_URL_S3` (prefixed like a database's with two or more buckets, e.g. `UPLOADS_S3_BUCKET`). `--storage S` sets the size (default `10Gi`); `--versioning` keeps object versions (default off). An in-cluster bucket is its own SeaweedFS per instance. With `--external` the store holds the six keys `endpoint`, `bucket`, `region`, `forcePathStyle`, `accessKeyId`, `secretAccessKey`; `--storage` and `--versioning` do not apply there.
- **Cache**: Redis-compatible, run as Valkey (`version: 8` or `9` in `system.yaml`, default 9; `--version` is for databases only). `--type redis` or `valkey` is answered with `cache`. Keys: `memory` (default `256Mi`, at least `64Mi`), `maxmemoryPolicy` (default `allkeys-lru`), `persistence` (default `false`; `true` adds an append-only file on a `storage` volume, default `1Gi`). Four variables per used cache: `REDIS_URL`, `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD` (the `url`, `host`, `port`, `password` of the Secret; with two or more caches prefixed like the others, e.g. `SESSIONS_REDIS_URL`). With `--external` the store holds the four keys `url`, `host`, `port`, `password` (use a `rediss://` URL for providers that require TLS); sizing keys do not apply there. A cache needs no operator, and cache data is not backed up (with or without `persistence`). Changing `persistence` or `storage` of a running cache: `kubectl delete statefulsets.apps <system>-<name> -n <system>-<env> --cascade=orphan`, then sync (the pod restarts; an existing volume is reused, not resized).
- **`--external [--path P]`**: the database is not run by the platform; its connection data comes from the secret store. Tell the user to put the keys `uri`, `host`, `port`, `dbname`, `user`, `password` in the store under the key `cplat` prints (default `<system>-<env>-<name>`, or `--path P`). It needs a secret store in the system.
- **Operator**: an in-cluster database needs CloudNativePG and an in-cluster bucket needs the SeaweedFS operator, which the platform installs through `operators/`. Apply `operators/root.yaml` once per cluster (`KUBE_CONTEXT=<ctx> devbox run bootstrap`; `devbox run cluster-up` does it locally). An environment that sets `operators: owner` must have the operator installed by its owner.

Observability is not a resource: it is set per environment under `environments.<env>.observability` in `system.yaml`; `resource add observability` exits 1 and says so. Removing a resource never deletes the database or the bucket data. No backups, PITR or pooling are provided (ADR-020).

> If a step fails because a platform template, script or command misbehaves (not because of the user's code), stop, summarize it in two lines and offer `/issue:report` so the user can file it. Never file anything without their OK.
