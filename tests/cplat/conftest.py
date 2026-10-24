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
def isolated_run_store(monkeypatch, tmp_path_factory):
    """Spec 087: run records go to a per-test state dir and never to a real store, whatever the developer's shell exports.
    (Only the environment is touched here: the `runs` module itself is not imported.)"""
    monkeypatch.setenv("CPLAT_RUNS_DIR", str(tmp_path_factory.mktemp("runs-state")))
    for name in ("CPLAT_RUNS_REPO", "CPLAT_RUN_PARENT", "CPLAT_HEADLESS"):
        monkeypatch.delenv(name, raising=False)
