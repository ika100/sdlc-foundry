"""Spec 122 acceptance tests: one stage vocabulary (AC-122.32), the Board's columns (AC-122.10) and the stage explanations (AC-122.12).

Contract: design.md "Stage vocabulary". Pure functions of scripts/cplat/stages.py."""
import pytest

from console_support import STAGES


def stages():
    import stages as m
    return m


def test_the_eight_stages_and_the_decision_columns_ac_122_32():  # AC-122.32
    s = stages()
    assert tuple(s.STAGES) == STAGES
    assert set(s.DECISION) == {"Spec", "Build", "Prod"}


@pytest.mark.parametrize("status, run, want", [
    ("draft", None, "Spec"),
    ("approved", None, "Plan"),
    ("building", None, "Build"),
    ("approved", {"phase": "plan", "stopped_in": None}, "Plan"),
    ("building", {"phase": "build", "stopped_in": None}, "Build"),
    ("building", {"phase": "pr", "stopped_in": None}, "Land"),
    ("building", {"phase": "land", "stopped_in": None}, "Land"),
    ("building", {"phase": "deploy", "stopped_in": None}, "Dev"),
    ("building", {"phase": "staging", "stopped_in": None}, "Staging"),
])
def test_a_spec_is_named_by_its_stage_and_nothing_else_ac_122_32(status, run, want):  # AC-122.32
    assert stages().stage_of_spec(status, run) == want


def test_a_finished_spec_has_no_column_ac_122_32():  # AC-122.32
    s = stages()
    assert s.stage_of_spec("done", None) is None and s.stage_of_spec("superseded", None) is None


@pytest.mark.parametrize("phase, want", [("plan", "Plan"), ("build", "Build"), ("pr", "Land"), ("land", "Land"), ("deploy", "Dev"),
                                          ("staging", "Staging")])
def test_a_run_phase_maps_to_a_stage_ac_122_32(phase, want):  # AC-122.32
    assert stages().stage_of_run(phase, None) == (want, False)


def test_an_escalated_run_stays_in_the_stage_where_it_stopped_ac_122_32():  # AC-122.32
    s = stages()
    assert s.stage_of_run("escalated", "build") == ("Build", True)
    assert s.stage_of_run("escalated", "land") == ("Land", True)
    with pytest.raises(ValueError):
        s.stage_of_run("nonsense", None)


def test_issues_and_releases_have_their_stage_ac_122_32():  # AC-122.32
    s = stages()
    assert s.stage_of_issue({"number": 5, "state": "OPEN", "labels": [{"name": "bug"}]}) == "Issue"
    assert s.stage_of_issue({"number": 5, "state": "OPEN", "labels": [{"name": "tracked"}]}) is None
    assert s.stage_of_issue({"number": 5, "state": "CLOSED", "labels": []}) is None
    assert s.stage_of_release({"component": "shop-api", "version": "1.4.0", "verified": True, "running_in_prod": False}) == "Prod"
    assert s.stage_of_release({"component": "shop-api", "version": "1.4.0", "verified": True, "running_in_prod": True}) is None


def test_a_system_spec_takes_the_earliest_stage_of_its_slices_ac_122_32():  # AC-122.32
    s = stages()
    assert s.earliest(["Land", "Build", "Dev"]) == "Build"
    assert s.earliest(["Prod", "Spec"]) == "Spec"


def test_every_mapping_returns_only_names_from_the_vocabulary_ac_122_32():  # AC-122.32
    s = stages()
    names = {s.stage_of_spec(st, r) for st in ("draft", "approved", "building") for r in (None, {"phase": "deploy", "stopped_in": None})}
    assert names <= set(STAGES)


def test_each_stage_is_explained_ac_122_12():  # AC-122.12
    s = stages()
    for name in STAGES:
        e = s.explain(name)
        assert e["what"] and isinstance(e["agents"], list) and isinstance(e["commands"], list)
        assert "decision" in e
    assert any("coder" in a for a in s.explain("Build")["agents"])
    assert any(c.startswith("/component:build") or c.startswith("/component:ship") for c in s.explain("Build")["commands"])


def test_only_decision_columns_say_what_the_user_decides_ac_122_10():  # AC-122.10
    s = stages()
    for name in STAGES:
        d = s.explain(name)["decision"]
        assert bool(d) == (name in {"Spec", "Build", "Prod"}), name
