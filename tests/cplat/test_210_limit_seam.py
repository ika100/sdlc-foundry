"""Spec 210 acceptance test: `cplat headless` records the limit a unit hit, and the next cycle holds (AC-210.8).

The seam is the one of spec 184 (`test_184_pause`): a units world whose fake `claude` answers one session with the usage-limit
message, and a fake clock for the pause. The file `usage/limit.json` is read where the run left it; then the dispatcher world takes
that file and runs a cycle. Kept in its own file because it reuses the autouse fixture of `test_184_pause`.
"""
import datetime as dt
import json
import os
from pathlib import Path

import dispatch_world
from support_210 import fresh, issues, plan_mode, usage_dir
from test_184_pause import NOW, T, lw, limit_message, one_task_per_unit, unix  # noqa: F401  (fixtures, helpers)
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)


def test_a_unit_that_hits_the_limit_leaves_limit_json_and_the_next_cycle_holds_starts_ac_210_8(lw, T, tmp_path, monkeypatch):  # AC-210.8
    reset = NOW + dt.timedelta(hours=4)
    lw.set({"task:t2": [limit_message(reset)]})
    state_file = Path(os.environ["XDG_STATE_HOME"]) / "sdlc-foundry" / "usage" / "limit.json"
    assert not state_file.exists()
    assert lw.w.run() == 0
    assert state_file.is_file(), "headless recorded no usage limit"
    recorded = json.loads(state_file.read_text())
    assert recorded["until"] == unix(reset) and recorded["reset_known"] is True
    assert "usage limit reached" in recorded["message"]

    sub = tmp_path / "dispatch"
    sub.mkdir()
    world = dispatch_world.World(sub, monkeypatch)                 # the dispatcher's world, at 2026-11-10 12:00: before the reset
    try:
        plan_mode(world, slots=2)
        issues(world, 2)
        world.behave(mode="wait")
        usage_dir(world).mkdir(parents=True, exist_ok=True)
        (usage_dir(world) / "limit.json").write_text(json.dumps(recorded))
        fresh(world, five=5, week=5)
        r = world.run("start", "--once")
        assert r.rc == 0 and "no starts: usage limit until" in r.out, r
        assert world.calls() == [] and world.claude_calls() == []
        assert world.plan()["plan"]["source"] == "limit"
    finally:
        world.close()
