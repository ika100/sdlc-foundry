"""Shared helpers of the spec 121 acceptance tests (not a test module, never collected).

Contract: docs/specs/121-.../design.md. Spells out the designed versions table (tags and digests), maps the new engine image
references back to the pre-121 ones (`unpin`, the way t19 amends the byte-identity tests of specs 118-120), builds committed
gitops checkouts with an `origin` and a fake `gh` for `cplat resource upgrade --pr`, and fills the in-memory cluster of
backup_fixtures with the objects the upgrade guards and the verification read. Nothing here touches the network or a cluster."""
import datetime
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import yaml

from backup_fixtures import FakeKube, bdoc, cnpg_backup, cnpg_cluster, make_repo, meta, objectstore  # noqa: F401  (re-exported for the tests)
from resources_fixtures import APP, ENVS, comp, db, platform_render_module, system  # noqa: F401  (re-exported for the tests)
from system_fixtures import ROOT, git, render

P = "applications/shop/system.yaml: "
DEV = {"to": "backups"}
CTX = "k3d-shop-local"
SHA64 = r"sha256:[0-9a-f]{64}"

# ---------------- the designed versions table (design.md "Contract: the versions table") ----------------

PG = {
    15: "ghcr.io/cloudnative-pg/postgresql:15.19-202610260819-standard-trixie@sha256:f617efc030d3099362e7fca616bb6d83d102599abf9b7b5e225482e4d0306aa3",
    16: "ghcr.io/cloudnative-pg/postgresql:16.15-202610260820-standard-trixie@sha256:1ec419e997a8bde5263b6951f4c5ebc4aa2e1937927001f2561025c0a816e174",
    17: "ghcr.io/cloudnative-pg/postgresql:17.11-202610260819-standard-trixie@sha256:ed6923f9ba2399cf9070379a353c710c29ced8a294be73986a2c3dae7e599ce3",
    18: "ghcr.io/cloudnative-pg/postgresql:18.6-202610260820-standard-trixie@sha256:39add80f5b1e573e2f6b641c66fd1a2f8dede67ca0330e870285bc1078551390",
}
VK = {8: "valkey/valkey:8.1.11@sha256:8f836008e0986c36adf50da714c7060cf689dbb335f61fe077939d90fa650809",
      9: "valkey/valkey:9.1.3@sha256:3add1a336a920ea54770a001ab6feb3da5fceea96a40373a3a2cd469b815f0b7"}
NATS = {"2.14": "nats:2.14.9-alpine@sha256:127c5ccbc538a93f53ebb19461dc193130df386c2d6dab8199661a28a30d85bd",
        "2.15": "nats:2.15.2-alpine@sha256:823e7f1d6d8ffe3b30dbd73d4a06bbb939acf94929f7fdf224404da7a05bafb5"}
NATS_CHART = {"repo_url": "https://nats-io.github.io/k8s/helm/charts", "chart": "nats", "chart_version": "2.15.1"}
SEAWEED = "chrislusf/seaweedfs:4.51@sha256:f7a49e3f3972ebed5be2ed4befa4a0c68eb7bdddba6e692d42729ceb545134b8"
VELERO_PLUGIN = "velero/velero-plugin-for-aws:v1.14.4@sha256:c85a7fa803569e3128c33e4f5766f84ab156c8d171c9f1dd2715581d45ce98fa"
COLLECTOR = "otel/opentelemetry-collector-contrib:0.162.0@sha256:39923a8e431bd1f57be82411999d389fcfe40857492e4365456d97a4c1f74be6"
LGTM = "grafana/otel-lgtm:0.35.0@sha256:2de1094c593c671cbfca878a28ffcd7e46ff5e32f2ce966c0cf33003f6cf4266"
CLUSTER_PINS = {
    "argo-cd": {"version": "v3.4.12", "manifest": "https://raw.githubusercontent.com/argoproj/argo-cd/v3.4.12/manifests/install.yaml"},
    "k3s": {"image": "rancher/k3s:v1.32.5-k3s1@sha256:b75eac801bbc91b4584769c840f346683c7740d72f83e630088370f8e1eb2c8a"},
    "gateway-api": {"version": "v1.2.1", "manifest": "https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.2.1/standard-install.yaml"},
}
SUPPORTED_MAJORS = {"database": (16, 17, 18), "cache": (8, 9), "broker": ("2.14", "2.15")}
DEPRECATED_MAJORS = {"database": (15,)}
UPGRADE_PATHS = {"database": {15: (16, 17, 18), 16: (17, 18), 17: (18,), 18: ()},
                 "cache": {8: (9,), 9: ()}, "broker": {"2.14": ("2.15",), "2.15": ()}}
