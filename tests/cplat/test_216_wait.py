"""Spec 216 acceptance tests: `cplat system ship wait` (AC-216.6, with the wait side of AC-216.4, AC-216.5 and AC-216.11).

Seams as in the driver tests (`support216.Sim`: the driver's spawn / alive / run_step) and the scripted clock of spec 143 (`waits.now` /
`waits.sleep`; each sleep applies the next scripted change). A run's driver is recorded in the system ship state (`driver`) and its
progress is `<git dir>/cplat-app-ship-driver.json` (design.md "The progress file"); a test writes both and moves the progress file
during the call.
"""
import datetime as dt
import json
import os
import re

import pytest

from support216 import (API_LIB, API_ONLY, CPLAT, ENTRY_PLAN, GITOPS, LOG, SPEC, Sim, app, dw, finish_repo, progress,  # noqa: F401
                        sessions, tick)  # noqa: F401  (fixtures)

T = 60
STEP_LINE = re.compile(r"^\d\d:\d\d:\d\d driver: cplat system ship (.+) -> exit (\d+)$")
RESULTS = ("DONE:", "ENTRY:", "WAIT:", "ESCALATED:", "STOPPED:", "ENDED:", "TIMEOUT:")


def now():
    return dt.datetime.now().isoformat(timespec="seconds")


def put_driver(dw, sim, steps=(), end=None, alive=True, starts=1, phase=None):
    """A recorded driver (this process counts as its pid) and the progress it wrote."""
    st = dw.started(API_LIB, phase=phase or "repos")
    rec = {"pid": os.getpid(), "log": LOG, "started": now(), "run_id": st["run_id"], "starts": starts}
    dw.edit(lambda s: s.update(driver=rec))
    (sim.live.add if alive else sim.live.discard)(os.getpid())
    write_progress(dw, st["run_id"], steps, end)
    return st


def write_progress(dw, run_id, steps=(), end=None):
    body = {"spec": SPEC, "run_id": run_id, "pid": os.getpid(), "log": LOG, "started": now(),
            "steps": [{"at": now(), "argv": list(a), "code": 0, "line": "", "ended": now()} for a in steps], "end": end}
    (dw.common / "cplat-app-ship-driver.json").write_text(json.dumps(body))


def add_step(dw, argv, code=0):
    p = progress(dw)
    p["steps"].append({"at": now(), "argv": list(argv), "code": code, "line": "", "ended": now()})
    (dw.common / "cplat-app-ship-driver.json").write_text(json.dumps(p))


def wait(dw, *args):
    return app(dw, "wait", *args)


def result_lines(r):
    return [ln for ln in r.out.splitlines() if ln.startswith(RESULTS)]


# ---------------- AC-216.6: the single result ----------------

def test_a_run_without_a_driver_exits_1_at_once_and_names_drive_ac_216_6(dw, tick, monkeypatch):  # AC-216.6
    Sim(dw, monkeypatch)
    dw.started(API_LIB, phase="repos")
    r = wait(dw)
    lines = [ln for ln in r.out.splitlines() if ln.strip()]
    assert r.rc == 1 and tick.slept == 0 and len(lines) == 1 and f"{CPLAT} drive" in r.out
    assert "driver" in lines[0]


def test_a_finished_run_prints_done_with_the_report_word_for_word_and_the_archive_ac_216_6(dw, tick, monkeypatch):  # AC-216.6
    sim = Sim(dw, monkeypatch)
    st = put_driver(dw, sim, end=None, alive=False)
    report = ["## Shipped: 012-shop — Shop", "", "| Repo | Repo spec |", "| shop-api | 002-api |", "- [ ] Set the queue URL"]
    write_progress(dw, st["run_id"], end={"kind": "done", "report": report, "archive": "/archive/cplat-app-ship-012-shop.json", "at": now()})
    dw.state_file.unlink()                                             # `finish` archived the state: only the progress file is left
    r = wait(dw)
    out = r.out.splitlines()
    assert r.rc == 0 and out[0].startswith("DONE:") and len(result_lines(r)) == 1
    i = out.index(report[0])
    assert out[i:i + len(report)] == report                            # the report as `complete` printed it, line for line
    assert "/archive/cplat-app-ship-012-shop.json" in "\n".join(out[i + len(report):])


def test_an_entry_end_exits_0_with_the_id_and_the_worktree_ac_216_5(dw, tick, monkeypatch):  # AC-216.5
    sim = Sim(dw, monkeypatch)
    st = put_driver(dw, sim, alive=False)
    write_progress(dw, st["run_id"], end={"kind": "entry", "id": GITOPS, "worktree": "/w/entry", "at": now()})
    r = wait(dw)
    assert r.rc == 0 and f"ENTRY: {GITOPS} in /w/entry" in r.out.splitlines() and len(result_lines(r)) == 1
    assert tick.slept == 0                                             # no waiting for the deadline


