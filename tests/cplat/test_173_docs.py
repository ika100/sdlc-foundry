"""Spec 173: the guides read without spec numbers (check-docs.py covers every guide in docs/)."""
import importlib.util

from system_fixtures import ROOT

_spec = importlib.util.spec_from_file_location("check_docs", ROOT / "scripts" / "check-docs.py")
check_docs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_docs)

CMDS = check_docs.commands()
PLUGINS, RECIPES = check_docs.live_plugins(CMDS), check_docs.recipes()


def problems_in(tmp_path, monkeypatch, text, name="docs/GUIDE.md"):
    """Run the page check on a page written into a scratch repository root, with the real reader-page rule."""
    page = tmp_path / name
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(text)
    monkeypatch.setattr(check_docs, "ROOT", tmp_path)
    return check_docs.check_page(page, CMDS, PLUGINS, RECIPES)


# ---------------- AC-173.1: every guide is a reader page ----------------

def test_every_guide_in_docs_is_a_reader_page_ac_173_1():  # AC-173.1
    guides = [f for f in check_docs.pages([], PLUGINS) if f.parent == ROOT / "docs"]
    assert {f.name for f in guides} >= {"unattended-delivery.md", "DOMAIN-MODEL.md", "AGENTS.md", "ADOPTING.md", "dispatch.md"}
    for f in guides:
        assert check_docs.is_plain(f) == (f.relative_to(ROOT).as_posix() not in check_docs.RECORDS), f.name


def test_a_spec_number_in_a_guide_fails_ac_173_1(tmp_path, monkeypatch):  # AC-173.1
    out = problems_in(tmp_path, monkeypatch, "# Guide\n\nRuns share one budget (spec 102).\n")
    assert out and out[0].startswith("docs/GUIDE.md:3: 'spec 102' on a reader page"), out


# ---------------- AC-173.2: records and history keep their provenance ----------------

def test_records_history_and_background_may_name_specs_ac_173_2(tmp_path, monkeypatch):  # AC-173.2
    assert check_docs.RECORDS == {"docs/PERFORMANCE.md", "docs/BASELINES.md"}
    assert problems_in(tmp_path, monkeypatch, "# Performance\n\nJourney 6 ran spec 128 (AC-128.3).\n", "docs/PERFORMANCE.md") == []
    history = "# Adopting\n\n## Migrating from 4.x to 5.0\n\n| `cplat smoke`, deploy gate (spec 105) |\n"
    assert problems_in(tmp_path, monkeypatch, history) == []
    background = "# Guide\n\nRuns share one budget.\n\n## Background\n\nSpec 102 introduced it.\n"
    assert problems_in(tmp_path, monkeypatch, background) == []


# ---------------- AC-173.3: the repository's guides pass ----------------

def test_the_guides_name_no_spec_outside_records_and_history_ac_173_3():  # AC-173.3
    guides = [f for f in check_docs.pages([], PLUGINS) if f.parent == ROOT / "docs"]
    found = [p for f in guides for p in check_docs.check_page(f, CMDS, PLUGINS, RECIPES) if "reader page" in p]
    assert found == []
