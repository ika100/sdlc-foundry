"""`model`: the domain model of a gitops-app System (spec 113, ADR-053; loaded from `system.yaml` since 5.0, spec 114).

One place owns the nouns (System, Environment, Component, Instance, Resource, Resource instance, API) and every rule about "a component
in an environment". It reads only declared state (`system.yaml`, the overlay pins and the shape registry) and makes no
subprocess, network or socket call. Commands keep their own I/O and ask the model for the answers.

Public API:

  build(doc, system, *, pins=None, shapes=None) -> Model     pure; `doc` is the parsed system.yaml (lenient: malformed parts are skipped)
  load_dir(app_dir) -> Model                                 strict: an unparseable file raises ModelError; NotMigrated for 4.x files
  load_remote(system, read) -> Model                         lenient: `read(path) -> dict | None`, None = absent
  type_lang(shape) / shape_for(type, lang) / TYPE_LANGS      the 4.x shape id <-> the 5.0 component type and lang
  pin_path(env, component) / pin_of(doc) / read_pin(...) / write_pin(...)
"""
from __future__ import annotations

import copy
import dataclasses
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import yaml
import autonomy as _autonomy
from core import PlatformError
from core import registry as _registry

ENVIRONMENTS: tuple[str, ...] = ("dev", "staging", "prod")
DEFAULT_LOCAL_PORT = 8088
SCHEMA = 2
DEFAULT_SCHEDULE = "0 3 * * *"
DEFAULT_RETENTION = "30d"
NOT_MIGRATED = "not migrated to 5.0: run `cplat platform update --migrate`"

_UNSET = object()
Pins = Callable[[str, str], "str | None"]


class ModelError(PlatformError):
    """A declared file cannot be parsed (load_dir only)."""


class NotMigrated(ModelError):
    """The application still has the 4.x `app.yaml` / `services.yaml`."""

    def __init__(self) -> None:
        super().__init__(NOT_MIGRATED, hint="this repo still has app.yaml/services.yaml (4.x)")


# ---------------- type and lang ----------------

def _pair(shape: dict) -> tuple[str, str] | None:
    lang = (shape.get("default_stack") or {}).get("language")
    if not lang:
        return None
    if shape.get("library"):
        return ("library", str(lang))
    return ("website" if shape.get("plugin") == "web" else "service", str(lang))


def _pairs(shapes: list[dict]) -> list[tuple[str, tuple[str, str]]]:
    return [(str(s.get("id")), p) for s in shapes for p in [_pair(s)] if p]


def type_lang(shape: str | None, shapes: list[dict] | None = None) -> tuple[str, str]:
    """A 4.x shape id as (type, lang); no or an unknown shape is ("service", "unknown")."""
    if shape:
        for sid, pair in _pairs(_registry.load() if shapes is None else shapes):
            if sid == shape:
                return pair
    return ("service", "unknown")


def shape_for(type: str, lang: str, shapes: list[dict] | None = None) -> str | None:  # noqa: A002
    """The shape id of a (type, lang) pair; None for service/unknown and pairs without a shape."""
    for sid, pair in _pairs(_registry.load() if shapes is None else shapes):
        if pair == (type, lang):
            return sid
    return None


TYPE_LANGS: tuple[tuple[str, str], ...] = (*dict.fromkeys(p for _, p in _pairs(_registry.load())), ("service", "unknown"))


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
    headers_secret: object = None
    query_secret: object = None


@dataclass(frozen=True)
class Environment:
    name: str
    order: int
    host: str | None = None
    url_template: str | None = None
    policy: str = "off"
    promotion: str = "manual"
    observability: Observability | None = None
    operators: str | None = None  # "owner" or None
    backup: dict | None = None  # {"to", "schedule", "retention"} (spec 117)
    autonomy: dict = field(default_factory=dict, compare=False)  # spec 124: declared and effective policy
    autoscaling: str | None = None  # "keda" when a running instance scales on a queue (spec 120)


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
    overridden: bool = False


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
    provides: tuple[str, ...] = ()
    consumes: tuple[str, ...] = ()
    libraries: tuple[str, ...] = ()


@dataclass(frozen=True)
class Api:
    name: str
    type: str = "openapi"
    provider: str | None = None
    consumers: tuple[str, ...] = ()
    broker: str | None = None  # events APIs only: the broker resource that carries it (spec 119)


