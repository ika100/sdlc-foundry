"""Spec 185 acceptance tests: a hung test fails on its own and names itself (AC-185.1), the pinned test tools hold pytest-timeout
(AC-185.2), and a test may not sleep for real longer than 1 s (AC-185.3).

Nothing here waits 120 s: the limit is checked in the ini file and by a nested pytest run with the same ini and `-o timeout=1`.
The sleep guard runs in nested pytest runs too; their test files are strings, so a sleep sample carries `fake-delay:` (spec 178).
"""
import configparser
import importlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from test_test_tools_127 import NEW_TOOLS, PIN, REQ, check, norm, requirement_lines, scratch

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "tests" / "cplat"
INI = TESTS / "pytest.ini"
TOP = ["pytest", "pytest-timeout", "pytest-xdist", "pyyaml", "ruamel.yaml"]


def nested(cwd, *args):
    env = {k: v for k, v in os.environ.items() if k not in ("PYTEST_ADDOPTS", "PYTEST_CURRENT_TEST", "PYTEST_XDIST_WORKER")}
    return subprocess.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *args], cwd=cwd, env=env,
                          capture_output=True, text=True, timeout=300)


# ---------------- AC-185.1: the per-test limit ----------------

def test_the_ini_file_sets_the_limit_the_method_and_the_required_plugins_ac_185_1():  # AC-185.1
    cfg = configparser.ConfigParser()
    cfg.read(INI)
    sec = cfg["pytest"]
    assert sec.get("timeout") == "120"
    assert sec.get("timeout_method") == "signal"
    assert {"pytest-timeout", "pytest-xdist"} <= set(sec.get("required_plugins", "").split())
    assert sec.get("timeout_func_only", "false").lower() == "false"   # setup and teardown count too
    assert "slow:" in sec.get("markers", "")                           # the marker stays


HUNG = ("import threading\n\n"
        "def test_ok_before():\n    assert True\n\n"
        "def test_hang():\n    ev = threading.Event()\n    ev.wait(10)\n    assert True\n\n"
        "def test_ok_after():\n    assert True\n")


@pytest.mark.parametrize("extra", [[], ["-n", "2"]], ids=["serial", "xdist"])
def test_a_test_over_the_limit_fails_with_id_limit_and_stack_and_the_others_run_ac_185_1(tmp_path, extra):  # AC-185.1
    shutil.copy(INI, tmp_path / "pytest.ini")
    (tmp_path / "test_hang.py").write_text(HUNG)
    p = nested(tmp_path, "-o", "timeout=1", "-v", "-rf", "--tb=short", *extra)
    out = p.stdout + p.stderr
    assert p.returncode == 1, out
    assert re.search(r"FAILED test_hang\.py::test_hang\b", out), out
    assert re.search(r"Timeout \(>1\.0s\)", out), out                  # the limit it was stopped at
    assert "test_hang.py:" in out and "ev.wait(" in out, out           # the stack where it was stopped
    assert re.search(r"test_hang\.py::test_ok_before\s+PASSED|test_ok_before\s+PASSED|PASSED\s+test_hang\.py::test_ok_before", out), out   # serial or xdist -v
    assert re.search(r"test_ok_after\s+PASSED|PASSED\s+test_hang\.py::test_ok_after", out), out   # the other tests still ran and reported
    assert "2 passed, 1 failed" in out or "1 failed, 2 passed" in out, out


SLOW_SETUP = ("import threading\nimport pytest\n\n"
              "@pytest.fixture()\ndef slow():\n    threading.Event().wait(10)\n    yield\n\n"
              "def test_slow_setup(slow):\n    assert True\n\n"
              "@pytest.fixture()\ndef slow_down():\n    yield\n    threading.Event().wait(10)\n\n"
              "def test_slow_teardown(slow_down):\n    assert True\n")


def test_a_slow_setup_or_teardown_is_stopped_too_ac_185_1(tmp_path):  # AC-185.1
    shutil.copy(INI, tmp_path / "pytest.ini")
    (tmp_path / "test_slow.py").write_text(SLOW_SETUP)
    p = nested(tmp_path, "-o", "timeout=1", "-v", "-rfE", "--tb=short")
    out = p.stdout + p.stderr
    assert p.returncode == 1, out
    assert re.search(r"(FAILED|ERROR) test_slow\.py::test_slow_setup\b", out), out
    assert re.search(r"(FAILED|ERROR) test_slow\.py::test_slow_teardown\b", out), out
    assert len(re.findall(r"Timeout \(>1\.0s\)", out)) >= 2, out


@pytest.mark.parametrize("rel", ["devbox.json", "scripts/ci-local.sh", ".github/workflows/ci.yml", "scripts/test-fast.sh"])
def test_no_suite_command_overrides_the_ini_limit_ac_185_1(rel):  # AC-185.1
    lines = [ln for ln in (ROOT / rel).read_text().splitlines() if "pytest" in ln and "uv run" in ln]
    assert lines, rel
    for ln in lines:
        assert not re.search(r"(^|\s)(-c|--config-file|--timeout\S*|-o|--override-ini)(\s|=)", ln), ln
        assert "no:timeout" not in ln and "timeout=" not in ln and "-p no:" not in ln, ln


