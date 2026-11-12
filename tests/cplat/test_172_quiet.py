"""Spec 172: `cplat quiet test-fast [--repeat N] -- <test args>` and the platform's `test-fast` with arguments (AC-172.3, AC-172.5).

Seam: `quiet.main(argv)` with a fake `devbox` on PATH that logs its argument list per call in $FAKE_DIR (one argument per line):
- a run started with CPLAT_REPEAT_RUN=<i> writes `rargs-<i>`, waits (bounded) until all $FAKE_N runs have started (proof that they run
  at once, `barrier-missed` otherwise), prints `rout-<i>` and exits 1 when that file exists, else passes;
- any other call is numbered k = 1, 2, ...: `cargs-<k>`; it prints `cout-<k>` when present and exits with the number in `crc-<k>` (default 0).
`scripts/test-fast.sh` runs under a fake `uv` that logs its arguments.
"""
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

import quiet
from waiting import fake_prelude, with_prelude
from failsum_support import sample

ROOT = Path(__file__).resolve().parents[2]

FAKE_DEVBOX = """#!/bin/sh
d="$FAKE_DIR"
if [ -n "$CPLAT_REPEAT_RUN" ]; then
  i="$CPLAT_REPEAT_RUN"
  printf '%s\\n' "$@" > "$d/rargs-$i"
  : > "$d/started-$i"
  n=0
  while [ "$(ls "$d" | grep -c '^started-')" -lt "${FAKE_N:-1}" ] && [ "$n" -lt 200 ]; do sleep 0.05; n=$((n+1)); done
  if [ "$(ls "$d" | grep -c '^started-')" -lt "${FAKE_N:-1}" ]; then : > "$d/barrier-missed"; fi
  if [ -f "$d/rout-$i" ]; then cat "$d/rout-$i"; exit 1; fi
  echo "1 passed"
  exit 0
fi
k=$(( $(ls "$d" | grep -c '^calls-') + 1 ))
: > "$d/calls-$k"
printf '%s\\n' "$@" > "$d/cargs-$k"
[ -f "$d/cout-$k" ] && cat "$d/cout-$k"
[ -f "$d/crc-$k" ] && exit "$(cat "$d/crc-$k")"
echo "1 passed"
exit 0
"""

USAGE = ("usage: cplat quiet [--raw] <devbox-script> | cplat quiet [--raw] test-fast [--repeat N] -- <test args>   "
         "(a key of shell.scripts in ./devbox.json; only test-fast takes arguments, after --)")
A = "tests/test_x.py::test_a"
B = "tests/test_x.py::test_b"


def pytest_out(*names):
    parts = ["tests/test_x.py " + "F" * len(names) + "                                [100%]\n",
             "=================================== FAILURES ===================================\n"]
    for n in names:
        parts.append(f"______________________ {n} _______________________\ntests/test_x.py:40: in {n}\n    assert elapsed < 3\n"
                     "E   assert 3.2 < 3\n")
    parts.append("=========================== short test summary info ============================\n")
    parts += [f"FAILED tests/test_x.py::{n} - assert 3.2 < 3\n" for n in names]
    parts.append(f"========================= {len(names)} failed, 1 passed in 4.10s ==========================\n")
    return "".join(parts)


class World:
    def __init__(self, d, cache, added):
        self.d, self.cache, self.added = d, cache, added

    def put(self, name, text):
        (self.d / name).write_text(text)

    def args(self, name):
        """The fake devbox's argv without `-e KEY=VALUE` pairs: since spec 185, `cplat quiet` passes the progress plugin's
        directory with `devbox run -e PYTHONPATH=…`, because devbox resets PYTHONPATH; the command itself is unchanged."""
        argv, out = (self.d / name).read_text().splitlines(), []
        skip = False
        for a in argv:
            if skip:
                skip = False
            elif a in ("-e", "--env"):
                skip = True
            else:
                out.append(a)
        return out

    def files(self, prefix):
        return sorted(p.name for p in self.d.iterdir() if p.name.startswith(prefix))

    def logs(self):
        return sorted((self.cache / "sdlc-foundry" / "logs" / "myrepo").glob("*.log"))


@pytest.fixture()
def world(tmp_path, monkeypatch):
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
    added = []
    monkeypatch.setattr(runs, "current_run", lambda r: "run-1")
    monkeypatch.setattr(runs, "add_to", lambda rid, name, item, **k: added.append((name, item)))
    return World(d, tmp_path / "cache", added)


