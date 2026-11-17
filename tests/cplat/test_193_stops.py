"""Spec 193 acceptance tests: a stopped item says what happened, why it asks and what keeps running (AC-193.4), and a stop
without a decision offers Try again / Park it / Show the log, or the budget choices (AC-193.5)."""
import json
import re

import pytest

from support_193 import BuildWorld, by_label, entry, labels, question

SHIP = {"spec": "189-progress", "phase": "build", "escalated": "needs a decision", "cause": "decision",
        "questions": [{"text": "Which store holds the queue?", "suggested": "Redis", "options": ["Redis", "Postgres"], "answered": False}]}


@pytest.fixture
def world(tmp_path, monkeypatch):
    w = BuildWorld(tmp_path, monkeypatch)
    w.queue()
    w.build(slots=2)
    w.local_spec("189-progress", "The progress screen", 3)
    return w


def decision(world, minutes_ago=125, ship=SHIP):
    world.unit("spec-189", "escalated", cause="decision", reason="needs a decision", ship=ship)
    world.stop_item("spec-189", "escalation", minutes_ago, spec_id="189-progress")


def block(screen):
    return screen.split("  ! ", 1)[1].split("\n\n", 1)[0]


# ---------------- AC-193.4: a decision ----------------

def test_decision_stop_lines_and_the_other_items(world, capsys, tmp_path):  # AC-193.4
    decision(world)
    world.unit("issue-712", "running")
    world.queue(entry(1, "spec 190", kind="ship", title="Second change", after="spec 189"))
    j = world.judgement(tmp_path, {"spec-189": {"what_happened": "The queue needs a store.", "why_ask": "Redis or Postgres?"},
                                   "issue-712": {"you_get": "A label that stays"}, "spec-190": {"you_get": "A second change"}})
    screen = world.screen(capsys, "--judgement", j)
    assert "1 run stopped and wait for you." in screen
    b = block(screen).splitlines()
    assert b[0].endswith("(spec 189)")
    assert "    What happened: The queue needs a store." in b
    assert "    Why I ask: Redis or Postgres?" in b
    i = b.index("    While you think:")
    assert "      A label that stays (#712) keeps running." in b[i + 1:]
    assert "      A second change (spec 190) waits for this one." in b[i + 1:]
    assert b[-1] == "    asked 2 h 05 min ago"


def test_without_judgement_the_reason_and_the_first_question_are_printed(world, capsys):  # AC-193.4  (A6)
    decision(world)
    b = block(world.screen(capsys)).splitlines()
    assert "    What happened: needs a decision" in b
    assert "    Why I ask: Which store holds the queue?" in b
    assert "    While you think: nothing else runs." in b


def test_without_a_question_it_says_it_needs_the_decision(world, capsys):  # AC-193.4
    decision(world, ship={"spec": "189-progress", "phase": "build", "escalated": "needs a decision", "cause": "decision"})
    assert "    Why I ask: it needs your decision to go on" in world.screen(capsys).splitlines()


@pytest.mark.parametrize("minutes,shown", [(4, False), (5, True), (125, True), (60 * 26, True)])
def test_the_age_appears_from_five_minutes(world, capsys, minutes, shown):  # AC-193.4  (A8)
    decision(world, minutes_ago=minutes)
    screen = world.screen(capsys)
    assert "Why I ask:" in screen
    assert ("asked " in screen) is shown
    if minutes == 5:
        assert "    asked 5 min ago" in screen
    if minutes == 60 * 26:
        assert re.search(r"asked 1 day", screen)


def test_decision_choices_put_the_recommended_answer_first(world, capsys):  # AC-193.4
    decision(world)
    doc = world.doc(capsys)
    q = next(q for q in doc["questions"] if q["header"] == "Decide")
    assert labels(q) == ["Redis", "Postgres", "Show details", "Stop this item (its work stays on branch feature/189-progress)"]
    assert q["options"][0]["recommended"] is True
    assert q["options"][0]["steps"] == ['cplat dispatch answer spec-189 --question 1 --answer "Redis"']
    assert q["options"][1]["steps"] == ['cplat dispatch answer spec-189 --question 1 --answer "Postgres"']
    stop = q["options"][3]
    assert stop["steps"] == ['cplat dispatch skip spec-189 --reason "stopped by you"']
    assert any("cplat dispatch resume spec-189" in u for u in stop["undo"])
    assert q["other"]["steps"] == ['cplat dispatch answer spec-189 --question 1 --answer "<answer>"']
    assert q["other"]["spec"].endswith("docs/specs/189-progress/spec.md")


