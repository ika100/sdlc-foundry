"""`cplat resource restore <db> --env <env> (--to <time|latest> | --switch | --discard)`: restore a database by generation (spec 117).

`--to` adds a restored instance `<system>-<db>-g<n>` next to the running one (state in git: `restore-state.yaml`), `--switch` makes
it the active one and repoints the connection Secret, `--discard` removes the restored (else the previous) instance with its
volumes. The change goes through Argo CD (a pull request, merged) when the addon application exists, else it is committed and
applied with kubectl."""
from __future__ import annotations

import argparse
import base64
import copy
import datetime
import json
import re
import time
from pathlib import Path

import backupstate
import core
import gitops
import model
from core import PlatformError, Report

POLL_S = 10.0
TIMEOUT_S = 30 * 60.0
ARGO_TIMEOUT_S = 10 * 60.0
PR_TIMEOUT_S = 30 * 60.0
PLUGIN_TIMEOUT_S = 10 * 60.0
FIRST_SETTLE_S = 180.0   # longer than backupstate.FIRST_GRACE: then a cluster without any Backup gets its first one
CLUSTER_KIND = "clusters.postgresql.cnpg.io"
SECRET_KEYS = ("host", "uri", "jdbc-uri", "pgpass", "fqdn-uri", "fqdn-jdbc-uri")
OFFSET_TIME = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(Z|z|[+-]\d\d:\d\d)$")
CHOOSE = "choose one of --to <time>, --switch or --discard"
PROD = model.ENVIRONMENTS[-1]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cplat resource restore", description=__doc__)
    p.add_argument("name", help="the database resource")
    p.add_argument("--env", required=True)
    p.add_argument("--to", metavar="TIME", help="restore to this RFC 3339 time (with an offset), or latest")
    p.add_argument("--switch", action="store_true", help="make the restored instance the active one")
    p.add_argument("--discard", action="store_true", help="remove the restored (else the previous) instance and its volumes")
    p.add_argument("--confirm", help=f"--switch and --discard in {PROD} need --confirm {PROD}")
    p.add_argument("--app")
    p.add_argument("--repo-dir", default=".")
    p.add_argument("--context", help="kube context (default: the current one)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    return p


def _now() -> str:
    return backupstate.fmt_time(datetime.datetime.fromtimestamp(time.time(), datetime.UTC).replace(microsecond=0))


def _read_cluster(name: str, kns: str, context: str | None) -> dict:
    try:
        return backupstate.get_json([CLUSTER_KIND, name, "-n", kns], context)
    except backupstate.ReadError as e:
        raise PlatformError(f"cannot read the cluster: {e}") from e


def check(ns: argparse.Namespace, m: model.Model) -> model.ResourceInstance:
    db, env = ns.name, ns.env
    actions = [bool(ns.to), ns.switch, ns.discard]
    if sum(actions) != 1:
        raise PlatformError(CHOOSE)
    if ns.confirm is not None and ns.confirm != PROD:
        raise PlatformError(f"--confirm takes {PROD}")
    if env not in model.ENVIRONMENTS:
        raise PlatformError(f"--env must be {', '.join(model.ENVIRONMENTS[:-1])} or {PROD}")
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
    if ns.to:
        if not ri.backup:
            raise PlatformError(f"{db} has no backup in {env}: set resources.{db}.instances.{env}.backup in system.yaml")
        if ns.to != "latest" and not (OFFSET_TIME.match(ns.to) and backupstate.parse_time(ns.to)):
            raise PlatformError(f"--to must be an RFC 3339 time with an offset (e.g. 2026-10-27T09:30:00Z) or latest, got '{ns.to}'")
    return ri


def _retarget_secret(secret: dict, old: str, new: str) -> list[dict]:
    """The JSON patch that detaches the connection Secret from CloudNativePG and points it at `<new>-rw`."""
    ops: list[dict] = []
    if (secret.get("metadata") or {}).get("ownerReferences"):
        ops.append({"op": "remove", "path": "/metadata/ownerReferences"})
    for key in SECRET_KEYS:
        raw = (secret.get("data") or {}).get(key)
        if raw is None:
            continue
        text = base64.b64decode(raw).decode()
        ops.append({"op": "replace", "path": f"/data/{key}", "value": base64.b64encode(text.replace(f"{old}-rw", f"{new}-rw").encode()).decode()})
    return ops


def _major_before_upgrade(state: dict, server: str) -> tuple[int, int] | None:
    """(major of the archive `server`, major of the next archive) when the restore source is an archive before a later upgrade."""
    archives = state.get("archives") or []
    for i, a in enumerate(archives[:-1]):
        if a.get("server") == server:
            return int(a["major"]), int(archives[i + 1]["major"])
    return None


def _write(args: list[str], context: str | None, what: str, **kw) -> str:
    rc, out, err = backupstate.kubectl(args, context, **kw)
    if rc != 0:
        raise PlatformError(f"{what}: {backupstate._why(rc, err, out)}")
    return out


def _argo_app(name: str, context: str | None) -> bool:
    try:
        backupstate.get_json(["applications.argoproj.io", name, "-n", "argocd"], context)
        return True
    except backupstate.ReadError:
        return False


def _publish(repo: Path, app_dir: Path, ns: argparse.Namespace, title: str, action: str, kns: str, r: Report) -> bool:
    """Commit the change and bring it to the cluster: a merged pull request synced by Argo CD, else commit and `apply -k`.
    Returns True on the Argo CD path. A ScheduledBackup's cluster cannot change in place, so on a switch the old one is deleted:
    after the sync (Argo CD recreates it) or, on the apply path, before the apply (which creates it for the new active cluster)."""
    db, env, ctx = ns.name, ns.env, ns.context
    app = f"addon-{db}-{env}"
    if _argo_app(app, ctx):
        import pr
        import ship
        branch = core.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo).stdout.strip() or "main"
        url = gitops.open_pr(repo, f"restore/{db}-{env}-{action}", title, f"`/resource:restore {db} --env {env}` ({action}). State in restore-state.yaml.")
        r.did.append(f"opened {url}")
        ok, lines = pr.wait(repo, url, True, PR_TIMEOUT_S, 20, ship.QUEUE_TIMEOUT)
        if not ok:
            raise PlatformError(f"the pull request {url} did not merge: {'; '.join(lines)}")
        core.run(["git", "checkout", "-q", branch if branch != "HEAD" else "main"], cwd=repo)
        core.run(["git", "pull", "-q"], cwd=repo, check=False)
        head = core.run(["git", "rev-parse", "HEAD"], cwd=repo).stdout.strip()
        deadline = time.monotonic() + ARGO_TIMEOUT_S
        while True:
            try:
                st = (backupstate.get_json(["applications.argoproj.io", app, "-n", "argocd"], ctx).get("status") or {}).get("sync") or {}
            except backupstate.ReadError:
                st = {}
            if st.get("revision") == head and st.get("status") == "Synced":
                break
            if time.monotonic() >= deadline:
                raise PlatformError(f"Argo CD application {app} did not sync {head[:7]} within 10 minutes")
            time.sleep(POLL_S)
        r.did.append(f"merged and synced by Argo CD ({app})")
        return True
    core.run(["git", "add", "-A"], cwd=repo)
    core.run(["git", *core.git_identity(repo), "commit", "-q", "-m", title], cwd=repo)
    r.did.append(f"committed: {title}")
    if action == "switch":
        _delete_scheduled_backup(f"{app_dir.name}-{db}", kns, ctx)
    _write(["apply", "-n", kns, "-k", str(app_dir / "addons" / env / db)], ctx, "cannot apply the database objects")
    r.did.append(f"applied applications/{app_dir.name}/addons/{env}/{db}")
    return False


