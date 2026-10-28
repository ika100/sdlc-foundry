"""Spec 088 (amendment 2026-10-26): the weekly retro shows the share of `unknown` escalations, week over week (AC-088.20, AC-088.21)."""
import copy

from retro_world import SHOP, Lazy, build, rid, run

retro_report = Lazy("retro_report")

UNKNOWN = {"cause": "unknown", "cause_source": "none"}
BY_RULE = {"cause": "environment", "cause_source": "rule", "rule": "git-action-awaits-approval"}
GIVEN = {"cause": "code", "cause_source": "given"}
SHARE_LINE = "unknown share: 50% (prev 83%) · unknown 2 of 4 (prev 5 of 6) · classified by rule 2 (prev 0)"
SECRET_REASON = "needs sign-off from acme-billing owner"


def er(name, ended, reason, **fields):
    return run(name, ended, outcome="escalated", repo=SHOP, escalation={"reason": reason, **fields})


def week_records():
    """Covered week (W43): 4 escalations, 2 still unknown, 2 by rule. Week before (W42): 6 escalations, 5 unknown, 1 given."""
    return [
        er("c1", "2026-10-20T10:00:00Z", SECRET_REASON, **UNKNOWN),
        er("c2", "2026-10-21T10:00:00Z", "who knows", **UNKNOWN),
        er("c3", "2026-10-22T10:00:00Z", "commit needs permission", **BY_RULE),
        er("c4", "2026-10-23T10:00:00Z", "waiting for approval to push", **BY_RULE),
        er("p1", "2026-10-13T10:00:00Z", "old unknown a", **UNKNOWN),
        er("p2", "2026-10-14T10:00:00Z", "old unknown b", **UNKNOWN),
        er("p3", "2026-10-15T10:00:00Z", "old unknown c", **UNKNOWN),
        er("p4", "2026-10-16T10:00:00Z", "old unknown d", **UNKNOWN),
        er("p5", "2026-10-17T10:00:00Z", "old unknown e", **UNKNOWN),
        er("p6", "2026-10-17T12:00:00Z", "tests red", **GIVEN),
    ]


def report():
    return build(week_records())


def section(text, name="## Escalations"):
    start = text.index(name)
    nxt = text.find("\n## ", start + 1)
    return text[start:nxt if nxt != -1 else len(text)]


def fig(cur, prev):
    return {"current": cur, "previous": prev}


def test_the_retro_shows_the_unknown_share_for_the_week_and_the_week_before():
    """AC-088.20: the escalations section opens with the share of unknown for the covered week and the week before."""
    r = report()
    assert r["unclassified"] == {"count": fig(2, 5), "escalations": fig(4, 6), "share": fig(0.5, 0.833), "by_rule": fig(2, 0)}
    assert list(r).index("unclassified") == list(r).index("escalations") + 1
    for text in (retro_report.render_text(r), retro_report.render_private(r, ""), retro_report.render_public(r, "")):
        lines = section(text).splitlines()
        assert lines[0] == "## Escalations" and lines[1] == SHARE_LINE


def test_a_week_without_escalations_shows_n_a_for_its_share():
    """AC-088.20: a week without escalations has no share: `n/a`."""
    only_current = [er("c1", "2026-10-20T10:00:00Z", "who knows", **UNKNOWN)]
    r = build(only_current)
    assert r["unclassified"]["share"] == fig(1.0, None)
    assert section(retro_report.render_text(r)).splitlines()[1].startswith("unknown share: 100% (prev n/a) · unknown 1 of 1 (prev 0 of 0)")


def test_the_private_retro_lists_every_still_unknown_reason_with_its_count():
    """AC-088.20: the private retro lists each reason still `unknown` with its run count; classified ones are not in that block."""
    for text in (retro_report.render_private(report(), ""), retro_report.render_text(report())):
        sec = section(text)
        unknown = sec[sec.index("unknown:"):]
        assert SECRET_REASON in unknown and "who knows" in unknown and "1 run(s)" in unknown
        assert "commit needs permission" not in unknown
        assert "commit needs permission" in sec[sec.index("environment:"):sec.index("unknown:")]


def test_the_public_issue_shows_counts_and_share_and_reason_n_only():
    """AC-088.20: the public issue counts and shows the share; the reasons stay `reason <n>`; no reason text reaches it."""
    r = report()
    body = retro_report.render_public(r, "")
    sec = section(body)
    assert SHARE_LINE in sec and "unknown: 2 (prev 5)" in sec
    assert "reason 1" in sec and "reason 2" in sec
    for private in (SECRET_REASON, "who knows", "commit needs permission", "waiting for approval to push", "acme-billing"):
        assert private not in body
    assert retro_report.leaks(body, r) == []


def test_older_unknown_records_count_under_the_rules_cause_in_the_retro():
    """AC-088.21: a record written before the rules existed is classified when the retro reads it."""
    old = [run("o1", "2026-10-20T10:00:00Z", outcome="escalated", repo=SHOP,
               escalation={"reason": "waiting for approval to create the branch", "cause": "unknown"}),
           run("o2", "2026-10-21T10:00:00Z", outcome="escalated", repo=SHOP, escalation={"reason": "who knows", "cause": "unknown"})]
    r = build(old)
    assert r["escalations"]["environment"]["count"] == fig(1, 0) and r["escalations"]["unknown"]["count"] == fig(1, 0)
    assert [x["reason"] for x in r["escalations"]["unknown"]["reasons"]] == ["who knows"]
    assert [x["reason"] for x in r["escalations"]["environment"]["reasons"]] == ["waiting for approval to create the branch"]
    assert r["unclassified"]["by_rule"] == fig(1, 0) and r["unclassified"]["count"] == fig(1, 0)


def test_unclassified_figures_are_evidence_refs():
    """AC-088.20: count, share and by_rule are evidence refs for the covered week and the week before."""
    r = report()
    ev, prev = r["evidence"], retro_report.previous_index(r)
    assert (ev["unclassified.count"], ev["unclassified.share"], ev["unclassified.by_rule"]) == (2, 0.5, 2)
    assert (prev["unclassified.count"], prev["unclassified.share"], prev["unclassified.by_rule"]) == (5, 0.833, 0)


def test_a_none_share_is_no_ref_and_an_older_report_has_none_of_them():
    """AC-088.20: a week without a share has no share ref; a report.json without the key yields no refs and no share line."""
    ev = build([er("c1", "2026-10-20T10:00:00Z", "who knows", **UNKNOWN)])
    assert "unclassified.share" in ev["evidence"] and "unclassified.share" not in retro_report.previous_index(ev)
    old = copy.deepcopy(report())
    del old["unclassified"]
    assert not any(k.startswith("unclassified.") for k in retro_report._index(old))
    assert "unknown share" not in retro_report.render_text(old) and "unknown share" not in retro_report.render_public(old, "")
