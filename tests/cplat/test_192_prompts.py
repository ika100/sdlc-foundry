"""Spec 192 acceptance tests: `/platform:next` and the hand-over at the end of eight prompts (AC-192.1, .6, .7, .8).

Structure only: the files exist, point to `cplat next`, and keep the hard rule that the person chooses. The few pins of
prompt wording carry `# interface:`. Prompts are read at test run time, so a missing file fails the test that needs it."""
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
NEXT = ROOT / "plugins" / "platform" / "commands" / "next.md"
HAND_OVER = [
    "plugins/component/commands/spec.md",
    "plugins/component/commands/build.md",
    "plugins/component/commands/ship.md",
    "plugins/component/commands/release.md",
    "plugins/issue/commands/triage.md",
    "plugins/platform/commands/release.md",
    "plugins/system/commands/spec.md",
    "plugins/system/commands/ship.md",
]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_next_command_exists_with_a_description():  # AC-192.1
    text = read(NEXT)
    m = re.match(r"\A---\n(.*?)\n---\n", text, re.S)
    assert m
    meta = yaml.safe_load(m.group(1))
    assert meta["description"] and len(meta["description"]) <= 260
    assert "/platform:next" in meta["description"]  # interface: the usage line names the command


def test_next_command_runs_cplat_next_json_and_follows_how():  # AC-192.6
    text = read(NEXT)
    assert "cplat next --json" in text  # interface: the command the prompt must run
    assert "`how`" in text  # interface: the field the prompt follows
    assert "$ARGUMENTS" in text


def test_next_command_never_chooses_for_the_person():  # AC-192.7
    text = read(NEXT)
    assert "Hard rule" in text or "hard rule" in text.lower()  # interface: the legend of hard rules
    register = ROOT / "docs" / "rules" / "plugins" / "platform" / "commands" / "next.yml"
    rules = yaml.safe_load(read(register))
    assert "user-decides-approval" in str(rules)  # interface: the hard-rule id of the person's approval


def test_next_command_is_listed_in_the_plugin_readme():  # AC-192.1
    assert "/platform:next" in read(ROOT / "plugins" / "platform" / "README.md")


@pytest.mark.parametrize("rel", HAND_OVER)
def test_prompt_ends_with_the_hand_over(rel):  # AC-192.8
    text = read(ROOT / rel)
    assert "cplat next --json" in text  # interface: the hand-over runs the command that prints the next step


@pytest.mark.parametrize("rel", HAND_OVER)
def test_hand_over_sentence_is_in_the_last_half_of_the_prompt(rel):  # AC-192.8
    text = read(ROOT / rel)
    assert text.rfind("cplat next --json") > len(text) * 0.4


def test_the_procedure_is_not_copied_into_the_prompts():  # AC-192.8
    how = None
    import nextcmd
    how = nextcmd.HOW
    for rel in HAND_OVER + [str(NEXT.relative_to(ROOT))]:
        assert how not in read(ROOT / rel)