def _delete_scheduled_backup(name: str, kns: str, ctx: str | None) -> None:
    _write(["delete", "scheduledbackup.postgresql.cnpg.io", name, "-n", kns, "--ignore-not-found"], ctx, "cannot delete the ScheduledBackup")


def _wait_ready(name: str, kns: str, ctx: str | None, db: str, env: str) -> None:
    rc, out, err = backupstate.kubectl(["wait", "--for=condition=Ready", f"cluster.postgresql.cnpg.io/{name}", "-n", kns,
                                        f"--timeout={int(TIMEOUT_S)}s"], ctx, timeout=TIMEOUT_S + 60)
    if rc == 0:
        return
    reason = backupstate._why(rc, err, out)
    try:
        st = backupstate.get_json([CLUSTER_KIND, name, "-n", kns], ctx).get("status") or {}
        reason = str(st.get("phaseReason") or "") or backupstate.cluster_phase({"status": st}) or reason
    except backupstate.ReadError:
        pass
    raise PlatformError(f"restore failed: {db}/{env}: {reason}", hint="the restored instance stays for inspection until --discard")


def _wait_archiving(name: str, kns: str, ctx: str | None) -> bool:
    """Wait until the cluster has loaded the backup plugin (ContinuousArchiving True); False after PLUGIN_TIMEOUT_S."""
    deadline = time.monotonic() + PLUGIN_TIMEOUT_S
    while True:
        try:
            arch = backupstate._cond(backupstate.get_json([CLUSTER_KIND, name, "-n", kns], ctx), "ContinuousArchiving")
            if arch and arch.get("status") == "True":
                return True
        except backupstate.ReadError:
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(POLL_S)


