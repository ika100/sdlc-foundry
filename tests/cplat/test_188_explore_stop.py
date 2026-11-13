"""Spec 188, AC-188.1 (second half): the benchmark workflow `explore-stop` runs /component:explore with a prompt that asks it to
write and commit a decisions file, then stop; the run passes only when the clone and the sample repo are as they were. No real
Claude run: git, gh and the headless session are the fakes of the spec 099 benchmark tests."""
import pytest

import core
import headless
import runs
import runs_bench
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)
from test_runs_usage_bench import benchmark_records, tasks, world  # noqa: F401  (fixtures)
from usage_support import projects, stored_records  # noqa: F401

RUN = ["benchmark", "explore-stop", "--plugins", str(core.PLATFORM_ROOT / "plugins")]


@pytest.fixture()
def explore(world, monkeypatch):  # noqa: F811
    """The session does nothing by default; `world.after` names what it leaves behind: dirty, commit or pr."""
    world.after = None
    world.head = "a" * 40
    inner = world.run

    def run(cmd, cwd=None):
        cmd = [str(c) for c in cmd]
        if cmd[:2] == ["git", "status"]:
            world.log.append(cmd)
            return 0, (" M README.md\n?? docs/decisions.md\n" if world.after == "dirty" else ""), ""
        if cmd[:3] == ["git", "rev-parse", "HEAD"]:
            world.log.append(cmd)
            return 0, world.head + "\n", ""
        return inner(cmd, cwd)
    monkeypatch.setattr(runs_bench, "run", run)

    def session(argv):
        world.headless_calls.append(argv)
        if world.after == "commit":
            world.head = "b" * 40
        if world.after == "pr":
            world.delivered_pr = 12
        return 0
    monkeypatch.setattr(headless, "main", session)
    return world


def test_the_task_asks_explore_to_write_and_commit_then_stop_ac_188_1():  # AC-188.1
    task = tasks()["workflows"]["explore-stop"]
    assert task["prompt"].startswith("/component:explore ")
    for ask in ("Write", "commit", "stop"):
        assert ask in task["prompt"], ask
    assert task["max_runs"] == 1 and runs_bench.EXPECTED["explore-stop"] == "unchanged"


def test_a_session_that_leaves_everything_as_it_was_passes_ac_188_1(explore, store, capsys):  # AC-188.1
    assert runs.main(RUN) == 0
    (r,) = benchmark_records(store)
    assert r["outcome"] == "done" and r["benchmark"]["workflow"] == "explore-stop" and r["benchmark"]["result_check"] is None
    assert explore.headless_calls[0][-1] == tasks()["workflows"]["explore-stop"]["prompt"]
    assert "benchmark explore-stop" in capsys.readouterr().out


@pytest.mark.parametrize("after,why", [("dirty", "explore changed the working tree"), ("commit", "explore made a commit"),
                                       ("pr", "explore opened a PR")])
def test_a_write_a_commit_or_a_pr_fails_the_run_and_names_it_ac_188_1(explore, store, capsys, after, why):  # AC-188.1
    explore.after = after
    runs.main(RUN)
    (r,) = benchmark_records(store)
    assert r["outcome"] == "failed" and r["benchmark"]["result_check"].startswith(why)
    assert why in capsys.readouterr().out


def test_a_failing_status_check_is_reported_not_passed_ac_188_1(explore, store, monkeypatch):  # AC-188.1
    inner = runs_bench.run
    monkeypatch.setattr(runs_bench, "run", lambda cmd, cwd=None: (128, "", "fatal: not a git repository")
                        if [str(c) for c in cmd][:2] == ["git", "status"] else inner(cmd, cwd))
    runs.main(RUN)
    (r,) = benchmark_records(store)
    assert r["outcome"] == "failed" and "not a git repository" in r["benchmark"]["result_check"]


def test_the_session_loads_the_component_plugin_the_sample_does_not_enable_ac_188_1(explore, store):  # AC-188.1
    assert runs.main(RUN) == 0
    argv = explore.headless_calls[0]
    dirs = [argv[i + 1] for i, a in enumerate(argv) if a == "--plugin-dir"]
    assert str(core.PLATFORM_ROOT / "plugins" / "component") in dirs, "without it /component:explore does not exist in the session"


def test_without_plugins_the_run_is_refused_before_a_session_ac_188_1(explore, store, capsys):  # AC-188.1
    with pytest.raises(core.PlatformError) as e:
        runs.main(["benchmark", "explore-stop"])
    assert "component" in str(e.value) and not explore.headless_calls and not benchmark_records(store)
