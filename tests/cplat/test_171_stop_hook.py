"""Spec 171 acceptance tests: the Stop hook knows the `cplat` waits a session started and still runs (AC-171.8).

A running wait marks itself in the checkout's git dir (`<git dir>/cplat-waits/<pid>.json`, design.md "Stop hook"); the hook of the
component ship (`ship.gate`) and of the system ship (`appship_state.gate`) hold the count of stops without progress while one runs.
Seams: marks written by the tests for a live pid (the test process) and a dead one; `waits.running` and `waits.live`; the 126 worlds.
"""
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import pr as prmod
import ship
import stopgate
import waits
from test_appship_097 import w  # noqa: F401  (fixture)
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)
from test_ship import git, repo  # noqa: F401  (fixtures, helpers)

SPEC = "007-price-alerts"
BRANCH = f"feature/{SPEC}"


@pytest.fixture(autouse=True)
def _no_session_env(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.delenv("CPLAT_SESSION_ID", raising=False)


def mark_file(checkout, pid):
    d = Path(subprocess.run(["git", "rev-parse", "--git-dir"], cwd=checkout, capture_output=True, text=True,
                            check=True).stdout.strip())
    d = d if d.is_absolute() else checkout / d
    return d / "cplat-waits" / f"{pid}.json"


def put_mark(checkout, command, pid=None):
    """A wait marked as running, as `waits.running` writes it (design.md): by default for this test process, which is alive."""
    pid = os.getpid() if pid is None else pid
    f = mark_file(checkout, pid)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"pid": pid, "command": command, "started_at": dt.datetime.now().isoformat(timespec="seconds")}))
    return f


def dead_pid():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def begin(repo, monkeypatch, session="A"):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", session)
    return ship.start(repo, "7", True)


def stop(repo, session="A", message=None):
    hook = {"session_id": session, "cwd": str(repo)}
    if message is not None:
        hook["last_assistant_message"] = message
    return ship.gate(repo, hook, run_tests=False)


def first_line(answer):
    assert answer["decision"] == "block", answer
    return answer["reason"].splitlines()[0]


def no_progress(repo):
    return ship.load_state(repo)["stop_gate"]["no_progress"]


# ---------------- AC-171.8: the component hook ----------------

# The block of a running wait (AC-171.8) is replaced by AC-202.1: see test_202_stop_hook.py.

def test_a_mark_of_a_process_that_is_gone_is_no_running_wait(repo, monkeypatch):  # AC-171.8
    begin(repo, monkeypatch)
    f = put_mark(repo, "cplat pr wait 7", pid=dead_pid())
    stop(repo)
    assert "waiting:" not in stop(repo)["reason"]
    assert no_progress(repo) == 1
    assert "escalated" in stop(repo, message="stuck")["systemMessage"]
    assert waits.live(repo) == [] and not f.exists()                 # a dead mark is removed


def test_a_wait_of_another_checkout_does_not_hold_this_run(repo, tmp_path, monkeypatch):  # AC-171.8
    begin(repo, monkeypatch)
    other = tmp_path / "elsewhere"
    other.mkdir()
    subprocess.run(["git", "init", "-q", str(other)], check=True)
    put_mark(other, "cplat pr wait 9")
    stop(repo)
    assert "waiting:" not in stop(repo)["reason"] and no_progress(repo) == 1


def test_without_a_wait_the_verdict_counts_as_before():  # AC-171.8
    st = {"owner": "A", "stop_gate": {"head": "h", "phase": "land", "no_progress": 1}}
    v = stopgate.check(st, "A", {"head": "h", "phase": "land"}, 0, [])
    assert (v.action, v.no_progress, v.waiting) == ("escalate", 2, None)


# ---------------- AC-171.8: the waits mark themselves while they run ----------------

def test_running_marks_the_wait_in_the_git_dir_and_removes_it_at_the_end(repo):  # AC-171.8
    with waits.running("cplat pr wait 7", repo):
        f = mark_file(repo, os.getpid())
        data = json.loads(f.read_text())
        assert data["pid"] == os.getpid() and data["command"] == "cplat pr wait 7" and data["started_at"]
        assert waits.live(repo) == ["cplat pr wait 7"]
    assert waits.live(repo) == [] and not f.exists()


