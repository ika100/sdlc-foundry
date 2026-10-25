"""Spec 090: the pure weekly report (`retro_report`): weeks, figures with the previous week, issues, agents, no data, public text."""
import datetime as dt
import json
import random

import pytest

from retro_world import (CONSUMER_SPEC, GENERATED, RID, SECRET, SHOP, STORE, WEB, WEBUI, WEEK, Lazy, auto_issues, build, dumps, esc,
                         open_issues, records, run, specs)
from test_runs_report_agents import CODER, ent

retro_report = Lazy("retro_report")


def fig(cur, prev):
    return {"current": cur, "previous": prev}


# ---------------- AC-090.1 the covered week ----------------

def test_the_last_complete_week_before_today():
    """AC-090.1: the ISO week before the current date: Monday 2026-10-26 reports 2026-W43, Sunday 2026-10-25 still 2026-W42."""
    assert retro_report.last_complete_week(dt.date(2026, 10, 26)) == "2026-W43"
    assert retro_report.last_complete_week(dt.date(2026, 10, 28)) == "2026-W43"
    assert retro_report.last_complete_week(dt.date(2026, 11, 1)) == "2026-W43"
    assert retro_report.last_complete_week(dt.date(2026, 10, 25)) == "2026-W42"
    assert retro_report.last_complete_week(dt.date(2027, 1, 4)) == "2026-W53"      # ISO year, not calendar year


def test_a_week_runs_from_monday_midnight_to_the_next_monday_midnight_utc():
    """AC-090.1: Monday 00:00 to Sunday 24:00 UTC."""
    start, end = retro_report.week_bounds("2026-W43")
    assert start.replace(tzinfo=None) == dt.datetime(2026, 10, 19) and end.replace(tzinfo=None) == dt.datetime(2026, 10, 26)
    assert retro_report.previous_week("2026-W43") == "2026-W42" and retro_report.previous_week("2026-W01") == "2025-W52"


def test_the_report_covers_exactly_that_week_and_the_one_before():
    """AC-090.1: records ended inside [Monday 00:00, next Monday 00:00) count; the boundaries belong to the right week."""
    r = build()
    assert (r["week"], r["since"], r["until"], r["previous_week"]) == (WEEK, "2026-10-19", "2026-10-25", "2026-W42")
    assert r["records"] == {"current": 9, "previous": 4, "malformed": 0}      # c8 at 00:00:00 is in, x1 at the next 00:00:00 is out
    assert r["store"] == STORE and r["schema"] == 1 and r["generated_at"] == GENERATED


def test_a_duplicate_run_id_is_counted_once_and_a_record_without_end_belongs_to_no_week():
    """AC-090.1: the first record of a run_id wins; an unparseable ended_at is in no week."""
    recs = records() + [dict(records()[0])] + [dict(records()[1], run_id="noend", ended_at="garbage")]
    assert build(recs)["records"]["current"] == 9


def test_cplat_knows_retro():
    """AC-090.1: the command is registered and documented."""
    import cplat
    assert cplat.COMMANDS["retro"] == "retro" and "cplat.py retro" in cplat.__doc__


# ---------------- AC-090.2 figures ----------------

def test_runs_per_kind_and_outcome_with_the_previous_week():
    """AC-090.2: every kind has all four outcomes, each with the previous week next to it."""
    r = build()
    assert r["runs"]["ship"] == {"done": fig(2, 2), "escalated": fig(5, 1), "failed": fig(0, 1), "abandoned": fig(1, 0)}
    assert r["runs"]["build"] == {"done": fig(0, 0), "escalated": fig(0, 0), "failed": fig(1, 0), "abandoned": fig(0, 0)}
    assert list(r["runs"]) == ["build", "ship"]


def test_a_record_without_a_known_outcome_is_counted_as_unknown():
    """AC-090.2: the four outcomes plus `unknown` for a record that has none."""
    r = build([run("u1", "2026-10-20T10:00:00Z", outcome="exploded", repo=SHOP)])
    assert r["runs"]["ship"]["unknown"] == fig(1, 0) and r["runs"]["ship"]["done"] == fig(0, 0)


