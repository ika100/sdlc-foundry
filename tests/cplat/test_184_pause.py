"""Spec 184 acceptance tests: `cplat headless` pauses at the usage limit instead of stopping (AC-184.1 to AC-184.3).

Two drivers, one decision: unit mode (a ship of units 131, a fake `claude` of `units131_support`) and the legacy loop (the
`test_headless` repo with a bash fake `claude`). A wrapper in front of the unit-mode fake prints the CLI's usage-limit message
(or nothing) for the n-th session of a unit and otherwise runs the real fake. Time is fake: `headless.clock` and `headless.sleep`
are replaced, a sleep moves both clocks (`headless.clock` and the run clock `runs.utcnow` the budget reads) and nothing waits.
"""
import datetime as dt
import json
import stat
import sys
import time

import pytest

import headless
import runs
import ship
from test_headless import fake_claude, repo as legacy_repo, runs as legacy_runs  # noqa: F401  (fixture, helpers)
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)
from units131_support import SPEC_ID, World
from waiting import fake_prelude

NOW = dt.datetime(2026, 11, 11, 10, 0)


class FakeTime:
    def __init__(self, run_clock):
        self.now = NOW
        self.sleeps = []
        self.run_clock = run_clock
        self.count = lambda: 0           # how many sessions have started (a test sets it)
        self.log = []                    # per sleep: (sessions started when it began, the time when it ended)

    def read(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        started = self.count()
        self.now += dt.timedelta(seconds=seconds)
        self.run_clock.tick(seconds)
        self.log.append((started, self.now))


@pytest.fixture()
def T(monkeypatch, clock):
    t = FakeTime(clock)
    monkeypatch.setattr(headless, "clock", t.read)
    monkeypatch.setattr(headless, "sleep", t.sleep)
    return t


@pytest.fixture(autouse=True)
def one_task_per_unit(monkeypatch):
    monkeypatch.setenv("CPLAT_PARALLEL_TASKS", "1")
    monkeypatch.delenv("CPLAT_SLOT", raising=False)


def unix(local: dt.datetime) -> int:
    return int(time.mktime(local.timetuple()))


def limit_message(reset: dt.datetime) -> str:
    return f"Claude AI usage limit reached|{unix(reset)}\n"


WRAPPER = r'''#!%(py)s
%(prelude)s
import json, os, pathlib, sys
W = pathlib.Path(%(world)r)
unit = os.environ.get("CPLAT_UNIT", "")
cfg = json.loads((W / "limits.json").read_text())
f = W / "limit-counts.json"
counts = json.loads(f.read_text()) if f.is_file() else {}
n = counts.get(unit, 0)
counts[unit] = n + 1
f.write_text(json.dumps(counts))
seq = cfg.get(unit) or []
limited = n < len(seq) and seq[n] is not None
with (W / "all-sessions.jsonl").open("a") as fh:
    fh.write(json.dumps({"unit": unit, "limited": limited}) + "\n")
if limited:
    sys.stdout.write(seq[n])
    sys.exit(0)
os.execv(%(real)r, [%(real)r] + sys.argv[1:])
'''


class Limited:
    """A units world whose `claude` answers the n-th session of a unit with a message (a string; "" is silence) or runs the real fake (None)."""

    def __init__(self, world: World):
        self.w = world
        real = world.dir / "claude-real"
        (world.dir / "claude").rename(real)
        exe = world.dir / "claude"
        exe.write_text(WRAPPER % {"py": sys.executable, "prelude": fake_prelude(), "world": str(world.dir), "real": str(real)})
        exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
        self.set({})

    def set(self, mapping):
        (self.w.dir / "limits.json").write_text(json.dumps(mapping))

    def sessions(self):
        f = self.w.dir / "all-sessions.jsonl"
        return [json.loads(ln) for ln in f.read_text().splitlines()] if f.is_file() else []

    def units(self):
        return [s["unit"] for s in self.sessions()]


@pytest.fixture()
def lw(tmp_path, monkeypatch, T):
    return Limited(World(tmp_path, monkeypatch, plan=True))      # units: red-tests, task:t1..t3, verification, land


FULL = ["red-tests", "task:t1", "task:t2", "task:t3", "verification", "land"]


def lines_of(capsys):
    return capsys.readouterr().out.splitlines()


def invocations():
    (data,) = [json.loads(p.read_text()) for p in (runs.state_dir() / "budgets").glob("*.json")]
    return data["carried"].get("invocations", 0) + data["used"].get("invocations", 0)


# ---------------- AC-184.1: unit mode ----------------

def test_a_reset_time_pauses_the_unit_until_one_minute_after_it_and_starts_the_same_unit_again_ac_184_1(lw, T, capsys):  # AC-184.1
    reset = NOW + dt.timedelta(hours=4)
    lw.set({"task:t2": [limit_message(reset)]})
    T.count = lambda: len(lw.sessions())
    assert lw.w.run() == 0
    lines = lines_of(capsys)
    assert "paused: usage limit, resumes at 2026-11-11 14:01" in lines
    assert T.sleeps == [4 * 3600 + 60] and T.now >= reset + dt.timedelta(minutes=1)
    assert T.log == [(3, reset + dt.timedelta(minutes=1))]          # 3 sessions had started; the next one only after reset + 1 minute
    assert lw.units() == ["red-tests", "task:t1", "task:t2", "task:t2", "task:t3", "verification", "land"]
    assert lw.w.units_run() == FULL                                  # the real work is the same as without the pause
    assert not any("escalat" in ln or "needs you" in ln for ln in lines)
    assert any(ln.startswith(f"HEADLESS shop-api: shipped {SPEC_ID}") for ln in lines)


def test_the_paused_session_is_no_invocation_ac_184_3(lw, T):  # AC-184.3
    lw.set({"task:t2": [limit_message(NOW + dt.timedelta(hours=1))]})
    assert lw.w.run() == 0
    assert len(lw.sessions()) == 7 and invocations() == 6


def test_the_pause_is_not_counted_against_the_minutes_of_the_budget_or_of_max_minutes_ac_184_3(lw, T):  # AC-184.3
    lw.set({"task:t2": [limit_message(NOW + dt.timedelta(hours=4))]})
    assert lw.w.run("--budget", "minutes=60", "--max-minutes", "60") == 0
    assert T.sleeps == [4 * 3600 + 60]                               # four hours passed in a 60 minute run
    assert lw.w.units_run() == FULL


# ---------------- AC-184.2: unit mode ----------------

def test_silent_sessions_pause_5_then_10_minutes_and_the_run_goes_on_ac_184_2(lw, T, capsys):  # AC-184.2
    lw.set({"task:t2": ["", ""]})
    assert lw.w.run() == 0
    lines = lines_of(capsys)
    assert "paused: usage limit, next try at 2026-11-11 10:05" in lines
    assert "paused: usage limit, next try at 2026-11-11 10:15" in lines
    assert T.sleeps == [300, 600]
    assert lw.w.units_run() == FULL


def test_the_limit_message_without_a_time_pauses_5_minutes_ac_184_2(lw, T, capsys):  # AC-184.2
    lw.set({"task:t1": ["Claude usage limit reached. Try again later.\n"]})
    assert lw.w.run() == 0
    assert "paused: usage limit, next try at 2026-11-11 10:05" in lines_of(capsys)
    assert T.sleeps == [300]


def test_pauses_beyond_360_minutes_stop_the_run_as_an_environment_pause_and_the_same_command_continues_ac_184_2(lw, T, store, capsys):  # AC-184.2
    lw.set({"task:t2": [""] * 12})
    assert lw.w.run() == 1
    assert T.sleeps == [m * 60 for m in (5, 10, 20, 40, 60, 60, 60, 60)]        # 315 minutes; one more would pass 360
    stop = "environment pause: usage limit resets at unknown"
    out = lines_of(capsys)
    assert f"HEADLESS shop-api: {stop}" in out
    assert lw.units().count("task:t2") == 9 and "task:t3" not in lw.units()      # no session after the stop
    rec = [r for r in stored(store) if r["kind"] == "headless"][-1]
    assert rec["outcome"] == "escalated" and {k: rec["escalation"].get(k) for k in ("reason", "cause")} == {"reason": stop, "cause": "environment"}
    assert not ship.load_state(lw.w.repo).get("escalated")                       # the ship is not escalated
    assert not (lw.w.units_file() or {}).get("escalated")
    lw.set({})                                                                   # the limit is over: the same command goes on
    assert lw.w.run() == 0
    assert lw.w.units_run() == FULL
    assert any(ln.startswith(f"HEADLESS shop-api: shipped {SPEC_ID}") for ln in lines_of(capsys))


def test_a_reset_time_beyond_the_cap_stops_at_once_naming_the_reset_ac_184_2(lw, T, capsys):  # AC-184.2
    lw.set({"task:t2": [limit_message(NOW + dt.timedelta(hours=7))]})
    assert lw.w.run() == 1
    assert T.sleeps == []
    assert "HEADLESS shop-api: environment pause: usage limit resets at 2026-11-11 17:00" in lines_of(capsys)
    assert lw.units() == ["red-tests", "task:t1", "task:t2"]


# ---------------- AC-184.3: unit mode ----------------

def test_two_empty_sessions_then_a_checkpoint_continue_to_the_next_unit_without_a_stall_ac_184_3(lw, T, capsys):  # AC-184.3
    lw.set({"task:t2": ["", ""]})
    assert lw.w.run() == 0
    out = "\n".join(lines_of(capsys))
    assert "no progress" not in out and "needs you" not in out
    assert lw.units() == ["red-tests", "task:t1", "task:t2", "task:t2", "task:t2", "task:t3", "verification", "land"]
    assert invocations() == 6


def test_a_pause_after_a_stall_adds_none_and_the_checkpoint_after_it_resets_the_count_ac_184_3(lw, T, capsys):  # AC-184.3
    lw.w.behave({"task:t2": ["say-approval", "ok"]})                             # session 1: text, no commit (a real stall)
    lw.set({"task:t2": [None, limit_message(NOW + dt.timedelta(hours=1))]})      # session 2: the limit; session 3: the work
    assert lw.w.run() == 0
    assert "no progress" not in "\n".join(lines_of(capsys))
    assert lw.units().count("task:t2") == 3 and lw.w.units_run() == ["red-tests", "task:t1", "task:t2", "task:t2", "task:t3", "verification", "land"]


# ---------------- legacy loop ----------------

def legacy_script(steps):
    """A bash `claude` that does `steps[n]` for its n-th session: a message to print, "done", "land", or None (nothing, silently)."""
    cases = []
    for n, step in enumerate(steps, 1):
        if step == "done":
            body = "sed -i.bak 's/\"phase\": \"[a-z]*\"/\"phase\": \"done\"/' \"$f\""
        elif step == "land":
            body = "sed -i.bak 's/\"phase\": \"[a-z]*\"/\"phase\": \"land\"/' \"$f\""
        elif step is None:
            body = "true"
        else:
            body = f"printf '%s\\n' '{step.strip()}'"
        cases.append(f'if [ "$n" -eq {n} ]; then {body}; fi')
    return 'n=$(wc -l < runs.txt)\nf=$(git rev-parse --git-common-dir)/cplat-ship.json\n' + "\n".join(cases)


def test_the_legacy_loop_pauses_and_starts_the_same_prompt_again_ac_184_1(legacy_repo, tmp_path, monkeypatch, T, store, capsys):  # AC-184.1
    reset = NOW + dt.timedelta(hours=2)
    ship.start(legacy_repo, "7", True)
    fake_claude(tmp_path, monkeypatch, legacy_script([limit_message(reset), "done"]))
    T.count = lambda: legacy_runs(legacy_repo)
    assert headless.main(["/svc:ship 7", "--repo", str(legacy_repo), "--max-runs", "1"]) == 0   # the paused session is no run
    lines = lines_of(capsys)
    assert "paused: usage limit, resumes at 2026-11-11 12:01" in lines
    assert T.sleeps == [2 * 3600 + 60] and legacy_runs(legacy_repo) == 2
    assert T.log == [(1, reset + dt.timedelta(minutes=1))]          # one session had started; the second only after reset + 1 minute
    assert any(ln.startswith("HEADLESS shop-api: shipped 007-price-alerts") for ln in lines)
    assert invocations() == 1                                                    # AC-184.3


def test_a_paused_session_does_not_count_as_no_progress_in_the_legacy_loop_ac_184_3(legacy_repo, tmp_path, monkeypatch, T, capsys):  # AC-184.3
    ship.start(legacy_repo, "7", True)
    fake_claude(tmp_path, monkeypatch, legacy_script(["land", limit_message(NOW + dt.timedelta(hours=1)), "done"]))
    assert headless.main(["/svc:ship 7", "--repo", str(legacy_repo)]) == 0
    out = "\n".join(lines_of(capsys))
    assert "no progress" not in out and legacy_runs(legacy_repo) == 3


def test_a_silent_session_pauses_the_legacy_loop_for_5_minutes_ac_184_2(legacy_repo, tmp_path, monkeypatch, T, capsys):  # AC-184.2
    ship.start(legacy_repo, "7", True)
    fake_claude(tmp_path, monkeypatch, legacy_script([None, "done"]))
    assert headless.main(["/svc:ship 7", "--repo", str(legacy_repo)]) == 0
    assert "paused: usage limit, next try at 2026-11-11 10:05" in lines_of(capsys)
    assert T.sleeps == [300]


def test_the_legacy_pause_is_no_time_of_max_minutes_or_the_budget_ac_184_3(legacy_repo, tmp_path, monkeypatch, T, capsys):  # AC-184.3
    ship.start(legacy_repo, "7", True)
    fake_claude(tmp_path, monkeypatch, legacy_script([limit_message(NOW + dt.timedelta(hours=4)), "done"]))
    assert headless.main(["/svc:ship 7", "--repo", str(legacy_repo), "--max-minutes", "60", "--budget", "minutes=60"]) == 0
    assert "time budget" not in "\n".join(lines_of(capsys))
    assert T.sleeps == [4 * 3600 + 60] and legacy_runs(legacy_repo) == 2


def test_the_legacy_loop_stops_as_an_environment_pause_beyond_the_cap_ac_184_2(legacy_repo, tmp_path, monkeypatch, T, store, capsys):  # AC-184.2
    result_file = tmp_path / "dispatch-result.json"
    monkeypatch.setenv("CPLAT_DISPATCH_RESULT", str(result_file))
    monkeypatch.setenv("CPLAT_DISPATCH_UNIT", "issue-9.1")
    ship.start(legacy_repo, "7", True)
    fake_claude(tmp_path, monkeypatch, legacy_script([limit_message(NOW + dt.timedelta(hours=7)), "done"]))
    assert headless.main(["/svc:ship 7", "--repo", str(legacy_repo)]) == 1
    stop = "environment pause: usage limit resets at 2026-11-11 17:00"
    assert f"HEADLESS shop-api: {stop}" in lines_of(capsys)
    assert T.sleeps == [] and legacy_runs(legacy_repo) == 1
    rec = [r for r in stored(store) if r["kind"] == "headless"][-1]
    assert rec["outcome"] == "escalated" and {k: rec["escalation"].get(k) for k in ("reason", "cause")} == {"reason": stop, "cause": "environment"}
    done = json.loads(result_file.read_text())
    assert done["cause"] == "environment" and done["stop_reason"] == "escalated" and done["result"] == stop
    assert not ship.load_state(legacy_repo).get("escalated")
    assert headless.main(["/svc:ship 7", "--repo", str(legacy_repo)]) == 0         # the same command continues
