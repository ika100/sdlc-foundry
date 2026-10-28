---
spec_id: 120-instances-scale-on-load-and-queue-depth
shape: platform
spec_hash: 9e86ee33f988
summary: "Scaling as an Instance property (additive 5.x): scale {min, max, on} on a service or website component (default of its instances) or on an instance, exclusive with replicas on one level, max 1..20, min 0..max (default 1), exactly one trigger (cpu or memory percent of the request, consumes <api> lag <n>, cache <r> list <k> length <n>); cpu/memory render a plain autoscaling/v2 HPA, queue triggers a KEDA ScaledObject (NATS JetStream lag of the component's durable consumer, unauthenticated monitoring; Redis list length with a TriggerAuthentication on the cache Secret <system>-<r>-app); scale to zero only with a queue trigger and never for exposed components or request-API providers; an external broker is refused as a trigger; scaled Deployments keep replicas: min while the environment's component ApplicationSet ignores /spec/replicas by name with RespectIgnoreDifferences (KEDA objects in wave 1, retry); autoscaling: keda is derived per environment and KEDA 2.19.0 joins the versions table as a per-cluster operator (operators/, cluster repos, local-cluster.sh WITH_KEDA, bootstrap, doctor rows naming the queue-triggered instances), metrics-server 3.14.0 is rendered when the repo answers resource_metrics: install; timings polling 15 s, cool-down 315 s, scale-down stabilization 345 s; model, model show, system status (replicas n (min–max)), component set refusals, docs, two ADRs and an e2e proof of wake, burst to max, return to zero, cpu metrics, a cache trigger and the switch back"
tasks:
  - id: t1
    title: render.py — scale schema (component and instance keys, exclusivity with replicas, min/max/on forms and values, zero needs a queue), reference and effective checks (consumes bound events API, cache in uses, zero refused for exposed or request APIs, cpu/memory requests, external broker), effective scale in _eff, cfg["autoscaling"], scaled_instances
    files: [templates/gitops-app/scripts/render.py, templates/cluster-gitops/scripts/system_render.py]
    covers: [AC-120.1, AC-120.2, AC-120.3, AC-120.4, AC-120.6, AC-120.7, AC-120.8, AC-120.9, AC-120.11, AC-120.16, AC-120.26, AC-120.28]
    parallel_safe: true
    depends_on: []
  - id: t2
    title: render.py — scaled Deployments (replicas min), hpa.yaml, scaledobject.yaml (nats-jetstream and redis triggers, timings), triggerauthentication.yaml, MANAGED_FILES, the environment ApplicationSet's ignoreDifferences, RespectIgnoreDifferences and retry
    files: [templates/gitops-app/scripts/render.py, templates/cluster-gitops/scripts/system_render.py]
    covers: [AC-120.2, AC-120.6, AC-120.10, AC-120.12, AC-120.13, AC-120.14, AC-120.15, AC-120.19, AC-120.20, AC-120.23, AC-120.26]
    parallel_safe: false
    depends_on: [t1]
  - id: t3
    title: render.py — versions table (OPERATORS keda 2.19.0 and metrics-server 3.14.0), operator_files (keda per derived autoscaling, metrics-server per the resource_metrics answer, never with operators owner), docstring
    files: [templates/gitops-app/scripts/render.py, templates/cluster-gitops/scripts/system_render.py]
    covers: [AC-120.16, AC-120.17, AC-120.24, AC-120.25, AC-120.26, AC-120.27]
    parallel_safe: false
    depends_on: [t2]
  - id: t4
    title: model — Instance.scale (effective, lenient), replicas None when scaled, Environment.autoscaling, JSON keys
    files: [scripts/cplat/model.py]
    covers: [AC-120.16, AC-120.21]
    parallel_safe: true
    depends_on: []
  - id: t5
    title: cplat model show — autoscaling keda on environment lines, scale <min>–<max> on <trigger> on instance lines
    files: [scripts/cplat/modelcmd.py]
    covers: [AC-120.16, AC-120.21]
    parallel_safe: true
    depends_on: [t4]
  - id: t6
    title: cplat system status — the replica count read from the cluster and the bounds of a scaled instance (JSON scale, text replicas n (min–max), ? when unreachable)
    files: [scripts/cplat/status.py]
    covers: [AC-120.22]
    parallel_safe: true
    depends_on: [t4]
  - id: t7
    title: cplat component set — --replicas refused on a scaled instance (naming the scale key) and on a component with scale
    files: [scripts/cplat/compose.py]
    covers: [AC-120.5]
    parallel_safe: true
    depends_on: []
  - id: t8
    title: doctor — operator keda row naming the queue-triggered instances (operators owner included), operator metrics-server row, resource metrics row
    files: [scripts/cplat/doctor.py]
    covers: [AC-120.17, AC-120.18, AC-120.25, AC-120.27]
    parallel_safe: true
    depends_on: [t3, t4]
  - id: t9
    title: local-cluster.sh WITH_KEDA/KEDA_VERSION and WITH_METRICS_SERVER/METRICS_SERVER_VERSION and the metrics wait (+ its cluster-gitops copy), bootstrap.sh waits for the KEDA CRD, the resource_metrics question, cluster check needs keda, cluster --crds skips an operator without a CRD
    files: [templates/gitops-app/scripts/local-cluster.sh, templates/cluster-gitops/scripts/local-cluster.sh, templates/gitops-app/scripts/bootstrap.sh, templates/gitops-app/copier.yml, templates/cluster-gitops/scripts/check.py, templates/cluster-gitops/scripts/render.py]
    covers: [AC-120.17, AC-120.25, AC-120.27]
    parallel_safe: true
    depends_on: [t3]
  - id: t10
    title: component plugin 1.3.0, system plugin 1.4.0, platform plugin 1.2.0 (commands, READMEs, manifests, catalog) and the CHANGELOG [Unreleased] entry
    files: [plugins/component/commands/set.md, plugins/component/README.md, plugins/component/.claude-plugin/plugin.json, plugins/system/commands/status.md, plugins/system/README.md, plugins/system/.claude-plugin/plugin.json, plugins/platform/commands/doctor.md, plugins/platform/README.md, plugins/platform/.claude-plugin/plugin.json, .claude-plugin/marketplace.json, docs/CHANGELOG.md]
    covers: [AC-120.5, AC-120.18, AC-120.22]
    parallel_safe: true
    depends_on: []
  - id: t11
    title: Docs — DOMAIN-MODEL.md (scale as an Instance property, four trigger examples, component default, exclusivity, derived autoscaling, zero, timings, Argo CD, KEDA and the metrics source), CLUSTERS.md, USER-JOURNEY.md and the site's domain-model page
    files: [docs/DOMAIN-MODEL.md, docs/CLUSTERS.md, docs/USER-JOURNEY.md, site/src/content/docs/concepts/domain-model.md]
    covers: [AC-120.24]
    parallel_safe: true
    depends_on: []
  - id: t12
    title: e2e — KEDA at cluster-up, an e2e-worker consuming jobs with scale min 0 max 5 lag 10; pins and rendered files, wake within 60 s, 100 messages to 5 replicas within 2 minutes, back to zero 5 to 7 minutes after the queue empties, sync emulation, status, cpu metrics on e2e-web, doctor rows, the component set refusal, a cache trigger to 3 replicas, the switch back, clean-up
    files: [tests/e2e/run.sh, .github/workflows/e2e.yml]
    covers: [AC-120.5, AC-120.6, AC-120.10, AC-120.12, AC-120.13, AC-120.14, AC-120.15, AC-120.17, AC-120.19, AC-120.20, AC-120.21, AC-120.22, AC-120.23, AC-120.25, AC-120.27]
    parallel_safe: false
    depends_on: [t3, t5, t6, t7, t8, t9]
  - id: t13
    title: Amend the spec 114/117/119 assertions that 120 extends (the instance key list, the model JSON normalisation, the OPERATORS order)
    files: [tests/cplat/test_system_render_114.py, tests/cplat/test_system_model_114.py, tests/cplat/test_backup_117.py, tests/cplat/test_broker_119.py]
    covers: [AC-120.16, AC-120.21, AC-120.25, AC-120.26]
    parallel_safe: true
    depends_on: []
