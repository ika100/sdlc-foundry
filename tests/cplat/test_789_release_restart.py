"""#789: releasing 5.23.3 took three starts. The second start reused the never-pushed `release/5.23.3` of the first, made from an
older main, and failed the same tests again; the third stopped because the local `main` (checked out in another worktree) was
behind origin/main. A release now branches from origin/main and starts such a branch again. Offline: see platrelease_world."""
from platrelease_world import w  # noqa: F401  (w is a fixture)

BRANCH = "release/5.5.0"


def origin_moves(w, name="fix.txt"):
    """Another clone merges a fix into origin/main; this clone fetches it, but its local main stays behind."""
    (w.other / name).write_text("fix\n")
    w.git("add", name, cwd=w.other)
    w.git("commit", "-q", "-m", "fix: on main", cwd=w.other)
    w.git("push", "-q", "origin", "main", cwd=w.other)
    w.git("fetch", "-q", "origin")


def test_a_local_main_behind_origin_does_not_stop_the_release_and_the_branch_holds_origin_main(w):
    origin_moves(w)
    r = w.run()
    assert r.rc == 3 and "CONFIRM: merge" in r.out, r.text
    assert w.git("merge-base", "--is-ancestor", "origin/main", BRANCH, check=False) == ""
    assert "fix.txt" in w.git("ls-tree", "--name-only", BRANCH).split()


def test_a_never_pushed_release_branch_behind_origin_is_started_again_from_origin_main(w):
    w.results["validate"] = (1, "ERROR: main is red")
    assert w.run().rc == 1                                   # the first start stops at its checks, the branch stays local
    assert w.git("rev-parse", "--verify", "-q", f"refs/heads/{BRANCH}").strip()
    w.git("reset", "-q", "--hard")
    w.git("switch", "-q", "main")                            # the next start runs from main
    origin_moves(w)
    w.results.pop("validate")
    r = w.run()
    assert r.rc == 3, r.text
    assert f"{BRANCH} was never pushed and is behind origin/main: started it again from origin/main" in r.out
    assert "fix.txt" in w.git("ls-tree", "--name-only", f"origin/{BRANCH}").split()


def test_a_restart_on_the_stale_branch_drops_its_changelog_edits_and_makes_them_again(w):
    w.results["validate"] = (1, "ERROR: main is red")
    assert w.run().rc == 1                                   # stops on the branch, its changelog edit uncommitted
    origin_moves(w)
    w.results.pop("validate")
    r = w.run()
    assert r.rc == 3, r.text
    assert w.git("diff", "--name-only", f"origin/main...origin/{BRANCH}").split() == ["docs/CHANGELOG.md"]


def test_a_merge_from_a_linked_worktree_leaves_it_detached_and_main_free_for_the_main_checkout(tmp_path):
    """The third start stopped on a local main the release could not move: `pr wait --merge` had switched a linked worktree to
    main after a merge there. A linked worktree is now left detached at origin/main and its merged branch deleted."""
    import subprocess

    import land_merge

    def run(cmd, cwd=None, check=False):
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=check)

    def git(d, *a):
        return run(["git", *a], cwd=d, check=True).stdout.strip()

    origin, main_co, linked = tmp_path / "origin.git", tmp_path / "main", tmp_path / "linked"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    git(tmp_path, "clone", "-q", str(origin), str(main_co))
    for k, v in (("user.name", "t"), ("user.email", "t@x"), ("commit.gpgsign", "false")):
        git(main_co, "config", k, v)
    git(main_co, "commit", "-q", "--allow-empty", "-m", "init")
    git(main_co, "push", "-q", "origin", "main")
    git(main_co, "switch", "-q", "-c", "feature/other")                 # the main checkout works on something else
    git(main_co, "worktree", "add", "-q", "-b", "fix/x", str(linked), "origin/main")
    warnings: list[str] = []
    land_merge._local(linked, "fix/x", "main", run, warnings)
    assert warnings == []
    assert git(linked, "branch", "--show-current") == "" and git(linked, "rev-parse", "HEAD") == git(main_co, "rev-parse", "origin/main")
    assert git(main_co, "branch", "--list", "fix/x") == ""
    git(main_co, "switch", "-q", "main")                                 # main is free for the main checkout
