"""Spec 099: `cplat runs benchmark` (AC-099.13, AC-099.15) and `cplat runs report --benchmarks`. Git, gh and the headless
driver are replaced; no network, no real clone, no real Claude session."""
import datetime as dt
import json
import re
from pathlib import Path

import pytest

import core
import runs
from core import PlatformError
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)
from test_runs_report import put, rec, report_json
from usage_support import call, projects, stored_records, write_session  # noqa: F401

TASKS = core.PLATFORM_ROOT / "scripts" / "cplat" / "benchmark" / "tasks.json"


def tasks():
    return json.loads(TASKS.read_text())


class World:
    """Fake git / gh: one remote `main`, a log of commands, switches for the failure cases."""

    def __init__(self):
        self.log: list[list[str]] = []
        self.main = None                     # None = the pinned revision
        self.reachable = True
        self.push_ok = True
        self.delivered_pr = None             # the PR number a successful run opened (or merged)

    def rev(self):
        return tasks()["sample"]["rev"]

    def run(self, cmd, cwd=None):
        cmd = [str(c) for c in cmd]
        self.log.append(cmd)
        line = " ".join(cmd)
        if cwd:
            Path(cwd).mkdir(parents=True, exist_ok=True)
        if "clone" in cmd:
            Path(cmd[-1]).mkdir(parents=True, exist_ok=True)
        if "ls-remote" in cmd:
            if not self.reachable:
                return 128, "", "fatal: unable to access"
            return 0, f"{self.main or self.rev()}\trefs/heads/main\n", ""
        if "push" in cmd and "--force" in cmd:
            if not self.push_ok:
                return 1, "", "remote: permission denied"
            self.main = None
            return 0, "", ""
        if cmd[:3] == ["gh", "pr", "list"] and self.delivered_pr and cmd[cmd.index("--state") + 1] in ("open", "merged", "all"):
            return 0, json.dumps([{"number": self.delivered_pr}]), ""
        if cmd[0] == "gh":
            return 0, "[]", ""
        return 0, "", ""

    def pushed(self):
        return [c for c in self.log if "push" in c and "--force" in c and any(a.endswith(":refs/heads/main") for a in c)]


@pytest.fixture()
def world(clock, store, projects, monkeypatch):
    import headless
    import runs_bench
    import runs_usage
    import transcripts
    w = World()
    w.headless_calls = []
    monkeypatch.setattr(runs_bench, "run", w.run)
    monkeypatch.setattr(runs_bench, "trusted", lambda clone: True)

    def fake_headless(argv):
        w.headless_calls.append(argv)
        clone = Path(argv[argv.index("--repo") + 1])
        write_session(projects, "bench-session", [call("b1", 5), call("b2", 6)], slug=transcripts.cwd_slug(clone))
        clock.now += dt.timedelta(seconds=30)
        w.delivered_pr = 12
        w.env = {k: __import__("os").environ.get(k) for k in ("CPLAT_RUN_PARENT", "CPLAT_BENCHMARK", "CPLAT_PLATFORM")}
        return 0
    monkeypatch.setattr(headless, "main", fake_headless)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "")
    return w


def benchmark_records(store):
    return [r for r in stored_records(store) if r["kind"] == "benchmark"]


@pytest.mark.parametrize("workflow", ["quick-task", "build", "ship"])
def test_a_benchmark_appends_one_marked_record_with_usage(world, store, workflow, capsys):  # AC-099.13
    """AC-099.13: one record of kind benchmark naming workflow, task version, sample repo and revision, with usage."""
    assert runs.main(["benchmark", workflow]) == 0
    (r,) = benchmark_records(store)
    t = tasks()
    b = r["benchmark"]
    assert b["workflow"] == workflow and b["task_version"] == t["workflows"][workflow]["task_version"]
    assert b["sample_repo"] == t["sample"]["repo"] and b["sample_rev"] == t["sample"]["rev"] and re.fullmatch(r"[0-9a-f]{40}", b["sample_rev"])
    assert r["usage"]["totals"]["calls"] == 2
    assert world.headless_calls and world.env["CPLAT_BENCHMARK"] == r["run_id"]
    assert "benchmark " + workflow in capsys.readouterr().out


