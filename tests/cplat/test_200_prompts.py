"""Spec 200 acceptance tests: the ship instructions hand off, relay and report (AC-200.1, AC-200.2, AC-200.5, AC-200.6, AC-200.7).

By structure, as spec 168 asks: a prompt names the `cplat` flags and the output words it reacts to, the hand-off reference exists
and covers each result of the wait, and the register files `docs/rules/<prompt path without .md>.yml` hold entries (source `spec 200`)
that quote the prompt. No sentence is pinned.
"""
import pytest

from prompts186_support import ROOT, collapsed, entries, prompt, sourced
from ship200_support import WAIT_COMMAND

SHIP = "plugins/component/commands/ship.md"
HANDOFF = "plugins/component/references/ship-handoff.md"
FINISH = "plugins/component/references/ship-finish.md"
LAND_RED = "plugins/component/references/ship-land-red.md"
BUILD = "plugins/component/commands/build.md"
CLASSES = {"hard", "practice", "experience"}


def section(text, start, end):
    i = text.index(start)
    return text[i:text.index(end, i + 1)] if end in text[i + 1:] else text[i:]


def test_ship_hands_off_unless_here_or_unit_ac_200_1():  # AC-200.1
    text = prompt(SHIP)
    head = text.split("---")[1]                                         # the frontmatter
    assert "--detach" in text and "--here" in text and "--unit" in text
    assert "--here" in head                                              # the usage line names the opt-out
    assert any("--detach" in ln and "ship start" in ln for ln in text.splitlines())


def test_ship_reads_the_hand_off_reference_on_a_headless_pid_line_ac_200_2():  # AC-200.2
    text = prompt(SHIP)
    assert "ship-handoff.md" in text and "headless: pid" in text
    assert (ROOT / HANDOFF).is_file()
    assert "references/ship-handoff.md" in collapsed(text)


def test_ship_applies_an_answer_from_the_shipping_session_ac_200_5():  # AC-200.5
    text = prompt(SHIP)
    assert "shipping session:" in text and "system ship:" in text      # both answer lines are applied the same way


def test_the_reference_covers_every_result_of_the_wait_ac_200_5():  # AC-200.5
    text = prompt(HANDOFF)
    for word in (WAIT_COMMAND, "WAIT:", "TIMEOUT:", "ENDED:", "REACHED:", "ESCALATED:", "--detach", "--answer"):
        assert word in text, word
    for word in ("subagent", "suggested", "decision", "cause", "Finish"):
        assert word in text, word


def test_the_reference_resumes_with_an_answer_and_reports_other_causes_ac_200_5():  # AC-200.5
    text = collapsed(prompt(HANDOFF))
    for cause in ("code", "environment", "platform", "unknown"):
        assert cause in text, cause                                    # the other causes are named: shown, nothing resumed


def test_the_reference_has_register_entries_that_quote_it_ac_200_5():  # AC-200.5
    body = collapsed(prompt(HANDOFF))
    found = entries(HANDOFF)
    assert found and sourced(HANDOFF, "spec 200")
    for e in found:
        assert e.get("class") in CLASSES and e.get("id") and collapsed(str(e.get("text"))) in body, e
    assert len({e["id"] for e in found}) == len(found)


def test_the_ship_register_holds_the_shipping_session_rule_ac_200_5():  # AC-200.5
    body = collapsed(prompt(SHIP))
    hits = [e for e in entries(SHIP) if "shipping session" in str(e.get("text")) and collapsed(str(e["text"])) in body]
    assert hits and all(e.get("class") in CLASSES for e in hits)


def test_the_report_comes_from_ship_status_ac_200_6():  # AC-200.6
    finish = prompt(FINISH)
    assert "report:" in finish and "ship status" in finish
    handoff = prompt(HANDOFF)
    assert "REACHED:" in handoff and "ship-finish.md" in prompt(SHIP) + handoff


@pytest.mark.parametrize("path", [LAND_RED, SHIP])
def test_every_fix_round_runs_the_test_diff_and_settles_a_helper_without_asking_ac_200_7(path):  # AC-200.7
    text = prompt(path)
    if path == SHIP:
        text = section(text, "## Phase `pr`", "## Phase `land`")
    assert "cplat spec test-diff" in text and "test helper" in text
    assert "build-tighten.md" in text


def test_the_land_red_reference_escalates_a_changed_test_as_a_decision_ac_200_7():  # AC-200.7
    text = collapsed(prompt(LAND_RED))
    assert "--task" in text and "decision" in text
    assert sourced(LAND_RED, "spec 200")


def test_the_verification_fix_rounds_of_the_build_run_the_test_diff_ac_200_7():  # AC-200.7
    phase = section(prompt(BUILD), "## Phase 4", "## Phase 5")
    assert "cplat spec test-diff" in phase and "test helper" in phase
