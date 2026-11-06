"""#496: a coordinator that ends its turn while a background subagent works made no commit, so the Stop hook counted
no progress and escalated the run. A running background agent of the session now counts as progress."""
import json
import os
import time

import pytest

import ship
import stopgate
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)
from test_ship import FakeGh, check, git, repo  # noqa: F401  (fixtures, helpers)
from test_ship_gate_126 import _no_session_env, begin, stop  # noqa: F401  (fixtures, helpers)


def _agent(transcript, name, finished, age=0.0):
    folder = transcript.with_suffix("") / "subagents"
    folder.mkdir(parents=True, exist_ok=True)
    meta = folder / f"agent-{name}.meta.json"
    meta.write_text(json.dumps({"agentType": "svc:architect", "requestShape": "background", **({"finished": True} if finished else {})}))
    log = folder / f"agent-{name}.jsonl"
    log.write_text("{}\n")
    t = time.time() - age
    os.utime(log, (t, t))
    os.utime(meta, (t, t))


@pytest.fixture()
def transcript(tmp_path):
    t = tmp_path / "proj" / "sess.jsonl"
    t.parent.mkdir()
    t.write_text("")
    return t


def test_only_unfinished_fresh_agents_are_running(transcript):
    hook = {"transcript_path": str(transcript)}
    assert stopgate.running_agents(hook) == 0
    _agent(transcript, "a1", finished=True)
    _agent(transcript, "a2", finished=False, age=stopgate.AGENT_STALE + 60)   # died without finishing
    assert stopgate.running_agents(hook) == 0
    _agent(transcript, "a3", finished=False)
    assert stopgate.running_agents(hook) == 1
    assert stopgate.running_agents({}) == 0


def test_a_running_agent_resets_the_no_progress_count():
    st = {"spec": "007-x", "phase": "plan"}
    stopgate.claim(st, "A")
    mark = {"head": "h1", "phase": "plan"}
    assert stopgate.check(st, "A", mark).action == "block"
    assert stopgate.check(st, "A", mark, running=1) == stopgate.Verdict("wait", 0)
    assert stopgate.check(st, "A", mark).no_progress == 1          # counts from zero again, no escalation


def test_the_ship_gate_lets_a_session_with_a_background_agent_stop_without_escalating(repo, monkeypatch, transcript):
    begin(repo, monkeypatch, "A")
    _agent(transcript, "arch", finished=False)
    for _ in range(4):
        answer = stop(repo, "A", transcript_path=str(transcript))
        assert "decision" not in answer and "waiting for 1 background agent" in answer["systemMessage"]
    st = ship.load_state(repo)
    assert not st.get("escalated") and st["stop_gate"]["no_progress"] == 0
