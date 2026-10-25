"""Spec 107: benchmark arms (`cplat runs benchmark <wf> --arm NAME`) and `--recall`. Git, gh and the headless driver are
replaced (the `world` fixture of the spec 099 tests); the arms under test live in a temporary copy of benchmark/."""
import json
import shutil
from pathlib import Path

import pytest

import core
import runs
import runs_bench
from core import PlatformError
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)
from test_runs_report import put, rec, report_json
from test_runs_usage_bench import benchmark_records, tasks, world  # noqa: F401  (fixtures)
from usage_support import projects, stored_records  # noqa: F401

REAL_BENCH = core.PLATFORM_ROOT / "scripts" / "cplat" / "benchmark"
ARM = {"name": "probe", "candidate": "probe-tool", "workflows": ["quick-task", "build"],
       "files": {"probe.cfg": "probe = on\n"}, "commands": [["probe-tool", "--install"]], "note": "test arm"}


@pytest.fixture()
def arms(world, monkeypatch, tmp_path):
    """A copy of benchmark/ with the arm `probe` (and `broken`, whose command fails); records every command with its cwd and
    what the clone looked like when the session started."""
    bench = tmp_path / "bench"
    shutil.copytree(REAL_BENCH, bench)
    (bench / "arms").mkdir(exist_ok=True)
    (bench / "arms" / "probe.json").write_text(json.dumps(ARM))
    (bench / "arms" / "broken.json").write_text(json.dumps({**ARM, "name": "broken", "commands": [["broken-tool", "--boom"]]}))
    monkeypatch.setattr(runs_bench, "BENCH_DIR", bench)
    world.calls = []          # (cmd, cwd)
    world.at_session = None   # snapshot taken when the session starts
    world.suite_exit = 0
    world.suite_out = ""

    def run(cmd, cwd=None):
        cmd = [str(c) for c in cmd]
        world.calls.append((cmd, str(cwd) if cwd else None))
        if cmd[0] == "broken-tool":
            return 1, "", "boom: cannot install"
        if cmd[0] not in ("git", "gh", "probe-tool") and "pytest" in " ".join(cmd) and "--force" not in cmd:
            return world.suite_exit, world.suite_out, ""
        return world.run(cmd, cwd)
    monkeypatch.setattr(runs_bench, "run", run)

    import headless
    inner = headless.main

    def headless_main(argv):
        if world.at_session is None:
            clone = Path(argv[argv.index("--repo") + 1])
            world.at_session = {"calls": len(world.calls), "probe": (clone / "probe.cfg").read_text() if (clone / "probe.cfg").exists() else None}
        return inner(argv)
    monkeypatch.setattr(headless, "main", headless_main)
    return world


def before_session(w):
    return w.calls[:w.at_session["calls"]]


def test_the_arm_is_applied_committed_and_pushed_before_the_session_and_the_reset_still_runs(arms, store):
    """AC-107.9: files written, commands run in the clone, commit `bench: arm probe`, push to main, then the session; reset after."""
    assert runs.main(["benchmark", "quick-task", "--arm", "probe"]) == 0
    assert arms.at_session["probe"] == "probe = on\n"
    pre = before_session(arms)
    clone = str(runs.state_dir() / "benchmark" / "quick-task")
    assert (["probe-tool", "--install"], clone) in pre
    commit = [i for i, (c, _) in enumerate(pre) if "commit" in c and "bench: arm probe" in c]
    push = [i for i, (c, _) in enumerate(pre) if "push" in c and "--force" not in c]
    assert commit and push and max(commit) < max(push)
    assert pre.index((["probe-tool", "--install"], clone)) < commit[0]
    assert arms.pushed()[-1][-1] == f"{tasks()['sample']['rev']}:refs/heads/main"   # the reset removes the arm
    (r,) = benchmark_records(store)
    assert r["benchmark"]["reset"] == "done"


