---
spec_id: 119-a-message-broker-resource-behind-events
shape: platform
spec_hash: 768a708167a9
summary: "The broker resource type (spec 115's last reserved slot, additive 5.x): type: broker with version (NATS 2.14 or 2.15, default 2.15), replicas (1 or 3), storage (1Gi) and resources per instance; apis.<api>.broker binds an events API (default: the system's only broker; none: a render note, the API stays unbound so 5.0 systems render byte-identically); providers and consumers use the broker implicitly and get NATS_URL, NATS_USER, NATS_PASSWORD from their own Secret <system>-<name>-<component>-app, NATS_INBOX_PREFIX and EVENTS_<API>_STREAM/_SUBJECT_PREFIX/_CONSUMER; each in-cluster instance is the official nats chart (pinned 2.15.1, image per minor line) as a nested Argo CD application plus generated users with subject rights, a NACK Account, a Stream <system>-<api> per API (7 days) and a durable pull Consumer per consuming component (explicit ack, 30 s), none of which a render or sync deletes; NACK 0.35.0 joins the versions table as a platform operator (operators/, cluster repos, local-cluster.sh WITH_NACK, bootstrap, doctor); external brokers read url/user/password per component from the secret store and the render prints the streams and consumers to create; model, model show, /api:list, /resource:add|remove, doctor rows, docs with one Python example, ADR-065 and an e2e proof of delivery, redelivery and refusals follow"
tasks:
  - id: t1
    title: render.py — broker schema and checks, apis.<a>.broker (events only), binding (explicit, only broker, several brokers, none = unbound), effective uses, uses/env checks, object clashes, renderer API with defaults, PLANNED_TYPES empty
    files: [templates/gitops-app/scripts/render.py, templates/cluster-gitops/scripts/system_render.py]
    covers: [AC-119.1, AC-119.2, AC-119.3, AC-119.5, AC-119.6, AC-119.7, AC-119.8, AC-119.24]
    parallel_safe: true
    depends_on: []
  - id: t2
    title: render.py — versions table (NATS_CHART, NATS_IMAGES, BROKER_VERSIONS, OPERATORS nack, OPERATOR_OF_TYPE), TYPES["broker"], broker_files (generator, user and NACK Secrets, nested nats Application, Account, Streams, Consumers), addon set retry, operators/apps/nack.yaml
    files: [templates/gitops-app/scripts/render.py, templates/cluster-gitops/scripts/system_render.py]
    covers: [AC-119.1, AC-119.2, AC-119.3, AC-119.9, AC-119.10, AC-119.12, AC-119.16, AC-119.20, AC-119.21, AC-119.22, AC-119.23, AC-119.24]
    parallel_safe: false
    depends_on: [t1]
  - id: t3
    title: render.py — component variables (per-component Secret, EVENTS_*, NATS_INBOX_PREFIX), external broker ExternalSecrets per component, render notes (unbound APIs, external names, retired streams and consumers), stale broker files, docstring
    files: [templates/gitops-app/scripts/render.py, templates/cluster-gitops/scripts/system_render.py]
    covers: [AC-119.6, AC-119.7, AC-119.11, AC-119.12, AC-119.14, AC-119.17, AC-119.24]
    parallel_safe: false
    depends_on: [t2]
  - id: t4
    title: model — Api.broker, implicit broker uses, broker sizing, ResourceInstance.broker (address, monitoring, users, streams with consumers), JSON keys
    files: [scripts/cplat/model.py]
    covers: [AC-119.3, AC-119.15, AC-119.17]
    parallel_safe: true
    depends_on: []
  - id: t5
    title: cplat model show and /api:list — broker of each events API, broker instance lines
    files: [scripts/cplat/modelcmd.py, scripts/cplat/apilist.py]
    covers: [AC-119.15]
    parallel_safe: true
    depends_on: [t4]
  - id: t6
    title: cplat resource add <name> --type broker [--version] [--replicas] [--external], remove refused while an events API is bound, broker texts, TYPE_KEYS and BROKER_VERSIONS mirrors
    files: [scripts/cplat/addon.py]
    covers: [AC-119.4, AC-119.17]
    parallel_safe: true
    depends_on: []
  - id: t7
    title: doctor — operator nack row (operators owner included) and one broker <name> (<env>) row per in-cluster broker instance (nats chart and server image vs the table)
    files: [scripts/cplat/doctor.py]
    covers: [AC-119.22, AC-119.23]
    parallel_safe: true
    depends_on: [t2]
  - id: t8
    title: local-cluster.sh WITH_NACK/NACK_VERSION (+ its cluster-gitops copy), bootstrap.sh waits for the NACK CRD, cluster check needs external-secrets for a broker
    files: [templates/gitops-app/scripts/local-cluster.sh, templates/cluster-gitops/scripts/local-cluster.sh, templates/gitops-app/scripts/bootstrap.sh, templates/cluster-gitops/scripts/check.py]
    covers: [AC-119.19, AC-119.22, AC-119.23]
    parallel_safe: true
    depends_on: []
  - id: t9
    title: resource plugin 1.5.0 and api plugin 1.1.0 (commands, READMEs, manifests, catalog) and the CHANGELOG [Unreleased] entry
    files: [plugins/resource/commands/add.md, plugins/resource/commands/remove.md, plugins/resource/README.md, plugins/resource/.claude-plugin/plugin.json, plugins/api/commands/list.md, plugins/api/README.md, plugins/api/.claude-plugin/plugin.json, .claude-plugin/marketplace.json, docs/CHANGELOG.md]
    covers: [AC-119.4, AC-119.15]
    parallel_safe: true
    depends_on: []
  - id: t10
    title: Docs — DOMAIN-MODEL.md (broker, binding, environment contract, rights, removal, external, one Python example), USER-JOURNEY.md, BACKUP-AND-RESTORE.md, CLUSTERS.md and the site's resources page
    files: [docs/DOMAIN-MODEL.md, docs/USER-JOURNEY.md, docs/BACKUP-AND-RESTORE.md, docs/CLUSTERS.md, site/src/content/docs/concepts/addons.md]
    covers: [AC-119.14, AC-119.17, AC-119.25]
    parallel_safe: true
    depends_on: []
  - id: t11
    title: e2e — a broker with two events APIs in dev; NACK and pins, Secrets and /jsz contract, delivery within 30 s, delivery after a stopped consumer, no redelivery after ack, refusals, doctor rows, remove refused, retired names printed while the stream stays, manual cleanup
    files: [tests/e2e/run.sh, .github/workflows/e2e.yml]
    covers: [AC-119.4, AC-119.9, AC-119.10, AC-119.11, AC-119.12, AC-119.13, AC-119.14, AC-119.16, AC-119.19, AC-119.20, AC-119.21, AC-119.22]
    parallel_safe: false
    depends_on: [t3, t6, t7, t8]
  - id: t12
    title: Amend the spec 115/116/117/118 assertions that 119 extends (no planned type left, the --version text, the --type help, the broker add, OPERATORS order, the resource plugin version)
    files: [tests/cplat/test_resources_115.py, tests/cplat/test_resources_115_cmds.py, tests/cplat/test_bucket_116.py, tests/cplat/test_bucket_116_cmds.py, tests/cplat/test_backup_117.py, tests/cplat/test_backup_117_cmds.py, tests/cplat/test_cache_118.py, tests/cplat/test_cache_118_cmds.py]
    covers: [AC-119.4, AC-119.22]
    parallel_safe: true
    depends_on: []
