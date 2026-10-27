"""`cplat system restore <env>`: list the Velero backups of an environment or restore one into its namespace (spec 117, AC-117.19 to .21).

Without `--backup` the backups are listed. With `--backup` the objects missing from the namespace are restored (`existingResourcePolicy:
none`); volumes that still exist are refused, or replaced with `--replace` (the workload is stopped, its PVCs deleted, and it comes
back from the backup). Databases are never touched. Every kubectl call goes through `backupstate.kubectl`."""
from __future__ import annotations

import argparse
import datetime
import json
import time
from pathlib import Path

import backupstate
import gitops
import model
import yaml
from core import PlatformError

POLL_S = 10.0
TIMEOUT_S = 30 * 60.0
SKIP = "argocd.argoproj.io/skip-reconcile"
DB_LINE = "databases are not part of environment backups: restore them with /resource:restore"
RESTORE_KIND = "restores.velero.io"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cplat system restore", description=__doc__)
    p.add_argument("env")
    p.add_argument("--backup", help="a backup name or latest (default: list the backups)")
    p.add_argument("--replace", action="store_true", help="stop the workloads whose volumes exist and replace the volumes")
    p.add_argument("--confirm", help="prod: pass `prod` to do it")
    p.add_argument("--app")
    p.add_argument("--repo-dir", default=".")
    p.add_argument("--context", help="kube context (default: the current one)")
    p.add_argument("--json", action="store_true")
    return p


def _row(b: dict) -> str:
    state = b["state"]
    if state == "partially failed":
        state += f" ({b['errors']} errors)"
    elif state == "failed":
        state += f" ({b['reason'] or b['phase']})"
    return f"  {b['name']}  {b['time'] or '-'}  {state}"


def _out(lines: list[str], ns: argparse.Namespace, data: dict, rc: int) -> int:
    if ns.json:
        print(json.dumps({**data, "text": lines}, indent=2))
    else:
        for ln in lines:
            print(ln, flush=True)
    return rc


def _say(ns: argparse.Namespace, lines: list[str], text: str) -> None:
    lines.append(text)
    if not ns.json:
        print(text, flush=True)


def _k(args: list[str], ns: argparse.Namespace, **kw: object) -> tuple[int, str, str]:
    return backupstate.kubectl(args, ns.context, **kw)


def _tracking_app(kind: str, name: str, kns: str, ns: argparse.Namespace) -> str | None:
    """The Argo CD application that tracks the workload root, None when there is none (or Argo CD is not there)."""
    try:
        apps = backupstate.get_items(["applications.argoproj.io", "-n", "argocd"], ns.context)
    except backupstate.ReadError:
        return None
    for a in apps:
        for r in (a.get("status") or {}).get("resources") or []:
            if r.get("kind") == kind and r.get("name") == name and r.get("namespace") in (kns, None):
                return a["metadata"]["name"]
    return None


def _wait_exists(root: dict, kns: str, ns: argparse.Namespace) -> None:
    deadline = time.monotonic() + TIMEOUT_S
    while True:
        try:
            backupstate.get_json([backupstate._resource(root), root["name"], "-n", kns], ns.context)
            return
        except backupstate.ReadError:
            if time.monotonic() >= deadline:
                raise PlatformError(f"restore failed: {root['kind']} {root['name']} did not come back after 30 minutes") from None
            time.sleep(POLL_S)


ROLLOUT_KINDS = ("Deployment", "StatefulSet", "DaemonSet")


def _wait_rollout(root: dict, kns: str, ns: argparse.Namespace) -> None:
    """Wait until the restored workload has rolled out (kinds without a rollout, e.g. operator resources, only have to exist)."""
    if root["kind"] not in ROLLOUT_KINDS:
        return
    rc, out, err = _k(["rollout", "status", f"{root['kind'].lower()}/{root['name']}", "-n", kns, f"--timeout={int(TIMEOUT_S)}s"], ns)
    if rc != 0:
        raise PlatformError(f"restore failed: {root['kind']} {root['name']} did not become ready after 30 minutes "
                            f"({backupstate._why(rc, err, out)})")


