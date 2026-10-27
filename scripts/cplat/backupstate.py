"""Backup state of databases and environments, read from the cluster (spec 117).

Every kubectl call of the backup commands, the status table and the alert poll goes through `kubectl(args, context, **kw)`: reads
(`get <kind> [name] -n NS [-l k=v] -o json`) and writes alike, so tests replace this one function. Nothing is written to git here
except `write_restore_state`. Values read from the cluster are never stored.

Readers: `database_state`, `environment_state`, `velero_backups`, `pod_volume_backups`, `existing_volumes`, `workload_root`,
`database_failing_since`, `environment_failing_since`, `first_backup_pending`, `take_first_backup`, `create_backup`. State file: `restore_state`, `write_restore_state`.
"""
from __future__ import annotations

import datetime
import json
import re
import subprocess
from pathlib import Path

import yaml

TIMEOUT_S = 60.0
PLUGIN = "barman-cloud.cloudnative-pg.io"
PLUGIN_UNAVAILABLE = "requested plugin is not available"
VELERO_NS = "velero"
HEADER = "# Written by `cplat resource restore` (spec 117). render.py reads it; do not edit it by hand.\n"
GEN = re.compile(r"-g([0-9]+)$")
RFC3339_Z = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?Z$")
ONE_HOUR = datetime.timedelta(hours=1)


class StateError(Exception):
    """A restore-state.yaml that does not parse or breaks the rules (the message is the whole design text)."""


class ReadError(Exception):
    """The cluster could not be read; the message says why."""


# ---------------- the seam ----------------

def kubectl(args: list[str], context: str | None = None, *, input: str | None = None, timeout: float = TIMEOUT_S,
            **_: object) -> tuple[int, str, str]:
    """(exit code, stdout, stderr). Never raises. `input` is fed to stdin. Tests replace this function."""
    cmd = ["kubectl", *(["--context", context] if context else []), *map(str, args)]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, input=input, timeout=timeout, check=False)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "kubectl timed out"
    except FileNotFoundError:
        return 127, "", "kubectl is missing"
    except Exception as e:  # noqa: BLE001
        return 1, "", f"{type(e).__name__}: {e}"


def _k(args: list[str], context: str | None, **kw: object) -> tuple[int, str, str]:
    return kubectl(args, context, **kw)  # looked up at call time: tests patch the module attribute


def _why(rc: int, err: str, out: str = "") -> str:
    text = (err or out or "").strip().splitlines()
    return text[-1] if text else f"kubectl exited {rc}"


def get_json(args: list[str], context: str | None) -> dict:
    """`kubectl get <args> -o json` as a dict; ReadError when it fails or the output is not JSON."""
    rc, out, err = _k(["get", *args, "-o", "json"], context)
    if rc != 0:
        raise ReadError(_why(rc, err, out))
    try:
        doc = json.loads(out or "{}")
    except ValueError as e:
        raise ReadError(f"kubectl printed no JSON ({e})") from e
    return doc if isinstance(doc, dict) else {}


def get_items(args: list[str], context: str | None) -> list[dict]:
    return [i for i in get_json(args, context).get("items") or [] if isinstance(i, dict)]


# ---------------- times ----------------

def parse_time(text: object) -> datetime.datetime | None:
    """An RFC 3339 time (any offset, `Z`, or a Postgres `+00` offset) as an aware UTC datetime; None when it is not one."""
    if not isinstance(text, str) or not text.strip():
        return None
    t = text.strip().replace(" ", "T", 1)
    if t.endswith(("Z", "z")):
        t = t[:-1] + "+00:00"
    t = re.sub(r"([+-]\d\d)$", r"\1:00", t)
    try:
        d = datetime.datetime.fromisoformat(t)
    except ValueError:
        return None
    if d.tzinfo is None:
        return None
    return d.astimezone(datetime.UTC)


