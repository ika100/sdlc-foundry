"""Spec 185 acceptance tests: `cplat quiet test-fast` gives up after 9 minutes and names what still runs (AC-185.4, AC-185.5).

Seam: `quiet.main(argv)` with a fake `devbox` on PATH and `quiet_limit.GIVE_UP_SECONDS` lowered to 1 s plus 20 times the fake delay. The fake copies the files
`progress` (or `progress-<i>` of a `--repeat` run) into the progress file quiet names in $PYTEST_PROGRESS_FILE (design.md,
"quiet gives up"), prints `out` when present, then hangs with a child of its own, unless the file `quick` holds an exit code.
"""
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

import json

import quiet
from test_172_quiet import pytest_out
from waiting import DELAY, fake_prelude, wait_file, wait_gone

ROOT = Path(__file__).resolve().parents[2]
GAVE_UP = "FAILED (gave up after 9 min): devbox run test-fast (log: "

FAKE_DEVBOX = """#!/bin/sh
d="$FAKE_DIR"
: > "$d/calls-$$"
env > "$d/env-$$"
run="${CPLAT_REPEAT_RUN:-0}"
p="$d/progress"
[ -f "$d/progress-$run" ] && p="$d/progress-$run"
if [ -n "$PYTEST_PROGRESS_FILE" ] && [ -f "$p" ]; then cp "$p" "$PYTEST_PROGRESS_FILE"; fi
[ -f "$d/out" ] && cat "$d/out"
if [ -f "$d/quick" ]; then echo "1 passed"; exit "$(cat "$d/quick")"; fi
echo "$$" > "$d/pid-$run"
sleep 600 &  # fake-delay: a hung test run, stopped by quiet
echo "$!" > "$d/child-$run"
wait
"""


class World:
    def __init__(self, d, cache):
        self.d, self.cache = d, cache

    def put(self, name, text):
        (self.d / name).write_text(text)

    def logs(self):
        return sorted((self.cache / "sdlc-foundry" / "logs" / "myrepo").glob("*"))

    def calls(self):
        return [p for p in self.d.iterdir() if p.name.startswith("calls-")]

    def progress(self, *tests, ended=()):
        lines = ["# cplat test progress"]
        for t in tests:
            lines.append(f"start {t}")
            if t in ended:
                lines.append(f"end {t}")
        return "\n".join(lines) + "\n"


@pytest.fixture()
def world(tmp_path, monkeypatch):
    import quiet_limit
    import runs
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "devbox"
    fake.write_text(FAKE_DEVBOX.replace("\n", "\n" + fake_prelude("sh") + "\n", 1))
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    work = tmp_path / "myrepo"
    work.mkdir()
    (work / "devbox.json").write_text(json.dumps({"shell": {"scripts": {"test-fast": "x", "quality": "y"}}}))
    d = tmp_path / "fake"
    d.mkdir()
    monkeypatch.chdir(work)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("FAKE_DIR", str(d))
    monkeypatch.delenv("CPLAT_REPEAT_RUN", raising=False)
    monkeypatch.setattr(runs, "current_run", lambda r: "run-1")
    monkeypatch.setattr(runs, "add_to", lambda rid, name, item, **k: None)
    # The fake first sleeps TEST_FAKE_DELAY (its prelude), so the limit grows with it, as `waiting.budget()` does: 1 s + 20 * delay.
    # quiet runs in this process under the sleep guard (spec 185, AC-185.3) with a deadline of about 1 s: `quiet_limit` must wait
    # with Popen.wait(timeout=) or an event, never with a repo-code time.sleep, or the guard fails these tests (design.md).
    monkeypatch.setattr(quiet_limit, "GIVE_UP_SECONDS", 1 + 20 * DELAY)
    return World(d, tmp_path / "cache")


def lines_of(capsys):
    return capsys.readouterr().out.splitlines()


# ---------------- AC-185.4: pytest runs ----------------

