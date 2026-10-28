"""Verification of a resource upgrade step (spec 121, design.md "Contract: verification").

`verify` waits up to 15 minutes for the resource to be healthy at the environment's pin, checks the connection Secrets, runs the smoke
tests of the components that use it, writes the record ConfigMap `<system>-<n>-upgrade` (also on failure) and, after a database major
with a backup, starts the first base backup of the new archive. `run` is what `cplat resource upgrade --verify` and `--wait` call: it
prints the verified / NOT VERIFIED block, starts the staging step after a verified dev step with `promote: after-dev-smoke`, and
returns the exit code. Seams: `backupstate.kubectl`, `smoke.run_smoke` / `smoke.liveness_probe`, `time.sleep` / `time.monotonic`."""
from __future__ import annotations

import argparse
import contextlib
import datetime
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import backupstate
import core
import gitops
import model
import smoke
import status
import yaml
from core import PlatformError

ENVS = list(model.ENVIRONMENTS)
WAIT_S = 900.0
POLL_S = 10.0
PROGRESS_S = 60.0
CONTAINERS = {"cache": "valkey", "broker": "nats"}


class RecordError(backupstate.ReadError):
    """The verification record of an environment could not be read from the cluster."""


@dataclass
class Result:
    ok: bool
    resource: str
    env: str
    major: object
    image: str
    check: str = ""
    lines: list[str] = field(default_factory=list)    # the block, header first
    record: dict = field(default_factory=dict)
    next: str | None = None
    auto_staging: bool = False


# ---------------- record ----------------

def read_record(system: str, resource: str, env: str, context: str | None) -> dict | None:
    """The record's data, None when there is none, RecordError when the cluster cannot be read."""
    try:
        doc = backupstate.get_json(["configmap", f"{system}-{resource}-upgrade", "-n", f"{system}-{env}"], context)
    except backupstate.ReadError as e:
        if "notfound" in str(e).lower().replace(" ", "") or "not found" in str(e).lower():
            return None
        raise RecordError(str(e)) from e
    return doc.get("data") or {}


def now_text() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_record(system: str, resource: str, env: str, context: str | None, data: dict) -> str | None:
    """Apply the ConfigMap; the reason when kubectl failed."""
    doc = {"apiVersion": "v1", "kind": "ConfigMap",
           "metadata": {"name": f"{system}-{resource}-upgrade", "namespace": f"{system}-{env}",
                        "labels": {"app.kubernetes.io/name": resource, "app.kubernetes.io/part-of": system,
                                   "app.kubernetes.io/managed-by": "cplat"}},
           "data": data}
    rc, out, err = backupstate.kubectl(["apply", "-f", "-"], context, input=yaml.safe_dump(doc, sort_keys=False))
    return None if rc == 0 else backupstate._why(rc, err, out)


# ---------------- health readers ----------------

def _int(v: object) -> int:
    return v if isinstance(v, int) else 0


def database_health(system: str, resource: str, env: str, context: str | None, active: str, pin: str, major: object) -> tuple[bool, str]:
    ns = f"{system}-{env}"
    try:
        c = backupstate.get_json(["clusters.postgresql.cnpg.io", active, "-n", ns], context)
    except backupstate.ReadError as e:
        return False, f"cannot read {active}: {e}"
    st, spec = c.get("status") or {}, c.get("spec") or {}
    phase = st.get("phase") or "no phase"
    want, ready = _int(spec.get("instances")), _int(st.get("readyInstances"))
    counts = f"{phase}, {ready}/{want} ready"
    info = st.get("pgDataImageInfo") or {}
    if st.get("image") != pin:
        return False, f"{counts}, still on image {st.get('image') or 'unknown'}"
    if info.get("majorVersion") is not None and str(info["majorVersion"]) != str(major):
        return False, f"{counts}, data on major {info['majorVersion']}"
    if phase != "Cluster in healthy state" or ready != want or want == 0:
        return False, counts
    return True, counts


def statefulset_health(system: str, resource: str, env: str, context: str | None, typ: str, pin: str) -> tuple[bool, str]:
    name = f"{system}-{resource}"
    try:
        s = backupstate.get_json(["statefulsets.apps", name, "-n", f"{system}-{env}"], context)
    except backupstate.ReadError as e:
        return False, f"cannot read {name}: {e}"
    st, spec = s.get("status") or {}, s.get("spec") or {}
    want, ready, updated = _int(spec.get("replicas")), _int(st.get("readyReplicas")), _int(st.get("updatedReplicas"))
    counts = f"{ready}/{want} ready"
    containers = ((spec.get("template") or {}).get("spec") or {}).get("containers") or []
    image = next((c.get("image") for c in containers if c.get("name") == CONTAINERS[typ]), None)
    if image != pin:
        return False, f"{counts}, still on image {image or 'unknown'}"
    if st.get("currentRevision") != st.get("updateRevision"):
        return False, f"{counts}, rollout to {st.get('updateRevision')} running"
    if not (ready == updated == want) or want == 0:
        return False, f"{counts}, {updated} updated"
    return True, counts


