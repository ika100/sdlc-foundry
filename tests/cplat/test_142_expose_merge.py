"""Spec 142 (AC-142.1): "make the API reachable" opened the expose PR and then asked whether to merge it (journey 2026-11-05).
An exposure is merged on green CI without a further question; the user can still say not to merge."""
from pathlib import Path

SET = (Path(__file__).resolve().parents[2] / "plugins/component/commands/set.md").read_text()


def test_an_exposure_is_merged_on_green_ci_without_asking_ac_142_1():  # AC-142.1
    step = SET[SET.index("3. **Merge an exposure**"):SET.index("4. **Report**")]
    assert "`cplat pr wait <pr-url> --merge`" in step and "do not ask again" in step
    assert "unless the user said not to merge" in step and "Other changes: leave the PR for review" in step