@dataclass(frozen=True)
class Resource:
    name: str
    type: str = "unknown"
    external: bool = False  # the resource-level flag is True


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
    autonomy: dict = field(default_factory=dict, compare=False)  # spec 124: {"max", "effective"}
    scale: dict | None = None  # effective {"min", "max", "on"} (spec 120); replicas is None when set
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
    argo_application: str | None
    secret: str | None = None
    sizing: dict = field(default_factory=dict)
    type: str = "unknown"
    external: bool = False
    store_key: str | None = None
    backup: dict | None = None  # {"to", "schedule", "retention"} of an in-cluster database (spec 117)
    broker: dict | None = None  # brokers only: {"address", "monitoring", "users", "streams"} (spec 119)
    version: int | str | None = None  # the effective major (database, cache, broker in the cluster); None for external and buckets (spec 121)
    pinned: str | None = None  # the image the instance's rendered file pins; None when external or not rendered yet (spec 121)


@dataclass
class Model:
    system: str
    owner: str = ""
    environments: Sequence[Environment] = ()
    components: Sequence[Component] = ()
    resources: Sequence[Resource] = ()
    instances: Sequence[Instance] = ()
    resource_instances: Sequence[ResourceInstance] = ()
    apis: Sequence[Api] = ()
    warnings: Sequence[str] = ()
    paused: bool = False

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

    def api(self, name: str) -> Api | None:
        return next((a for a in self.apis if a.name == name), None)

    def promoted_from(self, inst: Instance) -> Instance | None:
        i = ENVIRONMENTS.index(inst.environment) if inst.environment in ENVIRONMENTS else 0
        return self.instance(inst.component, ENVIRONMENTS[i - 1]) if i > 0 else None

    def staging_promotion(self, component: Component) -> str:
        """`after-dev-smoke` or `manual`."""
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
        return _instance_secrets(self.system, c, env, {}) if c else ()

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
        for a in self.apis:
            rel("part_of", f"api:{a.name}", sysid)
        known = {r.name for r in self.resources}
        for c in self.components:
            for u in c.uses:
                if u in known:
                    rel("uses", f"component:{c.name}", f"resource:{u}")
            for lib in c.libraries:
                rel("uses", f"component:{c.name}", f"component:{lib}")
        for c in self.components:
            for a in c.provides:
                rel("provides", f"component:{c.name}", f"api:{a}")
            for a in c.consumes:
                rel("consumes", f"component:{c.name}", f"api:{a}")
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
                    "queryURL": o.query_url, "alertmanagerURL": o.alertmanager_url,
                    "headersSecret": o.headers_secret, "querySecret": o.query_secret}

        def sec(s: Secret | InstanceSecret) -> dict:
            d = {"name": s.name, "kind": s.kind, "keys": list(s.keys)}
            if isinstance(s, InstanceSecret):
                d["store_key"] = s.store_key
                d["overridden"] = s.overridden
            return d

        def inst(i: Instance) -> dict:
            prev = self.promoted_from(i)
            return {"component": i.component, "environment": i.environment, "image": i.image, "tag": i.tag,
                    "replicas": i.replicas, "scale": copy.deepcopy(i.scale), "namespace": i.namespace, "argo_application": i.argo_application,
                    "url": i.url, "exposed": i.exposed,
                    "promoted_from": f"{prev.component}/{prev.environment}" if prev else None,
                    "secrets": [sec(s) for s in i.secrets], "autonomy": dict(i.autonomy)}

        return {
            "schema": SCHEMA,
            "autonomy": {"paused": self.paused, "levels": list(_autonomy.LEVELS)},
            "system": {"name": self.system, "owner": self.owner, "components": [c.name for c in self.components],
                       "resources": [r.name for r in self.resources], "apis": [a.name for a in self.apis]},
            "environments": [{"name": e.name, "host": e.host, "url": e.url_template, "policy": e.policy,
                              "promotion": e.promotion, "observability": obs(e.observability),
                              "operators": e.operators, "backup": e.backup, "autoscaling": e.autoscaling, "autonomy": copy.deepcopy(e.autonomy)} for e in self.environments],
            "components": [{
                "name": c.name, "type": c.type, "lang": c.lang, "shape": c.shape, "repo": c.repo, "image": c.image,
                "external": {"kind": c.external.kind, "namespace": c.external.namespace} if c.external else None,
                "expose": bool(c.expose), "metrics": c.metrics, "uses": list(c.uses), "environments": list(c.environments),
                "promotion": {"staging": c.promotion_staging}, "secrets": [sec(s) for s in c.secrets],
                "secret_refs": list(c.secret_refs), "provides": list(c.provides), "consumes": list(c.consumes),
                "libraries": list(c.libraries),
                "used_by": [o.name for o in self.components if c.name in o.libraries]} for c in self.components],
            "apis": [{"name": a.name, "type": a.type, "provider": a.provider, "consumers": list(a.consumers),
                      **({"broker": a.broker} if a.type == "events" else {})} for a in self.apis],
            "resources": [{"name": r.name, "type": r.type, "external": r.external,
                           "used_by": [c.name for c in self.components if r.name in c.uses]} for r in self.resources],
            "instances": [inst(i) for i in self.instances],
            "resource_instances": [{"resource": r.resource, "environment": r.environment, "type": r.type,
                                    "external": r.external, "argo_application": r.argo_application, "secret": r.secret,
                                    "store_key": r.store_key, "sizing": dict(r.sizing),
                                    "backup": r.backup, "version": r.version, "pinned": r.pinned,
                                    **({"broker": copy.deepcopy(r.broker)} if r.type == "broker" else {})}
                                   for r in self.resource_instances],
            "relations": self.relations(),
        }


