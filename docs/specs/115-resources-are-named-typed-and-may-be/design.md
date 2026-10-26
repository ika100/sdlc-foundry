# Design — 115 Resources are named, typed and may be external

## Decisions

- **One contract table per type, one naming rule for all types** (AC-115.5, AC-115.7, AC-115.8). `render.py` gets a `TYPES` table: per type the Secret keys and the variables a using component gets. The Secret is always `<system>-<name>-app` and an in-cluster instance's Argo application `addon-<name>-<env>`. For `postgres` these are exactly the 5.0 names, so nothing moves. ADR: [057](../../adr/057-named-typed-resources-with-fixed-contracts.md).
- **Every database is a CloudNativePG cluster named `<system>-<name>`.** CloudNativePG names its app Secret `<cluster>-app`, so the Secret rule needs no extra object. The initdb database and owner stay `<system with - → _>` in every database, which is what 5.0 renders for `postgres`.
- **External instances get one ExternalSecret per environment, in the overlay of the alphabetically first running component that uses the resource there** (AC-115.9). The spec rules out an Argo application for the resource. Putting the ExternalSecret in every using overlay would make two Argo applications own one object. `creationPolicy: Orphan` keeps the Secret when that first component changes. One `data` entry per contract key, with no `dataFrom` and no defaults, makes External Secrets Operator refuse a store entry that lacks a key: no Secret, an error naming the key on the ExternalSecret, and a component that cannot start (AC-115.12).
- **The versions table lives in `render.py`** (`POSTGRES_IMAGES`, `OPERATORS`) and travels with the renderer to every gitops repo. `cplat` reads the platform's copy for the expected versions. The image family stays the one 5.0 uses (`ghcr.io/cloudnative-pg/postgresql:<major>.<minor>`), so the move from `17` to `17.<minor>` is a minor rolling update by CloudNativePG (AC-115.17). ADR: [058](../../adr/058-pinned-versions-and-platform-installed-operators.md).
- **Supported database majors are 15, 16, 17 and 18**, the rows spec 121's versions table starts with (user decision, 2026-10-26). Any other major fails the render with an error naming the supported majors, because nothing can pin it. **This is the one accepted narrowing next to AC-115.6:** 5.0 never validated `version`, so a 5.0 `system.yaml` with another major (for example 14) no longer renders. Every other 5.0 `system.yaml` renders byte-identically except the pinned image.
- **Operators are cluster-level files outside every system's tree** (AC-115.18; confirmed by the user, 2026-10-26). They go in `operators/root.yaml` and `operators/apps/<operator>.yaml`, written once per repo (one `cluster_server` today) when any system needs them in an environment that is not opted out. `applications/<system>/` and `bootstrap/<system>-root.yaml` stay byte-identical for every 5.0 `system.yaml` except the pinned image (AC-115.6). This also keeps the migration's proof (`update._tree`, which compares `applications/` and `bootstrap/`) meaningful. On an existing cluster, a human applies the root once, like `bootstrap/`; `devbox run bootstrap` and `devbox run cluster-up` apply it for new and local clusters.
- **The migration proof normalises only the database image** (AC-115.6). `update.apply_systems` compares after rewriting `imageName: ghcr.io/cloudnative-pg/postgresql:<major><anything>` to `…:<major>` in `addons/*/*/cluster.yaml`. Everything else must still be byte-identical to the frozen 4.7 render, which stays untouched (`render_v4.py`).
- **Spec 114's tests that 115 supersedes are amended in one task**, named one by one in plan task t14. No other 114 assertion is weakened.
- **"Changing a pin follows spec 121"** (AC-115.17): 121 is not built yet. Until it ships, a new pin reaches every environment on the next render after `/platform:update`. For a minor move inside one major, CloudNativePG does that as a rolling update. Spec 121 replaces this with its rollout.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `templates/gitops-app/scripts/render.py` | schema, `TYPES`, versions table, database clusters, contract variables with prefix, external ExternalSecrets, `operators/` | changed |
| `templates/gitops-app/scripts/local-cluster.sh`, `scripts/bootstrap.sh` (new), `devbox.json`, `CLAUDE.md.jinja` | apply `operators/root.yaml` before the system roots; no k3s CloudNativePG install under Argo CD | changed |
| `scripts/cplat/addon.py` | `resource add <name> --type … [--external [--path]]`, `remove <name>` for any resource | changed |
| `scripts/cplat/model.py` | `Resource.external`, `ResourceInstance.type/external/store_key`, `Environment.operators`, every resource's Secret | changed |
| `scripts/cplat/modelcmd.py`, `status.py` | text output of the new fields; external cells in `/system:status` | changed |
| `scripts/cplat/doctor.py` | operator rows (owner-managed vs platform-managed), fixes the 5.0 `addon postgres` condition | changed |
| `scripts/cplat/update.py` | image normalisation in the migration proof | changed |
| `scripts/cplat/compose.py` | `--uses` help text; next step when the prefix rule starts to apply | changed |

