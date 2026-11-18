"""Spec 196 acceptance test: the console's spec panel shows a spec's priority and whether it is still a proposal (AC-196.12).

Contract: design.md "Console spec panel". The rows are the fixture rows of console_support with the two new fields of
`cplat spec list --json`."""
from console_support import console, parse, q, spec_row, specs_json  # noqa: F401  (fixture)


def panel(console, **fields):
    c = console()
    rows = specs_json()
    rows[0] = spec_row("012-checkout", "draft", title="Checkout", priority="P2", **fields)
    c.set("specs:acme/shop-api", rows)
    root, text = c.panel("spec", "012-checkout")
    return root, text


def test_a_proposed_priority_is_shown_as_a_proposal_not_yet_approved_ac_196_12(console):  # AC-196.12
    root, _ = panel(console, priority_state="proposed", priority_reason="P2: cosmetic")
    found = q(root, "p", data_priority="proposed")
    assert len(found) == 1
    line = found[0]
    assert line.text().strip() == "Priority: P2 (P2: cosmetic) - proposed, not yet approved"


def test_a_priority_the_user_chose_or_approved_has_no_proposal_note_ac_196_12(console):  # AC-196.12
    for state, reason in (("changed", "changed by you"), ("approved", "P2: cosmetic"), ("given", "given by you")):
        root, _ = panel(console, priority_state=state, priority_reason=reason)
        found = q(root, "p", data_priority=state)
        assert len(found) == 1
        line = found[0]
        assert line.text().strip() == f"Priority: P2 ({reason})" and "proposed" not in line.text()


def test_a_spec_without_a_priority_line_shows_no_priority_ac_196_12(console):  # AC-196.12
    root, _ = panel(console, priority_state="unset", priority_reason="")
    assert q(root, "p", data_priority=True) == []
    assert "Priority:" not in root.text()


def test_the_priority_line_sits_below_the_title_ac_196_12(console):  # AC-196.12
    _, text = panel(console, priority_state="proposed", priority_reason="P2: cosmetic")
    assert 'data-priority="proposed"' in text
    assert text.index("Checkout") < text.index('data-priority="proposed"')
