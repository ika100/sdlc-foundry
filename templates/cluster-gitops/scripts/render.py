#!/usr/bin/env python3
# /// script
# dependencies = ["pyyaml"]
# ///
"""Render cluster/ from cluster.yaml (spec 125).

cluster.yaml is the only hand-edited file of a cluster repo; this script derives every file under cluster/:
  cluster/operators-root.yaml       Argo CD application platform-operators (directory source cluster/operators)
  cluster/systems-root.yaml         Argo CD application platform-systems (directory source cluster/systems)
  cluster/operators/<op>.yaml       operator-<op>, the same document the system renderer writes (ADR-058)
  cluster/operators/secret-store.yaml   the ClusterSecretStore (with external-secrets)
  cluster/systems/<system>.yaml     system-<system>, syncing bootstrap/ of the system's repo
  cluster/kustomization.yaml        every manifest above (CI only: kustomize build cluster)

With `clusters` in cluster.yaml (spec 201) every listed cluster gets its own tree cluster/<name>/ with the same layout, `clusters/<name>/cluster.yaml`
holds that cluster's exceptions, and a later cluster may stay on an earlier platform release (clusters/<name>/release.yaml, rendered by the
renderer kept in .platform/releases/<release>/).

Usage: render.py [--check | --crds [<cluster>] | --systems | --name | --envs <cluster> | --clusters | --trees | --effective | --render-cluster]
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import system_render  # noqa: E402  (a copy of the gitops-app renderer: its versions table and application builder)

KEYS = ["cluster", "owner", "server", "org", "operators", "secretStore", "clusters", "systems"]
EXCEPTION_KEYS = ["operators", "secretStore", "server"]
ENVS = ["dev", "staging", "prod"]
RELEASE = re.compile(r"\d+\.\d+\.\d+")
DEFAULT_SERVER = "https://kubernetes.default.svc"
DEFAULT_STORE = "platform-secrets"
LABEL = re.compile(r"[a-z0-9]([-a-z0-9]*[a-z0-9])?")
SUBDOMAIN = re.compile(r"[a-z0-9]([-a-z0-9]*[a-z0-9])?(\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*")
OWNER = re.compile(r"[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?")
REPO = re.compile(r"([A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)/([A-Za-z0-9._-]+)")
URL = re.compile(r"https?://\S+")
SYNC_ANNOTATIONS = {"argocd.argoproj.io/sync-wave": "1", "argocd.argoproj.io/sync-options": "SkipDryRunOnMissingResource=true"}


class ClusterError(Exception):
    def __init__(self, message: str, file: str = "cluster.yaml"):
        super().__init__(message)
        self.file = file


def fail(message: str, file: str = "cluster.yaml"):
    raise ClusterError(message, file)


def release_of(root: Path = ROOT) -> str | None:
    """`platform: x.y.z` of .platform-version, else the recorded `_commit` without a leading v (spec 125 decision 6)."""
    def read(name: str) -> dict:
        f = root / name
        try:
            doc = yaml.safe_load(f.read_text()) if f.is_file() else None
        except yaml.YAMLError:
            return {}
        return doc if isinstance(doc, dict) else {}
    value = read(".platform-version").get("platform")
    if value is None:
        value = read(".copier-answers.yml").get("_commit")
    return str(value).removeprefix("v") if value else None


def answers() -> dict:
    f = ROOT / ".copier-answers.yml"
    return (yaml.safe_load(f.read_text()) or {}) if f.is_file() else {}


def load() -> dict:
    f = ROOT / "cluster.yaml"
    if not f.is_file():
        fail("is missing")
    try:
        doc = yaml.safe_load(f.read_text())
    except yaml.YAMLError as err:
        first = (str(err).splitlines() or ["?"])[0]
        fail(f"is not valid YAML ({first})")
    if not isinstance(doc, dict):
        fail("must be a mapping with cluster and owner")
    return doc


def validate(doc: dict, github_org: str) -> dict:
    """The cluster, with every default filled in; the first problem fails with one message."""
    for k in doc:
        if k not in KEYS:
            fail(f"unknown key '{k}' (allowed: {', '.join(KEYS)})")
    if "cluster" not in doc or doc["cluster"] is None:
        fail("cluster is required")
    cluster = doc["cluster"]
    if not (isinstance(cluster, str) and len(cluster) <= 40 and LABEL.fullmatch(cluster)):
        fail(f"cluster: '{cluster}' must be a lowercase DNS label of at most 40 characters")
    owner = doc.get("owner")
    if not (isinstance(owner, str) and owner.strip()):
        fail("owner is required: a non-empty string")
    server = doc.get("server", DEFAULT_SERVER)
    if not (isinstance(server, str) and URL.fullmatch(server)):
        fail("server must be an http(s) URL")
    org = doc.get("org", github_org)
    if not (isinstance(org, str) and OWNER.fullmatch(org)):
        fail("org must be a GitHub owner name")
    if github_org and org != github_org:
        fail(f"org: must be {github_org}, the owner of this repo "
             f"(Argo CD reads this repo and every system with one credential for https://github.com/{github_org})")

    operators = doc.get("operators")
    operators = [] if operators is None else operators
    if not (isinstance(operators, list) and all(isinstance(o, str) for o in operators)):
        fail("operators must be a list of operator names")
    seen: set[str] = set()
    for o in operators:
        if o not in system_render.OPERATORS:
            fail(f"operators: '{o}' is not an operator (allowed: {', '.join(sorted(system_render.OPERATORS))})")
        if o in seen:
            fail(f"operators: '{o}' is listed twice")
        seen.add(o)

    store = None
    if doc.get("secretStore") is not None:
        store = parse_store(doc["secretStore"])
        if "external-secrets" not in operators:
            fail("secretStore needs external-secrets in operators")

    listed: list[str] | None = None
    if "clusters" in doc:
        listed = parse_clusters(doc["clusters"])
    names = listed or []
    shown = ", ".join(names) or "none"
    dirs = ROOT / "clusters"
    for c in names:
        if not (dirs / c / "cluster.yaml").is_file():
            fail(f"clusters: '{c}' has no clusters/{c}/cluster.yaml (create it; empty when the cluster has no exceptions)")
    if dirs.is_dir():
        for d in sorted(p.name for p in dirs.iterdir() if p.is_dir()):
            if d not in names:
                fail(f"clusters/{d}/ belongs to no cluster in clusters (listed: {shown})")

    raw_systems = doc.get("systems")
    raw_systems = {} if raw_systems is None else raw_systems
    if not isinstance(raw_systems, dict):
        fail("systems must be a mapping of system names to {repo: <owner>/<name>}")
    systems: dict[str, str] = {}
    assign: dict[str, dict[str, str] | None] = {}
    first_of: dict[str, str] = {}
    for s, entry in raw_systems.items():
        if not (isinstance(s, str) and LABEL.fullmatch(s)):
            fail(f"systems.{s}: the name must be a lowercase DNS label")
        if not isinstance(entry, dict):
            fail(f"systems.{s} must be {{repo: <owner>/<name>}}")
        for k in entry:
            if k not in ("repo", "environments"):
                fail(f"systems.{s}: unknown key '{k}' (allowed: repo{', environments' if listed else ''})")
        if "repo" not in entry:
            fail(f"systems.{s}: repo is required (<owner>/<name>)")
        repo = entry["repo"]
        m = REPO.fullmatch(repo) if isinstance(repo, str) else None
        if not m:
            fail(f"systems.{s}: repo '{repo}' must be <owner>/<name>")
        if m.group(1).lower() != org.lower():
            fail(f"systems.{s}: repo '{repo}' is outside org '{org}' (Argo CD reads only https://github.com/{org})")
        key = repo.lower()
        if key in first_of:
            fail(f"systems.{s}: repo '{repo}' is already registered as systems.{first_of[key]}")
        first_of[key] = s
        systems[s] = repo
        assign[s] = None
        if "environments" in entry:
            envs = entry["environments"]
            if not isinstance(envs, dict):
                fail(f"systems.{s}.environments must map dev, staging and prod to listed clusters")
            for e, target in envs.items():
                if e not in ENVS:
                    fail(f"systems.{s}.environments: '{e}' is not an environment (allowed: {', '.join(ENVS)})")
                if target not in names:
                    fail(f"systems.{s}.environments.{e}: cluster '{target}' is not listed in clusters (listed: {shown})")
            assign[s] = dict(envs)
    c = {"cluster": cluster, "owner": owner, "server": server, "org": org, "operators": operators, "store": store, "systems": systems,
         "clusters": listed, "assign": assign, "dirs": {}}
    if listed:
        release = release_of()
        for i, name in enumerate(listed):
            c["dirs"][name] = read_cluster_dir(c, name, i == 0, release)
    return c


def parse_store(raw) -> dict:
    if not isinstance(raw, dict):
        fail("secretStore must be a mapping with name and provider")
    for k in raw:
        if k not in ("name", "provider"):
            fail(f"secretStore: unknown key '{k}' (allowed: name, provider)")
    name = raw.get("name", DEFAULT_STORE)
    if not (isinstance(name, str) and len(name) <= 253 and SUBDOMAIN.fullmatch(name)):
        fail(f"secretStore.name: '{name}' must be a lowercase DNS name")
    provider = raw.get("provider")
    if "provider" in raw and not (isinstance(provider, dict) and len(provider) == 1):
        fail("secretStore.provider must be a mapping with exactly one provider, e.g. {vault: {...}}")
    return {"name": name, "provider": provider}


def parse_clusters(raw) -> list[str]:
    if not (isinstance(raw, list) and all(isinstance(n, str) for n in raw)):
        fail("clusters must be a list of cluster names")
    if not raw:
        fail("clusters must list at least one cluster, or be left out")
    seen: set[str] = set()
    for n in raw:
        if not (len(n) <= 40 and LABEL.fullmatch(n)):
            fail(f"clusters: '{n}' must be a lowercase DNS label of at most 40 characters")
        if n in seen:
            fail(f"clusters: '{n}' is listed twice")
        seen.add(n)
    return list(raw)


def read_cluster_dir(c: dict, name: str, first: bool, repo_release: str | None) -> dict:
    """The exceptions of clusters/<name>/cluster.yaml and the release of clusters/<name>/release.yaml, both validated."""
    file = f"clusters/{name}/cluster.yaml"
    try:
        raw = yaml.safe_load((ROOT / file).read_text())
    except yaml.YAMLError as err:
        fail(f"is not valid YAML ({(str(err).splitlines() or ['?'])[0]})", file)
    raw = {} if raw is None else raw
    if not isinstance(raw, dict):
        fail(f"must be a mapping of exceptions ({', '.join(EXCEPTION_KEYS)})", file)
    for k in raw:
        if k not in EXCEPTION_KEYS:
            fail(f"'{k}' is not a shared setting a cluster can override (allowed: {', '.join(EXCEPTION_KEYS)})", file)
    exc: dict = {"operators": {}, "server": None, "store": None}
    ops = raw.get("operators")
    if ops is not None:
        if not (isinstance(ops, dict) and all(isinstance(v, bool) for v in ops.values())):
            fail("operators must map operator names to true or false", file)
        for o, want in ops.items():
            if o not in system_render.OPERATORS:
                fail(f"operators.{o}: '{o}' is not an operator (allowed: {', '.join(sorted(system_render.OPERATORS))})", file)
            if want == (o in c["operators"]):
                fail(f"operators.{o}: {'true' if want else 'false'} is the shared value (cluster.yaml operators); remove it", file)
        exc["operators"] = dict(ops)
    if "server" in raw:
        server = raw["server"]
        if not (isinstance(server, str) and URL.fullmatch(server)):
            fail("server must be an http(s) URL", file)
        exc["server"] = server
    if raw.get("secretStore") is not None:
        try:
            exc["store"] = parse_store(raw["secretStore"])
        except ClusterError as err:
            fail(str(err), file)
    ops_here = effective_operators(c, exc)
    if exc["store"] is not None and "external-secrets" not in ops_here:
        fail(f"secretStore needs external-secrets installed on cluster {name}", file)

    rel_file = f"clusters/{name}/release.yaml"
    release = None
    if (ROOT / rel_file).is_file():
        if first:
            fail(f"the first cluster runs this repo's release {repo_release or 'unknown'}; delete this file", rel_file)
        try:
            doc = yaml.safe_load((ROOT / rel_file).read_text())
        except yaml.YAMLError:
            doc = None
        value = str(doc.get("platform")) if isinstance(doc, dict) and set(doc) == {"platform"} else ""
        if not RELEASE.fullmatch(value):
            fail("must be {platform: <x.y.z>}", rel_file)
        release = value
    return {"exceptions": exc, "release": release}


def effective_operators(c: dict, exc: dict) -> list[str]:
    ops = [o for o in c["operators"] if exc["operators"].get(o) is not False]
    return ops + [o for o, want in exc["operators"].items() if want and o not in ops]


def root_app(name: str, repo_url: str, path: str, server: str, retry: bool) -> dict:
    policy: dict = {"automated": {"prune": True, "selfHeal": True}}
    if retry:
        policy["retry"] = {"limit": 10, "backoff": {"duration": "30s", "factor": 2, "maxDuration": "5m"}}
    return {
        "apiVersion": "argoproj.io/v1alpha1", "kind": "Application", "metadata": {"name": name, "namespace": "argocd"},
        "spec": {"project": "default", "source": {"repoURL": repo_url, "targetRevision": "main", "path": path},
                 "destination": {"server": server, "namespace": "argocd"}, "syncPolicy": policy}}


def system_app(system: str, repo: str, server: str, environments: list[str] | None = None) -> dict:
    """system-<system>: spec 125's form (path bootstrap) without `environments`, else the split form selecting those environments' roots."""
    source: dict = {"repoURL": f"https://github.com/{repo}", "targetRevision": "main", "path": "bootstrap"}
    policy: dict = {"prune": True, "selfHeal": True}
    if environments is not None:
        source["path"] = "bootstrap/environments"
        patterns = [f"*-{e}.yaml" for e in environments]
        if not patterns:
            source["directory"] = {"exclude": "*"}
        else:
            source["directory"] = {"include": patterns[0] if len(patterns) == 1 else "{" + ",".join(patterns) + "}"}
        policy["allowEmpty"] = True
    return {
        "apiVersion": "argoproj.io/v1alpha1", "kind": "Application",
        "metadata": {"name": f"system-{system}", "namespace": "argocd",
                     "labels": {"app.kubernetes.io/managed-by": "cluster-gitops", "app.kubernetes.io/component": "system"}},
        "spec": {"project": "default", "source": source,
                 "destination": {"server": server, "namespace": "argocd"},
                 "syncPolicy": {"automated": policy}}}


def secret_store_docs(store: dict | None) -> list[dict]:
    name = store["name"] if store else DEFAULT_STORE
    provider = store["provider"] if store else None
    docs: list[dict] = []
    if provider is None:
        ns = "secrets-store"
        docs += [
            {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": ns}},
            {"apiVersion": "v1", "kind": "ServiceAccount", "metadata": {"name": "eso-store", "namespace": ns}},
            {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "Role", "metadata": {"name": "eso-store", "namespace": ns},
             "rules": [{"apiGroups": [""], "resources": ["secrets"], "verbs": ["get", "list", "watch"]},
                       {"apiGroups": ["authorization.k8s.io"], "resources": ["selfsubjectrulesreviews"], "verbs": ["create"]}]},
            {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "RoleBinding", "metadata": {"name": "eso-store", "namespace": ns},
             "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "Role", "name": "eso-store"},
             "subjects": [{"kind": "ServiceAccount", "name": "eso-store", "namespace": ns}]},
        ]
        provider = {"kubernetes": {
            "remoteNamespace": ns,
            "server": {"caProvider": {"type": "ConfigMap", "name": "kube-root-ca.crt", "namespace": ns, "key": "ca.crt"}},
            "auth": {"serviceAccount": {"name": "eso-store", "namespace": ns}}}}
    docs.append({"apiVersion": "external-secrets.io/v1", "kind": "ClusterSecretStore",
                 "metadata": {"name": name, "annotations": dict(SYNC_ANNOTATIONS)}, "spec": {"provider": provider}})
    return docs


def render_cluster(spec: dict) -> dict[str, str]:
    """One cluster's tree from the `--render-cluster` JSON (version 1): path from the repo root -> text."""
    if spec.get("version") != 1:
        fail(f"unsupported --render-cluster version {spec.get('version')!r} (this renderer reads version 1)")
    dump = system_render.dump
    tree, server, repo_url = spec["tree"], spec["server"], spec["repo_url"]
    operators, store = spec["operators"], spec.get("store")
    files: dict[str, str] = {
        f"{tree}/operators-root.yaml": dump(root_app("platform-operators", repo_url, f"{tree}/operators", server, True)),
        f"{tree}/systems-root.yaml": dump(root_app("platform-systems", repo_url, f"{tree}/systems", server, False)),
    }
    resources = ["operators-root.yaml", "systems-root.yaml"]
    op_files = []
    for op in operators:
        files[f"{tree}/operators/{op}.yaml"] = dump(system_render.operator_application(op, server))
        op_files.append(f"operators/{op}.yaml")
    if "external-secrets" in operators:
        files[f"{tree}/operators/secret-store.yaml"] = "---\n".join(dump(d) for d in secret_store_docs(store))
        op_files.append("operators/secret-store.yaml")
    if not op_files:
        files[f"{tree}/operators/.gitkeep"] = ""
    sys_files = []
    for s in spec["systems"]:
        files[f"{tree}/systems/{s['name']}.yaml"] = dump(system_app(s["name"], s["repo"], server, s.get("environments")))
        sys_files.append(f"systems/{s['name']}.yaml")
    if not sys_files:
        files[f"{tree}/systems/.gitkeep"] = ""
    files[f"{tree}/kustomization.yaml"] = dump({
        "apiVersion": "kustomize.config.k8s.io/v1beta1", "kind": "Kustomization", "resources": resources + op_files + sys_files})
    return files


