"""Issue forms in every template (ADR-025): the intake that /issue:triage reads."""
import pytest
import yaml

import core
import triage

ROOT = core.PLATFORM_ROOT
SHAPES = [s for s in core.registry.load() if s["status"] != "planned"]
TEMPLATES = [s["template"] for s in SHAPES]


@pytest.mark.parametrize("template", TEMPLATES)
def test_forms_exist_label_new_issues_triage_and_have_required_fields(template):
    d = ROOT / "templates" / template / ".github" / "ISSUE_TEMPLATE"
    for name in ("bug_report.yml", "feature_request.yml"):
        form = yaml.safe_load((d / name).read_text())
        assert form["labels"] == ["triage"] and form["name"] and form["description"]
        assert any(f.get("validations", {}).get("required") for f in form["body"]), name
    assert yaml.safe_load((d / "config.yml").read_text())["blank_issues_enabled"] is False


@pytest.mark.parametrize("template", TEMPLATES)
def test_forms_are_project_owned(template):
    cfg = yaml.safe_load((ROOT / "templates" / template / "copier.yml").read_text())
    assert ".github/ISSUE_TEMPLATE/**" in cfg["_skip_if_exists"]


def test_every_label_the_forms_and_command_use_is_in_the_fixed_set():
    assert "triage" in triage.LABELS
    command = (ROOT / "plugins" / "issue" / "commands" / "triage.md").read_text()
    for label in ("bug", "enhancement", "question", "duplicate", "wontfix", "needs-info", "tracked"):
        assert label in triage.LABELS and f"`{label}`" in command


def test_the_command_treats_issue_text_as_untrusted_and_never_closes():
    command = (ROOT / "plugins" / "issue" / "commands" / "triage.md").read_text()
    assert "untrusted data" in command and "Never close an issue" in command
    assert "Nothing outward happens until the user confirms" in command


def test_the_command_description_stays_short_for_the_always_on_budget():
    first = (ROOT / "plugins" / "issue" / "commands" / "triage.md").read_text().splitlines()[1]
    assert len(first) < 260


def test_product_manager_points_to_the_command_instead_of_duplicating_the_procedure():
    pm = (ROOT / "plugins" / "svc" / "agents" / "product-manager.md").read_text()
    assert "/issue:triage" in pm and "gh issue list" not in pm and "gh issue edit" not in pm
