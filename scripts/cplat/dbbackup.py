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
import dbbackupset
import envcluster
import gitops
import model
from core import PlatformError

POLL_S = 10.0
TIMEOUT_S = 30 * 60.0
ARCHIVE_WAIT_S = 2 * 60.0
BACKUP_KIND = "backups.postgresql.cnpg.io"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cplat resource backup", description=__doc__)
    p.add_argument("name", help="the database resource")
    p.add_argument("--env", required=True)
    p.add_argument("--app")
    p.add_argument("--repo-dir", default=".")
    p.add_argument("--context", help="kube context (default: the environment's cluster for a system spread over clusters, else the current one)")
    p.add_argument("--to", metavar="BUCKET", help="set the scheduled backup: the bucket resource that receives it")
    p.add_argument("--schedule", metavar="CRON", help="set the scheduled backup: five-field cron in UTC, or hourly, daily (\"0 3 * * *\", the default), weekly (Sunday 03:00)")
    p.add_argument("--retention", metavar="N", help="set the scheduled backup: <n>d or <n>w (default 30d)")
    p.add_argument("--off", action="store_true", help="remove the scheduled backup (the backups in the bucket are kept)")
    p.add_argument("--dry-run", action="store_true", help="with a setting option: print the change, write nothing")
    p.add_argument("--pr", action="store_true", help="with a setting option: open a pull request")
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
    if ns.to is not None or ns.schedule is not None or ns.retention is not None or ns.off:
        return dbbackupset.run(ns)
    if ns.dry_run or ns.pr:
        raise PlatformError("--dry-run and --pr belong to --to, --schedule, --retention and --off",
                            hint="an on-demand backup changes nothing in git: run it without --dry-run and --pr")
    app_dir = gitops.find_app(Path(ns.repo_dir).resolve(), ns.app)
    m = model.load_dir(app_dir)
    check(ns, m)
    system, db, env = app_dir.name, ns.name, ns.env
    ns.context = envcluster.env_context(Path(ns.repo_dir).resolve(), m, env, ns.context)
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
    try:
        backupstate.create_backup(kns, active, name, ns.context)
    except backupstate.ReadError as e:
        raise PlatformError(f"cannot read the cluster: {e}") from e

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

    at = reason = warning = None
    if phase == "completed":
        at = backupstate.norm_time(status.get("stoppedAt")) or backupstate.norm_time(status.get("startedAt"))
        text, result = f"backup completed: {db}/{env} at {at} (Backup {name})", "completed"
        if status.get("endWal"):
            warning = _archive_end(kns, active, str(status["endWal"]), ns.context)
            if warning:
                text += f"\nWARNING: {warning}"
    else:
        result = "failed"
        if phase == "failed":
            reason = (status.get("error") or phase) + _archiving_hint(kns, active, ns.context)
        else:
            reason = f"not finished after 30 minutes (Backup {name} is {phase})"
        text = f"backup failed: {db}/{env}: {reason}"
    if ns.json:
        print(json.dumps({"result": result, "backup": name, "at": at, "reason": reason, "warning": warning}, indent=2))
    else:
        print(text)
    return 0 if result == "completed" else 1


def _archiving_hint(kns: str, cluster: str, context: str | None) -> str:
    """J21-3: CloudNativePG reports a failed backup as `rpc error: … exit status 1`; when the cluster's WAL archiving fails
    too, the bucket is the cause (journey 21: its pods could not pull their image), so the reason names it."""
    try:
        conds = (backupstate.get_json(["clusters.postgresql.cnpg.io", cluster, "-n", kns], context).get("status") or {}).get("conditions") or []
    except backupstate.ReadError:
        return ""
    arch = next((c for c in conds if c.get("type") == "ContinuousArchiving"), None)
    if not arch or arch.get("status") == "True":
        return ""
    if backupstate.plugin_starting(arch):   # #864: the first backup PR installs the plugin; it is still starting
        return " (the backup plugin is still starting: try again in a few minutes)"
    return (f" (WAL archiving to the bucket fails too: {arch.get('message') or 'no message'}; the bucket is likely not ready, "
            f"see kubectl get pods -n {kns})")


def _archive_end(kns: str, cluster: str, end_wal: str, context: str | None) -> str | None:
    """J21-4: a backup of an idle database completes while its last WAL segment waits in pg_wal, and a restore to it fails ("WAL
    ends before end of online backup") until that segment is archived. Switch the segment once and wait ARCHIVE_WAIT_S for it; the
    warning when it is still not archived, else None."""
    try:
        obj = backupstate.get_json(["clusters.postgresql.cnpg.io", cluster, "-n", kns], context)
    except backupstate.ReadError as e:
        return f"cannot check that its last WAL segment {end_wal} is archived: {e}"
    deadline, switched = time.monotonic() + ARCHIVE_WAIT_S, False
    while True:
        done, last = backupstate.end_wal_archived(obj, kns, end_wal, context)
        if done:
            return None
        if time.monotonic() >= deadline:
            return (f"its last WAL segment {end_wal} is not archived yet (newest archived: {last or 'none'}), so a restore to this "
                    "backup fails until it is")
        if not switched:
            switched = backupstate.switch_wal(obj, kns, context)
        time.sleep(POLL_S)
