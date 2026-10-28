# Design — 113 A domain model core in cplat

## Decisions

- **One module, `scripts/cplat/model.py`, owns the nouns and every rule about "a component in an environment"** (AC-113.1–AC-113.8): the environment list, the overlay pin (read and write), the namespace and Argo names, the URL rule, the staging promotion rule, the secret-store key, the Resource instances and their sizing. Commands keep their own I/O (GitHub, kubectl, registry, git) and their own output; they ask the model for the answers. The model imports only `core` (for `PlatformError` and the shape registry) and `yaml`; it never imports `gitops`, a command module or the gitops-app template (`gitops` imports the model, not the reverse).
- **A pure builder plus three thin loaders.** `build(system, services, app, pins=...)` turns already-parsed `services.yaml` and `app.yaml` mappings into a `Model` and never does I/O except through the `pins` callback. `load_dir` (a local checkout, strict: an unparseable file is an error naming it), `load_remote` (any repo-relative reader, lenient: an unreadable file is "absent", as `smoke` and `staging` behave today) and the callers that already hold parsed mappings (`alertsources`, `appship_sched`, which must stay lenient) all go through `build`. One builder is what makes AC-113.10 (GitHub equals checkout) true by construction.
- **Pins are read lazily.** `Instance.tag` reads its overlay on first access, at most once, through the loader's `pins` callback. Remote callers (smoke's dev URL, the staging decision) otherwise make overlay reads their existing `gh` fakes do not answer, and `cplat smoke run` needs no pin at all. `to_dict()` resolves every pin.
- **The `gh` seams stay in the callers.** `load_remote` takes `read(path) -> dict | None`; `smoke` passes a reader built on `smoke._read` (so `smoke.gh` is still the seam), `staging` one built on `staging._read` (`staging.gh`). No existing test changes (AC-113.12).
- **The structural guard is an AST test** over `scripts/cplat/*.py` minus `model.py` (AC-113.13), with positive controls so it cannot silently pass.
- `cplat model show` lives in a new command module `modelcmd.py` (like `shapecmd.py`), registered as `model` in `cplat.py`. No slash command (AC-113.17).
- No new ADR: ADR-053 already decides the module and the two-step path; everything here is local to this feature.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/model.py` | nouns, rules, loaders, pin read/write, `to_dict`, relations | new |
| `scripts/cplat/modelcmd.py` | `cplat model show [--json] [--app] [--repo-dir]` | new |
| `scripts/cplat/cplat.py` | `COMMANDS["model"] = "modelcmd"`, help line | changed |
| `scripts/cplat/gitops.py` | `ENVS = list(model.ENVIRONMENTS)` (alias for `compose`, which is not moved) | changed |
| `scripts/cplat/status.py` | rows from Instances and Resource instances; `pinned_tag` delegates to `model.read_pin` | changed |
| `scripts/cplat/promote.py` | env order, "is in <from>", `--all`, staging pin from the model; pin write through `model.write_pin` | changed |
| `scripts/cplat/smoke.py` | `dev_url` through `model.load_remote`, `find_component`, `url` | changed |
| `scripts/cplat/staging.py` | `_find`/`decide` through the model: promotion rule, "in staging", staging pin | changed |
| `scripts/cplat/staging_deploy.py` | reads the image from the Component `_find` now returns | changed |
| `scripts/cplat/alertsources.py` | polled environments, `ServiceDown` per Instance with metrics, label → environment from the model | changed |
| `scripts/cplat/secret.py` | secrets and store keys from `Model.secrets(component, env)` | changed |
| `scripts/cplat/appship_sched.py` | "exposed in dev" from the dev Instance | changed |
| `scripts/cplat/alerts.py` | none: it takes `cfg.envs` and `cfg.services` from `alertsources` | unchanged |

## Contract — `model.py` (Python API, binding for the tests)

```python
ENVIRONMENTS: tuple[str, ...] = ("dev", "staging", "prod")   # promotion order; the only such list in cplat
DEFAULT_LOCAL_PORT = 8088                                   # smoke.DEFAULT_LOCAL_PORT becomes an alias of this
SCHEMA = 1

class ModelError(core.PlatformError): ...                    # unparseable file (load_dir only)

def build(system: str, services: dict | None, app: dict | None, *,
          pins: Callable[[str, str], str | None] | None = None,      # (env, component) -> tag; None = nothing pinned
          shapes: list[dict] | None = None) -> Model                 # default: core.registry.load()
