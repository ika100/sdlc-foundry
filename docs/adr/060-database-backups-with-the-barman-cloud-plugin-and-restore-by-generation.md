# ADR-060: Databases are backed up by the CloudNativePG Barman Cloud plugin to a bucket resource; a point-in-time restore is a new generation next to the running one

**Status:** Accepted (2026-10-27)
**Builds on:** [ADR-057](057-named-typed-resources-with-fixed-contracts.md) (named, typed resources; the Secret `<system>-<name>-app`), [ADR-058](058-pinned-versions-and-platform-installed-operators.md) (pinned versions, operators under `operators/`), [ADR-059](059-in-cluster-buckets-on-seaweedfs-per-instance.md) (the bucket resource), spec 117; used by spec 121 (a fresh backup before a major upgrade)

## Context

Spec 117 adds continuous, point-in-time backups for in-cluster databases (CloudNativePG clusters `<system>-<name>`) to a bucket resource, an on-demand backup, and a restore that runs next to the live database and is switched to in a second step. The components must keep using the Secret `<system>-<name>-app` without a change to their configuration.

Facts that shape the decision:

- CloudNativePG deprecated its built-in Barman Cloud support; the Barman Cloud plugin (`plugin-barman-cloud` chart, `ObjectStore` resource) is the supported path from 1.26 on, and it needs cert-manager for the TLS between plugin and operator.
- `ObjectStore` and Velero locations take the bucket, the endpoint and the region as literal values, not from a Secret. An external bucket's coordinates live only in the secret store today.
- CloudNativePG cannot rename a cluster, and it writes and owns `<cluster>-app` (host `<cluster>-rw`). A restored cluster has another name, so its own Secret and host differ.
- CloudNativePG refuses to archive into a server path that already holds WAL of another cluster, so every restored cluster needs a new server name.
- Argo CD prunes nothing in the addon applications (`prune: false`) but heals every object that git describes. Anything that must survive a re-sync has to be in git.

## Decision

1. **The Barman Cloud plugin archives WAL and takes base backups.** A database instance with `backup` gets an `ObjectStore` `<system>-<name>` (destination `s3://<bucket>/databases`, the bucket's Secret for the keys, `retentionPolicy` = `retention`), the plugin as WAL archiver on its active cluster, and a `ScheduledBackup` `<system>-<name>` (`immediate: true`, method `plugin`). The plugin chart and cert-manager are platform operators under `operators/` (ADR-058), rendered only when a database instance in an environment without `operators: owner` sets `backup`. `/resource:backup` creates one `Backup` object and waits for it.
2. **An external bucket used as a backup target declares its non-secret coordinates in git** (`remote.s3: {endpoint, bucket, region, forcePathStyle}`). The keys still come only from the secret store.
3. **A restore creates a new generation.** The original cluster is generation 0 (`<system>-<name>`); restore n is the cluster `<system>-<name>-g<n>`, bootstrapped by `recovery` from the bucket (`targetTime`, or no target for `latest`), with its owner password taken from `<system>-<name>-app`. Generation numbers are never reused, so each cluster archives under its own server name. The restored generation archives nothing until it is switched to.
4. **The generations live in git**, in `applications/<system>/addons/<env>/<name>/restore-state.yaml`, which only `cplat resource restore` writes and `render.py` reads, like the image pins in the overlays. Each restore action is one commit: in a cluster that Argo CD manages, a pull request that the command merges after CI and then waits for; in a cluster without Argo CD (the end-to-end test), a local commit and `kubectl apply -k` of the addon directory.
5. **A switch detaches the connection Secret.** `--switch` makes the restored generation active in git (WAL archiving and the scheduled backup move to it), removes the owner reference of `<system>-<name>-app` and rewrites its host keys to the new `-rw` service, then restarts the using components' pods. From then on no operator manages that Secret: every generation is created with `recovery.secret: <system>-<name>-app`, so CloudNativePG never writes it again. The old generation stays as `previous` until `--discard`, which removes it from git and deletes the cluster and its volumes; the backups in the bucket are never deleted by a restore command.

## Consequences

- A cluster that needs backups runs two more platform operators (the plugin in `cnpg-system`, cert-manager). A cluster whose owner already runs cert-manager sets `operators: owner` and installs the plugin itself.
- Restore points before a switch are read from the old generation's server name; once a `previous` generation is discarded, nothing prunes its old backups any more (they stay in the bucket, by design never deleted by the platform).
- After the first switch, the connection Secret of that database is outside every operator. Rebuilding the environment from git alone needs that Secret back (a later spec may own it).
- A database without `backup` and without restores renders byte-identically to spec 115.

## Not included

- Logical dumps, single-table restore, restore into another environment or system (spec 117 non-goals).
- Backups of external databases: their provider does it.
- Encryption beyond what the bucket provides, replication of backups.
