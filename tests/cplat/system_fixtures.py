"""Shared helpers of the spec 114 acceptance tests (not a test module, never collected).

Contract: docs/specs/114-.../design.md. Builds 5.0 gitops-app checkouts by hand: `applications/<system>/system.yaml` plus the
image pins; and the same system in its 4.7 files (app.yaml + services.yaml) for the byte-identity comparisons. The 5.0 modules
(`apilist`, `migrate5`, ...) do not exist before the feature, so tests import them inside the test (`mod("migrate5")`): a
missing module fails the test and never breaks collection.

`RENDER4` is the frozen 4.7 renderer asset of plan task t1 (scripts/cplat/assets/render_v4.py); `RENDER5` is the template's
renderer, which 5.0 changes."""
import copy
import importlib
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
RENDER5 = ROOT / "templates" / "gitops-app" / "scripts" / "render.py"
RENDER4 = ROOT / "scripts" / "cplat" / "assets" / "render_v4.py"
PIN5 = ROOT / "templates" / "gitops-app" / "scripts" / "pin.py"
NOT_MIGRATED = "not migrated to 5.0: run `cplat platform update --migrate`"
SHA = "0123456789abcdef0123456789abcdef01234567"
ALLOWED_TOP = "system, owner, environments, components, apis, resources, gateway, secretStore, registries"
PAIRS = "service/python, service/java, service/go, website/typescript, library/python"


def mod(name: str):
    return importlib.import_module(name)


def dump(doc) -> str:
    return doc if isinstance(doc, str) else yaml.safe_dump(copy.deepcopy(doc), sort_keys=False)


# ---------------- the same system in 5.0 and in 4.7 ----------------

PROBES = {"liveness": "/health", "readiness": "/ready"}

FULL5 = {
    "system": "shop",
    "owner": "acme",
    "gateway": {"name": "traefik-gateway", "namespace": "kube-system"},
    "secretStore": {"name": "platform-secrets", "kind": "ClusterSecretStore"},
    "registries": ["ghcr.io/acme/"],
    "environments": {
        "dev": {"host": "{component}.{system}-dev.localhost", "url": "http://{host}:8088", "policy": "audit", "observability": {"ui": "lgtm"}},
        "staging": {"host": "{component}.{system}.example.com", "policy": "off", "promote": "after-dev-smoke", "observability": {"ui": "lgtm"}},
        "prod": {"policy": "enforce", "observability": {"ui": "lgtm"}},
    },
    "components": {
        "shop-api": {
            "type": "service", "lang": "python", "repo": "acme/shop-api", "image": "ghcr.io/acme/shop-api", "port": 8080,
            "probes": dict(PROBES), "user": 10001, "metrics": "/metrics", "volumes": {"tmp": "/tmp"}, "env": {"LOG_LEVEL": "INFO"},
            "secretRefs": ["shared-config"],
            "secrets": [
                {"name": "api-auth", "generate": ["JWT_KEY"]},
                {"name": "api-pay", "remote": {"keys": ["PAY_KEY"], "path": "{component}/{env}/{secret}"}},
                {"name": "api-keys", "remote": {"keys": ["STRIPE_KEY"]}},
            ],
            "resources": {"requests": {"cpu": "50m", "memory": "128Mi"}, "limits": {"memory": "512Mi"}},
            "expose": {"host": "api"}, "uses": ["postgres"],
            "instances": {"dev": {"replicas": 1}, "staging": {"replicas": 2, "promote": "manual"}, "prod": {"replicas": 3}},
        },
        "shop-web": {
            "type": "website", "lang": "typescript", "repo": "acme/shop-web", "image": "ghcr.io/acme/shop-web", "port": 3000,
            "probes": dict(PROBES), "expose": True, "instances": {"dev": {}, "staging": {}},
        },
        "stock": {
            "type": "service", "lang": "unknown", "repo": "acme/stock", "image": "ghcr.io/acme/stock",
            "external": {"kustomize": "external/stock"}, "instances": {"dev": {}},
        },
    },
    "resources": {"postgres": {"type": "database", "version": 17,
                               "instances": {"dev": {"replicas": 1, "storage": "1Gi"}, "prod": {"replicas": 3, "storage": "20Gi"}}}},
}

