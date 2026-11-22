"""Spec 219: website specs get a UX design step (#715).

The decision and the checks are cplat's: the registry flag through scripts/shapes.py, the routing through `shapecmd.route`
on repos named by their `.copier-answers.yml`, `cplat spec ux` and `cplat spec check` through `spec.main`. The prompts are
tested for structure only (spec 168, ADR-103): what they point to, their headings and the agent's front matter."""
from __future__ import annotations

import copy
import json

import pytest
import yaml

import cplat
import core
import shapecmd
import shapes
import spec
import structure

ROOT = core.PLATFORM_ROOT
SPEC_ID = "007-checkout"
AGENT = "plugins/web/agents/ux-designer.md"
PLAN = "plugins/component/commands/plan.md"
BUILD = "plugins/component/commands/build.md"
REVIEWER = "plugins/svc/agents/reviewer.md"

VISIBLE_AC = "Given a cart, when the person opens the checkout page, then the total is shown above the pay button."
HIDDEN_AC = "Given an order, when the payment provider confirms it, then the order is stored as paid within 5 seconds."

SPEC_MD = """---
spec_id: {spec_id}
title: Checkout
status: approved
priority: P1
{field}---

# 007 — Checkout

## Problem

People cannot pay.

## Stories

{story}

## Acceptance criteria

- **AC-007.1** {ac}
- **AC-007.2** Given an order, when it is paid, then a receipt number exists.
- ~~**AC-007.3**~~ withdrawn: refunds moved to spec 009.

## Non-goals

- Refunds

## Open questions

None.

## Changelog

- 2026-11-22 created
"""

UX_MD = """---
spec_id: {spec_id}
spec_hash: {hash}
---

# UX — 007 Checkout

## Flows

1. Cart → checkout page → pay (AC-007.1).

## Screens

- Checkout page: total, pay button ({ref}).

## States

- Empty cart, loading, payment error.

## Accessibility

- The pay button is reachable by keyboard.
"""


def repo(tmp_path, template: str | None = "web-nextjs"):
    root = tmp_path / (template or "plain")
    root.mkdir()
    if template:
        (root / ".copier-answers.yml").write_text(f"_src_path: gh:ika100/sdlc-foundry/templates/{template}\n")
    return root


def write_spec(root, *, ac=VISIBLE_AC, story="As a buyer, I want to pay, so that I get my order.", field=""):
    d = root / "docs" / "specs" / SPEC_ID
    d.mkdir(parents=True, exist_ok=True)
    (d / "spec.md").write_text(SPEC_MD.format(spec_id=SPEC_ID, field=field, story=story, ac=ac))
    return d


def write_ux(d, *, hash_=None, spec_id=SPEC_ID, ref="AC-007.1", drop=None, no_hash=False):
    text = UX_MD.format(spec_id=spec_id, hash=hash_ or spec.read(d).ac_hash(), ref=ref)
    if no_hash:
        text = "\n".join(ln for ln in text.splitlines() if not ln.startswith("spec_hash:")) + "\n"
    if drop:
        text = text.replace(f"## {drop}\n", "## Notes\n")
    (d / "ux.md").write_text(text)


def ux(root, capsys) -> dict:
    assert spec.main(["--repo", str(root), "ux", SPEC_ID, "--json"]) == 0
    return json.loads(capsys.readouterr().out)


def check(root, capsys) -> tuple[int, str]:
    rc = spec.main(["--repo", str(root), "check", SPEC_ID])
    cap = capsys.readouterr()
    return rc, cap.out + cap.err


# ---------------- AC-219.1: the registry flag ----------------

def test_only_web_nextjs_declares_the_ux_designer():  # AC-219.1
    flagged = [s["id"] for s in shapes.load_all() if s.get("ux_designer")]
    assert flagged == ["web-nextjs"]
    assert shapes.validate(shapes.load_all()) == []


def test_a_flag_without_the_agent_fails_the_registry_check():  # AC-219.1
    entry = copy.deepcopy(shapes.get("service-python"))
    entry["ux_designer"] = True
    errs = [e for e in shapes.validate([entry]) if "ux_designer" in e]
    assert errs and "service-python" in errs[0] and "plugins/svc/agents/ux-designer.md" in errs[0]


# ---------------- AC-219.2: the routing ----------------

def test_a_website_routes_the_ux_designer(tmp_path):  # AC-219.2
    assert shapecmd.route(repo(tmp_path))["agents"]["ux-designer"] == "web:ux-designer"


@pytest.mark.parametrize("template", ["service-python", "library-python", "service-typescript", "library-typescript", "service-go"])
def test_other_shapes_route_no_ux_designer(tmp_path, template):  # AC-219.2
    assert "ux-designer" not in shapecmd.route(repo(tmp_path, template))["agents"]


# ---------------- AC-219.3: derived from the criteria and stories ----------------

def test_a_visible_criterion_needs_ux_and_names_the_word(tmp_path, capsys):  # AC-219.3
    root = repo(tmp_path)
    write_spec(root)
    out = ux(root, capsys)
    assert out["spec"] == SPEC_ID and out["ux"] == "needed"
    assert any(w in out["reason"] for w in ("page", "button", "shown"))


def test_a_visible_story_needs_ux(tmp_path, capsys):  # AC-219.3
    root = repo(tmp_path)
    write_spec(root, ac=HIDDEN_AC, story="As a buyer, I want a dialog that confirms the payment, so that I trust it.")
    out = ux(root, capsys)
    assert out["ux"] == "needed" and "dialog" in out["reason"]


