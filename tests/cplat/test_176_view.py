"""Spec 176 acceptance tests: the overview (AC-176.2), the question pages and the confirmation (AC-176.3), through
`cplat issue triage overview|confirm` against a batch saved from a fake GitHub (`support_176`)."""
import json
import re

import pytest

import core
import triage
from support_176 import FORBIDDEN, ago, engine_body, comment, overview_world, row, world  # noqa: F401  (fixture)

OVERVIEW = """Triage of acme/shop: 7 issues

Needs your decision (2)
  #560  Login fails after the token refresh on Safari
        check, from: contributor
  #571  Add CSV export to the run list
Clear (3)
  #562  Crash when the config file is empty
        bug, P1, fix on its own
  #563  Dark mode for the console
        feature, P2, write new spec, from: none
  #564  How do I rotate the token
        question, answer in comment
Already handled (2)
  in spec 176 (approved): #548
  being worked on (fix/issue-551): #551
Skipped: #12 silent 3d

2 questions follow."""


def screen(w, rows, *extra):
    return w.run("overview", "--proposals", w.proposals(rows), *extra)


@pytest.fixture()
def scene(world):
    rows = overview_world(world)
    try:
        world.batch()
    except (SystemExit, core.PlatformError):     # `batch` is not there yet: the command of the test fails, not the fixture
        world.data = {"batch_file": str(world.tmp / "none.json")}
    return world, rows


# ---------------- AC-176.2 the overview ----------------

def test_the_overview_has_three_groups_with_counts_rows_and_the_question_count_ac_176_2(scene):  # AC-176.2
    w, rows = scene
    assert screen(w, rows).out.rstrip("\n") == OVERVIEW


def test_the_overview_fits_80_columns_has_no_colour_and_no_banned_words_ac_176_2(scene):  # AC-176.2
    w, rows = scene
    rows[0]["summary"] = "x" * 20 + " " + "long words " * 5 + "end"      # 80 characters, wrapped under its number
    text = screen(w, rows).out
    assert max(len(l) for l in text.splitlines()) <= 80 and "\x1b" not in text
    assert "#560" in text and re.search(r"^ {8}\S", text, re.M)
    for word in FORBIDDEN:
        assert word not in text.lower(), word


def test_empty_groups_are_printed_with_zero_and_no_questions_ac_176_2(world):  # AC-176.2
    world.issue(1)
    world.batch()
    text = screen(world, [row(1)]).out
    lines = text.splitlines()
    assert lines[0].startswith("Triage of acme/shop: 1 issue")
    heads = [l for l in lines if re.match(r"^(Needs your decision|Clear|Already handled) \(\d+\)$", l)]
    assert heads == ["Needs your decision (0)", "Clear (1)", "Already handled (0)"]
    assert lines[-1] == "No questions follow." and "Skipped" not in text


def test_one_question_is_announced_in_the_singular_ac_176_2(world):  # AC-176.2
    world.issue(1)
    world.batch()
    q = {"text": "Which?", "options": ["A", "B"]}
    assert screen(world, [row(1, question=q)]).out.splitlines()[-1] == "1 question follows."


def test_a_check_row_without_a_question_gets_one_with_the_class_first_ac_176_2(world):  # AC-176.2
    world.issue(1)
    world.batch()
    data = screen(world, [row(1, mark="check", **{"class": "feature"})], "--json").json()
    assert data["groups"] == {"decide": [1], "clear": [], "handled": []}
    [q] = data["pages"][0]["questions"]
    assert q["text"] == "Is #1 a feature?"
    assert [o["label"] for o in q["options"]] == ["feature (Recommended)", "bug", "small-change", "needs-info"]
    assert [o["recommended"] for o in q["options"]] == [True, False, False, False]
    assert screen(world, [row(1, mark="check", **{"class": "feature"})]).out.splitlines()[-1] == "1 question follows."


def test_more_than_one_priority_label_needs_a_decision_ac_176_2(world):  # AC-176.2
    world.issue(1, labels=("triage", "p1", "p2"))
    world.batch()
    assert screen(world, [row(1)], "--json").json()["groups"]["decide"] == [1]


