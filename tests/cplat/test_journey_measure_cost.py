"""journey measure: per actor sessions, calls, first-call context and estimated cost, and merged PRs per step."""
import json

import pytest

import usage_cost
from journey181_support import Transcript, at, system_ship, world  # noqa: F401  (fixture)
from test_865_measure_repo_sessions import coordinator

SONNET = "claude-sonnet-5-5"


def usage(read, write=0, hour=0, out=0):
    return {"input_tokens": 0, "cache_creation_input_tokens": write, "cache_read_input_tokens": read, "output_tokens": out,
            "cache_creation": {"ephemeral_1h_input_tokens": hour, "ephemeral_5m_input_tokens": write - hour}}


def priced(t, minute, msg_id, **kw):
    t.model(minute, usage(**kw), msg_id)
    t.events[-1]["message"]["model"] = SONNET
    return t


def test_each_actor_reports_sessions_calls_first_call_context_and_cost(world, capsys):
    child = priced(priced(Transcript(), 15, "r1", read=20_000, write=10_000, hour=10_000), 20, "r2", read=30_000, out=500)
    sub = priced(Transcript(), 25, "s1", read=40_000, write=4_000)
    world.child("child1", child, subagent=sub)
    system_ship(world)
    code, out, _ = world.measure(capsys, world.coordinator(coordinator()))
    assert code == 0
    t = out["tokens"]
    repo, subs = t["actors"]["repo_sessions"], t["actors"]["repo_subagents"]
    assert (repo["sessions"], repo["calls"], repo["start_context_median"]) == (1, 2, 30_000)
    assert (subs["sessions"], subs["calls"], subs["start_context_median"]) == (1, 1, 44_000)
    p = usage_cost.load_prices().models[SONNET]
    assert repo["cost_usd"] == pytest.approx(round((10_000 * 2 * p["input"] + 50_000 * p["cache_read"] + 500 * p["output"]) / 1e6, 2))
    assert t["cache_write_1h"] == 10_000


def test_cost_prices_one_hour_cache_writes_at_twice_the_input_price():
    prices = usage_cost.load_prices()
    p = prices.models[SONNET]
    five = usage_cost.model_cost(prices, SONNET, 0, 0, 0, 1_000_000)
    hour = usage_cost.model_cost(prices, SONNET, 0, 0, 0, 1_000_000, cache_write_1h=1_000_000)
    assert five == pytest.approx(p["cache_write"]) and hour == pytest.approx(2 * p["input"])
    assert usage_cost.model_cost(prices, SONNET, 1, 2, 3, 4) == usage_cost.model_cost(prices, SONNET, 1, 2, 3, 4, 0)


def test_an_unpriced_model_leaves_the_cost_unknown(world, capsys):
    world.child("child1", Transcript().model(15, usage(read=1000), "m1"))   # no model name: no price
    system_ship(world)
    code, out, _ = world.measure(capsys, world.coordinator(coordinator()))
    assert code == 0 and out["tokens"]["cost_usd"] is None


def test_each_step_counts_the_prs_merged_in_it(world, capsys, tmp_path):
    merged = [{"mergedAt": at(m)} for m in (5, 10, 40)] + [{"mergedAt": at(500)}]   # the last one is outside the journey
    answers = tmp_path / "prs.json"
    answers.write_text(json.dumps(merged))
    gh = world.root / "bin" / "gh"
    gh.write_text(gh.read_text().replace('else echo "[]"', f'elif [ "$1 $2" = "pr list" ]; then cat "{answers}"; else echo "[]"'))
    system_ship(world)
    steps = tmp_path / "steps.tsv"
    steps.write_text(f"{at(0)}\tfirst\n{at(30)}\tsecond\n")
    code, out, _ = world.measure(capsys, world.coordinator(coordinator()), "--steps", str(steps), repos=["o/one"])
    assert code == 0
    assert [s["merged_prs"] for s in out["steps"]] == [2, 1] and out["github"]["merged_prs"] == 3


def test_the_text_output_names_cost_and_first_call_context(world, capsys):
    world.child("child1", priced(Transcript(), 15, "r1", read=3_000_000))
    system_ship(world)
    code, text, _ = world.measure_text(capsys, world.coordinator(coordinator()))
    assert code == 0
    assert "first-call context median" in text and "est. cost" in text
