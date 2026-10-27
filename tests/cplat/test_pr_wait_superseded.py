"""`cplat pr wait`: a run superseded by a newer run of the same workflow (cancel-in-progress) does not count."""
import json

import pytest

import pr as prmod
import ship
from test_tags_and_wait import PR, Gh, _run_check, fake  # noqa: F401  (fixture)


class WfGh(Gh):
    """Gh plus the workflow of each run (default: every run is the same workflow)."""

    workflows: dict[str, int] = {}

    def __call__(self, args, *, cwd, check=True):
        if args[:2] == ["run", "view"] and "workflowDatabaseId" in args:
            return json.dumps({"workflowDatabaseId": self.workflows.get(args[2], 7)})
        return super().__call__(args, cwd=cwd, check=check)


@pytest.fixture()
def wf(fake, monkeypatch):  # noqa: F811
    g = WfGh()
    g.said, g.merges = fake.said, fake.merges
    monkeypatch.setattr(ship, "gh", g)
    return g


def test_older_cancelled_run_and_newer_green_run_is_green_and_merges(wf, tmp_path):
    wf.checks = [[_run_check("ci-success", "cancel", 41), _run_check("ci-success", "pass", 42)]]
    ok, lines = prmod.wait(tmp_path, PR, True, 600, 10, 300)
    assert ok and wf.merges == [PR] and lines[-1].startswith("merged")


def test_older_cancelled_run_and_newer_running_run_waits(wf, tmp_path):
    wf.checks = [[_run_check("ci-success", "cancel", 41), _run_check("ci-success", "pending", 42)],
                 [_run_check("ci-success", "cancel", 41), _run_check("ci-success", "pass", 42)]]
    ok, lines = prmod.wait(tmp_path, PR, False, 600, 10, 300)
    assert ok and lines[0].startswith("GREEN")
    assert not any("cancel" in s for s in wf.said)


def test_newest_run_cancelled_alone_is_still_red(wf, tmp_path):
    wf.checks = [[_run_check("ci-success", "cancel", 42)]]
    ok, lines = prmod.wait(tmp_path, PR, True, 600, 10, 300)
    assert not ok and wf.merges == [] and lines[0].startswith("RED")


def test_older_failed_run_and_newer_green_run_is_green(wf, tmp_path):
    wf.checks = [[_run_check("ci-success", "fail", 41), _run_check("ci-success", "pass", 42)]]
    ok, lines = prmod.wait(tmp_path, PR, False, 600, 10, 300)
    assert ok and lines[0].startswith("GREEN")


def test_a_failed_check_of_another_workflow_still_counts(wf, tmp_path):
    wf.workflows = {"41": 8, "42": 7}
    wf.checks = [[_run_check("lint", "fail", 41), _run_check("ci-success", "pass", 42)]]
    ok, lines = prmod.wait(tmp_path, PR, False, 600, 10, 300)
    assert not ok and lines[0].startswith("RED")


class ConflictGh(Gh):
    """Gh whose PR conflicts with its base: only CodeQL reported, as GitHub starts no pull_request workflow (#221)."""

    mergeable = "CONFLICTING"

    def __call__(self, args, *, cwd, check=True):
        if args[:2] == ["pr", "view"] and "mergeable" in args:
            return json.dumps({"mergeable": self.mergeable})
        return super().__call__(args, cwd=cwd, check=check)


@pytest.fixture()
def conflict(fake, monkeypatch):  # noqa: F811
    g = ConflictGh()
    g.said, g.merges = fake.said, fake.merges
    monkeypatch.setattr(ship, "gh", g)
    return g


def test_a_conflicting_pr_with_green_codeql_is_not_green_and_not_merged(conflict, tmp_path):   # #221
    conflict.checks = [[_run_check("CodeQL", "pass", 41), _run_check("Analyze (python)", "pass", 41)]]
    with pytest.raises(ship.Conflicting, match="conflicts with its base"):
        prmod.wait(tmp_path, PR, True, 600, 10, 300)
    assert conflict.merges == []


def test_a_conflicting_pr_without_checks_says_why(conflict, tmp_path):   # #221
    conflict.checks = [[]] * 200
    with pytest.raises(ship.Conflicting):
        prmod.wait(tmp_path, PR, False, 600, 10, 300)


def test_a_mergeable_pr_with_green_checks_is_still_green(conflict, tmp_path):   # #221
    conflict.mergeable = "MERGEABLE"
    conflict.checks = [[_run_check("ci-success", "pass", 41)]]
    ok, lines = prmod.wait(tmp_path, PR, True, 600, 10, 300)
    assert ok and conflict.merges == [PR]
