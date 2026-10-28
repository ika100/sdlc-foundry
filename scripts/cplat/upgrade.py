"""`cplat resource upgrade <name> --to <major> [--env <env>]`: one environment's engine upgrade of a database, cache or broker (spec 121).

A major step moves an environment to another major (`instances.<env>.version`, folded into `resources.<name>.version` by the last
environment); a pin move (`--to` equal to the current major) moves the environment to the versions table's pin of that major. Every check
runs before anything is written; with `--pr` the step is one signed-off commit on `resource/upgrade-<name>-<env>-<to>` and a pull request.
`--verify` and the verification after `--wait` are `upgradeverify.run(ns)`."""
from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import re
import sys
import time
from pathlib import Path

import backupstate
import core
import gitops
import model
import status
from core import PlatformError

ENVS = list(model.ENVIRONMENTS)
BACKUP_MAX_AGE_S = 3600
PR_TIMEOUT_S = 30 * 60.0
ARGO_TIMEOUT_S = 10 * 60.0
POLL_S = 10.0
ENGINES = {"database": "postgres", "cache": "valkey", "broker": "nats"}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cplat resource upgrade", description=__doc__)
    p.add_argument("name", help="the database, cache or broker resource")
    p.add_argument("--to", metavar="MAJOR", help="the major to move to (17, 9, 2.15); the current major moves the environment to this release's pin")
    p.add_argument("--env", help=f"the environment ({', '.join(ENVS)}); default: the first one where the resource has an instance")
    p.add_argument("--verify", action="store_true", help="verify the environment's step instead of making one")
    p.add_argument("--pr", action="store_true", help="branch, commit (signed off) and open a pull request")
    p.add_argument("--wait", action="store_true", help="with --pr: wait for the merge, then Argo CD, then verify")
    p.add_argument("--context", action="append", metavar="[ENV=]CTX", help="kube context (of one environment, or of all); repeatable")
    p.add_argument("--component-dir", action="append", metavar="C=DIR", help="a checkout of a component for the smoke tests; repeatable")
    p.add_argument("--app")
    p.add_argument("--repo-dir", default=".")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    return p


# ---------------- the repository's renderer: the table and the effective values ----------------

def load_renderer(repo: Path):
    path = repo / "scripts" / "render.py"
    if not path.is_file():
        raise PlatformError("scripts/render.py is missing", hint="run this inside a gitops-app repo")
    spec = importlib.util.spec_from_file_location("render_repo_upgrade", path)
    mod = importlib.util.module_from_spec(spec)
    keep, sys.dont_write_bytecode = sys.dont_write_bytecode, True    # no scripts/__pycache__ in the tree the checks must leave alone
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = keep
    for attr in ("SUPPORTED_MAJORS", "DEPRECATED_MAJORS", "UPGRADE_PATHS", "table_pin", "validate_resources"):
        if not hasattr(mod, attr):
            raise PlatformError("this repo's scripts/render.py predates the versions table of platform 5.4", hint="run /platform:update")
    return mod


def parse_major(typ: str, raw: str):
    """`17` reads as 17 for a database or cache; a broker line stays a string (`2.15`)."""
    text = str(raw).strip()
    if typ != "broker" and re.fullmatch(r"[0-9]+", text):
        return int(text)
    return text


def order_of(r, typ: str) -> list:
    return [*r.DEPRECATED_MAJORS.get(typ, ()), *r.SUPPORTED_MAJORS[typ]]


def list_text(items) -> str:
    return ", ".join(str(i) for i in items)


def minor_of(ref: str) -> str:
    """`16.15` of `ghcr.io/…/postgresql:16.15-2026…@sha256:…`."""
    tag = ref.split("@", 1)[0].rsplit(":", 1)[-1]
    m = re.match(r"\d+(?:\.\d+)*", tag)
    return m.group(0) if m else tag


# ---------------- the checks of design.md ----------------

