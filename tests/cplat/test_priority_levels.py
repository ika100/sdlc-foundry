"""Unit tests for scripts/cplat/priority.py (spec 196)."""
import priority


def test_levels_json_copies_phrases():
    rows = priority.levels_json()
    rows[0]["phrases"].append("x")
    assert "x" not in priority.LEVELS["P0"]["phrases"]


def test_reason_longer_than_60_is_refused():
    assert not priority.proposal_reason_ok("P0", "P0: outage" + " " * 60)


def test_unknown_level_is_refused():
    assert not priority.proposal_reason_ok("P9", "P9: outage")


def test_most_urgent_picks_p0_over_p1_and_p2():
    assert priority.most_urgent(["p2", "p1", "p0"]) == "P0"
    assert priority.most_urgent(["P0"]) is None


def test_skeleton_comment_renders_phrases_per_level():
    text = priority.skeleton_comment()
    assert "P2: cosmetic, convenience, easy workaround" in text
    assert text.endswith(" -->")
