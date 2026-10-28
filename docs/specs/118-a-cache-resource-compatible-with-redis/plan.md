---
spec_id: 118-a-cache-resource-compatible-with-redis
spec_hash: 69274e32de81
summary: "The cache resource type (spec 115's reserved slot, additive 5.x): type: cache with version (Valkey 8 or 9, default 9), memory (256Mi, at least 64Mi), maxmemoryPolicy (allkeys-lru), persistence (false) and storage (1Gi, only with persistence) per instance; type redis or valkey fails naming cache; the TYPES contract REDIS_URL, REDIS_HOST, REDIS_PORT, REDIS_PASSWORD from the Secret <system>-<name>-app (url, host, port, password; prefixed <NAME>_ for two caches); each in-cluster instance is one platform-rendered Valkey StatefulSet (pinned image per major, ClusterIP on 6379, maxmemory 80 % of the memory limit, AOF everysec only with persistence) with a password generated once by External Secrets Operator, no operator, every object labelled so spec 117's backups leave it out; external instances use spec 115's ExternalSecret; /resource:add --type cache, remove, model, compose, docs and the e2e proof follow; a system.yaml without a cache renders byte-identically"
tasks:
  - id: t1
    title: render.py — cache schema and checks (keys, version, memory, maxmemoryPolicy, persistence, storage, external sizing, type redis/valkey text, cache leaves PLANNED_TYPES, object clashes, renderer API with defaults)
    files: [templates/gitops-app/scripts/render.py, templates/cluster-gitops/scripts/system_render.py]
    covers: [AC-118.2, AC-118.3, AC-118.4, AC-118.5, AC-118.22]
    parallel_safe: true
    depends_on: []
  - id: t2
    title: render.py — TYPES["cache"], VALKEY_IMAGES and the in-cluster cache instance (Password generator, ExternalSecret, ClusterIP Service, Valkey StatefulSet with maxmemory, persistence and backup-exclusion labels)
    files: [templates/gitops-app/scripts/render.py, templates/cluster-gitops/scripts/system_render.py]
    covers: [AC-118.3, AC-118.6, AC-118.7, AC-118.8, AC-118.11, AC-118.14, AC-118.17, AC-118.18, AC-118.19, AC-118.20, AC-118.23]
    parallel_safe: false
    depends_on: [t1]
  - id: t3
    title: model — cache sizing (version, memory, maxmemoryPolicy, persistence, storage) on in-cluster cache instances
    files: [scripts/cplat/model.py]
    covers: [AC-118.3]
    parallel_safe: true
    depends_on: []
  - id: t4
    title: cplat resource add <name> --type cache [--external], the redis/valkey hint, cache texts in remove and in the next steps
    files: [scripts/cplat/addon.py]
    covers: [AC-118.1, AC-118.13, AC-118.22]
    parallel_safe: true
    depends_on: []
  - id: t5
    title: component set --uses — help text and the prefix note for caches
    files: [scripts/cplat/compose.py]
    covers: [AC-118.18]
    parallel_safe: true
    depends_on: []
  - id: t6
    title: resource plugin 1.4.0 (add, remove, README, manifest, catalog) and the CHANGELOG [Unreleased] entry
    files: [plugins/resource/commands/add.md, plugins/resource/commands/remove.md, plugins/resource/README.md, plugins/resource/.claude-plugin/plugin.json, .claude-plugin/marketplace.json, docs/CHANGELOG.md]
    covers: [AC-118.1, AC-118.13, AC-118.22]
    parallel_safe: true
    depends_on: []
  - id: t7
    title: Docs — DOMAIN-MODEL.md, USER-JOURNEY.md, BACKUP-AND-RESTORE.md and the site's resources page describe the cache type
    files: [docs/DOMAIN-MODEL.md, docs/USER-JOURNEY.md, docs/BACKUP-AND-RESTORE.md, site/src/content/docs/concepts/addons.md]
    covers: [AC-118.14, AC-118.21]
    parallel_safe: true
    depends_on: []
  - id: t8
    title: e2e — two caches used by e2e-web in dev; contract, auth, maxmemory and eviction, persistence across a pod restart, SET/GET through the component's variables, no cache data in the Velero backup
    files: [tests/e2e/run.sh]
    covers: [AC-118.6, AC-118.7, AC-118.8, AC-118.11, AC-118.14, AC-118.15, AC-118.18, AC-118.19, AC-118.23]
    parallel_safe: false
    depends_on: [t2, t4]
  - id: t9
    title: Amend the spec 115/116/117 assertions that 118 extends (cache no longer planned, the --uses help, the resource plugin version)
    files: [tests/cplat/test_resources_115.py, tests/cplat/test_resources_115_cmds.py, tests/cplat/test_bucket_116.py, tests/cplat/test_bucket_116_cmds.py, tests/cplat/test_backup_117_cmds.py]
    covers: [AC-118.18, AC-118.22]
    parallel_safe: true
    depends_on: []