FULL4_APP = {
    "gateway": {"name": "traefik-gateway", "namespace": "kube-system"},
    "hosts": {"dev": "{service}.{app}-dev.localhost", "staging": "{service}.{app}.example.com"},
    "urls": {"dev": "http://{host}:8088"},
    "secretStore": {"name": "platform-secrets", "kind": "ClusterSecretStore"},
    "promotion": {"staging": "auto"},
    "policies": {"mode": {"dev": "Audit", "staging": "Off", "prod": "Enforce"}, "registries": ["ghcr.io/acme/"]},
    "addons": {"postgres": {"version": 17, "instances": {"dev": 1, "prod": 3}, "storage": {"dev": "1Gi", "prod": "20Gi"}},
               "observability": {"ui": "lgtm"}},
}
FULL4_SERVICES = {"services": [
    {"name": "shop-api", "repo": "acme/shop-api", "shape": "service-python", "image": "ghcr.io/acme/shop-api", "port": 8080,
     "probes": dict(PROBES), "user": 10001, "metrics": "/metrics", "volumes": {"tmp": "/tmp"}, "env": {"LOG_LEVEL": "INFO"},
     "secretRefs": ["shared-config"],
     "secrets": [{"name": "api-auth", "generate": ["JWT_KEY"]},
                 {"name": "api-pay", "remote": {"keys": ["PAY_KEY"], "path": "{service}/{env}/{secret}"}},
                 {"name": "api-keys", "remote": {"keys": ["STRIPE_KEY"]}}],
     "replicas": {"dev": 1, "staging": 2, "prod": 3}, "resources": {"requests": {"cpu": "50m", "memory": "128Mi"}, "limits": {"memory": "512Mi"}},
     "expose": {"host": "api"}, "uses": ["postgres"], "promotion": {"staging": "manual"}, "environments": ["dev", "staging", "prod"]},
    {"name": "shop-web", "repo": "acme/shop-web", "shape": "web-nextjs", "image": "ghcr.io/acme/shop-web", "port": 3000,
     "probes": dict(PROBES), "expose": True, "environments": ["dev", "staging"]},
    {"name": "stock", "repo": "acme/stock", "image": "ghcr.io/acme/stock", "external": {"kustomize": "external/stock"}, "environments": ["dev"]},
]}
OLD_COMMENT = "# the shop services (hand-written comment)\n"
PINS = {("dev", "shop-api"): "sha-" + SHA, ("staging", "shop-api"): "1.2.0"}


def full5(**over) -> dict:
    d = copy.deepcopy(FULL5)
    d.update(copy.deepcopy(over))
    return d


def component(doc: dict, name: str = "shop-api") -> dict:
    return doc["components"][name]


def rich5() -> dict:
    """FULL5 plus an API, a library and an instance-level secret override."""
    doc = copy.deepcopy(FULL5)
    api = component(doc)
    api["provides"], api["uses"] = ["shop-api-rest"], ["postgres", "shop-lib"]
    api["instances"]["prod"]["secrets"] = [{"name": "api-pay", "remote": {"keys": ["PAY_KEY"], "path": "prod/{secret}"}}]
    component(doc, "shop-web")["consumes"] = ["shop-api-rest"]
    doc["components"]["shop-lib"] = {"type": "library", "lang": "python", "repo": "acme/shop-lib"}
    doc["apis"] = {"shop-api-rest": {"type": "openapi"}}
    return doc


def tiny(**comp) -> dict:
    """The smallest valid system: one python service in dev (overrides merge over the component)."""
    c = {"type": "service", "lang": "python", "repo": "acme/api", "image": "ghcr.io/acme/api", "port": 8080, "probes": dict(PROBES)}
    c.update(copy.deepcopy(comp))
    return {"system": "shop", "owner": "acme", "environments": {"dev": {"host": "{component}.{system}-dev.localhost"}, "staging": {}, "prod": {}},
            "components": {"api": c}}


# ---------------- writing checkouts ----------------

def write_pins(app_dir: Path, pins: dict) -> None:
    for (env, comp), tag in pins.items():
        k = app_dir / "overlays" / env / comp
        k.mkdir(parents=True, exist_ok=True)
        (k / "kustomization.yaml").write_text(yaml.safe_dump({"resources": ["deployment.yaml"], "images": [{"name": f"ghcr.io/acme/{comp}", "newTag": tag}]}, sort_keys=False))


def write_external(app_dir: Path) -> None:
    (app_dir / "external" / "stock").mkdir(parents=True, exist_ok=True)
    (app_dir / "external" / "stock" / "kustomization.yaml").write_text("resources: []\n")


def write_system(root: Path, doc, name: str = "shop", pins: dict | None = None) -> Path:
    """`applications/<name>/system.yaml` (text or document); returns the application directory."""
    d = Path(root) / "applications" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "system.yaml").write_text(dump(doc))
    write_external(d)
    if pins:
        write_pins(d, pins)
    return d


def write_old(root: Path, app=None, services=None, name: str = "shop", pins: dict | None = None, comments: bool = False) -> Path:
    """The 4.7 files of a system."""
    d = Path(root) / "applications" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "app.yaml").write_text(("# the shop application\n" if comments else "") + dump(FULL4_APP if app is None else app))
    (d / "services.yaml").write_text((OLD_COMMENT if comments else "") + dump(FULL4_SERVICES if services is None else services))
    write_external(d)
    if pins:
        write_pins(d, pins)
    return d


