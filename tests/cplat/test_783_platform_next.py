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
