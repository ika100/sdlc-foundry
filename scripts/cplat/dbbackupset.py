"""`cplat resource backup <db> --env <env> --to|--schedule|--retention|--off`: set, change or remove a database instance's scheduled
backup in system.yaml and render the manifests (spec 187, AC-187.4 to AC-187.6). Never reads the cluster."""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.scalarstring import DoubleQuotedScalarString

import gitops
import model
import systemset
from core import PlatformError, Report

RETENTION = re.compile(r"^[1-9][0-9]*[dw]$")
CRON_RANGES = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 7)]        # minute, hour, day of month, month, day of week
CRON_ITEM = re.compile(r"^(\*|[0-9]+|[0-9]+-[0-9]+)(/[0-9]+)?$")
RENDER_HINT = "system.yaml and the generated files are restored: fix what the render names and run again"


def names(items: list[str]) -> str:
    return ", ".join(items) or "none"


def cron_ok(value: str) -> bool:
    fields = value.split()
    ok = len(fields) == 5
    for field, (lo, hi) in zip(fields, CRON_RANGES):
        for item in field.split(","):
            m = CRON_ITEM.match(item)
            if not m:
                ok = False
                continue
            if m.group(2) is not None and int(m.group(2)[1:]) < 1:
                ok = False
            nums = [int(x) for x in m.group(1).split("-")] if m.group(1) != "*" else []
            if any(not lo <= x <= hi for x in nums) or (len(nums) == 2 and nums[0] > nums[1]):
                ok = False
    return ok


def rtype(name: str, conf) -> str:
    return str((conf or {}).get("type") or ("database" if name == "postgres" else "unknown"))


def run(ns: argparse.Namespace) -> int:
    repo = Path(ns.repo_dir).resolve()
    app_dir = gitops.find_app(repo, ns.app)
    y, data = gitops.load(app_dir)
    db, env = ns.name, ns.env
    key = f"resources.{db}.instances.{env}.backup"
    given = {k: v for k, v in (("to", ns.to), ("schedule", ns.schedule), ("retention", ns.retention)) if v is not None}
    if ns.off and given:
        raise PlatformError(f"{key}: --off cannot be combined with --to, --schedule or --retention", hint="run --off alone")
    envs = data.get("environments") or {}
    if env not in envs:
        raise PlatformError(f"environments.{env}: '{env}' is not an environment of the system", hint="environments: " + ", ".join(envs))
    resources = data.get("resources") or {}
    dbs = [n for n, c in resources.items() if rtype(n, c) == "database"]
    if db not in dbs:
        extra = f" (it is a {rtype(db, resources[db])})" if db in resources else ""
        raise PlatformError(f"resources.{db}: '{db}' is not a database resource of the system{extra}", hint=f"databases: {names(dbs)}")
    res = resources[db] or {}
    inst = (res.get("instances") or {}).get(env) or {}
    external = inst["external"] if "external" in inst else res.get("external")
    if external is True:
        raise PlatformError(f"resources.{db}.instances.{env}: an external database is backed up by its provider",
                            hint="set backups at the database's provider; nothing is set here")
    current = inst.get("backup")
    buckets = [n for n, c in resources.items() if rtype(n, c) == "bucket"]
    if ns.off and not current:
        raise PlatformError(f"{key}: there is no backup to turn off", hint="nothing to do: /system:status shows the backups")
    if not ns.off and not current and "to" not in given:
        raise PlatformError(f"{key}: --schedule and --retention need --to on an instance without backup",
                            hint=f"add --to <bucket> (buckets: {names(buckets)})")
    if "to" in given and given["to"] not in buckets:
        raise PlatformError(f"{key}.to: '{given['to']}' is not a bucket resource of the system (buckets: {names(buckets)})",
                            hint="add one with /resource:add <name> --type bucket, or pick a listed bucket")
    if "schedule" in given and not cron_ok(given["schedule"]):
        raise PlatformError(f"{key}.schedule '{given['schedule']}' is not a five-field cron expression "
                            "(minute hour day-of-month month day-of-week, in UTC)", hint='e.g. --schedule "0 3 * * *"')
    if "retention" in given and not (RETENTION.match(given["retention"]) and not given["retention"].endswith("\n")):
        raise PlatformError(f"{key}.retention '{given['retention']}' must be <n>d or <n>w with n of at least 1",
                            hint="e.g. --retention 30d or --retention 8w")

    if ns.off:
        eff = None
        kept = str(current.get("to"))
    else:
        base = dict(current) if current else {"schedule": model.DEFAULT_SCHEDULE, "retention": model.DEFAULT_RETENTION}
        base.update(given)
        eff = {k: str(base[k]) for k in ("to", "schedule", "retention") if k in base}
        kept = None
    r = Report(title=f"resource backup: {db}/{env} ({app_dir.name})")
    if eff is None:
        r.will_do.append(f"remove {key} (backups already in bucket {kept} are kept)")
    else:
        r.will_do.append(f'set {key}: to {eff["to"]}, schedule "{eff.get("schedule")}", retention {eff.get("retention")}')
    r.will_do.append("regenerate ApplicationSets and manifests (render.py)")
    if ns.pr:
        r.will_do.append("[outward] open a pull request (branch resource/backup-…)")
    if ns.dry_run:
        r.data = {"backup": eff, "kept_in": kept, "changed": [], "pr": None}
        r.emit(True, ns.json)
        return 0

    gitops.require_clean(repo)
    before = systemset.snapshot(repo)
    raw = (app_dir / "system.yaml").read_text()
    res = data["resources"][db]
    if eff is None:
        del res["instances"][env]["backup"]
        if not res["instances"][env]:
            del res["instances"][env]
        if not res["instances"]:
            del res["instances"]
    else:
        if res.get("instances") is None:
            res["instances"] = CommentedMap()
        if res["instances"].get(env) is None:
            res["instances"][env] = CommentedMap()
        node = res["instances"][env]
        if current:
            for k, v in given.items():
                node["backup"][k] = DoubleQuotedScalarString(v) if k == "schedule" else v
        else:
            b = CommentedMap()
            b["to"] = eff["to"]
            b["schedule"] = DoubleQuotedScalarString(eff["schedule"])
            b["retention"] = eff["retention"]
            node["backup"] = b
    gitops.save(app_dir, y, data)
    try:
        gitops.render(repo)
    except PlatformError as e:
        systemset.restore(repo, before)
        (app_dir / "system.yaml").write_text(raw)
        raise PlatformError(str(e), hint=getattr(e, "hint", None) or RENDER_HINT) from e
    changed = gitops.rendered_changes(repo)
    r.did.append(f"updated system.yaml and regenerated {len(changed)} file(s)")
    if eff is None:
        r.did.append(f"backups already in bucket {kept} are kept; /resource:restore can still read them")
    url = None
    if ns.pr:
        title = (f"chore(resource): stop scheduled backups of {db} in {env}" if eff is None
                 else f"chore(resource): back up {db} in {env}")
        url = gitops.open_pr(repo, f"resource/backup-{gitops.slug(db)}-{gitops.slug(env)}", title,
                             f"`cplat resource backup {db} --env {env}`: {r.will_do[0]}. Generated files regenerated by `devbox run render`.")
        r.did.append(f"opened {url}")
        r.next_steps.append("review and merge the PR; the first scheduled backup runs after the sync")
    else:
        r.next_steps.append("review the diff, run `devbox run validate`, then commit (or re-run with --pr)")
    r.undo.append("discard the working-tree changes under applications and bootstrap")
    r.data = {"backup": eff, "kept_in": kept, "changed": changed, "pr": url}
    r.emit(False, ns.json)
    return 0