ROW_KEYS = ["name", "kind", "engine", "major", "status", "version", "ref", "digest", "app_version", "crds"]
IMAGE_ROWS = ["postgres 15", "postgres 16", "postgres 17", "postgres 18", "valkey 8", "valkey 9", "nats 2.14", "nats 2.15"]
OPERATOR_NAMES = ["cloudnative-pg", "seaweedfs", "external-secrets", "kyverno", "plugin-barman-cloud", "cert-manager", "velero", "nack", "keda",
                  "metrics-server"]
ROW_ORDER = [*IMAGE_ROWS, "nats", "seaweedfs", "opentelemetry-collector", "lgtm", "velero-plugin-for-aws", "argo-cd", "k3s", "gateway-api",
             *[f"operator {n}" for n in OPERATOR_NAMES]]

# the pre-121 reference of every new engine reference (the byte-identity tests compare after this mapping)
OLD_PG = {15: "ghcr.io/cloudnative-pg/postgresql:15.19", 16: "ghcr.io/cloudnative-pg/postgresql:16.15",
          17: "ghcr.io/cloudnative-pg/postgresql:17.11", 18: "ghcr.io/cloudnative-pg/postgresql:18.6"}
UNPIN = {**{PG[m]: OLD_PG[m] for m in PG}, **{ref: ref.split("@")[0] for ref in (*VK.values(), SEAWEED, VELERO_PLUGIN, COLLECTOR)},
         **{ref.split(":", 1)[1]: ref.split(":", 1)[1].split("@")[0] for ref in NATS.values()}}


def unpin(g: dict) -> dict:
    """Every designed reference of a rendered tree mapped back to what releases before 121 wrote (string replacement per file)."""
    out = {}
    for path, text in g.items():
        for new, old in UNPIN.items():
            text = text.replace(new, old)
        out[path] = text
    return out


def digest_of(ref: str) -> str:
    return ref.split("@", 1)[1]


# ---------------- systems ----------------

def upgrade_doc(version=16, backup=True, promote=None, instances=None, **top) -> dict:
    """orders-db (version `version`, backup to the in-cluster bucket `backups` in every environment) used by `api` everywhere."""
    inst = {e: ({"backup": dict(DEV)} if backup else {}) for e in ENVS}
    for env, conf in (instances or {}).items():
        inst[env] = {**inst.get(env, {}), **conf}
    doc = bdoc(db_kw={"version": version, "instances": inst}, **top)
    if promote:
        doc["environments"]["staging"]["promote"] = promote
    return doc


def put_system(repo: Path, doc: dict) -> None:
    (repo / APP / "system.yaml").write_text("# the shop system (keep this comment)\n" + yaml.safe_dump(doc, sort_keys=False))


def read_system(repo: Path, ref: str | None = None) -> dict:
    if ref:
        return yaml.safe_load(git(repo, "show", f"{ref}:{APP}/system.yaml"))
    return yaml.safe_load((repo / APP / "system.yaml").read_text())


def commit_all(repo: Path, message: str = "x") -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "--allow-empty", "-m", message)


def rerender_commit(repo: Path, doc: dict) -> None:
    put_system(repo, doc)
    p = render(repo)
    assert p.returncode == 0, p.stdout + p.stderr
    commit_all(repo, "state")


def cluster_file(repo: Path, env: str, name: str = "orders-db", file: str = "cluster.yaml") -> dict:
    return yaml.safe_load((repo / APP / "addons" / env / name / file).read_text())


# ---------------- a repository with an origin and a fake gh ----------------

GH_SCRIPT = """#!{python}
import json, os, sys
with open(os.environ["GH_LOG"], "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
if sys.argv[1:3] == ["pr", "create"]:
    print("https://github.com/acme/shop-gitops/pull/7")
"""


class World:
    def __init__(self, repo: Path, log: Path):
        self.repo, self.log = repo, log

    def prs(self) -> list[dict]:
        """Every `gh pr create` as {title, body, base}."""
        out = []
        for ln in self.log.read_text().splitlines() if self.log.is_file() else []:
            args = json.loads(ln)
            if args[:2] == ["pr", "create"]:
                out.append({"title": args[args.index("--title") + 1], "body": args[args.index("--body") + 1], "args": args})
        return out

    def calls(self) -> list[list[str]]:
        return [json.loads(ln) for ln in self.log.read_text().splitlines()] if self.log.is_file() else []

    def branches(self) -> list[str]:
        return git(self.repo, "branch", "--format=%(refname:short)").split()

    def main_head(self) -> str:
        return git(self.repo, "rev-parse", "main").strip()


def make_world(tmp_path: Path, monkeypatch, doc: dict) -> World:
    """A committed gitops-app checkout (main) with a bare `origin` and `gh` replaced by a script that records its arguments."""
    repo = tmp_path / "gitops"
    repo.mkdir()
    make_repo(repo, doc)
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True, capture_output=True)
    git(repo, "remote", "add", "origin", str(origin))
    git(repo, "branch", "-M", "main")
    git(repo, "push", "-q", "-u", "origin", "main")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(GH_SCRIPT.format(python=sys.executable))
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "gh.log"
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("GH_LOG", str(log))
    return World(repo, log)


