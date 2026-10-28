"""Spec 087 (amendment 2026-10-26): the weekly retro shows why `pr-wait` runs ended (AC-087.26, AC-087.27)."""
from retro_world import SHOP, Lazy, build, records, rid, run

retro_report = Lazy("retro_report")

RESULTS = ["green", "merged", "red", "budget-refused", "timeout", "no-checks", "closed", "merge-failed", "error", "unrecorded"]
SECRET_CHECK = "acme-secret-check / deploy"


def pw(name, ended, result=None, checks=None, *, outcome=None):
    extra = {}
    if result is not None:
        extra["pr_wait"] = {"result": result, **({"checks": checks} if checks is not None else {})}
    outcome = outcome or ("done" if result in ("green", "merged") else "failed")
    return run(name, ended, kind="pr-wait", outcome=outcome, repo=SHOP, **extra)


def waits():
    return [
        pw("w1", "2026-10-20T10:00:00Z", "green"),
        pw("w2", "2026-10-21T10:00:00Z", "red", [SECRET_CHECK, "ci / test"]),
        pw("w3", "2026-10-22T10:00:00Z", "red", ["ci / test"]),
        pw("w4", "2026-10-23T10:00:00Z", "budget-refused", ["ci / test"]),
        pw("w5", "2026-10-23T11:00:00Z", "timeout", ["slow"]),
        pw("w6", "2026-10-24T10:00:00Z"),                                      # no section: unrecorded
        pw("p1", "2026-10-14T10:00:00Z", "red", ["ci / test"]),
        pw("p2", "2026-10-15T10:00:00Z", "merged"),
        pw("p3", "2026-10-16T10:00:00Z"),
        pw("p4", "2026-10-17T10:00:00Z", "red", ["lint"]),
    ]


def report():
    return build(records() + waits())


def fig(cur, prev):
    return {"current": cur, "previous": prev}


def test_ac_087_26_the_retro_counts_red_ci_instead_of_failed():  # AC-087.26
    r = report()["runs"]["pr-wait"]
    assert r["red-ci"] == fig(3, 2)
    assert r["failed"] == fig(2, 1)                                             # timeout and the record without a section
    assert r["done"] == fig(1, 1)
    assert list(r)[:5] == ["done", "escalated", "failed", "red-ci", "abandoned"]


def test_ac_087_26_the_red_ci_column_appears_only_when_one_was_counted():  # AC-087.26
    plain = build()["runs"]
    assert all("red-ci" not in outs for outs in plain.values())
    with_red = report()["runs"]
    assert all("red-ci" in outs for outs in with_red.values())                      # the columns are shared by every kind
    assert with_red["ship"]["red-ci"] == fig(0, 0)


def test_ac_087_26_retro_and_report_agree_on_the_classifier():  # AC-087.26
    import runs_report
    red = pw("z", "2026-10-20T10:00:00Z", "red", ["x"])
    assert runs_report.count_outcome(red) == "red-ci" and red["outcome"] == "failed"


def test_ac_087_27_results_for_both_weeks():  # AC-087.27
    res = report()["pr_wait"]["results"]
    assert list(res) == RESULTS
    assert res["green"] == fig(1, 0) and res["merged"] == fig(0, 1) and res["red"] == fig(2, 2)
    assert res["budget-refused"] == fig(1, 0) and res["timeout"] == fig(1, 0) and res["unrecorded"] == fig(1, 1)
    assert res["error"] == fig(0, 0)


def test_ac_087_27_top_red_checks_with_previous_count_and_run_ids():  # AC-087.27
    top = report()["pr_wait"]["red_checks"]
    assert [t["check"] for t in top] == ["ci / test", SECRET_CHECK]
    assert [t["rank"] for t in top] == [1, 2]
    assert top[0]["count"] == fig(3, 1) and top[1]["count"] == fig(1, 0)
    assert top[0]["run_ids"] == sorted([rid("w2", "2026-10-21T10:00:00Z"), rid("w3", "2026-10-22T10:00:00Z"), rid("w4", "2026-10-23T10:00:00Z")])


def test_ac_087_27_a_week_without_pr_wait_runs_has_zero_results_and_no_checks():  # AC-087.27
    pwr = build()["pr_wait"]
    assert list(pwr["results"]) == RESULTS and all(f == fig(0, 0) for f in pwr["results"].values())
    assert pwr["red_checks"] == []


def test_ac_087_27_evidence_refs_for_every_result_and_check_rank():  # AC-087.27
    r = report()
    assert r["evidence"]["pr_wait.red"] == 2 and r["evidence"]["pr_wait.green"] == 1 and r["evidence"]["pr_wait.error"] == 0
    assert r["evidence"]["pr_wait.check1"] == 3 and r["evidence"]["pr_wait.check2"] == 1
    assert retro_report.previous_index(r)["pr_wait.red"] == 2 and retro_report.previous_index(r)["pr_wait.check1"] == 1


def test_ac_087_27_the_private_text_names_the_checks_after_the_ci_section():  # AC-087.27
    for text in (retro_report.render_text(report()), retro_report.render_private(report(), "")):
        assert text.index("## CI") < text.index("## pr-wait") < text.index("## Escalations")
        assert "results: green 1 (prev 0)" in text and "unrecorded 1 (prev 1)" in text
        assert "red checks:" in text and "1. ci / test — 3 (prev 1)" in text and SECRET_CHECK in text


def test_ac_087_27_the_public_issue_shows_check_numbers_not_names():  # AC-087.27
    r = report()
    body = retro_report.render_public(r, "")
    assert "## pr-wait" in body and "1. check 1 — 3 (prev 1)" in body and "2. check 2 — 1 (prev 0)" in body
    assert SECRET_CHECK not in body and "ci / test" not in body
    assert retro_report.leaks(body, r) == []


def test_ac_087_27_a_week_without_runs_and_an_empty_list_render_plainly():  # AC-087.27
    empty = retro_report.render_text(build([]))
    assert "## pr-wait" in empty and "no data for this week" in empty[empty.index("## pr-wait"):empty.index("## Escalations")]
    no_red = retro_report.render_text(build(records() + [pw("g", "2026-10-20T10:00:00Z", "green")]))
    assert "red checks: none" in no_red
