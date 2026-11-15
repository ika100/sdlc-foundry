"""Spec 202 acceptance tests: the guard against looping sessions (AC-202.4, AC-202.5 for `cplat headless`).

Contract: design.md "Loop guard rules" and "`cplat headless`". The transcript is `<CLAUDE_CONFIG_DIR>/projects/<dir>/<session>.jsonl`;
a call is one assistant message id, idle when none of its lines holds a `tool_use` block (judged 3 s after its last line).
Time is fake: `Guard.observe(now)` takes a datetime, and `headless.clock`/`headless.sleep` move together; nothing waits.
"""
import datetime as dt
import json
import os
import stat
import subprocess
import sys

import pytest

import cplat
import core
import headless
import ship
from test_headless import fake_claude, repo, runs  # noqa: F401  (fixtures, helpers)
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)
from wait202_support import FakeTime
from waiting import budget, fake_prelude, wait_file

T0 = dt.datetime(2026, 11, 15, 10, 0, 0)
SID = "11111111-2222-3333-4444-555555555555"


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    for name in ("CLAUDE_CODE_SESSION_ID", "CPLAT_SESSION_ID", "CPLAT_DISPATCH_RESULT", "CPLAT_DISPATCH_UNIT", "CPLAT_UNIT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-config"))


def transcript(tmp_path):
    f = tmp_path / "claude-config" / "projects" / "proj" / f"{SID}.jsonl"
    f.parent.mkdir(parents=True, exist_ok=True)
    return f


def put(f, mid, *blocks, at=T0, sidechain=False):
    """One assistant line of message `mid`; a block is "text" or "tool"."""
    content = [{"type": "tool_use", "id": f"t-{mid}", "name": "Bash", "input": {}} if b == "tool" else {"type": "text", "text": f"said {mid}"}
               for b in blocks]
    line = {"type": "assistant", "isSidechain": sidechain, "timestamp": at.isoformat(), "message": {"id": mid, "role": "assistant", "content": content}}
    with f.open("a") as fh:
        fh.write(json.dumps(line) + "\n")


def guard(repo, calls=10, minutes=5, phase="land"):
    import loopguard
    return loopguard.Guard(calls, minutes, repo, SID, phase)


def at(seconds):
    return T0 + dt.timedelta(seconds=seconds)


def commit(repo, msg="step"):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", msg], cwd=repo, check=True)


# ---------------- AC-202.4 / AC-202.5: parse ----------------

def test_loop_guard_parses_calls_slash_minutes_and_the_default_is_10_in_5():  # AC-202.5
    import loopguard
    assert loopguard.DEFAULT == (10, 5)
    assert loopguard.parse("3/1") == (3, 1) and loopguard.parse("100/60") == (100, 60) and loopguard.parse("10/5") == (10, 5)


@pytest.mark.parametrize("text", ["2/5", "101/5", "10/0", "10/61", "10", "a/b", "10/5/1", "", "3.5/5"])
def test_loop_guard_refuses_values_outside_the_ranges(text):  # AC-202.5
    import loopguard
    with pytest.raises(core.PlatformError):
        loopguard.parse(text)


# ---------------- AC-202.4: the guard's rules ----------------

def test_a_session_answering_every_refused_stop_in_one_line_trips_at_its_10th_idle_call(repo, tmp_path):  # AC-202.4
    g, f = guard(repo), transcript(tmp_path)
    for i in range(1, 11):
        t = 1.5 * i                                           # one idle call every 1.5 seconds
        put(f, f"m{i}", "text", at=at(t))
        verdict = g.observe(at(t + 3.1))                      # an idle call is judged 3 s after its last line
        if i < 10:
            assert verdict is None, i
    assert verdict and verdict.startswith("looping: 10 model calls in 5 min without progress in phase land"), verdict
    assert g.observe(at(100)) == verdict                      # sticky


def test_a_call_that_runs_a_tool_is_never_idle_and_a_text_block_before_its_tool_use_does_not_count(repo, tmp_path):  # AC-202.4
    g, f = guard(repo), transcript(tmp_path)
    for i in range(1, 301):                                   # 15 minutes of calls (every 3 s), each runs a tool
        put(f, f"m{i}", "text", at=at(3 * i))
        put(f, f"m{i}", "tool", at=at(3 * i))
        assert g.observe(at(3 * i + 4)) is None, i


