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

Usage: render.py [--check | --crds | --systems | --name]
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import system_render  # noqa: E402  (a copy of the gitops-app renderer: its versions table and application builder)

KEYS = ["cluster", "owner", "server", "org", "operators", "secretStore", "systems"]
DEFAULT_SERVER = "https://kubernetes.default.svc"
DEFAULT_STORE = "platform-secrets"
LABEL = re.compile(r"[a-z0-9]([-a-z0-9]*[a-z0-9])?")
SUBDOMAIN = re.compile(r"[a-z0-9]([-a-z0-9]*[a-z0-9])?(\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*")
OWNER = re.compile(r"[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?")
REPO = re.compile(r"([A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)/([A-Za-z0-9._-]+)")
URL = re.compile(r"https?://\S+")
SYNC_ANNOTATIONS = {"argocd.argoproj.io/sync-wave": "1", "argocd.argoproj.io/sync-options": "SkipDryRunOnMissingResource=true"}


class ClusterError(Exception):
    pass


def fail(message: str):
    raise ClusterError(message)


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
        raw = doc["secretStore"]
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
        store = {"name": name, "provider": provider}
        if "external-secrets" not in operators:
            fail("secretStore needs external-secrets in operators")

    raw_systems = doc.get("systems")
    raw_systems = {} if raw_systems is None else raw_systems
    if not isinstance(raw_systems, dict):
        fail("systems must be a mapping of system names to {repo: <owner>/<name>}")
    systems: dict[str, str] = {}
    first_of: dict[str, str] = {}
    for s, entry in raw_systems.items():
        if not (isinstance(s, str) and LABEL.fullmatch(s)):
            fail(f"systems.{s}: the name must be a lowercase DNS label")
        if not isinstance(entry, dict):
            fail(f"systems.{s} must be {{repo: <owner>/<name>}}")
        for k in entry:
            if k != "repo":
                fail(f"systems.{s}: unknown key '{k}' (allowed: repo)")
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
    return {"cluster": cluster, "owner": owner, "server": server, "org": org, "operators": operators, "store": store, "systems": systems}


def root_app(name: str, repo_url: str, path: str, server: str, retry: bool) -> dict:
    policy: dict = {"automated": {"prune": True, "selfHeal": True}}
    if retry:
        policy["retry"] = {"limit": 10, "backoff": {"duration": "30s", "factor": 2, "maxDuration": "5m"}}
    return {
        "apiVersion": "argoproj.io/v1alpha1", "kind": "Application", "metadata": {"name": name, "namespace": "argocd"},
        "spec": {"project": "default", "source": {"repoURL": repo_url, "targetRevision": "main", "path": path},
                 "destination": {"server": server, "namespace": "argocd"}, "syncPolicy": policy}}


def system_app(system: str, repo: str, server: str) -> dict:
    return {
        "apiVersion": "argoproj.io/v1alpha1", "kind": "Application",
        "metadata": {"name": f"system-{system}", "namespace": "argocd",
                     "labels": {"app.kubernetes.io/managed-by": "cluster-gitops", "app.kubernetes.io/component": "system"}},
        "spec": {"project": "default",
                 "source": {"repoURL": f"https://github.com/{repo}", "targetRevision": "main", "path": "bootstrap"},
                 "destination": {"server": server, "namespace": "argocd"},
                 "syncPolicy": {"automated": {"prune": True, "selfHeal": True}}}}


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


def render_files(c: dict, ans: dict) -> dict[str, str]:
    """Relative path (under the repo root) -> text of every file the render owns."""
    dump = system_render.dump
    server = c["server"]
    org = ans.get("github_org") or c["org"]
    repo_url = f"https://github.com/{org}/{ans.get('project_name') or ROOT.name}"
    files: dict[str, str] = {
        "cluster/operators-root.yaml": dump(root_app("platform-operators", repo_url, "cluster/operators", server, True)),
        "cluster/systems-root.yaml": dump(root_app("platform-systems", repo_url, "cluster/systems", server, False)),
    }
    resources = ["operators-root.yaml", "systems-root.yaml"]
    op_files = []
    for op in c["operators"]:
        files[f"cluster/operators/{op}.yaml"] = dump(system_render.operator_application(op, server))
        op_files.append(f"operators/{op}.yaml")
    if "external-secrets" in c["operators"]:
        files["cluster/operators/secret-store.yaml"] = "---\n".join(dump(d) for d in secret_store_docs(c["store"]))
        op_files.append("operators/secret-store.yaml")
    if not op_files:
        files["cluster/operators/.gitkeep"] = ""
    sys_files = []
    for s, repo in c["systems"].items():
        files[f"cluster/systems/{s}.yaml"] = dump(system_app(s, repo, server))
        sys_files.append(f"systems/{s}.yaml")
    if not sys_files:
        files["cluster/systems/.gitkeep"] = ""
    files["cluster/kustomization.yaml"] = dump({
        "apiVersion": "kustomize.config.k8s.io/v1beta1", "kind": "Kustomization", "resources": resources + op_files + sys_files})
    return files


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
    if len(flags) > 1 or (flags and flags[0] not in ("--check", "--crds", "--systems", "--name")):
        print("usage: render.py [--check | --crds | --systems | --name]", file=sys.stderr)
        return 2
    flag = flags[0] if flags else ""
    ans = answers()
    try:
        c = validate(load(), ans.get("github_org") or "")
        files = render_files(c, ans)
    except ClusterError as err:
        print(f"ERROR: cluster.yaml: {err}", file=sys.stderr)
        return 1
    if flag == "--name":
        print(c["cluster"])
    elif flag == "--crds":
        for op in c["operators"]:
            if system_render.OPERATORS[op]["crd"] is not None:
                print(f"{op} {system_render.OPERATORS[op]['crd']}")
    elif flag == "--systems":
        for s, repo in c["systems"].items():
            print(f"{s} {repo}")
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
        print(f"rendered ({write(files)} file(s) changed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
