# Design — 116 An object storage resource for files and backups

Extends [spec 115's design](../115-resources-are-named-typed-and-may-be/design.md): the `TYPES` contract, the prefix rule, external
instances, the versions table and `operators/` are used as built. Everything here is additive. A `system.yaml` without
`type: bucket` renders byte-identically, and every message of spec 114/115 keeps its text, except that `bucket` is no longer a
"not available yet" type (AC-116.20).

## Decisions

- **The cluster-level piece is the SeaweedFS operator; each in-cluster bucket instance is its own SeaweedFS** (AC-116.2, AC-116.5,
  AC-116.19). The bucket name `<system>-<name>` is the same in every environment, and environments share a cluster (always
  locally), so one shared store per cluster cannot hold them. `storage` is the bucket's capacity, with no quotas (non-goal), which
  a volume per instance gives exactly. The operator (`seaweedfs-operator` chart) is rendered as `operators/apps/seaweedfs.yaml`
  under ADR-058's rules, like CloudNativePG for databases. ADR: [059](../../adr/059-in-cluster-buckets-on-seaweedfs-per-instance.md).
- **Bucket, identity and access are operator resources** (`Bucket`, `S3Identity`, `S3Credentials` of `seaweed.seaweedfs.com/v1`).
  One identity per bucket instance, granted `Read, Write, List, Tagging` on that bucket only (AC-116.6), so another environment's
  keys are refused (AC-116.5).
- **Keys are generated in the cluster by External Secrets Operator** (AC-116.5, AC-116.16). An `ExternalSecret` with two `Password`
  generators writes all six contract keys of `<system>-<name>-app` once (`refreshInterval: "0"`, through a template). `S3Credentials`
  points at that Secret, and the operator adopts an existing key pair. That is the same mechanism as `secrets.generate` and needs no
  value in git. Argo sync waves order it: generators and ExternalSecret at `-1`, `S3Credentials` at `1`, the rest at `0`.
- **Argo CD never deletes a bucket** (AC-116.12). Every object of an in-cluster bucket carries
  `argocd.argoproj.io/sync-options: Delete=false`, and `Bucket`/`S3Credentials` use `reclaimPolicy: Retain`. When the resource is
  removed, the ApplicationSet element and `addon-<name>-<env>` disappear, but the store, its volumes, its data and the Secret stay.
- **`versioning: false` renders `Suspended`; `true` renders `Enabled`** (AC-116.7). The operator's CRD refuses a return to `Off`
  once versioning was on (S3 semantics), and the renderer has no history. `Suspended` behaves as unversioned for new writes.
- **The filer's embedded S3 endpoint, not the standalone gateway.** The gateway is a Deployment, and the guard rails (ADR-022) check
  every Deployment in the namespace. The filer is a StatefulSet, so `policy.yaml` stays unchanged for every system.
- **Endpoint and region of an in-cluster bucket**: `http://<system>-<name>-filer.<system>-<env>.svc:8333`, region `us-east-1`,
  `forcePathStyle` `"true"` (AC-116.16).
- **`<system>-<name>` of an in-cluster bucket has at most 45 characters.** This rule comes on top of AC-116.2's S3 rule and waits
  for the user's confirmation. The operator creates the StatefulSet `<system>-<name>-volume`. Kubernetes labels its pods with the
  StatefulSet name plus an 11-character revision hash, and that label must fit in 63 characters. A longer name would render and then
  fail in the cluster, so the render fails it first.
- **Pins** (AC-116.15): `SEAWEEDFS_IMAGE = "chrislusf/seaweedfs:4.51"` and `OPERATORS["seaweedfs"]` (chart `0.1.45`, appVersion
  `1.0.42`). Both were checked on 2026-10-26: Docker Hub `chrislusf/seaweedfs:4.51` (digest
  `sha256:f7a49e3f3972ebed5be2ed4befa4a0c68eb7bdddba6e692d42729ceb545134b8`), and `https://seaweedfs.github.io/seaweedfs-operator/index.yaml`
  0.1.45 → appVersion 1.0.42. The chart's operator image tag defaults to its appVersion, so it is exact. Changing a pin follows spec
  121 (until it ships, as in 115: the next render after `/platform:update`).

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `templates/gitops-app/scripts/render.py` | bucket schema, `TYPES["bucket"]`, in-cluster bucket files, `SEAWEEDFS_IMAGE`, `OPERATORS["seaweedfs"]`, `operators/apps/seaweedfs.yaml` | changed |
| `templates/gitops-app/scripts/local-cluster.sh`, `scripts/bootstrap.sh`, `CLAUDE.md.jinja` | install or wait for the SeaweedFS operator like CloudNativePG | changed |
| `scripts/cplat/addon.py` | `resource add <name> --type bucket [--storage S] [--versioning]`, bucket texts in `remove` | changed |
| `scripts/cplat/model.py`, `modelcmd.py` | bucket sizing (`storage`, `versioning`) on in-cluster bucket instances | changed |
| `scripts/cplat/doctor.py` | an `operator seaweedfs` row next to `operator cloudnative-pg` | changed |
| `scripts/cplat/compose.py` | `--uses` help and the prefix note per type | changed |

## Contract: `system.yaml`

```yaml
resources:
  files:
    type: bucket
    storage: 10Gi            # default 10Gi; a Kubernetes size
    versioning: false        # true | false (default false)
    external: false          # spec 115
    remote: {path: "{system}-{env}-{resource}", refreshInterval: 1h}   # spec 115, only where external
    instances:
      dev: {versioning: true}
      prod: {external: true}  # spec 115; an external instance takes no storage or versioning
```

| Where (type `bucket`) | Allowed keys |
|---|---|
| `resources.<name>` | `type`, `external`, `remote`, `storage`, `versioning`, `instances` |
| `resources.<name>.instances.<env>` | `external`, `remote`, `storage`, `versioning` |
| `remote` | `path`, `refreshInterval` (as 115) |

A database keeps 115's lists. Effective values per environment: `external` and `remote` as in 115. `storage` = the instance's, else
the resource's, else `"10Gi"`. `versioning` = the instance's, else the resource's, else `false`.

### Render errors (exit 1, nothing written, each after `applications/<dir>/system.yaml: `)

Order per resource: 115's name and type checks, then for a bucket:

| Case | Text |
|---|---|
| unknown key (AC-116.1) | `resources.<r>: unknown key '<k>' (allowed: type, external, remote, storage, versioning, instances)` |
| `external` not boolean | 115 texts |
| instances not a mapping | `resources.<r>.instances must be a mapping of environments to {external, remote, storage, versioning}` |
| instance environment | 115 text |
| external instance with `storage`/`versioning` (AC-116.10); checked before the unknown-key check | `resources.<r>.instances.<env>: an external bucket is sized and configured at its provider (remove <key>)` |
| unknown instance key (AC-116.1) | `resources.<r>.instances.<env>: unknown key '<k>' (allowed: external, remote, storage, versioning)` |
| top-level `storage`/`versioning`, external everywhere (AC-116.10) | `resources.<r>: external in every environment: an external bucket is sized and configured at its provider (remove <key>)` |
| `remote` and `secretStore` | 115 texts |
| `versioning` not boolean (AC-116.1) | `resources.<r>: versioning must be true or false` / `resources.<r>.instances.<env>: versioning must be true or false` |
| `storage` not a size | `resources.<r>: storage must be a size such as 10Gi` / `resources.<r>.instances.<env>: storage must be a size such as 10Gi` (a string matching `^[0-9]+(\.[0-9]+)?(Ki\|Mi\|Gi\|Ti\|Pi\|Ei)?$`) |
| bucket name (AC-116.2), only if some environment is in-cluster | `resources.<r>: '<system>-<r>' is not a valid S3 bucket name (3 to 63 characters, lowercase letters, digits and hyphens, starting and ending with a letter or digit)` |
| store object names, only if some environment is in-cluster | `resources.<r>: '<system>-<r>' is too long for the in-cluster store (at most 45 characters)` |

Key and sizing checks for the external case come first, in the order of the table, as for a database. The cluster-object clash check
of 115 uses, for a bucket, `<system>-<name>` plus the suffixes `-app`, `-master`, `-master-peer`, `-volume`, `-volume-0`,
`-volume-peer`, `-filer`, `-filer-peer`, `-access-key`, `-secret-key` (`BUCKET_SUFFIXES`). `cache` and `broker` keep 115's
"not available yet" texts. `PLANNED_TYPES` becomes `{"cache": 118, "broker": 119}` (AC-116.20).

Renderer API: `cfg["resources"][name]["envs"][env]` of a bucket is `{"external", "version": None, "replicas": None, "storage",
"resources": None, "versioning", "store_key", "refreshInterval"}`. `storage` is `None` and `versioning` is `None` where external.
A database's dict is unchanged.

## Contract: what a using component gets (AC-116.16, AC-116.4)

```python
TYPES["bucket"] = {"keys": ["endpoint", "bucket", "region", "forcePathStyle", "accessKeyId", "secretAccessKey"],
                   "env": {"S3_ENDPOINT": "endpoint", "S3_BUCKET": "bucket", "S3_REGION": "region",
                           "S3_FORCE_PATH_STYLE": "forcePathStyle", "AWS_ACCESS_KEY_ID": "accessKeyId",
                           "AWS_SECRET_ACCESS_KEY": "secretAccessKey", "AWS_REGION": "region", "AWS_ENDPOINT_URL_S3": "endpoint"}}
```

Rendered by 115's `addon_env`: each `{"name": <VAR>, "valueFrom": {"secretKeyRef": {"name": "<system>-<r>-app", "key": <key>}}}`,
in table order, after the literal `env`. With two or more buckets: `<NAME>_<VAR>`, e.g. `UPLOADS_S3_BUCKET`, `UPLOADS_AWS_REGION`.
One bucket and one database give bare names for both. The env clash check of 115 covers the new names.

## Contract: in-cluster bucket instance

Directory `applications/<system>/addons/<env>/<name>/`, an element `<name>` of the ApplicationSet `<system>-addons-<env>` (prune
false, Argo application `addon-<name>-<env>`), as for a database. `L` = `{app.kubernetes.io/name: <name>, app.kubernetes.io/part-of:
<system>, app.kubernetes.io/managed-by: gitops-app}`. `K` = `argocd.argoproj.io/sync-options: Delete=false`. `<n>` = `<system>-<name>`.
`<ns>` = `<system>-<env>`.

`seaweed.yaml`:

```yaml
apiVersion: seaweed.seaweedfs.com/v1
kind: Seaweed
metadata: {name: <n>, labels: L, annotations: {K}}
spec:
  image: <SEAWEEDFS_IMAGE>
  volumeServerDiskCount: 1
  master: {replicas: 1, volumeSizeLimitMB: 1024, persistence: {enabled: true, resources: {requests: {storage: 1Gi}}}}
  volume: {replicas: 1, requests: {storage: <storage>}}
  filer:
    replicas: 1
    persistence: {enabled: true, resources: {requests: {storage: 1Gi}}}
    s3: {enabled: true}
    config: "[leveldb2]\nenabled = true\ndir = \"/data/filerldb2\"\n"
```

`bucket.yaml`:

```yaml
apiVersion: seaweed.seaweedfs.com/v1
kind: Bucket
metadata: {name: <n>, labels: L, annotations: {K}}
spec:
  name: <n>
  clusterRef: {name: <n>}
  reclaimPolicy: Retain
  versioning: Enabled | Suspended          # versioning true | false
  owner: <n>
  access: [{user: <n>, actions: [Read, Write, List, Tagging]}]
```

`identity.yaml`: `{apiVersion: seaweed.seaweedfs.com/v1, kind: S3Identity, metadata: {name: <n>, labels: L, annotations: {K}}, spec: {seaweedRef: {name: <n>}}}`

`credentials.yaml`:

```yaml
apiVersion: seaweed.seaweedfs.com/v1
kind: S3Credentials
metadata: {name: <n>, labels: L, annotations: {K, argocd.argoproj.io/sync-wave: "1"}}
spec:
  seaweedRef: {name: <n>}
  identityRef: {name: <n>}
  secretRef: {name: <n>-app, accessKeyField: accessKeyId, secretKeyField: secretAccessKey}
  reclaimPolicy: Retain
```

`access-key-generator.yaml` / `secret-key-generator.yaml`:

```yaml
apiVersion: generators.external-secrets.io/v1alpha1
kind: Password
metadata: {name: <n>-access-key | <n>-secret-key, labels: L, annotations: {K, argocd.argoproj.io/sync-wave: "-1"}}
spec: {length: 20 | 40, digits: 5 | 10, symbols: 0, noUpper: false, allowRepeat: true}
```

`externalsecret.yaml`:

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata: {name: <n>-app, labels: L, annotations: {K, argocd.argoproj.io/sync-wave: "-1"}}
spec:
  refreshInterval: "0"
  target:
    name: <n>-app
    creationPolicy: Owner
    deletionPolicy: Retain
    template:
      engineVersion: v2
      data:
        endpoint: http://<n>-filer.<ns>.svc:8333
        bucket: <n>
        region: us-east-1
        forcePathStyle: "true"
        accessKeyId: "{{ .accessKeyId }}"
        secretAccessKey: "{{ .secretAccessKey }}"
  dataFrom:
    - {sourceRef: {generatorRef: {apiVersion: generators.external-secrets.io/v1alpha1, kind: Password, name: <n>-access-key}},
       rewrite: [{regexp: {source: "^password$", target: accessKeyId}}]}
    - {sourceRef: {generatorRef: {apiVersion: generators.external-secrets.io/v1alpha1, kind: Password, name: <n>-secret-key}},
       rewrite: [{regexp: {source: "^password$", target: secretAccessKey}}]}
```

`kustomization.yaml`: `{apiVersion: kustomize.config.k8s.io/v1beta1, kind: Kustomization, resources: [access-key-generator.yaml,
bucket.yaml, credentials.yaml, externalsecret.yaml, identity.yaml, seaweed.yaml, secret-key-generator.yaml]}`.

Key order in every document is as written here. Field names were read from the operator's `api/v1` types (`master`) on 2026-10-26.
The build checks them against the CRDs of chart 0.1.45 (`helm template`). If a name differs there, the build follows the pinned CRD
and changes this section in the same PR.

## Contract: external bucket instance (AC-116.17, AC-116.18)

Spec 115's ExternalSecret `<system>-<name>-app` in the overlay of the alphabetically first running user, with one `data` entry per
`TYPES["bucket"]["keys"]` (`endpoint`, `bucket`, `region`, `forcePathStyle`, `accessKeyId`, `secretAccessKey`), store key
`{system}-{env}-{resource}` by default, no `dataFrom`, no defaults. There is no addon directory, ApplicationSet element or operator
for that environment.

## Contract: operators (AC-116.19, AC-116.15)

```python
SEAWEEDFS_IMAGE = "chrislusf/seaweedfs:4.51"          # matches ^chrislusf/seaweedfs:\d+\.\d+(@sha256:[0-9a-f]{64})?$
OPERATORS["seaweedfs"] = {"repo_url": "https://seaweedfs.github.io/seaweedfs-operator", "chart": "seaweedfs-operator",
                          "chart_version": "0.1.45", "operator_version": "1.0.42", "namespace": "seaweedfs-operator",
                          "release": "seaweedfs-operator", "crd": "buckets.seaweed.seaweedfs.com"}
```

`operators/apps/seaweedfs.yaml` exists exactly when some system has an in-cluster bucket instance in an environment without
`operators: owner`. `operators/root.yaml` exists when any operator file exists (115's document, unchanged). The `cloudnative-pg`
condition and file are unchanged.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: operator-seaweedfs
  namespace: argocd
  labels: {app.kubernetes.io/managed-by: gitops-app, app.kubernetes.io/component: operator}
spec:
  project: default
  source: {repoURL: https://seaweedfs.github.io/seaweedfs-operator, chart: seaweedfs-operator, targetRevision: 0.1.45,
           helm: {releaseName: seaweedfs-operator}}
  destination: {server: <cluster_server>, namespace: seaweedfs-operator}
  syncPolicy: {automated: {prune: true, selfHeal: true}, syncOptions: [CreateNamespace=true, ServerSideApply=true]}
```

## Contract: `cplat resource` (AC-116.12, AC-116.20)

`cplat resource add <name> [--type T] [--version N] [--storage SIZE] [--versioning] [--external [--path P]] …`. 115's checks keep
their order and texts. `bucket` passes the type checks. These checks come after `--path needs --external`:

| Case | Text |
|---|---|
| `--version`, type not database | `--version applies to --type database only` |
| `--storage` or `--versioning`, type not bucket | `--storage and --versioning apply to --type bucket only` |
| (115) `--version` with `--external` | unchanged |
| `--storage`/`--versioning` with `--external` | `an external bucket is sized and configured at its provider: --storage does not apply` (`--versioning` when only that one is given) |
| (115) version not supported | unchanged |
| storage not a size | `storage '<v>' is not a size, e.g. 10Gi` |
| (115) external without `secretStore` | unchanged |

Entries written: an in-cluster bucket `{type: bucket, storage: <--storage or 10Gi>, versioning: <true with --versioning, else false>}`.
An external resource `{type: <type>, external: true}` (+ `remote: {path: P}`), which now writes the given type, not always `database`.

Next steps after adding a bucket: the 115 `let components use it: …` line, then either
`the platform installs the SeaweedFS operator through operators/ (apply operators/root.yaml once per cluster: KUBE_CONTEXT=<ctx> devbox run bootstrap); environments with operators: owner need it installed by their owner`
(in-cluster) or `put the keys endpoint, bucket, region, forcePathStyle, accessKeyId, secretAccessKey in the secret store <store> under <dev key>, <staging key>, <prod key>` (external).
The external line for a database is unchanged.

`remove`: the unknown and used-by refusals are 115's (`<n> is still used by <c1>, <c2>`). The `will_do` lines for a bucket:

- in-cluster instances: `remove <n> from system.yaml; the Argo Application disappears but the bucket, its data and its Secret <system>-<n>-app stay in the cluster (delete them by hand when you are sure)`
- external instances: `remove <n> from system.yaml; the synced Secret <system>-<n>-app stays in the cluster (delete it by hand when you are sure); the external bucket is not touched`

## Contract: model, doctor, compose

- **Model**: an in-cluster bucket instance has `sizing = {"storage": <effective, default "10Gi">, "versioning": <bool, default False>}`.
  An external one has `{}`. `cplat model show` prints `storage 10Gi  versioning false` (booleans in lower case). Nothing else changes.
- **Doctor**: one row per needed operator, in the order `cloudnative-pg`, `seaweedfs`. `seaweedfs` is needed by an in-cluster bucket
  instance. It uses 115's table with `<op>` = `seaweedfs` and `<chart>` = `seaweedfs-operator`, for example
  `installed 1.0.41, expected 1.0.42 (operators: owner in prod)`, fix `move the seaweedfs-operator chart to 0.1.45 (operator 1.0.42)`,
  `install the seaweedfs-operator chart 0.1.45 (operator 1.0.42)`, `sync operator-seaweedfs in Argo CD`, detail
  `(Argo CD application operator-seaweedfs)`. The installed version is read from
  `kubectl get deploy -A -l app.kubernetes.io/name=seaweedfs-operator` (the label is checked against `helm template` of 0.1.45 at
  build). The texts of the `cloudnative-pg` row are unchanged.
- **compose**: the `--uses` help reads `resource or library the component needs (a database gives DATABASE_URL and PG*, a bucket S3_* and AWS_*); declare it first with cplat resource add <name> --type database|bucket`.
  The prefix note for a bucket reads `<c> now uses <n> bucket resources: their variables are prefixed (<NAME>_S3_ENDPOINT, …) and S3_*, AWS_* are no longer injected`.
  The database note is unchanged.

## Contract: local cluster and bootstrap

- `bootstrap.sh`: `seaweedfs) crd=buckets.seaweed.seaweedfs.com ;;` next to `cloudnative-pg`.
- `local-cluster.sh`: `WITH_SEAWEEDFS` defaults to 1 exactly when `operators/apps/seaweedfs.yaml` exists. `SEAWEEDFS_OPERATOR_VERSION`
  defaults to that file's `targetRevision`, else `0.1.45`. Without Argo CD it installs a HelmChart `kube-system/seaweedfs-operator`
  (repo, chart and namespace as above) and waits for the CRD and the operator Deployment's rollout. With Argo CD it applies
  `operators/root.yaml` whenever it exists (no longer only when CloudNativePG is needed), then waits for CloudNativePG as today and
  for the SeaweedFS CRD and rollout when `seaweedfs.yaml` exists. The legacy-HelmChart case keeps its message and skip. When
  `seaweedfs.yaml` exists it adds `SeaweedFS (operators/apps/seaweedfs.yaml) is not installed either; recreate the cluster`.

## Risks

- **The operator is young** (0.1.x, near-daily releases), and the filer-embedded S3 is deprecated upstream. The e2e test (AC-116.14)
  is the proof. Spec 121 owns moves, and switching to the gateway is a later spec (ADR-059).
- **Adoption race**: if `S3Credentials` reconciled before the ExternalSecret, the operator would generate its own pair, and ESO would
  then overwrite it. The operator rotates changed Secret keys onto the identity, so the two converge. The sync waves avoid the race
  under Argo CD, and the e2e test applies in the same order.
- **Changing the ExternalSecret template** in a later release makes ESO regenerate the keys. The operator rotates them, but running
  pods keep the old variables until they restart. This is the same behaviour as `secrets.generate`.
- **A bucket that was versioned keeps its old versions** after `versioning: false` (`Suspended`).
- **Per-instance cost**: three pods and three volumes per bucket and environment.

## Decisions confirmed by the user (2026-10-27)

1. Topology: the per-cluster platform application is the SeaweedFS operator; every bucket instance runs its own SeaweedFS (AC-116.19).
2. `versioning: false` renders the S3 state `Suspended`.
3. In-cluster bucket names: `<system>-<name>` at most 45 characters, a render rule on top of AC-116.2.
4. The filer's built-in S3 endpoint; the standalone gateway (and the guard-rail change it needs) is a later spec.
