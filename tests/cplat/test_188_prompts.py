"""Spec 188 acceptance tests: the explore commands and the prompts around them (AC-188.1, .3, .4, .5, .6, .9, .10, .11, .12).

Structure first (frontmatter, what a prompt points to, headings, register files); the few wording pins carry `# interface:`.
The whole-session half of AC-188.1 is behavioural and cannot run here: the definition grants no write tool and says it
writes, edits and commits nothing. The prompts are read at test run time, so a missing file fails the test that needs it."""
import re

import pytest
import yaml

import cplat
import core
import structure

ROOT = core.PLATFORM_ROOT
COMPONENT = "plugins/component/commands/explore.md"
SYSTEM = "plugins/system/commands/explore.md"
EXPLORE = (COMPONENT, SYSTEM)
PM = "plugins/svc/agents/product-manager.md"
ARCHITECT = "plugins/svc/agents/architect.md"
SPEC_COMMANDS = ("plugins/component/commands/spec.md", "plugins/system/commands/spec.md")
SPEC_REF = "plugins/svc/skills/spec-format/references/spec.md"
DESIGN_REF = "plugins/svc/skills/spec-format/references/design.md"
TRIAGE = "plugins/issue/commands/triage.md"
ALLOWED = {"Read", "Grep", "Glob", "AskUserQuestion", "Bash(cplat explore *)", "Bash(git status*)", "Bash(git log *)",
           "Bash(git diff *)", "Bash(git show *)", "Bash(git grep *)", "Bash(git blame *)", "Bash(git ls-files*)"}
NAMES = re.compile(r"/(component|system):explore|cplat explore")


def text(rel):
    return (ROOT / rel).read_text()


def frontmatter(rel):
    return yaml.safe_load(text(rel).split("---")[1])


@pytest.mark.parametrize("rel", EXPLORE)
def test_the_explore_commands_allow_read_tools_and_read_only_git_only_ac_188_1(rel):  # AC-188.1
    tools = {t.strip() for t in frontmatter(rel)["allowed-tools"].split(",")}
    assert tools == ALLOWED
    assert not tools & {"Write", "Edit", "NotebookEdit"}


@pytest.mark.parametrize("rel", EXPLORE)
def test_the_explore_commands_say_they_write_nothing_ac_188_1(rel):  # AC-188.1
    body = text(rel).lower()
    for word in ("write", "edit", "commit"):
        assert word in body, word
    assert "nothing" in body


@pytest.mark.parametrize("rel,own,other", [(COMPONENT, "/component:", "/system:explore"), (SYSTEM, "/system:", "/component:explore")])
def test_the_explore_commands_send_the_other_shape_away_ac_188_3(rel, own, other):  # AC-188.3
    assert structure.points_to(rel, other)


@pytest.mark.parametrize("rel,targets", [(COMPONENT, ("/component:fix", "/component:spec", "/component:build", "/component:plan")),
                                         (SYSTEM, ("/system:spec", "/system:plan"))])
def test_the_decline_rule_names_the_command_that_does_it_ac_188_3(rel, targets):  # AC-188.3
    for t in targets:
        assert structure.points_to(rel, t), t


@pytest.mark.parametrize("rel", EXPLORE)
def test_the_running_list_and_the_three_ways_out_ac_188_3(rel):  # AC-188.3
    body = text(rel)
    for pin in ("Decisions so far (", "Still open:", "[behaviour]", "AskUserQuestion", "spec it", "keep exploring", "stop"):
        assert pin in body, pin
    assert re.search(r"every 3rd turn", body)


@pytest.mark.parametrize("rel,spec_cmd", [(COMPONENT, "/component:spec"), (SYSTEM, "/system:spec")])
def test_spec_it_hands_over_labelled_decisions_in_a_decided_block_ac_188_4(rel, spec_cmd):  # AC-188.4
    body = text(rel)
    assert structure.points_to(rel, spec_cmd)
    for pin in ("DECIDED:", "behaviour", "constraint", "hint"):
        assert pin in body, pin
    assert "decisions file" in body.lower()


@pytest.mark.parametrize("rel", SPEC_COMMANDS)
def test_the_spec_commands_read_a_decided_block_and_create_an_explored_spec_ac_188_4(rel):  # AC-188.4
    body = text(rel)
    for pin in ("DECIDED:", "--explored", "cplat explore context"):
        assert pin in body, pin


def test_the_product_manager_maps_each_decision_kind_ac_188_5():  # AC-188.5
    body = text(PM)
    for pin in ("DECIDED:", "(decided in explore)", "Notes for the architect"):   # interface: the mapping of the contract
        assert pin in body, pin
    for kind in ("behaviour", "constraint", "hint"):
        assert kind in body, kind


