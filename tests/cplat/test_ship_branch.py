"""`cplat ship start` puts the session on the spec's feature branch (spec 067).

Headless coordinators improvised the branch step (`git checkout -B …`), which the template allowlist rightly refuses (it
resets an existing branch), so a ship benchmark escalated in phase plan. Creating or switching the branch is now code.
"""
import ship
from test_ship import git, repo  # noqa: F401  (fixture)

BRANCH = "feature/007-price-alerts"


def start(repo):
    assert ship.main(["--repo", str(repo), "start", "7"]) == 0


def test_start_creates_the_feature_branch_from_main(repo):
    """AC-067.1: on main, start creates the feature branch and switches to it."""
    start(repo)
    assert git(repo, "branch", "--show-current") == BRANCH


def test_a_resume_switches_back_to_the_existing_branch_keeping_its_commits(repo):
    """AC-067.1: a resumed run lands on its own branch with the work it already has."""
    start(repo)
    (repo / "work.txt").write_text("x\n")
    git(repo, "add", "work.txt")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "work")
    head = git(repo, "rev-parse", "HEAD")
    git(repo, "switch", "-q", "main")
    start(repo)
    assert git(repo, "branch", "--show-current") == BRANCH and git(repo, "rev-parse", "HEAD") == head


def test_after_the_merge_start_does_not_touch_the_branch(repo):
    """AC-067.1: from phase land on, the branch may be gone; start leaves the checkout alone."""
    start(repo)
    ship.set_phase(repo, "land")
    git(repo, "switch", "-q", "main")
    start(repo)
    assert git(repo, "branch", "--show-current") == "main"
