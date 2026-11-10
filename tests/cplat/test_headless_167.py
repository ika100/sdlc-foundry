"""Spec 167 (t3): `cplat headless` writes the dispatcher's result file and stops at the stop flag
before its next session. Nothing changes without `CPLAT_DISPATCH_RESULT` and `CPLAT_DISPATCH_UNIT`."""
import json

import pytest

import core
import headless
from test_headless import fake_claude, repo, runs  # noqa: F401  (fixtures, helpers)
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)


@pytest.fixture(autouse=True)
def _no_session_env(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.delenv("CPLAT_SESSION_ID", raising=False)
    monkeypatch.delenv("CPLAT_DISPATCH_RESULT", raising=False)
    monkeypatch.delenv("CPLAT_DISPATCH_UNIT", raising=False)


@pytest.fixture()
def result_file(tmp_path, monkeypatch):
    f = tmp_path / "result.json"
    monkeypatch.setenv("CPLAT_DISPATCH_RESULT", str(f))
    monkeypatch.setenv("CPLAT_DISPATCH_UNIT", "issue-123.1")
    return f


def run_fix(repo):
    return headless.main(["/svc:fix-bug the price is wrong", "--repo", str(repo)])


def test_the_result_file_has_the_start_record_while_the_run_goes_on_and_the_end_record_after(repo, tmp_path, monkeypatch, result_file, store):
    fake_claude(tmp_path, monkeypatch, f"cp {result_file} seen.json")
    assert run_fix(repo) == 0
    seen = json.loads((repo / "seen.json").read_text())
    assert seen["unit"] == "issue-123.1" and seen["ended_at"] is None and seen["run_id"] and seen["pid"] and seen["started_at"]
    end = json.loads(result_file.read_text())
    assert end["run_id"] == seen["run_id"] and end["started_at"] == seen["started_at"]
    assert end["ended_at"] and end["result"] == "finished" and end["stop_reason"] == "done" and end["outcome"] == "done"
    assert end["code"] == 0 and end["cause"] is None and end["tokens"] is None   # no session usage registered: unknown, not 0


def test_the_headless_record_names_the_dispatch_unit(repo, tmp_path, monkeypatch, result_file, store):
    fake_claude(tmp_path, monkeypatch, "true")
    run_fix(repo)
    assert stored(store)[-1]["dispatch_unit"] == "issue-123.1"


def test_tokens_are_the_sum_of_the_usage_totals(repo, tmp_path, monkeypatch, result_file, store):
    import runs_usage
    fake_claude(tmp_path, monkeypatch, "true")
    totals = {"input": 10, "output": 5, "cache_read": 100, "cache_write": 7}
    monkeypatch.setattr(runs_usage, "for_run", lambda rec, **kw: {"totals": totals, "incomplete": None})
    run_fix(repo)
    assert json.loads(result_file.read_text())["tokens"] == 122
    monkeypatch.setattr(runs_usage, "for_run", lambda rec, **kw: {"totals": totals, "incomplete": "transcript not found: x"})
    run_fix(repo)
    assert json.loads(result_file.read_text())["tokens"] is None


def test_an_exception_still_writes_the_end_record(repo, tmp_path, monkeypatch, result_file, store):
    fake_claude(tmp_path, monkeypatch, "true")

    def boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(headless, "_drive", boom)
    with pytest.raises(RuntimeError):
        run_fix(repo)
    end = json.loads(result_file.read_text())
    assert end["result"] == "error: boom" and end["stop_reason"] == "error" and end["outcome"] == "failed" and end["ended_at"]


def test_without_the_variables_no_file_and_no_field(repo, tmp_path, monkeypatch, store):
    fake_claude(tmp_path, monkeypatch, "true")
    run_fix(repo)
    assert "dispatch_unit" not in stored(store)[-1]
    assert not list(tmp_path.glob("result*"))


def test_the_stop_flag_ends_a_legacy_run_before_its_next_session(repo, tmp_path, monkeypatch, result_file, store, capsys):
    flag = core.git_dir(repo) / headless.STOP_FLAG
    fake_claude(tmp_path, monkeypatch, "true")
    assert not headless.stop_requested(repo)
    flag.write_text("")
    assert headless.stop_requested(repo)
    assert run_fix(repo) == 1
    assert runs(repo) == 0
    end = json.loads(result_file.read_text())
    assert end["result"] == "paused at a checkpoint by cplat dispatch" and end["stop_reason"] == "paused"
    assert end["outcome"] == "abandoned" and end["code"] == 1
    rec = stored(store)[-1]
    assert rec["outcome"] == "abandoned" and rec["stop_reason"] == "paused" and rec.get("escalation") is None
    assert "paused at a checkpoint" in capsys.readouterr().out


def test_the_stop_flag_written_during_a_session_stops_the_next_one(repo, tmp_path, monkeypatch, store):
    from test_headless import set_state
    import ship
    ship.start(repo, "7", True)
    set_state(repo, phase="build")
    flag = core.git_dir(repo) / headless.STOP_FLAG
    fake_claude(tmp_path, monkeypatch, f"touch {flag}")
    assert headless.main(["/svc:ship 7", "--repo", str(repo), "--max-runs", "6"]) == 1
    assert runs(repo) == 1 and ship.load_state(repo)["phase"] == "build"
    assert stored(store)[-1]["stop_reason"] == "paused"


def test_stop_of_maps_a_pause_to_abandoned():
    assert headless.stop_of("paused at a checkpoint by cplat dispatch", 1) == ("paused", "abandoned")


def test_the_stop_flag_ends_a_unit_run_before_its_next_session(tmp_path, monkeypatch, store):
    from units131_support import World
    monkeypatch.setenv("CPLAT_PARALLEL_TASKS", "1")
    w = World(tmp_path, monkeypatch, plan=True)
    (core.git_dir(w.repo) / headless.STOP_FLAG).write_text("")
    assert w.run() == 1
    assert w.sessions() == []
    assert stored(store)[-1]["stop_reason"] == "paused"
