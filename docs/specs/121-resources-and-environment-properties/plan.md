---
spec_id: 121-resources-and-environment-properties
shape: platform
spec_hash: a52353a91747
summary: "Pins, upgrades and their proof (additive 5.x): one complete versions table in render.py (engine images with immutable tags and digests: Postgres 15 deprecated, 16-18 standard-trixie; Valkey 8/9; NATS 2.14/2.15 with the digest in the chart's tag; SeaweedFS, collector, LGTM, Velero plugin; Argo CD v3.4.12, k3s and Gateway API rows; each operator's served CRD versions), versions_table() and render.py --versions, cplat platform versions with --diff/--changelog; resources.<r>.instances.<env>.version for database, cache and broker, effective majors, held pins kept from the rendered files of staging and prod, a Barman server per major recorded as archives in restore-state.yaml and restored generations on their own major; cplat resource upgrade <name> --to <major> [--env] (one environment per PR, dev first, staging after a verified dev and by itself with promote after-dev-smoke, prod by hand, the last step folds the entries, refusals for buckets, external, downgrades naming /resource:restore, unsupported jumps, unverified earlier environments, held pins and a database backup older than 60 minutes read from cplat system status --json; cache and broker say they have no backup), verification (healthy at the pin within 15 minutes, Secret names, smoke tests of every using instance, a ConfigMap record, NOT VERIFIED with exit 1 and the way back), /platform:update re-renders and lists the per-environment changes, --verify moves operators once per cluster and runs every environment's smoke tests; a gitops CI check against two-environment major changes; property_operators install|owner renders External Secrets, Kyverno and LGTM per need for new systems; doctor --context with ok/missing/older/newer, CRD versions and shared clusters; model version and pinned, status Resource versions; local cluster defaults equal to the table with override warnings; pin check, release check (CHANGELOG rows, majors need a major release), a release-blocking upgrade e2e from the latest 5.0.x in its own workflow with a tag-push gate; two ADRs"
tasks:
  - id: t1
    title: render.py — the complete versions table (digested engine images, Postgres immutable standard-trixie tags, COLLECTOR_IMAGE, LGTM_IMAGE, CLUSTER_PINS, SUPPORTED/DEPRECATED majors, UPGRADE_PATHS, each operator's crds), the NATS digest in the chart tag, versions_table(), --versions
    files: [templates/gitops-app/scripts/render.py, templates/cluster-gitops/scripts/system_render.py]
    covers: [AC-121.1, AC-121.2, AC-121.3, AC-121.22, AC-121.26]
    parallel_safe: true
    depends_on: []
  - id: t2
    title: render.py — instances.<env>.version (database, cache, broker), effective majors, pins with held staging/prod images read from the rendered files, archives and serverName per major, restored generations on their archive's major, the note
    files: [templates/gitops-app/scripts/render.py, templates/cluster-gitops/scripts/system_render.py]
    covers: [AC-121.3, AC-121.6, AC-121.7, AC-121.11, AC-121.16]
    parallel_safe: false
    depends_on: [t1]
  - id: t3
    title: render.py — property_operators (External Secrets, Kyverno, LGTM per need, never with operators owner), operators/apps/lgtm.yaml and operators/lgtm/, docstring
    files: [templates/gitops-app/scripts/render.py, templates/cluster-gitops/scripts/system_render.py]
    covers: [AC-121.17, AC-121.18]
    parallel_safe: false
    depends_on: [t2]
  - id: t4
    title: cplat platform versions (text, --json, --diff, --changelog) and the registration of platform versions and resource upgrade
    files: [scripts/cplat/versions.py, scripts/cplat/cplat.py]
    covers: [AC-121.1, AC-121.23]
    parallel_safe: true
    depends_on: [t1]
  - id: t5
    title: cplat resource upgrade — guards in order (bucket, external, downgrade, deprecated, unsupported jump, earlier environment not ready, held pin, backup within 60 minutes), the step's edit (instance version, folding, pin move, archives), PR with its body, --wait
    files: [scripts/cplat/upgrade.py]
    covers: [AC-121.6, AC-121.7, AC-121.9, AC-121.11, AC-121.12, AC-121.13, AC-121.14, AC-121.27]
    parallel_safe: true
    depends_on: [t2]
  - id: t6
    title: verification — health at the pin within 15 minutes, Secret names, smoke tests of every using instance (clone or --component-dir), the ConfigMap record, verified / NOT VERIFIED output, the automatic staging step
    files: [scripts/cplat/upgradeverify.py]
    covers: [AC-121.8, AC-121.15, AC-121.16]
    parallel_safe: true
    depends_on: [t5]
  - id: t7
    title: platform update — re-render after the template copy, the per-environment change list (report, JSON, fleet PR body), the migration proof ignores the collector digest, --verify (operators and CRDs, dev's moved pins, every environment's smoke tests, staging pin moves)
    files: [scripts/cplat/update.py, scripts/cplat/fleet_pr.py]
    covers: [AC-121.11, AC-121.20, AC-121.21, AC-121.22, AC-121.23]
    parallel_safe: true
    depends_on: [t3, t6]
  - id: t8
    title: resource restore — a restore to a time before a major upgrade names the major its generation runs on
    files: [scripts/cplat/dbrestore.py]
    covers: [AC-121.16]
    parallel_safe: true
    depends_on: [t2]
  - id: t9
    title: model version and pinned per resource instance; system status Resource versions (JSON resource_versions, text grid)
    files: [scripts/cplat/model.py, scripts/cplat/status.py]
    covers: [AC-121.5, AC-121.15]
    parallel_safe: true
    depends_on: [t2, t6]
  - id: t10
    title: doctor — --context, operator states ok/missing/older/newer with CRD versions and shared environments, FAIL on missing or a major older, rows for External Secrets, Kyverno and LGTM with install, broker rows without digests
    files: [scripts/cplat/doctor.py]
    covers: [AC-121.18, AC-121.19, AC-121.21, AC-121.22]
    parallel_safe: true
    depends_on: [t3]
  - id: t11
    title: local-cluster.sh (+ its cluster-gitops copy) — defaults equal to the table (Argo CD v3.4.12, k3s, LGTM and Velero plugin with digests), override warnings, ESO/Kyverno/LGTM from operators/ under Argo CD; bootstrap.sh waits for their CRDs
    files: [templates/gitops-app/scripts/local-cluster.sh, templates/cluster-gitops/scripts/local-cluster.sh, templates/gitops-app/scripts/bootstrap.sh]
    covers: [AC-121.4, AC-121.17]
    parallel_safe: true
    depends_on: [t3]
  - id: t12
    title: gitops-app template — the property_operators answer, upgrade-check.py with its recipe and CI job; system new answers install
    files: [templates/gitops-app/copier.yml, templates/gitops-app/devbox.json, templates/gitops-app/.github/workflows/ci.yml, templates/gitops-app/scripts/upgrade-check.py, scripts/cplat/newapp.py]
    covers: [AC-121.10, AC-121.17]
    parallel_safe: true
    depends_on: [t2]
  - id: t13
    title: pin check — table rows, a coverage render, the cluster scripts' defaults; devbox run validate runs it
    files: [scripts/check-pins.py, devbox.json]
    covers: [AC-121.2]
    parallel_safe: true
    depends_on: [t3, t11]
  - id: t14
    title: release check (CHANGELOG rows, majors need a major release, needs-upgrade-e2e, gate), the CI job and pin-check step, the tag-push release gate, CONTRIBUTING's release procedure
    files: [scripts/release-check.py, .github/workflows/ci.yml, .github/workflows/release-guard.yml, CONTRIBUTING.md]
    covers: [AC-121.2, AC-121.23, AC-121.24, AC-121.26]
    parallel_safe: true
    depends_on: [t4, t13]
  - id: t15
    title: upgrade e2e — from the latest 5.0.x (floating references resolved and recorded) to the candidate, held pins, operators once, backups, the refused upgrade, a forced failed verification, 16 to 17 through dev, staging and prod, data and doctor checks; its own workflow
    files: [tests/e2e/upgrade.sh, .github/workflows/e2e-upgrade.yml]
    covers: [AC-121.4, AC-121.5, AC-121.8, AC-121.11, AC-121.15, AC-121.16, AC-121.19, AC-121.21, AC-121.22, AC-121.24, AC-121.25]
    parallel_safe: false
    depends_on: [t5, t6, t7, t8, t9, t10, t11, t12, t14]
  - id: t16
    title: e2e run.sh — the system answers property_operators owner; the NATS image assertion reads the table
    files: [tests/e2e/run.sh]
    covers: [AC-121.2, AC-121.17]
    parallel_safe: true
    depends_on: [t1, t12]
  - id: t17
    title: resource plugin 1.6.0 (/resource:upgrade), platform plugin 1.3.0 (doctor --context, update --verify, versions), system plugin 1.5.0 (status), catalog, and the CHANGELOG [Unreleased] entry with the versions rows
    files: [plugins/resource/commands/upgrade.md, plugins/resource/README.md, plugins/resource/.claude-plugin/plugin.json, plugins/platform/commands/doctor.md, plugins/platform/commands/update.md, plugins/platform/README.md, plugins/platform/.claude-plugin/plugin.json, plugins/system/commands/status.md, plugins/system/README.md, plugins/system/.claude-plugin/plugin.json, .claude-plugin/marketplace.json, docs/CHANGELOG.md]
    covers: [AC-121.6, AC-121.19, AC-121.23]
    parallel_safe: true
    depends_on: [t4]
  - id: t18
    title: Docs — UPGRADES.md (new guide), DOMAIN-MODEL.md, USER-JOURNEY.md, CLUSTERS.md, the site's domain-model page, the two ADR index rows
    files: [docs/UPGRADES.md, docs/DOMAIN-MODEL.md, docs/USER-JOURNEY.md, docs/CLUSTERS.md, site/src/content/docs/concepts/domain-model.md, docs/adr/README.md]
    covers: [AC-121.17, AC-121.18]
    parallel_safe: true
    depends_on: []
  - id: t19
    title: Amend the spec 114-120 assertions that 121 extends (pin patterns and literals, instance key lists, the cache and broker version-key tests, byte-identity digests after unpinning, the 4.7 comparisons, the model normalisation)
    files: [tests/cplat/resources_fixtures.py, tests/cplat/cache_fixtures.py, tests/cplat/broker_fixtures.py, tests/cplat/test_addons.py, tests/cplat/test_resources_115.py, tests/cplat/test_bucket_116.py, tests/cplat/test_backup_117.py, tests/cplat/test_cache_118.py, tests/cplat/test_broker_119.py, tests/cplat/test_scale_120.py, tests/cplat/test_system_model_114.py, tests/cplat/test_system_render_114.py, tests/cplat/test_migrate_114.py]
    covers: [AC-121.2, AC-121.3, AC-121.5, AC-121.7]
    parallel_safe: true
    depends_on: []
---

# Plan — 121 Resources and environment properties upgrade safely

The contract (versions table and rows, `cplat platform versions`, the `system.yaml` key and its errors, effective majors and held pins,
archives per major, property operators, `cplat resource upgrade` with every refusal text, verification and its record, `/platform:update`
and `--verify`, the gitops CI check, doctor, model and status, local cluster, pin check, release check and gate, the upgrade e2e, what was
verified) is in [design.md](design.md). The decisions that outlive this spec are the two ADRs
[resource and operator upgrades roll through the environments in verified steps](../../adr/068-resource-and-operator-upgrades-roll-through-environments-in-verified-steps.md)
and [one versions table pins everything, and every release proves the upgrade](../../adr/069-one-versions-table-pins-everything-and-every-release-proves-the-upgrade.md).
It builds on spec 115 (the table, `operators/`, doctor rows), 116 (SeaweedFS), 117 (backups, generations, `restore-state.yaml`, status
`backups`, `/resource:backup`, `/resource:restore`), 118, 119 (pins, NACK's label), 120 (KEDA, `resource_metrics`, the e2e budget), 124
(key lists grow at the end; engines never promote forward) and 125 (shared `OPERATORS`, synced template copies).
Levels: t1, t18, t19 → t2, t4 → t3, t5, t8, t12, t17 → t6, t10, t11, t16 → t7, t9, t13 → t14 → t15.

`render.py` changes in three sequential tasks (t1 → t2 → t3). Each ends with `python3 scripts/sync-template-copies.py`, so
`templates/cluster-gitops/scripts/system_render.py` stays byte-equal (`--check` runs in CI), which is why each lists the copy; t11 runs the
same script for `local-cluster.sh` and lists that copy. Every other task owns its files. Never edit `scripts/cplat/assets/render_v4.py`.
A 5.x `system.yaml` without the new keys must render byte-identically except the engine image references (design.md, first section): the
acceptance tests compare the digests of specs 118–120 after `unpin` (t19), and the 114–125 suites, amended only by t19, stay green. Tests
that look for domain-like names or references (`clusters.postgresql.cnpg.io`, `nats:2.15.2-alpine`, `e2e-postgres-app`) match them with
regular expressions or equality, never with `"a.b.c" in text` (CodeQL flags those). Every `cplat` test fakes `kubectl`, `gh` and `git`
remotes; no unit test needs a cluster or the network.

**Spec readings resolved by default (design.md, "Spec readings" and "Decisions taken by default"); each needs a changelog line in spec.md
before its acceptance tests are written:**
- **AC-121.3**: Postgres 16–18 are supported and upgrade targets; 15 stays renderable as deprecated (AC-121.26 forbids dropping it in a
  minor release) and is never a target.
- **AC-121.3 / AC-121.27**: a bucket has no `version`; `/resource:upgrade` on a bucket refuses; its SeaweedFS image moves as a pin.
- **AC-121.2 / AC-121.3 vs AC-115.6, AC-118.22, AC-119.24, AC-120.26**: engine image references gain exact tags and digests; everything
  else stays byte-identical. The Postgres plain tags of spec 115 are not published upstream, so they move to immutable build tags.
- **AC-121.17**: External Secrets, Kyverno and LGTM are rendered when the repo answers `property_operators: install` (new systems);
  existing repos keep `owner`.
- **AC-121.19**: "with access to an environment's cluster" means `--context [ENV=]CTX`; only then do `missing` and a major `older` fail.
- **AC-121.20**: a gitops repo deploys every environment to one `cluster_server`, so 5.x has no separate-cluster case; AC-121.21 governs.
- **AC-121.24**: the first run starts from 5.0.x, which has no backups, buckets, caches or brokers; backups are added after the update,
  other resources only when the previous release supports them; "not tagged" is a CI gate plus the release procedure, never automation.

## t1 — render.py: the complete versions table

**Files:** templates/gitops-app/scripts/render.py, templates/cluster-gitops/scripts/system_render.py
**Covers:** AC-121.1, AC-121.2, AC-121.3, AC-121.22, AC-121.26
**Goal:** every image and chart the renderer writes or the local cluster installs is a row of one table with an exact version (images with
a digest), and `versions_table()` / `--versions` expose it as designed; rendered trees change only in the engine image references.

**Implementation notes:**
- Before writing values: re-read the CloudNativePG `catalog-standard-trixie.yaml`, the Docker Hub tag API for every image and run
  `docker manifest inspect` (or `docker buildx imagetools inspect`) on each designed reference, including the current
  `ghcr.io/cloudnative-pg/postgresql:17.11`; if a digest moved, take the new one and update design.md's "Verified" paragraph in the same PR.
- Constants exactly as designed (`POSTGRES_IMAGES`, `VALKEY_IMAGES`, `NATS_IMAGES`, `SEAWEEDFS_IMAGE`, `VELERO_AWS_PLUGIN_IMAGE`,
  `COLLECTOR_IMAGE` used by `ADDONS["observability"]`, `LGTM_IMAGE`, `CLUSTER_PINS`, `SUPPORTED_MAJORS`, `DEPRECATED_MAJORS`,
  `UPGRADE_PATHS`); `SUPPORTED_VERSIONS`, `CACHE_VERSIONS`, `BROKER_VERSIONS` keep their values and texts.
- `OPERATORS[*]["crds"]`: download each pinned chart archive (the `urls` of its Helm index entry), list every CRD it installs (in `crds/`
  or `templates/`, with its gate value at the default) and the versions with `served: true`; record in a code comment per row whether the
  CRDs sit in `crds/` (the risk in design.md). No other field of a row changes.
- Broker: `container.image` = `{repository, tag}` from splitting the reference at `@` first, the digest appended to `tag`.
- `versions_table()` with the row shape and order of design.md; `--versions` in `main()` before anything reads `applications/`.
- The comment above the table names spec 121 and ADR-069 instead of "Changing a pin follows spec 121".
- Run `python3 scripts/sync-template-copies.py` before committing.

**Done when:** the AC-121.1 table tests (rows, order, kinds, digests, the deprecated 15), the AC-121.3 render tests (each major renders its
exact reference; two renders give the same image; a major outside the table names the supported ones), the AC-121.2 row-format tests,
the AC-121.22/AC-121.26 row-data tests (`crds` present and non-empty for every operator with a CRD) and `--versions` pass; the 114–125
render suites pass after t19.

## t2 — render.py: per-environment majors, held pins, archives

**Files:** templates/gitops-app/scripts/render.py, templates/cluster-gitops/scripts/system_render.py
**Covers:** AC-121.3, AC-121.6, AC-121.7, AC-121.11, AC-121.16
**Goal:** `instances.<env>.version` is accepted and validated with the designed texts, every in-cluster instance renders its effective
major's pin, staging and prod keep their rendered pin while their major stays, and a backed-up database archives per major.

**Implementation notes:**
- `RESOURCE_INSTANCE_KEYS`, `CACHE_INSTANCE_KEYS`, `BROKER_INSTANCE_KEYS` gain `"version"` at the end; the cache exemption for `version`
  in the external sizing check goes; values validated with the existing `database_version` / cache / broker checks under
  `resources.<r>.instances.<env>`; the float hint for a broker.
- `envs[e]["version"]` = effective major; `envs[e]["pin"]` per the two rules of design.md (one helper per type reading the rendered file:
  active cluster file, `statefulset.yaml`, `server.yaml` image and `targetRevision`, `seaweed.yaml`); `database_cluster`, `cache_files`,
  `broker_files`, `bucket_files` read `pin` instead of the table.
- `read_restore_state` returns `archives` too (validated as designed); the plugin `serverName` after `barmanObjectName` only with
  `archives`; a restored or active generation whose `from.server` is an archive of another major renders that major's table image; the
  `note:` line through the existing notes path (stdout, like spec 119's notes).
- `cfg` keys documented in the renderer API comment; `load_system` stays lenient for nothing new (errors are render errors).
- Run `python3 scripts/sync-template-copies.py` before committing.

**Done when:** the AC-121.3/AC-121.6/AC-121.7 render tests (instance `version` per type, every error text, `"17"`, booleans, floats, the
folded form renders the same as per-environment entries of the same major), the AC-121.11 tests (a first render pins the table in every
environment; with an older rendered image staging and prod keep it byte for byte while dev moves; another major takes the table; a
broken file counts as absent; `--check` stable) and the AC-121.16 restore tests (`serverName` with archives only, a generation from an
older archive on its major, the note) pass; without the new keys and files nothing changes beyond t1.

## t3 — render.py: environment-property operators

**Files:** templates/gitops-app/scripts/render.py, templates/cluster-gitops/scripts/system_render.py
**Covers:** AC-121.17, AC-121.18
**Goal:** with `property_operators: install`, `operators/` holds External Secrets, Kyverno and LGTM exactly where design.md says, never
for an `operators: owner` environment; with `owner` or no answer, `operators/` is unchanged.

**Implementation notes:**
- `operator_files(apps, ans)`: `ans.get("property_operators", "owner") == "install"` gates the three; the needs as designed (125's secrets
  rule, external resources, in-cluster bucket/cache/broker, environment backup; `policy_envs`; `ui: lgtm` with a running instance).
- `lgtm_files(ans) -> dict[Path, str]`: `operators/lgtm/deployment.yaml`, `service.yaml`, `kustomization.yaml` (the documents
  `local-cluster.sh` applies, image `LGTM_IMAGE`, no dashboards, no HTTPRoute) and `operators/apps/lgtm.yaml` (Application
  `operator-lgtm`, path source on the gitops repo URL as `operators/root.yaml` builds it, namespace `observability`, sync options as
  designed, no finalizer). Order in `operators/apps`: `OPERATORS` order, then `lgtm`.
- Stale handling: `operators/lgtm/` is removed with `operators/` rules (render owns `operators/` entirely).
- Docstring: `instances.<env>.version` under resources, the `property_operators` answer in one line, the `archives` line next to
  `restore-state.yaml`.
- Run `python3 scripts/sync-template-copies.py` before committing.

**Done when:** the AC-121.17 render tests (each operator appears for exactly its need, once per repo for several environments and systems,
removed when nothing needs it, none with `owner`/no answer), the AC-121.18 tests (no operator file for an `operators: owner` environment;
any other value still fails with 115's text) and the docstring test pass.

## t4 — cplat platform versions

**Files:** scripts/cplat/versions.py, scripts/cplat/cplat.py
**Covers:** AC-121.1, AC-121.23
**Goal:** `cplat platform versions [--json] [--diff <ref>] [--changelog]` prints the table and its changes exactly as designed;
`cplat resource upgrade` is routed to `upgrade.py`.

**Implementation notes:**
- `rows(render_path) -> list[dict]` loads `versions_table()` from a renderer file; for an older release without it, build rows from its
  constants (`POSTGRES_IMAGES`, `VALKEY_IMAGES`, `NATS_IMAGES`, `NATS_CHART`, `SEAWEEDFS_IMAGE`, `VELERO_AWS_PLUGIN_IMAGE`, `ADDONS`,
  `OPERATORS`) with the same names; `git show <ref>:<path>` into a temporary file.
- `diff(old, new)` with the change kinds and the major rule (first number, or the second for `0.x`; leading `v` ignored); `changelog`
  lines exactly as designed.
- `cplat.py`: `NOUNS["platform"]["versions"] = ("versions", [])`, `NOUNS["resource"]["upgrade"] = ("upgrade", [])`, and their usage lines
  in the module docstring.

**Done when:** the AC-121.1 command tests (text columns, digest abbreviation, `--json` with full digests and the release) and the AC-121.23
diff tests (changed, added, removed, digest-only, `(major)`, CRD version removed, a pre-121 ref, an unreadable ref) pass.

## t5 — cplat resource upgrade

**Files:** scripts/cplat/upgrade.py
**Covers:** AC-121.6, AC-121.7, AC-121.9, AC-121.11, AC-121.12, AC-121.13, AC-121.14, AC-121.27
**Goal:** every refusal of design.md's table, in its order and with its text and hint, changes nothing; an allowed step writes exactly the
designed edit and, with `--pr`, one PR with the designed branch, title and body.

**Implementation notes:**
- Load with `gitops.find_app` and the repo's renderer (`load_system`) for effective majors, pins and instances; the platform's table for
  `SUPPORTED_MAJORS`, `DEPRECATED_MAJORS`, `UPGRADE_PATHS` and the current pins.
- Check 10 reads `upgradeverify.read_record` lazily (t6), contexts parsed with `status.parse_contexts`; checks 13–15 call
  `status.collect_backups` / `status.public_backups` in-process; `now()` and `kubectl` are seams tests replace.
- The edit with `gitops.load` / `gitops.save` (comments kept), the folding rule, the pin move in the rendered file, `archives` in
  `restore-state.yaml` (create the 117 document when absent), then `gitops.render`; on any render error restore the files and raise it.
- `--pr`: branch, signed-off commit, `gh pr create` like `addon.py`; `--wait`: `pr.wait(..., merge=True)`, the Argo sync wait (600 s,
  `ship.argo_health`-style, bounded), then `upgradeverify.verify`; `--verify` mode delegates to t6.
- `--dry-run` and `--json` as designed; `/resource:upgrade` is the slash command (t17).

**Done when:** the AC-121.6 tests (dev only, body with environment, majors and image), AC-121.7 (staging and prod steps, the folding edit),
AC-121.9 (each `<state>` text: not upgraded, not verified, failed, unreadable; nearest earlier environment with an instance), AC-121.11
(pin move: no backup check, rendered pin replaced, `system.yaml` unchanged; check 11), AC-121.12 (no key; `null`; 61 minutes; exactly 60
minutes passes; unreadable; dev included), AC-121.13, AC-121.14 (downgrade texts with and without the restore hint, deprecated target,
an unsupported jump with a patched `UPGRADE_PATHS` naming the intermediate) and AC-121.27 (cache and broker: no backup read, "has no
backup" in the body) pass, each refusal leaving the tree, the branch and `gh` untouched.

## t6 — verification

**Files:** scripts/cplat/upgradeverify.py
**Covers:** AC-121.8, AC-121.15, AC-121.16
**Goal:** `verify` waits, checks and records exactly as designed, prints the verified or NOT VERIFIED block, exits 0 or 1, and starts the
staging step only after a verified dev step with `promote: after-dev-smoke`.

**Implementation notes:**
- Health readers per type (`clusters.postgresql.cnpg.io`, `statefulsets.apps`, pods of a bucket) through one `kubectl` seam (reuse
  `backupstate.kubectl`); poll 10 s, bound 900 s, a progress line every 60 s; `sleep`/`monotonic` seams.
- Secret names per type; the using instances from the model (broker: providers and consumers of its APIs running there).
- Smoke: `--component-dir` first, else `gh repo clone <repo> <tmp> -- --depth 1` plus `git fetch --depth 1 origin <sha>` / `--branch
  <tag>`; `smoke.run_smoke` with the model's URL; a missing repo, clone or recipe is a failed check.
- Record ConfigMap applied with `kubectl apply -f -` (also on failure); `read_record` returns `None` when absent, raises a typed error when
  unreadable (check 10 turns it into `cannot be read`).
- After a database major step with backup: `backupstate.take_first_backup`, one line, not awaited.
- Auto staging: call back into `upgrade.step(..., env="staging")` with the same mode; never prod.

**Done when:** the AC-121.15 tests (healthy at the pin after polls; image or major mismatch keeps waiting; Secret names per type; smoke for
each using instance only; record fields), AC-121.16 (unhealthy after 900 s with faked time, a missing Secret, a failing smoke: exit 1, the
designed lines, the restore line only for a database, the record `failed`, no staging step) and AC-121.8 (after-dev-smoke starts staging;
manual prints the command; prod never starts) pass.

## t7 — platform update: re-render, change list, verify

**Files:** scripts/cplat/update.py, scripts/cplat/fleet_pr.py
**Covers:** AC-121.11, AC-121.20, AC-121.21, AC-121.22, AC-121.23
**Goal:** a gitops-app update re-renders with its new renderer (held pins follow), reports the designed per-environment block (report,
`--json`, fleet PR body), keeps the 4.x migration proof working, and `--verify` checks operators once per cluster and every environment.

**Implementation notes:**
- In `execute` for `gitops-app`: before the copy, record each instance's pin and each `operators/apps/*.yaml` `targetRevision` from the
  tree; after the copy, `gitops.render(repo)`; compare and build `data["versions"]` and the report lines; a render error restores like the
  migration's rollback path.
- `_normalised` also strips the `@sha256:<64 hex>` of the collector image in `addons/*/observability/*.yaml` (the 4.7 render has the same
  tag without a digest); keep the database rule.
- `fleet_pr.py`: the block in the PR body when `data["versions"]` is present.
- `--verify`: doctor's operator reading (t10's helpers, imported lazily) with a 900 s bound per operator, then t6's health check for dev's
  moved pins, then the smoke tests of every instance of every environment (shared cluster), the records, staging pin moves per
  after-dev-smoke. The cluster is the repo's one `cluster_server`; the code groups environments by that server so a later per-environment
  cluster gets AC-121.20's order, and says so in a comment.
- Component repos: no change.

**Done when:** the AC-121.11 tests (dev's pin moves, staging and prod keep theirs, the block names the `/resource:upgrade` to move them),
AC-121.23 (the block in the report, `--json` and the fleet PR body), AC-121.21/AC-121.22 `--verify` tests (an operator not at its version
or CRD waits and fails after 900 s; ok runs every environment's smoke), the AC-121.20 grouping test (environments on one server move
together) and the migration tests (4.7 → 5.x proof with a collector) pass.

## t8 — resource restore across a major

**Files:** scripts/cplat/dbrestore.py
**Covers:** AC-121.16
**Goal:** `/resource:restore <db> --env <env> --to <time>` to a time before a major upgrade creates the generation the renderer runs on the
old major, and says so.

**Implementation notes:**
- When the chosen source server is an `archives` entry with another major than the effective one, add to the output
  `the restored instance runs <db> <major> (the data from before the upgrade to <current>)`; `--switch` to it prints the renderer's note
  text (design.md) as its next step.
- No change to the window, checks or Argo/apply paths of spec 117.

**Done when:** the AC-121.16 restore tests (a time before the upgrade picks the old archive and prints the major line; after the upgrade
nothing new is printed) pass and the 117 restore suite stays green.

## t9 — model and status

**Files:** scripts/cplat/model.py, scripts/cplat/status.py
**Covers:** AC-121.5, AC-121.15
**Goal:** `cplat model show --json` carries `version` and `pinned` per resource instance; `/system:status` shows the "Resource versions"
section and `resource_versions` JSON, including "upgraded".

**Implementation notes:**
- `ResourceInstance.version` (effective major) and `.pinned` (read from the rendered file with the same rules as the renderer, lenient:
  `None` when missing or unreadable); `to_dict` adds both after `backup`.
- `status.collect_versions(repo, app, contexts, loaded)`: per instance one `kubectl` health read (t6's readers, imported lazily) and
  `upgradeverify.read_record`; `held` against the repo's own `scripts/render.py` table; text section after the resource grid, before
  Backups; JSON key `resource_versions`; the existing `resources` grid unchanged.

**Done when:** the AC-121.5 model tests (version and pinned per type, external and bucket nulls) and status tests (cells, held, unknown
without a context, upgraded/failed from records, text grid), the AC-121.15 "shown as upgraded" test and the 115/117/120/122 status tests
pass.

## t10 — doctor: operator states

**Files:** scripts/cplat/doctor.py
**Covers:** AC-121.18, AC-121.19, AC-121.21, AC-121.22
**Goal:** operator rows carry the designed `operator` JSON in every run; with `--context` their detail and status follow AC-121.19; without
it every text stays as in specs 115–120.

**Implementation notes:**
- `--context` (repeatable, `ENV=CTX` or `CTX`), parsed like status; every operator read uses that context.
- `_operator_row` computes `state`, CRD served versions (`customresourcedefinitions.apiextensions.k8s.io`), `shared`; the `--context`
  detail and status as designed; the old detail otherwise.
- With `property_operators: install` (`.copier-answers.yml`): rows `operator external-secrets`, `operator kyverno`, `operator lgtm`
  (selector `app=lgtm`); `check_policies` and the observability row stay as they are.
- `check_brokers`: strip `@sha256:…` from both sides before comparing and printing.

**Done when:** the AC-121.19 tests (ok, missing, older by a minor and by a major, newer, a missing CRD version; FAIL and exit 1 only with
`--context`), AC-121.18 (an `operators: owner` environment gets the same row and states), AC-121.21 (`shared by dev, staging, prod`),
AC-121.22 (CRD comparison) and the property-operator rows pass; the 115–120 and 125 doctor tests stay unchanged and green.

## t11 — local cluster and bootstrap

**Files:** templates/gitops-app/scripts/local-cluster.sh, templates/cluster-gitops/scripts/local-cluster.sh, templates/gitops-app/scripts/bootstrap.sh
**Covers:** AC-121.4, AC-121.17
**Goal:** a local cluster runs exactly the table's versions unless overridden, and then says so; ESO, Kyverno and LGTM come from
`operators/` under Argo CD when the render wrote them.

**Implementation notes:**
- Defaults: `ARGOCD_VERSION` `v3.4.12`, `K3S_IMAGE`, `LGTM_IMAGE`, `VELERO_AWS_PLUGIN_IMAGE` with digests; header comment lines updated;
  operator chart defaults and `rev_of` unchanged.
- One `warn_override VAR default row` helper, called for every version and image variable before the cluster is created, printing the
  designed `WARNING:` text when the variable is set and differs.
- Argo CD path: skip the ESO and Kyverno HelmCharts and the LGTM Deployment when `operators/apps/<name>.yaml` exists (keep an existing
  HelmChart with the designed message); add waits for their CRDs and `deploy/lgtm`, bounded; `WITH_ARGO=0` unchanged.
- `bootstrap.sh`: `external-secrets) crd=clustersecretstores.external-secrets.io ;;`, `kyverno) crd=namespacedvalidatingpolicies.policies.kyverno.io ;;`,
  `lgtm` falls through `*) continue`.
- Run `python3 scripts/sync-template-copies.py` so the cluster-gitops copy is byte-equal; commit both.

**Done when:** the AC-121.4 script tests (defaults equal the table's rows; each override variable prints the warning naming the variable,
the value and the table's version; Argo CD no longer `stable`) and the AC-121.17 script tests (Argo path skips the HelmCharts when the
operator files exist; the legacy message) pass; `bash -n`, `shellcheck` and `sync-template-copies.py --check` are green; the 115–120 script
tests stay green.

## t12 — gitops-app template: the answer and the CI check

**Files:** templates/gitops-app/copier.yml, templates/gitops-app/devbox.json, templates/gitops-app/.github/workflows/ci.yml, templates/gitops-app/scripts/upgrade-check.py, scripts/cplat/newapp.py
**Covers:** AC-121.10, AC-121.17
**Goal:** new gitops repos ask `property_operators` (default `owner`), `cplat system new` answers `install`, and every gitops PR runs the
one-environment-per-major check.

**Implementation notes:**
- `copier.yml`: the question exactly as designed, after `resource_metrics`.
- `newapp.py`: `--data property_operators=install` in the gitops-app copier call.
- `scripts/upgrade-check.py` (uv script header with pyyaml): designed behaviour and texts; imports the repo's `scripts/render.py` as a
  module; the base side from `git show <ref>:applications/<s>/system.yaml` in a temporary copy of the repo's `scripts/`.
- `devbox.json`: recipe `upgrade-check` = `uv run scripts/upgrade-check.py --base "${BASE_REF:-origin/main}"`.
- `ci.yml`: job `upgrade-check (one environment per major)`, `if: github.event_name == 'pull_request'`, checkout pinned like the others
  with `fetch-depth: 0`, devbox install as in `quality`, `BASE_REF: origin/${{ github.base_ref }}` (the file is not `.jinja`, so the
  expression stays verbatim), `devbox run upgrade-check`.

**Done when:** the AC-121.10 tests (two environments at once fail with the designed text; one environment, the folding step, a new system,
an unrendered base pass; the job exists with fetch-depth 0) and the AC-121.17 template tests (`copier copy --defaults` writes `owner`;
`system new` writes `install`) pass; `actionlint` and the pinned-actions check are green.

## t13 — pin check

**Files:** scripts/check-pins.py, devbox.json
**Covers:** AC-121.2
**Goal:** `python3 scripts/check-pins.py` fails on every reference outside the table, without a digest, floating or without an exact chart
version, naming file and reference; it is green on the tree after t1–t3 and t11.

**Implementation notes:**
- Three parts as designed; the coverage render in a temporary directory (copy `templates/gitops-app/scripts/render.py` and a generated
  `system.yaml` plus `.copier-answers.yml` with `resource_metrics: install` and `property_operators: install`).
- Reference walk over every YAML document (`yaml.safe_load_all`), keys compared as strings; script scan with anchored regexes per
  pattern (no substring checks).
- Root `devbox.json` `validate` runs it after the existing jq checks.

**Done when:** the AC-121.2 tests (a fixture tree with each kind of bad reference fails with the designed line; the real tree passes; a
script default that differs from its row fails) pass.

## t14 — release check and gate

**Files:** scripts/release-check.py, .github/workflows/ci.yml, .github/workflows/release-guard.yml, CONTRIBUTING.md
**Covers:** AC-121.2, AC-121.23, AC-121.24, AC-121.26
**Goal:** CI fails a PR whose CHANGELOG misses a changed row or whose major move is not a major release, the upgrade e2e runs when it is
needed, and a tag without a green upgrade e2e turns red; the release procedure names the gate.

**Implementation notes:**
- `rows`, `needs-upgrade-e2e`, `gate` exactly as designed; `versions.py` imported from `scripts/cplat`; `gh api` through one seam.
- `ci.yml`: step "every image and chart comes from the versions table" (`python3 scripts/check-pins.py`) in `validate-shapes`; job
  `release-check (versions table)` (checkout `fetch-depth: 0`, setup-uv, `uv run scripts/release-check.py rows`), added to `ci-success`'s
  needs; actions pinned by SHA (`scripts/pin-actions.py`), least-privilege permissions.
- `release-guard.yml`: `on: push: tags: ['v*']`, `permissions: {contents: read, checks: read}`, `GH_TOKEN: ${{ github.token }}`, one job
  `release gate (upgrade e2e green)`.
- `CONTRIBUTING.md` Releases: one sentence each for `release-check.py rows`, the gate before `git tag`, and deleting a tag whose gate is
  red; nothing else changes.

**Done when:** the AC-121.23 tests (a missing line fails naming it; all lines present pass; the section chosen), AC-121.26 (a major operator
move, a removed CRD version, a dropped major fail on a minor release and pass on a major one), the AC-121.24 gate tests (success passes;
failure, skipped and missing fail with the designed text) and the workflow tests (job names, triggers, no `git tag`, `gh release` or
`git push --delete` anywhere) pass; `actionlint` green.

## t15 — the upgrade e2e

**Files:** tests/e2e/upgrade.sh, .github/workflows/e2e-upgrade.yml
**Covers:** AC-121.4, AC-121.5, AC-121.8, AC-121.11, AC-121.15, AC-121.16, AC-121.19, AC-121.21, AC-121.22, AC-121.24, AC-121.25
**Goal:** design.md's six steps end to end, failing with the step's name, in at most 45 minutes in the log; the workflow as designed.

**Implementation notes:**
- Workflow: triggers, `decide` and `upgrade` jobs, the job name `e2e upgrade (previous release → candidate)` exactly (the gate reads it),
  `timeout-minutes: 75`, checkout `fetch-depth: 0`, actions pinned like `e2e.yml`, `permissions: contents: read`.
- Script header: the ACs, the steps and the budget; the devbox shim of `run.sh` (copied, not sourced); `FROM` resolution as designed;
  FROM's commands run as `uv run $work/from/scripts/cplat/cplat.py`, the candidate's as `uv run $root/scripts/cplat/cplat.py`.
- Commit before every `cplat` command that writes; one Python edit per `system.yaml` change, render, commit.
- Every wait bounded (seconds in the failure text) and streamed; every kind by its full name; probes are pods that load the component's
  own Secret (`envFrom`) and run `psql "$DATABASE_URL"` from the table's Postgres image, the AWS CLI with `S3_*`, `valkey-cli -u
  "$REDIS_URL"`, `nats` with `NATS_*` — as `run.sh` does.
- The resolved floating references file and its printout (AC-121.24); the forced failure through a copy of `upg-api` whose `smoke` recipe
  prints `FAIL forced` and exits 1.
- Assertions on JSON parse with `json.loads`; texts matched whole-word (`grep -w`, `re.search(r"\b…\b")`); YAML compared as strings.
- Run it locally against the release candidate before the PR; record the run (duration per step) in the verification.

**Done when:** `bash tests/e2e/upgrade.sh` passes on a local machine from the latest 5.0.x, prints the resolved references and
`UPGRADE E2E OK`, stays within 45 minutes in its log, and the workflow passes `actionlint`; the e2e-upgrade job is green on the PR.

## t16 — e2e run.sh adjustments

**Files:** tests/e2e/run.sh
**Covers:** AC-121.2, AC-121.17
**Goal:** the existing e2e keeps its 115–120 expectations under the new answer and pins.

**Implementation notes:**
- After `cplat system new`: set `property_operators: owner` in `e2e-gitops/.copier-answers.yml` (one Python edit with `yaml.safe_load`
  / `safe_dump`, the value written as a string) and commit, with a comment naming spec 121 (the e2e installs ESO and Kyverno itself).
- Lines 879–880: compare `repository:tag` with `NATS_IMAGES["2.15"]` read from `templates/gitops-app/scripts/render.py` (equality, not a
  literal); the `echo` at 917 and the doctor needles at 1190/1199 stay (doctor prints references without digests).
- No other step changes; the header gains one line about the answer.

**Done when:** `tests/e2e/run.sh` passes on a local machine and in the e2e job within its 90 minutes.

## t17 — plugins and the CHANGELOG entry

**Files:** plugins/resource/commands/upgrade.md, plugins/resource/README.md, plugins/resource/.claude-plugin/plugin.json, plugins/platform/commands/doctor.md, plugins/platform/commands/update.md, plugins/platform/README.md, plugins/platform/.claude-plugin/plugin.json, plugins/system/commands/status.md, plugins/system/README.md, plugins/system/.claude-plugin/plugin.json, .claude-plugin/marketplace.json, docs/CHANGELOG.md
**Covers:** AC-121.6, AC-121.19, AC-121.23
**Goal:** `/resource:upgrade` exists and says what it does; doctor, update and status describe the new behaviour; the release entry lists
every changed versions row.

**Implementation notes:**
- `resource/commands/upgrade.md` (description under 260 characters, usage `/resource:upgrade <name> --to <major> [--env <env>]`): runs
  `cplat resource upgrade <ARGS> --pr --wait`, relays output verbatim, explains one environment per PR, the backup rule, staging and prod,
  and that a failure names `/resource:restore`; the `/issue:report` footer. README; 1.5.0 → 1.6.0.
- `platform/commands/doctor.md`: `--context [ENV=]CTX`, the states and CRD versions; `update.md`: the versions block, `--verify` after the
  merge, `cplat platform versions`; README; 1.2.0 → 1.3.0.
- `system/commands/status.md`: the Resource versions section; README; 1.4.0 → 1.5.0. Catalog entries mirror all three (if a parallel
  session bumped one, take the next minor).
- CHANGELOG `## [Unreleased]`: a new 121 entry **above** the 120 entry (which stays untouched): what changed (ADR-068/069), the image
  exception to byte-identity and why (CloudNativePG publishes no plain tags), `/resource:upgrade`, `property_operators`, doctor
  `--context`, the upgrade e2e and the release gate; then a block **Versions** with every line `cplat platform versions --diff <latest
  tag> --changelog` prints (rows added by 118–120 included); **Action** for existing repos (run `/platform:update`; optionally answer
  `property_operators: install` after removing hand-installed ESO, Kyverno, LGTM). Not BREAKING.

**Done when:** `devbox run validate`, the version-match loop and the plugin-doc tests (description length, usage, the 121 entry) pass, and
`release-check.py rows` is green on the branch.

## t18 — Docs

**Files:** docs/UPGRADES.md, docs/DOMAIN-MODEL.md, docs/USER-JOURNEY.md, docs/CLUSTERS.md, site/src/content/docs/concepts/domain-model.md, docs/adr/README.md
**Covers:** AC-121.17, AC-121.18
**Goal:** owners can see their versions, roll an upgrade, recover from a failed one, and decide who installs the property operators.

**Implementation notes:**
- `UPGRADES.md` (new): the versions table and `cplat platform versions`; held pins after `/platform:update`; `/resource:upgrade` step by
  step with every refusal in plain words; the backup rule; verification and the record; staging and prod; the way back (`/resource:restore`,
  and the CloudNativePG revert of a failed upgrade job); operators on one cluster; doctor `--context`; `property_operators`; the release
  gate for maintainers.
- `DOMAIN-MODEL.md`: `version` in the resource instance key rows; a short "Upgrading a resource" section linking the guide. Leave the first
  YAML block under "One file per system" as it is (AC-114.71's test parses it) and keep the needles of the 115–120 doc tests.
- `USER-JOURNEY.md`: a row "Upgrade a database or a cache" next to the backup row; `CLUSTERS.md`: operators move once per cluster,
  `lgtm` is not a cluster-repo operator, `property_operators` for system repos.
- Site page: the per-environment `version` in short, linking the guide.
- `docs/adr/README.md`: rows for 068 and 069 after 067, each one sentence matching the ADR's decision.
- `python3 scripts/check-links.py` stays green.

**Done when:** the doc tests (guide present and linked, key rows, index rows) pass and the 114–120 doc tests stay green.

## t19 — amend the spec 114–120 assertions that 121 extends

**Files:** tests/cplat/resources_fixtures.py, tests/cplat/cache_fixtures.py, tests/cplat/broker_fixtures.py, tests/cplat/test_addons.py, tests/cplat/test_resources_115.py, tests/cplat/test_bucket_116.py, tests/cplat/test_backup_117.py, tests/cplat/test_cache_118.py, tests/cplat/test_broker_119.py, tests/cplat/test_scale_120.py, tests/cplat/test_system_model_114.py, tests/cplat/test_system_render_114.py, tests/cplat/test_migrate_114.py
**Covers:** AC-121.2, AC-121.3, AC-121.5, AC-121.7
**Goal:** the earlier suites assert 5.x behaviour after spec 121 and nothing else. Each changed line ends with a `# spec 121: …` comment,
and the verification lists them as approved test changes.

**Implementation notes:**
- `resources_fixtures.py` line 20: `PIN_RE` = `^ghcr\.io/cloudnative-pg/postgresql:(\d+)\.\d+-\d{12}-standard-trixie@sha256:[0-9a-f]{64}$`
  (stricter: the digest is required). Append `UNPIN` (each designed new reference → its pre-121 string: the four Postgres references →
  `…postgresql:15.19` / `16.15` / `17.11` / `18.6`, Valkey and SeaweedFS and the Velero plugin and the collector without `@sha256:…`, the
  NATS tags `2.14.9-alpine@sha256:…` → `2.14.9-alpine` and likewise for 2.15) and `def unpin(g)` (string replacement per file).
- `test_addons.py` line 54: `postgresql:17\.\d+-\d{12}-standard-trixie@sha256:[0-9a-f]{64}$`.
- `test_resources_115.py` line 366 and `test_backup_117.py` line 209: the allowed list ends `…, resources, backup, version)`.
- `test_backup_117.py` line 661: `AWS_IMAGE` gains the designed digest; line 698: the regex adds `@sha256:[0-9a-f]{64}`.
- `cache_fixtures.py` line 14: `ALLOWED_INST` ends `, version`; line 18: `IMAGES` with the designed digests.
- `test_cache_118.py` lines 63–65: `test_version_is_not_an_instance_key_ac_118_2` becomes `test_an_unsupported_instance_version_fails_ac_118_2`
  with `{"version": 7}` and `resources.sessions.instances.dev: version '7' is not a supported cache version (8, 9)` (spec 121 adds the key);
  line 734: `tree_digest(unpin(g))`, and the import of `unpin`.
- `broker_fixtures.py` line 16: `ALLOWED_INST` ends `, version`; line 20: `NATS_IMAGES` with digests; line 135: split at `@` first and
  append the digest to `tag`.
- `test_broker_119.py` line 75: the parametrization drops `"version"` (`["backup", "bogus"]`); line 1172: `tree_digest(unpin(g))`, and the
  import.
- `test_bucket_116.py` line 491: the designed `SEAWEEDFS_IMAGE`.
- `test_scale_120.py` line 1001: `tree_digest(unpin(g))`, and the import.
- `test_system_model_114.py` line 204: `resource_instances` also drops `"version"` and `"pinned"`.
- `test_system_render_114.py` lines 41 and 55 and `test_migrate_114.py` lines 299–301: the normalisation also strips `@sha256:<64 hex>`
  after `otel/opentelemetry-collector-contrib:<tag>` (the same rule t7 gives the migration proof).
- No other assertion is changed or removed; if another 114–125 test fails only because of the new key, the digests, the new JSON keys or
  the copier answer, stop and report it instead of editing it.

**Done when:** the amended tests pass once t1, t2 and t9 are merged, and `git diff` of these files touches only the lines named here (plus
the appended `UNPIN`/`unpin` and the three imports).
