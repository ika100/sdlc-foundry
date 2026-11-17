"""Spec 202 acceptance tests: a session that waits for a `cplat` wait may stop (AC-202.1), and a paused unit's session may stop (AC-202.7).

Contract: design.md "Stop hook answers": the gate lets the owning session stop (a `systemMessage`, no block), writes no counter and
escalates nothing. Seams: the wait marks of spec 171 (`put_mark`), `ship.gate`, `appship_state.gate` (the `w` world), `stopgate`.
The 60 seconds of the 2026-11-14 `ship land` are simulated by the mark that exists while the session tries to stop.
"""
import datetime as dt
import json
import os
import re

import pytest

import ship
import stopgate
import units
import units131_support as units131
from ship200_support import SPEC as HANDOFF_SPEC
from ship200_support import WAIT_COMMAND, handoff_file, procs  # noqa: F401  (fixture)
from test_200_gate import hand_off  # noqa: F401  (fixture)
from test_200_gate import stop as handoff_stop
from test_171_stop_hook import SPEC, begin, no_progress, put_mark, stop, sys_stop  # noqa: F401
from test_appship_097 import SPEC as SYSTEM_SPEC
from test_appship_097 import w  # noqa: F401  (fixture)
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)
from test_ship import git, repo  # noqa: F401  (fixtures, helpers)


