"""Spec 196 acceptance tests: triage proposes a priority and the user confirms it (AC-196.1 to AC-196.5, AC-196.7, the labels of
AC-196.6 and AC-196.8) through `cplat issue triage batch|confirm|apply|act|setup-labels` against the fake GitHub of `support_176`."""
import json
from pathlib import Path

import pytest

import core
from support_176 import row, world  # noqa: F401  (fixture)

PRIORITY_LABELS = {"p0", "p1", "p2"}


def confirm(w, rows, *extra):
    return w.run("confirm", "--proposals", w.proposals(rows), *extra)


def lines(w, rows):
    return {l["number"]: l for l in confirm(w, rows, "--json").json()["lines"]}


def refused(w, *argv):
    """The text of the error a command raises, or fail."""
    with pytest.raises(core.PlatformError) as err:
        w.run(*argv)
    return str(err.value) + " " + (err.value.hint or "")


def no_priority(**kw):
    return {"priority": None, "priority_reason": None, "expected": None, **kw}


# ---------------- AC-196.1: one proposed priority and a short reason, none for the other classes ----------------

def test_the_batch_carries_the_priority_levels_with_definitions_and_phrases_ac_196_1(world):  # AC-196.1
    world.issue(1)
    data = world.batch()
    levels = data["priority_levels"]
    assert [l["level"] for l in levels] == ["P0", "P1", "P2"]
    assert "data loss" in levels[0]["definition"] and "easy workaround" in levels[2]["definition"]
    assert "data loss" in levels[0]["phrases"] and "normal bug or feature" in levels[1]["phrases"]


@pytest.mark.parametrize("cls,extra", [("bug", {}), ("small-change", {}), ("feature", {"spec": "201-new-thing", "new_spec": True, "expected": None})])
def test_a_bug_small_change_or_feature_row_shows_one_priority_and_a_reason_of_at_most_60_characters_ac_196_1(world, cls, extra):  # AC-196.1
    world.issue(1)
    world.batch()
    got = lines(world, [row(1, **{"class": cls, "priority": "P0", "priority_reason": "P0: data loss", **extra})])[1]
    assert got["priority"] == "P0" and got["priority_reason"] == "P0: data loss" and len(got["priority_reason"]) <= 60
    assert got["decide"] is False
    assert f"{cls}, P0 (P0: data loss)" in got["text"]


def test_the_confirmation_line_names_the_priority_and_its_reason_ac_196_1(world):  # AC-196.1
    world.issue(560)
    world.batch()
    out = confirm(world, [row(560, priority="P0", priority_reason="P0: data loss")]).out
    assert "  #560  bug, P0 (P0: data loss): queue the fix, it runs on its own" in out.splitlines()


@pytest.mark.parametrize("cls,extra", [("question", {"comment": "see docs"}), ("duplicate", {"comment": "same", "duplicate_of": 2}),
                                       ("wontfix", {"comment": "no"}), ("needs-exploring", {}), ("needs-info", {"comment": "Thanks for the report. Which version?", "missing": ["version"]})])
def test_the_other_classes_show_no_priority_ac_196_1(world, cls, extra):  # AC-196.1
    world.issue(1)
    world.issue(2)
    world.batch()
    got = lines(world, [row(1, **{"class": cls, **no_priority(**extra)}), row(2)])[1]
    assert got["priority"] is None and got["priority_reason"] is None
    assert "P0" not in got["text"] and "P1" not in got["text"] and "P2" not in got["text"]


def test_a_priority_on_a_class_that_gets_none_is_refused_as_before_ac_196_1(world):  # AC-196.1
    world.issue(1)
    world.batch()
    text = refused(world, "confirm", "--proposals", world.proposals([row(1, **{"class": "question", "comment": "see docs"})]))
    assert "has no priority" in text


# ---------------- AC-196.2: the reason names the matched definition; P1 when nothing signals urgency ----------------

@pytest.mark.parametrize("level,reason", [("P0", "P0: data loss"), ("P0", "P0: security problem"), ("P2", "P2: easy workaround"),
                                          ("P2", "P2: cosmetic"), ("P1", "P1: normal bug or feature")])
def test_a_proposal_names_a_definition_phrase_of_its_level_ac_196_2(world, level, reason):  # AC-196.2
    world.issue(1)
    world.batch()
    got = lines(world, [row(1, priority=level, priority_reason=reason)])[1]
    assert (got["priority"], got["priority_reason"]) == (level, reason)


