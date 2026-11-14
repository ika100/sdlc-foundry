"""Spec 192 acceptance tests: the questions `cplat next --json` holds (AC-192.5 choices, .6, .7, .8 hand-over)."""
import re

import pytest

from support_192 import World, question


def by_label(q, label):
    return next(o for o in q["options"] if o["label"].startswith(label))


def asking(doc, label):
    return next(q for q in doc["questions"] if any(o["label"].startswith(label) for o in q["options"]))


@pytest.fixture
def world(tmp_path, monkeypatch):
    return World(tmp_path, monkeypatch)


def two_drafts(world):
    world.add_draft("189-web-image", "A web image without the finding", issue=682, pr=690, created="2026-11-10")
    world.add_draft("190-second", "Second change", issue=683, pr=691, created="2026-11-11")


def labels(q):
    return [o["label"] for o in q["options"]]


# ---------------- AC-192.5 ----------------

def test_approve_choices(world, capsys):  # AC-192.5
    two_drafts(world)
    q = question(world.doc(capsys), "approve")
    assert labels(q) == ["Approve all 2", "Show assumptions", "Approve only one", "Later"]
    assert q["options"][0]["recommended"] is True
    assert all("(recommended)" not in lbl.lower() for lbl in labels(q))


def test_one_draft_has_no_approve_all(world, capsys):  # AC-192.5
    world.add_draft("189-web-image", "A web image", pr=690)
    assert labels(question(world.doc(capsys), "approve")) == ["Approve", "Show assumptions", "Later"]


def test_a_draft_with_an_open_question_is_asked_first_and_not_approved_with_the_rest(world, capsys):  # AC-192.5
    two_drafts(world)
    world.add_draft("191-asks", "Asks something", pr=692, created="2026-11-12",
                    questions=("Which store? (suggested: Redis; alternatives: Postgres, Mongo)",))
    doc = world.doc(capsys)
    first = doc["questions"][0]
    assert "Which store" in first["question"]
    assert first["options"][0]["label"] == "Redis" and first["options"][0]["recommended"] is True
    assert "Postgres" in labels(first)
    approve = question(doc, "approve")
    assert approve["options"][0]["label"] == "Approve all 2"
    assert not any("191" in ref for ref in approve["options"][0]["record"])


def test_only_one_sub_screen_lists_two_specs_oldest_first(world, capsys):  # AC-192.5
    for i in range(3):
        world.add_draft(f"19{i}-spec", f"Spec number {i}", pr=690 + i, created=f"2026-11-0{i + 1}")
    doc = world.doc(capsys, "--choose", "approve")
    q = doc["questions"][0]
    assert labels(q)[:2] == ["Spec number 0 (spec 190)", "Spec number 1 (spec 191)"]
    assert "Next specs" in labels(q)


# ---------------- AC-192.6 ----------------

def many_questions(world, n=6):
    qs = tuple(f"Question {i}? (suggested: yes; alternatives: no, maybe)" for i in range(n))
    world.add_draft("189-asks", "Asks a lot", pr=690, questions=qs)


def check_shape(doc):
    assert len(doc["questions"]) <= 4
    for q in doc["questions"]:
        assert 1 <= len(q["options"]) <= 4
        assert len(q["header"]) <= 12
        assert [o["recommended"] for o in q["options"]].count(True) == 1
        assert q["options"][0]["recommended"] is True
        for o in q["options"]:
            assert not (o.get("steps") and o.get("then"))


def test_at_most_four_questions_per_page(world, capsys):  # AC-192.6
    many_questions(world)
    doc = world.doc(capsys)
    check_shape(doc)
    assert len(doc["questions"]) == 4
    assert doc["page"]["n"] == 1 and doc["page"]["of"] == 2 and doc["page"]["text"] == "page 1 of 2"
    second = world.doc(capsys, "--page", "2")
    check_shape(second)
    assert second["page"]["n"] == 2
    assert {q["question"] for q in second["questions"]}.isdisjoint({q["question"] for q in doc["questions"]})


def test_one_page_has_no_page_text(world, capsys):  # AC-192.6
    two_drafts(world)
    doc = world.doc(capsys)
    assert doc["page"]["of"] == 1 and doc["page"]["text"] == ""
    check_shape(doc)


def test_later_puts_an_item_off(world, capsys):  # AC-192.6
    two_drafts(world)
    doc = world.doc(capsys, "--later", "approve:o/n:189-web-image")
    assert doc["waiting"]["later"] == 1
    assert doc["waiting"]["items"] == ["approve:o/n:190-second"]
    assert "1 put off for later" in doc["screen"]
    assert "189-web-image" not in str(doc["questions"])
    assert labels(question(doc, "approve"))[0] == "Approve"


def test_later_option_carries_the_items_for_the_next_call(world, capsys):  # AC-192.6
    two_drafts(world)
    later = by_label(question(world.doc(capsys), "approve"), "Later")
    assert later["then"][:2] == ["cplat", "next"] and later["then"].count("--later") == 2
    assert "approve:o/n:189-web-image" in later["then"] and "approve:o/n:190-second" in later["then"]