---

# Plan — 120 Instances scale on load and queue depth

The contract (schema, error texts, effective scale, rendered documents with key order, the ApplicationSet change, pins and what was
verified, the `resource_metrics` answer, model, `model show`, status, `component set`, doctor, local cluster, timings, docs, e2e) is in
[design.md](design.md). The decisions that outlive this spec are the two ADRs
[instances scale with an HPA or KEDA](../../adr/066-instances-scale-with-an-hpa-or-keda-installed-per-cluster.md) and
[Argo CD leaves autoscaled replica counts alone](../../adr/067-argo-cd-leaves-autoscaled-replica-counts-alone.md). It builds on spec 114
(closed key lists, `_eff`), 115 (versions table, `operators/`, doctor rows), 118 (the cache Secret), 119 (durable consumers, the
monitoring endpoint, the e2e broker block), 124 (key lists grow at the end) and 125 (`OPERATORS` shared with cluster repos, synced copies).
Levels: t1, t4, t7, t10, t11, t13 → t2, t5, t6 → t3 → t8, t9 → t12.

`render.py` changes in three sequential tasks (t1 → t2 → t3). Each ends with `python3 scripts/sync-template-copies.py`, so
`templates/cluster-gitops/scripts/system_render.py` stays byte-equal (`--check` runs in CI), which is why each lists the copy; t9 runs the
same script for `local-cluster.sh` and lists that copy (render.py is unchanged in its branch, so only that copy is rewritten). Every other
task owns its files. Never edit `scripts/cplat/assets/render_v4.py`. Every 5.x `system.yaml` without `scale` must render byte-identically;
the acceptance tests pin digests taken from `main` before t1 (114's full/rich systems, a database and bucket system, a cache system, a
broker system with consumers), and the 114–125 suites, amended only by t13, stay green. `envrestore.py`, `addon.py`, `apilist.py`,
`promote.py`, the Kyverno policy and the Velero Schedule do not change. Tests that look for domain-like names (`scaledobjects.keda.sh`,
`v1beta1.metrics.k8s.io`, `e2e-bus.e2e-dev.svc`) match them with word-bounded regular expressions, never with `"a.b.c" in text` (CodeQL
flags those).

