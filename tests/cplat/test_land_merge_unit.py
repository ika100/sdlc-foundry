"""land_merge driven directly (spec 171, t4): wait_green, settle, merge, cleanup and regenerate on the gh stub world of land171_world.py."""
import pytest

import land_merge
import merge_lock
import ship
from core import run
from land171_world import BRANCH, PR_URL, git, make_world


@pytest.fixture()
def world(tmp_path, monkeypatch):
    return make_world(tmp_path, monkeypatch)


def land(world, before_merge=None):
    """What a caller does: the first wait for the checks, then settle."""
    watch = ship.CheckWatch(world.repo, PR_URL, 300)
    rounds = land_merge.Rounds()
    lines = []
    status, cs, failed, more = land_merge.wait_green(world.repo, PR_URL, watch, 900, 1, rounds, run)
    lines += more
    assert status == "green"
    out = land_merge.settle(world.repo, PR_URL, watch, 900, 1, rounds, run, before_merge)
    out.lines = lines + out.lines
    return out, rounds, watch


def test_a_clean_land_merges_without_delete_branch_and_cleans_up(world):
    out, rounds, _ = land(world)
    assert out.status == "merged" and out.sha == world.main_tip() and rounds.used == 0
    assert out.lines == [f"merged {PR_URL} (squash)"]
    assert [e["delete_branch"] for e in world.events("merge-attempt")] == [False]
    assert git(world.repo, "branch", "--show-current") == "main" and git(world.repo, "branch", "--list", BRANCH) == ""
    assert world.bare_git("branch", "--list", BRANCH) == ""


def test_a_blocked_switch_is_one_warning_after_the_merge_line(world):
    (world.repo / "work.txt").write_text("not committed\n")
    out, _, _ = land(world)
    assert out.status == "merged" and out.lines[0] == f"merged {PR_URL} (squash)"
    assert len(out.lines) == 2 and out.lines[1].startswith("WARNING: switching to main failed: ")


def test_cleanup_of_an_unreadable_pr_never_raises(world):
    world.configure(pr={"headRefName": "", "state": "MERGED"})
    assert land_merge.cleanup(world.repo, PR_URL, run) == []


def test_a_refused_merge_for_another_reason_is_merge_failed(world):
    world.configure(merge_fail="Pull request is not mergeable: the policy prohibits it.")
    with pytest.raises(land_merge.MergeFailed) as e:
        land(world)
    assert "the policy prohibits it" in str(e.value) and "conflict" not in (str(e.value) + (e.value.hint or "")).lower()


def test_merge_reports_a_moved_head_and_a_conflict(world):
    old = world.pr_head()
    world.push_pr_commit()
    kind, value = land_merge.merge(world.repo, PR_URL, old, run)
    assert (kind, value) == ("head-moved", world.pr_head())
    world.other_commit({"f.txt": "one\nmain line\nthree\n"})
    git(world.repo, "pull", "-q", "--ff-only", "origin", BRANCH)
    (world.repo / "f.txt").write_text("one\nfeature line\nthree\n")
    git(world.repo, "commit", "-qam", "feat: edit f")
    git(world.repo, "push", "-q", "origin", BRANCH)
    assert land_merge.merge(world.repo, PR_URL, world.pr_head(), run) == ("conflicting", "")


def test_a_head_pushed_after_green_is_waited_for_before_the_merge(world):
    world.after_checks(world.push_pr_commit)
    out, _, _ = land(world)
    [merged] = world.events("merged")
    assert out.status == "merged" and merged["head"] == world.events("checks")[-1]["sha"]


def test_await_head_waits_for_the_sha_and_gives_up(world):
    watch = ship.CheckWatch(world.repo, PR_URL, 300)
    assert land_merge.await_head(watch, world.pr_head()) and watch.head == world.pr_head()
    assert not land_merge.await_head(watch, "0" * 40, polls=2)


def test_before_merge_that_refuses_ends_red_without_a_merge(world):
    out, _, _ = land(world, before_merge=lambda: (False, ["gitops PR is red"]))
    assert out.status == "red" and out.lines == ["gitops PR is red"] and world.events("merge-attempt") == []


def test_regenerate_merges_the_backlog_and_pushes_on_top(world):
    world.feature_adds_spec(199)
    world.other_adds_spec(108)
    before = world.pr_head()
    watch = ship.CheckWatch(world.repo, PR_URL, 300)
    rounds = land_merge.Rounds()
    [line] = land_merge.regenerate(world.repo, PR_URL, watch, rounds, run)
    assert line.startswith("regenerated docs/backlog.md after merging main into ") and line.endswith("(round 1/3)")
    assert watch.head == world.pr_head() != before
    text = world.bare_git("show", f"{world.pr_head()}:docs/backlog.md")
    assert "108-more-108" in text and "199-more-199" in text and "<<<<<<<" not in text