def check_health(typ: str, system: str, resource: str, env: str, context: str | None, active: str, pin: str, major: object) -> tuple[bool, str]:
    if typ == "database":
        return database_health(system, resource, env, context, active, pin, major)
    return statefulset_health(system, resource, env, context, typ, pin)


def health_state(typ: str, system: str, resource: str, env: str, context: str | None, active: str | None = None) -> str:
    """`healthy`, `upgrading` (a CNPG phase starting "Upgrading", or a StatefulSet rollout), `degraded` (fewer ready than wanted) or
    `unknown` (not readable). For `cplat system status`."""
    try:
        if typ == "database":
            c = backupstate.get_json(["clusters.postgresql.cnpg.io", active or f"{system}-{resource}", "-n", f"{system}-{env}"], context)
            st, spec = c.get("status") or {}, c.get("spec") or {}
            if str(st.get("phase") or "").startswith("Upgrading"):
                return "upgrading"
            return "degraded" if _int(st.get("readyInstances")) < _int(spec.get("instances")) else "healthy"
        if typ in CONTAINERS:
            s = backupstate.get_json(["statefulsets.apps", f"{system}-{resource}", "-n", f"{system}-{env}"], context)
            st, spec = s.get("status") or {}, s.get("spec") or {}
            if st.get("currentRevision") != st.get("updateRevision"):
                return "upgrading"
            return "degraded" if _int(st.get("readyReplicas")) < _int(spec.get("replicas")) else "healthy"
    except backupstate.ReadError:
        pass
    return "unknown"


# ---------------- smoke ----------------

class SmokeSetupError(Exception):
    pass


def component_dir(comp: model.Component, inst: model.Instance, dirs: dict[str, str], tmp: Path) -> Path:
    if comp.name in dirs:
        return Path(dirs[comp.name])
    if not comp.repo:
        raise SmokeSetupError("no --component-dir and no repository")
    dest = tmp / comp.name
    tag = inst.tag
    extra: list[str] = []
    sha = None
    if tag and tag.startswith("sha-"):
        sha = tag[4:]
    elif tag and tag != "latest":
        extra = ["--branch", tag]
    try:
        core.run(["gh", "repo", "clone", comp.repo, str(dest), "--", "--depth", "1", *extra])
        if sha:
            core.run(["git", "fetch", "--depth", "1", "origin", sha], cwd=dest)
            core.run(["git", "checkout", "-q", "FETCH_HEAD"], cwd=dest)
    except PlatformError as e:
        raise SmokeSetupError(f"cannot clone {comp.repo}: {e}") from e
    if not dest.is_dir():
        raise SmokeSetupError(f"cloning {comp.repo} produced no directory")
    return dest


def run_component_smoke(m: model.Model, comp: model.Component, env: str, dirs: dict[str, str]) -> tuple[bool, str]:
    """(passed, "<n> passed" or the failure reason)."""
    inst = next((i for i in m.instances if i.component == comp.name and i.environment == env), None)
    if inst is None:
        return False, "no instance"
    # A component that is not exposed has no public URL: fall back to its Service (reachable only from inside the cluster; the
    # reachability probe then names the problem).
    url = m.url(comp.name, env)[0] or f"http://{comp.name}.{m.system}-{env}.svc.cluster.local"
    with tempfile.TemporaryDirectory(prefix="cplat-verify-") as tmp:
        try:
            path = component_dir(comp, inst, dirs, Path(tmp))
        except SmokeSetupError as e:
            return False, str(e)
        res = smoke.run_smoke(path, url, env=env, probe=smoke.liveness_probe(path))
    if res.ok:
        return True, f"{res.passed} passed"
    return False, "; ".join(res.failing) or res.reason or res.outcome


# ---------------- the verification ----------------

def contexts_list(contexts: dict[str, str]) -> list[str]:
    return [f"{e}={c}" for e, c in contexts.items()]


