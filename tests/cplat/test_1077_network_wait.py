"""#1077: `cplat pr wait` waits out a lost network up to its own timeout, one line a minute, without holding the merge lock."""
import subprocess
import threading

import core
import merge_lock
import pytest

DOWN = "dial tcp 140.82.121.5:443: connect: network is down"


@pytest.fixture()
def state(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setattr(core, "RATE_WAIT_HOOKS", [])
    monkeypatch.setattr(merge_lock, "sleep", lambda s: None)


def test_a_long_network_loss_is_waited_out_with_a_line_a_minute(monkeypatch, state, capsys):
    left, slept = [40], []      # 40 failures: far beyond the 5 minutes of a plain call

    def fake(cmd, **kw):
        if left[0]:
            left[0] -= 1
            return subprocess.CompletedProcess(cmd, 1, "", DOWN)
        return subprocess.CompletedProcess(cmd, 0, "ok\n", "")

    monkeypatch.setattr(core.subprocess, "run", fake)
    monkeypatch.setattr(core, "sleep", slept.append)
    monkeypatch.setattr(core, "NETWORK_RETRY_MAX_WAIT", 300)
    with pytest.raises(core.PlatformError):
        core.run(["gh", "pr", "view", "1"])
    left[0], slept[:] = 40, []
    capsys.readouterr()
    with core.network_patience(3600):
        assert core.run(["gh", "pr", "view", "1"]).stdout == "ok\n"
    assert sum(slept) > 1500 and core.NETWORK_PATIENCE is None
    lines = [x for x in capsys.readouterr().err.splitlines() if "network error" in x]
    assert 1 <= len(lines) < 40 and "of 60 min" in lines[-1]


def test_the_merge_lock_is_free_during_the_network_wait(monkeypatch, state):
    left, during = [3], {}

    def fake(cmd, **kw):
        if left[0]:
            left[0] -= 1
            return subprocess.CompletedProcess(cmd, 1, "", DOWN)
        return subprocess.CompletedProcess(cmd, 0, "ok\n", "")

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
    with merge_lock.held("a/b", "first", 5), core.network_patience(600):
        assert core.run(["gh", "pr", "view", "1"]).stdout == "ok\n"
        assert merge_lock._holder("a/b")["who"] == "first"
    assert during == {"got": True, "done": True}
