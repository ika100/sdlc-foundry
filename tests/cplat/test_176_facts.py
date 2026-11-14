"""Spec 176 acceptance tests: the facts the script finds (AC-176.5 duplicates, AC-176.6 engine route, AC-176.7 reply state, and
the status facts and author role of AC-176.1). The pure helpers of `triage_facts` are called directly; the rest runs through
`cplat issue triage batch --json`, `list --waiting` and `show` against a fake GitHub (`support_176`)."""
import json

import pytest

import claim
import triage
from support_176 import SIG, SLUG, ago, comment, engine_body, load, node, world  # noqa: F401  (fixture)


# ---------------- author role (AC-176.1) ----------------

@pytest.mark.parametrize("assoc,role", [("OWNER", "owner"), ("MEMBER", "member"), ("COLLABORATOR", "collaborator"),
                                        ("CONTRIBUTOR", "contributor"), ("FIRST_TIME_CONTRIBUTOR", "contributor"),
                                        ("FIRST_TIMER", "none"), ("NONE", "none"), ("MANNEQUIN", "none"), (None, "none")])
def test_the_author_role_follows_the_association_ac_176_1(assoc, role):  # AC-176.1
    assert load("triage_facts").role(assoc) == role


def test_owner_member_and_collaborator_are_the_writers_ac_176_1():  # AC-176.1
    facts = load("triage_facts")
    assert [facts.is_writer(r) for r in ("owner", "member", "collaborator", "contributor", "none")] == [True, True, True, False, False]


@pytest.mark.parametrize("seconds,text", [(59 * 60, "59m"), (3600, "1h"), (47 * 3600, "47h"), (48 * 3600, "2d"), (5 * 86400 + 100, "5d")])
def test_an_age_is_minutes_hours_or_days_rounded_down_ac_176_7(seconds, text):  # AC-176.7
    assert load("triage_facts").age(seconds) == text


# ---------------- the batch carries role, status facts, one request (AC-176.1) ----------------

def test_the_batch_returns_every_queued_issue_with_its_facts_from_one_request_ac_176_1(world):  # AC-176.1
    world.issue(1, assoc="CONTRIBUTOR", author="outsider", comments=[comment("me", "seen", "OWNER")])
    world.issue(2, assoc="OWNER", author="me")
    world.issue(3, labels=("tracked",))
    data = world.batch()
    assert [i["number"] for i in data["issues"]] == [1, 2]
    one = world.by_number()[1]
    assert one["role"] == "contributor" and one["author"] == "outsider"
    for key in ("title", "body", "comments", "duplicates", "engine", "reply", "status", "handled", "labels", "priority_labels"):
        assert key in one, key
    assert [c["role"] for c in one["comments"]] == ["owner"]
    assert [c[:2] for c in world.calls] == [["api", "graphql"]]
    assert "owner=acme" in world.calls[0] and "name=shop" in world.calls[0]


def test_the_batch_is_saved_where_the_next_steps_read_it_ac_176_1(world):  # AC-176.1
    world.issue(1)
    data = world.batch()
    path = world.batch_path()
    assert path.name == "batch.json" and path.parent.name == "acme__shop" and path.parent.parent.name == "triage"
    saved = json.loads(path.read_text())
    assert saved["repo"] == SLUG and [i["number"] for i in saved["issues"]] == [1] and saved["read_at"]
    assert data["repo"] == SLUG


def test_body_and_comments_are_redacted_fenced_and_cut_ac_176_1(world):  # AC-176.1
    world.issue(1, title="Crash for me@example.com", body="token ghp_" + "a" * 30 + " " + "word " * 3000,
                comments=[comment("x", "mail me@example.com " + "y" * 3000)])
    one = world.batch()["issues"][0]
    assert "@example.com" not in one["title"] and "ghp_" not in one["body"]
    assert "untrusted issue text" in one["body"] and "end of untrusted text" in one["body"] and "[truncated]" in one["body"]
    text = one["comments"][0]["text"]
    assert "untrusted issue text" in text and "@example.com" not in text and "[truncated]" in text