class Plan:
    """Everything the checks found out about the step."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


def first_instance_env(ris: dict) -> str:
    return next((e for e in ENVS if e in ris), ENVS[0])


def record_of(system: str, name: str, env: str, ctx: str | None) -> dict | None:
    """The verification ConfigMap's data, None when there is none; backupstate.ReadError when the cluster cannot be read."""
    try:
        doc = backupstate.get_json(["configmap", f"{system}-{name}-upgrade", "-n", f"{system}-{env}"], ctx)
    except backupstate.ReadError as e:
        if "notfound" in str(e).lower().replace(" ", "") or "not found" in str(e).lower():
            return None
        raise
    return doc.get("data") or {}


def check_previous(r, plan: Plan, cfg: dict, contexts: dict[str, str]) -> None:
    prev = next((e for e in reversed(ENVS[:ENVS.index(plan.env)]) if e in plan.instances), None)
    if prev is None:
        return
    name, to, typ = plan.name, plan.to, plan.type
    env_cfg = cfg["envs"][prev]
    if env_cfg.get("external"):
        return
    order = order_of(r, typ)
    ahead = env_cfg["version"] in order and order.index(env_cfg["version"]) > order.index(to)
    if not plan.major_step and ahead:
        to = env_cfg["version"]     # a pin move: the earlier environment may already run a higher major (verified at its own pin)
    table = r.table_pin(typ, to)["pin"]
    where = f"{prev} is not ready for {plan.env}: {name} in {prev}"
    if env_cfg["version"] != to or env_cfg["pin"] != table:
        hint = f"/resource:upgrade {name} --to {to}" + ("" if prev == ENVS[0] else f" --env {prev}")
        raise PlatformError(f"{where} runs {env_cfg['version']} ({env_cfg['pin']}), not {to} ({table})", hint=hint)
    verify = f"cplat resource upgrade {name} --verify --env {prev}"
    try:
        data = record_of(plan.system, name, prev, contexts.get(prev))
    except backupstate.ReadError as e:
        raise PlatformError(f"{where} cannot be read ({e})", hint=f"pass --context {prev}=<ctx>") from e
    if data and data.get("image") == table and data.get("state") == "verified":
        return
    if data and data.get("image") == table and data.get("state") == "failed":
        raise PlatformError(f"{where} failed its verification at {data.get('at', '?')} ({data.get('check', '')})", hint=verify)
    raise PlatformError(f"{where} is on {to} but not verified", hint=verify)


def check_backup(plan: Plan, ri, ns: argparse.Namespace, app_dir: Path) -> str:
    name, env = plan.name, plan.env
    if not ri.backup:
        raise PlatformError(f"{name} in {env} has no backup: resources.{name}.instances.{env}.backup is required for a major upgrade",
                            hint=f"set it in system.yaml, then /resource:backup {name} --env {env}")
    try:
        got = status.public_backups(status.collect_backups(Path(ns.repo_dir).resolve(), ns.app, ns.context))
    except (backupstate.ReadError, backupstate.StateError) as e:
        raise PlatformError(f"cannot read the backups of {name} in {env}: {e}",
                            hint=f"check the kube context: cplat system status --context {env}=<ctx>") from e
    entry = next((i for i in got["resource_instances"] if (i["resource"], i["environment"]) == (name, env)), None)
    b = (entry or {}).get("backup") or {}
    if b.get("state") == "unknown" or entry is None:
        contexts = status.parse_contexts(ns.context, ENVS)
        raise PlatformError(f"cannot read the backups of {name} in {env}: {b.get('error') or b.get('state') or 'not found'}",
                            hint=f"check the kube context: cplat system status --context {env}={contexts.get(env) or '<ctx>'}")
    last = b.get("last_success")
    when = backupstate.parse_time(last) if last else None
    if when is None or (datetime.datetime.now(datetime.UTC) - when).total_seconds() > BACKUP_MAX_AGE_S:
        raise PlatformError(f"{name} in {env}: the last successful backup is {last or 'never'} (more than 60 minutes ago); "
                            "a major upgrade needs one from the last 60 minutes", hint=f"take one now: /resource:backup {name} --env {env}")
    return last


