"""#501: worktrees start at main when the session did not start in the repo root, and the build then ran every task
serially. Parallel-safe tasks now still run in parallel: each coder resets its worktree to the feature head, and
`cplat component build merge` refuses a task branch that lacks the acceptance tests."""
from pathlib import Path

from test_replan import PLAN, SPEC_ID, branch_from, build, commit, jbuild, write_plan
from test_ship import git, repo  # noqa: F401  (fixture)

import cplat
import spec

BUILD = Path(__file__).resolve().parents[2] / "plugins" / "component" / "commands" / "build.md"


def _feature(repo):
    s = spec.read(repo / "docs" / "specs" / SPEC_ID)
    write_plan(repo, PLAN.format(sid=SPEC_ID, hash=s.ac_hash()))
    for f in ("a.py", "b.py", "c.py"):
        (repo / f).write_text("base\n")
    git(repo, "config", "user.name", "t")
    git(repo, "config", "user.email", "t@t")
    commit(repo, "base")
    main = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "-b", f"feature/{SPEC_ID}")
    (repo / "test_acceptance.py").write_text("def test_x(): assert False\n")
    commit(repo, f"test(007): acceptance tests for {SPEC_ID}")
    return main, git(repo, "rev-parse", "HEAD")


def test_two_parallel_safe_tasks_are_offered_as_one_parallel_batch(repo, capsys):
    _feature(repo)
    level = jbuild(capsys, repo, "schedule")["levels"][0]
    assert {"tasks": ["t1", "t2", "t3"], "parallel": True} in level


def test_a_task_branch_from_main_is_refused_and_one_from_the_feature_head_merges(repo, capsys):
    main, head = _feature(repo)
    branch_from(repo, "br-t1-main", main, {"a.py": "one\n"})
    rc, out, err = build(capsys, repo, "merge", "t1", "br-t1-main")
    assert rc != 0 and "does not contain the acceptance tests" in err
    assert git(repo, "rev-parse", "HEAD") == head
    branch_from(repo, "br-t1", head, {"a.py": "one\n"})
    rc, out, err = build(capsys, repo, "merge", "t1", "br-t1")
    assert rc == 0, err
    assert out.startswith("MERGED t1")


def test_a_probe_off_the_feature_head_no_longer_means_sequential():
    text = BUILD.read_text()
    probe = text.split("2.2 Worktree", 1)[1].split("### 2.3", 1)[0]
    assert "is fine (#501)" in probe
    assert "cplat component build reset <FEATURE_HEAD>" in text.split("### 2.3", 1)[1].split("### 2.4", 1)[0]


def _reset(capsys, where, sha):
    capsys.readouterr()
    rc = cplat.main(["component", "build", "reset", sha, "--repo", str(where)])
    out = capsys.readouterr()
    return rc, out.out, out.err


def test_reset_moves_a_clean_agent_worktree_to_the_feature_head(repo, tmp_path, capsys):
    """A headless coder may not run `git reset --hard` (no allowlist rule); `cplat component build reset` does it."""
    main, head = _feature(repo)
    wt = tmp_path / "agent-1"
    git(repo, "worktree", "add", "-q", "-b", "worktree-agent-1", str(wt), main)
    rc, out, err = _reset(capsys, wt, head)
    assert rc == 0, err
    assert git(wt, "rev-parse", "HEAD") == head
    assert (wt / "test_acceptance.py").exists()


def test_reset_refuses_the_main_checkout_and_a_worktree_with_edits(repo, tmp_path, capsys):
    main, head = _feature(repo)
    rc, out, err = _reset(capsys, repo, main)
    assert rc != 0 and "main checkout" in err
    assert git(repo, "rev-parse", "HEAD") == head
    wt = tmp_path / "agent-2"
    git(repo, "worktree", "add", "-q", "-b", "worktree-agent-2", str(wt), main)
    (wt / "a.py").write_text("edited\n")
    rc, out, err = _reset(capsys, wt, head)
    assert rc != 0 and "uncommitted changes" in err
    assert (wt / "a.py").read_text() == "edited\n"
    rc, out, err = _reset(capsys, wt, "no-such-ref")
    assert rc != 0 and "not a commit" in err
