"""Spec 125 acceptance tests, bootstrap and the local cluster: `devbox run bootstrap` (AC-125.9), `local-cluster.sh` with WITH_SYSTEM=0,
`devbox run cluster-up` and `cluster-down` (AC-125.15).

Contract: design.md sections 5 and 6. kubectl, gh, k3d and docker are PATH stubs that log every call (cluster_fixtures.stubs); `sleep`
returns at once, so the 10-minute CRD wait is 200 quick calls. The cluster repo is a shared Copier render of templates/cluster-gitops."""
import os
import re
import shutil
import subprocess

import pytest

from cluster_fixtures import ORG, ROOT, base, cluster_repo, render_ok, script, soft, stubs, sys_doc, system_repo

CTX = "my-ctx"
GITOPS_SCRIPTS = ROOT / "templates" / "gitops-app" / "scripts"


@pytest.fixture()
def world(shared_renders, tmp_path, monkeypatch):
    repo = cluster_repo(shared_renders, tmp_path)
    s = stubs(tmp_path, monkeypatch, extra=("k3d", "docker", "helm", "curl"))
    soft(render_ok, repo, base(operators=["cloudnative-pg", "external-secrets"], systems={"alpha": {"repo": f"{ORG}/alpha-gitops"}}))
    return repo, s


def boot(repo, **env):
    e = {"KUBE_CONTEXT": CTX, "REPO_TOKEN": "tok-123", **env}
    e = {k: v for k, v in e.items() if v is not None}
    base_env = {k: v for k, v in os.environ.items() if k not in ("KUBE_CONTEXT", "REPO_TOKEN")}
    return subprocess.run(["bash", "scripts/bootstrap.sh"], cwd=repo, capture_output=True, text=True, env={**base_env, **e})


def calls(s):
    return [ln for ln in s["kube_log"].read_text().splitlines() if ln.startswith("kubectl ")]


def first(lines, needle, start=0):
    for i in range(start, len(lines)):
        if needle in lines[i]:
            return i
    raise AssertionError(f"{needle!r} not in {lines}")


# ---------------- AC-125.9: bootstrap ----------------

def test_ac_125_9_bootstrap_applies_credential_operators_waits_for_crds_then_systems(world):  # AC-125.9
    repo, s = world
    p = boot(repo)
    assert p.returncode == 0, p.stdout + p.stderr
    c = calls(s)
    cred = first(c, "github-creds")
    ops = first(c, "cluster/operators-root.yaml")
    crd1 = first(c, "get crd clusters.postgresql.cnpg.io")
    crd2 = first(c, "get crd clustersecretstores.external-secrets.io")
    systems = first(c, "cluster/systems-root.yaml")
    assert cred < ops < crd1 < crd2 < systems, c


def test_ac_125_9_the_credential_template_is_for_the_org_and_read_only_token(world):  # AC-125.9
    repo, s = world
    assert boot(repo).returncode == 0
    text = "\n".join(calls(s))
    assert "argocd.argoproj.io/secret-type=repo-creds" in text and f"https://github.com/{ORG}" in text and "tok-123" in text
    assert re.search(r"github-creds", text) and "argocd" in text


def test_ac_125_9_every_kubectl_call_passes_the_context(world):  # AC-125.9
    repo, s = world
    assert boot(repo).returncode == 0
    for ln in calls(s):
        assert re.search(rf"--context[ =]{CTX}\b", ln), ln


def test_ac_125_9_without_kube_context_it_lists_the_contexts_and_exits_1(world):  # AC-125.9
    repo, s = world
    p = boot(repo, KUBE_CONTEXT=None)
    assert p.returncode == 1
    assert "Set KUBE_CONTEXT to the cluster to bootstrap, e.g. KUBE_CONTEXT=my-cluster devbox run bootstrap. Contexts:" in p.stdout + p.stderr
    assert not any("apply" in ln for ln in calls(s))


def test_ac_125_9_without_repo_token_it_names_the_token_and_exits_1(world):  # AC-125.9
    repo, s = world
    p = boot(repo, REPO_TOKEN=None)
    assert p.returncode == 1
    assert f"ERROR: set REPO_TOKEN to a read-only token (Contents: read) for the cluster repo and every system repo under https://github.com/{ORG}" in p.stderr
    assert not any("apply" in ln for ln in calls(s))


