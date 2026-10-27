---
spec_id: 117-databases-and-environments-are-backed-up
spec_hash: d94c1aa3145f
summary: "Backups and restores (additive 5.x): instances.<env>.backup on a database renders a Barman Cloud ObjectStore, the plugin as WAL archiver and a ScheduledBackup (immediate, 03:00 UTC, 30d by default) to a bucket resource; environments.<env>.backup renders per system and environment a Velero location, schedule (file-system backup of persistent volumes, databases, caches and the target bucket left out) and synced credentials under backup/<env>/; external targets declare remote.s3; plugin-barman-cloud, cert-manager and velero are pinned operators under operators/ unless operators: owner; /resource:backup, /resource:restore (--to, --switch, --discard, generations <system>-<db>-g<n> in restore-state.yaml, the connection Secret repointed) and /system:restore (list, missing objects, --replace); status, model, doctor warnings and operator rows, backup-failing alert issues, cluster-up, bootstrap and the e2e proof follow; a system.yaml without the new keys renders byte-identically"
tasks:
  - id: t1
    title: render.py — backup schema and checks (environment and database-instance backup, to/schedule/retention, external database refusal, bucket remote.s3, defaults in the renderer API)
    files: [templates/gitops-app/scripts/render.py]
    covers: [AC-117.1, AC-117.2, AC-117.5, AC-117.15, AC-117.16, AC-117.26]
    parallel_safe: true
    depends_on: []
  - id: t2
    title: render.py — database backup objects (ObjectStore, plugin WAL archiver, ScheduledBackup) and generations from restore-state.yaml
    files: [templates/gitops-app/scripts/render.py]
    covers: [AC-117.1, AC-117.3, AC-117.4, AC-117.8, AC-117.9, AC-117.10, AC-117.13, AC-117.22]
    parallel_safe: false
    depends_on: [t1]
  - id: t3
    title: render.py — environment backup objects under backup/<env>/, the backup ApplicationSet, preservedFields, target-bucket exclusion labels, stale handling
    files: [templates/gitops-app/scripts/render.py]
    covers: [AC-117.15, AC-117.17, AC-117.22]
    parallel_safe: false
    depends_on: [t2]
  - id: t4
    title: render.py — operators plugin-barman-cloud, cert-manager and velero in the versions table and under operators/ (values, finalizer, retry)
    files: [templates/gitops-app/scripts/render.py]
    covers: [AC-117.15, AC-117.22, AC-117.26, AC-117.30]
    parallel_safe: false
    depends_on: [t3]
  - id: t5
    title: model — backup on database resource instances and environments (JSON and model show text)
    files: [scripts/cplat/model.py, scripts/cplat/modelcmd.py]
    covers: [AC-117.7]
    parallel_safe: true
    depends_on: []
  - id: t6
    title: backupstate — read database and environment backup state from the cluster, restore points, Velero and pod-volume backups, restore-state.yaml read/write
    files: [scripts/cplat/backupstate.py]
    covers: [AC-117.6, AC-117.18, AC-117.27]
    parallel_safe: true
    depends_on: []
  - id: t7
    title: system status — backup rows in the table and the backups section of --json
    files: [scripts/cplat/status.py]
    covers: [AC-117.6, AC-117.9, AC-117.18, AC-117.27]
    parallel_safe: true
    depends_on: [t5, t6]
  - id: t8
    title: cplat resource backup (on-demand base backup) and the registration of resource backup, resource restore and system restore
    files: [scripts/cplat/dbbackup.py, scripts/cplat/cplat.py]
    covers: [AC-117.31, AC-117.32]
    parallel_safe: true
    depends_on: [t6]
  - id: t9
    title: cplat resource restore — --to, --switch, --discard through git (PR or commit) and the cluster, prod confirmation
    files: [scripts/cplat/dbrestore.py]
    covers: [AC-117.8, AC-117.9, AC-117.10, AC-117.11, AC-117.12, AC-117.13, AC-117.14]
    parallel_safe: true
    depends_on: [t2, t6, t8]
  - id: t10
    title: cplat system restore — list backups, restore missing objects, refuse or --replace existing volumes, prod confirmation
    files: [scripts/cplat/envrestore.py]
    covers: [AC-117.14, AC-117.19, AC-117.20, AC-117.21]
    parallel_safe: true
    depends_on: [t6, t8]
  - id: t11
    title: platform doctor — prod has no backup, prod backups in the same cluster, operator rows for plugin-barman-cloud, cert-manager and velero
    files: [scripts/cplat/doctor.py]
    covers: [AC-117.23, AC-117.29, AC-117.30]
    parallel_safe: true
    depends_on: [t4, t5]
  - id: t12
    title: alert poll — one "backup failing" issue per database or environment backup failing for more than an hour
    files: [scripts/cplat/alertsources.py, scripts/cplat/alerts.py, scripts/cplat/alertissues.py]
    covers: [AC-117.28]
    parallel_safe: true
    depends_on: [t5, t6]
  - id: t13
    title: gitops-app template — cluster-up and bootstrap install or wait for cert-manager, the Barman Cloud plugin and Velero
    files: [templates/gitops-app/scripts/local-cluster.sh, templates/gitops-app/scripts/bootstrap.sh, templates/gitops-app/CLAUDE.md.jinja]
    covers: [AC-117.15, AC-117.26]
    parallel_safe: true
    depends_on: []
  - id: t14
    title: e2e — point-in-time restore and switch of a database, environment backup and --replace restore of a component volume and a bucket
    files: [tests/e2e/run.sh]
    covers: [AC-117.8, AC-117.9, AC-117.20, AC-117.24, AC-117.31]
    parallel_safe: false
    depends_on: [t3, t4, t7, t9, t10, t13]
  - id: t15
    title: resource plugin 1.3.0 and system plugin 1.1.0 (new commands, READMEs, manifests, catalog) and the CHANGELOG [Unreleased] entry
    files: [plugins/resource/commands/backup.md, plugins/resource/commands/restore.md, plugins/resource/README.md, plugins/resource/.claude-plugin/plugin.json, plugins/system/commands/restore.md, plugins/system/commands/status.md, plugins/system/README.md, plugins/system/.claude-plugin/plugin.json, .claude-plugin/marketplace.json, docs/CHANGELOG.md]
    covers: [AC-117.8, AC-117.19, AC-117.31]
    parallel_safe: true
    depends_on: []
  - id: t16
    title: Docs — DOMAIN-MODEL.md (backup on Environment and on a database instance), the backup-and-restore guide, USER-JOURNEY.md, the site's resources page
    files: [docs/DOMAIN-MODEL.md, docs/BACKUP-AND-RESTORE.md, docs/USER-JOURNEY.md, site/src/content/docs/concepts/addons.md]
    covers: [AC-117.25]
    parallel_safe: true
    depends_on: []
  - id: t17
    title: Amend the spec 114/115 assertions that 117 extends (key lists with backup, the model's backup field, the command count)
    files: [tests/cplat/test_plugins_114.py, tests/cplat/test_system_model_114.py, tests/cplat/test_system_render_114.py, tests/cplat/test_resources_115.py, tests/cplat/test_resources_115_cmds.py]
    covers: [AC-117.2, AC-117.7, AC-117.15]
    parallel_safe: true
    depends_on: []
human_steps:
  - "Consumer note for the release: after the first backup in a cluster, re-apply operators/root.yaml once (KUBE_CONTEXT=<ctx> devbox run bootstrap; local clusters: devbox run cluster-up). A cluster that already runs cert-manager or Velero (or wants to install the Barman Cloud plugin itself) sets environments.<env>.operators: owner first."
  - "Velero's node agent is a privileged DaemonSet in the velero namespace: clusters that enforce Pod Security restricted there need an exception (or operators: owner)."
---

# Plan — 117 Databases and environments are backed up and restorable

The contract (schema, error texts, rendered objects, pins, CLI flags and outputs, status, doctor, alerts) is in
[design.md](design.md). The lasting decisions are
[ADR-061](../../adr/061-database-backups-with-the-barman-cloud-plugin-and-restore-by-generation.md) (database backups and restore by
generation) and [ADR-062](../../adr/062-environment-backups-with-velero.md) (environment backups with Velero). It builds on spec 115
(ADR-057/058) and spec 116 (ADR-059). Levels: t1, t5, t6, t13, t15, t16, t17 → t2, t7, t8, t12 → t3, t9, t10 → t4 → t11, t14.

`render.py` changes in four sequential tasks (t1 → t2 → t3 → t4). Every other task owns its files. Never edit
`scripts/cplat/assets/render_v4.py`. Every 5.0/115/116 `system.yaml` without the new keys must render byte-identically; the 115 and
116 suites, amended only by t17, prove that. Commands read the cluster only through `backupstate.py`'s kubectl seam, so every
command test runs without a cluster.

## t1 — render.py: backup schema and checks

**Files:** templates/gitops-app/scripts/render.py
**Covers:** AC-117.1, AC-117.2, AC-117.5, AC-117.15, AC-117.16, AC-117.26
**Goal:** `backup` is accepted on environments and database instances and `remote.s3` on buckets, and every invalid form fails with
the texts of design.md (Render errors) before anything is written. Nothing new is rendered yet.

**Implementation notes:**
- `ENV_KEYS` and `RESOURCE_INSTANCE_KEYS` gain `backup` (last). `BACKUP_KEYS = ["to", "schedule", "retention"]`,
  `BACKUP_DEFAULTS = {"schedule": "0 3 * * *", "retention": "30d"}`, `BUCKET_REMOTE_KEYS = [*REMOTE_KEYS, "s3"]`,
  `S3_KEYS = ["endpoint", "bucket", "region", "forcePathStyle"]`, `RETENTION = re.compile(r"^[1-9][0-9]*[dw]$")`, a `cron_ok(text)`
  helper with the field ranges of design.md.
- `validate_resource`: for a database instance that is external and has `backup`, the AC-117.5 text before the unknown-key check.
  `check_remote` takes the allowed keys per type; a bucket's `remote.s3` is checked with the design texts.
- New `validate_backups(doc, env_conf, resources, comps)` called after `validate_uses`, in the design's order; it needs the resource
  instances (a running component uses the bucket in that environment), so build them from `comps` like `resource_instances`.
- Normalise: `cfg["backup"]`, `envs[e]["backup"]` for databases, `envs[e]["s3"]` for buckets (defaults filled; `None` where absent).
- Update the module docstring's `environments:` and `resources:` blocks with a `backup` and a `remote.s3` example.

**Done when:** the render-error tests of AC-117.2, AC-117.5, AC-117.16 and AC-117.26 (a version key is an unknown key) pass, the
defaults of AC-117.1 appear in `load_system`, and the 115/116 render suites stay green after t17.

## t2 — render.py: database backup objects and generations

**Files:** templates/gitops-app/scripts/render.py
**Covers:** AC-117.1, AC-117.3, AC-117.4, AC-117.8, AC-117.9, AC-117.10, AC-117.13, AC-117.22
**Goal:** a database instance with `backup` gets `objectstore.yaml`, `scheduledbackup.yaml` and the plugin on its active cluster;
the clusters of `restore-state.yaml` are rendered as designed; without `backup` and without a state file the directory is
byte-identical to spec 115.

**Implementation notes:**
- `read_restore_state(app_dir, env, db)` parses and validates `addons/<env>/<db>/restore-state.yaml` (design rules; error text as
  designed); absent = one active cluster `<system>-<db>`.
- `database_cluster` takes the cluster name, role, `from` and whether backup is on; generation clusters get `bootstrap.recovery` and
  `externalClusters` (key order as designed, `recoveryTarget` omitted for `latest`); `plugins` only for active/previous with backup.
- `addon_files` for a database: one file per cluster (`cluster.yaml` for generation 0, `cluster-g<n>.yaml` otherwise), the two
  backup files, and `kustomization.yaml` listing every rendered file sorted. The target bucket's coordinates come from `<B>` of
  design.md (in-cluster endpoint, or `envs[e]["s3"]`). `ScheduledBackup.spec.schedule` = `"0 " + schedule`.
- The ApplicationSet `<system>-addons-<env>` gets `syncPolicy.retry` only when an instance in that environment has `backup`.
- `stale_paths` must not remove `restore-state.yaml` (it is not in `wanted`; leave non-managed files of a wanted addon dir alone —
  check the current behaviour and keep it).
- `ADDON_FILES`, if used for a database directory, is extended accordingly.

**Done when:** the render tests of AC-117.1 (objects, schedule, retention, defaults), AC-117.3 (`retentionPolicy`), AC-117.4 (no
plugin, no ObjectStore, nothing for any bucket), AC-117.8–AC-117.10/AC-117.13 (fixture state files: restored, switched, discarded
render the designed clusters and plugin placement) and AC-117.22 (removing `backup` removes the backup files and the plugin, keeps
the clusters) pass. A 115 fixture still renders byte-identically.

## t3 — render.py: environment backup objects

**Files:** templates/gitops-app/scripts/render.py
**Covers:** AC-117.15, AC-117.17, AC-117.22
**Goal:** an environment with `backup` gets `backup/<env>/` (eight objects and `kustomization.yaml`), the ApplicationSet
`<system>-backup-<env>` and `preservedFields` on its component and addon ApplicationSets; the target bucket's Secret carries its
labels; without `backup` nothing changes.

**Implementation notes:**
- `backup_files(app, env, cfg)` returns the documents of design.md (Schedule with `excludedResources`, the three-expression
  `labelSelector`, `ttl` hours from `<n>d`/`<n>w`, `resourcePolicy`). The NotIn name list is the target bucket plus every `cache`
  resource name (none renders today).
- In `render_app`, append the backup ApplicationSet after the policy ones; add `preservedFields` after `template` in `<system>-<env>`
  and `<system>-addons-<env>` only for environments with `backup`.
- `bucket_files` and `external_secrets` add `target.template.metadata.labels` (and for the external one `engineVersion: v2,
  mergePolicy: Merge`) only for the bucket that is `backup.to` of that environment.
- `stale_paths`: handle `backup` like `policies` (per-environment directory; whole tree when nothing is wanted).

**Done when:** the render tests of AC-117.15 (objects per environment, credentials from the bucket's Secret, BSL for in-cluster and
external targets), AC-117.17 (exclusions present, target labels) and AC-117.22 (removing `backup` removes `backup/<env>/` and the
ApplicationSet) pass; 115/116 fixtures render byte-identically.

## t4 — render.py: the three operators

**Files:** templates/gitops-app/scripts/render.py
**Covers:** AC-117.15, AC-117.22, AC-117.26, AC-117.30
**Goal:** `operators/apps/plugin-barman-cloud.yaml` and `cert-manager.yaml` exist exactly when an in-cluster database instance with
`backup` runs in an environment without `operators: owner`; `velero.yaml` exactly when such an environment has `backup`; all pinned
as designed.

**Implementation notes:**
- `VELERO_AWS_PLUGIN_IMAGE` and the three `OPERATORS` entries in design order. Re-check every pin against the indexes and Docker Hub
  before committing, and run `helm template` of each chart for the checks listed in design.md; follow the pinned charts and update
  design.md in the same PR where they differ.
- `operator_files`: compute needs from `cfg["backup"]` and the database instances' `backup`; add `valuesObject`, `finalizers` and
  `retry` from the entry's optional keys. The `cloudnative-pg` and `seaweedfs` documents stay byte-identical.

**Done when:** the AC-117.26 tests (present only when needed, exact pins, no range, absent with `operators: owner`), the AC-117.30
render half (backups still render with `operators: owner`) and AC-117.22 (velero.yaml removed with the last environment backup, its
finalizer) pass; the 115/116 operator tests stay green.

## t5 — model: backup fields

**Files:** scripts/cplat/model.py, scripts/cplat/modelcmd.py
**Covers:** AC-117.7
**Goal:** `ResourceInstance.backup` and `Environment.backup` as designed, in `to_dict` and in `cplat model show` text.

**Implementation notes:**
- Lenient like the rest of `build`: a mapping with a string `to` gives `{"to", "schedule", "retention"}` with defaults; anything else
  or an external/non-database instance gives `None`.
- Text: append the designed suffix only when set; every other line stays as it is.

**Done when:** the AC-117.7 model tests (JSON field with defaults, `null` without backup, schema 2, no cluster state) pass, and the
renderer–model agreement test stays green.

## t6 — backupstate: reading the cluster

**Files:** scripts/cplat/backupstate.py
**Covers:** AC-117.6, AC-117.18, AC-117.27
**Goal:** one module that computes the values of the status contract and the facts the commands and the alert poll need, from
`kubectl` output through one seam.

**Implementation notes:**
- Seam `kubectl(args, context) -> (rc, out, err)` (never raises), as in `alertsources`. Times are parsed and printed as RFC 3339 UTC
  ending in `Z`.
- `restore_state(app_dir, env, db)` / `write_restore_state(...)` in the design's format (comment header kept, rules checked).
- `database_state(...)`: clusters (`Ready`, `ContinuousArchiving`), `Backup`s (newest completed / failed), `ObjectStore`
  `serverRecoveryWindow`, `pg_stat_archiver.last_archived_time` via `kubectl exec` on the active primary; returns the JSON shape of
  design.md including `restored`/`previous`, plus the per-server windows the restore command uses.
- `environment_state(...)`, `velero_backups(...)` (newest first, state mapping), `pod_volume_backups(backup)`,
  `existing_volumes(...)` and `workload_root(...)` for `/system:restore`.
- `failing_since(...)` for the alert poll (the three rules of design.md).

**Done when:** the unit tests for each reader with recorded kubectl JSON pass (ok, failing, never, off, unknown; restore window over
two generations).

## t7 — system status: backups

**Files:** scripts/cplat/status.py
**Covers:** AC-117.6, AC-117.9, AC-117.18, AC-117.27
**Goal:** the text lines and the `backups` JSON of design.md; no cluster read and no text change when nothing has backup.

**Implementation notes:**
- `collect` gains the backups block from the model and `backupstate`; the context is `--context`, else the current one.
- `render_table` appends the Backups section only when something is configured; `main --json` always includes `backups`.

**Done when:** the AC-117.6, AC-117.18 and AC-117.27 status tests (text and JSON, `off`, `never`, `previous`, `unknown`) pass and
the existing status tests stay green.

## t8 — cplat resource backup and the registrations

**Files:** scripts/cplat/dbbackup.py, scripts/cplat/cplat.py
**Covers:** AC-117.31, AC-117.32
**Goal:** `/resource:backup <db> --env <env>` as designed; `cplat.py` maps `resource backup` → `dbbackup`, `resource restore` →
`dbrestore`, `system restore` → `envrestore` and lists them in its docstring.

**Implementation notes:**
- Checks in the design's order before any kubectl call; the active cluster comes from `backupstate.restore_state`.
- Poll interval and timeout are module constants (tests patch them).

**Done when:** the AC-117.31 tests (completed with time, `backup.last_success` read back by status, failed, timeout) and the
AC-117.32 refusals pass.

## t9 — cplat resource restore

**Files:** scripts/cplat/dbrestore.py
**Covers:** AC-117.8, AC-117.9, AC-117.10, AC-117.11, AC-117.12, AC-117.13, AC-117.14
**Goal:** `--to`, `--switch` and `--discard` exactly as designed, through the Argo path or the apply path, with every refusal before
any change.

**Implementation notes:**
- Use `addon.py`'s pattern (`Report`, `--dry-run`, `--json`, `gitops.require_clean`). The Argo path is chosen when the Argo CD
  application `addon-<db>-<env>` exists in the context.
- State changes through `backupstate.write_restore_state`, then `gitops.render`, then one commit (`core.git_identity`).
- Switch: Secret patch as a JSON patch (remove `ownerReferences`, replace the listed keys' values), then delete the users' pods
  (users from the model: running components in `<env>` with `<db>` in `uses`).
- Prod: `--switch`/`--discard` refuse without `--confirm prod` with the designed text; `--to` does not need it.

**Done when:** the command tests for AC-117.8 (state, commit, apply, output), AC-117.9 (state, Secret patch, pods deleted, previous),
AC-117.10, AC-117.11 (each refusal), AC-117.12 (failure and timeout keep the instance), AC-117.13 (the switched cluster gets the
plugin and the ScheduledBackup) and AC-117.14 pass with a fake kubectl and a local git repo.

## t10 — cplat system restore

**Files:** scripts/cplat/envrestore.py
**Covers:** AC-117.14, AC-117.19, AC-117.20, AC-117.21
**Goal:** list, restore missing objects, refuse or `--replace` existing volumes, as designed; every restore output ends with the
database line.

**Implementation notes:**
- Volumes and workload roots from `backupstate`; pausing writes and removes `argocd.argoproj.io/skip-reconcile` only on applications
  that exist; the annotation is removed even when the restore fails.
- Restore object name `<backup>-<YYYYMMDDHHMMSS>`; timeout constant patched by tests.

**Done when:** the AC-117.19 (list), AC-117.20 (missing only, refusal listing volumes, `--replace` order of actions, database line),
AC-117.21 (each refusal) and AC-117.14 (prod) tests pass.

## t11 — platform doctor: backup rows

**Files:** scripts/cplat/doctor.py
**Covers:** AC-117.23, AC-117.29, AC-117.30
**Goal:** the `backup prod` and `backup location` warnings and the three operator rows of design.md.

**Implementation notes:**
- `check_backups(repo)` from the models (no kubectl); called next to `check_operators` in both branches of `check_repo`.
- `check_operators` loops over a table that adds `plugin-barman-cloud`, `cert-manager`, `velero` with their needs; `_operator_row`
  compares versions without a leading `v`. The 115/116 texts stay byte-identical.

**Done when:** the AC-117.23, AC-117.29 and AC-117.30 doctor tests pass (render still succeeds in the same fixtures) and 115/116
doctor tests stay green.

## t12 — alert poll: backup failing

**Files:** scripts/cplat/alertsources.py, scripts/cplat/alerts.py, scripts/cplat/alertissues.py
**Covers:** AC-117.28
**Goal:** one issue `[auto] [alert] backup failing: <db or environment>/<env>` per failure older than one hour, none while it is
open, none with `alerts: false`.

**Implementation notes:**
- `alertsources.backup_alerts(cfg, now)` uses `backupstate.failing_since`; `load_app` records the backup environments (observability
  present, alerts not false, some backup configured) even when their metrics source is skipped.
- `alerts.poll`: an app whose metrics are skipped but has backup environments is not skipped; its alerts are the backup alerts.
- `alertissues.title` special-cases the name `backup failing`.

**Done when:** the AC-117.28 tests (after 59 vs 61 minutes, deduplication, alerts off, metrics skipped) pass and the spec 092 poll
tests stay green.

## t13 — gitops-app template: cluster-up and bootstrap

**Files:** templates/gitops-app/scripts/local-cluster.sh, templates/gitops-app/scripts/bootstrap.sh, templates/gitops-app/CLAUDE.md.jinja
**Covers:** AC-117.15, AC-117.26
**Goal:** local clusters (with or without Argo CD) and real clusters get cert-manager, the plugin and Velero before anything that
needs them syncs.

**Implementation notes:**
- Variables, defaults, HelmCharts and waits as designed; the Velero HelmChart's `valuesContent` equals the versions-table values
  (comment that they must match render.py). Header comments list the new variables.
- `CLAUDE.md.jinja`: `operators/` lists the three new operators; one line on `backup/<env>/` and `restore-state.yaml`.
- `bash -n` and shellcheck stay clean.

**Done when:** the template text tests of AC-117.15/AC-117.26 pass and t14's run installs the operators through this script.

## t14 — e2e: backups in the cluster

**Files:** tests/e2e/run.sh
**Covers:** AC-117.8, AC-117.9, AC-117.20, AC-117.24, AC-117.31
**Goal:** AC-117.24 end to end, failing with the step's name.

**Implementation notes:**
- Cluster-up gets `WITH_BARMAN_CLOUD=1 WITH_VELERO=1` (operators/ is written later). Check the three `operators/apps` files and their
  pins only after the step that makes a component use the resources, as for SeaweedFS.
- After the external-bucket steps: `cplat resource add backups --type bucket` (commit), e2e-web uses `backups`, `postgres` gets
  `instances.dev.backup`, `environments.dev.backup`, the external component `e2e-files` (package written into the gitops repo),
  render, commit. Each `cplat` write starts from a clean tree.
- Apply in order: the `backups` bucket addon (generalise `apply_bucket` to a bucket name), the postgres addon, `backup/dev` (without
  `-n`), the `e2e-files` and e2e-web overlays; wait for the immediate base backup.
- Database: `cplat resource backup postgres --env dev` → `backup completed`; status `last_success` matches; rows A/B around T,
  `pg_switch_wal()`, wait for `latest` ≥ T; restore, switch (cplat commits itself), read with a pod carrying e2e-api's database
  variables (pinned postgres image); discard; status no longer shows previous.
- Environment: file on the PVC, object in `files` via the e2e-api probe, a Velero `Backup` from the Schedule's template; delete
  both; refusal lists the volumes; `--replace`; read back; the active database cluster keeps its UID.

**Done when:** `tests/e2e/run.sh` passes on a local machine with the release candidate. Record the run in the verification.

## t15 — plugins and the CHANGELOG entry

**Files:** plugins/resource/commands/backup.md, plugins/resource/commands/restore.md, plugins/resource/README.md, plugins/resource/.claude-plugin/plugin.json, plugins/system/commands/restore.md, plugins/system/commands/status.md, plugins/system/README.md, plugins/system/.claude-plugin/plugin.json, .claude-plugin/marketplace.json, docs/CHANGELOG.md
**Covers:** AC-117.8, AC-117.19, AC-117.31
**Goal:** three new slash commands that run the `cplat` forms; the release is announced as minor and not breaking.

**Implementation notes:**
- Descriptions under 260 characters with `Usage:` lines: `/resource:backup <db> --env <env>`,
  `/resource:restore <db> --env <env> (--to <time|latest> | --switch | --discard) [--confirm prod]`,
  `/system:restore <env> [--backup <name|latest>] [--replace] [--confirm prod]`; bodies follow `remove.md`'s shape (preview with
  `--dry-run` where it exists, run, say what stays). `status.md` mentions the Backups section.
- `resource` 1.2.0 → 1.3.0, `system` 1.0.0 → 1.1.0 in both manifests and the catalog.
- CHANGELOG `## [Unreleased]`: a new 117 entry **above** the existing 116 and 115 entries, which stay untouched: what is backed up,
  ADR-061/061, the pins (plugin-barman-cloud 0.8.1, cert-manager v1.21.3, velero 12.2.1, velero-plugin-for-aws v1.14.4), the
  plugins line, and the Action of `human_steps`. Not BREAKING.

**Done when:** `devbox run validate` and the version-match loop of `devbox run quality` are green, and the amended AC-114.59 test
(t17) passes.

## t16 — Docs

**Files:** docs/DOMAIN-MODEL.md, docs/BACKUP-AND-RESTORE.md, docs/USER-JOURNEY.md, site/src/content/docs/concepts/addons.md
**Covers:** AC-117.25
**Goal:** the model lists `backup` as an Environment property next to observability and as a key of a database's
`instances.<env>`; a guide explains both kinds of backup.

**Implementation notes:**
- `BACKUP-AND-RESTORE.md`: what each kind covers (table), that an environment backup is not a consistent database backup, databases
  only through `/resource:restore`, external databases by their provider, cache data not backed up, emptyDir not covered,
  `remote.s3` for external targets, the commands with examples, prod confirmation, doctor warnings, alerts.
- Link it from `DOMAIN-MODEL.md` and `USER-JOURNEY.md`; keep the needles of AC-115.16's and 116's doc tests.
- `python3 scripts/check-links.py` stays green.

**Done when:** the AC-117.25 documentation test passes and the 115/116 doc tests stay green.

## t17 — amend the spec 114/115 assertions that 117 extends

**Files:** tests/cplat/test_plugins_114.py, tests/cplat/test_system_model_114.py, tests/cplat/test_system_render_114.py, tests/cplat/test_resources_115.py, tests/cplat/test_resources_115_cmds.py
**Covers:** AC-117.2, AC-117.7, AC-117.15
**Goal:** the 114/115 suites assert 5.x behaviour after spec 117 and nothing else. Each changed line ends with a `# spec 117: …`
comment, and the verification lists them as approved test changes.

**Implementation notes:**
- `test_plugins_114.py`: `WORKING` gains `system: restore` and `resource: backup, restore`; the count 30 becomes 33.
- `test_system_model_114.py`: `normalize_5` also drops `backup` from environments and resource instances (as it drops `operators`
  and the 115 fields).
- `test_system_render_114.py` line ~137 and `test_resources_115.py` line ~489: the environment key list ends with `, backup`.
- `test_resources_115.py` line ~366: the database instance key list ends with `, backup`.
- `test_resources_115_cmds.py` line ~260: the exact resource-instance dict gains `"backup": None`.
- No other assertion is changed or removed.

**Done when:** the amended tests pass once t1, t5 and t15 are merged, and `git diff` of these files touches only the lines named here.
