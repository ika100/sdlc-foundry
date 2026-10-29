"""`cluster new|add|remove` (spec 125): the cluster repo and the systems it installs (cluster.yaml, rendered by scripts/render.py)."""
from __future__ import annotations

import argparse
import base64
import io
import json
import re
from pathlib import Path

import yaml
from ruamel.yaml.comments import CommentedMap

import core
import gitops
import newsvc
import pr_rules
import versions
from core import PlatformError, Report, run

NAME_RE = re.compile(r"^[a-z]([a-z0-9-]{0,38}[a-z0-9])?$")
NAME_HINT = "lowercase letters, digits and hyphens, at most 40 characters, starting with a letter and not ending with a hyphen"


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cplat cluster", description=__doc__)
    sub = p.add_subparsers(dest="verb", required=True)
    n = sub.add_parser("new", help="create a cluster repo from templates/cluster-gitops")
    n.add_argument("name")
    n.add_argument("--org", help="GitHub org/user (default: your gh login)")
    n.add_argument("--public", action="store_true", help="create the GitHub repo as public (default: private)")
    n.add_argument("--dir", default=".", help="parent directory for the new repo (default: current directory)")
    n.add_argument("--no-github", action="store_true")
    n.add_argument("--ref", default="main")
    n.add_argument("--skip-tasks", action="store_true")
    n.add_argument("--server", help="the API server Argo CD deploys to (default: the cluster Argo CD runs in)")
    n.add_argument("--operators", default="", metavar="A,B", help="cluster-level operators, comma-separated (cluster.yaml operators)")
    n.add_argument("--secret-store", metavar="NAME", help="the ClusterSecretStore systems read secrets from (needs external-secrets)")
    _common(n)
    a = sub.add_parser("add", help="register a system's gitops repo")
    a.add_argument("repo", metavar="OWNER/REPO")
    a.add_argument("--name", help="the system, when the repo holds several")
    a.add_argument("--repo-dir", default=".")
    _common(a)
    r = sub.add_parser("remove", help="unregister a system")
    r.add_argument("system")
    r.add_argument("--repo-dir", default=".")
    _common(r)
    return p


# ---------------- new ----------------

def _new_steps(org: str, name: str, operators: bool = False) -> list[str]:
    return [
        f"cd {name}",
        *([] if operators else ["list the operators the cluster installs in cluster.yaml (operators: [...]) and run devbox run render"]),
        f"let CI read the systems: gh secret set SYSTEMS_TOKEN -R {org}/{name} (a fine-grained token with Contents: read on the system repos)",
        "/cluster:add <owner>/<system-gitops-repo> for each system",
        "once per cluster: KUBE_CONTEXT=<ctx> REPO_TOKEN=<read-only token> devbox run bootstrap (local: devbox run cluster-up)",
    ]