def test_median_and_longest_duration_per_phase():
    """AC-090.2: median and longest per phase, a week without the phase gives null and a count of 0."""
    b = build()["phases"]["build"]
    assert b["count"] == fig(2, 0) and b["median_s"] == fig(450.0, None) and b["max_s"] == fig(600.0, None)


def test_ci_rounds_and_reruns_in_total_and_per_run():
    """AC-090.2: CI rounds and reruns, and per run."""
    ci = build()["ci"]
    assert ci["rounds"] == fig(11, 6) and ci["reruns"] == fig(4, 1)
    assert ci["rounds_per_run"]["current"] == pytest.approx(11 / 9, abs=1e-3) and ci["rounds_per_run"]["previous"] == 1.5
    assert ci["reruns_per_run"]["current"] == pytest.approx(4 / 9, abs=1e-3) and ci["reruns_per_run"]["previous"] == 0.25


def test_escalations_per_cause_and_reasons_ranked_by_runs_then_duration():
    """AC-090.2: all five causes; identical texts (stripped) are grouped; ties go to the longer total duration."""
    e = build()["escalations"]
    assert list(e) == ["platform", "code", "decision", "environment", "unknown"]
    assert e["platform"]["count"] == fig(4, 1) and e["code"]["count"] == fig(1, 0) and e["decision"]["count"] == fig(0, 0)
    assert e["platform"]["reasons"] == [
        {"rank": 1, "reason": "merge failed", "runs": 2, "duration_s": 10800.0, "run_ids": sorted([RID("c2"), RID("c3")])},
        {"rank": 2, "reason": "stale base", "runs": 1, "duration_s": 18000.0, "run_ids": [RID("c4")]},      # ties "disk full" on runs, longer
        {"rank": 3, "reason": "disk full", "runs": 1, "duration_s": 1800.0, "run_ids": [RID("c9")]},
    ]
    assert e["code"]["reasons"][0]["reason"] == "tests red" and e["decision"]["reasons"] == []


def test_an_escalation_without_a_cause_is_unknown():
    """AC-090.2: the cause `unknown` collects escalations that name none."""
    r = build([run("u1", "2026-10-20T10:00:00Z", outcome="escalated", repo=SHOP, escalation={"reason": "who knows"})])
    assert r["escalations"]["unknown"]["count"] == fig(1, 0) and r["escalations"]["unknown"]["reasons"][0]["reason"] == "who knows"


def test_reruns_by_reason_and_by_check():
    """AC-090.2: reruns by reason (stale, stuck, transient) and the checks ranked by count, then name."""
    rr = build()["reruns"]
    assert rr["by_reason"] == {"stale": fig(1, 0), "stuck": fig(1, 1), "transient": fig(2, 0)}
    assert rr["by_check"] == [
        {"rank": 1, "check": "ci / test", "count": fig(2, 1), "run_ids": sorted([RID("c2"), RID("c3")])},
        {"rank": 2, "check": "lint", "count": fig(2, 0), "run_ids": sorted([RID("c3"), RID("c7")])},
    ]


def test_repos_count_once_per_shape_and_week():
    """AC-090.2: repos appear as counts per shape; the shape is the one a repo has in most of its records, a tie goes to the first."""
    s = build()["repos"]
    assert s["by_shape"]["service-python"] == fig(1, 1) and s["by_shape"]["web-nextjs"] == fig(1, 0)
    assert {x["repo"]: (x["shape"], x["runs"]) for x in s["list"]} == {SHOP: ("service-python", 7), WEBUI: ("web-nextjs", 2)}


def test_the_same_records_give_the_same_report_apart_from_the_timestamp():
    """AC-090.2: byte-identical report.json for the same records, in any input order."""
    a = build(generated_at="2026-10-26T06:00:00Z")
    shuffled = records()
    random.Random(7).shuffle(shuffled)
    b = build(shuffled, generated_at="2026-10-26T09:09:09Z")
    assert dumps(dict(a, generated_at="")) == dumps(dict(b, generated_at=""))
    assert dumps(build()) == dumps(build())


