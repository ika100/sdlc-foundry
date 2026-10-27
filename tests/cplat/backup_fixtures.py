"""Shared helpers of the spec 117 acceptance tests (not a test module, never collected).

Contract: docs/specs/117-.../design.md. Builds systems with backed-up databases and environments on top of resources_fixtures,
a hand-built gitops checkout (git repo + the template's renderer), and `FakeKube`, an in-memory cluster that replaces the one kubectl
seam of `backupstate` (design: "Seam `kubectl(args, context) -> (rc, out, err)`"). Nothing here touches the network or a cluster.

Assumptions about the seam (the design fixes the signature, not every query): reads are `kubectl get <kind> [name] [-n NS] [-l SEL]
-o json`; objects are written with stdin or a file; `exec` returns the `last_archived_time` of `pg_stat_archiver` as an RFC 3339
text; every other verb is recorded and succeeds."""
import copy
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

from resources_fixtures import APP, comp, db, system
from system_fixtures import RENDER5, git, init_git, render, write_system

P = "applications/shop/system.yaml: "
PLUGIN = "barman-cloud.cloudnative-pg.io"
S3 = {"endpoint": "https://s3.eu-central-1.amazonaws.com", "bucket": "acme-backups", "region": "eu-central-1", "forcePathStyle": False}
WRITE_VERBS = ("create", "apply", "delete", "patch", "annotate", "replace", "label", "scale", "rollout", "cordon", "drain")


def bucket(**kw) -> dict:
    return {"type": "bucket", **kw}


def bdoc(dbb=None, envb=None, bucket_kw=None, db_kw=None, comps=None, resources=None) -> dict:
    """orders-db (every environment) and the in-cluster bucket `backups`, both used by `api` everywhere. `dbb` is {env: backup}
    for the database's instances, `envb` {env: backup} for the environments."""
    db_kw = dict(db_kw or {})
    if dbb:
        db_kw["instances"] = {e: {**db_kw.get("instances", {}).get(e, {}), "backup": copy.deepcopy(b)} for e, b in dbb.items()}
    res = {"orders-db": db(**db_kw), "backups": bucket(**(bucket_kw or {}))}
    res.update(resources or {})
    doc = system(res, comps if comps is not None else {"api": comp("api", ["orders-db", "backups"])})
    for e, b in (envb or {}).items():
        doc["environments"][e]["backup"] = copy.deepcopy(b)
    return doc


def ext_prod_bucket(**kw) -> dict:
    """An in-cluster `backups` bucket in dev and staging, an external one (with remote.s3) in prod."""
    return {"instances": {"prod": {"external": True, "remote": {"s3": dict(S3)}}}, **kw}


def objs(root, env="dev", name="orders-db") -> Path:
    return Path(root) / APP / "addons" / env / name


def state_path(root, env="dev", name="orders-db") -> Path:
    return objs(root, env, name) / "restore-state.yaml"


FROM = {"server": "shop-orders-db", "to": "2026-10-27T09:59:00Z"}


def restored_state(to="2026-10-27T09:59:00Z") -> dict:
    return {"next": 2, "clusters": [{"name": "shop-orders-db", "role": "active"},
                                    {"name": "shop-orders-db-g1", "role": "restored", "from": {"server": "shop-orders-db", "to": to}}]}


def switched_state(to="2026-10-27T09:59:00Z") -> dict:
    return {"next": 2, "clusters": [{"name": "shop-orders-db", "role": "previous", "until": "2026-10-27T11:02:13Z"},
                                    {"name": "shop-orders-db-g1", "role": "active", "from": {"server": "shop-orders-db", "to": to}}]}


