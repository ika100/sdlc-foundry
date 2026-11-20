"""Module-level tests of dispatch_gate (spec 210, task t6): the order of the holds, the needs, the hints and the warning."""
import datetime as dt

import pytest

import dispatch_budget as db
import dispatch_gate as dg
import dispatch_pace as dpace
from dispatch_policy import Policy

NOW = dt.datetime(2026, 11, 18, 12, 0, 0)
DAY = "2026-11-18"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.setattr(db, "_since", lambda slug, key: "2026-11-18T10:00:00Z")
    monkeypatch.setattr(dg.ur, "any_reading_since", lambda epoch: False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(dg.dpace, "pace", lambda policy, now: dpace.Pace(max_running=1, filler=True))


def _policy(mode="cost", **budget):
    return Policy(values={"budget": {"mode": mode, **budget}})


def _usage(**kw):
    return db.Usage(DAY, kw.pop("used", 0), **kw)


def _gate(policy, usage=None, state=None):
    return dg.gate("r", policy, state or {}, usage or _usage(), now=NOW)


def test_pause_comes_before_everything():
    usage = _usage(usd=9.0, month_usd=90.0)
    g = _gate(_policy("plan", usd_per_day=1.0), usage, {"steering": {"paused": "pause"}})
    assert (g.why_not, g.text) == ("paused", "paused")
    assert _gate(_policy(usd_per_day=1.0), usage, {"steering": {"paused": "drain"}}).why_not == "drain"


def test_plan_hold_comes_before_the_usd_caps(monkeypatch):
    monkeypatch.setattr(dg.dpace, "pace", lambda policy, now: dpace.Pace(hold=("plan window", "plan-window 83 % ≥ 80 %")))
    g = _gate(_policy("plan", usd_per_day=1.0), _usage(usd=2.0))
    assert (g.why_not, g.text, g.max_running, g.filler) == ("plan window", "plan-window 83 % ≥ 80 %", None, False)
    assert g.plan is not None and g.plan["hold"] == "plan-window 83 % ≥ 80 %"
    assert [n["id"] for n in g.needs] == [f"budget:r:{DAY}"]


def test_usd_daily_before_monthly_before_tokens():
    policy = _policy(usd_per_day=1.0, usd_per_month=2.0, tokens_per_day=10)
    usage = _usage(used=50, usd=1.2, month_usd=30.4, unknown=["u1"], unknown_usd=["u2"])
    g = _gate(policy, usage)
    assert (g.why_not, g.text) == ("daily budget reached", "daily budget reached: $1.20 of $1.00")
    g = _gate(_policy(usd_per_month=2.0, tokens_per_day=10), usage)
    assert (g.why_not, g.text) == ("monthly budget reached", "monthly budget reached: $30.40 of $2.00")
    g = _gate(_policy(tokens_per_day=10), usage)
    assert (g.why_not, g.text) == ("daily budget reached", "daily budget reached: 50 of 10 tokens")
    g = _gate(_policy(tokens_per_day=100), usage)
    assert (g.why_not, g.text) == ("usage unknown", "usage unknown: u1")


def test_unknown_usd_only_matters_with_a_usd_cap():
    usage = _usage(unknown_usd=["u2"])
    assert _gate(_policy(), usage).why_not is None
    assert _gate(_policy(usd_per_day=5.0), usage).text == "usage unknown: u2"


def test_mode_plan_needs_token_knowledge_and_caps_only_when_set():
    assert _gate(_policy("plan"), _usage(usd=99.0)).why_not is None
    g = _gate(_policy("plan"), _usage(unknown=["u1", "u3"]))
    assert g.text == "usage unknown: u1, u3"
    assert (g.max_running, g.filler) == (None, False)
    free = _gate(_policy("plan"))
    assert (free.max_running, free.filler, free.plan is not None) == (1, True, True)


def test_cost_mode_has_no_plan_and_no_filler():
    g = _gate(_policy(usd_per_day=5.0))
    assert (g.plan, g.max_running, g.filler, g.why_not) == (None, None, False, None)
    assert g.cost == {"day": DAY, "used_usd": 0.0, "limit_usd": 5.0, "month_used_usd": 0.0, "month_limit_usd": None}


def test_cost_doc_rounds_to_two_decimals():
    doc = dg.cost_doc(_usage(usd=1.2349, month_usd=30.4051), _policy(usd_per_day=5.0, usd_per_month=100.0))
    assert doc["used_usd"] == 1.23 and doc["month_used_usd"] == 30.41 and doc["month_limit_usd"] == 100.0


def test_each_need_and_its_id():
    g = _gate(_policy(usd_per_day=1.0, usd_per_month=2.0, tokens_per_day=10), _usage(used=50, usd=1.2, month_usd=3.0))
    assert [n["id"] for n in g.needs] == [f"budget:r:{DAY}", "budget:r:2026-11"]
    daily, monthly = g.needs
    assert daily["reason"] == "daily cost budget reached: $1.20 of $1.00" and daily["command"] == dg.NEED_DAILY_USD
    assert monthly["reason"] == "monthly cost budget reached: $3.00 of $2.00" and monthly["command"] == dg.NEED_MONTHLY_USD
    assert daily["kind"] == "budget" and daily["stage"] == "Build" and daily["object"]["type"] == "dispatch"
    assert daily["since"] == "2026-11-18T10:00:00Z"
    tokens = _gate(_policy(tokens_per_day=10), _usage(used=50)).needs
    assert [n["reason"] for n in tokens] == ["daily token budget reached: 50 of 10 tokens"]
    assert tokens[0]["command"] == db.NEED_COMMAND
    assert _gate(_policy(usd_per_day=5.0), _usage(usd=1.0)).needs == []


def test_plan_usage_unknown_need(monkeypatch):
    monkeypatch.setattr(dg.dpace, "pace", lambda policy, now: dpace.Pace(hold=("plan usage unknown", dpace.UNKNOWN_TEXT)))
    g = _gate(_policy("plan"))
    assert g.why_not == "plan usage unknown"
    assert [(n["id"], n["reason"], n["command"]) for n in g.needs] == [
        (f"budget:r:{DAY}", dg.NEED_PLAN_UNKNOWN_REASON, dg.NEED_PLAN_UNKNOWN)]


def test_shared_day_id_keeps_the_first_need(monkeypatch):
    monkeypatch.setattr(dg.dpace, "pace", lambda policy, now: dpace.Pace(hold=("plan usage unknown", dpace.UNKNOWN_TEXT)))
    g = _gate(_policy("plan", usd_per_day=1.0), _usage(usd=2.0))
    assert [n["reason"] for n in g.needs] == ["daily cost budget reached: $2.00 of $1.00"]


def test_hint_for_readings_in_mode_cost(monkeypatch):
    seen = []
    monkeypatch.setattr(dg.ur, "any_reading_since", lambda epoch: seen.append(epoch) or True)
    assert _gate(_policy(usd_per_day=5.0)).hints == [dg.HINT_PLAN]
    assert seen == [NOW.timestamp() - 7 * 86400]
    assert _gate(_policy("plan")).hints == []


def test_hint_for_an_api_key_without_readings_in_mode_plan(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    assert _gate(_policy("plan")).hints == [dg.HINT_COST]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    assert _gate(_policy("plan")).hints == []
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    monkeypatch.setattr(dg.ur, "any_reading_since", lambda epoch: True)
    assert _gate(_policy("plan")).hints == []


def test_tokens_per_day_warning():
    g = _gate(_policy(tokens_per_day=10), _usage(usd=1.2))
    assert g.warnings == ["budget.tokens_per_day is deprecated: set budget.usd_per_day (cost today: $1.20)"]
    assert _gate(_policy(usd_per_day=5.0)).warnings == []
