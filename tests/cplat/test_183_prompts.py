"""Spec 183 acceptance tests: the prompts tell to use `cplat adr add` and `(replaces AC-…)` (AC-183.4, AC-183.8).

Content checks on the prompt files. The size check compares the total `promptrules.prompt_bytes` (the bytes of every prompt the
rules register covers) with the same total at the merge base with main: this spec may not make the prompts larger."""
import subprocess

import pytest

import core
import cplat
import evalgate
import promptrules

ROOT = core.PLATFORM_ROOT
ARCHITECT = "plugins/svc/agents/architect.md"
PLAN = "plugins/component/commands/plan.md"
PM = "plugins/svc/agents/product-manager.md"
PLANNER = "plugins/system/agents/planner.md"
SPEC_REF = "plugins/svc/skills/spec-format/references/spec.md"


def text(rel):
    return (ROOT / rel).read_text()


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def base_total():
    """The prompt bytes at the merge base with main (origin/main when there is one)."""
    for ref in ("origin/main", "main"):
        mb = git("merge-base", "HEAD", ref)
        if mb.returncode == 0 and mb.stdout.strip():
            break
    else:
        pytest.skip("no main to compare the prompt size with")
    listing = git("ls-tree", "-r", "-l", mb.stdout.strip(), "plugins").stdout
    total = 0
    for line in listing.splitlines():
        meta, path = line.split("\t", 1)
        if evalgate.PROMPT.match(path):
            total += int(meta.split()[3])
    return total


def rules_pass_and_size_holds():
    assert cplat.main(["platform", "rules", "check", "--repo", str(ROOT)]) == 0
    # a gated `rules rebaseline` (spec 168, ADR-103) is the one way the prompts may grow on a branch
    import yaml
    raised = yaml.safe_load((ROOT / "docs/rules/register.yml").read_text())["baseline"]["prompt_bytes"]
    assert promptrules.prompt_bytes(ROOT) <= max(base_total(), raised)


def test_architect_and_plan_use_cplat_adr_add_ac_183_4():  # AC-183.4
    for rel in (ARCHITECT, PLAN):
        body = text(rel)
        assert "cplat adr add" in body, rel
        assert "ADR_NEXT" not in body, rel
    assert "docs/adr/<nnn>-<title>.md" not in text(ARCHITECT)
    assert "index row" not in text(ARCHITECT).lower() or "by hand" not in text(ARCHITECT).lower()


def test_rules_check_passes_and_the_prompts_did_not_grow_ac_183_4():  # AC-183.4
    assert "cplat adr add" in text(ARCHITECT)           # the prompt change itself, so that this cannot pass before it
    rules_pass_and_size_holds()


def test_pm_planner_and_spec_reference_tell_to_mark_replaced_criteria_ac_183_8():  # AC-183.8
    for rel in (PM, PLANNER, SPEC_REF):
        body = text(rel)
        assert "(replaces AC-" in body, rel
        assert "superseded by" in body, rel


def test_new_prompt_rules_have_register_entries_ac_183_8():  # AC-183.8
    assert "(replaces AC-" in text(PM) and "(replaces AC-" in text(PLANNER)
    for prompt in (PM, PLANNER, SPEC_REF):
        entries = ROOT / promptrules.entries_path(prompt)
        if prompt == SPEC_REF and not entries.exists():
            continue        # the format reference has no register file today; a rule added to it brings one
        assert "#477" in entries.read_text(), entries


def test_rules_check_passes_and_total_size_holds_after_both_changes_ac_183_8():  # AC-183.8
    assert "(replaces AC-" in text(PM)                   # the prompt change itself, so that this cannot pass before it
    rules_pass_and_size_holds()
