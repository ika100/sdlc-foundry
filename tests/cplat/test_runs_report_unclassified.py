"""Spec 088 (amendment 2026-10-26): `cplat runs report` counts effective causes and shows the unclassified escalations (AC-088.19, AC-088.21)."""
import copy
import json

import runs
import runs_report
from test_runs import clock, mem, store  # noqa: F401  (fixtures)
from test_runs_report import NOW, put, rec

UNKNOWN = {"cause": "unknown", "cause_source": "none"}
BY_RULE = {"cause": "environment", "cause_source": "rule", "rule": "git-action-awaits-approval"}
GIVEN = {"cause": "code", "cause_source": "given"}


def esc(reason, **fields):
    return {"reason": reason, **(fields or UNKNOWN)}


def erec(name, escalation):
    return rec(name, "2026-10-23T10:00:00Z", outcome="escalated", escalation=escalation)


def agg_of(records):
    return runs_report.aggregate(records, [], malformed=0, buffered=0, since_days=30, repo=None, store="acme/runs", now=NOW)


def mixed():
    """Six escalations: two still unknown (same reason), three classified by rule, one stated."""
    return ([erec(f"u{i}", esc("needs a decision on rate limits")) for i in (1, 2)]
            + [erec(f"r{i}", esc("commit needs permission", **BY_RULE)) for i in (1, 2, 3)]
            + [erec("g1", esc("tests red", **GIVEN))]
            + [rec("ok", "2026-10-23T10:00:00Z")])                                      # a record without an escalation is not counted


def block(text):
    """The lines of the `Unclassified escalations:` block, up to the next group."""
    lines = text.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("Unclassified escalations:"))
    end = next(i for i in range(start + 1, len(lines)) if not lines[i].startswith("  "))
    return lines[start:end]


def test_the_report_shows_unclassified_escalations_n_of_m_with_percent():
    """AC-088.19: `Unclassified escalations: <n> of <m> (<p>%)`, right after the top reasons and before the reruns."""
    text = runs_report.render_text(agg_of(mixed()))
    assert "Unclassified escalations: 2 of 6 (33%)" in text.splitlines()
    assert text.index("Top escalation reasons:") < text.index("Unclassified escalations:") < text.index("Reruns by reason:")


def test_the_percentage_is_rounded_half_up_without_decimals():
    """AC-088.19: `<p>` is floor(100 * n / m + 0.5): 1 of 8 is 13%, 0 of 6 is 0%."""
    one_of_eight = [erec("a", esc("who knows"))] + [erec(f"b{i}", esc("x", **GIVEN)) for i in range(7)]
    assert "Unclassified escalations: 1 of 8 (13%)" in runs_report.render_text(agg_of(one_of_eight))
    none_unknown = [erec(f"b{i}", esc("x", **GIVEN)) for i in range(6)]
    assert "Unclassified escalations: 0 of 6 (0%)" in runs_report.render_text(agg_of(none_unknown))


def test_the_report_shows_the_classified_by_rule_count():
    """AC-088.19: the classified-by-rule count follows the first line, then each still unknown reason with its count."""
    assert block(runs_report.render_text(agg_of(mixed()))) == [
        "Unclassified escalations: 2 of 6 (33%)", "  classified by rule: 3", "  2  needs a decision on rate limits"]


def test_unknown_reasons_are_listed_most_frequent_first_at_most_20():
    """AC-088.19: most frequent first (ties by text), at most 20, then `… and <k> more`."""
    records = [erec(f"a{i}", esc("rare reason")) for i in range(3)] + [erec("one", esc("a single reason"))]
    records += [erec(f"d{i}", esc(f"distinct reason {i:02d}")) for i in range(22)]       # 24 distinct reasons in all
    lines = block(runs_report.render_text(agg_of(records)))
    assert lines[0] == "Unclassified escalations: 26 of 26 (100%)" and lines[1] == "  classified by rule: 0"
    reasons = lines[2:-1]
    assert len(reasons) == 20 and reasons[0] == "  3  rare reason"
    assert reasons[1] == "  1  a single reason" and reasons[2] == "  1  distinct reason 00"       # ties: by reason text
    assert lines[-1] == "  … and 4 more"


