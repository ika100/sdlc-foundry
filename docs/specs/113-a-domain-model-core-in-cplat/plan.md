---
spec_id: 113-a-domain-model-core-in-cplat
spec_hash: b710c65bb484
summary: One tested module (scripts/cplat/model.py) loads a gitops-app into System, Component, Resource, Environment,
  Instance and Resource instance with their rules; status, promote, smoke, the staging promotion, the alert poll, secret
  and the app-ship gate class take their answers from it with unchanged output; `cplat model show [--json]` prints the
  model; an AST guard keeps environment lists and overlay pin reads inside the model
tasks:
  - id: t1
    title: model.py — nouns, rules, build/load_dir/load_remote, lazy pins, pin read/write, to_dict and relations
    files: [scripts/cplat/model.py]
    covers: [AC-113.1, AC-113.2, AC-113.3, AC-113.4, AC-113.5, AC-113.6, AC-113.7, AC-113.8, AC-113.9, AC-113.10, AC-113.15]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: cplat model show [--json] [--app] [--repo-dir] and its help line
    files: [scripts/cplat/modelcmd.py, scripts/cplat/cplat.py]
    covers: [AC-113.14, AC-113.15, AC-113.16, AC-113.17]
    parallel_safe: true
    depends_on: [t1]
  - id: t3
    title: status on the model (Instances, Resource instances, observed state per run); gitops.ENVS becomes an alias
    files: [scripts/cplat/status.py, scripts/cplat/gitops.py]
    covers: [AC-113.9, AC-113.11, AC-113.12, AC-113.13]
    parallel_safe: true
    depends_on: [t1]
  - id: t4
    title: promote on the model (environment order, Instances, staging pin for the digest check, pin write)
    files: [scripts/cplat/promote.py]
    covers: [AC-113.9, AC-113.11, AC-113.12, AC-113.13]
    parallel_safe: true
    depends_on: [t1]
  - id: t5
    title: smoke dev URL and the staging promotion decision through model.load_remote
    files: [scripts/cplat/smoke.py, scripts/cplat/staging.py, scripts/cplat/staging_deploy.py]
    covers: [AC-113.10, AC-113.11, AC-113.12, AC-113.13]
    parallel_safe: true
    depends_on: [t1]
  - id: t6
    title: alert poll sources on the model (polled environments, ServiceDown per Instance, label to environment)
    files: [scripts/cplat/alertsources.py]
    covers: [AC-113.11, AC-113.12, AC-113.13]
    parallel_safe: true
    depends_on: [t1]
  - id: t7
    title: secret store keys and the app-ship "exposed in dev" gate class from the model
    files: [scripts/cplat/secret.py, scripts/cplat/appship_sched.py]
    covers: [AC-113.12, AC-113.13, AC-113.18]
    parallel_safe: true
    depends_on: [t1]
  - id: t8
    title: Docs — CHANGELOG (4.x minor, nothing changed for users) and the domain model guide's Status
    files: [docs/CHANGELOG.md, docs/DOMAIN-MODEL.md]
    covers: [AC-113.17]
    parallel_safe: true
    depends_on: []
---

# Plan — 113 A domain model core in cplat

Design: [design.md](design.md) (the `model.py` API, the `cplat model show` text and JSON, how each caller uses the model,
the guard). Red tests first, in new files only (`tests/cplat/test_model.py`, `test_model_show.py`,
`test_model_callers.py`, `test_model_guard.py`, `test_model_release.py`); no existing test file is edited (AC-113.12).
t1 and t8 start together; t2–t7 start when t1 is merged and run in parallel (no shared files). The guard (AC-113.13)
turns green only when t3–t7 are all merged. Gates (this repo has no `test-fast`/`ci` devbox scripts): the cplat tests
(`uv run --with pytest --with pytest-xdist --with pyyaml --with ruamel.yaml pytest tests/cplat -q -n auto`), then
`devbox run ci-local`.

## t1 — model.py