def fmt_time(d: datetime.datetime) -> str:
    """RFC 3339 UTC ending in `Z`; fractional seconds are kept when present."""
    d = d.astimezone(datetime.UTC)
    frac = f".{d.microsecond:06d}".rstrip("0") if d.microsecond else ""
    return d.strftime("%Y-%m-%dT%H:%M:%S") + frac + "Z"


def norm_time(text: object) -> str | None:
    d = parse_time(text)
    return fmt_time(d) if d else None


def _when(obj: dict, *paths: tuple[str, ...]) -> datetime.datetime | None:
    for path in paths:
        cur: object = obj
        for k in path:
            cur = cur.get(k) if isinstance(cur, dict) else None
        d = parse_time(cur)
        if d:
            return d
    return None


_MIN = datetime.datetime.min.replace(tzinfo=datetime.UTC)


# ---------------- restore-state.yaml ----------------

def state_file(app_dir: Path, env: str, db: str) -> Path:
    return Path(app_dir) / "addons" / env / db / "restore-state.yaml"


def check_state(state: object, system: str, db: str) -> str | None:
    """The reason a state breaks the rules of the design, or None."""
    if not isinstance(state, dict):
        return "not a mapping"
    clusters = state.get("clusters")
    if not isinstance(clusters, list) or not clusters or not all(isinstance(c, dict) for c in clusters):
        return "clusters must be a list of clusters"
    if not isinstance(state.get("next"), int) or isinstance(state.get("next"), bool):
        return "next must be a number"
    roles = [c.get("role") for c in clusters]
    if any(r not in ("active", "restored", "previous") for r in roles):
        return "role must be active, restored or previous"
    if roles.count("active") != 1:
        return "exactly one cluster must be active"
    if roles.count("restored") + roles.count("previous") > 1:
        return "at most one cluster may be restored or previous"
    base, top = f"{system}-{db}", 0
    for c in clusters:
        name = c.get("name")
        if not isinstance(name, str) or not name:
            return "every cluster needs a name"
        m = GEN.search(name)
        if name != base and not (m and name == f"{base}-g{m.group(1)}"):
            return f"cluster {name} is not {base} or {base}-g<n>"
        if m:
            top = max(top, int(m.group(1)))
            f = c.get("from")
            if not isinstance(f, dict) or not isinstance(f.get("server"), str):
                return f"cluster {name} needs from.server"
            if f.get("to") != "latest" and not (isinstance(f.get("to"), str) and RFC3339_Z.match(f["to"]) and parse_time(f["to"])):
                return f"cluster {name}: from.to must be an RFC 3339 UTC time ending in Z or latest"
        if c.get("role") == "previous" and not (isinstance(c.get("until"), str) and RFC3339_Z.match(c["until"])):
            return f"cluster {name} is previous and needs until (RFC 3339 UTC)"
    if state["next"] <= top:
        return "next must be greater than every generation number"
    return None


def restore_state(app_dir: Path, env: str, db: str) -> dict | None:
    """The parsed restore-state.yaml of `<app_dir>/addons/<env>/<db>/`, None when there is none. StateError when it is invalid."""
    p = state_file(app_dir, env, db)
    if not p.is_file():
        return None
    system = Path(app_dir).name
    shown = f"applications/{system}/addons/{env}/{db}/restore-state.yaml"
    try:
        state = yaml.safe_load(p.read_text())
    except (yaml.YAMLError, OSError) as e:
        raise StateError(f"{shown} is not valid (does not parse: {str(e).splitlines()[0] if str(e) else 'error'}); take it from git history") from e
    why = check_state(state, system, db)
    if why:
        raise StateError(f"{shown} is not valid ({why}); take it from git history")
    return state


def write_restore_state(app_dir: Path, env: str, db: str, state: dict) -> Path:
    """Write the state (header kept, rules checked first; StateError when broken). Returns the path."""
    system = Path(app_dir).name
    why = check_state(state, system, db)
    if why:
        raise StateError(f"applications/{system}/addons/{env}/{db}/restore-state.yaml is not valid ({why})")
    p = state_file(app_dir, env, db)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(HEADER + yaml.safe_dump(state, sort_keys=False, default_flow_style=False))
    return p


