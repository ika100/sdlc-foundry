"""Spec 172: `cplat component build merge` refuses a task branch with unsigned commits in the platform repo (AC-172.7).

Seam: the spec 094 / #501 build fixtures (`repo`, `_feature`, `branch_from`, `build`) with the repo turned into a platform repo
(`.platform-settings.yml` declares `shape: platform`, the `.copier-answers.yml` goes).
"""
from pathlib import Path

import replan
from test_build_parallel_501 import _feature
from test_replan import SPEC_ID, build, commit
from test_ship import git, repo  # noqa: F401  (fixture)


ROOT = Path(__file__).resolve().parents[2]


def as_platform(repo):
    (repo / ".copier-answers.yml").unlink()
    (repo / ".platform-settings.yml").write_text("shape: platform\n")


def commit_signed(repo, msg):
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qsm", msg)


def task_branch(repo, name, base, *, signed, extra=None):
    """A branch off `base` with one commit changing a.py; the commit is signed or not. Leaves the checkout where it was."""
    here = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    git(repo, "checkout", "-q", "-b", name, base)
    (repo / "a.py").write_text("one\n")
    (commit_signed if signed else commit)(repo, f"work on {name}")
    if extra:
        extra(repo)
    git(repo, "checkout", "-q", here)


def unchanged(repo, head):
    assert git(repo, "rev-parse", "HEAD") == head and git(repo, "status", "--porcelain", "--untracked-files=no") == ""
    assert (repo / "a.py").read_text() == "base\n"
    assert replan.pending(repo, SPEC_ID) == {}


def test_a_branch_with_an_unsigned_commit_is_refused_and_nothing_changes_ac_172_7(repo, capsys):  # AC-172.7
    as_platform(repo)
    main, head = _feature(repo)
    task_branch(repo, "br-t1", head, signed=False)
    unsigned = git(repo, "rev-parse", "br-t1")
    tree = git(repo, "rev-parse", "HEAD^{tree}")
    rc, out, err = build(capsys, repo, "merge", "t1", "br-t1")
    assert rc not in (0, 3, 4) and rc != 0
    assert "branch 'br-t1' brings in 1 commit(s) without a Signed-off-by line" in err
    assert f"{unsigned[:7]} work on br-t1" in err
    assert "rebase --signoff" in err and head[:7] in err          # onto the merge base, which is the feature head here
    assert out == "" and "CONFLICT" not in err
    unchanged(repo, head)
    assert git(repo, "rev-parse", "HEAD^{tree}") == tree


def test_the_hint_names_the_worktree_that_has_the_branch_ac_172_7(repo, tmp_path, capsys):  # AC-172.7
    as_platform(repo)
    main, head = _feature(repo)
    task_branch(repo, "br-t1", head, signed=False)
    wt = (tmp_path / "wt-t1")
    git(repo, "worktree", "add", "-q", str(wt), "br-t1")
    rc, out, err = build(capsys, repo, "merge", "t1", "br-t1")
    assert rc != 0 and f"git -C {wt.resolve()} rebase --signoff {head[:7]}" in err


def test_after_the_rebase_the_merge_goes_through_ac_172_7(repo, tmp_path, capsys):  # AC-172.7
    as_platform(repo)
    main, head = _feature(repo)
    task_branch(repo, "br-t1", head, signed=False)
    wt = tmp_path / "wt-t1"
    git(repo, "worktree", "add", "-q", str(wt), "br-t1")
    assert build(capsys, repo, "merge", "t1", "br-t1")[0] not in (0, 3, 4)
    git(wt, "-c", "user.name=t", "-c", "user.email=t@t", "rebase", "--signoff", head[:7])
    rc, out, err = build(capsys, repo, "merge", "t1", "br-t1")
    assert rc == 0 and out.startswith("MERGED t1"), err


def test_the_build_prompt_rebases_with_signoff_and_merges_again_without_asking_ac_172_7():  # AC-172.7
    build = (ROOT / "plugins" / "component" / "commands" / "build.md").read_text()
    step = build.split("### 2.4 Run batches", 1)[1].split("### 2.4a", 1)[0]
    line = next(ln for ln in step.splitlines() if "without `Signed-off-by`" in ln)
    assert "Exit 1" in line and "git -C <worktree> rebase --signoff <sha>" in line
    assert line.rstrip(".").split("rebase --signoff <sha>`, ")[1].startswith("merge again without asking")


def test_a_merge_commit_without_sign_off_is_named_too_ac_172_7(repo, capsys):  # AC-172.7
    as_platform(repo)
    main, head = _feature(repo)

    def merge_other(r):
        git(r, "checkout", "-q", "-b", "side", head)
        (r / "b.py").write_text("side\n")
        commit_signed(r, "side work")
        git(r, "checkout", "-q", "br-m")
        git(r, "-c", "user.name=t", "-c", "user.email=t@t", "merge", "--no-ff", "-m", "unsigned merge of side", "side")

    task_branch(repo, "br-m", head, signed=True, extra=merge_other)
    merge_sha = git(repo, "rev-parse", "br-m")
    rc, out, err = build(capsys, repo, "merge", "t1", "br-m")
    assert rc not in (0, 3, 4)
    assert "brings in 1 commit(s) without a Signed-off-by line" in err and f"{merge_sha[:7]} unsigned merge of side" in err
    unchanged(repo, head)


def test_a_signed_branch_merges_in_the_platform_repo_ac_172_7(repo, capsys):  # AC-172.7
    as_platform(repo)
    main, head = _feature(repo)
    task_branch(repo, "br-t1", head, signed=True)
    rc, out, err = build(capsys, repo, "merge", "t1", "br-t1")
    assert rc == 0 and out.startswith("MERGED t1"), err


def test_other_repos_merge_unsigned_branches_as_before_ac_172_7(repo, capsys):  # AC-172.7
    main, head = _feature(repo)                       # the fixture's service repo: no platform declaration
    task_branch(repo, "br-t1", head, signed=False)
    rc, out, err = build(capsys, repo, "merge", "t1", "br-t1")
    assert rc == 0 and out.startswith("MERGED t1"), err
