"""#856, decided by the user: a resumed escalated run re-checks the condition behind the escalation. `ship start` names the
escalation the resume resolved and what to check again (the current checks; a verification.md older than HEAD is stale), and
`ship escalate` refuses the same reason while verification.md was not checked again."""
import pytest

import core
import ship
from test_ship import git, repo  # noqa: F401  (fixture)

REASON = "environment: AC-208.7 timing unmeasured"


def _verification(repo, result):  # noqa: F811
    d = repo / "docs" / "specs" / ship.load_state(repo)["spec"]
    head = git(repo, "rev-parse", "HEAD")
    (d / "verification.md").write_text(f"# Verification\n\nChecked at {head}.\n\n**Result:** {result}\n")
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", f"docs(spec): verification {result}")


def _fix(repo, name="timing.md"):  # noqa: F811
    (repo / name).write_text("measured\n")
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "fix the cause")


def _escalated_then_resumed(repo, capsys):  # noqa: F811
    assert ship.main(["--repo", str(repo), "start", "7"]) == 0
    _verification(repo, "fail")
    assert ship.main(["--repo", str(repo), "escalate", REASON, "--cause", "environment"]) == 0
    _fix(repo)
    capsys.readouterr()
    assert ship.main(["--repo", str(repo), "start", "7"]) == 0
    return capsys.readouterr().out


def test_start_names_the_resolved_escalation_and_the_stale_verification_856(repo, capsys):  # noqa: F811
    out = _escalated_then_resumed(repo, capsys)
    assert f"resumed after: {REASON}" in out and "re-check: the current checks" in out
    assert "verification.md is 1 commit(s) older than HEAD: stale" in out
    capsys.readouterr()
    assert ship.main(["--repo", str(repo), "status"]) == 0
    assert "resumed after:" in capsys.readouterr().out


def test_the_same_reason_over_a_stale_verification_is_refused_856(repo, capsys):  # noqa: F811
    _escalated_then_resumed(repo, capsys)
    with pytest.raises(core.PlatformError, match="was not checked again") as e:
        ship.main(["--repo", str(repo), "escalate", REASON, "--cause", "environment"])
    assert "/component:verify" in e.value.hint
    assert not ship.load_state(repo).get("escalated")
    _verification(repo, "fail")                                   # the reviewer ran again and still says fail
    assert ship.main(["--repo", str(repo), "escalate", REASON, "--cause", "environment"]) == 0
    assert ship.load_state(repo)["escalated"] == REASON


def test_another_reason_or_a_phase_change_is_not_held_856(repo, capsys):  # noqa: F811
    _escalated_then_resumed(repo, capsys)
    assert ship.main(["--repo", str(repo), "escalate", "a new problem", "--cause", "code"]) == 0
    _fix(repo, "more.md")
    assert ship.main(["--repo", str(repo), "start", "7"]) == 0
    ship.set_phase(repo, "pr")
    assert "resumed_from" not in ship.load_state(repo)