def test_an_unknown_workflow_is_refused_and_writes_no_record(world, store):
    """AC-099.13: unknown workflow: argparse error, non-zero, no record, no git call."""
    with pytest.raises(SystemExit) as e:
        runs.main(["benchmark", "deploy-everything"])
    assert e.value.code != 0
    assert benchmark_records(store) == [] and world.log == []


def test_an_unreachable_sample_repo_is_refused_and_writes_no_record(world, store):
    """AC-099.13: the sample repo cannot be reached: PlatformError naming it, no record, nothing run."""
    world.reachable = False
    with pytest.raises(PlatformError, match=r"sample repo .*todo-api.* cannot be reached"):
        runs.main(["benchmark", "ship"])
    assert benchmark_records(store) == [] and world.headless_calls == []


def test_a_moved_sample_repo_is_refused_without_reset_first(world, store):
    """AC-099.13 (design): main is not at the pinned revision: refuse, no record; --reset-first resets and goes on."""
    world.main = "f" * 40
    with pytest.raises(PlatformError, match="not the pinned"):
        runs.main(["benchmark", "quick-task"])
    assert benchmark_records(store) == [] and world.headless_calls == []
    assert runs.main(["benchmark", "quick-task", "--reset-first"]) == 0
    assert len(world.pushed()) >= 2 and len(benchmark_records(store)) == 1


def test_report_benchmarks_shows_runs_median_and_outcomes_per_workflow_and_version(store, capsys):
    """AC-099.13: `report --benchmarks`: per workflow and platform version the runs, median tokens and cost, and the outcomes."""
    def bench(rid, day, outcome, tokens, cost, version="4.5.0", model=None):
        z = {"calls": 1, "failed_calls": 0, "input": tokens, "output": 0, "cache_read": 0, "cache_write": 0, "cost_usd": cost}
        u = {"sessions": ["s"], "price_table": "2026-10-25", "incomplete": None,
             "totals": {**z, "cost_complete": True, "models_without_price": []}, "by_phase": {}, "by_role": {}, "by_model": {}}
        r = rec(rid, f"2026-10-{day}T10:00:00Z", kind="benchmark", outcome=outcome, usage=u,
                benchmark={"workflow": "ship", "task_version": 1, "sample_repo": "ika100/todo-api", "sample_rev": "a" * 40,
                           "reset": "done", "reset_note": None, **({"coordinator_model": model} if model else {})})
        r["platform_version"] = version
        put(store, r)
    bench("b1", 20, "done", 1000, 1.0)
    bench("b2", 21, "done", 3000, 3.0)
    bench("b3", 22, "failed", 5000, 5.0)
    bench("b4", 22, "done", 10, 0.01, version="4.6.0")
    put(store, rec("plain", "2026-10-22T10:00:00Z"))                                    # not a benchmark
    out = report_json(capsys, "--benchmarks")
    # key gains the arm (spec 107, AC-107.10)
    row = out["benchmarks"]["ship"]["4.5.0 (unknown) {baseline}"]
    assert row["runs"] == 3 and row["outcomes"] == {"done": 2, "failed": 1}
    assert out["benchmarks"]["ship"]["4.6.0 (unknown) {baseline}"]["runs"] == 1 and "window" in out
    assert runs.main(["report", "--benchmarks"]) == 0
    text = capsys.readouterr().out
    assert "ship" in text and "4.5.0" in text and "estimate" in text.lower() and "2026-10-25" in text  # AC-099.7: names the price table date


