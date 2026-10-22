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