---

# Plan — 119 A message broker resource behind events APIs

The contract (schema, error texts, binding, rendered documents with key order, chart values, Secrets and rights, variables, pins, render
notes, CLI texts, model, `/api:list`, doctor, local cluster, docs example, e2e) is in [design.md](design.md). The decision that outlives
this spec is [ADR-065](../../adr/065-a-broker-is-nats-jetstream-with-declared-streams-and-per-component-users.md). It builds on spec 115
(ADR-057/058), 116 (ADR-059), 117 (ADR-061/062: broker data stays in the environment backup, nothing changes there), 118 (ADR-064:
the generated-once password pattern, `PLANNED_TYPES`, `TYPE_KEYS`) and 125 (ADR-060: `OPERATORS` shared with cluster repos). Levels:
t1, t4, t6, t8, t9, t10, t12 → t2, t5 → t3, t7 → t11.

`render.py` changes in three sequential tasks (t1 → t2 → t3). Each ends with `python3 scripts/sync-template-copies.py`, so
`templates/cluster-gitops/scripts/system_render.py` stays byte-equal to it (`--check` runs in CI), which is why each lists the copy;
t8 runs the same script for `local-cluster.sh` and lists that copy. Every other task owns its files. Never edit
`scripts/cplat/assets/render_v4.py`. Every 5.x `system.yaml` without a broker, with or without events APIs, must render
byte-identically; the 114–118 suites, amended only by t12, prove that. `compose.py`, `status.py`, `envrestore.py`, `backup_files` and
the Kyverno policy do not change.

**Spec contradiction resolved by default (design.md, "Decisions taken by default" 1):** AC-119.6 says a render with an events API and
no broker fails; AC-119.24 and the Problem section say a 5.0 `system.yaml` renders byte-identically, and 5.0 systems may declare events
APIs. The plan builds the compatible reading (unbound API, a render note naming the API and `/resource:add <name> --type broker`) and
the spec needs a changelog line saying so before the acceptance tests of AC-119.6 are written.