# ---------------- rules ----------------

def _map(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _names(value: object) -> tuple[str, ...]:
    return tuple(str(v) for v in value) if isinstance(value, list) else ()


def _str_or_none(v: object) -> str | None:
    return None if v is None else str(v)


def _policy(conf: dict, env: str) -> str:
    """`audit` | `enforce` | `off`; YAML 1.1 reads an unquoted `off` as false (the renderer's rule)."""
    v = conf.get("policy")
    if v is False:
        return "off"
    if v in (None, True):
        return "enforce" if env == "prod" else "audit"
    return str(v).lower()


def _promotion(conf: dict, env: str) -> str:
    if env == "dev":
        return "main"
    v = conf.get("promote")
    if env == "staging" and v:
        return str(v)
    return "manual"


def _url(system: str, c: Component, e: Environment) -> str | None:
    if not c.expose or not e.host:
        return None
    component = (c.expose.get("host") if isinstance(c.expose, dict) else None) or c.name
    try:
        host = e.host.format(component=component, system=system, env=e.name)
        if e.url_template:
            return e.url_template.format(host=host, component=c.name, system=system, env=e.name)
    except (KeyError, IndexError, ValueError):
        return None
    if host.endswith(".localhost"):
        port = os.environ.get("LOCAL_HTTP_PORT", "")
        return f"http://{host}:{port if port.isdigit() else DEFAULT_LOCAL_PORT}"
    return f"https://{host}"


def _secret_entries(entry: dict) -> list[dict]:
    return [s for s in entry.get("secrets") or [] if isinstance(s, dict) and s.get("name")]


def _secret_of(s: dict) -> Secret:
    remote = _map(s.get("remote"))
    if s.get("generate"):
        return Secret(str(s["name"]), "generate", tuple(str(k) for k in s["generate"]), None)
    return Secret(str(s["name"]), "remote", tuple(str(k) for k in remote.get("keys") or []), _str_or_none(remote.get("path")))


def _instance_secrets(system: str, c: Component, env: str, overrides: dict[str, dict]) -> tuple[InstanceSecret, ...]:
    out = []
    for s in c.secrets:
        o = overrides.get(s.name)
        if o:
            base = {"name": s.name}
            if s.kind == "generate":
                base["generate"] = list(s.keys)
            else:
                base["remote"] = {"keys": list(s.keys), **({"path": s.path} if s.path else {})}
            if "generate" in o:
                base.pop("remote", None)
            elif "remote" in o:
                base.pop("generate", None)
            s = _secret_of({**base, **o})
        key = None
        if s.kind == "remote":
            key = str(s.path or "{system}-{env}-{secret}").format(system=system, app=system, env=env, secret=s.name,
                                                                   component=c.name, service=c.name)
        out.append(InstanceSecret(s.name, s.kind, s.keys, key, overridden=bool(o)))
    return tuple(out)


def _external(entry: dict) -> External | None:
    ext = entry.get("external")
    if not ext:
        return None
    if not isinstance(ext, dict):
        return External("kustomize", None)
    kind = next((k for k in ("kustomize", "helm") if k in ext), "kustomize")
    return External(kind, _str_or_none(ext.get("namespace")))


def _replicas(entry: dict, inst: dict) -> int | None:
    if entry.get("external"):
        return None
    r = inst.get("replicas", entry.get("replicas", 1))
    try:
        return int(r)
    except (TypeError, ValueError):
        return 1


def _scale_of(value: object) -> dict | None:
    """A declared `scale` as the model keeps it; None when it is not a mapping with `max` and an `on` mapping (the renderer refuses it)."""
    if isinstance(value, dict) and True in value and "on" not in value:   # YAML 1.1 reads an unquoted `on:` as true (the renderer's rule)
        value = {("on" if k is True else k): v for k, v in value.items()}
    if not isinstance(value, dict) or "max" not in value or not isinstance(value.get("on"), dict):
        return None
    return {"min": value["min"] if "min" in value else 1, "max": value["max"], "on": copy.deepcopy(value["on"])}


def _effective_scale(entry: dict, inst: dict) -> dict | None:
    if entry.get("external"):
        return None
    if "scale" in inst:
        return _scale_of(inst["scale"])
    if "replicas" in inst:
        return None
    if "replicas" in entry:
        return None
    return _scale_of(entry.get("scale"))


def _component(name: str, entry: dict, shapes: list[dict], resources: set[str], libraries: set[str]) -> tuple[Component, list[str]]:
    ctype = str(entry.get("type") or "service")
    lang = str(entry.get("lang") or "unknown")
    instances = _map(entry.get("instances"))
    warns = [f"{name} has instances in unknown environment '{e}': no Instance" for e in instances if e not in ENVIRONMENTS]
    if ctype == "library":
        envs: tuple[str, ...] = ()
    else:
        envs = tuple(e for e in ENVIRONMENTS if e in instances) or (("dev",) if not instances else ())
    uses = _names(entry.get("uses"))
    staging = _map(instances.get("staging"))
    expose = entry.get("expose")
    return Component(
        name=name, repo=_str_or_none(entry.get("repo")), image=_str_or_none(entry.get("image")),
        shape=shape_for(ctype, lang, shapes), type=ctype, lang=lang, external=_external(entry), expose=expose if expose else None,
        metrics=_str_or_none(entry.get("metrics") or None),
        uses=tuple(u for u in uses if u in resources), libraries=tuple(u for u in uses if u in libraries),
        environments=envs, promotion_staging=_str_or_none(staging.get("promote")) if staging.get("promote") else None,
        secrets=tuple(_secret_of(s) for s in _secret_entries(entry)), secret_refs=_names(entry.get("secretRefs")),
        provides=_names(entry.get("provides")), consumes=_names(entry.get("consumes")),
    ), warns


def _sizing(conf: dict, env: str) -> dict:
    inst = _map(_map(conf.get("instances")).get(env))
    try:
        replicas = int(inst.get("replicas", conf.get("replicas", 1)))
    except (TypeError, ValueError):
        replicas = 1
    return {"replicas": replicas, "version": inst.get("version", conf.get("version", 17)), "storage": str(inst.get("storage", conf.get("storage", "1Gi")))}


def _bucket_sizing(conf: dict, env: str) -> dict:
    inst = _map(_map(conf.get("instances")).get(env))
    return {"storage": str(inst.get("storage", conf.get("storage", "10Gi"))),
            "versioning": inst.get("versioning", conf.get("versioning")) is True}


def _cache_sizing(conf: dict, env: str) -> dict:
    inst = _map(_map(conf.get("instances")).get(env))
    version = inst.get("version", conf.get("version", 9))
    if isinstance(version, str) and version.strip().isdigit():
        version = int(version)
    elif isinstance(version, bool) or not isinstance(version, int):
        version = 9
    persistence = inst.get("persistence", conf.get("persistence")) is True
    out = {"version": version, "memory": str(inst.get("memory", conf.get("memory", "256Mi"))),
           "maxmemoryPolicy": str(inst.get("maxmemoryPolicy", conf.get("maxmemoryPolicy", "allkeys-lru"))),
           "persistence": persistence}
    if persistence:
        out["storage"] = str(inst.get("storage", conf.get("storage", "1Gi")))
    return out


def _broker_sizing(conf: dict, env: str) -> dict:
    inst = _map(_map(conf.get("instances")).get(env))
    try:
        replicas = int(inst.get("replicas", conf.get("replicas", 1)))
    except (TypeError, ValueError):
        replicas = 1
    version = inst.get("version", conf.get("version", "2.15"))
    return {"version": str(version), "replicas": replicas, "storage": str(inst.get("storage", conf.get("storage", "1Gi")))}


def _major_of(typ: str, sizing: dict) -> int | str | None:
    """The effective major of an in-cluster database, cache or broker instance; None for any other type (spec 121)."""
    if typ not in ("database", "cache", "broker"):
        return None
    v = sizing.get("version")
    return int(v) if isinstance(v, str) and v.strip().isdigit() and typ != "broker" else v


def _backup(value: object) -> dict | None:
    """`{"to", "schedule", "retention"}` with defaults for a mapping with a string `to`; anything else is None (spec 117)."""
    if not isinstance(value, dict) or not isinstance(value.get("to"), str) or not value["to"]:
        return None
    return {"to": value["to"], "schedule": str(value.get("schedule", DEFAULT_SCHEDULE)),
            "retention": str(value.get("retention", DEFAULT_RETENTION))}


def _store_key(template: str, system: str, env: str, resource: str) -> str:
    return template.replace("{system}", system).replace("{env}", env).replace("{resource}", resource)


def _env_autonomy(env: str, conf: dict, paused: bool, promotion: str) -> dict:
    """The environment's autonomy object; a malformed block falls back to the defaults (the renderer validates)."""
    block = conf.get("autonomy")
    try:
        if isinstance(block, dict) and block.get("level", "observe") in _autonomy.LEVELS:
            return _autonomy.effective(env, block, paused=paused, promotion=promotion)
    except (TypeError, AttributeError, ValueError, KeyError):
        pass
    return _autonomy.effective(env, None, paused=paused, promotion=promotion)


def _instance_autonomy(env_obj: dict, idoc: dict) -> dict:
    block = _map(idoc.get("autonomy"))
    mx = block.get("max")
    return _autonomy.instance(env_obj, mx if mx in _autonomy.LEVELS else None)


def _broker_instance(system: str, env: str, name: str, external: bool, store_key: str | None,
                     api_broker: dict[str, str | None], components: list[tuple[dict, Component]]) -> dict:
    """The broker view of one instance: address, monitoring, users and streams with consumers (spec 119)."""
    carried = [a for a, b in api_broker.items() if b == name]
    running = [c for _, c in components if env in c.environments]
    users = [c for c in running if any(a in carried for a in (*c.provides, *c.consumes))]
    svc, ns = f"{system}-{name}", f"{system}-{env}"
    return {
        "address": None if external else f"nats://{svc}.{ns}.svc:4222",
        "monitoring": None if external else f"http://{svc}.{ns}.svc:8222",
        "users": [{"component": c.name, "secret": f"{svc}-{c.name}-app",
                   "store_key": store_key.replace("{component}", c.name) if external and store_key else None} for c in users],
        "streams": [{"api": a, "stream": f"{system}-{a}", "subjects": f"{system}.{a}.>", "subject_prefix": f"{system}.{a}",
                     "consumers": [{"name": c.name, "component": c.name} for c in running if a in c.consumes]} for a in carried],
    }


# ---------------- build ----------------

def build(doc: dict | None, system: str, *, pins: Pins | None = None, shapes: list[dict] | None = None) -> Model:
    """Turn a parsed `system.yaml` into a Model. Lenient: malformed parts are skipped; the renderer is the validator."""
    doc = doc if isinstance(doc, dict) else {}
    shapes = _registry.load() if shapes is None else shapes
    env_docs = _map(doc.get("environments"))
    paused = _map(doc.get("autonomy")).get("paused") is True
    envs = []
    for order, name in enumerate(ENVIRONMENTS):
        conf = _map(env_docs.get(name))
        o = None
        if "observability" in conf:
            ob = _map(conf["observability"])
            o = Observability(ob.get("ui"), ob.get("exportTo"), ob.get("alerts"), ob.get("rules"), ob.get("queryURL"),
                              ob.get("alertmanagerURL"), f"addon-observability-{name}", ob.get("headersSecret"), ob.get("querySecret"))
        envs.append(Environment(name, order, _str_or_none(conf.get("host")), _str_or_none(conf.get("url")), _policy(conf, name),
                                _promotion(conf, name), o, "owner" if conf.get("operators") == "owner" else None, _backup(conf.get("backup")),
                                _env_autonomy(name, conf, paused, _promotion(conf, name))))
    by_env = {e.name: e for e in envs}

    res_docs = {str(k): _map(v) for k, v in _map(doc.get("resources")).items()}
    brokers = [k for k, v in res_docs.items() if v.get("type") == "broker"]
    comp_docs = {str(k): v for k, v in _map(doc.get("components")).items() if isinstance(v, dict)}
    libraries = {n for n, v in comp_docs.items() if v.get("type") == "library"}
    components, warnings = [], []
    for name, entry in comp_docs.items():
        c, w = _component(name, entry, shapes, set(res_docs) - set(brokers), libraries)
        components.append((entry, c))
        warnings += w

    # events APIs and the brokers that carry them (spec 119); the broker is an implicit `uses` of provider and consumers
    api_broker: dict[str, str | None] = {}
    for aname, adoc in _map(doc.get("apis")).items():
        adoc = _map(adoc)
        if adoc.get("type") != "events":
            continue
        explicit = adoc.get("broker")
        if explicit is not None:
            api_broker[str(aname)] = explicit if isinstance(explicit, str) and explicit in brokers else None
        else:
            api_broker[str(aname)] = brokers[0] if len(brokers) == 1 else None
    components = [(e, dataclasses.replace(c, uses=(*c.uses, *dict.fromkeys(
        b for a in (*c.provides, *c.consumes) for b in [api_broker.get(a)] if b and b not in c.uses))))
        for e, c in components]

    resources = [Resource(k, str(v.get("type") or ("database" if k == "postgres" else "unknown")), v.get("external") is True)
                 for k, v in res_docs.items()]

    instances = []
    for entry, c in components:
        inst_docs = _map(entry.get("instances"))
        for env in c.environments:
            e = by_env[env]
            idoc = _map(inst_docs.get(env))
            ext = c.external
            scale = _effective_scale(entry, idoc)
            overrides = {str(s["name"]): s for s in _secret_entries(idoc)}
            instances.append(Instance(
                component=c.name, environment=env, image=c.image, replicas=None if scale else _replicas(entry, idoc), scale=scale,
                namespace=(ext.namespace if ext and ext.namespace else None) or f"{system}-{env}",
                argo_application=f"{c.name}-{env}", exposed=bool(c.expose and e.host), _rule=(system, c, e),
                staging_promotion=c.promotion_staging or by_env["staging"].promotion,
                secrets=_instance_secrets(system, c, env, overrides), _pins=pins,
                autonomy=_instance_autonomy(e.autonomy, idoc)))

    for e in envs:
        if any(i.environment == e.name and i.scale and ("consumes" in i.scale["on"] or "cache" in i.scale["on"]) for i in instances):
            by_env[e.name] = dataclasses.replace(e, autoscaling="keda")
    envs = [by_env[e.name] for e in envs]

    ris = []
    for r in resources:
        conf = res_docs.get(r.name, {})
        for env in ENVIRONMENTS:
            if any(r.name in c.uses and env in c.environments for _, c in components):
                idoc = _map(_map(conf.get("instances")).get(env))
                ext = idoc["external"] is True if "external" in idoc else r.external
                path = _map(idoc.get("remote")).get("path") or _map(conf.get("remote")).get("path")
                broker = r.type == "broker"
                store_key = (_store_key(str(path or ("{system}-{env}-{resource}-{component}" if broker
                                                      else "{system}-{env}-{resource}")), system, env, r.name) if ext else None)
                ris.append(ResourceInstance(
                    r.name, env, None if ext else f"addon-{r.name}-{env}", None if broker else f"{system}-{r.name}-app",
                    {} if ext else _sizing(conf, env) if r.type == "database" else _bucket_sizing(conf, env) if r.type == "bucket"
                    else _cache_sizing(conf, env) if r.type == "cache" else _broker_sizing(conf, env) if broker else {},
                    r.type, ext, store_key,
                    None if ext or r.type != "database" else _backup(idoc.get("backup")),
                    _broker_instance(system, env, r.name, ext, store_key, api_broker, components) if broker else None,
                    None if ext else _major_of(r.type, _sizing(conf, env) if r.type == "database" else _cache_sizing(conf, env)
                                               if r.type == "cache" else _broker_sizing(conf, env) if broker else {})))

    cs = [c for _, c in components]
    apis = []
    for name, adoc in _map(doc.get("apis")).items():
        apis.append(Api(str(name), str(_map(adoc).get("type") or "openapi"),
                        next((c.name for c in cs if name in c.provides), None),
                        tuple(c.name for c in cs if name in c.consumes), api_broker.get(str(name))))

    return Model(system=system, owner=str(doc.get("owner") or ""), environments=tuple(envs), components=tuple(cs),
                 resources=tuple(resources), instances=tuple(instances), resource_instances=tuple(ris), apis=tuple(apis),
                 warnings=tuple(warnings), paused=paused)


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


# ---------------- rendered pins (spec 121) ----------------

def _rendered_image(path: Path, typ: str) -> str | None:
    """The engine image a rendered instance file pins; None when it is absent or does not read as one."""
    try:
        doc = yaml.safe_load(path.read_text())
        if typ == "database":
            image = doc["spec"]["imageName"]
        elif typ == "cache":
            image = next(c["image"] for c in doc["spec"]["template"]["spec"]["containers"] if c["name"] == "valkey")
        elif typ == "broker":
            ref = doc["spec"]["source"]["helm"]["valuesObject"]["container"]["image"]
            image = f"{ref['repository']}:{ref['tag']}"
        else:
            image = doc["spec"]["image"]
    except (OSError, yaml.YAMLError, KeyError, IndexError, TypeError, StopIteration, AttributeError):
        return None
    return image if isinstance(image, str) and image else None


def _database_file(app_dir: Path, system: str, env: str, name: str) -> str:
    """`cluster.yaml`, or the generation file of the active cluster named by restore-state.yaml."""
    import backupstate
    try:
        active = backupstate.cluster_roles(system, name, backupstate.restore_state(app_dir, env, name))["active"]
    except Exception:  # noqa: BLE001  (an unreadable state: the model stays lenient)
        return "cluster.yaml"
    base = f"{system}-{name}"
    return "cluster.yaml" if active == base else f"cluster-g{active[len(base) + 2:]}.yaml"


def with_pins(m: Model, app_dir: Path) -> Model:
    """The model with every in-cluster resource instance's `pinned` read from its rendered file under addons/<env>/<resource>/."""
    out = []
    for ri in m.resource_instances:
        if ri.external or ri.type not in ("database", "cache", "broker", "bucket"):
            out.append(ri)
            continue
        file = {"cache": "statefulset.yaml", "broker": "server.yaml", "bucket": "seaweed.yaml"}.get(ri.type) \
            or _database_file(app_dir, m.system, ri.environment, ri.resource)
        out.append(dataclasses.replace(ri, pinned=_rendered_image(app_dir / "addons" / ri.environment / ri.resource / file, ri.type)))
    return dataclasses.replace(m, resource_instances=tuple(out))


# ---------------- loaders ----------------

def load_dir(app_dir: Path, *, shapes: list[dict] | None = None) -> Model:
    app_dir = Path(app_dir)
    system = app_dir.name
    if (app_dir / "app.yaml").exists() or (app_dir / "services.yaml").exists():
        raise NotMigrated()
    f = app_dir / "system.yaml"
    try:
        doc = yaml.safe_load(f.read_text())
        if doc is None:
            doc = {}
        if not isinstance(doc, dict):
            raise TypeError("the top level is not a mapping")
    except (OSError, yaml.YAMLError, TypeError) as ex:
        lines = [ln for ln in str(ex).splitlines() if ln.strip()]
        raise ModelError(f"cannot parse applications/{system}/system.yaml: {lines[0].strip() if lines else 'unreadable'}",
                         hint=f"fix the YAML in applications/{system}/system.yaml") from ex
    return with_pins(build(doc, system, pins=lambda env, c: read_pin(app_dir, env, c), shapes=shapes), app_dir)


def load_remote(system: str, read: Callable[[str], dict | None], *, shapes: list[dict] | None = None) -> Model:
    base = f"applications/{system}/"
    doc = read(base + "system.yaml")
    if doc is None and (read(base + "services.yaml") is not None or read(base + "app.yaml") is not None):
        raise NotMigrated()
    return build(doc if isinstance(doc, dict) else {}, system, pins=lambda env, c: pin_of(read(base + pin_path(env, c))), shapes=shapes)
