"""Spec 099: one main session coordinating two overlapping runs (AC-099.14)."""
import datetime as dt
import os
import subprocess

import pytest

import runs
from test_runs import clock, mem, store  # noqa: F401  (fixtures)
from usage_support import SESSION, T0, assert_sums_equal_totals, call, projects, stored_records, write_session  # noqa: F401


def git_dir(path):
    path.mkdir()
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    return path.resolve()


def at(clock, sec):
    clock.now = T0 + dt.timedelta(seconds=sec)


def test_overlapping_runs_split_the_shared_calls_and_keep_subagents_apart(clock, store, projects, tmp_path, monkeypatch):
    """AC-099.14: subagent calls only in the run they were spawned for; main calls in the overlap split evenly under
    `main (shared)`; main calls outside the overlap under `main`; together every call exactly once."""
    a_dir, b_dir = git_dir(tmp_path / "repo-a"), git_dir(tmp_path / "repo-b")
    main = [call("m-a", 50), call("m-s1", 150, i=10), call("m-s2", 160, i=30), call("m-b", 250)]
    x = [call("x1", 20, cwd=a_dir), call("x2", 70, cwd=a_dir)]                     # spawned while only A was running
    y = [call("y1", 120, cwd=b_dir / "sub"), call("y2", 260, cwd=b_dir)]           # spawned in the overlap, in B's directory
    write_session(projects, SESSION, main, {"ax": ({"agentType": "svc:coder"}, x), "by": ({"agentType": "svc:reviewer"}, y)})

    monkeypatch.chdir(a_dir)
    at(clock, 0)
    rid_a = runs.start("ship", repo="acme/a")
    monkeypatch.chdir(b_dir)
    at(clock, 100)
    rid_b = runs.start("build", repo="acme/b")
    at(clock, 200)
    runs.finish(rid_a, "done")
    at(clock, 300)
    runs.finish(rid_b, "done")
    ra, rb = (next(r for r in stored_records(store) if r["run_id"] == i) for i in (rid_a, rid_b))
    ua, ub = ra["usage"], rb["usage"]

    assert ua["by_role"]["main"]["calls"] == 1 and ub["by_role"]["main"]["calls"] == 1
    assert ua["by_role"]["main (shared)"]["calls"] == pytest.approx(2 / 2) and ub["by_role"]["main (shared)"]["calls"] == pytest.approx(2 / 2)
    assert ua["by_role"]["main (shared)"]["input"] == pytest.approx(20) and ub["by_role"]["main (shared)"]["input"] == pytest.approx(20)
    assert ua["by_role"]["svc:coder"]["calls"] == 2 and "svc:reviewer" not in ua["by_role"]
    assert ub["by_role"]["svc:reviewer"]["calls"] == 2 and "svc:coder" not in ub["by_role"]
    assert ua["by_role"]["main (shared)"]["cost_usd"] == pytest.approx(ub["by_role"]["main (shared)"]["cost_usd"])

    every = main + x + y
    for field, key in (("calls", None), ("input", "input_tokens"), ("output", "output_tokens"),
                       ("cache_read", "cache_read_input_tokens"), ("cache_write", "cache_creation_input_tokens")):
        want = len(every) if key is None else sum(c["message"]["usage"][key] for c in every)
        assert ua["totals"][field] + ub["totals"][field] == pytest.approx(want), field
    assert_sums_equal_totals(ua)
    assert_sums_equal_totals(ub)
