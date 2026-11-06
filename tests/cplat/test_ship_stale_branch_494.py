"""#494: `gh pr merge --squash --delete-branch` deletes the spec branch on GitHub and locally but leaves the stale
remote-tracking ref `origin/feature/<spec>`. The ship's start then tracked it and built on the spec's old commits, so the
build PR conflicted on spec.md. It now drops the stale ref and starts the branch from origin/main."""
from test_ship_branch_after_squash_410 import BRANCH, _setup, git

import ship


def _after_gh_merge(tmp_path):
    repo = _setup(tmp_path)                                   # on main, the branch deleted on origin
    old = git(repo, "rev-parse", BRANCH)
    git(repo, "branch", "-q", "-D", BRANCH)                   # gh deletes the local branch too
    git(repo, "update-ref", f"refs/remotes/origin/{BRANCH}", old)   # ...but not the remote-tracking ref
    return repo, old


def test_a_stale_tracking_ref_is_not_built_on(tmp_path):
    repo, old = _after_gh_merge(tmp_path)
    note = ship.on_branch(repo, BRANCH)
    assert "tracking origin" not in note
    assert git(repo, "branch", "--show-current") == BRANCH
    assert git(repo, "rev-parse", "HEAD") == git(repo, "rev-parse", "origin/main") != old
    assert git(repo, "for-each-ref", f"refs/remotes/origin/{BRANCH}") == ""


def test_a_local_main_behind_origin_starts_the_branch_from_origin_main(tmp_path):
    repo, _ = _after_gh_merge(tmp_path)
    git(repo, "reset", "-q", "--hard", "HEAD~1")              # the squash commit is not pulled yet
    assert "created from origin/main" in ship.on_branch(repo, BRANCH)
    assert git(repo, "rev-parse", "HEAD") == git(repo, "rev-parse", "origin/main")
    assert (repo / "docs/specs/001-tasks/spec.md").read_text() == "status: approved\n"


def test_a_branch_that_still_exists_on_origin_is_tracked(tmp_path):
    repo, old = _after_gh_merge(tmp_path)
    git(repo, "push", "-q", "origin", f"{old}:refs/heads/{BRANCH}")
    assert "tracking origin" in ship.on_branch(repo, BRANCH)
    assert git(repo, "rev-parse", "HEAD") == old
