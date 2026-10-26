"""`model`: the domain model of a gitops-app System (spec 113, ADR-053).

One place owns the nouns (System, Environment, Component, Instance, Resource, Resource instance) and every rule about "a component in
an environment". It reads only declared state (`services.yaml`, `app.yaml`, the overlay pins and the shape registry) and makes no
subprocess, network or socket call. Commands keep their own I/O and ask the model for the answers.

Public API:

  build(system, services, app, *, pins=None, shapes=None) -> Model     pure; `services` is the parsed services.yaml (or its list)
  load_dir(app_dir) -> Model                                           strict: an unparseable file raises ModelError
  load_remote(system, read) -> Model                                   lenient: `read(path) -> dict | None`, None = absent
  pin_path(env, component) / pin_of(doc) / read_pin(...) / write_pin(...)
"""
from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

import yaml
from core import PlatformError
from core import registry as _registry

ENVIRONMENTS: tuple[str, ...] = ("dev", "staging", "prod")
DEFAULT_LOCAL_PORT = 8088
SCHEMA = 1

_UNSET = object()
Pins = Callable[[str, str], "str | None"]


class ModelError(PlatformError):
    """A declared file cannot be parsed (load_dir only)."""


# ---------------- nouns ----------------

@dataclass(frozen=True)
class Observability:
    ui: object = None
    export_to: object = None
    alerts: object = None
    rules: object = None
    query_url: object = None
    alertmanager_url: object = None
    argo_application: str = ""


@dataclass(frozen=True)
class Environment:
    name: str
    order: int
    host: str | None = None
    url_template: str | None = None
    policy: str = "off"
    promotion: str = "manual"
    observability: Observability | None = None


@dataclass(frozen=True)
class External:
    kind: str
    namespace: str | None = None


@dataclass(frozen=True)
class Secret:
    name: str
    kind: str
    keys: tuple[str, ...] = ()
    path: str | None = None


@dataclass(frozen=True)
class InstanceSecret:
    name: str
    kind: str
    keys: tuple[str, ...] = ()
    store_key: str | None = None


@dataclass(frozen=True)
class Component:
    name: str
    repo: str | None = None
    image: str | None = None
    shape: str | None = None
    type: str = "service"
    lang: str = "unknown"
    external: External | None = None
    expose: object = None
    metrics: str | None = None
    uses: tuple[str, ...] = ()
    environments: tuple[str, ...] = ("dev",)
    promotion_staging: str | None = None
    secrets: tuple[Secret, ...] = ()
    secret_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class Resource:
    name: str
    type: str = "unknown"


@dataclass
class Instance:
    component: str
    environment: str
    image: str | None
    replicas: int | None
    namespace: str
    argo_application: str
    exposed: bool
    staging_promotion: str
    secrets: tuple[InstanceSecret, ...] = ()
    observed: dict = field(default_factory=dict, compare=False, repr=False)
    _pins: Pins | None = field(default=None, compare=False, repr=False)
    _tag: object = field(default=_UNSET, compare=False, repr=False)
    _rule: tuple | None = field(default=None, compare=False, repr=False)

    @property
    def url(self) -> str | None:
        """The URL, computed on access (LOCAL_HTTP_PORT is read then)."""
        return _url(*self._rule) if self._rule else None

    @property
    def tag(self) -> str | None:
        """The tag the overlay pins, read on first access (at most once)."""
        if self._tag is _UNSET:
            self._tag = self._pins(self.environment, self.component) if self._pins else None
        return self._tag  # type: ignore[return-value]


@dataclass(frozen=True)
class ResourceInstance:
    resource: str
    environment: str
    argo_application: str
    secret: str | None = None
    sizing: dict = field(default_factory=dict)