def cluster_roles(system: str, db: str, state: dict | None) -> dict:
    """{"active": name, "restored": name|None, "previous": {"name", "until"}|None, "all": [names]}."""
    base = f"{system}-{db}"
    out: dict = {"active": base, "restored": None, "previous": None, "all": [base]}
    for c in (state or {}).get("clusters") or []:
        if c["name"] not in out["all"]:
            out["all"].append(c["name"])
        if c["role"] == "active":
            out["active"] = c["name"]
        elif c["role"] == "restored":
            out["restored"] = c["name"]
        elif c["role"] == "previous":
            out["previous"] = {"name": c["name"], "until": c.get("until")}
    return out


# ---------------- databases ----------------

def _cond(cluster: dict, kind: str) -> dict | None:
    for c in (cluster.get("status") or {}).get("conditions") or []:
        if isinstance(c, dict) and c.get("type") == kind:
            return c
    return None


def cluster_ready(cluster: dict) -> bool:
    c = _cond(cluster, "Ready")
    return bool(c and c.get("status") == "True")


def cluster_phase(cluster: dict) -> str:
    """Why a cluster is not ready: its phase, else the Ready condition's message."""
    st = cluster.get("status") or {}
    return str(st.get("phase") or (_cond(cluster, "Ready") or {}).get("message") or "not ready")


def _finished(backups: list[dict]) -> list[dict]:
    """Backups that ended (completed or failed), newest first."""
    done = [b for b in backups if (b.get("status") or {}).get("phase") in ("completed", "failed")]
    return sorted(done, key=lambda b: _when(b, ("status", "stoppedAt"), ("metadata", "creationTimestamp")) or _MIN, reverse=True)


def _stopped(b: dict) -> datetime.datetime | None:
    return _when(b, ("status", "stoppedAt"), ("metadata", "creationTimestamp"))


def _phase(b: dict) -> str:
    return (b.get("status") or {}).get("phase") or ""


def _of(b: dict, cluster: str) -> bool:
    return ((b.get("spec") or {}).get("cluster") or {}).get("name") == cluster


def _plugin_failure(b: dict) -> bool:
    return PLUGIN_UNAVAILABLE in str((b.get("status") or {}).get("error") or "")


def create_backup(ns: str, cluster: str, name: str, context: str | None) -> None:
    """Create the plugin Backup `name` of `cluster` in namespace `ns`. ReadError (with kubectl's reason) when kubectl fails."""
    obj = {"apiVersion": "postgresql.cnpg.io/v1", "kind": "Backup", "metadata": {"name": name, "namespace": ns},
           "spec": {"cluster": {"name": cluster}, "method": "plugin", "pluginConfiguration": {"name": PLUGIN}}}
    rc, out, err = _k(["create", "-n", ns, "-f", "-"], context, input=json.dumps(obj))
    if rc != 0:
        raise ReadError(_why(rc, err, out))


FIRST_GRACE = datetime.timedelta(minutes=2)


def first_backup_pending(system: str, db: str, env: str, context: str | None, state: dict | None = None,
                         now: datetime.datetime | None = None) -> bool:
    """True when the active cluster has loaded the plugin (ContinuousArchiving True), has no completed and no running Backup, and
    either a failed Backup says the plugin was not available then, or (with `now`) it has no Backup at all although archiving has
    run for FIRST_GRACE (the ScheduledBackup's immediate Backup did not appear; seen after a switch). ReadError on kubectl failure."""
    ns, active = f"{system}-{env}", cluster_roles(system, db, state)["active"]
    arch = _cond(get_json(["clusters.postgresql.cnpg.io", active, "-n", ns], context), "ContinuousArchiving")
    if not arch or arch.get("status") != "True":
        return False
    mine = [b for b in get_items(["backups.postgresql.cnpg.io", "-n", ns], context) if _of(b, active)]
    if any(_phase(b) != "failed" for b in mine):  # completed or still running
        return False
    if any(_plugin_failure(b) for b in mine):
        return True
    since = parse_time(arch.get("lastTransitionTime"))
    return not mine and now is not None and since is not None and now - since >= FIRST_GRACE


