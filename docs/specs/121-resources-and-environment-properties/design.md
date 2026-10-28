# Design — 121 Resources and environment properties upgrade safely

Extends [spec 115's design](../115-resources-are-named-typed-and-may-be/design.md) (the versions table in `render.py`, `operators/`,
`operators: owner`, doctor's operator rows), [116](../116-an-object-storage-resource-for-files-and/design.md) (`SEAWEEDFS_IMAGE`),
[117](../117-databases-and-environments-are-backed-up/design.md) (`backup`, `restore-state.yaml` generations, `cplat system status --json`
`backups`, `/resource:backup`, `/resource:restore`), [118](../118-a-cache-resource-compatible-with-redis/design.md) (`VALKEY_IMAGES`),
[119](../119-a-message-broker-resource-behind-events/design.md) (`NATS_CHART`, `NATS_IMAGES`, NACK's legacy `app: <release>` label),
[120](../120-instances-scale-on-load-and-queue-depth/design.md) (KEDA and metrics-server rows, `resource_metrics`),
[124](../124-autonomy-is-declared-per-environment-and/design.md) (key lists grow at the end; an engine never promotes forward) and
[125](../125-a-cluster-repo-hosts-several-systems/design.md) (`OPERATORS` shared with cluster repos through the synced copy
`system_render.py`; `local-cluster.sh` is a synced copy too). Decisions that outlive the spec:
[ADR: resource and operator upgrades roll through the environments in verified steps](../../adr/068-resource-and-operator-upgrades-roll-through-environments-in-verified-steps.md)
and [ADR: one versions table pins everything, and every release proves the upgrade from the previous one](../../adr/069-one-versions-table-pins-everything-and-every-release-proves-the-upgrade.md)
(if a parallel session took these numbers before merge, rename both files, their two index rows and these links together).

Everything is additive except one deliberate change: **every engine image reference now carries an exact tag and a digest**
(AC-121.2, AC-121.3). A `system.yaml` without the new keys renders byte-identically to before **except those image references**
(the same exception spec 115 made for the database image, AC-115.6). This is not optional: the Postgres pins of spec 115
(`postgresql:17.11` and siblings) are plain `<major>.<minor>` tags, and CloudNativePG does not publish plain tags any more (verified below),
so they must move to the immutable `<major>.<minor>-<build>-standard-trixie` tags anyway. The byte-identity tests of specs 118–120 are
amended (plan t19) to compare after mapping each new reference back to the old one, which proves that nothing else changed.
`operators/` grows only for repos that answer `property_operators: install` (AC-121.17; every repo created before this release keeps
`owner`, see "Contract: environment-property operators").

## Decisions

- **The versions table stays in `render.py` and becomes complete** (AC-121.1 to AC-121.3): every engine image with tag and digest, the
  NATS chart, the collector, LGTM, the Velero plugin, Argo CD, k3s and the Gateway API manifest, and every operator chart with its app
  version and the CRD versions it serves. `versions_table()` turns it into rows; `cplat platform versions`, doctor, the pin check and the
  release check read those rows. The local cluster script keeps literal defaults, as specs 115–120 built it, and the pin check holds each
  one equal to its row. ADR-069.
- **Postgres images are `ghcr.io/cloudnative-pg/postgresql:<major>.<minor>-<build>-standard-trixie@sha256:<digest>`** for every major:
  one image family on one Debian release, because CloudNativePG's in-place major upgrade requires source and target on the same
  distribution. `standard` (PGAudit, pgvector, all locales) is a superset of `minimal`; `system` images are deprecated upstream.
- **Majors**: Postgres 16, 17, 18 are supported and are upgrade targets; 15 stays renderable as `deprecated` (dropping a supported major
  needs a major platform release, AC-121.26) and may be upgraded from, never to. Valkey 8, 9; NATS lines `2.14`, `2.15`. A bucket has
  no `version`: its SeaweedFS image moves with the platform release like a minor pin (AC-121.11).
- **A database major upgrade is CloudNativePG's in-place upgrade** (offline `pg_upgrade --link`, triggered by `imageName`, supported by
  operator 1.30.1, verified in its docs): the cluster keeps its name, its connection Secret and its volumes (AC-121.15). Import into a new
  cluster was rejected: it needs a second cluster, a connection to the old one and a switch of the Secret. Because `pg_upgrade` creates a
  new system identifier, a backed-up database archives to a **new Barman server name per major** (`<cluster>-pg<major>`), as
  CloudNativePG requires; a restore to a time before the upgrade recovers into a generation on the **old** major.
- **The per-environment major is `resources.<r>.instances.<env>.version`** (database, cache, broker), appended last to each instance key
  list. Effective major = the instance's `version`, else the resource's, else the type default.
- **A held pin lives in the rendered file, like an overlay's `newTag`** (AC-121.11): dev always renders the table's pin of its major;
  staging and prod keep the engine image (and the broker's chart version) of their existing rendered file while their major does not
  change. `/resource:upgrade <r> --to <current major> --env <env>` releases a hold. No new state file.
- **One upgrade step = one environment, one pull request** (AC-121.6 to AC-121.10), made by `cplat resource upgrade`; the last step folds
  the per-environment entries into the resource's `version`. A gitops CI check refuses a PR that changes one resource's major in two
  environments.
- **A step counts only after it is verified** (AC-121.15, AC-121.16): healthy at the new image within 15 minutes, the connection Secret
  under its name, and the smoke tests of every component instance using the resource in that environment. The result is recorded in the
  cluster as a ConfigMap `<system>-<resource>-upgrade` in `<system>-<env>`; the next environment's step reads it (AC-121.9).
- **Staging follows by itself only with `promote: after-dev-smoke`**; prod is always a person's `--env prod` (AC-121.8). An autonomy
  engine never runs a resource upgrade (ADR-063: an engine never promotes forward).
- **The 60-minute backup precondition** reads `backups.resource_instances[].backup.last_success` exactly as `cplat system status --json`
  reports it (spec 117), for database major steps in every environment (AC-121.12); cache and broker majors skip it and say so (AC-121.27).
- **Operators**: the renderer installs, once per cluster and only where needed, the resource operators as today plus External Secrets,
  Kyverno and LGTM when the repo answers `property_operators: install` (AC-121.17). Every environment of a gitops repo deploys to the one
  `cluster_server`, so an operator pin moves once, with dev's step, and every environment there is verified (AC-121.21); AC-121.20's
  separate-cluster order has no case in 5.x (see "Spec readings").
- **Doctor marks operators `ok`, `missing`, `older`, `newer`** with the CRD versions; it fails (exit 1) on `missing` or a major `older`
  only when told which cluster an environment runs on (`--context [ENV=]CTX`, AC-121.19); without it, today's warnings stay.
- **Releases prove the upgrade path**: a pin check (every reference from the table, digests, no floating tag, exact chart versions), a
  release check (CHANGELOG lists every changed row; a major move, a dropped CRD version or a dropped major needs a major release) and an
  upgrade e2e in its own workflow. A release is not tagged while it is red: CONTRIBUTING's procedure runs the gate before the tag, and a
  tag-push workflow turns red on a tag without a green upgrade e2e. Nothing publishes or deletes a tag. ADR-069.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `templates/gitops-app/scripts/render.py` (+ copy `templates/cluster-gitops/scripts/system_render.py`) | the complete versions table, `versions_table()`, `--versions`; `instances.<env>.version`; effective majors; held pins; Barman server per major; a generation's major; operators for properties (`property_operators`), `operators/lgtm/`; docstring | changed |
| `templates/gitops-app/scripts/local-cluster.sh` (+ copy) | defaults equal to the table (Argo CD, k3s, LGTM and the Velero plugin with exact versions and digests); override warnings; ESO, Kyverno, LGTM from `operators/` under Argo CD | changed |
| `templates/gitops-app/scripts/bootstrap.sh` | waits for the CRDs of `external-secrets` and `kyverno` | changed |
| `templates/gitops-app/scripts/upgrade-check.py` | the CI check of AC-121.10 | new |
| `templates/gitops-app/copier.yml`, `devbox.json`, `.github/workflows/ci.yml` | answer `property_operators`; recipe and job `upgrade-check` | changed |
| `scripts/cplat/versions.py` | rows, text/JSON, `--diff`, CHANGELOG lines; `cplat platform versions` | new |
| `scripts/cplat/upgrade.py` | `cplat resource upgrade`: guards, the step's edit, PR, `--wait` | new |
| `scripts/cplat/upgradeverify.py` | health wait, Secret names, smoke of the using instances, records, auto staging | new |
| `scripts/cplat/update.py`, `scripts/cplat/fleet_pr.py` | re-render after the template copy, the per-environment change list, `--verify` (operators and dev's pins) | changed |
| `scripts/cplat/newapp.py` | new systems answer `property_operators: install` | changed |
| `scripts/cplat/dbrestore.py` | a restore before a major upgrade says which major the generation runs | changed |
| `scripts/cplat/model.py` | `ResourceInstance.version`, `.pinned` | changed |
| `scripts/cplat/status.py` | section "Resource versions" (JSON `resource_versions`) | changed |
| `scripts/cplat/doctor.py` | `--context`, states, CRD versions, shared clusters, rows for ESO/Kyverno/LGTM with `install`; broker rows compare without digests | changed |
| `scripts/cplat/cplat.py` | `platform versions`, `resource upgrade` | changed |
| `scripts/check-pins.py`, `scripts/release-check.py` | AC-121.2; AC-121.23, AC-121.26 and the release gate | new |
| `tests/e2e/upgrade.sh`, `.github/workflows/e2e-upgrade.yml`, `.github/workflows/release-guard.yml` | AC-121.24, AC-121.25, the gate | new |
| `.github/workflows/ci.yml` | pin check step, `release-check` job | changed |
| `tests/e2e/run.sh` | answer `owner` after `system new`; the NATS image assertion reads the table | changed |
| `envrestore.py`, `addon.py`, `apilist.py`, `promote.py`, `compose.py`, the cluster renderer and `check.py`, Kyverno policy, Velero Schedule, `render_v4.py` | nothing | unchanged |

## Contract: the versions table (AC-121.1 to AC-121.3, AC-121.22, AC-121.26)

Module constants in `render.py`, values verified on 2026-10-28 (below). An image constant is always `<repository>:<tag>@sha256:<64 hex>`.

```python
POSTGRES_IMAGES = {
    15: "ghcr.io/cloudnative-pg/postgresql:15.19-202610260819-standard-trixie@sha256:f617efc030d3099362e7fca616bb6d83d102599abf9b7b5e225482e4d0306aa3",
    16: "ghcr.io/cloudnative-pg/postgresql:16.15-202610260820-standard-trixie@sha256:1ec419e997a8bde5263b6951f4c5ebc4aa2e1937927001f2561025c0a816e174",
    17: "ghcr.io/cloudnative-pg/postgresql:17.11-202610260819-standard-trixie@sha256:ed6923f9ba2399cf9070379a353c710c29ced8a294be73986a2c3dae7e599ce3",
    18: "ghcr.io/cloudnative-pg/postgresql:18.6-202610260820-standard-trixie@sha256:39add80f5b1e573e2f6b641c66fd1a2f8dede67ca0330e870285bc1078551390",
}
VALKEY_IMAGES = {8: "valkey/valkey:8.1.11@sha256:8f836008e0986c36adf50da714c7060cf689dbb335f61fe077939d90fa650809",
                 9: "valkey/valkey:9.1.3@sha256:3add1a336a920ea54770a001ab6feb3da5fceea96a40373a3a2cd469b815f0b7"}
NATS_IMAGES = {"2.14": "nats:2.14.9-alpine@sha256:127c5ccbc538a93f53ebb19461dc193130df386c2d6dab8199661a28a30d85bd",
               "2.15": "nats:2.15.2-alpine@sha256:823e7f1d6d8ffe3b30dbd73d4a06bbb939acf94929f7fdf224404da7a05bafb5"}
NATS_CHART = {...unchanged: 2.15.1}
SEAWEEDFS_IMAGE = "chrislusf/seaweedfs:4.51@sha256:f7a49e3f3972ebed5be2ed4befa4a0c68eb7bdddba6e692d42729ceb545134b8"
VELERO_AWS_PLUGIN_IMAGE = "velero/velero-plugin-for-aws:v1.14.4@sha256:c85a7fa803569e3128c33e4f5766f84ab156c8d171c9f1dd2715581d45ce98fa"
COLLECTOR_IMAGE = "otel/opentelemetry-collector-contrib:0.162.0@sha256:39923a8e431bd1f57be82411999d389fcfe40857492e4365456d97a4c1f74be6"
LGTM_IMAGE = "grafana/otel-lgtm:0.35.0@sha256:2de1094c593c671cbfca878a28ffcd7e46ff5e32f2ce966c0cf33003f6cf4266"
CLUSTER_PINS = {   # installed by local-cluster.sh, never rendered
    "argo-cd": {"version": "v3.4.12", "manifest": "https://raw.githubusercontent.com/argoproj/argo-cd/v3.4.12/manifests/install.yaml"},
    "k3s": {"image": "rancher/k3s:v1.32.5-k3s1@sha256:b75eac801bbc91b4584769c840f346683c7740d72f83e630088370f8e1eb2c8a"},
    "gateway-api": {"version": "v1.2.1",
                    "manifest": "https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.2.1/standard-install.yaml"},
}
SUPPORTED_MAJORS = {"database": (16, 17, 18), "cache": (8, 9), "broker": ("2.14", "2.15")}   # upgrade targets
DEPRECATED_MAJORS = {"database": (15,)}                                                       # render, upgrade from, never to
UPGRADE_PATHS = {"database": {15: (16, 17, 18), 16: (17, 18), 17: (18,), 18: ()},
                 "cache": {8: (9,), 9: ()}, "broker": {"2.14": ("2.15",), "2.15": ()}}
```

- `ADDONS["observability"]["image"]` becomes `COLLECTOR_IMAGE`; `SUPPORTED_VERSIONS`, `CACHE_VERSIONS`, `BROKER_VERSIONS` stay (the
  render's accepted values, 15 included) and equal `SUPPORTED_MAJORS ∪ DEPRECATED_MAJORS` per type.
- Every `OPERATORS` row gains `"crds": {<crd name>: [<served versions>, …]}` — every CRD the chart version installs and the versions it
  serves, read from the chart archive at build (plan t1; `metrics-server`: `{}`). `crd` (the one CRD bootstrap waits for) stays.
  Chart versions, operator versions, repos and selectors do not change in this spec.
- The broker's `server.yaml` keeps 119's shape `container.image: {repository: nats, tag: <tag>@sha256:<digest>}`: the chart's `nats.image`
  helper prints `<repository>:<tag>` (verified at tag `nats-2.15.1`), so the pod runs `nats:2.15.2-alpine@sha256:…`. `render.py` splits
  the reference at `@` before `rsplit(":", 1)`.
- `def versions_table() -> list[dict]` returns the rows in this order: postgres 15–18, valkey 8–9, nats 2.14–2.15, chart `nats`,
  `seaweedfs`, `opentelemetry-collector`, `lgtm`, `velero-plugin-for-aws`, `argo-cd`, `k3s`, `gateway-api`, then `operator <name>` in
  `OPERATORS` order. A row:

```python
{"name": "postgres 17", "kind": "image" | "chart" | "manifest", "engine": "database" | "cache" | "broker" | "bucket" | None,
 "major": 17 | "2.15" | None, "status": "supported" | "deprecated" | None,
 "version": "17.11",                       # image: the tag's version part; chart: chart_version; manifest: version
 "ref": "<image ref without digest>" | "<repo_url> <chart>" | "<manifest url>",
 "digest": "sha256:<64 hex>" | None,       # images only
 "app_version": "1.30.1" | None,           # operator rows: operator_version
 "crds": {...} | None}                     # operator rows
```

  Version parts: Postgres `17.11` from `17.11-202610260819-standard-trixie`, NATS `2.15.2` from `2.15.2-alpine`, `velero-plugin-for-aws`
  `v1.14.4`, k3s `v1.32.5-k3s1`, Argo CD `v3.4.12`, Gateway API `v1.2.1`, `cert-manager` `v1.21.3` (versions are compared without a
  leading `v`).
- CLI: `render.py --versions` prints `json.dumps(versions_table(), indent=2)` and exits 0 without reading `applications/`.

### `cplat platform versions [--json] [--diff <git ref>] [--changelog]` (AC-121.1, AC-121.23)

Reads the rows from the platform's `templates/gitops-app/scripts/render.py` (as doctor reads `OPERATORS`). Text, one row per line, columns
padded:

```
versions table of platform 5.4.0
  image     postgres 15 (deprecated)  15.19    ghcr.io/cloudnative-pg/postgresql:15.19-202610260819-standard-trixie  sha256:f617efc0…
  image     postgres 16               16.15    …
  chart     nats                      2.15.1   https://nats-io.github.io/k8s/helm/charts nats
  manifest  argo-cd                   v3.4.12  https://raw.githubusercontent.com/argoproj/argo-cd/v3.4.12/manifests/install.yaml
  chart     operator cloudnative-pg   0.29.1   https://cloudnative-pg.github.io/charts cloudnative-pg  operator 1.30.1  crds clusters.postgresql.cnpg.io v1, …
```

The digest column prints the first 8 hex characters after `sha256:` and `…`; `--json` prints `{"release": "<x.y.z>", "rows": [<row>…]}`
with full digests. `--diff <ref>` compares with the rows of `git show <ref>:templates/gitops-app/scripts/render.py` (loaded from a temp
file; a release without `versions_table()` is read from its `POSTGRES_IMAGES`, `OPERATORS`, … constants, and its absent rows count as
`added`) and prints only changes: `changed <name>: <old> → <new>` (`(major)` appended when the first version number differs, or the second
for a `0.x` version; for an image row also when only the digest changed: `<v> (digest <8>) → <v> (digest <8>)`), `added <name>: <new>`,
`removed <name>: <old>`, plus `crds <name>: removed <crd> <version>` for a CRD version the old row served and the new one does not.
`--changelog` prints the same changes as Markdown list items: ``- `<name>` <old> → <new>`` with ` **(major)**`, ``- `<name>` <new> (new)``,
``- `<name>` <old> (removed)``. Exit 0; an unreadable ref exits 1 with `cannot read the versions table at <ref>: <reason>`.

## Contract: `system.yaml` (AC-121.3, AC-121.6, AC-121.7)

```yaml
resources:
  orders-db:
    type: database
    version: 16                      # the major every environment runs unless its instance says otherwise
    instances:
      dev: {version: 17, backup: {to: backups}}    # NEW: per-environment major (database, cache, broker), written by /resource:upgrade
      staging: {backup: {to: backups}}
```

| Where | Allowed keys (new key last) |
|---|---|
| database `resources.<r>.instances.<env>` | `external, remote, replicas, storage, resources, backup, version` |
| cache `resources.<r>.instances.<env>` | `external, remote, memory, maxmemoryPolicy, persistence, storage, version` |
| broker `resources.<r>.instances.<env>` | `external, remote, replicas, storage, resources, version` |
| bucket instances, `environments.<env>` | unchanged (`operators` exists since spec 115) |

Render errors (exit 1, nothing written, after `applications/<dir>/system.yaml: `), checked where the resource-level `version` is checked
today, then per instance in ENVS order:

| Case | Text |
|---|---|
| version on an external instance (database, broker) | `resources.<r>.instances.<env>: an external resource runs nothing (remove version)` (115's text) |
| version on an external cache instance | `resources.<r>.instances.<env>: an external cache is sized and configured at its provider (remove version)` (118's text; the old exemption for `version` goes) |
| unsupported instance version | `resources.<r>.instances.<env>: version '<v>' is not a supported database version (15, 16, 17, 18)` (`cache version (8, 9)`, `broker version (2.14, 2.15)`) |
| a broker version that YAML read as a float other than a supported line | the text above followed by `; write it as a string, e.g. "2.15"` |

`"17"` reads as 17 as today; a boolean is never a version (`version: yes` is YAML 1.1 `true` and fails with `version 'True'`).

## Contract: renderer behaviour

**Effective major** `cfg["resources"][r]["envs"][env]["version"]`: the instance's `version`, else the resource's, else 17 / 9 / `"2.15"`.

**Pin of an in-cluster instance** `cfg["resources"][r]["envs"][env]["pin"]` (new; `None` when external):

1. `env == "dev"`, or no rendered file of that instance exists, or its rendered image is of another major than the effective one: the
   table's reference for the effective major (`POSTGRES_IMAGES`, `VALKEY_IMAGES`, `NATS_IMAGES` + `NATS_CHART["chart_version"]`,
   `SEAWEEDFS_IMAGE`).
2. Otherwise (staging or prod, same major): the image of the existing rendered file — `addons/<env>/<r>/<active cluster file>`
   `spec.imageName` (the active generation's file, spec 117), `statefulset.yaml` container `valkey`, `server.yaml`
   `spec.source.helm.valuesObject.container.image` (`repository:tag`) together with its `targetRevision`, `seaweed.yaml` `spec.image` —
   kept byte for byte.

   The major of a rendered image is read from its tag: `postgresql:(\d+)`, `valkey:(\d+)`, `nats:(\d+\.\d+)`; SeaweedFS has one major.
   A file that does not parse is treated as absent. `render --check` is deterministic (it reads the tree it checks).

**A backed-up database's archive per major** (CloudNativePG: change `serverName` with `imageName`): `addons/<env>/<db>/restore-state.yaml`
(spec 117's file) gains an optional top-level `archives: [{server: <name>, major: <int>}, …]`, written only by `cplat resource upgrade`.
The last entry is the current archive. The renderer:
- adds `serverName: <archives[-1].server>` to the active (and `previous`) cluster's plugin `parameters` (after `barmanObjectName`) when
  `archives` exists and the last server differs from the cluster's name; without `archives` nothing changes (byte-identical);
- renders a `restored` generation whose `from.server` is an archive entry with another major on **that** major's table image (the data
  of a physical backup only starts on its own major), and so does the active generation after a switch to it;
- prints, when the active generation's major differs from the effective major,
  `note: applications/<s>: <db> in <env> runs <cluster> on <m> (restored from before the upgrade to <v>); set resources.<db>.instances.<env>.version: <m>, or upgrade it again with /resource:upgrade <db> --to <v> --env <env>`.

**Changed after review (AC-121.16).** A restore reads the archives like this: `--to latest` restores from the current archive
(`archives[-1]`); each archive's recovery window closes where the next archive starts (the time of the major step), so a time picks
exactly one archive and a time inside the old window restores the old major. Switching to a restored generation gives it its own server
name (spec 117's rule: one Barman server per generation, because CloudNativePG refuses a non-empty archive): `cplat resource restore
--switch` appends `{server: <generation>, major: <major of its source archive>}` to `archives` and writes `archive: <server>` on the
cluster that becomes `previous`, so both archive apart; the renderer gives a `previous` cluster `serverName: <its archive>` and the
active one `archives[-1].server`. Databases without `archives` render as before.

`read_restore_state` validates `archives` (a list of mappings with a non-empty `server` and an integer `major` in the table, servers
unique) with 117's error form `… is not valid (archives: <reason>); take it from git history`.

## Contract: environment-property operators (AC-121.17, AC-121.18)

`templates/gitops-app/copier.yml`, after `resource_metrics`:

```yaml
property_operators:
  type: str
  help: "Who installs External Secrets, Kyverno and the LGTM dev stack on the cluster? install: the platform, as Argo CD applications under operators/, only for what the system uses; owner: the cluster's owner (every repo created before this release keeps owner)."
  choices: [install, owner]
  default: owner
```

The default is `owner` because `/platform:update` writes a new question's default into an existing repo, whose cluster has these
operators installed by hand (the documented 5.0 path); a second install would collide. `cplat system new` passes
`--data property_operators=install`, so new systems get AC-121.17 in full. A missing answer reads as `owner`.

With `install`, `operator_files` adds, for every environment not in `cfg["operators"]`:
- `external-secrets` where a running component has effective `secrets` or `secretRefs` (125's rule), a used resource instance is
  external, an in-cluster bucket, cache or broker instance runs (their credentials are generated by External Secrets), or the environment
  has `backup`;
- `kyverno` where `policy_envs(services, cfg)` holds the environment;
- `lgtm` where `observability.ui == "lgtm"` and an instance runs.

`external-secrets` and `kyverno` render with `operator_application` (their existing rows). LGTM is not a chart: `operators/apps/lgtm.yaml`
is an Application `operator-lgtm` (same metadata and labels as the others, no finalizer) whose source is
`{repoURL: <gitops repo>, targetRevision: main, path: operators/lgtm}`, destination namespace `observability`, sync options
`[CreateNamespace=true, ServerSideApply=true]`; `operators/lgtm/` holds `deployment.yaml` and `service.yaml` exactly as `local-cluster.sh`
applies them today (image `LGTM_IMAGE`, no dashboards mount, no HTTPRoute) and `kustomization.yaml`. The ClusterSecretStore stays the
cluster owner's (or the cluster repo's). Cluster repos keep their rules: they list `external-secrets` and `kyverno` already; `lgtm` is not
an `OPERATORS` row and a cluster repo does not install it.

`local-cluster.sh` with Argo CD installs ESO, Kyverno and LGTM itself only when `operators/apps/<name>.yaml` does not exist; a cluster that
already has the k3s HelmChart `external-secrets` (or `kyverno`) keeps it with the 115-style message
`External Secrets was installed by an older cluster-up (HelmChart kube-system/external-secrets); keeping it. Recreate the cluster to let Argo CD manage it`
(`Kyverno was installed …` likewise). Without Argo CD (`WITH_ARGO=0`) nothing changes.

## Contract: `cplat resource upgrade` (AC-121.6 to AC-121.9, AC-121.12 to AC-121.14, AC-121.27)

`cplat resource upgrade <name> --to <major> [--env dev|staging|prod] [--pr [--wait]] [--context [ENV=]CTX]… [--component-dir C=DIR]…
[--app S] [--repo-dir D] [--dry-run] [--json]` and `cplat resource upgrade <name> --verify --env <env> [--context …] [--component-dir …]
[--pr [--wait]]`. `/resource:upgrade <name> --to <major> [--env <env>]` runs it with `--pr --wait`. `--env` defaults to the first
environment (in ENVS order) where the resource has an instance. `<major>` is read like a `version` value (`17`, `"2.15"`).

A **major step** moves an environment to another major; a **pin move** (`--to` equal to the environment's current major) moves it to the
table's pin of that major (releasing a hold, AC-121.11). Every check runs before anything is written, in this order; each failure is a
`PlatformError` (exit 1, nothing changed):

| # | Case | Text | Hint |
|---|---|---|---|
| 1 | `--env` | `--env must be dev, staging or prod` | |
| 2 | unknown | `<n> is not a resource of the system (resources: <names or none>)` | |
| 3 | bucket | `<n> is a bucket: it has no version; its SeaweedFS image moves with the platform release (/platform:update, dev first)` | |
| 4 | `--to` not a version of the type | `version '<v>' is not a supported <type> version (<SUPPORTED_MAJORS and DEPRECATED_MAJORS of the type>)` | |
| 5 | no instance in `<env>` | `<n> has no instance in <env> (no component that runs in <env> uses it)` | |
| 6 | external in `<env>` (AC-121.13) | `<n> is external in <env>: its owner upgrades it, the platform does not` | |
| 7 | `--to` lower (AC-121.14) | `<n> in <env> is on <cur>; <to> is lower and /resource:upgrade only moves up` | database: `the way back for a database is /resource:restore <n> --env <env> --to <time\|latest>` |
| 8 | `--to` deprecated (major steps only; a pin move on the current major, even a deprecated one, is allowed) | `<to> is deprecated: upgrade to one of <SUPPORTED_MAJORS of the type>` | |
| 9 | unsupported jump (AC-121.14) | `<n> in <env>: <cur> → <to> is not a supported upgrade path for <engine>; upgrade to <the highest of UPGRADE_PATHS[cur] below <to>> first` | `/resource:upgrade <n> --to <intermediate> --env <env>` |
| 10 | earlier environment not ready (AC-121.9) | `<prev> is not ready for <env>: <n> in <prev> <state>` | see below |
| 11 | held pin before a major step | `<n> in <env> still runs <held ref> from an earlier platform release; move it to this release's <cur> pin first` | `/resource:upgrade <n> --to <cur> --env <env>` |
| 12 | nothing to do | — prints `<n> in <env> already runs <ref>; nothing to do`, exit 0 | |
| 13 | database major step, no `instances.<env>.backup` (AC-121.12) | `<n> in <env> has no backup: resources.<n>.instances.<env>.backup is required for a major upgrade` | `set it in system.yaml, then /resource:backup <n> --env <env>` |
| 14 | database major step, `last_success` null or older than 60 minutes | `<n> in <env>: the last successful backup is <time> (more than 60 minutes ago); a major upgrade needs one from the last 60 minutes` (`<time>` = `never` when null) | `take one now: /resource:backup <n> --env <env>` |
| 15 | backups unreadable | `cannot read the backups of <n> in <env>: <state or reason>` | `check the kube context: cplat system status --context <env>=<ctx>` |
| 16 | dirty tree | `gitops.require_clean`'s text | |

`<prev>` is the nearest earlier environment in ENVS order where the resource has an instance (none for the first one: no check 10).
`<state>`: `runs <major> (<ref>), not <to> (<this release's pin>)` → hint `/resource:upgrade <n> --to <to>` (plus ` --env <prev>` unless
`<prev>` is the first environment); `is on <to> but not verified` → hint `cplat resource upgrade <n> --verify --env <prev>`;
`failed its verification at <at> (<check>)` → same hint; `cannot be read (<reason>)` → hint `pass --context <prev>=<ctx>`. "Ready" means:
`<prev>`'s rendered pin is the table's pin of `<to>` and its record (below) says `verified` for exactly that `image`. For a pin move, `<prev>` may run `<to>` or a higher major: `<to>` then reads as `<prev>`'s own major (so a held staging can take its pin move once dev has moved on).

Checks 13–15 call `status.collect_backups(repo, app, contexts)` in-process and take the entry of `<n>`/`<env>` from
`status.public_backups(...)["resource_instances"]`, i.e. exactly what `cplat system status --json` shows as `backup.last_success`
(`state` `unknown` → check 15). Age = `now − last_success` in UTC seconds; 3600 s is still recent. Cache and broker major steps and every
pin move skip 13–15 (AC-121.11, AC-121.27).

If the edit or the render fails, every file under `applications/` and `bootstrap/` is put back as it was and the command exits 1 with the error.

**The step's edit** (round-trip YAML through `gitops.load`/`gitops.save`, comments kept), then `gitops.render`:
- a major step on the last environment that has an instance: `resources.<n>.version: <to>`, every `instances.<e>.version` removed (an
  instance mapping left empty is removed, an empty `instances` too); otherwise `resources.<n>.instances.<env>.version: <to>`;
- a pin move: the instance's rendered pin is replaced by the table's in its rendered file (the render then keeps it); `system.yaml` is
  unchanged;
- a database major step with `backup` in `<env>`: `restore-state.yaml` of `<n>`/`<env>` gets `archives` (when absent:
  `[{server: <active cluster>, major: <cur>}]` first; the file is created as `{next: 1, clusters: [{name: <system>-<n>, role: active}]}`
  when absent), then `{server: <system>-<n>-pg<to>, major: <to>}` appended.

Without `--pr`: the tree is left changed (not committed), the report says `wrote the <env> step: <what>; apply it, then verify:
cplat resource upgrade <n> --verify --env <env>`. With `--pr`: branch `resource/upgrade-<n>-<env>-<to>`, commit (signed off) and
`gh pr create`; title `feat(resource): upgrade <n> to <to> in <env>` (major) or `chore(resource): move <n> to <version> in <env>` (pin
move). The body (AC-121.6, AC-121.27):

```
Upgrade <n> (<type>) in <env>: <old major> → <new major>        # pin move: Move <n> (<type>) in <env> to this release's <major> pin
image: <old ref> → <new ref>
backup: last successful <time> (within 60 minutes)               # cache, broker: "<n> has no backup"; pin move: "no backup check (minor or patch move)"
after the merge: the platform waits up to 15 minutes for <n> to be healthy on <new ref>, then runs the smoke tests of <c> (<env>), …
next: staging follows by itself (promote: after-dev-smoke)       # or: /resource:upgrade <n> --to <to> --env <next>; prod: "prod is upgraded by hand"
```

With `--wait`: `cplat pr wait --merge` on the PR, then (when a context is known for `<env>`) the Argo application `addon-<n>-<env>` must be
`Synced` at the merge commit and not `Degraded` within 600 s, then the verification below. `--dry-run` prints the checks' outcome and
the edit, writes nothing. `--json`: `{"step": "major" | "pin", "resource", "type", "env", "from": {"major", "ref"}, "to": {"major",
"ref"}, "pr": <url|null>, "verification": <result|null>, "next": <str|null>}`.

## Contract: verification (AC-121.8, AC-121.15, AC-121.16)

`upgradeverify.verify(repo, app, resource, env, contexts, component_dirs) -> Result`, run by `--verify`, by `--wait` after a merge and by
`cplat platform update --verify`. In order, each bounded, each line printed as it happens:

1. **Health at the pin, ≤ 900 s** (poll 10 s; a progress line every 60 s: `  waiting for <n> in <env>: <what> (<m>m of 15m)`):
   - database: `clusters.postgresql.cnpg.io <active>` in `<system>-<env>`: `.status.phase == "Cluster in healthy state"`,
     `.status.readyInstances == .spec.instances`, `.status.image == <pin>`, and `.status.pgDataImageInfo.majorVersion == <major>` when set;
   - cache / broker: `statefulsets.apps <system>-<n>`: `readyReplicas == updatedReplicas == spec.replicas`, `currentRevision ==
     updateRevision`, container `valkey` / `nats` image `== <pin>`;
   - bucket (pin moves only): pods `<system>-<n>-master-0`, `-volume-0`, `-filer-0` Ready with image `== <pin>`.
2. **Secret names**: `secrets <system>-<n>-app` exists (broker: `<system>-<n>-<c>-app` for every provider and consumer of its events APIs
   running in `<env>`).
3. **Smoke**: for every component instance in `<env>` that uses the resource (database, cache: `uses`; broker: providers and consumers of
   its APIs), in `components:` order, `smoke.run_smoke(<dir>, <instance url>, env=<env>, probe=liveness_probe(<dir>))`. `<dir>`: the
   `--component-dir` entry, else a shallow clone of `components.<c>.repo` at the commit the instance runs (`sha-<40>` → that commit;
   a release tag → the tag; `latest` → `main`). No repository, a failed clone or no `smoke` recipe fails the check (`smoke <c>: <reason>`).
4. **Backup** (database with `backup`, after a major step): the first base backup of the new archive is started
   (`backupstate.take_first_backup`), `first base backup of <cluster> on <major> started (Backup <name>)`; its result is not waited for.

Record (always, also on failure), applied with `kubectl --context <ctx> apply -f -`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: <system>-<n>-upgrade
  namespace: <system>-<env>
  labels: {app.kubernetes.io/name: <n>, app.kubernetes.io/part-of: <system>, app.kubernetes.io/managed-by: cplat}
data: {major: "<major>", image: "<pin>", state: verified | failed, at: "<RFC 3339 UTC Z>", check: "<failed check or empty>", release: "<platform version>"}
```

It is not in git, so Argo CD never prunes it; the name label keeps it out of Velero's environment backups (ADR-062). `read_record(system,
resource, env, context) -> dict | None` is what checks 10, status and doctor read.

Output, verified (exit 0):

```
upgrade <n> in <env>: verified (<major>, <pin>)
  ok   <n> healthy on <major> after <m>m<s>s (<what>)
  ok   Secret <system>-<n>-app kept its name
  ok   smoke <c> (<env>): <passed> passed
next: staging follows by itself (promote: after-dev-smoke)   |   /resource:upgrade <n> --to <major> --env <next>   |   all environments are on <major>
```

Not verified (exit 1, AC-121.16), the first failed check ends the run:

```
upgrade <n> in <env>: NOT VERIFIED (<check>)
  FAIL <n> not healthy on <major> after 15 minutes (<phase or replica counts>)      # or: FAIL Secret …, FAIL smoke <c> (<env>): <failing tests>
  last successful backup: <time | never | none (<type> has no backup)>
  way back: /resource:restore <n> --env <env> --to <time|latest>                     # database only
  no later environment is upgraded until <env> is verified
```

After a verified **dev** step with `environments.staging.promote: after-dev-smoke` and an instance in staging, the same run performs the
staging step (same `--pr`/`--wait` mode, so locally it writes the tree and stops) and, with `--wait`, verifies it; with `manual` (the
default) it prints the command. Nothing ever starts prod.

## Contract: `/platform:update` and its verification (AC-121.11, AC-121.20 to AC-121.23)

In a gitops-app, after the template copy and before the commit, `cplat platform update` runs the repo's new `render.py` (held pins follow
from the renderer), and adds to the report and `--json` (`data["versions"]`):

```
versions in this system (platform <old> → <new>):
  dev       postgres 16: ghcr.io/cloudnative-pg/postgresql:16 → ghcr.io/cloudnative-pg/postgresql:16.15-…@sha256:1ec419e9… (moves now)
  staging   postgres 16: keeps ghcr.io/cloudnative-pg/postgresql:16 until /resource:upgrade postgres --to 16 --env staging
  prod      postgres 16: keeps … until /resource:upgrade postgres --to 16 --env prod
  cluster   operator cloudnative-pg 0.27.0 → 0.29.1 (operators/apps; shared by dev, staging, prod: moves with dev's step)
```

The lines come from the rendered tree before and after (each instance's pin, each `operators/apps` file's `targetRevision`), restricted to
what changed. `fleet_pr.py` puts the same block into the update PR's body. A component repo is unchanged.

`cplat platform update --verify [--context [ENV=]CTX]… [--component-dir C=DIR]…` (after the update is merged and synced): for every
operator in `operators/apps/` (and, with `operators: owner`, every operator an environment needs), wait ≤ 900 s until doctor's reading is
`ok` (installed = table and every CRD serves the table's versions, AC-121.22); then the health check of every dev resource instance whose
pin moved; then the smoke tests of **every** component instance of every environment on that cluster (all three in 5.x, AC-121.21). It
records `verified`/`failed` for each moved dev resource as above, prints the same verified / NOT VERIFIED blocks, and on success starts
the staging pin moves (after-dev-smoke) or prints them.

## Contract: the gitops CI check (AC-121.10)

`templates/gitops-app/scripts/upgrade-check.py --base <ref>` (recipe `upgrade-check`, job `upgrade-check (one environment per major)` on
`pull_request`, checkout with `fetch-depth: 0`, `--base origin/${{ github.base_ref }}`): for every `applications/*/system.yaml` present on
both sides, load both with `render.load_system` (the base file through a temporary copy) and compare each in-cluster resource instance's
effective major per environment. A resource whose major changes in two or more environments fails:

`ERROR: applications/<s>/system.yaml: resources.<r>: the major changes in <env1>, <env2> at once (<old> → <new>); upgrade one environment per pull request with /resource:upgrade <r> --to <new> [--env <env>]`

(`<old>` is listed per environment as `dev 16, staging 16` when they differ.) Otherwise `OK: no resource changes its major in more than
one environment`, exit 0. A base that does not render is ignored with a `WARNING:` line. The folding step passes (only the last
environment's effective major changes).

## Contract: doctor (AC-121.18, AC-121.19, AC-121.21, AC-121.22)

`cplat platform doctor [--context [ENV=]CTX]… [--json]`. `check_operators` covers, in this order, `cloudnative-pg`, `seaweedfs`,
`plugin-barman-cloud`, `cert-manager`, `velero`, `nack`, `keda`, `metrics-server`, then (only with `property_operators: install`)
`external-secrets`, `kyverno`, `lgtm` (`lgtm`: `deploy/lgtm` in `observability`, selector `app=lgtm`). Each row gains JSON keys (texts
unchanged without `--context`):

```json
{"operator": {"state": "ok" | "missing" | "older" | "newer", "expected": "1.30.1", "installed": "1.30.1" | null,
              "crds": {"clusters.postgresql.cnpg.io": {"expected": ["v1"], "served": ["v1"]}}, "shared": ["dev", "staging", "prod"]}}
```

`state`: `missing` (no Deployment), `older` (installed < expected, or a CRD lacks an expected served version), `newer` (installed >
expected), else `ok`. `served` = `kubectl get customresourcedefinitions.apiextensions.k8s.io <name> -o
jsonpath={.spec.versions[?(@.served==true)].name}`. `shared` = the environments that need the operator on that cluster.

With `--context`, the environments named (or all, for a plain `CTX`) are read in that context, and the row's detail is
`<state>: installed <have|none>, expected <want> (<where>); crds <crd> <served or missing>, …; shared by <envs>` (`; shared by` only with
more than one environment); status FAIL for `missing` and for `older` by a major (the first version number differs, or the second for a
`0.x` version), WARN for other `older` and `newer`, OK for `ok`. `operators: owner` environments are checked the same way (AC-121.18).
Exit 1 when any row is FAIL (doctor's existing rule).

`check_brokers` compares and prints references **without** their digest (`@sha256:…` stripped on both sides), so its texts stay those of
spec 119; the digest is the pin check's concern.

## Contract: model, `cplat model show`, status (AC-121.5, AC-121.15)

- **Model**: `ResourceInstance.version: int | str | None` (the effective major; `None` for external and buckets) and
  `ResourceInstance.pinned: str | None` (the image the instance's rendered file pins; `None` when external or not rendered yet).
  JSON (schema stays 2): every `resource_instances[]` gains `"version"` and `"pinned"` after `"backup"`. `cplat model show` text is
  unchanged.
- **`cplat system status`**: JSON gains `"resource_versions": [{"resource": <n>, "type": <t>, "cells": {<env>: <cell> | null}}]` (resources
  in declaration order, only those with an instance); `<cell>` = `{"version", "pinned", "held": bool, "health": "healthy" | "upgrading" |
  "degraded" | "unknown" | "external", "upgrade": {"state", "major", "image", "at", "check"} | null}`. `held` = the pin differs from the
  repo's own table pin of that major. Health reads the same objects as the verification's step 1 (one `kubectl` call per instance with the
  environment's context; `unknown` without a context or on failure). Text, after the resource grid and before "Backups":

```
Resource versions (read from the cluster k3d-shop-local now):
  resource   dev                         staging                          prod
  orders-db  17 (17.11) healthy upgraded  16 (16.15) healthy               16 (16) healthy held
  sessions   9 (9.1.3) healthy            9 (9.1.3) healthy                external
```

  Cell text: `<major> (<version part of the pin>) <health>`, then `  upgraded` when the record is `verified` for the current pin,
  `  upgrade failed (<check>)` when it is `failed`, `  held` when held; `external`; `-` without an instance. The existing `resources`
  grid and its cells do not change.

## Contract: local cluster (AC-121.4, AC-121.17)

`local-cluster.sh` (and its byte-equal cluster-gitops copy) keeps one literal default per pin, each equal to its table row (the pin check
enforces it, as the 115–120 tests already do for the operator charts): `ARGOCD_VERSION` `v3.4.12` (no more `stable`), `K3S_IMAGE`
`rancher/k3s:v1.32.5-k3s1@sha256:b75e…`, `LGTM_IMAGE` `grafana/otel-lgtm:0.35.0@sha256:2de1…` (`LGTM_VERSION`, when set, keeps its meaning:
image `grafana/otel-lgtm:<tag>`), `VELERO_AWS_PLUGIN_IMAGE` with its digest, the operator chart versions as today (the `rev_of
operators/apps/<op>.yaml` defaults stay). For every version or image variable a user set that differs from its default, before anything
is created:

`WARNING: <VAR>=<value> overrides the versions table (<row> <table version>); this cluster does not run what this platform release pins`

and the override is installed (AC-121.4). With Argo CD, ESO, Kyverno and LGTM come from `operators/root.yaml` when their `operators/apps/`
file exists (bootstrap waits for `clustersecretstores.external-secrets.io` and `namespacedvalidatingpolicies.policies.kyverno.io`;
`deploy/lgtm` rollout ≤ 300 s); otherwise the k3s HelmChart and the LGTM Deployment as today.

## Contract: pin check and release check (AC-121.2, AC-121.23, AC-121.24 gate, AC-121.26)

**`scripts/check-pins.py`** (ci.yml, job `validate-shapes`, step "every image and chart comes from the versions table"; also
`devbox run validate`). Fails, one line per finding `ERROR: <file>:<line or document path>: <reference>: <reason>`, then
`FAILED: <n> reference(s)`; else `OK: <n> references, all from the versions table`. Reasons: `not in the versions table`, `no digest`,
`floating tag '<tag>'` (`latest`, `stable`, `edge`, `main`, `master`, `nightly`, a bare major `\d+` or `v\d+`, a `<major>.<minor>` tag
where the row's version has three parts), `chart without an exact version` (not `^v?\d+\.\d+\.\d+$`), `differs from the versions table
(<row>: <table value>)`. It checks:
1. every table row (images: `<repo>:<tag>@sha256:<64 hex>`; charts and manifests exact);
2. a coverage render (a temporary gitops-app with every resource type in-cluster, backups, `ui: lgtm`, `policy: enforce`, a cpu and a
   queue `scale`, `resource_metrics: install`, `property_operators: install`): every `image`, `imageName`, `repository`+`tag` pair and
   every Argo `source` with `chart` + `targetRevision` in `applications/`, `bootstrap/`, `operators/` must equal a row;
3. `templates/gitops-app/scripts/local-cluster.sh` and `bootstrap.sh`, and the cluster-gitops scripts: every image reference (`image:`,
   `--image`, `*_IMAGE=` defaults), every chart `version:` in a HelmChart and every `*_VERSION` default must equal its row (the copy in
   `templates/cluster-gitops` is byte-equal and covered by `sync-template-copies.py --check`).

**`scripts/release-check.py`**:
- `rows --base <ref>`: runs `versions.py --diff <ref> --changelog` (ref default: the newest tag `v*` reachable from HEAD). Fails when a
  changed row's line is missing from the CHANGELOG section that will be released (the first `## [x.y.z]` heading newer than `<ref>`, else
  `## [Unreleased]`): `ERROR: docs/CHANGELOG.md: <section> does not list <line>`. Fails (AC-121.26) when a change is `(major)`, a CRD
  version is removed, or a `SUPPORTED_MAJORS`/`DEPRECATED_MAJORS` value is dropped, unless the released heading's version has a higher
  first number than `<ref>`: `ERROR: <change> needs a major platform release (<ref> → <version>)`. Runs in ci.yml as job
  `release-check (versions table)` on every PR and on main.
- `needs-upgrade-e2e --base <ref>`: prints `run=true|false` for `$GITHUB_OUTPUT`: true when the changes add a release heading, change a
  table row, or touch `tests/e2e/upgrade.sh`, `.github/workflows/e2e-upgrade.yml`, `scripts/cplat/upgrade*.py`, `scripts/cplat/update.py`.
- `gate <sha>`: exit 0 only when the commit has a check run named `e2e upgrade (previous release → candidate)` with conclusion `success`
  (`gh api repos/<repo>/commits/<sha>/check-runs`); else `ERROR: <sha> has no green upgrade e2e (<conclusion or none>): do not tag it`.

**Release gate.** `.github/workflows/release-guard.yml` (`on: push: tags: ['v*']`, `permissions: {contents: read, checks: read}`): job
`release gate (upgrade e2e green)` runs `gate ${{ github.sha }}` and fails red on a tag without a green upgrade e2e. CONTRIBUTING's
Releases procedure gains: run `python3 scripts/release-check.py gate <merge sha>` and tag only when it passes; a red release gate on a
tag means a maintainer deletes that tag. No workflow creates, moves or deletes a tag or a release.

## Contract: the upgrade e2e (AC-121.24, AC-121.25 and the cluster halves of AC-121.4, .5, .8, .11, .15, .16, .19, .21, .22)

`.github/workflows/e2e-upgrade.yml` — triggers `pull_request` (paths: `templates/gitops-app/scripts/render.py`,
`templates/gitops-app/scripts/local-cluster.sh`, `scripts/cplat/upgrade*.py`, `scripts/cplat/update.py`, `scripts/cplat/versions.py`,
`scripts/release-check.py`, `tests/e2e/upgrade.sh`, the workflow, `docs/CHANGELOG.md`), `push` to `main` (same paths), nightly
`schedule` and `workflow_dispatch`; `permissions: contents: read`. Job `decide` (2 minutes) runs `needs-upgrade-e2e`; job `upgrade`,
named `e2e upgrade (previous release → candidate)`, runs when `run=true` or on schedule/dispatch: checkout `fetch-depth: 0`, setup-uv,
copier, k3d v5.8.3, `bash tests/e2e/upgrade.sh`, `timeout-minutes: 75`. It is a separate workflow because the e2e job uses about 75 of
its 90 minutes.

`tests/e2e/upgrade.sh` (same conventions as `run.sh`: `fail`/`step`, bounded waits that name their seconds, long commands streamed with
`tee /dev/stderr`, full kind names — `clusters.postgresql.cnpg.io`, `statefulsets.apps`, `deployments.apps`, `configmaps`, `secrets`,
`helmcharts.helm.cattle.io`, `customresourcedefinitions.apiextensions.k8s.io`, `streams.jetstream.nats.io` — commit before every
`cplat` command that writes, probes that read the component's own Secret as a component would, whole-word matches with `grep -w` or
`re.search(r"\b…\b")`, YAML read with `yaml.safe_load` and keys/values compared as strings so `on`/`off`/`yes`/`no` cannot turn into
booleans):

1. **From.** `FROM` = `$E2E_UPGRADE_FROM`, else the newest tag `v5.0.*` while no release tag contains `scripts/cplat/versions.py`, else the
   newest such tag older than the candidate; `git worktree add $work/from $FROM`. No tag: `fail "no previous release tag found (v5.0.*)"`.
2. **Setup on FROM** (FROM's own `cplat` and templates): system `upg` with a python service `upg-api` (instances dev, staging, prod) using
   `postgres` (`--version 16`), staging `promote: after-dev-smoke`; image built and pushed to the local registry; FROM's `local-cluster.sh
   up` (`WITH_ARGO=0`, no version variables: its floating defaults); the three environments applied and healthy (≤ 600 s each). Resource
   types FROM supports (its `RESOURCE_TYPES` minus `PLANNED_TYPES`, read with `ast`) add `files` (bucket), `sessions` (cache), `bus` (broker
   carrying events API `orders`, provided and consumed by `upg-api`); an unsupported type prints `skip: <type> is not in <FROM>`.
   **Resolved floating references**: every container `imageID` in the system and operator namespaces and every HelmChart's chart version
   are printed as `resolved <reference> -> <digest or version>` and saved to `$work/resolved-<FROM>.txt` (AC-121.24).
   Data: per environment a row `(1, '<env>-before')` in table `upg_check`, an object `upg/<env>.txt`, a cache key, a stream message.
3. **Update to the candidate**: candidate `cplat platform update` in the gitops repo; its report lists dev's moved pin and staging's and
   prod's held pins; dev's `cluster.yaml` pins the table's 16, staging and prod keep FROM's reference. Candidate `local-cluster.sh up`
   on the same cluster (operators move once, AC-121.21); no `WARNING: … overrides` line. Dev applied; `cplat platform update --verify
   --context k3d-<c> --component-dir upg-api=$work/upg-api` verified (operators `ok`, CRDs at the table's versions, smoke of all three
   environments); the staging pin move it writes is committed, applied, verified; prod `--to 16 --env prod` likewise (AC-121.11). Data
   reads back unchanged.
4. **Guard (AC-121.25, first half)**: bucket `backups` and `backup: {to: backups}` on all three instances, rendered and committed but not
   applied; `cplat resource upgrade postgres --to 17` exits 1 naming `never` and `/resource:backup postgres --env dev`; HEAD, tree and the
   dev Cluster's `.spec.imageName` and `.metadata.generation` are unchanged. Then applied; each environment's `last_success` is set
   within 600 s (read from `cplat system status --json`).
5. **Major upgrade with a forced failure (AC-121.25, second half)**: dev step written, committed, applied; `--verify --env dev` with
   `--component-dir upg-api=$work/upg-api-failing` (a copy whose `smoke` recipe prints `FAIL forced` and exits 1) exits 1 naming dev,
   `smoke upg-api`, the last backup time and `/resource:restore postgres --env dev`; `--to 17 --env staging` exits 1 naming dev and
   `failed its verification`; staging and prod report `pgDataImageInfo.majorVersion` 16 and their rows read back. `--verify --env dev`
   with the real repo is verified and writes the staging step (after-dev-smoke); staging applied and verified; `--to 17 --env prod`
   folds the entries (no `instances.*.version` left, `version: 17`); prod applied and verified.
6. **Checks**: every environment reports major 17 and `server_version` 17.11; the row, object and message of step 2 read back unchanged
   (the cache key is not required); `cplat instance verify` green for every instance; `cplat platform doctor --context k3d-<c> --json`
   has every operator row `state == "ok"`; `cplat system status --json` shows `upgrade.state == "verified"` everywhere;
   `kubectl apply --dry-run=server -k` of every rendered addon and overlay is accepted (AC-121.22). Prints `UPGRADE E2E OK`.

Budget: about 40 minutes (FROM's setup 10, update and pin moves 9, backups 5, the three major steps with the forced failure 12, checks
4); the job has 75.

## Timings

- Health wait 900 s per step (poll 10 s, progress every 60 s); Argo sync wait 600 s before it (only with `--wait` and a context).
- Backup age: `now − last_success ≤ 3600 s` at the moment of the check, UTC.
- `cplat pr wait` keeps its own limits; smoke keeps `smoke.LIMIT_S`.

## Risks

- **A failed `pg_upgrade`** leaves the data untouched; CloudNativePG restarts the old major once `imageName` goes back. The platform's way
  back stays `/resource:restore` (spec non-goal: no automatic rollback); the guide mentions the hand-edit revert of a failed job.
- **Distribution**: 5.0's floating `postgresql:<major>` images are legacy builds; a held staging/prod must take this release's pin (a
  minor move) before its major step (check 11), so `pg_upgrade` always runs trixie → trixie. The bootstrap uses CloudNativePG's default
  `C` locale, so the glibc change of that minor move does not reorder indexes.
- **The current plain Postgres tags are frozen**: checked 2026-10-28 (orchestrator), `docker manifest inspect` finds
  `ghcr.io/cloudnative-pg/postgresql:15.19`, `16.15`, `17.11` and `18.6`, so 5.1–5.3 databases pull fine (the 117–120 e2e runs used
  them); upstream no longer builds plain tags, so they receive no further patches. t1 moves to the `standard-trixie` tags with digests.
- **`imageName` with tag and digest** is used by CloudNativePG's own image catalogs; the e2e proves that the operator parses the major
  from such a reference (not verified from source, see below).
- **Docker official images are rebuilt** (valkey, nats show `last_updated` of 2026-10-27): a digest pin keeps the image; t1 re-reads every
  digest at build.
- **The CloudNativePG chart repository moved** (`https://cloudnative-pg.github.io/charts/index.yaml` answers 301 to
  `https://cloudnative-pg.io/charts/index.yaml`); Argo CD and Helm follow it. Changing `repo_url` would change every `operators/` file;
  left for a later release.
- **CRDs of charts that keep them in `crds/`** are not upgraded by the k3s helm-controller (local `WITH_ARGO=0`); Argo CD applies them.
  The e2e's doctor CRD comparison catches a stale CRD; t1 records per chart where its CRDs live.
- **Several systems in one gitops repo** share one `operators/`: an operator moves for all at dev's step; `--verify` runs every system's
  smoke tests.
- **Records in the cluster**: a lost record (namespace recreated) only means the next environment asks for `--verify` again.

## Spec readings resolved by default (each needs a changelog line in spec.md before its acceptance tests are written)

- **AC-121.3 (Postgres majors)**: 16, 17, 18 are supported and upgrade targets; 15 stays renderable as `deprecated` (dropping it would
  need a major release under AC-121.26; spec 115 supports it) and is never a target.
- **AC-121.3 / AC-121.27 (bucket)**: a bucket has no `version`; its SeaweedFS image is one per release and moves as a pin (AC-121.11).
  `/resource:upgrade` on a bucket refuses (check 3); AC-121.27's bucket case applies once a release lists two SeaweedFS majors.
- **AC-121.2 / AC-121.3 vs the byte-identity of AC-115.6, AC-118.22, AC-119.24, AC-120.26**: engine image references gain exact tags and
  digests; everything else stays byte-identical (amended tests compare after mapping the references back).
- **AC-121.17 (ESO, Kyverno, LGTM)**: rendered when the repo answers `property_operators: install` (new systems); existing repos keep
  `owner` until they choose, because their clusters run hand-installed copies.
- **AC-121.19 ("with access to an environment's cluster")**: doctor knows an environment's cluster only through `--context [ENV=]CTX`;
  with it the states fail as specified, without it doctor keeps today's warnings against the current context.
- **AC-121.20 (separate clusters)**: every environment of a gitops repo deploys to its one `cluster_server` (ADR-058, ADR-066), so 5.x has
  no environments on separate clusters; AC-121.21 governs. The rule is documented for a later spec that adds per-environment clusters.
- **AC-121.24 (first run from 5.0.x)**: 5.0.x has no backups (spec 117, 5.2.0) and no bucket, cache or broker; the first run creates the
  database on 5.0.x, adds backups after the update (AC-121.12 needs them), and creates each other resource only when the previous release
  supports it.
- **AC-121.24 ("a release is not tagged")**: tags are made by people; the gate is a CI check plus the procedure, and a tag-push check
  turns red. Nothing tags or deletes automatically.

## Decisions taken by default

1. **In-place `pg_upgrade` for database majors.** Alternative: import into a new generation (needs a second cluster and a Secret switch).
2. **`standard-trixie` Postgres images, immutable build tags with digests.** Alternatives: `minimal-trixie` (no pgvector, PGAudit,
   locales); `system` (deprecated upstream).
3. **15 deprecated, not dropped.** Alternative: drop 15 (a major platform release).
4. **Held pins live in the rendered files.** Alternative: a `pins.yaml` state file (one more file for people and CI to keep in step).
5. **A new Barman server name per major (`<cluster>-pg<major>`), recorded as `archives` in `restore-state.yaml`.** Alternative: keep one
   server name (CloudNativePG warns of archive conflicts after `pg_upgrade`).
6. **Verification records are ConfigMaps in the environment's namespace.** Alternatives: a follow-up commit (another PR per step); the run
   store (optional, may be unset).
7. **Smoke tests run from a shallow clone at the instance's commit, or `--component-dir`.** Alternative: dispatch each repo's CI (no
   cluster access from hosted runners).
8. **A component without smoke tests fails the verification.** Alternative: count readiness only (weaker than AC-121.15).
9. **A major step needs the environment on this release's pin first (check 11).** Alternative: one combined step (`pg_upgrade` across
   distributions fails).
10. **`property_operators: install | owner`, default `owner`; `cplat system new` answers `install`.** Alternative: always render ESO,
    Kyverno, LGTM (double installs on every existing cluster).
11. **LGTM rendered as plain manifests under `operators/lgtm/`, not installed by cluster repos.** Alternative: a chart (there is no
    official otel-lgtm chart).
12. **ESO needed also by in-cluster caches, brokers and environment backups** (their Secrets come from generators). Alternative: 125's
    narrower rule (a cache would start without its password).
13. **Argo CD v3.4.12** (newest release tested on Kubernetes 1.32, the local k3s). Alternative: v3.5.6 (tested on 1.33–1.36 only).
14. **k3s and the Gateway API manifest are table rows** (the local script installs them); moving the cluster's Kubernetes stays a non-goal
    (a new k3s pin applies to new local clusters).
15. **Doctor escalates to FAIL only with `--context`.** Alternative: always (fails every doctor run pointed at an unrelated cluster).
16. **`--to <current major>` is the pin move.** Alternative: a separate verb.
17. **Default `--env` is the first environment with an instance** (dev when it has one).
18. **No `--confirm prod` for the prod step**: `--env prod` is already explicit and nothing deletes data.
19. **The upgrade e2e is its own workflow with a 75-minute limit**, gated by `needs-upgrade-e2e`; the release gate checks its check run on
    the tagged commit. Alternative: a job in `e2e.yml` (its 90 minutes are used up).
20. **The NATS digest rides in `tag`** (119's document shape; the chart prints `repository:tag`). Alternative: `fullImageName` (also read
    by the chart; changes the shape of every `server.yaml`).
21. **The local cluster script keeps literal defaults held equal to the table by the pin check** (the 115–120 tests read them). Alternative:
    read them at run time from `render.py` (drops the literals those tests require).
22. **Doctor's broker rows compare without digests.** Alternative: with digests (every running broker of an older render shows "differs").
23. **The CHANGELOG line format** ``- `<row>` <old> → <new>`` with **(major)**, and the release check reads the section being released.
24. **Plugins: `resource` 1.6.0 (`/resource:upgrade`), `platform` 1.3.0 (`doctor --context`, `update --verify`, `versions`), `system`
    1.5.0 (status).**
25. **Two ADRs** (the rollout of upgrades; the table and the release proof).

## Verified on 2026-10-28 (re-verify at build, plan t1)

- **CloudNativePG docs (branch `release-1.30`, `docs/src/postgres_upgrades.md`)**: major upgrades in place by changing the major in
  `.spec.imageName`; offline; `pg_upgrade --link` in a job; source and target must share the OS distribution; previous version and image
  recorded in `.status.pgDataImageInfo`; on failure revert `imageName`; "change the `serverName` parameter when you trigger the upgrade";
  no PITR across majors, take a new base backup. `api/v1/cluster_types.go` (`release-1.30`): `ImageInfo{image, majorVersion}`,
  `pgDataImageInfo`, phases `Cluster in healthy state`, `Upgrading Postgres major version`, `Upgrading cluster`; status `image`,
  `readyInstances`, `phase`. `container_images.md`: the major comes from `imageCatalogRef.major` or the `imageName` tag.
- **Postgres images**: `cloudnative-pg/postgres-containers` `docker-bake.hcl` (main) builds only `<major>-<type>-<os>`,
  `<major>.<minor>-<type>-<os>` and `<major>.<minor>-<YYYYMMDDhhmm>-<type>-<os>` tags (no plain `17.11`); its README calls the plain tags
  deprecated and no longer generated. `cloudnative-pg/artifacts` `image-catalogs/catalog-standard-trixie.yaml` (label date `20261026`)
  lists the four tags and digests above; the GitHub package page lists `18.6-202610260820-standard-trixie` with digest `39add80f…` and
  signature entries for the other three digests.
- **CloudNativePG Helm index** (`https://cloudnative-pg.io/charts/index.yaml`, read completely, `generated: 2026-10-01T10:18:01Z`; charts
  `cloudnative-pg` 46 versions, `cluster`, `cnpg-sandbox`, `pgbench`, `plugin-barman-cloud` 10): newest `cloudnative-pg` 0.29.1
  (appVersion 1.30.1, created 2026-09-23, digest `b53d3991…`); newest `plugin-barman-cloud` 0.8.1 (appVersion v0.15.1, created
  2026-09-30, digest `9ad0b9e5…`). The pins of spec 115/117 are current.
- **Docker Hub** (`/v2/repositories/<repo>/tags/<tag>`, index digests): valkey 8.1.11 `8f836008…` and 9.1.3 `3add1a33…` (both updated
  2026-10-27), nats 2.14.9-alpine `127c5ccb…` and 2.15.2-alpine `823e7f1d…` (2026-10-27), chrislusf/seaweedfs 4.51 `f7a49e3f…`,
  otel/opentelemetry-collector-contrib 0.162.0 `39923a8e…`, velero/velero-plugin-for-aws v1.14.4 `c85a7fa8…`, grafana/otel-lgtm 0.35.0
  `2de1094c…`, rancher/k3s v1.32.5-k3s1 `b75eac80…`; all `active`, amd64 and arm64 present.
- **Argo CD**: releases API — newest stable v3.5.6 (2026-10-20), v3.4.12 (2026-10-20), v3.3.18 (2026-10-22); `tested-kubernetes-versions.md`
  at v3.5.6: 3.5 → 1.33–1.36, 3.4 → 1.32–1.35.
- **NATS**: Helm index (`https://nats-io.github.io/k8s/helm/charts/index.yaml`, first 100 000 of 166 606 characters read; the `nats` and
  `nack` entries are at the start): `nats` 2.15.1 (appVersion 2.15.1, created 2026-10-13, digest `b209c627…`), `nack` 0.35.0 (appVersion
  0.24.0, created 2026-08-19, digest `54d4760e…`); `_helpers.tpl` at tag `nats-2.15.1` builds `repository:tag` (or `repository@digest`,
  or `fullImageName`).
- **Not verified here (t1 does it at build, with Bash)**: that CloudNativePG 1.30.1 parses the major from a `tag@sha256` `imageName`
  (the e2e proves it); the CRD names and served versions of every operator chart (read from each chart archive); the External Secrets,
  Kyverno, SeaweedFS-operator, cert-manager, Velero, KEDA and metrics-server indexes (unchanged pins, verified by specs 116–120 and 125);
  `docker manifest inspect` of every image above, and of the current `ghcr.io/cloudnative-pg/postgresql:17.11`; that the tags
  `v5.0.0`/`v5.0.1` exist in this repository.

**Re-verified at build (2026-10-28, t1):** every one of the 13 image references matches its designed digest
(`docker buildx imagetools inspect` and `docker manifest inspect <image>@<digest>`); every operator chart version is in its
Helm index (indexes read fully), its appVersion matches `operator_version`, and the archive's sha256 equals the index digest; served
CRD versions were read from the archives at their default values (NACK's `streamtemplates.jetstream.nats.io` has no served version
and is left out). The plain Postgres tags `15.19`, `16.15`, `17.11` and `18.6` still exist. `uv run scripts/check-pins.py` reports
81 references, all from the versions table.
- Known gap (review, AC-121.16): an archive's window closes where the next archive's first recoverability point starts, because
  `archives` records no time for the major step; a time between the step and the new archive's first base backup matches no archive
  and is refused as outside the restore points (never restored from the wrong major). Verification takes that first base backup right
  after the step, so the gap is short.
