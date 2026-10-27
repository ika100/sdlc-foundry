"""`cplat resource backup <db> --env <env>`: one base backup on demand through the Barman Cloud plugin (spec 117, AC-117.31, AC-117.32).

Creates `Backup <active>-manual-<YYYYMMDDHHMMSS>` for the active cluster of the database and waits for it. Nothing in git changes and
neither the schedule nor the retention is touched."""
from __future__ import annotations

import argparse
import datetime
import json
import time
from pathlib import Path

import backupstate
import gitops
import model
from core import PlatformError

POLL_S = 10.0
TIMEOUT_S = 30 * 60.0
BACKUP_KIND = "backups.postgresql.cnpg.io"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cplat resource backup", description=__doc__)
    p.add_argument("name", help="the database resource")
    p.add_argument("--env", required=True)
    p.add_argument("--app")
    p.add_argument("--repo-dir", default=".")
    p.add_argument("--context", help="kube context (default: the current one)")
    p.add_argument("--json", action="store_true")
    return p


def check(ns: argparse.Namespace, m: model.Model) -> None:
    db, env = ns.name, ns.env
    if env not in model.ENVIRONMENTS:
        raise PlatformError("--env must be dev, staging or prod")
    res = {r.name: r for r in m.resources}
    if db not in res:
        raise PlatformError(f"{db} is not a resource of the system (resources: {', '.join(res) or 'none'})")
    if res[db].type != "database":
        raise PlatformError(f"{db} is a {res[db].type}: only a database is backed up with /resource:backup")
    ri = next((i for i in m.resource_instances if i.resource == db and i.environment == env), None)
    if ri is None:
        raise PlatformError(f"{db} has no instance in {env} (no component that runs in {env} uses it)")
    if ri.external:
        raise PlatformError(f"{db} in {env}: an external database is backed up by its provider")
    if not ri.backup:
        raise PlatformError(f"{db} has no backup in {env}: set resources.{db}.instances.{env}.backup in system.yaml")


def main(argv: list[str]) -> int:
    ns = build_parser().parse_args(argv)
    app_dir = gitops.find_app(Path(ns.repo_dir).resolve(), ns.app)
    m = model.load_dir(app_dir)
    check(ns, m)
    system, db, env = app_dir.name, ns.name, ns.env
    try:
        roles = backupstate.cluster_roles(system, db, backupstate.restore_state(app_dir, env, db))
    except backupstate.StateError as e:
        raise PlatformError(str(e)) from e
    active, kns = roles["active"], f"{system}-{env}"
    try:
        backupstate.get_json(["clusters.postgresql.cnpg.io", active, "-n", kns], ns.context)
    except backupstate.ReadError as e:
        raise PlatformError(f"cannot read the cluster: {e}") from e

    stamp = datetime.datetime.fromtimestamp(time.time(), datetime.UTC).strftime("%Y%m%d%H%M%S")
    name = f"{active}-manual-{stamp}"
    obj = {"apiVersion": "postgresql.cnpg.io/v1", "kind": "Backup", "metadata": {"name": name, "namespace": kns},
           "spec": {"cluster": {"name": active}, "method": "plugin", "pluginConfiguration": {"name": backupstate.PLUGIN}}}
    rc, out, err = backupstate.kubectl(["create", "-n", kns, "-f", "-"], ns.context, input=json.dumps(obj))
    if rc != 0:
        raise PlatformError(f"cannot read the cluster: {backupstate._why(rc, err, out)}")

    deadline = time.monotonic() + TIMEOUT_S
    phase, status = "", {}
    while True:
        try:
            status = backupstate.get_json([BACKUP_KIND, name, "-n", kns], ns.context).get("status") or {}
        except backupstate.ReadError as e:
            status = {"phase": f"unknown: {e}"}
        phase = status.get("phase") or "pending"
        if phase in ("completed", "failed") or time.monotonic() >= deadline:
            break
        time.sleep(POLL_S)

    at = reason = None
    if phase == "completed":
        at = backupstate.norm_time(status.get("stoppedAt")) or backupstate.norm_time(status.get("startedAt"))
        text, result = f"backup completed: {db}/{env} at {at} (Backup {name})", "completed"
    else:
        result = "failed"
        if phase == "failed":
            reason = status.get("error") or phase
        else:
            reason = f"not finished after 30 minutes (Backup {name} is {phase})"
        text = f"backup failed: {db}/{env}: {reason}"
    if ns.json:
        print(json.dumps({"result": result, "backup": name, "at": at, "reason": reason}, indent=2))
    else:
        print(text)
    return 0 if result == "completed" else 1