def test_report_benchmarks_groups_by_coordinator_model_and_medians_done_runs_only(store, capsys):
    """AC-099.13: one row per coordinator model; the median covers done runs, failed runs are shown on their own."""
    def bench(rid, outcome, tokens, cost, model):
        z = {"calls": 1, "failed_calls": 0, "input": tokens, "output": 0, "cache_read": 0, "cache_write": 0, "cost_usd": cost}
        u = {"sessions": ["s"], "price_table": "2026-10-25", "incomplete": None,
             "totals": {**z, "cost_complete": True, "models_without_price": []}, "by_phase": {}, "by_role": {}, "by_model": {}}
        r = rec(rid, "2026-10-22T10:00:00Z", kind="benchmark", outcome=outcome, usage=u,
                benchmark={"workflow": "build", "task_version": 4, "sample_repo": "ika100/todo-api", "sample_rev": "a" * 40,
                           "reset": "done", "reset_note": None, "coordinator_model": model})
        r["platform_version"] = "4.5.0"
        put(store, r)
    bench("o1", "done", 2000, 2.0, "opus")
    bench("o2", "done", 4000, 4.0, "opus")
    bench("s1", "done", 1000, 1.0, "sonnet")
    bench("s2", "done", 1200, 1.2, "sonnet")
    bench("s3", "failed", 9000, 0.4, "sonnet")
    out = report_json(capsys, "--benchmarks")
    # key gains the arm (spec 107, AC-107.10)
    opus, sonnet = out["benchmarks"]["build"]["4.5.0 (opus) {baseline}"], out["benchmarks"]["build"]["4.5.0 (sonnet) {baseline}"]
    assert opus["coordinator_model"] == "opus" and opus["runs"] == 2 and opus["cost_usd_median"] == pytest.approx(3.0)
    assert sonnet["runs"] == 3 and sonnet["done"] == 2 and sonnet["outcomes"] == {"done": 1 + 1, "failed": 1}
    assert sonnet["tokens_median"] == 1100 and sonnet["cost_usd_median"] == pytest.approx(1.1)   # s3 (failed) left out
    assert sonnet["not_done"] == {"runs": 1, "tokens_median": 9000, "cost_usd_median": pytest.approx(0.4)}
    assert opus["not_done"] is None
    assert runs.main(["report", "--benchmarks"]) == 0
    text = capsys.readouterr().out
    assert "build 4.5.0 (sonnet) {baseline}: 3 run(s), median of 2 done" in text and "not done: 1 run(s)" in text
    assert "build 4.5.0 (opus) {baseline}" in text


def test_report_benchmarks_says_no_done_run_when_every_run_failed(store, capsys):
    """AC-099.13: a group without a done run has no median, only its failed runs."""
    u = {"sessions": ["s"], "price_table": "2026-10-25", "incomplete": None, "by_phase": {}, "by_role": {}, "by_model": {},
         "totals": {"calls": 1, "failed_calls": 0, "input": 3, "output": 0, "cache_read": 0, "cache_write": 0, "cost_usd": 0.1,
                    "cost_complete": True, "models_without_price": []}}
    put(store, rec("f1", "2026-10-22T10:00:00Z", kind="benchmark", outcome="failed", usage=u,
                   benchmark={"workflow": "quick-task", "task_version": 2, "coordinator_model": "sonnet"}))
    assert runs.main(["report", "--benchmarks"]) == 0
    text = capsys.readouterr().out
    assert "no done run" in text and "None" not in text and "not done: 1 run(s)" in text


def test_benchmarks_cannot_be_combined_with_agents(store):
    """AC-099.13: `report --benchmarks --agents` is refused."""
    with pytest.raises(PlatformError):
        runs.main(["report", "--benchmarks", "--agents"])


# ---------------- AC-099.15 ----------------

def test_the_sample_repo_is_reset_after_a_ship_and_the_record_says_so(world, store):
    """AC-099.15: after ship the sample repo's main is pushed back to the pinned revision; the record notes the reset."""
    assert runs.main(["benchmark", "ship"]) == 0
    assert any(c[-1] == f"{tasks()['sample']['rev']}:refs/heads/main" for c in world.pushed())
    (r,) = benchmark_records(store)
    assert r["benchmark"]["reset"] == "done"
    names = [p["name"] for p in r["phases"]]
    assert names.index("benchmark:reset") > names.index("benchmark:run")


def test_the_reset_also_runs_when_the_ship_fails(world, store, monkeypatch):
    """AC-099.15: the sample repo is reset when the ship stops without reaching dev; the outcome is failed."""
    import headless
    monkeypatch.setattr(headless, "main", lambda argv: 1)
    runs.main(["benchmark", "ship"])
    (r,) = benchmark_records(store)
    assert r["outcome"] == "failed" and r["benchmark"]["reset"] == "done" and world.pushed()


def test_a_failed_reset_exits_non_zero_names_the_repo_and_still_writes_the_record(world, store):
    """AC-099.15: reset fails -> PlatformError naming the sample repo; the record is written with reset `failed`."""
    world.push_ok = False
    with pytest.raises(PlatformError, match="ika100/todo-api"):
        runs.main(["benchmark", "ship"])
    (r,) = benchmark_records(store)
    assert r["benchmark"]["reset"] == "failed" and r["benchmark"]["reset_note"]