## Contract: `system.yaml` additions

```yaml
environments:
  prod:
    operators: owner              # NEW, optional; the only value. The platform installs no operator for prod.
resources:
  orders-db:                      # name: ^[a-z][a-z0-9-]*$, at most 30 characters, not a component name
    type: database                # REQUIRED: database | bucket | cache | broker
    version: 17                   # database only: 15 | 16 | 17 | 18 (default 17)
    replicas: 1                   # as 5.0
    storage: 1Gi                  # as 5.0
    resources: {requests: {cpu: 100m, memory: 256Mi}, limits: {memory: 512Mi}}   # as 5.0
    external: false               # NEW: true | false (default false); the default for every environment
    remote:                       # NEW, only where external: path and refreshInterval, both optional
      path: "{system}-{env}-{resource}"   # placeholders {system} {env} {resource}; this is the default
      refreshInterval: 1h         # default 1h
    instances:
      prod: {external: true, remote: {path: "prod/{resource}"}}   # NEW keys external, remote; plus replicas, storage, resources
```

| Where | Allowed keys |
|---|---|
| `environments.<env>` | `host`, `url`, `policy`, `promote`, `observability`, `operators` |
| `resources.<name>` | `type`, `external`, `remote`, `version`, `replicas`, `storage`, `resources`, `instances` |
| `resources.<name>.remote` and `instances.<env>.remote` | `path`, `refreshInterval` |
| `resources.<name>.instances.<env>` | `external`, `remote`, `replicas`, `storage`, `resources` |

Effective values in an environment: `external` = the instance's `external`, else the resource's, else `false`. `remote` = `{**resource.remote, **instance.remote}`. Sizing as 5.0 (instance value, else resource value, else default: replicas 1, storage `1Gi`, version 17, the 5.0 default `resources`).

A resource instance exists in every environment where a running component uses the resource (as in 5.0).

### Render errors (exit 1, nothing written, each after the prefix `applications/<dir>/system.yaml: `)

Checked per resource in declaration order, in this order:

| Case | Text |
|---|---|
| named `observability` (unchanged) | `resources.observability: observability is set per environment under environments.<env>.observability` |
| name (AC-115.3) | `resources.<r>: the name must start with a lowercase letter and contain only lowercase letters, digits and hyphens (at most 30 characters)` |
| not a mapping or no `type` (AC-115.1) | `resources.<r>: type is required (database, bucket, cache or broker)` |
| other type (AC-115.1) | `resources.<r>: type '<v>' is not a resource type (database, bucket, cache or broker)` |
| type not built yet (AC-115.2) | `resources.<r>: type bucket is not available yet: spec 116 brings it` (`cache`: 118, `broker`: 119) |
| unknown key | `resources.<r>: unknown key '<k>' (allowed: type, external, remote, version, replicas, storage, resources, instances)` |
| `external` not boolean (AC-115.11) | `resources.<r>: external must be true or false` / `resources.<r>.instances.<env>: external must be true or false` |
| instance environment | `resources.<r>.instances: '<e>' is not an environment (environments: dev, staging, prod)` |
| external instance with sizing (AC-115.11) | `resources.<r>.instances.<env>: an external resource runs nothing (remove <key>)` for `version`, `replicas`, `storage`, `resources`; checked before the unknown-key check, so `version` gets this text |
| unknown instance key | `resources.<r>.instances.<env>: unknown key '<k>' (allowed: external, remote, replicas, storage, resources)` |
| top-level sizing, external everywhere (AC-115.11) | `resources.<r>: external in every environment: an external resource runs nothing (remove <key>)` |
| `remote` where not external (AC-115.11) | `resources.<r>: remote needs external: true` (resource level, when no environment is external) / `resources.<r>.instances.<env>: remote needs external: true in <env>` |
| `remote` keys | `resources.<r>.remote: unknown key '<k>' (allowed: path, refreshInterval)` (same with `.instances.<env>.remote`); path placeholders use the 5.0 placeholder texts with `resources.<r>.remote.path` and allowed `{system}, {env}, {resource}`; `resources.<r>.remote.refreshInterval must be a string, e.g. 1h` |
| external without store (AC-115.11) | `resources.<r>: external in <env> needs the system's secretStore (declare secretStore: {name, kind})`, for the first environment in promotion order where it is external |
| version (AC-115.17; the accepted narrowing of AC-115.6) | `resources.<r>: version '<v>' is not a supported database version (15, 16, 17, 18)` (checked only if some environment is in-cluster; `"17"` is read as 17) |
| replicas (5.0 rule, the resource named) | `resources.<r>: replicas must be a number of at least 1` |

