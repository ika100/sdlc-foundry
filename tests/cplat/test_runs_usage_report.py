"""Spec 099: acceptance / security gate results in the record (AC-099.12) and the `usage` view of `cplat runs report` (AC-099.11)."""
import json

import pytest

import runs
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)
from test_runs_report import put, rec, report_json
from test_ship import git, repo  # noqa: F401  (fixtures)

TABLE = "2026-10-25"


def section(tokens, cost, *, complete=True):
    zero = {"calls": 1, "failed_calls": 0, "input": tokens, "output": 0, "cache_read": 0, "cache_write": 0, "cost_usd": cost}
    return {"sessions": ["s"], "price_table": TABLE, "incomplete": None,
            "totals": {**zero, "cost_complete": complete, "models_without_price": [] if complete else ["m-x"]},
            "by_phase": {"unphased": zero}, "by_role": {"main": zero}, "by_model": {"m": zero}}


# ---------------- AC-099.12 gates ----------------

def test_a_build_run_states_both_gates_and_the_last_call_wins(repo, store):
    """AC-099.12: `cplat runs gate` sets the result; a gate never told about is `not run`."""
    d = ["--dir", str(repo)]
    runs.main(["begin", "build", "--spec", "007-price-alerts", *d])
    assert runs.main(["gate", "acceptance", "failed", *d]) == 0
    assert runs.main(["gate", "acceptance", "passed", *d]) == 0
    runs.main(["end", "--outcome", "done", *d])
    (r,) = stored(store)
    assert r["gates"] == {"acceptance": "passed", "security": "not run"}


def test_a_ship_run_without_any_gate_call_has_both_not_run(clock, store):
    """AC-099.12: ship records always carry `gates`."""
    rid = runs.start("ship", repo="acme/a")
    runs.finish(rid, "escalated", escalation={"reason": "x", "cause": "code"})
    (r,) = stored(store)
    assert r["gates"] == {"acceptance": "not run", "security": "not run"}


def test_other_kinds_have_no_gates(clock, store):
    """AC-099.12: gates are written for ship and build only."""
    runs.finish(runs.start("pr-wait", repo="acme/a"), "done")
    assert "gates" not in stored(store)[0]


def test_the_gate_command_never_fails_without_a_run(repo, capsys):
    """AC-099.12: `cplat runs gate` prints nothing and never fails a command."""
    assert runs.main(["gate", "security", "failed", "--dir", str(repo)]) == 0
    assert capsys.readouterr().out == ""


# ---------------- AC-099.11 report ----------------

def dataset():
    g_ok, g_bad = {"acceptance": "passed", "security": "passed"}, {"acceptance": "passed", "security": "failed"}
    ship = lambda rid, day, outcome="done", usage=None, **kw: rec(rid, f"2026-10-{day}T10:00:00Z", outcome=outcome, gates=kw.pop("gates", g_ok),
                                                                 **({"usage": usage} if usage else {}), **kw)
    return [
        ship("d1", 20, usage=section(1000, 1.0)),
        ship("d2", 21, usage=section(3000, 3.0)),
        ship("d3", 22, usage=section(5000, 5.0, complete=False)),
        ship("gf", 22, usage=section(700, 0.7), gates=g_bad),                       # done, but the security gate failed
        ship("f1", 22, outcome="failed", usage=section(100, 0.1), gates={"acceptance": "failed", "security": "not run"}),
        ship("e1", 22, outcome="escalated", usage=section(200, 0.2)),
        ship("e2", 23, outcome="escalated", usage=section(400, 0.4)),
        ship("a1", 23, outcome="abandoned", usage=section(50, 0.05)),
        ship("n1", 23),                                                              # no usage data
        rec("b1", "2026-10-22T10:00:00Z", kind="benchmark", usage=section(9_000_000, 99.0), benchmark={"workflow": "ship"}),
        rec("b2", "2026-10-22T11:00:00Z", usage=section(9_000_000, 99.0), benchmark_of="b1"),
        rec("b3", "2026-10-22T12:00:00Z", kind="build", outcome="failed", benchmark_of="b1"),
    ]


@pytest.fixture()
def filled(store):
    for r in dataset():
        put(store, r)
    return store


def test_the_report_shows_delivered_runs_next_to_the_ones_that_did_not_deliver(filled, capsys):
    """AC-099.11: per kind: delivered with total and median, then failed / escalated / abandoned / gate-failed, and runs without usage."""
    agg = report_json(capsys)
    ship = agg["usage"]["kinds"]["ship"]
    assert ship["delivered"] == {"runs": 3, "tokens": 9000, "tokens_median": 3000, "cost_usd": pytest.approx(9.0),
                                 "cost_usd_median": pytest.approx(3.0), "cost_incomplete": 1}
    assert ship["gate_failed"]["runs"] == 1 and ship["gate_failed"]["tokens"] == 700
    assert (ship["failed"]["runs"], ship["failed"]["tokens"]) == (1, 100)
    assert (ship["escalated"]["runs"], ship["escalated"]["tokens"], ship["escalated"]["tokens_median"]) == (2, 600, 300)
    assert (ship["abandoned"]["runs"], ship["abandoned"]["tokens"]) == (1, 50)
    assert ship["no_usage"] == 1
    assert agg["usage"]["price_tables"] == [TABLE]


def test_benchmark_runs_are_left_out_and_empty_groups_have_no_median(filled, capsys):
    """AC-099.11: kind benchmark and benchmark_of records count nowhere; an empty group has null medians; old keys remain."""
    agg = report_json(capsys)
    assert "benchmark" not in agg["usage"]["kinds"]
    assert "build" not in agg["usage"]["kinds"] or agg["usage"]["kinds"]["build"]["failed"]["runs"] == 0
    assert agg["usage"]["kinds"]["ship"]["delivered"]["tokens"] < 1_000_000
    assert "window" in agg and "runs" in agg
    empty = [g for g in agg["usage"]["kinds"]["ship"].values() if isinstance(g, dict) and g.get("runs") == 0]
    assert all(g["tokens_median"] is None for g in empty)


def test_the_text_report_labels_the_numbers_as_an_estimate(filled, capsys):
    """AC-099.11 / AC-099.7: the printed cost is an estimate, names the price table date and says output is a lower bound."""
    assert runs.main(["report"]) == 0
    out = capsys.readouterr().out
    assert "estimate" in out and TABLE in out and "lower bound" in out and "delivered" in out


def test_records_without_usage_are_still_valid_in_the_report(store, capsys):
    """AC-099.11: a window of records without any usage section reports them all as no_usage."""
    put(store, rec("o1", "2026-10-20T10:00:00Z"))
    agg = report_json(capsys)
    assert agg["usage"]["kinds"]["ship"]["no_usage"] == 1
    assert agg["usage"]["kinds"]["ship"]["delivered"]["runs"] == 0
