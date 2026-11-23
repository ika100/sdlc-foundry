"""#783: `cplat next` in the platform repo asked `gh` once per run for its PR and once per spec for its text."""
from __future__ import annotations

import json
import re

import pytest

import needs
import runlist


@pytest.fixture(autouse=True)
def _clean():
    runlist._pr_lists.clear()
    yield
    runlist._pr_lists.clear()


def fake_run(monkeypatch, listing):
    import core
    calls: list[list[str]] = []

    def run(cmd, **kw):
        calls.append(cmd)
        return type("R", (), {"stdout": json.dumps(listing)})()

    monkeypatch.setattr(core, "run", run)
    return calls


def test_inside_shared_reads_the_prs_of_a_repo_are_asked_once(monkeypatch):
    calls = fake_run(monkeypatch, [
        {"number": 7, "url": "https://github.com/a/b/pull/7", "headRefName": "feature/001-x", "state": "OPEN"},
        {"number": 5, "url": "https://github.com/a/b/pull/5", "headRefName": "feature/002-y", "state": "MERGED"}])
    with runlist.shared_reads():
        assert runlist.lookup_pr("a/b", "feature/001-x") == {"number": 7, "url": "https://github.com/a/b/pull/7"}
        assert runlist.lookup_pr("a/b", "feature/002-y", state="merged")["number"] == 5
        assert runlist.lookup_pr("a/b", "feature/001-x", state="merged") is None
        assert runlist.lookup_pr("a/b", "feature/none") is None
    assert len(calls) == 1


def test_a_full_listing_falls_back_to_one_call_per_branch(monkeypatch):
    calls = fake_run(monkeypatch, [{"number": i, "url": f"u/{i}", "headRefName": f"b{i}", "state": "OPEN"}
                                   for i in range(runlist._PR_LIST_LIMIT)])
    with runlist.shared_reads():
        runlist.lookup_pr("a/b", "x")
        runlist.lookup_pr("a/b", "y")
    assert len(calls) == 3


def test_drafts_read_every_spec_and_keep_main_and_pr_drafts(monkeypatch):
    asked: list[str] = []

    def json_(call):
        if call[0] == "api":
            return [{"type": "dir", "name": "001-a"}, {"type": "dir", "name": "002-b"}, {"type": "file", "name": "README.md"}]
        return [{"number": 9, "body": "spec: 003-c", "createdAt": "2026-11-01T00:00:00Z", "url": "u/9", "headRefName": "spec/003"}]

    def text(slug, spec_id, ref=None):
        asked.append(spec_id)
        status = "approved" if spec_id == "002-b" else "draft"
        return f"---\nid: {spec_id}\ntitle: t\nstatus: {status}\n---\n# t\n"

    monkeypatch.setattr(needs, "_json", json_)
    monkeypatch.setattr(needs, "_spec_text", text)
    monkeypatch.setattr(needs, "MARKER", re.compile(r"spec: (\S+)"))
    found = needs._drafts("a/b")
    assert sorted(asked) == ["001-a", "002-b", "003-c"]
    assert {d["spec"].id: d["pr"] for d in found} == {"001-a": None, "003-c": 9}


# ---------------- #859: a repo with more PRs than one listing holds ----------------

def test_a_full_listing_still_answers_the_branches_it_holds(monkeypatch):
    calls = fake_run(monkeypatch, [{"number": i, "url": f"u/{i}", "headRefName": f"b{i}", "state": "OPEN"}
                                   for i in range(runlist._PR_LIST_LIMIT)])
    with runlist.shared_reads():
        assert runlist.lookup_pr("a/b", "b3") == {"number": 3, "url": "u/3"}
        assert runlist.lookup_pr("a/b", "b4") == {"number": 4, "url": "u/4"}
    assert len(calls) == 1


def test_a_branch_the_full_listing_misses_is_asked_once(monkeypatch):
    calls = fake_run(monkeypatch, [{"number": i, "url": f"u/{i}", "headRefName": f"b{i}", "state": "OPEN"}
                                   for i in range(runlist._PR_LIST_LIMIT)])
    with runlist.shared_reads():
        for _ in range(3):
            runlist.lookup_pr("a/b", "feature/old")
    assert len(calls) == 2
    assert not runlist._pr_answers


