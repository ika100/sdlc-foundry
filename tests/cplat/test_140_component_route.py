"""Spec 140: a feature of one component is specified and shipped in its repo (component route), not as a system spec."""
from pathlib import Path

from structure import points_to

ROOT = Path(__file__).resolve().parents[2]
SPEC_REL = "plugins/system/commands/spec.md"
SPEC = (ROOT / SPEC_REL).read_text()


def _step() -> str:
    return SPEC[SPEC.index("One repo"):SPEC.index("`cplat spec new")]


def test_system_spec_offers_the_component_route_for_one_component_ac_140_1():  # AC-140.1
    step = _step()
    assert "AskUserQuestion" in step and "Component route (Recommended)" in step
    assert points_to(SPEC_REL, "/component:spec")


def test_the_component_route_runs_in_the_components_clone_ac_140_2():  # AC-140.2
    step = _step()
    assert "/component:spec" in step and "cd <clone> &&" in step
    assert "/component:ship" in step and points_to(SPEC_REL, "/component:ship")


def test_several_components_or_a_resource_keep_the_system_route_ac_140_3():  # AC-140.3
    step = _step()
    assert "resource" in step and "exposure" in step and "environment" in step
    assert points_to(SPEC_REL, "cplat spec new")


def test_next_steps_recommend_the_route_by_scope_ac_140_4():  # AC-140.4
    newapp = (ROOT / "scripts/cplat/newapp.py").read_text()
    newsvc = (ROOT / "scripts/cplat/newsvc.py").read_text()
    for src in (newapp, newsvc):
        assert "/component:spec" in src and "spans repos" in src and "spec 140" in src
