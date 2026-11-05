"""Spec 143 (AC-143.11): the commands name the cplat wait to run, and no command or agent file writes a polling loop."""
import re

import pytest

import core

ROOT = core.PLATFORM_ROOT
PLUGINS = ROOT / "plugins"
FILES = sorted([*PLUGINS.glob("*/commands/*.md"), *PLUGINS.glob("*/agents/*.md")])

POLLED = re.compile(r"\b(kubectl|gh|cplat)\b")
LOOP = re.compile(r"\b(while|until|for)\b[^\n]*?(;|\n)\s*do\b|\bdo\b[\s\S]*?\bdone\b")
SLEEP = re.compile(r"\bsleep\b")


def code_chunks(text: str) -> list[str]:
    """Fenced blocks, inline code spans and prose lines that read as a shell loop (`; do` … `done`)."""
    fenced = re.findall(r"```[^\n]*\n(.*?)```", text, re.S)
    rest = re.sub(r"```[^\n]*\n.*?```", "", text, flags=re.S)
    inline = re.findall(r"`([^`\n]+)`", rest)
    lines = [ln for ln in rest.splitlines() if "; do" in ln and "done" in ln]
    return fenced + inline + lines


def polling_loops(text: str) -> list[str]:
    return [c for c in code_chunks(text) if SLEEP.search(c) and LOOP.search(c) and POLLED.search(c)]


def test_the_detector_finds_the_loops_the_coordinators_wrote_ac_143_11():  # AC-143.11
    release_loop = ("```bash\nsha=<TAG_COMMIT>\nfor _ in $(seq 1 12); do run=$(gh run list --workflow ci --branch main --commit "
                    "\"$sha\" --json databaseId --jq '.[0].databaseId'); [ -n \"$run\" ] && break; sleep 10; done\n```\n")
    argo_loop = "```bash\nwhile true; do\n  kubectl get applications -n argocd\n  sleep 15\ndone\n```\n"
    ship_loop = "Then `until cplat component ship status | grep -q deploy; do sleep 10; done`."
    for text in (release_loop, argo_loop, ship_loop):
        assert polling_loops(text), text
    assert not polling_loops("Wait for it, then sleep on it; do not poll `kubectl` for it.\n```bash\ncplat system wait --env dev\n```")


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(PLUGINS)))
def test_no_command_or_agent_polls_with_a_sleep_loop_ac_143_11(path):  # AC-143.11
    assert not polling_loops(path.read_text()), f"{path.relative_to(ROOT)}: a shell loop with sleep polls kubectl, gh or cplat"


WAITS = {
    "component/commands/set.md": ["cplat system wait"],
    "component/commands/add.md": ["cplat system wait"],
    "instance/commands/promote.md": ["cplat system wait"],
    "system/commands/set.md": ["cplat system wait"],
    "resource/commands/add.md": ["cplat system wait"],
    "cluster/commands/add.md": ["cplat cluster wait"],
    "system/commands/ship.md": ["cplat system ship next --wait", "cplat component ship wait"],
    "component/commands/release.md": ["cplat component release wait", "cplat pr wait"],
}


@pytest.mark.parametrize("rel", sorted(WAITS))
def test_each_command_names_its_wait_and_what_to_do_on_a_timeout_ac_143_11(rel):  # AC-143.11
    text = (PLUGINS / rel).read_text()
    for name in WAITS[rel]:
        assert name in text, f"{rel} names {name}"
    if any(w in ("cplat system wait", "cplat cluster wait") for w in WAITS[rel]):
        assert "--refresh" in text, f"{rel}: --refresh right after a merge it made"
    assert "exit 2" in text and "at most twice" in text, f"{rel}: run the same wait again on exit 2, at most twice"
    assert re.search(r"cause `?environment`?", text), f"{rel}: then escalate with cause environment"
    assert "polling loop" in text, f"{rel}: never write a polling loop"


def test_the_release_waits_for_mains_ci_with_cplat_before_the_tag_ac_143_11():  # AC-143.11
    text = (PLUGINS / "component/commands/release.md").read_text()
    phase = text[text.index("## Phase 5"):text.index("## Phase 6")]
    assert phase.index("cplat component release wait --commit") < phase.index("git tag -a vX.Y.Z")
    assert "gh run watch" not in phase and "do not tag" in phase


def test_the_waits_are_in_the_cplat_usage_and_agents_md_ac_143_11():  # AC-143.11
    usage = (ROOT / "scripts/cplat/cplat.py").read_text()
    for verb in ("cplat system wait", "cplat cluster wait", "component ship start|status|phase|pr|land|deploy|wait"):
        assert verb in usage
    assert "cplat system wait" in (ROOT / "docs/AGENTS.md").read_text()


def test_the_changelog_fragment_exists_ac_143_11():  # AC-143.11
    frag = ROOT / "docs/changelog.d/143-the-coordinator-waits-with-cplat.added.md"
    assert frag.is_file() and "(#475)" in frag.read_text()
