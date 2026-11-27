"""Spec 177 acceptance tests: `cplat issue triage` asks reporters plainly (AC-177.1, AC-177.2) and closes what needs no work
(AC-177.3, AC-177.4) through batch, confirm, act and the two gh seams, against the fake GitHub of `support_176` (extended here
with the closed `needs-info` issues of the new `waiting_closed` alias)."""
import json

import pytest

import core
import triage
from support_176 import SLUG, ago, comment, node, row, world  # noqa: F401  (fixture)

BUG = """name: Bug report
body:
  - type: textarea
    id: what
    attributes: {label: What happened}
    validations: {required: true}
  - type: textarea
    id: steps
    attributes: {label: Steps to reproduce}
    validations: {required: true}
  - type: input
    id: env
    attributes: {label: Environment}
"""
FEATURE = """name: Feature request
body:
  - type: textarea
    id: problem
    attributes: {label: Problem to solve}
    validations: {required: true}
"""
FILED = "### What happened\n\nIt broke\n\n### Steps to reproduce\n\n_No response_\n\n### Environment\n\nmac\n"
THANKS = "Thanks for the report. Could you add the Steps to reproduce?"


@pytest.fixture()
def w(world, monkeypatch):
    """The world with forms in the working tree and a `waiting_closed` list in the fake GraphQL answer."""
    world.waiting_closed = []
    fake = world

    def gh(args):
        out = fake(args)
        if args[:2] == ["api", "graphql"] and out:
            data = json.loads(out)
            if "data" in data:
                data["data"]["repository"]["waiting_closed"] = {"nodes": fake.waiting_closed}
                return json.dumps(data)
        return out

    monkeypatch.setattr(triage, "gh", gh)
    d = world.tmp / ".github" / "ISSUE_TEMPLATE"
    d.mkdir(parents=True)
    (d / "bug_report.yml").write_text(BUG)
    (d / "feature_request.yml").write_text(FEATURE)
    return world


def needs_info(**kw):
    return {"class": "needs-info", "priority": None, "priority_reason": None, "expected": None, **kw}


def refused(w, *argv):
    with pytest.raises(core.PlatformError) as err:
        w.run(*argv)
    return str(err.value) + "\n" + (err.value.hint or "")


def confirm(w, rows, *extra):
    return w.run("confirm", "--proposals", w.proposals(rows), *extra)


def act(w, rows, rows_arg="all", *extra):
    return w.run("act", "--proposals", w.proposals(rows), "--rows", rows_arg, *extra)


def calls(w, kind):
    """The gh calls `issue <kind> N …` in order, as (position, number, args)."""
    return [(i, int(c[2]), c) for i, c in enumerate(w.calls) if c[:2] == ["issue", kind]]


def issue_of(w, n, data=None):
    got = w.by_number(data).get(n)
    assert got is not None, f"#{n} is not in the batch"
    return got


def key_of(got, key):
    assert key in got, f"{key!r} is missing (have {sorted(got)})"
    return got[key]


def line_of(lines, start):
    found = [l for l in lines if l.startswith(start)]
    assert found, f"no line starts with {start!r}"
    return found[0]


def reporter():
    try:
        import triage_reporter
    except ModuleNotFoundError:
        pytest.fail("triage_reporter is missing (AC-177.2, AC-177.4)")
    return triage_reporter


def silent_issue(w, n=12, days=14):
    w.issue(n, title="Old question", labels=("needs-info",), created=ago(days=days, hours=1))
    return n


def closed_issue(w, n=7, comments=None, reason="NOT_PLANNED"):
    got = node(n, title="Closed, waiting", labels=("needs-info",), author="rep", assoc="NONE", created=ago(days=30),
               comments=comments if comments is not None else [comment("me", "Which version?", "OWNER", ago(days=10)),
                                                                comment("rep", "Version 2", "NONE", ago(days=1))])
    got.update(closedAt=ago(days=5), stateReason=reason)
    w.waiting_closed.append(got)
    return n