def test_running_marks_nothing_outside_a_checkout(tmp_path):  # AC-171.8
    with waits.running("cplat pr wait 7", tmp_path):
        assert waits.live(tmp_path) == []


def test_running_removes_its_mark_when_the_wait_fails(repo):  # AC-171.8
    with pytest.raises(RuntimeError), waits.running("cplat pr wait 7", repo):
        raise RuntimeError("boom")
    assert waits.live(repo) == []


def test_a_recorded_wait_is_marked_while_its_body_runs(repo, monkeypatch):  # AC-171.8
    monkeypatch.chdir(repo)
    seen = []

    def body():
        seen.append(waits.live(repo))
        return waits.REACHED, "reached"
    assert waits.record(repo, "system ship next --wait", body) == waits.REACHED  # interface: recorded wait name
    assert seen == [["cplat system ship next --wait"]]  # interface: recorded wait name
    assert waits.live(repo) == []


@pytest.mark.parametrize("merge", [False, True])
def test_pr_wait_marks_itself_while_it_runs(repo, monkeypatch, merge):  # AC-171.8
    monkeypatch.chdir(repo)
    seen = []
    monkeypatch.setattr(prmod, "wait", lambda *a, **k: (seen.append(waits.live(repo)), (True, ["ok"]))[1])
    assert prmod.main(["wait", "7", "--repo", str(repo), *(["--merge"] if merge else [])]) == 0
    (marks,) = seen
    assert len(marks) == 1 and marks[0].startswith("cplat pr wait") and marks[0].endswith("--merge") == merge
    assert waits.live(repo) == []


def test_ship_land_marks_itself_while_it_runs(repo, monkeypatch):  # AC-171.8
    monkeypatch.chdir(repo)
    seen = []
    monkeypatch.setattr(ship, "land", lambda *a, **k: (seen.append(waits.live(repo)), (True, ["ok"]))[1])
    assert ship.main(["--repo", str(repo), "land"]) == 0
    assert seen == [["cplat component ship land"]]  # interface: recorded wait name
    assert waits.live(repo) == []


# ---------------- AC-171.8: the system ship's hook ----------------

def sys_stop(w, session="A"):
    return w.app("gate", stdin=json.dumps({"session_id": session, "cwd": str(w.gitops)}))


def test_a_wait_of_another_session_in_this_checkout_does_not_hold_a_session_765(repo, monkeypatch):  # AC-171.8, #765
    other = put_mark(repo, "cplat component ship wait", pid=os.getppid())     # interface: wait mark command name (the shipping session's wait)
    other.write_text(json.dumps({**json.loads(other.read_text()), "session": "SHIPPING"}))
    own = put_mark(repo, "cplat pr wait 7")
    own.write_text(json.dumps({**json.loads(own.read_text()), "session": "UNIT"}))
    assert waits.live(repo, "UNIT") == ["cplat pr wait 7"]                   # a unit session sees only its own wait
    assert waits.live(repo, "SHIPPING") == ["cplat component ship wait"]   # interface: wait mark command name
    assert sorted(waits.live(repo)) == ["cplat component ship wait", "cplat pr wait 7"]   # interface: wait mark command names; no session: every wait
    own.unlink()
    assert waits.live(repo, "UNIT") == []


def test_a_mark_names_the_session_that_runs_the_wait_765(repo, monkeypatch):  # AC-171.8, #765
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "S9")
    with waits.running("cplat pr wait 7", repo):
        (f,) = list(mark_file(repo, os.getpid()).parent.glob("*.json"))
        assert json.loads(f.read_text())["session"] == "S9"
        assert waits.live(repo, "S9") == ["cplat pr wait 7"] and waits.live(repo, "OTHER") == []


def test_a_mark_without_a_session_still_holds_every_session_765(repo):  # AC-171.8, #765: marks of older versions
    put_mark(repo, "cplat pr wait 7")
    assert waits.live(repo, "ANY") == ["cplat pr wait 7"]