**Files:** scripts/cplat/model.py
**Covers:** AC-113.1, AC-113.2, AC-113.3, AC-113.4, AC-113.5, AC-113.6, AC-113.7, AC-113.8, AC-113.9, AC-113.10, AC-113.15
**Goal:** the one module that turns `app.yaml`, `services.yaml`, the overlay pins and the shape registry into the nouns,
with every rule about a component in an environment, exactly as the design's contract names them.

**Implementation notes:**
- `ENVIRONMENTS = ("dev", "staging", "prod")`, `DEFAULT_LOCAL_PORT = 8088`, `SCHEMA = 1`, `ModelError(core.PlatformError)`.
  Import only `core` and `yaml` (no `gitops`, no command module, nothing under `templates/`).
- Dataclasses `Environment`, `Observability`, `Component`, `External`, `Secret`, `InstanceSecret`, `Resource`,
  `Instance`, `ResourceInstance`, `Model` with the design's fields. `Instance.tag` is lazy (one `pins` call at most,
  cached); `Instance.observed` is an empty dict excluded from comparison and from `to_dict`.
- `build(system, services, app, *, pins=None, shapes=None)`: pure; skips entries that are not mappings or lack `name`;
  `type`/`lang` from the registry (`library: true` → library, `plugin: web` → website, else service; language from
  `default_stack.language`, else `unknown`); unknown environments become warnings, not Instances.
- Environment rules from `app.yaml`: `hosts`, `urls`, `policies` (off / per-env mode with Enforce-in-prod default),
  promotion (`main`, `promotion.staging` or `manual`, `manual`), observability as declared.
- Instance rules: replicas (per-env map default 1, or integer; None for external), namespace (`<system>-<env>` or
  `external.namespace`), `<component>-<env>`, `exposed`, the URL rule of the design (same as `smoke.dev_url` today,
  reading `LOCAL_HTTP_PORT` when computed), `staging_promotion`, secrets with `store_key`.
- Resources: every addon except `observability`; Resource instances only where a using Component has an Instance;
  postgres sizing per env with defaults 1, 17, `1Gi`, Argo `addon-<r>-<env>`, Secret `<system>-postgres-app`.
