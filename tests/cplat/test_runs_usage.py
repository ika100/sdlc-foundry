"""Spec 099: the `usage` section of the run record (counting, phases, roles, failed calls, costs, tolerance, privacy)."""
import json

import pytest

import runs
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)
from usage_support import (OPUS, SESSION, T0, assert_sums_equal_totals, call, iso, projects,  # noqa: F401
                           run_with_phases, write_session)

PHASES = [("build:tests", 10), ("build:implement", 100)]


def test_twelve_calls_are_summed_and_every_breakdown_adds_up(clock, store, projects):
    """AC-099.1: 12 calls over main and subagents: totals are the sums and by_phase / by_role / by_model each equal them."""
    main = [call(f"m{n}", 20 + n * 30, i=10 + n) for n in range(5)]
    coder = [call(f"c{n}", 30 + n * 40, o=7 + n) for n in range(4)]
    review = [call(f"r{n}", 120 + n * 10, model="claude-sonnet-4-5", cr=50) for n in range(3)]
    write_session(projects, SESSION, main, {"a1": ({"agentType": "svc:coder"}, coder), "a2": ({"agentType": "svc:reviewer"}, review)})
    rec = run_with_phases(clock, store, PHASES, 200)
    u = rec["usage"]
    assert u["totals"]["calls"] == 12 and u["totals"]["failed_calls"] == 0
    every = main + coder + review
    for field, key in (("input", "input_tokens"), ("output", "output_tokens"), ("cache_read", "cache_read_input_tokens"),
                       ("cache_write", "cache_creation_input_tokens")):
        assert u["totals"][field] == sum(x["message"]["usage"][key] for x in every)
    assert u["sessions"] == [SESSION]
    assert_sums_equal_totals(u)


def test_older_records_and_kinds_without_sessions_stay_valid(clock, store, monkeypatch):
    """AC-099.1: a run with no session to claim has no `usage` key at all."""
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    rec = run_with_phases(clock, store, [], 5, kind="pr-wait")
    assert "usage" not in rec


def test_one_streamed_message_in_three_entries_is_one_call(clock, store, projects):
    """AC-099.2: three entries with one message id are one call with the LAST entry's values, timed at the FIRST entry."""
    streamed = [call("msg_x", 50, o=1), call("msg_x", 60, o=5), call("msg_x", 130, o=9)]       # first in phase one, last in phase two
    write_session(projects, SESSION, streamed)
    u = run_with_phases(clock, store, PHASES, 200)["usage"]
    assert u["totals"]["calls"] == 1 and u["totals"]["output"] == 9
    assert list(u["by_phase"]) == ["build:tests"]


def test_a_call_counts_under_the_phase_that_was_open_at_its_timestamp(clock, store, projects):
    """AC-099.3: inside a phase (bounds inclusive) -> that phase; inside the run but outside every phase -> unphased."""
    main = [call("early", 5), call("edge", 10), call("t1", 60), call("i1", 100), call("i2", 150), call("late", 199)]
    write_session(projects, SESSION, main)
    u = run_with_phases(clock, store, PHASES, 200)["usage"]
    assert u["by_phase"]["unphased"]["calls"] == 1
    assert u["by_phase"]["build:tests"]["calls"] == 2                   # 10 (inclusive start) and 60
    assert u["by_phase"]["build:implement"]["calls"] == 3               # 100 (shared bound: the later phase wins), 150, 199
    assert u["totals"]["calls"] == 6
    assert_sums_equal_totals(u)


def test_calls_outside_the_run_window_are_not_counted(clock, store, projects):
    """AC-099.3: a call made before the run started or after it ended is not part of the run."""
    write_session(projects, SESSION, [call("before", -50), call("in", 50), call("after", 500)])
    u = run_with_phases(clock, store, PHASES, 200)["usage"]
    assert u["totals"]["calls"] == 1


