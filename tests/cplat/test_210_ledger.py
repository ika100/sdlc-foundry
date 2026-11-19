"""Module-level tests of the USD ledger of dispatch_budget (spec 210, task t4): unit growth, agent calls, unknown USD, month sum."""
import datetime as dt

import pytest

import dispatch_budget as db
import dispatch_state as ds
import runs

SLUG = "acme/shop-api"
NOW = dt.datetime(2026, 11, 10, 12, 0, 0)


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.delenv("CPLAT_RUNS_REPO", raising=False)
    monkeypatch.setattr(ds, "now", lambda: NOW)
    monkeypatch.setattr(runs, "_safe_buffer", lambda: [])
    monkeypatch.setattr(runs, "active", lambda rid: None)
    return tmp_path


def _book(home, monkeypatch, results):
    units = []
    for name, result in results.items():
        wt = home / name
        wt.mkdir(exist_ok=True)
        units.append({"unit": name, "worktree": str(wt)})
    by_wt = {str(home / n): r for n, r in results.items()}
    monkeypatch.setattr(ds, "read_result", lambda wt: by_wt[str(wt)])
    return db.book(SLUG, units)


def _tape(monkeypatch):
    seen = []
    import usage_readings
    monkeypatch.setattr(usage_readings, "append_booked", lambda tokens, at=None: seen.append(tokens))
    return seen


def test_the_growth_of_a_units_usd_is_booked_once_and_tokens_go_to_the_tape(home, monkeypatch):
    tape = _tape(monkeypatch)
    result = {"run_id": "r1", "ended_at": "x", "tokens": 100, "cost_usd": 1.5}
    usage = _book(home, monkeypatch, {"issue-1.1": result})
    assert (usage.used, usage.usd, usage.month_usd, usage.unknown_usd) == (100, 1.5, 1.5, [])
    result["cost_usd"] = 2.0
    assert _book(home, monkeypatch, {"issue-1.1": result}).usd == pytest.approx(2.0)
    day = ds.load(SLUG)["ledger"]["2026-11-10"]
    assert day["usd"] == {"issue-1.1": pytest.approx(2.0)} and ds.load(SLUG)["counted_usd"] == {"issue-1.1": 2.0}
    assert tape == [100, 0]                                                       # only the growth of the tokens is taped


def test_an_agent_call_books_its_reported_cost_else_priced_tokens_else_the_ceiling(home, monkeypatch):
    tape = _tape(monkeypatch)
    assert db.book_agent(SLUG, 1000, 0.25, "claude-opus-5") == 1000
    assert ds.load(SLUG)["ledger"]["2026-11-10"]["agent_usd"] == pytest.approx(0.25)
    db.book_agent(SLUG, 1_000_000, None, "claude-opus-5")                         # priced as input: $5.00
    assert ds.load(SLUG)["ledger"]["2026-11-10"]["agent_usd"] == pytest.approx(5.25)
    assert db.book_agent(SLUG, None, None, "claude-opus-5") == db.AGENT_CEILING   # 200 000 tokens at $5 per million
    assert ds.load(SLUG)["ledger"]["2026-11-10"]["agent_usd"] == pytest.approx(6.25)
    db.book_agent(SLUG, 10)                                                       # the old positional call still works
    assert tape[:3] == [1000, 1_000_000, db.AGENT_CEILING] and tape[3] == 10


def test_an_unpriced_model_is_booked_at_the_highest_input_price(home, monkeypatch):
    import usage_cost
    top = max(p["input"] for p in usage_cost.load_prices().models.values())
    db.book_agent(SLUG, 1_000_000, None, "claude-nowhere-9")
    assert ds.load(SLUG)["ledger"]["2026-11-10"]["agent_usd"] == pytest.approx(top)


def test_a_unit_without_a_known_cost_is_marked_unknown_usd_for_the_day(home, monkeypatch):
    _tape(monkeypatch)
    result = {"run_id": "r1", "ended_at": "x", "tokens": 100, "cost_usd": None}
    usage = _book(home, monkeypatch, {"issue-1.1": result})
    assert usage.unknown == [] and usage.unknown_usd == ["issue-1.1"]
    assert ds.load(SLUG)["unknown_usd"] == {"issue-1.1": "2026-11-10"}
    result["cost_usd"] = 3.0
    assert _book(home, monkeypatch, {"issue-1.1": result}).unknown_usd == []
    assert ds.load(SLUG)["unknown_usd"] == {}


def test_a_record_that_is_not_cost_complete_leaves_the_usd_unknown(home, monkeypatch):
    totals = {"input": 5, "output": 1, "cache_read": 0, "cache_write": 0, "cost_usd": 0.1, "cost_complete": False}
    monkeypatch.setattr(runs, "_safe_buffer", lambda: [{"run_id": "r1", "usage": {"totals": totals}}])
    assert db.unit_usage({}, {"run_id": "r1", "ended_at": "x", "tokens": None}) == (6, None)
    monkeypatch.setattr(runs, "_safe_buffer", lambda: [{"run_id": "r1", "usage": {"totals": {**totals, "cost_complete": True}}}])
    assert db.unit_usage({}, {"run_id": "r1", "ended_at": "x", "tokens": None}) == (6, 0.1)


def test_the_month_sums_the_ledger_days_of_the_local_month(home, monkeypatch):
    def day(d, usd, agent_usd=0.0):
        return {"units": {}, "agent": 0, "usd": {"a": usd}, "agent_usd": agent_usd}
    ds.update(SLUG, lambda st: st["ledger"].update({"2026-11-03": day(3, 60.0), "2026-11-10": day(10, 1.0, 0.5),
                                                    "2026-10-31": day(31, 500.0)}))
    usage = db.usage_today(SLUG)
    assert usage.usd == pytest.approx(1.5) and usage.month_usd == pytest.approx(61.5)
