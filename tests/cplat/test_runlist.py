"""Spec 122 acceptance tests: the run list `cplat runs [--json]` (AC-122.5) and the data the Board and the Done view read from it
(AC-122.9, AC-122.33, AC-122.48).

Contract: design.md "cplat runs". Records are written with the real run API into the per-test state dir (conftest)."""
import datetime as dt
import json

import pytest

import cplat
import runs

PHASES = {"plan", "build", "pr", "land", "deploy", "staging", "done", "escalated"}


def started(spec="011-cart", repo="acme/shop-api", kind="ship", phases=()):
    rid = runs.start(kind, repo=repo, spec=spec)
    for p in phases:
        runs.phase(rid, p)
    return rid


def collect(since=30, **kw):
    import runlist
    return runlist.collect(since, **kw)


def row(doc, rid):
    return next(r for r in doc["runs"] if r["run_id"] == rid)


def test_an_active_run_is_listed_with_its_fields_ac_122_5():  # AC-122.5
    rid = started(phases=["plan", "build"])
    doc = collect()
    assert doc["schema"] == 1 and "read_at" in doc and "store" in doc
    r = row(doc, rid)
    assert (r["spec"], r["repo"], r["phase"], r["active"]) == ("011-cart", "acme/shop-api", "build", True)
    assert r["stage"] == "Build" and r["stopped"] is False
    assert {"used", "limit"} <= set(r["budget"])
    assert r["phase"] in PHASES


@pytest.mark.parametrize("phases, phase, stage", [
    (["plan"], "plan", "Plan"), (["plan", "build", "pr"], "pr", "Land"), (["plan", "build", "pr", "land"], "land", "Land"),
    (["plan", "build", "pr", "land", "deploy"], "deploy", "Dev"),
])
def test_the_phase_is_the_last_opened_top_level_phase_ac_122_5(phases, phase, stage):  # AC-122.5
    rid = started(phases=phases)
    r = row(collect(), rid)
    assert (r["phase"], r["stage"]) == (phase, stage)


def test_an_escalated_run_keeps_the_phase_where_it_stopped_ac_122_5():  # AC-122.5
    rid = started(phases=["plan", "build"])
    runs.finish(rid, "escalated", escalation={"reason": "3 CI fix rounds without progress", "cause": "code"})
    r = row(collect(), rid)
    assert r["phase"] == "escalated" and r["stopped_in"] == "build" and r["stopped"] is True and r["stage"] == "Build"
    assert r["active"] is False and r["outcome"] == "escalated"
    assert r["escalation"]["reason"] == "3 CI fix rounds without progress"


def test_a_finished_run_is_done_and_has_no_escalation_ac_122_5():  # AC-122.5
    rid = started(phases=["plan", "build", "pr", "land", "deploy"])
    runs.finish(rid, "done")
    r = row(collect(), rid)
    assert r["phase"] == "done" and r["escalation"] is None and r["failure"] is None


def test_the_last_ten_activity_entries_have_time_and_agent_ac_122_5():  # AC-122.5
    rid = started(phases=["plan", "build"] + [f"build:t{i}" for i in range(15)])
    act = row(collect(), rid)["activity"]
    assert 0 < len(act) <= 10
    assert all({"at", "agent", "text"} <= set(a) for a in act)
    assert [a["at"] for a in act] == sorted((a["at"] for a in act), reverse=True)


def test_the_run_list_filters_by_repo_and_spec_ac_122_5():  # AC-122.5
    a = started(spec="011-cart", repo="acme/shop-api")
    b = started(spec="012-x", repo="acme/shop-web")
    doc = collect(repo="acme/shop-web")
    assert {r["run_id"] for r in doc["runs"]} == {b}
    doc = collect(spec="011-cart")
    assert {r["run_id"] for r in doc["runs"]} == {a}


def test_cplat_runs_json_prints_the_document_ac_122_5(capsys):  # AC-122.5
    rid = started(phases=["plan", "build"])
    assert cplat.main(["runs", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["schema"] == 1 and any(r["run_id"] == rid for r in doc["runs"])


def test_cplat_runs_without_json_prints_one_line_per_run_ac_122_5(capsys):  # AC-122.5
    started(spec="011-cart", phases=["plan", "build"])
    assert cplat.main(["runs"]) == 0
    out = capsys.readouterr().out
    assert "011-cart" in out and "acme/shop-api" in out


def test_a_runs_verb_is_still_the_moved_name_error_ac_122_5(capsys):  # AC-122.5
    assert cplat.main(["runs", "report"]) == 2


def test_active_runs_come_first_then_newest_ended_ac_122_5():  # AC-122.5
    old = started(spec="010-a", phases=["plan"])
    runs.finish(old, "done")
    act = started(spec="011-b", phases=["plan", "build"])
    ids = [r["run_id"] for r in collect()["runs"]]
    assert ids.index(act) < ids.index(old)


def test_since_zero_lists_runs_older_than_the_default_window_ac_122_48(monkeypatch):  # AC-122.48
    long_ago = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=100)
    monkeypatch.setattr(runs, "utcnow", lambda: long_ago)
    rid = started(spec="009-old", phases=["plan", "build"])
    runs.finish(rid, "done")
    monkeypatch.undo()
    assert all(r["run_id"] != rid for r in collect(30)["runs"])
    assert any(r["run_id"] == rid for r in collect(0)["runs"])


def test_a_stopped_run_carries_a_one_line_reason_for_the_card_ac_122_9():  # AC-122.9
    rid = started(phases=["plan", "build"])
    runs.finish(rid, "escalated", escalation={"reason": "merge conflict after the re-plan", "cause": "code"})
    r = row(collect(), rid)
    assert r["escalation"]["reason"] and "\n" not in (r["escalation"].get("summary") or r["escalation"]["reason"])


def test_the_failure_summary_of_an_escalated_run_has_the_contract_keys_ac_122_33():  # AC-122.33
    rid = started(phases=["plan", "build"])
    runs.finish(rid, "escalated", escalation={"reason": "3 CI fix rounds without progress", "cause": "code"})
    r = row(collect(), rid)
    assert set(r["failure"]) >= {"check", "test", "criterion", "error", "excerpt", "log", "diagnosis"}
    assert r["failure"]["diagnosis"]


def test_the_session_of_a_run_is_in_its_row_ac_122_36():  # AC-122.36
    rid = started(phases=["plan", "build"])
    r = row(collect(), rid)
    assert "session_id" in r and "repo_dir" in r