def checks(ns: argparse.Namespace, repo: Path, app_dir: Path, m: model.Model, r, doc: dict, cfgs: dict) -> Plan | str:
    """The designed checks 1 to 16 in order: a Plan, or the text of a step that has nothing to do."""
    name = ns.name
    ris_all = [ri for ri in m.resource_instances if ri.resource == name]
    ris = {ri.environment: ri for ri in ris_all}
    env = ns.env or first_instance_env(ris)
    if env not in ENVS:
        raise PlatformError(f"--env must be {', '.join(ENVS[:-1])} or {ENVS[-1]}")
    resources = {x.name: x for x in m.resources}
    if name not in resources:
        raise PlatformError(f"{name} is not a resource of the system (resources: {', '.join(resources) or 'none'})")
    typ = resources[name].type
    if typ == "bucket":
        raise PlatformError(f"{name} is a bucket: it has no version; its SeaweedFS image moves with the platform release (/platform:update, dev first)")
    if ns.to is None:
        raise PlatformError("--to is required (the major to move to)")
    to = parse_major(typ, ns.to)
    order = order_of(r, typ)
    if to not in order:
        raise PlatformError(f"version '{ns.to}' is not a supported {typ} version ({list_text(order)})")
    ri = ris.get(env)
    if ri is None:
        raise PlatformError(f"{name} has no instance in {env} (no component that runs in {env} uses it)")
    cfg = cfgs[name]
    env_cfg = cfg["envs"][env]
    if ri.external or env_cfg.get("external"):
        raise PlatformError(f"{name} is external in {env}: its owner upgrades it, the platform does not")
    cur = env_cfg["version"]
    if cur in order and order.index(to) < order.index(cur):
        raise PlatformError(f"{name} in {env} is on {cur}; {to} is lower and /resource:upgrade only moves up",
                            hint=f"the way back for a database is /resource:restore {name} --env {env} --to <time|latest>" if typ == "database" else None)
    major_step = to != cur
    if major_step and to in r.DEPRECATED_MAJORS.get(typ, ()):
        raise PlatformError(f"{to} is deprecated: upgrade to one of {list_text(r.SUPPORTED_MAJORS[typ])}")
    if major_step and to not in r.UPGRADE_PATHS[typ].get(cur, ()):
        below = [p for p in r.UPGRADE_PATHS[typ].get(cur, ()) if order.index(p) < order.index(to)]
        first = f"; upgrade to {below[-1]} first" if below else ""
        raise PlatformError(f"{name} in {env}: {cur} → {to} is not a supported upgrade path for {ENGINES[typ]}{first}",
                            hint=f"/resource:upgrade {name} --to {below[-1]} --env {env}" if below else None)
    plan = Plan(name=name, type=typ, env=env, to=to, cur=cur, major_step=major_step, instances=ris, system=m.system, ri=ri,
                old_ref=env_cfg["pin"], new_ref=r.table_pin(typ, to)["pin"], backup_time=None, cfg=cfg)
    contexts = status.parse_contexts(ns.context, ENVS)
    check_previous(r, plan, cfg, contexts)
    current_table = r.table_pin(typ, cur)
    held = env_cfg["pin"] != current_table["pin"] or (typ == "broker" and env_cfg.get("chart_version") != current_table["chart_version"])
    if major_step and held:
        raise PlatformError(f"{name} in {env} still runs {env_cfg['pin']} from an earlier platform release; move it to this release's {cur} pin first",
                            hint=f"/resource:upgrade {name} --to {cur} --env {env}")
    if not major_step and not held:
        return f"{name} in {env} already runs {env_cfg['pin']}; nothing to do"
    if major_step and typ == "database":
        plan.backup_time = check_backup(plan, ri, ns, app_dir)
    return plan


