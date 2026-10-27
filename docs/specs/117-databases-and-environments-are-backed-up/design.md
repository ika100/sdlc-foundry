# Design — 117 Databases and environments are backed up and restorable

Extends [spec 115's design](../115-resources-are-named-typed-and-may-be/design.md) (TYPES, versions table, `operators/`,
`operators: owner`) and [spec 116's design](../116-an-object-storage-resource-for-files-and/design.md) (the bucket resource). Everything
is additive: a `system.yaml` without the new keys (`environments.<env>.backup`, `instances.<env>.backup`, `remote.s3`) renders
byte-identically, and no command output changes for it, except the listed key texts of AC-114.4/AC-115 that now name `backup`
(amended tests, plan t17).

## Decisions

- **Database backups use the CloudNativePG Barman Cloud plugin** (`ObjectStore`, plugin WAL archiver, `ScheduledBackup` with
  `immediate: true`, method `plugin`); the plugin chart and cert-manager (the plugin's hard requirement) are platform operators
  under `operators/`. ADR: [060](../../adr/060-database-backups-with-the-barman-cloud-plugin-and-restore-by-generation.md).
- **A restore is a new generation** `<system>-<db>-g<n>` next to the active cluster, recorded in git in
  `addons/<env>/<db>/restore-state.yaml` (written only by `cplat resource restore`, read by `render.py`, like overlay pins).
  `--switch` makes it active in git, detaches the connection Secret `<system>-<db>-app` from CloudNativePG and repoints its host
  keys, then restarts the users' pods. ADR-060.
- **Restore commands change git and the cluster in one step.** When the Argo CD application `addon-<db>-<env>` exists, the command
  opens a PR, waits for CI, merges it (spec 079's `pr.wait(merge=True)`) and waits until Argo CD synced the merge commit. Otherwise
  (no Argo CD, as in the e2e test and `WITH_ARGO=0` clusters) it commits on the current branch and runs `kubectl apply -k` on the
  addon directory. The tree must be clean before (as every `cplat` write).
- **Environment backups use Velero** installed once per cluster, with per `(system, env)` objects in `velero` rendered under
  `applications/<system>/backup/<env>/`; file-system backup (kopia) of persistent volumes, `emptyDir` skipped. ADR:
  [061](../../adr/061-environment-backups-with-velero.md).
- **An external bucket as backup target needs `remote.s3`** (`endpoint`, `bucket`, `region`, `forcePathStyle`) in git, because
  `ObjectStore` and `BackupStorageLocation` take these as literal values; the keys stay in the secret store. (Decision taken by
  default, see the last section.)
- **The bucket must have a resource instance in the environment** (AC-117.2 as written): a component that runs there uses it.
- **Status reads the cluster; nothing about backup state is written to git** (AC-117.6, AC-117.27). One module
  (`scripts/cplat/backupstate.py`) reads it for `/system:status`, the commands, the alert poll and doctor.
- **Kyverno guard rails (ADR-022) match Deployments in system namespaces only.** Every new workload passes: Velero (Deployment +
  node-agent DaemonSet) lives in `velero`, the plugin in `cnpg-system`, cert-manager in `cert-manager` (no guard rail there); the
  plugin's sidecar is injected into CloudNativePG instance Pods and recovery Jobs (not Deployments); Velero's restore helper is an
  init container of restored Pods (not Deployments); Deployments that Velero restores are the rendered ones and satisfy every rule
  (registry, securityContext, labels, resources). `policy.yaml` does not change.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `templates/gitops-app/scripts/render.py` | `backup` schema and checks, `remote.s3`, database backup objects, generations from `restore-state.yaml`, `backup/<env>/` Velero objects, ApplicationSets, operators `plugin-barman-cloud`, `cert-manager`, `velero`, `VELERO_AWS_PLUGIN_IMAGE` | changed |
| `templates/gitops-app/scripts/local-cluster.sh`, `scripts/bootstrap.sh`, `CLAUDE.md.jinja` | install / wait for the three new operators | changed |
| `scripts/cplat/backupstate.py` | read backup state from the cluster (kubectl seam), restore points, Velero backups and pod-volume backups, `restore-state.yaml` read/write | new |
| `scripts/cplat/dbbackup.py` | `cplat resource backup` | new |
| `scripts/cplat/dbrestore.py` | `cplat resource restore` | new |
| `scripts/cplat/envrestore.py` | `cplat system restore` | new |
| `scripts/cplat/cplat.py` | registers `resource backup`, `resource restore`, `system restore` | changed |
| `scripts/cplat/model.py`, `modelcmd.py` | `backup` on database resource instances and environments | changed |
| `scripts/cplat/status.py` | backup rows (text) and `backups` (JSON) | changed |
| `scripts/cplat/doctor.py` | prod warnings, same-cluster warning, operator rows for the three operators | changed |
| `scripts/cplat/alertsources.py`, `alerts.py`, `alertissues.py` | "backup failing" issues | changed |

## Contract: `system.yaml`

```yaml
environments:
  prod:
    backup:                       # NEW (AC-117.15), optional; an Environment property next to observability
      to: backups                 # required: a bucket resource of the system with a resource instance in prod
      schedule: "0 3 * * *"       # optional: five-field cron in UTC (default "0 3 * * *")
      retention: 30d              # optional: <n>d or <n>w, n >= 1 (default 30d)
resources:
  orders-db:
    type: database
    instances:
      prod:
        backup: {to: backups, schedule: "30 2 * * *", retention: 8w}   # NEW (AC-117.1): same keys and defaults
  backups:
    type: bucket
    external: true
    remote:
      s3: {endpoint: "https://s3.eu-central-1.amazonaws.com", bucket: acme-backups, region: eu-central-1, forcePathStyle: false}   # NEW
```

| Where | Allowed keys (new in bold) |
|---|---|
| `environments.<env>` | `host`, `url`, `policy`, `promote`, `observability`, `operators`, **`backup`** |
| `resources.<db>.instances.<env>` (database) | `external`, `remote`, `replicas`, `storage`, `resources`, **`backup`** |
| `…backup` | `to`, `schedule`, `retention` |
| `remote` of a bucket (resource or instance) | `path`, `refreshInterval`, **`s3`** |
| `remote.s3` | `endpoint`, `bucket`, `region`, `forcePathStyle` (all four required when `s3` is present) |

`backup` is not allowed at `resources.<db>` level or on a bucket instance (unknown-key texts unchanged there). A database's `remote`
keeps `path, refreshInterval`. Effective `remote.s3` in an environment: the instance's `remote.s3`, else the resource's (the whole
mapping, no merge of its keys).

Cron (both kinds): exactly five whitespace-separated fields; each field a comma list of `*`, `*/n`, `a`, `a-b` or `a-b/n` with
numbers only, in the ranges minute 0–59, hour 0–23, day of month 1–31, month 1–12, day of week 0–7; `n >= 1`. No names, no `@`
macros. Retention: `^[1-9][0-9]*[dw]$`.

### Render errors (exit 1, nothing written, each after `applications/<dir>/system.yaml: `)

`environments.<env>: unknown key '<k>' (allowed: host, url, policy, promote, observability, operators, backup)` and
`resources.<r>.instances.<env>: unknown key '<k>' (allowed: external, remote, replicas, storage, resources, backup)` replace the 115
texts (database only). In `validate_resource` (115's order), for a database instance whose effective `external` is true and that has
`backup`, checked before the unknown-key check:

| Case | Text |
|---|---|
| external database with `backup` (AC-117.5) | `resources.<r>.instances.<env>: an external database is backed up by its provider (remove backup)` |
| bucket `remote` unknown key | `resources.<b>.remote: unknown key '<k>' (allowed: path, refreshInterval, s3)` (same with `.instances.<env>.remote`) |
| `remote.s3` | `<where>.s3 must be a mapping with endpoint, bucket, region and forcePathStyle`; `<where>.s3: unknown key '<k>' (allowed: endpoint, bucket, region, forcePathStyle)`; `<where>.s3 needs endpoint, bucket, region and forcePathStyle`; `<where>.s3.endpoint must be an http(s) URL`; `<where>.s3.bucket must be a valid S3 bucket name`; `<where>.s3.region must be a non-empty string`; `<where>.s3.forcePathStyle must be true or false` |

After `validate_uses`, a new `validate_backups` checks every backup: first `environments.<env>.backup` in `ENVS` order, then each
database in declaration order with its instances in `ENVS` order. `<w>` is `environments.<env>.backup` or
`resources.<r>.instances.<env>.backup` (AC-117.2, AC-117.16), in this order:

| Case | Text |
|---|---|
| not a mapping | `<w> must be a mapping with to, schedule and retention` |
| other key (AC-117.2) | `<w>: unknown key '<k>' (allowed: to, schedule, retention)` |
| `to` missing | `<w>.to is required: the name of a bucket resource of the system` |
| `to` not a bucket | `<w>.to: '<v>' is not a bucket resource of the system (buckets: <names in order or none>)` |
| no instance | `<w>.to: the bucket <b> has no resource instance in <env> (a component that runs in <env> must use it)` |
| external target without `s3` | `<w>.to: the external bucket <b> needs remote.s3 (endpoint, bucket, region, forcePathStyle) in <env>: backups cannot read them from the secret store` |
| schedule | `<w>.schedule '<v>' is not a five-field cron expression (minute hour day-of-month month day-of-week, in UTC)` |
| retention | `<w>.retention '<v>' must be <n>d or <n>w with n of at least 1` |

A key that would set a Velero or plugin version anywhere (e.g. `backup.version`, `environments.<env>.velero`) fails as an unknown key
(AC-117.26).

`restore-state.yaml` that does not parse or breaks the rules below fails with
`applications/<system>/addons/<env>/<db>/restore-state.yaml is not valid (<reason>); take it from git history` (`<reason>` e.g.
`exactly one cluster must be active`).

### Renderer API (additions)

- `cfg["backup"]` = `{env: {"to": str, "schedule": str, "retention": str}}` for environments with `backup` (defaults filled).
- A database's `cfg["resources"][r]["envs"][env]` gains `"backup": {"to", "schedule", "retention"} | None`.
- A bucket's envs dict gains `"s3": {"endpoint", "bucket", "region", "forcePathStyle": bool} | None`.

## Contract: rendered objects — database backups

`L` = `{app.kubernetes.io/name: <db>, app.kubernetes.io/part-of: <system>, app.kubernetes.io/managed-by: gitops-app}`. `<B>` = the
target bucket: for an in-cluster instance bucket name `<system>-<b>`, endpoint `http://<system>-<b>-filer.<system>-<env>.svc:8333`;
for an external one `remote.s3.bucket` and `remote.s3.endpoint`. `PLUGIN` = `barman-cloud.cloudnative-pg.io`.

`addons/<env>/<db>/objectstore.yaml` (only with `backup`):

```yaml
apiVersion: barmancloud.cnpg.io/v1
kind: ObjectStore
metadata: {name: <system>-<db>, labels: L}
spec:
  retentionPolicy: <retention>                 # e.g. 30d, 8w (AC-117.1, AC-117.3)
  configuration:
    destinationPath: s3://<B bucket>/databases
    endpointURL: <B endpoint>
    s3Credentials:
      accessKeyId: {name: <system>-<b>-app, key: accessKeyId}
      secretAccessKey: {name: <system>-<b>-app, key: secretAccessKey}
      region: {name: <system>-<b>-app, key: region}
    wal: {compression: gzip}
    data: {compression: gzip}
```

`addons/<env>/<db>/scheduledbackup.yaml` (only with `backup`):

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: ScheduledBackup
metadata: {name: <system>-<db>, labels: L}
spec:
  schedule: "0 <schedule>"                     # CloudNativePG's six-field form: seconds 0 + the five fields (UTC)
  immediate: true
  backupOwnerReference: none
  cluster: {name: <active cluster>}
  method: plugin
  pluginConfiguration: {name: PLUGIN}
```

**Clusters.** Without `restore-state.yaml` there is one cluster, `<system>-<db>`, active. Each cluster is one file: `cluster.yaml`
for `<system>-<db>` (unchanged from 115 except `plugins`), `cluster-g<n>.yaml` for `<system>-<db>-g<n>`. Every cluster has the 115
sizing (`instances`, `imageName`, `storage`, `enableSuperuserAccess: false`, `resources`). Additions:

- an `active` or `previous` cluster, when the instance has `backup`, ends its `spec` with
  `plugins: [{name: PLUGIN, isWALArchiver: true, parameters: {barmanObjectName: <system>-<db>}}]`; a `restored` one has none;
- a generation cluster has, instead of `initdb`:

```yaml
  bootstrap:
    recovery:
      source: origin
      database: <system, - → _>
      owner: <system, - → _>
      secret: {name: <system>-<db>-app}
      recoveryTarget: {targetTime: "<to>"}      # omitted when to is latest
  externalClusters:
    - name: origin
      plugin: {name: PLUGIN, parameters: {barmanObjectName: <system>-<db>, serverName: <from.server>}}
```

(key order: `instances, imageName, storage, enableSuperuserAccess, bootstrap, externalClusters, resources, plugins`).

`kustomization.yaml` lists every file of the directory except `restore-state.yaml`, sorted. With `backup` in an environment, the
ApplicationSet `<system>-addons-<env>` template's `syncPolicy` gains
`retry: {limit: 10, backoff: {duration: 30s, factor: 2, maxDuration: 10m}}` (an `ObjectStore` may sync before its CRD exists).

**`restore-state.yaml`** (input, never rendered; the render keeps it as it finds it):

```yaml
# Written by `cplat resource restore` (spec 117). render.py reads it; do not edit it by hand.
next: 2
clusters:
  - {name: shop-orders-db, role: previous, until: "2026-10-27T11:02:13Z"}
  - {name: shop-orders-db-g1, role: active, from: {server: shop-orders-db, to: "2026-10-27T09:59:00Z"}}
```

Rules: exactly one `active`; at most one `restored` or one `previous`, not both; a `-g<n>` cluster has `from` (`to` is an RFC 3339
UTC time ending in `Z`, or `latest`); `next` is greater than every generation number used; `until` (RFC 3339 UTC) is set when a
cluster became `previous`.

## Contract: rendered objects — environment backups

Directory `applications/<system>/backup/<env>/` for each environment with `backup`, and in `applicationset.yaml` after the policy
ApplicationSets:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata: {name: <system>-backup-<env>, namespace: argocd}
spec:
  generators: [{list: {elements: [{name: environment}]}}]
  template:
    metadata: {name: <system>-backup-<env>}
    spec:
      project: default
      source: {repoURL: <gitops repo>, targetRevision: main, path: applications/<system>/backup/<env>}
      destination: {server: <cluster_server>, namespace: velero}
      syncPolicy: {automated: {prune: true, selfHeal: true}, retry: {limit: 10, backoff: {duration: 30s, factor: 2, maxDuration: 10m}}}
```

In an environment with `backup`, the ApplicationSets `<system>-<env>` and `<system>-addons-<env>` gain, after `template`,
`preservedFields: {annotations: [argocd.argoproj.io/skip-reconcile]}` (so `--replace` can pause an application).

Files (all with labels `{app.kubernetes.io/name: backup, app.kubernetes.io/part-of: <system>, app.kubernetes.io/managed-by: gitops-app}`
and an explicit `metadata.namespace`; `<ns>` = `<system>-<env>`, `<n>` = `<system>-<env>`):

| File | Object |
|---|---|
| `serviceaccount.yaml` | `ServiceAccount <n>-backup` in `velero` |
| `role.yaml` | `Role <system>-backup-credentials` in `<ns>`: `get` on `secrets` with `resourceNames: [<system>-<b>-app]`; `create` on `selfsubjectrulesreviews` (`authorization.k8s.io`) |
| `rolebinding.yaml` | `RoleBinding <system>-backup-credentials` in `<ns>` → that Role, subject `ServiceAccount <n>-backup` in `velero` |
| `secretstore.yaml` | `SecretStore <n>-backup` in `velero` (`external-secrets.io/v1`): `provider.kubernetes: {remoteNamespace: <ns>, server: {caProvider: {type: ConfigMap, name: kube-root-ca.crt, key: ca.crt}}, auth: {serviceAccount: {name: <n>-backup}}}` |
| `externalsecret.yaml` | `ExternalSecret <n>-backup` in `velero`: `refreshInterval: 1h`, store `<n>-backup` (kind `SecretStore`), target `<n>-backup` (`creationPolicy: Owner`), template v2 with one key `cloud: "[default]\naws_access_key_id={{ .accessKeyId }}\naws_secret_access_key={{ .secretAccessKey }}\n"`, `data` = `accessKeyId`, `secretAccessKey` from key `<system>-<b>-app` |
| `storage-location.yaml` | `BackupStorageLocation <n>` in `velero`: `provider: aws`, `objectStorage: {bucket: <B bucket>, prefix: environments/<n>}`, `credential: {name: <n>-backup, key: cloud}`, `config: {region: <region>, s3ForcePathStyle: "<true|false>", s3Url: <B endpoint>}`, `accessMode: ReadWrite` (in-cluster: region `us-east-1`, path style `"true"`) |
| `resource-policy.yaml` | `ConfigMap <n>-backup-policy` in `velero`, `data: {policy.yaml: "version: v1\nvolumePolicies:\n- conditions:\n    volumeTypes:\n    - emptyDir\n  action:\n    type: skip\n"}` |
| `schedule.yaml` | below |
| `kustomization.yaml` | `resources` = the eight files above, sorted; no `namespace` |

```yaml
apiVersion: velero.io/v1
kind: Schedule
metadata: {name: <n>, namespace: velero, labels: …}
spec:
  schedule: "<schedule>"                       # five fields, Velero runs in UTC
  useOwnerReferencesInBackup: false
  template:
    includedNamespaces: [<ns>]
    excludedResources: [clusters.postgresql.cnpg.io, backups.postgresql.cnpg.io, scheduledbackups.postgresql.cnpg.io, objectstores.barmancloud.cnpg.io]
    labelSelector:
      matchExpressions:
        - {key: cnpg.io/cluster, operator: DoesNotExist}                                   # every object CloudNativePG creates
        - {key: app.kubernetes.io/name, operator: NotIn, values: [<b>, <cache names…>]}    # rendered objects of the target and caches
        - {key: app.kubernetes.io/instance, operator: NotIn, values: [<system>-<b>]}       # the target store's pods, StatefulSets, PVCs
    storageLocation: <n>
    ttl: <hours>h0m0s                          # 30d -> 720h0m0s, 4w -> 672h0m0s
    defaultVolumesToFsBackup: true
    snapshotVolumes: false
    resourcePolicy: {kind: configmap, name: <n>-backup-policy}
```

AC-117.17 for the target bucket's Secret: the target's ExternalSecret (in-cluster `addons/<env>/<b>/externalsecret.yaml`, or the
external one in the overlay) gets `target.template.metadata.labels: L(b)` only in an environment whose `backup.to` is that bucket;
the external one also gets `target.template: {engineVersion: v2, mergePolicy: Merge, …}`. `stale_paths` treats `backup/` like
`policies/` (a directory per environment, the whole tree removed when no environment has `backup`) (AC-117.22).

## Contract: versions table and `operators/` (AC-117.26, AC-117.30)

```python
VELERO_AWS_PLUGIN_IMAGE = "velero/velero-plugin-for-aws:v1.14.4"       # matches ^velero/velero-plugin-for-aws:v\d+\.\d+\.\d+$
OPERATORS["plugin-barman-cloud"] = {"repo_url": "https://cloudnative-pg.github.io/charts", "chart": "plugin-barman-cloud",
    "chart_version": "0.8.1", "operator_version": "0.15.1", "namespace": "cnpg-system", "release": "barman-cloud",
    "crd": "objectstores.barmancloud.cnpg.io", "retry": True}
OPERATORS["cert-manager"] = {"repo_url": "https://charts.jetstack.io", "chart": "cert-manager", "chart_version": "v1.21.3",
    "operator_version": "1.21.3", "namespace": "cert-manager", "release": "cert-manager", "crd": "certificates.cert-manager.io",
    "values": {"crds": {"enabled": True}}}
OPERATORS["velero"] = {"repo_url": "https://vmware-tanzu.github.io/helm-charts", "chart": "velero", "chart_version": "12.2.1",
    "operator_version": "1.18.2", "namespace": "velero", "release": "velero", "crd": "schedules.velero.io", "finalizer": True,
    "values": {"initContainers": [{"name": "velero-plugin-for-aws", "image": VELERO_AWS_PLUGIN_IMAGE,
                                   "volumeMounts": [{"mountPath": "/target", "name": "plugins"}]}],
               "deployNodeAgent": True, "snapshotsEnabled": False, "credentials": {"useSecret": False},
               "configuration": {"backupStorageLocation": [], "volumeSnapshotLocation": [], "uploaderType": "kopia"}}}
```

Dict order: `cloudnative-pg`, `seaweedfs`, `plugin-barman-cloud`, `cert-manager`, `velero`. `chart_version` is the chart's exact
published version (`^v?\d+\.\d+\.\d+$`; jetstack's carries a `v`); `operator_version` is the chart's appVersion without `v`
(`^\d+\.\d+\.\d+$`). No range, no `latest`.

Needs (an environment counts only without `operators: owner`): `plugin-barman-cloud` and `cert-manager` when some in-cluster
database instance has `backup`; `velero` when some environment has `backup`. `operator_files` writes, per needed operator, 115's
document plus: `helm.valuesObject: <values>` when `values` is set; `metadata.finalizers: [resources-finalizer.argocd.argoproj.io]`
when `finalizer` (velero only: it leaves the cluster when nothing needs it, AC-117.22); `syncPolicy.retry` as above when `retry`.
The `cloudnative-pg` and `seaweedfs` documents stay byte-identical. The plugin needs CloudNativePG ≥ 1.26 (pinned 1.30.1).

**Verified on 2026-10-27, re-verify at build:** `https://cloudnative-pg.io/charts/index.yaml` (plugin-barman-cloud 0.8.1 →
appVersion v0.15.1; cloudnative-pg 0.29.1 → 1.30.1), `https://charts.jetstack.io/index.yaml` (cert-manager v1.21.3),
`https://vmware-tanzu.github.io/helm-charts/index.yaml` (velero 12.2.1 → appVersion 1.18.2; only the first part of the index was
read, so confirm it is the newest), Docker Hub `velero/velero-plugin-for-aws:v1.14.4` (plugin 1.14 ↔ Velero 1.18). Run
`helm template` of each pinned chart and confirm: the CRD names above; the Deployment labels doctor reads
(`app.kubernetes.io/name=velero`, `=plugin-barman-cloud`, `=cert-manager`); that `configuration.backupStorageLocation: []` renders
no location; the plugin's `ObjectStore` field names; the SeaweedFS operator's `app.kubernetes.io/instance` label on its pods and
StatefulSets (0.1.45). Where a pinned chart differs, follow it and update this section in the same PR.

**Re-verified at build (2026-10-27):** the full indexes give each pin above as the newest release (velero 12.2.1 included), and
`v1.14.4` is the newest stable `velero-plugin-for-aws` tag. `helm` was not available, so the pinned chart archives were read instead
of rendered: the three CRD names are in the charts (cert-manager's behind `crds.enabled`); the three Deployments carry
`app.kubernetes.io/name` = the chart name (no `nameOverride`); `backupStorageLocation: []` ranges over nothing, so no location is
rendered; the `ObjectStore` CRD has `spec.retentionPolicy`, `spec.configuration.{destinationPath, endpointURL, s3Credentials.{accessKeyId,
secretAccessKey, region}, wal.compression, data.compression}` (`gzip` allowed) and `status.serverRecoveryWindow.*.firstRecoverabilityPoint`.
The SeaweedFS instance label on pods and StatefulSets is set by the operator, not the chart, so the e2e run (t14) checks it.

## Contract: `cplat model show` (AC-117.7)

- `ResourceInstance.backup: dict | None` — for an in-cluster database instance with `backup`: `{"to", "schedule", "retention"}` with
  defaults filled; otherwise `None`. `Environment.backup: dict | None` the same for `environments.<env>.backup`.
- JSON: every `resource_instances[]` gains `"backup"`, every `environments[]` gains `"backup"`; schema stays 2, no field changes.
- Text: an instance or environment line with backup ends with `  backup to <b> schedule "<cron>" retention <r>`; lines without it are
  unchanged.

## Contract: `/system:status` (AC-117.6, AC-117.9, AC-117.18, AC-117.27)

Backup state is read with `kubectl --context <--context or the current context>` only when the system has any backup or any
`restore-state.yaml`. JSON gains (always):

```json
"backups": {
  "resource_instances": [{"resource": "orders-db", "environment": "dev", "cluster": "shop-orders-db-g1",
    "backup": {"last_success": "2026-10-27T03:00:12Z", "state": "ok", "archiving": "ok", "error": null,
               "earliest": "2026-09-27T03:00:12Z", "latest": "2026-10-27T10:41:02Z"},
    "restored": {"name": "shop-orders-db-g2", "ready": false} , "previous": null}],
  "environments": [{"environment": "dev", "backup": {"last_success": "2026-10-27T03:00:40Z", "state": "completed", "reason": null, "kept": 3}}]
}
```

- `resource_instances`: every database resource instance. `state`: `off` (no `backup`), `external`, `ok`, `failing` (archiving
  failing, or the newest base backup failed after the last completed one), `unknown` (the cluster could not be read; `error` says
  why). `archiving` `ok` | `failing` | `null`. `last_success` = `.status.stoppedAt` of the newest completed `Backup` of any cluster of
  this database, in RFC 3339 UTC (`Z`), else `null`. `earliest` = the smallest `firstRecoverabilityPoint` of the database's server
  names in the `ObjectStore`'s `status.serverRecoveryWindow`; `latest` = `last_archived_time` of `pg_stat_archiver` on the active
  primary; both `null` without a restore point. Archiving error = the message of the active cluster's `ContinuousArchiving`
  condition when it is `False`.
- `environments`: all three. `state`: `off`, `never` (no finished backup), `completed`, `partially failed`, `failed`, `unknown`.
  `last_success` = `completionTimestamp` of the newest `Completed` Velero `Backup` labelled `velero.io/schedule-name=<system>-<env>`.
  `reason` = `failureReason`, or `<n> errors` for partially failed. `kept` = number of such Backups.
- Text (only when something has backup or a restore state), after the resource table:

```
Backups (read from the cluster k3d-shop-local now):
  orders-db/dev      last base backup 2026-10-27T03:00:12Z  archiving ok  restore points 2026-09-27T03:00:12Z … 2026-10-27T10:41:02Z
  orders-db/dev      restored shop-orders-db-g2 (not ready: Setting up primary)
  orders-db/staging  off
  orders-db/prod     last base backup never  archiving failing (<error>)  restore points none
  ext-db/prod        external (backed up by its provider)
  environment dev    last backup 2026-10-27T03:00:40Z  completed  3 kept
  environment prod   off
```

  A `previous` generation is its own line `  <db>/<env>      previous <cluster>` (AC-117.9). `unknown` lines read
  `  <db>/<env>  unknown (<reason>)`.

## Contract: `cplat resource backup` (AC-117.31, AC-117.32)

`cplat resource backup <db> --env <env> [--app S] [--repo-dir D] [--context C] [--json]`. Checks before anything, exit 1:

| Case | Text |
|---|---|
| env | `--env must be dev, staging or prod` |
| unknown | `<db> is not a resource of the system (resources: <names or none>)` |
| not a database | `<db> is a <type>: only a database is backed up with /resource:backup` |
| no instance | `<db> has no instance in <env> (no component that runs in <env> uses it)` |
| external | `<db> in <env>: an external database is backed up by its provider` |
| no backup | `<db> has no backup in <env>: set resources.<db>.instances.<env>.backup in system.yaml` |
| cluster unreadable | `cannot read the cluster: <reason>` |

It creates `Backup <active>-manual-<YYYYMMDDHHMMSS>` (`spec: {cluster: {name: <active>}, method: plugin, pluginConfiguration: {name:
PLUGIN}}`) and polls every 10 s for up to 30 minutes. Output: `backup completed: <db>/<env> at <stoppedAt, RFC 3339 UTC> (Backup
<name>)`, exit 0; `backup failed: <db>/<env>: <status.error or phase>`, exit 1; on timeout `backup failed: <db>/<env>: not finished
after 30 minutes (Backup <name> is <phase>)`, exit 1. JSON `{"result": "completed"|"failed", "backup": <name>, "at": <time|null>,
"reason": <str|null>}`.

## Contract: `cplat resource restore` (AC-117.8 – AC-117.14)

`cplat resource restore <db> --env <env> (--to <time|latest> | --switch | --discard) [--confirm prod] [--app S] [--repo-dir D]
[--context C] [--dry-run] [--json]`. All checks run before any change, exit 1:

| Case | Text |
|---|---|
| none or two of the actions | `choose one of --to <time>, --switch or --discard` |
| `--confirm` not `prod` | `--confirm takes prod` |
| env, unknown, not a database, no instance, external | the `resource backup` texts above |
| `--to` without backup (AC-117.11) | `<db> has no backup in <env>: set resources.<db>.instances.<env>.backup in system.yaml` |
| `--to` format | `--to must be an RFC 3339 time with an offset (e.g. 2026-10-27T09:30:00Z) or latest, got '<v>'` |
| `--to` while one exists | `<db>/<env> already has a restored instance <name>; discard it first: /resource:restore <db> --env <env> --discard` (`previous instance` likewise) |
| `--to` outside the window | `<time> is outside the restore points of <db>/<env>: earliest <e>, latest <l>` (`none` for both when there is no restore point) |
| `--switch` without ready restored | `<db>/<env> has no restored instance to switch to; restore one first: /resource:restore <db> --env <env> --to <time>` / `<db>/<env>: the restored instance <name> is not ready (<phase>)` |
| `--discard` with nothing | `<db>/<env> has no restored or previous instance to discard` |
| prod, `--switch`/`--discard` without `--confirm prod` (AC-117.14) | `would <action>; nothing was changed: add --confirm prod to do it`, where `<action>` is `switch <db>/prod from <old> to <new>` or `discard <name> (<restored|previous>) of <db>/prod and its volumes` |
| dirty tree | `gitops.require_clean`'s text |

**`--to`** (time normalised to UTC `…Z`, fractional seconds kept). The source server is the newest server name of the database whose
window `[firstRecoverabilityPoint, until or latest]` contains the time (`latest`: the active cluster). State: `restored` =
`<system>-<db>-g<next>` with `from`, `next` + 1. Commit `chore(restore): restore <db>/<env> to <time>`, then the Argo or the
apply path. Wait up to 30 minutes for the cluster's `Ready` condition. Output:

```
restored <db>/<env> to <time> as <name>; components still use <active>
check it: kubectl -n <system>-<env> exec -it <name>-1 -- psql <dbname>
switch to it: /resource:restore <db> --env <env> --switch
```

Failure (recovery Job failed or not ready after 30 minutes): `restore failed: <db>/<env>: <reason>`, exit 1; the restored instance
stays in git and the cluster for inspection until `--discard` (AC-117.12).

**`--switch`**: state `restored` → `active`, old `active` → `previous` (`until` = now). Commit
`chore(restore): switch <db>/<env> to <name>`; Argo or apply path; delete `ScheduledBackup <system>-<db>` so it is recreated for the
new cluster; patch `Secret <system>-<db>-app`: remove `metadata.ownerReferences`, replace `<old>-rw` by `<new>-rw` in every value of
`host`, `uri`, `jdbc-uri`, `pgpass`, `fqdn-uri`, `fqdn-jdbc-uri` that exists; delete the pods (`-l app=<c>`) of every running
component in `<env>` that uses `<db>` and wait for their rollout. Output:
`switched <db>/<env> to <new>; <old> is previous (no connections); discard it with /resource:restore <db> --env <env> --discard`.

**`--discard`**: removes the `restored` (else the `previous`) cluster from the state, commit
`chore(restore): discard <name> of <db>/<env>`, Argo or apply path, then `kubectl delete cluster <name>` and wait until its PVCs are
gone. Output: `discarded <name> (<role>) of <db>/<env> and its volumes; <active> stays active, the backups in the bucket are unchanged`.

Argo path: `gitops.open_pr(repo, "restore/<db>-<env>-<action>", <commit title>, <body>)`, `pr.wait(…, merge=True)`, `git checkout main
&& git pull`, then poll `addon-<db>-<env>` until `status.sync.revision` is the merge commit and `sync.status` is `Synced` (10 minutes).
Apply path: commit on the current branch, `kubectl apply -n <system>-<env> -k applications/<system>/addons/<env>/<db>`.
`--dry-run` runs every check (including the cluster reads) and prints `will_do` lines; `--json` prints the Report.

## Contract: `cplat system restore` (AC-117.19 – AC-117.21, AC-117.14)

`cplat system restore <env> [--backup <name|latest>] [--replace] [--confirm prod] [--app S] [--repo-dir D] [--context C] [--json]`.

| Case | Text (exit 1, nothing changed) |
|---|---|
| env | `<env> is not an environment (dev, staging, prod)` |
| no backup | `<env> has no backup: set environments.<env>.backup in system.yaml` |
| no backups yet | `<env> has no backups yet: the first scheduled backup has not finished` |
| unknown name (AC-117.21) | `no backup <name> in <env>; available: <names newest first>` |

Without `--backup` (AC-117.19), exit 0:

```
backups of <system>-<env> (newest first):
  <name>  <time>  <completed|partially failed (<n> errors)|failed (<reason>)|in progress>
```

With `--backup` (`latest` = the newest `Completed` one), every output ends with
`databases are not part of environment backups: restore them with /resource:restore` (AC-117.20):

- prod without `--confirm prod`: `would restore <backup> into <ns>[ and replace the volumes <list>]` /
  `nothing was changed: add --confirm prod to do it`, exit 1.
- Existing volumes (from the backup's `PodVolumeBackup`s: a live pod of the same workload mounts a PVC under the same volume name,
  or the StatefulSet PVC `<volume>-<pod>` exists) without `--replace`:
  `volumes of <backup> still exist in <ns>: <pvc> (<kind> <workload>), …` /
  `nothing was restored: add --replace to stop those workloads, replace their volumes from the backup and start them again`, exit 1.
- With `--replace`: for each workload root (the top of its owner references, e.g. the `Seaweed` of a bucket store): annotate its Argo
  CD application `argocd.argoproj.io/skip-reconcile=true` if one tracks it, delete the root and wait for its pods; delete the PVCs;
  print `stopped <kind> <name>` and `replaced <pvc>`.
- Then `Restore <backup>-<YYYYMMDDHHMMSS>` (`backupName`, `includedNamespaces: [<ns>]`, `existingResourcePolicy: none`,
  `restorePVs: true`), wait up to 30 minutes; remove the annotations, wait for the workloads; print
  `restored <backup> into <ns>: <itemsRestored> items` and `started <kind> <name>`; exit 0. `PartiallyFailed`:
  `restore partially failed: <n> errors (kubectl -n velero describe restore <name>)`, exit 1; `Failed`: `restore failed: <reason>`, exit 1.

## Contract: `/platform:doctor` (AC-117.23, AC-117.29, AC-117.30)

Rows per gitops-app repo, after the operator rows; no kubectl needed:

| Situation | Level | Name | Detail | Fix |
|---|---|---|---|---|
| some instance runs in prod; prod without `backup` or an in-cluster database instance in prod without `backup` | WARN | `backup prod` | `prod has no backup: <items>` (`environment prod`, then `<db>/prod` in resource order; with several systems prefixed `<system>: `) | `set environments.prod.backup and resources.<db>.instances.prod.backup in system.yaml (docs/BACKUP-AND-RESTORE.md)` |
| a prod backup's `to` instance is in-cluster | WARN | `backup location` | `prod backups live in the same cluster: <items>` (`<db>/prod (to <b>)`, `environment prod (to <b>)`) | `use an external bucket as to for prod` |

Operator rows (only with kubectl, 115's six situations and texts) in the order `cloudnative-pg`, `seaweedfs`, `plugin-barman-cloud`,
`cert-manager`, `velero`; label value = chart name; needs as in the versions section. Installed and expected versions are compared
without a leading `v`.

## Contract: alert poll (AC-117.28)

For each environment whose `observability` exists with `alerts` not `false` and that has `backup` or a database instance with
`backup`, the poll reads `backupstate` (current kube context) even when the metrics source of that environment is skipped. A
failure older than one hour gives one `Alert(name="backup failing", service=<db> or "environment", environment=<env>,
repo=<gitops repo>, severity="critical", summary=<last error>)`:

- WAL archiving: `ContinuousArchiving` is `False` and its `lastTransitionTime` is more than 1 hour ago;
- scheduled database backup: the newest `Backup` of `ScheduledBackup <system>-<db>` failed and none completed after the first such
  failure, which is more than 1 hour old;
- environment backup: the newest Velero `Backup` of the schedule is `Failed` or `PartiallyFailed` and none completed since the first
  such one, which is more than 1 hour old.

`alertissues.title` for that name is `[auto] [alert] backup failing: <db or environment>/<env>`. Deduplication and resolution are
the poll's (one open issue per signature). A kubectl failure is a `SourceError` of that environment.

## Contract: local cluster and bootstrap

- `bootstrap.sh`: `plugin-barman-cloud) crd=objectstores.barmancloud.cnpg.io`, `cert-manager) crd=certificates.cert-manager.io`,
  `velero) crd=schedules.velero.io`.
- `local-cluster.sh`: `WITH_BARMAN_CLOUD` (auto: `operators/apps/plugin-barman-cloud.yaml` exists; it also installs cert-manager),
  `BARMAN_CLOUD_VERSION` (default that file's `targetRevision`, else `0.8.1`), `CERT_MANAGER_VERSION` (default `cert-manager.yaml`'s,
  else `v1.21.3`), `WITH_VELERO` (auto: `operators/apps/velero.yaml`), `VELERO_VERSION` (default its `targetRevision`, else
  `12.2.1`), `VELERO_AWS_PLUGIN_IMAGE` (default `velero/velero-plugin-for-aws:v1.14.4`). Without Argo CD: HelmCharts
  `kube-system/cert-manager` (`crds.enabled: true`), `kube-system/plugin-barman-cloud` (target `cnpg-system`, after CloudNativePG and
  cert-manager are ready) and `kube-system/velero` (the versions-table values), each followed by its CRD and rollout waits (Velero:
  `deploy/velero` and `daemonset/node-agent`). With Argo CD: the same waits after `operators/root.yaml`.

## Contract: e2e (AC-117.24)

After the external-bucket steps: bucket `backups` (in-cluster) used by e2e-web (already prefixed), `instances.dev.backup: {to:
backups}` on `postgres`, `environments.dev.backup: {to: backups}`, and an external component `e2e-files` (kustomize package in the
gitops repo: a StatefulSet with a 1Gi PVC `data`, `busybox`, non-root). Cluster-up runs with `WITH_BARMAN_CLOUD=1 WITH_VELERO=1`
(forced, operators/ is written later). Database: `/resource:backup` completes; row A, time T, row B, `pg_switch_wal()`; wait until
status `latest` ≥ T; restore to T; switch; a pod with e2e-api's database variables reads A and not B; discard previous. Environment:
a file on `e2e-files-0`'s PVC and an object in `files`; a Velero `Backup` made from the Schedule's template; delete both; `system
restore dev --backup <b>` refuses and lists the volumes; `--replace` restores; both read back unchanged; the database cluster is
untouched (same UID).

## Risks

- **Restored pods and garbage collection.** Velero restores pods with stale owner references; data in PVCs survives a pod being
  garbage-collected, so only PVC-backed volumes are covered (emptyDir skipped). The e2e test is the proof.
- **The `SeaweedFS` store under `--replace`** is stopped by deleting its `Seaweed`; if the operator's finalizer deletes more than its
  StatefulSets, the build changes the stop step (e2e proves it).
- **CloudNativePG internals.** The switch relies on CloudNativePG not touching a Secret it no longer owns, and on a generation with
  `recovery.secret` not writing the Secret. The e2e switch is the proof; the build follows observed behaviour and updates this
  design and ADR-060.
- **cert-manager in clusters that already run one**: those set `operators: owner` (CHANGELOG action).
- **A discarded previous generation's backups are never pruned** (nothing runs its retention any more).
- **Only `operators/apps/velero.yaml` left** — when it is the last operator and is removed, `operators/` disappears and 115's
  "root without path" risk applies (Velero then stays until a human deletes `platform-operators`).
- **Path-style addressing** of barman-cloud against SeaweedFS is assumed (boto's default with a custom endpoint); the e2e proves it.
- **The alert poll needs cluster access** for environments with backup and alerts on; without it the poll turns red.

## Decisions taken by default

1. **External backup targets declare `remote.s3` in git** (endpoint, bucket, region, forcePathStyle). Alternative: a controller or
   templating that copies them from the synced Secret into `ObjectStore`/`BackupStorageLocation`. Chosen because both objects take
   literal values and nothing in the stack copies Secret data into custom resources safely; the values are not secret.
2. **The target bucket must be used by a component in the environment** (AC-117.2 as written). Alternative: a backup `to` creates the
   bucket instance. Chosen because the spec says so and 115's external ExternalSecret needs a using overlay.
3. **cert-manager is installed with the plugin** under the same rules (`operators: owner` opts out of all). Alternative: never install
   it and require it. Chosen because the plugin cannot run without it and "the platform installs what backups need" is the spec's
   promise.
4. **Restores are git changes** (state file + PR merged by the command, or commit + `kubectl apply` without Argo CD). Alternative:
   create the restored cluster only with kubectl. Chosen because Argo CD heals and would recreate a discarded tracked cluster.
5. **Restore by generation `-g<n>`, never reused; the switch repoints the connection Secret and restarts the users' pods** (deleting
   pods, not `rollout restart`, so Argo CD sees no drift).
6. **A restored instance archives nothing until switched; the previous keeps archiving until discarded.**
7. **`ScheduledBackup` uses `immediate: true`**, so a restore point exists right after `backup` is set. Alternative: wait for the
   first schedule (up to 24 h without restore point).
8. **Environment backups cover persistent volumes only (`emptyDir` skipped)**, via Velero file-system backup. Alternative: back up
   emptyDirs too; their restore is bound to a pod that controllers replace, so it cannot be relied on. The e2e "component volume" is
   the PVC of an external component.
9. **`/system:restore` with existing volumes and no `--replace` exits 1**; prod actions without `--confirm prod` exit 1 after printing
   what they would do. Alternative: exit 0. Chosen so scripts never mistake a refusal for success.
10. **Status reads the current kube context when `--context` is not given** (only when backups are configured). Alternative: require
    `--context` as for the Argo column.
11. **Alerts count `partially failed` environment backups as failing**; the issue title uses `environment/<env>` for environments.
12. **Doctor's "prod has no backup" warns only when something runs in prod.**
13. **Cron accepts numeric fields only (no names, no `@daily`)**, so the same text is valid for Velero and (with a leading `0`)
    CloudNativePG.
14. **Velero pin follows ADR-058's rule (the chart's appVersion 1.18.2)**, not the newer 1.18.4 image.
