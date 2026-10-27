"""Spec 122 acceptance tests: draft spec pull requests (AC-122.30) and the review request that is the GitHub notification for
approve and answer (AC-122.23).

Contract: design.md "cplat spec publish|land|review". `spec_pr.git(args, *, cwd)` and `spec_pr.gh(args, *, cwd)` return
`(returncode, stdout)` like `claim.gh`; `pr.wait` is replaced. Nothing is pushed anywhere."""
import json
import re
from pathlib import Path

import pytest
import yaml

import spec
from system_fixtures import ROOT, rich5, write_system
from test_spec import make

SPEC_ID = "007-price-alerts"
MARKER = f"<!-- cplat:spec {SPEC_ID} -->"
PR_URL = "https://github.com/acme/shop-api/pull/41"


class World:
    def __init__(self, root, monkeypatch, *, me="bob", owner="alice", existing=None):
        import pr as prmod
        import spec_pr
        self.root, self.me, self.existing = root, me, existing
        self.gh_calls, self.git_calls, self.waits = [], [], []
        self.reviews = []
        doc = rich5()
        doc["owner"] = owner
        write_system(root, doc)
        monkeypatch.setattr(spec_pr, "gh", self.gh)
        monkeypatch.setattr(spec_pr, "git", self.git)
        monkeypatch.setattr(prmod, "wait", lambda *a, **k: self.waits.append((a, k)) or 0)

    def git(self, args, *, cwd=None):
        self.git_calls.append(list(args))
        if "rev-parse" in args:
            return 0, "feature/" + SPEC_ID
        return 0, ""

    def gh(self, args, *, cwd=None):
        self.gh_calls.append(list(args))
        a = " ".join(args)
        if args[:2] == ["pr", "list"]:
            return 0, json.dumps([self.existing] if self.existing else [])
        if args[:2] == ["pr", "create"]:
            return 0, PR_URL
        if args[:2] == ["pr", "view"]:
            return 0, json.dumps({"number": 41, "url": PR_URL, "body": MARKER, "isDraft": True, "reviews": self.reviews, "comments": []})
        if args[0] == "api" and a.endswith("user") or "api user" in a:
            return 0, json.dumps({"login": self.me})
        if args[0] == "api" and "reviews" in a:
            return 0, json.dumps(self.reviews)
        if args[:2] == ["repo", "view"]:
            return 0, json.dumps({"nameWithOwner": "acme/shop-api"})
        return 0, "{}"

    def calls(self, *words):
        return [c for c in self.gh_calls if all(w in c for w in words)]

    def text(self):
        return " ".join(" ".join(c) for c in self.gh_calls)


@pytest.fixture()
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(spec, "repo_shape", lambda root: None)
    make(tmp_path, status="draft")
    return World(tmp_path, monkeypatch)


def run(world, *argv):
    return spec.main(["--repo", str(world.root), *argv])


def test_publish_opens_a_draft_pr_with_the_marker_and_the_owner_as_reviewer_ac_122_30(world, capsys):  # AC-122.30
    assert run(world, "publish", SPEC_ID, "--json") == 0
    [create] = world.calls("pr", "create")
    assert "--draft" in create and any(MARKER in a for a in create)
    assert any(a.startswith("docs(spec): " + SPEC_ID) for a in create)
    assert "alice" in " ".join(" ".join(c) for c in world.gh_calls if "reviewer" in " ".join(c))
    out = json.loads(capsys.readouterr().out)
    assert out["pr"] == 41 and out["url"] == PR_URL and out["reviewer"] == "alice"


def test_publish_pushes_only_the_specs_own_branch_without_force_ac_122_30(world):  # AC-122.30
    run(world, "publish", SPEC_ID)
    pushes = [c for c in world.git_calls if "push" in c]
    assert pushes and all(f"feature/{SPEC_ID}" in " ".join(c) for c in pushes)
    assert not any(a in ("--force", "-f", "--force-with-lease", "main") for c in pushes for a in c)


def test_publish_holds_only_the_spec_folder_ac_122_30(world):  # AC-122.30
    run(world, "publish", SPEC_ID)
    adds = [c for c in world.git_calls if "add" in c]
    assert adds and all(f"docs/specs/{SPEC_ID}" in " ".join(c) for c in adds)
    assert not any(a in ("-A", ".", "--all") for c in adds for a in c)


def test_publish_twice_updates_the_pr_instead_of_opening_a_second_ac_122_30(tmp_path, monkeypatch):  # AC-122.30
    monkeypatch.setattr(spec, "repo_shape", lambda root: None)
    make(tmp_path, status="draft")
    w = World(tmp_path, monkeypatch, existing={"number": 41, "url": PR_URL, "body": MARKER, "isDraft": True})
    assert run(w, "publish", SPEC_ID) == 0
    assert not w.calls("pr", "create")


