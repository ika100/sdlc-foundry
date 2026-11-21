"""Spec 211 acceptance tests: the unit briefing and its guards (AC-211.1 to AC-211.6, the API part).

Seam: `briefing.build / headings / problems / kind` (design.md section 1) on the released instructions and on temporary
copies of them (the `root` argument). The sections the briefing must hold are cut from the source by `support_211.cut`."""
import re
from pathlib import Path

import pytest

import support_211 as rc211
from support_211 import (FALLBACK_LINE, KNOWN, MAPPING, PLUGIN, UNIT_MD, UNITS, briefing, build_sections, copy_plugin, edit,
                         expected_keys, key_of, of, unit_rules_bullets)

HEADLINE = re.compile(r"^(#{2,3}) +")


def lines_of(text):
    return text.splitlines()


def build_headings(text):
    """The build-instruction heading keys in a briefing, in order (the unit-mode reference's own headings left out)."""
    known = set(build_sections())
    return [key_of(ln) for ln in lines_of(text) if HEADLINE.match(ln) and key_of(ln) in known]


# ---------------- AC-211.1: what the briefing holds ----------------

def test_a_briefing_starts_with_its_unit_and_holds_the_unit_mode_parts_ac_211_1():  # AC-211.1
    text = briefing.build("task:t1", "ship")
    assert lines_of(text)[0].startswith("briefing for unit task:t1 (ship), cut from ")
    unit_text = UNIT_MD.read_text()
    permissions = next(p for p in unit_text.split("\n\n") if p.startswith("**Permissions:**"))
    assert permissions.replace("${CLAUDE_PLUGIN_ROOT}", str(briefing.PLUGIN_ROOT)) in text
    assert "| Unit | What you do |" in text
    row = next(ln for ln in lines_of(unit_text) if ln.startswith("| `task:<id>`"))
    assert row.replace("${CLAUDE_PLUGIN_ROOT}", str(briefing.PLUGIN_ROOT)) in lines_of(text)
    for bullet in unit_rules_bullets():
        assert bullet.replace("${CLAUDE_PLUGIN_ROOT}", str(briefing.PLUGIN_ROOT)) in lines_of(text)
    assert "## Rules for every unit" in lines_of(text)


def test_the_briefing_holds_the_general_paragraph_and_the_mapped_sections_word_for_word_ac_211_1():  # AC-211.1
    text = briefing.build("verification", "ship")
    root = str(briefing.PLUGIN_ROOT)
    general = next(p for p in (PLUGIN / "commands" / "build.md").read_text().split("\n\n") if p.startswith("A rule marked **Hard rule:**"))
    assert general.replace("${CLAUDE_PLUGIN_ROOT}", root) in text
    sections = build_sections()
    for key in expected_keys("verification"):
        assert sections[key].replace("${CLAUDE_PLUGIN_ROOT}", root) in text, key


def test_the_plugin_root_is_substituted_and_every_reference_file_exists_ac_211_1():  # AC-211.1
    text = briefing.build("batch:t1,t2", "build")
    assert "${CLAUDE_PLUGIN_ROOT}" not in text
    assert str(briefing.PLUGIN_ROOT) == str(PLUGIN)
    paths = re.findall(re.escape(str(PLUGIN)) + r"/[\w./-]+\.md", text)
    assert paths, "the briefing names reference files under the plugin root"
    for p in paths:
        assert Path(p).is_file(), p


def test_the_plugin_root_argument_decides_the_root_that_is_printed_ac_211_1(tmp_path):  # AC-211.1
    root = copy_plugin(tmp_path)
    text = briefing.build("task:t1", "build", root)
    assert "${CLAUDE_PLUGIN_ROOT}" not in text and str(root) in text and str(PLUGIN) not in text


def test_the_build_instructions_stay_one_source_so_a_changed_section_shows_in_the_briefing_ac_211_1(tmp_path):  # AC-211.1
    root = copy_plugin(tmp_path)
    edit(root, "commands/build.md", "## Phase 5 — Container image\n", "## Phase 5 — Container image\nMARKER-211 one line.\n")
    assert "MARKER-211 one line." in briefing.build("verification", "build", root)
    assert "MARKER-211 one line." not in briefing.build("task:t1", "build", root)


# ---------------- AC-211.2: exactly the mapped sections ----------------

@pytest.mark.parametrize("unit,command,mapping_key", UNITS)
def test_each_units_headings_are_the_general_ones_plus_its_mapping_ac_211_2(unit, command, mapping_key):  # AC-211.2
    assert briefing.headings(unit, command) == expected_keys(mapping_key)
    assert build_headings(briefing.build(unit, command)) == expected_keys(mapping_key)


def test_plan_and_land_of_a_ship_hold_no_phase_section_ac_211_2():  # AC-211.2
    for unit in ("plan", "land"):
        assert briefing.headings(unit, "ship") == ["cplat", "Rules"]


