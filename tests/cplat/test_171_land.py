"""Spec 171 acceptance tests: a land settles what has an obvious answer (AC-171.3 to AC-171.6).

Both entries are tested: `cplat component ship land` (`ship`) and `cplat pr wait --merge` (`pr`). The world is in land171_world.py:
a bare repository stands for GitHub, a `gh` stub on PATH answers from its real state, nothing reaches GitHub or the network.
"""
import json
import subprocess

import pytest

import ship
from land171_world import BRANCH, PR_URL, git, make_world
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)
from waiting import with_prelude

ENTRIES = ["ship", "pr"]


@pytest.fixture()
def world(tmp_path, monkeypatch):
    return make_world(tmp_path, monkeypatch)


def land(world, entry, capsys):
    capsys.readouterr()
    rc = world.land(entry)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def warnings(text):
    return [ln for ln in text.splitlines() if ln.startswith("WARNING:")]


def no_conflict_talk(text):
    low = text.lower()
    assert "conflict" not in low and "ship escalate" not in low, text


def block_switch_to_main(world):
    """An edit of a tracked file that `git switch main` would overwrite (the feature adds work.txt, main has none)."""
    (world.repo / "work.txt").write_text("an edit that is not committed\n")


def current_branch(world):
    return git(world.repo, "branch", "--show-current")


def calls_order(world):
    return [(c["kind"], c["sha"] if c["kind"] == "checks" else c["head"]) for c in world.calls() if c.get("kind") in ("checks", "merged")]


# ---------------- AC-171.3: a merge GitHub accepted is a merge, whatever fails after it ----------------

@pytest.mark.parametrize("entry", ENTRIES)
def test_a_failed_switch_to_main_after_the_merge_is_a_warning_and_the_land_succeeds(world, capsys, entry):  # AC-171.3
    block_switch_to_main(world)
    rc, out, err = land(world, entry, capsys)
    assert rc == 0, out + err
    assert len(world.events("merged")) == 1
    assert any(ln.startswith("merged ") and PR_URL in ln for ln in out.splitlines())
    [warning] = warnings(out + err)
    assert warning.startswith("WARNING: switching to main failed: ") and len(warning) > len("WARNING: switching to main failed: ")
    no_conflict_talk(out + err)
    assert current_branch(world) == BRANCH                              # the failed switch left the checkout where it was


def test_the_ship_records_the_merge_that_a_failed_cleanup_did_not_undo(world, capsys):  # AC-171.3
    block_switch_to_main(world)
    rc, out, err = land(world, "ship", capsys)
    st = ship.load_state(world.repo)
    assert rc == 0 and st["phase"] == "deploy" and st["merge_sha"] == world.main_tip()


@pytest.mark.parametrize("entry", ENTRIES)
def test_with_main_in_another_worktree_no_switch_is_tried_and_nothing_is_warned(world, tmp_path, capsys, entry):  # AC-171.3
    other = tmp_path / "main-worktree"
    git(world.repo, "worktree", "add", "-q", str(other), "main")
    before = git(other, "rev-parse", "HEAD")
    rc, out, err = land(world, entry, capsys)
    assert rc == 0, out + err
    assert warnings(out + err) == []
    no_conflict_talk(out + err)
    assert any(ln.startswith("merged ") for ln in out.splitlines())
    assert git(other, "rev-parse", "HEAD") == before and git(other, "branch", "--show-current") == "main"   # never moved
    assert current_branch(world) == BRANCH
    assert git(world.repo, "branch", "--list", BRANCH) != ""            # not deleted while it is checked out here
    assert [e["delete_branch"] for e in world.events("merge-attempt")] == [False]    # gh's own local half is never asked for


@pytest.mark.parametrize("entry", ENTRIES)
def test_a_failed_delete_of_the_remote_branch_is_a_warning_naming_the_step(world, capsys, entry):  # AC-171.3
    world.configure(delete_fail="the token may not delete branches")
    rc, out, err = land(world, entry, capsys)
    assert rc == 0, out + err
    [warning] = warnings(out + err)
    assert warning.startswith("WARNING: deleting the remote branch") and "the token may not delete branches" in warning
    no_conflict_talk(out + err)
    assert current_branch(world) == "main"                              # the local steps still ran


