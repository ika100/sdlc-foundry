"""Spec 114: pure conversion of the 4.x `app.yaml` + `services.yaml` into the 5.0 `system.yaml` document.

`convert` never touches the disk and lists every key that has no place in 5.0 (`problems`); `dump` writes the document with the
generated header; `has_comments` tells whether an old file carried comments (they are not carried over).
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

import yaml

import model

HEADER = (
    "# system.yaml of the {system} system: the only hand-edited file of this system (sdlc-foundry 5.0).\n"
    "# Schema: https://github.com/ika100/sdlc-foundry/blob/main/docs/DOMAIN-MODEL.md#one-file-per-system\n"
    "# Written by `cplat platform update --migrate` from app.yaml and services.yaml; their comments were not carried over.\n"
)
TOP_ORDER = ("system", "owner", "gateway", "secretStore", "registries", "environments", "components", "resources")
APP_KEYS = ("gateway", "hosts", "urls", "secretStore", "promotion", "policies", "addons")
ENTRY_KEYS = ("name", "repo", "shape", "image", "port", "probes", "user", "metrics", "volumes", "env", "secretRefs", "secrets",
              "replicas", "resources", "expose", "uses", "promotion", "environments", "external", "provides", "consumes")
PG_KEYS = ("version", "instances", "storage", "resources")
PROMOTE = {"auto": "after-dev-smoke", "manual": "manual"}
DEFAULT_POLICY = {"dev": "Audit", "staging": "Audit", "prod": "Enforce"}


@dataclass
class Conversion:
    doc: dict
    problems: list[str] = field(default_factory=list)
    comments: bool = False


def _ph(value):
    """4.x placeholders {service} and {app} become {component} and {system}."""
    if isinstance(value, str):
        return value.replace("{service}", "{component}").replace("{app}", "{system}")
    return value


def _secrets(secrets):
    out = copy.deepcopy(secrets)
    if isinstance(out, list):
        for s in out:
            remote = s.get("remote") if isinstance(s, dict) else None
            if isinstance(remote, dict) and "path" in remote:
                remote["path"] = _ph(remote["path"])
    return out


def _per_env(value, problems: list[str], where: str) -> dict | None:
    """The per-environment map of a value, or None for a scalar; unknown environment names are problems."""
    if not isinstance(value, dict):
        return None
    for e in value:
        if e not in model.ENVIRONMENTS:
            problems.append(f"{where}: {e} (unknown environment)")
    return {e: v for e, v in value.items() if e in model.ENVIRONMENTS}


def _environments(app: dict, problems: list[str]) -> tuple[dict, dict]:
    envs: dict[str, dict] = {e: {} for e in model.ENVIRONMENTS}
    top: dict = {}
    for key, dest in (("hosts", "host"), ("urls", "url")):
        m = app.get(key)
        if m is None:
            continue
        if not isinstance(m, dict):
            problems.append(f"app.yaml: {key} (must map environments to text)")
            continue
        for e, v in m.items():
            if e not in envs:
                problems.append(f"app.yaml: {key}.{e} (unknown environment)")
            else:
                envs[e][dest] = _ph(v)
    pol = app.get("policies", None)
    if "policies" not in app or pol is False:
        modes = {e: "off" for e in envs}
    else:
        pol = {} if pol in (None, True) else pol
        if not isinstance(pol, dict):
            problems.append("app.yaml: policies (must be false or a mapping)")
            pol = {}
        for k in pol:
            if k not in ("mode", "registries"):
                problems.append(f"app.yaml: policies.{k} (no place in system.yaml)")
        mode = pol.get("mode")
        per = _per_env(mode, problems, "app.yaml: policies.mode")
        modes = {}
        for e in envs:
            v = per.get(e, DEFAULT_POLICY[e]) if per is not None else (DEFAULT_POLICY[e] if mode is None else mode)
            modes[e] = "off" if v is False else str(v).lower()
        if pol.get("registries"):
            top["registries"] = copy.deepcopy(pol["registries"])
    for e in envs:
        envs[e]["policy"] = modes[e]
    promotion = app.get("promotion")
    if promotion is not None:
        if not isinstance(promotion, dict):
            problems.append("app.yaml: promotion (must be a mapping)")
        else:
            for k, v in promotion.items():
                if k == "staging" and v in PROMOTE:
                    envs["staging"]["promote"] = PROMOTE[v]
                elif k == "prod" and v == "manual":
                    continue
                else:
                    problems.append(f"app.yaml: promotion.{k} (no place in system.yaml)")
    addons = app.get("addons")
    resources: dict = {}
    if addons is not None and not isinstance(addons, dict):
        problems.append("app.yaml: addons (must be a mapping)")
        addons = {}
    for name, conf in (addons or {}).items():
        if name == "observability":
            for e in envs:
                envs[e]["observability"] = copy.deepcopy(conf or {})
        elif name == "postgres":
            resources["postgres"] = _postgres(conf or {}, problems)
        else:
            problems.append(f"app.yaml: addons.{name} (no 5.0 resource or environment key)")
    order = {e: {k: envs[e][k] for k in ("host", "url", "policy", "promote", "observability") if k in envs[e]} for e in envs}
    if resources:
        top["resources"] = resources
    return order, top


def _postgres(conf, problems: list[str]) -> dict:
    out: dict = {"type": "database"}
    if not isinstance(conf, dict):
        problems.append("app.yaml: addons.postgres (must be a mapping)")
        return out
    for k in conf:
        if k not in PG_KEYS:
            problems.append(f"app.yaml: addons.postgres.{k} (no place in resources.postgres)")
    inst: dict[str, dict] = {}
    version = conf.get("version")
    if isinstance(version, dict):
        values = list(version.values())
        if values and all(v == values[0] for v in values):
            version = values[0]
        else:
            problems.append("app.yaml: addons.postgres.version (differs per environment; one version per system)")
            version = None
    if version is not None:
        out["version"] = version
    for src, dest in (("instances", "replicas"), ("storage", "storage")):
        v = conf.get(src)
        if v is None:
            continue
        per = _per_env(v, problems, f"app.yaml: addons.postgres.{src}")
        if per is None:
            out[dest] = v
        else:
            for e, x in per.items():
                inst.setdefault(e, {})[dest] = x
    if conf.get("resources") is not None:
        out["resources"] = copy.deepcopy(conf["resources"])
    if inst:
        out["instances"] = inst
    return out


def _component(entry: dict, shapes, problems: list[str]) -> tuple[str, dict] | None:
    name = entry.get("name")
    if not name:
        problems.append("services.yaml: services (an entry without name)")
        return None
    where = f"services.yaml: {name}"
    for k in entry:
        if k not in ENTRY_KEYS:
            problems.append(f"{where}.{k} (no place in system.yaml)")
    if "external" not in entry and ("port" not in entry or "probes" not in entry):
        problems.append(f"{where} (a v1 entry without port and probes)")
    envs = entry.get("environments")
    envs = ["dev"] if envs is None else envs
    if not isinstance(envs, list):
        problems.append(f"{where}.environments (must be a list)")
        envs = []
    for e in envs:
        if e not in model.ENVIRONMENTS:
            problems.append(f"{where}.environments: {e} (unknown environment)")
    running = [e for e in envs if e in model.ENVIRONMENTS]
    instances: dict[str, dict] = {e: {} for e in running}
    replicas = entry.get("replicas")
    per = _per_env(replicas, problems, f"{where}.replicas")
    if per is not None:
        for e, n in per.items():
            if e in instances:
                instances[e]["replicas"] = n
            else:
                problems.append(f"{where}.replicas: {e} (the service does not run in {e})")
    promotion = entry.get("promotion")
    if promotion is not None:
        for e, v in (promotion.items() if isinstance(promotion, dict) else [("?", None)]):
            if e == "staging" and e in instances and v in PROMOTE:
                instances[e]["promote"] = PROMOTE[v]
            else:
                problems.append(f"{where}.promotion: {e} (no place in system.yaml)")
    out: dict = {}
    for k, v in entry.items():
        if k in ("name", "environments", "promotion") or k not in ENTRY_KEYS:
            continue
        if k == "shape":
            out["type"], out["lang"] = model.type_lang(v, shapes)
        elif k == "replicas":
            if per is None and v is not None:
                out[k] = v
        elif k == "secrets":
            out[k] = _secrets(v)
        else:
            out[k] = copy.deepcopy(v)
    if "type" not in out:
        out = {"type": "service", "lang": "unknown", **out}
    out["instances"] = instances
    return str(name), out


def convert(system: str, app: dict | None, services: dict | None, owner: str | None, shapes: list[dict] | None = None) -> Conversion:
    """The `system.yaml` document of a 4.x application, and every key that cannot be converted."""
    app = app or {}
    services = services or {}
    problems: list[str] = []
    for k in app:
        if k not in APP_KEYS:
            problems.append(f"app.yaml: {k} (no place in system.yaml)")
    for k in services:
        if k != "services":
            problems.append(f"services.yaml: {k} (no place in system.yaml)")
    if not owner:
        problems.append("owner: not found (no github_org in .copier-answers.yml and no origin remote); set it in system.yaml")
    envs, top = _environments(app, problems)
    components: dict = {}
    for entry in services.get("services") or []:
        if not isinstance(entry, dict):
            problems.append("services.yaml: services (an entry must be a mapping)")
            continue
        made = _component(entry, shapes, problems)
        if made:
            components[made[0]] = made[1]
    doc: dict = {"system": system, "owner": owner}
    for k in ("gateway", "secretStore"):
        if app.get(k):
            doc[k] = copy.deepcopy(app[k])
    if "registries" in top:
        doc["registries"] = top["registries"]
    doc["environments"] = envs
    doc["components"] = components
    if "resources" in top:
        doc["resources"] = top["resources"]
    return Conversion(doc=doc, problems=problems)


def dump(doc: dict) -> str:
    """The document as text: the generated header, then the keys in the documented order."""
    ordered = {k: doc[k] for k in TOP_ORDER if k in doc}
    ordered.update({k: v for k, v in doc.items() if k not in ordered})
    head = HEADER.format(system=doc.get("system", ""))
    return head + yaml.safe_dump(ordered, sort_keys=False, default_flow_style=False)


def has_comments(text: str) -> bool:
    """True when a YAML text has a comment (a `#` at the start or after a blank, outside quotes)."""
    for line in text.splitlines():
        quote = ""
        prev = " "
        for ch in line:
            if quote:
                if ch == quote:
                    quote = ""
            elif ch in "'\"" and prev in " \t[{,:-":
                quote = ch
            elif ch == "#" and prev in " \t":
                return True
            prev = ch
    return False
