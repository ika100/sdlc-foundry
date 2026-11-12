"""Spec 149 acceptance tests: a spec decides by default and asks only what it may not decide (ADR-084).

Seams: real spec folders under tmp_path (`test_spec.make`), the plugin files as text, and `runs_built.assumed`."""
from pathlib import Path

import pytest

import runs_built
import spec
from test_spec import make

ROOT = Path(__file__).resolve().parents[2]
ASSUMED = """- **A1** A rule fires again only after the price crossed back (other option: once per hour; affects AC-007.1).
- **A2** Webhooks get the rule id in the body (other option: in a header; affects AC-007.2).
- ~~**A3** Email only.~~ Revised 2026-11-07: webhooks too, AC-007.2."""


@pytest.fixture(autouse=True)
def no_shape(monkeypatch):
    monkeypatch.setattr(spec, "repo_shape", lambda root: None)


def with_assumptions(root, text=ASSUMED, status="draft"):
    s = make(root, status=status)
    p = s.dir / "spec.md"
    p.write_text(p.read_text().replace("## Open questions", f"## Assumptions\n\n{text}\n\n## Open questions", 1))
    return spec.read(s.dir)


# ---------------- AC-149.1 ----------------

def test_the_product_manager_decides_by_default_and_asks_four_kinds_ac_149_1():  # AC-149.1
    pm = (ROOT / "plugins/svc/agents/product-manager.md").read_text()
    assert "Decide by default; ask only what you may not decide" in pm and "Don't guess. Ask." not in pm
    for kind in ("secrets", "money", "existing data", "so ambiguous"):
        assert kind in pm
    assert "- **A<n>** <the decision> (other option: <…>; affects AC-…)" in pm and "ASSUMPTIONS:" in pm  # interface: the assumption bullet format cplat spec parses
    ref = (ROOT / "plugins/svc/skills/spec-format/references/spec.md").read_text()
    assert "## Assumptions" in ref and "Never answer your own questions by assumption" not in ref
    assert (ROOT / "docs/adr/084-a-spec-decides-by-default.md").is_file()


# ---------------- AC-149.2 ----------------

def test_the_skeleton_has_an_assumptions_section_before_open_questions_ac_149_2(tmp_path):  # AC-149.2
    s = spec.new(tmp_path, "Price alerts", shape=None, priority="P1", tracks=[], parent=None)
    text = (s.dir / "spec.md").read_text()
    assert text.index("## Assumptions") < text.index("## Open questions")
    assert spec.read(s.dir).assumptions() == []          # the comment in the skeleton is no assumption


def test_assumptions_never_block_check_or_approval_ac_149_2(tmp_path):  # AC-149.2
    s = with_assumptions(tmp_path)
    assert s.open_questions() == [] and spec.check(s) == []
    assert spec.main(["--repo", str(tmp_path), "approve", s.id]) == 0
    assert spec.read(s.dir).status == "approved"


# ---------------- AC-149.3 ----------------

def test_list_and_detail_count_active_and_revised_assumptions_ac_149_3(tmp_path):  # AC-149.3
    s = with_assumptions(tmp_path)
    assert len(s.assumptions()) == 2 and len(s.assumptions(revised=True)) == 1
    assert spec.summary(tmp_path, s)["assumptions"] == 2
    d = spec.detail(tmp_path, s, None)
    assert d["assumptions_revised"] == 1 and d["assumption_list"][0].startswith("**A1**")


def test_a_spec_without_the_section_has_none_ac_149_3(tmp_path):  # AC-149.3
    s = make(tmp_path)
    assert s.assumptions() == [] and spec.summary(tmp_path, s)["assumptions"] == 0


# ---------------- AC-149.4 ----------------

@pytest.mark.parametrize("plugin", ["component", "system"])
def test_the_spec_commands_show_assumptions_and_ask_once_ac_149_4(plugin):  # AC-149.4
    cmd = (ROOT / f"plugins/{plugin}/commands/spec.md").read_text()
    assert '"Approve with these <n> assumptions (Recommended)" / "Change an assumption" / "I\'ll review the file first"' in cmd
    assert "Open questions" in cmd or "open questions" in cmd
    assert "ADR-084" in cmd


# ---------------- AC-149.5 ----------------

def test_the_built_block_counts_approved_and_revised_assumptions_ac_149_5(tmp_path):  # AC-149.5
    s = with_assumptions(tmp_path)
    assert runs_built.assumed(s.dir) == (3, 1)
    assert runs_built.assumed(None) == (0, 0)
    skeleton = spec.new(tmp_path / "other", "X", shape=None, priority="P1", tracks=[], parent=None)
    assert runs_built.assumed(skeleton.dir) == (0, 0)
