"""Spec 197 acceptance tests: generated repos bound the time of one test (AC-197.6, AC-197.7, AC-197.8).

Nothing here waits 120 s or 5 minutes. The pytest plugin runs in nested pytest runs with `LIMIT_S` set to 2 by a shim plugin loaded
first; `scripts/gate.sh` runs a fake command that dumps the environment it was given. Contract: design.md "Per-test limits"
(the gate.sh table and the pytest plugin). The plugin and the gate.sh variables do not exist yet: tests reach them in their bodies."""
import fnmatch
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "templates"
GATE = TEMPLATES / "gitops-app" / "scripts" / "gate.sh"
PLUGIN_REL = Path("scripts") / "pytest_limit" / "platform_test_limit.py"
PLUGIN = TEMPLATES / "service-python" / PLUGIN_REL
MAVEN_120 = "-Djunit.jupiter.execution.timeout.default=120s"
LIMIT = 2


# ---------------- AC-197.6: the pytest plugin ----------------

def nested(tmp_path, files, *args, extra_env=None, shim_extra="", ini=""):
    """A scratch pytest project with the plugin loaded and LIMIT_S shortened to LIMIT seconds."""
    assert PLUGIN.is_file(), f"{PLUGIN.relative_to(ROOT)} does not exist"
    for name, text in files.items():
        (tmp_path / name).write_text(text)
    (tmp_path / "pytest.ini").write_text("[pytest]\nmarkers =\n    timeout: a per-test limit of some other tool\n" + ini)
    (tmp_path / "short_limit.py").write_text(f"import platform_test_limit\nplatform_test_limit.LIMIT_S = {LIMIT}\n{shim_extra}")
    env = {k: v for k, v in os.environ.items() if k not in ("PYTEST_ADDOPTS", "PYTEST_CURRENT_TEST", "PYTEST_XDIST_WORKER", "PYTEST_TIMEOUT")}
    env["PYTHONPATH"] = os.pathsep.join([str(PLUGIN.parent), str(tmp_path)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    env.update(extra_env or {})
    junit = tmp_path / "junit.xml"
    start = time.monotonic()
    p = subprocess.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-p", "short_limit", "-p", "platform_test_limit",
                        f"--junitxml={junit}", *args], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    took = time.monotonic() - start
    return p, parse(junit), took


def parse(junit):
    """{test name: ("passed"|"failed"|"error", message text)} from the JUnit file; a test with failure and error keeps the first."""
    import xml.etree.ElementTree as ET
    if not junit.is_file():
        return {}
    got = {}
    for case in ET.parse(junit).getroot().iter("testcase"):
        bad = [c for c in case if c.tag in ("failure", "error")]
        got[case.get("name")] = (bad[0].tag, (bad[0].get("message") or "") + (bad[0].text or "")) if bad else ("passed", "")
    return got


HUNG = '''import threading

import pytest


@pytest.fixture
def stuck_setup():
    threading.Event().wait(60)


@pytest.fixture
def stuck_teardown():
    yield
    threading.Event().wait(60)


def test_ok_before():
    assert True


def test_stuck_body():
    threading.Event().wait(60)


def test_stuck_in_setup(stuck_setup):
    assert True


def test_stuck_in_teardown(stuck_teardown):
    assert True


def test_ok_after():
    assert True
'''


def test_a_hung_test_fails_with_id_and_limit_and_the_others_run_ac_197_6(tmp_path):  # AC-197.6
    p, results, took = nested(tmp_path, {"test_hung.py": HUNG}, "-q")
    out = p.stdout + p.stderr
    assert p.returncode == 1, out
    assert took < 60, "the run waited for the sleeps instead of stopping them"
    assert results["test_ok_before"][0] == "passed" and results["test_ok_after"][0] == "passed", out
    for name in ("test_stuck_body", "test_stuck_in_setup", "test_stuck_in_teardown"):
        kind, text = results[name]
        assert kind in ("failed", "failure", "error"), (name, out)
        assert f"Timeout (>{LIMIT}s)" in text and f"test_hung.py::{name}" in text, (name, text)
        assert f"per-test limit of {LIMIT} s" in text, (name, text)


def test_the_shipped_limit_is_120_seconds_ac_197_6():  # AC-197.6
    assert PLUGIN.is_file(), f"{PLUGIN.relative_to(ROOT)} does not exist"
    spec = importlib.util.spec_from_file_location("platform_test_limit_shipped", PLUGIN)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.LIMIT_S == 120


def test_a_suite_without_a_hung_test_is_unchanged_ac_197_6(tmp_path):  # AC-197.6
    ok = "import threading\n\n\ndef test_a():\n    threading.Event().wait(0.2)\n\n\ndef test_b():\n    assert 1 + 1 == 2\n"
    p, results, _ = nested(tmp_path, {"test_ok.py": ok}, "-q")
    assert p.returncode == 0, p.stdout + p.stderr
    assert results == {"test_a": ("passed", ""), "test_b": ("passed", "")}
    assert "2 passed" in p.stdout


def test_the_timer_and_handler_are_restored_after_each_test_ac_197_6(tmp_path):  # AC-197.6
    probe = ("import signal\n\n\ndef test_first():\n    assert signal.getitimer(signal.ITIMER_REAL)[0] > 0\n\n\n"
             "def test_second():\n    assert signal.getitimer(signal.ITIMER_REAL)[0] > 0\n")
    check = "def pytest_sessionfinish(session):\n    import signal\n    assert signal.getitimer(signal.ITIMER_REAL)[0] == 0\n    assert signal.getsignal(signal.SIGALRM) == signal.SIG_DFL\n"
    p, results, _ = nested(tmp_path, {"test_probe.py": probe, "conftest.py": check}, "-q")
    assert p.returncode == 0, p.stdout + p.stderr
    assert set(results.values()) == {("passed", "")}


def test_a_test_with_a_timeout_marker_keeps_its_own_limit_ac_197_8(tmp_path):  # AC-197.8
    marked = f"import threading\n\nimport pytest\n\n\n@pytest.mark.timeout(30)\ndef test_slow_but_allowed():\n    threading.Event().wait({LIMIT + 2})\n"
    p, results, _ = nested(tmp_path, {"test_marked.py": marked}, "-q")
    assert p.returncode == 0 and results["test_slow_but_allowed"][0] == "passed", p.stdout + p.stderr


def test_a_handler_another_tool_owns_is_left_alone_ac_197_8(tmp_path):  # AC-197.8
    owned = ("import signal\nimport threading\n\nsignal.signal(signal.SIGALRM, lambda *a: None)\n\n\n"
             f"def test_other_tool_owns_sigalrm():\n    threading.Event().wait({LIMIT + 2})\n")
    p, results, _ = nested(tmp_path, {"test_owned.py": owned}, "-q")
    assert p.returncode == 0 and results["test_other_tool_owns_sigalrm"][0] == "passed", p.stdout + p.stderr


@pytest.mark.skipif(importlib.util.find_spec("pytest_timeout") is None, reason="pytest-timeout is not installed here")
@pytest.mark.parametrize("how", ["env", "ini", "option"])
def test_a_repo_with_pytest_timeout_configured_keeps_it_ac_197_8(tmp_path, how):  # AC-197.8
    slow = f"import threading\n\n\ndef test_slow_but_inside_the_repos_limit():\n    threading.Event().wait({LIMIT + 2})\n"
    kw = {"env": {"extra_env": {"PYTEST_TIMEOUT": "60"}}, "ini": {"ini": "timeout = 60\n"}, "option": {}}[how]
    args = ["--timeout=60"] if how == "option" else []
    p, results, _ = nested(tmp_path, {"test_slow.py": slow}, "-q", *args, **kw)
    assert p.returncode == 0 and results["test_slow_but_inside_the_repos_limit"][0] == "passed", p.stdout + p.stderr


# ---------------- AC-197.6, AC-197.7: what gate.sh sets ----------------

@pytest.fixture()
def box(tmp_path):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(GATE, repo / "scripts" / "gate.sh")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    dump = tmp_path / "env.json"
    dumper = tmp_path / "dump_env.py"
    dumper.write_text("import json, os, sys\njson.dump({'env': dict(os.environ), 'argv': sys.argv[2:]}, open(sys.argv[1], 'w'))\n")

    class Box:
        pass

    b = Box()
    b.repo = repo

    def gate(runner, *command, **env):
        """Run `gate.sh tests test <runner> -- <dump command> <command...>`; the dumped environment and argv of the command."""
        dump.unlink(missing_ok=True)
        e = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "TMPDIR": str(tmp_path), "GIT_CEILING_DIRECTORIES": str(tmp_path)}
        e.update(env)
        subprocess.run(["bash", "scripts/gate.sh", "tests", "test", runner, "--", sys.executable, str(dumper), str(dump), *command],
                       cwd=repo, env=e, capture_output=True, text=True, timeout=60)     # its verdict (0 tests ran) is not the point
        assert dump.is_file(), "the command did not run"
        return json.loads(dump.read_text())

    b.gate = gate
    return b


