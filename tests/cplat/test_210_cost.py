"""Spec 210 acceptance tests: mode cost (AC-210.3, AC-210.4) and the cost lines of `plan` and `status` (AC-210.2).

Contract: design.md "The gate" (order, texts, needs), "Data" (`ledger[day].usd`, `agent_usd`, the result file's `cost_usd`),
"`plan --json` and `status --json`" (`cost`, `warnings`, text lines), "Policy". Seams: the dispatcher world; the fake claude reports
`total_cost_usd` 0.01 per agent call; a variant of the fake headless reports `cost_usd` in its result file; `world.write_state`
seeds the ledger; `world.set_now` moves the clock.
"""
import datetime as dt
import re

import pytest

import dispatch_world
from dispatch_world import world  # noqa: F401  (fixture)
from support_210 import TODAY, issues, ledger
from waiting import fake_prelude

WARNING = re.compile(r"^budget\.tokens_per_day is deprecated: set budget\.usd_per_day \(cost today: \$\d+(\.\d+)?\)$", re.M)


def _costing_headless(world):
    """The fake headless whose result file also carries `cost_usd` (what `World.behave(cost_usd=...)` sets)."""
    old = '"tokens": cfg.get("tokens", 1234)})'
    text = dispatch_world.FAKE_HEADLESS.replace(old, '"tokens": cfg.get("tokens", 1234), "cost_usd": cfg.get("cost_usd")})')
    assert text != dispatch_world.FAKE_HEADLESS
    exe = world.bin / "fake-headless-cost"
    exe.write_text(text % {"py": dispatch_world.sys.executable, "pre": fake_prelude()})
    exe.chmod(0o755)
    world.mp.setenv("CPLAT_DISPATCH_HEADLESS", str(exe))


def _budget_needs(world):
    return [i for i in world.needs("--json").json()["items"] if i["kind"] == "budget"]


# ---------------- AC-210.3: the USD caps ----------------

def test_once_the_sum_reaches_the_daily_usd_limit_nothing_starts_and_no_agent_call_is_made_ac_210_3(world):  # AC-210.3
    world.policy(slots=2, budget={"usd_per_day": 5})
    issues(world, 2)
    ledger(world, usd={"issue-9.1": 4.0}, agent_usd=1.0)
    r = world.run("start", "--once")
    assert r.rc == 0 and "no starts: daily budget reached: $5.00 of $5.00" in r.out, r
    assert world.calls() == [] and world.claude_calls() == [] and world.gh_writes() == []
    doc = world.plan()
    assert doc["starts"] == {"allowed": False, "why_not": "daily budget reached", "text": "daily budget reached: $5.00 of $5.00"}
    assert doc["cost"]["used_usd"] == pytest.approx(5.0) and doc["cost"]["limit_usd"] == 5.0
    assert all(c["verdict"] == "held" and c["reason"] == "budget" and c["detail"] == "daily budget reached: $5.00 of $5.00"
               for c in doc["candidates"])


def test_below_the_limit_units_start_and_the_cost_of_an_agent_call_is_booked_ac_210_3(world):  # AC-210.3
    world.policy(slots=1, budget={"usd_per_day": 5})
    issues(world, 1)
    ledger(world, usd={"issue-9.1": 1.0})
    assert world.run("start", "--once").rc == 0
    assert [c["unit"] for c in world.calls()] == ["issue-1.1"]
    day = world.state()["ledger"][TODAY]
    assert len(world.claude_calls()) >= 1
    assert day["agent_usd"] == pytest.approx(0.01 * len(world.claude_calls()))        # the call's reported total_cost_usd