def _first_backup_lines(system: str, db: str, env: str, name: str, kns: str, ctx: str | None, state: dict) -> list[str]:
    """After a switch: wait for the plugin on the new active cluster, then take its first base backup (CloudNativePG never retries
    the immediate Backup that failed because the plugin was not loaded yet)."""
    if not _wait_archiving(name, kns, ctx):
        return [f"the plugin is not loaded on {name} yet; the alert poll takes the first base backup when it is"]
    # The immediate Backup may be recorded as failed a moment after archiving starts: look again for FIRST_SETTLE_S, and stop as soon
    # as the cluster has a Backup that did not fail (running or completed).
    deadline = time.monotonic() + FIRST_SETTLE_S
    while True:
        try:
            backup = backupstate.take_first_backup(system, db, env, ctx, datetime.datetime.fromtimestamp(time.time(), datetime.UTC), state)
            if backup:
                return [f"first base backup of {name} started (Backup {backup})"]
            fine = [b for b in backupstate.database_backups(system, db, kns, [name], ctx) if (b.get("status") or {}).get("phase") != "failed"]
        except backupstate.ReadError as e:
            return [f"could not take the first base backup of {name}: {e}; the alert poll takes it when it can"]
        if fine or time.monotonic() >= deadline:
            return []
        time.sleep(POLL_S)


def _wait_volumes_gone(name: str, kns: str, ctx: str | None) -> None:
    deadline = time.monotonic() + TIMEOUT_S
    while True:
        try:
            left = backupstate.get_items(["persistentvolumeclaims", "-n", kns, "-l", f"cnpg.io/cluster={name}"], ctx)
        except backupstate.ReadError as e:
            raise PlatformError(f"cannot read the volumes of {name}: {e}") from e
        if not left:
            return
        if time.monotonic() >= deadline:
            raise PlatformError(f"the volumes of {name} are still there after 30 minutes: {', '.join(p['metadata']['name'] for p in left)}")
        time.sleep(POLL_S)