def test_idle_calls_in_a_message_split_over_lines_count_once(repo, tmp_path):  # AC-202.4
    g, f = guard(repo, calls=3), transcript(tmp_path)
    for i in range(1, 3):
        put(f, f"m{i}", "text", at=at(i))
        put(f, f"m{i}", "text", at=at(i))
    assert g.observe(at(10)) is None                          # two calls, not four


def test_sidechain_lines_never_count_as_idle_calls(repo, tmp_path):  # AC-202.4
    g, f = guard(repo, calls=3), transcript(tmp_path)
    for i in range(1, 8):
        put(f, f"s{i}", "text", at=at(i), sidechain=True)
    assert g.observe(at(30)) is None


def test_a_commit_a_phase_change_or_a_tool_call_is_progress(repo, tmp_path):  # AC-202.4
    f = transcript(tmp_path)
    ship.start(repo, "7", True)
    g = guard(repo, calls=4)
    for i in range(1, 4):
        put(f, f"a{i}", "text", at=at(i))
    assert g.observe(at(10)) is None
    commit(repo)                                              # a new commit: progress, the 3 idle calls before it no longer count
    for i in range(1, 4):
        put(f, f"b{i}", "text", at=at(20 + i))
    assert g.observe(at(30)) is None
    ship_state = ship.load_state(repo)
    ship.save_state(repo, {**ship_state, "phase": "review" if ship_state["phase"] != "review" else "land"})
    for i in range(1, 4):
        put(f, f"c{i}", "text", at=at(40 + i))
    assert g.observe(at(50)) is None
    put(f, "d1", "text", "tool", at=at(60))                   # a call that runs a tool
    for i in range(1, 4):
        put(f, f"e{i}", "text", at=at(61 + i))
    assert g.observe(at(70)) is None


def test_idle_calls_older_than_the_window_do_not_count(repo, tmp_path):  # AC-202.4
    g, f = guard(repo, calls=10, minutes=5), transcript(tmp_path)
    for i in range(1, 7):
        put(f, f"a{i}", "text", at=at(i))
    assert g.observe(at(20)) is None
    for i in range(1, 7):                                     # six minutes later: 6 + 6 calls, but only 6 in the last 5 minutes
        put(f, f"b{i}", "text", at=at(400 + i))
    assert g.observe(at(420)) is None


def test_no_transcript_means_no_calls_and_never_trips(repo):  # AC-202.4
    g = guard(repo)
    for i in range(50):
        assert g.observe(at(10 * i)) is None


def test_the_thresholds_are_the_guards_own(repo, tmp_path):  # AC-202.5
    g, f = guard(repo, calls=3, minutes=1), transcript(tmp_path)
    for i in range(1, 4):
        put(f, f"m{i}", "text", at=at(i))
    assert g.observe(at(10)).startswith("looping: 3 model calls in 1 min without progress in phase land")


# ---------------- AC-202.4: `cplat headless` ends a looping session ----------------

LOOPING = """#!{py}
{pre}
import json, os, sys, time, pathlib
args = sys.argv[1:]
sid = args[args.index("--session-id") + 1]
with open("runs.txt", "a") as fh:
    fh.write("run\\n")
pathlib.Path("pid.txt").write_text(str(os.getpid()))
f = pathlib.Path(os.environ["CLAUDE_CONFIG_DIR"]) / "projects" / "proj" / (sid + ".jsonl")
f.parent.mkdir(parents=True, exist_ok=True)
pathlib.Path("sid.txt").write_text(sid)
for i in range({n}):
    block = {{"type": "tool_use", "id": "t%d" % i, "name": "Bash", "input": {{}}}} if {tools} else {{"type": "text", "text": "Still waiting for the land to finish. token=ghp_abcdefghijklmnopqrstuvwxyz0123456789"}}
    line = {{"type": "assistant", "message": {{"id": "m%d" % i, "role": "assistant", "content": [block]}}}}
    with f.open("a") as fh:
        fh.write(json.dumps(line) + "\\n")
pathlib.Path("written.txt").write_text("")
deadline = time.time() + 60
while time.time() < deadline and not os.path.exists("release.txt"):
    time.sleep(0.05)  # fake-delay: a session that goes on until the guard ends it (or the test releases it)
pathlib.Path("natural.txt").write_text("")    # only a session that ends by itself gets here: the guard's signal ends it before
if {finish}:
    st = os.popen("git rev-parse --git-common-dir").read().strip() + "/cplat-ship.json"
    d = json.load(open(st)); d["phase"] = "done"; json.dump(d, open(st, "w"))
    sys.exit(0)
"""