def add_plugin(repo):
    target = repo / PLUGIN_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# stand-in for the platform plugin\n")


def test_gate_sh_loads_the_pytest_plugin_through_the_environment_ac_197_6(box):  # AC-197.6
    add_plugin(box.repo)
    got = box.gate("pytest", PYTHONPATH="/old/path", PYTEST_ADDOPTS="-q")
    paths = got["env"]["PYTHONPATH"].split(os.pathsep)
    assert Path(paths[0]).resolve() == (box.repo / PLUGIN_REL).parent.resolve() and paths[1:] == ["/old/path"]
    assert got["env"]["PYTEST_ADDOPTS"].split() == ["-q", "-p", "platform_test_limit"]


def test_gate_sh_sets_the_pytest_plugin_without_old_values_ac_197_6(box):  # AC-197.6
    add_plugin(box.repo)
    env = box.gate("pytest")["env"]
    assert Path(env["PYTHONPATH"].split(os.pathsep)[0]).resolve() == (box.repo / PLUGIN_REL).parent.resolve()
    assert env["PYTEST_ADDOPTS"].split() == ["-p", "platform_test_limit"]


def test_gate_sh_leaves_pytest_alone_without_the_plugin_file_ac_197_6(box):  # AC-197.6
    add_plugin(box.repo)                      # the plugin is there: the variables are set (fails until gate.sh does it) ...
    assert "platform_test_limit" in box.gate("pytest")["env"].get("PYTEST_ADDOPTS", "")
    (box.repo / PLUGIN_REL).unlink()          # ... and it asks for nothing the repo does not have
    assert "platform_test_limit" not in box.gate("pytest")["env"].get("PYTEST_ADDOPTS", "")