def test_a_stop_rule_is_reported_as_stopped_before_an_escalation_ac_216_4(dw, tick, monkeypatch):  # AC-216.4
    sim = Sim(dw, monkeypatch)
    st = put_driver(dw, sim, alive=False)
    line = "/w/shop-api has uncommitted changes; commit or stash them, then resume"
    write_progress(dw, st["run_id"], end={"kind": "stopped", "line": line, "at": now()})
    r = wait(dw)
    assert r.rc == 1 and f"STOPPED: {line}" in r.out.splitlines() and len(result_lines(r)) == 1
    app(dw, "escalate", "something else", "--cause", "code")           # an escalated run: the stop still comes first
    r = wait(dw)
    assert r.rc == 1 and result_lines(r) == [f"STOPPED: {line}"]


def test_an_escalated_run_prints_the_reason_cause_questions_table_log_and_resume_ac_216_6(dw, tick, monkeypatch):  # AC-216.6
    sim = Sim(dw, monkeypatch)
    put_driver(dw, sim, alive=False)
    questions = [{"text": "Which store holds the alerts?", "suggested": "redis"}, {"text": "How long do they live?", "suggested": None}]
    dw.edit(lambda s: s["repos"]["shop-api"].update(state="escalated", reason="the plan needs a store", cause="decision", questions=questions))
    app(dw, "escalate", "the plan needs a store")
    r = wait(dw)
    out = r.out.splitlines()
    assert r.rc == 1 and out[0].startswith("ESCALATED:") and len(result_lines(r)) == 1
    assert "the plan needs a store" in out[0] and "decision" in out[0]
    assert any("Which store holds the alerts?" in ln and "redis" in ln for ln in out)
    assert any("How long do they live?" in ln and "no suggestion" in ln for ln in out)
    assert any("shop-api" in ln and "escalated" in ln for ln in out[1:])     # the repo table
    assert f"log: {LOG}" in out
    assert out[-1] == "resume it with" + f" /system:ship {SPEC}"


def test_a_step_during_the_call_prints_one_line_and_ends_with_wait_and_exit_0_ac_216_6(dw, tick, monkeypatch):  # AC-216.6
    sim = Sim(dw, monkeypatch)
    put_driver(dw, sim, steps=[("next",)])
    tick.script = [lambda: None, lambda: add_step(dw, ["next", "--wait", "--json"], 0), lambda: add_step(dw, ["repo", "start", "shop-lib"], 0)]
    r = wait(dw, "--timeout", str(T))
    out = r.out.splitlines()
    assert r.rc == 0 and out[-1] == f"WAIT: driver still going, progress in the last {T}s; run the same wait again"
    assert len(result_lines(r)) == 1 and T <= tick.slept <= T + 10
    steps = [m.groups() for m in map(STEP_LINE.match, out) if m]
    assert steps == [("next --wait", "0"), ("repo start shop-lib", "0")]          # new steps only, words up to the first option


def test_the_escalate_step_line_leaves_its_reason_out_ac_216_6(dw, tick, monkeypatch):  # AC-216.6
    sim = Sim(dw, monkeypatch)
    put_driver(dw, sim)
    tick.script = [lambda: add_step(dw, ["escalate", "a long secret reason with words", "--cause", "environment"], 0)]
    r = wait(dw, "--timeout", "20")
    assert any(m and m.group(1).strip() == "escalate" for m in map(STEP_LINE.match, r.out.splitlines()))
    assert "secret reason" not in r.out.split("WAIT:")[0]


def test_a_change_of_the_run_state_is_progress_ac_216_6(dw, tick, monkeypatch):  # AC-216.6
    sim = Sim(dw, monkeypatch)
    put_driver(dw, sim)
    tick.script = [lambda: None, lambda: dw.edit(lambda s: s["repos"]["shop-api"].update(state="running"))]
    r = wait(dw, "--timeout", str(T))
    assert r.rc == 0 and result_lines(r) == [f"WAIT: driver still going, progress in the last {T}s; run the same wait again"]


def test_nothing_new_during_the_call_is_a_timeout_with_exit_2_ac_216_6(dw, tick, monkeypatch):  # AC-216.6
    sim = Sim(dw, monkeypatch)
    put_driver(dw, sim, steps=[("next",)], phase="repos")
    r = wait(dw, "--timeout", str(T))
    (line,) = result_lines(r)
    assert r.rc == 2 and line.startswith("TIMEOUT:") and "repos" in line and LOG in line and re.search(r"\d+ ?(s|min)", line)
    assert T <= tick.slept <= T + 10


