"""Spec 134: the contributing guide, ADR-080 and the changelog describe which e2e a pull request runs (AC-134.9)."""
import re

from system_fixtures import ROOT


def test_contributing_states_the_e2e_rules_ac_134_9():  # AC-134.9
    text = (ROOT / "CONTRIBUTING.md").read_text()
    assert "scripts/e2e-scope.py" in text
    assert "E2E_PART=<part> bash tests/e2e/run.sh" in text
    assert re.search(r"three parallel parts", text) and re.search(r"nightly", text)
    assert re.search(r"upgrade e2e[^.]*pull request's own (diff|changes)", text)
    assert "scripts/cplat/**" not in text.split("## CI cost", 1)[1].split("\n## ", 1)[0]


def test_adr_080_is_written_and_indexed_ac_134_9():  # AC-134.9
    adr = ROOT / "docs" / "adr" / "080-a-pull-request-runs-only-the-e2e-it-needs.md"
    assert adr.is_file() and "spec 134" in adr.read_text()
    assert "(080-a-pull-request-runs-only-the-e2e-it-needs.md)" in (ROOT / "docs" / "adr" / "README.md").read_text()


def test_the_changelog_lists_the_change_ac_134_9():  # AC-134.9
    import release_support
    _, text = release_support.entry(r"\(#281\)")      # any section or fragment: the release moves it (#321)
    assert "e2e" in text