def test_the_limit_is_nine_minutes_ac_185_4():  # AC-185.4
    import quiet_limit
    assert quiet_limit.GIVE_UP_SECONDS == 540 and quiet_limit.GIVE_UP_LABEL == "9 min"
    assert quiet_limit.MAX_LISTED == 20


def test_a_run_over_the_limit_prints_the_block_and_exits_124_ac_185_4(world, capsys):  # AC-185.4
    world.put("progress", world.progress("t/a.py::one", "t/a.py::two", "t/b.py::three", ended={"t/a.py::one"}))
    assert quiet.main(["test-fast"]) == 124
    (log,) = [p for p in world.logs() if p.name.endswith("-test-fast.log")]
    assert lines_of(capsys) == [GAVE_UP + f"{log})", "still running: t/a.py::two", "still running: t/b.py::three"]


def test_arguments_reach_the_run_that_gives_up_ac_185_4(world, capsys):  # AC-185.4
    world.put("progress", world.progress("t/a.py::one"))
    assert quiet.main(["test-fast", "--", "t/a.py"]) == 124
    out = lines_of(capsys)
    assert out[0].startswith(GAVE_UP) and out[1:] == ["still running: t/a.py::one"]


def test_at_most_twenty_tests_are_listed_then_the_rest_is_counted_ac_185_4(world, capsys):  # AC-185.4
    names = [f"t/a.py::t{i:02d}" for i in range(25)]
    world.put("progress", world.progress(*names))
    assert quiet.main(["test-fast"]) == 124
    out = lines_of(capsys)
    assert out[1:] == [f"still running: {n}" for n in names[:20]] + ["... and 5 more"]


def test_exactly_twenty_tests_have_no_more_line_ac_185_4(world, capsys):  # AC-185.4
    names = [f"t/a.py::t{i:02d}" for i in range(20)]
    world.put("progress", world.progress(*names))
    assert quiet.main(["test-fast"]) == 124
    assert lines_of(capsys)[1:] == [f"still running: {n}" for n in names]


def test_quiet_stops_the_run_and_every_process_it_started_ac_185_4(world):  # AC-185.4
    world.put("progress", world.progress("t/a.py::one"))
    assert quiet.main(["test-fast"]) == 124
    pid = int(wait_file(world.d / "pid-0").strip())
    child = int(wait_file(world.d / "child-0").strip())
    wait_gone(pid)
    wait_gone(child)


def test_the_flaky_rerun_does_not_happen_and_no_summary_is_written_ac_185_4(world):  # AC-185.4
    world.put("progress", world.progress("tests/test_x.py::test_a"))
    world.put("out", pytest_out("test_a"))
    assert quiet.main(["test-fast"]) == 124
    assert len(world.calls()) == 1
    assert [p for p in world.logs() if p.name.endswith(".summary.json")] == []
    assert [p for p in world.logs() if "rerun" in p.name] == []


def test_every_repeat_run_shares_one_deadline_and_prints_its_own_block_ac_185_4(world, capsys):  # AC-185.4
    world.put("progress-1", world.progress("t/a.py::first"))
    world.put("progress-2", world.progress("t/a.py::second"))
    assert quiet.main(["test-fast", "--repeat", "2", "--", "t/a.py"]) == 124
    out = lines_of(capsys)
    assert len([ln for ln in out if ln.startswith(GAVE_UP)]) == 2, out
    assert "still running: t/a.py::first" in out and "still running: t/a.py::second" in out
    assert len(world.calls()) == 2, "a test ran again alone"
    for run in ("1", "2"):
        wait_gone(int(wait_file(world.d / f"pid-{run}").strip()))


def test_quiet_names_the_progress_plugin_and_file_to_the_run_ac_185_4(world):  # AC-185.4
    world.put("progress", world.progress("t/a.py::one"))
    assert quiet.main(["test-fast"]) == 124
    (env_file,) = [p for p in world.d.iterdir() if p.name.startswith("env-")]
    env = dict(ln.split("=", 1) for ln in env_file.read_text().splitlines() if "=" in ln)
    import quiet_limit
    assert str(quiet_limit.PLUGIN_DIR) in env["PYTHONPATH"].split(os.pathsep)
    assert "-p cplat_test_progress" in env["PYTEST_ADDOPTS"]
    assert env["PYTEST_PROGRESS_FILE"].endswith(".progress")


