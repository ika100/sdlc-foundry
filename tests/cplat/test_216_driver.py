"""Spec 216 acceptance tests: `cplat system ship drive` and the driver's own end rules (AC-216.1, AC-216.4, AC-216.5, AC-216.9,
AC-216.10; the `drive` side).

Seams: the system ship world of spec 097 (`World`: real git on a local bare origin, fake `gh`), the clock of spec 143, and the driver's
seams `appship_driver.spawn` / `alive` / `run_step` (`support216.Sim`). The driver runs in this process: its steps are `appship.main`
calls with captured output. A fake `claude` on PATH fails when called. The new modules are imported inside the tests.
"""
import json
import os
import subprocess

import pytest

import appship_proc
import runs
from support216 import (API_LIB, API_ONLY, API_WORKER, CPLAT, ENTRY_PLAN, LOG, SPEC, GITOPS, Sim, app, claude_trap, dw, finish_repo,  # noqa: F401
                        mod, progress, running_repo, sessions, tick)  # noqa: F401  (fixtures)


def lines(r):
    return [ln for ln in r.out.splitlines() if ln.strip()]


def driver_line(pid=None):
    return f"driver: pid {pid if pid is not None else os.getpid()}, log {LOG}"


# ---------------- AC-216.1: starting the driver ----------------

@pytest.mark.parametrize("phase", ["publish", "repos", "complete"])
def test_drive_starts_one_detached_driver_and_records_it_ac_216_1(dw, monkeypatch, phase):  # AC-216.1
    sim = Sim(dw, monkeypatch)
    st = dw.started(API_LIB, phase=phase)
    r = app(dw, "drive")
    assert r.rc == 0, r.out
    assert lines(r) == [driver_line(), f"next: {CPLAT} wait"]
    assert sim.spawned == [(str(dw.gitops), st["run_id"], 1)]
    rec = dw.state()["driver"]
    assert rec["pid"] == os.getpid() and rec["log"] == LOG and rec["run_id"] == st["run_id"] and rec["starts"] == 1
    assert dw.state()["phase"] == phase and not dw.state().get("escalated")           # drive changes nothing else


def test_a_live_driver_of_the_run_is_not_started_twice_ac_216_1(dw, monkeypatch):  # AC-216.1
    sim = Sim(dw, monkeypatch)
    dw.started(API_LIB, phase="repos")
    first = app(dw, "drive")
    second = app(dw, "drive")
    assert first.rc == second.rc == 0 and len(sim.spawned) == 1
    assert lines(second) == lines(first)                                              # the existing `driver:` line again


