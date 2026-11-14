"""Spec 192 acceptance tests: the person's answers are recorded and reported (AC-192.10).

Answers are run-store follow-up lines (`followup: person`); with no run store configured they stay in the local buffer,
which is what these tests read."""
import datetime
import importlib

import pytest

import runs
import runs_report

NOW = datetime.datetime(2026, 11, 14, 10, 0, 0, tzinfo=datetime.timezone.utc)


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    monkeypatch.setattr(runs, "utcnow", lambda: NOW)


def shown(minutes_ago):
    return (NOW - datetime.timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def person_lines():
    return [i for i in runs._safe_buffer() if i.get("followup") == "person"]


def answer(capsys, shown_at, *refs, option="approve-all"):
    nextcmd = importlib.import_module("nextcmd")
    capsys.readouterr()
    argv = ["answer", "--shown-at", shown_at, "--option", option]
    for r in refs:
        argv += ["--item", r]
    rc = nextcmd.main(argv)
    return rc, capsys.readouterr().out


def test_an_answer_adds_one_question_and_the_minutes(capsys):  # AC-192.10
    rc, out = answer(capsys, shown(4), "spec:o/n:189-x")
    assert rc == 0 and "recorded: 1 item(s), 4.0 min" in out
    (line,) = person_lines()
    assert line["questions"] == 1 and line["minutes"] == 4.0
    assert line["spec"] == "189-x" and line["repo"] == "o/n" and line["issue"] is None
    assert line["option"] == "approve-all" and line["shown_at"] == shown(4)


def test_a_group_answer_splits_its_minutes_evenly(capsys):  # AC-192.10
    rc, out = answer(capsys, shown(6), "spec:o/n:189-x", "spec:o/n:190-y", "issue:o/n:676")
    assert rc == 0
    lines = person_lines()
    assert len(lines) == 3
    assert [ln["minutes"] for ln in lines] == [2.0, 2.0, 2.0]
    assert all(ln["questions"] == 1 for ln in lines)
    assert any(ln["issue"] == 676 and ln["spec"] is None for ln in lines)
    assert len({ln["run_id"] for ln in lines}) == 3


def test_minutes_are_capped_at_ten_per_question(capsys):  # AC-192.10
    answer(capsys, shown(600), "spec:o/n:189-x")
    assert person_lines()[0]["minutes"] == 10.0


def test_a_bad_timestamp_exits_2_and_records_nothing(capsys):  # AC-192.10
    rc, _ = answer(capsys, "yesterday-ish", "spec:o/n:189-x")
    assert rc == 2 and person_lines() == []


def test_the_store_function_exists():  # AC-192.10
    assert callable(runs.person_answer)


def delivered(run_id, spec=None, issue=None, kind="ship"):
    rec = {"schema": 1, "run_id": run_id, "kind": kind, "repo": "o/n", "outcome": "done",
           "started_at": "2026-11-13T08:00:00Z", "ended_at": "2026-11-13T09:00:00Z", "phases": []}
    if spec:
        rec["spec"] = spec
    if issue:
        rec["issue"] = {"repo": "o/n", "number": issue, "url": None}
    return rec


def person(spec=None, issue=None, minutes=2.5, run_id="person-aaaaaaaaaaaa"):
    return {"schema": 1, "followup": "person", "signature": "person", "run_id": run_id, "at": "2026-11-13T07:00:00Z",
            "shown_at": "2026-11-13T06:57:00Z", "repo": "o/n", "spec": spec, "issue": issue, "option": "approve-all", "questions": 1,
            "minutes": minutes}


def report(records, followups):
    return runs_report.aggregate(records, followups, malformed=0, buffered=0, since_days=30, repo=None, store="x", now=NOW)


def test_report_shows_questions_and_person_minutes_per_delivered_item():  # AC-192.10
    agg = report([delivered("r1", spec="189-x")], [person(spec="189-x", minutes=2.5, run_id="person-1"),
                                                   person(spec="189-x", minutes=5.0, run_id="person-2")])
    (row,) = agg["person"]["items"]
    assert row["kind"] == "spec" and row["id"] == "189-x" and row["questions"] == 2 and row["minutes"] == 7.5
    assert agg["person"]["questions"] == 2 and agg["person"]["minutes"] == 7.5
    text = runs_report.render_text(agg)
    assert "Person time per delivered item:" in text
    assert "spec 189-x  questions 2  person 7.5 min" in text


def test_item_without_records_shows_a_dash():  # AC-192.10
    agg = report([delivered("r1", issue=676, kind="fix")], [])
    (row,) = agg["person"]["items"]
    assert row["kind"] == "issue" and row["id"] == "676" and row["questions"] is None and row["minutes"] is None
    assert "issue o/n#676  questions –  person –" in runs_report.render_text(agg)


def test_no_delivered_items():  # AC-192.10
    agg = report([], [person(spec="189-x")])
    assert agg["person"]["items"] == []
    assert "Person time per delivered item: none" in runs_report.render_text(agg)


def test_person_lines_never_count_as_runs():  # AC-192.10
    plain = report([delivered("r1", spec="189-x")], [])
    with_person = report([delivered("r1", spec="189-x")], [person(spec="189-x")])
    assert "person" in with_person
    for key in plain:
        if key != "person":
            assert with_person[key] == plain[key], key