def test_the_reset_also_runs_when_a_session_with_an_arm_fails(arms, store, monkeypatch):
    """AC-107.9: a failing session still resets the sample repo."""
    import headless
    monkeypatch.setattr(headless, "main", lambda argv: 1)
    runs.main(["benchmark", "quick-task", "--arm", "probe"])
    (r,) = benchmark_records(store)
    assert r["outcome"] == "failed" and r["benchmark"]["reset"] == "done" and arms.pushed()


def test_the_record_names_the_arm_and_a_run_without_arm_is_baseline(arms, store):
    """AC-107.10: benchmark.arm is the arm's name, `baseline` without --arm."""
    assert runs.main(["benchmark", "quick-task", "--arm", "probe"]) == 0
    assert runs.main(["benchmark", "quick-task"]) == 0
    assert sorted(r["benchmark"]["arm"] for r in benchmark_records(store)) == ["baseline", "probe"]
    assert not any("bench: arm" in " ".join(c) for c, _ in arms.calls[arms.at_session["calls"]:] if "commit" in c)


@pytest.mark.parametrize("argv", [
    ["benchmark", "quick-task", "--arm", "no-such-arm"],        # unknown arm
    ["benchmark", "ship", "--arm", "probe"],                    # the arm does not list the workflow
    ["benchmark", "quick-task", "--arm", "broken"],             # an arm command fails
])
def test_a_refused_arm_exits_non_zero_before_any_session_and_writes_no_record(arms, store, argv, capsys):
    """AC-107.9: unknown arm, workflow not listed, failing arm command: non-zero, no session, no record."""
    with pytest.raises((PlatformError, SystemExit)) as e:
        runs.main(argv)
    assert getattr(e.value, "code", 1) != 0
    said = str(e.value) + capsys.readouterr().err
    assert "unrecognized arguments" not in said, "--arm is not a known option yet"
    assert argv[-1] in said
    assert arms.headless_calls == [] and benchmark_records(store) == []


def test_the_failing_arm_command_is_named(arms, store):
    """AC-107.9: the refusal names the arm command that failed."""
    with pytest.raises(PlatformError, match="broken"):
        runs.main(["benchmark", "quick-task", "--arm", "broken"])


def _bench(store, rid, arm, tokens, plugins=None):
    z = {"calls": 1, "failed_calls": 0, "input": tokens, "output": 0, "cache_read": 0, "cache_write": 0, "cost_usd": 1.0}
    u = {"sessions": ["s"], "price_table": "2026-10-25", "incomplete": None,
         "totals": {**z, "cost_complete": True, "models_without_price": []}, "by_phase": {}, "by_role": {}, "by_model": {}}
    b = {"workflow": "build", "task_version": 4, "sample_repo": "ika100/todo-api", "sample_rev": "a" * 40, "reset": "done",
         "reset_note": None, "coordinator_model": "sonnet"}
    if arm is not None:
        b["arm"] = arm
    r = rec(rid, "2026-10-22T10:00:00Z", kind="benchmark", outcome="done", usage=u, benchmark=b)
    r["platform_version"] = "4.6.0"
    put(store, r)


def test_the_report_row_key_carries_the_arm(store, capsys):
    """AC-107.2: runs of different arms are different rows: `<version> (<model>) {<arm>}`; baseline runs are `{baseline}`."""
    _bench(store, "a1", "baseline", 1000)
    _bench(store, "a2", "baseline", 1200)
    _bench(store, "t1", "testmon", 500)
    rows = report_json(capsys, "--benchmarks")["benchmarks"]["build"]
    assert set(rows) == {"4.6.0 (sonnet) {baseline}", "4.6.0 (sonnet) {testmon}"}
    assert rows["4.6.0 (sonnet) {baseline}"]["runs"] == 2 and rows["4.6.0 (sonnet) {testmon}"]["tokens_median"] == 500


