"""`component add|set|remove`: edit the components of a gitops-app repo's system.yaml and render the manifests."""
from __future__ import annotations

import argparse
import base64
import re
from pathlib import Path

import yaml

import core
import gitops
import model
from core import PlatformError, Report, run


def gh(args: list[str]) -> str:
    """`gh` wrapper (tests replace this)."""
    return run(["gh", *args]).stdout


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cplat component", description=__doc__)
    p.add_argument("action", choices=["add", "set", "remove"], help="set: change env, exposure, resource use or replicas of a component")
    p.add_argument("services", nargs="+", metavar="component", help="component repo names (org/name, or just name = <github_org>/name)")
    p.add_argument("--system", help="system name when the repo has several")
    p.add_argument("--repo-dir", default=".", help="the gitops-app repo (default: current directory)")
    p.add_argument("--env", action="append", default=[], metavar="KEY=VALUE", help="env var for the service (single service only)")
    p.add_argument("--expose", nargs="?", const=True, default=None, metavar="HOST", help="publish through the Gateway (optional host label)")
    p.add_argument("--generate", action="append", default=[], metavar="SECRET=KEY,KEY", help="Secret whose values ESO generates randomly once per environment (single service only)")
    p.add_argument("--secret", action="append", default=[], metavar="SECRET=KEY,KEY", help="Secret read from the secret store (set the values with `cplat secret set`; single service only)")
    p.add_argument("--secret-ref", action="append", default=[], metavar="NAME", help="existing Secret in the namespace to expose as env vars, e.g. the one generated for another service (single service only)")
    p.add_argument("--uses", action="append", default=[], metavar="ADDON", help="resource or library the component needs (a database gives DATABASE_URL and PG*, a bucket S3_* and AWS_*, a cache REDIS_URL and REDIS_*); declare it first with `cplat resource add <name> --type database|bucket|cache`")
    p.add_argument("--provides", action="append", default=[], metavar="NAME[:TYPE]", help="API the component provides (TYPE: openapi, grpc, graphql, events; default openapi; single component only)")
    p.add_argument("--consumes", action="append", default=[], metavar="NAME", help="API the component consumes; somebody must provide it (single component only)")
    p.add_argument("--replicas", type=int)
    p.add_argument("--instance", metavar="ENV", help="with set: change this instance only (with --replicas)")
    p.add_argument("--port", type=int, help="override the port (default: the service's template answer, else the shape default)")
    p.add_argument("--from-k8s", action="store_true", help="seed port/probes/env/replicas/resources from the service's existing k8s/base/deployment.yaml (v1 → v2 migration)")
    p.add_argument("--type", help="component type when its repo has no .copier-answers.yml (service, website, library)")
    p.add_argument("--lang", help="component language when its repo has no .copier-answers.yml")
    p.add_argument("--pr", action="store_true", help="create branch, commit, push and open a pull request")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    return p


def repo_file(slug: str, path: str) -> str | None:
    try:
        raw = gh(["api", f"repos/{slug}/contents/{path}", "-q", ".content"])
    except PlatformError:
        return None
    return base64.b64decode(raw).decode() if raw.strip() else None


def shape_of(answers_text: str | None, type_: str | None, lang: str | None) -> str:
    entries = core.registry.load()
    if type_ or lang:
        if not (type_ and lang):
            raise PlatformError("--type and --lang go together", hint="e.g. --type service --lang python")
        sid = model.shape_for(type_, lang, entries)
        if sid is None:
            raise PlatformError(f"no component of type {type_} and lang {lang}", hint="available: " + ", ".join(f"{t}/{l}" for t, l in model.TYPE_LANGS if model.shape_for(t, l, entries)))
        return sid
    if answers_text:
        src = (yaml.safe_load(answers_text) or {}).get("_src_path", "")
        for e in entries:
            if src.rstrip("/").endswith("templates/" + e["template"]):
                return e["id"]
    raise PlatformError("cannot tell the service's shape", hint="the component repo needs a .copier-answers.yml from the platform template, or pass --type <type> --lang <lang>")