def store_text(store: dict | None) -> str:
    if store is None:
        return "none"
    provider = next(iter(store["provider"])) if store["provider"] else "kubernetes (default)"
    return f"name {store['name']}, provider {provider}"


def effective(c: dict | None = None) -> dict:
    """The clusters with their effective settings (`--effective`); raises ClusterError when cluster.yaml is wrong."""
    if c is None:
        c = validate(load(), answers().get("github_org") or "")
    release = release_of()
    listed = c["clusters"]
    out: list[dict] = []
    for i, name in enumerate(listed or [c["cluster"]]):
        exc_lines: list[str] = []
        systems: list[dict] = []
        if listed:
            exc = c["dirs"][name]["exceptions"]
            operators = effective_operators(c, exc)
            for o, want in exc["operators"].items():
                exc_lines.append(f"cluster {name}: operator {o}: " + ("installed (shared: not installed)" if want else "not installed (shared: installed)"))
            if exc["server"] is not None:
                exc_lines.append(f"cluster {name}: server: {exc['server']} (shared: {c['server']})")
            if exc["store"] is not None:
                exc_lines.append(f"cluster {name}: secretStore: {store_text(exc['store'])} (shared: {store_text(c['store'])})")
            server = exc["server"] or c["server"]
            store = cluster_store(c, name)
            pinned = c["dirs"][name]["release"]
            for s, repo in c["systems"].items():
                assigned = c["assign"][s]
                if assigned is None:
                    if i == 0:
                        systems.append({"name": s, "repo": repo, "environments": None})
                else:
                    systems.append({"name": s, "repo": repo, "environments": [e for e in ENVS if assigned.get(e) == name]})
            tree = f"cluster/{name}"
        else:
            operators, server, store, pinned, tree = list(c["operators"]), c["server"], c["store"], None, "cluster"
            systems = [{"name": s, "repo": repo, "environments": None} for s, repo in c["systems"].items()]
        out.append({"name": name, "first": i == 0, "release": pinned or release, "tree": tree, "server": server, "operators": operators,
                    "store": {"name": store["name"], "provider": next(iter(store["provider"])) if store["provider"] else "kubernetes"}
                    if store else None, "exceptions": exc_lines, "systems": systems})
    return {"release": release, "clusters": out}


