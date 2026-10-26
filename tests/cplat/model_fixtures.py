"""Shared helpers of the spec 113 acceptance tests (not a test module, never collected).

Builds a gitops-app checkout by hand (no copier, no render): `applications/<app>/{services.yaml,app.yaml}` and the image pins in
`overlays/<env>/<service>/kustomization.yaml`. `model` / `modelcmd` do not exist before the feature, so they are imported inside
the tests (through `model()`), never at module level: a missing module fails the test, it does not break collection."""
import copy
import importlib
import subprocess
from pathlib import Path

import yaml

SHA = "0123456789abcdef0123456789abcdef01234567"
BARE_ENV = ("argo", "sync", "health", "digest", "running", "smoke", "alerts_firing", "ci", "observed")


def model():
    return importlib.import_module("model")


def write_app(root: Path, services, app=None, pins=None, name: str = "shop") -> Path:
    """Write the declared files; `pins` maps (env, service) to a tag (None: an overlay without a tag). Returns the app dir."""
    d = Path(root) / "applications" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "services.yaml").write_text(services if isinstance(services, str) else yaml.safe_dump({"services": copy.deepcopy(services)}, sort_keys=False))
    if app is not None:
        (d / "app.yaml").write_text(app if isinstance(app, str) else yaml.safe_dump(copy.deepcopy(app), sort_keys=False))
    for (env, svc), tag in (pins or {}).items():
        k = d / "overlays" / env / svc
        k.mkdir(parents=True, exist_ok=True)
        image = {"name": f"ghcr.io/acme/{svc}"}
        if tag is not None:
            image["newTag"] = tag
        (k / "kustomization.yaml").write_text(yaml.safe_dump({"resources": ["deployment.yaml"], "images": [image]}, sort_keys=False))
    return d


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=root, check=True, capture_output=True, text=True).stdout


def git_repo(root: Path) -> Path:
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "init")
    return root


def clean(root: Path) -> bool:
    return git(root, "status", "--porcelain").strip() == ""


def snapshot(root: Path) -> dict[str, bytes]:
    """Every file under root (not .git) with its bytes: equal before and after means nothing was written."""
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(Path(root).rglob("*")) if p.is_file() and ".git" not in p.relative_to(root).parts}


# ---------------- a small app (the design's example) ----------------

SMALL_APP = {"hosts": {"dev": "{service}.{app}-dev.localhost"}, "addons": {"postgres": {}, "observability": {"ui": "lgtm"}}}
SMALL_SERVICES = [
    {"name": "shop-api", "repo": "acme/shop-api", "image": "ghcr.io/acme/shop-api", "shape": "service-python", "port": 8080,
     "expose": True, "metrics": "/metrics", "uses": ["postgres"], "environments": ["dev", "staging"], "replicas": {"dev": 1, "staging": 2},
     "secrets": [{"name": "api-keys", "remote": {"keys": ["STRIPE_KEY"]}}]},
    {"name": "stock", "repo": "acme/stock", "image": "ghcr.io/acme/stock", "external": {"kustomize": "external/stock", "namespace": "stock"},
     "environments": ["dev"]},
]
SMALL_PINS = {("dev", "shop-api"): "sha-" + SHA, ("dev", "stock"): "sha-abc1234"}

SMALL_TEXT = f"""System: shop

Environments (promotion order):
  dev  host {{service}}.{{app}}-dev.localhost  url-template -  policy off  promotion follows main  observability ui=lgtm export=- alerts=on rules=0
  staging  host -  url-template -  policy off  promotion manual  observability ui=lgtm export=- alerts=on rules=0
  prod  host -  url-template -  policy off  promotion manual  observability ui=lgtm export=- alerts=on rules=0

Components:
  shop-api  type service  lang python  repo acme/shop-api  image ghcr.io/acme/shop-api  uses postgres  secrets api-keys
  stock  type service  lang unknown  repo acme/stock  image ghcr.io/acme/stock  external kustomize  uses -  secrets -

Instances:
  shop-api  dev  sha-{SHA}  replicas 1  namespace shop-dev  url http://shop-api.shop-dev.localhost:8088
  shop-api  staging  not pinned  replicas 2  namespace shop-staging  url -
  stock  dev  sha-abc1234  replicas -  namespace stock  url -

Resources:
  postgres  type database  used by shop-api
    dev  instances 1  version 17  storage 1Gi  argo addon-postgres-dev  secret shop-postgres-app
    staging  instances 1  version 17  storage 1Gi  argo addon-postgres-staging  secret shop-postgres-app
"""

