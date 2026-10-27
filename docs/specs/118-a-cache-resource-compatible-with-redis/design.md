# Design — 118 A cache resource compatible with Redis

Extends [spec 115's design](../115-resources-are-named-typed-and-may-be/design.md) (the `TYPES` contract, the prefix rule, external
instances, the versions table), [spec 116's design](../116-an-object-storage-resource-for-files-and/design.md) (a second type in
`validate_resource`, generated keys) and [spec 117's design](../117-databases-and-environments-are-backed-up/design.md) (the Velero
Schedule already leaves out every `cache` resource by its `app.kubernetes.io/name`). Everything is additive: a `system.yaml` without
`type: cache` renders byte-identically, and every message of specs 114–117 keeps its text, except that `cache` is no longer a
"not available yet" type (AC-118.22; amended tests, plan t9).

## Decisions

- **A cache instance is one Valkey StatefulSet that the renderer writes itself: no operator, no CRD, no Helm chart** (AC-118.23).
  `operators/` never gets an entry for a cache, `operators: owner` changes nothing for it, and `/platform:doctor` has no row for it.
  The image is the official `valkey/valkey` image, pinned exactly per major in the versions table (`VALKEY_IMAGES`, AC-118.17).
  ADR: [063](../../adr/063-a-cache-is-a-platform-rendered-valkey-statefulset.md).
- **The password is generated in the cluster by External Secrets Operator, once** (AC-118.19). A `Password` generator (32 letters
  and digits, no symbols, so it is safe inside a URL) feeds an `ExternalSecret` with `refreshPolicy: CreatedOnce` that writes all four
  contract keys of `<system>-<name>-app` through a template. Later renders, syncs, restarts and image upgrades never touch the Secret;
  nothing secret is in git. This is the mechanism of `secrets.generate` and of spec 116's bucket keys.
- **Valkey reads the password from that Secret** (env `VALKEY_PASSWORD`, `--requirepass $(VALKEY_PASSWORD)`), so the server and every
  client use one value (AC-118.11, AC-118.18).
- **Memory**: the container's memory request and limit are `memory`; the server gets `--maxmemory` = ⌊0.8 × bytes(`memory`)⌋ and
  `--maxmemory-policy` (AC-118.6). The 20 % headroom is for the server's own overhead and client buffers.
- **Persistence**: `persistence: true` = append-only file synced every second (`--appendonly yes --appendfsync everysec`) on a
  `storage`-sized volume from `volumeClaimTemplates` (AC-118.7). `persistence: false` = no volume at all and `--appendonly no`. RDB
  snapshots are off in both cases (`--save ""`).
- **Only a ClusterIP Service on port 6379** (`<system>-<name>`, also the StatefulSet's `serviceName`): no route, no `LoadBalancer`, no
  `NodePort` (AC-118.8). The host in the Secret is `<system>-<name>.<system>-<env>.svc`, so a scaler in another namespace (spec 120)
  reaches it with the same Secret.
- **Every object of a cache instance carries `app.kubernetes.io/name: <name>`** (StatefulSet, its pod template and volume claim
  template, Service, generator, ExternalSecret and, through the template, the Secret). Spec 117's Schedule leaves out exactly these
  objects and the pod volumes of those pods (`app.kubernetes.io/name NotIn [<target>, <cache names…>]`), so no cache data is in any
  backup (AC-118.14). `backup_files` does not change.
- **A change of `persistence` or `storage` recreates the StatefulSet** (`argocd.argoproj.io/sync-options: Force=true,Replace=true`
  on the StatefulSet), because `volumeClaimTemplates` cannot be updated in place. The pod restarts, which any template change does for
  a single node anyway; an existing volume is kept and reused.
- **Kyverno guard rails (ADR-022) match Deployments only and do not change.** The cache is a StatefulSet; it still satisfies every rule
  (non-root UID 999, read-only root filesystem, no privilege escalation, `drop: [ALL]`, requests and a memory limit, the part-of
  label), so nothing has to be weakened now or if the rules ever cover StatefulSets.
- **The type is called `cache`.** `type: redis` and `type: valkey` fail the render with "the type is `cache` (Redis-compatible, runs
  Valkey)" (AC-118.5); `/resource:add --type redis` keeps 114's message and adds that sentence as its hint (AC-118.22).

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `templates/gitops-app/scripts/render.py` (+ its copy `templates/cluster-gitops/scripts/system_render.py`) | cache schema and checks, `type: redis`/`valkey` text, `PLANNED_TYPES`, `CACHE_SUFFIXES`, `TYPES["cache"]`, `VALKEY_IMAGES`, `cache_files` (generator, ExternalSecret, Service, StatefulSet) | changed |
| `scripts/cplat/model.py` | cache sizing on in-cluster cache instances | changed |
| `scripts/cplat/addon.py` | `resource add <name> --type cache [--external [--path P]]`, the `redis`/`valkey` hint, cache texts in `remove` and the next steps | changed |
| `scripts/cplat/compose.py` | `--uses` help and the prefix note for caches | changed |
| `scripts/cplat/modelcmd.py`, `status.py`, `doctor.py` | nothing: they are generic over types (see their contracts below) | unchanged |