def test_roles_main_agent_type_and_unknown(clock, store, projects):
    """AC-099.4: main calls -> `main`; a subagent -> its agent type; no agent type -> `unknown`; the description is not stored."""
    desc = "Refactor-the-private-billing-module-DESCRIPTION"
    write_session(projects, SESSION, [call("m1", 20)], {
        "a1": ({"agentType": "svc:coder", "description": desc}, [call("c1", 30), call("c2", 40)]),
        "a2": ({"description": desc}, [call("u1", 50)])})
    rec = run_with_phases(clock, store, PHASES, 200)
    roles = {k: v["calls"] for k, v in rec["usage"]["by_role"].items()}
    assert roles == {"main": 1, "svc:coder": 2, "unknown": 1}
    assert desc not in json.dumps(rec)


def test_a_failed_call_counts_but_is_not_a_model_and_costs_nothing(clock, store, projects):
    """AC-099.6: `<synthetic>` counts in calls and failed_calls with its tokens; no model bucket, no cost, cost stays complete."""
    main = [call("ok", 20), call("bad", 30, model="<synthetic>", i=0, o=0, cr=0, cw=0), call("bad2", 40, model="<synthetic>", i=3, o=0, cr=0, cw=0)]
    write_session(projects, SESSION, main)
    u = run_with_phases(clock, store, PHASES, 200)["usage"]
    t = u["totals"]
    assert (t["calls"], t["failed_calls"], t["input"]) == (3, 2, 13)
    assert "<synthetic>" not in u["by_model"]
    assert u["by_model"][OPUS]["calls"] == 1
    assert t["cost_complete"] is True and t["models_without_price"] == []
    assert isinstance(t["cost_usd"], (int, float))
    assert_sums_equal_totals(u)


def test_each_models_cost_comes_from_its_four_counts_and_prices(clock, store, projects):
    """AC-099.7: cost_usd of a model = (in*p_in + cache_write*p_cw + cache_read*p_cr + out*p_out) / 1e6."""
    import usage_cost
    p = usage_cost.load_prices().models[OPUS]
    write_session(projects, SESSION, [call("a", 20, i=1000, o=2000, cr=30000, cw=400), call("b", 30, i=1, o=2, cr=3, cw=4)])
    u = run_with_phases(clock, store, PHASES, 200)["usage"]
    expected = ((1001) * p["input"] + 404 * p["cache_write"] + 30003 * p["cache_read"] + 2002 * p["output"]) / 1e6
    assert u["by_model"][OPUS]["cost_usd"] == pytest.approx(expected, rel=1e-6)
    assert u["totals"]["cost_usd"] == pytest.approx(expected, rel=1e-6)
    assert u["price_table"] == usage_cost.load_prices().taken


def test_price_lookup_and_unpriced_models_are_unknown_never_zero():
    """AC-099.7: exact id, then the longest key the id starts with + '-'; no entry -> None (never 0)."""
    import usage_cost
    prices = usage_cost.load_prices()
    p = prices.models[OPUS]
    exact = usage_cost.model_cost(prices, OPUS, 1_000_000, 0, 0, 0)
    assert exact == pytest.approx(p["input"])
    assert usage_cost.model_cost(prices, OPUS + "-20251101", 1_000_000, 0, 0, 0) == pytest.approx(p["input"])
    assert usage_cost.model_cost(prices, "claude-mystery-9", 5, 5, 5, 5) is None
    assert prices.taken


def test_an_unpriced_model_makes_the_cost_incomplete(clock, store, projects):
    """AC-099.7: unknown for that model, known sum in the totals, cost_complete false, the model listed once."""
    write_session(projects, SESSION, [call("a", 20), call("b", 30, model="claude-mystery-9"), call("c", 40, model="claude-mystery-9")])
    u = run_with_phases(clock, store, PHASES, 200)["usage"]
    assert u["by_model"]["claude-mystery-9"]["cost_usd"] == "unknown"
    assert u["by_model"][OPUS]["cost_usd"] == pytest.approx(u["totals"]["cost_usd"])
    assert u["totals"]["cost_complete"] is False and u["totals"]["models_without_price"] == ["claude-mystery-9"]
    assert_sums_equal_totals(u)