def cluster_store(c: dict, name: str) -> dict | None:
    """The secret store a cluster installs: its exception, else the shared one; only with external-secrets effective."""
    if not c["clusters"]:
        return c["store"]
    exc = c["dirs"][name]["exceptions"]
    return (exc["store"] or c["store"]) if "external-secrets" in effective_operators(c, exc) else None


def run_kept(cluster: dict, spec: dict) -> dict[str, str]:
    """The tree of a cluster pinned to an earlier release, rendered by the renderer kept for it."""
    x = cluster["release"]
    kept = ROOT / ".platform" / "releases" / x / "render.py"
    file = f"clusters/{cluster['name']}/release.yaml"
    if not kept.is_file():
        fail(f"platform {x} is not kept in .platform/releases/{x}/; promote the cluster: /cluster:promote {cluster['name']}", file)
    p = subprocess.run([sys.executable, str(kept), "--render-cluster"], input=json.dumps(spec), capture_output=True, text=True, cwd=ROOT)
    if p.returncode != 0:
        first = next((ln.strip() for ln in (p.stderr + p.stdout).splitlines() if ln.strip()), f"exit {p.returncode}")
        fail(f"cluster {cluster['name']} (platform {x}): {first.removeprefix('ERROR: ')}", file)
    try:
        files = json.loads(p.stdout)["files"]
        ok = isinstance(files, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in files.items())
    except (ValueError, KeyError, TypeError):
        ok = False
    if not ok:
        fail(f"cluster {cluster['name']} (platform {x}): the kept renderer did not answer with {{\"files\": {{path: text}}}}", file)
    for k in files:
        if not k.startswith(cluster["tree"] + "/") or ".." in k.split("/"):
            fail(f"cluster {cluster['name']} (platform {x}): the kept renderer wrote '{k}', outside {cluster['tree']}/", file)
    return files


