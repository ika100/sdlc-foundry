"""Spec 122: the console explains itself — one line under each place, a help panel per place, and only real commands."""
import re
from pathlib import Path

import stages
from console import help as help_text
from console_support import q

ROOT = Path(__file__).resolve().parents[2]
COMMAND = re.compile(r"/([a-z-]+):([a-z-]+)")


def real_commands():
    return {(p.parent.parent.name, p.stem) for p in ROOT.glob("plugins/*/commands/*.md")}


def test_every_place_has_its_one_line_answer_and_a_help_link(console):
    c = console()
    for place in ("inbox", "board", "system"):
        root, text = c.page(f"/{place}")
        assert help_text.INTRO[place] in text
        assert q(root, "a", href=f"/panel/help/{place}")


def test_the_help_panel_explains_the_place_the_stages_and_the_keys(console):
    c = console()
    for place in ("inbox", "board", "system"):
        root, text = c.panel("help", place)
        assert q(root, "aside", data_panel=True)
        assert all(step.replace("'", "&#x27;") in text or step in text for step in help_text.STEPS[place][:1])
        for stage in stages.STAGES:
            assert f'data-stage="{stage}"' in text
        assert "⌘K" in text and "/platform:doctor" in text


def test_an_unknown_help_page_is_404(console):
    st, _ = console().get("/panel/help/nope")
    assert st == 404


def test_the_help_and_the_stage_explanations_name_only_real_commands():
    texts = [str(stages.explain(s)) for s in stages.STAGES] + [str(help_text.STEPS), str(help_text.panel_help.__code__.co_consts)]
    named = {m for t in texts for m in COMMAND.findall(t)} - {("svc", "tester"), ("svc", "reviewer"), ("svc", "architect"),
                                                              ("svc", "product-manager"), ("shared", "quality"),
                                                              ("shared", "security")}
    missing = named - real_commands()
    assert not missing, missing