def test_the_spec_format_and_the_architect_know_notes_and_departures_ac_188_5():  # AC-188.5
    assert "## Notes for the architect" in text(SPEC_REF)                       # interface: the section heading of the format
    assert "Notes for the architect" in text(ARCHITECT)
    assert "Departs from note" in text(ARCHITECT) and "Departs from note" in text(DESIGN_REF)


def test_a_contradicting_decision_becomes_an_open_question_ac_188_6():  # AC-188.6
    body = text(PM)
    assert "contradicts" in body and "open question" in body.lower()
    assert re.search(r"ADR-<NNN>|accepted ADR", body, re.I) and "AC-<MMM>" in body
    for rel in SPEC_COMMANDS:
        assert "specs" in text(rel) and "adrs" in text(rel)


@pytest.mark.parametrize("rel,cmd", [(SPEC_COMMANDS[0], "/component:explore <topic>"), (SPEC_COMMANDS[1], "/system:explore <topic>")])
def test_too_ambiguous_a_request_recommends_explore_ac_188_9(rel, cmd):  # AC-188.9
    body = text(rel)
    assert "explore first" in body and cmd in body and "(Recommended)" in body
    assert "cplat spec discard" in body
    assert "explore first" in text(PM)


@pytest.mark.parametrize("rel", (PM, ARCHITECT))
def test_the_unattended_agents_never_name_explore_ac_188_11(rel):  # AC-188.11
    assert "Notes for the architect" in text(rel)      # interface: the explore change reached this agent (so that this cannot pass before it)
    assert not NAMES.search(text(rel))


def test_triage_offers_needs_exploring_next_to_spec_fix_and_reply_ac_188_10():  # AC-188.10
    body = text(TRIAGE)
    assert "needs exploring" in body or "needs-exploring" in body
    assert structure.points_to(TRIAGE, "/component:explore") and structure.points_to(TRIAGE, "/system:explore")
    assert "/component:explore #<n>" in body and "/system:explore #<n>" in body
    assert "#<n>" in body
    assert "keeps" in body or "stays in the queue" in body                   # interface: it says the issue stays in the queue


@pytest.mark.parametrize("rel", EXPLORE)
def test_the_explore_commands_say_only_a_person_starts_them_ac_188_11(rel):  # AC-188.11
    assert "person" in text(rel).lower() and "unattended" in text(rel).lower()


UNATTENDED = ["plugins/component/commands/ship.md", "plugins/component/commands/build.md", "plugins/component/commands/fix.md",
              "plugins/component/commands/plan.md", "plugins/system/commands/ship.md", "plugins/system/commands/plan.md",
              "plugins/shared/settings.json", "plugins/shared/hooks/hooks.json", "scripts/cplat/headless.py",
              "scripts/cplat/preflight.py", "scripts/cplat/dispatch_agent.py"]


def unattended_files():
    found = list(UNATTENDED)
    found += [str(p.relative_to(ROOT)) for p in (ROOT / "plugins" / "svc" / "agents").glob("*.md")]
    found += [str(p.relative_to(ROOT)) for p in (ROOT / "scripts" / "cplat").glob("dispatch*.py")]
    found += [str(p.relative_to(ROOT)) for p in (ROOT / "plugins").glob("*/settings.json")]
    return sorted(set(found))


def test_no_unattended_prompt_or_run_allowlist_names_explore_ac_188_11():  # AC-188.11
    assert (ROOT / COMPONENT).is_file() and (ROOT / SYSTEM).is_file()      # the commands exist, so the absence below means something
    bad = [rel for rel in unattended_files() if (ROOT / rel).is_file() and NAMES.search(text(rel))]
    assert bad == []


@pytest.mark.parametrize("scope", ("component", "system"))
def test_the_explore_prompts_have_register_files_ac_188_12(scope):  # AC-188.12
    assert (ROOT / "plugins" / scope / "commands" / "explore.md").is_file()
    reg = ROOT / "docs" / "rules" / "plugins" / scope / "commands" / "explore.yml"
    assert reg.is_file()
    for entry in yaml.safe_load(reg.read_text())["rules"]:
        assert entry["class"] in ("hard", "practice", "experience", "not a rule")


def test_rules_check_passes_with_the_explore_prompts_ac_188_12():  # AC-188.12
    assert (ROOT / COMPONENT).is_file() and (ROOT / SYSTEM).is_file()
    assert cplat.main(["platform", "rules", "check", "--repo", str(ROOT)]) == 0