def render_files(c: dict, ans: dict, eff: dict | None = None) -> dict[str, str]:
    """Relative path (under the repo root) -> text of every file the render owns."""
    eff = eff or effective(c)
    org = ans.get("github_org") or c["org"]
    repo_url = f"https://github.com/{org}/{ans.get('project_name') or ROOT.name}"
    files: dict[str, str] = {}
    for cl in eff["clusters"]:
        spec = {"version": 1, "tree": cl["tree"], "repo_url": repo_url, "server": cl["server"], "operators": cl["operators"],
                "store": cluster_store(c, cl["name"]), "systems": cl["systems"]}
        if cl["release"] == eff["release"]:
            files.update(render_cluster(spec))
        else:
            files.update(run_kept(cl, spec))
    return files


def behind_lines(eff: dict) -> list[str]:
    first = eff["clusters"][0]
    return [f"BEHIND: cluster {cl['name']} runs platform {cl['release']}, cluster {first['name']} runs {first['release']}; "
            f"promote it with /cluster:promote {cl['name']}" for cl in eff["clusters"][1:] if cl["release"] != first["release"]]


def placements(eff: dict) -> dict[tuple[str, str], str]:
    return {(s["name"], e): cl["name"] for cl in eff["clusters"] for s in cl["systems"] for e in (ENVS if s["environments"] is None else s["environments"])}


