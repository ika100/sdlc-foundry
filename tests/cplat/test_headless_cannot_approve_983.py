"""#983: in journey 26 the coordinator's own approval of a tightened acceptance test was denied by auto mode, then relayed to
the headless repo session as a "suggested answer", which ran `cplat spec test-diff --approve` and recorded it as approved by the
user. Only the user approves a test change (build-test-approval.md, hard rule), and no user reads an unattended session, so
`--approve` refuses there; the attended session still records the user's approval."""
import pytest

import spec
from test_spec_324 import PY_BEFORE, _committed_repo


@pytest.mark.parametrize("env", [{"CPLAT_HEADLESS": "1"}, {"CPLAT_UNIT": "verification"}])
def test_an_unattended_session_cannot_approve_a_test_change_983(tmp_path, capsys, monkeypatch, env):
    _committed_repo(tmp_path)
    (tmp_path / "tests" / "test_x.py").write_text(PY_BEFORE.replace("200.01", "1"))
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert spec.main(["--repo", str(tmp_path), "test-diff", "HEAD", "--approve", "tests/test_x.py",
                      "--reason", "system ship answer: yes, approve"]) == 1
<<<<<<< Updated upstream
    assert "only the user approves" in capsys.readouterr().err
=======
    assert "an unattended session cannot approve a test change" in capsys.readouterr().err
>>>>>>> Stashed changes
    assert spec.main(["--repo", str(tmp_path), "test-diff", "HEAD"]) == 1, "nothing was recorded"


def test_the_attended_session_still_records_the_users_approval_983(tmp_path, monkeypatch):
    _committed_repo(tmp_path)
    (tmp_path / "tests" / "test_x.py").write_text(PY_BEFORE.replace("200.01", "1"))
    monkeypatch.delenv("CPLAT_HEADLESS", raising=False)
    monkeypatch.delenv("CPLAT_UNIT", raising=False)
    assert spec.main(["--repo", str(tmp_path), "test-diff", "HEAD", "--approve", "tests/test_x.py", "--reason", "ok"]) == 0
    assert spec.main(["--repo", str(tmp_path), "test-diff", "HEAD"]) == 0