## t1 — render.py: broker schema, checks and binding

**Files:** templates/gitops-app/scripts/render.py, templates/cluster-gitops/scripts/system_render.py
**Covers:** AC-119.1, AC-119.2, AC-119.3, AC-119.5, AC-119.6, AC-119.7, AC-119.8, AC-119.24
**Goal:** `type: broker` and `apis.<a>.broker` are accepted with their keys and refused in every invalid form with the texts of
design.md (Render errors); `load_system` returns the broker's effective values, `cfg["events"]` and every service's effective `uses`.
Nothing is rendered for a broker yet.

**Implementation notes:**
- `PLANNED_TYPES = {}` (the "not available yet" branch stays, dead). Add `BROKER_KEYS`, `BROKER_INSTANCE_KEYS`, `BROKER_SIZING_KEYS =
  ["version", "replicas", "storage", "resources"]`, `BROKER_VERSIONS = ("2.14", "2.15")`, `BROKER_SUFFIXES = ("-headless", "-config",
  "-nack", "-password")`, `BROKER_DEFAULT_RESOURCES`, `EVENTS_API_NAME` (the DNS-label pattern). Other constants keep names and values.
- `validate_resource`: a broker branch next to bucket and cache (key lists; external-sizing texts are 115's generic "an external
  resource runs nothing"); the `backup`-on-external-instance check only for `type: database`; `check_remote` takes the allowed
  placeholders (a broker adds `component`); external `store_key` formatted with `component="{component}"` so the placeholder survives.
- New `check_broker(r, rc, inst, external)` after the `remote`/`secretStore` checks: version (only if some environment is in-cluster;
  a float or digit string read as its text), then per `<where>` replicas, storage, resources; the generic replicas loop skips brokers.
  The normalised envs as in design.md (Renderer API).
- `validate_apis`: `broker` allowed only on events APIs (AC-119.8 text before the unknown-key check); unknown-key text `(allowed: type,
  broker)` for events APIs, 114's `(allowed: type)` for the others.
- New `bind_events(doc, comps, resources) -> dict` after `validate_resources`: the three binding texts in design.md's order, the
  DNS-label rule for bound APIs; returns `cfg["events"]` (unbound = `"broker": None`).
- `object_names(system, r, typ, users=())` and `check_resource_clashes`: broker suffixes plus `<n>-<c>-app` per participant (any
  non-library component providing or consuming an API the broker carries); the connection map gains those names.
- `validate_uses`: the AC-119.7 refusal for a broker listed in `uses` that carries none of the component's APIs; the env clash check
  covers `NATS_*` (prefixed as 115), `EVENTS_<API>_*` and `NATS_INBOX_PREFIX`.
- `load_system` builds the effective `uses` (declared non-broker resources in order, then bound brokers by `provides` then `consumes`,
  each once) for every service, external components included, and adds `cfg["events"]`.
- Rendering a used broker may still fail until t2 (`addon_files` has no broker branch); tests of this task use validation only.
- Run `python3 scripts/sync-template-copies.py` before committing.

**Done when:** the render-error tests of AC-119.1, AC-119.2, AC-119.3 (defaults in `load_system`), AC-119.5, AC-119.6 (several brokers;
the unbound case renders), AC-119.7 (refusal; listing changes `uses` order nothing) and AC-119.8 pass; AC-119.24's byte-identity tests
(full5, rich5, db-bucket, a cache system and a system with an events API and no broker, digests taken from `main` before t1) pass; the
114–118 render suites stay green after t12.

## t2 — render.py: versions table and the in-cluster broker instance

**Files:** templates/gitops-app/scripts/render.py, templates/cluster-gitops/scripts/system_render.py
**Covers:** AC-119.1, AC-119.2, AC-119.3, AC-119.9, AC-119.10, AC-119.12, AC-119.16, AC-119.20, AC-119.21, AC-119.22, AC-119.23, AC-119.24
**Goal:** each environment where a running component provides or consumes an API of an in-cluster broker gets the documents of design.md
(in-cluster broker instance); `operators/apps/nack.yaml` appears exactly where design.md says; nothing changes for other systems.

**Implementation notes:**
- Versions table next to `VALKEY_IMAGES`: `NATS_CHART`, `NATS_IMAGES` (comment with the image pattern), `OPERATORS["nack"]` appended
  last, `OPERATOR_OF_TYPE["broker"] = "nack"`; `TYPES["broker"]` as designed. Before committing, re-check the Helm index (newest `nats`
  and `nack` charts, the `nack` appVersion) and Docker Hub (`nats` `2.15.x-alpine`, `2.14.x-alpine`); update the pins and the design's
  "Verified" paragraph in the same PR if they moved.
- `addon_files` gains `server` (from `render_app`'s `cluster_server`) and dispatches `broker` to `broker_files(app, name, env, cfg,
  services, server)` returning `password-generator.yaml`, `nack-secret.yaml`, `externalsecret-<c>.yaml` per user, `server.yaml`,
  `account.yaml`, `stream-<api>.yaml`, `consumer-<api>.<c>.yaml` and `kustomization.yaml`, with key order, labels, waves and annotations
  exactly as designed; the user list, the publish lists (both ack forms) and the container variables in user order.
- `replicas: 3` renders `config.cluster: {enabled: true, replicas: 3}` and `replicas: 3` on every Stream; `replicas: 1` renders
  `{enabled: false}` and `replicas: 1`.
- The `addons` ApplicationSet gets `retry: RETRY` when its group holds a broker (next to the backup condition); others unchanged.
- `external_secrets` (115) skips brokers: their per-component ExternalSecrets come in t3.
- `operator_files` needs no new code beyond `OPERATOR_OF_TYPE` (it reads the effective `uses`); confirm with fixtures: in-cluster
  broker → `operators/apps/nack.yaml`; `operators: owner` in that environment or an external broker → none.
- Confirm with a fixture that spec 117's Schedule names no broker and that every broker document and the chart values carry
  `app.kubernetes.io/name: <name>` (`nameOverride`).
- Run `python3 scripts/sync-template-copies.py` before committing.

**Done when:** the render tests of AC-119.1 (one server per environment with a running participant), AC-119.2 (cluster mode and stream
replicas for 3), AC-119.3 (defaults in the chart values), AC-119.9 (stream name, subjects, 168h), AC-119.10 (consumer per consuming
instance, explicit ack, 30s, none without an instance), AC-119.12 (users, publish and subscribe lists), AC-119.16 (monitor port on the
Service), AC-119.20 (exact chart and image pins, no floating tag), AC-119.21 (nats chart as an Application, Streams and Consumers in the
tree), AC-119.22 and AC-119.23 (render half: `nack.yaml` only where needed, never with `operators: owner`) pass; byte-identity holds.

## t3 — render.py: component variables, external brokers, notes

**Files:** templates/gitops-app/scripts/render.py, templates/cluster-gitops/scripts/system_render.py
**Covers:** AC-119.6, AC-119.7, AC-119.11, AC-119.12, AC-119.14, AC-119.17, AC-119.24
**Goal:** providers and consumers get the variables of design.md (what a component gets); external broker instances get their
per-component ExternalSecrets; the render prints the notes of design.md and cleans stale broker files.

**Implementation notes:**
- `addon_env`: for a broker the `secretKeyRef` name is `<app>-<b>-<svc>-app`; other types unchanged. `deployment` adds `EVENTS_*` and
  `NATS_INBOX_PREFIX` to the literal dict (sorted with the rest); unbound APIs add nothing.
- New `broker_secrets(app, env, services, cfg)` for external broker instances: one ExternalSecret per non-external participant with an
  instance in `env`, file `externalsecret-<app>-<b>-<c>-app.yaml` in its overlay, store key with `{component}` filled.
- Notes: `render_app` returns them next to the files (or a module-level collector reset per run); `main` prints, before the final line
  and also with `--check`: unbound events APIs, external broker streams and consumers, then retired streams and consumers read from the
  stale files (and from the YAML files inside a stale broker directory) before they are deleted. Exact texts and order in design.md.
- `stale_paths`: inside a wanted broker directory, files matching `^(stream-.+|consumer-.+|externalsecret-.+)\.yaml$` that are not
  rendered any more are stale; database rules unchanged.
- Docstring: the `resources:` comment line (`database, bucket, cache, broker`), a broker example with its defaults and the `apis:`
  example with `broker:`.
- Run `python3 scripts/sync-template-copies.py` before committing.

**Done when:** the render tests of AC-119.11 (variables, values, order, per-component Secret, prefix rule with two brokers, a library
and an external component), AC-119.7 (listing the broker changes no byte), AC-119.12 (the variables of a consumer never name another
component's Secret), AC-119.14 (removing a consumer or an API removes the files, prints the designed notes, keeps the others), AC-119.17
(external: no addon directory, per-component ExternalSecrets with the default and a custom path, the printed stream and consumer
names) and the AC-119.6 note pass; byte-identity holds.

## t4 — model: brokers

**Files:** scripts/cplat/model.py
**Covers:** AC-119.3, AC-119.15, AC-119.17
**Goal:** the model knows which broker carries each events API, which components use it implicitly, and each broker instance's
address, monitoring endpoint, users, streams and consumers.

**Implementation notes:**
- `Api.broker` (design.md rule; lenient: a `broker:` naming no broker resource gives `None`).
- `_component` keeps declared non-broker resources; `build` appends the bound brokers per component (provides then consumes), so
  resource instances, `used_by` and `relations` include implicit users.
- `_broker_sizing(conf, env)`: version as text (a float `2.15` → `"2.15"`), default `"2.15"`; replicas int default 1; storage default
  `"1Gi"`. External: `{}`.
- `ResourceInstance.broker: dict | None = None` filled for brokers as designed (`secret` `None`); users and consumers only for
  components with an instance in that environment; store keys formatted per component for external instances.
- `to_dict`: the `broker` key only on broker resource instances and on events APIs; schema stays 2.

**Done when:** the model tests of AC-119.15 (JSON per instance: environment, address, monitoring, streams with subject prefix and
consumers) and AC-119.17 (external: `None` address, names listed) pass, and the renderer–model agreement tests of AC-114.70/AC-115.15
pass with a broker fixture (the same resource instances as the renderer).

## t5 — model show and /api:list

**Files:** scripts/cplat/modelcmd.py, scripts/cplat/apilist.py
**Covers:** AC-119.15
**Goal:** the text and JSON outputs show the broker of each events API and each broker instance's details.

**Implementation notes:**
- `modelcmd.render`: an events API line ends with `  broker <b>` when bound; a broker instance line is followed by the address,
  users and stream lines of design.md. Other lines unchanged.
- `apilist`: the text suffix `  broker <b>` for bound events APIs; `--json` adds `"broker"` to events APIs only (114's tests stay green).

**Done when:** the AC-119.15 command tests for `cplat model show` (text and `--json`) and `cplat api list` (text and `--json`) pass and
the 114 tests of `api list` stay unchanged and green.

## t6 — cplat resource add/remove for brokers

**Files:** scripts/cplat/addon.py
**Covers:** AC-119.4, AC-119.17
**Goal:** `/resource:add <name> --type broker [--version V] [--replicas N] [--external [--path P]]` and `/resource:remove` behave as in
design.md (`cplat resource`); every refusal happens before anything is written.

**Implementation notes:**
- `PLANNED_TYPES = {}`; `TYPE_KEYS["broker"] = "url, user, password"`; `BROKER_VERSIONS` mirror (docstring names render.py as the source);
  help texts as designed; new `--replicas` (string parsed as int).
- Checks: the changed `--version` text, `--replicas` rules, broker version validation; database checks and texts otherwise unchanged.
- Entries: in-cluster `{"type": "broker"}` plus `version` (a string) and `replicas` when given; external stays the generic form.
- Next steps per type as designed (the broker replaces 115's `let components use it` line); external keys formatted with
  `component="<component>"`.
- `remove`: the bound-API refusal first (explicit `broker:` or the only broker), then 115's checks; the broker `will_do` lines.

**Done when:** the AC-119.4 command tests (entry with and without flags, rendered in the same run, `--pr` path, every refusal names its
reason and writes nothing, remove refused naming the APIs) and the command half of AC-119.17 (external entry, store keys with
`<component>`, the create-streams step) pass; the 115/116/118 command tests stay green after t12.

## t7 — doctor: NACK and brokers

**Files:** scripts/cplat/doctor.py
**Covers:** AC-119.22, AC-119.23
**Goal:** `/platform:doctor` warns about a missing or different NACK and about each broker instance whose chart or image differs from
the table, in environments with and without `operators: owner`.

**Implementation notes:**
- `check_operators` gains `("nack", "nack")`; `_operator_needs` maps `nack` to in-cluster broker instances. 115's row texts apply.
- New `check_brokers(repo)` after `check_operators` in the gitops-app branch, only with `kubectl`: rows and texts of design.md;
  expected values from render.py (`NATS_CHART`, `NATS_IMAGES`; extend `_operators()` into a loader that returns the module).
- The cluster-repo branch (`check_cluster`) needs no change: it lists `nack` when `cluster.yaml` does.

**Done when:** the AC-119.22/AC-119.23 doctor tests (kubectl faked: NACK installed, missing, different, with and without `operators:
owner`; a broker StatefulSet matching, missing, with another chart or image) pass and the 115/117/125 doctor tests stay green.

## t8 — local cluster, bootstrap and cluster check

**Files:** templates/gitops-app/scripts/local-cluster.sh, templates/cluster-gitops/scripts/local-cluster.sh, templates/gitops-app/scripts/bootstrap.sh, templates/cluster-gitops/scripts/check.py
**Covers:** AC-119.19, AC-119.22, AC-119.23
**Goal:** a local cluster gets NACK exactly like the other operators; bootstrap waits for its CRD; a cluster repo knows a broker needs
External Secrets.

**Implementation notes:**
- `local-cluster.sh`: header lines for `NACK_VERSION` and `WITH_NACK`; `nack_file=operators/apps/nack.yaml`, default via `rev_of`
  (`0.35.0`), auto mode; the k3s `HelmChart` `nack` with `WITH_ARGO=0` (wait up to 180 s for `streams.jetstream.nats.io`, then
  `rollout status deploy -l app.kubernetes.io/name=nack -n nack --timeout=300s`); with Argo CD, the wait in the operators block and
  `with_nack` in its condition; `WITH_SYSTEM=0` behaves like the other operator flags.
- Run `python3 scripts/sync-template-copies.py` so the cluster-gitops copy is byte-equal; commit both.
- `bootstrap.sh`: `nack) crd=streams.jetstream.nats.io ;;` and the header comment.
- `check.py` `needs`: `if typ in ("bucket", "broker"): ops.add("external-secrets")`.

**Done when:** the local-cluster tests of 115–117 style (flag parsing, HelmChart document, defaults from `operators/apps/nack.yaml`) and
the cluster check test for a broker pass; `sync-template-copies.py --check` and `shellcheck` are green.

## t9 — plugins and the CHANGELOG entry

**Files:** plugins/resource/commands/add.md, plugins/resource/commands/remove.md, plugins/resource/README.md, plugins/resource/.claude-plugin/plugin.json, plugins/api/commands/list.md, plugins/api/README.md, plugins/api/.claude-plugin/plugin.json, .claude-plugin/marketplace.json, docs/CHANGELOG.md
**Covers:** AC-119.4, AC-119.15
**Goal:** the commands describe the broker; the release is announced as minor and not breaking.

**Implementation notes:**
- `add.md` description (under 260 characters, keeps `--type database|bucket|cache`): `Declare a resource of the system in system.yaml.
  Usage: /resource:add <name> --type database|bucket|cache|broker [--version V] [--replicas N] [--storage S] [--versioning] [--external
  [--path P]]`. Body: the broker (NATS with JetStream), its keys and defaults, binding through `apis.<api>.broker`, the variables
  including `EVENTS_ORDERS_STREAM`, the per-component Secret, the external store keys with `{component}`, NACK as an operator; no type is
  reserved any more.
- `remove.md`: refused while an events API is bound; a removed broker keeps its server, volumes, streams and Secrets until deleted by hand.
- `resource` README types line names `broker`; manifest description `(databases, buckets, caches, brokers)`; 1.4.0 → 1.5.0 in the
  manifest and the catalog.
- `api` `list.md`: the line format with `  broker <b>` for bound events APIs; README likewise; 1.0.0 → 1.1.0 in the manifest and catalog.
- CHANGELOG `## [Unreleased]`: a new 119 entry **above** the 118 entry, which stays untouched (its `resource` 1.4.0 line too): the broker
  (spec 119, ADR-065), binding and variables, NACK installed as an operator, the pins (`nats` chart 2.15.1, `nats:2.14.9-alpine`,
  `nats:2.15.2-alpine`, `nack` chart 0.35.0 / controller 0.24.0), unbound events APIs only get a note, plugins `resource` 1.5.0 and `api`
  1.1.0. Not BREAKING.