def test_gate_sh_sets_the_junit_timeout_for_maven_ac_197_6(box):  # AC-197.6
    got = box.gate("maven", MAVEN_ARGS="-q")
    assert got["env"]["MAVEN_ARGS"].split() == ["-q", MAVEN_120]
    assert box.gate("maven")["env"]["MAVEN_ARGS"].split() == [MAVEN_120]


@pytest.mark.parametrize("where", ["argument", "MAVEN_ARGS", "MAVEN_OPTS", "pom.xml", "junit-platform.properties"])
def test_gate_sh_keeps_a_limit_the_java_repo_sets_itself_ac_197_8(box, where):  # AC-197.8
    own = "junit.jupiter.execution.timeout.default"
    assert MAVEN_120 in box.gate("maven")["env"]["MAVEN_ARGS"]                 # it is added when the repo sets none
    env, command = {}, []
    if where == "argument":
        command = [f"-D{own}=30s"]
    elif where in ("MAVEN_ARGS", "MAVEN_OPTS"):
        env[where] = f"-D{own}=30s"
    elif where == "pom.xml":
        (box.repo / "pom.xml").write_text(f"<project><properties><{own}>30s</{own}></properties></project>\n")
    else:
        res = box.repo / "src" / "test" / "resources"
        res.mkdir(parents=True)
        (res / "junit-platform.properties").write_text(f"{own}=30s\n")
    got = box.gate("maven", *command, **env)
    assert MAVEN_120 not in got["env"].get("MAVEN_ARGS", "")
    assert got["argv"] == command