def test_a_units_cost_is_added_up_and_stops_the_starts_ac_210_3(world):  # AC-210.3
    _costing_headless(world)
    world.policy(slots=1, budget={"usd_per_day": 5})
    issues(world, 2)
    world.behave("issue-1.1", mode="now", then="escalate", tokens=100, cost_usd=5.5)
    world.run("start", "--once")
    world.wait_ended("issue-1.1")
    r = world.run("start", "--once")
    assert re.search(r"no starts: daily budget reached: \$5\.5\d of \$5\.00", r.out), r.out
    assert world.calls_of("issue-2.1") == []
    assert world.run("status", "--json").json()["cost"]["used_usd"] >= 5.5


def test_one_budget_need_per_day_and_running_units_continue_ac_210_3(world):  # AC-210.3
    world.policy(slots=2, budget={"usd_per_day": 5})
    issues(world, 3)
    world.behave(mode="wait")
    world.run("start", "--once")
    pids = [c["pid"] for c in world.calls()]
    ledger(world, usd={"issue-9.1": 5.0})
    for _ in range(2):
        assert world.run("start", "--once").rc == 0
    assert all(world.alive(p) for p in pids) and len(world.calls()) == 2
    [need] = _budget_needs(world)
    assert need["id"] == f"budget:acme/shop-api:{TODAY}" and need["object"]["repo"] == "acme/shop-api"
    assert need["reason"].startswith("daily cost budget reached: $5.") and " of $5.00" in need["reason"]
    assert "budget.usd_per_day" in need["command"] and "midnight" in need["command"]


def test_starts_continue_after_midnight_without_a_need_ac_210_3(world):  # AC-210.3
    world.policy(slots=1, budget={"usd_per_day": 5})
    issues(world, 1)
    ledger(world, usd={"issue-9.1": 5.0})
    assert world.run("start", "--once").rc == 0 and world.calls() == [] and len(_budget_needs(world)) == 1
    world.set_now(dt.datetime(2026, 11, 11, 0, 5))
    assert world.run("start", "--once").rc == 0
    assert [c["unit"] for c in world.calls()] == ["issue-1.1"]
    assert _budget_needs(world) == []


def test_the_monthly_usd_limit_holds_from_the_first_of_the_month_and_ends_on_the_1st_ac_210_3(world):  # AC-210.3
    world.policy(slots=1, budget={"usd_per_day": 50, "usd_per_month": 100})
    issues(world, 1)
    ledger(world, day="2026-11-03", usd={"a": 60.0})
    ledger(world, day="2026-11-04", usd={"b": 40.0})
    ledger(world, day="2026-10-31", usd={"c": 500.0})                       # last month: not counted
    r = world.run("start", "--once")
    assert r.rc == 0 and "no starts: monthly budget reached: $100.00 of $100.00" in r.out, r
    assert world.calls() == [] and world.claude_calls() == []
    doc = world.plan()
    assert doc["starts"]["why_not"] == "monthly budget reached"
    assert doc["cost"]["month_used_usd"] == pytest.approx(100.0) and doc["cost"]["month_limit_usd"] == 100.0
    world.run("start", "--once")
    [need] = _budget_needs(world)
    assert need["id"] == "budget:acme/shop-api:2026-11" and need["reason"].startswith("monthly cost budget reached: $100.00 of $100.00")
    assert "budget.usd_per_month" in need["command"] and "1st" in need["command"]
    world.set_now(dt.datetime(2026, 12, 1, 0, 5))
    assert world.run("start", "--once").rc == 0
    assert [c["unit"] for c in world.calls()] == ["issue-1.1"]
    assert _budget_needs(world) == []


def test_the_daily_usd_cap_is_checked_before_the_monthly_one_ac_210_3(world):  # AC-210.3
    world.policy(slots=1, budget={"usd_per_day": 5, "usd_per_month": 100})
    issues(world, 1)
    ledger(world, usd={"a": 5.0})
    ledger(world, day="2026-11-03", usd={"b": 100.0})
    assert "no starts: daily budget reached: $5.00 of $5.00" in world.run("start", "--once").out