def take_first_backup(system: str, db: str, env: str, context: str | None, now: datetime.datetime,
                      state: dict | None = None) -> str | None:
    """Create Backup `<active>-first-<YYYYMMDDHHMMSS>` when the first base backup is pending; its name, else None."""
    if not first_backup_pending(system, db, env, context, state, now):
        return None
    active = cluster_roles(system, db, state)["active"]
    name = f"{active}-first-{now.astimezone(datetime.UTC).strftime('%Y%m%d%H%M%S')}"
    create_backup(f"{system}-{env}", active, name, context)
    return name


def database_backups(system: str, db: str, ns: str, names: list[str], context: str | None) -> list[dict]:
    """Every CloudNativePG Backup of any cluster of this database (a name in `names`)."""
    keep = set(names)
    return [b for b in get_items(["backups.postgresql.cnpg.io", "-n", ns], context) if ((b.get("spec") or {}).get("cluster") or {}).get("name") in keep]


def database_state(system: str, db: str, env: str, context: str | None, *, backup: bool, external: bool = False,
                   state: dict | None = None) -> dict:
    """The status row of a database resource instance (AC-117.6/.27). `state` is the parsed restore-state.yaml (or None).

    Returns {"resource", "environment", "cluster", "backup": {last_success, state, archiving, error, earliest, latest},
    "restored": {"name", "ready"} | None, "previous": {"name", "until"} | None, plus "restored_phase" (why the restored cluster is
    not ready, else None) and "windows" ({server: firstRecoverabilityPoint}, for the restore command)}.
    The cluster is read only when `backup` is set and the database is not external. A read failure gives state `unknown` with
    `error` set."""
    roles = cluster_roles(system, db, state)
    row: dict = {"resource": db, "environment": env, "cluster": roles["active"], "restored": None,
                 "previous": roles["previous"], "restored_phase": None, "windows": {}}
    row["backup"] = {"last_success": None, "state": "off", "archiving": None, "error": None, "earliest": None, "latest": None}
    if external:
        row["backup"]["state"] = "external"
        return row
    if not backup:
        return row
    ns = f"{system}-{env}"
    b = row["backup"]
    try:
        active = get_json(["clusters.postgresql.cnpg.io", roles["active"], "-n", ns], context)
        arch = _cond(active, "ContinuousArchiving")
        if arch:
            b["archiving"] = "ok" if arch.get("status") == "True" else "failing"
            if b["archiving"] == "failing":
                b["error"] = arch.get("message") or "continuous archiving is failing"
        backups = database_backups(system, db, ns, roles["all"], context)
        done = _finished(backups)
        completed = [x for x in done if (x.get("status") or {}).get("phase") == "completed"]
        if completed:
            b["last_success"] = norm_time((completed[0].get("status") or {}).get("stoppedAt")) or norm_time(
                completed[0]["metadata"].get("creationTimestamp"))
        mine = [x for x in done if _of(x, roles["active"])]
        failed_mine = [x for x in mine if _phase(x) == "failed"]
        only_plugin = bool(failed_mine) and len(failed_mine) == len(mine) and all(_plugin_failure(x) for x in failed_mine)
        pending = only_plugin and b["archiving"] != "failing" and not completed
        if pending:
            failing_backup = False
        elif done and (done[0].get("status") or {}).get("phase") == "failed":
            b["error"] = b["error"] or (done[0].get("status") or {}).get("error") or "the last base backup failed"
            failing_backup = True
        else:
            failing_backup = False
        row["windows"] = _windows(system, db, ns, context)
        firsts = [d for d in map(parse_time, row["windows"].values()) if d]
        if firsts:
            b["earliest"] = fmt_time(min(firsts))
            b["latest"] = _latest(active, ns, context)
        b["state"] = "failing" if b["archiving"] == "failing" or failing_backup else "pending" if pending else "ok"
        if roles["restored"]:
            r = get_json(["clusters.postgresql.cnpg.io", roles["restored"], "-n", ns], context)
            row["restored"] = {"name": roles["restored"], "ready": cluster_ready(r)}
            row["restored_phase"] = None if cluster_ready(r) else cluster_phase(r)
    except ReadError as e:
        b.update({"state": "unknown", "error": str(e), "last_success": None, "archiving": None, "earliest": None, "latest": None})
        row["restored"] = None
    return row