def test_the_text_shows_the_previous_value_next_to_every_figure():
    """AC-090.2: `<current> (prev <previous>)` in the tables and lines of the text report."""
    text = retro_report.render_text(build())
    ship = next(ln for ln in text.splitlines() if ln.startswith("| ship"))
    assert "2 (prev 2)" in ship and "5 (prev 1)" in ship and "0 (prev 1)" in ship and "1 (prev 0)" in ship
    build_line = next(ln for ln in text.splitlines() if ln.startswith("| build"))
    assert "7m 30s" in build_line and "10m 00s" in build_line
    assert "rounds 11 (prev 6)" in text and "reruns 4 (prev 1)" in text and "rounds per run 1.22 (prev 1.50)" in text
    assert "platform: 4 (prev 1)" in text and "1. merge failed" in text and "2 run(s)" in text
    assert "by reason: stale 1 (prev 0), stuck 1 (prev 1), transient 2 (prev 0)" in text
    assert "1. ci / test" in text


# ---------------- AC-090.3 platform issues ----------------

def test_issues_filed_or_counted_again_in_the_week_are_listed_and_ranked():
    """AC-090.3: occurrences in the week and in total, state, routed; ranked by occurrences in the week."""
    issues = build()["issues"]
    assert [i["number"] for i in issues] == [101, 102]                     # 103 has no signature, 104 is quiet, 105 is not auto-filed
    a, b = issues
    assert (a["occurrences_week"], a["occurrences_total"], a["state"], a["routed"]) == (2, 3, "open", False)
    assert (b["occurrences_week"], b["occurrences_total"], b["state"], b["routed"]) == (1, 1, "closed", True)
    assert a["title"] == "[auto] cplat ship: gate check hung" and a["signature"] == "platform:0123456789abcdef"
    assert a["url"].endswith("/issues/101")


def test_issues_with_the_same_occurrences_are_sorted_by_number():
    """AC-090.3: ties on occurrences go to the lower issue number."""
    two = [i for i in auto_issues() if i["number"] in (102,)]
    other = dict(two[0], number=100, title="[auto] another")
    assert [i["number"] for i in build(auto_issues=two + [other])["issues"]] == [100, 102]


def test_the_text_lists_the_issues_with_the_columns():
    """AC-090.3: issue, title, this week, total, state and routed in the text."""
    text = retro_report.render_text(build())
    line = next(ln for ln in text.splitlines() if "#101" in ln and "gate check hung" in ln)
    assert "| 2 |" in line and "| 3 |" in line and "open" in line
    assert "closed" in next(ln for ln in text.splitlines() if "#102" in ln)


# ---------------- AC-090.4 agents ----------------

def row(report, agent):
    (r,) = [x for x in report["agents"]["rows"] if x["agent"] == agent]
    return r


def test_one_row_per_agent_shape_model_with_the_089_metrics_of_both_weeks():
    """AC-090.4: runs, the 089 metrics, the previous week's metrics and the difference."""
    r = build()
    c = row(r, "svc:coder")
    assert (c["shape"], c["model"]) == ("service-python", "sonnet")
    assert c["runs"] == fig(4, 2) and c["few_runs"] is True
    assert c["metrics"]["fix_rounds"]["avg"] == 0.5 and c["previous"]["fix_rounds"]["avg"] == 1.5
    assert c["diff"]["fix_rounds"]["avg"] == -1.0
    assert c["diff"]["fix_rounds"]["by_cause"]["test"] == 0.5 and c["diff"]["fix_rounds"]["by_cause"]["ci"] == -1.5
    w = row(r, "web:coder")
    assert w["runs"] == fig(2, 0) and w["previous"] is None and w["metrics"]["fix_rounds"]["avg"] == 0.0