## Contract: `system.yaml`

```yaml
resources:
  sessions:
    type: cache
    version: 9                     # 8 | 9 (default 9): the Valkey major
    memory: 256Mi                  # default 256Mi; a Kubernetes quantity of at least 64Mi
    maxmemoryPolicy: allkeys-lru   # default allkeys-lru
    persistence: false             # true | false (default false)
    storage: 1Gi                   # only with persistence: true (default 1Gi there)
    external: false                # spec 115
    remote: {path: "{system}-{env}-{resource}", refreshInterval: 1h}   # spec 115, only where external
    instances:
      dev: {memory: 128Mi}
      prod: {persistence: true, storage: 5Gi}      # or {external: true}: an external instance takes no sizing key
```

| Where (type `cache`) | Allowed keys |
|---|---|
| `resources.<name>` | `type`, `external`, `remote`, `version`, `memory`, `maxmemoryPolicy`, `persistence`, `storage`, `instances` |
| `resources.<name>.instances.<env>` | `external`, `remote`, `memory`, `maxmemoryPolicy`, `persistence`, `storage` |
| `remote` | `path`, `refreshInterval` (as 115) |

Effective values per in-cluster environment: `version` = the resource's, else 9. `memory`, `maxmemoryPolicy`, `persistence` = the
instance's, else the resource's, else `256Mi`, `allkeys-lru`, `false`. `storage` = the instance's, else the resource's, else `1Gi`, and
only when the effective `persistence` is true (otherwise none). `external` and `remote` as in 115.

`memory` is a string (or integer) matching `^[0-9]+(\.[0-9]+)?(Ki|Mi|Gi|Ti|Pi|Ei|k|M|G|T|P|E)?$` whose byte value is at least 64Mi
(67108864). Bytes: binary suffixes are powers of 1024, decimal ones powers of 1000, no suffix = bytes; a fraction is allowed
(`0.5Gi`); the byte value is floored. `maxmemory` = ⌊bytes × 4 / 5⌋, e.g. `256Mi` → `214748364`, `64Mi` → `53687091`, `1Gi` →
`858993459`. Policies: `noeviction`, `allkeys-lru`, `allkeys-lfu`, `allkeys-random`, `volatile-lru`, `volatile-lfu`,
`volatile-random`, `volatile-ttl` (`MAXMEMORY_POLICIES`, in this order).

### Render errors (exit 1, nothing written, each after `applications/<dir>/system.yaml: `)

Before 115's "not a resource type" check (AC-118.5):

| Case | Text |
|---|---|
| `type: redis` or `type: valkey` | ``resources.<r>: type '<t>' is not a resource type: the type is `cache` (Redis-compatible, runs Valkey)`` |

The backticks around `cache` are part of the text. Every other type keeps 115's texts; `PLANNED_TYPES` becomes `{"broker": 119}`, so
only `broker` keeps "is not available yet". Then, for a cache, in this order (AC-118.2, AC-118.4):

