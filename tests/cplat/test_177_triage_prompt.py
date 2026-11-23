"""Spec 177 acceptance tests: the structure of `/issue:triage` after the change (AC-177.1 to AC-177.4). The hard rule now allows a
confirmed close and keeps its register id; the prompt uses the row fields the script gives it."""
import re

import yaml

import core

TRIAGE = "plugins/issue/commands/triage.md"
RULES = "docs/rules/plugins/issue/commands/triage.yml"
REGISTER = "docs/rules/register.yml"


def prompt():
    return (core.PLATFORM_ROOT / TRIAGE).read_text()


def hard_rule():
    rules = yaml.safe_load((core.PLATFORM_ROOT / RULES).read_text())["rules"]
    return next(r for r in rules if r.get("hard") == "triage-never-closes")


def test_the_closing_hard_rule_keeps_its_register_id_and_enforcement_ac_177_3():  # AC-177.3
    register = yaml.safe_load((core.PLATFORM_ROOT / REGISTER).read_text())
    hard = register["hard"]["triage-never-closes"] if "hard" in register else None
    assert hard is not None and hard["enforced_by"] == "cplat issue triage"
    assert hard_rule()["class"] == "hard"


def test_the_hard_rule_says_closing_needs_the_users_confirmation_ac_177_3():  # AC-177.3
    # interface: the user's confirmation is the condition the hard rule states (assumption A1); the register check ties text to prompt
    assert "without the user's confirmation" in hard_rule()["text"]
    assert "without the user's confirmation" in prompt()


def test_the_prompt_no_longer_forbids_every_close_ac_177_3():  # AC-177.3
    assert not re.search(r"Never close an issue,", prompt())


def test_the_prompt_uses_the_missing_field_and_form_facts_of_the_script_ac_177_1():  # AC-177.1
    body = prompt()
    # interface: `missing` and `form` are the row fields of the contract
    assert "`missing`" in body and "`form`" in body


def test_the_prompt_names_the_public_commands_only_for_reporters_ac_177_2():  # AC-177.2
    body = prompt()
    assert "/platform:doctor" in body and "/issue:report" in body


def test_the_prompt_still_confirms_before_it_acts_ac_177_4():  # AC-177.4
    body = prompt()
    assert "--rows" in body and body.index("confirm") < body.index("--rows")