# ---------------- AC-177.1: the batch names the form and the missing fields ----------------

def test_the_batch_carries_the_forms_and_the_missing_fields_of_a_form_filed_issue_ac_177_1(w):  # AC-177.1
    w.issue(1, body=FILED)
    data = w.batch()
    assert [f["id"] for f in key_of(data, "forms")] ==["bug_report", "feature_request"]
    assert key_of(issue_of(w, 1, data), "form") == {"id": "bug_report", "missing": ["Steps to reproduce"]}


def test_an_issue_filed_without_a_form_has_no_form_and_no_missing_fields_ac_177_1(w):  # AC-177.1
    w.issue(1, body="it just broke")
    assert key_of(issue_of(w, 1, w.batch()), "form") == {"id": None, "missing": []}


def test_a_needs_info_row_needs_the_missing_fields_ac_177_1(w):  # AC-177.1
    w.issue(1, body=FILED)
    w.batch()
    text = refused(w, "confirm", "--proposals", w.proposals([row(1, **needs_info(comment=THANKS))]))
    assert "#1: a needs-info row needs missing (the fields to ask the reporter for)" in text


def test_the_missing_list_must_hold_every_missing_field_of_the_form_ac_177_1(w):  # AC-177.1
    w.issue(1, body=FILED)
    w.batch()
    text = refused(w, "confirm", "--proposals", w.proposals([row(1, **needs_info(comment=THANKS, missing=["Environment"]))]))
    assert '#1: missing leaves out "Steps to reproduce", empty in the form' in text


def test_the_missing_list_names_only_fields_of_the_form_ac_177_1(w):  # AC-177.1
    w.issue(1, body=FILED)
    w.batch()
    text = refused(w, "confirm", "--proposals", w.proposals([row(1, **needs_info(comment=THANKS, missing=["Steps to reproduce", "Colour"]))]))
    assert '#1: missing names "Colour", not a field of Bug report' in text


def test_an_issue_filed_without_a_form_needs_the_matching_form_in_its_row_ac_177_1(w):  # AC-177.1
    w.issue(1, body="it just broke")
    w.batch()
    text = refused(w, "confirm", "--proposals", w.proposals([row(1, **needs_info(comment=THANKS, missing=["What happened"]))]))
    assert "#1: a needs-info row of an issue filed without a form needs form (one of bug_report, feature_request)" in text


def test_a_row_of_an_issue_without_a_form_is_valid_with_form_and_missing_fields_ac_177_1(w):  # AC-177.1
    w.issue(1, body="it just broke")
    w.batch()
    assert key_of(issue_of(w, 1), "form")["id"] is None and key_of(w.data, "forms")
    comment_ = "Thank you for the report. Please tell us What happened and the Steps to reproduce."
    ok = row(1, **needs_info(comment=comment_, missing=["What happened", "Steps to reproduce"], form="bug_report"))
    assert confirm(w, [ok]).rc == 0


def test_a_row_for_a_form_filed_issue_is_valid_ac_177_1(w):  # AC-177.1
    w.issue(1, body=FILED)
    w.batch()
    assert key_of(issue_of(w, 1), "form")["missing"] == ["Steps to reproduce"]
    assert confirm(w, [row(1, **needs_info(comment=THANKS, missing=["Steps to reproduce"]))]).rc == 0


def test_the_overview_shows_the_missing_fields_of_a_needs_info_row_ac_177_1(w):  # AC-177.1
    w.issue(1, body=FILED)
    w.batch()
    path = w.proposals([row(1, **needs_info(comment=THANKS, missing=["Steps to reproduce"]))])
    assert "missing: Steps to reproduce" in w.run("overview", "--proposals", path).out


# ---------------- AC-177.2: a comment to an outside reporter is plain ----------------

def one_row(w, cls_kw, assoc="NONE", body=FILED):
    w.issue(1, body=body, assoc=assoc)
    w.batch()
    return refused(w, "confirm", "--proposals", w.proposals([row(1, **cls_kw)]))


