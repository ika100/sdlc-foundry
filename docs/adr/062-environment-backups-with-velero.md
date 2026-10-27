# ADR-062: An environment is backed up by Velero, installed once per cluster; persistent volumes by file-system backup; databases, caches and the target bucket are left out

**Status:** Accepted (2026-10-27)
**Builds on:** [ADR-053](053-domain-model.md) (the Environment and its properties), [ADR-058](058-pinned-versions-and-platform-installed-operators.md) (operators under `operators/`), [ADR-059](059-in-cluster-buckets-on-seaweedfs-per-instance.md), [ADR-061](061-database-backups-with-the-barman-cloud-plugin-and-restore-by-generation.md), spec 117

## Context

Spec 117 makes `backup` an Environment property, like observability: the namespace `<system>-<env>` and the contents of its volumes are backed up on a schedule to a bucket resource and kept for a retention window. Velero is the chosen tool. Databases have their own consistent backup (ADR-061) and must not be part of it, nor caches (spec 118) nor the bucket that holds the backups. Local clusters (k3d, local-path volumes) have no volume snapshots, and component volumes in `system.yaml` are `emptyDir` scratch space.

## Decision

1. **Velero is a platform operator** (`velero` chart with the AWS object-store plugin pinned in the versions table), rendered as `operators/apps/velero.yaml` when an environment without `operators: owner` sets `backup`. It is the one operator with the Argo CD resources finalizer, so it is removed from the cluster when no environment needs it any more.
2. **Each `(system, environment)` with `backup` gets its own objects in the `velero` namespace**, rendered under `applications/<system>/backup/<env>/` and synced by the Argo CD application `<system>-backup-<env>` (prune on): a `BackupStorageLocation` `<system>-<env>` (prefix `environments/<system>-<env>` in the target bucket), a `Schedule` `<system>-<env>` (cron in UTC, `ttl` = retention), a resource policy that skips `emptyDir` volumes, and the location's credentials, copied by External Secrets Operator from the bucket's Secret in `<system>-<env>` through a namespaced store with read access to that one Secret.
3. **Volumes are backed up by Velero's file-system backup (kopia, node agent), never by snapshots.** Only persistent volumes are covered; `emptyDir` volumes are skipped.
4. **Exclusions are by kind and label, not by name lists of objects:** the CloudNativePG kinds (`Cluster`, `Backup`, `ScheduledBackup`, `ObjectStore`), every object with the label `cnpg.io/cluster`, and every object whose `app.kubernetes.io/name` is the target bucket or a cache resource or whose `app.kubernetes.io/instance` is the target bucket's store.
5. **Restore is additive by default.** `/system:restore` restores only objects that are missing; when a volume of the backup still exists, it refuses and lists them, and with `--replace` it pauses the Argo CD application of each affected workload (`argocd.argoproj.io/skip-reconcile`, preserved by the ApplicationSet), deletes the workload and its volumes, lets Velero restore them, and resumes.
6. **Removing `backup` stops the schedule and removes the location; the backups stay in the bucket** (Velero does not garbage-collect backups whose location is gone).

## Consequences

- An environment backup is not a consistent database backup, and it never touches a database; the guide says so and every restore ends with that note.
- The node agent is a privileged DaemonSet in `velero`; the guard rails (namespaced, Deployments only) do not apply to it. Clusters with Pod Security `restricted` on that namespace need an exception or `operators: owner`.
- Several systems on one cluster share one Velero; each system's objects are separate and named `<system>-<env>`.
- Writing a file to an `emptyDir` component volume is not protected; persistent data belongs in a resource or a persistent volume of an external component.

## Not included

- An on-demand environment backup command, restore into another environment, cluster-wide objects (spec 117 non-goals).
- Volume snapshots (CSI) and their snapshot classes.
