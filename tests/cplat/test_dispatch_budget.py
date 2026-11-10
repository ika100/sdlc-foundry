"""Module-level tests of dispatch_budget (spec 167): the ledger, unit usage, unknown usage, the limit, the need and the hint."""
import datetime as dt

import pytest

import dispatch_budget as db
import dispatch_state as ds
import runs
from dispatch_policy import Policy

SLUG = "acme/shop-api"
NOW = dt.datetime(2026, 11, 10, 12, 0, 0)


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.delenv("CPLAT_RUNS_REPO", raising=False)
    clock = {"now": NOW}
    monkeypatch.setattr(ds, "now", lambda: clock["now"])
    monkeypatch.setattr(runs, "_safe_buffer", lambda: [])
    monkeypatch.setattr(runs, "active", lambda rid: None)
    return clock


def _unit(tmp_path, name, result):
    wt = tmp_path / name
    wt.mkdir(exist_ok=True)
    return {"unit": name, "worktree": str(wt)}, result


def _book(monkeypatch, units):
    """book() with unit files and result files given as (unit, result) pairs."""
    results = {u["unit"]: r for u, r in units}
    monkeypatch.setattr(ds, "read_result", lambda wt: results[next(u["unit"] for u, _ in units if u["worktree"] == str(wt))])
    return db.book(SLUG, [u for u, _ in units])


def _policy(limit):
    return Policy(values={"budget": {"tokens_per_day": limit, "per_unit": {}}})


def test_the_growth_of_a_unit_is_booked_once_and_agent_calls_are_added(home, tmp_path, monkeypatch):
    u = _unit(tmp_path, "issue-1.1", {"run_id": "r1", "ended_at": "x", "tokens": 100})
    usage = _book(monkeypatch, [u])
    assert (usage.day, usage.used, usage.unknown) == ("2026-11-10", 100, [])
    assert _book(monkeypatch, [u]).used == 100                                       # nothing grew: nothing booked twice
    assert db.book_agent(SLUG, 50) == 50
    st = ds.load(SLUG)
    assert st["ledger"]["2026-11-10"] == {"units": {"issue-1.1": 100}, "agent": 50} and st["counted"] == {"issue-1.1": 100}


def test_a_call_without_usage_books_the_ceiling(home):
    assert db.book_agent(SLUG, None) == 200_000
    assert ds.load(SLUG)["ledger"]["2026-11-10"]["agent"] == 200_000


def test_the_day_changes_at_local_midnight_and_the_growth_goes_to_the_new_day(home, tmp_path, monkeypatch):
    u = _unit(tmp_path, "issue-1.1", {"run_id": "r1", "ended_at": None})
    monkeypatch.setattr(db, "_peek", lambda rid: 100)
    assert _book(monkeypatch, [u]).used == 100
    home["now"] = dt.datetime(2026, 11, 11, 0, 5)
    monkeypatch.setattr(db, "_peek", lambda rid: 130)
    usage = _book(monkeypatch, [u])
    assert (usage.day, usage.used) == ("2026-11-11", 30)


def test_unknown_usage_is_named_until_known_or_the_day_changes(home, tmp_path, monkeypatch):
    u = _unit(tmp_path, "issue-1.1", {"run_id": "r1", "ended_at": "x", "tokens": None})
    assert _book(monkeypatch, [u]).unknown == ["issue-1.1"]
    assert _book(monkeypatch, [u]).unknown == ["issue-1.1"]
    home["now"] = dt.datetime(2026, 11, 11, 0, 5)
    assert _book(monkeypatch, [u]).unknown == []
    known = _unit(tmp_path, "issue-1.1", {"run_id": "r1", "ended_at": "x", "tokens": 7})
    assert _book(monkeypatch, [known]).used == 7


def test_the_usage_of_a_finished_record_replaces_a_missing_result_figure(home, tmp_path, monkeypatch):
    totals = {"input": 10, "output": 5, "cache_read": 3, "cache_write": 2}
    monkeypatch.setattr(runs, "_safe_buffer", lambda: [{"run_id": "r1", "usage": {"totals": totals, "incomplete": None}}])
    assert db.unit_tokens({"unit": "u"}, {"run_id": "r1", "ended_at": "x", "tokens": None}) == 20
    monkeypatch.setattr(runs, "_safe_buffer", lambda: [{"run_id": "r1", "usage": {"totals": totals, "incomplete": "gap"}}])
    assert db.unit_tokens({"unit": "u"}, {"run_id": "r1", "ended_at": "x", "tokens": None}) is None
    monkeypatch.setattr(runs, "_safe_buffer", lambda: [])
    assert db.unit_tokens({"unit": "u"}, {"run_id": "r1", "ended_at": "x", "tokens": None}) is None


def test_a_unit_that_has_not_started_a_session_has_used_nothing(home):
    assert db.unit_tokens({"unit": "u"}, None) == 0
    assert db.unit_tokens({"unit": "u"}, {"run_id": "r1", "ended_at": None}) == 0


def test_the_limit_is_reached_at_the_limit_and_never_without_one(home):
    usage = db.Usage("2026-11-10", 1000)
    assert db.reached(usage, _policy(1000)) and not db.reached(usage, _policy(1001)) and not db.reached(usage, _policy(None))


def test_the_budget_need_is_one_per_day_and_resolved_below_the_limit(home):
    usage = db.Usage("2026-11-10", 20_104_332)
    need = db.budget_need(SLUG, usage, _policy(20_000_000), ["issue-123.1"])
    assert need["id"] == "budget:acme/shop-api:2026-11-10" and need["kind"] == "budget"
    assert need["reason"] == "daily token budget reached: 20104332 of 20000000 tokens"
    assert need["consequence"] == {"used": 20_104_332, "limit": 20_000_000, "running": ["issue-123.1"]}
    home["now"] = dt.datetime(2026, 11, 10, 15, 0)
    assert db.budget_need(SLUG, usage, _policy(20_000_000), [])["since"] == need["since"]
    assert db.budget_need(SLUG, usage, _policy(30_000_000), []) is None


def test_the_hint_lists_seven_days_oldest_first_from_top_level_records(home, monkeypatch):
    def at(days_ago):
        return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
    usage = {"totals": {"input": 100, "output": 20, "cache_read": 0, "cache_write": 0}}
    monkeypatch.setattr(ds, "now", lambda: dt.datetime.now())
    monkeypatch.setattr(runs, "_safe_buffer", lambda: [
        {"run_id": "a", "repo": SLUG, "started_at": at(0), "usage": usage},
        {"run_id": "b", "repo": SLUG, "started_at": at(0), "parent": "a", "usage": usage},
        {"run_id": "c", "repo": "other/repo", "started_at": at(0), "usage": usage},
        {"run_id": "d", "repo": SLUG, "started_at": at(3), "usage": {**usage, "incomplete": "gap"}}])
    hint = db.history_hint(SLUG)
    assert len(hint) == 7 and [h["day"] for h in hint] == sorted(h["day"] for h in hint)
    assert hint[-1] == {"day": dt.date.today().isoformat(), "tokens": 120}
    assert hint[-4]["tokens"] is None and hint[0]["tokens"] == 0
