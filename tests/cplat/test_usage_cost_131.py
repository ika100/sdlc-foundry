"""Spec 131 acceptance tests: the cost of a run tree includes every subagent, or is `unknown` (AC-131.17, #324).

The transcripts are fixture JSONL files under a fake projects root, with a `<session>/subagents/` directory for the coder,
tester and reviewer. A read that stopped early or could not read a file is incomplete and its cost is never shown as a number.
"""
import datetime as dt
import os

import pytest

import budget
import runs
import runs_usage
import usage_cost
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)
from units131_support import SPEC_ID
from usage_support import OPUS, SESSION, T0, call, iso, projects, write_session  # noqa: F401  (fixtures)


def headless_root(clock, tmp_path):
    clock.now = T0
    rid = runs.start("headless", repo="acme/shop-api", mode="headless")
    runs_usage.register(rid, mode="own", session=SESSION)
    budget.open_root(rid, f"acme/shop-api:{SPEC_ID}", ships=1)
    budget.count_invocation(rid)
    clock.now = T0 + dt.timedelta(seconds=200)
    return rid


def cost_shown(rid):
    return budget.used_of(budget.find(rid)[1])["cost"]


def calls_cost(lines):
    prices = usage_cost.load_prices()
    return sum(usage_cost.model_cost(prices, OPUS, x["message"]["usage"]["input_tokens"], x["message"]["usage"]["output_tokens"],
                                     x["message"]["usage"]["cache_read_input_tokens"],
                                     x["message"]["usage"]["cache_creation_input_tokens"]) for x in lines)


def agents():
    return {"a1": ({"agentType": "component:coder"}, [call(f"c{n}", 30 + n * 10, o=300) for n in range(3)]),
            "a2": ({"agentType": "component:tester"}, [call(f"t{n}", 60 + n * 10, o=200) for n in range(2)]),
            "a3": ({"agentType": "component:reviewer"}, [call(f"r{n}", 120 + n * 10, o=100) for n in range(2)])}


def test_the_cost_of_a_run_tree_includes_every_subagent(clock, tmp_path, projects):  # AC-131.17
    main = [call(f"m{n}", 20 + n * 30) for n in range(3)]
    subs = agents()
    write_session(projects, SESSION, main, subs)
    rid = headless_root(clock, tmp_path)
    every = main + [x for _, lines in subs.values() for x in lines]
    assert cost_shown(rid) == pytest.approx(calls_cost(every), abs=1e-4)
    assert cost_shown(rid) > calls_cost(main) * 2                    # not only the main transcript


def test_a_read_stopped_by_the_time_budget_is_unknown_never_the_partial_sum(clock, tmp_path, projects, monkeypatch):  # AC-131.17
    write_session(projects, SESSION, [call("m0", 20)], agents())
    rid = headless_root(clock, tmp_path)
    real = runs_usage.for_run
    monkeypatch.setattr(runs_usage, "for_run", lambda rec, **kw: real(rec, **{**kw, "budget_s": -1.0}))
    assert cost_shown(rid) == "unknown"
    sec = real(runs.active(rid), ended_at=iso(200), budget_s=-1.0, peek=True)
    assert sec["totals"]["cost_complete"] is False and "time budget" in sec["incomplete"]


def test_a_subagent_file_that_cannot_be_read_makes_the_cost_unknown(clock, tmp_path, projects):  # AC-131.17
    write_session(projects, SESSION, [call("m0", 20)], agents())
    (projects / "-proj" / SESSION / "subagents" / "agent-broken.jsonl").mkdir()      # a directory: cannot be read as a file
    rid = headless_root(clock, tmp_path)
    assert cost_shown(rid) == "unknown"
    sec = runs_usage.for_run(runs.active(rid), ended_at=iso(200), peek=True)
    assert sec["totals"]["cost_complete"] is False


def test_a_missing_transcript_is_unknown_not_zero(clock, tmp_path, projects):  # AC-131.17
    rid = headless_root(clock, tmp_path)                              # no transcript on this machine
    assert cost_shown(rid) == "unknown"
    sec = runs_usage.for_run(runs.active(rid), ended_at=iso(200), peek=True)
    assert sec["totals"]["cost_complete"] is False and "transcript not found" in sec["incomplete"]


def test_malformed_lines_alone_do_not_make_the_cost_incomplete(clock, tmp_path, projects):  # AC-131.17
    write_session(projects, SESSION, [call("m0", 20), call("m1", 50)], agents(), raw_head="not json\n")
    rid = headless_root(clock, tmp_path)
    sec = runs_usage.for_run(runs.active(rid), ended_at=iso(200), peek=True)
    assert sec["totals"]["cost_complete"] is True and isinstance(cost_shown(rid), float)


def test_a_file_that_has_not_changed_is_not_parsed_again(clock, tmp_path, projects):  # AC-131.17
    write_session(projects, SESSION, [call("m0", 20, i=10)])
    rid = headless_root(clock, tmp_path)
    main = projects / "-proj" / f"{SESSION}.jsonl"
    stat = main.stat()
    first = runs_usage.for_run(runs.active(rid), ended_at=iso(200), peek=True)["totals"]["input"]
    assert first == 10
    write_session(projects, SESSION, [call("m0", 20, i=11)])          # same size, other content
    os.utime(main, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert main.stat().st_size == stat.st_size
    assert runs_usage.for_run(runs.active(rid), ended_at=iso(200), peek=True)["totals"]["input"] == 10       # read from the cache
    os.utime(main, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
    assert runs_usage.for_run(runs.active(rid), ended_at=iso(200), peek=True)["totals"]["input"] == 11       # changed: parsed again


def test_a_cache_that_is_corrupt_is_parsed_again_never_an_error(clock, tmp_path, projects):  # AC-131.17
    write_session(projects, SESSION, [call("m0", 20, i=10)])
    rid = headless_root(clock, tmp_path)
    runs_usage.for_run(runs.active(rid), ended_at=iso(200), peek=True)
    cache = runs.state_dir() / "usage" / "cache"
    files = [f for f in cache.rglob("*") if f.is_file()]
    assert files
    for f in files:
        f.write_text("{corrupt")
    assert runs_usage.for_run(runs.active(rid), ended_at=iso(200), peek=True)["totals"]["input"] == 10
