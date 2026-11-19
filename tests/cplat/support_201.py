"""Shared helpers of the spec 201 acceptance tests (not a test module, never collected).

Contract: docs/specs/201-.../design.md. A cluster repo is a shared Copier render of templates/cluster-gitops (cluster_fixtures);
`cluster.yaml` and `clusters/<name>/cluster.yaml` are rewritten per test and the repo's own `scripts/render.py` runs as a script,
like `devbox run render`. Everything the feature adds is reached inside the test body, so a missing script, module or key fails
the test and never breaks collection."""
import json
import os
import stat
import sys
from pathlib import Path

import yaml

from cluster_fixtures import NAME, ORG, ROOT, SERVER, base, render, rendered, system_repo, write_cluster
from waiting import with_prelude

__all__ = ["NAME", "ORG", "ROOT", "SERVER"]

LOCAL, HOME = "local", "home"
TODO_REPO = f"{ORG}/todo-gitops"
SPLIT = {"dev": LOCAL, "staging": LOCAL, "prod": HOME}
ENVS = ("dev", "staging", "prod")
NO_FINALIZER = "resources-finalizer.argocd.argoproj.io"
UNKNOWN_KEYS = "cluster, owner, server, org, operators, secretStore, clusters, systems"


def multi(clusters=(LOCAL, HOME), operators=("cloudnative-pg",), systems=None, **more) -> dict:
    """A `cluster.yaml` document with `clusters` (keys in the contract's order)."""
    doc = base(operators=list(operators), **more)
    doc["clusters"] = list(clusters)
    doc["systems"] = systems or {}
    return doc


def todo(environments=SPLIT) -> dict:
    entry = {"repo": TODO_REPO}
    if environments is not None:
        entry["environments"] = dict(environments)
    return {"todo": entry}


def setup(repo: Path, doc, exceptions: dict | None = None, listed=None) -> None:
    """Write cluster.yaml and one `clusters/<c>/cluster.yaml` per listed cluster (empty unless `exceptions` has text or a mapping)."""
    write_cluster(repo, doc)
    names = listed if listed is not None else (doc.get("clusters") if isinstance(doc, dict) else None) or []
    for c in names:
        if not isinstance(c, str):
            continue
        d = repo / "clusters" / c
        d.mkdir(parents=True, exist_ok=True)
        exc = (exceptions or {}).get(c)
        text = "" if exc is None else exc if isinstance(exc, str) else yaml.safe_dump(exc, sort_keys=False)
        (d / "cluster.yaml").write_text(text)


def run_render(repo: Path, doc, exceptions: dict | None = None, *args: str):
    setup(repo, doc, exceptions)
    return render(repo, None, *args)


def render_clusters(repo: Path, doc, exceptions: dict | None = None):
    p = run_render(repo, doc, exceptions)
    assert p.returncode == 0, p.stdout + p.stderr
    return p


def tree(repo: Path, cluster: str) -> dict[str, str]:
    """Every file of one cluster's tree (path relative to the repo root -> text)."""
    return {k: v for k, v in rendered(repo).items() if k.startswith(f"cluster/{cluster}/")}


def load(repo: Path, rel: str):
    return yaml.safe_load((repo / rel).read_text())


def docs_of(text: str) -> list[dict]:
    return [d for d in yaml.safe_load_all(text) if d]


def system_app(repo: Path, cluster: str, system: str = "todo") -> dict:
    return load(repo, f"cluster/{cluster}/systems/{system}.yaml")


def fails(repo: Path, doc, message: str, file: str = "cluster.yaml", exceptions: dict | None = None, listed=None) -> None:
    """The render fails with exactly one `ERROR: <file>: <message>` line, exit 1, and writes nothing."""
    setup(repo, doc, exceptions, listed)
    before = rendered(repo)
    p = render(repo, None)
    assert p.returncode == 1, f"expected exit 1, got {p.returncode}: {p.stdout}{p.stderr}"
    assert p.stderr.strip().splitlines() == [f"ERROR: {file}: {message}"], p.stderr
    assert rendered(repo) == before, "a failed render must not write files"


def stdout_lines(p) -> list[str]:
    return p.stdout.strip().splitlines()


# ---------------- a kubectl that answers per kube context ----------------