@pytest.mark.parametrize("entry", ENTRIES)
def test_a_clean_land_prints_no_warning_and_leaves_main_updated(world, capsys, entry):  # AC-171.3
    rc, out, err = land(world, entry, capsys)
    assert rc == 0, out + err
    assert warnings(out + err) == [] and current_branch(world) == "main"
    assert git(world.repo, "rev-parse", "HEAD") == world.main_tip()
    assert git(world.repo, "branch", "--list", BRANCH) == ""


def test_a_pr_merged_before_the_land_ran_is_cleaned_up_with_warnings_too(world, capsys):  # AC-171.3
    world.configure(pr={"state": "MERGED", "mergeCommit": {"oid": world.main_tip()}})
    block_switch_to_main(world)
    rc, out, err = land(world, "ship", capsys)
    assert rc == 0, out + err
    assert "already merged" in out and len(warnings(out + err)) == 1 and "switching to main" in warnings(out + err)[0]
    assert world.events("merge-attempt") == []


@pytest.mark.parametrize("entry", ENTRIES)
def test_a_merge_refused_for_another_reason_says_so_and_never_blames_a_conflict(world, capsys, entry):  # AC-171.3
    world.configure(merge_fail="Pull request is not mergeable: the base branch policy prohibits the merge.")
    rc, out, err = land(world, entry, capsys)
    assert rc == 1 and world.events("merged") == []
    assert "merging" in err and "the base branch policy prohibits the merge" in err
    no_conflict_talk(out + err)
    if entry == "ship":
        assert "cplat component ship land" in err.split("fix:", 1)[1]  # interface: fix line printed by cplat


# ---------------- AC-171.4: the merge carries the head the checks were judged on ----------------

def pushed_head(world, bucket_of_new_head=None):
    def push():
        sha = world.push_pr_commit()
        if bucket_of_new_head:
            world.configure(checks={**json.loads((world.dir / "state.json").read_text())["checks"], sha: bucket_of_new_head})
    return push


def assert_new_head_was_judged_before_merging(world, old):
    new = world.pr_head() if world.events("merged") == [] else world.events("merged")[0]["head"]
    merged = world.events("merged")
    assert len(merged) == 1 and merged[0]["head"] == new != old
    order = calls_order(world)
    assert ("checks", new) in order and order.index(("checks", new)) < order.index(("merged", new))
    for attempt in world.events("merge-attempt"):
        assert attempt["match"], "every merge is guarded by the head its checks were judged on"


@pytest.mark.parametrize("entry", ENTRIES)
def test_a_head_unknown_before_the_lock_is_read_and_guards_the_merge(world, capsys, entry):  # AC-171.4
    old = world.pre
    # the watch never saw the head (the land of a ship reads it once before, to see whether anything is unpushed)
    world.configure(blind_until_checks=1, blind_skip=1 if entry == "ship" else 0, checks={"default": ["pending", "pass"]})
    world.after_compare(world.push_pr_commit)               # a commit is pushed between the checks and the merge
    rc, out, err = land(world, entry, capsys)
    assert rc == 0, out + err
    assert world.events("merge-attempt")[0]["match"] == old       # the head the lock read is the head the merge carries
    assert_new_head_was_judged_before_merging(world, old)
    assert "moved" in out and "waiting for its checks" in out


@pytest.mark.parametrize("entry", ENTRIES)
def test_a_commit_pushed_after_green_checks_is_not_merged_unchecked(world, capsys, entry):  # AC-171.4
    old = world.pre
    world.after_checks(world.push_pr_commit)
    rc, out, err = land(world, entry, capsys)
    assert rc == 0, out + err
    assert_new_head_was_judged_before_merging(world, old)


@pytest.mark.parametrize("entry", ENTRIES)
def test_the_checks_of_the_new_head_decide_and_a_red_one_merges_nothing(world, capsys, entry):  # AC-171.4
    world.after_checks(pushed_head(world, ["fail"]))
    rc, out, err = land(world, entry, capsys)
    assert rc == 1 and world.events("merged") == []
    assert "RED" in out, out + err


# ---------------- AC-171.5: unpushed local commits are pushed first ----------------