def main(argv: list[str]) -> int:
    ns = build_parser().parse_args(argv)
    repo = Path(ns.repo_dir).resolve()
    app_dir = gitops.find_app(repo, ns.app)
    m = model.load_dir(app_dir)
    ri = check(ns, m)
    system, db, env, ctx = app_dir.name, ns.name, ns.env, ns.context
    kns = f"{system}-{env}"
    try:
        state = backupstate.restore_state(app_dir, env, db)
    except backupstate.StateError as e:
        raise PlatformError(str(e)) from e
    roles = backupstate.cluster_roles(system, db, state)
    base_state = state if state is not None else {"next": 1, "clusters": [{"name": f"{system}-{db}", "role": "active"}]}
    new = copy.deepcopy(base_state)
    r = Report(title=f"resource restore {db} --env {env} ({system})")
    lines: list[str] = []

    if ns.to:
        when = ns.to if ns.to == "latest" or ns.to.endswith("Z") else backupstate.norm_time(ns.to)
        have = [(label, hit) for label, hit in (("restored", roles["restored"]), ("previous", (roles["previous"] or {}).get("name"))) if hit]
        if have:
            raise PlatformError(f"{db}/{env} already has a {have[0][0]} instance {have[0][1]}; discard it first: /resource:restore {db} --env {env} --discard")
        row = backupstate.database_state(system, db, env, ctx, backup=True, state=state)
        if row["backup"]["state"] == "unknown":
            raise PlatformError(f"cannot read the cluster: {row['backup']['error']}")
        pts = backupstate.restore_points(row)
        server = backupstate.source_server(row, state, when, system, db) if (when != "latest" or pts["earliest"]) else None
        if server is None:
            raise PlatformError(f"{when} is outside the restore points of {db}/{env}: earliest {pts['earliest'] or 'none'}, latest {pts['latest'] or 'none'}")
        name = f"{system}-{db}-g{base_state['next']}"
        new["clusters"].append({"name": name, "role": "restored", "from": {"server": server, "to": when}})
        new["next"] = base_state["next"] + 1
        title = f"chore(restore): restore {db}/{env} to {when}"
        action = "restore"
        r.will_do += [f"add the restored instance {name} (from {server}, to {when}) to restore-state.yaml and regenerate manifests (render.py)",
                      f"commit '{title}' and bring it to {kns} (Argo CD pull request if addon-{db}-{env} exists, else kubectl apply -k)",
                      f"wait up to 30 minutes for {name} to be ready"]
        old_major = _major_before_upgrade(base_state, server)
    elif ns.switch:
        if not roles["restored"]:
            raise PlatformError(f"{db}/{env} has no restored instance to switch to; restore one first: /resource:restore {db} --env {env} --to <time>")
        name, old = roles["restored"], roles["active"]
        cl = _read_cluster(name, kns, ctx)
        if not backupstate.cluster_ready(cl):
            raise PlatformError(f"{db}/{env}: the restored instance {name} is not ready ({backupstate.cluster_phase(cl)})")
        for c in new["clusters"]:
            if c["name"] == name:
                c["role"] = "active"
            elif c["name"] == old:
                c["role"], c["until"] = "previous", _now()
        title = f"chore(restore): switch {db}/{env} to {name}"
        action = "switch"
        what = f"switch {db}/{env} from {old} to {name}"
        r.will_do += [f"make {name} the active instance and {old} previous in restore-state.yaml; regenerate manifests (render.py)",
                      f"commit '{title}' and bring it to {kns}",
                      f"delete ScheduledBackup {system}-{db} (recreated for {name})",
                      f"point Secret {system}-{db}-app at {name}-rw and detach it from CloudNativePG",
                      f"delete the pods of the components that use {db} and wait for their rollout"]
    else:
        name = roles["restored"] or (roles["previous"] or {}).get("name")
        if not name:
            raise PlatformError(f"{db}/{env} has no restored or previous instance to discard")
        role = "restored" if roles["restored"] else "previous"
        new["clusters"] = [c for c in new["clusters"] if c["name"] != name]
        title = f"chore(restore): discard {name} of {db}/{env}"
        action = "discard"
        what = f"discard {name} ({role}) of {db}/{env} and its volumes"
        r.will_do += [f"remove {name} from restore-state.yaml; regenerate manifests (render.py)",
                      f"commit '{title}' and bring it to {kns}",
                      f"delete the cluster {name} and wait until its volumes are gone"]

    if (ns.switch or ns.discard) and env == PROD and ns.confirm != PROD and not ns.dry_run:
        raise PlatformError(f"would {what}; nothing was changed: add --confirm {PROD} to do it")
    if ns.dry_run:
        if ns.json:
            r.emit(True, True)
        else:
            print("\n".join([f"## {r.title}  (dry run - nothing was changed)", *(f"will_do: {s}" for s in r.will_do)]))
        return 0
    gitops.require_clean(repo)

    try:
        backupstate.write_restore_state(app_dir, env, db, new)
    except backupstate.StateError as e:
        raise PlatformError(str(e)) from e
    gitops.render(repo)
    r.did.append(f"updated restore-state.yaml and regenerated {len(gitops.rendered_changes(repo))} file(s)")
    via_argo = _publish(repo, app_dir, ns, title, action, kns, r)

    if ns.to:
        _wait_ready(name, kns, ctx, db, env)
        dbname = system.replace("-", "_")
        lines = [f"restored {db}/{env} to {when} as {name}; components still use {roles['active']}",
                 f"check it: kubectl -n {kns} exec -it {name}-1 -- psql {dbname}",
                 f"switch to it: /resource:restore {db} --env {env} --switch"]
        if old_major:
            lines.insert(1, f"the restored instance runs {db} {old_major[0]} (the data from before the upgrade to {old_major[1]})")
        r.data = {"result": "restored", "cluster": name, "to": when}
    elif ns.switch:
        if via_argo:
            _delete_scheduled_backup(f"{system}-{db}", kns, ctx)
        secret_name = f"{system}-{db}-app"
        try:
            secret = backupstate.get_json(["secret", secret_name, "-n", kns], ctx)
        except backupstate.ReadError as e:
            raise PlatformError(f"switched in git, but cannot read Secret {secret_name}: {e}") from e
        ops = _retarget_secret(secret, old, name)
        if ops:
            _write(["patch", "secret", secret_name, "-n", kns, "--type=json", "-p", json.dumps(ops)], ctx, f"cannot patch Secret {secret_name}")
        r.did.append(f"Secret {secret_name} points at {name}-rw")
        users = [c.name for c in m.components if db in c.uses and m.instance(c.name, env) is not None]
        for c in users:
            _write(["delete", "pod", "-n", kns, "-l", f"app={c}"], ctx, f"cannot delete the pods of {c}")
        for c in users:
            _write(["rollout", "status", f"deployment/{c}", "-n", kns, "--timeout=300s"], ctx, f"{c} did not roll out again", timeout=360)
        r.did.append(f"restarted {', '.join(users) or 'no component'}")
        lines = [f"switched {db}/{env} to {name}; {old} is previous (no connections); discard it with /resource:restore {db} --env {env} --discard"]
        if ri.backup:
            lines += _first_backup_lines(system, db, env, name, kns, ctx, new)
        r.data = {"result": "switched", "cluster": name, "previous": old}
    else:
        _write(["delete", CLUSTER_KIND, name, "-n", kns, "--ignore-not-found"], ctx, f"cannot delete the cluster {name}")
        _wait_volumes_gone(name, kns, ctx)
        active = backupstate.cluster_roles(system, db, new)["active"]
        lines = [f"discarded {name} ({role}) of {db}/{env} and its volumes; {active} stays active, the backups in the bucket are unchanged"]
        r.data = {"result": "discarded", "cluster": name, "role": role}
    r.did += lines
    r.undo.append("git revert the commit and run the command again, or restore the state file from git history")
    if ns.json:
        r.emit(False, True)
    else:
        print("\n".join(lines))
    return 0