| Case | Text |
|---|---|
| unknown key | `resources.<r>: unknown key '<k>' (allowed: type, external, remote, version, memory, maxmemoryPolicy, persistence, storage, instances)` |
| `external` not boolean | 115 texts |
| instances not a mapping | `resources.<r>.instances must be a mapping of environments to {external, remote, memory, maxmemoryPolicy, persistence, storage}` |
| instance environment, instance not a mapping | 115 texts |
| external instance with `memory`/`maxmemoryPolicy`/`persistence`/`storage`; checked before the unknown-key check | `resources.<r>.instances.<env>: an external cache is sized and configured at its provider (remove <key>)` |
| unknown instance key (`version` included) | `resources.<r>.instances.<env>: unknown key '<k>' (allowed: external, remote, memory, maxmemoryPolicy, persistence, storage)` |
| top-level `version`/`memory`/`maxmemoryPolicy`/`persistence`/`storage`, external everywhere | `resources.<r>: external in every environment: an external cache is sized and configured at its provider (remove <key>)` |
| `remote` and `secretStore` | 115 texts |
| `version` (only if some environment is in-cluster) | `resources.<r>: version '<v>' is not a supported cache version (8, 9)` (a digit string is read as its number, as for a database) |
| `memory` | `<where>: memory '<v>' must be a Kubernetes quantity of at least 64Mi, e.g. 256Mi` |
| `maxmemoryPolicy` | `<where>: maxmemoryPolicy '<v>' is not allowed (noeviction, allkeys-lru, allkeys-lfu, allkeys-random, volatile-lru, volatile-lfu, volatile-random, volatile-ttl)` |
| `persistence` not boolean | `<where>: persistence must be true or false` |
| `storage` not a size | `<where>: storage must be a size such as 1Gi` (`STORAGE_SIZE`) |
| instance `storage`, effective `persistence` false in that in-cluster environment | `resources.<r>.instances.<env>: storage needs persistence: true (persistence is false in <env>)` |
| resource `storage`, effective `persistence` false in every in-cluster environment | `resources.<r>: storage needs persistence: true in at least one environment` |

`<where>` is `resources.<r>` or `resources.<r>.instances.<env>`. The four value checks run per `<where>` (the resource first, then its
instances in their order), each `<where>` in the order memory, maxmemoryPolicy, persistence, storage; the two `storage needs
persistence` checks run last, instances in `ENVS` order, then the resource. 115's cluster-object clash check uses, for a cache,
`<system>-<name>` plus `CACHE_SUFFIXES = ("-app", "-password")`.

### Renderer API

`cfg["resources"][name]["envs"][env]` of a cache: `{"external", "version", "replicas": None, "storage", "resources": None, "memory",
"maxmemory", "maxmemoryPolicy", "persistence", "store_key", "refreshInterval"}`. In-cluster: `version` int, `memory` str as written,
`maxmemory` int bytes, `persistence` bool, `storage` str or `None` (persistence false). External: `version`, `storage`, `memory`,
`maxmemory`, `maxmemoryPolicy`, `persistence` are `None`. A database's and a bucket's dicts are unchanged.

## Contract: what a using component gets (AC-118.18, AC-118.20)

```python
TYPES["cache"] = {"keys": ["url", "host", "port", "password"],
                  "env": {"REDIS_URL": "url", "REDIS_HOST": "host", "REDIS_PORT": "port", "REDIS_PASSWORD": "password"}}
```

Rendered by 115's `addon_env`: `{"name": <VAR>, "valueFrom": {"secretKeyRef": {"name": "<system>-<r>-app", "key": <key>}}}` in table
order, after the literal `env`. With two or more caches: `<NAME>_<VAR>`, e.g. `SESSIONS_REDIS_URL`, `SESSIONS_REDIS_HOST`,
`SESSIONS_REDIS_PORT`, `SESSIONS_REDIS_PASSWORD`. One cache next to one database or bucket gives bare names for all. The env clash
check of 115 covers the new names. Every component that uses a cache gets the same Secret: database `0`, one password.

## Contract: in-cluster cache instance