def test_a_missing_reason_with_p1_becomes_the_fallback_reason_ac_196_2(world):  # AC-196.2
    world.issue(1)
    world.batch()
    got = lines(world, [row(1, priority="P1", priority_reason=None)])[1]
    assert (got["priority"], got["priority_reason"]) == ("P1", "P1: normal bug or feature")
    assert "bug, P1 (P1: normal bug or feature)" in got["text"]


@pytest.mark.parametrize("level", ["P0", "P2"])
def test_a_missing_reason_with_p0_or_p2_is_an_error_ac_196_2(world, level):  # AC-196.2
    world.issue(1)
    world.batch()
    assert "priority_reason is missing" in refused(world, "confirm", "--proposals", world.proposals([row(1, priority=level, priority_reason=None)]))


@pytest.mark.parametrize("level,reason", [("P0", "it hurts a lot"), ("P0", "P2: cosmetic"), ("P2", "P2: easy workaround, mostly"), ("P1", "P1: data loss")])
def test_a_reason_that_names_no_definition_of_the_level_is_refused_ac_196_2(world, level, reason):  # AC-196.2
    world.issue(1)
    world.batch()
    text = refused(world, "confirm", "--proposals", world.proposals([row(1, priority=level, priority_reason=reason)]))
    assert "priority_reason must be" in text


# ---------------- AC-196.3: an existing priority label wins ----------------

@pytest.mark.parametrize("label,level", [("p0", "P0"), ("p1", "P1"), ("p2", "P2")])
def test_a_priority_label_on_the_issue_wins_whatever_the_text_suggests_ac_196_3(world, label, level):  # AC-196.3
    other = "P2" if level != "P2" else "P0"
    reason = "P2: cosmetic" if other == "P2" else "P0: data loss"
    world.issue(1, labels=("triage", label))
    world.batch()
    got = lines(world, [row(1, priority=other, priority_reason=reason)])[1]
    assert (got["priority"], got["priority_reason"], got["decide"]) == (level, "set on the issue", False)
    assert f"bug, {level} (set on the issue)" in got["text"]


def test_more_than_one_priority_label_proposes_the_most_urgent_and_marks_the_row_ac_196_3(world):  # AC-196.3
    world.issue(1, labels=("triage", "p2", "p0"))
    world.batch()
    got = lines(world, [row(1, priority="P1")])[1]
    assert (got["priority"], got["priority_reason"], got["decide"]) == ("P0", "set on the issue", True)
    assert "  #1  bug, P0 (set on the issue; p0, p2: decide): queue the fix, it runs on its own" in confirm(world, [row(1, priority="P1")]).lines


def test_a_row_with_several_labels_stays_to_decide_until_the_user_decided_ac_196_3(world):  # AC-196.3
    world.issue(1, labels=("triage", "p1", "p2"))
    world.batch()
    path = world.proposals([row(1)])
    assert world.run("overview", "--proposals", path, "--json").json()["groups"]["decide"] == [1]
    world.run("confirm", "--proposals", path, "--set", "1=P1")
    got = {l["number"]: l for l in world.run("confirm", "--proposals", path, "--json").json()["lines"]}[1]
    assert got["decide"] is False and got["priority"] == "P1"


# ---------------- AC-196.4: change, confirm --set, and nothing written without the user ----------------

@pytest.mark.parametrize("spelling", ["P0", "p0"])
def test_confirm_set_shows_the_new_priority_with_the_reason_changed_by_you_ac_196_4(world, spelling):  # AC-196.4
    world.issue(560)
    world.batch()
    path = world.proposals([row(560)])
    out = world.run("confirm", "--proposals", path, "--set", f"560={spelling}")
    assert "  #560  bug, P0 (changed by you): queue the fix, it runs on its own" in out.lines
    saved = json.loads(Path(path).read_text())["rows"][0]
    assert saved["priority"] == "P0" and saved["priority_reason"] == "changed by you" and saved["priority_decided"] is True
    again = confirm(world, json.loads(Path(path).read_text())["rows"], "--json").json()["lines"][0]
    assert (again["priority"], again["priority_reason"]) == ("P0", "changed by you")


def test_confirm_set_json_prints_the_confirmation_as_without_set_ac_196_4(world):  # AC-196.4
    world.issue(1)
    world.issue(2)
    world.batch()
    data = world.run("confirm", "--proposals", world.proposals([row(1), row(2)]), "--set", "1=P2", "--set", "2=p0", "--json").json()
    got = {l["number"]: (l["priority"], l["priority_reason"]) for l in data["lines"]}
    assert got == {1: ("P2", "changed by you"), 2: ("P0", "changed by you")}
    assert data["choices"] == ["OK, do it", "Change one", "Cancel"]


