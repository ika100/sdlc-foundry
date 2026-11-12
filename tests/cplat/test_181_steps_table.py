"""Spec 181 AC-181.5: one row per step with wall, person, agents (coordinator, children) and waiting per kind; --json too."""
import subprocess
import sys
from pathlib import Path

from journey181_support import KINDS, Transcript, split_of, world  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parents[2]
LABELS = ["step", "wall", "person", "agents", "coord", "child", "CI", "deploy", "promo", "restore", "cluster", "smoke", "unattr",
          "no-tr"]


def coordinator(world):
    return world.coordinator(Transcript().model(0).bash(10, 40, "cplat pr wait 3").model(60))


def steps_file(tmp_path):
    f = tmp_path / "steps.tsv"
    f.write_text("2026-11-10T08:00:00Z\tOne spec for the whole system\n2026-11-10T08:30:00Z\tPlan and ship it to dev\n")
    return f


def test_the_text_table_has_one_row_per_step_and_a_total_ac_181_5(world, capsys, tmp_path):  # AC-181.5
    code, out, _ = world.measure_text(capsys, coordinator(world), "--steps", str(steps_file(tmp_path)))
    assert code == 0
    lines = out.splitlines()
    header = next(x for x in lines if x.startswith("step"))
    positions = [header.index(label) for label in LABELS]
    assert positions == sorted(positions)
    rows = lines[lines.index(header) + 1:]
    assert rows[0].startswith("One spec for the whole system") and rows[1].startswith("Plan and ship it to dev")
    assert rows[2].startswith("total")


def test_json_gives_the_same_numbers_per_step_ac_181_5(world, capsys, tmp_path):  # AC-181.5
    code, out, _ = world.measure(capsys, coordinator(world), "--steps", str(steps_file(tmp_path)))
    assert code == 0
    assert [s["step"] for s in out["steps"]] == ["One spec for the whole system", "Plan and ship it to dev"]
    for s in out["steps"]:
        split_of(s)
        assert set(s["waiting"]) == set(KINDS) and "started_at" in s and "ended_at" in s
    assert out["steps"][0]["waiting"]["ci"] == 20 and out["steps"][1]["waiting"]["ci"] == 10
    assert split_of(out["steps_total"])["wall_min"] == 60


def test_without_steps_there_are_no_step_rows_ac_181_5(world, capsys):  # AC-181.5
    code, out, _ = world.measure(capsys, coordinator(world))
    assert code == 0 and "steps" not in out and "steps_total" not in out
    assert split_of(out["wall"])["waiting"]["ci"] == 30


def test_the_old_script_forwards_with_the_same_output_ac_181_5(world, capsys, tmp_path):  # AC-181.5
    session = coordinator(world)
    world.records_file.write_text("")
    args = [session, "2026-11-10T08:00:00Z", "2026-11-10T09:00:00Z", "ika100-demo/shop-api", "--records", str(world.records_file),
            "--json"]
    done = subprocess.run([sys.executable, str(ROOT / "scripts" / "journey" / "measure.py"), *args], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    import json
    assert split_of(json.loads(done.stdout)["wall"])["waiting"]["ci"] == 30
