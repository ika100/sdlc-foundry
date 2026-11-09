"""Spec 163 (#591): a new `cplat headless` run after an escalation resumes where it stopped, without the old escalation."""
import json

import pytest

from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)
from units131_support import World


@pytest.fixture(autouse=True)
def one_task_per_unit(monkeypatch):
    monkeypatch.setenv("CPLAT_PARALLEL_TASKS", "1")


@pytest.fixture()
def w(tmp_path, monkeypatch):
    return World(tmp_path, monkeypatch, plan=False)


def escalate_on_disk(w, reason="no progress: unit plan after 2 sessions without a commit"):
    data = w.units_file()
    data["escalated"] = {"reason": reason, "cause": "environment"}
    (w.repo / ".git" / "cplat-units.json").write_text(json.dumps(data))


def test_a_resumed_run_after_an_escalation_runs_every_unit_left(w, capsys):
    """AC-163.1"""
    assert w.run("--max-runs", "2") == 1
    escalate_on_disk(w)
    assert w.run() == 0
    assert w.units_run() == ["plan", "red-tests", "task:t1", "task:t2", "task:t3", "verification", "land"]
    assert "needs you" not in capsys.readouterr().out


def test_an_escalation_inside_the_resumed_run_still_stops_it(w, capsys, monkeypatch):
    """AC-163.2"""
    import units
    assert w.run("--max-runs", "2") == 1
    escalate_on_disk(w, "old reason")
    real = units.end_session

    def escalating(repo, *a, **k):
        out = real(repo, *a, **k)
        units.escalate(repo, "new reason", "code")
        return out
    monkeypatch.setattr(units, "end_session", escalating)
    assert w.run() == 1
    out = capsys.readouterr().out
    assert "needs you: new reason" in out and "old reason" not in out
    assert len(w.units_run()) == 3