def test_two_drive_calls_at_once_start_one_process_ac_216_1(dw, monkeypatch):  # AC-216.1
    sim = Sim(dw, monkeypatch)
    dw.started(API_LIB, phase="repos")
    import threading
    results = []
    drive = mod("appship_driver").drive
    threads = [threading.Thread(target=lambda: results.append(drive(dw.gitops))) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(sim.spawned) == 1


def run_to_refusal(dw, monkeypatch, setup):
    sim = Sim(dw, monkeypatch)
    setup()
    r = app(dw, "drive")
    return sim, r


def test_without_a_run_drive_exits_1_with_one_line_and_starts_nothing_ac_216_1(dw, monkeypatch):  # AC-216.1
    sim, r = run_to_refusal(dw, monkeypatch, lambda: None)
    assert r.rc == 1 and sim.spawned == [] and len(lines(r)) == 1 and "/system:ship" in r.out


def test_in_phase_plan_drive_names_the_phase_and_the_step_ac_216_1(dw, monkeypatch):  # AC-216.1
    def setup():
        (dw.gitops / "docs" / "plan" / f"{SPEC}.md").unlink()
        assert dw.started()["phase"] == "plan"
    sim, r = run_to_refusal(dw, monkeypatch, setup)
    assert r.rc == 1 and sim.spawned == [] and len(lines(r)) == 1
    assert "phase plan" in r.out and f"{CPLAT} phase publish" in r.out


def test_an_escalated_run_is_not_driven_ac_216_1(dw, monkeypatch):  # AC-216.1
    def setup():
        dw.started(API_LIB, phase="repos")
        assert app(dw, "escalate", "stuck", "--cause", "environment").rc == 0
    sim, r = run_to_refusal(dw, monkeypatch, setup)
    assert r.rc == 1 and sim.spawned == [] and len(lines(r)) == 1
    assert "phase repos" in r.out and f"/system:ship {SPEC}" in r.out
    assert "driver" not in dw.state()


def test_a_done_run_is_not_driven_ac_216_1(dw, monkeypatch):  # AC-216.1
    sim, r = run_to_refusal(dw, monkeypatch, lambda: dw.started(API_LIB, phase="done"))
    assert r.rc == 1 and sim.spawned == [] and len(lines(r)) == 1
    assert "phase done" in r.out and f"{CPLAT} finish" in r.out


def test_the_real_spawn_is_a_detached_cplat_process_without_a_model_or_session_ac_216_1(dw, tmp_path, monkeypatch):  # AC-216.1
    d = mod("appship_driver")
    seen = {}

    class P:
        pid = 777

    def popen(cmd, **kw):
        seen.update(cmd=[str(c) for c in cmd], **kw)
        return P()
    monkeypatch.setattr(subprocess, "Popen", popen)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    for name in ("CLAUDE_CODE_SESSION_ID", "CPLAT_SESSION_ID", "CPLAT_HEADLESS", "CPLAT_SHIP_ANSWER", "CPLAT_SHIP_ANSWER_FROM"):
        monkeypatch.setenv(name, "x")
    rec = d.spawn(dw.gitops, "run-1", 1)
    assert rec["pid"] == 777 and rec["starts"] == 1 and rec["run_id"] == "run-1"
    assert rec["log"].endswith("-system-ship-driver.log") and os.path.isdir(os.path.dirname(rec["log"]))
    cmd = seen["cmd"]
    assert cmd[-2:] == ["drive", "--loop"] and "--repo" in cmd and str(dw.gitops) in cmd
    assert not any(w in ("claude", "headless") or w.endswith("/claude") for w in cmd)   # no model session of its own
    assert str(seen["cwd"]) == str(dw.gitops) and seen["start_new_session"] is True and seen["stdin"] == subprocess.DEVNULL
    env = seen["env"]
    assert env["CPLAT_SYSTEM_DRIVER_RUN"] == "run-1"
    for name in ("CLAUDE_CODE_SESSION_ID", "CPLAT_SESSION_ID", "CPLAT_HEADLESS", "CPLAT_SHIP_ANSWER", "CPLAT_SHIP_ANSWER_FROM"):
        assert name not in env, name                                                     # the driver claims nothing


def test_a_failed_spawn_is_one_error_line_and_exit_1_ac_216_1(dw, monkeypatch):  # AC-216.1
    d = mod("appship_driver")
    dw.started(API_LIB, phase="repos")

    def broken(*a, **k):
        raise OSError("no such file: cplat.py")
    monkeypatch.setattr(d, "spawn", broken)
    monkeypatch.setattr(d, "alive", lambda pid: False)
    r = app(dw, "drive")
    assert r.rc == 1 and "cannot start the system ship driver" in r.out and "no such file" in r.out


def test_the_driver_never_calls_a_model_ac_216_1(dw, tmp_path, tick, monkeypatch):  # AC-216.1
    marker = claude_trap(tmp_path, monkeypatch)
    sim = Sim(dw, monkeypatch)
    dw.started(API_ONLY, phase="repos")
    sim.can("complete", results=[(0, "## Shipped: 012-shop — Shop\n")])
    sim.can("finish", results=[(0, f"product ship ended; state archived to {dw.root}/archive.json\n")])
    tick.script = [lambda: finish_repo(dw, "shop-api")]
    assert sim.run() == 0
    assert sim.steps[-3:] == [("phase", "complete"), ("complete",), ("finish",)]
    assert not marker.exists(), "the driver ran `claude`"


def test_the_drivers_waiting_time_counts_toward_the_run_ac_216_1(dw, tick, monkeypatch):  # AC-216.1
    sim = Sim(dw, monkeypatch)
    st = dw.started(API_ONLY, phase="repos")
    sim.can("complete", results=[(0, "report\n")])
    sim.can("finish", results=[(0, "product ship ended; state archived to /x\n")])
    tick.script = [lambda: finish_repo(dw, "shop-api")]
    sim.run()
    rec = runs.active(st["run_id"])
    assert rec["waiting_s"] > 0 and any(x["wait"] == "system ship" + " next --wait" for x in rec["waits"])


# ---------------- AC-216.4: the two "stop" rules end the driver unescalated ----------------

def test_a_red_publish_check_ends_the_driver_and_no_repo_starts_ac_216_4(dw, monkeypatch):  # AC-216.4
    sim = Sim(dw, monkeypatch)
    dw.started(API_LIB)
    sim.can("publish", results=[(1, "spec/plan PR https://github.com/acme/shop-gitops/pull/1 is red: lint failed on pull_request\n")])
    assert sim.run() == 0
    assert sim.steps == [("publish",)]                                                  # no repo start, no escalate step
    end = progress(dw)["end"]
    assert end["kind"] == "stopped" and "is red" in end["line"]


def test_a_clone_with_uncommitted_changes_ends_the_driver_unescalated_ac_216_4(dw, monkeypatch):  # AC-216.4
    sim = Sim(dw, monkeypatch)
    dw.started(API_WORKER, phase="repos")
    (dw.clone("shop-api") / "dirty.txt").write_text("not committed")
    assert sim.run() == 0
    assert sim.steps == [("next",), ("repo", "start", "shop-api")]                       # stops at the refusal: shop-worker is not started
    end = progress(dw)["end"]
    assert end["kind"] == "stopped" and "has uncommitted changes" in end["line"] and "shop-api" in end["line"]
    st = dw.state()
    assert not st.get("escalated") and st["repos"]["shop-api"]["state"] != "running"
    assert appship_proc.SPAWNED == []


# ---------------- AC-216.5: the gitops entry stays with the session ----------------

def test_the_entry_is_started_with_the_other_repos_and_ends_the_driver_ac_216_5(dw, monkeypatch):  # AC-216.5
    sim = Sim(dw, monkeypatch)
    dw.started(ENTRY_PLAN, phase="repos")
    listed = dw.app("next", "--json").json["start"]
    entry = next(s for s in listed if s["entry"])
    assert sim.run() == 0
    assert sim.steps == [("next",), ("repo", "start", GITOPS), ("repo", "start", "shop-api")]
    assert [os.path.basename(s[0]) for s in appship_proc.SPAWNED] == ["shop-api"]        # the component repo's own session starts as today
    end = progress(dw)["end"]
    assert end["kind"] == "entry" and end["id"] == GITOPS and end["worktree"] == entry["clone"]
    assert dw.state()["repos"][GITOPS]["state"] == "running"


def test_a_dependent_of_the_entry_does_not_start_before_the_entry_is_merged_ac_216_5(dw, monkeypatch):  # AC-216.5
    sim = Sim(dw, monkeypatch)
    dw.started([(GITOPS, "gitops-app", [], ["AC-012.1"], False), ("shop-api", "service-python", [GITOPS], ["AC-012.1"], False)], phase="repos")
    assert sim.run() == 0
    assert sim.steps == [("next",), ("repo", "start", GITOPS)]
    assert appship_proc.SPAWNED == []
    assert progress(dw)["end"]["kind"] == "entry"


def test_a_resumed_run_whose_entry_is_running_goes_to_the_session_at_once_ac_216_5(dw, monkeypatch):  # AC-216.5
    sim = Sim(dw, monkeypatch)
    dw.started(ENTRY_PLAN, phase="repos", states={GITOPS: "running"})
    assert sim.run() == 0
    assert sim.steps == []                                                              # the end comes before any step
    end = progress(dw)["end"]
    assert end["kind"] == "entry" and end["id"] == GITOPS


def test_the_entry_end_is_not_an_early_end_so_drive_starts_with_a_fresh_count_ac_216_5(dw, monkeypatch):  # AC-216.5
    sim = Sim(dw, monkeypatch)
    dw.started(ENTRY_PLAN, phase="repos")
    assert app(dw, "drive").rc == 0
    sim.run()
    sim.live.clear()                                                                    # the driver process ended
    assert app(dw, "drive").rc == 0                                                     # the session built the entry and drives again
    assert [s[2] for s in sim.spawned] == [1, 1] and dw.state()["driver"]["starts"] == 1


# ---------------- AC-216.9: a run from today's flow ----------------

def test_a_run_of_todays_flow_is_taken_over_from_its_state_ac_216_9(dw, tick, monkeypatch):  # AC-216.9
    plan = [*API_WORKER, ("shop-web", "web-nextjs", ["shop-api"], ["AC-012.2"], False)]
    sim = Sim(dw, monkeypatch)
    dw.started(plan, phase="repos")
    for rid in ("shop-api", "shop-worker"):
        assert dw.app("repo", "start", rid).rc == 0                                    # today's flow: sessions of their own, no driver
    running_repo(dw, "shop-api")
    finish_repo(dw, "shop-worker")                                                     # finished meanwhile; the state still says running
    assert "driver" not in dw.state() and dw.state()["repos"]["shop-worker"]["state"] == "running"
    sim.can("complete", results=[(0, "report\n")])
    sim.can("finish", results=[(0, "product ship ended; state archived to /x\n")])
    assert app(dw, "drive").rc == 0 and len(sim.spawned) == 1
    tick.script = [lambda: finish_repo(dw, "shop-api"), lambda: finish_repo(dw, "shop-web")]
    assert sim.run() == 0
    assert sim.steps[0] == ("next",)
    repos = dw.state()["repos"]
    assert {i: repos[i]["state"] for i in ("shop-api", "shop-worker", "shop-web")} == dict.fromkeys(("shop-api", "shop-worker", "shop-web"), "passed")
    starts = sorted(os.path.basename(s[0]) for s in appship_proc.SPAWNED)
    assert starts == ["shop-api", "shop-web", "shop-worker"]                            # no repo session that was alive was started again
    assert progress(dw)["end"]["kind"] == "done"


def test_an_escalated_run_that_is_resumed_goes_on_the_same_way_ac_216_9(dw, tick, monkeypatch):  # AC-216.9
    sim = Sim(dw, monkeypatch)
    dw.started(API_ONLY, phase="repos")
    assert dw.app("repo", "start", "shop-api").rc == 0
    assert app(dw, "escalate", "stuck: runner offline", "--cause", "environment").rc == 0
    assert app(dw, "start", SPEC, "--context", "kind-shop").rc == 0                    # the resume
    assert not dw.state().get("escalated")
    sim.can("complete", results=[(0, "report\n")])
    sim.can("finish", results=[(0, "product ship ended; state archived to /x\n")])
    assert app(dw, "drive").rc == 0 and len(sim.spawned) == 1
    tick.script = [lambda: finish_repo(dw, "shop-api")]
    assert sim.run() == 0
    assert sim.steps[0] == ("next",) and ("repo", "start", "shop-api") not in sim.steps
    assert dw.state()["repos"]["shop-api"]["state"] == "passed" and progress(dw)["end"]["kind"] == "done"


# ---------------- AC-216.10: the switch ----------------

OFF = " ".join(["driver: off (CPLAT_SYSTEM_DRIVER=0);", "run phase repos", "in this session"])


def test_the_switch_starts_no_process_and_prints_the_off_line_ac_216_10(dw, monkeypatch):  # AC-216.10
    sim = Sim(dw, monkeypatch)
    dw.started(API_LIB, phase="repos")
    monkeypatch.setenv("CPLAT_SYSTEM_DRIVER", "0")
    before = dw.state_file.read_text()
    r = app(dw, "drive")
    assert r.rc == 0 and lines(r) == [OFF] and sim.spawned == []
    assert dw.state_file.read_text() == before


def test_the_switch_is_read_before_any_other_check_ac_216_10(dw, monkeypatch):  # AC-216.10
    sim = Sim(dw, monkeypatch)
    monkeypatch.setenv("CPLAT_SYSTEM_DRIVER", "0")
    r = app(dw, "drive")                                                                # no run at all
    assert r.rc == 0 and lines(r) == [OFF] and sim.spawned == []


@pytest.mark.parametrize("value", ["1", "", "false", "off", "00", "no"])
def test_any_other_value_leaves_the_driver_on_ac_216_10(dw, monkeypatch, value):  # AC-216.10
    sim = Sim(dw, monkeypatch)
    dw.started(API_LIB, phase="repos")
    monkeypatch.setenv("CPLAT_SYSTEM_DRIVER", value)
    r = app(dw, "drive")
    assert r.rc == 0 and lines(r)[0] == driver_line() and len(sim.spawned) == 1


def test_a_run_a_driver_started_goes_on_in_the_session_from_its_state_ac_216_10(dw, monkeypatch):  # AC-216.10
    sim = Sim(dw, monkeypatch)
    dw.started(API_LIB, phase="repos")
    assert app(dw, "drive").rc == 0
    monkeypatch.setenv("CPLAT_SYSTEM_DRIVER", "0")
    assert lines(app(dw, "drive")) == [OFF] and len(sim.spawned) == 1                   # nothing started, nothing stopped
    nxt = app(dw, "next", "--json")                                                     # the session takes the verbs itself
    assert nxt.rc == 0 and json.loads(nxt.out)["action"] == "start"
