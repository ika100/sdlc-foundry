"""#1028: a GitHub rate-limit wait never happens while the repo merge lock is held, and ends when the REST bucket has refilled."""
import subprocess
import threading

import core
import merge_lock
import pytest

GRAPHQL = "GraphQL: API rate limit already exceeded for user ID 1."


@pytest.fixture()
def state(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setattr(core, "RATE_WAIT_HOOKS", [])
    monkeypatch.setattr(merge_lock, "sleep", lambda s: None)
    return tmp_path


def test_another_waiter_gets_the_lock_during_a_rate_limit_wait(monkeypatch, state):
    answers = [(1, GRAPHQL), (0, "")]
    during = {}

    def fake(cmd, **kw):
        if cmd[:3] == ["gh", "api", "rate_limit"]:
            return subprocess.CompletedProcess(cmd, 0, str(int(core.now()) + 600), "")
        rc, err = answers.pop(0)
        return subprocess.CompletedProcess(cmd, rc, "ok\n", err)

    def sleep(seconds):
        def other():
            with merge_lock.held("a/b", "other", 5):
                during["got"] = True
        t = threading.Thread(target=other)
        t.start()
        t.join(5)
        during["done"] = not t.is_alive()

    monkeypatch.setattr(core.subprocess, "run", fake)
    monkeypatch.setattr(core, "sleep", sleep)
    with merge_lock.held("a/b", "first", 5):
        assert core.run(["gh", "pr", "view", "1"]).stdout == "ok\n"
        assert merge_lock._holder("a/b")["who"] == "first"      # the lock is back when the call has run again
    assert during == {"got": True, "done": True}
    assert core.RATE_WAIT_HOOKS == []


def test_the_wait_ends_when_the_rest_bucket_has_refilled(monkeypatch):
    slept, polls = [], []

    def fake(cmd, **kw):
        polls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "4498", "")

    monkeypatch.setattr(core.subprocess, "run", fake)
    monkeypatch.setattr(core, "sleep", slept.append)
    assert core._rate_limit_sleep(3600, "graphql") == core.RATE_POLL_EVERY
    assert slept == [core.RATE_POLL_EVERY] and ".resources.graphql.remaining" in polls[0]


def test_the_wait_goes_on_while_the_bucket_is_empty(monkeypatch):
    slept = []
    monkeypatch.setattr(core.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "0", ""))
    monkeypatch.setattr(core, "sleep", slept.append)
    assert core._rate_limit_sleep(2000, "graphql") == 2000 and slept == [900, 900, 200]
