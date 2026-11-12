"""Spec 181 AC-181.2: every minute of the wall clock is counted once, in the order person, agents, waiting."""
import pytest

from journey181_support import Transcript, split_of, world  # noqa: F401  (fixture)


def scenario(world):
    """08:00-09:00. Work 0-10, a typed answer after 10 (person 10-20, a subagent works 12-18 meanwhile), work 20-30,
    `pr wait` 30-40, work 40-45, a wait without a kind 45-60."""
    coord = (Transcript().model(0).model(10).prompt(20).model(20).bash(30, 40, "cplat pr wait 12").model(40)
             .bash(45, 60, "gh run watch 99"))
    sub = Transcript().bash(12, 18, "pytest -q")
    return world.coordinator(coord, subagent=sub)


def test_person_agents_and_waiting_add_up_to_the_wall_clock_ac_181_2(world, capsys):  # AC-181.2
    code, out, _ = world.measure(capsys, scenario(world))
    assert code == 0
    w = split_of(out["wall"])
    assert w["wall_min"] == 60
    assert abs(w["person_min"] - 10) <= 0.1                      # the subagent's work in the person interval counts once, as a person's
    assert abs(w["agents_min"] - 25) <= 0.1
    assert abs(w["waiting"]["ci"] - 10) <= 0.1 and abs(w["waiting"]["unattributed"] - 15) <= 0.1


def test_the_sum_holds_in_each_step_and_the_steps_add_up_ac_181_2(world, capsys, tmp_path):  # AC-181.2
    steps = tmp_path / "steps.tsv"
    steps.write_text("2026-11-10T08:00:00Z\tfirst\n2026-11-10T08:30:00Z\tsecond\n")
    code, out, _ = world.measure(capsys, scenario(world), "--steps", str(steps))
    assert code == 0
    first, second = (split_of(s) for s in out["steps"])
    assert (first["wall_min"], second["wall_min"]) == (30, 30)
    assert abs(first["person_min"] - 10) <= 0.1 and abs(first["agents_min"] - 20) <= 0.1 and first["waiting_min"] <= 0.1
    assert abs(second["agents_min"] - 5) <= 0.1 and abs(second["waiting"]["ci"] - 10) <= 0.1
    total = split_of(out["steps_total"])
    for key in ("person_min", "agents_min", "waiting_min", "wall_min"):
        assert total[key] == pytest.approx(first[key] + second[key], abs=0.1)