def write_state(root, state, env="dev", name="orders-db") -> Path:
    p = state_path(root, env, name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# Written by `cplat resource restore` (spec 117). render.py reads it; do not edit it by hand.\n" + yaml.safe_dump(state, sort_keys=False))
    return p


def rerender(root, doc=None) -> subprocess.CompletedProcess:
    if doc is not None:
        write_system(root, doc)
    return render(root)


def make_repo(tmp_path, doc) -> Path:
    """A committed gitops checkout (renderer, answers, first render). The first render is not asserted, so a missing renderer
    feature fails the test that needs it and not the setup."""
    write_system(tmp_path, "# the shop system (keep this comment)\n" + yaml.safe_dump(doc, sort_keys=False))
    (tmp_path / "scripts").mkdir(exist_ok=True)
    shutil.copy(RENDER5, tmp_path / "scripts" / "render.py")
    (tmp_path / ".copier-answers.yml").write_text("github_org: acme\napp_name: shop\nproject_name: shop-gitops\n")
    subprocess.run([sys.executable, "scripts/render.py"], cwd=tmp_path, capture_output=True, text=True)
    return init_git(tmp_path)


def head(repo) -> str:
    return git(repo, "rev-parse", "HEAD").strip()


def tree_state(repo) -> tuple:
    """(HEAD, porcelain status): equal before and after a command that changed nothing."""
    return head(repo), git(repo, "status", "--porcelain")


# ---------------- cluster objects ----------------

def meta(name, ns, **extra) -> dict:
    return {"name": name, "namespace": ns, "creationTimestamp": extra.pop("created", "2026-10-27T00:00:00Z"), **extra}


def cnpg_cluster(name="shop-orders-db", ns="shop-dev", ready=True, archiving="ok", archiving_since="2026-10-27T01:00:00Z", error="WAL archive check failed",
                 message="") -> dict:
    conds = [{"type": "Ready", "status": "True" if ready else "False", "message": message, "lastTransitionTime": "2026-10-27T00:00:00Z"}]
    if archiving is not None:
        conds.append({"type": "ContinuousArchiving", "status": "True" if archiving == "ok" else "False",
                      "message": "Continuous archiving is working" if archiving == "ok" else error, "lastTransitionTime": archiving_since})
    return {"apiVersion": "postgresql.cnpg.io/v1", "kind": "Cluster", "metadata": meta(name, ns),
            "status": {"phase": "Cluster in healthy state" if ready else (message or "Setting up primary"), "conditions": conds,
                       "currentPrimary": f"{name}-1"}}


def cnpg_backup(name, cluster="shop-orders-db", ns="shop-dev", phase="completed", stopped="2026-10-27T03:00:12Z", error=None, created=None,
                scheduled=True) -> dict:
    """A Backup of CloudNativePG; scheduled ones carry the label CloudNativePG puts on the Backups of a ScheduledBackup."""
    st = {"phase": phase, "stoppedAt": stopped}
    if error:
        st["error"] = error
    labels = {"cnpg.io/scheduled-backup": cluster.split("-g")[0]} if scheduled else {}
    return {"apiVersion": "postgresql.cnpg.io/v1", "kind": "Backup", "metadata": meta(name, ns, created=created or stopped or "2026-10-27T03:00:00Z", labels=labels),
            "spec": {"cluster": {"name": cluster}, "method": "plugin"}, "status": st}


def objectstore(windows: dict | None, name="shop-orders-db", ns="shop-dev") -> dict:
    st = {"serverRecoveryWindow": {s: {"firstRecoverabilityPoint": first, "lastSuccessfulBackupTime": first} for s, first in (windows or {}).items()}}
    return {"apiVersion": "barmancloud.cnpg.io/v1", "kind": "ObjectStore", "metadata": meta(name, ns), "status": st}


def velero_backup(name, env="dev", phase="Completed", done="2026-10-27T03:00:40Z", errors=0, reason=None, schedule=None) -> dict:
    st = {"phase": phase, "errors": errors}
    if done:
        st["completionTimestamp"] = done
    if reason:
        st["failureReason"] = reason
    return {"apiVersion": "velero.io/v1", "kind": "Backup",
            "metadata": meta(name, "velero", created=done or "2026-10-27T03:00:00Z", labels={"velero.io/schedule-name": schedule or f"shop-{env}"}), "status": st}


def argo_app(name="addon-orders-db-dev", revision="abc", sync="Synced") -> dict:
    return {"apiVersion": "argoproj.io/v1alpha1", "kind": "Application", "metadata": meta(name, "argocd"),
            "status": {"sync": {"status": sync, "revision": revision}, "health": {"status": "Healthy"}}}


def pod_volume_backup(backup, pod, volume, ns="shop-dev", kind="StatefulSet", workload="files") -> dict:
    return {"apiVersion": "velero.io/v1", "kind": "PodVolumeBackup",
            "metadata": meta(f"{backup}-{pod}-{volume}", "velero", labels={"velero.io/backup-name": backup}),
            "spec": {"pod": {"kind": "Pod", "name": pod, "namespace": ns}, "volume": volume, "tags": {"kind": kind, "workload": workload}},
            "status": {"phase": "Completed"}}


# ---------------- the fake cluster ----------------

def kind_key(args: list[str]) -> str:
    """The kind of a `get`-like call, normalised: backup is cnpg.backup or velero.backup by group or namespace."""
    token = args[1].split("/")[0].lower()
    base, _, group = token.partition(".")
    if base.endswith("ies"):
        base = base[:-3] + "y"
    elif base.endswith("s") and not base.endswith("ss"):
        base = base[:-1]
    base = {"persistentvolumeclaim": "pvc", "statefulset": "statefulset", "sts": "statefulset", "deploy": "deployment"}.get(base, base)
    ns = _opt(args, "-n", "--namespace")
    if base == "backup":
        return "velero.backup" if ("velero" in group or (not group and ns == "velero")) else "cnpg.backup"
    if base == "restore" and ("velero" in group or ns == "velero"):
        return "velero.restore"
    return base


def _opt(args, *names):
    for i, a in enumerate(args):
        if a in names and i + 1 < len(args):
            return args[i + 1]
        for n in names:
            if a.startswith(n + "=") and n.startswith("--"):
                return a.split("=", 1)[1]
    return None


class FakeKube:
    """Replaces `backupstate.kubectl(args, context)`. `store[kind]` is a list of objects; `calls` records every call as
    (args, context, stdin text or None). `auto` maps a kind to the status given to a freshly created object of that kind."""

    def __init__(self):
        self.store: dict[str, list[dict]] = {}
        self.calls: list[tuple[list[str], str | None, str | None]] = []
        self.auto: dict[str, dict] = {}
        self.error: tuple[int, str] | None = None          # every call fails with this (the cluster is unreadable)
        self.wait_rc = 0
        self.pg_latest = "2026-10-27T10:41:02Z"
        self.on_apply_k = None
        self.hooks: list = []                               # callables (args, stdin) -> (rc, out, err) | None

    # ---- setup
    def put(self, kind, *objs_):
        self.store.setdefault(kind, []).extend(copy.deepcopy(list(objs_)))
        return self

    def healthy_database(self, windows=None, backups=(), cluster="shop-orders-db", **cl):
        self.put("cluster", cnpg_cluster(cluster, **cl))
        self.put("objectstore", objectstore({"shop-orders-db": "2026-09-27T03:00:12Z"} if windows is None else windows))
        self.put("cnpg.backup", *backups)
        return self

    # ---- seam
    def __call__(self, args, context=None, *a, **kw):
        args = [str(x) for x in args]
        stdin = kw.get("input") or kw.get("stdin") or kw.get("data")
        if isinstance(stdin, bytes):
            stdin = stdin.decode()
        for i, x in enumerate(args):
            if x in ("-f", "--filename", "-k") and i + 1 < len(args) and args[i + 1] != "-" and os.path.isfile(args[i + 1]):
                stdin = (stdin or "") + Path(args[i + 1]).read_text()
        self.calls.append((args, context, stdin))
        if self.error:
            return self.error[0], "", self.error[1]
        for h in self.hooks:
            got = h(args, stdin)
            if got is not None:
                return got
        verb = args[0] if args else ""
        if verb == "get" and len(args) > 1:
            return self._get(args)
        if verb == "exec":
            return 0, self.pg_latest + "\n", ""
        if verb == "wait":
            return self.wait_rc, "", "timed out waiting for the condition" if self.wait_rc else ""
        if verb in ("create", "apply") and stdin and "-k" not in args:
            for d in yaml.safe_load_all(stdin):
                self._created(d)
        if verb == "apply" and "-k" in args and self.on_apply_k:
            self.on_apply_k(self, args)
        return 0, "", ""

    def _created(self, d):
        if not isinstance(d, dict) or "kind" not in d:
            return
        key = {"Backup": "velero.backup" if d.get("apiVersion", "").startswith("velero") else "cnpg.backup", "Restore": "velero.restore",
               "Cluster": "cluster"}.get(d["kind"], d["kind"].lower())
        d = copy.deepcopy(d)
        d.setdefault("status", {}).update(self.auto.get(key, {}))
        self.store.setdefault(key, []).append(d)

    def _get(self, args):
        key = kind_key(args)
        ns = _opt(args, "-n", "--namespace")
        items = [o for o in self.store.get(key, []) if ns is None or o["metadata"].get("namespace") in (ns, None) or "-A" in args]
        sel = _opt(args, "-l", "--selector")
        if sel:
            for pair in sel.split(","):
                k, _, v = pair.partition("=")
                items = [o for o in items if o["metadata"].get("labels", {}).get(k) == v]
        name = next((a for a in args[2:] if not a.startswith("-") and a not in (ns, sel, _opt(args, "-o")) and "/" not in a), None)
        if "/" in args[1]:
            name = args[1].split("/", 1)[1]
        if name:
            hit = [o for o in items if o["metadata"]["name"] == name]
            if not hit:
                return 1, "", f'Error from server (NotFound): {key} "{name}" not found'
            return 0, json.dumps(hit[0]), ""
        return 0, json.dumps({"apiVersion": "v1", "kind": "List", "items": items}), ""

    # ---- inspection
    def writes(self) -> list[list[str]]:
        return [c[0] for c in self.calls if c[0] and c[0][0] in WRITE_VERBS]

    def created(self, kind) -> list[dict]:
        out = []
        for args, _, stdin in self.calls:
            if args and args[0] in ("create", "apply") and stdin:
                out += [d for d in yaml.safe_load_all(stdin) if isinstance(d, dict) and d.get("kind") == kind]
        return out

    def text(self) -> str:
        return "\n".join(" ".join(c[0]) + ("\n" + c[2] if c[2] else "") for c in self.calls)

    def used(self, *needles) -> bool:
        t = self.text()
        return all(n in t for n in needles)


@pytest.fixture()
def kube(monkeypatch):
    """`backupstate.kubectl` replaced by a FakeKube. While scripts/cplat/backupstate.py does not exist nothing is patched, so each
    test fails on its own assertion and not in the fixture."""
    import importlib
    fake = FakeKube()
    try:
        bs = importlib.import_module("backupstate")
    except ModuleNotFoundError:
        return fake
    monkeypatch.setattr(bs, "kubectl", fake, raising=False)
    return fake


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def sleep(self, s):
        self.now += s

    def time(self):
        return self.now


@pytest.fixture()
def clock(monkeypatch):
    """Time does not pass by itself: sleeping advances it, so a 30 minute wait costs no real time."""
    c = Clock()
    monkeypatch.setattr(time, "sleep", c.sleep)
    monkeypatch.setattr(time, "monotonic", c.time)
    monkeypatch.setattr(time, "time", c.time)
    return c


def run_cplat(*argv, capsys):
    import cplat
    rc = cplat.main([*map(str, argv)])
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def prod_confirm_text(out_err: str) -> bool:
    return "nothing was changed: add --confirm prod to do it" in out_err