---

# Plan — 118 A cache resource compatible with Redis

The contract (schema, error texts, rendered documents with key order, Secret, variables, pins, CLI texts, model, status, doctor) is
in [design.md](design.md). The decision that outlives this spec is
[ADR-064](../../adr/064-a-cache-is-a-platform-rendered-valkey-statefulset.md). It builds on spec 115 (ADR-057/058), spec 116
(ADR-059) and spec 117 (ADR-062: the Velero Schedule already leaves out every cache by name). Levels: t1, t3, t4, t5, t6, t7, t9 →
t2 → t8.

`render.py` changes in two sequential tasks (t1 → t2). Each of them ends with `uv run scripts/sync-template-copies.py`, so
`templates/cluster-gitops/scripts/system_render.py` stays byte-equal to it (spec 125; `--check` runs in CI), which is why both list the
copy. Every other task owns its files. Never edit `scripts/cplat/assets/render_v4.py`. Every 5.x `system.yaml` without a cache must
render byte-identically; the 114–117 suites, amended only by t9, prove that. `local-cluster.sh`, `bootstrap.sh`, `operators/`,
`doctor.py`, `status.py`, `modelcmd.py` and the Kyverno policy do not change: a cache needs no operator (AC-118.23).

## t1 — render.py: cache schema and checks

**Files:** templates/gitops-app/scripts/render.py, templates/cluster-gitops/scripts/system_render.py
**Covers:** AC-118.2, AC-118.3, AC-118.4, AC-118.5, AC-118.22
**Goal:** `type: cache` is accepted with its keys and refused in every invalid form with the texts of design.md (Render errors), and
`load_system` returns the cache's effective values with the defaults. Nothing is rendered for a cache yet.

**Implementation notes:**
- `PLANNED_TYPES = {"broker": 119}`. Add `CACHE_KEYS`, `CACHE_INSTANCE_KEYS`, `CACHE_SIZING_KEYS = ["version", "memory",
  "maxmemoryPolicy", "persistence", "storage"]` (top level; an instance's sizing keys are the same without `version`),
  `CACHE_SUFFIXES = ("-app", "-password")`, `CACHE_VERSIONS = (8, 9)`, `MAXMEMORY_POLICIES` (design order), `QUANTITY`,
  `CACHE_MEMORY_MIN = 64 * 1024 ** 2` and a `quantity_bytes(text) -> int` helper (binary and decimal suffixes, fractions floored).
  `REDIS_TYPES = ("redis", "valkey")`. Database and bucket constants keep their names and values.
- `validate_resource`: the `redis`/`valkey` text before 115's "not a resource type" check; select the key, instance-key and sizing
  lists by type (a third branch next to `bucket`); the external-sizing texts for a cache are the "an external cache is sized and
  configured at its provider" forms. Database and bucket texts do not change.
- New `check_cache(r, rc, inst, external)` after the `remote`/`secretStore` checks, in the design's order: version (only when some
  environment is in-cluster), the four value checks per `<where>`, then the two `storage needs persistence` checks.
- The normalised envs of a cache as in design.md (Renderer API), including `maxmemory` = `quantity_bytes(memory) * 4 // 5`.
- `object_names`: a cache uses `CACHE_SUFFIXES`; `broker` keeps `-app`.
- Update the module docstring: the `resources:` comment line (`database, bucket, cache; broker comes with spec 119`) and a cache example
  with its defaults.
- Rendering a used cache may still fail until t2 (`addon_files` has no cache branch); tests of this task use validation only.
- Run `uv run scripts/sync-template-copies.py` before committing.