def test_the_owner_who_is_the_author_is_assigned_not_asked_for_review_ac_122_30(tmp_path, monkeypatch, capsys):  # AC-122.30
    monkeypatch.setattr(spec, "repo_shape", lambda root: None)
    make(tmp_path, status="draft")
    w = World(tmp_path, monkeypatch, me="alice", owner="alice")
    assert run(w, "publish", SPEC_ID, "--json") == 0
    assert not any("reviewer" in " ".join(c) for c in w.gh_calls)
    assert any("assignee" in " ".join(c) and "alice" in c for c in w.gh_calls)
    out = json.loads(capsys.readouterr().out)
    assert out["reviewer"] is None and out["note"]


def test_land_refuses_a_spec_that_is_not_approved_ac_122_30(world, capsys):  # AC-122.30
    rc = run(world, "land", SPEC_ID)
    assert rc == 1 and not world.waits
    assert "approved" in capsys.readouterr().err


def test_land_approves_the_review_marks_ready_and_merges_ac_122_30(tmp_path, monkeypatch):  # AC-122.30
    monkeypatch.setattr(spec, "repo_shape", lambda root: None)
    make(tmp_path, status="approved")
    w = World(tmp_path, monkeypatch, existing={"number": 41, "url": PR_URL, "body": MARKER, "isDraft": True})
    assert run(w, "land", SPEC_ID) == 0
    assert w.calls("pr", "review", "--approve") and w.calls("pr", "ready")
    [(args, kw)] = w.waits
    assert 41 in args or "41" in args
    assert kw.get("merge") is True or True in args


def test_land_as_the_author_says_who_approved_ac_122_30(tmp_path, monkeypatch):  # AC-122.30
    monkeypatch.setattr(spec, "repo_shape", lambda root: None)
    make(tmp_path, status="approved")
    w = World(tmp_path, monkeypatch, me="alice", owner="alice", existing={"number": 41, "url": PR_URL, "body": MARKER, "isDraft": True})
    assert run(w, "land", SPEC_ID) == 0
    assert not w.calls("pr", "review", "--approve")
    assert "approved by alice (author is the system owner)" in w.text()


def test_request_changes_posts_a_changes_requested_review_ac_122_30(tmp_path, monkeypatch):  # AC-122.30
    monkeypatch.setattr(spec, "repo_shape", lambda root: None)
    make(tmp_path, status="draft")
    w = World(tmp_path, monkeypatch, existing={"number": 41, "url": PR_URL, "body": MARKER, "isDraft": True})
    body = tmp_path / "comment.txt"
    body.write_text("Please cap the number of rules.")
    assert run(w, "review", SPEC_ID, "--request-changes", "--body-file", str(body)) == 0
    assert w.calls("pr", "review", "--request-changes")
    assert "Please cap the number of rules." in w.text() or any(str(body) in " ".join(c) for c in w.gh_calls)


def test_the_amend_reads_review_comments_as_json_ac_122_30(tmp_path, monkeypatch, capsys):  # AC-122.30
    monkeypatch.setattr(spec, "repo_shape", lambda root: None)
    make(tmp_path, status="draft")
    w = World(tmp_path, monkeypatch, existing={"number": 41, "url": PR_URL, "body": MARKER, "isDraft": True})
    w.reviews = [{"author": {"login": "alice"}, "user": {"login": "alice"}, "body": "Please cap the number of rules.",
                  "submittedAt": "2026-10-26T08:00:00Z", "submitted_at": "2026-10-26T08:00:00Z", "state": "CHANGES_REQUESTED"}]
    assert run(w, "review", SPEC_ID, "--comments", "--json") == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows and set(rows[0]) >= {"author", "body", "at"} and rows[0]["author"] == "alice"
    assert "cap the number of rules" in rows[0]["body"]


@pytest.mark.parametrize("plugin", ["component", "system"])
def test_the_spec_commands_publish_land_and_read_reviews_ac_122_30(plugin):  # AC-122.30
    text = (ROOT / "plugins" / plugin / "commands" / "spec.md").read_text()
    for needle in ("cplat spec publish", "cplat spec land", "cplat spec review"):
        assert needle in text, (plugin, needle)
    m = re.match(r"^---\n(.*?)\n---", text, re.S)
    desc = yaml.safe_load(m.group(1))["description"]
    assert len(desc) <= 260 and "Usage:" in desc


def test_the_review_request_is_the_github_notification_for_approve_and_answer_ac_122_23(world):  # AC-122.23
    """Every draft write publishes the draft PR, and the owner is requested as reviewer: that review request is the notification."""
    run(world, "publish", SPEC_ID)
    reviewer_calls = [c for c in world.gh_calls if "reviewer" in " ".join(c)]
    assert reviewer_calls and all("alice" in c or "acme/alice" in " ".join(c) for c in reviewer_calls)
