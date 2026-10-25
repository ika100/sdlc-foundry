import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "cplat"))

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def no_real_issue_claims(monkeypatch):
    """Spec 082: claims call GitHub; tests never do. Tracked issues look closed (nothing to claim) unless a test
    replaces `claim.gh` itself."""
    import claim
    monkeypatch.setattr(claim, "gh", lambda args, *, cwd: (0, '{"state": "CLOSED"}') if args[:2] == ["issue", "view"] else (0, ""))


@pytest.fixture(autouse=True)
def no_real_devbox_install(monkeypatch):
    """`cplat update-service` refreshes devbox.lock with `devbox install`; tests never download packages. Tests of the refresh
    itself call the saved original, `update.REAL_REFRESH_DEVBOX_LOCK`."""
    import update
    if not hasattr(update, "REAL_REFRESH_DEVBOX_LOCK"):
        update.REAL_REFRESH_DEVBOX_LOCK = update.refresh_devbox_lock
    monkeypatch.setattr(update, "refresh_devbox_lock", lambda repo, changed: None)


@pytest.fixture(autouse=True)
def isolated_run_store(monkeypatch, tmp_path_factory):
    """Spec 087: run records go to a per-test state dir and never to a real store, whatever the developer's shell exports.
    (Only the environment is touched here: the `runs` module itself is not imported.)"""
    monkeypatch.setenv("CPLAT_RUNS_DIR", str(tmp_path_factory.mktemp("runs-state")))
    for name in ("CPLAT_RUNS_REPO", "CPLAT_RUN_PARENT", "CPLAT_HEADLESS"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def no_real_auto_issues(monkeypatch):
    """Spec 088: automatic issue filing never reaches GitHub in tests. Tests that need GitHub behaviour install their own
    tracker; the switches that move or stop filing are unset, whatever the developer's shell exports."""
    import autoissue

    class _NoGitHub:
        def _refuse(self, *args, **kwargs):
            raise autoissue.TrackerError("tests never call GitHub")
        find = comments = create = comment = _refuse

    monkeypatch.setattr(autoissue, "tracker", lambda: _NoGitHub())
    for name in ("CPLAT_AUTO_ISSUES", "CPLAT_FEEDBACK_REPO"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture()
def clock(monkeypatch):
    """The run-clock fixture of test_runs.py for modules that import `mem` / `store` from there under an alias
    (test_autoissue.py imports `clock as run_clock`, which pytest registers as `run_clock`, so `mem` cannot find `clock`).
    test_runs.py defines its own `clock` and overrides this one there."""
    import runs
    from test_runs import Clock
    c = Clock()
    monkeypatch.setattr(runs, "utcnow", c.utcnow)
    monkeypatch.setattr(runs, "monotonic", c.monotonic)
    return c
