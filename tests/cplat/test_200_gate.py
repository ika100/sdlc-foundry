"""Spec 200 acceptance tests: the Stop hook holds the shipping session of a handed-off run (AC-200.6).

Seams: `ship.gate` (what `cplat component ship gate` answers), the spec 171 wait marks (`put_mark`), `Procs` for the hand-off. The
shipping session is the session id the hand-off recorded (`by` of `<git common dir>/cplat-ship-handoff.json`); its stop counter
lives in that file, never in `cplat-ship.json` (design.md, "Stop hook").
"""
import json

import pytest

import ship
import stopgate
from ship200_support import SPEC, WAIT_COMMAND, detach, handoff_file, interactive, procs  # noqa: F401
from test_171_stop_hook import put_mark
from test_ship import repo  # noqa: F401  (fixture)

LIMIT = stopgate.NO_PROGRESS_LIMIT


def stop(repo, session="S1", message=None):
    hook = {"session_id": session, "cwd": str(repo)}
    if message is not None:
        hook["last_assistant_message"] = message
    return ship.gate(repo, hook, run_tests=False)


@pytest.fixture()
def hand_off(repo, procs, monkeypatch, capsys):
    """Call it in the test body: session S1 hands the ship of spec 007 off to a (fake) headless process."""
    def go():
        p = procs()
        interactive(monkeypatch, "S1")
        rc, out, err = detach(capsys, repo)
        assert rc == 0, out + err
        return p
    return go


def test_the_hook_holds_the_shipping_session_with_the_wait_as_next_step_ac_200_6(repo, hand_off):  # AC-200.6
    hand_off()
    h = ship.load_state(repo)["headless"]
    answer = stop(repo)
    assert answer["decision"] == "block"
    reason = answer["reason"]
    assert WAIT_COMMAND in reason and str(h["pid"]) in reason and h["log"] in reason
    assert SPEC in reason


def test_the_shipping_sessions_counter_lives_in_the_handoff_file_not_in_the_ship_state_ac_200_6(repo, hand_off):  # AC-200.6
    hand_off()
    before = ship.state_path(repo).read_text()
    for _ in range(LIMIT + 1):
        stop(repo)
    assert ship.state_path(repo).read_text() == before                   # the headless process owns this file
    assert json.loads(handoff_file(repo).read_text())["by"] == "S1"


def test_stops_without_progress_end_in_a_system_message_not_an_escalation_ac_200_6(repo, hand_off):  # AC-200.6
    hand_off()
    answers = [stop(repo) for _ in range(LIMIT + 2)]
    assert answers[0]["decision"] == "block"
    last = answers[-1]
    assert "decision" not in last and WAIT_COMMAND in last["systemMessage"]
    st = ship.load_state(repo)
    assert str(st["headless"]["pid"]) in last["systemMessage"]
    assert not st.get("escalated")                                       # the run itself is not stuck


def test_progress_of_the_run_resets_the_count_ac_200_6(repo, hand_off):  # AC-200.6
    hand_off()
    for _ in range(LIMIT + 1):
        stop(repo)
    ship.set_phase(repo, "pr")                                           # the headless session moved on
    assert stop(repo)["decision"] == "block"


def test_a_running_wait_lets_the_stop_through_and_is_named_ac_200_6(repo, hand_off):  # AC-200.6, AC-202.1
    hand_off()
    stop(repo)
    mark = put_mark(repo, WAIT_COMMAND)
    for _ in range(LIMIT + 3):                                           # more stops than would end the hold
        answer = stop(repo)
        assert "decision" not in answer and WAIT_COMMAND in answer["systemMessage"]
    assert not ship.load_state(repo).get("escalated")
    mark.unlink()                                                        # the wait ended: stops count again
    later = [stop(repo) for _ in range(LIMIT + 2)]
    assert "systemMessage" in later[-1]


def test_a_finished_run_lets_the_shipping_session_stop_ac_200_6(repo, hand_off):  # AC-200.6
    hand_off()
    ship.save_state(repo, {**ship.load_state(repo), "phase": "done"})
    assert stop(repo) is None


def test_an_escalated_run_lets_the_shipping_session_stop_ac_200_6(repo, hand_off):  # AC-200.6
    hand_off()
    ship.save_state(repo, {**ship.load_state(repo), "escalated": "needs a store", "cause": "decision"})
    assert stop(repo) is None
