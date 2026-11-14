"""Unit tests of the pure helpers in `triage_facts` (spec 176), without a fake GitHub."""
from datetime import datetime, timezone
from types import SimpleNamespace

import triage_facts as tf

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)


def c(author, assoc, at, body="x"):
    return {"author": author, "authorAssociation": assoc, "createdAt": at, "body": body}


def test_duplicates_skip_self_and_old_closed_issues():
    me = {"number": 1, "title": "Crash on empty config", "body": "Signature: s1\n"}
    old = {"number": 2, "title": "other", "body": "Signature: s1", "closedAt": "2026-09-01T00:00:00Z"}
    new = {"number": 3, "title": "other", "body": "Signature: s1", "closedAt": "2026-11-05T00:00:00Z"}
    assert [d["number"] for d in tf.duplicates(me, [me], [old, new], NOW)] == [3]


def test_reply_without_question_counts_from_creation():
    issue = {"author": "rep", "createdAt": "2026-11-10T09:00:00Z", "labels": [{"name": "needs-info"}], "comments": []}
    assert tf.reply(issue, NOW) == {"state": "silent", "age": "3h", "since": "2026-11-10T09:00:00Z"}
    assert tf.reply({**issue, "labels": []}, NOW) is None


def test_new_since_follows_the_newest_writer_comment():
    issue = {"author": "rep", "comments": [c("me", "OWNER", "2026-11-01T00:00:00Z"), c("rep", "NONE", "2026-11-02T00:00:00Z")]}
    assert [x["author"] for x in tf.new_since(issue)] == ["rep"]


def test_status_and_handled_order():
    spec = SimpleNamespace(id="176-x", number="176", status="approved", meta={"tracks": [5]})
    issue = {"number": 5, "labels": [], "comments": [c("me", "OWNER", "2026-11-01T00:00:00Z", "Duplicate of #9")]}
    prs = [{"number": 4, "title": "t #5", "body": "", "url": "u"}, {"number": 6, "title": "#50", "body": "", "url": "v"}]
    st = tf.status(issue, [spec], {9}, prs)
    assert st["duplicate_of"] == 9 and [p["number"] for p in st["merged_prs"]] == [4]
    assert tf.handled(st)["line"] == "in spec 176 (approved)"
    assert tf.handled({**st, "specs": []})["line"] == "fixed by #4"
    assert tf.handled({**st, "specs": [], "merged_prs": []})["line"] == "duplicate of #9"
    assert tf.handled({**st, "specs": [], "merged_prs": [], "duplicate_of": None}) is None
