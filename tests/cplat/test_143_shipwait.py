"""Spec 143 acceptance tests: `cplat component ship wait` and `cplat system ship next --wait` (design.md "Contract").

Seams: a clone's `<git dir>/cplat-ship.json`, written with `ship.save_state` and changed by the scripted clock (`waits.sleep`
applies the next state); the system ship world of spec 097 (`test_appship_097.World`) for `next --wait`.
"""
import json
import re

import pytest

import cplat
import runs
import ship
from test_appship_097 import GITOPS, World  # noqa: F401
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)
from test_ship import repo  # noqa: F401  (fixture)

SPEC = "007-price-alerts"
TIME = re.compile(r"^\d\d:\d\d:\d\d ")


def state(phase, **kw):
    return {"spec": SPEC, "phase": phase, "merge": True, "branch": f"feature/{SPEC}", "started": "2026-11-05T08:00:00",
            "recorded": True, "run_id": "20261105T080000Z-abcd", **kw}


class Clock:
    """`waits.now` / `waits.sleep`; each sleep applies the next scripted change (a callable) before time moves on."""

    def __init__(self, monkeypatch):
        self.t, self.slept, self.script = 5000.0, 0.0, []
        monkeypatch.setattr("waits.now", lambda: self.t)
        monkeypatch.setattr("waits.sleep", self.sleep)

    def sleep(self, s):
        self.t += s
        self.slept += s
        if self.script:
            self.script.pop(0)()


@pytest.fixture()
def tick(monkeypatch):
    return Clock(monkeypatch)


def ship_wait(capsys, repo, *args):
    capsys.readouterr()
    rc = cplat.main(["component", "ship", "wait", "--repo", str(repo), *args])
    cap = capsys.readouterr()
    return rc, cap.out.splitlines(), cap.err


def result(lines, first):
    i = next(i for i, ln in enumerate(lines) if ln.startswith(first))
    return lines[i:]


# ---------------- AC-143.8 ----------------

def test_a_line_per_phase_change_and_exit_0_at_the_phase_ac_143_8(repo, tick, capsys):  # AC-143.8
    ship.save_state(repo, state("build"))
    tick.script = [lambda: None, lambda: ship.save_state(repo, state("pr")), lambda: ship.save_state(repo, state("land"))]
    rc, out, _ = ship_wait(capsys, repo, "--phase", "land")
    assert rc == 0
    changes = [ln for ln in out if TIME.match(ln)]
    assert [ln.rsplit(" ", 1)[-1] for ln in changes] == ["build", "pr", "land"]
    assert result(out, "REACHED:")


def test_a_later_phase_counts_and_done_is_the_default_ac_143_8(repo, tick, capsys):  # AC-143.8
    ship.save_state(repo, state("build"))
    tick.script = [lambda: ship.save_state(repo, state("deploy"))]
    assert ship_wait(capsys, repo, "--phase", "pr")[0] == 0
    tick.script = [lambda: ship.save_state(repo, state("done"))]
    rc, out, _ = ship_wait(capsys, repo)
    assert rc == 0 and any(TIME.match(ln) and ln.endswith("done") for ln in out)


def test_a_run_finished_and_archived_meanwhile_counts_as_done_ac_143_8(repo, tick, capsys):  # AC-143.8
    ship.save_state(repo, state("deploy"))
    tick.script = [lambda: (ship.save_state(repo, state("done")), ship.finish(repo))]
    rc, out, _ = ship_wait(capsys, repo)
    assert rc == 0 and result(out, "REACHED:")


def test_an_escalated_run_exits_1_with_the_reason_and_cause_ac_143_8(repo, tick, capsys):  # AC-143.8
    ship.save_state(repo, state("land"))
    tick.script = [lambda: ship.save_state(repo, state("land", escalated="CI red after 2 rounds", cause="code"))]
    rc, out, _ = ship_wait(capsys, repo)
    first = result(out, "ESCALATED:")[0]
    assert rc == 1 and "CI red after 2 rounds" in first and "code" in first


def test_the_timeout_names_the_phase_and_how_long_the_run_is_in_it_ac_143_8(repo, tick, capsys):  # AC-143.8
    ship.save_state(repo, state("build"))
    rc, out, _ = ship_wait(capsys, repo, "--timeout", "120")
    first = result(out, "TIMEOUT:")[0]
    assert rc == 2 and "build" in first and re.search(r"\d+ ?(s|min)", first) and tick.slept >= 120


def test_the_default_timeout_is_540_seconds_ac_143_8(repo, tick, capsys):  # AC-143.8
    ship.save_state(repo, state("build"))
    rc, _, _ = ship_wait(capsys, repo)
    assert rc == 2 and 540 <= tick.slept < 560


def test_a_clone_without_a_ship_run_exits_at_once_ac_143_8(repo, tick, capsys):  # AC-143.8
    rc, out, err = ship_wait(capsys, repo)
    assert rc != 0 and tick.slept == 0 and "no ship run" in (err + "\n".join(out))


