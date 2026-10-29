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


class QueuedGh(Gh):
    """Gh whose head commit has workflow runs: `runs` answers `gh run list --commit` poll by poll (#269)."""

    runs: list[list[dict]] = []

    def __call__(self, args, *, cwd, check=True):
        if args[:2] == ["run", "list"] and "--commit" in args:
            self.calls.append(args)
            seq = self.runs
            return json.dumps(seq.pop(0) if len(seq) > 1 else seq[0]) if seq else "[]"
        return super().__call__(args, cwd=cwd, check=check)


@pytest.fixture()
def queued(fake, monkeypatch):  # noqa: F811
    g = QueuedGh()
    g.said, g.merges = fake.said, fake.merges
    g.heads = ["abc123"]
    monkeypatch.setattr(ship, "gh", g)
    return g


def test_a_queued_workflow_run_without_checks_is_not_green(queued, tmp_path):   # #269
    """Only CodeQL reported while the CI run is still queued: the wait goes on and merges only once that run is done."""
    codeql = [_run_check("CodeQL", "pass", 41)]
    queued.checks = [codeql, codeql, [*codeql, _run_check("ci-success", "pass", 42)]]
    queued.runs = [[{"status": "completed"}, {"status": "queued"}], [{"status": "completed"}, {"status": "queued"}],
                   [{"status": "completed"}, {"status": "completed"}]]
    ok, lines = prmod.wait(tmp_path, PR, True, 600, 10, 300)
    assert ok and queued.merges == [PR] and lines[0].startswith("GREEN: all 2 check(s)")
    assert any("abc123" in c and "acme/other" in c for c in queued.calls if c[:2] == ["run", "list"])


def test_a_queued_run_that_never_starts_times_out_unmerged(queued, tmp_path):   # #269
    queued.checks = [[_run_check("CodeQL", "pass", 41)]]
    queued.runs = [[{"status": "queued"}]]
    with pytest.raises(ship.ChecksPending, match="queued"):
        prmod.wait(tmp_path, PR, True, 120, 10, 300)
    assert queued.merges == []



class QueuedWfGh(QueuedGh, WfGh):
    """The run list of the head commit plus the workflow of each run (#244, #282)."""


@pytest.fixture()
def qwf(fake, monkeypatch):  # noqa: F811
    g = QueuedWfGh()
    g.said, g.merges = fake.said, fake.merges
    g.heads = ["abc123"]
    monkeypatch.setattr(ship, "gh", g)
    return g


def test_older_failed_run_while_the_newer_run_is_queued_waits_and_merges(qwf, tmp_path):   # #244
    """A label on `gh pr create` starts a second run; the first is cancelled and its ci-success fails. While the newer
    run is queued it reports no checks, and the run list alone says it exists: the old failure does not count."""
    old = [_run_check("CodeQL", "pass", 40), _run_check("ci-success", "fail", 41)]
    qwf.checks = [old, old, [_run_check("CodeQL", "pass", 40), _run_check("ci-success", "fail", 41), _run_check("ci-success", "pass", 42)]]
    qwf.runs = [[{"status": "completed", "databaseId": 41, "workflowDatabaseId": 7}, {"status": "queued", "databaseId": 42, "workflowDatabaseId": 7}]] * 2 + \
                  [[{"status": "completed", "databaseId": 41, "workflowDatabaseId": 7}, {"status": "completed", "databaseId": 42, "workflowDatabaseId": 7}]]
    ok, lines = prmod.wait(tmp_path, PR, True, 600, 10, 300)
    assert ok and qwf.merges == [PR] and lines[0].startswith("GREEN"), lines


def test_cancelled_jobs_of_a_replaced_run_while_the_newer_one_is_queued_are_not_red(qwf, tmp_path):   # #282
    old = [_run_check("shape registry + detection", "cancel", 41), _run_check("smoke-test cluster-gitops template", "cancel", 41)]
    qwf.checks = [old, [*old, _run_check("ci-success", "pass", 42)]]
    qwf.runs = [[{"status": "completed", "databaseId": 41, "workflowDatabaseId": 7}, {"status": "queued", "databaseId": 42, "workflowDatabaseId": 7}],
                   [{"status": "completed", "databaseId": 41, "workflowDatabaseId": 7}, {"status": "completed", "databaseId": 42, "workflowDatabaseId": 7}]]
    ok, lines = prmod.wait(tmp_path, PR, False, 600, 10, 300)
    assert ok and lines[0].startswith("GREEN"), lines


def test_a_failed_run_with_no_newer_run_in_the_list_is_still_red(qwf, tmp_path):   # #244
    qwf.checks = [[_run_check("ci-success", "fail", 42)]]
    qwf.runs = [[{"status": "completed", "databaseId": 42, "workflowDatabaseId": 7}]]
    ok, lines = prmod.wait(tmp_path, PR, True, 600, 10, 300)
    assert not ok and qwf.merges == [] and lines[0].startswith("RED")