def repeat(monkeypatch, w, n, *tests):
    monkeypatch.setenv("FAKE_N", str(n))
    return quiet.main(["test-fast", "--repeat", str(n), "--", *tests])


# ---------------- AC-172.3: arguments reach the test runner unchanged ----------------

def test_arguments_after_dashes_reach_devbox_test_fast_unchanged_ac_172_3(world, capsys):  # AC-172.3
    assert quiet.main(["test-fast", "--", "tests/a.py", "-k", "x or y"]) == 0
    assert world.args("cargs-1") == ["run", "test-fast", "--", "tests/a.py", "-k", "x or y"]
    printed = capsys.readouterr().out
    assert printed.startswith("ok: devbox run test-fast (") and printed.endswith("1 passed\n")
    assert [p.name.split("-", 2)[2] for p in world.logs()] == ["test-fast.log"]


def test_nothing_after_the_dashes_is_the_same_as_no_arguments_ac_172_3(world):  # AC-172.3
    assert quiet.main(["test-fast", "--"]) == 0
    assert world.args("cargs-1") == ["run", "test-fast"]


def test_a_failure_with_arguments_prints_the_summary_with_the_arguments_ac_172_3(world, capsys):  # AC-172.3
    world.put("cout-1", sample("mypy.log"))
    world.put("crc-1", "1")
    assert quiet.main(["test-fast", "--", "tests/a.py"]) == 1
    printed = capsys.readouterr().out
    assert printed.startswith("FAILED (exit 1): devbox run test-fast") and "command: devbox run test-fast -- tests/a.py |" in printed
    (log,) = world.logs()
    assert Path(str(log) + ".summary.json").exists()


def test_a_flaky_failure_with_arguments_is_rerun_alone_as_before_ac_172_3(world, capsys):  # AC-172.3
    world.put("cout-1", pytest_out("test_a"))
    world.put("crc-1", "1")
    assert quiet.main(["test-fast", "--", "tests/test_x.py"]) == 0
    printed = capsys.readouterr().out
    assert "flaky: 1 test(s) failed, then passed when run again alone" in printed and "flaky: tests/test_x.py::test_a" in printed
    assert world.args("cargs-1") == ["run", "test-fast", "--", "tests/test_x.py"]
    assert world.args("cargs-2") == ["run", "test-fast", "--", "tests/test_x.py::test_a"]
    assert world.added == [("flaky_tests", {"test": "tests/test_x.py::test_a", "script": "test-fast"})]


@pytest.mark.parametrize("argv", [
    ["quality", "--", "tests/a.py"], ["quality", "tests/a.py"], ["quality", "--repeat", "2", "--", "x"],
    ["test-fast", "tests/a.py"], ["test-fast", "-k", "x"], ["nosuch"], ["nosuch", "--", "x"],
    ["--raw", "test-fast", "tests/a.py"], [],
])
def test_other_forms_are_refused_with_the_usage_line_and_exit_2_ac_172_3(world, capsys, argv):  # AC-172.3
    assert quiet.main(argv) == 2
    assert capsys.readouterr().err.strip() == USAGE
    assert world.files("") == []                          # devbox never ran


def test_the_platform_test_fast_recipe_and_script_take_arguments_ac_172_3():  # AC-172.3
    recipe = json.loads((ROOT / "devbox.json").read_text())["shell"]["scripts"]["test-fast"]
    assert 'bash scripts/test-fast.sh "$@"' in recipe        # with arguments; spec 127 keeps the literal suite line beside it (approved 2026-11-10)
    assert (ROOT / "scripts" / "test-fast.sh").is_file()