def test_status_facts_win_over_the_proposal_and_need_no_row_ac_176_2(world):  # AC-176.2
    world.spec("176-triage-x", tracks=[1], status="building")
    world.issue(1)
    world.issue(2)
    world.batch()
    data = screen(world, [row(2)], "--json").json()
    assert data["groups"] == {"decide": [], "clear": [2], "handled": [1]}
    assert "in spec 176 (building): #1" in data["screen"]


def test_handled_issues_are_folded_one_line_per_status_in_the_documented_order_ac_176_2(world):  # AC-176.2
    world.issue(1, labels=("triage", "in-progress"), comments=[comment("me", "<!-- cplat-claim -->\nClaimed for branch `fix/a` (cplat dispatch).", "OWNER")])
    world.issue(2, comments=[comment("me", "Duplicate of #5", "OWNER")])
    world.issue(3)
    world.issue(4, labels=("triage", "in-progress"), comments=[comment("me", "<!-- cplat-claim -->\nClaimed for branch `fix/a` (cplat dispatch).", "OWNER")])
    world.issue(5)
    world.spec("200-s", tracks=[3], status="draft")
    world.merged = [{"number": 77, "title": "fix", "body": "Closes #5", "url": "u", "closingIssuesReferences": {"nodes": []}}]
    world.batch()
    text = screen(world, []).out
    handled = text.split("Already handled (5)\n")[1].split("\nSkipped")[0].split("\n\n")[0].splitlines()
    assert [l.strip() for l in handled] == ["in spec 200 (draft): #3", "being worked on (fix/a): #1, #4", "fixed by #77: #5", "duplicate of #5: #2"]


def test_the_overview_json_pages_hold_at_most_four_questions_with_the_recommended_first_ac_176_3(world):  # AC-176.3
    for n in range(1, 7):
        world.issue(n)
    world.batch()
    rows = [row(n, question={"text": f"Q{n}?", "options": [f"first{n}", f"second{n}"]}) for n in range(1, 7)]
    data = screen(world, rows, "--json").json()
    pages = data["pages"]
    assert [p["page"] for p in pages] == ["1 of 2", "2 of 2"] and [len(p["questions"]) for p in pages] == [4, 2]
    q = pages[0]["questions"][0]
    assert q["number"] == 1 and q["header"] == "#1" and q["text"] == "Q1?"
    assert q["options"] == [{"label": "first1 (Recommended)", "recommended": True}, {"label": "second1", "recommended": False}]
    assert [q["number"] for p in pages for q in p["questions"]] == [1, 2, 3, 4, 5, 6]
    assert data["screen"].splitlines()[-1] == "6 questions follow."


def test_four_questions_fit_one_page_ac_176_3(world):  # AC-176.3
    for n in range(1, 5):
        world.issue(n)
    world.batch()
    rows = [row(n, question={"text": "Q?", "options": ["a"]}) for n in range(1, 5)]
    assert [p["page"] for p in screen(world, rows, "--json").json()["pages"]] == ["1 of 1"]


# ---------------- the proposals file is validated, all errors at once ----------------

def message(err):
    return str(err.value) + " " + (err.value.hint or "")


def test_every_proposal_error_is_listed_at_once_ac_176_2(world):  # AC-176.2
    for n in (1, 2, 3, 4):
        world.issue(n)
    world.batch()
    rows = [row(1, summary="x" * 81), row(2, **{"class": "bogus"}), row(3, summary="two\nlines")]      # no row for #4
    with pytest.raises(core.PlatformError) as err:
        screen(world, rows)
    text = message(err)
    for n in (1, 2, 3, 4):
        assert f"#{n}" in text, n