def test_every_step_can_be_gone_through_by_choosing(world, capsys):  # AC-192.6
    two_drafts(world)
    world.add_issue(700, "An issue")
    world.stuck(500)
    doc = world.doc(capsys)
    check_shape(doc)
    for q in doc["questions"]:
        for o in q["options"]:
            assert o["steps"] or o["then"] or o["label"] in ("Later", "Wait for tomorrow", "Not now")


def test_how_tells_the_session_what_to_do(world, capsys):  # AC-192.6
    how = world.doc(capsys)["how"]
    for word in ("screen", "questions", "record", "steps", "undo"):
        assert word in how


# ---------------- AC-192.7 ----------------

def test_approve_names_each_outward_action_and_the_irreversible_one(world, capsys):  # AC-192.7
    two_drafts(world)
    o = by_label(question(world.doc(capsys), "approve"), "Approve all")
    whats = [a["what"] for a in o["actions"]]
    assert whats.count("approval commit") == 2 and whats.count("merge") == 2
    merge = next(a for a in o["actions"] if a["what"] == "merge")
    assert merge["target"] == "PR #690 into main" and merge["undo"] is None
    assert o["cannot_undo"] and "PR #690" in o["cannot_undo"][0]
    assert o["description"].startswith("Cannot be undone:")
    assert len(o["undo"]) == 2 and all(u.startswith("Undo: ") for u in o["undo"])
    assert o["steps"] == ["/component:spec approve 189", "/component:spec approve 190"] or len(o["steps"]) == 2


def test_nothing_outward_runs_before_the_choice(world, capsys):  # AC-192.7
    two_drafts(world)
    world.add_issue(700, "An issue")
    world.stuck(500)
    world.doc(capsys)
    world.doc(capsys, "--show", "assumptions")
    assert world.writes() == []


def test_show_details_option_on_every_outward_question(world, capsys):  # AC-192.7
    world.add_issue(700, "An issue")
    world.stuck(500)
    doc = world.doc(capsys)
    for q in doc["questions"]:
        if any(o["actions"] for o in q["options"] if o.get("actions")):
            assert "Show details" in labels(q)


def test_triage_details_list_labels_and_a_comment(world, capsys):  # AC-192.7
    world.add_issue(700, "An issue")
    q = asking(world.doc(capsys), "Triage them")
    assert labels(q) == ["Triage them", "Show details", "Later"]
    action = by_label(q, "Triage them")["actions"][0]
    assert action["what"] == "labels and a comment" and "#700" in action["target"]
    details = world.screen(capsys, "--show", f"details:{q['id']}")
    assert "labels and a comment" in details and "#700" in details
    assert details.split("\n\n")[-1].startswith("Your part:")


def test_release_actions_say_what_cannot_be_undone(world, capsys):  # AC-192.7
    (world.repo / "docs" / "changelog.d").mkdir(parents=True)
    (world.repo / "docs" / "changelog.d" / "9-x.added.md").write_text("**x** (spec 9).\n")
    world._git("add", "-A")
    world._git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "fragment")
    q = asking(world.doc(capsys), "Release now")
    o = q["options"][0]
    assert o["label"] == "Release now" and o["steps"] == ["/platform:release"]
    assert [a["what"] for a in o["actions"]] == ["release pull request and merge", "tag", "GitHub release"]
    assert o["undo"] == [] and len(o["cannot_undo"]) >= 1
    assert "the tag and the published release" in o["cannot_undo"]


def test_assumptions_sub_screen_lists_actions_with_targets(world, capsys):  # AC-192.7
    two_drafts(world)
    screen = world.screen(capsys, "--show", "assumptions")
    assert "PR #690" in screen and "approval commit" in screen
    assert screen.split("\n\n")[-1].startswith("Your part:")


def test_record_argv_names_the_option_and_items(world, capsys):  # AC-192.7
    two_drafts(world)
    doc = world.doc(capsys)
    rec = by_label(question(doc, "approve"), "Approve all")["record"]
    assert rec[:3] == ["cplat", "next", "answer"]
    assert rec[rec.index("--shown-at") + 1] == doc["shown_at"]
    assert rec[rec.index("--option") + 1] == "approve-all"
    items = [rec[i + 1] for i, a in enumerate(rec) if a == "--item"]
    assert items == ["spec:o/n:189-web-image", "spec:o/n:190-second"]


# ---------------- AC-192.8 ----------------

def test_first_question_is_the_next_step_as_a_choice_with_the_recommended_option_first(world, capsys):  # AC-192.8
    world.add_issue(700, "An issue")
    q = world.doc(capsys)["questions"][0]
    assert q["options"][0]["recommended"] is True
    assert q["options"][0]["steps"] == ["/issue:triage 700"] or q["options"][0]["steps"] == ["/issue:triage"]


def test_command_lines_are_secondary_details(world, capsys):  # AC-192.8
    two_drafts(world)
    world.add_issue(700, "An issue")
    for q in world.doc(capsys)["questions"]:
        for o in q["options"]:
            assert not re.match(r"^(/|cplat )", o["label"])
            assert not re.match(r"^(/|cplat )", o["description"])