**Done when:** `devbox run validate` and the version-match loop of `devbox run quality` are green, and the amended version assertions
(t12) pass.

## t10 — Docs

**Files:** docs/DOMAIN-MODEL.md, docs/USER-JOURNEY.md, docs/BACKUP-AND-RESTORE.md, docs/CLUSTERS.md, site/src/content/docs/concepts/addons.md
**Covers:** AC-119.14, AC-119.17, AC-119.25
**Goal:** users can declare a broker, bind events APIs, use the environment contract from code, run an external broker and know what
stays after a removal.

**Implementation notes:**
- `DOMAIN-MODEL.md`: keys table rows for broker `resources.<name>` and `.instances.<env>` and `apis.<api>.broker`; replace "`broker`,
  which is reserved: spec 119 delivers it" by the built broker (spec 119); a broker section: NATS with JetStream, binding rules (explicit,
  only broker, several, none = a note), implicit use, the variables and their values, `NATS_INBOX_PREFIX` and why, the Secret
  `<system>-<name>-<component>-app` as the contract spec 120 relies on, rights, stream and consumer names, 7 days, 30 s, pull consumers,
  the monitoring endpoint (`/jsz`), removal (nothing deleted, how a person deletes a stream and a consumer), the external broker (store
  keys, the printed names), replicas and storage changes, downgrades before spec 121, and exactly the Python example of design.md. Keep
  the needles of AC-115.16's and 118's doc tests (`spec 116`, `spec 118`, `spec 119`, cache "not backed up", …).