def test_while_a_units_usage_is_unknown_no_unit_starts_and_status_names_it_ac_210_3(world):  # AC-210.3
    _costing_headless(world)
    world.policy(slots=2, budget={"usd_per_day": 5})
    issues(world, 3)
    world.behave(mode="wait")
    world.behave("issue-1.1", mode="now", then="escalate", tokens=None, cost_usd=None)
    world.run("start", "--once")
    world.wait_ended("issue-1.1")
    r = world.run("start", "--once")
    assert r.rc == 0 and "no starts: usage unknown: issue-1.1" in r.out, r
    assert world.calls_of("issue-3.1") == []
    assert world.run("plan", "--json").json()["starts"]["why_not"] == "usage unknown"
    assert "issue-1.1" in world.run("status").out


# ---------------- AC-210.4: the deprecated token cap ----------------

def test_the_token_cap_alone_applies_as_before_ac_210_4(world):  # AC-210.4
    world.policy(slots=1, budget={"tokens_per_day": 1_000_000})
    issues(world, 1)
    world.write_state(ledger={TODAY: {"units": {}, "agent": 1_000_000}}, counted={})
    r = world.run("start", "--once")
    assert r.rc == 0 and "no starts: daily budget reached: 1000000 of 1000000 tokens" in r.out, r
    assert world.calls() == [] and world.claude_calls() == []
    [need] = _budget_needs(world)
    assert need["id"] == f"budget:acme/shop-api:{TODAY}" and "daily token budget reached: 1000000 of 1000000 tokens" in need["reason"]
    world.set_now(dt.datetime(2026, 11, 11, 0, 5))
    world.run("start", "--once")
    assert [c["unit"] for c in world.calls()] == ["issue-1.1"]


def test_plan_and_status_warn_that_the_token_cap_is_deprecated_ac_210_4(world):  # AC-210.4
    world.policy(slots=1, budget={"tokens_per_day": 1_000_000})
    for verb in ("plan", "status"):
        assert WARNING.search(world.run(verb).out), world.run(verb).out
        doc = world.run(verb, "--json").json()
        assert len(doc["warnings"]) == 1 and WARNING.search(doc["warnings"][0])


def test_the_warning_shows_the_cost_of_today_ac_210_4(world):  # AC-210.4
    world.policy(slots=1, budget={"tokens_per_day": 1_000_000})
    ledger(world, usd={"a": 1.2})
    assert "budget.tokens_per_day is deprecated: set budget.usd_per_day (cost today: $1.20)" in world.run("plan").out


def test_no_warning_without_the_token_cap_ac_210_4(world):  # AC-210.4
    world.policy(slots=1, budget={"usd_per_day": 5})
    for verb in ("plan", "status"):
        assert "deprecated" not in world.run(verb).out and world.run(verb, "--json").json()["warnings"] == []


def test_with_both_caps_the_token_cap_holds_when_reached_first_ac_210_4(world):  # AC-210.4
    world.policy(slots=1, budget={"tokens_per_day": 1_000_000, "usd_per_day": 50})
    issues(world, 1)
    ledger(world, usd={"a": 1.0}, agent=1_000_000)
    r = world.run("start", "--once")
    assert "no starts: daily budget reached: 1000000 of 1000000 tokens" in r.out, r
    assert world.calls() == []


def test_with_both_caps_the_usd_cap_holds_when_reached_first_ac_210_4(world):  # AC-210.4
    world.policy(slots=1, budget={"tokens_per_day": 1_000_000, "usd_per_day": 5})
    issues(world, 1)
    ledger(world, usd={"a": 5.0}, agent=10)
    r = world.run("start", "--once")
    assert "no starts: daily budget reached: $5.00 of $5.00" in r.out, r
    assert world.calls() == []


# ---------------- AC-210.2: the cost lines and the policy block ----------------