def _windows(system: str, db: str, ns: str, context: str | None) -> dict:
    """{server name: firstRecoverabilityPoint} of the database's ObjectStore (RFC 3339 UTC)."""
    store = get_json(["objectstores.barmancloud.cnpg.io", f"{system}-{db}", "-n", ns], context)
    win = (store.get("status") or {}).get("serverRecoveryWindow") or {}
    out = {}
    for server, w in win.items():
        first = norm_time((w or {}).get("firstRecoverabilityPoint")) if isinstance(w, dict) else None
        if first:
            out[server] = first
    return out


def _latest(active: dict, ns: str, context: str | None) -> str | None:
    """`last_archived_time` of pg_stat_archiver on the active primary; None when it cannot be read."""
    primary = (active.get("status") or {}).get("currentPrimary")
    if not primary:
        return None
    sql = "select last_archived_time from pg_stat_archiver"
    rc, out, _ = _k(["exec", "-n", ns, str(primary), "-c", "postgres", "--", "psql", "-U", "postgres", "-At", "-c", sql], context)
    return norm_time(out.strip()) if rc == 0 else None


def restore_points(row: dict) -> dict:
    """{"earliest", "latest"} of a `database_state` row (both None without a restore point)."""
    return {"earliest": row["backup"]["earliest"], "latest": row["backup"]["latest"]}


def source_server(row: dict, state: dict | None, when: str, system: str, db: str) -> str | None:
    """The newest server name whose window [firstRecoverabilityPoint, until or latest] contains `when` (an RFC 3339 UTC time, or
    `latest` for the active cluster's own server). None when no server covers it."""
    roles = cluster_roles(system, db, state)
    if when == "latest":
        return roles["active"]
    t = parse_time(when)
    latest = parse_time(row["backup"]["latest"])
    untils = {c["name"]: parse_time(c.get("until")) for c in (state or {}).get("clusters") or [] if c["role"] == "previous"}
    best = None
    for server, first in row["windows"].items():
        lo = parse_time(first)
        hi = untils.get(server) or latest
        if t and lo and hi and lo <= t <= hi:
            n = int(GEN.search(server).group(1)) if GEN.search(server) else 0
            if best is None or n > best[0]:
                best = (n, server)
    return best[1] if best else None


# ---------------- environments (Velero) ----------------

def velero_state(b: dict) -> str:
    return {"Completed": "completed", "PartiallyFailed": "partially failed", "Failed": "failed",
            "FailedValidation": "failed"}.get((b.get("status") or {}).get("phase"), "in progress")


def velero_backups(system: str, env: str, context: str | None) -> list[dict]:
    """The Velero Backups of the environment's schedule (`velero.io/schedule-name=<system>-<env>`), newest first:
    {"name", "time" (RFC 3339 UTC | None), "state" (completed | partially failed | failed | in progress), "phase", "errors",
    "reason" (failureReason, else `<n> errors` for partially failed, else None)}. ReadError when the cluster cannot be read."""
    items = get_items(["backups.velero.io", "-n", VELERO_NS, "-l", f"velero.io/schedule-name={system}-{env}"], context)
    out = []
    for b in items:
        st = b.get("status") or {}
        state = velero_state(b)
        errors = int(st.get("errors") or 0)
        reason = st.get("failureReason") or (f"{errors} errors" if state == "partially failed" else None)
        when = _when(b, ("status", "completionTimestamp"), ("metadata", "creationTimestamp"))
        out.append({"name": b["metadata"]["name"], "time": fmt_time(when) if when else None, "state": state,
                    "phase": st.get("phase") or "New", "errors": errors, "reason": reason, "_at": when or _MIN})
    out.sort(key=lambda x: x["_at"], reverse=True)
    for x in out:
        del x["_at"]
    return out