def _replace(vols: list[dict], kns: str, ns: argparse.Namespace, lines: list[str]) -> tuple[list[dict], list[tuple[str, str]]]:
    """Stop the workload roots and delete the PVCs. Returns (roots, [(application, root name)] that were paused)."""
    roots: dict[tuple[str, str], dict] = {}
    pods: dict[tuple[str, str], set[str]] = {}
    for v in vols:
        root = backupstate.workload_root(v["kind"], v["workload"], kns, ns.context)
        key = (root["kind"], root["name"])
        roots.setdefault(key, root)
        pods.setdefault(key, set()).add(v["pod"])
    paused: list[tuple[str, str]] = []
    for key, root in roots.items():
        app = _tracking_app(root["kind"], root["name"], kns, ns)
        if app:
            rc, _, err = _k(["annotate", "applications.argoproj.io", app, "-n", "argocd", f"{SKIP}=true", "--overwrite"], ns)
            if rc != 0:
                raise PlatformError(f"cannot pause Argo CD application {app}: {backupstate._why(rc, err)}")
            paused.append((app, root["name"]))
    try:
        for key, root in roots.items():
            rc, out, err = _k(["delete", backupstate._resource(root), root["name"], "-n", kns, "--wait=false", "--ignore-not-found"], ns)
            if rc != 0:
                raise PlatformError(f"cannot stop {root['kind']} {root['name']}: {backupstate._why(rc, err, out)}")
            for pod in sorted(pods[key]):
                _k(["wait", "--for=delete", f"pod/{pod}", "-n", kns, f"--timeout={int(TIMEOUT_S)}s"], ns)
            _say(ns, lines, f"stopped {root['kind']} {root['name']}")
        for v in vols:
            rc, out, err = _k(["delete", "pvc", v["pvc"], "-n", kns, "--ignore-not-found"], ns)
            if rc != 0:
                raise PlatformError(f"cannot replace {v['pvc']}: {backupstate._why(rc, err, out)}")
            _say(ns, lines, f"replaced {v['pvc']}")
    except PlatformError:
        _unpause(paused, ns)
        raise
    return list(roots.values()), paused


def _unpause(paused: list[tuple[str, str]], ns: argparse.Namespace) -> None:
    for app, _ in paused:
        _k(["annotate", "applications.argoproj.io", app, "-n", "argocd", f"{SKIP}-"], ns)


def _run_restore(backup: str, kns: str, ns: argparse.Namespace) -> tuple[str, dict, str]:
    """Create the Restore and wait. Returns (name, status, phase)."""
    stamp = datetime.datetime.fromtimestamp(time.time(), datetime.UTC).strftime("%Y%m%d%H%M%S")
    name = f"{backup}-{stamp}"
    obj = {"apiVersion": "velero.io/v1", "kind": "Restore", "metadata": {"name": name, "namespace": backupstate.VELERO_NS},
           "spec": {"backupName": backup, "includedNamespaces": [kns], "existingResourcePolicy": "none", "restorePVs": True}}
    rc, out, err = _k(["create", "-n", backupstate.VELERO_NS, "-f", "-"], ns, input=yaml.safe_dump(obj, sort_keys=False))
    if rc != 0:
        raise PlatformError(f"cannot create the restore: {backupstate._why(rc, err, out)}")
    deadline = time.monotonic() + TIMEOUT_S
    status: dict = {}
    while True:
        try:
            status = backupstate.get_json([RESTORE_KIND, name, "-n", backupstate.VELERO_NS], ns.context).get("status") or {}
        except backupstate.ReadError:
            status = {}
        phase = status.get("phase") or "New"
        if phase in ("Completed", "PartiallyFailed", "Failed", "FailedValidation") or time.monotonic() >= deadline:
            return name, status, phase
        time.sleep(POLL_S)