Directory `applications/<system>/addons/<env>/<name>/`, an element `<name>` of the ApplicationSet `<system>-addons-<env>` (prune
false, Argo application `addon-<name>-<env>`), exactly as for a database. `<n>` = `<system>-<name>`, `<ns>` = `<system>-<env>`.
`L` = `{app.kubernetes.io/name: <name>, app.kubernetes.io/part-of: <system>, app.kubernetes.io/managed-by: gitops-app}`.
`S` = `{app.kubernetes.io/name: <name>, app.kubernetes.io/part-of: <system>}`. `W` = `argocd.argoproj.io/sync-wave: "-1"`.
Key order in every document is as written. Labels are fresh dicts (no YAML anchors).

`password-generator.yaml`:

```yaml
apiVersion: generators.external-secrets.io/v1alpha1
kind: Password
metadata: {name: <n>-password, labels: L, annotations: {W}}
spec: {length: 32, digits: 5, symbols: 0, noUpper: false, allowRepeat: true}
```

`externalsecret.yaml`:

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata: {name: <n>-app, labels: L, annotations: {W}}
spec:
  refreshPolicy: CreatedOnce
  target:
    name: <n>-app
    creationPolicy: Owner
    deletionPolicy: Retain
    template:
      engineVersion: v2
      metadata: {labels: L}
      data:
        url: "redis://:{{ .password }}@<n>.<ns>.svc:6379/0"
        host: <n>.<ns>.svc
        port: "6379"
        password: "{{ .password }}"
  dataFrom:
    - sourceRef: {generatorRef: {apiVersion: generators.external-secrets.io/v1alpha1, kind: Password, name: <n>-password}}
```

`service.yaml`:

```yaml
apiVersion: v1
kind: Service
metadata: {name: <n>, labels: L}
spec:
  type: ClusterIP
  selector: S
  ports: [{name: redis, port: 6379, targetPort: redis}]
```

`statefulset.yaml`:

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata: {name: <n>, labels: L, annotations: {argocd.argoproj.io/sync-options: "Force=true,Replace=true"}}
spec:
  replicas: 1
  serviceName: <n>
  selector: {matchLabels: S}
  template:
    metadata: {labels: L}
    spec:
      automountServiceAccountToken: false
      securityContext: {runAsNonRoot: true, runAsUser: 999, runAsGroup: 999, fsGroup: 999, seccompProfile: {type: RuntimeDefault}}
      containers:
        - name: valkey
          image: <VALKEY_IMAGES[version]>
          command: [valkey-server]
          args: [--port, "6379", --requirepass, $(VALKEY_PASSWORD), --maxmemory, "<maxmemory>", --maxmemory-policy, <policy>,
                 --save, "", --dir, /data, --appendonly, "no"]                        # persistence: false
          # persistence: true ends with: --appendonly, "yes", --appendfsync, everysec
          env: [{name: VALKEY_PASSWORD, valueFrom: {secretKeyRef: {name: <n>-app, key: password}}}]
          ports: [{name: redis, containerPort: 6379}]
          resources: {requests: {cpu: 50m, memory: <memory>}, limits: {memory: <memory>}}
          readinessProbe: {exec: {command: [sh, -c, 'valkey-cli --no-auth-warning -a "$VALKEY_PASSWORD" ping | grep -q PONG']}, periodSeconds: 5}
          livenessProbe: {tcpSocket: {port: redis}, initialDelaySeconds: 10, periodSeconds: 10}
          securityContext: {runAsNonRoot: true, runAsUser: 999, allowPrivilegeEscalation: false, readOnlyRootFilesystem: true, capabilities: {drop: [ALL]}}
          volumeMounts: [{name: data, mountPath: /data}]                               # persistence: true only
  volumeClaimTemplates:                                                                # persistence: true only
    - metadata: {name: data, labels: L}
      spec: {accessModes: [ReadWriteOnce], resources: {requests: {storage: <storage>}}}
```

`<maxmemory>` and `"6379"` are strings in `args`; `<memory>` is the effective value as a string. With `persistence: false` there is no
`volumeMounts` and no `volumeClaimTemplates` key at all (AC-118.7). `kustomization.yaml`: `{apiVersion: kustomize.config.k8s.io/v1beta1,
kind: Kustomization, resources: [externalsecret.yaml, password-generator.yaml, service.yaml, statefulset.yaml]}`.

