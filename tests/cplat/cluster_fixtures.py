"""Shared helpers of the spec 125 acceptance tests (not a test module, never collected).

Contract: docs/specs/125-.../design.md. A cluster repo is a Copier copy of templates/cluster-gitops (rendered once per process through
the ADR-052 shared renders and copied privately per test). `cluster.yaml` is rewritten per test and the repo's own `scripts/render.py`
runs as a script, like `devbox run render`. System repos are fixture directories handed to the cluster scripts by a `gh` stub on PATH
(`gh repo clone`, `gh api repos/<o>/<n>/contents/...`, `gh repo view`, `gh pr create`). Nothing touches the network except the Copier
run, as in the other template tests. Everything the feature adds is reached inside the test body, so a missing template, script or
module fails the test instead of breaking collection."""
import os
import stat
import subprocess
import sys
from pathlib import Path

import yaml

from resources_fixtures import comp, db, system
from system_fixtures import ROOT, git, init_git, write_system

TEMPLATE = ROOT / "templates" / "cluster-gitops"
GITOPS_RENDER = ROOT / "templates" / "gitops-app" / "scripts" / "render.py"
ORG = "acme"
NAME = "home"
ENVS = ("dev", "staging", "prod")
SERVER = "https://kubernetes.default.svc"


def _copier(dest: Path, name: str, org: str) -> Path:
    cmd = ["uv", "tool", "run", "--from", "copier", "copier", "copy", str(TEMPLATE), str(dest), "--defaults", "--trust", "--skip-tasks",
           "--data", f"project_name={name}", "--data", f"github_org={org}", "--data", "description=check"]
    subprocess.run(cmd, check=True, capture_output=True)
    return dest


def cluster_repo(shared_renders, tmp_path: Path, name: str = NAME, org: str = ORG) -> Path:
    """A private copy of `copier copy templates/cluster-gitops --defaults` (rendered once per process).

    When the template is missing or does not copy, the result is an empty directory holding `.render-error` and the error is printed:
    the test then fails in its body (no scripts/render.py, no cluster.yaml), never as a fixture ERROR."""
    dest = tmp_path / name
    try:
        return shared_renders.copy(f"cluster-gitops {name} {org}", lambda workdir: _copier(workdir / name, name, org), dest)
    except Exception as err:   # noqa: BLE001
        dest.mkdir(parents=True, exist_ok=True)
        (dest / ".render-error").write_text(str(err))
        print(f"cluster repo render failed: {err}", file=sys.stderr)
        return dest


def soft(fn, *args, **kw):
    """Run a fixture step that depends on the feature; a failure is left for the test body to show."""
    try:
        return fn(*args, **kw)
    except (Exception, SystemExit):   # noqa: BLE001
        return None


def write_cluster(repo: Path, doc) -> None:
    (repo / "cluster.yaml").write_text(doc if isinstance(doc, str) else yaml.safe_dump(doc, sort_keys=False))


def base(**more) -> dict:
    return {"cluster": NAME, "owner": ORG, **more}


def script(repo: Path, name: str, *args: str, env: dict | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess:
    py = name.endswith(".py")
    cmd = [sys.executable, f"scripts/{name}", *args] if py else ["bash", f"scripts/{name}", *args]
    return subprocess.run(cmd, cwd=cwd or repo, capture_output=True, text=True, env={**os.environ, **(env or {})})


def render(repo: Path, doc=None, *args: str) -> subprocess.CompletedProcess:
    if doc is not None:
        write_cluster(repo, doc)
    return script(repo, "render.py", *args)


def rendered(repo: Path) -> dict[str, str]:
    """Every file under cluster/ (relative path -> text)."""
    base_dir = repo / "cluster"
    return {p.relative_to(repo).as_posix(): p.read_text() for p in sorted(base_dir.rglob("*")) if p.is_file()}


def docs(text: str) -> list[dict]:
    return [d for d in yaml.safe_load_all(text) if d]


def load(repo: Path, rel: str):
    return yaml.safe_load((repo / rel).read_text())


def render_ok(repo: Path, doc) -> dict[str, str]:
    p = render(repo, doc)
    assert p.returncode == 0, p.stdout + p.stderr
    return rendered(repo)


def render_fails(repo: Path, doc, message: str) -> str:
    """The render fails with exactly one `ERROR: cluster.yaml: <message>` line, exit 1, and changes nothing."""
    before = rendered(repo)
    p = render(repo, doc)
    assert p.returncode == 1, f"expected exit 1, got {p.returncode}: {p.stdout}{p.stderr}"
    assert p.stderr.strip().splitlines() == [f"ERROR: cluster.yaml: {message}"], p.stderr
    assert rendered(repo) == before, "a failed render must not write files"
    return p.stderr


def platform_module(name: str = "render_125"):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, GITOPS_RENDER)
    r = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(r)
    return r


