"""Spec 082: claimed issues keep parallel sessions apart; platform PRs that close an issue carry a spec."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

import claim
import core
import ship
import spec
from test_ship import repo  # noqa: F401  (fixture)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
spec_required = __import__("check-spec-required")


class Issues:
    """A canned `gh` for issues: state, labels and comments per number; records edits and comments."""

    def __init__(self, **issues):
        self.issues = {int(n): {"state": "OPEN", "labels": [], "comments": [], **v} for n, v in issues.items()}
        self.calls = []

    def __call__(self, args, *, cwd):
        self.calls.append(args)
        if args[:2] == ["issue", "view"]:
            return 0, json.dumps(self.issues[int(args[2])])
        if args[:2] == ["issue", "comment"]:
            self.issues[int(args[2])]["comments"].append({"body": args[args.index("--body") + 1]})
        if args[:2] == ["issue", "edit"]:
            labels = self.issues[int(args[2])]["labels"]
            if "--add-label" in args:
                labels.append({"name": args[args.index("--add-label") + 1]})
            if "--remove-label" in args:
                labels[:] = [lb for lb in labels if lb["name"] != args[args.index("--remove-label") + 1]]
        return 0, ""


def test_claim_labels_assigns_and_names_the_branch(tmp_path, monkeypatch):
    """AC-082.1: label, assignee, a comment with the branch; a second claim for the same branch is a no-op."""
    gh = Issues(**{"104": {}})
    monkeypatch.setattr(claim, "gh", gh)
    assert claim.claim(tmp_path, [104], "feature/074-ci") == ["#104: claimed for feature/074-ci"]
    assert ["issue", "edit", "104", "--add-assignee", "@me", "--add-label", "in-progress"] in gh.calls
    assert claim.holder(gh.issues[104]) == "feature/074-ci"
    assert claim.claim(tmp_path, [104], "feature/074-ci") == []


def test_a_claim_for_another_branch_stops_the_second_session(tmp_path, monkeypatch):
    """AC-082.1: the collision of 2026-10-22 (#107/#108 vs #111) is refused; --take-over moves the claim."""
    gh = Issues(**{"104": {}})
    monkeypatch.setattr(claim, "gh", gh)
    claim.claim(tmp_path, [104], "feature/074-ci")
    with pytest.raises(core.PlatformError, match="already being worked on, on branch feature/074-ci"):
        claim.claim(tmp_path, [104], "ci/templates-once")
    assert claim.claim(tmp_path, [104], "ci/templates-once", take_over=True) == ["#104: claimed for ci/templates-once"]
    assert "Taken over from `feature/074-ci`" in gh.issues[104]["comments"][-1]["body"]


def test_released_or_closed_issues_are_free(tmp_path, monkeypatch):
    gh = Issues(**{"1": {}, "2": {"state": "CLOSED"}})
    monkeypatch.setattr(claim, "gh", gh)
    claim.claim(tmp_path, [1], "feature/a")
    claim.release(tmp_path, [1], "escalated")
    assert claim.holder(gh.issues[1]) is None
    assert claim.claim(tmp_path, [1, 2], "feature/b") == ["#1: claimed for feature/b"]


def test_offline_never_blocks(tmp_path, monkeypatch):
    monkeypatch.setattr(claim, "gh", lambda args, cwd: (1, ""))
    assert claim.claim(tmp_path, [5], "feature/x") == ["#5: not claimed (GitHub not reachable)"]


def test_ship_start_claims_and_escalate_releases(repo, monkeypatch):
    """AC-082.1: a ship run of a spec with `tracks` claims its issues; an escalation releases them."""
    sp = spec.find(repo, "7")
    meta, body = spec.load(sp.dir / "spec.md")
    meta["tracks"] = [42]
    spec.save(sp.dir / "spec.md", meta, body)
    gh = Issues(**{"42": {}})
    monkeypatch.setattr(claim, "gh", gh)
    monkeypatch.setattr(ship, "say", lambda s: None)
    ship.start(repo, "7", True)
    assert claim.holder(gh.issues[42]) == "feature/007-price-alerts"
    ship.escalate(repo, "merge conflict")
    assert claim.holder(gh.issues[42]) is None and "merge conflict" in gh.issues[42]["comments"][-1]["body"]


@pytest.mark.parametrize("body, labels, files, ok", [
    ("Closes #104", [], ["templates/service-go/ci.yml"], False),
    ("Closes #104", [], ["templates/service-go/ci.yml", "docs/specs/074-x/spec.md"], True),
    ("Closes #104", ["no-spec"], ["scripts/cplat/ship.py"], True),
    ("Fixes #9", [], ["docs/HOW-IT-WORKS.md"], True),                 # docs only
    ("chore: release 4.4.0", [], ["docs/CHANGELOG.md", "plugins/svc/.claude-plugin/plugin.json"], True),
])
def test_platform_prs_that_close_an_issue_carry_a_spec(body, labels, files, ok):
    """AC-082.2: the CI rule."""
    assert (spec_required.verdict(body, labels, files) is None) is ok


def test_the_rule_runs_in_ci():
    """AC-082.2: a job in the platform CI, required by ci-success, rerun when a label changes."""
    text = (core.PLATFORM_ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "python3 scripts/check-spec-required.py" in text and "spec-required, pr-title]" in text and "labeled" in text