**Spec readings resolved by default (design.md, "Decisions taken by default"); each needs a changelog line in spec.md before its
acceptance tests are written:**
- **AC-120.13 / AC-120.9 (broker)**: spec 119's monitoring endpoint is unauthenticated, so a broker trigger needs no credentials and
  renders no `TriggerAuthentication`; the broker half of AC-120.13 holds because no credential is used or rendered. An external broker has
  no monitoring endpoint in its contract and is refused as a trigger (a new reason under AC-120.9).
- **AC-120.27 (metrics source)**: a render cannot see whether a cluster serves resource metrics; the gitops repo declares it with the
  answer `resource_metrics: provided | install` (default `provided`), and `install` renders the pinned metrics-server.
- **AC-120.15 (lower bound)**: KEDA reaches zero 300–330 s after the queue empties; an HPA reaches `min ≥ 1` 330 s after the backlog
  fell to `min × lag`, which is "no earlier than 5 minutes after the queue became empty" when the last `min × lag` items are worked off
  within 30 s. The upper bound (7 minutes) always holds.
- **AC-120.17 (local cluster)**: as with spec 119's NACK, the local cluster installs KEDA when `operators/apps/keda.yaml` exists (an
  environment without `operators: owner` derives `keda`) or `WITH_KEDA=1`; a local cluster whose KEDA environments are all
  `operators: owner` needs `WITH_KEDA=1`.
- **AC-120.23 ("the Argo application stays Synced")**: the e2e runs without Argo CD (`WITH_ARGO=0`, since its first version); it proves
  the sync behaviour by applying what `RespectIgnoreDifferences` applies (replica count and generation unchanged), and the render tests
  prove the ignore rule.
- **AC-120.1 (`on`)**: only `max` is named as required; `on` is required too (a scale without a trigger has nothing to follow).

## t1 — render.py: the `scale` schema and its checks

**Files:** templates/gitops-app/scripts/render.py, templates/cluster-gitops/scripts/system_render.py
**Covers:** AC-120.1, AC-120.2, AC-120.3, AC-120.4, AC-120.6, AC-120.7, AC-120.8, AC-120.9, AC-120.11, AC-120.16, AC-120.26, AC-120.28
**Goal:** `scale` is accepted on service and website components and their instances and refused in every invalid form with the texts of
design.md (Render errors); `load_system` returns each instance's effective scale, `cfg["autoscaling"]` and `scaled_instances`. Nothing
is rendered differently yet.

**Implementation notes:**
- `SERVICE_KEYS` and `INSTANCE_KEYS` gain `"scale"` at the end; `EXTERNAL_KEYS`, `LIBRARY_KEYS`, an external instance's
  `["promote", "autonomy"]` and `ENV_KEYS` do not change. New constants: `SCALE_KEYS = ["min", "max", "on"]`, `SCALE_MAX = 20`,
  `ON_FORMS` (the text), `TRIGGER_FORMS = {"cpu": ["cpu"], "memory": ["memory"], "consumes": ["consumes", "lag"], "cache": ["cache", "list", "length"]}`,
  `REQUEST_API_TYPES = ("openapi", "grpc", "graphql")`.
