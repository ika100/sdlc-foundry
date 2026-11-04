"""The console polish: readable card titles, rounded amounts, state tones, named sources and the Inbox before its first read."""
from types import SimpleNamespace

import pytest

from console import board, inbox
from console.html import money, source_label, unavailable


@pytest.mark.parametrize("slug, words", [
    ("013-ai-ops-serves-as-the-platform-s-autonomy", "Ai ops serves as the platform's autonomy"),
    ("001-stock-move", "Stock move"),
    ("#12", ""),
    ("shop-api sha-1234567", ""),
    ("20261027T071349Z-1a6f269d", ""),
])
def test_a_spec_slug_reads_as_words(slug, words):
    assert board.readable(slug) == words


@pytest.mark.parametrize("value, shown", [(33.7487, "33.75"), (60, "60"), (170.0, "170"), (0.5, "0.5"), (None, "None")])
def test_amounts_show_at_most_two_decimals(value, shown):
    assert money(value) == shown


@pytest.mark.parametrize("item, tone", [
    ({"stopped": True, "state": "Stopped", "stage": "Build"}, "stopped"),
    ({"stopped": False, "state": "Running", "stage": "Build"}, "running"),
    ({"stopped": False, "state": "Not started", "stage": "Build"}, "idle"),
    ({"stopped": False, "state": "2 open questions", "stage": "Spec"}, "decide"),
    ({"stopped": False, "state": "Verified in staging, waits to be promoted", "stage": "Prod"}, "decide"),
])
def test_a_card_tone_follows_its_state_not_its_column(item, tone):
    assert board.tone(item) == tone


def test_an_unavailable_part_names_its_source_in_words():
    part = unavailable("needs", "2026-11-04T10:05:55Z", "timed out after 60 s")
    assert "The list of open decisions is not available" in part and 'data-source="needs"' in part
    assert source_label("specs:ika100/ai-ops") == "The specs of ika100/ai-ops"
    assert source_label("cluster:prod") == "cluster:prod"


def _ctx(source):
    return SimpleNamespace(source=lambda name: source if name == "needs" else None,
                           data=lambda name: None, state=lambda: {"read_at": None, "badge": 0})


def test_the_inbox_does_not_claim_nothing_waits_before_it_read_the_decisions():
    html = inbox.page(_ctx(SimpleNamespace(data=None, read_at=None, error=None, unavailable_since=None)), {})
    assert "Reading the open decisions" in html and "Nothing waits for you" not in html


def test_the_inbox_says_nothing_waits_once_it_read_an_empty_list():
    src = SimpleNamespace(data={"items": []}, read_at="2026-11-04T10:00:00Z", error=None, unavailable_since=None)
    ctx = _ctx(src)
    ctx.data = lambda name: {"items": []} if name == "needs" else None
    assert "Nothing waits for you" in inbox.page(ctx, {})


# ---------------- the glossary: one text per term, for the ? tips and the How it works page ----------------

import re
from pathlib import Path

from console import glossary
from console_support import q

CONSOLE = Path(__file__).resolve().parents[2] / "scripts" / "cplat" / "console"


def test_every_tip_and_legend_names_a_term_of_the_glossary():
    used = set()
    for path in CONSOLE.glob("*.py"):
        text = path.read_text()
        used |= set(re.findall(r"""glossary\.tip\(["'](\w+)["']""", text))
        for keys in re.findall(r"glossary\.legend\(\(([^)]*)\)", text):
            used |= set(re.findall(r"""["'](\w+)["']""", keys))
    assert used and used <= set(glossary.TERMS), used - set(glossary.TERMS)


def test_every_term_is_on_the_how_it_works_page_once():
    listed = [k for _, _, _, keys in glossary.SECTIONS for k in keys]
    assert sorted(listed) == sorted(glossary.TERMS) and len(listed) == len(set(listed))


def test_a_tip_is_a_labelled_button_with_its_text_and_a_link_to_the_term():
    html = glossary.tip("verified")
    assert 'aria-label="What is verified?"' in html and 'role="tooltip"' in html and 'href="/help#t-verified"' in html
    with pytest.raises(KeyError):
        glossary.tip("no-such-term")


def test_how_it_works_lists_the_eight_stages_and_anchors_every_term(console):
    root, text = console().page("/help")
    assert [n.attrs["data-stage"] for n in q(root, None, data_stage=True) if any(a.tag == "ol" for a in n.ancestors())] == \
        ["Issue", "Spec", "Plan", "Build", "Land", "Dev", "Staging", "Prod"]
    for key in glossary.TERMS:
        assert q(root, None, id=f"t-{key}"), key


@pytest.mark.parametrize("path, keys", [
    ("/inbox", {"decision", "waiting", "read_at"}),
    ("/board", {"running", "stopped", "waits", "not_started", "decision_stage", "budget"}),
    ("/system", {"promote_rule", "policy", "verified", "not_verified", "model"}),
])
def test_each_page_explains_its_terms_where_they_appear(console, path, keys):
    root, _ = console().page(path)
    assert keys <= {n.attrs["data-tip"] for n in q(root, None, data_tip=True)}


def test_the_menu_links_how_it_works(console):
    root, _ = console().page("/inbox")
    assert any(a.attrs.get("href") == "/help" for a in q(root, "a"))