def environment_state(system: str, env: str, context: str | None, *, backup: bool) -> dict:
    """The status row of an environment (AC-117.18/.27): {"environment", "backup": {last_success, state, reason, kept}}.
    `state`: off | never | completed | partially failed | failed | unknown (then `reason` says why)."""
    b: dict = {"last_success": None, "state": "off", "reason": None, "kept": 0}
    row = {"environment": env, "backup": b}
    if not backup:
        return row
    try:
        backups = velero_backups(system, env, context)
    except ReadError as e:
        b.update({"state": "unknown", "reason": str(e)})
        return row
    b["kept"] = len(backups)
    finished = [x for x in backups if x["state"] != "in progress"]
    done = [x for x in finished if x["state"] == "completed"]
    b["last_success"] = done[0]["time"] if done else None
    if finished:
        b["state"], b["reason"] = finished[0]["state"], finished[0]["reason"] if finished[0]["state"] != "completed" else None
    else:
        b["state"] = "never"
    return row


def pod_volume_backups(backup: str, context: str | None) -> list[dict]:
    """The PodVolumeBackups of a Velero Backup: {"pod", "namespace", "volume", "kind", "workload"} (kind/workload from the tags,
    None when absent). ReadError when the cluster cannot be read."""
    items = get_items(["podvolumebackups.velero.io", "-n", VELERO_NS, "-l", f"velero.io/backup-name={backup}"], context)
    out = []
    for i in items:
        spec = i.get("spec") or {}
        pod = spec.get("pod") or {}
        tags = spec.get("tags") or {}
        out.append({"pod": pod.get("name"), "namespace": pod.get("namespace"), "volume": spec.get("volume"),
                    "kind": tags.get("kind"), "workload": tags.get("workload")})
    return out


def existing_volumes(backup: str, ns: str, context: str | None) -> list[dict]:
    """The volumes of `backup` that still exist in `ns`: [{"pvc", "kind", "workload", "pod", "volume"}], sorted by pvc. A volume
    exists when a live pod of the same workload (same name as the backed-up pod, or owned by the workload) mounts a PVC under the
    same volume name, or the StatefulSet PVC `<volume>-<pod>` exists."""
    pvbs = [p for p in pod_volume_backups(backup, context) if p["volume"] and p["pod"]]
    if not pvbs:
        return []
    pods = get_items(["pods", "-n", ns], context)
    pvcs = {i["metadata"]["name"] for i in get_items(["persistentvolumeclaims", "-n", ns], context)}
    found: dict[str, dict] = {}
    for p in pvbs:
        claim = None
        for pod in pods:
            same = pod["metadata"]["name"] == p["pod"] or any(o.get("name") == p["workload"] for o in pod["metadata"].get("ownerReferences") or [])
            if not same:
                continue
            for v in (pod.get("spec") or {}).get("volumes") or []:
                if v.get("name") == p["volume"] and (v.get("persistentVolumeClaim") or {}).get("claimName"):
                    claim = v["persistentVolumeClaim"]["claimName"]
        if claim is None and f"{p['volume']}-{p['pod']}" in pvcs:
            claim = f"{p['volume']}-{p['pod']}"
        if claim:
            found[claim] = {"pvc": claim, "kind": p["kind"] or "Pod", "workload": p["workload"] or p["pod"], "pod": p["pod"], "volume": p["volume"]}
    return [found[k] for k in sorted(found)]


