"""Spec 089: `cplat runs report --agents` (rows per agent x shape x model, averages, not measured, versions, causes, re-plans)."""
import datetime as dt
import json

import pytest

import core
import feedback
import runs
import runs_report
from test_runs import clock, mem, store, attach  # noqa: F401  (fixtures)
from test_runs_report import NOW, put, rec

ALL = ["fix_rounds", "merge_conflicts", "out_of_plan", "red_ci", "refused_test_diffs", "replans", "tester_events", "findings"]
ARCH, CODER, TESTER = ("svc:architect", "service-python", "opus"), ("svc:coder", "service-python", "sonnet"), ("svc:tester", "service-python", "sonnet")
SECRET = "ghp_abc123abc123abc123abc123abc123"


def ev(kind, n, **fields):
    return {"id": f"{kind}:{n}", "kind": kind, **fields}


def ent(key, events=(), model_id=None):
    agent, shape, model = key
    return {"id": f"{agent}|{shape}|{model}", "agent": agent, "shape": shape, "model": model, "model_id": model_id, "counts": {}, "events": list(events)}


def arec(run_id, ended, entries, measured=ALL, *, complete=True, version="4.4.0", repo="acme/a", **extra):
    return rec(run_id, ended, kind="build", repo=repo, platform_version=version, agents=list(entries), replans=[],
               agent_metrics={"schema": 1, "complete": complete, "measured": list(measured), "problems": []}, **extra)


def agg(records, **kw):
    args = dict(malformed=0, buffered=0, since_days=30, repo=None, agent=None, shape=None, by_version=False, store="acme/runs", now=NOW)
    args.update(kw)
    return runs_report.aggregate_agents(records, **args)


def row(a, agent, shape="service-python", model=None, version=None):
    found = [r for r in a["rows"] if r["agent"] == agent and r["shape"] == shape and (model is None or r["model"] == model)
             and r["platform_version"] == version]
    assert len(found) == 1, [(r["agent"], r["shape"], r["model"], r["platform_version"]) for r in a["rows"]]
    return found[0]


def fixrounds(*causes):
    return [ev("fix-round", i + 1, cause=c, task=None) for i, c in enumerate(causes)]


def dataset():
    """A coder row with 2 runs, an architect row with 5 runs, a pre-089 record and an old record."""
    out = [
        arec("c1", "2026-10-20T10:00:00Z", [ent(CODER, fixrounds("test", "test", "lint/type"))]),
        arec("c2", "2026-10-21T10:00:00Z", [ent(CODER, [ev("finding", 1, criterion="AC-089.3", task=None, severity="not met", **{"pass": "after fix"}, cycle=2, tasks=["t2"])])]),
    ]
    for i in range(5):
        evs = [ev("out-of-plan", 1, task="t1", path="scripts/cplat/runs.py"), ev("out-of-plan", 2, task="t1", path="scripts/cplat/ship.py")] if i == 0 else []
        out.append(arec(f"a{i}", f"2026-10-2{i}T12:00:00Z", [ent(ARCH, evs)]))
    out.append(rec("pre", "2026-10-22T09:00:00Z", kind="build"))                         # no agents section at all
    out.append(arec("old", "2026-08-01T10:00:00Z", [ent(CODER, fixrounds("ci"))]))      # outside the window
    return out


# ---------------- AC-089.11 rows, averages, sort, filters ----------------

def test_one_row_per_agent_shape_model_with_per_run_averages():
    """AC-089.11: runs, averages of each metric of the role, derived from the events; the window and pre-089 records are handled."""
    a = agg(dataset())
    assert a["window"]["records"] == 8 and a["window"]["days"] == 30 and a["window"]["by_version"] is False and a["window"]["store"] == "acme/runs"
    assert [(r["agent"], r["shape"], r["model"]) for r in a["rows"]] == [CODER, ARCH]    # the pre-089 and old records are in no row
    c, ar = a["rows"]
    assert c["runs"] == 2 and c["few_runs"] is True and c["platform_version"] is None
    assert set(c["metrics"]) == {"fix_rounds", "red_ci", "findings", "refused_test_diffs"}
    assert c["metrics"]["fix_rounds"] == {"runs": 2, "avg": 1.5, "by_cause": {"lint/type": 0.5, "test": 1.0, "ci": 0.0, "verification": 0.0}}
    assert c["metrics"]["red_ci"] == {"runs": 2, "avg": 0.0}
    f = c["metrics"]["findings"]
    assert f["runs"] == 2 and f["avg"] == 0.0 and f["by_severity"] == {"not met": 0.0, "partial": 0.0, "deviation": 0.0}
    assert f["after_fix"] == {"avg": 0.5, "by_severity": {"not met": 0.5, "partial": 0.0, "deviation": 0.0}}
    assert ar["runs"] == 5 and ar["few_runs"] is False and set(ar["metrics"]) == {"out_of_plan", "merge_conflicts", "replans"}
    assert ar["metrics"]["out_of_plan"] == {"runs": 5, "avg": 0.4}
    assert ar["metrics"]["replans"] == {"runs": 5, "avg": 0.0}