def on_disk(first_name: str) -> dict[tuple[str, str], str]:
    """(system, environment) -> cluster as the trees on disk place them (form 125: all three; split form: its include patterns)."""
    old: dict[tuple[str, str], str] = {}
    base = ROOT / "cluster"
    trees = [(first_name, base / "systems")] + [(d.name, d / "systems") for d in sorted(base.iterdir()) if d.is_dir() and d.name != "systems"] \
        if base.is_dir() else []
    for name, folder in trees:
        for f in sorted(folder.glob("*.yaml")) if folder.is_dir() else []:
            try:
                src = yaml.safe_load(f.read_text())["spec"]["source"]
            except (yaml.YAMLError, KeyError, TypeError):
                continue
            include = (src.get("directory") or {}).get("include")
            if src.get("path") == "bootstrap":
                envs = ENVS
            elif isinstance(include, str):
                envs = [e for e in ENVS if f"*-{e}.yaml" in include.strip("{}").split(",")]
            else:
                envs = []
            for e in envs:
                old[(f.stem, e)] = name
    return old


def moved_lines(eff: dict, old: dict[tuple[str, str], str]) -> list[str]:
    new = placements(eff)
    return [f"MOVED: {s} {e}: cluster {old[(s, e)]} -> {new[(s, e)]}; nothing is copied, and its namespace {s}-{e} and data stay on {old[(s, e)]} until a person deletes them"
            for (s, e) in new if (s, e) in old and old[(s, e)] != new[(s, e)]]


