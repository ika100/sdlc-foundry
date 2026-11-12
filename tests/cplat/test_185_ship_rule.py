"""Spec 185 acceptance test: both ship prompts carry the decision-becomes-a-task rule with a register entry (AC-185.6).

Structure only (specs 168 and 180): a `practice` entry with source `spec 185` exists per prompt, its text is quoted in the prompt,
it states a reason, and `cplat platform rules check` passes, which also holds the size baseline.
"""
import re

import pytest
import yaml

import cplat
from conftest import ROOT

PROMPTS = ["component", "system"]


def norm(text):
    return re.sub(r"\s+", " ", text).strip()


def entry_of(plugin):
    data = yaml.safe_load((ROOT / f"docs/rules/plugins/{plugin}/commands/ship.yml").read_text())
    found = [r for r in data["rules"] if str(r.get("source", "")) == "spec 185"]
    return found


@pytest.mark.parametrize("plugin", PROMPTS)
def test_the_ship_prompt_has_a_register_entry_of_spec_185_quoted_in_it_ac_185_6(plugin):  # AC-185.6
    found = entry_of(plugin)
    assert len(found) == 1, found
    (entry,) = found
    assert entry["class"] == "practice"
    prompt = norm((ROOT / f"plugins/{plugin}/commands/ship.md").read_text())
    text = norm(entry["text"])
    assert text and text in prompt, "the register text is not a quote of the prompt"


@pytest.mark.parametrize("plugin", PROMPTS)
def test_the_rule_names_a_task_in_the_plan_and_gives_a_reason_ac_185_6(plugin):  # AC-185.6
    (entry,) = entry_of(plugin)
    text = entry["text"].lower()
    assert "task" in text and "plan" in text and "decision" in text, text
    assert "escalation" in text, text
    # interface: the spec names the point in time at which the decision must be a task
    assert "before the ship goes on" in text, text
    assert re.search(r"\b(so that|because|since)\b", text), "no reason clause"


def test_the_rules_check_passes_with_both_entries_and_within_the_baseline_ac_185_6(capsys):  # AC-185.6
    assert all(len(entry_of(p)) == 1 for p in PROMPTS)
    rc = cplat.main(["platform", "rules", "check", "--repo", str(ROOT)])
    out = capsys.readouterr().out
    assert rc == 0, out
    m = re.search(r"prompts (\d+) bytes \(baseline (\d+)\)", out)
    assert m and int(m.group(1)) <= int(m.group(2)), out
