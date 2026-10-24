"""Spec 087: `cplat runs report` (text and JSON), the aggregation, and tolerance of old and unknown records."""
import datetime as dt
import json

import pytest

import runs
import runs_report
import runs_store
from test_runs import clock, mem, one_run, store, attach  # noqa: F401  (fixtures)

NOW = dt.datetime(2026, 10, 24, 8, 0, 0, tzinfo=dt.timezone.utc)


def rec(run_id, ended, *, kind="ship", outcome="done", repo="acme/a", phases=(), reruns=(), escalation=None, filed=(), **extra):
    return {"schema": 1, "run_id": run_id, "kind": kind, "repo": repo, "spec": None, "platform_version": "4.4.0", "mode": "interactive",
            "started_at": "2026-10-01T00:00:00Z", "ended_at": ended, "phases": [dict(zip(("name", "started_at", "ended_at"), p)) for p in phases],
            "ci_rounds": 1, "reruns": [{"check": c, "reason": r} for c, r in reruns], "escalation": escalation, "filed": list(filed),
            "outcome": outcome, "resumes": None, **extra}


def build(secs):
    return ("build", "2026-10-20T00:00:00Z", (dt.datetime(2026, 10, 20, tzinfo=dt.timezone.utc) + dt.timedelta(seconds=secs)).strftime("%Y-%m-%dT%H:%M:%SZ"))


def esc(reason, cause="platform"):
    return {"reason": reason, "cause": cause} if cause else {"reason": reason}


def dataset():
    return [
        rec("r1", "2026-10-20T10:00:00Z", phases=[build(1200)]),
        rec("r2", "2026-10-23T10:00:00Z", phases=[build(600)]),
        rec("r3", "2026-10-21T10:00:00Z", repo="acme/b", outcome="escalated", escalation=esc("merge failed"), phases=[build(900)],
            reruns=[("ci / test", "stuck")], filed=[{"signature": "s1", "url": "https://github.com/x/y/issues/1", "result": "new"}]),
        rec("r4", "2026-10-23T12:00:00Z", repo="acme/b", outcome="escalated", escalation=esc("merge failed "),
            filed=[{"signature": "s1", "url": "https://github.com/x/y/issues/1", "result": "+1"}]),
        rec("r5", "2026-10-22T12:00:00Z", repo="acme/b", outcome="escalated", escalation=esc("tests red", "code"), phases=[build(300)],
            filed=[{"signature": "s2", "url": None, "result": "pending"}]),
        rec("r6", "2026-10-23T14:00:00Z", repo="acme/b", kind="pr-wait", outcome="failed", reruns=[("ci / test", "transient")]),
        rec("r7", "2026-10-19T10:00:00Z", outcome="escalated", escalation=esc("x", None), reruns=[("lint", "transient")]),
        rec("old", "2026-08-01T10:00:00Z"),                                                    # outside the 30-day window
        rec("fut", "2026-10-10T10:00:00Z", kind="future-kind", agents=[{"id": "a1"}], brand_new_field={"x": 1}),
        {"schema": 0, "run_id": "legacy", "ended_at": "2026-10-10T10:00:00Z"},                  # an older schema with almost nothing
    ]


def put(s, record, name=None):
    path = runs_store.record_path(record) if name is None else name
    s.files[path] = json.dumps(record) + "\n"


@pytest.fixture()
def filled(store):
    for r in dataset():
        put(store, r)
    put(store, dataset()[0], name="runs/2026/10/20/copy-of-r1.json")                          # a duplicate run_id is counted once
    store.files["runs/2026/10/20/broken.json"] = "this is {not json\n"
    follow = {"schema": 1, "followup": "filed", "run_id": "r5", "signature": "s2", "url": "https://github.com/x/y/issues/2",
              "result": "new", "at": "2026-10-23T08:00:00Z"}
    put(store, follow)
    return store


def report_json(capsys, *args):
    assert runs.main(["report", "--json", *args]) == 0
    return json.loads(capsys.readouterr().out)