def render(root: Path, *args: str, script: Path = RENDER5) -> subprocess.CompletedProcess:
    """Run a copy of a renderer inside the checkout (`scripts/render.py`), like `devbox run render`."""
    assert script.is_file(), f"missing renderer: {script.relative_to(ROOT)}"
    s = Path(root) / "scripts"
    s.mkdir(exist_ok=True)
    shutil.copy(script, s / "render.py")
    return subprocess.run([sys.executable, str(s / "render.py"), *args], cwd=root, capture_output=True, text=True)


def render5(root: Path, doc, *args: str, name: str = "shop", pins: dict | None = None) -> subprocess.CompletedProcess:
    write_system(root, doc, name, pins)
    return render(root, *args)


def generated(root: Path) -> dict[str, str]:
    """Every rendered file under applications/ and bootstrap/ (not the inputs, not external packages)."""
    out = {}
    for base in ("applications", "bootstrap"):
        for p in sorted((Path(root) / base).rglob("*")) if (Path(root) / base).is_dir() else []:
            rel = p.relative_to(root).as_posix()
            if p.is_file() and p.name not in ("system.yaml", "app.yaml", "services.yaml") and "/external/" not in rel:
                out[rel] = p.read_text()
    return out


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=root, check=True, capture_output=True, text=True).stdout


def init_git(root: Path) -> Path:
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "init")
    return root


def files(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(Path(root).rglob("*"))
            if p.is_file() and ".git" not in p.relative_to(root).parts}


def load(path: Path):
    return yaml.safe_load(Path(path).read_text())


def docs(path: Path) -> list:
    return [d for d in yaml.safe_load_all(Path(path).read_text()) if d]


# ---------------- 4.7 checkouts for the migration tests ----------------

V4_REF = "96dbdcf"            # the last 4.x state of this checkout (before the 5.0 work)
OTHER_PLUGIN = "mytool@other-market"
SRC_PATH = "gh:ika100/sdlc-foundry/templates/{}"


def archive_4x(paths: list[str], dest: Path) -> Path:
    """`git archive V4_REF <paths>` extracted into dest; skips the test when the commit is not in this checkout."""
    import io
    import tarfile

    import pytest
    got = subprocess.run(["git", "archive", V4_REF, *paths], cwd=ROOT, capture_output=True)
    if got.returncode != 0:
        pytest.skip(f"commit {V4_REF} is not available in this checkout")
    dest.mkdir(parents=True, exist_ok=True)
    tarfile.open(fileobj=io.BytesIO(got.stdout)).extractall(dest)
    return dest


def copier_render(template: Path, dest: Path, **data) -> Path:
    import core
    cmd = [*core.find_copier(), "copy", str(template), str(dest), "--defaults", "--trust", "--skip-tasks"]
    for k, v in data.items():
        cmd += ["--data", f"{k}={v}"]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return Path(dest)


def stamp(repo: Path, platform: str, shape: str) -> None:
    (repo / ".platform-version").write_text(f"platform: {platform}\nshape: {shape}\nref: main\n")
    ans = repo / ".copier-answers.yml"
    lines = [f"_src_path: {SRC_PATH.format(shape)}" if ln.startswith("_src_path:") else ln for ln in ans.read_text().splitlines()]
    ans.write_text("\n".join(lines) + "\n")


def build_old_gitops(root: Path, comments: bool = True) -> Path:
    """A real 4.x gitops-app repo: the pre-5.0 template rendered with copier, FULL4 as its app.yaml + services.yaml, rendered by
    its own 4.7 render.py, stamped 4.7.0, one plugin entry of its own, committed."""
    import json
    src = archive_4x(["templates/gitops-app"], root / "tpl")
    repo = copier_render(src / "templates" / "gitops-app", root / "shop-gitops", project_name="shop-gitops", app_name="shop", github_org="acme")
    write_old(repo, pins=PINS, comments=comments)
    done = subprocess.run([sys.executable, "scripts/render.py"], cwd=repo, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    stamp(repo, "4.7.0", "gitops-app")
    settings = repo / ".claude" / "settings.json"
    d = json.loads(settings.read_text())
    d["enabledPlugins"][OTHER_PLUGIN] = True
    settings.write_text(json.dumps(d, indent=2) + "\n")
    return init_git(repo)


def build_old_component(root: Path, template: str = "service-go", name: str = "svc") -> Path:
    """A 4.x component repo: the pre-5.0 template (V4_REF) rendered with copier, stamped 4.7.0, with both old plugins enabled."""
    import json
    src = archive_4x([f"templates/{template}"], root / f"tpl-{name}")
    repo = copier_render(src / "templates" / template, root / name, project_name=name, github_org="acme")
    stamp(repo, "4.7.0", template)
    settings = repo / ".claude" / "settings.json"
    d = json.loads(settings.read_text())
    d["enabledPlugins"].update({"app@sdlc-foundry": True, "gitops@sdlc-foundry": True, OTHER_PLUGIN: True})
    settings.write_text(json.dumps(d, indent=2) + "\n")
    return init_git(repo)
