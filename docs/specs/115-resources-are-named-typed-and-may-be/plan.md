---
spec_id: 115-resources-are-named-typed-and-may-be
spec_hash: 5373e3577645
summary: "Resources become named and typed (database; bucket, cache and broker reserved with the spec that brings each), several databases per system each get their own CloudNativePG cluster and Secret <system>-<name>-app, a component using two resources of one type gets <NAME>_-prefixed variables, any resource instance may be external (one ExternalSecret from the secretStore, no cluster, no Argo app), the database image (majors 15-18) and the CloudNativePG chart are pinned exactly in the renderer's versions table, operators are rendered once per cluster under operators/ unless environments.<env>.operators: owner; /resource:add|remove, the model, status, doctor and the migration proof follow; a 5.0 system.yaml renders byte-identically except the pinned image"
tasks:
  - id: t1
    title: render.py — resource schema and validation (names, types, reserved types, external/remote keys, clashes, operators key, majors 15-18)
    files: [templates/gitops-app/scripts/render.py]
    covers: [AC-115.1, AC-115.2, AC-115.3, AC-115.5, AC-115.11, AC-115.17, AC-115.18]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: render.py — one CloudNativePG cluster per used database, the TYPES contract with the prefix rule, the versions table and the pinned image
    files: [templates/gitops-app/scripts/render.py]
    covers: [AC-115.4, AC-115.5, AC-115.6, AC-115.7, AC-115.8, AC-115.17]
    parallel_safe: false
    depends_on: [t1]
    done: true
  - id: t3
    title: render.py — external resource instances (ExternalSecret in the first using overlay, per-environment override, no cluster, no Argo app)
    files: [templates/gitops-app/scripts/render.py]
    covers: [AC-115.9, AC-115.10, AC-115.12]
    parallel_safe: false
    depends_on: [t2]
    done: true
  - id: t4
    title: render.py — operators/ once per cluster (root and pinned CloudNativePG application), operators owner opt-out, check and stale handling
    files: [templates/gitops-app/scripts/render.py]
    covers: [AC-115.18]
    parallel_safe: false
    depends_on: [t3]
    done: true
  - id: t5
    title: model.py — typed, external resource instances with Secret, Argo app and store key; Resource.external; Environment.operators
    files: [scripts/cplat/model.py]
    covers: [AC-115.5, AC-115.15]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t6
    title: model show text and system status cells for typed and external resource instances
    files: [scripts/cplat/modelcmd.py, scripts/cplat/status.py]
    covers: [AC-115.15]
    parallel_safe: true
    depends_on: [t5]
    done: true
  - id: t7
    title: cplat resource add <name> --type … [--external [--path]] and remove <name> for any resource
    files: [scripts/cplat/addon.py]
    covers: [AC-115.2, AC-115.13, AC-115.14]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t8
    title: Migration proof normalises the database image only
    files: [scripts/cplat/update.py]
    covers: [AC-115.6]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t9
    title: platform doctor — operator cloudnative-pg row (owner-managed vs platform-managed, installed vs expected)
    files: [scripts/cplat/doctor.py]
    covers: [AC-115.18]
    parallel_safe: true
    depends_on: [t2, t5]
    done: true
  - id: t10
    title: gitops-app template — bootstrap.sh and cluster-up apply operators/root.yaml first; no k3s CloudNativePG under Argo CD
    files: [templates/gitops-app/scripts/local-cluster.sh, templates/gitops-app/scripts/bootstrap.sh, templates/gitops-app/devbox.json, templates/gitops-app/CLAUDE.md.jinja]
    covers: [AC-115.18]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t11
    title: e2e — a second, external database with a missing store key, then complete; the operator comes from operators/
    files: [tests/e2e/run.sh]
    covers: [AC-115.9, AC-115.12, AC-115.18]
    parallel_safe: false
    depends_on: [t4, t10]
    done: true
  - id: t12
    title: resource plugin 1.1.0 (commands, README, manifest, catalog) and the CHANGELOG [Unreleased] entry
    files: [plugins/resource/commands/add.md, plugins/resource/commands/remove.md, plugins/resource/README.md, plugins/resource/.claude-plugin/plugin.json, .claude-plugin/marketplace.json, docs/CHANGELOG.md]
    covers: [AC-115.13, AC-115.14, AC-115.16]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t13
    title: Docs — DOMAIN-MODEL.md, USER-JOURNEY.md, README and the site's resources page
    files: [docs/DOMAIN-MODEL.md, docs/USER-JOURNEY.md, README.md, site/src/content/docs/concepts/addons.md]
    covers: [AC-115.16]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t14
    title: Amend the spec 113/114 assertions that spec 115 supersedes (pinned image, new keys and messages, added model fields)
    files: [tests/cplat/test_system_render_114.py, tests/cplat/test_commands_114.py, tests/cplat/test_migrate_114.py, tests/cplat/test_system_model_114.py, tests/cplat/test_addons.py, tests/cplat/test_model_show.py, tests/cplat/model_fixtures.py]
    covers: [AC-115.1, AC-115.6, AC-115.13, AC-115.15]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t15
    title: component set --uses — help text and the next step when the prefix rule starts to apply
    files: [scripts/cplat/compose.py]
    covers: [AC-115.8]
    parallel_safe: true
    depends_on: []
    done: true