@dataclass
class Model:
    system: str
    environments: Sequence[Environment] = ()
    components: Sequence[Component] = ()
    resources: Sequence[Resource] = ()
    instances: Sequence[Instance] = ()
    resource_instances: Sequence[ResourceInstance] = ()
    declared_addons: tuple[str, ...] = ()
    warnings: Sequence[str] = ()

    # ---- lookups ----

    def environment(self, name: str) -> Environment | None:
        return next((e for e in self.environments if e.name == name), None)

    def component(self, name: str) -> Component | None:
        return next((c for c in self.components if c.name == name), None)

    def find_component(self, repo: str, name: str) -> Component | None:
        return next((c for c in self.components if c.repo == repo), None) or self.component(name)

    def instance(self, component: str, env: str) -> Instance | None:
        return next((i for i in self.instances if i.component == component and i.environment == env), None)

    def instances_of(self, component: str) -> list[Instance]:
        return [i for i in self.instances if i.component == component]

    def instances_in(self, env: str) -> list[Instance]:
        return [i for i in self.instances if i.environment == env]

    def resource_instances_of(self, resource: str) -> list[ResourceInstance]:
        return [r for r in self.resource_instances if r.resource == resource]

    def promoted_from(self, inst: Instance) -> Instance | None:
        i = ENVIRONMENTS.index(inst.environment) if inst.environment in ENVIRONMENTS else 0
        return self.instance(inst.component, ENVIRONMENTS[i - 1]) if i > 0 else None

    def staging_promotion(self, component: Component) -> str:
        if component.promotion_staging:
            return component.promotion_staging
        staging = self.environment("staging")
        return staging.promotion if staging else "manual"

    def url(self, component: str, env: str) -> tuple[str | None, str | None]:
        inst = self.instance(component, env)
        if inst is not None:
            url = inst.url
        else:
            c, e = self.component(component), self.environment(env)
            url = _url(self.system, c, e) if c and e else None
        return (url, None) if url else (None, f"not exposed in {env}")

    def secrets(self, component: str, env: str) -> tuple[InstanceSecret, ...]:
        inst = self.instance(component, env)
        if inst is not None:
            return inst.secrets
        c = self.component(component)
        return _instance_secrets(self.system, c, env) if c else ()

    # ---- serialization ----

    def relations(self) -> list[dict]:
        sysid = f"system:{self.system}"
        out: list[dict] = []

        def rel(t: str, a: str, b: str) -> None:
            out.append({"type": t, "from": a, "to": b})
        for c in self.components:
            rel("part_of", f"component:{c.name}", sysid)
        for r in self.resources:
            rel("part_of", f"resource:{r.name}", sysid)
        known = {r.name for r in self.resources}
        for c in self.components:
            for u in c.uses:
                if u in known:
                    rel("uses", f"component:{c.name}", f"resource:{u}")
        for i in self.instances:
            iid = f"instance:{i.component}/{i.environment}"
            rel("instance_of", iid, f"component:{i.component}")
            rel("runs_in", iid, f"environment:{i.environment}")
            prev = self.promoted_from(i)
            if prev is not None:
                rel("promoted_from", iid, f"instance:{prev.component}/{prev.environment}")
        for ri in self.resource_instances:
            rid = f"resource_instance:{ri.resource}/{ri.environment}"
            rel("instance_of", rid, f"resource:{ri.resource}")
            rel("runs_in", rid, f"environment:{ri.environment}")
        for a, b in zip(self.environments, self.environments[1:]):
            rel("promotes_to", f"environment:{a.name}", f"environment:{b.name}")
        return out

    def to_dict(self) -> dict:
        def obs(o: Observability | None) -> dict | None:
            if o is None:
                return None
            return {"ui": o.ui, "exportTo": o.export_to, "alerts": o.alerts, "rules": o.rules,
                    "queryURL": o.query_url, "alertmanagerURL": o.alertmanager_url}

        def sec(s: Secret | InstanceSecret) -> dict:
            d = {"name": s.name, "kind": s.kind, "keys": list(s.keys)}
            if isinstance(s, InstanceSecret):
                d["store_key"] = s.store_key
            return d

        def inst(i: Instance) -> dict:
            prev = self.promoted_from(i)
            return {"component": i.component, "environment": i.environment, "image": i.image, "tag": i.tag,
                    "replicas": i.replicas, "namespace": i.namespace, "argo_application": i.argo_application,
                    "url": i.url, "exposed": i.exposed,
                    "promoted_from": f"{prev.component}/{prev.environment}" if prev else None,
                    "secrets": [sec(s) for s in i.secrets]}

        return {
            "schema": SCHEMA,
            "system": {"name": self.system, "components": [c.name for c in self.components],
                       "resources": [r.name for r in self.resources]},
            "environments": [{"name": e.name, "host": e.host, "url": e.url_template, "policy": e.policy,
                              "promotion": e.promotion, "observability": obs(e.observability)} for e in self.environments],
            "components": [{
                "name": c.name, "type": c.type, "lang": c.lang, "shape": c.shape, "repo": c.repo, "image": c.image,
                "external": {"kind": c.external.kind, "namespace": c.external.namespace} if c.external else None,
                "expose": bool(c.expose), "metrics": c.metrics, "uses": list(c.uses), "environments": list(c.environments),
                "promotion": {"staging": c.promotion_staging}, "secrets": [sec(s) for s in c.secrets],
                "secret_refs": list(c.secret_refs)} for c in self.components],
            "resources": [{"name": r.name, "type": r.type,
                           "used_by": [c.name for c in self.components if r.name in c.uses]} for r in self.resources],
            "instances": [inst(i) for i in self.instances],
            "resource_instances": [{"resource": r.resource, "environment": r.environment, "argo_application": r.argo_application,
                                    "secret": r.secret, "sizing": dict(r.sizing)} for r in self.resource_instances],
            "relations": self.relations(),
        }