def test_a_decision_without_questions_offers_to_let_it_go_on(world, capsys):  # AC-193.4
    decision(world, ship={"spec": "189-progress", "phase": "build", "escalated": "needs a decision", "cause": "decision"})
    q = next(q for q in world.doc(capsys)["questions"] if q["header"] == "Decide")
    assert labels(q)[0] == "Let it go on" and q["options"][0]["steps"] == ["cplat dispatch resume spec-189"]
    assert labels(q)[-1].startswith("Stop this item") and "other" not in q


def test_stopping_an_item_parks_it_and_leaves_the_branch(world, capsys):  # AC-193.4
    decision(world)
    world.skipped("spec-189", "stopped by you")
    flow = world.doc(capsys)["build"]["flow"]
    assert {"ref": "spec 189", "reason": "stopped by you"} in flow["parked"]


def test_a_stop_that_is_not_a_unit_keeps_the_old_options(world, capsys):  # AC-193.4
    world.stuck(500)       # a stuck item whose run is not a dispatcher unit worktree
    doc = world.doc(capsys)
    assert "What happened:" in doc["screen"]
    assert "Why I ask:" not in doc["screen"] and "Already tried:" not in doc["screen"]


# ---------------- AC-193.5: no decision ----------------

def failure(world, minutes_ago=125, starts=2, red=False):
    world.unit("issue-712", "stuck", cause="stuck", reason="the run ended twice without finishing", starts=starts)
    world.stop_item("issue-712", "stuck", minutes_ago, reason="the run for #712 stopped")
    if red:
        world.event("red", "#712", "2026-11-14T09:30:00", unit="issue-712.1")


def test_failure_screen_says_what_happened_and_what_was_tried(world, capsys):  # AC-193.5
    failure(world)
    screen = world.screen(capsys)
    b = block(screen).splitlines()
    assert b[0].endswith("(#712)")
    assert any(ln.startswith("    What happened: ") and len(ln) > len("    What happened: ") for ln in b)
    assert "    Already tried: restarted once" in b
    assert "    asked 2 h 05 min ago" in b
    assert "While you think" not in screen and "Why I ask" not in screen
    assert "exit code" not in screen.lower()


def test_failure_tried_list_names_a_rerun_check_and_a_restarted_landing(world, capsys):  # AC-193.5
    failure(world, starts=2, red=True)
    assert "    Already tried: restarted once, check rerun once" in world.screen(capsys)


def test_failure_of_a_restarted_landing(world, capsys):  # AC-193.5
    world.unit("issue-712", "stuck", cause="stuck", reason="the landing stopped", starts=1, land_starts=2)
    world.stop_item("issue-712", "stuck", 125, reason="the run for #712 stopped")
    assert "    Already tried: landing restarted once" in world.screen(capsys)


def test_nothing_tried_yet(world, capsys):  # AC-193.5
    failure(world, starts=1)
    assert "    Already tried: nothing yet" in world.screen(capsys)


def test_failure_choices(world, capsys):  # AC-193.5
    failure(world)
    q = next(q for q in world.doc(capsys)["questions"] if q["header"] == "Stopped")
    assert labels(q)[:3] == ["Try again", "Park it", "Show the log"]
    assert q["options"][0]["recommended"] is True and q["options"][0]["steps"] == ["cplat dispatch resume issue-712"]
    park = by_label(q, "Park it")
    assert len(park["steps"]) == 1 and park["steps"][0].startswith('cplat dispatch skip issue-712 --reason "parked: ')
    assert any("cplat dispatch resume issue-712" in u for u in park["undo"])
    log = by_label(q, "Show the log")
    assert not log["steps"] and "--show" in log["then"] and "log:issue-712" in log["then"]


def test_show_the_log_prints_the_log_path_and_leaves_out_its_own_option(world, capsys):  # AC-193.5
    failure(world)
    screen = world.screen(capsys, "--show", "log:issue-712")
    assert "Log: " in screen and "issue-712.1.log" in screen
    assert "AGENT-OUTPUT-SENTINEL" not in screen
    q = next(q for q in world.doc(capsys, "--show", "log:issue-712")["questions"] if q["header"] == "Stopped")
    assert not any(lbl.startswith("Show the log") for lbl in labels(q))
    assert "No log is recorded for" in world.screen(capsys, "--show", "log:issue-999")


