"""#410: `cplat spec land` squash-merges the spec PR and deletes its branch, but the local `feature/<spec>` keeps the original
spec commits. A ship that builds on them opens a feature PR that conflicts with main's squash commit. The ship's start now
restarts the branch from origin/main when everything on it is already on main."""
import subprocess
from pathlib import Path

import ship

BRANCH = "feature/001-tasks"


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def _write(repo: Path, rel: str, text: str) -> None:
    (repo / rel).parent.mkdir(parents=True, exist_ok=True)
    (repo / rel).write_text(text)


def _setup(tmp_path: Path) -> Path:
    origin, repo = tmp_path / "origin.git", tmp_path / "repo"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(repo)], check=True, capture_output=True)
    for k, v in (("user.name", "t"), ("user.email", "t@example.com"), ("commit.gpgsign", "false")):
        git(repo, "config", k, v)
    _write(repo, "README.md", "x\n")
    git(repo, "add", "-A"); git(repo, "commit", "-qm", "init"); git(repo, "push", "-q", "origin", "main")
    git(repo, "switch", "-qc", BRANCH)
    _write(repo, "docs/specs/001-tasks/spec.md", "status: draft\n")
    git(repo, "add", "-A"); git(repo, "commit", "-qm", "spec")
    _write(repo, "docs/specs/001-tasks/spec.md", "status: approved\n")
    git(repo, "commit", "-qam", "approve")
    git(repo, "push", "-q", "-u", "origin", BRANCH)
    # what `cplat spec land` does on GitHub: one squash commit on main, the branch deleted
    git(repo, "switch", "-q", "main")
    _write(repo, "docs/specs/001-tasks/spec.md", "status: approved\n")
    git(repo, "add", "-A"); git(repo, "commit", "-qm", "docs(spec): 001 (#2)"); git(repo, "push", "-q", "origin", "main")
    git(repo, "push", "-q", "origin", "--delete", BRANCH)
    return repo


def test_a_branch_whose_spec_was_squash_merged_restarts_from_main(tmp_path):
    repo = _setup(tmp_path)
    git(repo, "switch", "-q", BRANCH)
    note = ship.on_branch(repo, BRANCH)
    assert "restarted from origin/main" in note
    assert git(repo, "branch", "--show-current") == BRANCH
    assert git(repo, "rev-parse", "HEAD") == git(repo, "rev-parse", "origin/main")
    assert (repo / "docs/specs/001-tasks/spec.md").read_text() == "status: approved\n"


def test_from_main_the_ship_also_lands_on_the_restarted_branch(tmp_path):
    repo = _setup(tmp_path)                    # still on main, as after `cplat spec land`
    ship.on_branch(repo, BRANCH)
    assert git(repo, "branch", "--show-current") == BRANCH
    assert git(repo, "rev-parse", "HEAD") == git(repo, "rev-parse", "origin/main")


def test_a_branch_with_work_main_does_not_have_is_kept(tmp_path):
    repo = _setup(tmp_path)
    git(repo, "switch", "-q", BRANCH)
    _write(repo, "src/app.py", "print(1)\n")
    git(repo, "add", "-A"); git(repo, "commit", "-qm", "code")
    head = git(repo, "rev-parse", "HEAD")
    assert ship.on_branch(repo, BRANCH) == f"branch: {BRANCH}"
    assert git(repo, "rev-parse", "HEAD") == head


def test_a_branch_still_on_origin_is_kept(tmp_path):
    repo = _setup(tmp_path)
    git(repo, "switch", "-q", BRANCH)
    git(repo, "push", "-q", "origin", BRANCH)
    head = git(repo, "rev-parse", "HEAD")
    ship.on_branch(repo, BRANCH)
    assert git(repo, "rev-parse", "HEAD") == head
