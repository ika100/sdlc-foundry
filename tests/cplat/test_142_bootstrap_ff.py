"""Spec 142 (AC-142.3): bootstrap applies what main holds on GitHub. In the journey of 2026-11-05 the local main was behind
the merged gitops PR, so the first `devbox run bootstrap` found no operators/ and applied nothing."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture()
def behind(tmp_path):
    """A clone of a gitops repo whose origin/main has one more commit (operators/root.yaml) than its main."""
    origin, repo, other = tmp_path / "origin.git", tmp_path / "repo", tmp_path / "other"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    for d in (repo, other):
        subprocess.run(["git", "clone", "-q", str(origin), str(d)], check=True, capture_output=True)
        for k, v in (("user.name", "t"), ("user.email", "t@example.com"), ("commit.gpgsign", "false")):
            git(d, "config", k, v)
    (repo / "scripts").mkdir()
    shutil.copy(ROOT / "templates/gitops-app/scripts/bootstrap.sh", repo / "scripts/bootstrap.sh")
    (repo / "bootstrap").mkdir()
    (repo / "bootstrap/root.yaml").write_text("kind: Application\n")
    git(repo, "add", "-A"); git(repo, "commit", "-qm", "init"); git(repo, "push", "-q", "origin", "main")
    git(other, "pull", "-q", "origin", "main")
    (other / "operators").mkdir()
    (other / "operators/root.yaml").write_text("kind: Application\n")
    git(other, "add", "-A"); git(other, "commit", "-qm", "operators"); git(other, "push", "-q", "origin", "main")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "kubectl").write_text(f'#!/bin/sh\necho "$@" >> {tmp_path}/kubectl.log\nexit 0\n')
    (bin_dir / "kubectl").chmod(0o755)
    return repo, {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "KUBE_CONTEXT": "k3d-x-local"}, tmp_path


def test_a_main_that_is_behind_is_fast_forwarded_and_its_operators_applied(behind):
    repo, env, tmp = behind
    p = subprocess.run(["bash", "scripts/bootstrap.sh"], cwd=repo, env=env, capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "fast-forwarded main" in p.stdout and (repo / "operators/root.yaml").is_file()
    assert "-f operators/root.yaml" in (tmp / "kubectl.log").read_text()


def test_a_checkout_that_cannot_fast_forward_stops_before_applying(behind):
    repo, env, tmp = behind
    git(repo, "switch", "-qc", "feature/x")
    p = subprocess.run(["bash", "scripts/bootstrap.sh"], cwd=repo, env=env, capture_output=True, text=True)
    assert p.returncode == 1 and "behind origin/main" in p.stderr and "git switch main && git pull --ff-only" in p.stderr
    assert not (tmp / "kubectl.log").exists()


def test_both_bootstrap_scripts_carry_the_check():
    for f in ("templates/gitops-app/scripts/bootstrap.sh", "templates/cluster-gitops/scripts/bootstrap.sh"):
        assert "Spec 142 (AC-142.3)" in (ROOT / f).read_text(), f