def test_the_report_succeeds_over_old_unknown_and_malformed_lines(filled, capsys):
    """AC-087.14: older schemas, unknown kinds and fields and one malformed line: the report succeeds and counts the skipped line."""
    agg = report_json(capsys)
    assert agg["window"]["malformed"] == 1 and agg["window"]["records"] == 9
    assert agg["runs"]["future-kind"] == {"done": 1}                                             # an unknown kind counts under its own name
    assert agg["runs"]["unknown"] == {"unknown": 1}                                              # missing fields count as unknown
    assert runs.main(["report"]) == 0
    assert "1 malformed line(s) skipped" in capsys.readouterr().out


def test_parse_separates_records_followups_and_malformed_lines():
    """AC-087.14: parse() counts non-JSON and non-object lines as malformed and recognises follow-ups."""
    texts = ['{"run_id": "a", "kind": "ship", "unknown_field": 1}\n', "not json\n\n", "[1, 2]\n",
             '{"schema": 1, "followup": "filed", "run_id": "a", "signature": "s", "url": "u", "result": "new", "at": "2026-10-24T00:00:00Z"}\n']
    records, fups, malformed = runs_report.parse(texts)
    assert [r["run_id"] for r in records] == ["a"] and len(fups) == 1 and malformed == 2


def test_the_report_has_every_aggregate(filled, capsys):
    """AC-087.17: kinds and outcomes, phase median and p90, causes, top reasons, reruns, filed issues, buffered."""
    agg = report_json(capsys)
    assert agg["runs"]["ship"] == {"done": 2, "escalated": 4}
    assert agg["runs"]["pr-wait"] == {"failed": 1}
    assert agg["phases"]["build"] == {"count": 4, "median_s": 750.0, "p90_s": 1200.0}
    assert agg["causes"] == {"platform": 2, "code": 1, "unknown": 1}
    assert agg["escalations"] == [{"reason": "merge failed", "count": 2}, {"reason": "tests red", "count": 1}, {"reason": "x", "count": 1}]
    assert agg["reruns"] == {"by_reason": {"stuck": 1, "transient": 2}, "by_check": {"ci / test": 2, "lint": 1}}
    assert agg["filed"] == {"new": 2, "+1": 1, "suppressed": 0, "pending": 0}


def test_the_report_counts_locally_buffered_records_but_does_not_include_them(store, capsys):
    """AC-087.17: the buffered records are counted apart."""
    store.reachable = False
    one_run()
    one_run()
    store.reachable = True
    assert report_json(capsys)["buffered"] == 2
    assert runs.main(["report"]) == 0
    assert "Buffered locally, not included: 2 record(s) (cplat runs flush)" in capsys.readouterr().out