@pytest.mark.parametrize("args,targets", [
    ([], ["tests/cplat"]),
    (["tests/cplat/test_169_red_freeze.py"], ["tests/cplat/test_169_red_freeze.py"]),
    (["tests/cplat/test_169_red_freeze.py::test_a_unit_commit_off_the_branch_is_ignored_ac_169_2"],
     ["tests/cplat/test_169_red_freeze.py::test_a_unit_commit_off_the_branch_is_ignored_ac_169_2"]),
    (["-k", "red_freeze"], ["tests/cplat", "-k", "red_freeze"]),
    (["-x"], ["tests/cplat", "-x"]),
], ids=["no-args", "a-file", "a-node-id", "k-expression", "option-only"])
def test_the_platform_test_fast_runs_only_the_given_tests_ac_172_3(tmp_path, args, targets):  # AC-172.3
    bindir = tmp_path / "bin"
    bindir.mkdir()
    uv = bindir / "uv"
    uv.write_text(with_prelude('#!/bin/sh\nprintf \'%s\\n\' "$@" > "$UV_OUT"\n'))
    uv.chmod(uv.stat().st_mode | stat.S_IEXEC)
    out = tmp_path / "uv-args.txt"
    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}", "UV_OUT": str(out)}
    subprocess.run(["bash", "scripts/test-fast.sh", *args], cwd=ROOT, env=env, capture_output=True, check=False)
    assert out.exists(), "scripts/test-fast.sh did not run uv"
    got = out.read_text().splitlines()
    assert got[:7] == ["run", "--with-requirements", "requirements-test.txt", "pytest", "-q", "-n", "auto"]
    assert got[7:] == targets


@pytest.mark.parametrize("template", ["service-python", "library-python", "service-go", "service-java", "web-nextjs"])
def test_every_template_test_fast_recipe_ends_in_the_arguments_ac_172_3(template):  # AC-172.3
    path = next((ROOT / "templates" / template).glob("devbox.json*"))
    line = next(ln for ln in path.read_text().splitlines() if ln.strip().startswith('"test-fast"'))
    assert line.rstrip().rstrip(",").endswith('\\"$@\\""')


@pytest.mark.parametrize("template", ["service-python", "library-python"])
def test_a_python_template_test_fast_runs_only_the_given_file_or_k_expression_ac_172_3(template, tmp_path):  # AC-172.3
    path = ROOT / "templates" / template / "devbox.json"
    line = next(ln for ln in path.read_text().splitlines() if ln.strip().startswith('"test-fast"'))
    recipe = line.strip().rstrip(",").split(":", 1)[1].strip()[1:-1].replace('\\"', '"')    # the template is not plain JSON
    runner = recipe.split(" -- ", 1)[1]                      # the test runner's own command, after the gate script's `--`
    runner = runner.replace("uv run python", sys.executable).replace("uv run pytest", f"{sys.executable} -m pytest")
    runner = runner.replace("-p scripts.smoke_pytest", "").replace("-q", "-v")
    assert '"$@"' in runner and "uv" not in runner.split()
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_one.py").write_text("def test_alpha():\n    pass\n\n\ndef test_beta():\n    pass\n")
    (tmp_path / "tests" / "test_two.py").write_text("def test_gamma():\n    pass\n")

    def ran(*args):
        p = subprocess.run(["sh", "-c", runner, "sh", *args], cwd=tmp_path, capture_output=True, text=True, check=False,
                           env={**os.environ, "PYTHONPATH": ""})
        assert p.returncode == 0, p.stdout + p.stderr
        return sorted(ln.split()[0] for ln in p.stdout.splitlines() if " PASSED" in ln)

    assert ran() == ["tests/test_one.py::test_alpha", "tests/test_one.py::test_beta", "tests/test_two.py::test_gamma"]
    assert ran("tests/test_two.py") == ["tests/test_two.py::test_gamma"]
    assert ran("-k", "alpha or gamma") == ["tests/test_one.py::test_alpha", "tests/test_two.py::test_gamma"]


# ---------------- AC-172.5: --repeat ----------------

@pytest.mark.parametrize("argv", [
    ["--repeat", "1", "--", "tests/a.py"], ["--repeat", "6", "--", "tests/a.py"], ["--repeat", "0", "--", "tests/a.py"],
    ["--repeat", "x", "--", "tests/a.py"], ["--repeat", "3"], ["--repeat", "3", "--"], ["--repeat", "--", "tests/a.py"],
    ["--repeat"],
])
def test_repeat_without_tests_or_with_n_outside_2_to_5_is_refused_ac_172_5(world, capsys, argv):  # AC-172.5
    assert quiet.main(["test-fast", *argv]) == 2
    assert capsys.readouterr().err.strip() == USAGE
    assert world.files("") == []