def main(argv: list[str]) -> int:
    ns = build_parser().parse_args(argv)
    env = ns.env
    if env not in model.ENVIRONMENTS:
        raise PlatformError(f"{env} is not an environment (dev, staging, prod)")
    app_dir = gitops.find_app(Path(ns.repo_dir).resolve(), ns.app)
    m = model.load_dir(app_dir)
    e = m.environment(env)
    if e is None or not e.backup:
        raise PlatformError(f"{env} has no backup: set environments.{env}.backup in system.yaml")
    system, kns = app_dir.name, f"{app_dir.name}-{env}"
    try:
        backups = backupstate.velero_backups(system, env, ns.context)
        backups = [b for b in backups if b["state"] == "in progress"] + [b for b in backups if b["state"] != "in progress"]
    except backupstate.ReadError as ex:
        raise PlatformError(f"cannot read the backups: {ex}") from ex
    if not ns.backup:
        if not backups:
            raise PlatformError(f"{env} has no backups yet: the first scheduled backup has not finished")
        lines = [f"backups of {kns} (newest first):", *map(_row, backups)]
        return _out(lines, ns, {"result": "listed", "backups": backups}, 0)

    completed = [b for b in backups if b["state"] == "completed"]
    restorable = [b for b in backups if b["phase"] in ("Completed", "PartiallyFailed")]
    available = ", ".join(b["name"] for b in restorable) or "none"
    if ns.backup == "latest":
        if not completed:
            raise PlatformError(f"{env} has no backups yet: the first scheduled backup has not finished")
        chosen = completed[0]["name"]
    else:
        chosen = ns.backup
        if chosen not in {b["name"] for b in backups}:
            if not backups:
                raise PlatformError(f"{env} has no backups yet: the first scheduled backup has not finished")
            raise PlatformError(f"no backup {chosen} in {env}; available: {available}")
        picked = next(b for b in backups if b["name"] == chosen)
        if picked not in restorable:
            text = (f"backup {chosen} is {picked['state']}: only a completed or partially failed backup can be restored "
                    f"(available: {available})")
            return _out([text, DB_LINE], ns, {"result": "refused", "backup": chosen, "namespace": kns}, 1)

    lines: list[str] = []
    try:
        vols = backupstate.existing_volumes(chosen, kns, ns.context)
    except backupstate.ReadError as ex:
        raise PlatformError(f"cannot read the volumes: {ex}") from ex

    def say(text: str) -> None:
        lines.append(text)
        if not ns.json:
            print(text, flush=True)

    def finish(rc: int, result: str) -> int:
        lines.append(DB_LINE)
        if ns.json:
            print(json.dumps({"result": result, "backup": chosen, "namespace": kns, "text": lines}, indent=2))
        else:
            print(DB_LINE, flush=True)
        return rc

    if env == "prod" and ns.confirm != "prod":
        extra = f" and replace the volumes {', '.join(v['pvc'] for v in vols)}" if ns.replace and vols else ""
        say(f"would restore {chosen} into {kns}{extra}")
        say("nothing was changed: add --confirm prod to do it")
        return finish(1, "refused")
    if vols and not ns.replace:
        say(f"volumes of {chosen} still exist in {kns}: " + ", ".join(f"{v['pvc']} ({v['kind']} {v['workload']})" for v in vols))
        say("nothing was restored: add --replace to stop those workloads, replace their volumes from the backup and start them again")
        return finish(1, "refused")

    paused: list[tuple[str, str]] = []
    roots: list[dict] = []
    if vols:
        try:
            roots, paused = _replace(vols, kns, ns, lines)
        except PlatformError as ex:
            say(str(ex))
            return finish(1, "failed")
    try:
        name, status, phase = _run_restore(chosen, kns, ns)
    except PlatformError as ex:
        _unpause(paused, ns)
        say(str(ex))
        return finish(1, "failed")
    _unpause(paused, ns)

    if phase == "Completed":
        items = (status.get("progress") or {}).get("itemsRestored", 0)
        say(f"restored {chosen} into {kns}: {items} items")
        try:
            for root in roots:
                _wait_exists(root, kns, ns)
                _wait_rollout(root, kns, ns)
                say(f"started {root['kind']} {root['name']}")
        except PlatformError as ex:
            say(str(ex))
            return finish(1, "failed")
        return finish(0, "restored")
    if phase == "PartiallyFailed":
        say(f"restore partially failed: {int(status.get('errors') or 0)} errors (kubectl -n velero describe restore {name})")
    elif phase in ("Failed", "FailedValidation"):
        reason = status.get("failureReason") or (status.get("validationErrors") or [phase])[0]
        say(f"restore failed: {reason}")
    else:
        say(f"restore failed: not finished after 30 minutes (Restore {name} is {phase})")
    return finish(1, "failed")
