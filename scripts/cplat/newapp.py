"""`system new`: create a whole system (gitops-app repo + component repos) from a manifest.

Everything per repo is delegated to `new-service` (same rendering, bootstrap commit, topics, plugin enablement); this
module only adds the manifest, the creation order, an all-or-nothing pre-flight and the failure/resume handling.
After the repos exist, one `compose add --pr` pins every deployable component in the gitops-app repo.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import re
from pathlib import Path

import yaml

import compose
import core
import newsvc
from core import PlatformError, Report, run

TOP_KEYS = {"system", "owner", "org", "visibility", "components"}
COMPONENT_KEYS = {"name", "description", "type", "lang", "data"}
# creation order after the gitops-app repo: libraries before the services that use them, web frontends last
SHAPE_ORDER = {"service-python": 1, "service-java": 2, "service-go": 3, "web-nextjs": 4}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cplat system new", description=__doc__)
    p.add_argument("manifest", help="path to the system manifest (system.yml)")
    p.add_argument("--org", help="GitHub org/user (default: the manifest's org, else your gh login)")
    p.add_argument("--public", action="store_true", help="create the GitHub repos as public (default: the manifest's visibility, else private)")
    p.add_argument("--ref", default="main", help="platform git ref recorded for the plugin marketplace (default main)")
    p.add_argument("--dir", default=".", help="parent directory for the new repos (default: current directory)")
    p.add_argument("--no-github", action="store_true", help="local repos only; print the GitHub and compose commands instead of running them")
    p.add_argument("--resume", action="store_true", help="skip repos that already exist and continue with the rest")
    p.add_argument("--skip-tasks", action="store_true", help="skip the templates' bootstrap tasks (tests/CI)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    return p


def load_manifest(path: Path) -> dict:
    try:
        raw = yaml.safe_load(path.read_text())
    except OSError as e:
        raise PlatformError(f"cannot read {path}: {e.strerror}", hint="pass the path to your system manifest") from None
    except yaml.YAMLError as e:
        raise PlatformError(f"{path} is not valid YAML: {e}") from None
    if not isinstance(raw, dict):
        raise PlatformError(f"{path} must be a mapping with `system`, `owner` and `components`")
    if "app" in raw:
        raise PlatformError("`app` is `system` in 5.0")
    unknown = set(raw) - TOP_KEYS
    if unknown:
        raise PlatformError(f"unknown key(s) in {path.name}: {', '.join(sorted(unknown))}", hint="allowed: " + ", ".join(sorted(TOP_KEYS)))
    app = raw.get("system")
    if not isinstance(app, str) or not newsvc.NAME_RE.match(app):
        raise PlatformError(f"invalid system name '{app}'", hint="kebab-case, 2-40 chars, must start with a letter: ^[a-z][a-z0-9-]{1,39}$")
    if not isinstance(raw.get("owner"), str) or not raw["owner"].strip():
        raise PlatformError("`owner` is required (a team or person that owns the system)")
    if raw.get("visibility", "private") not in ("private", "public"):
        raise PlatformError(f"visibility must be private or public, got '{raw['visibility']}'")
    comps = raw.get("components")
    if not isinstance(comps, list) or not comps:
        raise PlatformError("`components` must be a non-empty list")
    seen = {app, f"{app}-gitops"}
    for i, c in enumerate(comps, 1):
        if not isinstance(c, dict):
            raise PlatformError(f"component {i} must be a mapping with name, description, type and lang")
        if "shape" in c:
            raise PlatformError(f"component '{c.get('name', i)}': shape is replaced by type and lang in 5.0")
        bad = set(c) - COMPONENT_KEYS
        if bad:
            raise PlatformError(f"component {i}: unknown key(s) {', '.join(sorted(bad))}", hint="allowed: " + ", ".join(sorted(COMPONENT_KEYS)))
        for key in ("name", "description", "type", "lang"):
            if not isinstance(c.get(key), str) or not c[key].strip():
                raise PlatformError(f"component {i}: `{key}` is required")
        name = c["name"]
        if name in seen:
            raise PlatformError(f"component {i}: name '{name}' is " + ("the gitops repo name" if name in (app, f"{app}-gitops") else "used twice"),
                                hint=f"the gitops repo is created as {app}-gitops; every component needs its own name")
        seen.add(name)
        if (c["type"], c["lang"]) not in newsvc.valid_pairs():
            raise PlatformError(f"component '{name}': {c['type']}/{c['lang']} is not a valid component type (valid: {newsvc.pairs_text()})")
        if c.get("data") is not None and not isinstance(c["data"], dict):
            raise PlatformError(f"component '{name}': `data` must be a mapping of template options")
    return raw


def shape_of(component: dict) -> str:
    """The shape id (template) a manifest component's type and lang map to."""
    return newsvc.shape_of_pair(component["type"], component["lang"])


