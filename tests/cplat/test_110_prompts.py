"""Spec 110 acceptance tests, AC-110.11 (and the prompt side of AC-110.4): the planner agent and ADR-011 show the `### Rules`
part, the machine-readable `errors:` block and the worked example of design 1 (a title with a maximum length and a status
with allowed values). The tests read the structure (headings, fenced yaml blocks, keys, rule kinds) and run the example through
plan-check; they pin no prompt sentence, only short names (headings, kinds, the copy's file name)."""
import re

import pytest
import yaml
from support_110 import ROOT, error_lines, plan_text, validate, world

PLANNER = ROOT / "plugins" / "system" / "agents" / "planner.md"
ADR = ROOT / "docs" / "adr" / "011-multi-repo-plan-format.md"
FROM_PLAN = ROOT / "plugins" / "component" / "references" / "spec-from-plan.md"
FENCE = re.compile(r"^```ya?ml\n(.*?)^```", re.M | re.S)


def blocks(text, key):
    found = []
    for raw in FENCE.findall(text):
        try:
            doc = yaml.safe_load(raw)
        except yaml.YAMLError:
            continue
        if isinstance(doc, dict) and key in doc:
            found.append(doc[key])
    return found


def parts(path):
    text = path.read_text()
    if path == ADR:
        assert "## Amendment (spec 110)" in text, "ADR-011 has no `## Amendment (spec 110)` section"
        text = text[text.index("## Amendment (spec 110)"):]
    rules, errors = blocks(text, "rules"), blocks(text, "errors")
    assert rules, f"{path.name} shows no yaml block with `rules:`"
    assert errors, f"{path.name} shows no yaml block with `errors:`"
    return text, rules[0], errors[0]


@pytest.mark.parametrize("path", [PLANNER, ADR], ids=["planner", "adr-011"])
def test_the_format_shows_the_rules_part_next_to_errors_and_timeouts_ac_110_11(path):  # AC-110.11
    text, _, _ = parts(path)
    headings = re.findall(r"^###\s+(Rules|Errors|Timeouts)\s*$", text, re.M)
    order = [headings.index(h) for h in ("Rules", "Errors", "Timeouts")]
    assert order == sorted(order), headings


@pytest.mark.parametrize("path", [PLANNER, ADR], ids=["planner", "adr-011"])
def test_the_worked_example_has_a_title_maximum_and_status_allowed_values_ac_110_11(path):  # AC-110.11
    _, rules, _ = parts(path)
    kinds = {(r["field"], r["kind"]) for r in rules}
    assert ("title", "max_length") in kinds and ("status", "allowed") in kinds, kinds
    title = next(r for r in rules if (r["field"], r["kind"]) == ("title", "max_length"))
    status = next(r for r in rules if (r["field"], r["kind"]) == ("status", "allowed"))
    assert isinstance(title["value"], int) and isinstance(status["value"], list) and len(status["value"]) >= 2
    for rule in rules:                                    # every entry carries the keys of design 1
        assert {"id", "endpoint", "field", "kind", "value", "provider", "consumers"} <= set(rule), rule


@pytest.mark.parametrize("path", [PLANNER, ADR], ids=["planner", "adr-011"])
def test_the_machine_readable_error_contract_is_shown_ac_110_11(path):  # AC-110.11
    _, _, errors = parts(path)
    assert isinstance(errors["status"], int) and 400 <= errors["status"] <= 599
    assert {"field", "rule", "message"} <= set(errors["body"]), errors["body"]
    assert errors["unlisted"]["message"]


@pytest.mark.parametrize("path", [PLANNER, ADR], ids=["planner", "adr-011"])
def test_the_worked_example_passes_plan_check_ac_110_11(tmp_path, path):  # AC-110.11
    _, rules, errors = parts(path)
    provider = rules[0]["provider"]
    consumers = sorted({c for r in rules for c in r["consumers"]})
    repos = "".join(f"  - {{id: {rid}, shape: {shape}, summary: {rid}, acs: [{ac}], depends_on: [], done: false}}\n"
                    for rid, shape, ac in [(provider, "service-python", "AC-003.1"), (consumers[0], "web-nextjs", "AC-003.2")]
                    + [(c, "web-nextjs", "") for c in consumers[1:]])
    head = plan_text().split("repos:\n")[0] + "repos:\n" + repos + "---\n"
    contract = ("\n## Contract\n\n### Rules\n\n```yaml\n" + yaml.safe_dump({"rules": rules}, sort_keys=False) + "```\n\n### Errors\n\n"
                "```yaml\n" + yaml.safe_dump({"errors": errors}, sort_keys=False) + "```\n\n### Timeouts\n\n3 s\n")
    root = world(tmp_path)
    proc = validate(root, head + contract)
    assert proc.returncode == 0 and not error_lines(proc), proc.stderr


def test_the_planner_template_names_the_rules_part_before_the_timeouts_ac_110_11():  # AC-110.11
    text = PLANNER.read_text()
    heading = re.search(r"^## Contract$", text, re.M)
    assert heading, "the planner template has no `## Contract` heading line"
    template = text[heading.start():text.index("## gitops-app PR")]
    expected = ["Rules", "Errors", "Timeouts"]
    assert re.findall(r"^###\s+(\w+)", template, re.M) == expected


def test_the_planner_names_the_six_rule_kinds_ac_110_11():  # AC-110.11
    text = PLANNER.read_text()
    kinds = ("required", "min_length", "max_length", "min_value", "max_value", "allowed")
    for kind in kinds:
        assert re.search(rf"\b{kind}\b", text), kind


# ---------------- AC-110.4: the plugin text for `/component:spec --from-plan` ----------------

def test_spec_from_plan_tells_the_agent_about_the_copy_ac_110_4():  # AC-110.4
    text = FROM_PLAN.read_text()
    assert "contract/<plan_id>.json" in text
    path = r"contract/<plan_id>\.json"
    assert re.search(rf"{path}[^\n]*(spec step|written by)|(spec step|written by)[^\n]*{path}", text, re.I)
