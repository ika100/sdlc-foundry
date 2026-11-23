"""Spec 205 acceptance tests: `cplat quiet test-fast --red -- <test files>` classes each red test (AC-205.5).

Seam: `quiet.main(argv)` in a small git repo (shape service-python, `test-fast` runs pytest) with a fake `devbox` on PATH. The fake
applies the `-e KEY=VALUE` pairs `cplat quiet` passes, then runs a real `python -m pytest` on the arguments after `--`, so the
injected plugins (design.md, section 2) run for real. Contract: design.md section 2.
"""
import collections
import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

import quiet
from waiting import with_prelude

USAGE = ("usage: cplat quiet [--raw] <devbox-script> | cplat quiet [--raw] test-fast [--repeat N | --red] -- <test args>   "
         "(a key of shell.scripts in ./devbox.json; only test-fast takes arguments, after --)")

FAKE_DEVBOX = """#!/bin/sh
: > "$FAKE_DIR/calls-$$"
shift
while [ "$1" = "-e" ]; do export "$2"; shift 2; done
shift
[ "$1" = "--" ] && shift
unset PYTEST_XDIST_WORKER PYTEST_CURRENT_TEST
exec "$FAKE_PY" -m pytest -q -p no:cacheprovider "$@"
"""

PKG = "def boom():\n    raise ValueError('bad input')\n"

HELPERS = '''import pytest

import pkg


def make_repo(path, name):
    (path / name / "sub").mkdir()


@pytest.fixture()
def broken():
    raise RuntimeError("fixture boom")
'''

MIXED = HELPERS + '''

def test_assertion():
    assert 1 == 2


def test_not_implemented():
    raise NotImplementedError("later")


def test_missing_module():
    import pkg.redcheck  # noqa: F401


def test_missing_attribute():
    pkg.nothing_here()


def test_non_test_frame():
    pkg.boom()


def test_helper_mkdir(tmp_path):
    make_repo(tmp_path, "a")


def test_helper_wrong_arguments():
    make_repo()


def test_fixture_error(broken):
    assert True


def test_other_exception_in_test_code():
    {}["k"]


def test_passes():
    assert True
'''

MISSING = {
    "test_assertion", "test_not_implemented", "test_missing_module", "test_missing_attribute", "test_non_test_frame",
}
ERRORS = {"test_helper_mkdir", "test_helper_wrong_arguments", "test_fixture_error", "test_other_exception_in_test_code"}


class World:
    def __init__(self, root, d):
        self.root, self.d = root, d

    def put(self, rel, text):
        (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
        (self.root / rel).write_text(text)

    def calls(self):
        return [p for p in self.d.iterdir() if p.name.startswith("calls-")]


@pytest.fixture()
def world(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "devbox"
    fake.write_text(with_prelude(FAKE_DEVBOX))
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    root = tmp_path / "myrepo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    (root / ".copier-answers.yml").write_text("_src_path: gh:ika100/sdlc-foundry/templates/service-python\nproject_name: myrepo\n")
    (root / "devbox.json").write_text(json.dumps({"shell": {"scripts": {"test-fast": "uv run pytest -q \"$@\"", "quality": "y"}}}))
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text(PKG)
    d = tmp_path / "fake"
    d.mkdir()
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false",
                    "commit", "-q", "-m", "init"], cwd=root, check=True)
    monkeypatch.chdir(root)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("FAKE_DIR", str(d))
    monkeypatch.setenv("FAKE_PY", sys.executable)
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    return World(root, d)


def red(capsys, *files):
    capsys.readouterr()
    rc = quiet.main(["test-fast", "--red", "--", *files])
    out = capsys.readouterr().out
    lines = out.splitlines()
    judged = {}
    for ln in lines:
        node, sep, rest = ln.partition(": ")
        if sep and "::" in node:
            cls, _, why = rest.partition(" — ")
            judged[node] = (cls, why)
    return rc, judged, lines


def by_name(judged, file="tests/test_red.py"):
    found = {n.split("::", 1)[1]: v for n, v in judged.items() if n.startswith(file + "::")}
    return collections.defaultdict(lambda: ("no line printed", ""), found)


# ---------------- AC-205.5: the classes ----------------

