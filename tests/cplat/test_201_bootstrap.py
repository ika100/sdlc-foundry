"""Spec 201 acceptance tests, bootstrap and the local clusters: `devbox run bootstrap [<cluster>]` and its identity guard (AC-201.6),
`cluster-up [<cluster>]` and `cluster-down [<cluster>]` (AC-201.6), and the template's own files (AC-201.1, AC-201.4).

Contract: design.md section 5. kubectl answers per kube context (support_201.kube_stub); gh, k3d, docker, helm and curl are PATH stubs
that log every call; `sleep` returns at once, so the 10-minute CRD wait is 200 quick calls."""
import json
import os
import re
import subprocess

import pytest

from cluster_fixtures import ORG, base, cluster_repo, render_ok, script, stubs
from support_201 import HOME, LOCAL, ROOT, kube_calls, kube_stub, multi, render_clusters, todo

CTX = "my-ctx"
REPO_URL = f"https://github.com/{ORG}/home"
TOOLS = ("k3d", "docker", "helm", "curl")


@pytest.fixture()
def world(shared_renders, tmp_path, monkeypatch):
    repo = cluster_repo(shared_renders, tmp_path)
    stubs(tmp_path, monkeypatch, extra=TOOLS)
    log = kube_stub(tmp_path, monkeypatch, reachable=(CTX, "k3d-home-local", "k3d-home-home"))
    return repo, log


def boot(repo, name=None, **env):
    e = {"KUBE_CONTEXT": CTX, "REPO_TOKEN": "tok-123", **env}
    e = {k: v for k, v in e.items() if v is not None}
    base_env = {k: v for k, v in os.environ.items() if k not in ("KUBE_CONTEXT", "REPO_TOKEN")}
    return subprocess.run(["bash", "scripts/bootstrap.sh", *([name] if name else [])], cwd=repo, capture_output=True, text=True, env={**base_env, **e})


def applied(log):
    return [ln for ln in kube_calls(log) if " apply " in f" {ln} " and "--dry-run" not in ln]


def index(lines, needle, start=0):
    for i in range(start, len(lines)):
        if needle in lines[i]:
            return i
    raise AssertionError(f"{needle!r} not in {lines}")


def clustered(repo, exceptions=None, **more):
    render_clusters(repo, multi(operators=["cloudnative-pg", "external-secrets"], systems=todo(), **more), exceptions)


# ---------------- AC-201.6: bootstrap of a named cluster ----------------

def test_ac_201_6_bootstrap_applies_the_credential_then_that_clusters_operators_waits_for_its_crds_then_its_systems(world):  # AC-201.6
    repo, log = world
    clustered(repo, {HOME: {"operators": {"kyverno": True}}})
    p = boot(repo, HOME)
    assert p.returncode == 0, p.stdout + p.stderr
    c = kube_calls(log)
    cred = index(c, "github-creds")
    ops = index(c, "cluster/home/operators-root.yaml")
    crds = [index(c, f"get crd {crd}") for crd in ("clusters.postgresql.cnpg.io", "clustersecretstores.external-secrets.io",
                                                  "namespacedvalidatingpolicies.policies.kyverno.io")]
    systems = index(c, "cluster/home/systems-root.yaml")
    assert cred < ops < min(crds) and max(crds) < systems, c
    assert not any("cluster/local/" in ln for ln in c)


def test_ac_201_6_the_crds_waited_for_are_those_of_the_clusters_own_operators(world):  # AC-201.6
    repo, log = world
    clustered(repo, {HOME: {"operators": {"kyverno": True}}})
    assert boot(repo, LOCAL).returncode == 0
    c = kube_calls(log)
    assert index(c, "get crd clusters.postgresql.cnpg.io") < index(c, "cluster/local/systems-root.yaml")
    assert not any("kyverno" in ln for ln in c), "local does not install kyverno"
    assert not any("cluster/home/" in ln for ln in c)


def test_ac_201_6_the_credential_template_is_for_the_org_with_the_read_only_token(world):  # AC-201.6
    repo, log = world
    clustered(repo)
    assert boot(repo, LOCAL).returncode == 0
    text = "\n".join(kube_calls(log))
    assert "argocd.argoproj.io/secret-type=repo-creds" in text and f"https://github.com/{ORG}" in text and "tok-123" in text


def test_ac_201_6_every_kubectl_call_passes_the_context(world):  # AC-201.6
    repo, log = world
    clustered(repo)
    assert boot(repo, HOME).returncode == 0
    for ln in kube_calls(log):
        assert re.search(rf"--context[ =]{CTX}\b", ln), ln


