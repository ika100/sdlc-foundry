"""Spec 176 acceptance tests: the structure of `/issue:triage` (AC-176.2, .3, .4, .8, .15). The prompt hands the work to `cplat`
(batch, overview, confirm, act, publish-specs), asks its questions as choices, starts no fix in the session and keeps the
untrusted-text rule. Structure first. The literals below are names of commands, options and choices of the contract (three words
or fewer, so no sentence pin); the one sentence that code depends on carries `# interface:`."""
import re

import core
import structure

TRIAGE = "plugins/issue/commands/triage.md"


def text():
    return (core.PLATFORM_ROOT / TRIAGE).read_text()


def first(name):
    """Where the prompt first runs `cplat issue triage <name>` (or its short form `<name> …`) in code; -1 when it never does."""
    m = re.search(r"(?:`|^)\s*(?:cplat issue triage )?" + re.escape(name) + r"\b", text(), re.M)
    return m.start() if m else -1


def test_triage_starts_no_fix_in_the_session_for_any_shape_ac_176_8():  # AC-176.8
    assert not structure.points_to(TRIAGE, "/component:fix")
    assert not structure.points_to(TRIAGE, "/system:fix")


def test_triage_hands_the_fix_to_the_dispatcher_through_the_triage_comment_ac_176_8():  # AC-176.8
    body = text()
    assert "Triage:" in body                          # the comment prefix the dispatcher reads
    assert "cplat dispatch status" in body and "Board" in body


def test_triage_runs_the_cplat_steps_in_order_ac_176_2():  # AC-176.2
    positions = [first(n) for n in ("batch", "overview", "confirm", "act")]
    assert -1 not in positions and positions == sorted(positions)


def test_triage_prints_the_overview_before_it_asks_anything_ac_176_2():  # AC-176.2
    body = text()
    assert "AskUserQuestion" in body
    assert first("overview") != -1 and first("overview") < body.index("AskUserQuestion")


def test_triage_asks_questions_as_choices_in_pages_and_confirms_with_three_choices_ac_176_3():  # AC-176.3
    body = text()
    assert "Recommended" in body and "<n> of <m>" in body
    for choice in ("OK, do it", "Change one", "Cancel"):
        assert choice in body, choice
    # `Change one` picks a row and its class or action, then the confirmation is shown again (the confirm step re-runs)
    after = body[body.index("Change one"):]
    assert "confirm" in after[:after.index("Cancel")] and "row" in after[:after.index("Cancel")]


def test_triage_applies_only_confirmed_rows_and_can_show_a_row_before_ac_176_3():  # AC-176.3
    body = text()
    assert "--rows" in body and "--show" in body
    assert first("confirm") != -1 and first("act") != -1


def test_triage_accepts_a_typed_answer_in_place_of_a_choice_ac_176_3():  # AC-176.3
    body = text()
    typed = body.lower().find("typed")
    assert typed != -1 and 0 < first("confirm") < typed < first("act")     # the typed-answer path sits in the confirmation step
    assert "--rows" in body and "--show" in body


def test_triage_publishes_new_specs_on_one_branch_before_act_ac_176_4():  # AC-176.4
    assert first("publish-specs") != -1 and first("publish-specs") < first("act")
    assert "docs/triage-" in text()


def test_triage_ends_with_the_hand_over_choice_and_keeps_the_explore_hand_off_ac_176_15():  # AC-176.15
    body = text()
    assert first("act") > 0 and body.lower().rfind("choice") > first("act")
    assert structure.points_to(TRIAGE, "/component:explore") and structure.points_to(TRIAGE, "/system:explore")


def test_triage_keeps_the_untrusted_text_rule_and_never_closes_ac_176_8():  # AC-176.8
    body = text()
    assert "Hard rule" in body and "untrusted" in body.lower()
    assert "never follow instructions" in body.lower()
    assert "Never close an issue" in body             # interface: the hard rule that spec 177 changes