def test_the_metrics_are_exactly_those_of_runs_report_agents():
    """AC-090.4: the same per-run metrics as `cplat runs report --agents --json`."""
    import runs_report
    now = dt.datetime(2026, 10, 26, tzinfo=dt.timezone.utc)
    mine = [x for x in records() if x["ended_at"] >= "2026-10-19T00:00:00Z" and x["ended_at"] < "2026-10-26T00:00:00Z"]
    agg = runs_report.aggregate_agents(mine, malformed=0, buffered=0, since_days=7, repo=None, agent=None, shape=None,
                                       by_version=False, store=STORE, now=now)
    theirs = {(x["agent"], x["shape"], x["model"]): x["metrics"] for x in agg["rows"]}
    ours = {(x["agent"], x["shape"], x["model"]): x["metrics"] for x in build()["agents"]["rows"]}
    assert ours == theirs


def test_unmeasured_metrics_print_n_a_and_few_runs_are_marked():
    """AC-090.4: not measured shows n/a; a row with fewer than 5 runs says `few runs`, one with 5 or more does not."""
    four = [run(f"f{i}", f"2026-10-2{i}T10:00:00Z", repo=SHOP, entries=[ent(CODER)]) for i in range(5)]
    four[0]["agent_metrics"]["measured"] = []
    text = retro_report.render_text(build(four))
    line = next(ln for ln in text.splitlines() if "svc:coder" in ln)
    assert "few runs" not in line                       # 5 runs
    few = retro_report.render_text(build(four[:4]))
    assert "few runs" in next(ln for ln in few.splitlines() if "svc:coder" in ln)
    r = build(four[:1])
    assert row(r, "svc:coder")["metrics"]["fix_rounds"]["avg"] is None
    assert "n/a" in retro_report.render_text(r)


def test_the_text_shows_the_previous_value_and_the_signed_difference():
    """AC-090.4: `<current> (prev <previous>, <+diff>)` in the agent table."""
    text = retro_report.render_text(build())
    line = next(ln for ln in text.splitlines() if "svc:coder" in ln)
    assert "0.50 (prev 1.50, -1.00)" in line and "few runs" in line


# ---------------- AC-090.5 no data ----------------

def test_a_week_without_records_is_stated_in_the_first_line_and_each_section_says_no_data():
    """AC-090.5: zero runs in the first line, every affected section says it, the report is still produced."""
    r = build([], auto_issues=[])
    assert r["no_data"] == ["runs", "agents", "issues"] and r["records"] == {"current": 0, "previous": 0, "malformed": 0}
    text = retro_report.render_text(r)
    assert text.splitlines()[0] == "Weekly retro 2026-W43 (2026-10-19 to 2026-10-25): no runs this week"
    assert text.count("no data for this week") >= 4
    assert "## Runs" in text and "## Agents" in text and "## Platform issues" in text


def test_records_without_agent_metrics_and_no_issues_name_only_those_sections():
    """AC-090.5: runs exist, agents and issues have no data."""
    r = build([x for x in records() if "agents" not in x], auto_issues=[])
    assert r["no_data"] == ["agents", "issues"] and r["agents"]["rows"] == []
    text = retro_report.render_text(r)
    assert text.splitlines()[0].startswith("Weekly retro 2026-W43 (2026-10-19 to 2026-10-25): 3 run(s) in 1 repo(s)")
    agents = text.split("## Agents")[1].split("\n---")[0]
    assert "no data for this week" in agents and "no data for this week" in text.split("## Platform issues")[1]
    assert "no data for this week" not in text.split("## Runs")[1].split("## ")[0]


def test_the_first_line_counts_runs_and_repos():
    """AC-090.5: a normal week states runs and repos."""
    assert retro_report.render_text(build()).splitlines()[0] == "Weekly retro 2026-W43 (2026-10-19 to 2026-10-25): 9 run(s) in 2 repo(s)"


# ---------------- the evidence index (AC-090.7) ----------------