def test_ac_201_6_a_missing_crd_fails_after_ten_minutes_naming_the_crd_and_the_application(world, monkeypatch):  # AC-201.6
    repo, log = world
    clustered(repo)
    p = boot(repo, HOME, KUBE_NO_CRD="1")
    assert p.returncode == 1
    assert "ERROR: the CRD clusters.postgresql.cnpg.io did not appear within 10 minutes." in p.stderr
    assert f"kubectl --context {CTX} -n argocd get application operator-cloudnative-pg -o yaml" in p.stderr
    c = kube_calls(log)
    assert sum("get crd clusters.postgresql.cnpg.io" in ln for ln in c) == 200
    assert not any("cluster/home/systems-root.yaml" in ln for ln in c), "the systems follow the operators' CRDs"


def test_ac_201_6_running_it_again_applies_the_same_objects(world):  # AC-201.6
    repo, log = world
    clustered(repo)
    assert boot(repo, HOME).returncode == 0
    first = kube_calls(log)
    log.write_text("")
    assert boot(repo, HOME).returncode == 0
    assert kube_calls(log) == first


# ---------------- AC-201.6: the cluster name ----------------

def test_ac_201_6_without_a_name_a_repo_with_clusters_lists_them_and_changes_nothing(world):  # AC-201.6
    repo, log = world
    clustered(repo)
    p = boot(repo)
    assert p.returncode == 1
    assert "ERROR: name the cluster to bootstrap: devbox run bootstrap <cluster> (clusters: local, home)" in p.stderr
    assert applied(log) == []


def test_ac_201_6_an_unknown_name_lists_the_clusters_and_changes_nothing(world):  # AC-201.6
    repo, log = world
    clustered(repo)
    p = boot(repo, "edge")
    assert p.returncode == 1 and "ERROR: unknown cluster 'edge' (clusters: local, home)" in p.stderr
    assert applied(log) == []


def test_ac_201_6_the_name_is_optional_in_a_repo_without_clusters(world):  # AC-201.6
    repo, log = world
    render_ok(repo, base(operators=["cloudnative-pg"], systems={"todo": {"repo": f"{ORG}/todo-gitops"}}))
    p = boot(repo)
    assert p.returncode == 0, p.stdout + p.stderr
    c = kube_calls(log)
    assert index(c, "cluster/operators-root.yaml") < index(c, "cluster/systems-root.yaml")
    log.write_text("")
    assert boot(repo, "home").returncode == 0, "the cluster's own name is accepted"


def test_ac_201_6_another_name_in_a_repo_without_clusters_is_unknown(world):  # AC-201.6
    repo, log = world
    render_ok(repo, base(operators=["cloudnative-pg"]))
    p = boot(repo, "edge")
    assert p.returncode == 1 and "ERROR: unknown cluster 'edge' (this repo has one cluster: home)" in p.stderr
    assert applied(log) == []


# ---------------- AC-201.6: the identity guard ----------------

def test_ac_201_6_a_context_that_runs_another_cluster_of_this_repo_stops_the_bootstrap(world):  # AC-201.6
    repo, log = world
    clustered(repo)
    p = boot(repo, HOME, KUBE_OPERATORS_SOURCE=f"{REPO_URL} cluster/local/operators")
    assert p.returncode == 1
    assert (f"ERROR: {CTX} already runs cluster local of this repo (platform-operators syncs cluster/local/operators); "
            "bootstrapping home there would replace it. Nothing was changed.") in p.stderr
    assert "  fix: pass the kube context of home: KUBE_CONTEXT=<its context> devbox run bootstrap home" in p.stderr
    assert applied(log) == [], "not one object applied"
    assert not any("create" in ln and "secret" in ln for ln in kube_calls(log)), "no credential written either"


def test_ac_201_6_the_same_cluster_may_be_bootstrapped_again(world):  # AC-201.6
    repo, log = world
    clustered(repo)
    p = boot(repo, HOME, KUBE_OPERATORS_SOURCE=f"{REPO_URL} cluster/home/operators")
    assert p.returncode == 0, p.stderr


def test_ac_201_6_the_one_cluster_tree_may_be_taken_over_by_the_first_cluster_only(world):  # AC-201.6
    repo, log = world
    clustered(repo)
    assert boot(repo, LOCAL, KUBE_OPERATORS_SOURCE=f"{REPO_URL} cluster/operators").returncode == 0
    log.write_text("")
    p = boot(repo, HOME, KUBE_OPERATORS_SOURCE=f"{REPO_URL} cluster/operators")
    assert p.returncode == 1 and "bootstrapping home there would replace it. Nothing was changed." in p.stderr
    assert applied(log) == []