def test_the_mapping_in_code_is_the_mapping_of_the_spec_ac_211_2():  # AC-211.2
    assert {k: tuple(v) for k, v in briefing.MAPPING.items()} == MAPPING
    assert tuple(briefing.GENERAL) == ("cplat", "Rules")


def test_the_headings_come_in_build_md_order_ac_211_2():  # AC-211.2
    order = list(build_sections())
    for unit, command, _ in UNITS:
        keys = briefing.headings(unit, command)
        assert keys == sorted(keys, key=order.index)


# ---------------- AC-211.3: a missing mapped heading, an orphan section ----------------

def test_the_released_instructions_pass_every_guard_ac_211_3():  # AC-211.3
    assert briefing.problems() == []
    assert rc211.check_real_repo() == []


def test_a_renamed_mapped_heading_fails_naming_it_ac_211_3(tmp_path):  # AC-211.3
    root = copy_plugin(tmp_path)
    edit(root, "commands/build.md", "## Phase 5 — Container image", "## Stage 5 — Container image")
    found = of(briefing.problems(root), "briefing-heading")
    assert found and any("Phase 5" in p.message and "is missing" in p.message for p in found)
    assert all(p.file.endswith("commands/build.md") for p in found)


def test_a_removed_mapped_subsection_fails_naming_it_ac_211_3(tmp_path):  # AC-211.3
    root = copy_plugin(tmp_path)
    edit(root, "commands/build.md", "### 2.2 Worktree probe", "Worktree probe")
    assert any('"2.2"' in p.message for p in of(briefing.problems(root), "briefing-heading"))


def test_a_section_that_belongs_to_no_unit_fails_naming_it_ac_211_3(tmp_path):  # AC-211.3
    root = copy_plugin(tmp_path)
    edit(root, "commands/build.md", "## Rules\n", "## Phase 8 — Something new\nText.\n\n### 8.1 Deeper\nMore.\n\n## Rules\n")
    found = of(briefing.problems(root), "briefing-orphan")
    messages = " ".join(p.message for p in found)
    assert "Phase 8 — Something new" in messages and "8.1 Deeper" in messages
    assert all("belongs to no unit" in p.message for p in found)


def test_the_rules_check_fails_for_a_missing_heading_and_an_orphan_ac_211_3(tmp_path):  # AC-211.3
    root = rc211.tree(tmp_path)
    edit(root, "plugins/component/commands/build.md", "## Phase 6 — Close the spec", "## Stage 6 — Close the spec")
    rc, out, _ = rc211.run_cli(root)
    assert rc == 1
    assert any(ln.startswith("FAIL briefing-heading ") and "Phase 6" in ln for ln in out.splitlines())
    assert any(ln.startswith("FAIL briefing-orphan ") and "Stage 6" in ln for ln in out.splitlines())


def test_the_rules_check_with_only_names_the_instruction_files_ac_211_3(tmp_path):  # AC-211.3
    root = rc211.tree(tmp_path)
    edit(root, "plugins/component/commands/build.md", "## Phase 6 — Close the spec", "## Stage 6 — Close the spec")
    for only in ("plugins/component/commands/build.md", "plugins/component/references/unit-mode.md", "plugins/component"):
        _, out, _ = rc211.run_cli(root, "--only", only)
        assert "FAIL briefing-heading" in out, only


# ---------------- AC-211.4: references a slice would lose ----------------

def refs(problems):
    return sorted((p.message for p in of(problems, "briefing-ref")))


def test_a_phase_reference_the_briefing_does_not_hold_fails_naming_unit_and_reference_ac_211_4(tmp_path):  # AC-211.4
    root = copy_plugin(tmp_path)
    edit(root, "commands/build.md", "## Phase 6 — Close the spec\n", "## Phase 6 — Close the spec\nStop as in Phase 2 when a test fails.\n")
    found = of(briefing.problems(root), "briefing-ref")
    assert any("unit verification" in p.message and '"Phase 2"' in p.message and "holds no such section" in p.message for p in found)
    assert not any("unit batch" in p.message and '"Phase 2"' in p.message for p in found)


def test_a_numbered_section_reference_fails_naming_it_ac_211_4(tmp_path):  # AC-211.4
    root = copy_plugin(tmp_path)
    edit(root, "commands/build.md", "## Phase 6 — Close the spec\n", "## Phase 6 — Close the spec\nSee 2.4a for the re-plan.\n")
    found = of(briefing.problems(root), "briefing-ref")
    assert any("unit verification" in p.message and '"2.4a"' in p.message for p in found)


def test_phases_and_longer_numbers_are_no_references_ac_211_4(tmp_path):  # AC-211.4
    root = copy_plugin(tmp_path)
    before = refs(briefing.problems(root))
    edit(root, "commands/build.md", "## Phase 6 — Close the spec\n", "## Phase 6 — Close the spec\nPhases 1 and 2 ran; version 4.14.1 is pinned.\n")
    assert refs(briefing.problems(root)) == before