def test_gate_sh_sets_the_go_package_timeout_ac_197_7(box):  # AC-197.7
    assert box.gate("go", GOFLAGS="-mod=readonly")["env"]["GOFLAGS"].split() == ["-mod=readonly", "-timeout=5m"]
    assert box.gate("go")["env"]["GOFLAGS"].split() == ["-timeout=5m"]


def test_gate_sh_keeps_a_go_timeout_the_repo_sets_ac_197_8(box):  # AC-197.8
    assert "-timeout=5m" in box.gate("go")["env"]["GOFLAGS"]                    # it is added when the repo sets none
    assert box.gate("go", GOFLAGS="-timeout=10m -mod=readonly")["env"]["GOFLAGS"] == "-timeout=10m -mod=readonly"


def test_gate_sh_adds_nothing_for_vitest_ac_197_7(box):  # AC-197.7
    add_plugin(box.repo)
    assert "platform_test_limit" in box.gate("pytest")["env"]["PYTEST_ADDOPTS"]     # the other runners get theirs ...
    env = box.gate("vitest")["env"]
    assert not {"GOFLAGS", "MAVEN_ARGS", "PYTEST_ADDOPTS"} & set(env) and "pytest_limit" not in env.get("PYTHONPATH", "")


# ---------------- AC-197.8: existing repos get it through platform-owned files only ----------------

PYTHON_TEMPLATES = ["service-python", "library-python"]
BUILD_FILE = {"service-python": "pyproject.toml", "library-python": "pyproject.toml", "service-java": "pom.xml", "service-go": "go.mod"}


@pytest.mark.parametrize("template", PYTHON_TEMPLATES)
def test_the_plugin_ships_in_both_python_templates_without_jinja_syntax_ac_197_8(template):  # AC-197.8
    copy = TEMPLATES / template / PLUGIN_REL
    assert copy.is_file(), f"{template} has no {PLUGIN_REL}"
    assert copy.read_bytes() == PLUGIN.read_bytes()
    for token in ("{{", "{%", "{#"):
        assert token not in copy.read_text(), f"the plugin must not contain {token!r} (the Python templates render every file with Jinja)"


def test_the_sync_script_covers_the_plugin_copy_ac_197_8():  # AC-197.8
    text = (ROOT / "scripts" / "sync-template-copies.py").read_text()
    assert "platform_test_limit.py" in text
    done = subprocess.run([sys.executable, str(ROOT / "scripts" / "sync-template-copies.py"), "--check"], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


@pytest.mark.parametrize("template", ["service-python", "library-python", "service-java", "service-go"])
def test_the_limits_travel_in_platform_owned_files_only_ac_197_8(template):  # AC-197.8
    """The build file stays project-owned and untouched; the plugin and gate.sh are not skipped when they exist in the repo."""
    conf = yaml.safe_load((TEMPLATES / template / "copier.yml").read_text())
    skip = conf["_skip_if_exists"]
    assert BUILD_FILE[template] in skip
    owned = ["scripts/gate.sh"] + (["scripts/pytest_limit/platform_test_limit.py"] if template in PYTHON_TEMPLATES else [])
    for rel in owned:
        assert (TEMPLATES / template / rel).is_file(), rel
        assert not [pat for pat in skip if fnmatch.fnmatch(rel, pat)], f"{rel} would be skipped by /platform:update"
    gate = (TEMPLATES / template / "scripts" / "gate.sh").read_text()
    assert {"service-python": "platform_test_limit", "library-python": "platform_test_limit",
            "service-java": "junit.jupiter.execution.timeout.default=120s", "service-go": "-timeout=5m"}[template] in gate
    build = next(p for p in (TEMPLATES / template).iterdir() if p.name.startswith(BUILD_FILE[template]))
    assert re.search(r"platform_test_limit|execution\.timeout\.default|-timeout=5m", build.read_text()) is None