@pytest.mark.parametrize("changes", [
    {"class": "bogus"}, {"mark": "maybe"}, {"priority": "P3"}, {"priority": None}, {"priority_reason": "r" * 61},
    {"question": {"text": "Q?", "options": []}}, {"question": {"text": "Q?", "options": list("abcde")}}, {"summary": ""},
    {"expected": None}, {"number": 99},
], ids=lambda c: next(iter(c)) + "=" + str(next(iter(c.values())))[:12])
def test_a_bad_proposal_row_is_refused_ac_176_2(world, changes):  # AC-176.2
    world.issue(1)
    world.batch()
    with pytest.raises(core.PlatformError):
        screen(world, [row(1, **changes)])


@pytest.mark.parametrize("rows", [
    [row(1, **{"class": "question", "priority": None, "comment": None})],
    [row(1, **{"class": "duplicate", "priority": None, "comment": "dup", "duplicate_of": None})],
    [row(1, **{"class": "wontfix", "priority": "P2", "comment": "no"})],
    [row(1, **{"class": "needs-info", "priority": None, "comment": ""})],
    [row(1), row(1)],
    [],
], ids=["question-without-comment", "duplicate-without-target", "priority-on-wontfix", "needs-info-empty-comment", "two-rows", "no-row"])
def test_proposal_rules_by_class_and_coverage_ac_176_2(world, rows):  # AC-176.2
    world.issue(1)
    world.batch()
    with pytest.raises(core.PlatformError):
        screen(world, rows)


def test_a_valid_row_of_each_class_is_accepted_ac_176_2(world):  # AC-176.2
    for n in range(1, 9):
        world.issue(n)
    world.batch()
    kinds = {1: ("bug", "P0"), 2: ("small-change", "P2"), 3: ("feature", "P1"), 4: ("question", None), 5: ("duplicate", None),
             6: ("wontfix", None), 7: ("needs-exploring", None), 8: ("needs-info", None)}
    rows = [row(n, **{"class": c, "priority": p, "comment": "text" if c in ("question", "duplicate", "wontfix", "needs-info") else None,
                      "duplicate_of": 2 if c == "duplicate" else None, "expected": "ok" if c in ("bug", "small-change") else None})
            for n, (c, p) in kinds.items()]
    assert screen(world, rows).rc == 0


def test_an_engine_row_takes_the_engine_class_and_mark_ac_176_6(world):  # AC-176.6
    world.issue(1, labels=("triage", "signal"), body=engine_body("fix", 0.9))
    world.issue(2, labels=("triage", "signal"), body=engine_body("fix", 0.5, key="k2"))
    world.issue(3, labels=("triage", "signal"), body=engine_body("fix", 0.9, key="k3"))
    world.batch()
    plain = {n: {"number": n, "summary": f"Engine issue {n}", "priority": "P1", "expected": "stays up"} for n in (1, 2, 3)}
    plain[3]["class"] = "feature"          # the triager disagrees with the engine
    data = screen(world, list(plain.values()), "--json").json()
    assert data["groups"]["clear"] == [1] and data["groups"]["decide"] == [2, 3]
    assert "bug, P1, fix on its own" in data["screen"]


# ---------------- the saved batch ----------------

def test_a_batch_older_than_two_hours_is_refused_ac_176_1(scene):  # AC-176.1
    w, rows = scene
    path = w.batch_path()
    saved = json.loads(path.read_text())
    saved["read_at"] = ago(hours=3)
    path.write_text(json.dumps(saved))
    with pytest.raises(core.PlatformError) as err:
        screen(w, rows)
    assert "batch again" in message(err)


def test_without_a_saved_batch_the_commands_say_to_run_batch_ac_176_1(world):  # AC-176.1
    with pytest.raises(core.PlatformError) as err:
        screen(world, [row(1)])
    assert "batch" in message(err)


# ---------------- AC-176.3 the confirmation ----------------

PLAN = """The plan (6 actions):
  #560  bug, P1: queue the fix, it runs on its own
  #571  feature, P1: write a new spec, track the issue in it
  #562  bug, P1: queue the fix, it runs on its own
  #563  feature, P2: write a new spec, track the issue in it
  #564  question: post the answer, label question
  #548  tracked in spec 176: label tracked
Choose: OK, do it / Change one / Cancel"""


