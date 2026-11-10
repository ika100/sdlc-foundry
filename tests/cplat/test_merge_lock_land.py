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