def last_backup_text(typ: str, repo: Path, app: str | None, resource: str, env: str, contexts: dict[str, str], backup: bool) -> str:
    if typ != "database":
        return f"none ({typ} has no backup)"
    if not backup:
        return "none (no backup is configured)"
    try:
        got = status.public_backups(status.collect_backups(repo, app, contexts_list(contexts)))
    except (backupstate.ReadError, backupstate.StateError) as e:
        return f"unreadable ({e})"
    entry = next((i for i in got["resource_instances"] if (i["resource"], i["environment"]) == (resource, env)), None)
    return ((entry or {}).get("backup") or {}).get("last_success") or "never"


def next_line(m: model.Model, cfgs_res: dict, env: str, resource: str, major: object, pin_of, promote: str | None) -> tuple[str, bool]:
    """(the `next:` text, whether staging follows by itself)."""
    for later in ENVS[ENVS.index(env) + 1:]:
        cfg = cfgs_res["envs"].get(later)
        if not any(ri.resource == resource and ri.environment == later for ri in m.resource_instances) or not cfg or cfg.get("external"):
            continue
        if cfg["version"] == major and cfg["pin"] == pin_of:
            continue
        if env == ENVS[0] and later == "staging" and promote == "after-dev-smoke":
            return "staging follows by itself (promote: after-dev-smoke)", True
        return f"/resource:upgrade {resource} --to {major} --env {later}", False
    return f"all environments are on {major}", False


def verify(repo: Path, app: str | None, resource: str, env: str, contexts: dict[str, str], component_dirs: dict[str, str]) -> Result:
    import upgrade
    repo = Path(repo).resolve()
    app_dir = gitops.find_app(repo, app)
    m = model.load_dir(app_dir)
    r = upgrade.load_renderer(repo)
    doc = yaml.safe_load((app_dir / "system.yaml").read_text()) or {}
    try:
        cfgs = r.validate_resources(doc, app_dir)
    except r.RenderError as e:
        raise PlatformError(f"applications/{app_dir.name}/system.yaml: {e}") from e
    res = next((x for x in m.resources if x.name == resource), None)
    if res is None:
        raise PlatformError(f"{resource} is not a resource of the system")
    if env not in ENVS:
        raise PlatformError(f"--env must be {', '.join(ENVS[:-1])} or {ENVS[-1]}")
    typ = res.type
    if typ not in ("database", "cache", "broker"):
        raise PlatformError(f"{resource} is a {typ}: only a database, cache or broker has an upgrade to verify")
    ris = {ri.environment: ri for ri in m.resource_instances if ri.resource == resource}
    if env not in ris:
        raise PlatformError(f"{resource} has no instance in {env} (no component that runs in {env} uses it)")
    cfg = cfgs[resource]
    env_cfg = cfg["envs"][env]
    if ris[env].external or env_cfg.get("external"):
        raise PlatformError(f"{resource} is external in {env}: its owner upgrades it, the platform does not")
    system, major, pin, ctx = m.system, env_cfg["version"], env_cfg["pin"], contexts.get(env)
    state = backupstate.restore_state(app_dir, env, resource) if typ == "database" else None
    active = backupstate.cluster_roles(system, resource, state)["active"] if typ == "database" else ""
    plan = upgrade.Plan(name=resource, type=typ, env=env, to=major, instances=ris)
    users = upgrade.users_of(m, plan)

    out: list[str] = []          # the ok lines
    progress: list[str] = []
    failed: str | None = None
    fail_line = ""

    # 1. health at the pin
    start = time.monotonic()
    next_progress = PROGRESS_S
    while True:
        ok, detail = check_health(typ, system, resource, env, ctx, active, pin, major)
        elapsed = time.monotonic() - start
        if ok:
            out.append(f"  ok   {resource} healthy on {major} after {int(elapsed) // 60}m{int(elapsed) % 60}s ({detail})")
            break
        if elapsed >= next_progress:
            progress.append(f"  waiting for {resource} in {env}: {detail} ({int(next_progress // 60)}m of 15m)")
            next_progress += PROGRESS_S
        if elapsed >= WAIT_S:
            failed = f"{resource} not healthy on {major} after 15 minutes"
            fail_line = f"  FAIL {failed} ({detail})"
            break
        time.sleep(POLL_S)

    # 2. connection Secrets
    if not failed:
        names = ([f"{system}-{resource}-{c}-app" for c in users] if typ == "broker" else [f"{system}-{resource}-app"])
        for name in names:
            try:
                backupstate.get_json(["secrets", name, "-n", f"{system}-{env}"], ctx)
            except backupstate.ReadError as e:
                failed = f"Secret {name}"
                fail_line = f"  FAIL Secret {name} is missing in {system}-{env} ({e})"
                break
            out.append(f"  ok   Secret {name} kept its name")

    # 3. smoke
    if not failed:
        comps = {c.name: c for c in m.components}
        for c in users:
            passed, text = run_component_smoke(m, comps[c], env, component_dirs)
            if not passed:
                failed = f"smoke {c} ({env})"
                fail_line = f"  FAIL smoke {c} ({env}): {text}"
                break
            out.append(f"  ok   smoke {c} ({env}): {text}")

    # 4. first base backup of the new archive: a database with a backup whose major has no verified record yet (a re-run does not take
    # another one); the result is not awaited
    backup_line = None
    if not failed and typ == "database" and ris[env].backup:
        try:
            before = read_record(system, resource, env, ctx)
            if not (before and before.get("state") == "verified" and before.get("major") == str(major)):
                stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%d%H%M%S")
                name = f"{active}-first-{stamp}"
                backupstate.create_backup(f"{system}-{env}", active, name, ctx)
                backup_line = f"first base backup of {active} on {major} started (Backup {name})"
        except backupstate.ReadError as e:
            backup_line = f"  warn the first base backup could not be started ({e})"

    data = {"major": str(major), "image": pin, "state": "failed" if failed else "verified", "at": now_text(), "check": failed or "",
            "release": core.platform_version()}
    wrote = write_record(system, resource, env, ctx, data)

    result = Result(ok=not failed, resource=resource, env=env, major=major, image=pin, check=failed or "", record=data)
    if failed:
        backup = last_backup_text(typ, repo, app, resource, env, contexts, bool(ris[env].backup))
        result.lines = [f"upgrade {resource} in {env}: NOT VERIFIED ({failed})", *progress, *out, fail_line, f"  last successful backup: {backup}"]
        if typ == "database":
            result.lines.append(f"  way back: /resource:restore {resource} --env {env} --to <time|latest>")
        result.lines.append(f"  no later environment is upgraded until {env} is verified")
    else:
        promote = ((doc.get("environments") or {}).get("staging") or {}).get("promote")
        nxt, auto = next_line(m, cfg, env, resource, major, pin, promote)
        result.next, result.auto_staging = nxt, auto
        result.lines = [f"upgrade {resource} in {env}: verified ({major}, {pin})", *progress, *out]
        if backup_line:
            result.lines.append(backup_line)
        result.lines.append(nxt if nxt.startswith("all ") else f"next: {nxt}")
    if wrote:
        result.lines.insert(1, f"  warn the record {system}-{resource}-upgrade was not written ({wrote})")
    return result