- `USER-JOURNEY.md`: "Events between components" row next to "A cache".
- `BACKUP-AND-RESTORE.md`: broker volumes are in the environment backup (nothing to configure); keep AC-117.25's and 118's needles.
- `CLUSTERS.md`: `nack` among the operators a cluster repo may list, needed by in-cluster brokers.
- Site `concepts/addons.md`: the broker row and its variables.
- `python3 scripts/check-links.py` stays green.

**Done when:** the AC-119.25 doc test (one Python code block that connects with `NATS_URL`, `NATS_USER`, `NATS_PASSWORD`,
`NATS_INBOX_PREFIX`, publishes under `EVENTS_<API>_SUBJECT_PREFIX` and fetches through `EVENTS_<API>_CONSUMER`; no template ships
publisher or subscriber code) and the AC-119.14/AC-119.17 doc tests pass; the 115–118 doc tests stay green.

## t11 — e2e: a broker in the cluster

**Files:** tests/e2e/run.sh
**Covers:** AC-119.4, AC-119.9, AC-119.10, AC-119.11, AC-119.12, AC-119.13, AC-119.14, AC-119.16, AC-119.19, AC-119.20, AC-119.21, AC-119.22
**Goal:** AC-119.13 and AC-119.19 end to end, failing with the step's name. The e2e job already runs ~50 of its 60 minutes: the broker
steps must take at most 5 minutes in the log, and NACK at cluster-up plus the probe build at most 1.5 minutes more; say so in the
header comment.

