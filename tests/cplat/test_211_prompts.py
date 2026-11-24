"""Spec 211 acceptance tests: the prompts start unit sessions from the briefing (AC-211.6) and the measurement is written down
(AC-211.10).

Seam: the prompt files of the component plugin read as text, looking for commands and markers (never for sentences: spec 180), and
`rulescheck.check` on this repository for the recorded size. The measurement plan is docs/specs/211-.../measurements.md."""
import re

import core
import rulescheck
from support_211 import PLUGIN, SPEC_DIR

SHIP = PLUGIN / "commands" / "ship.md"
BUILD = PLUGIN / "commands" / "build.md"
MEASUREMENTS = SPEC_DIR / "measurements.md"


def component_files():
    return sorted(p for p in PLUGIN.rglob("*.md"))


def test_no_prompt_finds_its_red_commit_itself_any_more_ac_211_6():  # AC-211.6
    for path in component_files():
        text = path.read_text()
        assert "$RED" not in text and "RED=$(git log" not in text, path.name
    assert rulescheck.check(core.PLATFORM_ROOT).ok            # the prompts stay within their recorded size and register


def test_the_ship_instructions_start_a_unit_session_with_one_call_ac_211_6():  # AC-211.6
    text = SHIP.read_text()
    command = " ".join(["cplat", "component", "ship", "start", "<spec>", "--unit", "<unit>"])      # design section 7: the start call
    assert command in text


def test_the_build_instructions_start_a_unit_session_with_ship_unit_ac_211_6():  # AC-211.6
    text = BUILD.read_text()
    assert "cplat component ship unit" in text  # interface: the command a unit session of a build starts with (design section 7)


NEGATION = r"\b(no|not|never|without|instead of)\b"


def unit_sentences(path):
    """The clauses of a prompt that speak of a unit session (`--unit`), split at full stops and semicolons."""
    return [s for s in re.split(r"[.;]\s+", path.read_text()) if "--unit" in s]


def test_no_prompt_tells_a_unit_session_to_run_shape_first_ac_211_6():  # AC-211.6
    for path in (SHIP, BUILD):
        for sentence in unit_sentences(path):
            if "cplat shape" in sentence:
                assert re.search(NEGATION + r"[^`]{0,30}`cplat shape`", sentence), (path.name, sentence)


def test_no_prompt_tells_a_unit_session_to_read_the_instructions_first_ac_211_6():  # AC-211.6
    """Every sentence of ship.md and build.md that says to read build.md or unit-mode.md, `--unit` or not (a unit of a ship follows
    ship.md's Phase `build`), has to name the unit session as the exception: the briefing replaces that reading (design section 7)."""
    for path in (SHIP, BUILD):
        for sentence in re.split(r"[.;]\s+", path.read_text()):
            reads = re.search(r"\bread\b", sentence, re.I) and re.search(r"(commands/build|references/unit-mode)\.md", sentence)
            if reads:
                assert re.search(r"\bunit\b", sentence) and re.search(NEGATION + r"|\b(except|unless|skip)", sentence), (
                    path.name, sentence)


def test_the_unit_mode_reference_is_still_the_source_both_prompts_name_ac_211_6():  # AC-211.6
    for path in (SHIP, BUILD):
        assert "references/unit-mode.md" in path.read_text(), path.name


def test_the_phase_markers_the_commands_set_are_no_longer_called_by_the_build_instructions_ac_211_6():  # AC-211.6
    text = BUILD.read_text()
    for marker in ("implement", "qa", "verify", "image", "close"):
        assert not re.search(rf"runs phase build:{marker}\b", text), marker
    assert re.search(r"runs phase build:tests\b", text) and re.search(r"runs phase build:pr\b", text)


# ---------------- AC-211.10: the measurement is planned and recorded ----------------

def test_the_measurement_plan_names_journey_23_the_baseline_and_the_thresholds_ac_211_10():  # AC-211.10
    assert MEASUREMENTS.is_file(), "docs/specs/211-unit-sessions-start-with-their/measurements.md"
    text = MEASUREMENTS.read_text()
    for needle in ("journey 23", "journey 22", "cplat platform runs journey measure --steps", "25 %", "10 %",
                   "docs/PERFORMANCE.md"):
        assert needle in text, needle