def seed_from_k8s(slug: str) -> dict:
    text = repo_file(slug, "k8s/base/deployment.yaml")
    if not text:
        raise PlatformError(f"{slug} has no k8s/base/deployment.yaml to import")
    dep = yaml.safe_load(text)
    spec = dep["spec"]["template"]["spec"]
    c = spec["containers"][0]
    out: dict = {}
    if c.get("ports"):
        out["port"] = c["ports"][0]["containerPort"]
    probes = {}
    for k, key in (("liveness", "livenessProbe"), ("readiness", "readinessProbe")):
        path = ((c.get(key) or {}).get("httpGet") or {}).get("path")
        if path:
            probes[k] = path
    if len(probes) == 2:
        out["probes"] = probes
    env = {e["name"]: str(e["value"]) for e in c.get("env", []) if "value" in e and e["name"] != "PORT"}
    if env:
        out["env"] = env
    if "replicas" in dep["spec"]:
        out["replicas"] = dep["spec"]["replicas"]
    if c.get("resources"):
        out["resources"] = c["resources"]
    return out


def parse_secret_args(items: list[str]) -> list[tuple[str, list[str]]]:
    out = []
    for item in items:
        name, _, keys = item.partition("=")
        ks = [k for k in keys.split(",") if k]
        if not name or not ks:
            raise PlatformError(f"expected SECRET=KEY[,KEY...], got '{item}'", hint="e.g. --generate todo-api-auth=DB_PASSWORD,JWT_KEY")
        out.append((name, ks))
    return out


