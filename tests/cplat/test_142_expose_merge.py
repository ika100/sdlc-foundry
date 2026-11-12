"""Spec 142 (AC-142.1): "make the API reachable" opened the expose PR and then asked whether to merge it (journey 2026-11-05).
An exposure is merged on green CI without a further question; the user can still say not to merge."""
from pathlib import Path

from structure import points_to

SET_REL = "plugins/component/commands/set.md"
SET = (Path(__file__).resolve().parents[2] / SET_REL).read_text()


def test_an_exposure_is_merged_on_green_ci_without_asking_ac_142_1():  # AC-142.1
    step = SET[SET.index("Merge an exposure"):SET.index("4. **")]   # spec 143 put the wait before the report
    assert "`cplat pr wait" in step and "--merge" in step
    assert points_to(SET_REL, "cplat pr wait")
