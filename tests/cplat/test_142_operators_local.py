"""Spec 142 (AC-142.2): after the system plan declared Postgres, `/system:ship` stopped for a human `devbox run bootstrap` on
the local cluster (journey 2026-11-05). On the cluster of `devbox run cluster-up` the run now applies new operators itself;
on any other cluster it stays a human step."""
import subprocess

import appship
import pytest

ROOT_APPLIED: list[bool] = []

def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture()
def gitops(tmp_path, monkeypatch):
    repo = tmp_path / "shop-gitops"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    for k, v in (("user.name", "t"), ("user.email", "t@example.com"), ("commit.gpgsign", "false")):
        git(repo, "config", k, v)
    (repo / "README.md").write_text("x\n")
    git(repo, "add", "-A"); git(repo, "commit", "-qm", "init")
    (repo / "operators/apps").mkdir(parents=True)
    (repo / "operators/root.yaml").write_text("kind: Application\n")
    (repo / "operators/apps/cloudnative-pg.yaml").write_text("kind: Application\n")
    git(repo, "add", "-A"); git(repo, "commit", "-qm", "feat(compose): postgres (#11)")
    monkeypatch.setattr(appship, "_land_main", lambda r: None)
    calls = []
    ROOT_APPLIED.clear()
    real = appship.run

    def run(cmd, **kw):
        if cmd[:1] == ["kubectl"]:
            return subprocess.CompletedProcess(cmd, 0 if ROOT_APPLIED else 1, "", "")
        if cmd[:2] == ["devbox", "run"]:
            calls.append((cmd, kw.get("env")))
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return real(cmd, **kw)
    monkeypatch.setattr(appship, "run", run)
    return repo, calls


def test_the_local_cluster_gets_the_new_operators_without_asking_ac_142_2(gitops):  # AC-142.2
    repo, calls = gitops
    lines, steps = appship.install_operators(repo, "k3d-shop-local")
    assert calls == [(["devbox", "run", "bootstrap"], {"KUBE_CONTEXT": "k3d-shop-local"})]
    assert steps == [] and "applied them on the local cluster k3d-shop-local" in lines[0]


def test_a_cluster_with_platform_operators_gets_new_operators_from_git_522(gitops):
    """#522: once operators/root.yaml is applied, a new operator file arrives through git; nobody runs bootstrap."""
    repo, calls = gitops
    ROOT_APPLIED.append(True)              # kubectl finds the application platform-operators
    for ctx in ("k3d-shop-local", "prod-eu"):
        lines, steps = appship.install_operators(repo, ctx)
        assert calls == [] and steps == [] and "platform-operators" in lines[0]


def test_another_cluster_keeps_the_human_step_ac_142_2(gitops):  # AC-142.2
    repo, calls = gitops
    _lines, steps = appship.install_operators(repo, "prod-eu")
    assert calls == [] and steps == ["apply the new operators: KUBE_CONTEXT=prod-eu devbox run bootstrap (in shop-gitops)"]


def test_no_operator_change_does_nothing_ac_142_2(gitops):  # AC-142.2
    repo, calls = gitops
    (repo / "README.md").write_text("y\n")
    git(repo, "commit", "-qam", "docs")
    assert appship.install_operators(repo, "k3d-shop-local") == ([], []) and calls == []
