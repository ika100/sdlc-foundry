"""Spec 186: a ship escalation carries questions; a resumed ship records and shows the answer."""
import ship
from test_ship import repo  # noqa: F401  (fixture)


def test_escalate_stores_questions_with_and_without_suggestion(repo):
    ship.start(repo, "7", True)
    st = ship.escalate(repo, "needs a decision", "decision",
                       questions=["Which db? (suggested: postgres; alternatives: mysql)", "Ship it?"])
    assert st["questions"] == [{"text": "Which db?", "suggested": "postgres"}, {"text": "Ship it?", "suggested": None}]
    assert ship.load_state(repo)["questions"] == st["questions"]


def test_escalate_without_questions_has_no_key(repo):
    ship.start(repo, "7", True)
    ship.escalate(repo, "x", "decision", questions=["Q? (suggested: A)"])
    assert "questions" not in ship.escalate(repo, "y", "decision")


def test_cli_question_option_is_repeatable(repo, monkeypatch):
    ship.start(repo, "7", True)
    monkeypatch.chdir(repo)
    ship.main(["escalate", "why", "--cause", "decision", "--question", "A? (suggested: 1)", "--question", "B?"])
    assert [q["text"] for q in ship.load_state(repo)["questions"]] == ["A?", "B?"]


def test_resume_records_and_prints_the_answer_once(repo, monkeypatch):
    said = []
    monkeypatch.setattr(ship, "say", said.append)
    monkeypatch.setenv("CPLAT_SHIP_ANSWER", "use postgres")
    ship.start(repo, "7", True)
    ship.escalate(repo, "q", "decision", questions=["Which? (suggested: postgres)"])
    st = ship.start(repo, "7", True)
    assert "questions" not in st and "escalated" not in st
    assert [a["text"] for a in st["answers"]] == ["use postgres"]
    ship.escalate(repo, "again", "decision")
    st = ship.start(repo, "7", True)
    assert len(st["answers"]) == 1
    assert said.count("answer from the system ship: use postgres") == 1
    assert "  answer from the system ship: use postgres" in ship.describe(st)