# ---------------- a rich app: every rule of the model once ----------------

RICH_APP = {
    "gateway": {"name": "traefik-gateway", "namespace": "kube-system"},
    "hosts": {"dev": "{service}.{app}-dev.localhost", "staging": "{service}.staging.example.com"},
    "urls": {"staging": "https://{host}/{service}"},
    "promotion": {"staging": "auto"},
    "policies": {"mode": {"dev": "Audit", "staging": "Off"}},
    "addons": {
        "postgres": {"version": 17, "instances": {"dev": 1, "prod": 3}, "storage": {"dev": "1Gi", "prod": "20Gi"}},
        "observability": {"ui": "lgtm", "exportTo": "https://otlp.example.com", "alerts": False, "queryURL": "http://q.example.com",
                          "alertmanagerURL": "http://am.example.com", "rules": [{"name": "R", "query": "up == 0", "severity": "warning"}]},
    },
}
RICH_SERVICES = [
    {"name": "shop-api", "repo": "acme/shop-api", "image": "ghcr.io/acme/shop-api", "shape": "service-python", "port": 8080,
     "expose": {"host": "api"}, "metrics": "/metrics", "uses": ["postgres"], "environments": ["dev", "staging"],
     "replicas": {"dev": 1, "staging": 2}, "promotion": {"staging": "manual"},
     "secrets": [{"name": "api-keys", "remote": {"keys": ["STRIPE_KEY", "STRIPE_HOOK"]}},
                 {"name": "api-pay", "remote": {"keys": ["PAY_KEY"], "path": "{service}/{env}/{secret}"}},
                 {"name": "api-auth", "generate": ["DB_PASSWORD", "JWT_KEY"]}],
     "secretRefs": ["shared-config"]},
    {"name": "shop-web", "repo": "acme/shop-web", "image": "ghcr.io/acme/shop-web", "shape": "web-nextjs", "port": 3000,
     "expose": True, "environments": ["dev", "staging", "prod"], "replicas": 3},
    {"name": "stock", "repo": "acme/stock", "image": "ghcr.io/acme/stock", "external": {"kustomize": "external/stock", "namespace": "stock"},
     "environments": ["dev"]},
    {"name": "ai-ops", "repo": "acme/ai-ops", "image": "ghcr.io/acme/ai-ops",
     "external": {"helm": {"repoURL": "https://github.com/acme/ai-ops", "path": "charts/ai-ops"}}, "environments": ["dev", "prod"]},
    {"name": "ledger", "repo": "acme/ledger", "image": "ghcr.io/acme/ledger", "shape": "service-java", "port": 8080},
    {"name": "batch", "repo": "acme/batch", "image": "ghcr.io/acme/batch", "shape": "service-go", "port": 8080, "environments": ["dev", "qa"]},
    {"name": "mystery", "repo": "acme/mystery", "image": "ghcr.io/acme/mystery", "shape": "service-cobol", "port": 8080, "environments": ["dev"]},
    {"name": "plain", "repo": "acme/plain", "image": "ghcr.io/acme/plain", "port": 8080, "environments": []},
]
RICH_PINS = {
    ("dev", "shop-api"): "sha-" + SHA,
    ("dev", "shop-web"): "latest",
    ("staging", "shop-web"): None,          # an overlay without a tag
    ("prod", "shop-web"): "1.2.0",
    ("dev", "stock"): "sha-abc1234",
}


def rich(root: Path) -> Path:
    return write_app(root, RICH_SERVICES, RICH_APP, RICH_PINS)


def small(root: Path) -> Path:
    return write_app(root, SMALL_SERVICES, SMALL_APP, SMALL_PINS)


def reader(root: Path, log: list | None = None):
    """A `read(path) -> dict | None` over a checkout, like the `gh` readers of smoke and staging."""
    def read(path: str):
        if log is not None:
            log.append(path)
        f = Path(root) / path
        if not f.is_file():
            return None
        data = yaml.safe_load(f.read_text())
        return data if isinstance(data, dict) else None
    return read
