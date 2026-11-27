"""Spec 216 acceptance tests: the Stop hook with a driver (AC-216.8), as `cplat system ship gate` answers it.

The world is the one of spec 097 / 126 (`test_appship_gate_126`); a driver is recorded in the state (`driver`) and its progress is
`<git dir>/cplat-app-ship-driver.json`. The wait marks of spec 171 are written as `waits.running` writes them: the session's own wait
carries its session id, the driver's carries `driver:<run id>` (design.md "The driver's environment").
"""
import json
import os

import pytest

import appship_proc
from support216 import API_LIB, CPLAT, Sim, dw, mod, progress, running_repo  # noqa: F401  (fixtures)
from test_171_stop_hook import mark_file
from test_appship_097 import SPEC
from test_appship_gate_126 import block

WAIT = f"{CPLAT} wait"


@pytest.fixture(autouse=True)
def _no_session_env(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.delenv("CPLAT_SESSION_ID", raising=False)


def stop(dw, session="A", message=None):
    hook = {"session_id": session, "cwd": str(dw.gitops)}
    if message is not None:
        hook["last_assistant_message"] = message
    return dw.app("gate", stdin=json.dumps(hook))


def with_driver(dw, monkeypatch, session="A"):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", session)
    st = dw.started(API_LIB, phase="repos")
    dw.edit(lambda s: s.update(driver={"pid": os.getpid(), "log": "/logs/d.log", "started": "2026-11-23T10:00:00",
                                       "run_id": st["run_id"], "starts": 1}))
    write_steps(dw, 0)
    return st


def write_steps(dw, n):
    st = dw.state()
    body = {"spec": SPEC, "run_id": st["run_id"], "pid": os.getpid(), "log": "/logs/d.log", "started": "2026-11-23T10:00:00",
            "steps": [{"at": "2026-11-23T10:00:00", "argv": ["next", "--json"], "code": 0, "line": "", "ended": "2026-11-23T10:00:01"}
                      for _ in range(n)], "end": None}
    (dw.common / "cplat-app-ship-driver.json").write_text(json.dumps(body))


def put_mark(dw, command, session, pid):
    f = mark_file(dw.gitops, pid)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"pid": pid, "command": command, "session": session, "started_at": "2999-01-01T00:00:00"}))
    return f


def first_line(r):
    line = block(r)
    assert WAIT in r.json["reason"], r.json["reason"]                       # a held owner is always told the wait
    return line


# ---------------- AC-216.8 ----------------

def test_the_owner_outside_a_wait_is_held_with_the_wait_as_next_step_ac_216_8(dw, monkeypatch):  # AC-216.8
    with_driver(dw, monkeypatch)
    r = stop(dw)
    assert r.rc == 0 and r.json["decision"] == "block"
    assert WAIT in r.json["reason"] and f"The product ship of {SPEC} is not finished" in r.json["reason"]


def test_the_drivers_own_wait_does_not_let_the_owner_stop_ac_216_8(dw, monkeypatch):  # AC-216.8
    st = with_driver(dw, monkeypatch)
    put_mark(dw, f"{CPLAT} next --wait",f"driver:{st['run_id']}", os.getppid())
    r = stop(dw)
    assert r.json.get("decision") == "block" and WAIT in r.json.get("reason", "")


def test_a_running_wait_of_the_owner_lets_the_stop_through_ac_216_8(dw, monkeypatch):  # AC-216.8
    with_driver(dw, monkeypatch)
    assert WAIT in stop(dw).json["reason"]                                 # outside the wait the owner is held
    before = dw.state()["stop_gate"]["no_progress"]
    put_mark(dw, WAIT, "A", os.getpid())
    for _ in range(4):
        r = stop(dw)
        assert r.rc == 0 and "decision" not in r.json and WAIT in r.json["systemMessage"]
    assert dw.state()["stop_gate"]["no_progress"] == before and not dw.state().get("escalated")


def test_two_stops_without_progress_escalate_the_run_ac_216_8(dw, monkeypatch):  # AC-216.8
    with_driver(dw, monkeypatch)
    assert "stops without progress: 0/2" in first_line(stop(dw))
    assert "stops without progress: 1/2" in first_line(stop(dw))
    r = stop(dw, message="I do not know how to go on")
    st = dw.state()
    assert st["escalated"] and "no progress: 2 stops in phase repos" in st["escalated"]
    assert "decision" not in r.json and "systemMessage" in r.json


def test_a_driver_step_is_progress_ac_216_8(dw, monkeypatch):  # AC-216.8
    with_driver(dw, monkeypatch)
    stop(dw)
    assert "1/2" in first_line(stop(dw))
    write_steps(dw, 1)                                                    # the driver ended a step
    assert "stops without progress: 0/2" in first_line(stop(dw))
    assert "1/2" in first_line(stop(dw))
    write_steps(dw, 2)
    assert "stops without progress: 0/2" in first_line(stop(dw))


def test_a_repo_state_change_is_progress_ac_216_8(dw, monkeypatch):  # AC-216.8
    with_driver(dw, monkeypatch)
    stop(dw)
    assert "1/2" in first_line(stop(dw))
    dw.edit(lambda s: s["repos"]["shop-api"].update(state="running"))
    assert "stops without progress: 0/2" in first_line(stop(dw))


def test_a_commit_in_a_running_repos_clone_is_progress_ac_216_8(dw, monkeypatch):  # AC-216.8
    with_driver(dw, monkeypatch)
    assert dw.app("repo", "start", "shop-api").rc == 0
    running_repo(dw, "shop-api")
    stop(dw)
    assert "1/2" in first_line(stop(dw))
    import subprocess
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "--allow-empty", "-qm", "work"],
                   cwd=dw.clone("shop-api"), check=True)
    assert "stops without progress: 0/2" in first_line(stop(dw))


def test_a_session_that_does_not_own_the_run_is_not_held_ac_216_8(dw, monkeypatch):  # AC-216.8
    with_driver(dw, monkeypatch, "A")
    assert WAIT in stop(dw, "A").json["reason"]                            # the owner is held
    before = dw.state_file.read_text()
    r = stop(dw, "B")
    assert r.rc == 0 and r.out.strip() == "" and dw.state_file.read_text() == before


def test_the_driver_never_claims_the_run_ac_216_8(dw, monkeypatch):  # AC-216.8
    sim = Sim(dw, monkeypatch)
    with_driver(dw, monkeypatch, "A")
    dw.edit(lambda s: s.update(phase="complete"))
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID")                           # the driver's environment carries no session id
    sim.can("complete", results=[(0, "report\n")])
    sim.can("finish", results=[(0, "product ship ended; state archived to /x\n")])
    assert sim.run() == 0 and sim.steps == [("complete",), ("finish",)]
    assert dw.state()["owner"] == "A" and "driver:" not in json.dumps(dw.state().get("stop_gate") or {})
    assert appship_proc.SPAWNED == []
