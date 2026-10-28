"""Spec 126 AC-126.15 is a measurement of the first 7 days after the release; the number goes in measurements.md (as spec 112 did).

What the tests can check is that the measurement is written down the way the criterion asks: the command and the four checks.
"""
import core

MEASUREMENTS = core.PLATFORM_ROOT / "docs" / "specs" / "126-unattended-runs-stop-wasting-turns-and" / "measurements.md"


def text():
    assert MEASUREMENTS.is_file(), f"{MEASUREMENTS} is missing"
    return MEASUREMENTS.read_text()


def test_ac_126_15_measurements_md_names_the_report_command():  # AC-126.15
    assert "cplat platform runs report --since 7" in text()


def test_ac_126_15_measurements_md_has_one_section_per_check():  # AC-126.15
    t = text().lower()
    assert "gave up after" in t                                   # no escalation reads it
    assert "non-owning session" in t or "did not start or resume" in t   # no escalation records a session that did not own the run
    assert "environment" in t and "088.16" in t                    # environment only with a matched rule
    assert "pr-title" in t and "spec-required" in t                # no red check on a PR of a platform command
