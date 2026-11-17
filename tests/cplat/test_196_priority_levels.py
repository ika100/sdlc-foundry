"""Spec 196 acceptance tests: the one priority scale `scripts/cplat/priority.py` (design.md "priority.py (shared)").

The module is imported inside each test, so that a missing module fails the test and not the collection."""
import importlib

import pytest


def pri():
    return importlib.import_module("priority")


def test_the_three_levels_come_in_urgency_order_with_their_definitions_ac_196_2():  # AC-196.2
    p = pri()
    assert list(p.LEVELS) == ["P0", "P1", "P2"]
    assert p.LEVELS["P0"]["definition"] == "an outage, data loss, a security problem, or something that blocks all other work"
    assert p.LEVELS["P1"]["definition"] == "a normal bug or feature; the fallback when nothing signals urgency"
    assert p.LEVELS["P2"]["definition"] == "cosmetic, a convenience, or something with an easy workaround"
    assert p.LEVELS["P0"]["phrases"] == ["outage", "data loss", "security problem", "blocks all other work"]
    assert p.LEVELS["P2"]["phrases"] == ["cosmetic", "convenience", "easy workaround"]
    assert p.FALLBACK_REASON == "P1: normal bug or feature"


@pytest.mark.parametrize("level,reason", [("P0", "P0: data loss"), ("P0", "P0: outage"), ("P2", "P2: easy workaround"),
                                          ("P1", "P1: normal bug or feature"), ("P2", "P2: cosmetic")])
def test_a_reason_naming_a_phrase_of_its_level_is_a_proposal_reason_ac_196_2(level, reason):  # AC-196.2
    assert pri().proposal_reason_ok(level, reason) is True


@pytest.mark.parametrize("level,reason", [("P0", "P2: data loss"), ("P0", "P0: it hurts a lot"), ("P0", "data loss"),
                                          ("P1", "P1: data loss"), ("P2", "P2: cosmetic, mostly"), ("P2", "changed by you"),
                                          ("P0", "set on the issue")])
def test_any_other_wording_is_no_proposal_reason_ac_196_2(level, reason):  # AC-196.2
    assert pri().proposal_reason_ok(level, reason) is False


def test_every_proposal_reason_fits_60_characters_ac_196_1():  # AC-196.1
    p = pri()
    for level, spec in p.LEVELS.items():
        for phrase in spec["phrases"]:
            assert len(f"{level}: {phrase}") <= 60


def test_the_most_urgent_label_wins_and_other_labels_are_ignored_ac_196_3():  # AC-196.3
    p = pri()
    assert p.most_urgent(["p2", "p0"]) == "P0"
    assert p.most_urgent(["bug", "p1", "p2"]) == "P1"
    assert p.most_urgent(["p2"]) == "P2"
    assert p.most_urgent(["bug", "triaged"]) is None
    assert p.most_urgent([]) is None


def test_label_and_level_map_both_ways_ac_196_5():  # AC-196.5
    p = pri()
    assert [p.label_of(x) for x in ("P0", "P1", "P2")] == ["p0", "p1", "p2"]
    assert [p.level_of(x) for x in ("p0", "p1", "p2")] == ["P0", "P1", "P2"]


def test_the_batch_list_has_level_definition_and_phrases_in_urgency_order_ac_196_1():  # AC-196.1
    p = pri()
    rows = p.levels_json()
    assert [r["level"] for r in rows] == ["P0", "P1", "P2"]
    assert all(set(r) == {"level", "definition", "phrases"} for r in rows)
    assert rows[0]["phrases"] == p.LEVELS["P0"]["phrases"] and rows[2]["definition"] == p.LEVELS["P2"]["definition"]


def test_the_skeleton_comment_is_one_html_comment_line_with_the_definitions_ac_196_10():  # AC-196.10
    p = pri()
    text = p.skeleton_comment()
    assert "\n" not in text.strip() and text.startswith("<!--") and text.rstrip().endswith("-->")
    for level, spec in p.LEVELS.items():
        assert level in text and spec["definition"] in text
        assert all(phrase in text for phrase in spec["phrases"])