# ---------------- rules ----------------

def _per_env(value: object, env: str, default: object) -> object:
    """A scalar, or a per-environment map ({dev: 1, prod: 3}); missing environments fall back to `default` (render.py's rule)."""
    if isinstance(value, dict):
        return value.get(env, default)
    return default if value is None else value


def _policy(app: dict, env: str) -> str:
    conf = app.get("policies")
    if conf in (None, False):
        return "off"
    conf = conf if isinstance(conf, dict) else {}
    return str(_per_env(conf.get("mode"), env, "Enforce" if env == "prod" else "Audit"))


def _str_or_none(v: object) -> str | None:
    return None if v is None else str(v)


def _url(system: str, c: Component, e: Environment) -> str | None:
    if not c.expose or not e.host:
        return None
    service = (c.expose.get("host") if isinstance(c.expose, dict) else None) or c.name
    host = e.host.format(service=service, app=system, env=e.name)
    if e.url_template:
        return e.url_template.format(host=host, service=c.name, app=system, env=e.name)
    if host.endswith(".localhost"):
        port = os.environ.get("LOCAL_HTTP_PORT", "")
        return f"http://{host}:{port if port.isdigit() else DEFAULT_LOCAL_PORT}"
    return f"https://{host}"


def _instance_secrets(system: str, c: Component, env: str) -> tuple[InstanceSecret, ...]:
    out = []
    for s in c.secrets:
        key = None
        if s.kind == "remote":
            key = str(s.path or "{app}-{env}-{secret}").format(app=system, env=env, secret=s.name, service=c.name)
        out.append(InstanceSecret(s.name, s.kind, s.keys, key))
    return tuple(out)


def _secrets_of(entry: dict) -> tuple[Secret, ...]:
    out = []
    for s in entry.get("secrets") or []:
        if not isinstance(s, dict) or not s.get("name"):
            continue
        remote = s.get("remote") if isinstance(s.get("remote"), dict) else {}
        if s.get("generate"):
            out.append(Secret(str(s["name"]), "generate", tuple(str(k) for k in s["generate"]), None))
        else:
            out.append(Secret(str(s["name"]), "remote", tuple(str(k) for k in remote.get("keys") or []), _str_or_none(remote.get("path"))))
    return tuple(out)


def _external(entry: dict) -> External | None:
    ext = entry.get("external")
    if not ext:
        return None
    if not isinstance(ext, dict):
        return External("kustomize", None)
    kind = next((k for k in ("kustomize", "helm") if k in ext), "kustomize")
    return External(kind, _str_or_none(ext.get("namespace")))