def test_nothing_visible_needs_no_ux(tmp_path, capsys):  # AC-219.3
    root = repo(tmp_path)
    write_spec(root, ac=HIDDEN_AC, story="As the shop, I want paid orders stored, so that I can ship them.")
    out = ux(root, capsys)
    assert out["ux"] == "none" and out["reason"]


# ---------------- AC-219.4: the spec's own field ----------------

def test_the_field_decides_over_the_criteria(tmp_path, capsys):  # AC-219.4
    root = repo(tmp_path)
    write_spec(root, field="ux: none\n")
    out = ux(root, capsys)
    assert out["ux"] == "none" and "spec.md" in out["reason"]
    write_spec(root, ac=HIDDEN_AC, story="As the shop, I want paid orders stored.", field="ux: needed\n")
    out = ux(root, capsys)
    assert out["ux"] == "needed" and "spec.md" in out["reason"]


def test_an_unknown_field_value_fails_the_check(tmp_path, capsys):  # AC-219.4
    root = repo(tmp_path)
    write_spec(root, field="ux: maybe\n")
    rc, out = check(root, capsys)
    assert rc == 1 and "ux" in out and "needed" in out and "none" in out and "maybe" in out


# ---------------- AC-219.5: other shapes never get it ----------------

@pytest.mark.parametrize("template", ["service-python", "library-typescript", None])
def test_other_shapes_answer_none_whatever_the_field(tmp_path, capsys, template):  # AC-219.5
    root = repo(tmp_path, template)
    write_spec(root, field="ux: needed\n")
    out = ux(root, capsys)
    assert out["ux"] == "none"
    assert (template or "no shape") in out["reason"]


# ---------------- AC-219.6: done and stale ----------------

def test_a_current_ux_md_is_done_and_a_stale_one_is_needed(tmp_path, capsys):  # AC-219.6
    root = repo(tmp_path)
    d = write_spec(root)
    write_ux(d)
    assert ux(root, capsys)["ux"] == "done"
    write_ux(d, hash_="0123456789ab")
    out = ux(root, capsys)
    assert out["ux"] == "needed" and "stale" in out["reason"]


# ---------------- AC-219.7: the ux.md check ----------------

def test_a_complete_ux_md_passes_the_check(tmp_path, capsys):  # AC-219.7
    root = repo(tmp_path)
    write_ux(write_spec(root))
    assert check(root, capsys)[0] == 0


@pytest.mark.parametrize("section", ["Flows", "Screens", "States", "Accessibility"])
def test_a_missing_section_fails_naming_it(tmp_path, capsys, section):  # AC-219.7
    root = repo(tmp_path)
    write_ux(write_spec(root), drop=section)
    rc, out = check(root, capsys)
    assert rc == 1 and "ux.md" in out and section in out


@pytest.mark.parametrize("ref", ["AC-007.9", "AC-007.3"])
def test_an_unknown_or_withdrawn_criterion_fails(tmp_path, capsys, ref):  # AC-219.7
    root = repo(tmp_path)
    write_ux(write_spec(root), ref=ref)
    rc, out = check(root, capsys)
    assert rc == 1 and "ux.md" in out and ref in out


def test_bad_front_matter_fails(tmp_path, capsys):  # AC-219.7
    root = repo(tmp_path)
    d = write_spec(root)
    write_ux(d, spec_id="008-other")
    rc, out = check(root, capsys)
    assert rc == 1 and "ux.md" in out and "spec_id" in out
    write_ux(d, no_hash=True)
    rc, out = check(root, capsys)
    assert rc == 1 and "ux.md" in out and "spec_hash" in out


# ---------------- AC-219.8: the agent ----------------

def _front(rel: str) -> dict:
    return yaml.safe_load((ROOT / rel).read_text().split("---\n")[1])


def test_the_agent_reads_and_writes_but_runs_nothing():  # AC-219.8
    meta = _front(AGENT)
    tools = {t.strip() for t in meta["tools"].split(",")}
    assert meta["name"] == "ux-designer" and meta["model"] == "opus"
    assert {"Read", "Write"} <= tools and "Bash" not in tools


def test_the_agent_names_the_ux_md_sections_and_passes_the_rules_check(capsys):  # AC-219.8
    assert {"Flows", "Screens", "States", "Accessibility"} <= set(structure.headings(AGENT))
    assert cplat.main(["platform", "rules", "check", "--repo", str(ROOT), "--only", AGENT]) == 0


# ---------------- AC-219.9: the plan command ----------------

def test_plan_asks_cplat_and_designs_before_the_architect():  # AC-219.9
    assert structure.points_to(PLAN, "cplat spec ux")
    heads = structure.headings(PLAN)
    ux_step = next(i for i, h in enumerate(heads) if "UX" in h)
    architect = next(i for i, h in enumerate(heads) if "Architect" in h)
    assert ux_step < architect
    assert "agents.ux-designer" in (ROOT / PLAN).read_text()


# ---------------- AC-219.10: build and review ----------------

def test_the_coder_brief_has_ux_and_the_reviewer_reads_ux_md():  # AC-219.10
    assert "`UX`" in (ROOT / BUILD).read_text()
    assert "ux.md" in (ROOT / REVIEWER).read_text()


# ---------------- AC-219.11: docs ----------------

def test_the_docs_name_the_step():  # AC-219.11
    skill = (ROOT / "plugins/svc/skills/spec-format/SKILL.md").read_text()
    assert "`ux.md`" in skill and "ux-designer" in skill
    assert "\nux:" in (ROOT / "plugins/svc/skills/spec-format/references/spec.md").read_text()
    assert "ux-designer" in (ROOT / "plugins/web/README.md").read_text()
    assert "ux-designer" in (ROOT / "docs/AGENTS.md").read_text()