def test_ac_201_6_an_application_of_another_repo_is_not_this_repos_cluster(world):  # AC-201.6
    repo, log = world
    clustered(repo)
    p = boot(repo, HOME, KUBE_OPERATORS_SOURCE=f"https://github.com/{ORG}/elsewhere cluster/local/operators")
    assert p.returncode == 0, p.stderr


# ---------------- AC-201.6: cluster-up and cluster-down ----------------

def up(repo, *args, **env):
    return script(repo, "cluster-up.sh", *args, env={"LOCAL_HTTP_PORT": "8098", "STUB_PORT": "8098", **env})


def test_ac_201_6_cluster_up_builds_the_first_listed_cluster_by_default(world):  # AC-201.6
    repo, log = world
    clustered(repo)
    p = up(repo)
    out = p.stdout + p.stderr
    assert p.returncode == 0, out
    text = log.read_text()
    assert "k3d cluster create home-local" in text
    c = kube_calls(log)
    assert index(c, "cluster/local/operators-root.yaml") < index(c, "cluster/local/systems-root.yaml")
    assert "--context k3d-home-local" in c[index(c, "cluster/local/operators-root.yaml")]
    assert "Record the context for cplat: kube_contexts: {local: k3d-home-local} in ~/.config/sdlc-foundry/settings.yml" in out


def test_ac_201_6_cluster_up_creates_only_the_namespaces_of_the_environments_of_that_cluster(world):  # AC-201.6
    repo, log = world
    clustered(repo)
    assert up(repo, LOCAL).returncode == 0
    text = log.read_text()
    assert "namespace todo-dev" in text and "namespace todo-staging" in text and "namespace todo-prod" not in text


def test_ac_201_6_cluster_up_for_a_named_cluster_builds_that_cluster(world):  # AC-201.6
    repo, log = world
    clustered(repo)
    p = up(repo, HOME)
    assert p.returncode == 0, p.stdout + p.stderr
    text = log.read_text()
    assert "k3d cluster create home-home" in text, "LOCAL_CLUSTER defaults to <cluster>-<name>"
    assert "namespace todo-prod" in text and "namespace todo-dev" not in text
    c = kube_calls(log)
    assert any("cluster/home/operators-root.yaml" in ln for ln in c) and not any("cluster/local/" in ln for ln in c)
    assert "Record the context for cplat: kube_contexts: {home: k3d-home-home}" in p.stdout + p.stderr


def test_ac_201_6_cluster_up_without_clusters_behaves_as_before(world):  # AC-201.6
    repo, log = world
    render_ok(repo, base(operators=["cloudnative-pg"]))
    p = up(repo)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "k3d cluster create home-local" in log.read_text()
    assert "Record the context for cplat" not in p.stdout + p.stderr


def test_ac_201_6_cluster_down_removes_the_named_cluster(world):  # AC-201.6
    repo, log = world
    clustered(repo)
    recipe = json.loads((repo / "devbox.json").read_text())["shell"]["scripts"]["cluster-down"]
    assert "scripts/cluster-down.sh" in (recipe if isinstance(recipe, str) else "\n".join(recipe))
    p = script(repo, "cluster-down.sh", HOME)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "k3d cluster delete home-home" in log.read_text()


def test_ac_201_6_cluster_down_defaults_to_the_first_listed_cluster(world):  # AC-201.6
    repo, log = world
    clustered(repo)
    assert script(repo, "cluster-down.sh").returncode == 0
    assert "k3d cluster delete home-local" in log.read_text()


# ---------------- the template ----------------

def test_ac_201_1_validate_builds_every_tree_and_the_copier_file_keeps_the_hand_edited_directories(world):  # AC-201.1
    repo, _ = world
    recipe = json.loads((repo / "devbox.json").read_text())["shell"]["scripts"]["validate"]
    text = recipe if isinstance(recipe, str) else "\n".join(recipe)
    assert "--trees" in text and "kustomize build" in text and "kubeconform" in text
    copier = (ROOT / "templates" / "cluster-gitops" / "copier.yml").read_text()
    skip = copier.split("_skip_if_exists:")[1].split("_exclude:")[0]
    assert "clusters/**" in skip and ".platform/**" in skip


def test_ac_201_6_the_scripts_are_valid_bash(world):  # AC-201.6
    repo, _ = world
    for f in ("bootstrap.sh", "cluster-up.sh", "cluster-down.sh"):
        assert (repo / "scripts" / f).is_file(), f
        assert subprocess.run(["bash", "-n", str(repo / "scripts" / f)]).returncode == 0, f
