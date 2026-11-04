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