human_steps:
  - "Consumer note for the release: a gitops repo whose real cluster already runs a hand-installed CloudNativePG sets environments.<env>.operators: owner before anyone applies operators/root.yaml; everyone else applies it once per cluster with KUBE_CONTEXT=<ctx> devbox run bootstrap (local clusters: devbox run cluster-up applies it)"
---

# Plan — 115 Resources are named, typed and may be external

The contract (schema, every message, render outputs, model fields, doctor rows) is in [design.md](design.md). The decisions
that outlive this spec are [ADR-057](../../adr/057-named-typed-resources-with-fixed-contracts.md) (named, typed resources,
contracts, external) and [ADR-058](../../adr/058-pinned-versions-and-platform-installed-operators.md) (versions table,
operators). Levels: t1, t5, t7, t8, t10, t12, t13, t14, t15 → t2, t6 → t3, t9 → t4 → t11.

`render.py` changes in four sequential tasks (t1 → t2 → t3 → t4) so each stays one focused pass. Every other task owns its
own files and runs in parallel. Never edit `scripts/cplat/assets/render_v4.py`.

## t1 — render.py: resource schema and validation

**Files:** templates/gitops-app/scripts/render.py
**Covers:** AC-115.1, AC-115.2, AC-115.3, AC-115.5, AC-115.11, AC-115.17, AC-115.18
**Goal:** `system.yaml` accepts any number of named, typed resources with `external`/`remote` and `environments.<env>.operators`,
and refuses every invalid form with the exact texts of design.md (Render errors). The rendered output does not change yet.

**Implementation notes:**
- Constants: `RESOURCE_TYPES`, `PLANNED_TYPES`, `RESOURCE_KEYS`, `RESOURCE_INSTANCE_KEYS`, `REMOTE_KEYS = ["path", "refreshInterval"]`,
  `RESOURCE_NAME = re.compile(r"^[a-z][a-z0-9-]*$")` (plus a length of at most 30), `ENV_KEYS` += `operators`.
- Rewrite `validate_resources(doc)` in the check order of the design table, per resource in declaration order; return the
  normalised `cfg["resources"]` mapping of design.md (Renderer API), with effective per-environment values for all three environments.
- In `validate_environments`, validate `operators` and keep the value in `conf["operators"][env]` (`"owner"` or absent).
- Run the cross checks in `_load_system` after the components are validated: resource vs component name, cluster-object
  clash (`CNPG_SUFFIXES`), component secret vs `<system>-<r>-app`.
- Support only the database `version` values 15, 16, 17 and 18 (int, or a digit string read as int). Any other major fails
  with the error naming the supported majors; this is the accepted narrowing of AC-115.6 (design.md). Checked only where
  some environment is in-cluster.
- Update the module docstring's `system.yaml` block (resources with `type`, `external`, `remote`, `instances.<env>.external`,
  `operators: owner`).
- Keep `cfg["postgres"]` until t2 replaces its readers, so the tree still renders after this task.