def test_setting_the_priority_a_row_already_has_keeps_its_reason_ac_196_4(world):  # AC-196.4
    world.issue(1)
    world.batch()
    path = world.proposals([row(1, priority="P0", priority_reason="P0: data loss")])
    got = world.run("confirm", "--proposals", path, "--set", "1=P0", "--json").json()["lines"][0]
    assert (got["priority"], got["priority_reason"]) == ("P0", "P0: data loss")


def test_a_choice_overrides_the_label_of_the_issue_ac_196_4(world):  # AC-196.4
    world.issue(1, labels=("triage", "p1"))
    world.batch()
    path = world.proposals([row(1)])
    got = world.run("confirm", "--proposals", path, "--set", "1=P0", "--json").json()["lines"][0]
    assert (got["priority"], got["priority_reason"]) == ("P0", "changed by you")


def test_confirm_set_refuses_what_is_not_a_priority_row_and_leaves_the_file_ac_196_4(world):  # AC-196.4
    world.issue(1)
    world.issue(2)
    world.batch()
    path = world.proposals([row(1), row(2, **{"class": "question", **no_priority(comment="see docs")})])
    before = Path(path).read_text()
    assert "#9 is not an issue of the batch" in refused(world, "confirm", "--proposals", path, "--set", "9=P0")
    assert "#2 is a question: it gets no priority" in refused(world, "confirm", "--proposals", path, "--set", "2=P0")
    assert "--set takes N=P0|P1|P2" in refused(world, "confirm", "--proposals", path, "--set", "1=P3")
    assert Path(path).read_text() == before


def test_a_run_without_confirmation_writes_no_label_and_makes_no_spec_ac_196_4(world):  # AC-196.4
    world.spec("201-new-thing", status="draft")
    specs_dir = world.tmp / "docs" / "specs"
    before = {p.name for p in specs_dir.iterdir()}
    world.issue(1, labels=("triage", "p2"))
    world.issue(2)
    world.batch()
    path = world.proposals([row(1), row(2, **{"class": "feature", "spec": "201-new-thing", "new_spec": True, "expected": None})])
    world.run("overview", "--proposals", path)
    world.run("confirm", "--proposals", path)
    world.run("confirm", "--proposals", path, "--set", "1=P0")
    world.run("act", "--proposals", path, "--rows", "all", "--dry-run")
    assert world.writes() == []
    assert {p.name for p in specs_dir.iterdir()} == before


def test_an_unattended_act_with_a_priority_change_refuses_before_any_write_ac_196_4(world, monkeypatch):  # AC-196.4
    monkeypatch.setenv("CPLAT_HEADLESS", "1")
    world.issue(1)
    world.issue(2, labels=("triage",))
    world.batch()
    text = refused(world, "act", "--proposals", world.proposals([row(2, **{"class": "question", **no_priority(comment="see docs")}), row(1)]),
                   "--rows", "all")
    assert "a priority label needs the user's confirmation" in text and "run /issue:triage in a Claude Code session" in text
    assert world.writes() == []


def test_an_unattended_act_without_a_priority_change_still_works_ac_196_4(world, monkeypatch):  # AC-196.4
    monkeypatch.setenv("CPLAT_HEADLESS", "1")
    world.issue(1, labels=("triage", "p1"))
    world.batch()
    assert world.run("act", "--proposals", world.proposals([row(1, **{"class": "bug", "comment": "see docs"})]),
                     "--rows", "all").rc == 0
    assert "bug" in world.edits()[1][0] and not (world.edits()[1][0] & PRIORITY_LABELS)


# ---------------- AC-196.5: exactly one priority label afterwards ----------------

def test_adding_a_priority_label_removes_every_other_one_in_the_same_edit_ac_196_5(world):  # AC-196.5
    world.issue(1, labels=("triage", "p1", "p2"))
    world.run("apply", "1", "--add", "p0")
    assert world.edits() == {1: ({"p0"}, {"p1", "p2"})}


def test_a_confirmed_priority_replaces_the_one_on_the_issue_when_the_command_acts_ac_196_5(world):  # AC-196.5
    world.issue(1, labels=("triage", "p1"))
    world.batch()
    world.run("act", "--proposals", world.proposals([row(1, priority="P0", priority_reason="changed by you",
                                                                  priority_decided=True)]), "--rows", "all")   # as `confirm --set` writes it
    add, remove = world.edits()[1]
    assert "p0" in add and "p1" in remove and not ((add | remove) & {"p2"})


def test_two_priority_labels_in_one_apply_are_refused_before_any_github_call_ac_196_5(world):  # AC-196.5
    world.issue(1, labels=("triage",))
    text = refused(world, "apply", "1", "--add", "p0", "--add", "p1")
    assert "more than one priority label: p0, p1" in text and "an issue carries one of p0, p1, p2" in text
    assert world.calls == []