# ---------------- command ----------------

def parse_dirs(values: list[str] | None) -> dict[str, str]:
    out = {}
    for v in values or []:
        name, sep, path = v.partition("=")
        if not sep or not name or not path:
            raise PlatformError(f"--component-dir expects COMPONENT=DIR, got '{v}'")
        out[name] = path
    return out


def staging_argv(ns: argparse.Namespace, resource: str, major: object) -> list[str]:
    argv = [resource, "--to", str(major), "--env", "staging", "--repo-dir", str(ns.repo_dir)]
    if ns.app:
        argv += ["--app", ns.app]
    for c in ns.context or []:
        argv += ["--context", c]
    for c in ns.component_dir or []:
        argv += ["--component-dir", c]
    if ns.pr:
        argv.append("--pr")
    if getattr(ns, "wait", False):
        argv.append("--wait")
    return argv


def run(ns: argparse.Namespace, env: str | None = None, quiet: bool = False) -> int:
    """Verify `ns.name` in `env` (default `ns.env`), print the block (to stderr when `quiet`), start the staging step when the design says
    so, and return the exit code."""
    env = env or ns.env
    contexts = status.parse_contexts(ns.context, ENVS)
    result = verify(Path(ns.repo_dir), ns.app, ns.name, env, contexts, parse_dirs(ns.component_dir))
    stream = sys.stderr if quiet else sys.stdout
    for line in result.lines:
        print(line, file=stream)
    if not result.ok:
        return 1
    if result.auto_staging:
        import upgrade
        try:
            with contextlib.redirect_stdout(sys.stderr if quiet else sys.stdout):
                return upgrade.main(staging_argv(ns, ns.name, result.major))
        except PlatformError as e:
            print(f"the staging step was not started: {e}", file=stream)
            return 1
    return 0