def test_a_missing_transcript_changes_nothing_about_the_run(clock, store, projects, capsys):
    """AC-099.8: no transcript: outcome, exit code and output as without usage; the section says why it is incomplete."""
    rec = run_with_phases(clock, store, PHASES, 200)
    assert rec["outcome"] == "done"
    assert rec["usage"]["totals"]["calls"] == 0
    assert "transcript not found" in rec["usage"]["incomplete"]
    assert capsys.readouterr().err == ""                                              # no warning line either


def test_malformed_lines_are_counted_and_the_rest_is_used(clock, store, projects):
    """AC-099.8: 3 malformed lines -> '3 malformed lines'; the readable calls are counted; a half-written last line is not malformed."""
    write_session(projects, SESSION, [call("a", 20), call("b", 30)], raw_head="not json\n{broken\n", raw_tail='[1, 2]\n{"type": "assis')
    u = run_with_phases(clock, store, PHASES, 200)["usage"]
    assert u["totals"]["calls"] == 2
    assert u["incomplete"] == "3 malformed lines"


def test_an_error_while_collecting_never_changes_the_run(clock, store, projects, monkeypatch):
    """AC-099.8: a crash inside usage collection: the record is still written with outcome and exit unchanged."""
    import transcripts
    write_session(projects, SESSION, [call("a", 20)])

    def boom(*a, **k):
        raise RuntimeError("disk on fire")
    monkeypatch.setattr(transcripts, "read_session", boom)
    rec = run_with_phases(clock, store, PHASES, 200)
    assert rec["outcome"] == "done"
    assert "usage" not in rec or "error: RuntimeError" in (rec["usage"]["incomplete"] or "")


def test_collection_stops_at_its_time_budget(clock, store, projects):
    """AC-099.8: a spent budget stops reading and says so; the call never raises."""
    import runs_usage
    write_session(projects, SESSION, [call("a", 20)])
    clock.now = T0
    rid = runs.start("ship", repo="acme/shop-api")
    rec = runs.active(rid)
    u = runs_usage.for_run(rec, ended_at=iso(200), budget_s=-1.0)
    assert u is not None and "time budget of 10 s used up" in u["incomplete"]


def test_neither_the_record_nor_the_output_holds_prompts_code_or_secrets(clock, store, projects, capsys):
    """AC-099.9: prompt text, tool input/output, file contents and a secret never reach the record or `runs usage`."""
    secret, prompt, code = "GH_TOKEN=ghp_abc123abc123abc123abc123abc123", "PLEASE-REFACTOR-THE-PAYROLL-SECRETS", "def payroll(): return 4711"
    line = call("m1", 20, text=prompt)
    line["message"]["content"] += [{"type": "tool_use", "name": "Bash", "input": {"command": f"export {secret}"}},
                                   {"type": "tool_result", "content": code}]
    line["toolUseResult"] = {"stdout": secret, "file": {"content": code}}
    sneaky = call("m2", 30, model=secret, text=secret)                                  # a model name that is a secret
    write_session(projects, SESSION, [line, sneaky], {"a1": ({"agentType": secret, "description": prompt}, [call("c1", 40, text=code)])})
    rec = run_with_phases(clock, store, PHASES, 200)
    dump = json.dumps(rec) + json.dumps(stored(store))
    assert runs.main(["usage", rec["run_id"]]) == 0
    printed = capsys.readouterr().out
    assert runs.main(["usage", rec["run_id"], "--json"]) == 0
    printed += capsys.readouterr().out
    assert runs.main(["usage", "--session", SESSION]) == 0
    printed += capsys.readouterr().out
    for needle in (secret, "ghp_abc123", prompt, code, "payroll", "export "):
        assert needle not in dump and needle not in printed, needle
    assert rec["usage"]["totals"]["calls"] == 3