def load_dir(app_dir: Path, *, shapes: list[dict] | None = None) -> Model
def load_remote(system: str, read: Callable[[str], dict | None], *, shapes: list[dict] | None = None) -> Model
def pin_path(env: str, component: str) -> str                # "overlays/<env>/<component>/kustomization.yaml" (relative to the app dir)
def pin_of(doc: dict | None) -> str | None                   # first `images` entry with a non-empty newTag, as str
def read_pin(app_dir: Path, env: str, component: str) -> str | None
def write_pin(app_dir: Path, env: str, component: str, tag: str) -> None
```

- `load_dir(app_dir)`: system = `app_dir.name`; parses `services.yaml` (must exist) and `app.yaml` (absent = `{}`) with `yaml.safe_load`; a YAML error or a top level that is not a mapping raises `ModelError(f"cannot parse applications/<app>/<file>: <first line of the problem>", hint=f"fix the YAML in applications/<app>/<file>")`. Pins: `read_pin(app_dir, env, c)`.
- `load_remote(system, read)`: calls `read(f"applications/{system}/services.yaml")` and `read(f"applications/{system}/app.yaml")` once each (None = `{}`); pins call `read(f"applications/{system}/" + pin_path(env, c))` lazily. Nothing else is read.
- `read_pin` returns None when the file is missing or unparseable. `write_pin` reads the overlay, sets `images[0].newTag`, and writes it with `yaml.safe_dump(doc, sort_keys=False, default_flow_style=False)` (exactly what `promote` writes today).
- Entries of `services` that are not mappings or have no `name` are skipped (as `alertsources` does today).

### Nouns

| Class | Fields (all read-only for callers except `Instance.observed`) |
|---|---|
| `Environment` | `name`, `order` (0,1,2), `host: str \| None` (`hosts.<env>`), `url_template: str \| None` (`urls.<env>`), `policy: str` (`off`, else `str(policies.mode.<env>)` per-env map or scalar, default `Enforce` in prod and `Audit` elsewhere; `policies` absent or `false` = `off`), `promotion: str` (dev `main`; staging `promotion.staging` of `app.yaml` or `manual`; prod `manual`), `observability: Observability \| None` |
| `Observability` | `ui`, `export_to`, `alerts`, `rules`, `query_url`, `alertmanager_url`: the declared values or None; `argo_application` = `addon-observability-<env>`. Present on every Environment when `app.yaml` `addons` has the key `observability` (a null value counts as declared). Never a Resource |
| `Component` | `name`, `repo`, `image`, `shape` (as declared or None), `type` (`library` when the registry entry has `library: true`, `website` when its `plugin` is `web`, else `service`; unknown or missing shape: `service`), `lang` (registry `default_stack.language`, else `unknown`), `external: External \| None`, `expose` (raw: falsy, `true` or a mapping), `metrics: str \| None`, `uses: tuple[str]` (declared Resources only, in entry order), `environments: tuple[str]` (the entry's list, `[dev]` when missing or empty, filtered to `ENVIRONMENTS`, de-duplicated, in promotion order), `promotion_staging: str \| None` (entry `promotion.staging`), `secrets: tuple[Secret]`, `secret_refs: tuple[str]` |
| `External` | `kind` (`kustomize` or `helm`, the first key present), `namespace: str \| None` |
| `Secret` | `name`, `kind` (`generate` when `generate` is non-empty, else `remote`), `keys: tuple[str]` (generate keys or `remote.keys`), `path: str \| None` (`remote.path`) |
| `InstanceSecret` | `name`, `kind`, `keys`, `store_key: str \| None` (remote: `(path or "{app}-{env}-{secret}").format(app=system, env=env, secret=name, service=component)`; generate: None) |
| `Resource` | `name` (every `app.yaml` addon except `observability`), `type` (`database` for postgres, else `unknown`) |
| `Instance` | `component`, `environment`, `image`, `tag` (lazy, see above), `replicas: int \| None` (entry `replicas.<env>` default 1, or its single integer; None for external), `namespace` (`<system>-<env>`, or `external.namespace`), `argo_application` (`<component>-<env>`), `exposed: bool` (`expose` truthy and the Environment has a host), `url: str \| None`, `staging_promotion: str` (Component's `promotion_staging`, else the staging Environment's `promotion`), `secrets: tuple[InstanceSecret]`, `observed: dict` (empty; a command may attach what it computed for its own run; never serialized) |
| `ResourceInstance` | `resource`, `environment`, `argo_application` (`addon-<resource>-<env>`), `secret` (`<system>-postgres-app` for postgres, else None), `sizing` (postgres: `instances` int, `version`, `storage` str, each per-env map or scalar, defaults 1, 17, `1Gi`; others `{}`). One per Environment in which at least one Component that uses the Resource has an Instance |
| `Model` | `system`, `environments`, `components`, `resources`, `instances` (component order, then promotion order), `resource_instances` (resource order, then promotion order), `declared_addons: tuple[str]` (`app.yaml` addon keys in file order, including `observability`), `warnings: tuple[str]` |

### URL rule (AC-113.5; the rule `smoke.dev_url` has today)

`Instance.url` is None unless the Component has `expose` and the Environment has a host template. Then `host = host_template.format(service=(expose.host if expose is a mapping else None) or component, app=system, env=env)`; the URL is `url_template.format(host=host, service=component, app=system, env=env)` when `urls.<env>` is set, else `http://<host>:<LOCAL_HTTP_PORT if it is all digits else 8088>` for a host ending in `.localhost`, else `https://<host>`. `LOCAL_HTTP_PORT` is read from the environment when `url` is computed.