def test_local_commits_are_pushed_and_only_their_checks_are_judged(world, capsys):  # AC-171.5
    old = world.pre
    world.configure(checks={"default": ["pass"], old: ["fail"]})         # the old head is red: judging it would stop the land
    first, new = world.local_commit("a.txt"), None
    new = world.local_commit("b.txt")
    rc, out, err = land(world, "ship", capsys)
    assert rc == 0, out + err
    assert f"pushed 2 local commit(s) to {BRANCH}" in out
    assert {e["sha"] for e in world.events("checks")} == {new}           # never a check of the old head
    assert [e["head"] for e in world.events("merged")] == [new] and first != new
    assert [c for c in world.calls() if c["args"][:2] == ["pr", "create"]] == []     # the open PR is reused


def test_the_local_checks_run_before_the_push_with_the_prs_own_title(world, capsys):  # AC-171.5
    world.add_ci_script()
    world.local_commit("a.txt")
    rc, out, err = land(world, "ship", capsys)
    assert rc == 0, out + err
    assert world.devbox_runs() == ["run ci title=feat(alerts): price alerts"]


def test_a_red_local_check_pushes_nothing_and_judges_no_checks(world, capsys, monkeypatch):  # AC-171.5
    world.add_ci_script()
    world.local_commit("a.txt")
    monkeypatch.setenv("DEVBOX_RC", "1")
    rc, out, err = land(world, "ship", capsys)
    assert rc == 1 and "nothing was pushed" in err
    assert world.pr_head() == world.pre and world.events("checks") == [] and world.events("merged") == []


def test_a_refused_push_exits_1_naming_the_commits_and_the_fix_and_judges_no_checks(world, capsys):  # AC-171.5
    world.local_commit("a.txt")
    world.local_commit("b.txt")
    hook = world.bare / "hooks" / "pre-receive"
    hook.write_text(with_prelude("#!/bin/sh\necho 'refused by the test hook' >&2\nexit 1\n"))
    hook.chmod(0o755)
    rc, out, err = land(world, "ship", capsys)
    assert rc == 1
    assert "ERROR: local commits not pushed: 2 commit(s) ahead of the PR head" in err
    assert "fix:" in err and "cplat component ship pr" in err.split("fix:", 1)[1]  # interface: fix line printed by cplat
    assert f"push of {BRANCH} failed" in out + err
    assert world.events("checks") == [] and world.events("merged") == [] and world.pr_head() == world.pre


def test_a_branch_with_nothing_ahead_is_not_pushed_and_runs_no_local_check(world, capsys):  # AC-171.5
    world.add_ci_script()
    world.local_commit("a.txt")
    git(world.repo, "push", "-q", "origin", BRANCH)
    rc, out, err = land(world, "ship", capsys)
    assert rc == 0, out + err
    assert "local commit(s)" not in out and world.devbox_runs() == []


# ---------------- AC-171.6: a conflict in a generated file is regenerated ----------------

def conflicts(world) -> bool:
    res = subprocess.run(["git", "--git-dir", str(world.bare), "merge-tree", "--write-tree", "main", BRANCH], capture_output=True)
    return res.returncode == 1


def both_add_a_spec(world, feature=199, main=108):
    world.feature_adds_spec(feature)
    world.other_adds_spec(main)
    assert conflicts(world), "the setup is a real conflict of the index"
    return world.pr_head()


def clean_checkout(world):
    assert git(world.repo, "status", "--porcelain") == ""
    assert subprocess.run(["git", "rev-parse", "-q", "--verify", "MERGE_HEAD"], cwd=world.repo, capture_output=True).returncode != 0