def build_entry(name: str, slug: str, shape_entry: dict, port: int | None, registry_ns: str, ns: argparse.Namespace, seed: dict) -> dict:
    rt = shape_entry["runtime"]
    ctype, clang = model.type_lang(shape_entry["id"])
    entry = {
        "type": ctype, "lang": clang, "repo": slug, "image": f"{registry_ns}/{name}",
        "port": ns.port or seed.get("port") or port or rt["port"],
        "probes": seed.get("probes") or dict(rt["probes"]),
        "user": rt["user"],
        "metrics": rt["metrics"],
        "volumes": dict(rt.get("volumes") or {}),
        "env": {**(rt.get("env") or {}), **(seed.get("env") or {})},
        "secretRefs": [],
        "resources": seed.get("resources") or rt["resources"],
        "instances": {"dev": {}},
    }
    if ns.replicas or seed.get("replicas"):
        entry["replicas"] = ns.replicas or seed["replicas"]
    for kv in ns.env:
        k, _, v = kv.partition("=")
        if not k or not _:
            raise PlatformError(f"--env expects KEY=VALUE, got '{kv}'")
        entry["env"][k] = v
    secrets = [{"name": n, "generate": keys} for n, keys in parse_secret_args(ns.generate)] + \
              [{"name": n, "remote": {"keys": keys}} for n, keys in parse_secret_args(ns.secret)]
    if secrets:
        entry["secrets"] = secrets
    if ns.uses:
        entry["uses"] = list(dict.fromkeys(ns.uses))
    for ref in ns.secret_ref:
        if not re.match(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", ref) or len(ref) > 63:
            raise PlatformError(f"--secret-ref '{ref}' is not a valid Secret name", hint="lowercase letters, digits and '-', e.g. pm-backend-auth")
    entry["secretRefs"] = list(dict.fromkeys(ns.secret_ref))
    if ns.expose:
        entry["expose"] = {"host": name if ns.expose is True else ns.expose}
    return entry


API_TYPES = ("openapi", "grpc", "graphql", "events")


def parse_provides(items: list[str]) -> list[tuple[str, str]]:
    """`NAME[:TYPE]` items to (name, type); a type outside API_TYPES is refused before any edit."""
    out = []
    for item in items:
        name, _, kind = item.partition(":")
        kind = kind or "openapi"
        if not name or kind not in API_TYPES:
            raise PlatformError(f"--provides {name or item}:{kind}: type must be one of {', '.join(API_TYPES)}")
        out.append((name, kind))
    return out


def apply_apis(data, entry, provides: list[tuple[str, str]], consumes: list[str]) -> None:
    """Add the APIs to `apis:` and the names to the component's provides/consumes (no duplicates). Round-trip safe."""
    if provides and data.get("apis") is None:
        data["apis"] = {}
    for name, kind in provides:
        apis = data["apis"]
        have = apis.get(name)
        if have is None:
            apis[name] = {"type": kind}
        elif (have.get("type") or "openapi") != kind:
            raise PlatformError(f"apis.{name} is already of type {have.get('type') or 'openapi'}, not {kind}", hint="an API keeps its type; edit system.yaml by hand to change it")
    for key, names in (("provides", [n for n, _ in provides]), ("consumes", consumes)):
        if names:
            entry[key] = list(dict.fromkeys([*(entry.get(key) or []), *names]))


def restore_tree(repo: Path) -> None:
    """Undo an edit plus a failed render (the tree was clean when the command started)."""
    run(["git", "checkout", "-q", "--", "."], cwd=repo, check=False)
    run(["git", "clean", "-fdq", "--", "applications", "bootstrap"], cwd=repo, check=False)


def resolve_slug(arg: str, org: str) -> tuple[str, str]:
    slug = arg if "/" in arg else f"{org}/{arg}"
    return slug.split("/", 1)[1], slug


def check_remote(slug: str) -> str | None:
    """Verify repo + topic via gh; returns the service's answers file text."""
    try:
        info = yaml.safe_load(gh(["repo", "view", slug, "--json", "repositoryTopics"]) or "{}")  # JSON is valid YAML
    except PlatformError:
        raise PlatformError(f"repository {slug} not found or not readable", hint=f"check the name; create it with /component:new {slug.split('/')[1]} …") from None
    topics = [t["name"] for t in (info.get("repositoryTopics") or [])]
    if "deployable-service" not in topics:
        raise PlatformError(f"{slug} does not have the topic deployable-service", hint=f"gh repo edit {slug} --add-topic deployable-service")
    return repo_file(slug, ".copier-answers.yml")


def main(argv: list[str]) -> int:
    ns = build_parser().parse_args(argv)
    repo = Path(ns.repo_dir).resolve()
    app_dir = gitops.find_app(repo, ns.system)
    ans = gitops.answers(repo)
    org = ans.get("github_org", "ika100")
    registry_ns = ans.get("docker_registry", f"ghcr.io/{org}")
    if ns.action == "set" and len(ns.services) != 1:
        raise PlatformError("component set changes exactly one component", hint="run it once per component")
    if ns.action == "set" and not (ns.env or ns.expose or ns.uses or ns.replicas or ns.provides or ns.consumes):
        raise PlatformError("nothing to change", hint="pass --env KEY=VALUE, --expose [HOST], --uses RESOURCE, --replicas N, --provides NAME[:TYPE] or --consumes NAME")
    if (ns.provides or ns.consumes) and (len(ns.services) != 1 or ns.instance):
        raise PlatformError("--provides and --consumes apply to exactly one component and not to an --instance", hint="run it once per component")
    provides = parse_provides(ns.provides)
    if ns.instance and ns.action != "set":
        raise PlatformError("--instance applies to component set only")
    if ns.instance and (ns.env or ns.expose or ns.uses or not ns.replicas):
        raise PlatformError("--instance changes replicas only", hint="component set <name> --instance ENV --replicas N")
    if (ns.env or ns.generate or ns.secret or ns.uses or ns.secret_ref) and len(ns.services) != 1:
        raise PlatformError("--env, --generate, --secret, --secret-ref and --uses apply to exactly one component")
    if not ns.dry_run:
        gitops.require_clean(repo)
    shapes = {e["id"]: e for e in core.registry.load()}

    y, data = gitops.load(app_dir)
    components = gitops.components_of(data)
    declared_apis = set(data.get("apis") or {}) | {n for n, _ in provides}
    for cname in ns.consumes:
        if cname not in declared_apis:
            raise PlatformError(f"--consumes {cname}: no component is the provider of this API", hint=f"declare it first with --provides {cname}[:TYPE] on the component that serves it")
    r = Report(title=f"component {ns.action}: {', '.join(ns.services)} ({app_dir.name})")
    names: list[str] = []

    if ns.action == "add":
        new = []
        for arg in ns.services:
            name, slug = resolve_slug(arg, org)
            old = components.get(name)
            half = old is not None and "port" not in old and "probes" not in old     # a half-written entry: complete it in place
            if old is not None and not half:
                raise PlatformError(f"{name} is already in system.yaml", hint="edit its entry by hand, or remove it first")
            answers_text = check_remote(slug)
            shape = shape_of(answers_text, ns.type, ns.lang)
            port = (yaml.safe_load(answers_text) or {}).get("port") if answers_text else None
            seed = seed_from_k8s(slug) if ns.from_k8s else {}
            entry = build_entry(name, slug, shapes[shape], port, registry_ns, ns, seed)
            if half:  # keep the environments that already run (their overlays and image pins) as instance keys
                keys = list((old.get("instances") or {}).keys()) or [e for e in gitops.ENVS if (app_dir / "overlays" / e / name).is_dir()] or ["dev"]
                entry["instances"] = {k: {} for k in keys}
            new.append((name, entry))
            names.append(name)
            r.will_do.append(("complete " if half else "add ") + f"{name} ({entry['type']}/{entry['lang']}): port {entry['port']}, image {entry['image']}, instances {list(entry['instances'])}" + (", exposed" if "expose" in entry else "") + "".join(f", provides {pn} ({pk})" for pn, pk in provides) + "".join(f", consumes {cn}" for cn in ns.consumes))
        if not ns.dry_run:
            for name, e in new:
                components[name] = e
                apply_apis(data, components[name], provides, ns.consumes)
            gitops.save(app_dir, y, data)
    elif ns.action == "set":
        prefix_notes: list[str] = []
        name, _ = resolve_slug(ns.services[0], org)
        if name not in components:
            raise PlatformError(f"{name} is not in system.yaml", hint="current: " + ", ".join(components) if components else "system.yaml has no components")
        entry = components[name]
        if ns.instance and ns.instance not in (entry.get("instances") or {}):
            raise PlatformError(f"{name} has no instance in {ns.instance}", hint="instances: " + ", ".join(entry.get("instances") or {}))
        if ns.replicas:
            fix = f"edit applications/{app_dir.name}/system.yaml, then run component set again"
            if ns.instance:
                inst_entry = (entry.get("instances") or {}).get(ns.instance) or {}
                if "scale" in inst_entry:
                    key = f"components.{name}.instances.{ns.instance}.scale"
                elif "replicas" in inst_entry or "scale" not in entry:
                    key = ""
                else:
                    key = f"components.{name}.scale"
                if key:
                    raise PlatformError(f"{name} is scaled in {ns.instance} ({key}): scale and replicas exclude each other; remove {key} from system.yaml first", hint=fix)
            elif "scale" in entry:
                key = f"components.{name}.scale"
                raise PlatformError(f"{name} is scaled ({key}): scale and replicas exclude each other; remove {key} from system.yaml first", hint=fix)
        changes = []
        for kv in ns.env:
            k, sep, v = kv.partition("=")
            if not k or not sep:
                raise PlatformError(f"--env expects KEY=VALUE, got '{kv}'")
            changes.append(f"env {k}={v}")
        if ns.expose:
            changes.append(f"expose at {name if ns.expose is True else ns.expose}")
        if ns.uses:
            changes.append("uses " + ", ".join(ns.uses))
        if ns.replicas:
            changes.append(f"replicas {ns.replicas}" + (f" in {ns.instance}" if ns.instance else ""))
        changes += [f"provides {pn} (api {pk})" for pn, pk in provides] + [f"consumes {cn}" for cn in ns.consumes]
        names.append(name)
        r.will_do.append(f"set {name}: " + "; ".join(changes))
        if ns.uses:
            declared = data.get("resources") or {}
            by_type: dict[str, int] = {}
            for u in dict.fromkeys([*(entry.get("uses") or []), *ns.uses]):
                t = (declared.get(u) or {}).get("type") if isinstance(declared.get(u), dict) else None
                if t:
                    by_type[t] = by_type.get(t, 0) + 1
            for t, n in by_type.items():
                if n >= 2:
                    first, gone = {"bucket": ("S3_ENDPOINT", "S3_*, AWS_*"), "cache": ("REDIS_URL", "REDIS_*")}.get(t, ("DATABASE_URL", "DATABASE_URL, PG*"))
                    prefix_notes.append(f"{name} now uses {n} {t} resources: their variables are prefixed (<NAME>_{first}, …) and {gone} are no longer injected")
        if not ns.dry_run:  # mutate the round-trip entry in place, so comments and order in system.yaml survive
            if ns.env:
                env = entry.setdefault("env", {})
                for kv in ns.env:
                    k, _, v = kv.partition("=")
                    env[k] = v
            if ns.expose:
                entry["expose"] = {"host": name if ns.expose is True else ns.expose}
            if ns.uses:
                entry["uses"] = list(dict.fromkeys([*(entry.get("uses") or []), *ns.uses]))
            apply_apis(data, entry, provides, ns.consumes)
            if ns.replicas and ns.instance:
                inst = entry["instances"]
                if inst[ns.instance] is None:
                    inst[ns.instance] = {}
                inst[ns.instance]["replicas"] = ns.replicas
            elif ns.replicas:
                entry["replicas"] = ns.replicas
            gitops.save(app_dir, y, data)
    else:
        for arg in ns.services:
            name, _ = resolve_slug(arg, org)
            if name not in components:
                raise PlatformError(f"{name} is not in system.yaml", hint="current: " + ", ".join(components) if components else "system.yaml has no components")
            names.append(name)
            r.will_do.append(f"remove {name}; Argo prunes its Applications and workloads after the PR merges (prune is on)")
        if not ns.dry_run:
            for name in names:
                del components[name]
            gitops.save(app_dir, y, data)

    r.will_do.append("regenerate ApplicationSets and manifests (render.py)")
    if ns.pr:
        r.will_do.append("[outward] open a pull request (branch component/…)")
    if ns.dry_run:
        if ns.action == "set":
            r.next_steps.extend(prefix_notes)
        r.emit(True, ns.json)
        return 0

    try:
        gitops.render(repo)
    except PlatformError:
        if provides or ns.consumes:
            restore_tree(repo)
        raise
    changed = gitops.rendered_changes(repo)
    r.did.append(f"updated system.yaml and regenerated {len(changed)} file(s)")
    if ns.pr:
        title = f"feat(component): {ns.action} {' '.join(names)}"
        url = gitops.open_pr(repo, f"component/{ns.action}-{gitops.slug('-'.join(names))}", title, f"`/component:{ns.action} {' '.join(names)}`. Generated files regenerated by `devbox run render`.")
        r.did.append(f"opened {url}")
        r.next_steps.append("review and merge the PR; Argo syncs after the merge")
    else:
        r.next_steps.append("review the diff, run `devbox run validate`, then commit (or re-run with --pr)")
    if ns.action == "set":
        r.next_steps.extend(prefix_notes)
    if ns.action == "add":
        r.next_steps.append("adapt the entry if needed (env wiring such as API_URL, replicas, --expose); components start in dev only — `/instance:promote` adds staging/prod; `/resource:add <name> --type database` declares a database")
    r.undo.append("discard the working-tree changes under applications and bootstrap")
    r.data = {"components": names, "changed": changed}
    r.emit(False, ns.json)
    return 0