# ---------------- the step's edit ----------------

def users_of(m: model.Model, plan: Plan) -> list[str]:
    """The components running in the environment that use the resource (a broker: providers and consumers of its events APIs)."""
    running = {i.component for i in m.instances if i.environment == plan.env}
    events = {a.name for a in m.apis if a.type == "events"}
    out = []
    for c in m.components:
        if c.name not in running:
            continue
        if plan.name in c.uses or (plan.type == "broker" and events & {*c.provides, *c.consumes}):
            out.append(c.name)
    return out


def edit_system(app_dir: Path, plan: Plan) -> str:
    """Write the version into system.yaml (comments kept); returns what was written."""
    from ruamel.yaml.comments import CommentedMap
    y, data = gitops.load(app_dir)
    res = data["resources"][plan.name]
    last = [e for e in ENVS if e in plan.instances][-1]
    if plan.env == last:
        res["version"] = plan.to
        inst = res.get("instances")
        if inst:
            for e in list(inst):
                if isinstance(inst[e], dict):
                    inst[e].pop("version", None)
                    if not inst[e]:
                        del inst[e]
            if not inst:
                del res["instances"]
        what = f"resources.{plan.name}.version: {plan.to}"
    else:
        if res.get("instances") is None:
            res["instances"] = CommentedMap()
        if res["instances"].get(plan.env) is None:
            res["instances"][plan.env] = CommentedMap()
        res["instances"][plan.env]["version"] = plan.to
        what = f"resources.{plan.name}.instances.{plan.env}.version: {plan.to}"
    gitops.save(app_dir, y, data)
    return what


def write_archives(app_dir: Path, plan: Plan) -> str:
    """The new archive of a backed-up database: the last entry is the current one (restore-state.yaml `archives`)."""
    name, env = plan.name, plan.env
    state = backupstate.restore_state(app_dir, env, name)
    base = f"{app_dir.name}-{name}"
    if state is None:
        state = {"next": 1, "clusters": [{"name": base, "role": "active"}]}
    archives = list(state.get("archives") or [])
    if not archives:
        archives.append({"server": backupstate.cluster_roles(app_dir.name, name, state)["active"], "major": plan.cur})
    server = f"{base}-pg{plan.to}"
    archives.append({"server": server, "major": plan.to})
    backupstate.write_restore_state(app_dir, env, name, {**state, "archives": archives})
    return server


def drop_rendered_pin(app_dir: Path, plan: Plan) -> str:
    """A pin move: the rendered file of the instance goes, the render writes it again with the table's pin."""
    folder = app_dir / "addons" / plan.env / plan.name
    if plan.type == "database":
        base = f"{app_dir.name}-{plan.name}"
        active = backupstate.cluster_roles(app_dir.name, plan.name, backupstate.restore_state(app_dir, plan.env, plan.name))["active"]
        file = "cluster.yaml" if active == base else f"cluster-g{active[len(base) + 2:]}.yaml"
    else:
        file = {"cache": "statefulset.yaml", "broker": "server.yaml"}[plan.type]
    (folder / file).unlink(missing_ok=True)
    return f"applications/{app_dir.name}/addons/{plan.env}/{plan.name}/{file}"


def next_of(plan: Plan, doc: dict) -> str | None:
    if not plan.major_step:
        return None
    later = next((e for e in ENVS[ENVS.index(plan.env) + 1:] if e in plan.instances), None)
    if later is None:
        return None
    promote = ((doc.get("environments") or {}).get("staging") or {}).get("promote")
    if plan.env == ENVS[0] and later == "staging" and promote == "after-dev-smoke":
        return "staging follows by itself (promote: after-dev-smoke)"
    cmd = f"/resource:upgrade {plan.name} --to {plan.to} --env {later}"
    return f"prod is upgraded by hand: {cmd}" if later == ENVS[-1] else cmd


