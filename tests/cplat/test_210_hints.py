"""Spec 210 acceptance tests: choosing the mode (AC-210.10).

Contract: design.md "Hints" and "`plan --json` and `status --json`" (`hints`, one line per hint after the plan or cost line). The readings
are fixture files in `$XDG_STATE_HOME/sdlc-foundry/usage/`; `ANTHROPIC_API_KEY` is set or removed with monkeypatch.
"""
import pytest

from dispatch_world import world  # noqa: F401  (fixture)
from support_210 import API_HINT, D, H, PRIOR_HINT, fresh, put_readings, reading, window


@pytest.fixture(autouse=True)
def no_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def _out(world, verb):
    r = world.run(verb)
    assert r.rc == 0, r
    return r.out.splitlines()


@pytest.mark.parametrize("verb", ["plan", "status"])
def test_readings_found_in_mode_cost_print_the_subscription_hint_ac_210_10(world, verb):  # AC-210.10
    world.policy(budget={"usd_per_day": 5})
    fresh(world, five=10, week=30)
    assert PRIOR_HINT in _out(world, verb)
    assert world.run(verb, "--json").json()["hints"] == [PRIOR_HINT]


def test_a_reading_of_the_last_7_days_counts_even_when_old_ac_210_10(world):  # AC-210.10
    world.policy(budget={"usd_per_day": 5})
    old = world.now - 6 * D
    put_readings(world, five=window(reading(old, 10, old + 5 * H)), seven=window(reading(old, 10, old + 7 * D)))
    assert world.run("plan", "--json").json()["hints"] == [PRIOR_HINT]


def test_a_reading_older_than_7_days_gives_no_hint_ac_210_10(world):  # AC-210.10
    world.policy(budget={"usd_per_day": 5})
    old = world.now - 9 * D
    put_readings(world, five=window(reading(old, 10, old + 5 * H)), seven=window(reading(old, 10, old + 7 * D)))
    assert world.run("plan", "--json").json()["hints"] == []


def test_without_a_policy_file_the_mode_is_cost_and_the_hint_is_still_printed_ac_210_10(world):  # AC-210.10
    fresh(world, five=10, week=30)
    doc = world.plan()
    assert doc["policy"]["values"]["budget"]["mode"] == "cost" and doc["plan"] is None
    assert PRIOR_HINT in world.run("status").out


def test_no_readings_and_no_key_in_mode_cost_print_no_hint_ac_210_10(world):  # AC-210.10
    world.policy(budget={"usd_per_day": 5})
    for verb in ("plan", "status"):
        assert world.run(verb, "--json").json()["hints"] == []
        assert not [ln for ln in _out(world, verb) if ln.startswith("hint:")]


@pytest.mark.parametrize("verb", ["plan", "status"])
def test_an_api_key_and_no_readings_in_mode_plan_print_the_api_hint_ac_210_10(world, monkeypatch, verb):  # AC-210.10
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    world.policy(budget={"mode": "plan"})
    assert API_HINT in _out(world, verb)
    assert world.run(verb, "--json").json()["hints"] == [API_HINT]


def test_the_api_hint_needs_a_non_empty_key_and_no_reading_ac_210_10(world, monkeypatch):  # AC-210.10
    world.policy(budget={"mode": "plan"})
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    assert world.run("plan", "--json").json()["hints"] == []
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    fresh(world, five=10, week=30)
    assert world.run("plan", "--json").json()["hints"] == []


def test_the_mode_never_changes_and_the_policy_file_is_never_written_ac_210_10(world, monkeypatch):  # AC-210.10
    world.policy(budget={"usd_per_day": 5})
    path = world.repo / ".platform" / "dispatch.yml"
    before, mtime = path.read_text(), path.stat().st_mtime_ns
    fresh(world, five=10, week=30)
    for verb in ("plan", "status"):
        assert world.run(verb, "--json").json()["plan"] is None
        assert world.plan()["policy"]["values"]["budget"]["mode"] == "cost"
    assert path.read_text() == before and path.stat().st_mtime_ns == mtime
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    world.policy(budget={"mode": "plan"})
    path = world.repo / ".platform" / "dispatch.yml"
    before, mtime = path.read_text(), path.stat().st_mtime_ns
    (world.state_home / "sdlc-foundry" / "usage" / "readings.json").unlink()
    for verb in ("plan", "status"):
        assert world.run(verb, "--json").json()["plan"] is not None
        assert world.plan()["policy"]["values"]["budget"]["mode"] == "plan"
    assert path.read_text() == before and path.stat().st_mtime_ns == mtime
