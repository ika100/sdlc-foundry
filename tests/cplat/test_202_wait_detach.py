"""Spec 202 acceptance tests: a wait outlives its headless session and the next session learns its result (AC-202.2, AC-202.3).

Contract: design.md "Detached waits", "`cplat waits handover`", "`cplat headless`". Seams: real processes in their own session
as the detached waits (`wait202_support`), a fake `gh` on PATH for the end-to-end detach, `headless.clock`/`headless.sleep`
(a sleep moves the clock; 120 minutes pass in no time), `waitdetach.hold(..., clock=, sleep=)` (the clock returns a datetime).
"""
import contextlib
import io
import json
import os
import signal
import stat
import subprocess
import sys
from pathlib import Path

import pytest

import core
import headless
import ship
import usagelimit
from test_headless import fake_claude, repo, runs  # noqa: F401  (fixtures, helpers)
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)
from wait202_support import Detached, FakeTime, detached_dir, wait_gone
from waiting import budget, fake_prelude, wait_for

CPLAT = Path(__file__).resolve().parents[2] / "scripts" / "cplat" / "cplat.py"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for name in ("CLAUDE_CODE_SESSION_ID", "CPLAT_SESSION_ID", "CPLAT_DISPATCH_RESULT", "CPLAT_DISPATCH_UNIT", "CPLAT_WAIT_CHILD"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture()
def made(repo):
    """Detached waits started by a test; every one is ended at teardown."""
    made = []

    def make(*a, **k):
        d = Detached(repo, *a, **k)
        made.append(d)
        return d
    yield make
    for d in made:
        d.close()


def handover(repo):
    import cplat
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = cplat.main(["waits", "handover", "--repo-dir", str(repo)])
    return rc, out.getvalue()


# ---------------- AC-202.3: a wait keeps running after its caller and records its result ----------------

FAKE_GH = """#!{py}
{pre}
import os, sys, time
args = sys.argv[1:]
if args[:2] == ["pr", "view"]:
    while not os.path.exists(os.environ["FAKE_WAIT_RELEASE"]):
        time.sleep(0.05)  # fake-delay: the wait runs until the test releases it
    print('{{"state": "MERGED", "url": "https://github.com/acme/shop-api/pull/7"}}')
else:
    print("{{}}")
"""


def test_a_wait_of_a_headless_session_runs_on_when_its_caller_is_killed_and_records_its_result(repo, tmp_path, monkeypatch):  # AC-202.3
    gh = tmp_path / "bin" / "gh"
    gh.parent.mkdir()
    gh.write_text(FAKE_GH.format(py=sys.executable, pre=fake_prelude()))
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    release = tmp_path / "release"
    env = {**os.environ, "PATH": f"{gh.parent}{os.pathsep}{os.environ['PATH']}", "CPLAT_HEADLESS": "1", "FAKE_WAIT_RELEASE": str(release),
           "HOME": str(tmp_path / "home"), "XDG_STATE_HOME": str(tmp_path / "state"), "XDG_CACHE_HOME": str(tmp_path / "cache")}
    env.pop("CPLAT_WAIT_CHILD", None)
    caller = subprocess.Popen([sys.executable, str(CPLAT), "pr", "wait", "7", "--repo", str(repo)], cwd=repo, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
    record = None
    try:
        wait_for(lambda: list(detached_dir(repo).glob("*.json")) if detached_dir(repo).is_dir() else None, what="the detached record")
        (record_file,) = [f for f in detached_dir(repo).glob("*.json") if not f.name.endswith(".result.json")]
        record = json.loads(record_file.read_text())
        assert record["command"] == "cplat pr wait 7" and record["pid"] != caller.pid
        os.killpg(caller.pid, signal.SIGKILL)                   # the session's process group ends: claude -p ends its shells
        caller.wait(timeout=budget())
        assert os.getpgid(record["pid"]) == record["pid"]       # the wait leads its own process group and is still running
        release.write_text("")
        result_file = detached_dir(repo) / f"{record['id']}.result.json"
        wait_for(result_file.is_file, what="the recorded result")
        result = json.loads(result_file.read_text())
        assert result["code"] == 0 and result["command"] == "cplat pr wait 7"
        assert len(result["tail"]) <= 20 and any("already merged" in ln for ln in result["tail"])
    finally:
        release.write_text("")
        if caller.poll() is None:
            caller.kill()
        if record:
            with contextlib.suppress(OSError):
                os.killpg(record["pid"], signal.SIGKILL)


def test_outside_headless_a_wait_is_not_detached(repo, monkeypatch):  # AC-202.2
    """An interactive session keeps its background task: the wait runs in the calling process and ends with it."""
    import pr as prmod
    import waits
    import cplat
    monkeypatch.delenv("CPLAT_HEADLESS", raising=False)
    monkeypatch.chdir(repo)
    seen = []
    monkeypatch.setattr(prmod, "wait", lambda *a, **k: (seen.append(waits.live(repo)), (True, ["merged"]))[1])
    assert cplat.main(["pr", "wait", "7", "--repo", str(repo)]) == 0
    assert seen and seen[0] and not detached_dir(repo).exists()


def test_an_interactive_session_wakes_on_the_waits_result_by_the_instructions_ac_202_2():  # AC-202.2
    root = Path(__file__).resolve().parents[2] / "plugins" / "component"
    text = (root / "commands" / "ship.md").read_text().lower() + (root / "references" / "unit-mode.md").read_text().lower()
    assert "background" in text and "exit code" in text, "the ship instructions: a session may stop while its wait runs and reads its result"

def test_the_shared_plugin_hands_the_wait_result_over_at_every_session_start_ac_202_2():  # AC-202.2
    hooks = json.loads((Path(__file__).resolve().parents[2] / "plugins" / "shared" / "hooks" / "hooks.json").read_text())
    commands = [h["command"] for g in hooks["hooks"]["SessionStart"] for h in g["hooks"]]
    assert any("cplat" in c and "waits handover" in c for c in commands), commands

# ---------------- AC-202.3: `cplat waits handover` ----------------

def test_handover_prints_the_result_of_an_ended_wait_and_removes_its_files(repo, made):  # AC-202.3
    d = made("cplat component ship land")  # interface: wait command name
    d.end(code=3, tail=[f"line {i}" for i in range(20)])
    rc, out = handover(repo)
    assert rc == 0
    lines = out.splitlines()
    assert lines[0].startswith("wait cplat component ship land ended: exit 3 at ") and lines[0].endswith("; its last lines:")
    assert [ln.strip() for ln in lines[1:]] == [f"line {i}" for i in range(20)]
    assert not list(detached_dir(repo).glob(f"{d.ident}.*"))
    assert handover(repo) == (0, "")                               # nothing to report: no output


def test_handover_reports_a_wait_that_was_killed_and_a_wait_that_still_runs(repo, made):  # AC-202.3
    gone = made("cplat pr wait 7", ident="a")
    gone.end(code=None)
    live = made("cplat component ship wait", ident="b")  # interface: wait command name
    rc, out = handover(repo)
    assert rc == 0
    assert "wait cplat pr wait 7 ended without a result" in out.splitlines()
    assert f"wait cplat component ship wait is still running (pid {live.proc.pid})" in out.splitlines()
    assert not list(detached_dir(repo).glob("a.*")) and (detached_dir(repo) / "b.json").is_file()


def test_handover_without_detached_waits_prints_nothing_and_exits_0(repo):  # AC-202.3
    assert handover(repo) == (0, "")


# ---------------- AC-202.3: waitdetach ----------------

def test_alive_and_ended_tell_the_waits_of_the_checkout_apart(repo, made):  # AC-202.3
    import waitdetach
    running, finished = made("cplat pr wait 7", ident="a"), made("cplat component ship land", ident="b")  # interface: wait command name
    finished.end(code=0, tail=["done"])
    assert [d.command for d in waitdetach.alive(repo)] == ["cplat pr wait 7"]
    (e,) = waitdetach.ended(repo)
    assert e.code == 0 and e.tail == ["done"]
    running.end(code=None)
    assert sorted(x.result is None for x in waitdetach.ended(repo)) == [False, True]


def test_every_wait_command_a_caller_records_is_listed():  # AC-202.3
    import waitdetach
    for command in ("pr wait", "component ship land", "component ship wait", "system wait", "cluster wait", "dispatch wait",
                    "component release wait", "component release gates"):
        assert command in waitdetach.WAIT_COMMANDS or tuple(command.split()) in waitdetach.WAIT_COMMANDS, command


def test_hold_returns_at_once_without_a_wait(repo):  # AC-202.3
    import waitdetach
    t = FakeTime()
    h = waitdetach.hold(repo, clock=t.clock, sleep=t.sleep)
    assert h.done is True and t.sleeps == []


def test_hold_polls_every_5_seconds_without_a_session_until_the_wait_ends(repo, made):  # AC-202.3
    import waitdetach
    d = made("cplat pr wait 7")
    t = FakeTime(on_sleep=lambda n, now: d.end(code=0) if n == 4 else None)
    h = waitdetach.hold(repo, clock=t.clock, sleep=t.sleep)
    assert h.done is True and set(t.sleeps) == {5} and len(t.sleeps) == 4


def test_hold_stops_a_wait_still_running_after_120_minutes(repo, made):  # AC-202.3
    import waitdetach
    d = made("cplat pr wait 7")
    t = FakeTime()
    h = waitdetach.hold(repo, limit_min=120, poll=5, clock=t.clock, sleep=t.sleep)
    assert h.done is False and h.command == "cplat pr wait 7"
    assert 119 * 60 <= sum(t.sleeps) <= 121 * 60
    d.proc.wait(timeout=budget())                                  # its process group was stopped


# ---------------- AC-202.3: `cplat headless` holds before every session ----------------

@pytest.fixture()
def T(monkeypatch):
    holder = {}

    def make(on_sleep=None):
        t = FakeTime(on_sleep)
        monkeypatch.setattr(headless, "clock", t.clock)
        monkeypatch.setattr(headless, "sleep", t.sleep)
        holder["t"] = t
        return t
    monkeypatch.setattr(usagelimit, "QUICK_SECONDS", 60)           # a silent, quick session reads as a usage limit unless a wait explains it
    return make


SPAWN = """import json, os, subprocess, sys
repo = sys.argv[1]
git = subprocess.run(["git", "rev-parse", "--git-dir"], cwd=repo, capture_output=True, text=True).stdout.strip()
d = os.path.join(os.path.abspath(os.path.join(repo, git)), "cplat-waits", "detached")
os.makedirs(d, exist_ok=True)
hold = os.path.join(d, "w1.release")
p = subprocess.Popen([sys.executable, "-c", {sleeper!r}, hold], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
open(os.path.join(d, "w1.log"), "w").close()
json.dump({{"id": "w1", "pid": p.pid, "command": "cplat pr wait 7", "argv": ["pr", "wait", "7"], "session": None,
           "log": os.path.join(d, "w1.log"), "started_at": "2026-11-15T10:00:00"}}, open(os.path.join(d, "w1.json"), "w"))
"""

FINISH = """f=$(git rev-parse --git-common-dir)/cplat-ship.json
sed -i.bak 's/"phase": "[a-z]*"/"phase": "done"/' "$f"
"""


def end_wait(repo, code=0, tail=("merged",)):
    pid = json.loads((detached_dir(repo) / "w1.json").read_text())["pid"]
    (detached_dir(repo) / "w1.release").write_text("")
    wait_gone(pid)
    (detached_dir(repo) / "w1.result.json").write_text(json.dumps({"id": "w1", "command": "cplat pr wait 7", "code": code,
                                                                  "tail": list(tail), "ended_at": "2026-11-15T10:30:00"}))


def test_no_session_starts_while_a_wait_of_the_ended_session_runs_and_the_next_one_gets_its_result(repo, tmp_path, monkeypatch, capsys, T):  # AC-202.3
    import wait202_support as s
    ship.start(repo, "7", True)
    spawn = tmp_path / "spawn.py"
    spawn.write_text(SPAWN.format(sleeper=s.SLEEPER))
    fake_claude(tmp_path, monkeypatch, f'''n=$(wc -l < runs.txt)
if [ "$n" -ge 2 ]; then {FINISH} else {sys.executable} {spawn} {repo}; fi''')
    seen = []

    def on_sleep(n, now):
        seen.append(runs(repo))                                    # no session starts while the wait runs
        if n == 3:
            end_wait(repo)
    T(on_sleep)
    assert headless.main(["/svc:ship 7", "--repo", str(repo)]) == 0
    assert seen and set(seen) == {1} and runs(repo) == 2
    out = capsys.readouterr().out
    assert "waiting for cplat pr wait 7 (pid " in out and "no session starts until it ends" in out
    assert "wait cplat pr wait 7 ended: exit 0" in out
    assert "no progress" not in out and not ship.load_state(repo).get("escalated")   # AC-080.2, AC-131.5: such a session end is no stall


def test_a_wait_that_ended_without_a_result_lets_the_next_session_start_at_once(repo, tmp_path, monkeypatch, capsys, T):  # AC-202.3
    ship.start(repo, "7", True)
    d = Detached(repo)
    d.end(code=None)
    fake_claude(tmp_path, monkeypatch, FINISH)
    t = T()
    assert headless.main(["/svc:ship 7", "--repo", str(repo)]) == 0
    assert runs(repo) == 1 and t.sleeps == []
    assert "wait cplat pr wait 7 ended without a result" in capsys.readouterr().out


def test_a_wait_still_running_120_minutes_after_its_session_ended_escalates_with_cause_environment(repo, tmp_path, monkeypatch, capsys, T):  # AC-202.3
    ship.start(repo, "7", True)
    d = Detached(repo)
    fake_claude(tmp_path, monkeypatch, FINISH)
    t = T()
    try:
        assert headless.main(["/svc:ship 7", "--repo", str(repo)]) == 1
        d.proc.wait(timeout=budget())                              # the wait was stopped
    finally:
        d.close()
    assert runs(repo) == 0                                         # no session started
    assert 119 * 60 <= sum(t.sleeps) <= 121 * 60
    out = capsys.readouterr().out
    assert "HEADLESS shop-api: wait cplat pr wait 7 still running after 120 min" in out
    st = ship.load_state(repo)
    assert st["escalated"] == "wait cplat pr wait 7 still running after 120 min" and st["cause"] == "environment"