def workload_root(kind: str, name: str, ns: str, context: str | None, *, depth: int = 6) -> dict:
    """The top of the owner references of a workload (e.g. the `Seaweed` of a bucket store): {"kind", "name", "api_version"}.
    The workload itself when nothing owns it or the owner cannot be read."""
    cur = {"kind": kind, "name": name, "api_version": None}
    for _ in range(depth):
        try:
            obj = get_json([_resource(cur), cur["name"], "-n", ns], context)
        except ReadError:
            break
        cur["api_version"] = obj.get("apiVersion") or cur["api_version"]
        owners = (obj.get("metadata") or {}).get("ownerReferences") or []
        owner = next((o for o in owners if o.get("controller")), owners[0] if owners else None)
        if not owner or not owner.get("kind") or not owner.get("name"):
            break
        cur = {"kind": owner["kind"], "name": owner["name"], "api_version": owner.get("apiVersion")}
    return cur


def _resource(w: dict) -> str:
    group = (w.get("api_version") or "").partition("/")[0] if "/" in (w.get("api_version") or "") else ""
    base = w["kind"].lower()
    return f"{base}.{group}" if group else base


# ---------------- failing backups for the alert poll ----------------

def database_failing_since(system: str, db: str, env: str, context: str | None, now: datetime.datetime, *,
                           state: dict | None = None, min_age: datetime.timedelta = ONE_HOUR) -> list[dict]:
    """Failures of a database backup older than `min_age` (AC-117.28): [{"rule": "archiving"|"backup", "since", "error"}].
    archiving: ContinuousArchiving False since a time before `now - min_age`; backup: the newest Backup of ScheduledBackup
    `<system>-<db>` failed and none completed after the first such failure, which is older than `min_age`. ReadError on kubectl
    failure."""
    ns, roles = f"{system}-{env}", cluster_roles(system, db, state)
    out = []
    active = get_json(["clusters.postgresql.cnpg.io", roles["active"], "-n", ns], context)
    arch = _cond(active, "ContinuousArchiving")
    if arch and arch.get("status") == "False":
        since = parse_time(arch.get("lastTransitionTime"))
        if since and now - since > min_age:
            out.append({"rule": "archiving", "since": fmt_time(since), "error": arch.get("message") or "continuous archiving is failing"})
    sched = get_items(["backups.postgresql.cnpg.io", "-n", ns, "-l", f"cnpg.io/scheduled-backup={system}-{db}"], context)
    if not any(_phase(b) == "completed" and _of(b, roles["active"]) for b in get_items(["backups.postgresql.cnpg.io", "-n", ns], context)):
        sched = [b for b in sched if not (_phase(b) == "failed" and _plugin_failure(b))]  # the first backup is pending, not failing
    done = _finished(sched)
    run = []
    for b in done:
        if (b.get("status") or {}).get("phase") != "failed":
            break
        run.append(b)
    if run:
        since = _stopped(run[-1])
        if since and now - since > min_age:
            out.append({"rule": "backup", "since": fmt_time(since), "error": (run[0].get("status") or {}).get("error") or "the scheduled backup failed"})
    return out


def environment_failing_since(system: str, env: str, context: str | None, now: datetime.datetime, *,
                              min_age: datetime.timedelta = ONE_HOUR) -> dict | None:
    """{"since", "error"} when the newest Velero Backup of the schedule is Failed or PartiallyFailed and none completed since the
    first such one, which is older than `min_age`; else None. ReadError on kubectl failure."""
    finished = [b for b in velero_backups(system, env, context) if b["state"] != "in progress"]
    run = []
    for b in finished:
        if b["state"] == "completed":
            break
        run.append(b)
    if not run:
        return None
    since = parse_time(run[-1]["time"])
    if since and now - since > min_age:
        return {"since": fmt_time(since), "error": run[0]["reason"] or run[0]["state"]}
    return None