def test_a_run_that_ends_in_time_prints_and_exits_as_before_ac_185_4(world, capsys):  # AC-185.4
    import quiet_limit
    quiet_limit.GIVE_UP_SECONDS = 30            # restored by the fixture's monkeypatch
    world.put("quick", "0")
    assert quiet.main(["test-fast"]) == 0
    out = lines_of(capsys)
    assert out[0].startswith("ok: devbox run test-fast (") and out[-1] == "1 passed"


def test_a_failing_run_that_ends_in_time_still_exits_with_its_code_ac_185_4(world, capsys):  # AC-185.4
    import quiet_limit
    quiet_limit.GIVE_UP_SECONDS = 30
    world.put("quick", "1")
    assert quiet.main(["test-fast"]) == 1
    assert capsys.readouterr().out.startswith("FAILED (exit 1): devbox run test-fast")


def test_the_progress_plugin_writes_start_and_end_lines_and_hides_its_file_ac_185_4(tmp_path):  # AC-185.4
    import quiet_limit
    env_add, progress = quiet_limit.progress_env(tmp_path / "x.log")
    (tmp_path / "test_p.py").write_text(
        "import os\n\ndef test_one():\n    assert True\n\n"
        "def test_two():\n    assert 'PYTEST_PROGRESS_FILE' not in os.environ\n")
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_ADDOPTS"}
    env.update(env_add)
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
    assert progress.read_text().splitlines() == ["# cplat test progress", "start test_p.py::test_one", "end test_p.py::test_one",
                                                  "start test_p.py::test_two", "end test_p.py::test_two"]
    assert quiet_limit.still_running(progress) == []


def test_under_xdist_only_the_controller_writes_each_start_and_end_once_ac_185_4(tmp_path):  # AC-185.4
    import quiet_limit
    env_add, progress = quiet_limit.progress_env(tmp_path / "x.log")
    (tmp_path / "test_p.py").write_text("".join(f"def test_{i}():\n    assert True\n\n" for i in range(6)))
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_ADDOPTS"}
    env.update(env_add)
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-n", "2", "-p", "no:cacheprovider"], cwd=tmp_path, env=env,
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
    lines = progress.read_text().splitlines()
    assert lines[0] == "# cplat test progress"
    for i in range(6):
        node = f"test_p.py::test_{i}"
        assert lines.count(f"start {node}") == 1 and lines.count(f"end {node}") == 1, lines
        assert lines.index(f"start {node}") < lines.index(f"end {node}")
    assert len(lines) == 1 + 12, lines
    assert quiet_limit.still_running(progress) == []


def test_still_running_is_none_without_a_progress_file_ac_185_4(tmp_path):  # AC-185.4
    import quiet_limit
    assert quiet_limit.still_running(tmp_path / "missing.progress") is None
    f = tmp_path / "p.progress"
    f.write_text("# cplat test progress\nstart a::1\nstart a::2\nend a::1\n")
    assert quiet_limit.still_running(f) == ["a::2"]


# ---------------- AC-185.5: a test runner that is not pytest ----------------

def test_a_run_without_a_progress_file_gives_up_with_the_unreported_line_ac_185_5(world, capsys):  # AC-185.5
    assert quiet.main(["test-fast"]) == 124
    (log,) = [p for p in world.logs() if p.name.endswith("-test-fast.log")]
    assert lines_of(capsys) == [GAVE_UP + f"{log})", "still running: not reported by this test runner"]


def test_a_run_without_a_progress_file_is_stopped_with_its_processes_ac_185_5(world):  # AC-185.5
    assert quiet.main(["test-fast"]) == 124
    wait_gone(int(wait_file(world.d / "pid-0").strip()))
    wait_gone(int(wait_file(world.d / "child-0").strip()))
    assert len(world.calls()) == 1