**Done when:** the AC-115.1, 115.2 (render part), 115.3 and 115.11 tests pass, as do the version-validation part of AC-115.17
and the `operators`-value part of AC-115.18, and the cluster-object and secret clash tests of AC-115.5.

## t2 — render.py: databases, contract variables, prefix rule, pinned image

**Files:** templates/gitops-app/scripts/render.py
**Covers:** AC-115.4, AC-115.5, AC-115.6, AC-115.7, AC-115.8, AC-115.17
**Goal:** every used in-cluster database renders its own `cluster.yaml` (`<system>-<name>`, the pinned image), and components
get the contract variables, prefixed where the rule says.

**Implementation notes:**
- Add `TYPES`, `POSTGRES_IMAGES`, `OPERATORS` (design.md). Fill in the exact values at build time: the newest
  `ghcr.io/cloudnative-pg/postgresql:<major>.<minor>` tag of 15, 16, 17 and 18 (the same image family as 5.0's `postgresql:17`),
  the CloudNativePG chart that `local-cluster.sh` uses today (`0.29.1`) unless it no longer exists, and that chart's
  `appVersion` as `operator_version`. Check each against the registry or chart index; name the sources in the commit message.
- Replace `ADDONS["postgres"]` with `TYPES["database"]`. `ADDONS` keeps only `observability`. The prune grouping reads
  "resource = no prune, observability = prune".
- `postgres_cluster` becomes `database_cluster(app, name, env, conf)`: the name and the `app.kubernetes.io/name` label come
  from the resource, `imageName` from `POSTGRES_IMAGES`. Key order and defaults stay as in 5.0.
- `addons_in`, `addon_files`: only in-cluster instances (all of them until t3), every name dispatched by type.
- `addon_env(app, svc, resources)`: in `uses` order, the bare names when the component uses one resource of that type,
  otherwise `<NAME>_<VAR>`. `validate_uses` checks clashes against these names.
- Expose `resource_instances(system)` and drop `cfg["postgres"]`.
- Byte identity: rendering a 5.0 `system.yaml` must differ from the 4.7 render only in `imageName` (the AC-115.6 test runs
  `same_as_4x` with the image normalised).

**Done when:** the AC-115.4, 115.5 (names), 115.6 (render part), 115.7, 115.8 and 115.17 tests pass.

## t3 — render.py: external resource instances

**Files:** templates/gitops-app/scripts/render.py
**Covers:** AC-115.9, AC-115.10, AC-115.12
**Goal:** an instance that is external in an environment renders no addon directory and no ApplicationSet element there,
only the ExternalSecret of design.md, in the overlay of the alphabetically first running component that uses it.

**Implementation notes:**
- `addons_in` skips external instances. A helper `external_secrets(app, env, services, cfg) -> {component: {fname: doc}}`
  builds one ExternalSecret per external resource instance with the store key, refreshInterval and data entries in
  `TYPES[type]["keys"]` order, `creationPolicy: Orphan`, `deletionPolicy: Retain`.
- In `render_app`'s overlay loop, merge the owner's files into `files`, so the `kustomization.yaml` `resources` list them
  (sorted) and `stale_paths` treats them as managed (`externalsecret-` prefix).
- The using components' variables (t2) are unchanged: the same names in every environment.
- `secretStoreRef` from `cfg["secretStore"]` (t1 guarantees it exists for external instances).

**Done when:** the AC-115.9 and AC-115.10 tests pass, as does the rendered-contract test of AC-115.12 (one `data` entry per
key, no `dataFrom`, no defaults). The in-cluster half of AC-115.12 is proven by t11.

## t4 — render.py: operators/ once per cluster

**Files:** templates/gitops-app/scripts/render.py
**Covers:** AC-115.18
**Goal:** `operators/root.yaml` and `operators/apps/cloudnative-pg.yaml` exist exactly when some system has an in-cluster
database instance in an environment without `operators: owner`. Otherwise `operators/` does not exist.

**Implementation notes:**
- `render_operators(app_dirs, ans) -> dict[Path, str]`, called in `main()` after every `render_app` succeeded (still
  validate-all-before-write). Documents exactly as in design.md (no `finalizers`).
- Stale handling: every file under `operators/` that is not wanted is stale. If nothing is wanted, `operators/` is removed.
  `--check` reports both like the other drift.
- `render_app`'s signature and outputs stay unchanged (`scripts/pin.py` calls it).

**Done when:** the AC-115.18 render tests pass (one operator application for two systems in one repo, none with every using
environment on `operators: owner`, none without in-cluster databases, removal when the last one goes). A 5.0 system without
a database renders no `operators/`.

## t5 — model.py: typed, external resource instances

**Files:** scripts/cplat/model.py
**Covers:** AC-115.5, AC-115.15
**Goal:** the model knows every resource's type and external flag. Every resource instance has its environment, type,
external flag, Secret `<system>-<name>-app`, Argo application (in-cluster only) and store key (external only).

**Implementation notes:**
- Fields and `to_dict()` keys exactly as in design.md (the model section); `schema` stays 2. New dataclass fields go at the
  end with defaults.
- Effective `external` per environment, by the render rule (instance, else resource, else false; only `True` counts).
  Store key from `remote.path` (merged), default `{system}-{env}-{resource}`.
- `_sizing` for every in-cluster database; `{}` for external instances.
- `Environment.operators` = `"owner"` when set, else `None`; in `to_dict()` as `"operators"`.
- Keep the model lenient (malformed parts skipped; the renderer validates).

**Done when:** the model part of AC-115.15 passes (the renderer–model agreement test compares name, environment, type and
external against `render.resource_instances`), plus the AC-115.5 model-name tests.

## t6 — model show text and system status cells

**Files:** scripts/cplat/modelcmd.py, scripts/cplat/status.py
**Covers:** AC-115.15
**Goal:** `cplat model show` prints the lines of design.md, and `/system:status` shows `external` for an external
resource instance instead of looking up a missing Argo application.

**Implementation notes:**
- `modelcmd.render`: the resource line, the in-cluster and external instance lines, and `  operators owner` on an
  environment line only when set.
- `status.py`: a cell `{"argo": "external"}` when `ri.external`; the text cell becomes `argo external`. Nothing else changes.

**Done when:** the text tests of AC-115.15 pass and the existing status tests stay green.

## t7 — cplat resource add/remove for any resource

**Files:** scripts/cplat/addon.py
**Covers:** AC-115.2, AC-115.13, AC-115.14
**Goal:** `/resource:add <name> --type database [--version N] [--external [--path P]]` and `/resource:remove <name>`
behave as in design.md (`cplat resource`). Every refusal happens before anything is written.

**Implementation notes:**
- Arguments `--type`, `--external`, `--path`; `postgres` defaults to `database`. The checks run in the order of the design
  table, using the same name rule and type lists as `render.py` (local constants; the module docstring names that file as
  the source).
- Entries and next steps as designed. Store keys for the next step via the default or `--path` template for dev, staging and prod.
- `remove`: the unknown-name text with the resource list; the used-by text with every user; `will_do` sentences per kind of instance.
- Docstring and argparse help say "resource", not "postgres".

**Done when:** the AC-115.13, AC-115.14 and command half of AC-115.2 tests pass (files unchanged on every refusal), and
5.0's `resource add postgres` default entry is unchanged.

## t8 — migration proof normalises the database image only

**Files:** scripts/cplat/update.py
**Covers:** AC-115.6
**Goal:** `cplat platform update --migrate` on a 4.7 repo writes the same `system.yaml` and accepts the new render when it
differs from the 4.7 render only in the pinned database image.

**Implementation notes:**
- In `apply_systems`, map both trees with the regex of design.md (only `applications/*/addons/*/*/cluster.yaml`) before the
  diff. The `missing`/`extra`/`changed` texts and the report stay as they are.
- `_tree` keeps comparing only `applications/` and `bootstrap/`; `operators/` is committed with the migration.

**Done when:** the AC-115.6 migration test passes and AC-114.40 to 114.42 stay green after t14.

## t9 — platform doctor: operator row

**Files:** scripts/cplat/doctor.py
**Covers:** AC-115.18
**Goal:** doctor prints one `operator cloudnative-pg` row per the design table, and for owner-managed environments compares
the installed with the expected version.

**Implementation notes:**
- Load the platform's `templates/gitops-app/scripts/render.py` with `importlib.util.spec_from_file_location` to read
  `OPERATORS` (the expected versions of this platform release).
- Needs come from the models (`_models`): in-cluster database resource instances per environment and `Environment.operators`.
- Installed version via `run(["kubectl", "get", "deploy", "-A", "-l", "app.kubernetes.io/name=cloudnative-pg", "-o", "jsonpath=…"])`.
  An empty result means missing.
- Remove the 5.0 `addon postgres` branch of `check_addons`; the lgtm branch stays.

**Done when:** the doctor tests of AC-115.18 (equal, missing, differing, owner vs platform, no row without in-cluster
databases or without kubectl) pass.

## t10 — gitops-app template: operator-first bootstrap and cluster-up

**Files:** templates/gitops-app/scripts/local-cluster.sh, templates/gitops-app/scripts/bootstrap.sh, templates/gitops-app/devbox.json, templates/gitops-app/CLAUDE.md.jinja
**Covers:** AC-115.18
**Goal:** a real cluster and the local cluster get the operator from `operators/` before the systems sync. The local
cluster installs CloudNativePG through k3s only without Argo CD.

**Implementation notes:**
- `scripts/bootstrap.sh` as in design.md (`set -euo pipefail`, shellcheck-clean). The `bootstrap` recipe in `devbox.json`
  runs it; no other recipe changes.
- `local-cluster.sh`: `WITH_CNPG` auto from `operators/apps/cloudnative-pg.yaml`, `CNPG_VERSION` default from its
  `targetRevision`, the Argo CD branch and the leftover-HelmChart message exactly as designed; update the header comment.
- `CLAUDE.md.jinja`: the layout lists `operators/` (GENERATED, cluster-level, applied once by a human) and the bootstrap row
  says it applies `operators/root.yaml` first.

**Done when:** the template text tests of AC-115.18 pass and `bash -n` and shellcheck are clean on both scripts.

## t11 — e2e: external database and operator from operators/

**Files:** tests/e2e/run.sh
**Covers:** AC-115.9, AC-115.12, AC-115.18
**Goal:** the end-to-end test shows that an external database instance syncs only with a complete store entry, and that the
CloudNativePG operator is installed at the pinned chart version from `operators/`.

**Implementation notes:**
- After the rendered `system.yaml` has its database: assert that `operators/apps/cloudnative-pg.yaml` exists and that the
  installed chart (HelmChart `kube-system/cnpg` version, `WITH_ARGO=0`) equals its `targetRevision`.
- Add `resources.ext-db: {type: database, external: true}` used by the website component in dev. Put a store entry
  `e2e-dev-ext-db` without `password` in the local store, render, apply the website overlay. Assert: no Secret
  `e2e-ext-db-app` within 60 s, the ExternalSecret's status message names `password`, the website pod not Ready. Then add
  `password` and assert the Secret has all six keys and the pod becomes Ready.
- Keep the later steps working (the Java service keeps its unprefixed `DATABASE_URL`: it uses only `postgres`).

**Done when:** `tests/e2e/run.sh` passes on a local machine with the release candidate; record the run in the
verification.

## t12 — resource plugin 1.1.0 and the CHANGELOG entry

**Files:** plugins/resource/commands/add.md, plugins/resource/commands/remove.md, plugins/resource/README.md, plugins/resource/.claude-plugin/plugin.json, .claude-plugin/marketplace.json, docs/CHANGELOG.md
**Covers:** AC-115.13, AC-115.14, AC-115.16
**Goal:** the commands describe named, typed and external resources; the change is announced as a minor, non-breaking release.

**Implementation notes:**
- `add.md` description: `Declare a resource of the system in system.yaml. Usage: /resource:add <name> --type database [--version N] [--external [--path P]]`
  (under 260 characters). The body covers the four types and the spec of each not-yet type, the prefix rule, external
  plus the store keys to set, the supported majors 15–18, and the operator note (operators/ or `operators: owner`).
- `remove.md`: any name; it refuses while used and names the users; data and the external Secret stay.
- `resource` 1.0.0 → 1.1.0 in both manifests. No other plugin changes.
- CHANGELOG `## [Unreleased]`: named, typed resources (ADR-057, spec 115), external instances, exact database image pins
  (majors 15–18; another `version` now fails the render, the one narrowing against 5.0) and operators under `operators/` with
  `operators: owner` (ADR-058), the consumer step of `human_steps`, resource 1.1.0. Do not mark it BREAKING.

**Done when:** `devbox run validate` and the version-match loop of `devbox run quality` are green, and the AC-115.16
changelog/version test passes.

## t13 — Docs

**Files:** docs/DOMAIN-MODEL.md, docs/USER-JOURNEY.md, README.md, site/src/content/docs/concepts/addons.md
**Covers:** AC-115.16
**Goal:** users can read how to declare named, typed and external resources.

**Implementation notes:**
- `DOMAIN-MODEL.md`: `resources.<name>` with `type`, the four types with spec 116/118/119 for the reserved ones, `external`
  with `remote` and the per-instance override, the prefix rule with the `orders-db`/`users-db` example, the Secret and
  Argo names, the supported database majors (15–18), `operators: owner`; the keys table rows as in design.md. Replace
  "postgres is the one resource in 5.0".
- `USER-JOURNEY.md`: the database row and the operators limitation (line ~270) now say the platform installs operators
  from `operators/`, unless the environment says `operators: owner`.
- `README.md` command table: `/resource:add|remove <name>`. Site `concepts/addons.md`: the database row with names, type and external.
- `python3 scripts/check-links.py` stays green; no 4.x names (AC-114.52's test).

**Done when:** the AC-115.16 documentation test passes.

## t14 — amend the spec 113/114 assertions that spec 115 supersedes

**Files:** tests/cplat/test_system_render_114.py, tests/cplat/test_commands_114.py, tests/cplat/test_migrate_114.py, tests/cplat/test_system_model_114.py, tests/cplat/test_addons.py, tests/cplat/test_model_show.py, tests/cplat/model_fixtures.py
**Covers:** AC-115.1, AC-115.6, AC-115.13, AC-115.15
**Goal:** the older suites assert 5.x behaviour where spec 115 changes it on purpose, and nothing else. Each change carries a
`# spec 115: …` comment, and the verification lists them as approved test changes.

**Implementation notes:**
- `test_system_render_114.py`: `same_as_4x` normalises `imageName` (the design regex) on both sides; the environment-key
  message lists `operators`; `test_another_resource_name_or_type_fails_ac_114_19` expects the AC-115.1 texts
  (`redis` of type `database` now renders); `test_an_unknown_resource_key_fails_ac_114_19` expects the new allowed list.
- `test_commands_114.py`: `resource add redis` without `--type` expects `--type is required for redis (database, bucket, cache or broker)`.
- `test_migrate_114.py`: the AC-114.40 byte-identity test normalises `imageName` before comparing.
- `test_addons.py`: the image assertion matches the pinned form `postgresql:17\.\d+`; the `mysql` case expects the AC-115.3/115.1 outcome (a valid database).
- `test_model_show.py`, `model_fixtures.py`, `test_system_model_114.py`: expected resource and resource-instance JSON and text
  gain the added fields; the 4.7 ↔ 5.0 comparison drops the 115 fields before comparing.
- No other assertion is changed or removed.

**Done when:** the amended tests pass once t1–t8 are merged, and `git diff` of these files touches only the assertions named here.

## t15 — component set --uses: help and prefix note

**Files:** scripts/cplat/compose.py
**Covers:** AC-115.8
**Goal:** the developer learns when a second resource of one type renames their variables.

**Implementation notes:**
- `--uses` help: `resource or library the component needs (a database gives DATABASE_URL and PG*); declare it first with cplat resource add <name> --type database`.
- After `set --uses`, if the component now uses two or more resources of one type (types read from `resources:` of the
  loaded system.yaml), add the next step `<component> now uses <n> <type> resources: their variables are prefixed (<NAME>_DATABASE_URL, …) and DATABASE_URL, PG* are no longer injected`.
- The next-step line after `add` names `/resource:add <name> --type database` instead of `/resource:add postgres`.

**Done when:** the AC-115.8 command-note test passes; the existing compose tests stay green.