- New `check_scale(at: str, scale) -> dict` for the structural table in design.md's order (an `int` that is a `bool` is no integer);
  returns `{"min", "max", "trigger", "on"}`.
- `validate_component`: after 114's checks of a non-external component, the AC-120.3 text when both `scale` and `replicas` are keys, then
  `check_scale("components.<c>", …)`; the normalised scale goes to `svc` for `validate_instances`.
- `validate_instances`: per non-external instance, after `promote`/`autonomy`: the AC-120.3 text, `check_scale` of the instance's own
  `scale`, then the effective scale (own; none with own `replicas`; else the component's) with `source`; a scaled instance gets no
  `replicas` in `eff`.
- New `validate_scaling(comps, apis, resources, events)` after `validate_uses`: the reference table (declared scales, components order,
  then instances in ENVS order for the effective checks); `<what>` of AC-120.28 as designed; requests read from the effective `resources`.
- `_load_system`: `cfg["autoscaling"] = {env: "keda" | None}`; module-level `scaled_instances(services, env)`.
- Run `python3 scripts/sync-template-copies.py` before committing.

**Done when:** the render-error tests of AC-120.1, AC-120.3, AC-120.4, AC-120.6 (range), AC-120.7, AC-120.8, AC-120.9, AC-120.11 and
AC-120.28 pass (each text exactly, nothing written), the effective-scale tests of AC-120.2 (inheritance, whole replacement, own
`replicas` wins) and the derived `cfg["autoscaling"]` of AC-120.16 pass, an `environments.<env>.autoscaling` key still fails with 114's
text, and AC-120.26's byte-identity digests hold; the 114–125 render suites stay green after t13.

## t2 — render.py: autoscaler documents and Argo CD

**Files:** templates/gitops-app/scripts/render.py, templates/cluster-gitops/scripts/system_render.py
**Covers:** AC-120.2, AC-120.6, AC-120.10, AC-120.12, AC-120.13, AC-120.14, AC-120.15, AC-120.19, AC-120.20, AC-120.23, AC-120.26
**Goal:** every scaled instance renders the documents of design.md (Contract: rendered documents) in its overlay, and the environment's
component ApplicationSet carries the ignore rule; unscaled instances and environments render byte for byte as before.

**Implementation notes:**
- `replicas_for(svc, env)`: the effective scale's `min` when scaled, else 114's value.
- New `autoscaler_files(app, svc, env, cfg) -> dict[str, dict]`: `hpa.yaml` for `cpu`/`memory`; `scaledobject.yaml` for `consumes`
  (endpoint `<app>-<b>.<ns>.svc:8222`, `<b>` from `cfg["events"]`) and `cache`, plus `triggerauthentication.yaml` for `cache`; key order,
  labels (`labels_for`, fresh dicts), annotations, string metadata values and the timing constants (`KEDA_POLLING = 15`,
  `KEDA_COOLDOWN = 315`, `SCALE_DOWN_WINDOW = 345`) exactly as designed.
- `render_app`: the files join the component's `files` before the kustomization is written (so `resources` lists them sorted).
- `MANAGED_FILES` gains `hpa.yaml`, `scaledobject.yaml`, `triggerauthentication.yaml` (stale ones are deleted on a switch or removal).
- The environment ApplicationSet: only when `scaled_instances(services, env)` is not empty, `syncOptions` becomes
  `["CreateNamespace=true", "RespectIgnoreDifferences=true"]`, `retry: RETRY` follows when `cfg["autoscaling"][env] == "keda"`, and
  `ignoreDifferences` (one entry per scaled instance) follows `syncPolicy`; other environments unchanged.
- External components and libraries render nothing new.
- Run `python3 scripts/sync-template-copies.py` before committing.

**Done when:** the render tests of AC-120.6 (HPA for cpu and memory, no KEDA object), AC-120.10/AC-120.14/AC-120.15/AC-120.23 (the
ScaledObject's trigger, bounds and timing constants), AC-120.12 and AC-120.13 (redis trigger, `TriggerAuthentication` on
`<system>-<r>-app`, no TriggerAuthentication for a broker, no credential value anywhere in the tree), AC-120.19 (the ignore entries,
`RespectIgnoreDifferences`, retry only with KEDA, no `Replace` option), AC-120.20 (switching to `replicas` deletes the autoscaler files
and the ignore entry; switching cpu ↔ queue swaps the files), AC-120.2 (inherited scale renders per instance) pass; byte-identity holds.

## t3 — render.py: versions table, operators, docstring

**Files:** templates/gitops-app/scripts/render.py, templates/cluster-gitops/scripts/system_render.py
**Covers:** AC-120.16, AC-120.17, AC-120.24, AC-120.25, AC-120.26, AC-120.27
**Goal:** `operators/apps/keda.yaml` and `operators/apps/metrics-server.yaml` appear exactly where design.md says, pinned from the table;
the docstring documents `scale`.

**Implementation notes:**
- `OPERATORS["keda"]` and `OPERATORS["metrics-server"]` appended after `nack`, exactly as designed (`"crd": None` for metrics-server);
  `OPERATOR_OF_TYPE` unchanged. Before committing, re-read the KEDA and metrics-server Helm indexes completely and run
  `docker manifest inspect` on `ghcr.io/kedacore/keda:2.19.0`, `ghcr.io/kedacore/keda-metrics-apiserver:2.19.0`,
  `ghcr.io/kedacore/keda-admission-webhooks:2.19.0` and `registry.k8s.io/metrics-server/metrics-server:v0.9.0`; if a pin moved or an
  image is missing, update the pin and design.md's "Verified" paragraph in the same PR.
- `operator_files`: `keda` when an environment not in `cfg["operators"]` has `cfg["autoscaling"][env] == "keda"`; `metrics-server` when
  `ans.get("resource_metrics", "provided") == "install"` and such an environment has a running `cpu`/`memory` instance. Order stays the
  `OPERATORS` order.
- Docstring: `scale` lines under `components:` (component default and an instance override with each trigger form, min/max ranges,
  exclusivity with `replicas`), and the `resource_metrics` answer in one line.
- Run `python3 scripts/sync-template-copies.py` before committing.

**Done when:** the render tests of AC-120.27 (one `keda.yaml` for several KEDA environments; none for cpu-only or unscaled systems; none
when every KEDA environment is `operators: owner`; `metrics-server.yaml` only with `install` and a cpu/memory instance outside `owner`
environments), AC-120.25 (exact chart versions, no range or `latest`, `operator_application` equal to the file), AC-120.17's render half
and the AC-120.24 docstring test pass; byte-identity holds.

## t4 — model: scale and autoscaling

**Files:** scripts/cplat/model.py
**Covers:** AC-120.16, AC-120.21
**Goal:** the model knows each instance's effective scale and each environment's derived `autoscaling`, as the renderer does.

**Implementation notes:**
- `Instance.scale: dict | None = None` (`{"min", "max", "on"}`, `min` default 1, values as declared); `_replicas` returns `None` for a
  scaled instance; the effective rule as design.md (own `scale`, own `replicas`, component `scale`). External components never scale.
- `Environment.autoscaling: str | None = None`: `"keda"` when an instance there has a `consumes` or `cache` trigger.
- `to_dict`: `"autoscaling"` after `"backup"` in environments, `"scale"` after `"replicas"` in instances, for every entry; schema stays 2.
- Lenient: a malformed `scale` never raises (it is reported by the renderer).

**Done when:** the model tests of AC-120.21 (scaled: `scale` with min/max/on and `replicas: null`; unscaled: `replicas` and
`scale: null`; inherited and replaced scales) and AC-120.16 (`autoscaling: keda` / `null` per environment) pass, and the renderer–model
agreement tests (AC-114.70) pass with a scaled fixture.

## t5 — model show

**Files:** scripts/cplat/modelcmd.py
**Covers:** AC-120.16, AC-120.21
**Goal:** the text output shows the derived `autoscaling` and each scaled instance's bounds and trigger.

**Implementation notes:**
- Environment line: `  autoscaling keda` appended after `_backup(...)` and before the autonomy line, only for `keda`.
- Instance line: `replicas -` and `  scale <min>–<max> on <t>` before the autonomy line (`<t>` as designed, U+2013 dash).
- Every other line unchanged.

**Done when:** the AC-120.16/AC-120.21 command tests of `cplat model show` (text and `--json`) pass and the 113/114/119 `model show` tests
stay unchanged and green.

## t6 — system status

**Files:** scripts/cplat/status.py
**Covers:** AC-120.22
**Goal:** a scaled instance's cell shows the replica count the autoscaler chose and its bounds; nothing else changes.

**Implementation notes:**
- In `collect_all`, for an instance with `scale`: `kubectl --context <ctx> -n <namespace> get deployments.apps <c> -o jsonpath={.spec.replicas}`
  through `sh()` (bounded by its 30 s timeout); `None` without a context for the environment or on failure; the cell gets
  `"scale": {"replicas", "min", "max"}`.
- `_cell`: append `  replicas <n|?> (<min>–<max>)` when the cell has `scale`.
- Argo reading, states and unscaled cells unchanged.

**Done when:** the AC-120.22 status tests (kubectl faked: a count, an unreachable cluster `?`, no context `?`, unscaled cells unchanged in
text and JSON) pass and the 117/122 status tests stay green.

## t7 — component set refuses replicas on a scaled instance

**Files:** scripts/cplat/compose.py
**Covers:** AC-120.5
**Goal:** `cplat component set <c> [--instance <env>] --replicas <n>` refuses as designed and writes nothing.

**Implementation notes:**
- After the component and instance lookups, before any change: with `--instance`, the effective rule on the raw entry (instance `scale`;
  else instance `replicas` = not scaled; else component `scale`) and the designed text naming the key; without `--instance`, the component
  text when `components.<c>.scale` exists.
- The hint names `applications/<system>/system.yaml`; `--dry-run` refuses the same way.

**Done when:** the AC-120.5 command tests (instance scale, inherited component scale, own replicas under a component scale allowed,
component-level refusal, tree and branch unchanged) pass and the 114 `component set` tests stay green.

## t8 — doctor: KEDA, metrics-server, resource metrics

**Files:** scripts/cplat/doctor.py
**Covers:** AC-120.17, AC-120.18, AC-120.25, AC-120.27
**Goal:** `/platform:doctor` warns when KEDA (or, with `install`, metrics-server) is missing or at another version, naming the
environments, the queue-triggered instances and the expected version, and says whether the cluster serves resource metrics.

**Implementation notes:**
- `check_operators` gains `("keda", "keda")` and `("metrics-server", "metrics-server")` after `nack`; `_operator_needs` as designed
  (`metrics-server` reads the repo's `.copier-answers.yml`); the `keda` row's detail gets `; queue-triggered: <c> (<env>), …`.
- New `check_metrics(repo)` after `check_brokers` in the gitops-app branch: the `resource metrics` row with the designed texts and fixes.
- `check_cluster` (cluster repos) needs no change; `metrics-server`'s selector reads its image tag `v0.9.0` as `0.9.0`.

**Done when:** the AC-120.18 doctor tests (kubectl faked: KEDA installed, missing, other version, with and without `operators: owner`,
the instances named), the AC-120.17/AC-120.27 metrics tests (APIService available, unavailable, answer `provided`/`install`) and the
AC-120.25 version comparison pass, and the 115/117/119/125 doctor tests stay green.

## t9 — local cluster, bootstrap, copier answer, cluster repos

**Files:** templates/gitops-app/scripts/local-cluster.sh, templates/cluster-gitops/scripts/local-cluster.sh, templates/gitops-app/scripts/bootstrap.sh, templates/gitops-app/copier.yml, templates/cluster-gitops/scripts/check.py, templates/cluster-gitops/scripts/render.py
**Covers:** AC-120.17, AC-120.25, AC-120.27
**Goal:** a local cluster gets KEDA and (when declared) metrics-server like the other operators and reports its metrics source; bootstrap
waits for KEDA's CRD; new gitops repos ask `resource_metrics`; a cluster repo knows a queue-triggered system needs KEDA.

**Implementation notes:**
- `local-cluster.sh`: header lines for `KEDA_VERSION`, `WITH_KEDA`, `METRICS_SERVER_VERSION`, `WITH_METRICS_SERVER`; `rev_of` defaults
  (2.19.0, 3.14.0) and auto modes from `operators/apps/keda.yaml` / `metrics-server.yaml`; `--k3s-arg "--disable=metrics-server@server:*"`
  only when creating a cluster with `WITH_METRICS_SERVER=1`; the k3s `HelmChart`s with `WITH_ARGO=0`; with Argo CD the waits in the
  operators block and both flags in its condition; the bounded metrics wait and warning; `WITH_SYSTEM=0` behaves like the other operator
  flags. Every wait bounded and naming what it waits for.
- Run `python3 scripts/sync-template-copies.py` so the cluster-gitops copy is byte-equal; commit both.
- `bootstrap.sh`: `keda) crd=scaledobjects.keda.sh ;;` and the header comment.
- `copier.yml`: the `resource_metrics` question exactly as designed, after `cluster_server`.
- `check.py` `needs`: `ops.add("keda")` when `system["cfg"]["autoscaling"][env] == "keda"`.
- `templates/cluster-gitops/scripts/render.py --crds`: skip an operator whose `crd` is `None`.

**Done when:** the local-cluster tests in 115–119 style (flag parsing, the HelmCharts, defaults from the operator files, the k3s argument
only with metrics-server), the cluster check test for a KEDA system, the `--crds` test with `metrics-server` listed and the copier question
test pass; `sync-template-copies.py --check` and `shellcheck` are green.

## t10 — plugins and the CHANGELOG entry

**Files:** plugins/component/commands/set.md, plugins/component/README.md, plugins/component/.claude-plugin/plugin.json, plugins/system/commands/status.md, plugins/system/README.md, plugins/system/.claude-plugin/plugin.json, plugins/platform/commands/doctor.md, plugins/platform/README.md, plugins/platform/.claude-plugin/plugin.json, .claude-plugin/marketplace.json, docs/CHANGELOG.md
**Covers:** AC-120.5, AC-120.18, AC-120.22
**Goal:** the commands describe scaling where users meet it; the release is announced as minor and not breaking.

**Implementation notes:**
- `component/commands/set.md`: `--replicas` is refused on a scaled instance or component (name the key to remove; `scale` is edited in
  `system.yaml`, there are no scale flags); description unchanged unless needed (under 260 characters). README likewise; 1.2.0 → 1.3.0 in
  the manifest and the catalog.
- `system/commands/status.md`: a scaled instance's cell shows `replicas <n> (<min>–<max>)`, `?` when the cluster cannot be read.
  README likewise; 1.3.0 → 1.4.0.
- `platform/commands/doctor.md`: the rows `operator keda` (queue-triggered instances), `operator metrics-server`, `resource metrics`.
  README likewise; 1.1.0 → 1.2.0.
- CHANGELOG `## [Unreleased]`: a new 120 entry **above** the 119 entry, which stays untouched: `scale` (spec 120, ADR-066/067), the four
  triggers, zero only for queues, Argo CD's ignore rule, KEDA 2.19.0 and metrics-server 3.14.0 as operators, the `resource_metrics`
  answer (default `provided`), the two "allowed:" key lists that gain `scale`, the e2e job limit of 90 minutes, plugins `component`
  1.3.0, `system` 1.4.0, `platform` 1.2.0. Not BREAKING.

**Done when:** `devbox run validate` and the version-match loop of `devbox run quality` are green and the AC-120.5/AC-120.18/AC-120.22
plugin-doc tests pass.

## t11 — Docs

**Files:** docs/DOMAIN-MODEL.md, docs/CLUSTERS.md, docs/USER-JOURNEY.md, site/src/content/docs/concepts/domain-model.md
**Covers:** AC-120.24
**Goal:** users can declare scaling on a component or an instance and know what the platform renders, installs and shows.

**Implementation notes:**
- `DOMAIN-MODEL.md`: `scale` in the keys-table rows of the service/website component and of `components.<c>.instances.<env>`; a section
  "Scaling an instance" with everything design.md (Contract: docs) lists and one YAML example per trigger form (`cpu`, `memory`,
  `consumes`, `cache`). Leave the first YAML block under "One file per system" as it is (AC-114.71's test parses it) and keep the needles of
  the 115–119 doc tests.
- `CLUSTERS.md`: `keda` (needed by queue-triggered instances) and `metrics-server` (optional, for clusters without resource metrics)
  among the operators a cluster repo may list.
- `USER-JOURNEY.md`: a row "Scale an instance on load or on a queue" next to "Events between components".
- Site `concepts/domain-model.md`: `scale` as an Instance property in short, linking the guide.
- `python3 scripts/check-links.py` stays green.

**Done when:** the AC-120.24 doc test (the four forms, the component default, exclusivity, `autoscaling` derived) passes and the 114–119
doc tests stay green.

## t12 — e2e: scaling in the cluster

**Files:** tests/e2e/run.sh, .github/workflows/e2e.yml
**Covers:** AC-120.5, AC-120.6, AC-120.10, AC-120.12, AC-120.13, AC-120.14, AC-120.15, AC-120.17, AC-120.19, AC-120.20, AC-120.21, AC-120.22, AC-120.23, AC-120.25, AC-120.27
**Goal:** AC-120.23 and the cluster halves end to end, as design.md (Contract: e2e) lists, failing with the step's name. The scaling steps
take at most 13 minutes in the log; KEDA at cluster-up and the worker image at most 1.5 minutes more; say so in the header comment.

**Implementation notes:**
- `.github/workflows/e2e.yml`: the e2e job's `timeout-minutes` 75 → 90 (about 60 minutes before this spec, about 74.5 after; the
  scale-down cannot be shortened below the 5 minutes the spec fixes).
- Cluster-up (the `local-cluster.sh up` line) gets `WITH_KEDA=1`: no component uses KEDA then, so `operators/apps/keda.yaml` is checked only
  in the declare step. "Build and push the images" builds `e2e-worker:latest` from a context directory written into `$work` (FROM the
  nats probe image), pushed like the others. Header comment: the scaling steps, their ACs and the budget.
- Steps with `sstep`/`sfail` (like `nstep`/`nfail`) after spec 119's doctor step, before "resource remove bus is refused". Before every
  `cplat` command that writes, commit if the tree is dirty; one Python edit per system.yaml change, render, commit.
- Reuse spec 119's helpers (`apply_py` for the bus addon, `nrun` with a regenerated `natsenv-e2e-api.json`, `jsz`/`jsz_wait`, `secret_val`)
  and spec 118's `crun`; every wait bounded (seconds named in the failure), long commands streamed (`tee /dev/stderr`), every kind by its
  full name (`scaledobjects.keda.sh`, `triggerauthentications.keda.sh`, `horizontalpodautoscalers.autoscaling`, `deployments.apps`,
  `helmcharts.helm.cattle.io`, `apiservices.apiregistration.k8s.io`, `streams.jetstream.nats.io`, `consumers.jetstream.nats.io`,
  `externalsecrets.external-secrets.io`).
- The burst watcher is a background function with its own bound (≤ 600 s, 5 s period) writing to a file in `$work`; the join step waits for
  it with a bound, prints the file, then asserts maximum, `T`, `Z` and `Z − T`. Steps of design.md step 5 run while it runs.
- Doctor and status checks parse JSON and match whole words (`re.search(r"\be2e-worker\b", detail)`), never substrings.
- Clean-up (design.md step 9) leaves exactly what spec 119's remaining steps expect; change no step of 115–119 other than the cluster-up
  line and the image build.

**Done when:** `tests/e2e/run.sh` passes on a local machine with the release candidate, the scaling steps take at most 13 minutes in its
log (KEDA at cluster-up and the worker image at most 1.5 minutes more), and the run is recorded in the verification.

## t13 — amend the spec 114/117/119 assertions that 120 extends

**Files:** tests/cplat/test_system_render_114.py, tests/cplat/test_system_model_114.py, tests/cplat/test_backup_117.py, tests/cplat/test_broker_119.py
**Covers:** AC-120.16, AC-120.21, AC-120.25, AC-120.26
**Goal:** the earlier suites assert 5.x behaviour after spec 120 and nothing else. Each changed line ends with a `# spec 120: …` comment,
and the verification lists them as approved test changes.

**Implementation notes:**
- `test_system_render_114.py` line 353: the allowed list becomes `(allowed: replicas, resources, env, promote, secrets, autonomy, scale)`
  (comment `# spec 124: autonomy; spec 120: scale`).
- `test_system_model_114.py` line 198: `normalize_5` also drops the environment key `autoscaling` (`("operators", "backup", "autonomy",
  "autoscaling")`); line 203: it also drops the instance key `scale` (`k not in ("autonomy", "scale")`).
- `test_backup_117.py` line 696: the `OPERATORS` order list ends with `"nack", "keda", "metrics-server"`.
- `test_broker_119.py` line 1027: `list(r.OPERATORS).index("nack") == 7` replaces `list(r.OPERATORS)[-1] == "nack"` (nack stays the eighth
  entry; the `OPERATOR_OF_TYPE` half is unchanged).
- No other assertion is changed or removed; if another 114–125 test fails only because of `scale`/`autoscaling` keys or the two new
  operators, stop and report it instead of editing it.

**Done when:** the amended tests pass once t1, t3 and t4 are merged, and `git diff` of these files touches only the lines named here.