def test_budget_screen_and_choices(world, capsys):  # AC-193.5
    world.history("fix", 25, 1_200_000, n=3)
    world.queue(entry(1, "#712", title="Fix a"), entry(2, "#713", title="Fix b"))
    world.used(20_000_000)
    world.budget(since="2026-11-14T06:00:00Z")
    screen = world.screen(capsys)
    b = block(screen).splitlines()
    assert "    What happened: The day's token budget is reached: 20,000,000 of 20,000,000." in b
    assert "    Already tried: nothing yet" in b
    q = next(q for q in world.doc(capsys)["questions"] if q["header"] == "Budget")
    assert labels(q) == ["Wait for tomorrow", "Raise today's budget", "Park it"]
    assert q["options"][0]["recommended"] is True and not q["options"][0]["steps"]
    raise_ = q["options"][1]
    assert raise_["input"]["name"] == "tokens" and not raise_["steps"]
    assert raise_["then"][-2:] == ["--show", "raise-budget:<tokens>"]
    assert q["options"][2]["steps"] == ["cplat dispatch pause --drain"]
    assert any("cplat dispatch resume" in u for u in q["options"][2]["undo"])


def test_raise_confirmation_shows_the_use_and_the_need(world, capsys):  # AC-193.5
    world.history("fix", 25, 1_200_000, n=3)
    world.queue(entry(1, "#712", title="Fix a"), entry(2, "#713", title="Fix b"))
    world.used(20_000_000)
    world.budget()
    screen = world.screen(capsys, "--show", "raise-budget:25000000")
    assert "Tokens today: 20,000,000 of 20,000,000." in screen
    assert "This queue needs about 2,400,000." in screen
    assert re.search(r"New budget for today: 25,?000,?000\.", screen)
    q = question(world.doc(capsys, "--show", "raise-budget:25000000"), "raise-budget")
    assert q["header"] == "Raise" and len(q["options"]) == 2
    assert labels(q)[0].startswith("Raise to") and labels(q)[1] == "Keep the budget"
    assert q["options"][0]["steps"] == ["cplat dispatch budget --today 25000000"]
    assert any("cplat dispatch budget --reset-today" in u for u in q["options"][0]["undo"])
    assert not q["options"][1]["steps"]


def test_raise_confirmation_without_a_known_need_leaves_the_line_out(world, capsys):  # AC-193.5
    world.queue(entry(1, "#712", title="Fix a"))
    world.used(20_000_000)
    world.budget()
    screen = world.screen(capsys, "--show", "raise-budget:25000000")
    assert "Tokens today: 20,000,000 of 20,000,000." in screen and "This queue needs" not in screen


@pytest.mark.parametrize("value", ["100", "20000000", "lots"])
def test_a_number_that_is_not_above_the_limit_is_not_offered(world, capsys, value):  # AC-193.5
    world.used(20_000_000)
    world.budget()
    screen = world.screen(capsys, "--show", f"raise-budget:{value}")
    assert re.search(rf"{value} is not above today's budget of 20,?000,?000\.", screen)
    assert "New budget for today" not in screen
    q = question(world.doc(capsys, "--show", f"raise-budget:{value}"), "raise-budget")
    assert labels(q) == ["Try another number", "Keep the budget"]
    assert q["options"][0]["input"]["name"] == "tokens" and q["options"][0]["then"][-2:] == ["--show", "raise-budget:<tokens>"]


def test_a_raised_budget_shows_in_the_tokens_line_and_the_document(world, capsys):  # AC-193.5
    world.queue(entry(1, "#712", title="Fix a"))
    world.used(21_000_000)
    world.state(lambda st: st["steering"].__setitem__("budget_today", {"day": "2026-11-14", "tokens": 25_000_000, "at": "2026-11-14T09:00:00"}))
    screen = world.screen(capsys)
    assert re.search(r"Tokens today: 21,000,000 of 25,000,000 \(raised for today\)", screen)
    assert world.doc(capsys)["build"]["tokens"] == {"used": 21_000_000, "limit": 25_000_000, "raised": True}


# ---------------- the ship state keeps each question's options ----------------

def test_a_ship_escalation_keeps_each_questions_alternatives(tmp_path, monkeypatch):  # AC-193.4
    import subprocess
    import ship
    repo = tmp_path / "r"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    ship.state_path(repo).write_text(json.dumps({"spec": "189-progress", "phase": "build", "branch": "feature/189-progress"}))
    ship.escalate(repo, "needs a decision", "decision", questions=["Which store? (suggested: Redis; alternatives: Postgres, Mongo)"])
    (q,) = json.loads(ship.state_path(repo).read_text())["questions"]
    assert q["text"] == "Which store?" and q["suggested"] == "Redis" and q["options"] == ["Redis", "Postgres", "Mongo"]