def test_the_evidence_index_holds_the_figures_of_the_covered_week():
    """AC-090.7: every figure a proposal may cite is a ref with a value in the report."""
    ev = build()["evidence"]
    assert ev["records"] == 9 and ev["runs.ship.escalated"] == 5 and ev["runs.build.failed"] == 1
    assert ev["phases.build.count"] == 2 and ev["phases.build.median_s"] == 450.0 and ev["phases.build.max_s"] == 600.0
    assert ev["ci.rounds"] == 11 and ev["ci.reruns"] == 4
    assert ev["escalations.platform"] == 4 and ev["escalations.platform.reason1"] == 2 and ev["escalations.code"] == 1
    assert ev["reruns.stuck"] == 1 and ev["reruns.check1"] == 2 and ev["repos.service-python"] == 1
    assert ev["issues.#101"] == 2 and ev["issues.#102"] == 1
    assert ev["agents.svc:coder|service-python|sonnet.runs"] == 4
    assert ev["agents.svc:coder|service-python|sonnet.fix_rounds.avg"] == 0.5
    assert ev["agents.svc:coder|service-python|sonnet.fix_rounds.by_cause.test"] == 0.5
    assert all(v is not None for v in ev.values())


def test_context_lists_the_open_specs_and_issues_for_the_agent():
    """AC-090.8: the report carries the specs that are not done and the open issues a proposal may cover."""
    c = build()["context"]
    assert c["specs"] == specs() and c["open_issues"] == open_issues()


# ---------------- AC-090.11 the public rendering ----------------

def test_the_public_body_has_no_private_name_and_uses_counts_and_placeholders():
    """AC-090.11: no repo, no consumer spec, no record text, no store; counts per shape; reason 1 / check 1; run ids stay."""
    r = build()
    body = retro_report.render_public(r, "Proposals: not generated (no proposal step ran)")
    low = body.lower()
    for private in (SHOP, WEBUI, "shop-api", "web-ui", CONSUMER_SPEC, STORE, "merge failed", "stale base", "disk full", "tests red",
                    "ci / test"):
        assert private.lower() not in low, private
    assert "reason 1" in body and "check 1" in body and RID("c2") in body
    assert "service-python" in body and "web-nextjs" in body
    assert "Proposals: not generated (no proposal step ran)" in body
    assert retro_report.leaks(body, r) == []
    assert "gate check hung" in body                                          # the issue title is already public


def test_the_private_text_keeps_the_detail():
    """AC-090.11: the committed report has the repo list, the reason texts and the check names."""
    private = retro_report.render_private(build(), "Proposals: not generated (x)")
    for detail in (SHOP, WEBUI, "merge failed", "stale base", "ci / test"):
        assert detail in private
    assert retro_report.render_text(build()).count("merge failed") >= 1


def test_leaks_finds_a_planted_name_case_insensitively():
    """AC-090.11: repo, spec and store names are found; clean text gives nothing."""
    r = build()
    assert retro_report.leaks("see ACME/Shop-API for details", r)
    assert retro_report.leaks(f"the spec {CONSUMER_SPEC}", r)
    assert retro_report.leaks(f"stored in {STORE}", r)
    assert retro_report.leaks("2 runs, 1 repo per shape", r) == []


def test_private_names_map_to_placeholders():
    """AC-090.11: repo, spec and store become <repo>, <spec>, <run-store>."""
    names = retro_report.private_names(build())
    assert names[SHOP] == "<repo>" and names[WEBUI] == "<repo>" and names[CONSUMER_SPEC] == "<spec>" and names[STORE] == "<run-store>"


def test_posted_text_has_passed_the_redaction_and_the_names_are_replaced():
    """AC-090.11: a secret or a repo name inside the proposals section does not survive `render_public`."""
    body = retro_report.render_public(build(), f"## Proposed specs\n1. leaked {SECRET} and {SHOP} and {CONSUMER_SPEC}")
    assert SECRET not in body and SHOP not in body and CONSUMER_SPEC not in body
    assert retro_report.leaks(body, build()) == []


def test_a_kind_that_is_not_a_safe_token_never_appears_publicly():
    """AC-090.11: free text in a kind becomes `kind<n>` in the evidence index and in the public body."""
    r = build([run("k1", "2026-10-20T10:00:00Z", kind="Acme Secret Kind", repo=SHOP)])
    assert "runs.kind1.done" in r["evidence"]
    assert "Acme Secret Kind".lower() not in retro_report.render_public(r, "").lower()