def test_a_reference_to_a_section_the_briefing_holds_is_fine_ac_211_4(tmp_path):  # AC-211.4
    root = copy_plugin(tmp_path)
    before = refs(briefing.problems(root))
    edit(root, "commands/build.md", "## Phase 6 — Close the spec\n", "## Phase 6 — Close the spec\nSee Phase 4 and 2.5 first.\n")
    assert refs(briefing.problems(root)) == before


def test_the_rules_check_reports_a_lost_reference_ac_211_4(tmp_path):  # AC-211.4
    root = rc211.tree(tmp_path)
    edit(root, "plugins/component/commands/build.md", "## Phase 6 — Close the spec\n", "## Phase 6 — Close the spec\nStop as in Phase 2.\n")
    rc, out, _ = rc211.run_cli(root)
    assert rc == 1 and any(ln.startswith("FAIL briefing-ref ") and "unit verification" in ln and "Phase 2" in ln for ln in out.splitlines())


# ---------------- AC-211.5: the general part ----------------

def lacking(monkeypatch, strip):
    """`briefing.build` as it is, with `strip(text)` applied to every unit's briefing (`problems` calls `build` through the module)."""
    import briefing as module
    real = module.build

    def build(unit, command, root=None):
        return strip(real(unit, command, root))
    monkeypatch.setattr(module, "build", build)


def test_a_briefing_without_the_general_paragraph_fails_naming_the_unit_ac_211_5(monkeypatch):  # AC-211.5
    lacking(monkeypatch, lambda t: "\n".join(ln for ln in t.splitlines() if not ln.startswith("A rule marked **Hard rule:**")))
    found = of(briefing.problems(), "briefing-general")
    assert found and all(p.message.startswith("unit ") for p in found)
    assert {p.message.split(":")[0] for p in found} >= {"unit plan", "unit red-tests", "unit verification", "unit land"}


def test_a_briefing_without_the_rules_section_fails_naming_the_unit_ac_211_5(monkeypatch):  # AC-211.5
    def strip(text):
        out, skip = [], False
        for ln in text.splitlines():
            if ln == "## Rules":
                skip = True
            elif ln.startswith(FALLBACK_LINE):
                skip = False
            if not skip:
                out.append(ln)
        return "\n".join(out)
    lacking(monkeypatch, strip)
    found = of(briefing.problems(), "briefing-general")
    assert found and all(p.message.startswith("unit ") for p in found)
    assert any("## Rules" in p.message for p in found)


def test_a_briefing_without_a_bullet_of_the_unit_rules_fails_naming_the_unit_ac_211_5(monkeypatch):  # AC-211.5
    first = unit_rules_bullets()[0]
    lacking(monkeypatch, lambda t: "\n".join(ln for ln in t.splitlines() if ln != first))
    found = of(briefing.problems(), "briefing-general")
    assert found and all(p.message.startswith("unit ") for p in found)
    assert any(first[2:40] in p.message for p in found)


def test_a_briefing_without_a_general_part_is_reported_by_the_rules_check_ac_211_5(tmp_path):  # AC-211.5
    root = rc211.tree(tmp_path)
    edit(root, "plugins/component/commands/build.md", "A rule marked **Hard rule:**", "Rules marked **Hard rule:**")
    rc, out, _ = rc211.run_cli(root)
    assert rc == 1 and "FAIL briefing-general" in out


# ---------------- AC-211.6: failure and fallback ----------------

def test_an_unknown_unit_is_refused_naming_the_known_units_ac_211_6():  # AC-211.6
    with pytest.raises(briefing.UnknownUnit) as e:
        briefing.kind("bogus", "ship")
    assert str(e.value) == f"unknown unit 'bogus'; known units: {KNOWN}"
    for bad in ("batch:", "task:", "task:t1,t2", "red", ""):
        with pytest.raises(briefing.UnknownUnit):
            briefing.kind(bad, "build")


def test_unreadable_instructions_make_the_briefing_unavailable_with_a_reason_ac_211_6(tmp_path):  # AC-211.6
    with pytest.raises(briefing.BriefingUnavailable) as e:
        briefing.build("task:t1", "ship", tmp_path / "nowhere")
    assert e.value.reason.startswith("cannot read ")


def test_a_mapped_heading_missing_at_run_time_makes_it_unavailable_ac_211_6(tmp_path):  # AC-211.6
    root = copy_plugin(tmp_path)
    edit(root, "commands/build.md", "## Phase 5 — Container image", "## Stage 5 — Container image")
    with pytest.raises(briefing.BriefingUnavailable) as e:
        briefing.build("verification", "ship", root)
    assert e.value.reason.startswith('heading "Phase 5" missing from ')
    assert briefing.build("task:t1", "ship", root)          # a unit that does not map it still gets its briefing


@pytest.mark.parametrize("unit,command,_", UNITS)
def test_every_briefing_ends_with_the_fallback_line_ac_211_6(unit, command, _):  # AC-211.6
    last = briefing.build(unit, command).rstrip("\n").splitlines()[-1]
    assert last == f"{FALLBACK_LINE} {briefing.PLUGIN_ROOT}/commands/build.md"