def _component(entry: dict, shapes: list[dict]) -> tuple[Component, list[str]]:
    name = str(entry["name"])
    shape = entry.get("shape")
    reg = next((s for s in shapes if s.get("id") == shape), None) if shape else None
    if reg and reg.get("library"):
        kind = "library"
    elif reg and reg.get("plugin") == "web":
        kind = "website"
    else:
        kind = "service"
    lang = ((reg or {}).get("default_stack") or {}).get("language") or "unknown"
    listed = entry.get("environments")
    listed = listed if isinstance(listed, list) else []
    warns = []
    for e in dict.fromkeys(listed):
        if e not in ENVIRONMENTS:
            warns.append(f"{name} lists unknown environment '{e}': no Instance")
    envs = tuple(e for e in ENVIRONMENTS if e in listed) or ("dev",)
    promo = entry.get("promotion")
    expose = entry.get("expose")
    uses = entry.get("uses")
    refs = entry.get("secretRefs")
    return Component(
        name=name, repo=_str_or_none(entry.get("repo")), image=_str_or_none(entry.get("image")), shape=_str_or_none(shape),
        type=kind, lang=str(lang), external=_external(entry), expose=expose if expose else None,
        metrics=_str_or_none(entry.get("metrics") or None),
        uses=tuple(str(u) for u in uses) if isinstance(uses, list) else (),
        environments=envs,
        promotion_staging=_str_or_none(promo.get("staging")) if isinstance(promo, dict) else None,
        secrets=_secrets_of(entry), secret_refs=tuple(str(r) for r in refs) if isinstance(refs, list) else (),
    ), warns


def _replicas(entry: dict, env: str) -> int | None:
    if entry.get("external"):
        return None
    r = entry.get("replicas", 1)
    try:
        return int(r.get(env, 1)) if isinstance(r, dict) else int(r)
    except (TypeError, ValueError):
        return 1


def _sizing(conf: dict, env: str) -> dict:
    return {"instances": int(_per_env(conf.get("instances"), env, 1)),  # type: ignore[call-overload]
            "version": _per_env(conf.get("version"), env, 17),
            "storage": str(_per_env(conf.get("storage"), env, "1Gi"))}


# ---------------- build ----------------

def build(system: str, services: dict | list | None, app: dict | None, *, pins: Pins | None = None,
          shapes: list[dict] | None = None) -> Model:
    """Turn parsed `services.yaml` (a mapping with `services:`, or the list itself) and `app.yaml` into a Model."""
    app = app if isinstance(app, dict) else {}
    shapes = _registry.load() if shapes is None else shapes
    entries = services.get("services") if isinstance(services, dict) else services
    entries = [s for s in (entries or []) if isinstance(s, dict) and s.get("name")]

    hosts = app.get("hosts") if isinstance(app.get("hosts"), dict) else {}
    urls = app.get("urls") if isinstance(app.get("urls"), dict) else {}
    promo = app.get("promotion") if isinstance(app.get("promotion"), dict) else {}
    addons = app.get("addons") if isinstance(app.get("addons"), dict) else {}
    obs = None
    if "observability" in addons:
        o = addons["observability"] if isinstance(addons["observability"], dict) else {}
        obs = o
    envs = []
    for order, name in enumerate(ENVIRONMENTS):
        promotion = "main" if name == "dev" else (str(promo.get("staging") or "manual") if name == "staging" else "manual")
        o = None
        if obs is not None:
            o = Observability(obs.get("ui"), obs.get("exportTo"), obs.get("alerts"), obs.get("rules"), obs.get("queryURL"),
                              obs.get("alertmanagerURL"), f"addon-observability-{name}")
        envs.append(Environment(name, order, _str_or_none(hosts.get(name)), _str_or_none(urls.get(name)), _policy(app, name),
                                promotion, o))
    by_env = {e.name: e for e in envs}

    components, warnings = [], []
    for entry in entries:
        c, w = _component(entry, shapes)
        components.append((entry, c))
        warnings += w
    declared = tuple(str(k) for k in addons)
    names = {k for k in declared if k != "observability"}
    components = [(e, replace(c, uses=tuple(u for u in c.uses if u in names))) for e, c in components]
    resources = [Resource(k, "database" if k == "postgres" else "unknown") for k in declared if k != "observability"]

    staging_default = by_env["staging"].promotion
    instances = []
    for entry, c in components:
        for env in c.environments:
            e = by_env[env]
            ext = c.external
            instances.append(Instance(
                component=c.name, environment=env, image=c.image, replicas=_replicas(entry, env),
                namespace=(ext.namespace if ext and ext.namespace else None) or f"{system}-{env}",
                argo_application=f"{c.name}-{env}", exposed=bool(c.expose and e.host), _rule=(system, c, e),
                staging_promotion=c.promotion_staging or staging_default, secrets=_instance_secrets(system, c, env),
                _pins=pins))

    ris = []
    for r in resources:
        conf = addons.get(r.name) if isinstance(addons.get(r.name), dict) else {}
        for env in ENVIRONMENTS:
            if any(r.name in c.uses and env in c.environments for _, c in components):
                ris.append(ResourceInstance(
                    r.name, env, f"addon-{r.name}-{env}", f"{system}-postgres-app" if r.name == "postgres" else None,
                    _sizing(conf, env) if r.name == "postgres" else {}))

    return Model(system=system, environments=tuple(envs), components=tuple(c for _, c in components), resources=tuple(resources),
                 instances=tuple(instances), resource_instances=tuple(ris), declared_addons=declared, warnings=tuple(warnings))