After all resources, still in `_load_system`:

| Case | Text |
|---|---|
| resource name = component name (AC-115.3) | `resources.<r>: components.<r> has the same name; a resource and a component need different names` |
| two resources share a cluster object name (AC-115.5) | `resources.<a> and resources.<b> would both create the object <system>-<x>; rename one`. A database creates `<system>-<name>` plus the CloudNativePG suffixes `-app`, `-ca`, `-replication`, `-server`, `-superuser`, `-rw`, `-ro`, `-r`, `-primary`. Any other type creates `<system>-<name>` and `<system>-<name>-app`. |
| a component secret takes a connection Secret's name (AC-115.5) | `components.<c>: secret '<s>' is the connection Secret of resources.<r>; rename it` |
| `operators` (AC-115.18) | `environments.<env>.operators must be owner, got '<v>'` |
| unknown environment key | `environments.<env>: unknown key '<k>' (allowed: host, url, policy, promote, observability, operators)` |

The `uses` errors and the env clash text keep their 5.0 wording. The clash check compares the effective, possibly prefixed, variable names.

## Contract: what a using component gets (AC-115.7, AC-115.8)

```python
TYPES = {"database": {"keys": ["uri", "host", "port", "dbname", "user", "password"],
                      "env": {"DATABASE_URL": "uri", "PGHOST": "host", "PGPORT": "port",
                              "PGDATABASE": "dbname", "PGUSER": "user", "PGPASSWORD": "password"}}}
RESOURCE_TYPES = ("database", "bucket", "cache", "broker")
PLANNED_TYPES = {"bucket": 116, "cache": 118, "broker": 119}
```

For each resource in the component's `uses`, in `uses` order: the type's variables in table order, each `{"name": <VAR>, "valueFrom": {"secretKeyRef": {"name": "<system>-<r>-app", "key": <key>}}}`, appended after the literal `env` entries as in 5.0. `<VAR>` is the bare name when the component uses exactly one resource of that type. Otherwise it is `<NAME>_<VAR>`, with `NAME = r.upper().replace("-", "_")`. Example: a component with `uses: [orders-db, users-db, shop-lib]` gets `ORDERS_DB_DATABASE_URL … ORDERS_DB_PGPASSWORD, USERS_DB_DATABASE_URL … USERS_DB_PGPASSWORD` and no `DATABASE_URL`. The variables are the same in every environment, in-cluster or external.

## Contract: render outputs

**In-cluster database instance** `applications/<system>/addons/<env>/<name>/cluster.yaml`. It is the 5.0 document with the name generalised; `kustomization.yaml` is unchanged:

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: <system>-<name>
  labels: {app.kubernetes.io/name: <name>, app.kubernetes.io/part-of: <system>, app.kubernetes.io/managed-by: gitops-app}
spec:
  instances: <replicas>
  imageName: <POSTGRES_IMAGES[version]>          # the only difference from 5.0 for postgres
  storage: {size: <storage>}
  enableSuperuserAccess: false
  bootstrap: {initdb: {database: <system, - → _>, owner: <same>}}
  resources: <resources or the 5.0 default>
```

Key order and the ApplicationSet `<system>-addons-<env>` (elements = the in-cluster resource names used in `<env>`, sorted; template name `addon-{{name}}-<env>`, prune false) are as in 5.0.

**External instance**: no `addons/<env>/<name>/` and no ApplicationSet element. In `overlays/<env>/<owner>/`, where `<owner>` is the alphabetically first running component using the resource in `<env>`, the file `externalsecret-<system>-<name>-app.yaml` is listed in that overlay's `kustomization.yaml` `resources` (sorted, as every overlay file):

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: <system>-<name>-app
  labels: {app.kubernetes.io/name: <name>, app.kubernetes.io/part-of: <system>, app.kubernetes.io/managed-by: gitops-app}
spec:
  refreshInterval: <remote.refreshInterval or "1h">
  secretStoreRef: {name: <secretStore.name>, kind: <secretStore.kind or ClusterSecretStore>}
  target: {name: <system>-<name>-app, creationPolicy: Orphan, deletionPolicy: Retain}
  data:                                            # one entry per TYPES[type].keys, in table order
    - {secretKey: uri, remoteRef: {key: <store key>, property: uri}}
    - …                                            # host, port, dbname, user, password
```