def test_a_class_that_gets_no_priority_leaves_the_existing_priority_label_ac_196_5(world):  # AC-196.5
    world.issue(1, labels=("triage", "p2"))
    world.batch()
    world.run("act", "--proposals", world.proposals([row(1, **{"class": "question", **no_priority(comment="see docs")})]), "--rows", "all")
    add, remove = world.edits()[1]
    assert not ((add | remove) & PRIORITY_LABELS)


def test_an_unattended_apply_refuses_any_change_of_a_priority_label_ac_196_5(world, monkeypatch):  # AC-196.5
    monkeypatch.setenv("CPLAT_HEADLESS", "1")
    world.issue(1, labels=("triage", "p1"))
    text = refused(world, "apply", "1", "--add", "p0")
    assert "a priority label needs the user's confirmation" in text and "run /issue:triage in a Claude Code session" in text
    text = refused(world, "apply", "1", "--remove", "p1")
    assert "a priority label needs the user's confirmation" in text
    assert world.writes() == []
    assert world.run("apply", "1", "--add", "bug").rc == 0 and world.edits()[1][0] == {"bug"}


# ---------------- AC-196.6 / AC-196.7: the label follows the confirmed priority, the spec keeps its own ----------------

def test_a_confirmed_feature_row_gets_the_matching_label_ac_196_6(world):  # AC-196.6
    world.spec("201-new-thing", status="draft")
    world.issue(563)
    world.batch()
    world.run("act", "--proposals", world.proposals([row(563, **{"class": "feature", "priority": "P0", "priority_reason": "P0: outage",
                                                                   "spec": "201-new-thing", "new_spec": True, "expected": None})]),
              "--rows", "all")
    assert world.edits()[563][0] == {"enhancement", "tracked", "triaged", "p0"}


def existing_spec_world(w, spec_priority="P2"):
    w.spec("123-x", status="approved")
    path = w.tmp / "docs" / "specs" / "123-x" / "spec.md"
    path.write_text(path.read_text().replace("priority: P1", f"priority: {spec_priority}"))
    w.issue(560)
    w.batch()
    return path, [row(560, **{"class": "feature", "priority": "P1", "priority_reason": "P1: normal bug or feature", "spec": "123-x",
                              "expected": None})]


def test_a_feature_added_to_a_spec_with_another_priority_names_both_and_the_way_to_change_it_ac_196_7(world):  # AC-196.7
    path, rows = existing_spec_world(world)
    before = path.read_text()
    res = world.run("act", "--proposals", world.proposals(rows), "--rows", "all")
    assert "p1" in world.edits()[560][0]
    assert path.read_text() == before and "priority: P2" in before
    assert "Priority" in res.lines
    assert "  #560 p1, spec 123 P2: the spec keeps P2; change it with cplat spec priority 123 P1" in res.lines


def test_the_json_summary_lists_the_priority_notes_ac_196_7(world):  # AC-196.7
    _, rows = existing_spec_world(world)
    data = world.run("act", "--proposals", world.proposals(rows), "--rows", "all", "--json").json()
    assert data["priority_notes"] == [{"number": 560, "label": "p1", "spec": "123-x", "spec_priority": "P2",
                                       "command": "cplat spec priority 123 P1"}]


def test_a_spec_with_the_same_priority_adds_no_note_ac_196_7(world):  # AC-196.7
    _, rows = existing_spec_world(world, "P1")
    res = world.run("act", "--proposals", world.proposals(rows), "--rows", "all", "--json")
    assert res.json()["priority_notes"] == []
    assert "Priority\n" not in world.run("act", "--proposals", world.proposals(rows), "--rows", "all").out


# ---------------- AC-196.8: the labels exist ----------------

def test_setup_labels_creates_the_three_priority_labels_and_leaves_existing_ones_ac_196_8(world):  # AC-196.8
    world.repo_labels = ["bug", "p1"]
    world.run("setup-labels")
    created = {c[2] for c in world.calls if c[:2] == ["label", "create"]}
    assert {"p0", "p2"} <= created and not ({"bug", "p1"} & created)


# ---------------- the prompt names the commands it must run (structure only) ----------------

def test_the_triage_prompt_changes_a_priority_through_confirm_set_ac_196_4():  # AC-196.4
    text = (Path(__file__).resolve().parents[2] / "plugins" / "issue" / "commands" / "triage.md").read_text()
    assert "--set" in text and "confirm" in text and "priority_levels" in text    # short names the commands need, not sentences