def test_a_deleted_author_reads_as_ghost_and_errors_are_named_ac_176_1(world):  # AC-176.1
    world.issue(1, author=None)
    assert world.batch()["issues"][0]["author"] == "ghost"
    world.errors = "Could not resolve to a Repository"
    with pytest.raises(triage.PlatformError, match="reading the issues failed") as err:
        world.run("batch", "--json")
    assert "Could not resolve" in str(err.value) + (err.value.hint or "")


def test_the_batch_names_what_it_skipped_and_the_missing_labels_ac_176_1(world):  # AC-176.1
    for n in range(100, 200):
        world.issue(n, labels=())
    world.total = 123
    world.repo_labels = ["triage", "bug"]
    data = world.batch()
    assert {"number": None, "reason": "23 more open issues not read (limit 100)"} in data["skipped"]
    assert {"p0", "p1", "p2", "tracked"} <= set(data["missing_labels"]) and "bug" not in data["missing_labels"]


def test_the_batch_without_json_prints_a_line_per_issue_and_the_file_ac_176_1(world):  # AC-176.1
    world.issue(1, title="First")
    world.issue(2, title="Second", assoc="CONTRIBUTOR")
    out = world.run("batch").out
    lines = out.splitlines()
    assert any(l.startswith("#1") and "First" in l for l in lines) and any(l.startswith("#2") and "contributor" in l for l in lines)
    assert "batch.json" in out


def test_the_batch_carries_the_priority_labels_of_an_issue_ac_176_1(world):  # AC-176.1
    world.issue(1, labels=("triage", "p1", "bug"))
    assert world.batch()["issues"][0]["priority_labels"] == ["p1"]


# ---------------- status facts and handled (AC-176.1) ----------------

def status_world(w):
    w.spec("176-triage-x", tracks=[10, 11], status="approved")
    w.spec("150-other", tracks=[10], status="draft")
    w.issue(10)
    w.issue(11)
    w.issue(12, labels=("triage", "in-progress"),
            comments=[comment("me", f"{claim.MARK}\nClaimed for branch `fix/issue-12` (cplat dispatch).", "OWNER")])
    w.issue(13)
    w.issue(14)
    w.issue(15)
    w.issue(16, comments=[comment("me", "Duplicate of #15, same crash.", "OWNER")])
    w.issue(17, comments=[comment("stranger", "Duplicate of #15", "NONE")])
    w.merged = [{"number": 90, "title": "fix: thing", "body": "Fixes #13", "url": "u90", "closingIssuesReferences": {"nodes": []}},
                {"number": 91, "title": "fix: other", "body": "", "url": "u91", "closingIssuesReferences": {"nodes": [{"number": 13}]}},
                {"number": 92, "title": "fix: near miss", "body": "see #140 and #1", "url": "u92", "closingIssuesReferences": {"nodes": []}}]
    return w.batch()


def test_status_facts_name_specs_claim_pull_requests_and_the_duplicate_ac_176_1(world):  # AC-176.1
    status_world(world)
    by = world.by_number()
    assert [(s["id"], s["number"], s["status"]) for s in by[10]["status"]["specs"]] == [("150-other", "150", "draft"), ("176-triage-x", "176", "approved")]
    assert by[12]["status"]["claim"] == {"branch": "fix/issue-12"} and by[11]["status"]["claim"] is None
    assert sorted(p["number"] for p in by[13]["status"]["merged_prs"]) == [90, 91]
    assert by[14]["status"]["merged_prs"] == [] and by[16]["status"]["duplicate_of"] == 15
    assert by[17]["status"]["duplicate_of"] is None


def test_the_handled_line_follows_spec_claim_fix_duplicate_ac_176_1(world):  # AC-176.1
    status_world(world)
    by = world.by_number()
    assert by[11]["handled"] == {"kind": "spec", "line": "in spec 176 (approved)"}
    assert by[10]["handled"]["line"] == "in spec 150 (draft)"
    assert by[12]["handled"] == {"kind": "claimed", "line": "being worked on (fix/issue-12)"}
    assert by[13]["handled"] == {"kind": "fixed", "line": "fixed by #91"}
    assert by[16]["handled"] == {"kind": "duplicate", "line": "duplicate of #15"}
    assert by[14]["handled"] is None and by[17]["handled"] is None