Nothing else is rendered for a cache: no `HTTPRoute`, no other Service, no operator file (AC-118.8, AC-118.23). The pod is
`<n>-0`; with persistence its volume is the PVC `data-<n>-0`.

**Spec 117 (AC-118.14).** No change: `backup_files` already puts every `cache` resource name (sorted, used or not) after the target in
`app.kubernetes.io/name NotIn`, and the labels above put every cache object and pod under it. Velero's file-system backup only backs up
volumes of selected pods, so `data-<n>-0` is never read.

## Contract: external cache instance (AC-118.20)

Spec 115's ExternalSecret `<system>-<name>-app` in the overlay of the alphabetically first running user, one `data` entry per
`TYPES["cache"]["keys"]` (`url`, `host`, `port`, `password`), store key `{system}-{env}-{resource}` by default, no defaults, no
template. A `rediss://` URL is copied as stored. No addon directory, ApplicationSet element or StatefulSet for that environment.

## Contract: versions table (AC-118.17, AC-118.23)

```python
VALKEY_IMAGES = {                  # matches ^valkey/valkey:\d+\.\d+\.\d+(@sha256:[0-9a-f]{64})?$; no bare major, no latest
    8: "valkey/valkey:8.1.11",
    9: "valkey/valkey:9.1.3",
}
CACHE_VERSIONS = (8, 9)            # default 9
```

Next to `POSTGRES_IMAGES`. A cache instance runs `VALKEY_IMAGES[version]`. Changing a pin or a `version` follows spec 121 (until it
ships, as in 115/116: the next render after `/platform:update` writes it into every environment; the order through the environments
and the downgrade refusal come with spec 121; its fresh-backup precondition never applies to a cache, AC-121.27).

**Verified on 2026-10-27, re-verify at build:** Docker Hub's tags API (`hub.docker.com/v2/repositories/valkey/valkey/tags`, ordered by
`last_updated`): `9`, `9.1` and `latest` point at the same push as `9.1.3` (2026-10-27T00:41Z, index digest
`sha256:3add1a336a920ea54770a001ab6feb3da5fceea96a40373a3a2cd469b815f0b7`, amd64, arm64, arm/v7, ppc64le); `8` and `8.1` at the same push
as `8.1.11` (2026-10-27T00:44Z, `sha256:8f836008e0986c36adf50da714c7060cf689dbb335f61fe077939d90fa650809`). Older lines still pushed:
`9.0.7`, `8.0.12`, `7.2.15`. Only the first ~60 of 321 tags were listed, ordered by push time, so a higher patch released later on
the same day would not be seen. At build also confirm in the pinned image: the user `valkey` is UID/GID 999, `/data` exists and is the
working directory, `valkey-server` and `valkey-cli` are on `PATH`, `sh` exists, and `valkey-cli -u redis://…` is accepted.

## Contract: `cplat resource` (AC-118.1, AC-118.13, AC-118.22)

`cplat resource add <name> --type cache [--external [--path P]]`. 115/116 checks keep their order and texts; `cache` passes the type
checks (`PLANNED_TYPES = {"broker": 119}`); `--version` stays database-only (`--version applies to --type database only`) and
`--storage`/`--versioning` bucket-only (their 116 texts). `--type` help: `resource type: database, bucket or cache (broker is planned)`.

| Case | Text |
|---|---|
| `--type redis` or `--type valkey` | 114's `unknown resource type '<t>' (database, bucket, cache or broker)` unchanged, with the hint ``the type is `cache` (Redis-compatible, runs Valkey): /resource:add <name> --type cache`` |

Entries written: in-cluster `{type: cache}` (no sizing key, AC-118.1); external `{type: cache, external: true}` (+ `remote: {path: P}`).

Next steps after adding a cache: 115's `let components use it: …` line, then either
`no operator is needed: each environment where a component uses it runs one Valkey StatefulSet (defaults: Valkey 9, memory 256Mi, allkeys-lru, persistence false; set them in system.yaml)`
(in-cluster) or `put the keys url, host, port, password in the secret store <store> under <dev key>, <staging key>, <prod key>` (external).