URL_RE = re.compile(r"https?://\S+")
STORE_RE = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?(\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*$")


def _properties(ns: argparse.Namespace) -> list[str]:
    """`--data` answers for cluster.yaml's server, operators and secretStore, checked as the cluster render checks them (#259)."""
    data: list[str] = []
    if ns.server:
        if not URL_RE.fullmatch(ns.server):
            raise PlatformError(f"--server '{ns.server}' must be an http(s) URL")
        data.append(f"server={ns.server}")
    ops = [o.strip() for o in (ns.operators or "").split(",") if o.strip()]
    known = sorted(versions.current()[1])
    for o in ops:
        if o not in known:
            raise PlatformError(f"--operators: '{o}' is not an operator", hint=f"allowed: {', '.join(known)}")
    if len(set(ops)) != len(ops):
        raise PlatformError("--operators lists an operator twice")
    if ops:
        data.append(f"operators={','.join(ops)}")
    if ns.secret_store:
        if not (len(ns.secret_store) <= 253 and STORE_RE.match(ns.secret_store)):
            raise PlatformError(f"--secret-store '{ns.secret_store}' must be a lowercase DNS name")
        if "external-secrets" not in ops:
            raise PlatformError("--secret-store needs external-secrets in --operators")
        data.append(f"secret_store={ns.secret_store}")
    return data


def cmd_new(ns: argparse.Namespace) -> Report:
    name = ns.name
    if not NAME_RE.match(name):
        raise PlatformError(f"invalid cluster name '{name}'", hint=NAME_HINT)
    props = _properties(ns)
    org = ns.org or ("" if ns.no_github else core.gh_login()) or "ika100"
    if not ns.no_github and core.has_gh() and run(["gh", "repo", "view", f"{org}/{name}"], check=False).returncode == 0:
        raise PlatformError(f"GitHub repository {org}/{name} already exists", hint="choose another name")
    argv = [name, "--description", f"Cluster repo for {name}", "--shape", "cluster-gitops", "--org", org, "--data", f"owner={org}",
            "--dir", ns.dir, "--ref", ns.ref]
    for d in props:
        argv += ["--data", d]
    for flag, on in (("--public", ns.public), ("--no-github", ns.no_github), ("--skip-tasks", ns.skip_tasks)):
        if on:
            argv.append(flag)
    req = newsvc.resolve(argv)
    title = f"New cluster repo: {org}/{name}"
    if ns.dry_run:
        r = newsvc.plan(req)
        extra: list[str] = []
    else:
        r = newsvc.execute(req)
        extra = r.next_steps[len(newsvc._next_steps(req)):]
    r.title = title
    r.next_steps = _new_steps(org, name, bool(ns.operators.strip())) + extra
    return r


# ---------------- add / remove ----------------

def _repo(ns: argparse.Namespace) -> Path:
    repo = Path(ns.repo_dir)
    if not (repo / "cluster.yaml").is_file():
        raise PlatformError(f"not a cluster repo: {ns.repo_dir} has no cluster.yaml", hint="run it in the cluster repo (/cluster:new creates one)")
    return repo


def _systems(repo: Path) -> dict:
    try:
        doc = yaml.safe_load((repo / "cluster.yaml").read_text())
    except yaml.YAMLError as e:
        raise PlatformError(f"cluster.yaml is not valid YAML ({str(e).splitlines()[0]})") from None
    systems = doc.get("systems") if isinstance(doc, dict) else None
    return systems if isinstance(systems, dict) else {}


def _org_of(repo: Path) -> str:
    doc = yaml.safe_load((repo / "cluster.yaml").read_text()) or {}
    if isinstance(doc, dict) and isinstance(doc.get("org"), str):
        return doc["org"]
    try:
        answers = yaml.safe_load((repo / ".copier-answers.yml").read_text()) or {}
    except (OSError, yaml.YAMLError):
        answers = {}
    return answers.get("github_org") or (doc.get("owner") if isinstance(doc, dict) else "") or ""


def _gh_error(res) -> str:
    lines = (res.stderr or res.stdout or "").strip().splitlines()
    return lines[-1] if lines else f"gh exited {res.returncode}"


def discover(slug: str) -> list[str]:
    """The systems `applications/<d>/system.yaml` on the repo's main."""
    hint = "check the name and that your gh login can read it"
    top = run(["gh", "api", f"repos/{slug}/contents?ref=main"], check=False)  # the repo itself must be readable
    if top.returncode != 0:
        raise PlatformError(f"cannot read {slug}: {_gh_error(top)}", hint=hint)
    res = run(["gh", "api", f"repos/{slug}/contents/applications?ref=main"], check=False)
    if res.returncode != 0:
        raise PlatformError(f"{slug} is not a system's gitops repo: no applications/<system>/system.yaml on main")
    try:
        entries = json.loads(res.stdout)
    except ValueError:
        raise PlatformError(f"cannot read {slug}: unexpected answer from gh", hint="check the name and that your gh login can read it") from None
    names = [e["name"] for e in entries if isinstance(e, dict) and e.get("type") == "dir"]
    found = [d for d in names if run(["gh", "api", f"repos/{slug}/contents/applications/{d}/system.yaml?ref=main"], check=False).returncode == 0]
    return found


def _dump(y, data) -> str:
    buf = io.StringIO()
    y.dump(data, buf)
    return buf.getvalue()


def _block(m: CommentedMap) -> CommentedMap:
    m.fa.set_block_style()
    return m


def _edit(repo: Path, change) -> str:
    """Apply `change(systems)` to cluster.yaml with comments preserved; returns the original text."""
    path = repo / "cluster.yaml"
    original = path.read_text()
    y = gitops._yaml()
    data = y.load(original)
    systems = data.get("systems")
    if not isinstance(systems, CommentedMap):
        systems = CommentedMap()
        data["systems"] = systems
    change(systems)
    if systems:
        _block(systems)
    else:
        systems.fa.set_flow_style()
    path.write_text(_dump(y, data))
    return original


def _render(repo: Path, original: str) -> None:
    res = run(["uv", "run", "scripts/render.py"], cwd=repo, check=False)
    if res.returncode != 0:
        (repo / "cluster.yaml").write_text(original)
        lines = [ln for ln in (res.stderr or res.stdout or "").strip().splitlines() if ln.strip()]
        text = lines[-1] if lines else f"scripts/render.py exited {res.returncode}"
        raise PlatformError(re.sub(r"^ERROR:\s*", "", text))


def _pr(repo: Path, branch: str, title: str, body: str) -> str:
    title = pr_rules.fit(title)
    run(["git", "checkout", "-q", "-b", branch], cwd=repo)
    run(["git", "add", "cluster.yaml", "cluster"], cwd=repo)
    run(["git", *core.git_identity(repo), "commit", "-q", "-s", "-m", title], cwd=repo)
    run(["git", "push", "-q", "-u", "origin", branch], cwd=repo)
    out = run(["gh", "pr", "create", "--base", "main", "--title", title, "--body", body], cwd=repo).stdout.strip().splitlines()
    return out[-1] if out else ""


def _preflight(repo: Path, system: str, slug: str) -> None:
    """Run this cluster repo's own check (`scripts/check.py`, the CI job) with the system added, then put cluster.yaml back:
    a system the check rejects is not registered, and no PR is opened for it (#263). Problems of other systems do not stop it."""
    entry = lambda s: s.__setitem__(system, _block(CommentedMap([("repo", slug)])))   # noqa: E731
    original = _edit(repo, entry)
    try:
        res = run(["uv", "run", "scripts/check.py"], cwd=repo, check=False)
    finally:
        (repo / "cluster.yaml").write_text(original)
    mine = re.compile(rf"^ERROR: {re.escape(system)}[ :(]")
    errs = [ln.removeprefix("ERROR: ") for ln in (res.stdout or "").splitlines() if mine.match(ln)]
    if errs:
        raise PlatformError(f"{system} ({slug}) fails this cluster's check, nothing was changed:\n  " + "\n  ".join(errs),
                            hint=f"fix it in {slug} (or list the missing operators in cluster.yaml), then run cluster add again")


def cmd_add(ns: argparse.Namespace) -> Report:
    repo = _repo(ns)
    gitops.require_clean(repo)
    slug = ns.repo
    found = discover(slug)
    if not found:
        raise PlatformError(f"{slug} is not a system's gitops repo: no applications/<system>/system.yaml on main")
    if ns.name:
        if ns.name not in found:
            raise PlatformError(f"{slug} has no applications/{ns.name}/system.yaml on main")
        system = ns.name
    elif len(found) > 1:
        raise PlatformError(f"{slug} holds several systems ({', '.join(found)}): pass --name")
    else:
        system = found[0]
    for key, entry in _systems(repo).items():
        listed = entry.get("repo") if isinstance(entry, dict) else None
        if key == system or listed == slug:
            raise PlatformError(f"{system} is already registered (systems.{key}: {listed})")
    org = _org_of(repo)
    if org and slug.split("/")[0] != org:
        raise PlatformError(f"{slug} is outside org '{org}'", hint=f"Argo CD reads only https://github.com/{org}")
    title = f"feat(cluster): install {system} from {slug}"
    r = Report(title=f"Register system {system} ({slug})")
    _preflight(repo, system, slug)
    steps = [f"checked {system} against this cluster (scripts/check.py): no problems",
             f"add systems.{system}: {{repo: {slug}}} to cluster.yaml", "run uv run scripts/render.py (cluster/systems/" + system + ".yaml)",
             f"[outward] branch cluster/add-{system}, commit '{title}' (signed off), push and open one PR"]
    r.next_steps = [f"merge it: Argo CD then syncs {slug}'s bootstrap/; the CI check names any operator the system still needs"]
    if ns.dry_run:
        r.will_do = steps
        return r
    original = _edit(repo, lambda s: s.__setitem__(system, _block(CommentedMap([("repo", slug)]))))
    _render(repo, original)
    url = _pr(repo, f"cluster/add-{system}", title, f"Registers system `{system}` ({slug}) in cluster.yaml and renders its Argo CD application.")
    r.did = [steps[0], f"added systems.{system} to cluster.yaml and rendered cluster/", f"opened {url}"]
    r.data = {"system": system, "pr": url}
    return r


def cmd_remove(ns: argparse.Namespace) -> Report:
    repo = _repo(ns)
    gitops.require_clean(repo)
    system = ns.system
    systems = _systems(repo)
    if system not in systems:
        raise PlatformError(f"unknown system '{system}' (registered: {', '.join(systems) or 'none'})")
    kept = (f"kept in the cluster: the namespaces {system}-dev, {system}-staging, {system}-prod, the Argo CD application {system}-root "
            f"and everything it created, and all data stay until a human deletes them (system-{system} has no resources finalizer, "
            "so merging deletes nothing)")
    title = f"feat(cluster): remove {system}"
    r = Report(title=f"Remove system {system}")
    if ns.dry_run:
        r.will_do = [f"remove systems.{system} from cluster.yaml", f"run uv run scripts/render.py (cluster/systems/{system}.yaml disappears)",
                     f"[outward] branch cluster/remove-{system}, commit '{title}' (signed off), push and open one PR", kept]
        return r
    original = _edit(repo, lambda s: s.pop(system))
    _render(repo, original)
    url = _pr(repo, f"cluster/remove-{system}", title, f"Removes system `{system}` and its Argo CD application.\n\n{kept}")
    r.did = [f"removed systems.{system} from cluster.yaml and rendered cluster/", f"opened {url}", kept]
    r.data = {"system": system, "pr": url}
    return r


def main(argv: list[str]) -> int:
    ns = build_parser().parse_args(argv)
    {"new": cmd_new, "add": cmd_add, "remove": cmd_remove}[ns.verb](ns).emit(ns.dry_run, ns.json)
    return 0