# ---------------- AC-176.5 duplicates ----------------

def dup(by, n):
    return [(d["number"], d["reason"]) for d in by[n]["duplicates"]]


def test_the_same_signature_of_an_open_or_recently_closed_issue_is_a_candidate_ac_176_5(world):  # AC-176.5
    world.issue(1, title="alpha one", body=f"x\n\n{SIG}\n")
    world.issue(2, title="beta two", body=f"y\n\n{SIG}\n")
    world.issue(3, title="gamma three", body="Signature: signal:ffffffffffffffff\n")
    world.closed = [{"number": 8, "title": "delta four", "body": f"{SIG}\n", "closedAt": ago(days=10)},
                    {"number": 9, "title": "epsilon five", "body": f"{SIG}\n", "closedAt": ago(days=45)}]
    world.batch()
    by = world.by_number()
    assert dup(by, 1) == [(2, "same signature"), (8, "same signature")]
    assert dup(by, 2) == [(1, "same signature"), (8, "same signature")] and dup(by, 3) == []
    assert by[1]["duplicates"][0]["state"] == "open" and by[1]["duplicates"][1]["state"] == "closed"
    assert by[1]["duplicates"][0]["title"] == "beta two"


def test_similar_titles_of_open_issues_are_candidates_above_the_threshold_ac_176_5(world):  # AC-176.5
    world.issue(1, title="Login fails after token refresh on Safari")
    world.issue(2, title="Login fails after the token refresh on Safari browser")
    world.issue(3, title="Login page colours")
    world.issue(4, title="Safari export")
    world.closed = [{"number": 8, "title": "Login fails after token refresh on Safari", "body": "", "closedAt": ago(days=1)}]
    world.batch()
    by = world.by_number()
    assert dup(by, 1) == [(2, "similar title")] and dup(by, 2) == [(1, "similar title")]
    assert dup(by, 3) == [] and dup(by, 4) == []


def test_a_pair_matching_both_reasons_is_listed_once_and_never_the_issue_itself_ac_176_5(world):  # AC-176.5
    world.issue(1, title="Crash when config is empty", body=f"{SIG}\n")
    world.issue(2, title="Crash when config is empty again", body=f"{SIG}\n")
    world.batch()
    by = world.by_number()
    assert dup(by, 1) == [(2, "same signature")] and dup(by, 2) == [(1, "same signature")]


def test_show_lists_the_duplicate_candidates_too_ac_176_5(world):  # AC-176.5
    world.view = {**node(9, body=f"{SIG}\n"), "labels": [{"name": "triage"}], "author": {"login": "rep"}, "state": "OPEN", "url": "u", "comments": []}
    world.listing = [{"number": 9, "title": "issue 9", "body": f"{SIG}\n", "state": "OPEN", "closedAt": None},
                     {"number": 5, "title": "five", "body": f"{SIG}\n", "state": "OPEN", "closedAt": None},
                     {"number": 6, "title": "six", "body": "other", "state": "OPEN", "closedAt": None}]
    out = world.run("show", "9", "--json").json()
    assert out["duplicates"] == [{"number": 5, "title": "five", "state": "open", "reason": "same signature"}]
    assert any(c[:2] == ["issue", "list"] and "all" in c for c in world.calls)


# ---------------- AC-176.6 engine route ----------------