`<store key>` = `(remote.path or "{system}-{env}-{resource}").format(system=, env=, resource=<name>)`.

**Operators** (repo level, written by `main()` after all systems render; `--check` and stale removal cover them; render owns `operators/` entirely). The CloudNativePG operator is needed when some system has an in-cluster database instance in an environment without `operators: owner`. When nothing is needed, `operators/` does not exist.

`operators/root.yaml`:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata: {name: platform-operators, namespace: argocd}
spec:
  project: default
  source: {repoURL: <gitops repo URL as render_app builds it>, targetRevision: main, path: operators/apps}
  destination: {server: <cluster_server>, namespace: argocd}
  syncPolicy: {automated: {prune: true, selfHeal: true}}
```

`operators/apps/cloudnative-pg.yaml` (no `finalizers`):

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: operator-cloudnative-pg
  namespace: argocd
  labels: {app.kubernetes.io/managed-by: gitops-app, app.kubernetes.io/component: operator}
spec:
  project: default
  source: {repoURL: https://cloudnative-pg.github.io/charts, chart: cloudnative-pg, targetRevision: <OPERATORS[...].chart_version>,
           helm: {releaseName: cnpg}}
  destination: {server: <cluster_server>, namespace: cnpg-system}
  syncPolicy: {automated: {prune: true, selfHeal: true}, syncOptions: [CreateNamespace=true, ServerSideApply=true]}
```

The gitops repo URL with several systems: `https://github.com/<github_org>/<project_name>`; without `project_name`, the first system's name plus `-gitops` (render_app's rule).

**Versions table** (module constants; exact values filled in by plan task t2 from the registries at build time):

```python
POSTGRES_IMAGES = {15: "ghcr.io/cloudnative-pg/postgresql:15.<minor>", 16: "ghcr.io/cloudnative-pg/postgresql:16.<minor>",
                   17: "ghcr.io/cloudnative-pg/postgresql:17.<minor>", 18: "ghcr.io/cloudnative-pg/postgresql:18.<minor>"}
                                                                            # each with an optional "@sha256:<64 hex>" suffix
OPERATORS = {"cloudnative-pg": {"repo_url": "https://cloudnative-pg.github.io/charts", "chart": "cloudnative-pg",
                                "chart_version": "<x.y.z>", "operator_version": "<x.y.z>", "namespace": "cnpg-system",
                                "release": "cnpg", "crd": "clusters.postgresql.cnpg.io"}}
```

Each image matches `^ghcr\.io/cloudnative-pg/postgresql:<major>\.\d+(@sha256:[0-9a-f]{64})?$`, and each version `^\d+\.\d+\.\d+$`. `operator_version` is the chart's `appVersion`.

**Renderer API for the model check** (AC-115.15). It adds to the 5.0 API and does not replace it:

```python
load_system(app_dir)["cfg"]["resources"] -> {name: {"type": str, "external": bool,
    "envs": {env: {"external": bool, "version": int | None, "replicas": int | None, "storage": str | None,
                   "resources": dict | None, "store_key": str | None, "refreshInterval": str | None}}}}
resource_instances(system: dict) -> list[tuple[str, str, str, bool]]   # (name, env, type, external) for each used
                                                                         # instance, in resource order then ENVS order
```

`cfg["postgres"]` is removed. Nothing outside `render.py` reads it.

## Contract: `cplat resource` (AC-115.13, AC-115.14, AC-115.2)

`cplat resource add <name> [--type database|bucket|cache|broker] [--version N] [--external [--path P]] [--app S] [--repo-dir D] [--pr] [--dry-run] [--json]`. Errors exit 1 and change nothing. All checks run before any write, in this order:

| Case | Text (`PlatformError` message; hint where given) |
|---|---|
| `observability` (unchanged) | `observability is set per environment under environments.<env>.observability in system.yaml` |
| invalid name | `resource name '<n>' must start with a lowercase letter and contain only lowercase letters, digits and hyphens (at most 30 characters)` |
| no `--type`, name not `postgres` | `--type is required for <n> (database, bucket, cache or broker)` |
| other type | `unknown resource type '<t>' (database, bucket, cache or broker)` |
| type not built yet | `resource type bucket is not available yet: spec 116 brings it` (`cache`: 118, `broker`: 119) |
| exists | `<n> is already declared`, hint `edit its settings in system.yaml` (unchanged) |
| component name | `<n> is a component of the system; a resource needs a name of its own` |
| `--path` without `--external` | `--path needs --external` |
| `--version` with `--external` | `an external resource runs nothing: --version does not apply` |
| `--version` not supported | `version '<v>' is not a supported database version (15, 16, 17, 18)` |
| `--external`, no `secretStore` | `an external resource needs the system's secretStore`, hint `declare secretStore: {name, kind} in system.yaml first` |

Entries written (round-trip, comments kept): in-cluster, the 5.0 default `{type: database, version: 17, replicas: 1, storage: 1Gi, instances: {prod: {replicas: 3, storage: 20Gi}}}`, with `version` from `--version`. External: `{type: database, external: true}`, plus `remote: {path: P}` with `--path`. `postgres` without `--type` is `--type database`. Then render, and with `--pr` open one PR: branch `resource/add-<name>`, title `feat(resource): add <name>`, body as 5.0.

Next steps after `add`: `let components use it: /component:set <component> --uses <n> (or uses: [<n>] in system.yaml)`. For an in-cluster database: `the platform installs CloudNativePG through operators/ (apply operators/root.yaml once per cluster: KUBE_CONTEXT=<ctx> devbox run bootstrap); environments with operators: owner need it installed by their owner`. For external: `put the keys uri, host, port, dbname, user, password in the secret store <store name> under <dev key>, <staging key>, <prod key>`.

`cplat resource remove <name> …`:

| Case | Text |
|---|---|
| unknown | `<n> is not a resource of the system (resources: <names in order or none>)` |
| used | `<n> is still used by <c1>, <c2>` (every using component, system.yaml order), hint `remove it from their uses: first (/component:set)` |

On success it deletes `resources.<n>` (and an empty `resources:`), renders, and with `--pr` opens one PR `resource/remove-<n>`. The `will_do` line for in-cluster instances keeps the 5.0 text with the name. For external instances it is `remove <n> from system.yaml; the synced Secret <system>-<n>-app stays in the cluster (delete it by hand when you are sure); the external database is not touched`. A resource with both kinds of instance gets both sentences.

## Contract: the model (schema 2, fields added)

```python
@dataclass(frozen=True)
class Resource:            name: str; type: str = "unknown"; external: bool = False        # external: the resource-level flag is True
@dataclass(frozen=True)
class ResourceInstance:    resource: str; environment: str; argo_application: str | None; secret: str | None = None
                           sizing: dict = {}; type: str = "unknown"; external: bool = False; store_key: str | None = None
@dataclass(frozen=True)
class Environment:         … ; operators: str | None = None                              # "owner" or None
```

- A resource instance exists for every declared resource in every environment where a component that runs there uses it (5.0 rule, now for every name). `secret` = `<system>-<name>-app` for every resource. `argo_application` = `addon-<name>-<env>` if in-cluster, else `None`. `sizing` = `{"replicas", "version", "storage"}` for an in-cluster database, else `{}`. `store_key` as in the render, external only.
- `to_dict()`: `resources[]` = `{"name", "type", "external", "used_by"}`. `resource_instances[]` = `{"resource", "environment", "type", "external", "argo_application", "secret", "store_key", "sizing"}`. `environments[]` gain `"operators"`. `schema` stays 2.
- Text (`cplat model show`): resource line `  <name>  type <type>  external <true|false>  used by <list or ->`. In-cluster instance: `    <env>  type <type>  external false  replicas <n>  version <v>  storage <s>  argo addon-<name>-<env>  secret <secret>`. External: `    <env>  type <type>  external true  argo -  secret <secret>  store <store key>`. An environment line ends with `  operators owner` only when set.
- `/system:status`: an external resource instance's cell is `external` (JSON `{"argo": "external"}`); in-cluster cells as 5.0.

## Contract: `/platform:doctor` (AC-115.18)

One row per operator the repo's systems need (CloudNativePG: an in-cluster database instance in some environment), only when `kubectl` is present. The installed version is the tag of the first image of `kubectl get deploy -A -l app.kubernetes.io/name=cloudnative-pg -o jsonpath={.items[*].spec.template.spec.containers[*].image}`, with any digest dropped. The expected version is `OPERATORS["cloudnative-pg"]["operator_version"]` from the platform's `templates/gitops-app/scripts/render.py`. Name `operator cloudnative-pg`.