def test_the_budget_ledgers_are_read_once_per_shared_read(monkeypatch):
    import budget
    reads: list[int] = []
    monkeypatch.setattr(budget, "_all", lambda: reads.append(1) or [("f", {"roots": ["r1"], "limits": {}})])
    with runlist.shared_reads():
        assert runlist._ledger({"run_id": "r1"}) == {"roots": ["r1"], "limits": {}}
        assert runlist._ledger({"run_id": "r2"}) is None
    assert len(reads) == 1
    runlist._ledger({"run_id": "r1"})
    assert len(reads) == 2


def test_the_screen_names_a_slow_source_as_slow():
    import nextscreen
    out = nextscreen._Lines()
    nextscreen._unavailable_lines(out, {"unavailable": [{"source": "github", "error": "no answer within 20 s", "kinds": []}]})
    text = " ".join(line.strip() for line in out.out)
    assert "Could not read GitHub within 20 s; it may be missing" in text


def test_the_drafts_on_main_come_from_one_graphql_call(monkeypatch):
    calls: list[list[str]] = []

    def json_(call):
        calls.append(call)
        if call[:2] == ["api", "graphql"]:
            return {"data": {"repository": {"s0": {"text": "---\nid: 001-a\ntitle: t\nstatus: draft\n---\n# t\n"},
                                            "s1": {"text": "---\nid: 002-b\ntitle: t\nstatus: approved\n---\n# t\n"}}}}
        if call[0] == "api":
            return [{"type": "dir", "name": "001-a"}, {"type": "dir", "name": "002-b"}]
        return []

    monkeypatch.setattr(needs, "_json", json_)
    monkeypatch.setattr(needs, "_spec_text", lambda *a, **k: pytest.fail("asked per spec"))
    found = needs._drafts("a/b")
    assert [d["spec"].meta["id"] for d in found] == ["001-a"]
    assert len(calls) == 3                                  # the listing, the open draft PRs, one GraphQL call


def test_a_failed_graphql_call_asks_per_spec(monkeypatch):
    asked: list[str] = []

    def json_(call):
        if call[:2] == ["api", "graphql"]:
            raise RuntimeError("graphql down")
        return [{"type": "dir", "name": "001-a"}] if call[0] == "api" else []

    monkeypatch.setattr(needs, "_json", json_)
    monkeypatch.setattr(needs, "_spec_text", lambda slug, sid, ref=None: asked.append(sid) or None)
    needs._drafts("a/b")
    assert asked == ["001-a"]


def test_inside_shared_reads_the_run_list_is_built_once(monkeypatch):
    built: list[int] = []
    monkeypatch.setattr(runlist, "_collect", lambda *a: built.append(1) or {"schema": 1, "runs": [{"run_id": "r1"}]})
    with runlist.shared_reads():
        first = runlist.collect(30, repo="a/b")
        first["runs"][0]["phase"] = "changed"
        second = runlist.collect(30, repo="a/b")
        runlist.collect(7, repo="a/b")
    assert len(built) == 2 and second["runs"] == [{"run_id": "r1"}]
    runlist.collect(30, repo="a/b")
    assert len(built) == 3


def test_the_finished_check_reads_the_spec_texts_the_drafts_read(monkeypatch):
    monkeypatch.setattr(needs, "_spec_text", lambda *a, **k: pytest.fail("asked per spec"))
    monkeypatch.setattr(needs, "_json", lambda call: [])
    texts = {"a/b": {"128-x": "---\nid: 128-x\ntitle: t\nstatus: done\n---\n# t\n", "129-y": None}}
    assert needs._finished({"repo": "a/b", "spec": "128"}, None, {}, texts)
    assert not needs._finished({"repo": "a/b", "spec": "129-y"}, None, {}, texts)
    assert not needs._finished({"repo": "a/b", "spec": "130"}, None, {}, texts)