def test_an_engine_issue_carries_route_confidence_and_files_ac_176_6(world):  # AC-176.6
    world.issue(1, labels=("triage", "signal"), body=engine_body("fix", 0.9, ("a.py", "b.py")))
    world.issue(2, labels=("triage", "signal"), body=engine_body("fix", 0.5, key="k2"))
    world.issue(3, labels=("triage", "signal"), body=engine_body("spec", 0.7, key="k3"))
    world.issue(4, labels=("triage", "signal"), body=engine_body("investigate", 0.95, key="k4"))
    world.issue(5, labels=("triage", "signal"), body=engine_body("small-change", 0.8, key="k5"))
    world.batch()
    by = world.by_number()
    assert by[1]["engine"] == {"route": "fix", "confidence": 0.9, "suspected_files": ["a.py", "b.py"], "class": "bug", "mark": "sure"}
    assert (by[2]["engine"]["class"], by[2]["engine"]["mark"]) == ("bug", "check")
    assert (by[3]["engine"]["class"], by[3]["engine"]["mark"]) == ("feature", "sure")
    assert (by[4]["engine"]["class"], by[4]["engine"]["mark"]) == (None, "check")
    assert (by[5]["engine"]["class"], by[5]["engine"]["mark"]) == ("small-change", "sure")


def test_only_a_signal_issue_with_a_triage_section_has_an_engine_row_ac_176_6(world):  # AC-176.6
    world.issue(1, labels=("triage",), body=engine_body())
    world.issue(2, labels=("triage", "signal"), body="Just a note\n")
    world.batch()
    by = world.by_number()
    assert by[1]["engine"] is None and by[2]["engine"] is None


# ---------------- AC-176.7 reply state ----------------

def waiting_world(w):
    w.issue(1, labels=("needs-info",), author="rep", created=ago(days=9),
            comments=[comment("rep", "Old chatter", "NONE", ago(days=8)), comment("me", "Which version?", "OWNER", ago(days=4)),
                      comment("rep", "Version 2.1", "NONE", ago(days=2, hours=1)), comment("other", "me too", "NONE", ago(days=1))])
    w.issue(2, labels=("needs-info",), author="rep2", created=ago(days=9),
            comments=[comment("me", "Which version?", "OWNER", ago(hours=5, minutes=30)), comment("other", "me too", "NONE", ago(hours=2))])
    w.issue(3, labels=("triage",))


def test_an_answered_needs_info_issue_is_in_the_batch_with_only_new_comments_marked_ac_176_7(world):  # AC-176.7
    waiting_world(world)
    data = world.batch()
    by = world.by_number()
    assert sorted(by) == [1, 3] and by[1]["reply"]["state"] == "answered" and by[1]["reply"]["age"] == "2d"
    assert by[1]["reply"]["since"][:10] == ago(days=4)[:10]
    assert [(c["author"], c["new"]) for c in by[1]["comments"]] == [("rep", False), ("me", False), ("rep", True), ("other", True)]
    assert by[3]["reply"] is None
    assert data["skipped"][0]["number"] == 2


def test_a_silent_needs_info_issue_is_skipped_with_its_age_ac_176_7(world):  # AC-176.7
    waiting_world(world)
    skipped = world.batch()["skipped"]
    assert {"number": 2, "reason": "silent 5h"} in skipped


def test_list_waiting_shows_answered_or_silent_with_the_age_ac_176_7(world):  # AC-176.7
    def listed(n, labels, author, comments):
        return {"number": n, "title": f"t{n}", "body": "b", "labels": [{"name": x} for x in labels], "author": {"login": author},
                "createdAt": ago(days=9), "comments": [{**c, "author": c["author"]} for c in comments]}
    world.listing = [listed(7, ["needs-info"], "rep", [comment("me", "Which version?", "OWNER", ago(days=4)), comment("rep", "2.1", "NONE", ago(days=2, hours=3))]),
                     listed(8, ["needs-info"], "rep", [comment("me", "Which version?", "OWNER", ago(hours=7))])]
    text = world.run("list", "--waiting").lines
    assert any(l.startswith("#7") and l.rstrip().endswith("answered 2d") for l in text)
    assert any(l.startswith("#8") and l.rstrip().endswith("silent 7h") for l in text)
    items = {i["number"]: i for i in world.run("list", "--waiting", "--json").json()["issues"]}
    assert items[7]["reply"]["state"] == "answered" and items[8]["reply"]["state"] == "silent"
    assert any("comments" in c[-1] for c in world.calls if c[:2] == ["issue", "list"])
