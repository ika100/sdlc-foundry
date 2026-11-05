"""Found in journey 1 (2026-11-05): `cplat component set --pr` stopped on a temporary GitHub error when it opened the PR.
`gitops.open_pr` now tries `gh pr create` again after a transient error (5xx, timeout); any other error stops at once, and
on a final failure the clone is restored as before (spec 142, AC-142.5)."""
import os
import subprocess

import core
import gitops
import pytest


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
    # GH_ANSWERS: one word per call, "ok" or an error text; the calls are counted in a file
    (bin_dir / "gh").write_text(f'''#!/bin/sh
n=$(cat {tmp_path}/n 2>/dev/null || echo 0); n=$((n+1)); echo $n > {tmp_path}/n
a=$(echo "$GH_ANSWERS" | cut -d, -f$n)
if [ "$a" = ok ]; then echo https://github.com/acme/shop-gitops/pull/9; exit 0; fi
echo "$a" >&2; exit 1
''')
    (bin_dir / "gh").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    slept = []
    monkeypatch.setattr(core, "sleep", slept.append)
    (repo / "applications/shop/system.yaml").write_text("pin: sha-2\n")
    return repo, tmp_path, slept


def calls(tmp):
    return int((tmp / "n").read_text())


def test_a_transient_error_is_tried_again(clone, monkeypatch):
    repo, tmp, slept = clone
    monkeypatch.setenv("GH_ANSWERS", "HTTP 502: Bad Gateway,ok")
    url = gitops.open_pr(repo, "promote/shop-staging", "chore(promote): shop dev→staging", "body")
    assert url.endswith("/pull/9") and calls(tmp) == 2 and slept == [5]
    assert git(repo, "branch", "--show-current") == "promote/shop-staging"


def test_another_error_is_not_retried_and_the_clone_is_restored(clone, monkeypatch):
    repo, tmp, slept = clone
    monkeypatch.setenv("GH_ANSWERS", "a pull request for branch promote/shop-staging already exists")
    with pytest.raises(core.PlatformError, match="already exists"):
        gitops.open_pr(repo, "promote/shop-staging", "chore(promote): shop dev→staging", "body")
    assert calls(tmp) == 1 and slept == []
    assert git(repo, "branch", "--show-current") == "main" and git(repo, "status", "--porcelain") == ""


def test_three_transient_errors_fail_and_restore_the_clone(clone, monkeypatch):
    repo, tmp, slept = clone
    monkeypatch.setenv("GH_ANSWERS", "HTTP 503,HTTP 502: Bad Gateway,something went wrong")
    with pytest.raises(core.PlatformError, match="was pushed to origin"):
        gitops.open_pr(repo, "promote/shop-staging", "chore(promote): shop dev→staging", "body")
    assert calls(tmp) == 3 and slept == [5, 15]
    assert git(repo, "branch", "--show-current") == "main" and git(repo, "status", "--porcelain") == ""