### `Model` methods

```python
environment(name) -> Environment | None
component(name) -> Component | None
find_component(repo: str, name: str) -> Component | None     # by `repo` first, then by name (smoke/staging lookup)
instance(component, env) -> Instance | None
instances_of(component) -> list[Instance];  instances_in(env) -> list[Instance]
resource_instances_of(resource) -> list[ResourceInstance]
promoted_from(inst) -> Instance | None    # same component, directly preceding environment; None for dev or when that Instance is missing
staging_promotion(component) -> str       # Component's promotion_staging, else staging Environment's promotion
url(component, env) -> tuple[str | None, str | None]          # (url, None) or (None, f"not exposed in {env}")
secrets(component, env) -> tuple[InstanceSecret, ...]          # the Instance's secrets; for an env without an Instance, the same rule (secret.py lists every env)
relations() -> list[dict]; to_dict() -> dict                   # the JSON below
```

Warnings: one string per (component, unknown environment) in entry order: `<component> lists unknown environment '<env>': no Instance`.

## Contract — `cplat model show`

`cplat model show [--json] [--app NAME] [--repo-dir DIR]`. `--repo-dir` default `.`, resolved like `cplat status`; the app dir comes from `gitops.find_app`, so outside a gitops-app, with several applications and with an unknown `--app` the error and `fix:` lines are exactly those of `cplat status` (exit 1). An unparseable `services.yaml`/`app.yaml` exits 1 with `ERROR: cannot parse applications/<app>/<file>: …`. It reads only the files listed in the spec and the shape registry, writes nothing, and makes no subprocess or network call. Exit 0 otherwise. Each model warning is printed to **stderr** as `warning: <warning>` (so `--json` stdout stays one JSON object).

### Text (stdout)

Sections in this order, separated by one empty line. Each item line is two spaces and then its fields joined by two spaces (no padding). `-` stands for "none".

```
System: shop

Environments (promotion order):
  dev  host {service}.{app}-dev.localhost  url-template -  policy off  promotion follows main  observability ui=lgtm export=- alerts=on rules=0
  staging  host -  url-template -  policy off  promotion manual  observability ui=lgtm export=- alerts=on rules=0
  prod  host -  url-template -  policy off  promotion manual  observability ui=lgtm export=- alerts=on rules=0

Components:
  shop-api  type service  lang python  repo acme/shop-api  image ghcr.io/acme/shop-api  uses postgres  secrets api-keys
  stock  type service  lang unknown  repo acme/stock  image ghcr.io/acme/stock  external kustomize  uses -  secrets -

Instances:
  shop-api  dev  sha-0123456789abcdef0123456789abcdef01234567  replicas 1  namespace shop-dev  url http://shop-api.shop-dev.localhost:8088
  shop-api  staging  not pinned  replicas 2  namespace shop-staging  url -
  stock  dev  sha-abc1234  replicas -  namespace stock  url -

Resources:
  postgres  type database  used by shop-api
    dev  instances 1  version 17  storage 1Gi  argo addon-postgres-dev  secret shop-postgres-app
```