def order(components: list[dict]) -> list[dict]:
    """Libraries first, then services and web frontends; stable for equal shapes (manifest order)."""
    shapes = {s["id"]: s for s in core.registry.load()}

    def key(c: dict) -> int:
        shape = shape_of(c)
        entry = shapes.get(shape)
        if entry is not None and entry["library"]:
            return 0
        return SHAPE_ORDER.get(shape, 5)
    return sorted(components, key=key)


def _is_repo(target: Path, shape: str) -> bool:
    answers = target / ".copier-answers.yml"
    if not answers.is_file():
        return False
    src = (yaml.safe_load(answers.read_text()) or {}).get("_src_path", "")
    return str(src).rstrip("/").endswith(f"templates/{shape}")


def _remote_exists(slug: str) -> bool:
    return run(["gh", "repo", "view", slug], check=False).returncode == 0


def resolve(argv: list[str]) -> dict:
    """Parse and validate everything; no side effects. Each repo is validated by new-service's own resolver."""
    ns = build_parser().parse_args(argv)
    manifest = load_manifest(Path(ns.manifest))
    system = manifest["system"]
    app = f"{system}-gitops"  # the gitops repo; the system name stays the application directory
    github = not ns.no_github and core.has_gh()
    org = ns.org or manifest.get("org") or (core.gh_login() if not ns.no_github else None) or "ika100"
    visibility = "public" if ns.public else manifest.get("visibility", "private")
    if visibility == "public" and ns.no_github:
        raise PlatformError("public repositories need GitHub", hint="drop --no-github, or set visibility: private")
    base = ["--org", org, "--dir", ns.dir, "--ref", ns.ref]
    base += ["--no-github"] if ns.no_github else ["--visibility", visibility]
    if ns.skip_tasks:
        base.append("--skip-tasks")

    entries = [{"name": app, "shape": "gitops-app", "description": f"GitOps repo for the {system} system",
                "args": ["--shape", "gitops-app", "--data", f"owner={manifest['owner'].strip()}"]}]
    for c in order(manifest["components"]):
        args = ["--type", c["type"], "--lang", c["lang"], "--system", f"{org}/{app}"]
        for k, v in (c.get("data") or {}).items():
            args += ["--data", f"{k}={v}"]
        entries.append({"name": c["name"], "shape": shape_of(c), "description": c["description"].strip(), "args": args})

    shapes = {s["id"]: s for s in core.registry.load()}
    for e in entries:
        target = Path(ns.dir).resolve() / e["name"]
        e["slug"] = f"{org}/{e['name']}"
        shape = shapes.get(e["shape"])
        e["existing"] = bool(ns.resume and shape and _is_repo(target, shape["template"]))
        try:
            e["req"] = None if e["existing"] else newsvc.resolve([e["name"], "--description", e["description"], *e["args"], *base])
        except PlatformError as err:
            raise PlatformError(f"{e['name']}: {err}", hint=err.hint) from None
        if github and not e["existing"] and _remote_exists(e["slug"]):
            raise PlatformError(f"GitHub repository {e['slug']} already exists",
                                hint="choose another name, or clone it into the target directory and re-run with --resume" if ns.resume
                                else "choose another name; to continue an interrupted run use --resume")
    deployable = [e["name"] for e in entries[1:] if shapes[e["shape"]]["deployable"]]
    return {"ns": ns, "app": app, "org": org, "entries": entries, "deployable": deployable, "github": github, "dir": Path(ns.dir).resolve()}