def test_a_run_without_the_timeout_plugin_fails_at_once_ac_185_1(tmp_path):  # AC-185.1
    (tmp_path / "pytest.ini").write_text("[pytest]\nrequired_plugins = pytest-no-such-plugin-185\n")
    (tmp_path / "test_a.py").write_text("def test_a():\n    assert True\n")
    p = nested(tmp_path)
    assert p.returncode != 0 and "pytest-no-such-plugin-185" in p.stdout + p.stderr   # control: the mechanism the ini relies on
    assert "pytest-timeout" in INI.read_text(), "the real ini does not require pytest-timeout"


# ---------------- AC-185.2: pins ----------------

def test_requirements_test_in_lists_exactly_the_five_top_level_packages_unpinned_ac_185_2():  # AC-185.2
    lines = [ln.strip() for ln in (ROOT / "requirements-test.in").read_text().splitlines() if ln.strip() and not ln.strip().startswith("#")]
    assert lines == TOP, lines


def test_requirements_test_txt_pins_pytest_timeout_and_every_requirement_exactly_ac_185_2():  # AC-185.2
    text = (ROOT / REQ).read_text()
    assert "uv pip compile --universal requirements-test.in -o requirements-test.txt" in text
    lines = requirement_lines(ROOT / REQ)
    bad = [ln for ln in lines if not PIN.match(ln)]
    assert bad == [], bad
    names = {norm(PIN.match(ln).group(1)) for ln in lines}
    assert {norm(x) for x in TOP} <= names, {norm(x) for x in TOP} - names
    assert len(names) > len(TOP), "dependencies are pinned too"


@pytest.mark.parametrize("form", ["--with pytest-timeout", "--with=pytest-timeout", "--with pytest-timeout==1.0", "--with 'pytest-timeout>=1'"])
def test_check_pins_fails_on_pytest_timeout_installed_without_the_file_ac_185_2(tmp_path, form):  # AC-185.2
    devbox = (ROOT / "devbox.json").read_text().replace(NEW_TOOLS, f"{NEW_TOOLS} {form}")
    assert form in devbox
    p = check(scratch(tmp_path, devbox=devbox))
    assert p.returncode == 1, p.stdout + p.stderr
    assert "devbox.json:" in p.stdout and "installs pytest-timeout without requirements-test.txt" in p.stdout, p.stdout


# ---------------- AC-185.3: the sleep guard ----------------

CONFTEST = '''import sys
from pathlib import Path

sys.path.insert(0, {tests!r})
import sleepguard

HERE = Path(__file__).resolve().parent
sleepguard.ROOT = HERE
sleepguard.EXEMPT = {{HERE / "waiting.py"}}
sleepguard.install()
from sleepguard import pytest_runtest_makereport, pytest_runtest_protocol  # noqa: F401,E402
'''


def guarded(tmp_path, body, *args):
    (tmp_path / "conftest.py").write_text(CONFTEST.format(tests=str(TESTS)))
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    (tmp_path / "test_a.py").write_text(body)
    p = nested(tmp_path.resolve(), "-v", "--tb=short", *args)
    return p.returncode, p.stdout + p.stderr


MSG = (r"real sleep of {s} s at test_a\.py:\d+ takes this test over 1 s; "
       r"wait for an event or a file, or use the fake clock")


def test_the_guard_module_has_the_documented_seam_ac_185_3():  # AC-185.3
    sys.path.insert(0, str(TESTS))
    guard = importlib.import_module("sleepguard")
    assert guard.LIMIT_S == 1.0 and callable(guard.install)
    assert callable(guard.pytest_runtest_protocol) and callable(guard.pytest_runtest_makereport)
    assert "sleepguard.install()" in (TESTS / "conftest.py").read_text()


@pytest.mark.parametrize("module", ["core", "engine", "dispatch"])
def test_the_modules_that_bind_sleep_at_import_hold_the_guard_not_the_original_ac_185_3(module):  # AC-185.3
    """The guard is installed before any `cplat` module is imported, so `core.sleep = time.sleep` bound the wrapper."""
    import time
    mod = importlib.import_module(module)
    for fn in (mod.sleep, time.sleep):
        code = getattr(fn, "__code__", None)
        assert code is not None and Path(code.co_filename).name == "sleepguard.py", f"{module}.sleep is the builtin, not the guard"
    assert mod.sleep is time.sleep


def test_a_sleep_over_one_second_fails_at_once_even_if_the_assertions_pass_ac_185_3(tmp_path):  # AC-185.3
    marker = tmp_path / "after-sleep"
    body = ("import time\n\ndef test_slept():\n"
            "    t = time.monotonic()\n"
            "    try:\n        time.sleep(3)  # fake-delay: guard sample, must not sleep\n"
            "    finally:\n        open('elapsed', 'w').write(str(time.monotonic() - t))\n"
            f"    open({str(marker)!r}, 'w').write('x')\n    assert True\n")
    rc, out = guarded(tmp_path, body)
    assert rc == 1 and "test_a.py::test_slept FAILED" in out, out
    assert re.search(MSG.format(s="3"), out), out
    assert float((tmp_path / "elapsed").read_text()) < 1.0, "the guard slept"
    assert not marker.exists()