**Implementation notes:**
- `.github/workflows/e2e.yml`: the e2e job's `timeout-minutes` goes from 60 to 75 (the run is near 50 minutes before the broker steps; ~56.5 after).
- Cluster-up (line 132) gets `WITH_NACK=1` (the broker is used only after cluster-up; check `operators/` files only in the broker
  steps). "Build and push the images" also builds and pushes `e2e-natsprobe:1` (`python:3.13-slim`, `pip install nats-py==2.16.0`) the
  way the service images are pushed. Header comment: the broker steps and their ACs.
- Steps after the cache doctor step, before "Write and approve a spec", with `nstep`/`nfail` (like `cstep`/`cfail`). Declare: commit if
  dirty, `cplat resource add bus --type broker` → commit; one Python edit: `apis.orders: {type: events}`, `apis.audit: {type: events}`,
  e2e-api `provides += [orders]`, e2e-web `consumes += [orders]`, `provides += [audit]`; `uv run scripts/render.py`; commit. Assert
  `operators/apps/nack.yaml` pins 0.35.0 and equals the HelmChart `nack` installed by cluster-up, the NACK Deployment image tag is
  0.24.0, `addons/dev/bus/server.yaml` pins chart 2.15.1 and tag `2.15.2-alpine` (AC-119.20, AC-119.22), the expected files exist, and
  `kubectl kustomize overlays/dev/e2e-web` has `NATS_*` from `e2e-bus-e2e-web-app`, `EVENTS_ORDERS_*` (`e2e-orders`, `e2e.orders`,
  `e2e-web`), `EVENTS_AUDIT_*` and `NATS_INBOX_PREFIX=_INBOX.e2e-web` (AC-119.11).
