"""Spec 087 (amendment 2026-10-26): `cplat runs report` shows why `pr-wait` runs ended (AC-087.25, AC-087.26)."""
import pytest

import runs
import runs_report
from test_runs import clock, mem, one_run, store, attach  # noqa: F401  (fixtures)
from test_runs_report import NOW, put, rec, report_json

RESULTS = ["green", "merged", "red", "budget-refused", "timeout", "no-checks", "closed", "merge-failed", "error", "unrecorded"]


def pw(run_id, result=None, checks=None, *, outcome=None, ended="2026-10-22T10:00:00Z", **extra):
    section = None if result is None else {"result": result, **({"checks": checks} if checks is not None else {})}
    outcome = outcome or ("done" if result in ("green", "merged") else "failed")
    return rec(run_id, ended, kind="pr-wait", outcome=outcome, **({"pr_wait": section} if section else {}), **extra)


def dataset():
    return [
        pw("g1", "green"), pw("g2", "green"), pw("m1", "merged"),
        pw("r1", "red", ["ci / test", "lint"]), pw("r2", "red", ["ci / test"]),
        pw("b1", "budget-refused", ["ci / test", "e2e"]),
        pw("t1", "timeout", ["slow"]),                                   # pending checks are not red checks
        pw("n1", "no-checks"), pw("c1", "closed"), pw("f1", "merge-failed"), pw("e1", "error"),
        pw("u1"), pw("u2"),                                              # older records: no section
        rec("s1", "2026-10-22T10:00:00Z", kind="ship", outcome="failed", pr_wait={"result": "red", "checks": ["ship-only"]}),
    ]


@pytest.fixture()
def filled(store):
    for r in dataset():
        put(store, r)
    return store


def agg(records):
    return runs_report.aggregate(records, [], malformed=0, buffered=0, since_days=30, repo=None, store="acme/runs", now=NOW)


def test_ac_087_25_results_are_counted_per_result_with_unrecorded(filled, capsys):  # AC-087.25
    data = report_json(capsys)["pr_wait"]
    assert list(data["results"]) == RESULTS
    assert data["results"] == {"green": 2, "merged": 1, "red": 2, "budget-refused": 1, "timeout": 1, "no-checks": 1, "closed": 1,
                               "merge-failed": 1, "error": 1, "unrecorded": 2}


def test_ac_087_25_red_checks_count_red_and_budget_refused_only(filled, capsys):  # AC-087.25
    assert report_json(capsys)["pr_wait"]["red_checks"] == [
        {"check": "ci / test", "count": 3}, {"check": "e2e", "count": 1}, {"check": "lint", "count": 1}]


def test_ac_087_25_json_key_comes_after_usage_and_is_always_there(store, capsys):  # AC-087.25
    data = report_json(capsys)
    keys = list(data)
    assert keys[keys.index("usage") + 1] == "pr_wait"   # later keys (spec 088's `unclassified`) may follow
    assert list(data["pr_wait"]["results"]) == RESULTS and set(data["pr_wait"]["results"].values()) == {0}
    assert data["pr_wait"]["red_checks"] == []


def test_ac_087_25_text_lines_follow_the_runs_block(filled, capsys):  # AC-087.25
    assert runs.main(["report"]) == 0
    out = capsys.readouterr().out
    assert ("pr-wait results: green 2, merged 1, red 2, budget-refused 1, timeout 1, no-checks 1, closed 1, merge-failed 1, error 1, "
            "unrecorded 2") in out
    assert "Red checks: ci / test 3, e2e 1, lint 1" in out
    lines = out.splitlines()
    assert out.index("Runs per kind and outcome:") < out.index("pr-wait results:") < out.index("Phases (median / p90):")


def test_ac_087_25_text_says_none_without_pr_wait_records(store, capsys):  # AC-087.25
    put(store, rec("x1", "2026-10-22T10:00:00Z"))
    assert runs.main(["report"]) == 0
    out = capsys.readouterr().out
    assert "pr-wait results: none" in out and "Red checks: none" in out


def test_ac_087_25_a_check_counts_once_per_record_and_only_the_top_five_are_listed():  # AC-087.25
    recs = [pw("a", "red", ["x", "x", "k1", "k2", "k3", "k4", "k5"]), pw("b", "red", ["k1", "k2", "k3", "k4"]), pw("c", "red", "oops"),
            pw("d", "red", ["k1", 7, None])]
    top = runs_report.aggregate_pr_wait(recs)["red_checks"]
    assert [t["check"] for t in top] == ["k1", "k2", "k3", "k4", "k5"]
    assert [t["count"] for t in top] == [3, 2, 2, 2, 1]
    assert runs_report.aggregate_pr_wait([pw("a", "red", ["x", "x"])])["red_checks"] == [{"check": "x", "count": 1}]


def test_ac_087_25_an_unlisted_or_missing_result_keeps_its_own_name():  # AC-087.25
    recs = [pw("a", "brand-new"), rec("b", "2026-10-22T10:00:00Z", kind="pr-wait", outcome="failed", pr_wait={"x": 1})]
    res = runs_report.aggregate_pr_wait(recs)["results"]
    assert res["brand-new"] == 1 and res["unknown"] == 1
    assert runs_report.pr_wait_result(rec("z", "2026-10-22T10:00:00Z")) is None
    assert runs_report.pr_wait_result(pw("u")) == "unrecorded"


def test_ac_087_26_red_ci_replaces_failed_for_red_and_budget_refused(filled, capsys):  # AC-087.26
    kinds = report_json(capsys)["runs"]
    # failed holds timeout, no-checks, closed, merge-failed, error and the two records without a section
    assert kinds["pr-wait"]["red-ci"] == 3 and kinds["pr-wait"]["failed"] == 7 and kinds["pr-wait"]["done"] == 3
    assert kinds["ship"]["failed"] == 1 and "red-ci" not in kinds["ship"]          # another kind with a pr_wait section is untouched
    assert runs.main(["report"]) == 0
    line = next(ln for ln in capsys.readouterr().out.splitlines() if ln.strip().startswith("pr-wait:"))
    assert "red-ci 3" in line and "failed 7" in line


def test_ac_087_26_count_outcome_is_a_readers_count_and_the_record_keeps_failed():  # AC-087.26
    red, refused, timeout = pw("a", "red", ["x"]), pw("b", "budget-refused", ["x"]), pw("c", "timeout", ["x"])
    assert [runs_report.count_outcome(r) for r in (red, refused, timeout)] == ["red-ci", "red-ci", "failed"]
    assert red["outcome"] == "failed" and red["pr_wait"]["result"] == "red"
    assert runs_report.count_outcome(pw("d")) == "failed"
    assert runs_report.count_outcome(rec("e", "2026-10-22T10:00:00Z", kind="ship", outcome="failed", pr_wait={"result": "red"})) == "failed"
    assert runs_report.count_outcome(pw("f", "red", outcome="done")) == "done"      # only a failed record turns into red-ci


def test_ac_087_26_the_store_keeps_outcome_failed(filled):  # AC-087.26
    import json
    stored_red = [json.loads(t) for t in filled.files.values() if '"r1"' in t]
    assert stored_red and stored_red[0]["outcome"] == "failed" and "red-ci" not in json.dumps(stored_red[0])
    assert runs_report.RED_CI == "red-ci"