- `Model` methods: `environment`, `component`, `find_component(repo, name)` (repo first, then name), `instance`,
  `instances_of`, `instances_in`, `resource_instances_of`, `promoted_from` (directly preceding env only),
  `staging_promotion`, `url(component, env)` → `(url, None)` or `(None, "not exposed in <env>")`, `secrets(component,
  env)`, `relations()`, `to_dict()` (the design's JSON, `schema: 1`, no observed state).
- Loaders: `load_dir(app_dir)` (strict: `ModelError` naming `applications/<app>/<file>` for a YAML error or a non-mapping
  top level; missing `app.yaml` = `{}`), `load_remote(system, read)` (reads the two files once, pins lazily, unreadable
  = absent). No subprocess, network or GitHub call of its own.
- Pins: `pin_path`, `pin_of` (first image with a non-empty `newTag`, as str), `read_pin` (None when missing or
  unparseable), `write_pin` (set `images[0].newTag`, `yaml.safe_dump(sort_keys=False, default_flow_style=False)`).

**Done when:** `tests/cplat/test_model.py` passes (including the order check against the renderer's `ENVS` and the
GitHub-equals-checkout comparison), and `model.py` makes no subprocess or network call (AC-113.9).

## t2 — cplat model show

**Files:** scripts/cplat/modelcmd.py, scripts/cplat/cplat.py
**Covers:** AC-113.14, AC-113.15, AC-113.16, AC-113.17
**Goal:** the read-only command that prints the model in the design's text or JSON form.

**Implementation notes:**
- `modelcmd.main(argv)`: subcommand `show` with `--json`, `--app`, `--repo-dir` (default `.`, resolved like `status`).
- App dir from `gitops.find_app` (same errors and fixes as `cplat status`); `model.load_dir` (its `ModelError` exits 1
  through `cplat.main`).
- Text: the five sections in the design's order and format; `  (none)` for an empty section; `not pinned` and `-`.
- JSON: `print(json.dumps(m.to_dict(), indent=2))`.
- Each `m.warnings` entry to stderr as `warning: <text>`; exit 0. Writes nothing; no observed state.
- `cplat.py`: `COMMANDS["model"] = "modelcmd"` and the help line
  `cplat.py model show [--json] [--app APP] [--repo-dir DIR]   the product in the domain model's nouns, declared state only (spec 113)`.
  No slash command.

**Done when:** `tests/cplat/test_model_show.py` passes and the `--help` part of `test_model_release.py` passes.

## t3 — status on the model

**Files:** scripts/cplat/status.py, scripts/cplat/gitops.py
**Covers:** AC-113.9, AC-113.11, AC-113.12, AC-113.13
**Goal:** `cplat status` rows come from Instances and Resource instances; table, `--json` and exit code unchanged.

**Implementation notes:**
- `collect`: `model.load_dir(app_dir)`; CI and platform lookups once per Component with a `repo`, before its rows (as
  now); one row per `m.instances_of(c)` with `inst.tag or "?"`, `inst.argo_application`, `bool(c.expose)`, pin PR on
  dev only; attach Argo/CI answers to `inst.observed` for this run.
- Addon rows in `m.declared_addons` order: `observability` → one row per Environment with Instances
  (`env.observability.argo_application`); others → `m.resource_instances_of(name)`.
- `pinned_tag(app_dir, env, name)` stays (tests call it) as `return model.read_pin(app_dir, env, name)`. Drop `ENVS`.
- `gitops.py`: `ENVS = list(model.ENVIRONMENTS)` (kept for `compose`, which this spec does not move).

**Done when:** the existing status tests in `test_gitops.py`, `test_drift.py`, `test_feedback.py`,
`test_autoissue_ship.py` pass unchanged, and the status parts of `test_model_callers.py` pass (same rows as before,
clean working tree after `status --context`).

## t4 — promote on the model

**Files:** scripts/cplat/promote.py
**Covers:** AC-113.9, AC-113.11, AC-113.12, AC-113.13
**Goal:** `cplat promote` takes the environment order, Instance membership and the staging pin from the model and writes
pins through it; every message, JSON key, refusal and written file stays the same.

**Implementation notes:**
- Drop `ORDER` and `_staging_tag`; validate and order environments with `model.ENVIRONMENTS`.
- After `gitops.load`, `m = model.load_dir(app_dir)`; `--all` and "is not in <from> yet" use `m.instance(n, frm)`.
- Digest check: `staging_tag = inst.tag if (inst := m.instance(n, "staging")) else None` for prod promotions.
- Pin write after the first `gitops.render`: `model.write_pin(app_dir, to, n, tag)`; keep both renders.
- The ruamel edit of `environments` stays as it is.

**Done when:** `test_gitops.py` promote tests and `test_promote_digest.py` pass unchanged, and the promote parts of
`test_model_callers.py` pass (including a clean working tree after `--dry-run`).

## t5 — smoke dev URL and the staging decision

**Files:** scripts/cplat/smoke.py, scripts/cplat/staging.py, scripts/cplat/staging_deploy.py
**Covers:** AC-113.10, AC-113.11, AC-113.12, AC-113.13
**Goal:** both read the linked gitops-app through `model.load_remote` with their own `gh` seams, and answer exactly as
before.

**Implementation notes:**
- `smoke.dev_url`: keep `_slug`, `_read`, `_app_dirs` and the two final reasons; per app dir
  `m = model.load_remote(a, lambda p: _read(slug, p, repo))`, `c = m.find_component(me, service)`; `url, why =
  m.url(c.name, env)`; reason text `f"{service} has no {env} URL ({why})"`. `DEFAULT_LOCAL_PORT = model.DEFAULT_LOCAL_PORT`.
- `staging._find` returns `(slug, app_dir, component, model, me)` through `model.load_remote(a, lambda p: _read(slug, p,
  repo))`; `decide` uses `m.staging_promotion(c)`, `m.instance(c.name, "staging")`, and `inst.tag` as `previous`.
  Remove `effective` and `staging_tag` (no test uses them); keep every reason string.
- `staging_deploy.promote`: `registry.image_name({"image": found[2].image} if found else None, ship.service_slug(repo))`.

**Done when:** `test_smoke_091_run.py`, `test_smoke_091_ship.py`, `test_staging_093_*.py`, `test_deploy_checks.py`,
`test_telemetry_more.py` pass unchanged, and the smoke/staging parts of `test_model_callers.py` pass.

## t6 — alert poll sources on the model

**Files:** scripts/cplat/alertsources.py
**Covers:** AC-113.11, AC-113.12, AC-113.13
**Goal:** the polled environments, the built-in `ServiceDown` rules and the label-to-environment mapping come from the
model; every skip reason, note and alert stays the same.

**Implementation notes:**
- `load_app` keeps its lenient `_read_yaml`, then `m = model.build(app, services_doc, cfg)`; add
  `model: Model | None = None` as the last `AppConfig` field.
- `envs = [e.name for e in m.environments if m.instances_in(e.name)]`; `ServiceDown` per `inst in m.instances` whose
  Component has `metrics` (same order as before: component, then environment).
- `_env_of` uses `model.ENVIRONMENTS` for the label values and the namespace/instance patterns. Drop `ENVS` and
  `_envs_of`; `NO_ENV_NOTE` text unchanged.
- `alerts.py` needs no change.

**Done when:** `test_alertsources.py`, `test_alerts_poll.py` and the other `test_alerts_*.py` pass unchanged, and the
alert parts of `test_model_callers.py` pass.

## t7 — secret and the app-ship gate class

**Files:** scripts/cplat/secret.py, scripts/cplat/appship_sched.py
**Covers:** AC-113.12, AC-113.13, AC-113.18
**Goal:** `cplat secret` takes secrets and store keys, and `gate_class` takes "exposed in dev", from the model.

**Implementation notes:**
- `secret.py`: replace `declared` and `store_key` with `m = model.load_dir(app_dir)` and `m.secrets(c.name, ns.env)`
  over the Components that declare secrets (same order); generated vs remote, keys, `MISSING → …` lines, the
  "has no secret" / "not a key" errors and the store key in `set` stay byte-for-byte.
- `appship_sched.gate_class`: keep the `git show origin/main` reads and the entry matching; once found,
  `m = model.build(<app basename>, services, app_doc)`, `inst = m.instance(found.get("name"), "dev")`;
  `exposed` when `inst is not None and inst.exposed`, else `internal`. Update the docstring to name the model.

**Done when:** the secret tests in `test_gitops.py` and `test_appship_097.py` pass unchanged, and the secret and
gate-class parts of `test_model_callers.py` pass.

## t8 — Docs

**Files:** docs/CHANGELOG.md, docs/DOMAIN-MODEL.md
**Covers:** AC-113.17
**Goal:** the release notes and the guide say what this 4.x minor adds and that nothing else changes.

**Implementation notes:**
- CHANGELOG `[Unreleased]`: `**Feat (113): a domain model core in cplat.**` with links to ADR-053 and the guide; one
  module now answers "this component in that environment" for `status`, `promote`, `smoke`, the staging promotion, the
  alert poll, `secret` and the `/app:ship` gate; new `cplat model show [--json]` (no slash command); no command, flag,
  output format or file schema changed, no action for existing repos; the JSON carries `schema: 1` and may change in 5.0.
- DOMAIN-MODEL.md "Status": the internal core (spec 113) is in place; `cplat model show` prints a product in these
  nouns; its JSON (`schema: 1`) may change in 5.0; the switch to `system.yaml` and noun commands is still spec 114.

**Done when:** the changelog and guide parts of `test_model_release.py` pass and the Markdown link check is green.