def test_ac_125_9_without_argo_cd_it_stops_before_applying_anything(world):  # AC-125.9
    repo, s = world
    p = boot(repo, KUBE_NO_ARGOCD="1")
    assert p.returncode == 1 and f"ERROR: Argo CD is not installed in {CTX} (it is a cluster prerequisite)" in p.stderr
    assert not any("apply" in ln for ln in calls(s))


def test_ac_125_9_stale_rendered_files_stop_the_bootstrap(world):  # AC-125.9
    repo, s = world
    (repo / "cluster" / "operators" / "stray.yaml").write_text("kind: ConfigMap\n")
    p = boot(repo)
    assert p.returncode == 1 and not any("apply" in ln for ln in calls(s))


def test_ac_125_9_a_missing_crd_fails_after_the_wait_naming_the_crd_and_application(world):  # AC-125.9
    repo, s = world
    p = boot(repo, KUBE_NO_CRD="1")
    assert p.returncode == 1
    assert "ERROR: the CRD clusters.postgresql.cnpg.io did not appear within 10 minutes." in p.stderr
    assert f"  fix: inspect the Argo CD application operator-cloudnative-pg: kubectl --context {CTX} -n argocd get application operator-cloudnative-pg -o yaml" in p.stderr
    c = calls(s)
    assert sum("get crd clusters.postgresql.cnpg.io" in ln for ln in c) == 200
    assert not any("cluster/systems-root.yaml" in ln for ln in c), "the systems are applied only after the operators' CRDs"


def test_ac_125_9_running_it_again_applies_the_same_objects(world):  # AC-125.9
    repo, s = world
    assert boot(repo).returncode == 0
    first_run = calls(s)
    s["kube_log"].write_text("")
    assert boot(repo).returncode == 0
    assert calls(s) == first_run


def test_ac_125_9_a_cluster_without_operators_still_applies_both_roots(shared_renders, tmp_path, monkeypatch):  # AC-125.9
    repo = cluster_repo(shared_renders, tmp_path)
    s = stubs(tmp_path, monkeypatch)
    soft(render_ok, repo, base())
    assert boot(repo).returncode == 0
    c = calls(s)
    assert first(c, "cluster/operators-root.yaml") < first(c, "cluster/systems-root.yaml")
    assert not any("get crd" in ln for ln in c)


# ---------------- AC-125.15: local-cluster.sh WITH_SYSTEM=0 ----------------

def gitops_skeleton(tmp_path):
    sk = tmp_path / "bare"
    (sk / "scripts").mkdir(parents=True)
    for f in ("local-cluster.sh", "ports.sh"):
        shutil.copy(GITOPS_SCRIPTS / f, sk / "scripts" / f)
    (sk / ".copier-answers.yml").write_text(f"github_org: {ORG}\n")
    return sk


def up(sk, **env):
    e = {**os.environ, "WITH_ESO": "0", "WITH_KYVERNO": "0", "WITH_LGTM": "0", "WITH_CNPG": "0", "WITH_SEAWEEDFS": "0", "LOCAL_HTTP_PORT": "18099", **env}
    return subprocess.run(["bash", "scripts/local-cluster.sh", "up"], cwd=sk, capture_output=True, text=True, env=e)


def test_ac_125_15_with_system_0_needs_a_cluster_name(tmp_path, monkeypatch):  # AC-125.15
    stubs(tmp_path, monkeypatch, extra=("k3d", "docker", "helm", "curl"))
    sk = gitops_skeleton(tmp_path)
    p = up(sk, WITH_SYSTEM="0")
    assert p.returncode == 2 and "ERROR: WITH_SYSTEM=0 needs LOCAL_CLUSTER" in p.stderr


