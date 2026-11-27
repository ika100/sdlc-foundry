"""The repo merge lock around `ship land` and the lock itself (spec 167, ADR-089): unit tests next to the acceptance tests."""
import pytest

import merge_lock
import ship
from test_ship import check, gh, repo, to_land  # noqa: F401  (fixtures)


def test_a_lone_land_takes_the_repo_lock_and_releases_it(repo, gh, monkeypatch):
    seen = []
    real = merge_lock.held

    def spy(slug, who, timeout, interval=5):
        seen.append((slug, who))
        return real(slug, who, timeout, interval)
    monkeypatch.setattr(merge_lock, "held", spy)
    to_land(repo, gh)
    gh.checks = [[check("test", "pass")]]
    ok, _ = ship.land(repo, timeout=600, interval=10)
    assert ok and seen == [("acme/shop-api", "pr 7")]
    with merge_lock.held("acme/shop-api", "again", 0.1):     # released: free to take at once
        pass


def test_a_busy_lock_stops_the_land_before_a_merge_and_without_a_fix_round(repo, gh, monkeypatch):
    to_land(repo, gh)
    gh.checks = [[check("test", "pass")]]
    monkeypatch.setattr(merge_lock, "sleep", lambda s: None)
    monkeypatch.setattr(merge_lock.release_hold, "alive", lambda pid: False)     # the holder's process is gone
    with merge_lock.held("acme/shop-api", "pr 9 (issue-9)", 5):
        with pytest.raises(merge_lock.Busy, match="held by pr 9 .issue-9. since"):
            # a zero timeout: the lock is taken by this process, flock on a second open file description blocks
            ship.land(repo, timeout=0, interval=0)
    assert gh.merges == []
    assert ship.load_state(repo).get("fix_rounds", 0) == 0


def test_an_unreadable_compare_answer_merges_nothing(repo, gh, monkeypatch):
    to_land(repo, gh)
    gh.checks = [[check("test", "pass")]]
    answer, asked = gh.__call__, []

    def broken(args, *, cwd, check=True):
        if args[:1] == ["api"] and "/compare/" in args[1]:
            asked.append(args)
            return ""
        return answer(args, cwd=cwd, check=check)
    monkeypatch.setattr(ship, "gh", broken)
    with pytest.raises(merge_lock.Unknown, match="could not tell whether"):
        ship.land(repo, timeout=600, interval=10)
    assert gh.merges == []
    assert len(asked) == merge_lock.BEHIND_TRIES


def test_an_unknown_head_is_read_before_the_behind_check(repo, gh, monkeypatch):
    to_land(repo, gh)
    watch = ship.CheckWatch(repo, "7", 600)
    assert watch.head is None
    assert merge_lock.catch_up(repo, "https://github.com/acme/shop-api/pull/7", watch, 600, 10).updated is False
    assert ["pr", "view", "7", "--json", "headRefOid"] in gh.calls


def test_a_merge_that_would_pass_the_prompt_baseline_is_refused_before_the_update(repo, gh, monkeypatch):
    """#1076: each side fits the baseline, together they do not: a land problem with the overshoot, no update."""
    to_land(repo, gh)
    monkeypatch.setattr(merge_lock, "_behind", lambda *a: (1, "main"))
    monkeypatch.setattr(merge_lock, "_merged_prompt_bytes", lambda repo, base, head: (390315, 390314))
    watch = ship.CheckWatch(repo, "7", 600)
    with pytest.raises(merge_lock.PromptsOver, match="1 more than the baseline 390314") as e:
        merge_lock.catch_up(repo, "https://github.com/acme/shop-api/pull/7", watch, 600, 10)
    assert "shorten the prompts" in e.value.hint
    assert not any(c[:2] == ["pr", "update-branch"] for c in gh.calls)


def test_a_merge_within_the_prompt_baseline_goes_on_to_the_update(repo, gh, monkeypatch):
    to_land(repo, gh)
    monkeypatch.setattr(merge_lock, "_behind", lambda *a: (1, "main"))
    monkeypatch.setattr(merge_lock, "_merged_prompt_bytes", lambda repo, base, head: (390314, 390314))
    gh.checks = [[check("test", "pass")]]
    updates = []
    monkeypatch.setattr(merge_lock, "run", lambda cmd, **k: updates.append(cmd) or type("R", (), {"returncode": 1, "stderr": "conflict", "stdout": ""})())
    watch = ship.CheckWatch(repo, "7", 600)
    with pytest.raises(merge_lock.Conflict):
        merge_lock.catch_up(repo, "https://github.com/acme/shop-api/pull/7", watch, 600, 10)
    assert updates and updates[0][:3] == ["gh", "pr", "update-branch"]