def diff(files: dict[str, str]) -> tuple[list[str], list[str]]:
    """(paths to write, stale paths to delete), both relative to the repo root."""
    changed = [p for p, text in files.items() if not (ROOT / p).is_file() or (ROOT / p).read_text() != text]
    base = ROOT / "cluster"
    stale = sorted(p.relative_to(ROOT).as_posix() for p in base.rglob("*") if p.is_file() and p.relative_to(ROOT).as_posix() not in files) \
        if base.is_dir() else []
    return changed, stale


def write(files: dict[str, str]) -> int:
    changed, stale = diff(files)
    for p in changed:
        f = ROOT / p
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(files[p])
    for p in stale:
        (ROOT / p).unlink()
    base = ROOT / "cluster"
    for d in sorted((d for d in base.rglob("*") if d.is_dir()), key=lambda d: len(d.parts), reverse=True):
        if not any(d.iterdir()):
            d.rmdir()
    return len(changed) + len(stale)


def main() -> int:
    flags = sys.argv[1:]
    usage = ("usage: render.py [--check | --crds [<cluster>] | --systems | --name | --envs <cluster> | --clusters | --trees | --effective"
             " | --render-cluster]")
    plain = ("--check", "--systems", "--name", "--clusters", "--trees", "--effective", "--render-cluster")
    flag = flags[0] if flags else ""
    arg = flags[1] if len(flags) == 2 else None
    if len(flags) > 2 or (flags and flag not in plain + ("--crds", "--envs")) or (arg is not None and flag not in ("--crds", "--envs")) \
            or (flag == "--envs" and arg is None):
        print(usage, file=sys.stderr)
        return 2
    if flag == "--render-cluster":
        try:
            print(json.dumps({"files": render_cluster(json.load(sys.stdin))}))
        except (ClusterError, ValueError, KeyError, TypeError) as err:
            print(f"ERROR: --render-cluster: {err if isinstance(err, ClusterError) else 'malformed input (' + repr(err) + ')'}", file=sys.stderr)
            return 1
        return 0
    ans = answers()
    try:
        c = validate(load(), ans.get("github_org") or "")
        eff = effective(c)
        files = render_files(c, ans, eff) if flag in ("", "--check") else {}
    except ClusterError as err:
        print(f"ERROR: {err.file}: {err}", file=sys.stderr)
        return 1
    clusters = eff["clusters"]
    names = ", ".join(cl["name"] for cl in clusters)
    if flag == "--name":
        print(c["cluster"])
    elif flag == "--crds":
        if c["clusters"] and arg is None:
            print(f"ERROR: name the cluster: --crds <cluster> (clusters: {names})", file=sys.stderr)
            return 2
        target = next((cl for cl in clusters if cl["name"] == (arg or c["cluster"])), None)
        if target is None:
            where = f"clusters: {names}" if c["clusters"] else f"this repo has one cluster: {c['cluster']}"
            print(f"ERROR: unknown cluster '{arg}' ({where})", file=sys.stderr)
            return 2
        for op in target["operators"]:
            if system_render.OPERATORS[op]["crd"] is not None:
                print(f"{op} {system_render.OPERATORS[op]['crd']}")
    elif flag == "--systems":
        for s, repo in c["systems"].items():
            print(f"{s} {repo}")
    elif flag == "--envs":
        target = next((cl for cl in clusters if cl["name"] == arg), None)
        if target is None:
            where = f"clusters: {names}" if c["clusters"] else f"this repo has one cluster: {c['cluster']}"
            print(f"ERROR: unknown cluster '{arg}' ({where})", file=sys.stderr)
            return 2
        for s in target["systems"]:
            for e in (ENVS if s["environments"] is None else s["environments"]):
                print(f"{s['name']} {e}")
    elif flag == "--clusters":
        for name in c["clusters"] or []:
            print(name)
    elif flag == "--trees":
        for cl in clusters:
            print(f"{cl['name']} {cl['tree']}")
    elif flag == "--effective":
        print(json.dumps(eff))
    elif flag == "--check":
        if len(files) == 0:
            gate = os.environ.get("GATE_NAME") or "render-check"
            print(f"{gate}: checked nothing: 0 files compared - run `devbox run render` and check cluster.yaml", file=sys.stderr)
            return 1
        changed, stale = diff(files)
        if not changed and not stale:
            print("OK: up to date")
            return 0
        print("ERROR: rendered files are out of date — run `devbox run render`:", file=sys.stderr)
        for p in sorted(changed):
            print(f"  {p}", file=sys.stderr)
        for p in stale:
            print(f"  {p} (stale)", file=sys.stderr)
        return 1
    else:
        old = on_disk(clusters[0]["name"])
        lines = [f"EXCEPTION: {t}" for cl in clusters for t in cl["exceptions"]] + behind_lines(eff) + moved_lines(eff, old)
        for ln in lines:
            print(ln)
        print(f"rendered ({write(files)} file(s) changed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