def test_plan_in_mode_cost_has_a_null_plan_and_the_cost_document_ac_210_2(world):  # AC-210.2
    world.policy(slots=1, budget={"usd_per_day": 5, "usd_per_month": 100})
    ledger(world, usd={"issue-1.1": 1.2})
    ledger(world, day="2026-11-05", usd={"x": 29.2})
    doc = world.plan()
    assert doc["plan"] is None
    assert doc["cost"] == {"day": TODAY, "used_usd": pytest.approx(1.2), "limit_usd": 5.0,
                           "month_used_usd": pytest.approx(30.4), "month_limit_usd": 100.0}
    out = world.run("plan").out
    assert "cost today: $1.20 of $5.00 · this month: $30.40 of $100.00" in out.splitlines()
    assert world.run("status", "--json").json()["cost"] == doc["cost"]
    assert "cost today: $1.20 of $5.00 · this month: $30.40 of $100.00" in world.run("status").out.splitlines()


def test_the_cost_line_has_no_month_part_without_a_monthly_limit_ac_210_2(world):  # AC-210.2
    world.policy(slots=1, budget={"usd_per_day": 5})
    ledger(world, usd={"issue-1.1": 1.2})
    doc = world.plan()
    assert doc["cost"]["limit_usd"] == 5.0 and doc["cost"]["month_limit_usd"] is None
    out = world.run("plan").out
    assert "cost today: $1.20 of $5.00" in out.splitlines() and "this month" not in out


def test_without_a_daily_usd_limit_the_cost_line_says_so_ac_210_2(world):  # AC-210.2
    world.policy(slots=1, budget={"tokens_per_day": 1_000_000})
    ledger(world, usd={"issue-1.1": 1.2})
    assert world.plan()["cost"]["limit_usd"] is None
    assert "cost today: $1.20 (no USD limit set)" in world.run("plan").out


def test_an_unset_daily_usd_limit_is_shown_as_unset_with_the_last_7_days_ac_210_2(world):  # AC-210.2
    world.policy_text("slots: 2\n")
    doc = world.plan()
    pol = doc["policy"]
    assert pol["unset"] == ["budget.usd_per_day"] and pol["values"]["budget"]["usd_per_day"] is None
    hint = pol["usage_hint"]
    assert len(hint) == 7 and all({"day", "tokens", "usd"} <= set(h) for h in hint)
    assert all(h["usd"] is None or isinstance(h["usd"], (int, float)) for h in hint)
    text = world.run("plan").out
    assert re.search(r"budget\.usd_per_day: unset \(required by start and resume in mode cost\) — last 7 days: 2026-11-0\d \$[\d.?]+", text), text
    assert "budget.tokens_per_day: unset (deprecated)" in text


def test_status_shows_the_same_held_reasons_as_plan_ac_210_2(world):  # AC-210.2
    world.policy(slots=1, budget={"usd_per_day": 5})
    issues(world, 2)
    ledger(world, usd={"a": 5.0})
    world.run("start", "--once")
    held = world.run("status", "--json").json()["held"]
    assert [h["item"] for h in held] == ["#1", "#2"] and all(h["reason"] == "budget" for h in held)
    assert all(h["detail"] == "daily budget reached: $5.00 of $5.00" for h in held)
    text = world.run("status").out
    assert "cost today: $5.00 of $5.00" in text and "daily budget reached: $5.00 of $5.00" in text
    plan_rows = [c for c in world.plan()["candidates"]]
    assert [(c["verdict"], c["detail"]) for c in plan_rows] == [("held", "daily budget reached: $5.00 of $5.00")] * 2
    assert "held: daily budget reached: $5.00 of $5.00" in world.run("plan").out


def test_plan_and_status_change_nothing_in_mode_cost_ac_210_2(world):  # AC-210.2
    world.policy(slots=2, budget={"usd_per_day": 5})
    issues(world, 2)
    before = world.fingerprint()
    for args in (("plan",), ("plan", "--json"), ("status",), ("status", "--json")):
        assert world.run(*args).rc == 0
    assert world.fingerprint() == before and world.calls() == [] and world.gh_writes() == [] and world.claude_calls() == []