- Apply (no Argo CD): `kubectl kustomize addons/dev/bus` without the `Application` document, applied with `kubectl apply -f -`; the
  `Application` turned into a k3s `helmcharts.helm.cattle.io` `e2e-bus` in `kube-system` (repo, chart, version, `targetNamespace`,
  `valuesContent` = the `valuesObject`). Bounded waits: the three Secrets (120 s; on failure the ExternalSecret events), the
  `statefulsets.apps/e2e-bus` (exists within 120 s, `rollout status --timeout=180s`, streamed), `streams.jetstream.nats.io` `e2e-orders`,
  `e2e-audit` and `consumers.jetstream.nats.io` `e2e-orders.e2e-web` Ready (120 s; on failure `describe` and the NACK log). Component
  overlays are not applied (design.md e2e).
- Contract (AC-119.9, .10, .11, .16, .21): each Secret has `url` `nats://e2e-bus.e2e-dev.svc:4222`, `user` = the component, a 32-character
  password; the Service `e2e-bus` is ClusterIP with 4222 and 8222; `/jsz?accounts=true&streams=true&consumers=true&config=true` (read
  with `wget` inside `e2e-bus-0 -c nats`) shows `e2e-orders` with subjects `["e2e.orders.>"]`, `max_age` 7 days in ns, file storage, and
  consumer `e2e-web` with ack policy explicit and ack wait 30 s.
- Through the components (AC-119.13, AC-119.19), plain probe Pods (`nrun`, bounded like `crun`) with the env list of the rendered
  Deployment, `runAsUser: 1000`, read-only root filesystem, `PYTHONDONTWRITEBYTECODE=1`, running the docs example's calls: P1 (e2e-api)
  publishes m1 and prints its time; C1 (e2e-web) fetches one message within 30 s of P1 (m1), acks; P2 (e2e-api) publishes m2 and m3
  while no consumer runs; `/jsz` shows `num_pending` 2 and `num_ack_pending` 0 (AC-119.16); C2 (e2e-web) fetches exactly m2 and m3 (not
  m1), acks, and a further fetch times out; `/jsz` shows 0 and 0 and `e2e-orders` 3 messages.