def plan(req: dict) -> Report:
    r = Report(title=f"New system: {req['app']} ({len(req['entries'])} repos)")
    for i, e in enumerate(req["entries"], 1):
        if e["req"] is None:
            r.will_do.append(f"{e['name']} ({e['shape']}): already exists, skipped (--resume)")
        else:
            r.will_do.append(f"{e['name']} ({e['shape']}): " + "; ".join(newsvc.plan(e["req"]).will_do))
    if req["deployable"]:
        if req["github"]:
            r.will_do.append(f"[outward] open one pull request in {req['org']}/{req['app']} adding to system.yaml: {', '.join(req['deployable'])}")
        else:
            r.will_do.append("gh is not available or --no-github: try the component add; print its command if the pull request cannot be opened")
    return r


def _failure(req: dict, created: list[str], failed: str, err: Exception, undo: list[str]) -> PlatformError:
    left = [e["name"] for e in req["entries"] if e["name"] not in created and e["name"] != failed]
    lines = [f"{failed} failed: {err}"]
    lines.append("created: " + (", ".join(created) or "nothing"))
    if left:
        lines.append("not started: " + ", ".join(left))
    hint = "fix the cause, then re-run the same command with --resume to continue"
    if undo:
        hint += ". To start over instead: " + " && ".join(undo)
    return PlatformError("; ".join(lines), hint=hint)


def execute(req: dict) -> Report:
    r = plan(req)
    created: list[str] = []
    undo: list[str] = []
    for e in req["entries"]:
        if e["req"] is None:
            r.did.append(f"{e['name']}: already exists, skipped")
            created.append(e["name"])
            continue
        try:
            sub = newsvc.execute(e["req"])
        except Exception as err:  # noqa: BLE001  (any failure leaves partial state: report it and how to continue)
            raise _failure(req, created, e["name"], err, undo) from err
        created.append(e["name"])
        undo += sub.undo
        r.did.append(f"{e['name']} ({e['shape']}): " + "; ".join(sub.did))
    r.undo = list(dict.fromkeys(undo))

    app_dir = req["dir"] / req["app"]
    names = req["deployable"]
    compose_cmd = f"cd {req['app']} && /component:add {' '.join(names)} --pr"
    if names:
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                compose.main(["add", *names, "--repo-dir", str(app_dir), "--pr"])
        except Exception as err:  # noqa: BLE001
            if req["github"]:
                raise PlatformError(f"repos created, but wiring them into {req['app']} failed: {err}",
                                    hint=f"run it again by hand: {compose_cmd}") from err
            r.next_steps.append(f"after the repos are on GitHub: {compose_cmd}")  # local-only repos have no remote to open the PR on
        else:
            url = re.search(r"https://\S+/pull/\d+", buf.getvalue())
            r.did.append("composed " + ", ".join(names) + (f"; opened {url.group(0)}" if url else ""))
            r.next_steps.append(f"review and merge the pull request in {req['org']}/{req['app']}; then `cd {req['app']} && devbox run cluster-up`")
        r.next_steps.append(newsvc.token_step(f"{req['org']}/{req['app']}", [f"{req['org']}/{n}" for n in names]))
    r.next_steps.append(f'spec first: cd {req["app"]} and run /system:spec "<first feature of the system>" (answer, approve), then /system:plan <NNN> (review the plan) and /system:ship <NNN>')
    r.next_steps.append("more components later: /component:new, then /component:add <name> in the gitops repo")
    r.next_steps.append("env wiring and exposure per component: /component:set (see its --env and --expose)")
    r.data = {"app": req["app"], "repos": created, "composed": names if req["github"] else []}
    return r


def main(argv: list[str]) -> int:
    req = resolve(argv)
    if req["ns"].dry_run:
        plan(req).emit(True, req["ns"].json)
        return 0
    execute(req).emit(False, req["ns"].json)
    return 0