def test_the_total_of_a_test_counts_and_each_test_has_its_own_budget_ac_185_3(tmp_path):  # AC-185.3
    body = ("import time\n\n"
            "def test_within():\n    time.sleep(0.3)  # fake-delay: within the budget\n    time.sleep(0.3)  # fake-delay: within the budget\n\n"
            "def test_within_again():\n    time.sleep(0.5)  # fake-delay: a fresh budget\n    time.sleep(0.4)  # fake-delay: a fresh budget\n\n"
            "def test_over():\n    time.sleep(0.6)  # fake-delay: within\n    time.sleep(0.6)  # fake-delay: crosses 1 s\n")
    rc, out = guarded(tmp_path, body)
    assert rc == 1, out
    assert "test_a.py::test_within PASSED" in out and "test_a.py::test_within_again PASSED" in out, out
    assert "test_a.py::test_over FAILED" in out and re.search(MSG.format(s="0.6"), out), out


def test_setup_counts_towards_the_budget_of_the_test_ac_185_3(tmp_path):  # AC-185.3
    body = ("import time\nimport pytest\n\n"
            "@pytest.fixture()\ndef f():\n    time.sleep(0.7)  # fake-delay: setup share of the budget\n\n"
            "def test_x(f):\n    time.sleep(0.7)  # fake-delay: crosses 1 s with the fixture\n")
    rc, out = guarded(tmp_path, body)
    assert rc == 1 and re.search(MSG.format(s="0.7"), out), out


def test_a_total_of_exactly_one_second_passes_ac_185_3(tmp_path):  # AC-185.3
    body = ("import time\n\n"
            "def test_exact():\n    time.sleep(0.5)  # fake-delay: half of the budget\n    time.sleep(0.5)  # fake-delay: reaches 1.0 s, not over\n")
    rc, out = guarded(tmp_path, body)
    assert rc == 0 and "test_a.py::test_exact PASSED" in out, out


def test_a_sleep_called_by_the_standard_library_is_not_counted_ac_185_3(tmp_path):  # AC-185.3
    body = ("import subprocess\nimport sys\n\n"
            "def test_popen_wait():\n"
            "    code = 'import time; time.sleep(1.5)'  # fake-delay: a fake program in its own process\n"
            "    p = subprocess.Popen([sys.executable, '-c', code])\n"
            "    assert p.wait(timeout=60) == 0\n")            # Popen.wait(timeout=) polls with time.sleep from the standard library
    rc, out = guarded(tmp_path, body)
    assert rc == 0 and "test_a.py::test_popen_wait PASSED" in out, out


def test_the_waiting_helper_is_exempt_ac_185_3(tmp_path):  # AC-185.3
    shutil.copy(TESTS / "waiting.py", tmp_path / "waiting.py")
    body = ("import pytest\nimport waiting\n\n"
            "def test_poll():\n    with pytest.raises(AssertionError):\n        waiting.wait_for(lambda: False, timeout=1.5, what='nothing')\n")
    rc, out = guarded(tmp_path, body)
    assert rc == 0 and "test_a.py::test_poll PASSED" in out, out


def test_a_sleep_in_a_thread_of_the_test_fails_the_test_ac_185_3(tmp_path):  # AC-185.3
    body = ("import threading\nimport time\n\n"
            "def test_thread():\n    t = threading.Thread(target=lambda: time.sleep(4))  # fake-delay: thread sample\n"
            "    t.start()\n    t.join()\n")
    rc, out = guarded(tmp_path, body)
    assert rc == 1 and "test_a.py::test_thread FAILED" in out and re.search(MSG.format(s="4"), out), out


def test_a_swallowing_except_does_not_hide_the_crossing_ac_185_3(tmp_path):  # AC-185.3
    body = ("import time\n\n"
            "def test_swallowed():\n    try:\n        time.sleep(2)  # fake-delay: swallowed sample\n"
            "    except BaseException:\n        pass\n")
    rc, out = guarded(tmp_path, body)
    assert rc == 1 and re.search(MSG.format(s="2"), out), out


def test_an_asyncio_sleep_follows_the_same_rule_ac_185_3(tmp_path):  # AC-185.3
    body = ("import asyncio\n\n"
            "def test_async():\n    asyncio.run(asyncio.sleep(2))  # fake-delay: async sample\n")
    rc, out = guarded(tmp_path, body)
    assert rc == 1 and re.search(MSG.format(s="2"), out), out


def test_a_sleep_in_a_separate_process_does_not_count_ac_185_3(tmp_path):  # AC-185.3
    body = ("import subprocess\nimport sys\n\n"
            "def test_child():\n"
            "    code = 'import time; time.sleep(1.3)'  # fake-delay: a fake program in its own process\n"
            "    assert subprocess.run([sys.executable, '-c', code]).returncode == 0\n")
    rc, out = guarded(tmp_path, body)
    assert rc == 0, out