def test_a_record_without_arm_counts_as_baseline_in_the_report(store, capsys):
    """AC-107.10: records written before arms existed are baseline runs, and stay in the same row as `baseline` ones."""
    _bench(store, "old", None, 1000)
    _bench(store, "new", "baseline", 3000)
    rows = report_json(capsys, "--benchmarks")["benchmarks"]["build"]
    assert list(rows) == ["4.6.0 (sonnet) {baseline}"] and rows["4.6.0 (sonnet) {baseline}"]["runs"] == 2


def test_the_text_report_shows_the_arm(store, capsys):
    """AC-107.2: the text report names the arm in the row."""
    _bench(store, "t1", "testmon", 500)
    assert runs.main(["report", "--benchmarks"]) == 0
    assert "build 4.6.0 (sonnet) {testmon}" in capsys.readouterr().out


# ---------------- --recall ----------------

def test_recall_runs_the_full_suite_after_the_session_and_before_the_reset(arms, store):
    """AC-107.3: with --recall the full suite runs in the clone after the session; all green keeps the record done."""
    arms.suite_out = "== 12 passed =="
    assert runs.main(["benchmark", "quick-task", "--arm", "probe", "--recall"]) == 0
    clone = str(runs.state_dir() / "benchmark" / "quick-task")
    after = arms.calls[arms.at_session["calls"]:]
    suite = [i for i, (c, cwd) in enumerate(after) if "pytest" in " ".join(c) and cwd == clone]
    reset = [i for i, (c, _) in enumerate(after) if "--force" in c and "push" in c]
    assert suite and max(suite) < reset[-1]
    (r,) = benchmark_records(store)
    assert r["outcome"] == "done"


def test_a_deselected_failing_test_fails_the_record_with_a_named_reason(arms, store):
    """AC-107.3: the session ended green but the full suite has a failing test the arm's selection skipped: record failed, test named."""
    arms.suite_exit = 1
    arms.suite_out = "FAILED tests/test_todos_api.py::test_list_todos - assert 1 == 2\n== 1 failed, 11 passed =="
    assert runs.main(["benchmark", "quick-task", "--arm", "probe", "--recall"]) == 1
    (r,) = benchmark_records(store)
    assert r["outcome"] == "failed" and r["benchmark"]["reset"] == "done"
    assert "tests/test_todos_api.py::test_list_todos" in r["benchmark"]["result_check"]
    assert "recall" in r["benchmark"]["result_check"].lower()


def test_without_recall_the_full_suite_is_not_run(arms, store):
    """AC-107.3: --recall is opt-in."""
    assert runs.main(["benchmark", "quick-task", "--arm", "probe"]) == 0
    assert not [c for c, _ in arms.calls[arms.at_session["calls"]:] if "pytest" in " ".join(c)]


# ---------------- shipped arms ----------------

SHIPPED = ["testmon", "pytest-impact", "semgrep", "trivy", "codebase-memory"]


@pytest.mark.parametrize("name", SHIPPED)
def test_a_shipped_arm_is_well_formed_and_names_only_existing_workflows(name):
    """AC-107.1: each candidate has an arm file with the contract's keys, naming only workflows that tasks.json defines."""
    path = REAL_BENCH / "arms" / f"{name}.json"
    assert path.is_file(), f"missing arm {path}"
    arm = json.loads(path.read_text())
    assert set(arm) >= {"name", "candidate", "workflows", "files", "commands", "note"}
    assert arm["name"] == name and arm["candidate"] and arm["note"]
    assert arm["workflows"] and set(arm["workflows"]) <= set(tasks()["workflows"])
    assert isinstance(arm["files"], dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in arm["files"].items())
    assert isinstance(arm["commands"], list) and all(isinstance(c, list) and c and all(isinstance(a, str) for a in c) for c in arm["commands"])
    assert arm["files"] or arm["commands"]


def test_the_change_aware_test_arms_run_on_build():
    """AC-107.1: testmon and pytest-impact are measured on the build workflow (design)."""
    for name in ("testmon", "pytest-impact"):
        assert "build" in json.loads((REAL_BENCH / "arms" / f"{name}.json").read_text())["workflows"]