def test_a_comment_to_an_outside_reporter_with_internal_terms_is_refused_ac_177_2(w):  # AC-177.2
    text = one_row(w, {"class": "wontfix", "priority": None, "priority_reason": None, "expected": None,
                       "comment": "Thanks. See spec 176 and /component:fix."})
    assert "#1: the comment to an outside reporter uses internal terms: spec 176, /component:fix; use plain words" in text


def test_a_label_name_is_an_internal_term_ac_177_2(w):  # AC-177.2
    text = one_row(w, needs_info(comment="Thanks, the issue keeps the needs-info label. Steps to reproduce?", missing=["Steps to reproduce"]))
    assert "uses internal terms" in text and "needs-info" in text


def test_a_needs_info_comment_must_thank_the_reporter_ac_177_2(w):  # AC-177.2
    text = one_row(w, needs_info(comment="Please add the Steps to reproduce.", missing=["Steps to reproduce"]))
    assert "#1: the comment to an outside reporter does not thank them" in text


def test_a_needs_info_comment_must_ask_for_each_missing_field_ac_177_2(w):  # AC-177.2
    text = one_row(w, needs_info(comment="Thanks for the report, it helps.", missing=["Steps to reproduce"]))
    assert '#1: the comment does not ask for "Steps to reproduce"' in text


def test_the_public_commands_are_allowed_in_a_comment_to_an_outside_reporter_ac_177_2(w):  # AC-177.2
    w.issue(1, body=FILED)
    w.batch()
    text = "Thanks. Run /platform:doctor, send us the Steps to reproduce, or file it with /issue:report."
    assert "uses internal terms" in refused(w, "confirm", "--proposals", w.proposals(
        [row(1, **needs_info(comment=text + " See spec 176.", missing=["Steps to reproduce"]))]))
    assert confirm(w, [row(1, **needs_info(comment=text, missing=["Steps to reproduce"]))]).rc == 0


@pytest.mark.parametrize("assoc", ["OWNER", "MEMBER", "COLLABORATOR"])
def test_a_writer_may_get_internal_terms_and_needs_no_thanks_ac_177_2(w, assoc):  # AC-177.2
    w.issue(1, body=FILED, assoc=assoc)
    w.issue(2, body=FILED)
    w.batch()
    text = "Tracked in spec 176; the needs-info label is set, give the Steps to reproduce."
    ask = needs_info(comment=text, missing=["Steps to reproduce"])
    found = refused(w, "confirm", "--proposals", w.proposals([row(1, **ask), row(2, **ask)]))   # only #2 is an outside reporter
    assert "#2: the comment to an outside reporter uses internal terms" in found and "#1:" not in found


def test_the_shown_comment_ends_with_the_days_and_reopen_sentence_ac_177_2(w):  # AC-177.2
    triage_reporter = reporter()
    w.issue(1, body=FILED)
    w.batch()
    shown = confirm(w, [row(1, **needs_info(comment=THANKS, missing=["Steps to reproduce"]))], "--show", "1").out
    assert THANKS in shown and triage_reporter.footer(14) in shown
    assert "within 14 days" in shown and "reopens the review" in shown


def test_the_days_in_the_comment_follow_the_project_setting_ac_177_2(w):  # AC-177.2
    (w.tmp / ".platform-settings.yml").write_text("needs_info_close_days: 30\n")
    w.issue(1, body=FILED)
    w.batch()
    shown = confirm(w, [row(1, **needs_info(comment=THANKS, missing=["Steps to reproduce"]))], "--show", "1").out
    assert "within 30 days" in shown and "within 14 days" not in shown


def test_act_posts_the_comment_with_the_days_sentence_and_keeps_the_issue_open_ac_177_2(w):  # AC-177.2
    triage_reporter = reporter()
    w.issue(1, body=FILED)
    w.batch()
    act(w, [row(1, **needs_info(comment=THANKS, missing=["Steps to reproduce"]))])
    posted = w.comments()[1]
    assert posted.startswith(THANKS) and posted.endswith(triage_reporter.footer(14))
    assert calls(w, "close") == []