def test_regenerate_stops_on_another_file_and_leaves_the_checkout_as_it_was(world):
    (world.repo / "f.txt").write_text("one\nfeature line\nthree\n")
    git(world.repo, "commit", "-qam", "feat: edit f")
    git(world.repo, "push", "-q", "origin", BRANCH)
    world.other_commit({"f.txt": "one\nmain line\nthree\n"})
    tip = git(world.repo, "rev-parse", "HEAD")
    with pytest.raises(land_merge.Unresolvable) as e:
        land_merge.regenerate(world.repo, PR_URL, ship.CheckWatch(world.repo, PR_URL, 300), land_merge.Rounds(), run)
    assert "rebase is a human decision" in str(e.value) and "f.txt" in str(e.value)
    assert git(world.repo, "rev-parse", "HEAD") == tip and git(world.repo, "status", "--porcelain") == ""


def test_regenerate_needs_the_pr_branch_checked_out_and_a_clean_tree(world):
    git(world.repo, "switch", "-q", "-c", "other-branch")
    with pytest.raises(land_merge.Unresolvable, match="not on"):
        land_merge.regenerate(world.repo, PR_URL, ship.CheckWatch(world.repo, PR_URL, 300), land_merge.Rounds(), run)
    git(world.repo, "switch", "-q", BRANCH)
    (world.repo / "work.txt").write_text("edited\n")
    with pytest.raises(land_merge.Unresolvable, match="uncommitted"):
        land_merge.regenerate(world.repo, PR_URL, ship.CheckWatch(world.repo, PR_URL, 300), land_merge.Rounds(), run)


def test_a_refused_push_resets_the_branch_to_where_it_was(world):
    world.feature_adds_spec(199)
    world.other_adds_spec(108)
    hook = world.bare / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho 'refused by the test hook' >&2\nexit 1\n")
    hook.chmod(0o755)
    tip = git(world.repo, "rev-parse", "HEAD")
    with pytest.raises(land_merge.PlatformError, match="pushing the regenerated merge"):
        land_merge.regenerate(world.repo, PR_URL, ship.CheckWatch(world.repo, PR_URL, 300), land_merge.Rounds(), run)
    assert git(world.repo, "rev-parse", "HEAD") == tip and git(world.repo, "status", "--porcelain") == ""


def test_the_fourth_round_of_one_land_is_refused(world):
    rounds = land_merge.Rounds(used=land_merge.MAX_REGEN_ROUNDS)
    with pytest.raises(land_merge.Unresolvable, match="after 3 regeneration rounds: rebase is a human decision"):
        land_merge.regenerate(world.repo, PR_URL, ship.CheckWatch(world.repo, PR_URL, 300), rounds, run)


def test_unresolvable_is_a_merge_lock_conflict():
    assert issubclass(land_merge.Unresolvable, merge_lock.Conflict)


def test_a_backlog_conflict_is_regenerated_checked_again_and_merged(world):
    world.feature_adds_spec(199)
    world.other_adds_spec(108)
    out, rounds, _ = land(world)
    [merged] = world.events("merged")
    assert out.status == "merged" and rounds.used == 1
    assert [ln for ln in out.lines if "regenerated" in ln] and merged["head"] == world.events("merge-attempt")[-1]["match"]
    order = [(c["kind"], c["sha"] if c["kind"] == "checks" else c["head"]) for c in world.calls() if c.get("kind") in ("checks", "merged")]
    assert order.index(("checks", merged["head"])) < order.index(("merged", merged["head"]))


def test_main_moving_after_every_pushed_head_stops_after_three_rounds(world):
    world.feature_adds_spec(199)
    world.other_adds_spec(108)
    start = world.pr_head()
    numbers = iter([110, 111, 112])
    world.on_new_head_checks(lambda: world.other_adds_spec(next(numbers)), times=3)
    with pytest.raises(land_merge.Unresolvable, match="after 3 regeneration rounds"):
        land(world)
    assert int(world.bare_git("rev-list", "--merges", "--count", f"{start}..{world.pr_head()}")) == 3
    assert git(world.repo, "status", "--porcelain") == "" and world.events("merged") == []


def test_a_head_unknown_before_the_lock_is_read_and_guards_the_merge(world):
    old = world.pre
    world.configure(blind_until_checks=1, checks={"default": ["pending", "pass"]})
    world.after_compare(world.push_pr_commit)
    out, _, _ = land(world)
    assert world.events("merge-attempt")[0]["match"] == old and out.status == "merged"
    assert world.events("merged")[0]["head"] != old