# ---------------- AC-143.9 ----------------

@pytest.fixture()
def sw(tmp_path, monkeypatch, capsys):
    world = World(tmp_path, monkeypatch, capsys)
    monkeypatch.setattr(ship, "argo_health", lambda *a, **k: "Synced/Healthy")
    return world


def running(sw, rid, phase):
    ship.save_state(sw.clone(rid), {"spec": "007-price-alerts", "phase": phase, "recorded": True, "run_id": f"r-{rid}"})


def next_wait(sw, *args):
    return sw.app("next", "--wait", *args)


def test_next_wait_blocks_until_the_action_changes_ac_143_9(sw, tick):  # AC-143.9
    sw.started(states={GITOPS: "passed", "shop-lib": "passed", "shop-api": "running", "shop-worker": "running"})
    running(sw, "shop-api", "build")
    running(sw, "shop-worker", "deploy")
    tick.script = [lambda: running(sw, "shop-api", "land"),
                   lambda: (sw.ship_state("shop-api"), sw.ship_state("shop-worker"))]
    r = next_wait(sw)
    assert r.rc == 0
    lines = r.out.splitlines()
    assert any(TIME.match(ln) and "shop-api" in ln and ln.endswith("land") for ln in lines)
    assert "action: start" in r.out and "start shop-web" in r.out
    assert sw.state()["repos"]["shop-api"]["state"] == "passed"


def test_next_wait_prints_json_like_next_ac_143_9(sw, tick):  # AC-143.9
    sw.started(states={GITOPS: "passed", "shop-lib": "passed", "shop-api": "running", "shop-worker": "passed"})
    running(sw, "shop-api", "deploy")
    tick.script = [lambda: sw.ship_state("shop-api")]
    sw.capsys.readouterr()
    import appship
    rc = appship.main(["--repo", str(sw.gitops), "next", "--wait", "--json"])
    out = sw.capsys.readouterr().out
    assert rc == 0 and json.loads(out)["action"] == "start"


def test_next_wait_returns_at_once_when_the_action_is_not_wait_ac_143_9(sw, tick):  # AC-143.9
    sw.started(states={GITOPS: "passed"})
    r = next_wait(sw)
    assert r.rc == 0 and "action: start" in r.out and tick.slept == 0


def test_next_wait_times_out_with_the_running_repos_and_phases_ac_143_9(sw, tick):  # AC-143.9
    sw.started(states={GITOPS: "passed", "shop-lib": "passed", "shop-api": "running", "shop-worker": "running"})
    running(sw, "shop-api", "build")
    running(sw, "shop-worker", "land")
    r = next_wait(sw, "--timeout", "60")
    first = next(ln for ln in r.out.splitlines() if ln.startswith("TIMEOUT:"))
    assert r.rc == 2 and "shop-api (build)" in first and "shop-worker (land)" in first


# ---------------- AC-143.10 ----------------

def test_the_ship_wait_counts_toward_the_run_it_runs_in_ac_143_10(repo, tick, capsys, monkeypatch, store):  # AC-143.10
    rid = runs.start("ship", repo="acme/shop-api", spec=SPEC)
    monkeypatch.setenv("CPLAT_RUN_PARENT", rid)
    ship.save_state(repo, state("build"))
    tick.script = [lambda: ship.save_state(repo, state("done"))]
    assert ship_wait(capsys, repo)[0] == 0
    rec = runs.active(rid)
    assert rec["waiting_s"] == pytest.approx(tick.slept) and rec["waits"][-1]["result"] == "reached"
    assert rec["waits"][-1]["wait"] == "component ship wait"


@pytest.mark.parametrize("change, result, outcome", [
    ("done", "reached", "done"), ("escalated", "escalated", "failed"), (None, "timeout", "failed")])
def test_outside_a_run_the_ship_wait_records_its_own_run_ac_143_10(repo, tick, capsys, store, change, result, outcome):  # AC-143.10
    ship.save_state(repo, state("build"))
    if change == "done":
        tick.script = [lambda: ship.save_state(repo, state("done"))]
    elif change:
        tick.script = [lambda: ship.save_state(repo, state("build", escalated="stuck", cause="environment"))]
    ship_wait(capsys, repo, "--timeout", "30")
    (r,) = [r for r in stored(store) if r["kind"] == "wait"]
    assert r["outcome"] == outcome and r["wait"]["result"] == result and r["wait"]["command"] == "component ship wait"


def test_next_wait_counts_toward_the_system_ship_run_ac_143_10(sw, tick):  # AC-143.10
    st = sw.started(states={GITOPS: "passed", "shop-lib": "passed", "shop-api": "running", "shop-worker": "passed"})
    running(sw, "shop-api", "deploy")
    tick.script = [lambda: sw.ship_state("shop-api")]
    assert next_wait(sw).rc == 0
    rec = runs.active(st["run_id"])
    assert rec["waiting_s"] > 0 and rec["waits"][-1]["wait"] == "system ship next --wait"  # interface: wait name recorded in the run