def looping_claude(tmp_path, monkeypatch, n, tools=False, finish=False):
    exe = tmp_path / "claude"
    exe.write_text(LOOPING.format(py=sys.executable, pre=fake_prelude(), n=n, tools=tools, finish=finish))
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("CPLAT_CLAUDE", str(exe))


@pytest.fixture()
def fake_time(monkeypatch):
    t = FakeTime()
    monkeypatch.setattr(headless, "clock", t.clock)
    monkeypatch.setattr(headless, "sleep", t.sleep)
    return t


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_a_looping_session_is_ended_after_its_10th_idle_call_and_the_run_escalates(repo, tmp_path, monkeypatch, capsys, fake_time):  # AC-202.4
    ship.start(repo, "7", True)
    phase = ship.load_state(repo)["phase"]
    looping_claude(tmp_path, monkeypatch, 10)
    seen = {}

    def on_sleep(n, now):                                     # the fake session would end by itself 6 minutes after its 10th call
        if (repo / "written.txt").exists():
            if now - seen.setdefault("at", now) >= dt.timedelta(minutes=6):
                (repo / "release.txt").write_text("")
    fake_time.on_sleep = on_sleep
    assert headless.main(["/svc:ship 7", "--repo", str(repo), "--max-runs", "3"]) == 1
    assert runs(repo) == 1                                    # no new session
    assert not (repo / "natural.txt").exists()                # the guard ended it (by signal) before it could end by itself
    assert not alive(int((repo / "pid.txt").read_text()))
    out = capsys.readouterr().out
    reason = f"looping: 10 model calls in 5 min without progress in phase {phase}"
    [line] = [ln for ln in out.splitlines() if ln.startswith(f"HEADLESS shop-api: {reason}")]
    assert "; last message: Still waiting for the land to finish." in line
    assert "ghp_abcdefghijklmnopqrstuvwxyz0123456789" not in out and len(line.split("; last message: ")[1]) <= 200   # redacted, at most 200 characters
    st = ship.load_state(repo)
    assert st["escalated"].startswith(reason) and st["cause"] == "platform"


def test_a_session_that_runs_a_tool_in_every_call_is_never_stopped_by_the_guard(repo, tmp_path, monkeypatch, capsys, fake_time):  # AC-202.4
    ship.start(repo, "7", True)
    looping_claude(tmp_path, monkeypatch, 0, finish=True)     # the session lives for 15 fake minutes and ends by itself, done
    seen = {}

    def on_sleep(n, now):                                     # one model call per poll, each with a text block and then its tool_use
        if not (repo / "sid.txt").exists():
            return
        started = seen.setdefault("at", now)
        f = tmp_path / "claude-config" / "projects" / "proj" / f"{(repo / 'sid.txt').read_text()}.jsonl"
        put(f, f"m{n}", "text", at=now)
        put(f, f"m{n}", "tool", at=now)
        seen["calls"] = seen.get("calls", 0) + 1
        if now - started >= dt.timedelta(minutes=15):
            (repo / "release.txt").write_text("")
    fake_time.on_sleep = on_sleep
    assert headless.main(["/svc:ship 7", "--repo", str(repo)]) == 0
    assert runs(repo) == 1 and (repo / "release.txt").exists() and seen["calls"] >= 15
    assert "looping:" not in capsys.readouterr().out


def test_the_loop_guard_option_sets_the_threshold_of_a_run_started_by_hand(repo, tmp_path, monkeypatch, capsys, fake_time):  # AC-202.5
    ship.start(repo, "7", True)
    looping_claude(tmp_path, monkeypatch, 3)
    assert headless.main(["/svc:ship 7", "--repo", str(repo), "--loop-guard", "3/1", "--max-runs", "3"]) == 1
    assert "looping: 3 model calls in 1 min without progress in phase" in capsys.readouterr().out
    assert runs(repo) == 1


@pytest.mark.parametrize("value", ["2/5", "101/5", "10/0", "10/61", "ten", "10"])
def test_a_bad_loop_guard_is_refused_and_nothing_starts(repo, tmp_path, monkeypatch, capsys, store, value):  # AC-202.5
    ship.start(repo, "7", True)
    looping_claude(tmp_path, monkeypatch, 1)
    rc = cplat.main(["headless", "/svc:ship 7", "--repo", str(repo), "--loop-guard", value])
    assert rc == 1 and runs(repo) == 0 and stored(store) == []
    err = capsys.readouterr().err
    assert f"ERROR: --loop-guard: {value} is not allowed (allowed: <calls>/<minutes>, calls an integer 3..100, minutes an integer 1..60)" in err