def title_of(plan: Plan) -> str:
    if plan.major_step:
        return f"feat(resource): upgrade {plan.name} to {plan.to} in {plan.env}"
    return f"chore(resource): move {plan.name} to {minor_of(plan.new_ref)} in {plan.env}"


def body_of(plan: Plan, users: list[str], nxt: str | None) -> str:
    n, env = plan.name, plan.env
    if plan.major_step:
        head = f"Upgrade {n} ({plan.type}) in {env}: {plan.cur} → {plan.to}"
        backup = (f"backup: last successful {plan.backup_time} (within 60 minutes)" if plan.type == "database" else f"backup: {n} has no backup")
    else:
        head = f"Move {n} ({plan.type}) in {env} to this release's {plan.to} pin"
        backup = "backup: no backup check (minor or patch move)"
    smoke = ", ".join(f"{c} ({env})" for c in users) or "no component"
    lines = [head, f"image: {plan.old_ref} → {plan.new_ref}", backup,
             f"after the merge: the platform waits up to 15 minutes for {n} to be healthy on {plan.new_ref}, then runs the smoke tests of {smoke}"]
    if nxt:
        lines.append(f"next: {nxt}")
    elif plan.major_step:
        lines.append(f"next: none, {n} runs {plan.to} in every environment")
    return "\n".join(lines)


# ---------------- pull request, wait ----------------

def open_pr(repo: Path, branch: str, title: str, body: str) -> str:
    """Branch, commit (signed off), push and `gh pr create`; returns the URL."""
    core.run(["git", "checkout", "-q", "-b", branch], cwd=repo)
    core.run(["git", "add", "applications", "bootstrap"], cwd=repo, check=False)
    core.run(["git", *core.git_identity(repo), "commit", "-q", "-s", "-m", title], cwd=repo)
    core.run(["git", "push", "-q", "-u", "origin", branch], cwd=repo)
    out = core.run(["gh", "pr", "create", "--base", "main", "--title", title, "--body", body], cwd=repo).stdout.strip().splitlines()
    return out[-1] if out else ""


def wait_for_argo(name: str, env: str, system: str, ctx: str | None, say) -> None:
    app = f"addon-{name}-{env}"
    deadline = time.monotonic() + ARGO_TIMEOUT_S
    while True:
        try:
            st = backupstate.get_json(["applications.argoproj.io", app, "-n", "argocd"], ctx).get("status") or {}
        except backupstate.ReadError:
            st = {}
        sync = (st.get("sync") or {}).get("status")
        health = (st.get("health") or {}).get("status")
        if sync == "Synced" and health != "Degraded":
            say(f"Argo CD application {app} is Synced")
            return
        if time.monotonic() >= deadline:
            raise PlatformError(f"Argo CD application {app} is not Synced and healthy within 10 minutes ({sync or 'unknown'}, {health or 'unknown'})")
        time.sleep(POLL_S)


# ---------------- rollback of a failed edit or render ----------------

TREES = ("applications", "bootstrap")


def snapshot_tree(repo: Path) -> dict[Path, bytes]:
    """Every file the command can write (applications/ and bootstrap/), to put back when the edit or the render fails."""
    return {f: f.read_bytes() for t in TREES if (repo / t).is_dir() for f in (repo / t).rglob("*") if f.is_file()}


def restore_tree(repo: Path, saved: dict[Path, bytes]) -> None:
    for t in TREES:
        if (repo / t).is_dir():
            for f in [f for f in (repo / t).rglob("*") if f.is_file() and f not in saved]:
                f.unlink()
    for f, data in saved.items():
        if not f.is_file() or f.read_bytes() != data:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(data)
    for t in TREES:
        if (repo / t).is_dir():
            for d in sorted((d for d in (repo / t).rglob("*") if d.is_dir()), reverse=True):
                if not any(d.iterdir()):
                    d.rmdir()


# ---------------- command ----------------

