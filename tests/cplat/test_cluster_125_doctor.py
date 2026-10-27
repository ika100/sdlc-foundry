"""Spec 125 acceptance tests, `/platform:doctor` in a cluster repo (AC-125.13).

Contract: design.md section 8. kubectl is faked by replacing `doctor.run` for kubectl commands (as the spec 116 doctor tests do) and
`doctor.shutil.which`; every other command (detect-shape.sh, git) runs for real on a Copier render of templates/cluster-gitops."""
from types import SimpleNamespace

import pytest

import doctor
from cluster_fixtures import ORG, base, cluster_repo, git_repo, platform_module, render_ok, soft


@pytest.fixture()
def repo(shared_renders, tmp_path, monkeypatch):
    r = cluster_repo(shared_renders, tmp_path / "w")
    soft(render_ok, r, base(operators=["cloudnative-pg", "external-secrets", "kyverno"],
                            systems={"todo": {"repo": f"{ORG}/todo-gitops"}, "ai-ops": {"repo": f"{ORG}/ai"}, "gone": {"repo": f"{ORG}/gone"}}))
    soft(git_repo, r, tmp_path)
    return r


def table(name):
    ops = platform_module("render_125_doctor").OPERATORS
    assert name in ops, f"OPERATORS has {name}"
    return ops[name]


def kube(monkeypatch, installed: dict, apps: dict, kubectl=True):
    """installed: operator -> image tag (absent: not installed); apps: system -> 'Synced Healthy' (absent: not found)."""
    monkeypatch.setattr(doctor.shutil, "which", lambda t: f"/usr/bin/{t}" if kubectl else None)
    real = doctor.run
    calls = []

    def fake(cmd, *a, **k):
        if cmd[0] != "kubectl":
            return real(cmd, *a, **k)
        calls.append(cmd)
        text = " ".join(cmd)
        if "deploy" in cmd:
            for op, tag in installed.items():
                if op in text.split("-l")[-1]:
                    return SimpleNamespace(stdout=f"ghcr.io/x/{op}:{tag}@sha256:{'a' * 64}", stderr="", returncode=0)
            return SimpleNamespace(stdout="", stderr="", returncode=0)
        if "application" in cmd or "applications" in cmd:
            for s, state in apps.items():
                if f"system-{s}" in text:
                    return SimpleNamespace(stdout=state, stderr="", returncode=0)
            return SimpleNamespace(stdout="", stderr='Error from server (NotFound): applications.argoproj.io "x" not found', returncode=1)
        if "current-context" in cmd:
            return SimpleNamespace(stdout="k3d-home-local", stderr="", returncode=0)
        return SimpleNamespace(stdout="", stderr="", returncode=0)
    monkeypatch.setattr(doctor, "run", fake)
    return calls


def rows(repo):
    return {c["name"]: c for c in doctor.check_repo(repo)}


def good_versions():
    return {op: table(op)["operator_version"] for op in ("cloudnative-pg", "external-secrets", "kyverno")}


def test_ac_125_13_an_operator_at_the_expected_version_is_ok(repo, monkeypatch):  # AC-125.13
    kube(monkeypatch, good_versions(), {})
    r = rows(repo)
    for op in ("cloudnative-pg", "external-secrets", "kyverno"):
        want = table(op)["operator_version"]
        assert r[f"operator {op}"]["status"] == "ok"
        assert r[f"operator {op}"]["detail"] == f"installed {want}, expected {want} (cluster.yaml)"


def test_ac_125_13_a_leading_v_of_the_image_tag_is_ignored(repo, monkeypatch):  # AC-125.13
    want = table("cloudnative-pg")["operator_version"]
    kube(monkeypatch, {**good_versions(), "cloudnative-pg": f"v{want}"}, {})
    assert rows(repo)["operator cloudnative-pg"]["status"] == "ok"


