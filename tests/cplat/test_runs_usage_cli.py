"""Spec 099: `cplat runs usage <run_id>` and `cplat runs usage --session <id>`."""
import json

import pytest

import runs
from core import PlatformError
from test_runs import clock, mem, store  # noqa: F401  (fixtures)
from usage_support import OPUS, SESSION, call, projects, run_with_phases, write_session  # noqa: F401

PHASES = [("build:tests", 10), ("build:implement", 100)]


@pytest.fixture()
def done_run(clock, store, projects):
    write_session(projects, SESSION, [call("m1", 20), call("m2", 120)], {"a1": ({"agentType": "svc:coder"}, [call("c1", 50, model="claude-mystery-9")])})
    return run_with_phases(clock, store, PHASES, 200)


def test_usage_of_a_run_prints_totals_and_every_breakdown(done_run, capsys):
    """AC-099.10: totals, by phase, by role and by model; output column 'output (as reported)'; output cost is a lower bound."""
    assert runs.main(["usage", done_run["run_id"]]) == 0
    out = capsys.readouterr().out
    assert done_run["run_id"] in out and "output (as reported)" in out
    for needle in ("total", "By phase", "By role", "By model", "build:tests", "build:implement", "svc:coder", "main", OPUS, "claude-mystery-9"):
        assert needle in out, needle
    assert "lower bound" in out
    assert "estimate" in out.lower() and done_run["usage"]["price_table"] in out          # AC-099.7: labelled, dated
    assert "unknown" in out and "claude-mystery-9" in out                                    # the unpriced model's cost


def test_usage_of_a_session_has_no_phase_breakdown(done_run, capsys):
    """AC-099.10: --session prints the same by role and by model, with no phase breakdown."""
    assert runs.main(["usage", "--session", SESSION]) == 0
    out = capsys.readouterr().out
    assert SESSION in out and "By role" in out and "By model" in out and "svc:coder" in out
    assert "By phase" not in out and "output (as reported)" in out and "lower bound" in out


def test_json_prints_one_document_and_nothing_else(done_run, capsys):
    """AC-099.10: --json for a run and for a session: stdout is exactly one JSON document."""
    assert runs.main(["usage", done_run["run_id"], "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["run_id"] == done_run["run_id"] and doc["usage"]["totals"]["calls"] == 3 and "by_phase" in doc["usage"]
    assert runs.main(["usage", "--session", SESSION, "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["session"] == SESSION and doc["usage"]["totals"]["calls"] == 3 and "by_phase" not in doc["usage"]


def test_an_unknown_run_is_an_error_naming_it(done_run):
    """AC-099.10: unknown run id -> non-zero (PlatformError), the message says the run was not found."""
    with pytest.raises(PlatformError, match="run 20990101T000000Z-deadbeef not found"):
        runs.main(["usage", "20990101T000000Z-deadbeef"])


def test_a_run_without_usage_is_an_error_naming_it(clock, store, monkeypatch):
    """AC-099.10: a run recorded without usage -> 'has no usage section'."""
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    rec = run_with_phases(clock, store, [], 5, kind="pr-wait")
    with pytest.raises(PlatformError, match="has no usage section"):
        runs.main(["usage", rec["run_id"]])


def test_a_session_without_a_transcript_is_an_error_naming_it(projects):
    """AC-099.10: a session with no transcript on this machine."""
    with pytest.raises(PlatformError, match="no transcript for session abc-123 on this machine"):
        runs.main(["usage", "--session", "abc-123"])
