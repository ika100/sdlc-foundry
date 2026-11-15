"""Spec 203 acceptance tests: `cplat next` always returns and never waits for input (AC-203.5, AC-203.6).

Seams (design.md): `nextstate.SOURCE_SECONDS` / `TOTAL_SECONDS` (lowered here), `nextcmd.hard_exit` (replaced: the real one ends
the process), the sources of spec 192 faked in `support_192.World`. A source that "does not answer" is a faked call that waits for
`HANG` seconds (released at teardown). The input test runs the real `cplat next` as a process with a fake `gh` that reads its
standard input, and an open terminal on `cplat`'s own input that nobody types into.
"""
import json
import os
import pty
import signal
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import core
from support_192 import World

HANG = 5
SOURCE, TOTAL = 1, 2
LIMIT = 4          # seconds `cplat next` may take with the lowered deadlines (HANG is longer)


@pytest.fixture
def world(tmp_path, monkeypatch):
    return World(tmp_path, monkeypatch)


@pytest.fixture(autouse=True)
def isolated_process_state(monkeypatch):
    """`cplat next` points fd 0 at /dev/null and sets prompt variables in this process: restore both after each test."""
    for name in ("GIT_TERMINAL_PROMPT", "GH_PROMPT_DISABLED", "GIT_SSH_COMMAND"):
        monkeypatch.setenv(name, "x")          # registers the variable with monkeypatch: undone at teardown
        monkeypatch.delenv(name)
    saved = os.dup(0)
    yield
    os.dup2(saved, 0)
    os.close(saved)


@pytest.fixture
def gate():
    event = threading.Event()
    yield event
    event.set()


@pytest.fixture
def exits(monkeypatch):
    """`nextcmd.hard_exit` replaced; the codes it was asked to end the process with."""
    import nextcmd
    calls = []
    monkeypatch.setattr(nextcmd, "hard_exit", lambda c: calls.append(c) or c, raising=False)     # the seam may not exist yet: the test then fails below
    return calls


@pytest.fixture
def short(monkeypatch):
    import nextstate
    monkeypatch.setattr(nextstate, "SOURCE_SECONDS", SOURCE, raising=False)
    monkeypatch.setattr(nextstate, "TOTAL_SECONDS", TOTAL, raising=False)
    return nextstate


def test_the_limits_are_20_seconds_per_source_and_60_in_total_ac_203_5():  # AC-203.5
    import nextcmd
    import nextstate
    assert (nextstate.SOURCE_SECONDS, nextstate.TOTAL_SECONDS) == (20, 60)
    assert callable(nextcmd.hard_exit)


def silent(monkeypatch, gate, module, name):
    """`module.name` waits for HANG seconds (or the teardown), then returns a fixed value: an abandoned thread never calls the real source."""
    getattr(module, name)

    def slow(*a, **k):
        gate.wait(HANG)
        return None
    monkeypatch.setattr(module, name, slow)


def hang_github(monkeypatch, gate, world):
    import needs
    silent(monkeypatch, gate, needs, "gh")


def hang_runs(monkeypatch, gate, world):
    import runlist
    silent(monkeypatch, gate, runlist, "collect")


def hang_dispatcher(monkeypatch, gate, world):
    import dispatch_view
    silent(monkeypatch, gate, dispatch_view, "status_doc")


def hang_notifications(monkeypatch, gate, world):
    import notify_config
    silent(monkeypatch, gate, notify_config, "load")


def hang_state_files(monkeypatch, gate, world):
    import notify
    silent(monkeypatch, gate, notify, "load_state")


SILENT = [(hang_github, "github", {"approve", "answer", "triage"}), (hang_runs, "runs", {"escalation"}),
          (hang_dispatcher, "dispatcher", {"budget", "stuck"}), (hang_notifications, "notifications", set()),
          (hang_state_files, "notifications", set())]


def timed(world, capsys, *args):
    began = time.monotonic()
    rc, out = world.next(capsys, *args)
    return rc, out, time.monotonic() - began