def test_no_more_line_when_every_reason_fits():
    """AC-088.19: exactly 20 distinct reasons: no `… and <k> more` line."""
    records = [erec(f"d{i}", esc(f"distinct reason {i:02d}")) for i in range(20)]
    lines = block(runs_report.render_text(agg_of(records)))
    assert len(lines) == 2 + 20 and not any("more" in ln for ln in lines)


def test_no_escalation_in_the_window_reads_none():
    """AC-088.19: no escalation in the window: one line `Unclassified escalations: none`."""
    text = runs_report.render_text(agg_of([rec("a", "2026-10-23T10:00:00Z")]))
    assert block(text) == ["Unclassified escalations: none"]
    assert text.index("Top escalation reasons:") < text.index("Unclassified escalations: none") < text.index("Reruns by reason:")


def test_the_json_report_has_the_unclassified_key():
    """AC-088.19: `unclassified` after `pr_wait` with count, escalations, share, by_rule and reasons, in that order."""
    agg = agg_of(mixed())
    assert list(agg)[-1] == "unclassified" and list(agg).index("pr_wait") + 1 == list(agg).index("unclassified")
    u = agg["unclassified"]
    assert list(u) == ["count", "escalations", "share", "by_rule", "reasons"]
    assert (u["count"], u["escalations"], u["share"], u["by_rule"]) == (2, 6, 0.333, 3)
    assert u["reasons"] == [{"reason": "needs a decision on rate limits", "count": 2}]


def test_the_json_key_without_escalations_has_a_null_share():
    """AC-088.19: no escalation: zero counts, `share` null, no reasons."""
    assert agg_of([])["unclassified"] == {"count": 0, "escalations": 0, "share": None, "by_rule": 0, "reasons": []}


def test_the_json_reasons_are_capped_at_20_like_the_text():
    """AC-088.19: `reasons` holds at most 20 entries; `count` still counts every unknown escalation."""
    u = agg_of([erec(f"d{i}", esc(f"distinct reason {i:02d}")) for i in range(23)])["unclassified"]
    assert len(u["reasons"]) == 20 and u["count"] == 23 and u["escalations"] == 23 and u["share"] == 1.0
    assert u["reasons"][0] == {"reason": "distinct reason 00", "count": 1}
    assert runs_report.MAX_UNCLASSIFIED == 20


def test_older_unknown_records_are_counted_under_the_rules_cause():
    """AC-088.21: an older `unknown` record (no `cause_source`) that a rule now matches counts under the rule's cause and as by rule."""
    old = [erec("o1", {"reason": "waiting for approval to create the branch", "cause": "unknown"}),
           erec("o2", {"reason": "stopped: working tree is dirty"}),
           erec("o3", {"reason": "who knows", "cause": "unknown"}),
           erec("o4", {"reason": "working tree is dirty", "cause": "code"})]
    agg = agg_of(old)
    assert agg["causes"] == {"environment": 2, "unknown": 1, "code": 1}
    u = agg["unclassified"]
    assert (u["count"], u["escalations"], u["by_rule"]) == (1, 4, 2) and u["reasons"] == [{"reason": "who knows", "count": 1}]
    text = runs_report.render_text(agg)
    assert "environment 2" in text and "Unclassified escalations: 1 of 4 (25%)" in text and "  classified by rule: 2" in text


def test_effective_escalation_is_none_without_an_escalation():
    """AC-088.21: `effective_escalation` gives None for a record without an escalation dict and the resolved cause otherwise."""
    assert runs_report.effective_escalation(rec("a", "2026-10-23T10:00:00Z")) is None
    res = runs_report.effective_escalation(erec("b", {"reason": "left for the user to review", "cause": "unknown"}))
    assert (res.cause, res.source, res.rule) == ("decision", "rule", "left-for-review")


def test_reading_does_not_rewrite_the_store(store, capsys):
    """AC-088.21: the report classifies on read; the stored files stay byte for byte the same and nothing is put."""
    put(store, erec("o1", {"reason": "waiting for approval to create the branch", "cause": "unknown"}))
    before, puts = copy.deepcopy(store.files), len(store.puts)
    assert runs.main(["report", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["causes"] == {"environment": 1} and out["unclassified"]["by_rule"] == 1
    assert runs.main(["report"]) == 0
    assert store.files == before and len(store.puts) == puts
