# Design — 120 Instances scale on load and queue depth

Extends [spec 114's design](../114-the-platform-speaks-the-domain-model-5-0/design.md) (the closed key lists, `_eff` per instance, the
component ApplicationSet per environment), [spec 115's design](../115-resources-are-named-typed-and-may-be/design.md) (versions table,
`operators/`, `operators: owner`, doctor's operator rows), [spec 118's design](../118-a-cache-resource-compatible-with-redis/design.md)
(the cache Secret `<system>-<name>-app` with `url`, `host`, `port`, `password`), [spec 119's design](../119-a-message-broker-resource-behind-events/design.md)
(durable consumer `<c>` on stream `<system>-<api>`, the monitoring endpoint on 8222, `cfg["events"]`, the e2e broker steps) and
[spec 125's design](../125-a-cluster-repo-hosts-several-systems/design.md) (`OPERATORS` shared with cluster repos, `check.py needs`,
synced template copies). Decisions that outlive the spec: [ADR: instances scale with an HPA or KEDA](../../adr/066-instances-scale-with-an-hpa-or-keda-installed-per-cluster.md)
and [ADR: Argo CD leaves autoscaled replica counts alone](../../adr/067-argo-cd-leaves-autoscaled-replica-counts-alone.md) (if a parallel
session took these numbers before merge, rename both files, their two index rows and these links together).

Everything is additive: a `system.yaml` without `scale` renders byte for byte as before (AC-120.26), whatever resources and APIs it
declares. The only texts that change for such a system are the two "unknown key … (allowed: …)" lists, which gain `scale` at the end
(spec 124's precedent; amended test in plan t13).

## Decisions

- **`scale` is an Instance property** with a component-level default (AC-120.1 to AC-120.3): `components.<c>.scale` applies to every
  instance of `<c>` that has neither `scale` nor `replicas`; an instance `scale` replaces it as a whole; `scale` and `replicas` on one
  level fail. External components and libraries keep refusing it with their existing texts. ADR-066.
- **CPU and memory: a plain `autoscaling/v2` HorizontalPodAutoscaler `<c>`** in the component overlay (AC-120.6). **Queue triggers: a
  KEDA `ScaledObject` `<c>`** (AC-120.9 to AC-120.15), plus a `TriggerAuthentication` `<c>` for a cache. Exactly one autoscaler object
  per scaled instance.
- **Argo CD leaves the count alone** (AC-120.19, AC-120.20): a scaled Deployment renders `spec.replicas: <min>`; the environment's
  component ApplicationSet gets one `ignoreDifferences` entry per scaled Deployment (by name, `/spec/replicas`) and the sync option
  `RespectIgnoreDifferences=true`; KEDA objects sync in wave 1 and an environment with a KEDA instance retries. No `Replace`, no
  `PruneLast`. ADR-067.
- **KEDA is a platform operator** (`OPERATORS["keda"]`, chart 2.19.0): `operators/apps/keda.yaml` exists exactly when an environment
  without `operators: owner` derives `autoscaling: keda` (AC-120.16, AC-120.27); cluster repos list it and `check.py` requires it.
- **The metrics source is declared, not detected** (AC-120.17, AC-120.27): the gitops repo answer `resource_metrics` (`provided`, the
  default, or `install`); with `install`, `operators/apps/metrics-server.yaml` (chart 3.14.0) is rendered when an environment without
  `operators: owner` has a CPU or memory instance. Doctor shows whether the current cluster serves `metrics.k8s.io`.
- **The scaler reads what the instance reads** (AC-120.13): a cache trigger authenticates with `host`, `port`, `password` of
  `<system>-<r>-app` through a `TriggerAuthentication`; a broker trigger reads the unauthenticated monitoring endpoint of spec 119
  (decision 17 there) and needs no credentials, so no `TriggerAuthentication` is rendered for it. No credential value is rendered.
- **An external broker cannot be a trigger** (AC-120.9): its monitoring endpoint is not part of spec 119's external contract (`url`,
  `user`, `password`). The render fails for that instance with the reason.
- **Timings are constants** (AC-120.10, AC-120.12, AC-120.14, AC-120.15, AC-120.23): `pollingInterval: 15`, `cooldownPeriod: 315`,
  scale-down stabilization 345 s (100 % per 15 s), scale-up Kubernetes' default (stabilization 0, up to +100 % or +4 pods per 15 s).
  See "Timings".

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `templates/gitops-app/scripts/render.py` (+ its copy `templates/cluster-gitops/scripts/system_render.py`) | `scale` schema and checks, effective scale per instance, `cfg["autoscaling"]`, scaled Deployments, `hpa.yaml`, `scaledobject.yaml`, `triggerauthentication.yaml`, the environment ApplicationSet's ignore rules, `OPERATORS["keda"]`, `OPERATORS["metrics-server"]`, `operator_files`, docstring | changed |
| `templates/gitops-app/scripts/local-cluster.sh` (+ copy) | `WITH_KEDA`/`KEDA_VERSION`, `WITH_METRICS_SERVER`/`METRICS_SERVER_VERSION`, the metrics wait | changed |
| `templates/gitops-app/scripts/bootstrap.sh` | waits for `scaledobjects.keda.sh` after `operators/apps/keda.yaml` | changed |
| `templates/gitops-app/copier.yml` | the question `resource_metrics` | changed |
| `templates/cluster-gitops/scripts/check.py`, `templates/cluster-gitops/scripts/render.py` | `needs` adds `keda`; `--crds` skips an operator without a CRD | changed |
| `scripts/cplat/model.py` | `Instance.scale`, `replicas: None` when scaled, `Environment.autoscaling`, JSON | changed |
| `scripts/cplat/modelcmd.py` | the `scale` and `autoscaling` texts | changed |
| `scripts/cplat/status.py` | the replica count and bounds of a scaled instance | changed |
| `scripts/cplat/compose.py` | `component set --replicas` refused on a scaled instance or component | changed |
| `scripts/cplat/doctor.py` | rows `operator keda` (with the queue-triggered instances), `operator metrics-server`, `resource metrics` | changed |
| `envrestore.py`, `addon.py`, `apilist.py`, `promote.py`, Kyverno policy, Velero Schedule | nothing | unchanged |

## Contract: `system.yaml`

```yaml
components:
  worker:
    type: service
    # ... image, port, probes, resources ...
    consumes: [jobs]
    uses: [sessions]
    scale: {min: 1, max: 5, on: {consumes: jobs, lag: 10}}      # default of every instance without scale or replicas
    instances:
      dev: {scale: {min: 0, max: 3, on: {cache: sessions, list: jobs, length: 10}}}   # replaces the component's scale as a whole
      staging: {}                                                                    # gets the component's scale
      prod: {replicas: 2}                                                            # a fixed count, no autoscaler
  api:
    type: service
    resources: {requests: {cpu: 100m, memory: 128Mi}, limits: {memory: 256Mi}}
    instances:
      prod: {scale: {max: 10, on: {cpu: 70}}}                                        # min defaults to 1
```

| Where | Allowed keys |
|---|---|
| service or website `components.<c>` | 114's list, then `scale` (last) |
| `components.<c>.instances.<env>` (not external) | `replicas`, `resources`, `env`, `promote`, `secrets`, `autonomy`, `scale` |
| `scale` | `min` (0 to `max`, default 1), `max` (1 to 20, required), `on` (required) |
| `on` | exactly one of `{cpu: <1..100>}`, `{memory: <1..100>}`, `{consumes: <api>, lag: <n ≥ 1>}`, `{cache: <resource>, list: <non-empty string>, length: <n ≥ 1>}` |

Integers are YAML integers; a boolean is never an integer. `scale: null` is not a mapping. An external component keeps 069's text
(`components.<c> is external: scale belongs in its package, not in system.yaml`), its instances keep `(allowed: promote, autonomy)`;
a library keeps 114's unknown-key text. `environments.<env>.autoscaling` stays an unknown environment key (AC-120.16).

Effective scale of an instance `<c>/<env>`: the instance's `scale` if it has the key; otherwise none if it has `replicas`; otherwise the
component's `scale` (if any). A scaled instance has no effective `replicas`.

### Render errors (exit 1, nothing written, each after `applications/<dir>/system.yaml: `)

`ON_FORMS` = `{cpu: <percent>}, {memory: <percent>}, {consumes: <api>, lag: <n>} or {cache: <resource>, list: <key>, length: <n>}`.
`<at>` = `components.<c>` or `components.<c>.instances.<env>`; `<where>` = `<at>.scale`.

Structural checks run while the component is read (`validate_component`, `validate_instances`): the component level after 114's checks
of the component (unknown keys, missing image/port/probes, secrets, env) and before its instances; each instance after its unknown-key,
`promote` and `autonomy` checks and before its `replicas` check. Per level, in this order (AC-120.1, AC-120.3, AC-120.4, AC-120.6, AC-120.8):

| Case | Text |
|---|---|
| `scale` and `replicas` on one level | `<at>: scale and replicas exclude each other; remove one (replicas is a fixed number, scale lets the autoscaler choose between min and max)` |
| not a mapping | `<where> must be a mapping with min, max and on, e.g. {min: 1, max: 5, on: {cpu: 70}}` |
| unknown key (first in order) | `<where>: unknown key '<k>' (allowed: min, max, on)` |
| no `max` | `<where>: max is required: an integer from 1 to 20` |
| `max` not an integer 1..20 | `<where>.max must be an integer from 1 to 20, got <v>` |
| `min` not an integer 0..max | `<where>.min must be an integer from 0 to max (<max>), got <v>` |
| no `on` | `<where>.on is required: exactly one of ON_FORMS` |
| `on` not a mapping, empty, an unknown key, two triggers, a queue trigger without its number | `<where>.on must be exactly one of ON_FORMS, got <got>` |
| `cpu`/`memory` not an integer 1..100 | `<where>.on.cpu must be an integer from 1 to 100 (percent of the CPU request), got <v>` / `<where>.on.memory must be an integer from 1 to 100 (percent of the memory request), got <v>` |
| `lag` | `<where>.on.lag must be an integer of at least 1, got <v>` |
| `list` | `<where>.on.list must be a non-empty string: the key of the list in the cache, got <v>` |
| `length` | `<where>.on.length must be an integer of at least 1, got <v>` |
| `min: 0` with `cpu`/`memory` | `<where>: scale to zero (min: 0) needs a queue trigger (consumes or cache); a cpu trigger has nothing to measure at zero replicas` (`memory` likewise) |

`<got>`: `{k1, k2}` with the keys in the given order (`{}` when empty) for a mapping, else the value as YAML prints it. The form is
decided by the key set alone: `{cpu}`, `{memory}`, `{consumes, lag}`, `{cache, list, length}`; the value checks follow in key order of
the form. `<v>` is the value as given (`True`, `0`, `'x'` printed with Python's `str`).

Reference and effective checks (`validate_scaling`, after `validate_uses`, before `validate_backups`). Components in `components:` order;
per component its declared `scale`s (the component's first, then its instances' in their order), then its instances in ENVS order with
their effective scale (AC-120.7, AC-120.9, AC-120.11, AC-120.28):

| Case | Text |
|---|---|
| `consumes: <api>` not in the component's `consumes` | `<where>.on.consumes: <c> does not consume '<api>' (consumes: <a1>, <a2> \| none)` |
| `<api>` not of type `events` | `<where>.on.consumes: '<api>' is a <type> API; only an events API carried by a broker has a queue to scale on` |
| `<api>` bound to no broker (`cfg["events"][api]["broker"] is None`) | `<where>.on.consumes: the events API '<api>' is carried by no broker; add one with /resource:add <name> --type broker` |
| `cache: <r>` not a cache resource | `<where>.on.cache: '<r>' is not a cache resource of the system (caches: <r1>, <r2> \| none)` |
| `<r>` not in the component's declared `uses` | `<where>.on.cache: <c> does not use the cache '<r>'; add it to components.<c>.uses` |
| `min: 0` on a component with `expose` or providing an `openapi`/`grpc`/`graphql` API | `<where>: min 0 is not possible for <c>: an instance at zero replicas cannot answer requests (<what>)` |
| per instance, CPU (memory) trigger without `resources.requests.cpu` (`.memory`) in the effective `resources` | `components.<c>.instances.<env>: scale on cpu needs a CPU request; set resources.requests.cpu on components.<c> or on this instance` (memory: `a memory request; set resources.requests.memory …`) |
| per instance, `consumes` whose broker is external in `<env>` | `components.<c>.instances.<env>: scale on consumes '<api>' needs the broker <b> in the cluster, but it is external in <env>; the platform cannot read the queue depth of an external broker` |

`<what>`: `exposed at host <h>` (`<h>` = `expose.host` when `expose` is a mapping with `host`, else the component name), then
`provides <a> (<type>), <b> (<type>)` for its request APIs in `provides` order, joined by `; `. The effective `resources` are 114's: the
instance's `resources` replace the component's (no merge), exactly what the Deployment gets.

### Renderer API

`svc["_eff"][env]["scale"]` (every non-external component; `None` when unscaled):
`{"min": int, "max": int, "trigger": "cpu" | "memory" | "consumes" | "cache", "on": {…as declared, ints as int…}, "source": "component" | "instance"}`.
A scaled instance has no `replicas` key in `_eff[env]`.

`cfg["autoscaling"]`: `{env: "keda" | None}` for `dev`, `staging`, `prod`: `"keda"` when a running instance there has a `consumes` or
`cache` trigger. `scaled_instances(services, env) -> list[str]`: the non-external components running in `env` with an effective scale, in
`components:` order. Both are what `operator_files`, `check.py`, the model agreement tests and doctor read.

## Contract: rendered documents

`<c>` component, `<env>`, `<app>` system, `<ns>` = `<app>-<env>`, `L` = `labels_for(app, svc)` (`app`, `app.kubernetes.io/name`,
`app.kubernetes.io/part-of`, `app.kubernetes.io/managed-by`), fresh dicts. Key order as written.

**Deployment** of a scaled instance: unchanged except `spec.replicas: <min>`.

**`hpa.yaml`** (trigger `cpu` or `memory`; AC-120.6):

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata: {name: <c>, labels: L}
spec:
  scaleTargetRef: {apiVersion: apps/v1, kind: Deployment, name: <c>}
  minReplicas: <min>
  maxReplicas: <max>
  metrics:
    - type: Resource
      resource: {name: cpu | memory, target: {type: Utilization, averageUtilization: <percent>}}
```

**`scaledobject.yaml`** (trigger `consumes` or `cache`):

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: <c>
  labels: L
  annotations: {argocd.argoproj.io/sync-wave: "1", argocd.argoproj.io/sync-options: SkipDryRunOnMissingResource=true}
spec:
  scaleTargetRef: {apiVersion: apps/v1, kind: Deployment, name: <c>}
  pollingInterval: 15
  cooldownPeriod: 315
  minReplicaCount: <min>
  maxReplicaCount: <max>
  advanced:
    horizontalPodAutoscalerConfig:
      behavior:
        scaleDown:
          stabilizationWindowSeconds: 345
          policies: [{type: Percent, value: 100, periodSeconds: 15}]
  triggers: [<trigger>]
```

`consumes` trigger (`<b>` the broker carrying `<api>`; AC-120.9, AC-120.10, AC-120.13, AC-120.14):

```yaml
- type: nats-jetstream
  metadata:
    natsServerMonitoringEndpoint: <app>-<b>.<ns>.svc:8222
    account: $G
    stream: <app>-<api>
    consumer: <c>
    lagThreshold: "<lag>"
    activationLagThreshold: "0"
    useHttps: "false"
```

`cache` trigger (AC-120.11 to AC-120.14):

```yaml
- type: redis
  metadata: {listName: <list>, listLength: "<length>", activationListLength: "0", databaseIndex: "0"}
  authenticationRef: {name: <c>, kind: TriggerAuthentication}
```

**`triggerauthentication.yaml`** (cache trigger only; in-cluster and external cache alike, the Secret is the one the instance reads):

```yaml
apiVersion: keda.sh/v1alpha1
kind: TriggerAuthentication
metadata:
  name: <c>
  labels: L
  annotations: {argocd.argoproj.io/sync-options: SkipDryRunOnMissingResource=true}
spec:
  secretTargetRef:
    - {parameter: host, name: <app>-<r>-app, key: host}
    - {parameter: port, name: <app>-<r>-app, key: port}
    - {parameter: password, name: <app>-<r>-app, key: password}
```

`$G` is NATS' global account, where spec 119's `authorization.users` live. KEDA's lag is `num_pending + num_ack_pending` of the durable
consumer (verified in the scaler's source); "N pending messages" in the spec means that sum. Metadata values are strings (KEDA's CRD
types `metadata` as `map[string]string`).

The overlay `kustomization.yaml` lists these files with the others (`sorted(files)`). `MANAGED_FILES` gains `hpa.yaml`,
`scaledobject.yaml` and `triggerauthentication.yaml`, so a render that drops `scale` (or switches HPA ↔ KEDA) deletes the stale file
(AC-120.20).

**Environment ApplicationSet** `<app>-<env>`, only when `scaled_instances(services, env)` is not empty (AC-120.19):

```yaml
      spec:
        project: default
        source: {…unchanged…}
        destination: {…unchanged…}
        syncPolicy:
          automated: {prune: true, selfHeal: true}
          syncOptions: [CreateNamespace=true, RespectIgnoreDifferences=true]
          retry: RETRY                                    # only when cfg["autoscaling"][env] == "keda"
        ignoreDifferences:
          - {group: apps, kind: Deployment, name: <c1>, jsonPointers: [/spec/replicas]}   # per scaled instance, components: order
```

The entries apply to every application of the set; each application holds one Deployment named after its component, so an entry only
ever matches its own component.

## Contract: versions table and operators (AC-120.25, AC-120.27)

```python
OPERATORS["keda"] = {"repo_url": "https://kedacore.github.io/charts", "chart": "keda", "chart_version": "2.19.0",
                     "operator_version": "2.19.0", "namespace": "keda", "release": "keda", "crd": "scaledobjects.keda.sh",
                     "selector": "app.kubernetes.io/name=keda-operator"}
OPERATORS["metrics-server"] = {"repo_url": "https://kubernetes-sigs.github.io/metrics-server", "chart": "metrics-server",
                               "chart_version": "3.14.0", "operator_version": "0.9.0", "namespace": "kube-system",
                               "release": "metrics-server", "crd": None, "selector": "app.kubernetes.io/name=metrics-server"}
```

Appended in this order after `nack`. Both render with 058/125's `operator_application(name, server)` without values.
`OPERATOR_OF_TYPE` does not change. `operator_files` adds `keda` when some environment not in `cfg["operators"]` has
`cfg["autoscaling"][env] == "keda"`, and `metrics-server` when `ans.get("resource_metrics", "provided") == "install"` and some environment
not in `cfg["operators"]` has a running instance with a `cpu` or `memory` trigger. One file per repo = one application per cluster.

**Verified on 2026-10-28, re-verify at build:**
- KEDA Helm index `https://kedacore.github.io/charts/index.yaml`, read completely (ends with `generated: "2026-09-23T16:59:21.474824372Z"`;
  entries `keda`, `keda-add-ons-http`, `external-scaler-azure-cosmos-db`; 79 `keda` entries): newest `keda` 2.21.0 (appVersion 2.21.0, created
  2026-09-23T16:59:21Z, digest `a7da56bf41a33dad9d2fc82a6fdecee552fff947d80bf1e1dbcf4db0f9e26dee`); then 2.20.2 (2026-07-31), 2.20.1, 2.20.0,
  **2.19.0 (appVersion 2.19.0, digest `6ee0edbb604577aaa2db07a4eecd836c69e1b1266f2db88a55010870faaad34b`; index entry re-created
  2026-06-15, GitHub release v2.19.0 on 2026-02-02)**. KEDA's compatibility table (keda.sh/docs/2.21/operate/cluster): v2.21 tested on
  Kubernetes 1.34–1.36, v2.20 on 1.33–1.35, v2.19 on 1.32–1.34; the local cluster and the e2e run k3s v1.32.5 (`K3S_IMAGE` default), hence
  2.19.0 (decision 1). v2.21.0's release notes list three breaking changes (Vault/bound service-account tokens, Temporal, Azure Pipelines),
  none in the scalers used here; v2.19.0's only breaking change removes the NATS Streaming (Stan) scaler, not `nats-jetstream`.
- Chart `keda` at tag `v2.19.0` (`github.com/kedacore/charts`): `templates/manager/deployment.yaml` names the Deployment
  `{{ .Values.operator.name }}` = `keda-operator` with labels `app`, `name`, `app.kubernetes.io/name` = `keda-operator` (hence the
  `selector`; the default `app.kubernetes.io/name=keda` would match nothing) and image
  `<registry>/<image.keda.repository>:<tag | default .Chart.AppVersion>` = `ghcr.io/kedacore/keda:2.19.0`; `templates/metrics-server/deployment.yaml`
  names `keda-operator-metrics-apiserver` (image `ghcr.io/kedacore/keda-metrics-apiserver:2.19.0`); `templates/webhooks/deployment.yaml`
  names `keda-admission-webhooks` (on by default; image `ghcr.io/kedacore/keda-admission-webhooks:2.19.0`). `values.yaml`: `crds.install:
  true`, `webhooks.enabled: true`, `operator.name: keda-operator`, image tags empty (= appVersion), containers non-root with read-only
  root filesystems and `drop: [ALL]`. CRDs in `templates/crds/`: `cloudeventsources`, `clustercloudeventsources`,
  `clustertriggerauthentications`, `scaledjobs`, `scaledobjects`, `triggerauthentications` (`.keda.sh`), only `v1alpha1` served.
  `ScaledObject` (v2.21.0's CRD, same fields used): `scaleTargetRef.name` required, `pollingInterval`, `cooldownPeriod`, `minReplicaCount`
  (≥ 0), `maxReplicaCount` (≥ 1), `advanced.horizontalPodAutoscalerConfig.behavior`, `triggers` (≥ 1; `type`, `metadata` map of strings,
  `authenticationRef {name, kind}`); `TriggerAuthentication.spec.secretTargetRef[]` with required `parameter`, `name`, `key` (v2.19.0).
- Scalers at `kedacore/keda` tag `v2.19.0` (and unchanged in v2.21.0): `nats_jetstream_scaler.go` reads `natsServerMonitoringEndpoint`
  and `account` from authParams or metadata, `stream`, `consumer`, `lagThreshold` (default 10), `activationLagThreshold` (default 0),
  `useHttps`; lag = `NumPending + NumAckPending`; active when lag > activation; a missing consumer falls back to the stream's last
  sequence; with a clustered server it finds the consumer leader through `/varz`. `redis_scaler.go` reads `address`/`host`/`port`/
  `username`/`password` from metadata, the environment or authParams, `listName`, `listLength` (default 5), `activationListLength`,
  `databaseIndex`; length via `LLEN` in a Lua `EVAL`.
- metrics-server Helm index `https://kubernetes-sigs.github.io/metrics-server/index.yaml`, read completely (`generated:
  "2026-08-19T11:35:24.161461547Z"`, 17 entries): newest `metrics-server` 3.14.0 (appVersion 0.9.0, created 2026-08-19T11:35:24Z, digest
  `c2ca1185c01e6e7f53dd1b7d131f0c9b3fa50e003ed068b784563a1b5a3422a1`). Chart 3.14.0: selector labels `app.kubernetes.io/name:
  metrics-server` and `app.kubernetes.io/instance: <release>`, image `registry.k8s.io/metrics-server/metrics-server:v0.9.0` (tag default
  `v<appVersion>`), `apiService.create: true`, default args `--cert-dir=/tmp`, `--kubelet-preferred-address-types=InternalIP,ExternalIP,Hostname`,
  `--kubelet-use-node-status-port`, `--metric-resolution=15s` (no `--kubelet-insecure-tls`). k3s' bundled metrics-server
  (`manifests/metrics-server/metrics-server-deployment.yaml`, k3s master) is `rancher/mirrored-metrics-server:v0.9.0`, label
  `k8s-app: metrics-server`, also without `--kubelet-insecure-tls`.
- Argo CD sync options (stable docs): `RespectIgnoreDifferences=true` applies `ignoreDifferences` during the sync, only for resources that
  already exist (example: `/spec/replicas` of Deployments); `PruneLast` makes pruning a final implicit wave.
- Not verifiable without a registry token: that the three `ghcr.io/kedacore/*:2.19.0` images exist with those tags (the chart pins them
  through its appVersion). The build checks them with `docker manifest inspect` before committing t3.

## Contract: the gitops repo answer `resource_metrics` (AC-120.17, AC-120.27)

`templates/gitops-app/copier.yml`, after `cluster_server`:

```yaml
resource_metrics:
  type: str
  help: "Does the cluster already serve resource metrics (metrics.k8s.io)? provided: yes (k3s, k3d, GKE, AKS, EKS with its metrics-server add-on); install: the platform installs metrics-server when an instance scales on cpu or memory."
  choices: [provided, install]
  default: provided
```

`render.py` reads it from `.copier-answers.yml` (`answers()`); a missing answer (every repo generated before this release) is `provided`.

## Contract: model, `cplat model show`, status (AC-120.16, AC-120.21, AC-120.22)

- **Model** (`build`, lenient, never fails): `Environment.autoscaling: str | None` (`"keda"` as the renderer derives it, else `None`);
  `Instance.scale: dict | None` = `{"min": int, "max": <as declared>, "on": <the declared mapping>}` (the effective one; `min` default 1;
  values that are not integers are kept as declared), and `Instance.replicas` is `None` when `scale` is set. JSON (schema stays 2):
  `environments[]` gains `"autoscaling"` after `"backup"`, `instances[]` gains `"scale"` after `"replicas"`; both keys are present for
  every environment and instance (`null` when absent).
- **`cplat model show`** text: an environment line ends with `  autoscaling keda` when it derives KEDA (before the autonomy line); a
  scaled instance line prints `replicas -` and ends with `  scale <min>–<max> on <t>`, `<t>` = `cpu <p>%` | `memory <p>%` |
  `consumes <api> lag <n>` | `cache <r> list <k> length <n>`; `–` is U+2013. Other lines do not change.
- **`cplat system status`**: the cell of a scaled instance gains `"scale": {"replicas": <int | null>, "min": <min>, "max": <max>}`; the
  replica count is `kubectl --context <ctx> -n <namespace> get deployments.apps <c> -o jsonpath={.spec.replicas}` (what the autoscaler
  decided), `null` when there is no context for the environment or the call fails. Text: the cell ends with `  replicas <n|?> (<min>–<max>)`,
  e.g. `healthy sha-1a2b3c4 ci ok argo Synced/Healthy  replicas 3 (1–5)`, `… replicas ? (1–5)`. Unscaled cells are unchanged (no key, no
  text).

## Contract: `cplat component set` (AC-120.5)

Before anything is written (after the component and instance lookups), with `--replicas`:

| Case | Text (PlatformError) | Hint |
|---|---|---|
| `--instance <env>` and the instance's effective config has `scale` | `<c> is scaled in <env> (<key>): scale and replicas exclude each other; remove <key> from system.yaml first` | `edit applications/<system>/system.yaml, then run component set again` |
| no `--instance`, and `components.<c>.scale` exists | `<c> is scaled (components.<c>.scale): scale and replicas exclude each other; remove components.<c>.scale from system.yaml first` | same |

`<key>` = `components.<c>.instances.<env>.scale` when the instance has it, else `components.<c>.scale`. An instance with its own
`replicas` under a component `scale` is not scaled and may be changed. Exit code 1, the tree unchanged.

## Contract: doctor (AC-120.17, AC-120.18, AC-120.25, AC-120.27)

- `check_operators` gains `("keda", "keda")` and `("metrics-server", "metrics-server")` after `nack`. `_operator_needs`: `keda` = the
  environments whose model `autoscaling` is `keda`; `metrics-server` = the environments with a `cpu`/`memory` instance, only when the
  repo answer is `install`. The rows use 115's texts; a `keda` row's detail ends with `; queue-triggered: <c> (<env>), …` (instances in
  model order). With `operators: owner` and KEDA missing (AC-120.18):
  WARN `operator keda`: `not installed in the current kube context, expected 2.19.0 (operators: owner in dev); queue-triggered: worker (dev)`,
  fix `install the keda chart 2.19.0 (operator 2.19.0)`.
- New `check_metrics(repo)` after `check_brokers`, only with `kubectl` and only when some instance has a `cpu`/`memory` trigger; row
  `resource metrics`, read with `kubectl get apiservices.apiregistration.k8s.io v1beta1.metrics.k8s.io -o jsonpath={.status.conditions[?(@.type=="Available")].status}`:
  - OK: `the cluster serves metrics.k8s.io; cpu and memory triggers: <c> (<env>), …`
  - WARN (not `True`): `the current kube context serves no resource metrics (metrics.k8s.io); the cpu and memory triggers of <c> (<env>), … cannot scale`,
    fix `set resource_metrics: install in .copier-answers.yml and run devbox run render (the platform then installs metrics-server 3.14.0), or install a metrics server yourself`;
    with the answer already `install`: fix `apply operators/root.yaml once: KUBE_CONTEXT=<ctx> devbox run bootstrap (local: devbox run cluster-up)`.
- Cluster repos: `check.py needs` adds `keda` for an environment with `cfg["autoscaling"][env] == "keda"`; `metrics-server` is never
  required (the cluster may serve metrics itself) but may be listed in `cluster.yaml`; `render.py --crds` prints no line for an operator
  whose `crd` is `None`.

## Contract: local cluster and bootstrap (AC-120.17)

`local-cluster.sh` (the copy in `templates/cluster-gitops` stays byte-equal):
- `KEDA_VERSION` (default: `targetRevision` of `operators/apps/keda.yaml`, else `2.19.0`), `WITH_KEDA` (1, 0, default 1 exactly when that
  file exists). With Argo CD it comes from `operators/root.yaml` (`with_keda` joins the operators condition) and `up` waits for
  `scaledobjects.keda.sh` (≤ 600 s) and `rollout status` of `deploy/keda-operator`, `deploy/keda-operator-metrics-apiserver` and
  `deploy/keda-admission-webhooks` in `keda` (≤ 300 s each); with `WITH_ARGO=0` a k3s `HelmChart` `keda` (namespace `kube-system`,
  `targetNamespace: keda`, `createNamespace: true`, repo/chart/version of the table, no values) and the same waits (CRD ≤ 180 s).
- `METRICS_SERVER_VERSION` (default from `operators/apps/metrics-server.yaml`, else `3.14.0`), `WITH_METRICS_SERVER` (default 1 exactly
  when that file exists). When 1, a new k3d cluster is created with `--k3s-arg "--disable=metrics-server@server:*"` (one metrics source,
  the pinned one); with `WITH_ARGO=0` a `HelmChart` `metrics-server` (`targetNamespace: kube-system`, no values). A reused cluster keeps
  what it has and the script says so.
- Always (with a system): after the operators, wait up to 120 s for `apiservices.apiregistration.k8s.io/v1beta1.metrics.k8s.io`
  `Available=True`; on timeout print `WARNING: the cluster serves no resource metrics yet (v1beta1.metrics.k8s.io is not Available); cpu and memory triggers cannot scale until it is`
  and continue. k3s ships metrics-server, so a default local cluster has a resource-metrics source.
- `bootstrap.sh`: `keda) crd=scaledobjects.keda.sh ;;`; `metrics-server` has no CRD and falls through `*) continue`; the header comment
  names KEDA and metrics-server.

## Timings (AC-120.10, AC-120.12, AC-120.14, AC-120.15, AC-120.23)

- **Scale-up**: KEDA's HPA asks the metrics adapter every 15 s (HPA sync period); with no scale-up stabilization and the default policies
  (+100 % or +4 pods per 15 s, the larger), 1 → 3 or 1 → 5 takes one step: well within 2 minutes once pods start.
- **Wake from zero**: KEDA polls every 15 s and scales 0 → 1 when lag (length) > 0; a pod is running within 60 s when it starts in under
  ~40 s (AC-120.14).
- **Back to zero** (`min: 0`): KEDA scales to 0 when the trigger was last active more than `cooldownPeriod` (315 s) ago, checked every
  15 s. The last active poll is at most 15 s before the queue became empty, so zero comes 300 to 330 s after the queue emptied.
- **Back to `min ≥ 1`**: the HPA keeps the highest recommendation of the last 345 s. The last recommendation above `min` is at most 15 s
  older than the moment the backlog fell to `min × lag` (`min × length`), so `min` comes 330 s after that moment at the earliest and
  345 + 15 s after the queue emptied at the latest (6 minutes). This meets "no earlier than 5 minutes after the queue became empty" when the
  last `min × lag` items are worked off within 30 s (see "Decisions taken by default" 5 and the changelog line for AC-120.15).

## Contract: docs (AC-120.24)

`docs/DOMAIN-MODEL.md`: the keys table rows for the component and the instance gain `scale`; a section "Scaling an instance" with the
schema, the component default and the whole-replacement rule, the exclusivity with `replicas`, `autoscaling` as a derived environment
property (and that `environments.<env>.autoscaling` is refused), scale to zero (queue triggers only, never for exposed components or
request APIs), the timings above, what Argo CD does (ADR-067), KEDA and the metrics source (`resource_metrics`), the external-broker
refusal, and one example per trigger form (the four `on:` forms of the `system.yaml` contract above, each in a component or instance).
`render.py`'s docstring gains the `scale` lines (it is the schema reference in every gitops repo). The site page
`site/src/content/docs/concepts/domain-model.md` gets the same rule in short; `docs/CLUSTERS.md` names `keda` and `metrics-server` among the
operators a cluster repo may list.

## Contract: e2e (AC-120.23, and the cluster halves of AC-120.5, .10, .12 to .15, .17, .19 to .22, .25, .27)

Inserted in the broker block, after spec 119's doctor step and before its "resource remove bus is refused" step (the broker is running
then), all in dev. Cluster-up gets `WITH_KEDA=1` (no component uses KEDA at cluster-up, so `operators/apps/keda.yaml` does not exist yet).
"Build and push" also builds `localhost:<regport>/e2e-worker:latest` from a context directory in `$work` (`FROM` the nats probe image,
`USER 1000`, a worker script, `CMD ["python", "-u", "/worker.py"]`): it answers 200 to every GET on `$PORT`, connects with `NATS_URL`,
`NATS_USER`, `NATS_PASSWORD` and `NATS_INBOX_PREFIX`, binds a pull subscription to `EVENTS_JOBS_CONSUMER` on `EVENTS_JOBS_STREAM`, and loops:
fetch one message (5 s timeout), sleep `WORK_SECONDS` (3), acknowledge; errors are printed and retried after 2 s.

1. Declare (commit first): `apis.jobs: {type: events}` (bound to `bus`), e2e-api `provides += [jobs]`, a component `e2e-worker`
   (`type: service`, `lang: python`, image `<registry>/e2e-worker`, port 8080, probes `/health`, `user: 1000`, `volumes: {tmp: /tmp}`,
   `env: {PYTHONDONTWRITEBYTECODE: "1", WORK_SECONDS: "3"}`, requests 50m/64Mi, memory limit 128Mi, `consumes: [jobs]`, `uses: [sessions]`,
   `instances: {dev: {scale: {min: 0, max: 5, on: {consumes: jobs, lag: 10}}}}`); render; commit. Checks: `operators/apps/keda.yaml` pins
   2.19.0 and equals the `helmcharts.helm.cattle.io` `keda` version; the `keda-operator` image tag is 2.19.0; `scaledobjects.keda.sh` and
   `triggerauthentications.keda.sh` exist; no `operators/apps/metrics-server.yaml`; `overlays/dev/e2e-worker/` has `scaledobject.yaml`
   (the designed trigger, endpoint `e2e-bus.e2e-dev.svc:8222`, stream `e2e-jobs`, consumer `e2e-worker`, lag "10") and no `hpa.yaml` or
   `triggerauthentication.yaml`, the Deployment has `replicas: 0`; `applicationset.yaml`'s dev set has the ignore entry for `e2e-worker`,
   `RespectIgnoreDifferences=true` and the retry; the rendered tree holds no password (grep of the worker overlay for the Secret's value);
   `cplat model show --json`: dev `autoscaling: keda`, staging/prod `null`, `e2e-worker/dev` `scale` as declared and `replicas: null`,
   `e2e-api/dev` `scale: null`.
2. Apply (bounded, streamed): the bus addon again as spec 119 does (new user Secret, chart values, stream `e2e-jobs`, consumer
   `e2e-jobs.e2e-worker` Ready ≤ 120 s), then the worker overlay without the `ScaledObject` (Deployment, Service), then the `ScaledObject`
   (wave 1) with `Ready=True` ≤ 90 s; the Deployment has 0 replicas.
3. Wake (AC-120.14): a probe with e2e-api's variables publishes one message on `e2e.jobs.one`; `readyReplicas ≥ 1` within 60 s.
4. Burst (AC-120.10, AC-120.23): the same probe publishes 100 messages; a bounded background watcher (5 s period, ≤ 600 s, every line
   printed at the join) records time, `.spec.replicas` and the consumer's lag from `/jsz`; `.spec.replicas` reaches 5 within 120 s of the
   publish.
5. While the watcher runs: the sync emulation of AC-120.19 on e2e-worker (the rendered Deployment with `spec.replicas` replaced by the
   live count, as `RespectIgnoreDifferences` does, is applied; `.spec.replicas` and `.metadata.generation` do not change); `cplat system
   status --context k3d-<cluster> --json` (e2e-worker's dev cell has `scale.min` 0, `scale.max` 5 and an integer `replicas`; the text
   output matches `\breplicas [0-5] \(0–5\)`; e2e-api's cell has no `scale`); the CPU step (AC-120.6, AC-120.17): e2e-web's dev instance
   gets `scale: {min: 1, max: 2, on: {cpu: 80}}` (commit, render, commit), `overlays/dev/e2e-web/hpa.yaml` exists with no
   `scaledobject.yaml`, only the HPA document is applied, and `.status.currentMetrics[0].resource.current.averageUtilization` is set within
   120 s; doctor (rows `operator keda` ok with 2.19.0 and the word `e2e-worker`, `resource metrics` ok; no `operator metrics-server` row);
   AC-120.5 (commit first): `cplat component set e2e-worker --instance dev --replicas 2` fails naming
   `components.e2e-worker.instances.dev.scale`, the tree unchanged; then e2e-web's `scale` is removed (render deletes `hpa.yaml`, the HPA
   is deleted by its full kind name as Argo CD's prune would, commit).
6. Join the watcher (AC-120.15, AC-120.23): the maximum replica count seen is 5; the lag reached 0 at `T`; the count reached 0 at `Z`
   with 295 s ≤ `Z − T` ≤ 420 s (5 s sampling).
7. Cache trigger (AC-120.11 to AC-120.13): e2e-worker's dev trigger becomes `{cache: sessions, list: jobs, length: 10}` (render: a
   `TriggerAuthentication` reading `host`, `port`, `password` of `e2e-sessions-app`, the redis trigger); apply both; a cache probe (spec
   118's `crun`) RPUSHes 30 entries to `jobs`; `.spec.replicas` reaches 3 within 120 s and never exceeds 3 while the list holds 30; then
   `DEL jobs`.
8. Switch back (AC-120.20): `scale` replaced by `replicas: 1` in dev; render removes `scaledobject.yaml` and `triggerauthentication.yaml`,
   the Deployment has `replicas: 1`, the dev ignore entry is gone; the `ScaledObject` and `TriggerAuthentication` are deleted by full kind
   name (Argo's prune), the Deployment applied; sampled every 2 s, the count never falls below 1 and ends at 1; `keda-hpa-e2e-worker`
   (`horizontalpodautoscalers.autoscaling`) is gone within 60 s.
9. Clean-up: `jobs`, e2e-api's `provides: jobs` and e2e-worker are removed (render prints the retired stream `e2e-jobs` and consumer
   `e2e-worker`; `operators/apps/keda.yaml` is gone, AC-120.27); the bus chart is applied again without the user; the worker's Deployment
   and Service, `consumers.jetstream.nats.io/e2e-jobs.e2e-worker`, `streams.jetstream.nats.io/e2e-jobs`, the ExternalSecret and Secret
   `e2e-bus-e2e-worker-app` and the list are deleted, so spec 119's remaining steps see the cluster they expect.

Budget: the steps take at most 13 minutes in the log (the scale-down is the floor: ≥ 5 minutes after the burst is worked off, overlapped
with step 5); KEDA at cluster-up and the worker image at most 1.5 minutes more. The e2e job (75 minutes, already ~60) gets 90.

## Risks

- **Two controllers during a switch.** An HPA → KEDA switch relies on the old HPA being pruned in wave 0 before the `ScaledObject` (wave 1)
  meets KEDA's admission webhook ("already managed by the hpa"); if Argo CD orders it otherwise the sync fails once and the retry
  succeeds. A KEDA → HPA switch leaves both for one wave (the HPAs report `AmbiguousSelector` and do nothing until the prune).
- **The ApplicationSet and the overlay change in one commit**; if the component application syncs first, a switch to `scale` sets
  `replicas: <min>` once (never below `min`), a switch back keeps the autoscaler's count until the next self-heal applies the fixed
  number.
- **A missing durable consumer** makes KEDA's NATS scaler fall back to the stream's last sequence (it may scale to `max`): the consumer is in
  wave 3 of the addon and exists before a worker is useful; the e2e applies it first.
- **Clustered brokers (`replicas: 3`)**: the scaler finds the consumer leader through `/varz` of each server; not exercised by the e2e.
- **Label tracking in Argo CD** would make KEDA's HPA (which copies the `ScaledObject`'s labels) look extraneous; the platform's Argo CD
  uses annotation tracking (default since 3.0). Documented.
- **External caches with TLS** (`rediss://`) are not supported by the cache trigger (no TLS parameters); documented.
- **KEDA 2.19** is two minors behind; spec 121 moves it with the local cluster's Kubernetes. The CVE fixed in 2.21.0 concerns
  bound service-account tokens, which the platform does not use.
- **Backups**: Velero backs up `ScaledObject`s, `TriggerAuthentication`s and HPAs with the namespace; KEDA recreates its own HPA after a
  restore. Not exercised by the e2e.
- **kubeconform** (`devbox run validate`) checks `hpa.yaml` and `scaledobject.yaml` (`[dsehp]*.yaml`) against the default and the Datree
  catalog schemas (`keda.sh/scaledobject_v1alpha1`); if the catalog lacks it, the build adds the kind to the skip list and says so in the
  CHANGELOG.
- **The metrics-server chart on a k3s cluster** (`resource_metrics: install` plus a local cluster) replaces k3s' own; both run v0.9.0 with
  the same kubelet TLS settings, but this path is not exercised by the e2e.

## Decisions taken by default

1. **KEDA chart 2.19.0** (newest KEDA tested on Kubernetes 1.32, the local cluster's and the e2e's k3s). Alternative: 2.21.0, the newest
   chart, tested on 1.34–1.36 only; it would need the local cluster's `K3S_IMAGE` raised (a change to every local cluster).
2. **Argo CD coexistence by name-scoped `ignoreDifferences` plus `RespectIgnoreDifferences=true`, `spec.replicas: <min>` kept.**
   Alternatives: omitting `spec.replicas` (a client-side apply then deletes it on the switch and drops to 1 replica, against AC-120.20);
   `managedFieldsManagers: [kube-controller-manager]` (keeps ignoring after a switch back); `Replace=true` (recreates on every sync).
3. **The metrics source is the repo answer `resource_metrics: provided | install` (default `provided`).** Alternatives: always render
   metrics-server (conflicts with the built-in source of k3s, GKE, AKS); never (fails AC-120.27).
4. **`on` is required** (no default trigger). Alternative: default `{cpu: 80}`.
5. **Timings: polling 15 s, cool-down 315 s, scale-down stabilization 345 s (100 % per 15 s).** Alternative: KEDA's defaults (30 s, 300 s,
   300 s), which can reach zero up to 15 s and `min` up to 30 s before the 5 minutes.
6. **Lag is KEDA's `num_pending + num_ack_pending`.** Alternative: pending only (not what the scaler offers).
7. **An external broker cannot be a trigger.** Alternative: add a `monitoring` key to spec 119's external contract (a change to its store
   keys).
8. **No `TriggerAuthentication` for a broker trigger** (the monitoring endpoint is unauthenticated). Alternative: render one reading the
   per-component Secret, which holds nothing the scaler uses.
9. **A cache trigger reads `host`, `port`, `password` from `<system>-<r>-app`** (works for in-cluster and external caches),
   `databaseIndex: "0"`, no TLS. Alternative: `address` in the metadata (in-cluster only, a name in git).
10. **Autoscaler objects are named after the component, in its overlay** (`hpa.yaml`, `scaledobject.yaml`, `triggerauthentication.yaml`).
    Alternative: a separate directory and application (another application per instance).
11. **KEDA objects in sync wave 1 with `SkipDryRunOnMissingResource`; the environment set retries when it holds a KEDA instance.**
    Alternatives: `PruneLast` (would prune the old HPA after the new `ScaledObject` is refused); KEDA's `validations.keda.sh/hpa-ownership:
    "false"` (would also hide real conflicts).
12. **`component set --replicas` without `--instance` is refused too while `components.<c>.scale` exists.** Alternative: let the render
    fail with AC-120.3's text after the edit.
13. **AC-120.28 names the host label (`expose.host` or the component name)**, checked at the declaration. Alternative: the rendered
    hostname per environment (an environment without `host` has none).
14. **AC-120.7 reads 114's effective `resources`** (the instance's replace the component's), exactly what the Deployment gets.
15. **`metrics-server` in the table with `namespace: kube-system`, no values, `crd: None`** (cluster `--crds` skips it, bootstrap has
    nothing to wait for). Alternative: leave it out of the table (no pin, against AC-120.25).
16. **`scale` is appended last to both key lists** (spec 124's precedent for `autonomy`); the two "allowed:" texts change.
17. **Status shows `.spec.replicas`** (what the autoscaler decided). Alternative: ready replicas (lags behind during a rollout).
18. **Status text `replicas <n> (<min>–<max>)` appended to the cell; JSON `scale` only on scaled cells.**
19. **The model's `scale` has exactly `min`, `max`, `on`** (where it was declared is not shown).
20. **The local cluster uses k3s' own metrics-server; with `operators/apps/metrics-server.yaml` a new cluster is created without it.**
    Alternative: run both (two sources for one APIService).
21. **`local-cluster.sh up` waits up to 120 s for the metrics APIService and only warns.** Alternative: fail (a cluster without CPU
    triggers does not need it).
22. **The e2e adds one component `e2e-worker` (built from the nats probe image) and an events API `jobs`, applies only the HPA for e2e-web's
    CPU step, overlaps the scale-down wait with the CPU, status, doctor and refusal checks, and raises the job limit to 90 minutes.**
    Alternative: a second consumer for `min ≥ 1` (another 6 minutes).
23. **Plugins: `component` 1.3.0 (`set`), `system` 1.4.0 (`status`), `platform` 1.2.0 (`doctor`).**
24. **Two ADRs** (the scaling model and operators; the Argo CD coexistence) rather than one, because the second applies to any later
    controller that owns a field Argo CD renders.
25. **`min` defaults to 1 when absent; `scale: null` is "not a mapping".**

**Verified at plan time (2026-10-28, orchestrator):** `docker manifest inspect` finds `ghcr.io/kedacore/keda:2.19.0`,
`keda-metrics-apiserver:2.19.0`, `keda-admission-webhooks:2.19.0` and `registry.k8s.io/metrics-server/metrics-server:v0.9.0`.
