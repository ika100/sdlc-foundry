"""Shared helpers of the spec 115 acceptance tests (not a test module, never collected).

Contract: docs/specs/115-.../design.md. Builds systems with named, typed and external resources on top of system_fixtures and runs
the template's renderer as a script in a hand-built checkout (like `devbox run render`). Nothing here touches the network."""
import copy
import re
import subprocess
from pathlib import Path

import pytest
import yaml

from system_fixtures import PROBES, ROOT, generated, render, render5, tiny

APP = "applications/shop"
STORE = {"name": "platform-secrets", "kind": "ClusterSecretStore"}
ENVS = ("dev", "staging", "prod")
KEYS = ["uri", "host", "port", "dbname", "user", "password"]
VARS = {"DATABASE_URL": "uri", "PGHOST": "host", "PGPORT": "port", "PGDATABASE": "dbname", "PGUSER": "user", "PGPASSWORD": "password"}
PIN_RE = re.compile(r"^ghcr\.io/cloudnative-pg/postgresql:(\d+)\.\d+(@sha256:[0-9a-f]{64})?$")
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
TYPES_LINE = "(database, bucket, cache or broker)"
LABELS = {"app.kubernetes.io/managed-by": "gitops-app", "app.kubernetes.io/part-of": "shop"}
IMAGE_LINE = re.compile(rb"(imageName: ghcr\.io/cloudnative-pg/postgresql:)(\d+)\S*")


def comp(name, uses=(), envs=ENVS, **extra) -> dict:
    c = {"type": "service", "lang": "python", "repo": f"acme/{name}", "image": f"ghcr.io/acme/{name}", "port": 8080,
         "probes": dict(PROBES), "instances": {e: {} for e in envs}}
    if uses:
        c["uses"] = list(uses)
    c.update(copy.deepcopy(extra))
    return c


def system(resources=None, comps=None, store=True, **top) -> dict:
    doc = tiny()
    doc["components"] = comps if comps is not None else {"api": comp("api")}
    if store:
        doc["secretStore"] = dict(STORE)
    if resources is not None:
        doc["resources"] = resources
    doc.update(copy.deepcopy(top))
    return doc


def db(**kw) -> dict:
    return {"type": "database", **kw}


def two_dbs(**over) -> dict:
    """orders (all environments) uses orders-db, users (dev and staging) uses users-db, each database with values of its own."""
    res = {"orders-db": db(version=16, replicas=2, storage="5Gi", resources={"requests": {"cpu": "200m", "memory": "512Mi"}, "limits": {"memory": "1Gi"}},
                           instances={"prod": {"replicas": 3, "storage": "50Gi"}}),
           "users-db": db(version=18, storage="2Gi", instances={"staging": {"storage": "3Gi"}}),
           "idle-db": db()}
    return system(res, {"orders": comp("orders", ["orders-db"]), "users": comp("users", ["users-db"], envs=("dev", "staging"))}, **over)


def tree(root: Path) -> dict[str, str]:
    """Everything the renderer writes: applications/, bootstrap/ and the cluster-level operators/."""
    out = generated(root)
    base = Path(root) / "operators"
    for p in sorted(base.rglob("*")) if base.is_dir() else []:
        if p.is_file():
            out[p.relative_to(root).as_posix()] = p.read_text()
    return out


def ok(tmp_path, doc, *args) -> dict[str, str]:
    p = render5(tmp_path, doc, *args)
    assert p.returncode == 0, p.stdout + p.stderr
    return tree(tmp_path)


def fails(tmp_path, doc, *needles) -> str:
    """The render fails with exit 1, names every needle on stderr and writes nothing."""
    p = render5(tmp_path, doc)
    assert p.returncode == 1, f"expected a failed render, got {p.returncode}: {p.stdout}{p.stderr}"
    for n in needles:
        assert n in p.stderr, f"{n!r} not in: {p.stderr}"
    assert tree(tmp_path) == {}, "a failed render must not write files"
    return p.stderr


def y(g: dict, path: str):
    return yaml.safe_load(g[path])


def cluster(g, env, name) -> dict:
    return y(g, f"{APP}/addons/{env}/{name}/cluster.yaml")


def sets(g) -> dict:
    return {d["metadata"]["name"]: d for d in yaml.safe_load_all(g[f"{APP}/applicationset.yaml"]) if d}


def addon_names(g, env) -> list[str]:
    s = sets(g).get(f"shop-addons-{env}")
    return [e["name"] for e in s["spec"]["generators"][0]["list"]["elements"]] if s else []


def env_list(g, env, name) -> list[dict]:
    return y(g, f"{APP}/overlays/{env}/{name}/deployment.yaml")["spec"]["template"]["spec"]["containers"][0]["env"]


def secret_vars(g, env, name) -> dict[str, tuple[str, str]]:
    return {e["name"]: (e["valueFrom"]["secretKeyRef"]["name"], e["valueFrom"]["secretKeyRef"]["key"])
            for e in env_list(g, env, name) if "valueFrom" in e}


def var_order(g, env, name) -> list[str]:
    return [e["name"] for e in env_list(g, env, name) if "valueFrom" in e]


def contract_vars(resource: str, prefix: str = "") -> dict[str, tuple[str, str]]:
    return {prefix + v: (f"shop-{resource}-app", k) for v, k in VARS.items()}


def external_secret_path(env, owner, resource) -> str:
    return f"{APP}/overlays/{env}/{owner}/externalsecret-shop-{resource}-app.yaml"


def external_secret(resource, store_key, refresh="1h", store=STORE) -> dict:
    return {"apiVersion": "external-secrets.io/v1", "kind": "ExternalSecret",
            "metadata": {"name": f"shop-{resource}-app", "labels": {"app.kubernetes.io/name": resource, **LABELS}},
            "spec": {"refreshInterval": refresh, "secretStoreRef": {"name": store["name"], "kind": store["kind"]},
                     "target": {"name": f"shop-{resource}-app", "creationPolicy": "Orphan", "deletionPolicy": "Retain"},
                     "data": [{"secretKey": k, "remoteRef": {"key": store_key, "property": k}} for k in KEYS]}}


def kustomization(g, env, name) -> dict:
    return y(g, f"{APP}/overlays/{env}/{name}/kustomization.yaml")


def platform_render_module(name: str = "render_115"):
    """The template's render.py as a module (for its constants)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, ROOT / "templates" / "gitops-app" / "scripts" / "render.py")
    r = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(r)
    return r


def render_50(tmp_path: Path, doc) -> dict[str, str]:
    """Render with the 5.0 renderer (git tag v5.0.0 of this checkout); skips when the tag is not available."""
    got = subprocess.run(["git", "show", "v5.0.0:templates/gitops-app/scripts/render.py"], cwd=ROOT, capture_output=True, text=True)
    if got.returncode != 0:
        pytest.skip("tag v5.0.0 is not available in this checkout")
    script = tmp_path / "render_v50.py"
    script.write_text(got.stdout)
    root = tmp_path / "v50"
    root.mkdir()
    from system_fixtures import write_system
    write_system(root, doc)
    p = render(root, script=script)
    assert p.returncode == 0, "the 5.0 side must render: " + p.stderr
    return generated(root)


def normalized(text: str) -> str:
    """The migration proof's rule (design.md): the database image is compared by its major only."""
    return IMAGE_LINE.sub(rb"\1\2", text.encode()).decode()
