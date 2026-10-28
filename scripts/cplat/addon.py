"""`resource add|remove`: declare or remove a named, typed resource in system.yaml (ADR-020, ADR-054, ADR-057).

`resource add <name> --type database|bucket|cache|broker [--version N] [--replicas N] [--external [--path P]]` writes `resources.<name>`; components then opt in
with `component set --uses <name>` (or `uses: [<name>]`). The name rule, types and database majors mirror
templates/gitops-app/scripts/render.py (the source; BROKER_VERSIONS too). Observability is not a resource: it is set per environment under
`environments.<env>.observability`.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import gitops
from core import PlatformError, Report

DEFAULT = {"type": "database", "version": 17, "replicas": 1, "storage": "1Gi", "instances": {"prod": {"replicas": 3, "storage": "20Gi"}}}
RESOURCE_TYPES = ["database", "bucket", "cache", "broker"]
PLANNED_TYPES = {}
RESOURCE_NAME = re.compile(r"^[a-z][a-z0-9-]*$")
DB_VERSIONS = (15, 16, 17, 18)
BROKER_VERSIONS = ("2.14", "2.15")
STORAGE_SIZE = re.compile(r"^[0-9]+(\.[0-9]+)?(Ki|Mi|Gi|Ti|Pi|Ei)?$")
BUCKET_KEYS = "endpoint, bucket, region, forcePathStyle, accessKeyId, secretAccessKey"
TYPES_LINE = "(database, bucket, cache or broker)"
# External secret keys per type; mirrors TYPES[...]["keys"] in templates/gitops-app/scripts/render.py (the source).
TYPE_KEYS = {
    "database": "uri, host, port, dbname, user, password",
    "bucket": BUCKET_KEYS,
    "cache": "url, host, port, password",
    "broker": "url, user, password",
}
CACHE_HINT = "the type is `cache` (Redis-compatible, runs Valkey): /resource:add <name> --type cache"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cplat resource", description=__doc__)
    p.add_argument("action", choices=["add", "remove"])
    p.add_argument("name", help="resource name (lowercase letters, digits, hyphens; at most 30 characters)")
    p.add_argument("--type", help="resource type: database, bucket, cache or broker")
    p.add_argument("--version", help="database major (15, 16, 17, 18) or broker version (2.14, 2.15)")
    p.add_argument("--replicas", help="broker replicas: 1 or 3 (default 1)")
    p.add_argument("--storage", help="bucket size, e.g. 10Gi (default 10Gi)")
    p.add_argument("--versioning", action="store_true", help="keep object versions in the bucket")
    p.add_argument("--external", action="store_true", help="the resource runs outside the cluster; its secret is synced from the secret store")
    p.add_argument("--path", help="secret store key template for --external ({system}, {env}, {resource}; a broker also {component})")
    p.add_argument("--app")
    p.add_argument("--repo-dir", default=".")
    p.add_argument("--pr", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    return p


def _check_add(ns: argparse.Namespace, data, declared, components) -> None:
    n = ns.name
    if not RESOURCE_NAME.match(n) or len(n) > 30:
        raise PlatformError(f"resource name '{n}' must start with a lowercase letter and contain only lowercase letters, digits and hyphens (at most 30 characters)")
    typ = ns.type or ("database" if n == "postgres" else None)
    if typ is None:
        raise PlatformError(f"--type is required for {n} {TYPES_LINE}")
    if typ not in RESOURCE_TYPES:
        hint = CACHE_HINT if typ in ("redis", "valkey") else None
        raise PlatformError(f"unknown resource type '{typ}' {TYPES_LINE}", hint=hint)
    if typ in PLANNED_TYPES:
        raise PlatformError(f"resource type {typ} is not available yet: spec {PLANNED_TYPES[typ]} brings it")
    if n in declared:
        raise PlatformError(f"{n} is already declared", hint="edit its settings in system.yaml")
    if n in components:
        raise PlatformError(f"{n} is a component of the system; a resource needs a name of its own")
    if ns.path and not ns.external:
        raise PlatformError("--path needs --external")
    if ns.version and typ not in ("database", "broker"):
        raise PlatformError("--version applies to --type database or broker only")
    if ns.replicas is not None and typ != "broker":
        raise PlatformError("--replicas applies to --type broker only")
    if (ns.storage or ns.versioning) and typ != "bucket":
        raise PlatformError("--storage and --versioning apply to --type bucket only")
    if ns.version and ns.external:
        raise PlatformError("an external resource runs nothing: --version does not apply")
    if ns.external and (ns.storage or ns.versioning):
        flag = "--storage" if ns.storage else "--versioning"
        raise PlatformError(f"an external bucket is sized and configured at its provider: {flag} does not apply")
    if ns.external and ns.replicas is not None:
        raise PlatformError("an external resource runs nothing: --replicas does not apply")
    if ns.version and typ == "broker":
        if ns.version not in BROKER_VERSIONS:
            raise PlatformError(f"version '{ns.version}' is not a supported broker version (2.14, 2.15)")
    elif ns.version:
        v = int(ns.version) if ns.version.isdigit() else None
        if v not in DB_VERSIONS:
            raise PlatformError(f"version '{ns.version}' is not a supported database version (15, 16, 17, 18)")
    if ns.replicas is not None and ns.replicas not in ("1", "3"):
        raise PlatformError("--replicas must be 1 or 3: a broker runs with 1 or 3 replicas")
    if ns.storage and not STORAGE_SIZE.match(ns.storage):
        raise PlatformError(f"storage '{ns.storage}' is not a size, e.g. 10Gi")
    if ns.external and not (data.get("secretStore") or {}):
        raise PlatformError("an external resource needs the system's secretStore", hint="declare secretStore: {name, kind} in system.yaml first")


def _carries(data, declared, name: str, api) -> bool:
    """True when the events API `api` is carried by broker `name` (explicit `broker:`, else the system's only broker)."""
    if not isinstance(api, dict) or api.get("type") != "events":
        return False
    if api.get("broker") is not None:
        return api["broker"] == name
    brokers = [n for n, v in declared.items() if (v or {}).get("type") == "broker"]
    return brokers == [name]


def main(argv: list[str]) -> int:
    ns = build_parser().parse_args(argv)
    repo = Path(ns.repo_dir).resolve()
    app_dir = gitops.find_app(repo, ns.app)
    if ns.name == "observability":
        raise PlatformError("observability is set per environment under environments.<env>.observability in system.yaml",
                            hint="nothing was changed; edit system.yaml and run `devbox run render`")
    y, data = gitops.load(app_dir)
    declared = data.get("resources") or {}
    components = gitops.components_of(data)
    r = Report(title=f"resource {ns.action} {ns.name} ({app_dir.name})")

    if ns.action == "add":
        _check_add(ns, data, declared, components)
        typ = ns.type or "database"
        if ns.external:
            entry = {"type": typ, "external": True}
            if ns.path:
                entry["remote"] = {"path": ns.path}
        elif typ == "cache":
            entry = {"type": "cache"}
        elif typ == "broker":
            entry = {"type": "broker"}
            if ns.version:
                entry["version"] = ns.version
            if ns.replicas is not None:
                entry["replicas"] = int(ns.replicas)
        elif typ == "bucket":
            entry = {"type": "bucket", "storage": ns.storage or "10Gi", "versioning": bool(ns.versioning)}
        else:
            entry = {k: v for k, v in DEFAULT.items()}
            entry["instances"] = {e: dict(v) for e, v in DEFAULT["instances"].items()}
            if ns.version:
                entry["version"] = int(ns.version)
        r.will_do.append(f"declare {ns.name} {entry} in system.yaml")
    else:
        if ns.name not in declared:
            names = ", ".join(declared) or "none"
            raise PlatformError(f"{ns.name} is not a resource of the system (resources: {names})")
        carried = [a for a, v in (data.get("apis") or {}).items() if _carries(data, declared, ns.name, v)]
        if (declared[ns.name] or {}).get("type") == "broker" and carried:
            raise PlatformError(f"{ns.name} carries the events APIs {', '.join(carried)}",
                                hint="bind them to another broker (apis.<api>.broker) or remove them first")
        using = [n for n, c in components.items() if ns.name in ((c or {}).get("uses") or [])]
        if using:
            raise PlatformError(f"{ns.name} is still used by {', '.join(using)}", hint="remove it from their uses: first (/component:set)")
        res = declared[ns.name] or {}
        inst = res.get("instances") or {}
        rtype = res.get("type") or "database"
        flags = [bool((inst.get(e) or {}).get("external", res.get("external", False))) for e in gitops.ENVS]
        if rtype == "broker":
            sysname = app_dir.name
            if not all(flags):
                r.will_do.append(f"remove {ns.name} from system.yaml; the Argo Application disappears but the broker, its volumes, streams, consumers and Secrets {sysname}-{ns.name}-<component>-app stay in the cluster (delete them by hand when you are sure)")
            if any(flags):
                r.will_do.append(f"remove {ns.name} from system.yaml; the synced Secrets {sysname}-{ns.name}-<component>-app stay in the cluster (delete them by hand when you are sure); the external broker is not touched")
        elif not all(flags):
            if rtype == "cache":
                r.will_do.append(f"remove {ns.name} from system.yaml; the Argo Application disappears but the cache, its volume and its Secret {app_dir.name}-{ns.name}-app stay in the cluster (delete them by hand when you are sure)")
            elif rtype == "bucket":
                r.will_do.append(f"remove {ns.name} from system.yaml; the Argo Application disappears but the bucket, its data and its Secret {app_dir.name}-{ns.name}-app stay in the cluster (delete them by hand when you are sure)")
            else:
                r.will_do.append(f"remove {ns.name} from system.yaml; the Argo Application disappears but the database and its data stay in the cluster (delete them by hand when you are sure)")
        if any(flags) and rtype != "broker":
            what = rtype if rtype in ("bucket", "cache") else "database"
            r.will_do.append(f"remove {ns.name} from system.yaml; the synced Secret {app_dir.name}-{ns.name}-app stays in the cluster (delete it by hand when you are sure); the external {what} is not touched")
    r.will_do.append("regenerate manifests (render.py)")
    if ns.pr:
        r.will_do.append("[outward] open a pull request (branch resource/…)")
    if ns.dry_run:
        r.emit(True, ns.json)
        return 0

    gitops.require_clean(repo)
    from ruamel.yaml.comments import CommentedMap
    if ns.action == "add":
        if data.get("resources") is None:
            data["resources"] = CommentedMap()
        data["resources"][ns.name] = entry
    else:
        del data["resources"][ns.name]
        if not data["resources"]:
            del data["resources"]
    gitops.save(app_dir, y, data)
    gitops.render(repo)
    r.did.append(f"updated system.yaml and regenerated {len(gitops.rendered_changes(repo))} file(s)")
    if ns.pr:
        r.did.append("opened " + gitops.open_pr(repo, f"resource/{ns.action}-{ns.name}", f"feat(resource): {ns.action} {ns.name}",
                                                f"`/resource:{ns.action} {ns.name}`. Generated files regenerated by `devbox run render`."))
    if ns.action == "add":
        n = ns.name
        if typ == "broker":
            r.next_steps.append(f"bind events APIs to it: an events API uses the system's only broker, or set apis.<api>.broker: <name>; its provider and consumers then get NATS_URL, NATS_USER, NATS_PASSWORD and EVENTS_<API>_* (no uses: needed)")
        else:
            r.next_steps.append(f"let components use it: /component:set <component> --uses {n} (or uses: [{n}] in system.yaml)")
        if ns.external:
            store = data["secretStore"]["name"]
            tpl = ns.path or ("{system}-{env}-{resource}-{component}" if typ == "broker" else "{system}-{env}-{resource}")
            keys = ", ".join(tpl.format(system=app_dir.name, env=e, resource=n, secret=n, component="<component>") for e in gitops.ENVS)
            kl = TYPE_KEYS[typ]
            r.next_steps.append(f"put the keys {kl} in the secret store {store} under {keys}")
            if typ == "broker":
                r.next_steps.append("create on the external broker the streams and durable consumers that devbox run render prints (the platform creates none there)")
        elif typ == "broker":
            r.next_steps.append("the platform installs the NACK controller through operators/ (apply operators/root.yaml once per cluster: KUBE_CONTEXT=<ctx> devbox run bootstrap); environments with operators: owner need it installed by their owner")
        elif typ == "cache":
            r.next_steps.append("no operator is needed: each environment where a component uses it runs one Valkey StatefulSet (defaults: Valkey 9, memory 256Mi, allkeys-lru, persistence false; set them in system.yaml)")
        elif typ == "bucket":
            r.next_steps.append("the platform installs the SeaweedFS operator through operators/ (apply operators/root.yaml once per cluster: KUBE_CONTEXT=<ctx> devbox run bootstrap); environments with operators: owner need it installed by their owner")
        else:
            r.next_steps.append("the platform installs CloudNativePG through operators/ (apply operators/root.yaml once per cluster: KUBE_CONTEXT=<ctx> devbox run bootstrap); environments with operators: owner need it installed by their owner")
    r.undo.append("git checkout -- . && git clean -fd applications")
    r.emit(False, ns.json)
    return 0