@pytest.mark.parametrize("entry", ENTRIES)
def test_a_conflict_in_the_backlog_index_is_regenerated_committed_pushed_and_merged(world, capsys, entry):  # AC-171.6
    before = both_add_a_spec(world)
    rc, out, err = land(world, entry, capsys)
    assert rc == 0, out + err
    [line] = [ln for ln in out.splitlines() if "regenerated" in ln]
    assert "docs/backlog.md" in line
    [merged] = world.events("merged")
    head = merged["head"]
    assert head != before and world.bare_git("rev-parse", f"{head}^") != ""
    assert len(world.bare_git("rev-list", "--parents", "-n", "1", head).split()) == 3          # main merged into the branch
    assert "Signed-off-by:" in world.bare_git("log", "-1", "--format=%B", head)
    git(world.bare, "merge-base", "--is-ancestor", before, head)                                  # pushed on top: no force
    text = world.bare_git("show", f"{head}:docs/backlog.md")
    assert "108-more-108" in text and "199-more-199" in text and "007-price-alerts" in text
    assert "<<<<<<<" not in text and ">>>>>>>" not in text and "hand written head line one" in text
    order = calls_order(world)
    assert ("checks", head) in order and order.index(("checks", head)) < order.index(("merged", head))   # the new head's checks first


@pytest.mark.parametrize("entry", ENTRIES)
def test_the_hand_written_rest_of_the_backlog_is_merged_as_text(world, capsys, entry):  # AC-171.6
    both_add_a_spec(world)
    world.other_commit({"docs/backlog.md": world.bare_git("show", "main:docs/backlog.md")
                        .replace("hand written head line one", "hand written head line one, edited on main")})
    rc, out, err = land(world, entry, capsys)
    assert rc == 0, out + err
    [merged] = world.events("merged")
    text = world.bare_git("show", f"{merged['head']}:docs/backlog.md")
    assert "edited on main" in text and "108-more-108" in text and "199-more-199" in text and "<<<<<<<" not in text


@pytest.mark.parametrize("entry", ENTRIES)
@pytest.mark.parametrize("also_the_index", [False, True])
def test_a_conflict_in_any_other_file_stops_and_leaves_no_half_merged_state(world, capsys, entry, also_the_index):  # AC-171.6
    (world.repo / "f.txt").write_text("one\nfeature line\nthree\n")
    git(world.repo, "add", "-A")
    git(world.repo, "commit", "-qm", "feat: edit f")
    git(world.repo, "push", "-q", "origin", BRANCH)
    if also_the_index:
        world.feature_adds_spec(199)
        world.other_adds_spec(108)
    world.other_commit({"f.txt": "one\nmain line\nthree\n"})
    assert conflicts(world)
    tip, head = git(world.repo, "rev-parse", "HEAD"), world.pr_head()
    rc, out, err = land(world, entry, capsys)
    assert rc == 1 and world.events("merged") == []
    assert "rebase is a human decision" in err and "f.txt" in err
    clean_checkout(world)
    assert git(world.repo, "rev-parse", "HEAD") == tip and world.pr_head() == head      # nothing pushed, nothing left behind


@pytest.mark.parametrize("entry", ENTRIES)
def test_a_conflict_in_the_hand_written_part_of_the_backlog_stops_too(world, capsys, entry):  # AC-171.6
    text = (world.repo / "docs" / "backlog.md").read_text()
    (world.repo / "docs" / "backlog.md").write_text(text.replace("head line one", "head line one, the feature's words"))
    git(world.repo, "add", "-A")
    git(world.repo, "commit", "-qm", "docs: edit the backlog")
    git(world.repo, "push", "-q", "origin", BRANCH)
    world.other_commit({"docs/backlog.md": text.replace("head line one", "head line one, main's words")})
    assert conflicts(world)
    tip = git(world.repo, "rev-parse", "HEAD")
    rc, out, err = land(world, entry, capsys)
    assert rc == 1 and world.events("merged") == []
    assert "rebase is a human decision" in err and "docs/backlog.md" in err
    clean_checkout(world)
    assert git(world.repo, "rev-parse", "HEAD") == tip


@pytest.mark.parametrize("entry", ENTRIES)
def test_after_three_regeneration_rounds_in_one_land_it_stops(world, capsys, entry):  # AC-171.6
    start = both_add_a_spec(world)
    numbers = iter([110, 111, 112])
    world.on_new_head_checks(lambda: world.other_adds_spec(next(numbers)), times=3)     # main moves after every pushed head
    rc, out, err = land(world, entry, capsys)
    assert rc == 1 and world.events("merged") == []
    assert "rebase is a human decision" in err
    assert int(world.bare_git("rev-list", "--merges", "--count", f"{start}..{world.pr_head()}")) == 3     # three rounds, no fourth
    clean_checkout(world)