`remove`: 115's refusals (`<n> is still used by <c1>, <c2>`, nothing changed, AC-118.13). The `will_do` lines for a cache:

- in-cluster instances: `remove <n> from system.yaml; the Argo Application disappears but the cache, its volume and its Secret <system>-<n>-app stay in the cluster (delete them by hand when you are sure)`
- external instances: `remove <n> from system.yaml; the synced Secret <system>-<n>-app stays in the cluster (delete it by hand when you are sure); the external cache is not touched`

## Contract: model, status, doctor, compose

- **Model**: an in-cluster cache instance has `sizing = {"version": <int, default 9>, "memory": <default "256Mi">, "maxmemoryPolicy":
  <default "allkeys-lru">, "persistence": <bool, default False>}` plus `"storage": <default "1Gi">` last, only when persistence is true.
  An external one has `{}`. Lenient like the rest of `build` (a digit-string version is read as a number). `cplat model show` prints
  `version 9  memory 256Mi  maxmemoryPolicy allkeys-lru  persistence false` (booleans lower case, `modelcmd` unchanged). JSON: schema
  2, `resource_instances[].sizing` as above, nothing else changes.
- **Status**: no change. A cache is a row of the resource table and of `resources[]` in `--json` with its `addon-<name>-<env>` Argo
  state (`external` where external), like any resource; it is not part of the `backups` section (that lists database instances and
  environments only).
- **Doctor**: no change and no row for a cache: `check_operators` has no operator for the type and `check_backups` names databases and
  environments only (AC-118.15, AC-118.23).
- **compose**: the `--uses` help reads
  ``resource or library the component needs (a database gives DATABASE_URL and PG*, a bucket S3_* and AWS_*, a cache REDIS_URL and REDIS_*); declare it first with `cplat resource add <name> --type database|bucket|cache` ``.
  The prefix note for caches reads `<c> now uses <n> cache resources: their variables are prefixed (<NAME>_REDIS_URL, …) and REDIS_* are no longer injected`.
  The database and bucket notes are unchanged.

## Contract: e2e (AC-118.15 and the cluster halves of AC-118.6, .7, .8, .11, .14, .18, .19, .23)

After the external-bucket steps and before the ship steps, in dev, with the cluster already up (no new cluster-up flag: a cache needs
no operator): caches `sessions` (`instances.dev: {persistence: true}`) and `ratelimit` (`memory: 64Mi`), both used by e2e-web (two
caches: the prefix rule). Checks: no new file under `operators/`; the Secrets carry four keys, a 32-character password and the
designed `url`; NOAUTH / WRONGPASS / PONG; `maxmemory` `53687091` and `allkeys-lru` on ratelimit, limit `64Mi`; only ClusterIP
Services; a probe pod with e2e-web's `*_REDIS_*` variables SETs and GETs a value through `SESSIONS_REDIS_URL`; filling ratelimit past
`maxmemory` evicts keys without a restart, and under `noeviction` (set at runtime) a write gets `OOM`; deleting both pods keeps the
sessions key and empties ratelimit; the password survives restart and re-apply; doctor names no cache. In the backup steps: the
Schedule's NotIn list holds both names, and neither the Velero Backup's pod volume backups nor the restore's volume list name
`e2e-sessions-0`.

## Risks

- **`refreshPolicy: CreatedOnce` in the pinned ESO (2.12.0).** The field is documented upstream; if the pinned CRD lacks it, the build
  uses spec 116's `refreshInterval: "0"` instead and changes this section (that form regenerates the password when the ExternalSecret's
  spec changes, so its document must then never change between releases).
- **Small memory values.** At 64Mi the headroom is ~13 MiB; Valkey's base footprint is a few MiB. The e2e fill test is the proof; if
  the server is OOM-killed there, the minimum is raised (design and the AC-118.4 text change in the same PR).
- **Fork during an AOF rewrite** (`persistence: true`) copies changed pages and can exceed the 20 % headroom for write-heavy caches
  near `maxmemory`. Documented: give persistent caches more `memory`.