# ---------------- AC-177.3: confirmed duplicate, question, wontfix are closed as not planned ----------------

CLOSING = [("question", {"comment": "See the docs page on tokens."}),
           ("duplicate", {"comment": "Same problem as the other one.", "duplicate_of": 2}),
           ("wontfix", {"comment": "We will not do this because it conflicts with the design."})]


def closing_row(n, cls, extra):
    return row(n, **{"class": cls, "priority": None, "priority_reason": None, "expected": None, **extra})


@pytest.mark.parametrize("cls,extra", CLOSING)
def test_act_posts_the_comment_then_closes_the_issue_as_not_planned_ac_177_3(w, cls, extra):  # AC-177.3
    w.issue(1, assoc="OWNER")
    w.issue(2, assoc="OWNER")
    w.batch()
    assert act(w, [closing_row(1, cls, extra), row(2)], "1").rc == 0
    closes = calls(w, "close")
    assert [n for _, n, _ in closes] == [1]
    args = closes[0][2]
    assert args[args.index("--reason") + 1] == "not planned"
    comment_at = next(i for i, c in enumerate(w.calls) if c[:2] == ["issue", "comment"] and c[2] == "1")
    assert comment_at < closes[0][0]
    assert w.comments()[1].endswith(extra["comment"])


def test_a_duplicate_comment_links_the_original_ac_177_3(w):  # AC-177.3
    w.issue(1, assoc="OWNER")
    w.issue(2, assoc="OWNER")
    w.batch()
    act(w, [closing_row(1, "duplicate", {"comment": "Same problem as the other one.", "duplicate_of": 2}), row(2)], "1")
    assert w.comments()[1].startswith("Duplicate of #2")


def test_a_duplicate_comment_that_already_starts_with_the_link_is_not_prefixed_twice_ac_177_3(w):  # AC-177.3
    w.issue(1, assoc="OWNER")
    w.issue(2, assoc="OWNER")
    w.batch()
    act(w, [closing_row(1, "duplicate", {"comment": "Duplicate of #2, same crash.", "duplicate_of": 2}), row(2)], "1")
    assert w.comments()[1].count("Duplicate of #2") == 1 and [n for _, n, _ in calls(w, "close")] == [1]


@pytest.mark.parametrize("cls,extra", CLOSING)
def test_an_unconfirmed_row_is_never_closed_ac_177_3(w, cls, extra):  # AC-177.3
    w.issue(1, assoc="OWNER")
    w.issue(2, assoc="OWNER")
    w.batch()
    rows = [closing_row(1, cls, extra), row(2)]
    act(w, rows, "2")
    assert calls(w, "close") == [] and 1 not in w.comments() and 1 not in w.edits()
    act(w, rows, "1")
    assert [n for _, n, _ in calls(w, "close")] == [1]


@pytest.mark.parametrize("cls,extra", [("bug", {}), ("small-change", {}),
                                       ("feature", {"spec": "201-new-thing", "new_spec": True, "expected": None}),
                                       ("needs-exploring", {"priority": None, "priority_reason": None, "expected": None})])
def test_the_other_classes_are_never_closed_ac_177_3(w, cls, extra):  # AC-177.3
    w.spec("201-new-thing", status="draft")
    w.issue(1, assoc="OWNER")
    w.issue(2, assoc="OWNER")
    w.batch()
    act(w, [row(1, **{"class": cls, **extra}), closing_row(2, "question", {"comment": "See the docs."})])
    assert [n for _, n, _ in calls(w, "close")] == [2]


def test_the_confirmation_says_which_rows_close_as_not_planned_ac_177_3(w):  # AC-177.3
    w.issue(1, assoc="OWNER")
    w.issue(2, assoc="OWNER")
    w.batch()
    rows = [closing_row(1, "question", {"comment": "See the docs."}), row(2)]
    lines = confirm(w, rows).lines
    one = line_of(lines, "  #1 ")
    two = line_of(lines, "  #2 ")
    assert one.endswith(", close as not planned") and "close as not planned" not in two