def confirm(w, rows, *extra):
    return w.run("confirm", "--proposals", w.proposals(rows), *extra)


def test_the_confirmation_is_one_line_per_action_in_group_order_ac_176_3(scene):  # AC-176.3
    w, rows = scene
    out = confirm(w, rows).out
    assert out.rstrip("\n") == PLAN
    assert max(len(l) for l in out.splitlines()) <= 80
    for word in FORBIDDEN:
        assert word not in out.lower(), word


def test_the_confirmation_json_has_lines_and_the_three_choices_ac_176_3(scene):  # AC-176.3
    w, rows = scene
    data = confirm(w, rows, "--json").json()
    assert data["choices"] == ["OK, do it", "Change one", "Cancel"]
    assert [(l["number"], l["class"]) for l in data["lines"]][:3] == [(560, "bug"), (571, "feature"), (562, "bug")]
    assert "queue the fix, it runs on its own" in data["lines"][0]["text"]
    assert [l["number"] for l in data["lines"]][-1] == 548 and 551 not in [l["number"] for l in data["lines"]]


@pytest.mark.parametrize("cls,extra,phrase", [
    ("small-change", {}, "queue the fix, it runs on its own"),
    ("feature", {"spec": "201-existing"}, "track the issue in spec 201"),
    ("feature", {"spec": "201-existing", "new_spec": True}, "write a new spec, track the issue in it"),
    ("duplicate", {"comment": "same", "duplicate_of": 7, "priority": None}, "mark as duplicate of #7"),
    ("wontfix", {"comment": "no", "priority": None}, "explain why, label wontfix"),
    ("needs-info", {"comment": "which?", "priority": None}, "ask the reporter, label needs-info"),
    ("needs-exploring", {"priority": None}, "nothing posted, explore it next"),
])
def test_the_plan_phrase_by_class_ac_176_3(world, cls, extra, phrase):  # AC-176.3
    world.issue(1)
    world.batch()
    data = confirm(world, [row(1, **{"class": cls, **extra})], "--json").json()
    assert phrase in data["lines"][0]["text"]


def test_show_prints_the_exact_labels_and_comment_of_a_row_ac_176_3(scene):  # AC-176.3
    w, rows = scene
    rows[1]["answers"] = ["Only on Linux", "Since 5.2"]
    out = confirm(w, rows, "--show", "562").out
    assert "labels: +bug, +triaged, +p1, -triage" in out
    assert ("Triage: Crash when the config file is empty\n\nClass: bug, priority P1.\nAnswers: Only on Linux; Since 5.2\n"
            "Expected result: Issue 562 works") in out
    assert w.writes() == []


def test_show_replaces_other_priority_labels_and_a_row_without_actions_shows_none_ac_176_8(world):  # AC-176.8
    world.issue(1, labels=("triage", "p2"))
    world.issue(2)
    world.batch()
    rows = [row(1, priority="P0"), row(2, **{"class": "needs-exploring", "priority": None, "expected": None})]
    assert "labels: +bug, +triaged, +p0, -triage, -p2" in confirm(world, rows, "--show", "1").out
    out = confirm(world, rows, "--show", "2").out
    assert "labels: none" in out and "comment: none" in out


def test_show_of_a_feature_comment_names_the_spec_ac_176_8(world):  # AC-176.8
    world.issue(1)
    world.batch()
    rows = [row(1, **{"class": "feature", "spec": "201-new-thing", "new_spec": True, "expected": None})]
    out = confirm(world, rows, "--show", "1").out
    assert "labels: +enhancement, +tracked, +triaged, +p1, -triage" in out and "Tracked as spec 201-new-thing" in out


def test_the_apply_subcommand_still_refuses_unknown_labels_and_knows_the_priorities_ac_176_8():  # AC-176.8
    assert {"p0", "p1", "p2"} <= set(triage.LABELS)
    assert triage.LABELS["p0"][0] == "b60205" and triage.LABELS["p1"][0] == "d93f0b" and triage.LABELS["p2"][0] == "fef2c0"