@pytest.fixture(autouse=True)
def _no_session_env(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.delenv("CPLAT_SESSION_ID", raising=False)
    monkeypatch.delenv("CPLAT_UNIT", raising=False)


def phase(repo):
    return ship.load_state(repo)["phase"]


def lets_stop(answer):
    """A stop that is let through: a one-line `systemMessage`, never a block (`decision`)."""
    assert answer is not None and "decision" not in answer and "reason" not in answer, answer
    assert set(answer) == {"systemMessage"} and "\n" not in answer["systemMessage"], answer
    return answer["systemMessage"]


# ---------------- AC-202.1: the verdict ----------------

def test_a_running_wait_is_a_verdict_that_lets_the_stop_through_and_leaves_the_state_alone():  # AC-202.1
    st = {"owner": "A", "stop_gate": {"head": "h", "phase": "land", "no_progress": 1}}
    v = stopgate.check(st, "A", {"head": "h", "phase": "land"}, 0, ["cplat pr wait 7"])
    assert (v.action, v.no_progress, v.waiting) == ("waiting", 1, "cplat pr wait 7")
    assert st["stop_gate"] == {"head": "h", "phase": "land", "no_progress": 1}
    moved = stopgate.check(st, "A", {"head": "h2", "phase": "land"}, 0, ["cplat pr wait 7"])
    assert moved.action == "waiting" and st["stop_gate"] == {"head": "h", "phase": "land", "no_progress": 1}  # not written at all
    assert not hasattr(stopgate, "wait_line")                                   # ADR-093's block is gone


def test_the_waiting_line_names_the_commands_and_the_place():  # AC-202.1
    answer = stopgate.waiting_message("ship 007-price-alerts", ["cplat pr wait 7", "cplat component ship land"], "in phase land")  # interface: wait command name
    assert answer == {"systemMessage": "ship 007-price-alerts: waiting for cplat pr wait 7, cplat component ship land in phase land"}


def test_without_a_wait_the_verdict_counts_as_before_ac_126_5():  # AC-202.1
    st = {"owner": "A", "stop_gate": {"head": "h", "phase": "land", "no_progress": 1}}
    v = stopgate.check(st, "A", {"head": "h", "phase": "land"}, 0, [])
    assert (v.action, v.no_progress) == ("escalate", 2)


# ---------------- AC-202.1: the component ship ----------------

def test_the_2026_11_14_case_a_land_that_runs_while_the_session_stops_shows_one_stop_and_no_block(repo, monkeypatch):  # AC-202.1
    begin(repo, monkeypatch)
    stop(repo)                                                      # the first stop is progress
    assert "stops without progress: 1/2" in stop(repo)["reason"]    # counts as in AC-126.4 without a wait
    before = no_progress(repo)
    mark = put_mark(repo, "cplat component ship land")  # interface: wait command name; `ship land` runs for 60 s
    line = lets_stop(stop(repo))
    assert line == f"ship {SPEC}: waiting for cplat component ship land in phase {phase(repo)}"
    for _ in range(40):                                             # a session that kept trying (every 1.5 s for 60 s) is never blocked
        assert lets_stop(stop(repo)) == line
    assert no_progress(repo) == before and not ship.load_state(repo).get("escalated")
    mark.unlink()                                                   # land ended: stops count as in AC-126.4 / AC-126.5
    assert "escalated" in stop(repo, message="stuck")["systemMessage"]


def test_a_wait_does_not_start_the_count_either(repo, monkeypatch):  # AC-202.1
    begin(repo, monkeypatch)
    put_mark(repo, "cplat pr wait 7 --merge")
    for _ in range(5):
        lets_stop(stop(repo))
    assert no_progress(repo) == 0 and not ship.load_state(repo).get("escalated")


def test_several_waits_are_named_together_oldest_first(repo, monkeypatch):  # AC-202.1
    begin(repo, monkeypatch)
    first = put_mark(repo, "cplat pr wait 7")
    other = put_mark(repo, "cplat component ship wait", pid=os.getppid())  # interface: wait command name
    later = dt.datetime.fromisoformat(json.loads(first.read_text())["started_at"]) + dt.timedelta(seconds=5)
    other.write_text(json.dumps({**json.loads(other.read_text()), "started_at": later.isoformat(timespec="seconds")}))
    line = lets_stop(stop(repo))
    assert re.fullmatch(rf"ship {SPEC}: waiting for cplat pr wait 7, cplat component ship wait in phase \w+", line), line


# ---------------- AC-202.1: the product ship ----------------

def test_a_running_wait_lets_the_product_ship_stop_too(w, monkeypatch):  # AC-202.1
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "A")
    w.started()
    sys_stop(w)
    before = w.state()["stop_gate"]["no_progress"]
    put_mark(w.gitops, "cplat system ship next --wait")  # interface: wait command name
    for _ in range(4):
        r = sys_stop(w)
        assert r.rc == 0 and "decision" not in r.json, r.out
        line = r.json["systemMessage"]
        assert re.fullmatch(rf"ship {SYSTEM_SPEC}: waiting for cplat system ship next --wait in phase \S+", line), line
    assert w.state()["stop_gate"]["no_progress"] == before and not w.state().get("escalated")


# ---------------- AC-202.7: the dispatcher's stop flag lets a session stop ----------------

def set_flag(repo):
    import dispatch_state
    dispatch_state.stop_path(repo).write_text("2026-11-15T10:00:00\n")


def test_pause_requested_reads_the_dispatchers_stop_flag(repo):  # AC-202.7
    assert stopgate.pause_requested(repo) is False
    set_flag(repo)
    assert stopgate.pause_requested(repo) is True


def test_a_paused_unit_session_is_let_stop_before_its_checkpoint_and_nothing_is_counted(repo, monkeypatch):  # AC-202.7
    begin(repo, monkeypatch)
    stop(repo)
    before = no_progress(repo)
    set_flag(repo)
    for _ in range(5):                                              # a session looping as in AC-202.4 ends at its next stop
        line = lets_stop(stop(repo))
        assert line == f"ship {SPEC}: paused by cplat dispatch in phase {phase(repo)}; cplat dispatch resume continues it"
    assert no_progress(repo) == before and not ship.load_state(repo).get("escalated")


