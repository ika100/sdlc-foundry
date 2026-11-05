"""Spec 140: a feature of one component is specified and shipped in its repo (component route), not as a system spec."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = (ROOT / "plugins/system/commands/spec.md").read_text()


def test_system_spec_offers_the_component_route_for_one_component_ac_140_1():  # AC-140.1
    step = SPEC[SPEC.index("0. **One repo is enough?**"):SPEC.index("1. `cplat spec new")]
    assert "names exactly one component" in step and "no resource, exposure or environment change" in step
    assert "AskUserQuestion" in step and "Component route (Recommended)" in step and "ask once" in step


def test_the_component_route_runs_in_the_components_clone_ac_140_2():  # AC-140.2
    step = SPEC[SPEC.index("0. **One repo is enough?**"):SPEC.index("1. `cplat spec new")]
    assert "/component:spec <the description>" in step and "cd <clone> &&" in step
    assert "/component:ship <id>" in step and "no system spec, plan or plan PR" in step


def test_several_components_or_a_resource_keep_the_system_route_ac_140_3():  # AC-140.3
    step = SPEC[SPEC.index("0. **One repo is enough?**"):SPEC.index("1. `cplat spec new")]
    assert "Two or more components, or any resource, exposure or environment change: continue below without asking" in step


def test_next_steps_recommend_the_route_by_scope_ac_140_4():  # AC-140.4
    newapp = (ROOT / "scripts/cplat/newapp.py").read_text()
    newsvc = (ROOT / "scripts/cplat/newsvc.py").read_text()
    for src in (newapp, newsvc):
        assert "/component:spec" in src and "spans repos" in src and "spec 140" in src
