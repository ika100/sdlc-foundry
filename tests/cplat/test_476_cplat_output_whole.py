"""#476: an agent ran `cplat instance verify dev 2>&1 | grep -E 'smoke:|Smoke|FAIL'` and the grep hid the `Promotion (staging)` decision.
cplat's output is read whole: no command, agent or reference text pipes it into `grep`, `head` or `tail`, and every command and agent
that calls cplat says so (a subagent prompt written by a command too)."""
import re

import pytest

import core

ROOT = core.PLATFORM_ROOT
PLUGINS = ROOT / "plugins"
TEXTS = sorted([*PLUGINS.glob("*/commands/*.md"), *PLUGINS.glob("*/agents/*.md"), *PLUGINS.glob("*/references/*.md")])
RULE = "`grep`, `head` or `tail`"
# a cplat call whose output goes through a filter in the same shell command (`;`, `&&` and a closing backtick end the command)
FILTERED = re.compile(r"\bcplat\b(?:(?!&&|\|\||[;\n`]).)*?(?<!\|)\|(?!\|)\s*(grep|head|tail)\b")


def tombstone(text: str) -> bool:
    return bool(re.search(r"^description:\s*\"?Moved in", text, re.M))


def calls_cplat(text: str) -> bool:
    return bool(re.search(r"(`|^)cplat [a-z]", text, re.M))


def filtered_calls(text: str) -> list[str]:
    return [m.group(0) for m in FILTERED.finditer(text)]


def test_the_check_finds_the_pipe_of_the_journey_and_allows_other_tools():
    assert filtered_calls("Run `cplat instance verify dev 2>&1 | grep -E 'smoke:|Smoke|FAIL'`.")
    assert filtered_calls("```bash\ncplat component ship status | tail -5\n```")
    assert filtered_calls("cplat platform runs report --json | head -20")
    assert not filtered_calls("gh api repos/o/r/contents/CLAUDE.md -q .content | base64 -d | head -120")   # not cplat
    assert not filtered_calls("`cplat api list --json | jq '.[0]'`")                                       # jq reads JSON whole
    assert not filtered_calls("run `cplat spec list`; then `git log | head -3`")


@pytest.mark.parametrize("path", TEXTS, ids=lambda p: str(p.relative_to(PLUGINS)))
def test_no_text_filters_cplats_output(path):
    assert not filtered_calls(path.read_text()), f"{path.relative_to(ROOT)} filters cplat's output: read it whole or use --json"


CALLERS = [p for p in TEXTS if "/references/" not in str(p) and not tombstone(p.read_text()) and calls_cplat(p.read_text())]


@pytest.mark.parametrize("path", CALLERS, ids=lambda p: str(p.relative_to(PLUGINS)))
def test_every_command_and_agent_that_calls_cplat_says_to_read_its_output_whole(path):
    text = path.read_text()
    assert RULE in text and "whole" in text, f"{path.relative_to(ROOT)}: say that cplat's output is read whole, never through {RULE}"


def test_the_system_ships_subagent_prompt_carries_the_rule():
    text = (PLUGINS / "system/commands/ship.md").read_text()
    prompt = text[text.index("Prompt: *"):text.index("*", text.index("Prompt: *") + 9)]
    assert RULE in prompt


def test_the_changelog_fragment_exists():
    frags = list((ROOT / "docs/changelog.d").glob("476-*.fixed.md"))
    assert frags and "(#476)" in frags[0].read_text()