# ---------------- system repos (what `gh` serves) ----------------

def sys_doc(name: str, *, db_resource=False, secrets=False, bucket=False, policy=False, owner_envs=ENVS, external_db=False) -> dict:
    res = {}
    uses = []
    if db_resource:
        res["db"] = db()
        uses.append("db")
    if external_db:
        res["ext"] = db(external=True)
        uses.append("ext")
    if bucket:
        res["files"] = {"type": "bucket"}
        uses.append("files")
    extra = {"secrets": [{"name": "api-auth", "generate": ["JWT_KEY"]}]} if secrets else {}
    doc = system(res or None, {"api": comp("api", uses, **extra)})
    doc["system"] = name
    for e in ENVS:
        doc["environments"][e] = dict(doc["environments"].get(e) or {})
        doc["environments"][e]["policy"] = "audit" if policy and e == "dev" else "off"
        if e in owner_envs:
            doc["environments"][e]["operators"] = "owner"
    return doc


def system_repo(fixtures: Path, slug: str, doc: dict | None = None, *, release: str | None = "5.1.0", commit: str | None = None, hostnames=None,
                extra_systems: dict | None = None) -> Path:
    """`<fixtures>/<owner>__<name>`: a system's gitops repo as `main` serves it."""
    d = Path(fixtures) / slug.replace("/", "__")
    d.mkdir(parents=True, exist_ok=True)
    systems = {doc["system"]: doc} if doc else {}
    systems.update(extra_systems or {})
    for name, sdoc in systems.items():
        write_system(d, sdoc, name)
        for host in (hostnames or {}).get(name, []):
            route = d / "applications" / name / "overlays" / "dev" / "api" / "httproute.yaml"
            route.parent.mkdir(parents=True, exist_ok=True)
            route.write_text(yaml.safe_dump({"apiVersion": "gateway.networking.k8s.io/v1", "kind": "HTTPRoute", "metadata": {"name": "api"},
                                             "spec": {"hostnames": [host]}}))
    answers = {"github_org": ORG}
    if commit:
        answers["_commit"] = commit
    (d / ".copier-answers.yml").write_text(yaml.safe_dump(answers))
    if release:
        (d / ".platform-version").write_text(f"platform: {release}\n")
    return d


GH = '''#!{py}
import base64, json, os, pathlib, shutil, sys
a = sys.argv[1:]
fx = pathlib.Path(os.environ["GH_FIXTURES"])
with open(os.environ["GH_LOG"], "a") as f:
    f.write(" ".join(a) + "\\n")
def rd(slug):
    return fx / slug.replace("/", "__")
def notfound():
    print("gh: Not Found (HTTP 404)", file=sys.stderr)
    sys.exit(1)
if a[:2] == ["auth", "token"]:
    print("gh-token"); sys.exit(0)
if a[:2] == ["repo", "view"]:
    sys.exit(0 if os.environ.get("GH_EXISTING") == a[2] else 1)
if a[:2] == ["repo", "create"]:
    sys.exit(0)
if a[:2] == ["pr", "create"]:
    print("https://github.com/acme/home/pull/7"); sys.exit(0)
if a[:2] == ["repo", "clone"]:
    src = rd(a[2])
    if not src.is_dir():
        print("GraphQL: Could not resolve to a Repository with the name '%s'. (repository)" % a[2], file=sys.stderr); sys.exit(1)
    shutil.copytree(src, a[3], dirs_exist_ok=True); sys.exit(0)
if a[0] == "api":
    path = next((x for x in a[1:] if x.startswith("repos/")), "").split("?")[0]
    parts = path.split("/")
    if len(parts) < 4 or parts[3] != "contents":
        sys.exit(0)
    root = rd("/".join(parts[1:3]))
    target = root / "/".join(parts[4:])
    if not root.is_dir() or not target.exists():
        notfound()
    jq = next((a[i + 1] for i, x in enumerate(a) if x in ("-q", "--jq") and i + 1 < len(a)), None)
    if target.is_dir():
        entries = [{"name": p.name, "type": "dir" if p.is_dir() else "file", "path": str(p.relative_to(root))} for p in sorted(target.iterdir())]
        if jq:
            print("\\n".join(e["name"] for e in entries if jq == ".[].name" or e["type"] == "dir"))
        else:
            print(json.dumps(entries))
        sys.exit(0)
    data = target.read_bytes()
    if jq == ".content" or (not jq and "raw" not in " ".join(a)):
        payload = {"type": "file", "encoding": "base64", "content": base64.b64encode(data).decode(), "name": target.name}
        print(payload["content"] if jq else json.dumps(payload))
    else:
        sys.stdout.write(data.decode())
    sys.exit(0)
sys.exit(0)
'''

