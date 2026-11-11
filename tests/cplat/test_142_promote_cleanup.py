"""Spec 142 (AC-142.5): a gitops PR step that fails leaves the clone clean. In the journey of 2026-11-05 a promotion stopped on
a local branch left by an earlier, merged PR; its pin edit stayed uncommitted on main, so the next promotion failed too."""
import os
import subprocess

import core
import gitops
import pytest
from waiting import with_prelude


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture()
def clone(tmp_path, monkeypatch):
    origin, repo = tmp_path / "origin.git", tmp_path / "repo"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(repo)], check=True, capture_output=True)
    for k, v in (("user.name", "t"), ("user.email", "t@example.com"), ("commit.gpgsign", "false")):
        git(repo, "config", k, v)
    (repo / "applications/shop").mkdir(parents=True)
    (repo / "applications/shop/system.yaml").write_text("pin: sha-1\n")
    (repo / "bootstrap").mkdir()
    (repo / "bootstrap/root.yaml").write_text("kind: Application\n")
    git(repo, "add", "-A"); git(repo, "commit", "-qm", "init"); git(repo, "push", "-q", "origin", "main")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text(with_prelude('#!/bin/sh\nif [ "$GH_FAIL" = 1 ]; then echo "HTTP 502" >&2; exit 1; fi\necho https://github.com/acme/shop-gitops/pull/9\n'))
    (bin_dir / "gh").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    return repo


def test_a_stale_local_branch_of_a_merged_pr_is_replaced(clone):
    git(clone, "branch", "promote/shop-staging")                     # left behind; its remote branch was deleted on merge
    (clone / "applications/shop/system.yaml").write_text("pin: sha-2\n")
    url = gitops.open_pr(clone, "promote/shop-staging", "chore(promote): shop dev→staging", "body")
    assert url.endswith("/pull/9") and git(clone, "branch", "--show-current") == "promote/shop-staging"
    assert "sha-2" in git(clone, "show", "HEAD:applications/shop/system.yaml")


def test_a_failed_pr_leaves_the_clone_on_main_with_nothing_changed(clone, monkeypatch):
    monkeypatch.setenv("GH_FAIL", "1")
    (clone / "applications/shop/system.yaml").write_text("pin: sha-2\n")
    (clone / "applications/shop/new-overlay.yaml").write_text("x: 1\n")
    with pytest.raises(core.PlatformError) as e:
        gitops.open_pr(clone, "promote/shop-staging", "chore(promote): shop dev→staging", "body")
    assert git(clone, "branch", "--show-current") == "main" and git(clone, "status", "--porcelain") == ""
    assert "promote/shop-staging" not in git(clone, "branch")
    assert "was pushed to origin" in str(e.value) and "back on main" in (e.value.hint or "")
    assert (clone / "applications/shop/system.yaml").read_text() == "pin: sha-1\n"


def test_discard_changes_touches_only_the_gitops_paths(clone):
    (clone / "applications/shop/system.yaml").write_text("pin: sha-2\n")
    (clone / "notes.txt").write_text("mine\n")
    gitops.discard_changes(clone)
    assert (clone / "applications/shop/system.yaml").read_text() == "pin: sha-1\n" and (clone / "notes.txt").is_file()


def test_operator_files_the_render_wrote_are_committed(clone):
    """#504: a prod promotion with a backed-up bucket rendered operators/apps/*.yaml but committed only applications/ and
    bootstrap/; CI's render-check failed on the PR and the leftovers blocked the next promotion."""
    (clone / "applications/shop/system.yaml").write_text("pin: 1.0.0\n")
    (clone / "operators/apps").mkdir(parents=True)
    (clone / "operators/apps/seaweedfs.yaml").write_text("kind: Application\n")
    gitops.open_pr(clone, "promote/shop-prod", "chore(promote): shop staging→prod", "body")
    assert git(clone, "status", "--porcelain") == ""
    assert "operators/apps/seaweedfs.yaml" in git(clone, "show", "--name-only", "--format=", "HEAD").splitlines()


def test_a_change_outside_the_commit_refuses_the_pr_before_the_push(clone):
    (clone / "applications/shop/system.yaml").write_text("pin: 1.0.0\n")
    (clone / "stray.yaml").write_text("x: 1\n")
    with pytest.raises(core.PlatformError, match="outside the commit: stray.yaml"):
        gitops.open_pr(clone, "promote/shop-prod", "chore(promote): shop staging→prod", "body")
    assert git(clone, "branch", "--show-current") == "main" and "promote/shop-prod" not in git(clone, "branch")
    assert git(clone, "ls-remote", "--heads", "origin", "promote/shop-prod") == ""
    assert (clone / "applications/shop/system.yaml").read_text() == "pin: sha-1\n"


def test_discard_changes_removes_operator_leftovers(clone):
    (clone / "operators/apps").mkdir(parents=True)
    (clone / "operators/apps/external-secrets.yaml").write_text("kind: Application\n")
    gitops.discard_changes(clone)
    assert git(clone, "status", "--porcelain") == ""