def test_show_names_the_state_change_ac_177_3(w):  # AC-177.3
    w.issue(1, assoc="OWNER")
    w.issue(2, assoc="OWNER")
    w.batch()
    rows = [closing_row(1, "question", {"comment": "See the docs."}), row(2)]
    assert "state: close as not planned" in confirm(w, rows, "--show", "1").out.splitlines()
    assert "state: unchanged" in confirm(w, rows, "--show", "2").out.splitlines()


def test_actions_of_a_closing_row_close_and_do_not_reopen_ac_177_3(w):  # AC-177.3
    import triage_view
    w.issue(1, assoc="OWNER")
    w.issue(2, assoc="OWNER")
    w.batch()
    rows = triage_view.load_proposals(w.proposals([closing_row(1, "wontfix", {"comment": "No, by design."}), row(2)]), w.data)
    issues = w.by_number()
    a = triage_view.actions(issues[1], rows[0])
    assert key_of(a, "close") is True and key_of(a, "reopen") is False and a["comment"] == "No, by design." and "wontfix" in a["add"]
    b = triage_view.actions(issues[2], rows[1])
    assert key_of(b, "close") is False and key_of(b, "reopen") is False


def test_the_json_summary_says_closed_and_the_undo_lists_a_reopen_ac_177_3(w):  # AC-177.3
    w.issue(1, assoc="OWNER")
    w.issue(2, assoc="OWNER")
    w.batch()
    data = act(w, [closing_row(1, "question", {"comment": "See the docs."}), row(2)], "all", "--json").json()
    done = {d["number"]: d for d in data["done"]}
    assert key_of(done[1], "closed") is True and key_of(done[1], "reopened") is False and key_of(done[2], "closed") is False
    assert "#1: gh issue reopen 1" in data["undo"]


def test_the_summary_says_answered_and_closed_ac_177_3(w):  # AC-177.3
    w.issue(1, assoc="OWNER")
    w.batch()
    assert "answered and closed" in act(w, [closing_row(1, "question", {"comment": "See the docs."})]).out


def test_the_summary_says_closed_as_duplicate_of_the_original_ac_177_3(w):  # AC-177.3
    w.issue(1, assoc="OWNER")
    w.issue(2, assoc="OWNER")
    w.batch()
    assert "closed as duplicate of #2" in act(w, [closing_row(1, "duplicate", {"comment": "Same.", "duplicate_of": 2}), row(2)], "1").out


def test_the_dry_run_closes_nothing_ac_177_3(w):  # AC-177.3
    w.issue(1, assoc="OWNER")
    w.batch()
    out = act(w, [closing_row(1, "question", {"comment": "See the docs."})], "all", "--dry-run").out
    assert calls(w, "close") == [] and "close as not planned" in out


def test_an_unattended_run_refuses_to_close_before_any_write_ac_177_3(w, monkeypatch):  # AC-177.3
    monkeypatch.setenv("CPLAT_HEADLESS", "1")
    w.issue(1, assoc="OWNER")
    w.issue(2, assoc="OWNER")
    w.batch()
    rows = [row(1, **{"class": "needs-exploring", "priority": None, "expected": None}), closing_row(2, "question", {"comment": "See docs."})]
    text = refused(w, "act", "--proposals", w.proposals(rows), "--rows", "all")
    assert "closing an issue needs the user's confirmation" in text and "run /issue:triage in a Claude Code session" in text
    assert w.writes() == [] and calls(w, "close") == []


def test_close_one_runs_one_gh_close_with_the_reason_and_its_undo_ac_177_3(w):  # AC-177.3
    report = triage.close_one(SLUG, 5, False)
    assert [c for c in w.calls if c[:2] == ["issue", "close"]] == [["issue", "close", "5", "-R", SLUG, "--reason", "not planned"]]
    assert "gh issue reopen 5" in " ".join(report.undo)


