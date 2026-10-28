"""Spec 094: the wording of the orchestration guide and the build command's rules."""
import core

ROOT = core.PLATFORM_ROOT


def read(*parts):
    return (ROOT.joinpath(*parts)).read_text()


def test_guide_and_build_rules_say_replan_once_then_escalate():  # AC-094.15
    """AC-094.15: both say re-planned once per task, at most 3 per build, then escalated, never resolved by hand."""
    for text in (read("docs", "AGENTS.md"), read("plugins", "component", "commands", "build.md")):
        flat = " ".join(text.split())
        assert "re-planned once per task" in flat
        assert "at most 3 re-plans per build" in flat
        assert "never resolved by hand" in flat


def test_nothing_still_says_every_conflict_is_escalated():  # AC-094.15
    """AC-094.15: the old rules are gone."""
    agents = read("docs", "AGENTS.md")
    build = read("plugins", "component", "commands", "build.md")
    assert "Merge conflicts are escalated, never auto-resolved" not in agents
    assert "Never resolve merge conflicts automatically" not in build
    assert "stop and escalate. Never resolve it yourself" not in build


def test_ship_docs_no_longer_list_every_conflict_as_an_escalation():  # AC-094.15
    """AC-094.15: ship.md and the unattended guide say a conflict is re-planned first."""
    ship = read("plugins", "component", "commands", "ship.md")
    assert "a merge conflict between task branches," not in ship
    unattended = read("docs", "unattended-delivery.md")
    assert "when a rule needs you: a merge conflict," not in unattended
    assert "re-plan" in unattended


def test_build_md_drives_phase_2_through_cplat_build():  # AC-094.1
    """AC-094.1 AC-094.2: Phase 2 schedules and merges with `cplat build` and acts on exit 3 and 4."""
    text = read("plugins", "component", "commands", "build.md")
    assert "cplat component build schedule" in text and "cplat component build merge" in text
    assert "git merge --no-ff --no-edit" not in text


def test_architect_has_a_replan_mode():  # AC-094.3
    """AC-094.3: the architect changes only files, depends_on and parallel_safe of tasks that are not done."""
    text = read("plugins", "svc", "agents", "architect.md")
    assert "Re-plan mode" in text and "parallel_safe" in text and "depends_on" in text