- Environment `promotion` prints `follows main` for dev, else the value. `observability -` when absent; else `ui=<ui or none> export=<exportTo or -> alerts=<off when alerts is false, else on> rules=<number of declared rules>`.
- The `external <kind>` field appears only for external Components, between `image` and `uses`. `secrets` lists declared secret names joined by `,`.
- An empty section prints `  (none)`. A Resource with no Resource instance prints only its line.
- No Argo sync/health, running image, digest, smoke result or alert appears anywhere.

### JSON (`--json`, stdout, `indent=2`)

```json
{
  "schema": 1,
  "system": {"name": "shop", "components": ["shop-api"], "resources": ["postgres"]},
  "environments": [
    {"name": "dev", "host": "{service}.{app}-dev.localhost", "url": null, "policy": "off", "promotion": "main",
     "observability": {"ui": "lgtm", "exportTo": null, "alerts": null, "rules": null, "queryURL": null, "alertmanagerURL": null}}
  ],
  "components": [
    {"name": "shop-api", "type": "service", "lang": "python", "shape": "service-python", "repo": "acme/shop-api",
     "image": "ghcr.io/acme/shop-api", "external": null, "expose": true, "metrics": "/metrics", "uses": ["postgres"],
     "environments": ["dev", "staging"], "promotion": {"staging": null},
     "secrets": [{"name": "api-keys", "kind": "remote", "keys": ["STRIPE_KEY"]}], "secret_refs": []}
  ],
  "resources": [{"name": "postgres", "type": "database", "used_by": ["shop-api"]}],
  "instances": [
    {"component": "shop-api", "environment": "staging", "image": "ghcr.io/acme/shop-api", "tag": null, "replicas": 2,
     "namespace": "shop-staging", "argo_application": "shop-api-staging", "url": null, "exposed": false,
     "promoted_from": "shop-api/dev",
     "secrets": [{"name": "api-keys", "kind": "remote", "keys": ["STRIPE_KEY"], "store_key": "shop-staging-api-keys"}]}
  ],
  "resource_instances": [
    {"resource": "postgres", "environment": "dev", "argo_application": "addon-postgres-dev", "secret": "shop-postgres-app",
     "sizing": {"instances": 1, "version": 17, "storage": "1Gi"}}
  ],
  "relations": [{"type": "part_of", "from": "component:shop-api", "to": "system:shop"}]
}
```

- `environments` is in promotion order. `environments[].promotion` is `main` | `auto` | `manual` (or the declared string). `observability` is null when not declared; its values are as declared (null when absent).
- `external` is null or `{"kind": "kustomize" | "helm", "namespace": str | null}`. `expose` is a boolean (truthy `expose`).
- `instances[].tag` is null when not pinned; `url` null when not exposed; `promoted_from` is `"<component>/<env>"` or null; `secrets[].store_key` is null for generated secrets. No secret value is read or printed.
- `relations[]` objects are `{"type", "from", "to"}` with ids `system:<name>`, `component:<name>`, `resource:<name>`, `environment:<name>`, `instance:<component>/<env>`, `resource_instance:<resource>/<env>`. Types: `part_of` (component and resource → system), `uses` (component → resource), `instance_of` (instance → component, resource instance → resource), `runs_in` (instance and resource instance → environment), `promoted_from` (instance → instance), `promotes_to` (environment → next environment). Order is not part of the contract.
- No observed-state keys (`argo`, `sync`, `health`, `digest`, `running`, `smoke`, `alerts_firing`, `ci`) anywhere.

## How each caller uses the model