def test_each_test_gets_its_class_and_the_exception_line_ac_205_5(world, capsys):  # AC-205.5
    world.put("tests/test_red.py", MIXED)
    rc, judged, lines = red(capsys, "tests/test_red.py")
    got = by_name(judged)
    assert {n for n, (c, _) in got.items() if c == "missing behaviour"} == MISSING
    assert {n for n, (c, _) in got.items() if c == "test error"} == ERRORS
    assert got["test_passes"][0] == "passes"
    assert set(got) == MISSING | ERRORS | {"test_passes"}                    # one line per test, no other
    assert got["test_missing_module"][1] == "ModuleNotFoundError: No module named 'pkg.redcheck'"
    assert got["test_non_test_frame"][1] == "ValueError: bad input"
    assert got["test_helper_mkdir"][1].startswith("FileNotFoundError: ")      # the spec 157 case: a helper creates no parents
    assert got["test_helper_wrong_arguments"][1].startswith("TypeError: ")
    assert got["test_fixture_error"][1] == "RuntimeError: fixture boom"
    assert got["test_passes"][1] == ""
    assert [ln.split(": ")[0] for ln in lines[:-1]] == sorted(ln.split(": ")[0] for ln in lines[:-1])      # sorted by node id
    assert lines[-1].startswith("red check: ") and "5 missing behaviour" in lines[-1] and "4 test error" in lines[-1]
    assert "1 passes" in lines[-1]
    assert rc == 1


def test_a_run_where_every_test_misses_behaviour_exits_0_ac_205_5(world, capsys):  # AC-205.5
    world.put("tests/test_red.py", HELPERS + "\n\ndef test_a():\n    assert 1 == 2\n\n\ndef test_b():\n    pkg.boom()\n")
    rc, judged, lines = red(capsys, "tests/test_red.py")
    assert {c for c, _ in by_name(judged).values()} == {"missing behaviour"} and len(judged) == 2
    assert rc == 0
    assert lines[-1].startswith("red check: 2 missing behaviour")


@pytest.mark.parametrize("body", [
    "def test_a():\n    assert True\n",
    "def test_a():\n    assert 1 == 2\n\n\ndef test_b():\n    assert True\n",
    "def test_a():\n    assert 1 == 2\n\n\ndef test_b():\n    {}['k']\n",
])
def test_any_other_class_makes_the_exit_1_ac_205_5(world, capsys, body):  # AC-205.5
    world.put("tests/test_red.py", body)
    rc, judged, _ = red(capsys, "tests/test_red.py")
    assert judged and rc == 1


def test_a_test_node_id_selects_one_test_ac_205_5(world, capsys):  # AC-205.5
    world.put("tests/test_red.py", MIXED)
    capsys.readouterr()
    rc = quiet.main(["test-fast", "--red", "--", "tests/test_red.py::test_assertion"])
    out = capsys.readouterr().out.splitlines()
    assert rc == 0 and out[0].startswith("tests/test_red.py::test_assertion: missing behaviour")
    assert len([ln for ln in out if "::" in ln.split(" ")[0]]) == 1


def test_a_collection_error_naming_a_missing_module_is_missing_behaviour_once_per_test_ac_205_5(world, capsys):  # AC-205.5
    world.put("tests/test_new.py", "import pkg.redcheck\n\n\ndef test_one():\n    assert pkg.redcheck.x\n\n\ndef test_two():\n    assert pkg.redcheck.y\n")
    rc, judged, _ = red(capsys, "tests/test_new.py")
    got = by_name(judged, "tests/test_new.py")
    assert set(got) == {"test_one", "test_two"}
    assert {c for c, _ in got.values()} == {"missing behaviour"}
    assert all(why == "ModuleNotFoundError: No module named 'pkg.redcheck'" for _, why in got.values())
    assert rc == 0


# ---------------- AC-205.5 (#956): only the repo's own code is missing behaviour ----------------

def test_a_missing_third_party_package_is_a_test_error_naming_the_dev_dependency_ac_205_5(world, capsys):  # AC-205.5
    world.put("tests/test_red.py", "def test_a():\n    import testcontainers_956  # noqa: F401\n")
    world.put("tests/test_top.py", "import testcontainers_956.postgres\n\n\ndef test_b():\n    assert True\n")
    rc, judged, _ = red(capsys, "tests/test_red.py")
    assert by_name(judged)["test_a"] == ("test error", "testcontainers_956 is not installed: add it to the dev dependencies")
    assert rc == 1
    rc, judged, _ = red(capsys, "tests/test_top.py")                          # at collection too
    assert by_name(judged, "tests/test_top.py")["test_b"] == (
        "test error", "testcontainers_956 is not installed: add it to the dev dependencies")
    assert rc == 1


def test_own_code_importing_a_missing_package_is_a_test_error_ac_205_5(world, capsys):  # AC-205.5
    world.put("pkg/store.py", "import testcontainers_956  # noqa: F401\n")
    world.put("tests/test_red.py", "def test_a():\n    import pkg.store  # noqa: F401\n")
    rc, judged, _ = red(capsys, "tests/test_red.py")
    assert by_name(judged)["test_a"] == ("test error", "testcontainers_956 is not installed: add it to the dev dependencies")
    assert rc == 1


def test_a_missing_name_of_an_installed_package_is_a_test_error_ac_205_5(world, capsys):  # AC-205.5
    world.put("tests/test_red.py", "def test_a():\n    from json import no_such_name_956  # noqa: F401\n")
    rc, judged, _ = red(capsys, "tests/test_red.py")
    cls, why = by_name(judged)["test_a"]
    assert cls == "test error" and why.startswith("ImportError: ") and "no_such_name_956" in why
    assert rc == 1