| Situation | Level | Detail | Fix |
|---|---|---|---|
| every environment needing it has `operators: owner`; equal | OK | `installed <v>, expected <v> (operators: owner in <envs>)` | |
| owner; missing | WARN | `not installed in the current kube context, expected <v> (operators: owner in <envs>)` | `install the cloudnative-pg chart <chart_version> (operator <v>)` |
| owner; differs | WARN | `installed <iv>, expected <v> (operators: owner in <envs>)` | `move the cloudnative-pg chart to <chart_version> (operator <v>)` |
| some environment platform-managed; equal | OK | `installed <v>, expected <v> (Argo CD application operator-cloudnative-pg)` | |
| platform-managed; missing | WARN | `not installed in the current kube context, expected <v> (Argo CD application operator-cloudnative-pg)` | `apply operators/root.yaml once: KUBE_CONTEXT=<ctx> devbox run bootstrap (local: devbox run cluster-up)` |
| platform-managed; differs | WARN | `installed <iv>, expected <v> (Argo CD application operator-cloudnative-pg)` | `sync operator-cloudnative-pg in Argo CD` |

`<envs>` are comma-separated, in promotion order. This row replaces 5.0's `addon postgres` row, whose condition (`type == "postgres"`) never matched.

## Contract: local cluster and bootstrap

- `scripts/bootstrap.sh` (new; `devbox run bootstrap` runs `bash scripts/bootstrap.sh`): requires `KUBE_CONTEXT` (the 5.0 message). If `operators/root.yaml` exists, it applies that file to `argocd` first. For each `operators/apps/*.yaml` it waits up to 10 minutes for the operator's CRD (CloudNativePG: `clusters.postgresql.cnpg.io`); on a timeout it exits 1 naming the CRD. It then applies `bootstrap/` as 5.0 did.
- `local-cluster.sh`: `WITH_CNPG` auto = 1 exactly when `operators/apps/cloudnative-pg.yaml` exists. `CNPG_VERSION` defaults to that file's `targetRevision`. With Argo CD, it installs no k3s HelmChart for CloudNativePG; after Argo CD it applies `operators/root.yaml`, waits for the CRD and the `cnpg-system/cnpg-cloudnative-pg` rollout, then applies `bootstrap/`. If a HelmChart `kube-system/cnpg` already exists (a cluster made by 5.0), it prints `CloudNativePG was installed by an older cluster-up (HelmChart kube-system/cnpg); keeping it. Recreate the cluster to let Argo CD manage it` and skips `operators/root.yaml`. Without Argo CD (`WITH_ARGO=0`), it installs the HelmChart at `CNPG_VERSION` as today.

## Contract: migration proof (`update.apply_systems`)

Before comparing, both trees map every `applications/*/addons/*/*/cluster.yaml` through `re.sub(rb"(imageName: ghcr\.io/cloudnative-pg/postgresql:)(\d+)\S*", rb"\1\2", data)`. The report texts and JSON (`byte_identical`, `compared`) are unchanged. `operators/` is outside `_tree` and is committed with the migration. A 4.7 repo whose postgres `version` is outside 15–18 fails the migration at the render step (the accepted narrowing); nothing is changed, by the 5.0 rollback.

## Risks

- **Clusters whose owner installed CloudNativePG by hand** (as 5.0's docs said) would get a second install if someone applied `operators/root.yaml`. Nothing applies it automatically. The CHANGELOG tells those owners to set `operators: owner` first, and plan `human_steps` repeats it.
- **Several gitops repos on one cluster** render the same `operator-cloudnative-pg`. All but one set `operators: owner` (ADR-058).
- **Argo CD does not retry a failed automated sync of the same commit**: a database Cluster synced before its CRD exists stays failed. Hence the operator-first order in `bootstrap.sh` and `local-cluster.sh`.
- **Removing the last database** leaves `platform-operators` pointing at a missing `operators/apps`. It shows an error in Argo CD until a human deletes it. The operator keeps running (no finalizer).
- **A system on a major outside 15–18** stops rendering after `/platform:update`. The CHANGELOG names the supported majors.
- `templates/gitops-app/scripts/plan.py` still knows only `postgres` as a resource for multi-repo plan operations. That keeps 5.0 behaviour and is a follow-up, not part of this spec.