def test_n_runs_start_at_the_same_time_and_all_pass_ac_172_5(world, monkeypatch, capsys):  # AC-172.5
    assert repeat(monkeypatch, world, 3, "tests/a.py", "tests/b.py") == 0
    assert world.files("barrier-missed") == [], "the runs did not overlap"
    assert [world.args(f"rargs-{i}") for i in (1, 2, 3)] == [["run", "test-fast", "--", "tests/a.py", "tests/b.py"]] * 3
    assert world.files("calls-") == [] and world.added == []
    assert capsys.readouterr().out.startswith("ok: 3 runs at once of devbox run test-fast passed (logs: ")
    assert len(world.logs()) == 3


@pytest.mark.parametrize("n", [2, 5])
def test_the_limits_of_n_are_accepted_ac_172_5(world, monkeypatch, n):  # AC-172.5
    assert repeat(monkeypatch, world, n, "tests/a.py") == 0
    assert len(world.files("rargs-")) == n and world.files("barrier-missed") == []


def test_a_test_that_fails_under_load_and_passes_alone_is_flaky_exit_3_ac_172_5(world, monkeypatch, capsys):  # AC-172.5
    world.put("rout-2", pytest_out("test_a"))
    assert repeat(monkeypatch, world, 3, "tests/test_x.py") == 3
    printed = capsys.readouterr().out
    assert f"flaky under load: {A} (failed in 1 of 3 runs)" in printed
    assert "FLAKY: 1 test(s) failed under load and passed alone; fix the harness before the pull request" in printed.splitlines()[-1]
    assert world.args("cargs-1") == ["run", "test-fast", "--", A] and world.files("calls-") == ["calls-1"]
    assert world.added == [("flaky_tests", {"test": A, "script": "test-fast", "repeat": 3, "failed_runs": 1})]


def test_the_count_is_the_number_of_runs_the_test_failed_in_ac_172_5(world, monkeypatch, capsys):  # AC-172.5
    world.put("rout-1", pytest_out("test_a"))
    world.put("rout-3", pytest_out("test_a"))
    assert repeat(monkeypatch, world, 3, "tests/test_x.py") == 3
    assert f"flaky under load: {A} (failed in 2 of 3 runs)" in capsys.readouterr().out
    assert world.files("calls-") == ["calls-1"]                 # one rerun alone per distinct test
    assert [item["failed_runs"] for _, item in world.added] == [2]


def test_a_test_that_fails_alone_too_exits_1_and_never_0_ac_172_5(world, monkeypatch, capsys):  # AC-172.5
    world.put("rout-1", pytest_out("test_a"))
    world.put("cout-1", pytest_out("test_a"))
    world.put("crc-1", "1")
    assert repeat(monkeypatch, world, 2, "tests/test_x.py") == 1
    printed = capsys.readouterr().out
    assert "flaky under load" not in printed and "FAILED (exit 1): devbox run test-fast -- " + A in printed
    assert world.added == []


def test_one_flaky_and_one_failing_test_exit_1_and_name_the_flaky_one_ac_172_5(world, monkeypatch, capsys):  # AC-172.5
    world.put("rout-1", pytest_out("test_a", "test_b"))
    world.put("rout-2", pytest_out("test_a"))
    world.put("cout-2", pytest_out("test_b"))          # sorted: test_a alone is call 1 (passes), test_b alone is call 2 (fails)
    world.put("crc-2", "1")
    assert repeat(monkeypatch, world, 2, "tests/test_x.py") == 1
    printed = capsys.readouterr().out
    assert f"flaky under load: {A} (failed in 2 of 2 runs)" in printed and f"flaky under load: {B}" not in printed
    assert world.args("cargs-1") == ["run", "test-fast", "--", A] and world.args("cargs-2") == ["run", "test-fast", "--", B]
    assert [item["test"] for _, item in world.added] == [A]


def test_a_failure_that_names_no_test_exits_1_without_reruns_ac_172_5(world, monkeypatch, capsys):  # AC-172.5
    world.put("rout-2", "Traceback (most recent call last):\n  boom\nRuntimeError: no tests ran\n")
    assert repeat(monkeypatch, world, 2, "tests/test_x.py") == 1
    printed = capsys.readouterr().out
    assert "FAILED under load: a failure not attributable to named tests" in printed
    assert "FAILED (exit 1): devbox run test-fast -- tests/test_x.py" in printed       # the failure summary is printed first
    assert "RuntimeError: no tests ran" in printed
    assert world.files("calls-") == [] and world.added == []
