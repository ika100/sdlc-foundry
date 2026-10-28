# Design — 119 A message broker resource behind events APIs

Extends [spec 115's design](../115-resources-are-named-typed-and-may-be/design.md) (the `TYPES` contract, the prefix rule, external
instances, the versions table, `operators/`), [spec 116's design](../116-an-object-storage-resource-for-files-and/design.md)
(`Delete=false` on data-bearing objects), [spec 117's design](../117-databases-and-environments-are-backed-up/design.md) (the Velero
Schedule, `envrestore`), [spec 118's design](../118-a-cache-resource-compatible-with-redis/design.md) (passwords generated once by
External Secrets Operator, `PLANNED_TYPES`, `TYPE_KEYS`) and [spec 125's design](../125-a-cluster-repo-hosts-several-systems/design.md)
(`OPERATORS` shared with cluster repos through `operator_application`, synced template copies). Everything is additive: a
`system.yaml` without `type: broker` renders byte-identically, including one that declares events APIs (decision 1 under "Decisions
taken by default"), and every message of specs 114–118 keeps its text except the ones this spec retires on purpose (`broker` is no
longer "not available yet"; `--version applies to --type database only` names the broker too; amended tests, plan t12).

## Decisions

- **A broker instance is one NATS server (JetStream on, file storage) from the official `nats` Helm chart, installed as a nested Argo
  CD `Application` that the broker's addon directory renders** (AC-119.1, AC-119.21). The addon directory also holds the generated
  credentials and the NACK objects (`Account`, one `Stream` per events API, one `Consumer` per consuming component). Streams and
  consumers are declared objects, so Argo CD shows them and the platform never talks to the broker itself.
  ADR: [065](../../adr/065-a-broker-is-nats-jetstream-with-declared-streams-and-per-component-users.md).
- **NACK (the NATS JetStream controller) is a platform operator** in the versions table (`OPERATORS["nack"]`,
  `OPERATOR_OF_TYPE["broker"] = "nack"`): `operators/apps/nack.yaml` appears exactly when an environment that does not set
  `operators: owner` runs an in-cluster broker (AC-119.22, AC-119.23), and cluster repos list it like any operator (ADR-060). It runs
  in its default (legacy) mode with `-crd-connect`, which the chart sets by itself when no global server URL is given; each broker
  instance is reached through its own `Account` object. The experimental `--control-loop` mode is not used.
- **One user per component and environment, generated once**: a `Password` generator `<n>-password` feeds one `ExternalSecret` per
  component (`refreshPolicy: CreatedOnce`) that writes `url`, `user`, `password` into `<system>-<name>-<component>-app`
  (AC-119.11). The NATS server reads each password from those Secrets through container variables referenced in its config
  (`<< $USER_<C>_PASSWORD >>`); nothing secret is in git. NACK has its own admin user `_nack` (Secret `<n>-nack`); a component
  name is a DNS label, so `_nack` can never be a component's user.
- **Rights are subject permissions per user** (AC-119.12): the provider of an API may publish on `<system>.<api>.>`; a consumer may
  only fetch from and acknowledge on its own durable consumer; every user may subscribe only to its own inbox prefix
  `_INBOX.<component>.>`. Because a shared `_INBOX.>` would let any component read the messages another component fetches, each
  component also gets `NATS_INBOX_PREFIX` (= `_INBOX.<component>`) and must pass it to its client (the docs example does).
- **Names**: stream `<system>-<api>`, subjects `<system>.<api>.>`, durable consumer = the component name, kept 7 days, acknowledged
  within 30 seconds (AC-119.9, AC-119.10). Consumers are pull consumers (no deliver subject), deliver policy `all`, unlimited
  redeliveries.
- **Nothing that holds messages is ever deleted by a render or a sync** (AC-119.14): `Stream` and `Consumer` carry
  `preventDelete: true` (NACK leaves the server object when the Kubernetes object goes), `argocd.argoproj.io/sync-options:
  Delete=false,…` and `argocd.argoproj.io/compare-options: IgnoreExtraneous` (a removed one does not turn the application
  OutOfSync); the addon application never prunes (spec 115). The render that removes their files prints each one.
- **Binding**: an events API is carried by `broker: <name>` or, without it, by the system's only broker (AC-119.5, AC-119.6). Its
  provider and consumers use that broker implicitly (AC-119.7). A component's broker variables always follow the variables of its
  declared resources, in the order of its `provides` then `consumes`, wherever (and whether) the broker is listed in `uses`, so
  listing it changes nothing.
- **Broker data is part of the environment backup** (spec 117, as the spec's non-goal states): the chart's `nameOverride` sets
  `app.kubernetes.io/name: <name>` on every chart object, which no `NotIn` entry of spec 117's Schedule (the target bucket, the caches)
  can match, because resource names are unique; the `Account`, `Stream` and `Consumer` objects carry the same label. `backup_files`
  does not change; the JetStream volume of each broker pod is backed up with the pod volume backups and restored by `cplat system
  restore --replace` like any other workload volume (its root is the StatefulSet, tracked by the nested application, which
  `envrestore` already pauses by `status.resources`).
- **Kyverno guard rails (ADR-022) match Deployments only and do not change.** The NATS StatefulSet is hardened anyway (non-root,
  read-only root filesystem, no privilege escalation, `drop: [ALL]`, RuntimeDefault seccomp); `natsBox` (a Deployment) is disabled.
- **No sync option recreates anything**: the nested application syncs with `prune` and `selfHeal` only; a change of `storage` stops at
  the StatefulSet's immutable `volumeClaimTemplates` exactly like a cache (one documented `--cascade=orphan` delete).

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `templates/gitops-app/scripts/render.py` (+ its copy `templates/cluster-gitops/scripts/system_render.py`) | broker schema and checks, `apis.<a>.broker`, binding, effective `uses`, object clashes; `TYPES["broker"]`, `NATS_CHART`, `NATS_IMAGES`, `BROKER_VERSIONS`, `OPERATORS["nack"]`; `broker_files`; the component variables; external broker ExternalSecrets; render notes; stale broker files | changed |
| `templates/gitops-app/scripts/local-cluster.sh` (+ its copy in `templates/cluster-gitops/scripts/`) | `WITH_NACK`, `NACK_VERSION`: NACK from `operators/root.yaml` (Argo CD) or a k3s `HelmChart` (`WITH_ARGO=0`) | changed |
| `templates/gitops-app/scripts/bootstrap.sh` | waits for `streams.jetstream.nats.io` after `operators/apps/nack.yaml` | changed |
| `templates/cluster-gitops/scripts/check.py` | a broker instance needs `external-secrets` too | changed |
| `scripts/cplat/model.py` | `Api.broker`, implicit broker `uses`, broker sizing, `ResourceInstance.broker` | changed |
| `scripts/cplat/modelcmd.py`, `scripts/cplat/apilist.py` | broker lines in `model show`, `broker` in `/api:list` | changed |
| `scripts/cplat/addon.py` | `resource add <name> --type broker [--version V] [--replicas N] [--external [--path P]]`, the refusal of `remove` while an events API is bound | changed |
| `scripts/cplat/doctor.py` | `operator nack` row, one `broker <name> (<env>)` row per in-cluster broker instance | changed |
| `scripts/cplat/compose.py`, `status.py`, `envrestore.py`, `backup_files` | nothing: brokers come through APIs; status and restore are generic | unchanged |

## Contract: `system.yaml`

```yaml
resources:
  bus:
    type: broker
    version: "2.15"                # "2.14" | "2.15" (default "2.15"): the NATS server minor line; a YAML float 2.15 is read as "2.15"
    replicas: 1                    # 1 | 3 (default 1)
    storage: 1Gi                   # JetStream file storage per replica (default 1Gi)
    resources: {requests: {cpu: 100m, memory: 256Mi}, limits: {memory: 512Mi}}   # the defaults
    external: false                # spec 115
    remote: {path: "{system}-{env}-{resource}-{component}", refreshInterval: 1h}   # spec 115 + {component}; only where external
    instances:
      prod: {replicas: 3, storage: 10Gi}           # or {external: true}: an external instance takes no sizing key
apis:
  orders: {type: events, broker: bus}   # broker: only on events APIs; optional when the system has exactly one broker
```

| Where (type `broker`) | Allowed keys |
|---|---|
| `resources.<name>` | `type`, `external`, `remote`, `version`, `replicas`, `storage`, `resources`, `instances` |
| `resources.<name>.instances.<env>` | `external`, `remote`, `replicas`, `storage`, `resources` |
| `remote` | `path`, `refreshInterval`; `path` placeholders `{system}`, `{env}`, `{resource}`, `{component}` |
| `apis.<api>` | `type`, plus `broker` when `type: events` |

Effective values per in-cluster environment: `version` = the resource's (a float or digit string read as its text), else `"2.15"`;
`replicas`, `storage`, `resources` = the instance's, else the resource's, else `1`, `"1Gi"`, `BROKER_DEFAULT_RESOURCES =
{"requests": {"cpu": "100m", "memory": "256Mi"}, "limits": {"memory": "512Mi"}}`.

### Render errors (exit 1, nothing written, each after `applications/<dir>/system.yaml: `)

`PLANNED_TYPES` becomes `{}`: `broker` is accepted. For a broker, in 115's order (AC-119.1, AC-119.2, AC-119.3):

| Case | Text |
|---|---|
| unknown key | `resources.<r>: unknown key '<k>' (allowed: type, external, remote, version, replicas, storage, resources, instances)` |
| `external` not boolean, instance environment, instance not a mapping | 115 texts |
| instances not a mapping | `resources.<r>.instances must be a mapping of environments to {external, remote, replicas, storage, resources}` |
| external instance with `replicas`/`storage`/`resources`; before the unknown-key check | 115's `resources.<r>.instances.<env>: an external resource runs nothing (remove <key>)` |
| unknown instance key (`version` and `backup` included) | `resources.<r>.instances.<env>: unknown key '<k>' (allowed: external, remote, replicas, storage, resources)` |
| top-level sizing, external everywhere | 115's `resources.<r>: external in every environment: an external resource runs nothing (remove <key>)` |
| `remote`, `secretStore`, placeholders | 115 texts; the allowed placeholders of a broker's `remote.path` are `{system}, {env}, {resource}, {component}` |
| `version` (only if some environment is in-cluster) | `resources.<r>: version '<v>' is not a supported broker version (2.14, 2.15)` |
| `replicas` not 1 or 3 | `<where>: a broker runs with 1 or 3 replicas (replicas: <v>)` |
| `storage` not a size | `<where>: storage must be a size such as 1Gi` (`STORAGE_SIZE`) |
| `resources` not a mapping | `<where>: resources must be a mapping with requests and limits, e.g. {requests: {cpu: 100m, memory: 256Mi}, limits: {memory: 512Mi}}` |

`<where>` is `resources.<r>` or `resources.<r>.instances.<env>`; the three value checks run per `<where>` (the resource first, then its
instances in their order), each in the order replicas, storage, resources. 115's generic `replicas must be a number of at least 1`
does not run for a broker. The database-only check `an external database is backed up by its provider` runs only for `type:
database` (for a broker `backup` is an unknown instance key).

APIs (`validate_apis`, before the resources are read; AC-119.8):

| Case | Text |
|---|---|
| `broker` on an API whose type is not `events` | `apis.<a>: only events APIs are carried by a broker (remove broker from this <type> API)` |
| unknown key on an events API | `apis.<a>: unknown key '<k>' (allowed: type, broker)` |
| unknown key on any other API | 114's `apis.<a>: unknown key '<k>' (allowed: type)` (unchanged) |

Binding (`bind_events`, after `validate_resources`, events APIs in `apis:` order; AC-119.5, AC-119.6):

| Case | Text |
|---|---|
| `broker:` names no resource, a resource of another type, or is not a string | `apis.<a>: broker '<b>' is not a broker resource of the system (brokers: <b1>, <b2> \| none)` |
| no `broker:` and two or more brokers | `apis.<a>: the system has several brokers (<b1>, <b2>): choose one with apis.<a>.broker` |
| a bound API whose name is not a lowercase DNS label | `apis.<a>: an events API carried by a broker needs a lowercase DNS label as its name (it names the stream <system>-<a> and the subjects <system>.<a>.>)` |
| no `broker:` and no broker in the system | no error: the API stays unbound and the render prints the note of AC-119.6 (decision 1 under "Decisions taken by default") |

Components (`validate_uses`; AC-119.7), after 115's "neither a resource nor a library" check:

| Case | Text |
|---|---|
| `uses` lists a broker that carries none of the component's events APIs | `components.<c>: uses '<b>', a broker; a component reaches a broker through an events API it provides or consumes, and none of <c>'s is carried by <b>` |
| the component's `env` sets a variable the broker gives it (NATS_*, EVENTS_*, NATS_INBOX_PREFIX) | 115's `components.<c>: env <K> is provided by the '<b>' resource; remove it from `env`` |

Object clashes (115's check): a broker creates `<n>`, `<n>-headless`, `<n>-config` (chart objects), `<n>-nack`, `<n>-password`
(`BROKER_SUFFIXES`) and `<n>-<c>-app` for every component that provides or consumes an API it carries; 115's connection-Secret map
gains each `<n>-<c>-app`, so a component secret of that name fails with 115's text.

### Renderer API

`cfg["resources"][name]["envs"][env]` of a broker: `{"external", "version", "replicas", "storage", "resources", "store_key",
"refreshInterval"}` (a database's keys without `backup`). In-cluster: `version` str, `replicas` int, `storage` str, `resources` the
mapping or `None` (the renderer then uses `BROKER_DEFAULT_RESOURCES`). External: `version`, `replicas`, `storage`, `resources` are
`None`; `store_key` keeps `{component}` (e.g. `shop-dev-bus-{component}`).

`cfg["events"]`: `{api: {"broker": <name> | None, "provider": <component> | None, "consumers": [<component>, …]}}` for every events
API in `apis:` order (consumers in `components:` order). Each service's `uses` is its effective list: the declared resources that are
not brokers, in `uses` order, then the brokers of its events APIs (`provides` then `consumes`, first appearance), each once. This is
what `addons_in`, `resource_instances`, `operator_files`, `variable_names` and the model read.

## Contract: what a component gets (AC-119.11)

```python
TYPES["broker"] = {"keys": ["url", "user", "password"],
                   "env": {"NATS_URL": "url", "NATS_USER": "user", "NATS_PASSWORD": "password"}}
```

For a component `<c>` that provides or consumes an events API carried by broker `<b>`:

- From `addon_env`, after the variables of its other resources: `NATS_URL`, `NATS_USER`, `NATS_PASSWORD` as
  `{"name": <VAR>, "valueFrom": {"secretKeyRef": {"name": "<system>-<b>-<c>-app", "key": <key>}}}` (the per-component Secret, not
  `<system>-<b>-app`). Two brokers: `<NAME>_NATS_URL`, … (115's prefix rule).
- In the sorted literal block (with `PORT`, the OTEL variables and `env`): per events API `<api>` it provides or consumes
  `EVENTS_<API>_STREAM` = `<system>-<api>`, `EVENTS_<API>_SUBJECT_PREFIX` = `<system>.<api>`, plus `EVENTS_<API>_CONSUMER` = `<c>`
  when it consumes `<api>`; `<API>` is the name in upper case with `-` → `_`. Once: `NATS_INBOX_PREFIX` = `_INBOX.<c>`. An unbound
  events API (no broker in the system) gives nothing.
- A library gets nothing (no instance). An external component (spec 069) gets no injected variables (its package wires itself, as
  for every resource); on the broker side it counts like any component (user, Secret in `<system>-<env>`, consumer).

## Contract: in-cluster broker instance (AC-119.1 to .3, .9 to .12, .16, .20, .21)

Directory `applications/<system>/addons/<env>/<name>/`, an element of the ApplicationSet `<system>-addons-<env>` (prune false,
application `addon-<name>-<env>`). It is rendered where a running component (any instance in `<env>`, external components included)
provides or consumes an API the broker carries. The `addons` ApplicationSet of such an environment gets 115's `retry: RETRY` in its
`syncPolicy` (the `Account`, streams and consumers wait for NACK and the server); an environment without a broker keeps its
ApplicationSet byte for byte. `<n>` = `<system>-<name>`, `<ns>` = `<system>-<env>`, `<url>` = `nats://<n>.<ns>.svc:4222`,
`L` = `{app.kubernetes.io/name: <name>, app.kubernetes.io/part-of: <system>, app.kubernetes.io/managed-by: gitops-app}`. Users =
the components with an instance in `<env>` that provide or consume an API the broker carries, in `components:` order. Key order in
every document is as written; labels are fresh dicts.

`password-generator.yaml`:

```yaml
apiVersion: generators.external-secrets.io/v1alpha1
kind: Password
metadata: {name: <n>-password, labels: L, annotations: {argocd.argoproj.io/sync-wave: "-1"}}
spec: {length: 32, digits: 5, symbols: 0, noUpper: false, allowRepeat: true}
```

`nack-secret.yaml` (NACK's admin user) and `externalsecret-<c>.yaml` per user (same shape):

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata: {name: <n>-nack | <n>-<c>-app, labels: L, annotations: {argocd.argoproj.io/sync-wave: "-1"}}
spec:
  refreshPolicy: CreatedOnce
  target:
    name: <n>-nack | <n>-<c>-app
    creationPolicy: Owner
    deletionPolicy: Retain
    template:
      engineVersion: v2
      metadata: {labels: L}
      data: {user: _nack, password: "{{ .password }}"}                      # nack-secret.yaml
      # externalsecret-<c>.yaml: data: {url: <url>, user: <c>, password: "{{ .password }}"}
  dataFrom:
    - sourceRef: {generatorRef: {apiVersion: generators.external-secrets.io/v1alpha1, kind: Password, name: <n>-password}}
```

`server.yaml`, the NATS server (AC-119.21):

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata: {name: <system>-<name>-<env>-nats, namespace: argocd, labels: L}
spec:
  project: default
  source:
    repoURL: https://nats-io.github.io/k8s/helm/charts
    chart: nats
    targetRevision: 2.15.1                               # NATS_CHART["chart_version"]
    helm:
      releaseName: <n>
      valuesObject:
        nameOverride: <name>
        fullnameOverride: <n>
        global: {labels: {app.kubernetes.io/part-of: <system>}}
        config:
          cluster: {enabled: false}                      # replicas 3: {enabled: true, replicas: 3}
          jetstream:
            enabled: true
            fileStore: {enabled: true, pvc: {enabled: true, size: <storage>}}
            memoryStore: {enabled: false}
          monitor: {enabled: true, port: 8222}
          merge:
            authorization:
              users:
                - {user: _nack, password: "<< $ADMIN_PASSWORD >>"}
                - user: <c>
                  password: "<< $USER_<C>_PASSWORD >>"
                  permissions:
                    publish: {allow: [<publish list>]}
                    subscribe: {allow: ["_INBOX.<c>.>"]}
        container:
          image: {repository: nats, tag: <tag>}          # NATS_IMAGES[version] split at the last ':'
          env:
            ADMIN_PASSWORD: {valueFrom: {secretKeyRef: {name: <n>-nack, key: password}}}
            USER_<C>_PASSWORD: {valueFrom: {secretKeyRef: {name: <n>-<c>-app, key: password}}}   # per user, in user order
          merge:
            resources: <resources or BROKER_DEFAULT_RESOURCES>
            securityContext: S
        reloader:
          enabled: true
          merge: {securityContext: S}
        podTemplate:
          merge:
            spec:
              automountServiceAccountToken: false
              securityContext: {runAsNonRoot: true, runAsUser: 1000, runAsGroup: 1000, fsGroup: 1000, seccompProfile: {type: RuntimeDefault}}
        service: {ports: {monitor: {enabled: true}}}
        natsBox: {enabled: false}
  destination: {server: <cluster_server>, namespace: <ns>}
  syncPolicy: {automated: {prune: true, selfHeal: true}}
```

`S` = `{runAsNonRoot: true, runAsUser: 1000, allowPrivilegeEscalation: false, readOnlyRootFilesystem: true, capabilities: {drop:
[ALL]}}`. `<C>` = the component name upper-cased with `-` → `_`. The `_nack` user has no `permissions` (all rights). A user's publish
list, APIs in `apis:` order: for each API it provides `"<system>.<api>.>"`; then for each API it consumes, `<s>` = `<system>-<api>`:
`"$JS.API.CONSUMER.INFO.<s>.<c>"`, `"$JS.API.CONSUMER.MSG.NEXT.<s>.<c>"`, `"$JS.ACK.<s>.<c>.>"`, `"$JS.ACK.*.*.<s>.<c>.>"` (the
second ack form is JetStream's domain-qualified ack subject). The `<< … >>` strings are unquoted by the chart into NATS variable
references, resolved from the container environment. The chart then creates the StatefulSet `<n>` (pods `<n>-0` …, label
`app.kubernetes.io/name: <name>`), the Services `<n>` (ports 4222 and 8222, ClusterIP) and `<n>-headless`, the ConfigMap `<n>-config`,
a PodDisruptionBudget `<n>` and per pod the PVC `<n>-js-<n>-<i>`.

`account.yaml`:

```yaml
apiVersion: jetstream.nats.io/v1beta2
kind: Account
metadata: {name: <n>, labels: L, annotations: {argocd.argoproj.io/sync-wave: "1", argocd.argoproj.io/sync-options: SkipDryRunOnMissingResource=true}}
spec: {name: <n>, servers: ["<url>"], user: {secret: {name: <n>-nack}, user: user, password: password}}
```

`stream-<api>.yaml` per events API the broker carries (all of them, in `apis:` order, whether or not its provider runs in `<env>`):

```yaml
apiVersion: jetstream.nats.io/v1beta2
kind: Stream
metadata:
  name: <system>-<api>
  labels: L
  annotations: {argocd.argoproj.io/sync-wave: "2", argocd.argoproj.io/sync-options: "Delete=false,SkipDryRunOnMissingResource=true", argocd.argoproj.io/compare-options: IgnoreExtraneous}
spec: {name: <system>-<api>, subjects: ["<system>.<api>.>"], storage: file, replicas: <replicas>, retention: limits, discard: old, maxAge: 168h, account: <n>, preventDelete: true}
```

`consumer-<api>.<c>.yaml` per consuming component with an instance in `<env>` (the dot keeps `<api>`/`<c>` pairs unique):

```yaml
apiVersion: jetstream.nats.io/v1beta2
kind: Consumer
metadata:
  name: <system>-<api>.<c>
  labels: L
  annotations: {argocd.argoproj.io/sync-wave: "3", argocd.argoproj.io/sync-options: "Delete=false,SkipDryRunOnMissingResource=true", argocd.argoproj.io/compare-options: IgnoreExtraneous}
spec: {streamName: <system>-<api>, durableName: <c>, deliverPolicy: all, ackPolicy: explicit, ackWait: 30s, maxDeliver: -1, account: <n>, preventDelete: true}
```

`kustomization.yaml`: `{apiVersion: kustomize.config.k8s.io/v1beta1, kind: Kustomization, resources: <sorted file names>}`.

Monitoring (AC-119.16): `http://<n>.<ns>.svc:8222/jsz?accounts=true&streams=true&consumers=true` lists per stream `state.messages` and
per consumer `num_pending` (not yet delivered) and `num_ack_pending` (delivered, not acknowledged). It is unauthenticated and
reachable only inside the cluster (ClusterIP).

## Contract: external broker instance (AC-119.17)

No addon directory, server, NACK object or operator. Per component with an instance in `<env>` that provides or consumes an API the
broker carries and is not an external component, an ExternalSecret `<n>-<c>-app` in that component's overlay, file
`externalsecret-<n>-<c>-app.yaml`, with 115's shape (labels `L`, `refreshInterval`, `secretStoreRef`, `target: {name, creationPolicy:
Orphan, deletionPolicy: Retain}`, one `data` entry per key `url`, `user`, `password`). Its store key is `remote.path` (instance's,
else resource's) with `{component}` = `<c>`, default `{system}-{env}-{resource}-{component}` (e.g. `shop-dev-bus-web`). A path without
`{component}` makes every component read one key (one shared user; the rights are then the broker owner's business). 115's single
`<system>-<name>-app` ExternalSecret is never rendered for a broker. The component gets the same variables as in-cluster.

## Contract: render notes (AC-119.6, AC-119.14, AC-119.17)

Printed on stdout, in this order, before the final `rendered (…)` / `OK: up to date` line, in write mode and with `--check`:

1. Unbound events APIs (system order, then `apis:` order):
   `note: applications/<system>: events API <api> is carried by no broker yet: add one with /resource:add <name> --type broker`
2. External broker instances (resource order, then `ENVS` order, then `apis:` order), one line per stream:
   `note: applications/<system>: broker <name> is external in <env>: create stream <system>-<api> (subjects <system>.<api>.>, file storage, max age 7d)[ with the durable consumers <c1>, <c2> (pull, explicit ack, ack wait 30s)]; the platform creates none on an external broker`
   (the bracketed part only when a consumer has an instance in `<env>`).
3. Streams and consumers whose files a render removes (paths sorted; read from the stale file before it is deleted, also inside a whole
   stale broker directory):
   `note: applications/<system>/addons/<env>/<name>: stream <spec.name> is no longer declared; it and its messages stay on the broker until you delete them`
   `note: applications/<system>/addons/<env>/<name>: durable consumer <spec.durableName> of stream <spec.streamName> is no longer declared; it stays on the broker until you delete it`

`stale_paths` removes, inside a broker directory that is still wanted, every file it no longer renders whose name matches
`^(stream-.+|consumer-.+|externalsecret-.+)\.yaml$` (database files and `restore-state.yaml` keep 117's rules).

## Contract: versions table (AC-119.20, AC-119.22)

```python
NATS_CHART = {"repo_url": "https://nats-io.github.io/k8s/helm/charts", "chart": "nats", "chart_version": "2.15.1"}
NATS_IMAGES = {                    # matches ^nats:\d+\.\d+\.\d+-alpine(@sha256:[0-9a-f]{64})?$; no bare minor, no latest
    "2.14": "nats:2.14.9-alpine",
    "2.15": "nats:2.15.2-alpine",
}
BROKER_VERSIONS = ("2.14", "2.15")  # default "2.15"
BROKER_DEFAULT_RESOURCES = {"requests": {"cpu": "100m", "memory": "256Mi"}, "limits": {"memory": "512Mi"}}
OPERATORS["nack"] = {"repo_url": "https://nats-io.github.io/k8s/helm/charts", "chart": "nack", "chart_version": "0.35.0",
                     "operator_version": "0.24.0", "namespace": "nack", "release": "nack", "crd": "streams.jetstream.nats.io"}
OPERATOR_OF_TYPE = {"database": "cloudnative-pg", "bucket": "seaweedfs", "broker": "nack"}
```

`nack` is appended last to `OPERATORS` (after `velero`). Its application is 058/125's `operator_application("nack", server)` without
`values`: the chart then passes `-crd-connect` to the controller. The doctor selector is the default `app.kubernetes.io/name=nack`
(the chart's Deployment `nack`, image `natsio/jetstream-controller:0.24.0`). `NATS_CHART` is not an operator (it is per broker
instance, never in `operators/` or `cluster.yaml`). The config reloader image (`natsio/nats-server-config-reloader:0.24.0`) is pinned by
the chart pin. Changing any of these follows spec 121.

**Verified on 2026-10-27, re-verify at build:** the Helm index `https://nats-io.github.io/k8s/helm/charts/index.yaml` (only its first
100,000 characters could be read; entries are newest first): `nats` 2.15.1 (appVersion 2.15.1, created 2026-10-13T06:38:45Z, digest
`b209c62784b1b24c714d5ff6503b4c7dd948ec187d4222beee16b579f1258cc1`) is the newest chart; the 1.x line ended with 1.3.16 (2025-10-24).
`nack` 0.35.0 (appVersion 0.24.0, created 2026-08-19T13:52:48Z, digest `54d4760ea03ed3fbcc567bc1f655b17102bb420867a295a5b1752ba88844492c`)
is the newest chart. Docker Hub `library/nats` tags (ordered by `last_updated`): `2.15.2-alpine` (pushed 2026-10-27T16:58Z, index digest
`sha256:40861340fe033e5ade564f7449bae1e805021b2f2038e6a324de80f39c786bc1`; `2.15-alpine` moved the same minute), `2.14.9-alpine`
(2026-10-27T16:57Z, `sha256:61d5fed1f6f9fe64673fb660e2f2504007e8035cc63bb71ea1a22f9621932585`); the chart's own default is
`2.15.1-alpine`; no 2.13 or older line was pushed in the pages read. `natsio/jetstream-controller:0.24.0` (2026-08-18,
`sha256:58862daca582c990dcc7d3ca4449d2d9b194dc24e3359a9c3ca6a3320cddc77d`); `0.25.0` exists (2026-10-21) but no `nack` chart ships it yet.
Read from the charts at their tags (`nats-2.15.1`, `nack-0.35.0`): every values key used above (`nameOverride`, `fullnameOverride`,
`global.labels`, `config.cluster`, `config.jetstream.fileStore.pvc.size`, `config.monitor`, `config.merge` with `<< >>` literals,
`container.image`, `container.env` with map values rendered as `valueFrom`, `container.merge`, `reloader.merge`, `podTemplate.merge`,
`service.ports.monitor.enabled` default false, `natsBox.enabled` default true, PDB enabled by default, default names `<n>`,
`<n>-headless`, `<n>-config`, PVC `<n>-js`); NACK's Deployment template (no `jetstream.nats.url` → `-crd-connect`; name and
`app.kubernetes.io/name` = `nack`); NACK v0.24.0's CRDs (`Stream`: `name`, `subjects`, `storage`, `replicas`, `retention`, `discard`,
`maxAge`, `account`, `preventDelete`; `Consumer`: `streamName`, `durableName`, `deliverPolicy`, `ackPolicy`, `ackWait` (default `1ns`,
so it must be set), `maxDeliver`, `account`, `preventDelete`; `Account`: `servers`, `user: {secret: {name}, user, password}`); the legacy
controller reads `Account.user` with `-crd-connect` and skips deleting a stream with `preventDelete`. `nats-py` 2.16.0 (PyPI,
2026-09-16): `connect(user=, password=, inbox_prefix=)`; `pull_subscribe_bind` makes no JetStream API call; `fetch` publishes to
`$JS.API.CONSUMER.MSG.NEXT.<stream>.<consumer>` with a reply on the connection's inbox prefix; `js.publish` is a request on it.

## Contract: `cplat resource` (AC-119.4, AC-119.17)

`cplat resource add <name> --type broker [--version V] [--replicas N] [--external [--path P]]`. `PLANNED_TYPES = {}`; `TYPE_KEYS["broker"]
= "url, user, password"`; `BROKER_VERSIONS = ("2.14", "2.15")` (mirrors render.py). Help texts: `--type` `resource type: database,
bucket, cache or broker`; `--version` `database major (15, 16, 17, 18) or broker version (2.14, 2.15)`; `--replicas` (new) `broker
replicas: 1 or 3 (default 1)`; `--path` `secret store key template for --external ({system}, {env}, {resource}; a broker also {component})`.
Checks in 115–118's order, with these changes and additions:

| Case | Text |
|---|---|
| `--version` with bucket or cache (replaces 115's text) | `--version applies to --type database or broker only` |
| `--replicas` with any other type | `--replicas applies to --type broker only` |
| `--replicas` with `--external` | `an external resource runs nothing: --replicas does not apply` |
| broker `--version` not supported | `version '<v>' is not a supported broker version (2.14, 2.15)` |
| `--replicas` not 1 or 3 | `--replicas must be 1 or 3: a broker runs with 1 or 3 replicas` |

Entries written: in-cluster `{type: broker}` plus `version: "<V>"` (a string) and `replicas: <N>` when given; external `{type: broker,
external: true}` (+ `remote: {path: P}`).

Next steps after adding a broker (instead of 115's `let components use it` line):
`bind events APIs to it: an events API uses the system's only broker, or set apis.<api>.broker: <name>; its provider and consumers then get NATS_URL, NATS_USER, NATS_PASSWORD and EVENTS_<API>_* (no uses: needed)`, then either
`the platform installs the NACK controller through operators/ (apply operators/root.yaml once per cluster: KUBE_CONTEXT=<ctx> devbox run bootstrap); environments with operators: owner need it installed by their owner` (in-cluster) or
`put the keys url, user, password in the secret store <store> under <dev key>, <staging key>, <prod key>` (keys formatted with
`{component}` → `<component>`, e.g. `shop-dev-bus-<component>`) followed by
`create on the external broker the streams and durable consumers that devbox run render prints (the platform creates none there)` (external).

`remove` (AC-119.4), first, before 115's `still used by` check: the events APIs bound to it (`broker: <name>`, or no `broker:` while it is
the system's only broker), in `apis:` order: `<name> carries the events APIs <a1>, <a2>`, hint `bind them to another broker
(apis.<api>.broker) or remove them first`; nothing is written. `will_do` lines:

- in-cluster instances: `remove <n> from system.yaml; the Argo Application disappears but the broker, its volumes, streams, consumers and Secrets <system>-<n>-<component>-app stay in the cluster (delete them by hand when you are sure)`
- external instances: `remove <n> from system.yaml; the synced Secrets <system>-<n>-<component>-app stay in the cluster (delete them by hand when you are sure); the external broker is not touched`

## Contract: model, `/api:list`, status, doctor (AC-119.15, AC-119.17, AC-119.22, AC-119.23)

- **Model** (`build`, lenient): `Api` gains `broker: str | None` (explicit `broker:` if it names a broker resource, else the only broker,
  else `None`; always `None` for non-events APIs). A component's `uses` is the effective list of the renderer (declared non-broker
  resources, then its bound brokers), so `resources[].used_by`, `relations` (`uses`) and the resource instances include implicit users.
  A broker resource instance: `secret` `None`; `sizing` `{"version": <str, default "2.15">, "replicas": <int, default 1>, "storage":
  <default "1Gi">}` in-cluster, `{}` external; `store_key` as 115 with `{component}` kept; new field `broker`:
  `{"address": "nats://<n>.<ns>.svc:4222" | None, "monitoring": "http://<n>.<ns>.svc:8222" | None, "users": [{"component", "secret":
  "<n>-<c>-app", "store_key": <key with the component> | None}], "streams": [{"api", "stream": "<system>-<api>", "subjects":
  "<system>.<api>.>", "subject_prefix": "<system>.<api>", "consumers": [{"name": <c>, "component": <c>}]}]}` (`None`s when external;
  users and consumers only for components with an instance in that environment). JSON: schema 2; `resource_instances[]` gets the key
  `broker` only for brokers, `apis[]` the key `broker` only for events APIs; nothing else changes.
- **`cplat model show`**: an events API line ends with `  broker <b>` when bound. A broker instance line prints `secret -` and is followed
  by `      address <address|->  monitoring <monitoring|->`, `      users <c1> (<secret>), <c2> (<secret>)` (or `-`) and per stream
  `      stream <stream>  subjects <subjects>  consumers <c1>,<c2>|-`.
- **`/api:list`**: text lines of bound events APIs end with `  broker <b>`; other lines are unchanged (114's tests). `--json`: events APIs
  carry `"broker": <b> | null`; other APIs are unchanged.
- **Status**: no change; a broker is a row of the resource table with its `addon-<name>-<env>` state (`external` where external).
- **Doctor**: `check_operators` gains `("nack", "nack")` (needs: the environments with an in-cluster broker instance), so `operator nack`
  follows 115's texts, including `operators: owner` (`install the nack chart 0.35.0 (operator 0.24.0)`). New `check_brokers` after it,
  only with `kubectl`, one row per in-cluster broker instance, named `broker <name> (<env>)` (`<system>/<name>` with several systems):
  it reads `kubectl -n <ns> get statefulsets.apps <n> -o jsonpath='{.metadata.labels.helm\.sh/chart} {.spec.template.spec.containers[?(@.name=="nats")].image}'`.
  - OK: `nats chart 2.15.1, server nats:2.15.2-alpine (expected)`
  - WARN, not found: `not running in the current kube context; expected nats chart 2.15.1, server nats:2.15.2-alpine`, fix `sync the Argo CD application <system>-<name>-<env>-nats (local: devbox run cluster-up)`
  - WARN, different: `nats chart <have>, server <have>; expected nats chart 2.15.1, server nats:2.15.2-alpine`, fix `sync the Argo CD application <system>-<name>-<env>-nats`
- **Cluster repos**: `check.py`'s `needs` adds `external-secrets` for an in-cluster broker (like a bucket); `nack` follows from
  `OPERATOR_OF_TYPE`. `bootstrap.sh` (gitops-app) maps `nack` to the CRD `streams.jetstream.nats.io`.

## Contract: local cluster (AC-119.19, AC-119.22)

`local-cluster.sh`: `NACK_VERSION` (default: the `targetRevision` of `operators/apps/nack.yaml`, else `0.35.0`); `WITH_NACK` (1, 0, default
1 exactly when `operators/apps/nack.yaml` exists). With Argo CD it comes from `operators/root.yaml` and `up` waits for
`streams.jetstream.nats.io` and `rollout status deploy/nack -n nack`; with `WITH_ARGO=0` a k3s `HelmChart` `nack` (namespace
`kube-system`, `targetNamespace: nack`, repo/chart/version of the table, no values). The script copy in `templates/cluster-gitops` stays
byte-equal.

## Contract: docs (AC-119.25)

`docs/DOMAIN-MODEL.md` gets a broker section with the environment contract and exactly one Python example (`nats-py`), which a provider
and a consumer each use half of:

```python
import asyncio, os
import nats

async def main():
    nc = await nats.connect(os.environ["NATS_URL"], user=os.environ["NATS_USER"], password=os.environ["NATS_PASSWORD"],
                            inbox_prefix=os.environ["NATS_INBOX_PREFIX"])
    js = nc.jetstream()
    # provider of the events API `orders`: publish under its subject prefix
    await js.publish(os.environ["EVENTS_ORDERS_SUBJECT_PREFIX"] + ".created", b'{"id": 42}')
    # consumer: read through the component's own durable consumer, acknowledge within 30 s
    sub = await js.pull_subscribe_bind(durable=os.environ["EVENTS_ORDERS_CONSUMER"], stream=os.environ["EVENTS_ORDERS_STREAM"])
    for msg in await sub.fetch(10, timeout=5):
        print(msg.subject, msg.data)
        await msg.ack()
    await nc.close()

asyncio.run(main())
```

No template ships publisher or subscriber code.

## Contract: e2e (AC-119.19, and the cluster halves of AC-119.4, .9 to .14, .16, .20 to .22)

After the cache steps and before "Write and approve a spec", in dev. Cluster-up gets `WITH_NACK=1` (the components use the broker only
after cluster-up, so `operators/apps/nack.yaml` does not exist yet then). The "Build and push" step also builds a probe image
`localhost:<regport>/e2e-natsprobe:1` (`python:3.13-slim` + `pip install nats-py==2.16.0`). A broker `bus` (1 replica), two events APIs:
`orders` (provided by e2e-api, consumed by e2e-web) and `audit` (provided by e2e-web, consumed by nobody: it makes e2e-api a non-member).
The component overlays are not applied: probe pods take their variables from the rendered Deployments (`kubectl kustomize`), so no
live workload ever depends on the broker. Checks: `operators/apps/nack.yaml` (chart 0.35.0) and the NACK Deployment's image tag 0.24.0;
the rendered files and variables; server, Secrets, `Account`, streams and the consumer ready; the Secret contract and `/jsz` (stream
subjects, 7 days, file storage; consumer explicit ack, 30 s); through probe pods with the components' variables, the docs example's
calls deliver one message within 30 s, a message published while no consumer runs arrives later, an acknowledged one never again;
`/jsz` pending and ack-pending counts; the refusals of AC-119.12; doctor's `operator nack` and `broker bus (dev)` rows; `/resource:remove`
refused while the APIs are bound; removing the APIs prints the three retired names while the stream and its messages stay; then the
e2e deletes the broker by hand (as a person would) so that the ship steps (e2e-api is promoted to staging) and spec 117's backup steps
run exactly as before. The broker steps take at most 5 minutes; NACK at cluster-up and the probe build add at most 1.5 minutes more.

## Risks

- **The NATS server as non-root with a read-only root filesystem** (UID 1000, `fsGroup` 1000) is not proven for the pinned image and
  the reloader's signal across containers (same UID, the chart's shared process namespace). The e2e run proves it; if it fails, the build
  drops `runAsUser`/`runAsGroup` for the reloader first, then the read-only root filesystem of the server, and updates this section.
- **Restart on a new user**: a new component user is a new container variable, so the broker pods roll (1 replica: a short outage that
  clients ride out by reconnecting; JetStream keeps the data on its volume). Rights-only changes are hot-reloaded by the reloader.
- **The ack subject format**: both forms are allowed; if the pinned server uses yet another form, the e2e's acknowledgement check fails
  and the publish list changes in the same PR.
- **NACK legacy mode** reconciles on change, not continuously: a stream deleted by hand on the server is recreated only when its object
  changes or NACK restarts. Documented.
- **Replicas 1 → 3** switches the server from standalone to clustered JetStream; NATS supports raising stream replicas, but the switch is
  not exercised by the e2e (a laptop cluster). Documented with the advice to start prod with 3. `storage` changes stop at the
  immutable `volumeClaimTemplates` (one documented `kubectl delete statefulsets.apps <n> -n <ns> --cascade=orphan`).
- **A live file-system backup of JetStream** may catch a block mid-write; NATS truncates a torn tail block on start. Spec 117 accepted
  this; documented. The e2e does not back up or restore a broker volume (the render tests prove the labels and the Schedule).
- **kubeconform** (gitops-app `validate`) checks the `jetstream.nats.io` objects against the Datree catalog with `-strict`; if the
  catalog lags NACK v0.24.0, the build adds the three kinds to the skip list and says so in the CHANGELOG.
- **The NATS 2.14 line with chart 2.15.1** is not exercised by the e2e (it runs 2.15); the render tests pin the image only.
- **Downgrades** (`"2.15"` → `"2.14"`) are not refused before spec 121. Documented next to `version`.

## Decisions taken by default

1. **An events API in a system without any broker stays unbound and only gets a render note** (AC-119.6's "with no broker the render
   fails" is not built). AC-119.24 and the Problem section require a 5.0 `system.yaml` to render byte-identically, and 5.0 systems may
   declare events APIs (spec 114; `tests/cplat/test_system_render_114.py` line 421 and `tests/cplat/test_compose_apis.py` lines 34, 40
   and 45 render or write them); failing them would be a breaking change in a minor release. Alternative: fail as AC-119.6 says (then
   those tests and every 5.0 repo with an events API break, and the release is BREAKING). **Needs a changelog line in spec.md.**
2. **The NATS server is a nested Argo CD `Application` (the official chart) inside the broker's addon directory.** Alternative: a
   separate ApplicationSet with Helm sources (cannot carry per-instance values) or rendering the chart's output into git (not "from the
   official chart").
3. **NACK runs in its default legacy mode with `-crd-connect` and one `Account` per broker instance.** Alternative: `--control-loop`
   (marked experimental in NACK 0.24.0).
4. **Per-component inbox prefix `_INBOX.<component>` and the extra variable `NATS_INBOX_PREFIX`.** Alternative: allow `_INBOX.>` to
   everybody (any component could read what another fetches).
5. **Passwords reach the server as container variables referenced from its config.** Alternative: one auth file assembled by ESO from
   all Secrets (needs a cluster-side secret store per namespace).
6. **NACK's own admin user `_nack` with Secret `<n>-nack`.** Alternative: one of the components' users (would need full rights).
7. **`version` is the NATS minor line as a string (`"2.14"`, `"2.15"`, default `"2.15"`), a YAML float is read as its text.**
   Alternative: the major `2` (no granularity for spec 121's downgrade rule).
8. **Default resources: requests 100m CPU and 256Mi, memory limit 512Mi** (a database's defaults).
9. **Pull consumers, deliver `all`, unlimited redeliveries, replicas inherited from the stream.** Alternative: push consumers (need a
   deliver subject per component and more rights).
10. **Streams: file storage, `limits` retention, discard old, `maxAge: 168h`, replicas = broker replicas, no size limit beyond the
    volume.**
11. **Removed streams and consumers stay through `preventDelete`, `Delete=false` and `IgnoreExtraneous`; the note is printed by the
    render that removes their files** (a render cannot see the cluster). Alternative: keep a record in git and print on every render.
12. **External broker store key `{system}-{env}-{resource}-{component}` with the `{component}` placeholder; keys `url`, `user`,
    `password`.** Alternative: one shared key per environment (no per-component users).
13. **External components (spec 069) count on the broker side (user, Secret, consumer) but get no injected variables, and no
    ExternalSecret on an external broker** (115's rule for external components). Alternative: leave them out entirely (their consumers
    would be missing, against AC-119.10).
14. **A component's broker variables follow its declared resources' variables, whatever its `uses` says**, so listing a broker changes
    nothing (AC-119.7).
15. **`EVENTS_*` and `NATS_INBOX_PREFIX` are literal values in the sorted literal block.** Alternative: keys of the Secret (the external
    store would have to hold them).
16. **The NATS pods are hardened although no guard rail matches them; `natsBox` is disabled.**
17. **The monitoring port 8222 is on the ClusterIP Service, unauthenticated.** Alternative: a separate Service or basic auth (KEDA's NATS
    scaler of spec 120 reads it without credentials).
18. **Broker data is in the environment backup; `backup_files` does not change**; `nameOverride` keeps the name label consistent.
    Alternative: leave brokers out like caches (spec 119's non-goal says spec 117 includes them).
19. **`compose.py` does not change**: brokers come through APIs, `--uses` help stays as 118 left it.
20. **A bound events API needs a DNS-label name** (it becomes a stream name, a subject token and an object name).
21. **Both JetStream ack subject forms are allowed.**
22. **The config reloader stays on (chart default)** for rights-only changes.
23. **The addon ApplicationSet of an environment with a broker retries its sync** (115's `RETRY`).
24. **The e2e uses a second events API `audit`** to have a component that is not part of an API, and a probe image with `nats-py`
    2.16.0, because the probe must use what a component uses (the docs example), not the `nats` CLI.
25. **The e2e unbinds and deletes the broker after its steps**, so staging (where e2e-api is promoted) never needs a broker and spec 117's
    backup steps keep their time and assertions. Alternative: run a second broker in staging and back it up (several more minutes).
26. **Plugins: `resource` 1.5.0, `api` 1.1.0**; `platform` (doctor) does not change its commands.

**Re-verified at build (2026-10-28):** the full NATS Helm index gives nats 2.15.1 and nack 0.35.0 as the newest; `nats:2.15.2-alpine` and
`2.14.9-alpine` are still the newest tags per line (their digests changed on 2026-10-27, the tags did not); the nats chart's
`podTemplate.configChecksumAnnotation` defaults to `false` (rights changes hot-reload); the rendered Stream and Consumer documents
validate against the datreeio CRDs-catalog schemas `jetstream.nats.io/{stream,consumer}_v1beta2` that `devbox run validate` uses.