- Refusals (AC-119.12), inside C1 and P2 (error callback text `Permissions Violation`): e2e-web publishing on `e2e.orders.created` and
  subscribing to `e2e.orders.>` is refused, publishing on `e2e.audit.done` succeeds; e2e-api subscribing to `e2e.audit.>` and publishing
  on `e2e.audit.x` is refused; the message counts do not move.
- Doctor (AC-119.22): `timeout 180 $cplat platform doctor --repo "$gitops_repo" --json`; rows `operator nack` (ok, 0.24.0) and
  `broker bus (dev)` (ok, `nats chart 2.15.1`, `nats:2.15.2-alpine`).
- Removal (AC-119.4, AC-119.14): `cplat resource remove bus` fails naming `orders, audit` and the tree stays clean; the Python edit
  removes both APIs and their `provides`/`consumes`; the render output (tee'd) holds the notes for stream `e2e-orders`, stream
  `e2e-audit` and durable consumer `e2e-web` of `e2e-orders` in `addons/dev/bus`; commit; `/jsz` still shows `e2e-orders` with 3 messages
  and its consumer; `cplat resource remove bus` succeeds (commit) and `operators/apps/nack.yaml` is gone. Then the e2e deletes the broker
  as a person would (consumers, streams and the account by full kind name, the HelmChart, waiting at most 90 s for `e2e-bus-0` to go,
  the PVC `e2e-bus-js-e2e-bus-0`, the ExternalSecrets, the Secrets and the generator), so the ship and backup steps run as before.
- Name every kind in full (`streams.jetstream.nats.io`, `consumers.jetstream.nats.io`, `accounts.jetstream.nats.io`,
  `statefulsets.apps`, `deployments.apps`, `helmcharts.helm.cattle.io`, `externalsecrets.external-secrets.io`,
  `passwords.generators.external-secrets.io`, `persistentvolumeclaims`); stream long commands; bound every wait and print what it waited
  for; change no step of 115–118.

**Done when:** `tests/e2e/run.sh` passes on a local machine with the release candidate, the broker steps take at most 5 minutes in its
log (cluster-up's NACK and the probe build at most 1.5 minutes more), and the run is recorded in the verification.

## t12 — amend the spec 115–118 assertions that 119 extends

**Files:** tests/cplat/test_resources_115.py, tests/cplat/test_resources_115_cmds.py, tests/cplat/test_bucket_116.py, tests/cplat/test_bucket_116_cmds.py, tests/cplat/test_backup_117.py, tests/cplat/test_backup_117_cmds.py, tests/cplat/test_cache_118.py, tests/cplat/test_cache_118_cmds.py
**Covers:** AC-119.4, AC-119.22
**Goal:** the 115–118 suites assert 5.x behaviour after spec 119 and nothing else. Each changed line ends with a `# spec 119: …`
comment, and the verification lists them as approved test changes.

**Implementation notes:**
- `test_resources_115.py` line 42: the AC-115.2 "not available yet" parametrisation becomes `[]` (no type is planned; pytest reports it
  as skipped); line 183: `PLANNED_TYPES == {}`.
- `test_resources_115_cmds.py` line 138: the parametrisation becomes `[]`.
- `test_bucket_116.py` line 660: `PLANNED_TYPES == {}`; line 663: the parametrisation becomes `[]`.
- `test_bucket_116_cmds.py` line 135: the needle becomes `--version applies to --type database or broker only`; line 161: the
  parametrisation becomes `[]`.
- `test_backup_117.py` line 696: the `OPERATORS` order list ends with `"nack"`.
- `test_backup_117_cmds.py` line 803: `plugin_version("resource") == ("1.5.0", "1.5.0")` (the function name stays).
- `test_cache_118.py` line 679: `PLANNED_TYPES == {}` (the test name on line 677 stays); lines 689–690: an unused broker renders
  (`ok(...)`) and writes no `/addons/` path, instead of the "not available yet" failure.
- `test_cache_118_cmds.py` line 124: the needle becomes `--version applies to --type database or broker only`; line 150: `resource
  type: database, bucket, cache or broker`; line 151: the regex matches `PLANNED_TYPES = {}`; lines 169–170: `rc == 0` without "not
  available yet", and the tree changed (`files(repo) != before`); line 517: `"1.5.0"`.
- No other assertion is changed or removed.

**Done when:** the amended tests pass once t1, t2, t6 and t9 are merged, and `git diff` of these files touches only the lines named here.