def snapshot(repo: Path) -> tuple:
    """(HEAD, branches, porcelain status): equal before and after a command that changed nothing."""
    return (git(repo, "rev-parse", "HEAD").strip(), git(repo, "branch", "--format=%(refname:short)").split(), git(repo, "status", "--porcelain"))


# ---------------- the cluster ----------------

def ts(minutes_ago: float) -> str:
    d = datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=minutes_ago)
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def pg_cluster(env="dev", name="shop-orders-db", image=None, major=None, instances=1, ready=1, phase="Cluster in healthy state") -> dict:
    """A CloudNativePG Cluster as the verification reads it: phase, readyInstances, image and pgDataImageInfo."""
    c = cnpg_cluster(name, f"shop-{env}")
    c["spec"] = {"instances": instances}
    c["status"].update({"phase": phase, "readyInstances": ready, "image": image or PG[17]})
    if major is not None:
        c["status"]["pgDataImageInfo"] = {"image": image or PG[17], "majorVersion": major}
    return c


def backed_up(kube: FakeKube, envs=("dev", "staging", "prod"), minutes_ago: float | None = 30, name="shop-orders-db", clusters: bool = True) -> str | None:
    """Every environment's database cluster with archiving ok and a completed base backup `minutes_ago` minutes ago (None: never).
    `clusters=False` leaves the Cluster objects to the caller (the verification puts its own)."""
    stamp = ts(minutes_ago) if minutes_ago is not None else None
    for env in envs:
        ns = f"shop-{env}"
        if clusters:
            kube.put("cluster", cnpg_cluster(name, ns))
        kube.put("objectstore", objectstore({name: stamp} if stamp else {}, name, ns))
        if stamp:
            kube.put("cnpg.backup", cnpg_backup(f"{name}-b1", cluster=name, ns=ns, stopped=stamp))
    kube.pg_latest = stamp or ""
    return stamp


def record(env="dev", major="17", image=None, state="verified", check="", resource="orders-db", at="2026-10-28T10:00:00Z") -> dict:
    """The ConfigMap `<system>-<resource>-upgrade` of design.md."""
    return {"apiVersion": "v1", "kind": "ConfigMap",
            "metadata": meta(f"shop-{resource}-upgrade", f"shop-{env}",
                             labels={"app.kubernetes.io/name": resource, "app.kubernetes.io/part-of": "shop", "app.kubernetes.io/managed-by": "cplat"}),
            "data": {"major": major, "image": image or PG[int(major)], "state": state, "at": at, "check": check, "release": "5.4.0"}}


def secret(env="dev", name="shop-orders-db-app") -> dict:
    return {"apiVersion": "v1", "kind": "Secret", "metadata": meta(name, f"shop-{env}"), "data": {}}


def applied(kube: FakeKube, kind: str = "ConfigMap") -> list[dict]:
    return kube.created(kind)


def word(text: str, name: str) -> bool:
    """Whole-word match of a (domain-like) name; never `"a.b.c" in text`."""
    return re.search(rf"(?<![\w.-]){re.escape(name)}(?![\w-])", text) is not None


def versions_module():
    import importlib
    return importlib.import_module("versions")


def render_module(name="render_121"):
    return platform_render_module(name)


def row(rows: list[dict], name: str) -> dict:
    return next(r for r in rows if r["name"] == name)


def table_rows(name="render_121_rows") -> list[dict]:
    return render_module(name).versions_table()


def doc_with_everything() -> dict:
    """A database with backups, a bucket, a cache and a broker, all in-cluster in every environment, plus the lgtm UI."""
    from broker_fixtures import broker, events
    from cache_fixtures import cache
    res = {"orders-db": db(version=17, instances={e: {"backup": dict(DEV)} for e in ENVS}), "backups": {"type": "bucket"}, "sessions": cache(),
           "bus": broker()}
    comps = {"api": comp("api", ["orders-db", "sessions"], provides=["orders"]), "web": comp("web", ["backups"], consumes=["orders"])}
    doc = system(res, comps, apis=events("orders"))
    return doc


def statefulset(env, name, container, image, replicas=1, ready=1, updated=1, current="r1", update="r1") -> dict:
    """A StatefulSet as the cache and broker health reads it (readyReplicas, updatedReplicas, revisions, the container image)."""
    return {"apiVersion": "apps/v1", "kind": "StatefulSet", "metadata": meta(name, f"shop-{env}"),
            "spec": {"replicas": replicas, "template": {"spec": {"containers": [{"name": container, "image": image}]}}},
            "status": {"readyReplicas": ready, "updatedReplicas": updated, "currentRevision": current, "updateRevision": update}}