def test_close_one_dry_run_calls_nothing_ac_177_3(w):  # AC-177.3
    report = triage.close_one(SLUG, 5, True)
    assert calls(w, "close") == [] and "[outward] close as not planned" in report.will_do


def test_reopen_one_runs_one_gh_reopen_and_has_a_close_undo_ac_177_3(w):  # AC-177.3
    report = triage.reopen_one(None, 5, False)
    assert [c for c in w.calls if c[:2] == ["issue", "reopen"]] == [["issue", "reopen", "5"]]
    assert 'gh issue close 5 --reason "not planned"' in " ".join(report.undo)
    triage.reopen_one(SLUG, 6, True)
    assert [n for _, n, _ in calls(w, "reopen")] == [5]


def test_refuse_unattended_close_only_refuses_a_headless_run_ac_177_3(monkeypatch):  # AC-177.3
    monkeypatch.delenv("CPLAT_HEADLESS", raising=False)
    triage.refuse_unattended_close()
    monkeypatch.setenv("CPLAT_HEADLESS", "1")
    with pytest.raises(core.PlatformError) as err:
        triage.refuse_unattended_close()
    assert "closing an issue needs the user's confirmation" in str(err.value)


# ---------------- AC-177.4: silent needs-info issues are proposed for closing ----------------

def test_a_needs_info_issue_silent_for_14_days_is_proposed_for_closing_ac_177_4(w):  # AC-177.4
    silent_issue(w)
    data = w.batch()
    got = issue_of(w, 12, data)
    handled = key_of(got, "handled")
    assert handled["kind"] == "silent" and handled["line"].startswith("silent ") and "close with a final comment" in handled["line"]
    assert key_of(got, "state") == "open" and key_of(data, "close_after_days") == 14
    assert all(s["number"] != 12 for s in data["skipped"])


def test_a_needs_info_issue_silent_for_13_days_stays_skipped_ac_177_4(w):  # AC-177.4
    silent_issue(w, days=13)
    silent_issue(w, n=13, days=14)
    data = w.batch()
    assert key_of(issue_of(w, 13, data), "handled")["kind"] == "silent"
    assert 12 not in w.by_number(data) and any(s["number"] == 12 and s["reason"].startswith("silent ") for s in data["skipped"])


def test_the_days_come_from_the_project_setting_ac_177_4(w):  # AC-177.4
    (w.tmp / ".platform-settings.yml").write_text("needs_info_close_days: 30\n")
    silent_issue(w, n=12, days=20)
    silent_issue(w, n=13, days=31)
    data = w.batch()
    assert key_of(data, "close_after_days") == 30 and set(w.by_number(data)) == {13}


def test_a_silent_issue_needs_no_row_and_appears_in_the_confirmation_ac_177_4(w):  # AC-177.4
    silent_issue(w)
    w.batch()
    lines = confirm(w, []).lines
    line = line_of(lines, "  #12 ")
    assert line.startswith("  #12  needs-info, silent ") and line.endswith("days: close as not planned with a final comment")


def test_the_overview_lists_the_silent_issue_under_already_handled_ac_177_4(w):  # AC-177.4
    silent_issue(w)
    w.batch()
    assert w.run("overview", "--proposals", w.proposals([]), "--json").json()["groups"]["handled"] == [12]


def test_act_closes_a_silent_issue_with_the_final_comment_only_when_named_ac_177_4(w):  # AC-177.4
    triage_reporter = reporter()
    silent_issue(w)
    w.issue(2, assoc="OWNER")
    w.batch()
    act(w, [row(2)], "2")
    assert calls(w, "close") == [] and 12 not in w.comments()
    act(w, [row(2)], "12")
    assert [n for _, n, _ in calls(w, "close")] == [12]
    assert w.comments()[12] == triage_reporter.final_comment(14)
    assert 12 not in w.edits()                       # the close keeps the needs-info label