**Done when:** the render-error tests of AC-118.2, AC-118.4 and AC-118.5, the defaults of AC-118.3 in `load_system`, the render half of
AC-118.22 (`broker` keeps its text, every other 114/115 message unchanged) pass, and the 115/116/117 render suites stay green after t9.

## t2 — render.py: the cache contract and the in-cluster instance

**Files:** templates/gitops-app/scripts/render.py, templates/cluster-gitops/scripts/system_render.py
**Covers:** AC-118.3, AC-118.6, AC-118.7, AC-118.8, AC-118.11, AC-118.14, AC-118.17, AC-118.18, AC-118.19, AC-118.20, AC-118.23
**Goal:** a component that uses a cache gets the four variables (prefixed for two caches); each environment where a running component
uses an in-cluster cache gets the four documents of design.md; an external instance gets 115's ExternalSecret with the four keys; no
operator file appears for a cache.

**Implementation notes:**
- `TYPES["cache"]` exactly as designed; `addon_env`, `variable_names` and `external_secrets` already read `TYPES`.
- `VALKEY_IMAGES` next to `POSTGRES_IMAGES` (comment: matches `^valkey/valkey:\d+\.\d+\.\d+(@sha256:[0-9a-f]{64})?$`). Before
  committing, re-check both tags on Docker Hub's tags API and that no newer patch of 8 or 9 exists; update the pins and the design's
  "Verified" paragraph in the same PR if they moved. Check in the pinned 9 image (`docker run --rm --entrypoint id valkey/valkey:9.1.3
  valkey`, `… sh -c 'pwd; command -v valkey-server valkey-cli sh'`) the assumptions listed in design.md.
- `addon_files` dispatches `cache` to a new `cache_files(app, name, env, conf)` returning `password-generator.yaml`,
  `externalsecret.yaml`, `service.yaml`, `statefulset.yaml` and `kustomization.yaml` with key order, labels, waves and the two
  persistence variants exactly as designed. No secret value in any file; the password comes only from the generator.
- `args` are strings throughout (`"6379"`, `"<maxmemory>"`, `""` after `--save`); `persistence: false` renders neither
  `volumeMounts` nor `volumeClaimTemplates`.
- `operator_files` needs no change (`OPERATOR_OF_TYPE` has no cache): add no entry. `backup_files` needs no change; confirm with a test
  fixture that a cache name is in the Schedule's NotIn list and that every cache document carries `app.kubernetes.io/name: <name>`.
- `stale_paths` already removes addon directories that are no longer wanted; a cache's file set never varies, so nothing new is needed.
- Run `uv run scripts/sync-template-copies.py` before committing.

**Done when:** the render tests of AC-118.3 (defaults in the StatefulSet), AC-118.6 (limit, `--maxmemory` bytes, policy), AC-118.7
(volume only with persistence, AOF args), AC-118.8 (ClusterIP only, no route), AC-118.11 (`--requirepass` from the Secret),
AC-118.14 (labels, NotIn list), AC-118.17 (exact pin per major, no floating tag), AC-118.18 (four variables, prefix rule, shared
Secret), AC-118.19 (generator length 32, `CreatedOnce`, no value in the tree), AC-118.20 (external: four keys, no StatefulSet) and
AC-118.23 (no `operators/` file with or without `operators: owner`) pass. 115/116/117 fixtures render byte-identically.

## t3 — model: cache sizing

**Files:** scripts/cplat/model.py
**Covers:** AC-118.3
**Goal:** an in-cluster cache instance in the model carries the designed `sizing`, so `cplat model show` and its JSON show the defaults.