def test_the_text_report_prints_the_documented_lines(filled, capsys):
    """AC-087.17: the text form in the documented order and layout."""
    assert runs.main(["report"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Runs 2026-09-24 to 2026-10-24 (30 days) in acme/runs: 9 record(s); 1 malformed line(s) skipped")
    order = ["Runs per kind and outcome:", "Phases (median / p90):", "Escalations per cause:", "Top escalation reasons:",
             "Reruns by reason:", "Reruns by check:", "Filed issues:", "Buffered locally, not included:"]
    assert [out.index(h) for h in order] == sorted(out.index(h) for h in order)
    assert "  build: 12m 30s / 20m 00s (n=4)" in out
    assert "Filed issues: new 2, +1 1, suppressed 0, pending 0" in out
    assert "  2  merge failed" in out and "platform 2" in out and "transient 2" in out and "ci / test 2" in out
    ship_line = next(ln for ln in out.splitlines() if ln.strip().startswith("ship:"))
    assert "done 2" in ship_line and "escalated 4" in ship_line


def test_since_and_repo_narrow_the_report(filled, capsys):
    """AC-087.17: the window defaults to 30 days; --since and --repo narrow it."""
    assert report_json(capsys)["window"]["days"] == 30
    narrow = report_json(capsys, "--since", "2")
    assert narrow["window"]["days"] == 2 and narrow["window"]["records"] == 4 and narrow["window"]["malformed"] == 0
    assert narrow["runs"] == {"ship": {"done": 1, "escalated": 2}, "pr-wait": {"failed": 1}}
    mine = report_json(capsys, "--repo", "acme/a")
    assert mine["window"]["repo"] == "acme/a" and mine["window"]["records"] == 4 and "pr-wait" not in mine["runs"]
    assert runs.main(["report", "--repo", "acme/a"]) == 0
    assert ", repo acme/a" in capsys.readouterr().out.splitlines()[0]


def test_json_output_has_stable_keys_and_nothing_else_on_stdout(filled, capsys):
    """AC-087.18: one JSON document with exactly the documented keys; stdout carries nothing but that document."""
    assert runs.main(["report", "--json"]) == 0
    out = capsys.readouterr().out
    agg = json.loads(out)                                                                         # the whole of stdout parses
    assert list(agg) == ["window", "runs", "phases", "causes", "escalations", "reruns", "filed", "buffered"]
    assert {"since", "until", "days", "repo", "store", "records", "malformed"} <= set(agg["window"])
    assert agg["window"]["store"] == "acme/runs" and agg["window"]["until"] == "2026-10-24" and agg["buffered"] == 0
    assert set(agg["reruns"]) == {"by_reason", "by_check"}


def test_an_empty_store_gives_an_empty_but_complete_report(store, capsys):
    """AC-087.18 AC-087.17: no records: every key is there, filed has all four results, groups print `none`."""
    agg = report_json(capsys)
    assert agg["runs"] == {} and agg["phases"] == {} and agg["escalations"] == [] and agg["filed"] == {"new": 0, "+1": 0, "suppressed": 0, "pending": 0}
    assert runs.main(["report"]) == 0
    assert "none" in capsys.readouterr().out


def test_only_the_ten_most_common_escalation_reasons_are_listed():
    """AC-087.17: top 10 by count, then by text; identical texts (after strip) are grouped."""
    records = [rec(f"e{i}", "2026-10-23T10:00:00Z", outcome="escalated", escalation=esc(f"reason {i:02d}")) for i in range(12)]
    records += [rec("g1", "2026-10-23T10:00:00Z", outcome="escalated", escalation=esc("reason 11 ")),
                rec("g2", "2026-10-23T10:00:00Z", outcome="escalated", escalation=esc("reason 11"))]
    agg = runs_report.aggregate(records, [], malformed=0, buffered=0, since_days=30, repo=None, store="acme/runs", now=NOW)
    top = agg["escalations"]
    assert len(top) == 10 and top[0] == {"reason": "reason 11", "count": 3}
    assert [t["reason"] for t in top[1:]] == [f"reason {i:02d}" for i in range(9)]


def test_percentiles_use_nearest_rank_and_incomplete_phases_are_skipped():
    """AC-087.17: median is the statistics median, p90 the nearest rank; a phase without both timestamps is not counted."""
    records = [rec(f"p{i}", "2026-10-23T10:00:00Z", phases=[build(s)]) for i, s in enumerate((10, 20, 30, 40, 50, 60, 70, 80, 90, 100))]
    records.append(rec("p-open", "2026-10-23T10:00:00Z", phases=[("build", "2026-10-20T00:00:00Z", None)]))
    agg = runs_report.aggregate(records, [], malformed=0, buffered=0, since_days=30, repo=None, store="acme/runs", now=NOW)
    assert agg["phases"]["build"] == {"count": 10, "median_s": 55.0, "p90_s": 90.0}


def test_render_text_survives_an_aggregate_of_unknowns():
    """AC-087.14: records with missing fields only count as unknown; rendering never fails."""
    agg = runs_report.aggregate([{"run_id": "z", "ended_at": "2026-10-23T10:00:00Z"}, {"kind": "ship", "ended_at": "2026-10-23T10:00:00Z", "escalation": {}, "reruns": [{}], "phases": [{"name": "x"}]}], [],
                                malformed=0, buffered=0, since_days=30, repo=None, store="acme/runs", now=NOW)
    assert "unknown" in runs_report.render_text(agg)


def test_a_follow_up_replaces_the_pending_result():
    """AC-087.22: the report counts a filing with the result of its follow-up line."""
    record = rec("r5", "2026-10-23T10:00:00Z", filed=[{"signature": "s2", "url": None, "result": "pending"}])
    follow = {"schema": 1, "followup": "filed", "run_id": "r5", "signature": "s2", "url": "u", "result": "+1", "at": "2026-10-23T11:00:00Z"}
    agg = runs_report.aggregate([record], [follow], malformed=0, buffered=0, since_days=30, repo=None, store="acme/runs", now=NOW)
    assert agg["filed"] == {"new": 0, "+1": 1, "suppressed": 0, "pending": 0}