def test_a_missing_own_package_is_missing_behaviour_ac_205_5(world, capsys):  # AC-205.5
    world.put("pyproject.toml", '[project]\nname = "my-service"\n')
    world.put("tests/test_red.py", "def test_a():\n    import my_service  # noqa: F401\n")
    rc, judged, _ = red(capsys, "tests/test_red.py")
    assert by_name(judged)["test_a"] == ("missing behaviour", "ModuleNotFoundError: No module named 'my_service'")
    assert rc == 0


def test_a_new_module_of_a_package_under_src_is_missing_behaviour_ac_205_5(world, capsys):  # AC-205.5
    world.put("src/mylib/__init__.py", "")
    world.put("tests/test_red.py", "def test_a():\n    from mylib import newmod  # noqa: F401\n\n\n"
                                   "def test_b():\n    import mylib.other  # noqa: F401\n")
    rc, judged, _ = red(capsys, "tests/test_red.py")
    got = by_name(judged)
    assert got["test_a"][0] == "missing behaviour" and got["test_b"][0] == "missing behaviour"
    assert rc == 0


def test_any_other_collection_error_is_a_test_error_ac_205_5(world, capsys):  # AC-205.5
    world.put("tests/test_bad.py", "value = undefined_name\n\n\ndef test_one():\n    assert value\n")
    rc, judged, _ = red(capsys, "tests/test_bad.py")
    got = by_name(judged, "tests/test_bad.py")
    assert got["test_one"][0] == "test error" and got["test_one"][1].startswith("NameError: ")
    assert rc == 1


def test_an_import_error_naming_a_test_module_is_a_test_error_ac_205_5(world, capsys):  # AC-205.5
    world.put("tests/test_imp.py", "def test_one():\n    from tests import nothing  # noqa: F401\n")
    rc, judged, _ = red(capsys, "tests/test_imp.py")
    assert by_name(judged, "tests/test_imp.py")["test_one"][0] == "test error"
    assert rc == 1


def test_an_exception_in_a_conftest_is_a_test_error_ac_205_5(world, capsys):  # AC-205.5
    world.put("tests/conftest.py", "import pytest\n\n\n@pytest.fixture()\ndef client():\n    return {}['missing']\n")
    world.put("tests/test_c.py", "def test_one(client):\n    assert client\n")
    rc, judged, _ = red(capsys, "tests/test_c.py")
    assert by_name(judged, "tests/test_c.py")["test_one"][0] == "test error"
    assert rc == 1


def test_the_check_writes_its_record_for_the_freeze_gate_ac_205_5(world, capsys):  # AC-205.5
    text = "def test_a():\n    assert 1 == 2\n"
    world.put("tests/test_red.py", text)
    assert red(capsys, "tests/test_red.py::test_a")[0] == 0
    rec = json.loads((world.root / ".git" / "cplat-red-check.json").read_text())
    assert rec["exit"] == 0 and rec["files"] == {"tests/test_red.py": hashlib.sha256(text.encode()).hexdigest()}
    assert rec["head"] is not None and rec["at"]
    world.put("tests/test_red.py", "def test_a():\n    assert True\n")
    assert red(capsys, "tests/test_red.py")[0] == 1
    assert json.loads((world.root / ".git" / "cplat-red-check.json").read_text())["exit"] == 1


# ---------------- AC-205.5: exit 2 with the usage line ----------------

def test_a_repo_whose_test_fast_does_not_run_pytest_gets_the_usage_line_ac_205_5(world, capsys):  # AC-205.5
    (world.root / "devbox.json").write_text(json.dumps({"shell": {"scripts": {"test-fast": "go test ./..."}}}))
    capsys.readouterr()
    assert quiet.main(["test-fast", "--red", "--", "x_test.go"]) == 2
    assert capsys.readouterr().err.strip() == USAGE
    assert world.calls() == []                                    # nothing ran


@pytest.mark.parametrize("argv", [
    ["test-fast", "--red"], ["test-fast", "--red", "--"], ["test-fast", "--red", "--repeat", "2", "--", "tests/a.py"],
    ["test-fast", "--repeat", "2", "--red", "--", "tests/a.py"], ["quality", "--red", "--", "tests/a.py"],
    ["--raw", "test-fast", "--red"],
])
def test_other_forms_of_the_flag_are_refused_with_the_usage_line_ac_205_5(world, capsys, argv):  # AC-205.5
    capsys.readouterr()
    assert quiet.main(argv) == 2
    assert capsys.readouterr().err.strip() == USAGE
    assert world.calls() == []


def test_the_usage_line_names_the_flag_for_every_refusal_ac_205_5(world, capsys):  # AC-205.5
    capsys.readouterr()
    assert quiet.main(["test-fast", "tests/a.py"]) == 2
    assert capsys.readouterr().err.strip() == USAGE