def test_the_summary_says_closed_after_days_without_an_answer_ac_177_4(w):  # AC-177.4
    silent_issue(w)
    w.batch()
    out = act(w, [], "12").out
    assert "closed after" in out and "days without an answer" in out


def test_a_silent_issue_is_not_closed_by_a_headless_run_ac_177_4(w, monkeypatch):  # AC-177.4
    monkeypatch.setenv("CPLAT_HEADLESS", "1")
    silent_issue(w)
    w.batch()
    assert "closing an issue needs the user's confirmation" in refused(w, "act", "--proposals", w.proposals([]), "--rows", "12")
    assert calls(w, "close") == []


# ---------------- AC-177.4: a reporter comment on a closed needs-info issue puts it back in the queue ----------------

def test_a_reporter_comment_after_the_close_queues_the_closed_issue_ac_177_4(w):  # AC-177.4
    closed_issue(w)
    got = w.by_number(w.batch())
    assert 7 in got and key_of(got[7], "state") == "closed" and "needs-info" in got[7]["labels"]


def test_a_closed_issue_without_a_reporter_comment_after_the_close_stays_out_ac_177_4(w):  # AC-177.4
    closed_issue(w, comments=[comment("me", "Which version?", "OWNER", ago(days=10)), comment("rep", "Version 2", "NONE", ago(days=8))])
    closed_issue(w, n=8)
    assert {7, 8} & set(w.by_number(w.batch())) == {8}


def test_a_comment_by_someone_else_after_the_close_does_not_queue_it_ac_177_4(w):  # AC-177.4
    closed_issue(w, comments=[comment("other", "me too", "NONE", ago(days=1))])
    closed_issue(w, n=8)
    assert {7, 8} & set(w.by_number(w.batch())) == {8}


def test_an_issue_closed_as_completed_stays_out_ac_177_4(w):  # AC-177.4
    closed_issue(w, reason="COMPLETED")
    closed_issue(w, n=8)
    assert {7, 8} & set(w.by_number(w.batch())) == {8}


def test_a_batch_answer_without_the_closed_alias_reads_as_no_closed_issues_ac_177_4(world):  # AC-177.4
    world.issue(1)
    assert key_of(issue_of(world, 1, world.batch()), "state") == "open"     # the plain fake gh has no waiting_closed


def test_act_reopens_a_requeued_issue_before_its_labels_and_comment_ac_177_4(w):  # AC-177.4
    closed_issue(w)
    w.batch()
    data = act(w, [row(7)], "all", "--json").json()
    reopen = calls(w, "reopen")
    assert [n for _, n, _ in reopen] == [7]
    after = [i for i, c in enumerate(w.calls) if c[:2] in (["issue", "edit"], ["issue", "comment"]) and c[2] == "7"]
    assert after and reopen[0][0] < min(after)
    assert key_of(next((d for d in data["done"] if d["number"] == 7), {}), "reopened") is True
    assert calls(w, "close") == []


def test_the_confirmation_and_the_overview_say_reopen_ac_177_4(w):  # AC-177.4
    closed_issue(w)
    w.batch()
    path = w.proposals([row(7)])
    line = line_of(w.run("confirm", "--proposals", path).lines, "  #7 ")
    assert line.startswith("  #7  reopen, ")
    assert "state: reopen" in w.run("confirm", "--proposals", path, "--show", "7").out.splitlines()
    assert "reopened by the reporter" in w.run("overview", "--proposals", path).out


def test_a_requeued_issue_answered_with_a_closing_class_stays_closed_ac_177_4(w):  # AC-177.4
    closed_issue(w)
    w.batch()
    path = w.proposals([closing_row(7, "question", {"comment": "See the docs."})])
    assert "state: unchanged" in w.run("confirm", "--proposals", path, "--show", "7").out.splitlines()
    act(w, [closing_row(7, "question", {"comment": "See the docs."})])
    assert calls(w, "reopen") == [] and calls(w, "close") == []
