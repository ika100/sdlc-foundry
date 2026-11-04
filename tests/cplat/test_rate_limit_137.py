"""Spec 137 (#409): cplat waits out GitHub's rate limit instead of failing, shows gh's own error, and the console stops reading
its sources while nobody looks at it."""
import subprocess

import core
import pytest
import spec_pr
from console import sources


class FakeGh:
    """Answers `gh …` calls from a script of (returncode, stderr) pairs; `gh api rate_limit` returns `reset`."""

    def __init__(self, answers, reset=None):
        self.answers, self.reset, self.calls = list(answers), reset, []

    def __call__(self, cmd, **kw):
        self.calls.append(list(cmd))
        if cmd[:3] == ["gh", "api", "rate_limit"]:
            out = "" if self.reset is None else str(self.reset)
            return subprocess.CompletedProcess(cmd, 0, out, "")
        rc, err = self.answers.pop(0)
        return subprocess.CompletedProcess(cmd, rc, "ok\n" if rc == 0 else "", err)


@pytest.fixture()
def clock(monkeypatch):
    t = {"now": 1_800_000_000.0, "slept": []}
    monkeypatch.setattr(core, "now", lambda: t["now"])

    def sleep(s):
        t["slept"].append(s)
        t["now"] += s
    monkeypatch.setattr(core, "sleep", sleep)
    return t


GRAPHQL = "GraphQL: API rate limit already exceeded for user ID 1."


def test_a_rate_limited_gh_call_waits_for_the_reset_and_runs_again_ac_137_1_ac_137_2(monkeypatch, clock, capsys):  # AC-137.1, AC-137.2, AC-137.7
    fake = FakeGh([(1, GRAPHQL), (0, "")], reset=int(clock["now"]) + 600)
    monkeypatch.setattr(core.subprocess, "run", fake)
    proc = core.run(["gh", "pr", "view", "1"])
    assert proc.returncode == 0 and proc.stdout == "ok\n"
    assert [c[:3] for c in fake.calls] == [["gh", "pr", "view"], ["gh", "api", "rate_limit"], ["gh", "pr", "view"]]
    assert ".resources.graphql.reset" in fake.calls[1]
    assert clock["slept"] == [630]                       # until the reset, plus 30 s
    assert "GitHub rate limit (graphql): waiting until" in capsys.readouterr().err


def test_without_a_known_reset_the_waits_back_off_ac_137_2(monkeypatch, clock):  # AC-137.2
    fake = FakeGh([(1, "API rate limit exceeded"), (1, "You have exceeded a secondary rate limit"), (1, GRAPHQL), (0, "")])
    monkeypatch.setattr(core.subprocess, "run", fake)
    core.run(["gh", "api", "repos/a/b"])
    assert clock["slept"] == [60, 120, 240]


def test_a_limit_that_does_not_clear_fails_after_65_minutes_with_a_hint_ac_137_3(monkeypatch, clock):  # AC-137.3
    fake = FakeGh([(1, "You have exceeded a secondary rate limit")] * 20)
    monkeypatch.setattr(core.subprocess, "run", fake)
    with pytest.raises(core.PlatformError) as e:
        core.run(["gh", "pr", "list"])
    assert "secondary rate limit" in str(e.value) and sum(clock["slept"]) <= core.RATE_LIMIT_MAX_WAIT
    assert "second `cplat platform ui`" in (e.value.hint or "")


@pytest.mark.parametrize("err", ["HTTP 404: Not Found", "authentication required", "HTTP 502: Bad Gateway"])
def test_other_gh_failures_do_not_wait_ac_137_4(monkeypatch, clock, err):  # AC-137.4
    fake = FakeGh([(1, err)])
    monkeypatch.setattr(core.subprocess, "run", fake)
    with pytest.raises(core.PlatformError) as e:
        core.run(["gh", "api", "x"])
    assert clock["slept"] == [] and err.split(":")[0] in str(e.value)


def test_a_non_gh_command_never_waits_ac_137_4(monkeypatch, clock):  # AC-137.4
    fake = FakeGh([(1, GRAPHQL)])
    monkeypatch.setattr(core.subprocess, "run", fake)
    assert core.run(["git", "push"], check=False).returncode == 1 and clock["slept"] == []


def test_spec_publish_errors_carry_ghs_own_message_ac_137_5(monkeypatch, tmp_path):  # AC-137.5
    monkeypatch.setattr(spec_pr, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "pull request create failed: GraphQL: boom"))
    rc, _ = spec_pr.gh(["pr", "create"], cwd=tmp_path)
    err = spec_pr._gh_failed("opening the draft pull request", rc)
    assert "gh exit 1" in str(err) and "GraphQL: boom" in str(err)


def test_the_console_reads_nothing_while_idle_and_refreshes_on_the_next_request_ac_137_6(monkeypatch):  # AC-137.6, AC-137.7
    t = {"now": 0.0}
    refresher = sources.Refresher({}, lambda name: None, clock=lambda: t["now"], idle_after=600)
    reads = []
    monkeypatch.setattr(refresher, "refresh", lambda names=None: reads.append(t["now"]))
    t["now"] = 300
    assert not refresher.idle()
    t["now"] = 601
    assert refresher.idle()
    started = []
    monkeypatch.setattr(sources.threading, "Thread", lambda target, daemon=True, **kw: type("T", (), {"start": lambda self: (started.append(1), target())})())
    refresher.touch()
    assert not refresher.idle() and reads == [601] and started == [1]   # one refresh at once on the first request after the pause
    refresher.touch()
    assert reads == [601]                                                # a request while active adds no extra refresh