# ---------------- AC-203.5: a source without an answer is abandoned and named ----------------

@pytest.mark.parametrize("hang,source,kinds", SILENT, ids=[f"{h.__name__}" for h, _, _ in SILENT])
def test_next_json_returns_within_the_deadline_and_lists_the_silent_source_ac_203_5(world, capsys, monkeypatch, gate, short, exits, hang, source, kinds):  # AC-203.5
    world.running("189-x", "build")
    hang(monkeypatch, gate, world)
    rc, out, elapsed = timed(world, capsys, "--json")
    assert rc == 0 and elapsed < LIMIT, f"{elapsed:.1f} s"
    doc = json.loads(out)
    named = [u for u in doc["unavailable"] if u["source"] == source]
    assert named and named[0]["error"] == f"no answer within {SOURCE} s"
    assert kinds <= set(named[0]["kinds"])
    assert "Nothing is waiting" not in doc["screen"]
    assert doc["questions"][-1]["options"][0]["label"] == "Try again"
    assert exits == [0]                                                         # the abandoned call may not hold the process


@pytest.mark.parametrize("hang", [h for h, _, _ in SILENT], ids=[h.__name__ for h, _, _ in SILENT])
def test_the_screen_names_the_silent_source_and_exits_zero_ac_203_5(world, capsys, monkeypatch, gate, short, exits, hang):  # AC-203.5
    world.running("189-x", "build")
    hang(monkeypatch, gate, world)
    rc, out, elapsed = timed(world, capsys)
    assert rc == 0 and elapsed < LIMIT, f"{elapsed:.1f} s"
    assert "Nothing is waiting" not in out and "Could not read" in out and "may be missing" in out


def test_the_sources_that_answered_are_shown_as_usual_ac_203_5(world, capsys, monkeypatch, gate, short, exits):  # AC-203.5
    world.running("189-x", "build")
    hang_github(monkeypatch, gate, world)
    rc, out, elapsed = timed(world, capsys, "--json")
    doc = json.loads(out)
    assert elapsed < LIMIT and [u["source"] for u in doc["unavailable"]] == ["github"]
    assert len(doc["running"]) == 1                                             # the run rows came from the runs source


def test_a_silent_dispatcher_leaves_the_run_rows_ac_203_5(world, capsys, monkeypatch, gate, short, exits):  # AC-203.5
    world.running("189-x", "build")
    hang_dispatcher(monkeypatch, gate, world)
    rc, out, elapsed = timed(world, capsys, "--json")
    doc = json.loads(out)
    assert elapsed < LIMIT and "dispatcher" in [u["source"] for u in doc["unavailable"]]
    assert len(doc["running"]) == 1


def test_every_source_silent_at_once_still_returns_within_the_total_ac_203_5(world, capsys, monkeypatch, gate, short, exits):  # AC-203.5
    for hang, _, _ in SILENT:
        hang(monkeypatch, gate, world)
    rc, out, elapsed = timed(world, capsys, "--json")
    assert rc == 0 and elapsed < LIMIT, f"{elapsed:.1f} s"
    assert {"github", "runs", "dispatcher", "notifications"} <= {u["source"] for u in json.loads(out)["unavailable"]}
    assert exits == [0]


def test_a_state_lock_another_process_holds_does_not_hold_next_ac_203_5(world, capsys, monkeypatch, gate, short, exits):  # AC-203.5
    import dispatch_view
    import runs
    held, release = threading.Event(), threading.Event()

    def waits_for_the_lock(*a, **k):                                            # the dispatcher source takes the state lock
        with runs._locked():
            return None
    monkeypatch.setattr(dispatch_view, "status_doc", waits_for_the_lock)

    def holder():
        with runs._locked():
            held.set()
            release.wait(HANG)
    thread = threading.Thread(target=holder, daemon=True)
    thread.start()
    assert held.wait(5)
    try:
        rc, out, elapsed = timed(world, capsys, "--json")
    finally:
        release.set()
    assert rc == 0 and elapsed < LIMIT, f"{elapsed:.1f} s"
    assert "dispatcher" in [u["source"] for u in json.loads(out)["unavailable"]]


