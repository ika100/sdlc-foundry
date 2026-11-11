"""Spec 178 acceptance tests: tests that do not race (AC-178.5, AC-178.6).

`scripts/check-test-sleeps.py` is run as a process on a temporary tree (`--root`) and on the real one; `tests/cplat/waiting.py`, the
helper tests wait through, is tested for its API and for `TEST_FAKE_DELAY`. Nothing here waits by a fixed sleep: a test waits for a
process with `subprocess.run`/`communicate` and a timeout, or for a file the helper polls for.
"""
import importlib
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "scripts" / "check-test-sleeps.py"
HINT = ('waits a fixed time: wait for an event or a file (waiting.wait_for, waiting.wait_file) or use the fake clock; '
        'a fake program marks its delay "fake-delay: <reason>"')
TIMEOUT = 120


def tree(tmp_path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        f = tmp_path / "tests" / "cplat" / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(textwrap.dedent(text).lstrip("\n"))
    return tmp_path


def check(root: Path, *extra: str):
    res = subprocess.run([sys.executable, str(CHECK), "--root", str(root), *extra], capture_output=True, text=True, timeout=TIMEOUT)
    return res.returncode, res.stdout.splitlines(), res.stderr


def occurrences(lines: list[str]) -> list[tuple[str, int, str]]:
    """(file, line, the rest) of every `tests/cplat/<file>.py:<line>: ...` line."""
    out = []
    for ln in lines:
        head, _, rest = ln.partition(": ")
        path, _, number = head.rpartition(":")
        if path.startswith("tests/cplat/") and number.isdigit():
            out.append((path, int(number), rest))
    return out


# ---------------- AC-178.6: the check ----------------

@pytest.mark.parametrize("name, source, line", [
    ("time", "import time\n\n\ndef test_x():\n    time.sleep(0.5)\n", 5),
    ("asyncio", "import asyncio\n\n\nasync def test_x():\n    await asyncio.sleep(1)\n", 5),
    ("from_time", "from time import sleep\n\n\ndef test_x():\n    sleep(2)\n", 5),
    ("from_asyncio", "from asyncio import sleep\n\n\nasync def test_x():\n    await sleep(2)\n", 5),
    ("aliased", "import time as t\n\n\ndef test_x():\n    t.sleep(2)\n", 5),
], ids=["time", "asyncio", "from-time", "from-asyncio", "aliased"])
def test_a_real_sleep_in_a_test_is_one_line_naming_file_line_and_fix(tmp_path, name, source, line):  # AC-178.6
    root = tree(tmp_path, {f"test_{name}.py": source})
    code, out, _ = check(root)
    assert code == 1, out
    [(path, number, rest)] = occurrences(out)
    assert (path, number) == (f"tests/cplat/test_{name}.py", line)
    assert "sleep" in rest.split(HINT)[0] and rest.endswith(HINT), rest
    assert out[-1] == "check-test-sleeps: 1 fixed sleep(s) in tests/cplat"
    assert len(out) == 2                                              # one line per occurrence, then the count


def test_every_occurrence_has_its_own_line_in_every_file_below_tests_cplat(tmp_path):  # AC-178.6
    root = tree(tmp_path, {
        "test_a.py": "import time\n\n\ndef test_x():\n    time.sleep(1)\n    time.sleep(2)\n",
        "sub/helper.py": "import time\n\n\ndef wait():\n    time.sleep(3)\n",
    })
    code, out, _ = check(root)
    assert code == 1
    found = occurrences(out)
    assert sorted((p, n) for p, n, _ in found) == [("tests/cplat/sub/helper.py", 5), ("tests/cplat/test_a.py", 5), ("tests/cplat/test_a.py", 6)]
    assert out[-1] == "check-test-sleeps: 3 fixed sleep(s) in tests/cplat"


def test_a_tree_without_a_real_sleep_is_ok(tmp_path):  # AC-178.6
    root = tree(tmp_path, {"test_a.py": "def test_x():\n    assert sleep_free()\n\n\ndef sleep_free():\n    return 'sleeping beauty'\n"})
    code, out, _ = check(root)
    assert (code, out) == (0, ["OK: no fixed sleeps in tests/cplat"])


def test_a_sleep_outside_tests_cplat_is_not_this_checks_business(tmp_path):  # AC-178.6
    (tmp_path / "tests" / "e2e").mkdir(parents=True)
    (tmp_path / "tests" / "e2e" / "test_x.py").write_text("import time\ntime.sleep(5)\n")
    (tmp_path / "tests" / "cplat").mkdir()
    code, out, _ = check(tmp_path)
    assert (code, out) == (0, ["OK: no fixed sleeps in tests/cplat"])


def test_waiting_py_is_the_one_file_that_may_sleep(tmp_path):  # AC-178.6
    root = tree(tmp_path, {"waiting.py": "import time\n\n\ndef poll():\n    time.sleep(0.02)\n"})
    code, out, _ = check(root)
    assert (code, out) == (0, ["OK: no fixed sleeps in tests/cplat"])


def test_a_sleep_in_a_fake_program_needs_a_marker_with_a_reason(tmp_path):  # AC-178.6
    root = tree(tmp_path, {"test_fake.py": '''
        PROGRAM = """#!/usr/bin/env python3
        import time
        time.sleep(2)  # fake-delay: stands in for a slow build
        time.sleep(3)
        time.sleep(4)  # fake-delay:
        """
    '''})
    code, out, _ = check(root)
    assert code == 1
    assert [(p, n) for p, n, _ in occurrences(out)] == [("tests/cplat/test_fake.py", 4), ("tests/cplat/test_fake.py", 5)]
    assert out[-1] == "check-test-sleeps: 2 fixed sleep(s) in tests/cplat"


def test_the_marker_outside_a_string_allows_nothing(tmp_path):  # AC-178.6
    root = tree(tmp_path, {"test_marker.py": "import time\n\n\ndef test_x():\n    time.sleep(1)  # fake-delay: not a fake program\n"})
    code, out, _ = check(root)
    assert code == 1 and [(p, n) for p, n, _ in occurrences(out)] == [("tests/cplat/test_marker.py", 5)]


@pytest.mark.parametrize("text, flagged", [
    ("sleep 1", True),
    ("sleep $DELAY", True),
    ("echo started; sleep 2", True),
    ("true && sleep 2", True),
    ("echo a | sleep 2", True),
    ("sleep 2  # fake-delay: a slow fake gh", False),
    ("echo sleepy", False),
    ("asleep 2", False),
], ids=["line-start", "variable", "after-semicolon", "after-and", "after-pipe", "marked", "other-word", "suffix-word"])
def test_a_shell_sleep_in_a_fake_program_is_found(tmp_path, text, flagged):  # AC-178.6
    root = tree(tmp_path, {"test_shell.py": f'PROGRAM = """#!/bin/sh\n{text}\nexit 0\n"""\n'})
    code, out, _ = check(root)
    if flagged:
        assert code == 1 and [(p, n) for p, n, _ in occurrences(out)] == [("tests/cplat/test_shell.py", 2)], out
    else:
        assert (code, out) == (0, ["OK: no fixed sleeps in tests/cplat"])


def test_a_python_sleep_call_in_a_fake_program_is_found_inside_a_string_literal(tmp_path):  # AC-178.6
    root = tree(tmp_path, {"test_prog.py": 'PROGRAM = "import asyncio; asyncio.sleep(2)"\nOTHER = "import time; time.sleep(1)"\n'})
    code, out, _ = check(root)
    assert code == 1 and [(p, n) for p, n, _ in occurrences(out)] == [("tests/cplat/test_prog.py", 1), ("tests/cplat/test_prog.py", 2)]


def test_the_real_tree_has_no_fixed_sleep_left(tmp_path):  # AC-178.5
    res = subprocess.run([sys.executable, str(CHECK)], capture_output=True, text=True, cwd=ROOT, timeout=TIMEOUT)
    assert res.returncode == 0, res.stdout + res.stderr
    assert res.stdout.splitlines() == ["OK: no fixed sleeps in tests/cplat"]


# ---------------- AC-178.5: the helper tests wait through ----------------

def load(monkeypatch, delay=None):
    """tests/cplat/waiting.py, read again under the given TEST_FAKE_DELAY (none: unset)."""
    if delay is None:
        monkeypatch.delenv("TEST_FAKE_DELAY", raising=False)
    else:
        monkeypatch.setenv("TEST_FAKE_DELAY", str(delay))
    import waiting as module
    return importlib.reload(module)


def test_the_helper_exposes_the_waits_the_suite_uses(monkeypatch):  # AC-178.5
    waiting = load(monkeypatch)
    for name in ("DELAY", "budget", "wait_for", "wait_file", "wait_process", "wait_gone", "fake_prelude"):
        assert hasattr(waiting, name), name
    assert waiting.DELAY == 0.0


@pytest.mark.parametrize("delay", [0, 2, 0.5])
def test_the_budget_grows_with_the_fake_delay(monkeypatch, delay):  # AC-178.5
    module = load(monkeypatch, delay)
    assert module.DELAY == float(delay)
    assert module.budget() == pytest.approx(30 + 20 * delay)
    assert module.budget(5) == pytest.approx(5 + 20 * delay)


def test_wait_for_returns_the_first_truthy_result(monkeypatch):  # AC-178.5
    waiting = load(monkeypatch)
    seen = []

    def pred():
        seen.append(1)
        return "ready" if len(seen) >= 3 else None
    assert waiting.wait_for(pred, timeout=10, what="three polls") == "ready"
    assert len(seen) == 3


def test_wait_for_names_what_it_waited_for_when_the_time_is_up(monkeypatch):  # AC-178.5
    waiting = load(monkeypatch)
    with pytest.raises(AssertionError) as e:
        waiting.wait_for(lambda: False, timeout=0.1, what="a thing that never happens")
    assert "timed out after" in str(e.value) and "waiting for a thing that never happens" in str(e.value)


def test_wait_file_returns_the_text_once_it_has_the_wanted_content(monkeypatch, tmp_path):  # AC-178.5
    waiting = load(monkeypatch)
    f = tmp_path / "out.txt"
    writer = subprocess.Popen([sys.executable, "-c", f"import pathlib; p = pathlib.Path({str(f)!r}); p.write_text('one'); p.write_text('one two')"])
    try:
        assert waiting.wait_file(f, timeout=60, contains="two") == "one two"
    finally:
        writer.wait(timeout=60)
    with pytest.raises(AssertionError):
        waiting.wait_file(tmp_path / "never.txt", timeout=0.1)


def test_wait_process_returns_the_exit_code_and_fails_on_timeout(monkeypatch):  # AC-178.5
    waiting = load(monkeypatch)
    done = subprocess.Popen([sys.executable, "-c", "raise SystemExit(3)"])
    assert waiting.wait_process(done, timeout=60) == 3
    hanging = subprocess.Popen([sys.executable, "-c", "import sys; sys.stdin.read()"], stdin=subprocess.PIPE)
    try:
        with pytest.raises(AssertionError):
            waiting.wait_process(hanging, timeout=0.2)
    finally:
        hanging.communicate(timeout=60)


def test_wait_gone_returns_when_the_process_has_ended(monkeypatch):  # AC-178.5
    waiting = load(monkeypatch)
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait(timeout=60)
    waiting.wait_gone(p.pid, timeout=10)
    holder = subprocess.Popen([sys.executable, "-c", "import sys; sys.stdin.read()"], stdin=subprocess.PIPE)
    try:
        with pytest.raises(AssertionError):
            waiting.wait_gone(holder.pid, timeout=0.2)
    finally:
        holder.communicate(timeout=60)
    waiting.wait_gone(holder.pid, timeout=10)


@pytest.mark.parametrize("kind, argv", [("python", [sys.executable, "-c"]), ("sh", ["sh", "-c"])])
def test_the_prelude_of_a_fake_program_waits_the_fake_delay_and_says_why(monkeypatch, kind, argv):  # AC-178.5
    module = load(monkeypatch, 0)
    text = module.fake_prelude(kind)
    assert "fake-delay:" in text and "TEST_FAKE_DELAY" in text
    began = time.monotonic()
    fast = subprocess.run([*argv, text], capture_output=True, text=True, timeout=TIMEOUT, env={**os.environ, "TEST_FAKE_DELAY": "0"})
    assert fast.returncode == 0, fast.stderr
    quick = time.monotonic() - began
    began = time.monotonic()
    slow = subprocess.run([*argv, text], capture_output=True, text=True, timeout=TIMEOUT, env={**os.environ, "TEST_FAKE_DELAY": "1"})
    assert slow.returncode == 0, slow.stderr
    assert time.monotonic() - began >= 1.0 and time.monotonic() - began > quick


def test_a_prelude_written_into_a_test_file_passes_the_check(tmp_path, monkeypatch):  # AC-178.5
    module = load(monkeypatch, 0)
    body = module.fake_prelude("python").replace("\\", "\\\\").replace('"""', "'''")
    root = tree(tmp_path, {"test_fake.py": f'PROGRAM = """\n{body}\nprint("fake")\n"""\n'})
    code, out, _ = check(root)
    assert (code, out) == (0, ["OK: no fixed sleeps in tests/cplat"]), out