KUBECTL = '''#!{py}
import os, sys
a = sys.argv[1:]
data = ""
if any(x in ("-f", "--filename") for x in a) and "-" in a:
    data = sys.stdin.read()
with open(os.environ["KUBE_LOG"], "a") as f:
    f.write("kubectl " + " ".join(a) + ((" <<" + data.replace(chr(10), " | ")) if data else "") + "\\n")
if a[:1] == ["config"] or "get-contexts" in a:
    print("ctx-a"); print("ctx-b"); sys.exit(0)
if "get" in a and ("ns" in a or "namespace" in a) and "argocd" in a:
    sys.exit(1 if os.environ.get("KUBE_NO_ARGOCD") else 0)
if "get" in a and "crd" in a:
    sys.exit(1 if os.environ.get("KUBE_NO_CRD") else 0)
if "create" in a and "secret" in a:
    print("apiVersion: v1\\nkind: Secret\\nmetadata:\\n  name: stub\\n  namespace: argocd")
sys.exit(0)
'''

GENERIC = '''#!{py}
import os, sys
with open(os.environ["KUBE_LOG"], "a") as f:
    f.write("{tool} " + " ".join(sys.argv[1:]) + "\\n")
tool = "{tool}"
a = sys.argv[1:]
if tool == "k3d" and a[:2] == ["cluster", "list"]:
    sys.exit(1)
if tool == "docker" and a[:1] == ["port"]:
    print("0.0.0.0:" + os.environ.get("STUB_PORT", "8098"))
if tool == "gh" and a[:2] == ["auth", "token"]:
    print("gh-token")
sys.exit(0)
'''


def stubs(tmp_path: Path, monkeypatch, fixtures: Path | None = None, *, extra: tuple[str, ...] = ()) -> dict:
    """PATH stubs for gh (fixture repos), kubectl (a call log) and, in `extra`, k3d/docker/helm/curl; `sleep` returns at once."""
    bin_dir = tmp_path / "stub-bin"
    bin_dir.mkdir(exist_ok=True)
    fx = fixtures or (tmp_path / "fixtures")
    fx.mkdir(exist_ok=True)
    gh_log, kube_log = tmp_path / "gh.log", tmp_path / "kube.log"
    gh_log.touch(), kube_log.touch()

    def put(name, body):
        p = bin_dir / name
        p.write_text(body)
        p.chmod(p.stat().st_mode | stat.S_IEXEC)

    put("gh", GH.replace("{py}", sys.executable))
    put("kubectl", KUBECTL.replace("{py}", sys.executable))
    put("sleep", "#!/bin/sh\nexit 0\n")
    for tool in extra:
        put(tool, GENERIC.replace("{py}", sys.executable).replace("{tool}", tool))
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("GH_FIXTURES", str(fx))
    monkeypatch.setenv("GH_LOG", str(gh_log))
    monkeypatch.setenv("KUBE_LOG", str(kube_log))
    monkeypatch.setenv("GH_TOKEN", "gh-token")
    for k in ("GH_EXISTING", "KUBE_NO_ARGOCD", "KUBE_NO_CRD", "KUBE_CONTEXT", "REPO_TOKEN", "LOCAL_CLUSTER"):
        monkeypatch.delenv(k, raising=False)
    for k, v in (("GIT_AUTHOR_NAME", "t"), ("GIT_AUTHOR_EMAIL", "t@t"), ("GIT_COMMITTER_NAME", "t"), ("GIT_COMMITTER_EMAIL", "t@t")):
        monkeypatch.setenv(k, v)
    return {"fixtures": fx, "gh_log": gh_log, "kube_log": kube_log, "bin": bin_dir}


def git_repo(repo: Path, tmp_path: Path) -> Path:
    """Commit the repo on `main` with a bare `origin`."""
    init_git(repo)
    remote = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True, capture_output=True)
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-q", "origin", "main")
    return remote


__all__ = ["ROOT", "git"]