def test_a_run_whose_sources_all_answer_ends_the_ordinary_way_ac_203_5(world, capsys, monkeypatch, short, exits):  # AC-203.5
    rc, out, _ = timed(world, capsys, "--json")
    assert rc == 0 and json.loads(out)["unavailable"] == []
    assert exits == []                                                          # no abandoned call, no hard exit


# ---------------- AC-203.6: no input, no prompts ----------------

def test_next_points_its_input_at_devnull_and_turns_prompts_off_ac_203_6(world, capsys, monkeypatch, exits):  # AC-203.6
    pipe_r, pipe_w = os.pipe()
    saved = os.dup(0)
    os.dup2(pipe_r, 0)                                                          # an open input nobody writes to
    try:
        rc, out = world.next(capsys, "--json")
        info, null = os.fstat(0), os.stat(os.devnull)
        on_devnull = stat.S_ISCHR(info.st_mode) and info.st_rdev == null.st_rdev
    finally:
        os.dup2(saved, 0)
        for fd in (saved, pipe_r, pipe_w):
            os.close(fd)
    assert rc == 0
    assert on_devnull
    assert os.environ["GIT_TERMINAL_PROMPT"] == "0" and os.environ["GH_PROMPT_DISABLED"] == "1"
    assert "BatchMode=yes" in os.environ["GIT_SSH_COMMAND"]


def test_next_keeps_an_ssh_command_the_person_set_ac_203_6(world, capsys, monkeypatch, exits):  # AC-203.6
    monkeypatch.setenv("GIT_SSH_COMMAND", "ssh -i /my/key")
    monkeypatch.setenv("GIT_TERMINAL_PROMPT", "1")
    assert world.next(capsys, "--json")[0] == 0
    assert os.environ["GIT_SSH_COMMAND"] == "ssh -i /my/key"
    assert os.environ["GIT_TERMINAL_PROMPT"] == "0"


READING_GH = """#!/bin/sh
# a `gh` that waits for a person: it reads its input before it answers
read -r _line
echo '[]'
"""


def test_a_program_that_reads_its_input_does_not_hold_next_ac_203_6(tmp_path):  # AC-203.6
    """The real `cplat next` as a process, an open terminal on its input, and a `gh` that reads its input."""
    repo = tmp_path / "repo"
    repo.mkdir()
    for cmd in (["init", "-q"], ["remote", "add", "origin", "https://github.com/o/n.git"]):
        subprocess.run(["git", "-C", str(repo), *cmd], check=True, capture_output=True)
    (repo / ".platform-settings.yml").write_text("shape: platform\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(READING_GH)
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "HOME": str(tmp_path / "home"),
           "XDG_STATE_HOME": str(tmp_path / "state"), "XDG_CONFIG_HOME": str(tmp_path / "config"),
           "XDG_CACHE_HOME": str(tmp_path / "cache"), "LANG": "en_US.UTF-8"}
    for name in ("CPLAT_RUNS_REPO", "CPLAT_HEADLESS", "GIT_TERMINAL_PROMPT", "GH_PROMPT_DISABLED"):
        env.pop(name, None)
    cplat = Path(core.PLATFORM_ROOT) / "scripts" / "cplat" / "cplat.py"
    master, slave = pty.openpty()
    proc = subprocess.Popen([sys.executable, str(cplat), "next", "--json", "--repo-dir", str(repo)], stdin=slave,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, start_new_session=True, text=True)
    os.close(slave)
    try:
        out, err = proc.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        pytest.fail("cplat next waited for input from a program it called (no answer within 30 s)")
    finally:
        os.close(master)
    assert proc.returncode == 0, err
    assert json.loads(out)["schema"] == 1
