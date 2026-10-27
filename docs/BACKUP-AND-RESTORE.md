# Backup and restore

Two kinds of backup exist, and they cover different data (spec 117, [ADR-060](adr/060-database-backups-with-the-barman-cloud-plugin-and-restore-by-generation.md), [ADR-061](adr/061-environment-backups-with-velero.md)). Both write to a **bucket resource** of the system, and both are declared in `system.yaml`.

| Data | Covered by | Not covered |
|---|---|---|
| A database (in-cluster `type: database`) | A database backup: base backups plus continuous WAL archiving (CloudNativePG with the Barman Cloud plugin). Restores to a point in time | |
| Persistent volumes of the environment's namespace (for example the store of an in-cluster bucket) | An environment backup (Velero, file-system backup of volumes) | `emptyDir` volumes: they hold scratch data and are skipped |
| Kubernetes objects of the namespace (the system's workloads, Services, ConfigMaps) | An environment backup | Anything git already declares is recreated by Argo CD; the backup is for the state around it |
| An external database | Its provider | The platform renders no backup for it; an external database is backed up by its provider |
| Cache data | Nothing | Cache data is not backed up: a cache is rebuilt from its source |
| An external bucket (the data in it) | Its provider | Only the use of a bucket as a backup *target* is supported |

An environment backup is not a consistent database backup: it copies files of a running database. Databases are restored only with `/resource:restore`; `/system:restore` never restores one and says so.

## Declare it

```yaml
environments:
  prod:
    backup: {to: backups, schedule: "0 3 * * *", retention: 30d}
resources:
  orders-db:
    type: database
    instances:
      prod:
        backup: {to: backups, retention: 8w}
  backups:
    type: bucket
    external: true
    remote:
      s3: {endpoint: "https://s3.eu-central-1.amazonaws.com", bucket: acme-backups, region: eu-central-1, forcePathStyle: false}
```

- `to` names a bucket resource of the system that has an instance in that environment (a component that runs there uses it).
- `schedule` is a five-field cron in UTC with numbers only (default `0 3 * * *`); `retention` is `<n>d` or `<n>w` (default `30d`).
- `backup` sits on an environment and on `instances.<env>` of a database, never on the resource itself. An external database takes none.
- `remote.s3` (`endpoint`, `bucket`, `region`, `forcePathStyle`, all four) is required when the target bucket is `external: true`: the backup objects take these as literal values, so they live in git (they are not secret). The keys stay in the secret store.
- The first scheduled database backup runs right after `backup` is set, so a restore point exists at once.
- For prod, put the target in an external bucket. `/platform:doctor` warns when prod backups live in the cluster they protect (`backup location`) and when something runs in prod without a backup (`backup prod`).

The platform installs what backups need (the Barman Cloud plugin, cert-manager, Velero) from `operators/`. After the first backup in a cluster, apply `operators/root.yaml` once (`devbox run bootstrap`; `cluster-up` does it locally). A cluster that owns these operators sets `environments.<env>.operators: owner`.

## Back up a database now

```
/resource:backup orders-db --env prod
```

Waits until the base backup finishes (up to 30 minutes). Scheduled backups need no command.

## Restore a database

A restore never touches the running database. It creates a new instance next to it, in steps:

```
/resource:restore orders-db --env staging --to 2026-10-27T09:30:00Z   # point in time (or --to latest)
/resource:restore orders-db --env staging --switch                    # components use the restored instance
/resource:restore orders-db --env staging --discard                   # remove the restored (or the previous) instance
```

1. `--to` restores a point in time from the backups into a new instance `<system>-<db>-g<n>` and prints how to look at it. Components still use the active one.
2. `--switch` makes the restored instance the active one and restarts the pods of the components that use the database. The old one stays as `previous` until you discard it.
3. `--discard` removes the restored or previous instance and its volumes. The backups in the bucket stay.

The commands change git and the cluster in one step: with Argo CD they open a PR, wait for CI and merge it; without Argo CD they commit and apply. The working tree must be clean.

In prod, `--switch` and `--discard` first print what they would do and change nothing; add `--confirm prod` to do it.

## Restore an environment

```
/system:restore prod                                  # list the backups, newest first
/system:restore prod --backup latest --confirm prod   # restore into the namespace
/system:restore prod --backup <name> --replace --confirm prod
```

- Without `--backup` it lists the backups and their state.
- Objects and volumes that already exist are left alone. When volumes of the backup still exist, the command stops and names them; `--replace` stops the workloads that own them, replaces the volumes from the backup and starts the workloads again.
- Databases are not part of an environment backup: every output ends by pointing to `/resource:restore`.

## See and alert

- `/system:status` shows, from the cluster, the last backup, whether WAL archiving works, the restore window (earliest and latest point in time) and any restored or previous instance, per database and per environment.
- When a backup or WAL archiving has failed for more than an hour, the alert poll opens one issue, `[auto] [alert] backup failing: <db or environment>/<env>`, for environments with `observability` alerts on.
- Right after you turn on `backup` for a database that already runs, the database restarts once to load the backup plugin, so the very first scheduled backup cannot run. Status then says `last base backup never (first backup pending)`, not "failing". cplat takes the first base backup by itself as soon as the plugin is loaded: at the end of `/resource:restore --switch`, or in the next alert poll. `/resource:backup` always works too.