- **status** (`collect`): `m = model.load_dir(gitops.find_app(repo, app))`. For each Component (CI and platform lookups once per Component with a `repo`, as now), one row per `m.instances_of(c)`: `tag = inst.tag or "?"`, `argo` key `inst.argo_application`, `exposed = bool(c.expose)`, pin PR only on dev. The command attaches its Argo and CI answers to `inst.observed` for this run only. Addon rows: for each name in `m.declared_addons`, `observability` gives a row per Environment that has Instances (`argo` key `env.observability.argo_application`), any other name a row per `m.resource_instances_of(name)` (`ri.argo_application`). `pinned_tag(app_dir, env, name)` stays as a wrapper of `model.read_pin`. `ENVS` goes.
- **promote**: `ORDER` goes; environment checks use `model.ENVIRONMENTS`. After `gitops.load`, `m = model.load_dir(app_dir)`; "is not in <from> yet" and `--all` use `m.instance(n, frm)`; the digest check uses `m.instance(n, "staging").tag` (None when no staging Instance). `_staging_tag` goes. Pins are written with `model.write_pin(app_dir, to, n, tag)`. Messages, JSON, written files and the two `gitops.render` calls stay as they are.
- **smoke** (`dev_url`): per linked slug, `_app_dirs` as now; per dir `m = model.load_remote(a, lambda p: _read(slug, p, repo))`, `c = m.find_component(_slug(repo), service)`; none → next dir; else `url, why = m.url(c.name, env)` and the old reason text `f"{service} has no {env} URL ({why})"`. The two "could not read" / "not in the linked gitops-app" endings are unchanged. Note: `app.yaml` is now read for every directory scanned, not only after an exposed entry was found; the existing fakes answer it.
- **staging**: `_find` returns `(slug, app_dir, component, model, me)` using `model.load_remote(a, lambda p: _read(slug, p, repo))` and `find_component`. `decide` uses `m.staging_promotion(c) != "auto"` (replaces `effective`), `m.instance(c.name, "staging") is None` for "not in staging yet", and `previous = inst.tag` (replaces `staging_tag`). `staging_deploy.promote` passes `{"image": found[2].image}` to `registry.image_name`.
- **alertsources** (`load_app`): keeps its lenient `_read_yaml`, then `m = model.build(app, services_doc, cfg)`. `AppConfig` gains `model: Model | None = None` (default keeps the dataclass compatible). `envs = [e.name for e in m.environments if m.instances_in(e.name)]`; `ServiceDown` rules for `inst in m.instances` whose Component has `metrics`; `_env_of` uses `model.ENVIRONMENTS` for the labels, namespace and instance patterns. `ENVS` goes.
- **secret**: `declared` and `store_key` are replaced by `m = model.load_dir(app_dir)` and `m.secrets(c.name, env)`; the list order (components, then their secrets) and every message stay.
- **appship_sched** (`gate_class`): the matching of the plan repo to an entry stays; once found, `m = model.build(<app basename>, services, app_doc)` and `inst = m.instance(found["name"], "dev")`; `exposed` when `inst` exists and `inst.exposed`, else `internal`.

## The guard (AC-113.13)

`tests/cplat/test_model_guard.py` parses every `scripts/cplat/*.py` except `model.py` with `ast` and fails, naming the file and line, when:

1. a `List`, `Tuple` or `Set` literal has string constants `dev`, `staging` and `prod` among its elements (an own environment list);
2. any string constant, or a constant part of an f-string, contains `newTag` (reading or writing an overlay pin);
3. one function (or the module body) contains both a string constant containing `overlays` and one containing `kustomization.yaml` (building an overlay pin path).

Positive controls: the same detector, run on source snippets of the code before this spec (`ENVS = ["dev", "staging", "prod"]`, the old `status.pinned_tag`, the old `staging.staging_tag` f-string), reports each. Prose such as `"dev, staging or prod"` in a hint is a single string, not a list, and does not trip rule 1; `compose.py`'s overlay directory check has no `kustomization.yaml` and does not trip rule 3.

## Tests the testers write (new files only, AC-113.12)

`tests/cplat/test_model.py` (AC-113.1–AC-113.8, AC-113.10: fixtures as files in a tmp gitops-app; the renderer order is read from `templates/gitops-app/scripts/render.py` with `ast`, never imported by cplat), `test_model_show.py` (AC-113.14–AC-113.16), `test_model_callers.py` (AC-113.9, AC-113.11, AC-113.18: the same fixtures through `status`, `promote`, `smoke.dev_url`, `staging.decide`, `alertsources.load_app`, `secret`, `appship_sched.gate_class`, plus a clean `git status` after `status --context` and `promote --dry-run`), `test_model_guard.py` (AC-113.13), `test_model_release.py` (AC-113.17: `cplat --help`, CHANGELOG, DOMAIN-MODEL Status, no `model` slash command).

## Risks

- **Strict parsing in local callers.** `status`, `promote` and `secret` now load through `load_dir`, so an unparseable `app.yaml` or `services.yaml` exits 1 with the file named instead of a crash (exit 70) or, for `secret`/`promote`, being ignored. Valid files behave exactly as before (AC-113.11); only a repo that `render.py` already rejects is affected.
- **Pin parsing unified.** `pin_of` takes the first `images` entry with a non-empty `newTag` as a string. Before, `promote` took `images[0]` only and `status` returned the raw value. Every overlay `render.py` writes has exactly one image with a string tag, so the answers are equal on real repos.
- **One more `app.yaml` read in `smoke`/`staging`** per scanned directory; both fakes answer it, and the real `gh api` cost is one call.