def test_a_step_that_ended_before_the_call_is_not_news_ac_216_6(dw, tick, monkeypatch):  # AC-216.6
    sim = Sim(dw, monkeypatch)
    put_driver(dw, sim, steps=[("next",), ("repo", "start", "shop-api")])
    r = wait(dw, "--timeout", "30")
    assert r.rc == 2 and not [ln for ln in r.out.splitlines() if STEP_LINE.match(ln)]


def test_the_default_timeout_is_540_seconds_ac_216_6(dw, tick, monkeypatch):  # AC-216.6
    sim = Sim(dw, monkeypatch)
    put_driver(dw, sim)
    r = wait(dw)
    assert r.rc == 2 and 540 <= tick.slept <= 550


def test_a_driver_that_ended_early_is_reported_as_ended_with_the_phase_and_log_ac_216_6(dw, tick, monkeypatch):  # AC-216.6
    sim = Sim(dw, monkeypatch)
    put_driver(dw, sim, steps=[("next",)], alive=False)
    r = wait(dw)
    assert r.rc == 1 and result_lines(r) == [f"ENDED: driver ended in phase repos; log {LOG}"] and tick.slept == 0
    assert not dw.state().get("escalated")


# ---------------- AC-216.11: a driver killed mid-run ----------------

def test_a_killed_driver_is_started_again_and_a_second_end_escalates_ac_216_11(dw, tick, monkeypatch):  # AC-216.11, AC-216.6
    from support216 import Killed
    sim = Sim(dw, monkeypatch)
    dw.started(API_ONLY, phase="repos")
    assert app(dw, "drive").rc == 0 and [s[2] for s in sim.spawned] == [1]
    sim.kill_at = 3                                                    # next, repo start, then the process dies in the third step
    with pytest.raises(Killed):
        sim.run()
    sim.live.clear()
    r = wait(dw, "--timeout", "30")
    assert r.rc == 1 and result_lines(r) == [f"ENDED: driver ended in phase repos; log {LOG}"]
    assert not dw.state().get("escalated")
    assert app(dw, "drive").rc == 0                                     # `drive` starts the driver again from the state
    assert [s[2] for s in sim.spawned] == [1, 2] and dw.state()["driver"]["starts"] == 2
    sim.kill_at = len(sim.steps) + 2
    with pytest.raises(Killed):
        sim.run()
    sim.live.clear()
    r = wait(dw, "--timeout", "30")
    out = r.out.splitlines()
    st = dw.state()
    assert r.rc == 1 and out[0].startswith("ESCALATED:") and LOG in r.out
    assert st["escalated"] and st["cause"] == "environment" and LOG in st["escalated"]
    assert app(dw, "drive").rc == 1                                     # an escalated run is not driven again
    assert len(sim.spawned) == 2


def test_drive_after_a_second_early_end_escalates_instead_of_starting_a_third_ac_216_6(dw, tick, monkeypatch):  # AC-216.6
    sim = Sim(dw, monkeypatch)
    put_driver(dw, sim, steps=[("next",)], alive=False, starts=2)
    r = app(dw, "drive")
    assert r.rc == 1 and r.out.startswith("ESCALATED:") and sim.spawned == []
    st = dw.state()
    assert st["escalated"] and st["cause"] == "environment" and LOG in st["escalated"]


# ---------------- the whole run through `wait` ----------------

def test_a_run_driven_to_the_end_is_reported_done_by_the_wait_ac_216_11(dw, tick, monkeypatch):  # AC-216.11, AC-216.6
    from test_appship_097 import all_passed
    sim = Sim(dw, monkeypatch)
    all_passed(dw)
    assert app(dw, "drive").rc == 0
    assert sim.run() == 0
    sim.live.clear()
    r = wait(dw)
    out = r.out.splitlines()
    assert r.rc == 0 and out[0].startswith("DONE:") and "## Shipped: 012-shop — Shop" in out
    assert any(ln.endswith(".json") for ln in out)                      # the archive path


def test_the_entry_scenario_ends_with_entry_for_the_session_ac_216_11(dw, tick, monkeypatch):  # AC-216.11, AC-216.5
    sim = Sim(dw, monkeypatch)
    dw.started(ENTRY_PLAN, phase="repos")
    assert app(dw, "drive").rc == 0
    sim.run()
    sim.live.clear()
    r = wait(dw)
    import appship_sched
    worktree = appship_sched.entry_path(dw.gitops, SPEC)                # the entry's worktree as the scheduler names it
    assert r.rc == 0 and result_lines(r) == [f"ENTRY: {GITOPS} in {worktree}"]