def main(argv: list[str]) -> int:
    ns = build_parser().parse_args(argv)
    if ns.verify:
        import upgradeverify
        if not ns.env:
            raise PlatformError("--verify needs --env")
        return upgradeverify.run(ns)
    if ns.wait and not ns.pr:
        raise PlatformError("--wait needs --pr")
    repo = Path(ns.repo_dir).resolve()
    app_dir = gitops.find_app(repo, ns.app)
    m = model.load_dir(app_dir)
    r = load_renderer(repo)
    import yaml
    doc = yaml.safe_load((app_dir / "system.yaml").read_text()) or {}
    try:
        cfgs = r.validate_resources(doc, app_dir)
    except r.RenderError as e:
        raise PlatformError(f"applications/{app_dir.name}/system.yaml: {e}") from e
    say = (lambda *_: None) if ns.json else print
    plan = checks(ns, repo, app_dir, m, r, doc, cfgs)
    if isinstance(plan, str):
        say(plan)
        return 0
    if not ns.dry_run:
        gitops.require_clean(repo)
    users = users_of(m, plan)
    nxt = next_of(plan, doc)
    result = {"step": "major" if plan.major_step else "pin", "resource": plan.name, "type": plan.type, "env": plan.env,
              "from": {"major": plan.cur, "ref": plan.old_ref}, "to": {"major": plan.to, "ref": plan.new_ref}, "pr": None,
              "verification": None, "next": nxt if plan.major_step else None}
    if ns.dry_run:
        if ns.json:
            print(json.dumps(result, indent=2))
            return 0
        print(f"## upgrade {plan.name} in {plan.env}  (dry run - nothing was changed)")
        print(f"  {plan.name} ({plan.type}) in {plan.env}: {plan.cur} → {plan.to}; image {plan.old_ref} → {plan.new_ref}")
        if plan.major_step:
            print(f"  would write instances.{plan.env}.version: {plan.to}" + (" and a new archive" if plan.type == "database" and plan.ri.backup else ""))
        else:
            print("  would move the rendered pin to this release's pin")
        print(f"  would run the smoke tests of {', '.join(users) or 'no component'}")
        return 0
    what = []
    saved = snapshot_tree(repo)
    try:
        if plan.major_step:
            what.append(edit_system(app_dir, plan))
            if plan.type == "database" and plan.ri.backup:
                what.append(f"archive {write_archives(app_dir, plan)}")
        else:
            what.append(f"moved the pin ({drop_rendered_pin(app_dir, plan)})")
        gitops.render(repo)
    except BaseException:
        restore_tree(repo, saved)
        raise
    if not ns.pr:
        if ns.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"wrote the {plan.env} step: {'; '.join(what)}; apply it, then verify: cplat resource upgrade {plan.name} --verify --env {plan.env}")
        return 0
    original = core.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo).stdout.strip() or "main"
    url = open_pr(repo, f"resource/upgrade-{plan.name}-{plan.env}-{plan.to}", title_of(plan), body_of(plan, users, nxt))
    result["pr"] = url
    say(f"opened {url}")
    code = 0
    if ns.wait:
        import pr
        import ship
        ok, lines = pr.wait(repo, url, True, PR_TIMEOUT_S, 20, ship.QUEUE_TIMEOUT)
        if not ok:
            raise PlatformError(f"the pull request {url} did not merge: {'; '.join(lines)}")
        core.run(["git", "checkout", "-q", original if original != "HEAD" else "main"], cwd=repo)
        core.run(["git", "pull", "-q"], cwd=repo, check=False)
        ctx = status.parse_contexts(ns.context, ENVS).get(plan.env)
        if ctx:
            wait_for_argo(plan.name, plan.env, plan.system, ctx, say)
        import upgradeverify
        code = upgradeverify.run(ns, env=plan.env, quiet=ns.json)
    else:
        core.run(["git", "checkout", "-q", original if original != "HEAD" else "main"], cwd=repo, check=False)
    if ns.json:
        print(json.dumps(result, indent=2))
    return code
