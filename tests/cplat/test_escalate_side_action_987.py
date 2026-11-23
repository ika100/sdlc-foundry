"""#987 item 1: an escalation's suggested answer was "file /issue:report …", which decides nothing; the coordinator resumed with
it and the same conflict came back 12 minutes later. `ship escalate` refuses a question whose suggested answer is only a side
action, and records nothing."""
import pytest

import ship
from test_ship import repo  # noqa: F401  (fixture)


@pytest.mark.parametrize("q", ["Which store? (suggested: file /issue:report about the conflict)",
                               "Keep the old schema? (suggested: open an issue for the platform)",
                               "Retry? (suggested: cplat feedback --title 'merge conflict')"])
def test_a_side_action_as_the_suggested_answer_is_refused_987(repo, capsys, q):  # noqa: F811
    assert ship.main(["--repo", str(repo), "start", "7"]) == 0
    capsys.readouterr()
    assert ship.main(["--repo", str(repo), "escalate", "conflict", "--cause", "decision", "--question", q]) == 2
    err = capsys.readouterr().err
    assert "side action" in err and "suggest the decision itself" in err
    assert not ship.load_state(repo).get("escalated")


@pytest.mark.parametrize("q", ["Which store? (suggested: redis; alternatives: file an issue)",
                               "Which issue tracker label? (suggested: bug)", "How long?"])
def test_a_suggestion_that_decides_is_kept_987(repo, q):  # noqa: F811
    assert ship.main(["--repo", str(repo), "start", "7"]) == 0
    assert ship.main(["--repo", str(repo), "escalate", "needs the user", "--cause", "decision", "--question", q]) == 0
    assert ship.load_state(repo)["escalated"] == "needs the user"