# ---------------- pins ----------------

def pin_path(env: str, component: str) -> str:
    return f"overlays/{env}/{component}/kustomization.yaml"


def pin_of(doc: dict | None) -> str | None:
    """The first `images` entry with a non-empty newTag, as text."""
    images = doc.get("images") if isinstance(doc, dict) else None
    for img in images if isinstance(images, list) else []:
        if isinstance(img, dict) and img.get("newTag") not in (None, ""):
            return str(img["newTag"])
    return None


def read_pin(app_dir: Path, env: str, component: str) -> str | None:
    try:
        return pin_of(yaml.safe_load((Path(app_dir) / pin_path(env, component)).read_text()))
    except (OSError, yaml.YAMLError):
        return None


def write_pin(app_dir: Path, env: str, component: str, tag: str) -> None:
    f = Path(app_dir) / pin_path(env, component)
    doc = yaml.safe_load(f.read_text())
    doc["images"][0]["newTag"] = tag
    f.write_text(yaml.safe_dump(doc, sort_keys=False, default_flow_style=False))


# ---------------- loaders ----------------

def load_dir(app_dir: Path, *, shapes: list[dict] | None = None) -> Model:
    app_dir = Path(app_dir)
    system = app_dir.name

    def parse(fname: str, required: bool) -> dict:
        f = app_dir / fname
        try:
            if not f.is_file() and not required:
                return {}
            doc = yaml.safe_load(f.read_text())
            if doc is None:
                return {}
            if not isinstance(doc, dict):
                raise TypeError("the top level is not a mapping")
        except (OSError, yaml.YAMLError, TypeError) as ex:
            lines = [ln for ln in str(ex).splitlines() if ln.strip()]
            raise ModelError(f"cannot parse applications/{system}/{fname}: {lines[0].strip() if lines else 'unreadable'}",
                             hint=f"fix the YAML in applications/{system}/{fname}") from ex
        return doc

    services, app = parse("services.yaml", True), parse("app.yaml", False)
    return build(system, services, app, pins=lambda env, c: read_pin(app_dir, env, c), shapes=shapes)


def load_remote(system: str, read: Callable[[str], dict | None], *, shapes: list[dict] | None = None) -> Model:
    base = f"applications/{system}/"
    services, app = read(base + "services.yaml"), read(base + "app.yaml")
    return build(system, services if isinstance(services, dict) else {}, app if isinstance(app, dict) else {},
                 pins=lambda env, c: pin_of(read(base + pin_path(env, c))), shapes=shapes)