KUBECTL = '''#!{py}
import json, os, sys
a = sys.argv[1:]
data = ""
if "-" in a and any(x in ("-f", "--filename") for x in a):
    data = sys.stdin.read()
with open(os.environ["KUBE_LOG"], "a") as f:
    f.write(" ".join(a) + "\\n")
ctx = a[a.index("--context") + 1] if "--context" in a else ""
if a[:2] == ["config", "current-context"]:
    print("the-wrong-current-context"); sys.exit(0)
if "get-contexts" in a:
    print("ctx-a"); sys.exit(0)
reach = [c for c in os.environ.get("KUBE_REACHABLE", "").split(",") if c]
if ctx and ctx not in reach:
    print("Unable to connect to the server: dial tcp 10.0.0.5:6443: no route to host", file=sys.stderr); sys.exit(1)
text = " ".join(a)
fmt = a[a.index("-o") + 1] if "-o" in a else ""
state = json.loads(os.environ.get("KUBE_STATE") or "{}").get(ctx, {})
if "platform-operators" in text and fmt.startswith("jsonpath"):
    print(os.environ.get("KUBE_OPERATORS_SOURCE", "")); sys.exit(0)
if "get" in a and ("applications" in a or "application" in a or "applications.argoproj.io" in a):
    apps = state.get("apps", {})
    named = [x for x in a if x in apps or x.startswith(("operator-", "system-"))]
    if named and "applications" not in a:
        one = apps.get(named[0])
        if one is None:
            print("Error from server (NotFound): applications.argoproj.io " + named[0] + " not found", file=sys.stderr); sys.exit(1)
        sync, health = one.split()
        if fmt.startswith("jsonpath"):
            print(sync + " " + health); sys.exit(0)
        print(json.dumps({"metadata": {"name": named[0]}, "status": {"sync": {"status": sync}, "health": {"status": health}}})); sys.exit(0)
    if fmt == "name":
        print("\\n".join("application.argoproj.io/" + n for n in apps)); sys.exit(0)
    items = [{"metadata": {"name": n}, "status": {"sync": {"status": s.split()[0], "revision": "deadbeef"},
                                                    "health": {"status": s.split()[1]}, "summary": {"images": []}}} for n, s in apps.items()]
    print(json.dumps({"items": items})); sys.exit(0)
if "version" in a and "json" in fmt:
    print(json.dumps({"serverVersion": {"gitVersion": "v" + state.get("k8s", "1.31.4") + "+k3s1"}})); sys.exit(0)
if "argocd-server" in text:
    image = "quay.io/argoproj/argocd:v" + state.get("argo", "2.13.1")
    print(json.dumps({"spec": {"template": {"spec": {"containers": [{"image": image}]}}}}) if fmt == "json" else image); sys.exit(0)
if "gatewayclass" in text.lower():
    names = state.get("gateway", ["traefik.io/gateway-controller"])
    print(json.dumps({"items": [{"spec": {"controllerName": n}} for n in names]}) if fmt == "json" else ",".join(names)); sys.exit(0)
if "gateways.gateway.networking.k8s.io" in text:
    v = state.get("bundle", "v1.2.0")
    print(json.dumps({"metadata": {"annotations": {"gateway.networking.k8s.io/bundle-version": v}}}) if fmt == "json" else v); sys.exit(0)
if "get" in a and "crd" in a:
    sys.exit(1 if os.environ.get("KUBE_NO_CRD") else 0)
if "get" in a and ("ns" in a or "namespace" in a) and "argocd" in a:
    sys.exit(0)
if "create" in a and "secret" in a:
    print("apiVersion: v1\\nkind: Secret\\nmetadata:\\n  name: stub\\n  namespace: argocd")
sys.exit(0)
'''


def kube_stub(tmp_path: Path, monkeypatch, *, reachable=(), state: dict | None = None, operators_source: str = "") -> Path:
    """Replace `kubectl` on PATH (the dir stubs() made, else a new one) with one that answers per `--context`."""
    bin_dir = tmp_path / "stub-bin"
    bin_dir.mkdir(exist_ok=True)
    p = bin_dir / "kubectl"
    p.write_text(with_prelude(KUBECTL.replace("{py}", sys.executable)))
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "kube.log"
    log.touch()
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("KUBE_LOG", str(log))
    monkeypatch.setenv("KUBE_REACHABLE", ",".join(reachable))
    monkeypatch.setenv("KUBE_STATE", json.dumps(state or {}))
    monkeypatch.setenv("KUBE_OPERATORS_SOURCE", operators_source)
    for k in ("KUBE_NO_ARGOCD", "KUBE_NO_CRD", "CPLAT_KUBE_CONTEXT"):
        monkeypatch.delenv(k, raising=False)
    return log


def kube_calls(log: Path) -> list[str]:
    return [ln for ln in log.read_text().splitlines() if ln.strip()]


def user_settings(tmp_path: Path, monkeypatch, text: str | None) -> Path:
    """The personal settings file (ADR-036) under a private XDG_CONFIG_HOME."""
    xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    f = xdg / "sdlc-foundry" / "settings.yml"
    if text is None:
        f.unlink(missing_ok=True)
    else:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
    return f


# ---------------- a system repo that runs on several clusters ----------------

def split_doc(name: str = "todo", cluster_keys=SPLIT, **kw) -> dict:
    from cluster_fixtures import sys_doc
    doc = sys_doc(name, **kw)
    for env, c in (cluster_keys or {}).items():
        doc["environments"][env]["cluster"] = c
    return doc


def split_repo(fixtures: Path, doc: dict | None = None, slug: str = TODO_REPO, *, release: str | None = "5.1.0", roots: bool = True) -> Path:
    """The system repo as `main` serves it, with the `bootstrap/environments/<s>-<env>.yaml` files a split system renders."""
    doc = doc or split_doc()
    d = system_repo(fixtures, slug, doc, release=release)
    if roots:
        out = d / "bootstrap" / "environments"
        out.mkdir(parents=True, exist_ok=True)
        for env in ENVS:
            (out / f"{doc['system']}-{env}.yaml").write_text(f"# {doc['system']}-{env}-root\n")
    return d


# ---------------- a later cluster kept at its release ----------------

KEPT = '''import json, os, sys
spec = json.load(sys.stdin)
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "stdin.json"), "w") as f:
    json.dump(spec, f)
here = os.path.basename(os.path.dirname(os.path.abspath(__file__)))
print(json.dumps({"files": {spec["tree"] + "/operators-root.yaml": "kept: " + spec["tree"] + " by " + here + "\\n"}}))
'''


def pin_release(repo, release="5.1.0", later="4.12.0", kept=True):
    (repo / ".platform-version").write_text(f"platform: {release}\n")
    (repo / "clusters" / HOME).mkdir(parents=True, exist_ok=True)
    (repo / "clusters" / HOME / "release.yaml").write_text(f"platform: {later}\n")
    if kept:
        d = repo / ".platform" / "releases" / later
        d.mkdir(parents=True, exist_ok=True)
        (d / "render.py").write_text(KEPT)