- **`Force=true,Replace=true`** recreates the StatefulSet for any change, so every change restarts the pod (as a single node does
  anyway). Growing `storage` does not resize an existing volume (Kubernetes reuses the PVC `data-<n>-0`); documented.
- **Downgrades** (`version: 9` → `8`) are not refused before spec 121; an AOF written by 9 may not load in 8. With persistence the pod
  then crash-loops until the volume is deleted. Documented next to `version`.
- **Read-only root filesystem with `persistence: false`**: Valkey writes nothing without AOF and RDB. The e2e run proves it; if the
  pinned image needs a writable directory, the build mounts an `emptyDir` at `/tmp` (not `/data`) and updates this section.

## Decisions taken by default

1. **`memory` must be at least 64Mi.** The spec only requires a Kubernetes quantity; below 64Mi the server has no headroom (and `0`
   would mean "no limit" to Valkey). Alternative: no minimum. Chosen so a valid render never yields a server killed for memory.
2. **Quantities**: plain number, binary (`Ki`…`Ei`) and decimal (`k`, `M`…`E`) suffixes, a fraction allowed; no milli, no exponent
   form. `maxmemory` is floored to whole bytes.
3. **The password is 32 letters and digits, generated once (`refreshPolicy: CreatedOnce`)**. Alternative: symbols (would need URL
   encoding in `url`) or spec 116's `refreshInterval: "0"` (regenerates when the document changes).
4. **`host` is `<n>.<ns>.svc`**, not the short name, so the same Secret works from another namespace (spec 120's scaler).
5. **One ClusterIP Service is also the StatefulSet's `serviceName`**; no headless Service (one pod needs no per-pod DNS).
6. **`persistence: false` renders no volume at all** (not an `emptyDir`), which is what AC-118.7 says.
7. **RDB snapshots are off in both modes; persistence is AOF `everysec`** (the spec's answer), so no fork happens without persistence.
8. **The StatefulSet is recreated on change (`Force=true,Replace=true`)**. Alternative: refuse `persistence`/`storage` changes, or
   leave Argo CD stuck on an immutable field. Chosen because a cache tolerates a restart and the volume is kept.
9. **Resources: memory request = limit = `memory`, CPU request 50m, no CPU limit.** Alternative: make CPU configurable (not in the
   spec's key list, AC-118.2).
10. **Valkey runs as UID 999, read-only root filesystem, `drop: [ALL]`, RuntimeDefault seccomp, no service-account token**, bypassing the
    image's entrypoint (`command: [valkey-server]`).
11. **`/resource:add --type cache` takes no sizing flags**; `--version` stays database-only. Sizing is edited in `system.yaml`, and
    116's flag texts stay unchanged. Alternative: `--version`/`--memory` flags.
12. **`/resource:add --type redis|valkey` keeps 114's message and adds the `cache` sentence as a hint** (AC-118.22 forbids changing
    the message; the render text is AC-118.5's).
13. **Removing a cache keeps its objects in the cluster** (addons are not pruned), like a database. Alternative: prune caches (their
    data is disposable). Chosen for one rule across resource types.
14. **Version moves and downgrades wait for spec 121**; 118 only adds the table rows. **Pins are tags without digest** like the other
    rows; the verified digests are recorded above for spec 121, which adds digests to every row.
15. **Object clash suffixes are `-app` and `-password`.**
16. **The e2e test has no external cache step**: 115's generic ExternalSecret is already proven for a database and a bucket, and the
    render tests prove the four keys and the unchanged `rediss://` URL. It keeps the e2e job under its 60-minute limit.
17. **The `--uses` help and prefix note name caches**, which amends one 116 assertion (plan t9).

**Verified at plan time (2026-10-27, orchestrator):** the External Secrets 2.12.0 chart's `ExternalSecret` CRD has
`refreshPolicy: CreatedOnce`; `valkey/valkey:9.1.3` and `valkey/valkey:8.1.11` have user `valkey` with UID/GID 999 and working directory
`/data` (read from the images' `/etc/passwd` and config, nothing run). Still for t2/t8: the read-only root filesystem without a volume,
`valkey-cli -u`, and eviction within 64Mi.
