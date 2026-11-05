"""#452: a ship run of a spec ended `done` (its dev smoke could not run) and was archived. A new start of the done spec began at
phase `pr`, and `ship pr` opened a second PR from a branch identical to main; its squash commit was empty, so CI built no
image and deploy never got a dev pin. A start now resumes at deploy with the merged PR, and `ship pr` refuses an empty PR."""
import json
import subprocess
import time

import core
import pytest
import ship
import spec
from test_ship import SHA, repo  # noqa: F401  (pytest fixture)


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture()
def merged(repo, tmp_path):  # noqa: F811
    """The fixture repo with a real origin whose main has everything: the spec's code is merged."""
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    git(repo, "remote", "set-url", "origin", str(origin))
    git(repo, "push", "-q", "origin", "main")
    git(repo, "switch", "-qc", "feature/007-price-alerts")
    return repo


def _archive_done_run(repo):  # noqa: F811
    ship.start(repo, "7", True)
    st = ship.load_state(repo)
    st.update({"phase": "done", "pr": "https://github.com/acme/shop-api/pull/3", "merge_sha": SHA, "deployed": f"sha-{SHA}"})
    ship.save_state(repo, st)
    ship.finish(repo)
    f = spec.find(repo, "7").dir / "spec.md"                 # mark it done as the reviewer's run would (verification.md is not the point)
    f.write_text(f.read_text().replace("status: approved", "status: done", 1))


def test_a_new_start_of_a_merged_done_spec_resumes_at_deploy(merged, monkeypatch):
    monkeypatch.setattr(ship, "missing_gitops_token", lambda _repo: False)
    _archive_done_run(merged)
    st = ship.start(merged, "7", True)
    assert st["phase"] == "deploy" and st["merge_sha"] == SHA and st["pr"].endswith("/pull/3")


def test_a_done_spec_with_new_work_still_opens_its_pr(merged, monkeypatch):
    monkeypatch.setattr(ship, "missing_gitops_token", lambda _repo: False)
    _archive_done_run(merged)
    (merged / "fix.txt").write_text("x\n")
    git(merged, "add", "-A")
    git(merged, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "more")
    assert ship.start(merged, "7", True)["phase"] == "pr"


def test_ship_pr_refuses_a_pull_request_that_changes_nothing(merged, monkeypatch):
    monkeypatch.setattr(ship, "gh", lambda args, **kw: json.dumps([]) if args[:2] == ["pr", "list"] else "")
    monkeypatch.setattr(ship, "missing_gitops_token", lambda _repo: False)
    ship.start(merged, "7", True)
    ship.set_phase(merged, "pr")
    body = merged / ".git" / "PR_BODY.md"
    body.write_text("## Summary\n")
    with pytest.raises(core.PlatformError, match="changes nothing on origin/main"):
        ship.open_pr(merged, "feat(alerts): price alerts", body)


def test_the_duplicate_runs_empty_merge_is_skipped_for_the_real_one(merged, monkeypatch):
    """The journey of 2026-11-05: the newest archive was the escalated duplicate (empty squash f560cac); the resume must take
    the earlier merge that built the image, not revive the duplicate."""
    monkeypatch.setattr(ship, "missing_gitops_token", lambda _repo: False)
    _archive_done_run(merged)                              # the real merge: SHA
    time.sleep(1.1)                                        # archives are named by the second
    git(merged, "switch", "-q", "main")
    git(merged, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "duplicate (#4)")
    empty = git(merged, "rev-parse", "HEAD")
    git(merged, "push", "-q", "origin", "main")
    git(merged, "switch", "-q", "feature/007-price-alerts")
    git(merged, "merge", "-q", "--ff-only", "main")
    ship.start(merged, "7", True)
    st = ship.load_state(merged)
    st.update({"phase": "deploy", "pr": "https://github.com/acme/shop-api/pull/4", "merge_sha": empty})
    ship.save_state(merged, st)
    ship.escalate(merged, "no dev pin for the empty merge", cause="platform")
    ship.finish(merged)
    st = ship.start(merged, "7", True)
    assert st["phase"] == "deploy" and st["merge_sha"] == SHA and st["pr"].endswith("/pull/3")