def test_rework_sums_the_averages_and_sorts_worst_first():
    """AC-089.11: rework = sum of metric averages plus after-fix findings; rows are sorted by it, descending."""
    a = agg(dataset())
    assert [r["rework"] for r in a["rows"]] == [2.0, 0.4]
    tie = [arec("t1", "2026-10-20T10:00:00Z", [ent(("web:coder", "web-nextjs", "sonnet")), ent(("svc:coder", "service-python", "sonnet"))])]
    assert [r["agent"] for r in agg(tie)["rows"]] == ["svc:coder", "web:coder"]          # ties: agent ascending


def test_roles_without_metrics_have_an_empty_metrics_object():
    """AC-089.11: the reviewer took part but has no metrics; the quality agent only counts refused test diffs."""
    r = [arec("q1", "2026-10-20T10:00:00Z", [ent(("svc:reviewer", "service-python", "opus")),
                                              ent(("shared:quality", "service-python", "sonnet"), [ev("refused-test-diff", 1, file="tests/t.py", reason="changed", task=None)])])]
    a = agg(r)
    assert row(a, "svc:reviewer")["metrics"] == {}
    assert row(a, "shared:quality")["metrics"] == {"refused_test_diffs": {"runs": 1, "avg": 1.0}}


def test_tester_events_have_their_reasons():
    """AC-089.11: tester events by reason."""
    evs = [ev("tester", 1, reason="untraced", criterion="AC-1.1", test=None), ev("tester", 2, reason="wrong failure", criterion=None, test="test_a")]
    a = agg([arec("t1", "2026-10-20T10:00:00Z", [ent(TESTER, evs)]), arec("t2", "2026-10-21T10:00:00Z", [ent(TESTER)])])
    assert row(a, "svc:tester")["metrics"]["tester_events"] == {"runs": 2, "avg": 1.0, "by_reason": {"untraced": 0.5, "wrong failure": 0.5}}


def test_filters_narrow_the_rows():
    """AC-089.11: --agent (full name, or a role without ':'), --shape and --repo."""
    recs = dataset() + [arec("w1", "2026-10-20T10:00:00Z", [ent(("web:coder", "web-nextjs", "sonnet"), fixrounds("ci"))], repo="acme/web")]
    assert {r["agent"] for r in agg(recs, agent="coder")["rows"]} == {"svc:coder", "web:coder"}
    assert [r["agent"] for r in agg(recs, agent="svc:coder")["rows"]] == ["svc:coder"]
    assert [r["agent"] for r in agg(recs, shape="web-nextjs")["rows"]] == ["web:coder"]
    w = agg(recs, repo="acme/web")
    assert [r["agent"] for r in w["rows"]] == ["web:coder"] and w["window"]["records"] == 1 and w["window"]["repo"] == "acme/web"
    assert agg(recs, agent="coder")["window"]["agent"] == "coder" and agg(recs, shape="web-nextjs")["window"]["shape"] == "web-nextjs"


def test_since_widens_and_narrows_the_window():
    """AC-089.11: --since <days>; the same run_id is counted once."""
    recs = dataset() + [dataset()[0]]
    assert row(agg(recs), "svc:coder")["runs"] == 2
    assert row(agg(recs, since_days=90), "svc:coder")["runs"] == 3
    assert [(r["agent"], r["runs"]) for r in agg(recs, since_days=1)["rows"]] == [("svc:architect", 2)]   # a3 and a4 only


def test_incomplete_runs_are_counted_in_the_row():
    """AC-089.11 AC-089.10: runs whose agent metrics are incomplete are named in the row."""
    r = [arec("i1", "2026-10-20T10:00:00Z", [ent(ARCH)], complete=False), arec("i2", "2026-10-21T10:00:00Z", [ent(ARCH)])]
    assert row(agg(r), "svc:architect")["incomplete_runs"] == 1


