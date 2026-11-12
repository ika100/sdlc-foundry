"""Spec 186 (t3): the answer action, hold and resume as module functions of the system ship scheduler."""
from __future__ import annotations

import appship_sched as sched
import shipwait
from test_186_system_ship import api_and_worker, spawned, w  # noqa: F401  (fixtures)


def _next(world):
    return sched.next_action(world.gitops, world.state())


def test_answer_then_resume_then_wait_leaves_the_other_repo_alone(w, spawned):
    api_and_worker(w)
    worker = w.state()["repos"]["shop-worker"]
    assert _next(w)["action"] == "answer"
    sched.resume_repo(w.gitops, "shop-api", "use redis")
    assert w.state()["repos"]["shop-worker"] == worker
    nxt = _next(w)
    assert nxt["action"] == "wait" and "answer" not in nxt and nxt["held"] == []
    assert spawned[-1]["answer"] == "use redis"


def test_hold_then_the_running_repo_ends_then_escalate(w):
    api_and_worker(w)
    assert "held for you" in sched.hold_repo(w.gitops, "shop-api")
    assert _next(w)["action"] == "wait"
    w.edit(lambda st: st["repos"]["shop-worker"].update(state="passed"))
    assert _next(w)["action"] == "escalate"


def test_next_wait_returns_the_first_action_that_is_not_wait():
    assert shipwait.next_wait is not None
    assert sched.questions_of("plain reason", None) == []
    assert sched.questions_of("Which? (suggested: a; alternatives: b)", None) == [{"text": "Which?", "suggested": "a"}]
    assert sched.questions_of("r", [{"text": "q", "suggested": None}]) == [{"text": "q", "suggested": None}]