def test_ac_125_13_a_missing_operator_warns_with_the_bootstrap_fix(repo, monkeypatch):  # AC-125.13
    versions = good_versions()
    del versions["kyverno"]
    kube(monkeypatch, versions, {})
    row = rows(repo)["operator kyverno"]
    want = table("kyverno")["operator_version"]
    assert row["status"] == "warn" and row["detail"] == f"not installed in the current kube context, expected {want} (cluster.yaml)"
    assert row["fix"] == "KUBE_CONTEXT=k3d-home-local devbox run bootstrap (local: devbox run cluster-up)" or \
        row["fix"] == "KUBE_CONTEXT=<ctx> devbox run bootstrap (local: devbox run cluster-up)"


def test_ac_125_13_a_different_version_warns_naming_both_and_the_sync_fix(repo, monkeypatch):  # AC-125.13
    kube(monkeypatch, {**good_versions(), "external-secrets": "0.0.1"}, {})
    row = rows(repo)["operator external-secrets"]
    assert row["status"] == "warn"
    assert row["detail"] == f"installed 0.0.1, expected {table('external-secrets')['operator_version']} (cluster.yaml)"
    assert row["fix"] == "sync operator-external-secrets in Argo CD"


def test_ac_125_13_kyverno_is_found_through_its_selector(repo, monkeypatch):  # AC-125.13
    calls = kube(monkeypatch, good_versions(), {})
    rows(repo)
    deploys = [" ".join(c) for c in calls if "deploy" in c]
    assert any(table("kyverno")["selector"] in c for c in deploys)
    assert any("app.kubernetes.io/name=cloudnative-pg" in c for c in deploys) and any("app.kubernetes.io/name=external-secrets" in c for c in deploys)


def test_ac_125_13_only_listed_operators_get_a_row(shared_renders, tmp_path, monkeypatch):  # AC-125.13
    r = cluster_repo(shared_renders, tmp_path / "w")
    soft(render_ok, r, base(operators=["cloudnative-pg"]))
    soft(git_repo, r, tmp_path)
    kube(monkeypatch, {"cloudnative-pg": table("cloudnative-pg")["operator_version"]}, {})
    names = [n for n in rows(r) if n.startswith("operator ")]
    assert names == ["operator cloudnative-pg"]


def test_ac_125_13_each_system_application_shows_sync_and_health(repo, monkeypatch):  # AC-125.13
    kube(monkeypatch, good_versions(), {"todo": "Synced Healthy", "ai-ops": "OutOfSync Degraded"})
    r = rows(repo)
    assert r["system todo"]["status"] == "ok" and r["system todo"]["detail"] == "system-todo: Synced, Healthy"
    bad = r["system ai-ops"]
    assert bad["status"] == "warn" and bad["detail"] == "system-ai-ops: OutOfSync, Degraded"
    assert bad["fix"] == "kubectl -n argocd get application system-ai-ops -o yaml"
    gone = r["system gone"]
    assert gone["status"] == "warn" and gone["detail"] == "system-gone: no such application in the current kube context"
    assert gone["fix"] in ("KUBE_CONTEXT=<ctx> devbox run bootstrap", "KUBE_CONTEXT=k3d-home-local devbox run bootstrap")


def test_ac_125_13_the_cluster_rows_come_after_the_repo_shape_and_version_rows(repo, monkeypatch):  # AC-125.13
    kube(monkeypatch, good_versions(), {"todo": "Synced Healthy"})
    names = [c["name"] for c in doctor.check_repo(repo)]
    assert names[0] == "repo shape"
    assert names.index("operator cloudnative-pg") > names.index("repo shape")


def test_ac_125_13_without_kubectl_there_are_no_cluster_rows(repo, monkeypatch):  # AC-125.13
    kube(monkeypatch, {}, {}, kubectl=False)
    assert rows(repo)["repo shape"]["detail"] == "cluster-gitops"
    assert not [n for n in rows(repo) if n.startswith(("operator ", "system "))]


def test_ac_125_13_an_unreadable_cluster_yaml_is_one_warning(repo, monkeypatch):  # AC-125.13
    kube(monkeypatch, {}, {})
    (repo / "cluster.yaml").write_text("a: [unclosed\n")
    r = rows(repo)
    assert r["cluster.yaml"]["status"] == "warn" and r["cluster.yaml"]["fix"] == "devbox run render"
    assert not [n for n in r if n.startswith(("operator ", "system "))]