def test_cli_json_prints_one_document_and_nothing_else(store, capsys):
    """AC-089.11: `--json` is the same rows as one JSON document; --since, --agent, --shape and --repo narrow it."""
    for r in dataset():
        put(store, r)
    assert runs.main(["report", "--agents", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert [(r["agent"], r["rework"]) for r in doc["rows"]] == [("svc:coder", 2.0), ("svc:architect", 0.4)]
    assert set(doc) == {"window", "rows", "buffered"} and doc["window"]["store"] == "acme/runs"
    assert runs.main(["report", "--agents", "--json", "--agent", "architect", "--shape", "service-python", "--repo", "acme/a", "--since", "60"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert [r["agent"] for r in doc["rows"]] == ["svc:architect"] and doc["window"]["days"] == 60 and doc["window"]["agent"] == "architect"


def test_cli_text_prints_the_documented_lines(store, capsys):
    """AC-089.11: header, one line per row with `few runs`, the role's metric line, causes and the buffered line."""
    for r in dataset():
        put(store, r)
    assert runs.main(["report", "--agents"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Agents 2026-09-24 to 2026-10-24 (30 days) in acme/runs: 8 record(s); 0 malformed line(s) skipped")
    assert "svc:coder service-python sonnet: 2 run(s), few runs, rework 2.00" in out
    assert "svc:architect service-python opus: 5 run(s), rework 0.40" in out
    assert "fix rounds 1.50 (lint/type 0.50, test 1.00, ci 0.00, verification 0.00)" in out
    assert "out-of-plan files 0.40" in out and "causes:" in out
    assert out.index("svc:coder") < out.index("svc:architect")
    assert "Buffered locally, not included: 0 record(s) (cplat runs flush)" in out


def test_the_agent_flags_need_agents():
    """AC-089.11 AC-089.12: --by-version, --agent and --shape without --agents are a platform error with a hint."""
    for flag in (["--by-version"], ["--agent", "coder"], ["--shape", "web-nextjs"]):
        with pytest.raises(core.PlatformError, match="need --agents"):
            runs.main(["report", *flag])


def test_an_empty_store_prints_none(store, capsys):
    """AC-089.11: no rows: the line `  none` after the header; JSON has an empty row list."""
    assert runs.main(["report", "--agents"]) == 0
    assert "\n  none" in capsys.readouterr().out
    assert runs.main(["report", "--agents", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["rows"] == []


# ---------------- AC-089.9 not measured ----------------

def test_unmeasured_runs_are_left_out_of_the_average():
    """AC-089.9: the average divides by the runs that measured the metric, not by all runs."""
    r = [arec("m1", "2026-10-20T10:00:00Z", [ent(CODER, fixrounds("ci", "ci"))], measured=["fix_rounds"]),
         arec("m2", "2026-10-21T10:00:00Z", [ent(CODER)], measured=["fix_rounds"]),
         arec("m3", "2026-10-22T10:00:00Z", [ent(CODER, fixrounds("ci"))], measured=[])]        # recorded an event but never measured: left out
    c = row(agg(r), "svc:coder")
    assert c["runs"] == 3
    assert c["metrics"]["fix_rounds"]["runs"] == 2 and c["metrics"]["fix_rounds"]["avg"] == 1.0
    assert c["metrics"]["red_ci"] == {"runs": 0, "avg": None}


def test_a_metric_nobody_measured_is_null_and_prints_n_a():
    """AC-089.9: no run measured it: avg and every per-cause value are null; the text says n/a."""
    r = [arec("n1", "2026-10-20T10:00:00Z", [ent(CODER)], measured=[]), rec("pre", "2026-10-21T10:00:00Z", kind="build")]
    a = agg(r)
    f = row(a, "svc:coder")["metrics"]["fix_rounds"]
    assert f["runs"] == 0 and f["avg"] is None and set(f["by_cause"].values()) == {None}
    assert row(a, "svc:coder")["metrics"]["findings"]["after_fix"]["avg"] is None
    text = runs_report.render_agents_text(a)
    assert "fix rounds n/a (lint/type n/a, test n/a, ci n/a, verification n/a)" in text and "red-CI rounds n/a" in text


def test_a_record_without_agent_metrics_measured_nothing():
    """AC-089.9: a record that has `agents` but no `agent_metrics` (or a pre-089 record) counts for the row but measured nothing."""
    r = rec("x1", "2026-10-20T10:00:00Z", kind="build", agents=[ent(CODER, fixrounds("ci"))])
    c = row(agg([r]), "svc:coder")
    assert c["runs"] == 1 and c["metrics"]["fix_rounds"]["avg"] is None


# ---------------- AC-089.12 by version ----------------

def versioned():
    return [arec("v1", "2026-10-20T10:00:00Z", [ent(CODER, fixrounds("test", "test", "ci"))], version="4.3.0"),
            arec("v2", "2026-10-21T10:00:00Z", [ent(CODER)], version="4.10.0"),
            arec("v3", "2026-10-22T10:00:00Z", [ent(CODER, fixrounds("ci"))], version="4.9.0"),
            arec("v4", "2026-10-22T11:00:00Z", [ent(ARCH, [ev("out-of-plan", 1, task="t1", path="a.py")])], version="4.9.0")]


def test_by_version_splits_each_row_and_keeps_versions_side_by_side():
    """AC-089.12: one row per platform_version, versions ascending (numerically), groups placed by their worst row."""
    a = agg(versioned(), by_version=True)
    assert a["window"]["by_version"] is True
    assert [(r["agent"], r["platform_version"]) for r in a["rows"]] == [("svc:coder", "4.3.0"), ("svc:coder", "4.9.0"), ("svc:coder", "4.10.0"),
                                                                       ("svc:architect", "4.9.0")]
    assert [r["metrics"]["fix_rounds"]["avg"] for r in a["rows"][:3]] == [3.0, 1.0, 0.0]


def test_without_by_version_the_versions_are_merged():
    """AC-089.12: the default has one row per agent and a null platform_version."""
    a = agg(versioned())
    assert [r["platform_version"] for r in a["rows"]] == [None, None] and row(a, "svc:coder")["runs"] == 3


def test_cli_by_version_text_and_json(store, capsys):
    """AC-089.12: `cplat runs report --agents --by-version` shows the version in every row."""
    for r in versioned():
        put(store, r)
    assert runs.main(["report", "--agents", "--by-version", "--json"]) == 0
    assert [r["platform_version"] for r in json.loads(capsys.readouterr().out)["rows"]] == ["4.3.0", "4.9.0", "4.10.0", "4.9.0"]
    assert runs.main(["report", "--agents", "--by-version"]) == 0
    out = capsys.readouterr().out
    assert "svc:coder service-python sonnet 4.3.0: 1 run(s), few runs" in out and "svc:coder service-python sonnet 4.10.0: 1 run(s)" in out


# ---------------- AC-089.13 causes with run ids, redaction ----------------

def test_top_causes_are_ranked_and_cite_the_latest_run():
    """AC-089.13: up to 3 causes by count then label, path patterns, one run_id each (the most recent record that shows it)."""
    paths = ["scripts/cplat/runs.py", "scripts/cplat/ship.py", "scripts/cplat/spec.py", "README.md", "docs/a.md", "docs/b.md", "docs/c.md"]
    r1 = arec("r1", "2026-10-18T10:00:00Z", [ent(ARCH, [ev("out-of-plan", i + 1, task="t1", path=p) for i, p in enumerate(paths[:3])])])
    r2 = arec("r2", "2026-10-22T10:00:00Z", [ent(ARCH, [ev("out-of-plan", 1, task="t2", path="scripts/cplat/x.py"), ev("out-of-plan", 2, task="t2", path="README.md"),
                                                       ev("merge-conflict", 1, spec="s", task="t2", **{"with": None}, paths=["tests/cplat/a.py"], author={}, outcome="escalated")])])
    r3 = arec("r3", "2026-10-19T10:00:00Z", [ent(ARCH, [ev("out-of-plan", 1, task="t2", path="docs/a.md")])])
    top = row(agg([r1, r2, r3]), "svc:architect")["top_causes"]
    assert [(c["cause"], c["count"], c["run_id"]) for c in top] == [
        ("out-of-plan scripts/cplat/*.py", 4, "r2"), ("merge-conflict tests/cplat/*.py", 1, "r2"), ("out-of-plan *.md", 1, "r2")]


def one(shape_name, agent_key, events):
    return ent((agent_key[0], shape_name, agent_key[2]), events)


def test_labels_per_event_kind():
    """AC-089.13: fix-round <cause>, red-ci <check>, <severity> <criterion or task>, refused-test-diff <file>, untraced/wrong failure, merge-conflict <pattern>."""
    es = {
        "s1": [ev("fix-round", 1, cause="ci", task=None)],
        "s2": [ev("red-ci", 1, check="lint", checks=["lint"])],
        "s3": [ev("finding", 1, criterion="AC-089.3", task=None, severity="not met", **{"pass": "first"}, cycle=1, tasks=["t1"])],
        "s4": [ev("finding", 1, criterion=None, task="t2", severity="deviation", **{"pass": "first"}, cycle=1, tasks=["t2"])],
        "s5": [ev("refused-test-diff", 1, file="tests/a_test.py", reason="changed", task=None)],
    }
    tester = ent((TESTER[0], "s6", TESTER[2]), [ev("tester", 1, reason="untraced", criterion="AC-1.1", test=None),
                                                ev("tester", 2, reason="wrong failure", criterion=None, test="test_x")])
    arch = ent((ARCH[0], "s7", ARCH[2]), [ev("merge-conflict", 1, spec="s", task="t3", paths=["scripts/cplat/runs.py", "docs/a.md"], author={}, outcome="escalated", **{"with": "t1"}),
                                          ev("re-plan", 1, task="t3", conflict="merge-conflict:1")])
    a = agg([arec("l1", "2026-10-20T10:00:00Z", [one(k, CODER, v) for k, v in es.items()] + [tester, arch])])
    got = lambda shape_name, agent_name: {c["cause"] for c in row(a, agent_name, shape_name)["top_causes"]}  # noqa: E731
    assert got("s1", "svc:coder") == {"fix-round ci"} and got("s2", "svc:coder") == {"red-ci lint"}
    assert got("s3", "svc:coder") == {"not met AC-089.3"} and got("s4", "svc:coder") == {"deviation t2"}
    assert got("s5", "svc:coder") == {"refused-test-diff tests/a_test.py"}
    assert got("s6", "svc:tester") == {"untraced AC-1.1", "wrong failure test_x"}
    assert got("s7", "svc:architect") == {"merge-conflict scripts/cplat/*.py", "merge-conflict docs/*.md"}      # a re-plan gives no label


def test_a_row_without_causes_says_none():
    """AC-089.13: the causes line prints `causes: none`."""
    assert "causes: none" in runs_report.render_agents_text(agg([arec("z1", "2026-10-20T10:00:00Z", [ent(ARCH)])]))


def test_text_from_runs_is_redacted_like_feedback():
    """AC-089.13: labels (and the identity fields) go through feedback.redact, so a secret in a path never reaches the report."""
    leak = f"tests/GH_TOKEN={SECRET}_test.py"
    r = [arec("s1", "2026-10-20T10:00:00Z", [ent(CODER, [ev("refused-test-diff", 1, file=leak, reason="changed", task=None)], model_id=f"id-{SECRET}")])]
    a = agg(r)
    assert SECRET not in json.dumps(a) and SECRET not in runs_report.render_agents_text(a)
    (cause,) = row(a, "svc:coder")["top_causes"]
    assert cause["cause"] == feedback.redact(f"refused-test-diff {leak}")[:200] and cause["run_id"] == "s1"


# ---------------- AC-089.14 conflicts and re-plans ----------------

def conflict(n, outcome, task="t3"):
    return ev("merge-conflict", n, spec="007", task=task, paths=["a.py"], author={"agent": "svc:architect", "model": "opus", "model_id": None},
              outcome=outcome, **{"with": "t1"})


def test_conflicts_and_replans_are_separate_and_the_resolved_share_is_reported():
    """AC-089.14: merge conflicts and re-plans are two metrics; resolved_share = resolved conflicts / all conflicts."""
    r1 = arec("p1", "2026-10-20T10:00:00Z", [ent(ARCH, [conflict(1, "resolved"), ev("re-plan", 1, task="t3", conflict="merge-conflict:1")])])
    r2 = arec("p2", "2026-10-21T10:00:00Z", [ent(ARCH, [conflict(1, "escalated"), conflict(2, "re-planned"), conflict(3, "escalated")])])
    r3 = arec("p3", "2026-10-22T10:00:00Z", [ent(ARCH)])
    m = row(agg([r1, r2, r3]), "svc:architect")["metrics"]
    assert m["merge_conflicts"] == {"runs": 3, "avg": 1.333, "resolved_share": 0.25}
    assert m["replans"] == {"runs": 3, "avg": 0.333}


def test_resolved_share_is_null_without_conflicts_and_prints_n_a():
    """AC-089.14: no conflicts: null in JSON, n/a in the text; with conflicts a percentage."""
    a = agg([arec("p1", "2026-10-20T10:00:00Z", [ent(ARCH)])])
    assert row(a, "svc:architect")["metrics"]["merge_conflicts"]["resolved_share"] is None
    assert "merge conflicts 0.00 (resolved n/a)" in runs_report.render_agents_text(a)
    b = agg([arec("p2", "2026-10-20T10:00:00Z", [ent(ARCH, [conflict(1, "resolved"), conflict(2, "escalated")])])])
    t = runs_report.render_agents_text(b)
    assert "merge conflicts 2.00 (resolved 50%)" in t and "re-plans 0.00" in t