def test_ac_125_15_with_system_0_creates_the_cluster_and_argo_cd_but_no_system(tmp_path, monkeypatch):  # AC-125.15
    s = stubs(tmp_path, monkeypatch, extra=("k3d", "docker", "helm", "curl"))
    sk = gitops_skeleton(tmp_path)
    p = up(sk, WITH_SYSTEM="0", LOCAL_CLUSTER="e2e-x")
    out = p.stdout + p.stderr
    assert p.returncode == 0, out
    assert "Cluster k3d-e2e-x is ready (no system: WITH_SYSTEM=0) on host port 18099" in out
    log = s["kube_log"].read_text()
    assert "k3d cluster create e2e-x" in log
    assert "github-creds" in log
    assert "bootstrap/" not in log and "operators/root.yaml" not in log
    assert not re.search(r"create (namespace|ns) \S+-(dev|staging|prod)", log) and "ghcr-pull" not in log


# ---------------- AC-125.15: cluster-up and cluster-down ----------------

def test_ac_125_15_cluster_up_builds_the_local_cluster_bootstraps_and_prints_the_urls(world):  # AC-125.15
    repo, s = world
    system_repo(s["fixtures"], f"{ORG}/alpha-gitops", sys_doc("alpha"), hostnames={"alpha": ["api.alpha-dev.localhost"]})
    p = script(repo, "cluster-up.sh", env={"LOCAL_HTTP_PORT": "8098", "STUB_PORT": "8098"})
    out = p.stdout + p.stderr
    assert p.returncode == 0, out
    log = s["kube_log"].read_text()
    assert "k3d cluster create home-local" in log                       # <cluster>-local
    assert "github-creds" in log and "gh-token" in log                   # Argo CD gets the user's gh token for the org
    for env in ("dev", "staging", "prod"):
        assert f"alpha-{env}" in log
    assert "ghcr-pull" in log and "docker-registry" in log and "imagePullSecrets" in log
    kube = [ln for ln in log.splitlines() if ln.startswith("kubectl ")]
    ops, systems = first(kube, "cluster/operators-root.yaml"), first(kube, "cluster/systems-root.yaml")
    assert ops < systems and "--context k3d-home-local" in kube[ops]      # the bootstrap of AC-125.9 against the new cluster
    assert "Exposed: http://api.alpha-dev.localhost:8098/   (alpha, once the workloads are running)" in out
    assert "kubectl --context k3d-home-local -n argocd get applications" in out
    assert "k9s --context k3d-home-local" in out and "devbox run cluster-down" in out


def test_ac_125_15_cluster_up_reuses_a_named_cluster(world):  # AC-125.15
    repo, s = world
    p = script(repo, "cluster-up.sh", env={"LOCAL_CLUSTER": "my-local", "LOCAL_HTTP_PORT": "8098"})
    assert p.returncode == 0, p.stdout + p.stderr
    assert "k3d cluster create my-local" in s["kube_log"].read_text()


def test_ac_125_15_cluster_down_removes_the_local_cluster(world):  # AC-125.15
    repo, s = world
    import json
    recipe = json.loads((repo / "devbox.json").read_text())["shell"]["scripts"]["cluster-down"]
    cmd = recipe if isinstance(recipe, str) else "\n".join(recipe)
    assert "WITH_SYSTEM=0" in cmd and "local-cluster.sh down" in cmd and "-local" in cmd
    p = subprocess.run(["bash", "-c", cmd], cwd=repo, capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "k3d cluster delete home-local" in s["kube_log"].read_text()


def test_ac_125_15_the_scripts_are_valid_bash_and_share_the_system_local_cluster_script(world):  # AC-125.15
    repo, _ = world
    for f in ("bootstrap.sh", "cluster-up.sh", "local-cluster.sh", "ports.sh"):
        assert subprocess.run(["bash", "-n", str(repo / "scripts" / f)]).returncode == 0, f
    assert (repo / "scripts" / "local-cluster.sh").read_bytes() == (GITOPS_SCRIPTS / "local-cluster.sh").read_bytes()
    assert (repo / "scripts" / "ports.sh").read_bytes() == (GITOPS_SCRIPTS / "ports.sh").read_bytes()


def test_ac_125_15_the_cluster_repo_has_no_cluster_ui_recipe(world):  # AC-125.15
    import json
    repo, _ = world
    assert "cluster-ui" not in json.loads((repo / "devbox.json").read_text())["shell"]["scripts"]
