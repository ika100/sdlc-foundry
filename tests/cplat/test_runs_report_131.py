"""Spec 131 acceptance tests: the success measure of AC-131.18 as a section of `cplat platform runs report --since 7`.

The measurement itself is post-release (human step: docs/specs/131-runs-that-finish-on-their-own/measurements.md); these tests
pin the report that makes it: the "Unattended ships (spec 131)" section and `unattended_ships` in the JSON, on fixture records.
"""
import json
import re

import pytest

import runs
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)
from test_runs_report import put, rec

ENDED = "2026-10-23T10:00:00Z"


def headless(rid, outcome, cost, *, command="/component:ship 7", reason=None, stop=None, verification_left=None, complete=True, **kw):
    extra = {"command": command, "sessions": 3, "stop_reason": stop or {"done": "done", "escalated": "escalated"}.get(outcome, "error"),
             "usage": {"sessions": ["s"], "price_table": "2026-10-25", "incomplete": None, "by_phase": {}, "by_role": {}, "by_model": {},
                       "totals": {"calls": 3, "failed_calls": 0, "input": 1, "output": 1, "cache_read": 0, "cache_write": 0,
                                  "cost_usd": cost, "cost_complete": complete, "models_without_price": []}}, **kw}
    if verification_left is not None:
        extra["budget"] = {"limits": {}, "used": {}, "limit": "invocations", "phase": "verify", "point": "session",
                           "verification_left": verification_left}
    r = rec(rid, ENDED, kind="headless", outcome=outcome, mode="headless",
            escalation={"reason": reason, "cause": "decision"} if reason else None, **extra)
    return r


@pytest.fixture()
def mixed(store):
    for r in [
        headless("h1", "done", 2.0), headless("h2", "done", 3.0), headless("h3", "done", 5.0),
        headless("h4", "escalated", 4.0, reason="no progress: unit task:t2 after 2 sessions without a commit"),
        headless("h5", "failed", 1.0),
        headless("h6", "escalated", 1.0, reason="tests red", complete=False),
        headless("h7", "escalated", 0.5, reason="waiting for approval to run git push"),
        headless("h8", "escalated", 0.0, reason="preflight failed: blocked-by-settings"),
        headless("h9", "escalated", 2.0, reason="budget exhausted: invocations", stop="budget", verification_left=True),
        headless("sys1", "done", 6.0, command="/system:ship 12"),
        headless("fix", "done", 9.0, command="/component:fix the price"),                  # not a ship
        rec("plain-ship", ENDED, kind="ship", outcome="done"),                              # not under headless
    ]:
        put(store, r)
    return store


def section(capsys, *args):
    assert runs.main(["report", "--since", "7", *args]) == 0
    out = capsys.readouterr().out
    assert "Unattended ships (spec 131):" in out
    return out.split("Unattended ships (spec 131):")[1]


def test_the_json_has_the_unattended_ship_numbers(mixed, capsys):  # AC-131.18
    assert runs.main(["report", "--json", "--since", "7"]) == 0
    u = json.loads(capsys.readouterr().out)["unattended_ships"]
    assert u["runs"] == 10 and u["done"] == 4                            # /system:ship counts, /component:fix does not
    assert u["done_pct"] == pytest.approx(40.0, abs=0.1)
    assert u["spend_total"] == pytest.approx(23.5) and u["spend_bad"] == pytest.approx(7.5)
    assert u["spend_bad_pct"] == pytest.approx(7.5 / 23.5 * 100, abs=0.1)
    assert u["unknown_cost"] == 1
    assert u["approval_escalations"] == 2                                # the git push approval and blocked-by-settings
    assert u["verification_budget_stops"] == 1


def test_the_text_section_marks_each_target(mixed, capsys):  # AC-131.18
    text = section(capsys)
    assert re.search(r"  runs: 10 \(/component:ship and /system:ship under cplat headless\)", text)
    assert re.search(r"  done: 4/10 = 40(\.\d)?%   \(target >= 70%\)   MISSED", text)
    assert re.search(r"  spend in escalated or failed: \$7\.5\d? of \$23\.5\d? = 3[12](\.\d)?%   \(target < 20%\)   MISSED   "
                     r"\[1 runs? with unknown cost\]", text)
    assert "  escalations on a git/gh approval: 2   (target 0)   MISSED" in text
    assert "  budget stops with only verification left: 1   (target 0)   MISSED" in text


def test_every_target_met_is_ok(store, capsys):  # AC-131.18
    for i in range(9):
        put(store, headless(f"d{i}", "done", 3.0))
    put(store, headless("e1", "escalated", 1.0, reason="tests red"))
    text = section(capsys)
    assert "MISSED" not in text
    assert re.search(r"  done: 9/10 = 90(\.\d)?%   \(target >= 70%\)   ok", text)
    assert re.search(r"= [34](\.\d)?%   \(target < 20%\)   ok", text)
    assert "  escalations on a git/gh approval: 0   (target 0)   ok" in text
    assert "  budget stops with only verification left: 0   (target 0)   ok" in text


def test_a_budget_stop_with_the_verification_left_false_is_not_counted(store, capsys):  # AC-131.18
    put(store, headless("b1", "escalated", 1.0, reason="budget exhausted: cost", stop="budget", verification_left=False))
    assert runs.main(["report", "--json", "--since", "7"]) == 0
    assert json.loads(capsys.readouterr().out)["unattended_ships"]["verification_budget_stops"] == 0


def test_no_unattended_ship_means_runs_0_and_no_division_by_zero(store, capsys):  # AC-131.18
    put(store, rec("plain-ship", ENDED, kind="ship", outcome="done"))
    text = section(capsys)
    assert "  runs: 0" in text and "MISSED" not in text and "   ok" not in text
    assert runs.main(["report", "--json", "--since", "7"]) == 0
    assert json.loads(capsys.readouterr().out)["unattended_ships"]["runs"] == 0