**Implementation notes:**
- `_cache_sizing(conf, env)`: version (resource's, a digit string read as a number, else 9), memory, maxmemoryPolicy, persistence
  (`is True`), then `storage` only when persistence is true (instance's, else resource's, else `"1Gi"`).
- In `build`, use `_cache_sizing` for `r.type == "cache"`; `{}` when external. Nothing else changes; `modelcmd.py` already prints
  booleans in lower case.

**Done when:** the model tests for cache instances (JSON and `model show` text, with and without persistence, external) pass, and the
renderer–model agreement tests of AC-114.70/AC-115.15 pass with a cache fixture.

## t4 — cplat resource add/remove for caches

**Files:** scripts/cplat/addon.py
**Covers:** AC-118.1, AC-118.13, AC-118.22
**Goal:** `/resource:add <name> --type cache [--external [--path P]]` and `/resource:remove` behave as in design.md (`cplat resource`);
every refusal happens before anything is written.

**Implementation notes:**
- `PLANNED_TYPES = {"broker": 119}`; `--type` help as designed. The module docstring names `--type cache`.
- `--type redis`/`valkey`: the unchanged 114 message with the designed hint (`PlatformError(..., hint=...)`).
- Entries: in-cluster `{"type": "cache"}`; external stays the generic `{type, external: true}` form.
- Next steps and `will_do` texts per type: replace the `bucket`/`database` two-way choices with a per-type lookup (`what` = the type
  name; the external key list from a local `TYPE_KEYS` mirror of render.py's `TYPES`, docstring names the source). Database and bucket
  texts stay byte-identical.

**Done when:** the AC-118.1 command tests (entry without sizing, rendered in the same run, `--pr` path), AC-118.13 (refusal while
used, naming the users, nothing written) and the command half of AC-118.22 (other messages unchanged, the hint) pass; 115/116 command
tests stay green after t9.

## t5 — component set --uses: help and prefix note

**Files:** scripts/cplat/compose.py
**Covers:** AC-118.18
**Goal:** the developer learns which variables a cache gives, and when a second cache prefixes them.

**Implementation notes:**
- The `--uses` help text exactly as designed.
- The prefix-note lookup gains `"cache": ("REDIS_URL", "REDIS_*")`; database and bucket notes unchanged.

**Done when:** the AC-118.18 command-note test (two caches → the prefix note; one cache and one database → none) passes, and
`test_resources_115_more.py` and the 116 compose tests stay green after t9.

## t6 — resource plugin 1.4.0 and the CHANGELOG entry

**Files:** plugins/resource/commands/add.md, plugins/resource/commands/remove.md, plugins/resource/README.md, plugins/resource/.claude-plugin/plugin.json, .claude-plugin/marketplace.json, docs/CHANGELOG.md
**Covers:** AC-118.1, AC-118.13, AC-118.22
**Goal:** the commands describe the cache type; the release is announced as minor and not breaking.

**Implementation notes:**
- `add.md` description (under 260 characters) keeps the substring `--type database|bucket` (a 116 test reads it):
  `Declare a resource of the system in system.yaml. Usage: /resource:add <name> --type database|bucket|cache [--version N] [--storage S] [--versioning] [--external [--path P]]`.
  The body: `cache` is built (Redis-compatible, runs Valkey; "redis" is answered with `cache`), its keys and defaults, the four
  variables and the prefix example `SESSIONS_REDIS_URL`, the four store keys of an external cache (a `rediss://` URL for TLS
  providers), no operator, cache data is not backed up; only `broker` is still reserved (119).
- `remove.md`: a removed in-cluster cache keeps its StatefulSet, volume and Secret until deleted by hand.
- README: the types line names `cache`; manifest description `(databases, buckets, caches)`.
- `resource` 1.3.0 → 1.4.0 in both manifests and the catalog. No other plugin changes.
- CHANGELOG `## [Unreleased]`: a new 118 entry **above** the existing entries there, which stay untouched: the cache resource (spec
  118, ADR-064), the pins (`valkey/valkey:8.1.11`, `valkey/valkey:9.1.3`), "no operator is installed", resource 1.4.0. Not BREAKING.

**Done when:** `devbox run validate` and the version-match loop of `devbox run quality` are green, and the amended AC-117.31 version
assertion (t9) passes.

## t7 — Docs

**Files:** docs/DOMAIN-MODEL.md, docs/USER-JOURNEY.md, docs/BACKUP-AND-RESTORE.md, site/src/content/docs/concepts/addons.md
**Covers:** AC-118.14, AC-118.21
**Goal:** users can read how to declare, size, use and externalise a cache, and that its data is not backed up.

**Implementation notes:**
- `DOMAIN-MODEL.md`: keys table rows for cache `resources.<name>` and `.instances.<env>`; in Semantics replace "`cache` and `broker`,
  which are reserved" by `cache` rendered (spec 118) and `broker` reserved (spec 119); a cache bullet: speaks the Redis protocol, runs
  Valkey and why (BSD licence; Redis 8 only under AGPLv3, RSAL or SSPL), the type is `cache`, not `redis`; keys and defaults
  (`version` 8/9 default 9, `memory` 256Mi and at least 64Mi, `maxmemory` 80 %, `maxmemoryPolicy` allkeys-lru, `persistence` false,
  `storage` 1Gi with persistence); the four variables and the `<NAME>_` prefix (`SESSIONS_REDIS_URL`); the Secret
  `<system>-<name>-app` with `url`, `host`, `port`, `password` as the contract other specs (spec 120) rely on; database `0` shared;
  external store keys; not backed up; no operator. Keep the needles of AC-115.16's test (`spec 116`, `spec 118`, `spec 119`, …).
- `USER-JOURNEY.md`: an "A cache" row next to "A bucket".
- `BACKUP-AND-RESTORE.md`: the existing "cache data is not backed up" sentence names why (caches are left out by name) and that this
  holds with `persistence: true` too; keep AC-117.25's needles.
- Site `concepts/addons.md`: the cache row and variables.
- `python3 scripts/check-links.py` stays green.

**Done when:** the AC-118.21 and AC-118.14 documentation tests pass and the AC-115.16, 116 and AC-117.25 doc tests stay green.

## t8 — e2e: caches in the cluster

**Files:** tests/e2e/run.sh
**Covers:** AC-118.6, AC-118.7, AC-118.8, AC-118.11, AC-118.14, AC-118.15, AC-118.18, AC-118.19, AC-118.23
**Goal:** AC-118.15 end to end in a few minutes, failing with the step's name; the e2e job already runs ~45 of its 60 minutes, so the
cache steps must add at most ~5.

**Implementation notes:**
- Place the steps after "External bucket: completing the store entry…" and before "Ship a spec". Cluster-up is already done and
  gets no new flag (a cache has no operator). Use `cstep`/`cfail` helpers like `bstep`/`bfail` so every failure names its step.
- Declare: start from a clean tree (`[ -z "$(git -C "$gitops_repo" status --porcelain)" ] || commit …`), then `cplat resource add
  sessions --type cache` → commit, `cplat resource add ratelimit --type cache` → commit (cplat refuses a dirty tree); then one
  Python edit (as the existing steps do): `sessions.instances.dev = {persistence: true}`, `ratelimit.memory = 64Mi`, e2e-web
  `uses += [sessions, ratelimit]`; `uv run scripts/render.py`; commit. Assert `ls operators/apps` is unchanged (AC-118.23) and the
  rendered e2e-web Deployment has `SESSIONS_REDIS_URL` … `RATELIMIT_REDIS_PASSWORD` from `e2e-sessions-app`/`e2e-ratelimit-app`.
- Apply each cache addon with `kubectl apply -n $ns -k addons/dev/<c>`; wait up to 120 s for the Secret's four keys; on failure print
  the ExternalSecret and its events (`--field-selector involvedObject.kind=ExternalSecret,involvedObject.name=e2e-<c>-app`: ESO
  names a problem only there). `rollout status statefulsets.apps/e2e-<c> --timeout=180s` (stream its output), then re-apply the
  e2e-web overlay and `rollout status deploy/e2e-web`. Name every kind in full: `statefulsets.apps`, `externalsecrets.external-secrets.io`,
  `passwords.generators.external-secrets.io`, `podvolumebackups.velero.io`, `schedules.velero.io`.
- Contract (cheap, `kubectl exec` into `e2e-<c>-0 -c valkey`, password from the container's own `$VALKEY_PASSWORD` inside `sh -c`):
  password length 32 and `url` = `redis://:<pw>@e2e-sessions.e2e-dev.svc:6379/0` (AC-118.19); `valkey-cli ping` without a password →
  `NOAUTH`, with a wrong one → `WRONGPASS`, with the right one → `PONG` (AC-118.11); `CONFIG GET maxmemory` on ratelimit →
  `53687091`, `maxmemory-policy` → `allkeys-lru`, container limit `64Mi` (AC-118.6); `services` of the system are all `ClusterIP`,
  the cache Services expose 6379, no `httproutes.gateway.networking.k8s.io` named for a cache (AC-118.8).
- Through the component (AC-118.15, AC-118.18): a probe Pod (not a Deployment: the guard rails do not cover it, and they are never
  weakened) with e2e-web's `*_REDIS_*` `valueFrom` entries, the cache's own Valkey image (already on the node), `runAsUser: 999`;
  it runs `valkey-cli -u "$SESSIONS_REDIS_URL" SET …` and `GET …` and prints the value; compare with the payload. Reuse the
  `s3run` pattern (bounded wait, logs, delete).
- Eviction (AC-118.6): a second probe Pod pipes ~1200 `SET k<i> <64 KiB>` lines into `valkey-cli -u "$RATELIMIT_REDIS_URL"`; then
  `INFO stats` `evicted_keys` > 0, `DBSIZE` < 1200, the pod's `restartCount` 0 and no `OOMKilled`. Then `CONFIG SET maxmemory-policy
  noeviction` and SET 64 KiB values until a reply contains `OOM` (at most 100; fail otherwise).
- Persistence (AC-118.7, AC-118.19): SET a key in sessions and ratelimit, `sleep 2`, delete both pods, wait until the new pods (new
  UID) are Ready (bounded loop, then `kubectl wait --for=condition=Ready`), GET: sessions has the key, ratelimit `DBSIZE` is 0; the PVC
  `data-e2e-sessions-0` exists and ratelimit's pod mounts no PVC; the Secret's password is unchanged after the restart and after
  re-applying the addon and annotating the ExternalSecret `force-sync`.
- Doctor (AC-118.15, AC-118.23): `timeout 180 $cplat platform doctor --repo "$gitops_repo" --json` (any exit code); no row's name
  or detail mentions `cache`, `valkey`, `sessions` or `ratelimit`.
- Backups (AC-118.14), in the existing steps: after "render writes the three operators", the Schedule `e2e-dev`'s NotIn values contain
  `ratelimit` and `sessions`; after the Velero Backup completes, its `podvolumebackups.velero.io` (`-o jsonpath='{.items[*].spec.pod.name}'`)
  do not name `e2e-sessions-0`; the refusal of `system restore` without `--replace` does not list `data-e2e-sessions-0`.
- Keep every wait bounded and print what it waited for; do not change the steps of 115–117 beyond the three backup checks above.

**Done when:** `tests/e2e/run.sh` passes on a local machine with the release candidate, the cache steps take at most ~5 minutes in its
log, and the run is recorded in the verification.

## t9 — amend the spec 115/116/117 assertions that 118 extends

**Files:** tests/cplat/test_resources_115.py, tests/cplat/test_resources_115_cmds.py, tests/cplat/test_bucket_116.py, tests/cplat/test_bucket_116_cmds.py, tests/cplat/test_backup_117_cmds.py
**Covers:** AC-118.18, AC-118.22
**Goal:** the 115–117 suites assert 5.x behaviour after spec 118 and nothing else. Each changed line ends with a `# spec 118: …`
comment, and the verification lists them as approved test changes.

**Implementation notes:**
- `test_resources_115.py` line 42: the AC-115.2 parametrisation drops `("cache", 118)` (`[("broker", 119)]`); line 183: the AC-115.7
  table test expects `PLANNED_TYPES == {"broker": 119}`.
- `test_resources_115_cmds.py` line 138: the AC-115.2 command parametrisation drops `("cache", 118)`.
- `test_bucket_116.py` line 660: `PLANNED_TYPES == {"broker": 119}`; line 663: the parametrisation drops `("cache", 118)`.
- `test_bucket_116_cmds.py` line 161: the parametrisation drops `("cache", 118)`; lines 420–421: the `--uses` help string becomes
  design.md's (`…, a bucket S3_* and AWS_*, a cache REDIS_URL and REDIS_*); declare it first with `cplat resource add <name> --type database|bucket|cache``).
- `test_backup_117_cmds.py` line 803: `plugin_version("resource") == ("1.4.0", "1.4.0")` (the function name stays).
- No other assertion is changed or removed.

**Done when:** the amended tests pass once t1, t4, t5 and t6 are merged, and `git diff` of these files touches only the lines named here.