def test_reset_leaves_prs_branches_and_tags_that_existed_before_the_run(monkeypatch, tmp_path):
    """AC-099.15: the reset after a run only undoes what the run created; an open Dependabot PR survives."""
    import runs_bench
    rev = tasks()["sample"]["rev"]
    log: list[str] = []
    heads = f"{rev}\trefs/heads/main\nx\trefs/heads/dependabot/all\ny\trefs/heads/feature/900\n"
    tags = "z\trefs/tags/v0.1.0\nw\trefs/tags/v0.2.0\n"

    def fake(cmd, cwd=None):
        cmd = [str(c) for c in cmd]
        log.append(" ".join(cmd))
        if cmd[:3] == ["gh", "pr", "list"]:
            return 0, '[{"number": 4}, {"number": 7}]', ""
        if "--heads" in cmd:
            return 0, heads, ""
        if "--tags" in cmd:
            return 0, tags, ""
        if cmd[:2] == ["gh", "api"]:
            return 0, "diverged", ""
        if "ls-remote" in cmd:
            return 0, f"{rev}\trefs/heads/main\n", ""
        return 0, "", ""
    monkeypatch.setattr(runs_bench, "run", fake)
    keep = {"prs": {4}, "refs": {"refs/heads/main", "refs/heads/dependabot/all", "refs/tags/v0.1.0"}}
    runs_bench.reset_sample("ika100/todo-api", rev, tmp_path, keep)
    closed = [line for line in log if line.startswith("gh pr close")]
    deleted = [line for line in log if " --delete " in line]
    assert closed == ["gh pr close 7 --repo ika100/todo-api --delete-branch"]
    assert any(line.endswith("refs/heads/feature/900") for line in deleted)
    assert any(line.endswith("refs/tags/v0.2.0") for line in deleted)
    assert not any("dependabot" in line or "v0.1.0" in line for line in deleted)


def test_an_untrusted_benchmark_folder_is_refused_before_any_session(world, store, monkeypatch):
    """An untrusted folder would ignore the repo's permission rules: refuse with the trust hint, no record, no session."""
    import runs_bench
    monkeypatch.setattr(runs_bench, "trusted", lambda clone: False)
    with pytest.raises(PlatformError, match="not trusted") as e:
        runs.main(["benchmark", "quick-task"])
    assert "claude" in (e.value.hint or "") and str(runs.state_dir() / "benchmark" / "quick-task") in str(e.value)
    assert benchmark_records(store) == [] and world.headless_calls == []


def test_a_session_that_ends_without_its_pr_is_recorded_as_failed(world, store, monkeypatch):
    """A headless run that exits 0 but opened no PR did not deliver: outcome failed, the record says why."""
    import headless
    monkeypatch.setattr(headless, "main", lambda argv: 0)
    assert runs.main(["benchmark", "quick-task"]) == 1
    (r,) = benchmark_records(store)
    assert r["outcome"] == "failed" and r["benchmark"]["result_check"] == "no new open PR in ika100/todo-api"
    assert r["benchmark"]["reset"] == "done"


def test_build_plans_first_then_builds_as_two_phases(world, store):
    """/svc:build needs a plan.md: the build benchmark runs /svc:plan, then /svc:build, each as its own phase."""
    assert runs.main(["benchmark", "build"]) == 0
    assert [argv[-1] for argv in world.headless_calls] == ["/svc:plan 900", "/svc:build 900"]
    (r,) = benchmark_records(store)
    names = [p["name"] for p in r["phases"]]
    assert names[:2] == ["benchmark:plan", "benchmark:build"] and names[-1] == "benchmark:reset"


def test_a_failed_step_stops_the_run_and_says_which(world, store, monkeypatch):
    import headless
    calls = []
    monkeypatch.setattr(headless, "main", lambda argv: calls.append(argv[-1]) or 1)
    assert runs.main(["benchmark", "build"]) == 1
    (r,) = benchmark_records(store)
    assert calls == ["/svc:plan 900"] and r["outcome"] == "failed"
    assert r["benchmark"]["result_check"] == "step plan did not finish" and r["benchmark"]["reset"] == "done"
