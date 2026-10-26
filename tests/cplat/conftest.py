import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "cplat"))

import pytest
from sharding import (  # noqa: F401  (spec 112: --shard / --shard-report)
    pytest_addoption,
    pytest_collection_modifyitems,
    pytest_configure,
    pytest_report_collectionfinish,
    pytest_runtest_logreport,
    pytest_sessionfinish,
    pytest_sessionstart,
    pytest_testnodedown,
)


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
    for name in ("CPLAT_RUNS_REPO", "CPLAT_RUN_PARENT", "CPLAT_HEADLESS", "CLAUDE_CODE_SESSION_ID"):
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


@pytest.fixture(autouse=True)
def no_leaking_alert_settings(monkeypatch):
    """Spec 092: the shell's alert settings never leak into a test. The seams (`alertissues.tracker`, `alertsources.http_get` /
    `kubectl`) are replaced by each test that needs them: the tests of the real defaults call them with a stubbed transport."""
    for name in ("ALERTS_TOKEN", "ALERTS_QUERY_AUTHORIZATION", "ALERTS_PROMETHEUS_URL", "GITHUB_STEP_SUMMARY"):
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


@pytest.fixture(autouse=True)
def no_leaking_telemetry_settings(monkeypatch):
    """Spec 101: the shell's OpenTelemetry settings never leak into a test (they would turn export on for fake sessions)."""
    import os
    for name in list(os.environ):
        if name.startswith(("OTEL_", "CPLAT_OTLP_")) or name in ("CPLAT_KUBE_CONTEXT", "CLAUDE_CODE_ENABLE_TELEMETRY"):
            monkeypatch.delenv(name, raising=False)


@pytest.fixture(scope="session")
def shared_renders(tmp_path_factory):
    """Spec 112: renders shared by the tests of one process; they live in this run's basetemp only."""
    from shared_render import SharedRenders
    return SharedRenders(tmp_path_factory.mktemp("shared-renders"))


@pytest.fixture()
def new_service(shared_renders):
    """Spec 112: `new_service(argv)` is `newsvc.main(argv)` for an argv with `--dir D`, returning `D/<name>` as a private
    copy of a render made once per process."""
    import newsvc
    from shared_render import service_key

    def make(argv: list[str]) -> Path:
        key, name, rest = service_key(argv)
        dest_root = Path(argv[argv.index("--dir") + 1])

        def build(workdir: Path) -> Path:
            code = newsvc.main([*rest, "--dir", str(workdir)])
            if code:
                raise RuntimeError(f"newsvc exited with {code}")
            return workdir / name

        dest_root.mkdir(parents=True, exist_ok=True)
        return shared_renders.copy(key, build, dest_root / name)

    return make
