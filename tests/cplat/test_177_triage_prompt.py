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
    assert "without the user's confirmation" in hard_rule()["text"]   # interface: the closing condition the rule must now carry


def test_the_hard_rule_says_closing_needs_the_users_confirmation_ac_177_3():  # AC-177.3
    # the user's confirmation is the condition the hard rule states (assumption A1); the register check ties text to prompt
    assert "without the user's confirmation" in hard_rule()["text"]   # interface: the condition of the hard rule
    assert "without the user's confirmation" in prompt()


def test_the_prompt_no_longer_forbids_every_close_ac_177_3():  # AC-177.3
    # the old hard-rule sentence is what must disappear; the register check ties the new text to the rule
    assert not re.search(r"Never close an issue,", prompt())


def test_the_prompt_uses_the_missing_field_and_form_facts_of_the_script_ac_177_1():  # AC-177.1
    body = prompt()
    # `missing` and `form` are the row fields of the contract
    assert "`missing`" in body and "`form`" in body


def test_the_prompt_limits_questions_to_the_user_to_what_the_user_may_know_ac_177_1():  # AC-177.1
    # the prompt's split of questions (user versus reporter comment) is its only statement of the AC-177.1 rule
    body = prompt().lower()
    assert "may know" in body and "reporter comment" in body


def test_the_prompt_carries_the_reporter_comment_rules_ac_177_2():  # AC-177.2
    # the rules the script validates (thanks, plain words, no internal terms, days sentence) are named to the drafter
    body = prompt().lower()
    for word in ("thank", "plain words", "internal terms", "days", "reopen"):
        assert word in body, word
    assert "/platform:doctor" in body and "/issue:report" in body


def test_the_prompt_confirms_a_silent_needs_info_proposal_before_it_acts_ac_177_4():  # AC-177.4
    # `silent` is the batch's handled kind of the contract; act closes only the rows named by --rows
    body = prompt()
    assert "`silent`" in body and "final comment" in body
    assert body.index("confirm") < body.index("--rows") and "only the confirmed" in body.lower()
