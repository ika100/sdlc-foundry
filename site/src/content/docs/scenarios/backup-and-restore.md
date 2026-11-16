---
title: "Back up and restore data"
description: "Scheduled database and environment backups, a restore to a point in time, checked before anything switches."
---

**Situation.** `shop` runs in production with the database `orders-db`. You want nightly backups outside the cluster, and when someone deletes the wrong rows you want the data from 09:30 back without touching the running database first.

## Steps

Declare a bucket outside the cluster as the backup target, then the backups, in the GitOps repository:

```text
/resource:add backups --type bucket --external
/resource:backup orders-db --env prod --to backups --schedule "0 3 * * *" --retention 8w
```

The environment backup (the namespace's volumes and objects) is one line in `system.yaml`: `backup: {to: backups, schedule: "0 3 * * *", retention: 30d}` under `environments.prod`. The external bucket also needs its `remote.s3` settings there; the [backup guide](/sdlc-foundry/guides/backup-and-restore/) shows the whole block. Merge the pull requests. The first database backup runs right away, so a restore point exists at once.

To restore, work on a copy first:

```text
/resource:restore orders-db --env prod --to 2026-11-14T09:30:00Z     # a new instance next to the running one
/resource:query orders-db --env prod --copy g2 "select count(*) from orders"
/resource:restore orders-db --env prod --switch --confirm prod         # components now use the restored copy
/resource:restore orders-db --env prod --discard --confirm prod        # remove the previous instance when you are sure
```

## What you get

- Database backups with continuous archiving: you restore to any point in the retention window, not only to last night.
- A restore never overwrites the running database. It creates a new generation (`g2`) that you read with `/resource:query` before anything switches.
- In prod, `--switch` and `--discard` first print what they would do and change nothing until you add `--confirm prod`.
- Environment backups cover the namespace's volumes, such as a bucket store or broker data. `/system:restore prod` lists them, and `/system:restore prod --backup latest --confirm prod` restores one. It never restores a database: databases come back only through `/resource:restore`.

## Check it

- `/system:status` shows the last backup, whether archiving works and the restore window (earliest and latest point in time) per database and environment.
- `/platform:doctor` warns when prod backups live in the cluster they protect, and when something runs in prod without a backup.
- When a backup has failed for more than an hour, the alert poll opens an issue for it (environments with alerts on).

Every journey on [Watch a real run](/sdlc-foundry/get-started/watch-a-run/) ends with this restore drill in prod.

## Limits to know

Cache data is not backed up. An external database is backed up by its provider. Moving data from one cluster to another is not covered. Details are in [Backup and restore](/sdlc-foundry/guides/backup-and-restore/).
