"""Spec 171 acceptance tests: the Stop hook knows the `cplat` waits a session started and still runs (AC-171.8).

A running wait marks itself in the checkout's git dir (`<git dir>/cplat-waits/<pid>.json`, design.md "Stop hook"); the hook of the
component ship (`ship.gate`) and of the system ship (`appship_state.gate`) hold the count of stops without progress while one runs.
Seams: marks written by the tests for a live pid (the test process) and a dead one; `waits.running` and `waits.live`; the 126 worlds.
"""
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
from test_appship_097 import SPEC as SYSTEM_SPEC
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
    f.write_text(json.dumps({"pid": pid, "command": command, "started_at": "2026-11-10T10:00:00"}))
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

def test_a_running_wait_blocks_the_stop_holds_the_count_and_names_itself(repo, monkeypatch):  # AC-171.8
    begin(repo, monkeypatch)
    stop(repo)                                                       # the first stop is progress: 0
    assert "stops without progress: 1/2" in first_line(stop(repo))   # a stop without a wait counts as in AC-126.4
    mark = put_mark(repo, "cplat pr wait 7 --merge")
    for _ in range(4):                                               # more stops than would escalate at 2
        answer = stop(repo)
        assert first_line(answer) == "waiting: cplat pr wait 7 --merge; stops without progress: 1/2"
        assert f"The ship run of {SPEC} is not finished" in answer["reason"]
        assert "cplat component ship escalate" in answer["reason"]          # the keep-going sentence stays
        assert no_progress(repo) == 1 and not ship.load_state(repo).get("escalated")
    mark.unlink()                                                    # the wait ended: stops count again
    answer = stop(repo, message="I do not know how to go on")
    assert "escalated" in answer["systemMessage"] and ship.load_state(repo)["escalated"].startswith("no progress: 2 stops")


def test_several_running_waits_are_named_together(repo, monkeypatch):  # AC-171.8
    begin(repo, monkeypatch)
    put_mark(repo, "cplat pr wait 7")
    put_mark(repo, "cplat component ship wait", pid=os.getppid())
    line = first_line(stop(repo))
    assert line.startswith("waiting: ") and "cplat pr wait 7" in line and "cplat component ship wait" in line
    assert line.endswith("; stops without progress: 0/2")


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


def test_the_verdict_of_a_running_wait_is_a_block_that_keeps_the_count():  # AC-171.8
    st = {"owner": "A", "stop_gate": {"head": "h", "phase": "land", "no_progress": 1}}
    v = stopgate.check(st, "A", {"head": "h", "phase": "land"}, 0, ["cplat pr wait 7"])
    assert (v.action, v.no_progress, v.waiting) == ("block", 1, "cplat pr wait 7")
    assert st["stop_gate"] == {"head": "h", "phase": "land", "no_progress": 1}
    assert stopgate.wait_line(v) == "waiting: cplat pr wait 7; stops without progress: 1/2"
    again = stopgate.check(st, "A", {"head": "h", "phase": "land"}, 0, ["cplat pr wait 7"])
    assert again.action == "block" and again.no_progress == 1          # never 2: a wait does not escalate
    moved = stopgate.check(st, "A", {"head": "h2", "phase": "land"}, 0, ["cplat pr wait 7"])
    assert moved.no_progress == 0                                      # a new commit is progress as ever


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
    assert waits.record(repo, "system ship next --wait", body) == waits.REACHED
    assert seen == [["cplat system ship next --wait"]] and waits.live(repo) == []


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
    assert seen == [["cplat component ship land"]] and waits.live(repo) == []


# ---------------- AC-171.8: the system ship's hook ----------------

def sys_stop(w, session="A"):
    return w.app("gate", stdin=json.dumps({"session_id": session, "cwd": str(w.gitops)}))


def sys_first_line(r):
    assert r.rc == 0 and r.json["decision"] == "block", r.out
    return r.json["reason"].splitlines()[0]


def test_a_running_wait_holds_the_product_ship_too(w, monkeypatch):  # AC-171.8
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "A")
    w.started()
    sys_stop(w)
    assert "stops without progress: 1/2" in sys_first_line(sys_stop(w))
    put_mark(w.gitops, "cplat system ship next --wait")
    for _ in range(3):
        answer = sys_stop(w)
        assert sys_first_line(answer) == "waiting: cplat system ship next --wait; stops without progress: 1/2"
        assert f"The product ship of {SYSTEM_SPEC} is not finished" in answer.json["reason"]
        assert w.state()["stop_gate"]["no_progress"] == 1 and not w.state().get("escalated")