def test_a_looping_session_ends_at_its_next_stop_after_the_pause(repo, monkeypatch):  # AC-202.7
    """The fake session answers every refused stop with a new stop attempt (as in AC-202.4); a pause ends it at the next one."""
    begin(repo, monkeypatch)
    stop(repo)
    attempts, ended = 0, False
    for attempts in range(1, 7):
        if attempts == 1:
            set_flag(repo)                                          # `cplat dispatch pause` while the session loops, before AC-126.5 escalates
        answer = stop(repo)
        if answer is not None and "decision" not in answer:
            ended = True
            break
    assert ended and attempts == 1
    assert not ship.load_state(repo).get("escalated")


def test_the_flag_comes_before_a_wait(repo, monkeypatch):  # AC-202.7
    begin(repo, monkeypatch)
    put_mark(repo, "cplat pr wait 7")
    set_flag(repo)
    assert "paused by cplat dispatch" in lets_stop(stop(repo))


# ---------------- AC-202.1, AC-202.7: the gates of a handed-off run and of a unit session ----------------

def test_a_running_wait_lets_the_shipping_session_of_a_handed_off_run_stop_and_counts_nothing(repo, hand_off):  # AC-202.1
    hand_off()
    handoff_stop(repo)                                                              # the first stop is progress
    handoff_stop(repo)                                                              # a stop without a wait counts
    before = json.loads(handoff_file(repo).read_text())["gate"]["no_progress"]
    assert before == 1
    put_mark(repo, WAIT_COMMAND)
    for _ in range(stopgate.NO_PROGRESS_LIMIT + 3):
        line = lets_stop(handoff_stop(repo))
        assert line == f"ship {HANDOFF_SPEC}: waiting for {WAIT_COMMAND} in phase {phase(repo)}"
    assert json.loads(handoff_file(repo).read_text())["gate"]["no_progress"] == before
    assert not ship.load_state(repo).get("escalated")


def unit_session(repo, monkeypatch, command, unit):
    """A unit session of `cplat headless` (`CPLAT_UNIT`): the units file of spec 131 holds the unit."""
    monkeypatch.setenv("CPLAT_PARALLEL_TASKS", "1")
    if command == "ship":
        ship.start(repo, "7", True)
    units131.git(repo, "checkout", "-qb", units131.BRANCH)
    units.prepare(repo, command, units131.SPEC_ID)
    monkeypatch.setenv("CPLAT_UNIT", unit)


def unit_stop(repo):
    return ship.gate(repo, {"session_id": "S", "cwd": str(repo)}, run_tests=False)


def test_a_running_wait_lets_a_ship_unit_session_stop_and_counts_nothing(repo, monkeypatch):  # AC-202.1
    unit_session(repo, monkeypatch, "ship", "task:t1")
    before = units._read(repo)
    put_mark(repo, "cplat component ship land")  # interface: wait command name
    for _ in range(3):
        line = lets_stop(unit_stop(repo))
        assert line == f"ship {units131.SPEC_ID}: waiting for cplat component ship land in phase {phase(repo)}"
    assert units._read(repo) == before and not ship.load_state(repo).get("escalated")


def test_a_running_wait_lets_a_build_unit_session_stop_and_counts_nothing(repo, monkeypatch):  # AC-202.1
    unit_session(repo, monkeypatch, "build", "task:t1")
    before = units._read(repo)
    put_mark(repo, "cplat pr wait 7")
    for _ in range(3):
        line = lets_stop(unit_stop(repo))
        assert line == f"build {units131.SPEC_ID}: waiting for cplat pr wait 7 in unit task:t1"
    assert units._read(repo) == before


def test_a_paused_build_unit_session_is_let_stop_and_nothing_is_counted(repo, monkeypatch):  # AC-202.7
    unit_session(repo, monkeypatch, "build", "task:t1")
    before = units._read(repo)
    set_flag(repo)
    for _ in range(3):
        line = lets_stop(unit_stop(repo))
        assert line == f"build {units131.SPEC_ID}: paused by cplat dispatch in unit task:t1; cplat dispatch resume continues it"
    assert units._read(repo) == before
