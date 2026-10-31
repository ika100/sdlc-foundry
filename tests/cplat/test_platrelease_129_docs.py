"""Spec 129 acceptance tests: the `/platform:release` command and the pointers to it (AC-129.20, AC-129.21).
Text tests on the command files and CONTRIBUTING.md: they assert the key strings, not whole paragraphs."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLATFORM = ROOT / "plugins/platform/commands/release.md"
COMPONENT = ROOT / "plugins/component/commands/release.md"
CONTRIBUTING = ROOT / "CONTRIBUTING.md"


def test_the_platform_release_command_runs_cplat_with_its_arguments():  # AC-129.20
    assert PLATFORM.is_file(), "plugins/platform/commands/release.md is missing"
    text = PLATFORM.read_text()
    assert text.startswith("---\n") and re.search(r"^description: .*release", text.split("---")[1], re.M | re.I)
    assert "cplat platform release $ARGUMENTS" in text
    assert "--version" in text


def test_the_platform_release_command_asks_at_each_stop_and_continues_only_after_a_yes():  # AC-129.20
    assert PLATFORM.is_file(), "plugins/platform/commands/release.md is missing"
    text = PLATFORM.read_text()
    assert "CONFIRM:" in text and "--confirm merge" in text and "--confirm tag" in text
    low = text.lower()
    assert "ask" in low and ("agree" in low or " yes" in low)
    assert "ERROR:" in text                      # on a failure it reports the error line and stops


def test_the_component_release_refusal_names_the_platform_command():  # AC-129.21
    text = COMPONENT.read_text()
    assert "## Release refused" in text
    refusal = text.split("## Release refused", 1)[1].split("```", 1)[0]
    assert "/platform:release" in refusal and "cplat platform release" in refusal
    assert text.index("Release refused") < text.index("## Phase 1")     # it still refuses before anything changes


def test_contributing_names_the_command_as_the_release_procedure():  # AC-129.21
    text = CONTRIBUTING.read_text()
    section = text.split("\n## Releases", 1)[1].split("\n## ", 1)[0]
    assert "/platform:release" in section and "cplat platform release" in section
    assert "/component:release" in section             # still says that one refuses in this repo
