"""Spec 132 acceptance tests: changelog fragments that the release assembles (AC-132.1 .. AC-132.13, #321).

Contract: design.md. The release runs offline in platrelease_world (spec 129); release-check runs in the mini platform of the spec 121
tests. AC-132.11/.12 call the old changelog and plugin version tests with a changed changelog or bumped plugins."""
import re
import subprocess

import pytest

from platrelease_world import CHANGELOG, NOTES, DAY, moved_changelog, w  # noqa: F401  (w is a fixture)
from system_fixtures import ROOT

BRANCH = "release/5.5.0"
FRAG = "docs/changelog.d"


# ---------------- AC-132.1: the fragment format ----------------

def test_a_fragment_names_its_section_in_the_file_name_ac_132_1():  # AC-132.1
    import platrelease_changelog as cl
    assert cl.FRAGMENTS == "docs/changelog.d"
    assert cl.parse_fragment("321-changelog-fragments.added.md", "**New.** Text (#321).\n") == ("Added", "**New.** Text (#321).")
    assert cl.parse_fragment("400-x.changed.md", "c\n")[0] == "Changed"
    assert cl.parse_fragment("132-y.fixed.md", "f")[0] == "Fixed"


def test_read_fragments_skips_the_readme_and_sorts_by_name_ac_132_1(tmp_path):  # AC-132.1
    import platrelease_changelog as cl
    d = tmp_path / FRAG
    d.mkdir(parents=True)
    (d / "README.md").write_text("# how to\n")
    (d / "500-b.fixed.md").write_text("b\n")
    (d / "400-a.added.md").write_text("a\n")
    assert cl.read_fragments(tmp_path) == [("400-a.added.md", "a\n"), ("500-b.fixed.md", "b\n")]
    assert cl.read_fragments(tmp_path / "nowhere") == []


def test_the_fragment_readme_describes_the_format_ac_132_1():  # AC-132.1
    text = (ROOT / FRAG / "README.md").read_text()
    assert "<id>-<slug>.<added|changed|fixed>.md" in text
    assert "cplat platform release" in text and "../" in text


# ---------------- AC-132.2: assembly ----------------

UNREL = "Loose text.\n\n### Fixed\n\n**Old fix.** x.\n\n### Removed\n\n**Gone.** y.\n\n### Added\n\n**Old add.** z.\n"


def test_assembly_orders_added_changed_fixed_then_others_unreleased_first_ac_132_2():  # AC-132.2
    import platrelease_changelog as cl
    frags = [("500-b.fixed.md", "**New fix B.**\n"), ("400-a.fixed.md", "**New fix A.**\n"), ("450-c.changed.md", "**Chg.**\n"),
             ("460-d.added.md", "**New add.**\n")]
    out = cl.assemble(UNREL, sorted(frags))
    assert out.strip().startswith("Loose text.")
    heads = re.findall(r"(?m)^### (.+)$", out)
    assert heads == ["Added", "Changed", "Fixed", "Removed"]
    fixed = out.split("### Fixed")[1].split("###")[0]
    assert fixed.index("**Old fix.**") < fixed.index("**New fix A.**") < fixed.index("**New fix B.**")
    added = out.split("### Added")[1].split("###")[0]
    assert added.index("**Old add.**") < added.index("**New add.**")
    assert "\n\n**New fix A.**\n\n**New fix B.**" in fixed


def test_move_unreleased_puts_the_fragments_under_the_new_heading_ac_132_2():  # AC-132.2
    import platrelease_changelog as cl
    text = "# CHANGELOG\n\n## [Unreleased]\n\n### Fixed\n\n**Old.** a.\n\n## [5.4.0] — 2026-05-01\n\nold\n"
    out = cl.move_unreleased(text, "5.5.0", "2026-06-15", [("400-a.added.md", "**New.** b.\n")])
    assert out == ("# CHANGELOG\n\n## [Unreleased]\n\n## [5.5.0] - 2026-06-15\n\n### Added\n\n**New.** b.\n\n### Fixed\n\n**Old.** a.\n\n"
                   "## [5.4.0] — 2026-05-01\n\nold\n")


def test_fragments_alone_make_a_section_ac_132_2():  # AC-132.2
    import platrelease_changelog as cl
    out = cl.assemble("", [("1-a.fixed.md", "**F.**\n"), ("2-b.added.md", "**A.**\n")])
    assert out.strip() == "### Added\n\n**A.**\n\n### Fixed\n\n**F.**"


def push_fragments(w, files: dict, changelog: str | None = None) -> None:
    for name, text in files.items():
        p = w.repo / FRAG / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    if changelog is not None:
        (w.repo / "docs/CHANGELOG.md").write_text(changelog)
    w.git("add", "-A")
    w.git("commit", "-q", "-m", "docs: fragments")
    w.git("push", "-q", "origin", "main")


FRAGS = {"README.md": "# Changelog fragments\n", "410-new-thing.added.md": "**A new thing (#410).** It is new.\n",
         "420-a-fix.fixed.md": "**A fix (#420).** See [ADR-078](../adr/078-x.md).\n"}


def test_the_release_assembles_unreleased_and_fragments_on_the_branch_ac_132_2(w):  # AC-132.2
    push_fragments(w, FRAGS)
    r = w.run()
    assert r.rc == 3 and "CONFIRM: merge" in r.out, r.text
    text = w.git("show", f"{BRANCH}:docs/CHANGELOG.md")
    section = text.split(f"## [5.5.0] - {DAY.isoformat()}")[1].split("## [5.4.0]")[0]
    assert section.index(NOTES.split("\n")[0]) < section.index("### Added") < section.index("**A new thing (#410).**") \
        < section.index("### Fixed") < section.index("**A fix (#420).**")
    assert text.split("## [Unreleased]")[1].split("## [5.5.0]")[0].strip() == ""


# ---------------- AC-132.3: the release commit deletes the fragments ----------------

def test_the_release_commit_deletes_the_fragments_and_keeps_the_readme_ac_132_3(w):  # AC-132.3
    push_fragments(w, FRAGS)
    assert w.run().rc == 3
    files = w.git("ls-tree", "-r", "--name-only", f"origin/{BRANCH}", FRAG).split()
    assert files == [f"{FRAG}/README.md"]
    changed = sorted(w.git("diff", "--name-only", f"origin/main...origin/{BRANCH}").split())
    assert changed == sorted(["docs/CHANGELOG.md", f"{FRAG}/410-new-thing.added.md", f"{FRAG}/420-a-fix.fixed.md"])
    assert w.ahead(f"origin/{BRANCH}") == 1
    body = w.git("log", "-1", "--format=%B", f"origin/{BRANCH}")
    assert body.splitlines()[0] == "chore: release 5.5.0" and "Signed-off-by:" in body
    a = w.created[0]
    assert "2 fragment(s) of docs/changelog.d" in a[a.index("--body") + 1]
    assert w.git("status", "--porcelain").strip() == ""


# ---------------- AC-132.4: links ----------------

def test_relative_links_are_rewritten_for_the_changelog_ac_132_4():  # AC-132.4
    import platrelease_changelog as cl
    body = ("See [ADR](../adr/078-x.md), [spec](../specs/132-y/spec.md#ac), [web](https://example.com/../a), [top](#x), "
            "[here](README.md).\n")
    _, out = cl.parse_fragment("1-a.added.md", body)
    assert "[ADR](adr/078-x.md)" in out and "[spec](specs/132-y/spec.md#ac)" in out
    assert "[web](https://example.com/../a)" in out and "[top](#x)" in out


def test_the_release_rewrites_links_ac_132_4(w):  # AC-132.4
    push_fragments(w, FRAGS)
    assert w.run().rc == 3
    text = w.git("show", f"{BRANCH}:docs/CHANGELOG.md")
    assert "[ADR-078](adr/078-x.md)" in text and "../adr" not in text


# ---------------- AC-132.5: without fragments nothing changes ----------------

def test_without_fragments_the_release_is_unchanged_ac_132_5(w):  # AC-132.5
    import platrelease_changelog as cl
    assert cl.move_unreleased(CHANGELOG, "5.5.0", DAY.isoformat()) == moved_changelog("5.5.0")
    assert cl.move_unreleased(CHANGELOG, "5.5.0", DAY.isoformat(), []) == moved_changelog("5.5.0")
    push_fragments(w, {"README.md": "# Changelog fragments\n"})
    assert w.run().rc == 3
    assert w.git("show", f"{BRANCH}:docs/CHANGELOG.md") == moved_changelog("5.5.0")
    a = w.created[0]
    assert a[a.index("--body") + 1] == ("Release 5.5.0: [Unreleased] of docs/CHANGELOG.md moved under ## [5.5.0].\n"
                                        "Opened by cplat platform release.")
    assert w.git("diff", "--name-only", f"origin/main...origin/{BRANCH}").split() == ["docs/CHANGELOG.md"]


# ---------------- AC-132.6: preflight ----------------

def test_fragments_count_as_content_in_the_preflight_ac_132_6(w):  # AC-132.6
    push_fragments(w, FRAGS, changelog=CHANGELOG.replace(NOTES, ""))
    r = w.run()
    assert r.rc == 3 and "has no content" not in r.err, r.text
    assert "**A new thing (#410).**" in w.git("show", f"{BRANCH}:docs/CHANGELOG.md")


def test_neither_text_nor_fragments_still_stops_the_run_ac_132_6(w):  # AC-132.6
    push_fragments(w, {"README.md": "# Changelog fragments\n"}, changelog=CHANGELOG.replace(NOTES, ""))
    r = w.run()
    assert r.rc == 1 and "## [Unreleased] in docs/CHANGELOG.md has no content" in r.err


# ---------------- AC-132.7: invalid fragments ----------------

@pytest.mark.parametrize("name, text", [("321-x.md", "body"), ("321-x.security.md", "body"), ("321-x.added.txt", "body"),
                                        ("321-x.added.md", "  \n\n")])
def test_an_invalid_fragment_is_an_error_naming_the_file_ac_132_7(name, text):  # AC-132.7
    import platrelease_changelog as cl
    with pytest.raises(cl.FragmentError) as e:
        cl.parse_fragment(name, text)
    assert f"docs/changelog.d/{name}" in str(e.value) and "<id>-<slug>.<added|changed|fixed>.md" in str(e.value)


def test_read_fragments_rejects_a_stray_file_ac_132_7(tmp_path):  # AC-132.7
    import platrelease_changelog as cl
    (tmp_path / FRAG).mkdir(parents=True)
    (tmp_path / FRAG / "notes.txt").write_text("x\n")
    with pytest.raises(cl.FragmentError, match="notes.txt"):
        cl.read_fragments(tmp_path)


def test_an_invalid_fragment_stops_the_release_before_a_branch_ac_132_7(w):  # AC-132.7
    push_fragments(w, {"321-oops.feature.md": "x\n"})
    r = w.run()
    assert r.rc == 1 and "docs/changelog.d/321-oops.feature.md" in r.err and "<id>-<slug>.<added|changed|fixed>.md" in r.err
    assert not [b for b in w.git("branch", "--list").split() if b.startswith("release/")]
    assert w.created == []


def rows_world(tmp_path, fragments: dict, unreleased: str = ""):
    from test_upgrade_121_ops import KEDA_PATCH, changelog_with, git, mini_platform, patch_render
    root = mini_platform(tmp_path)
    patch_render(root, KEDA_PATCH)
    (root / "docs" / "CHANGELOG.md").write_text(changelog_with(unreleased))
    for name, text in fragments.items():
        (root / FRAG).mkdir(parents=True, exist_ok=True)
        (root / FRAG / name).write_text(text)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "candidate")
    return root


def test_release_check_rows_fails_on_an_invalid_fragment_ac_132_7(tmp_path):  # AC-132.7
    from test_upgrade_121_ops import KEDA_LINE, rows_check
    root = rows_world(tmp_path, {"README.md": "x\n", "400-keda.added.md": KEDA_LINE + "\n", "401-bad-name.md": "y\n"})
    rc, out = rows_check(root)
    assert rc == 1 and re.search(r"(?m)^ERROR: .*docs/changelog\.d/401-bad-name\.md", out), out


# ---------------- AC-132.8: release-check rows reads fragments ----------------

def test_a_row_listed_in_a_fragment_counts_as_listed_ac_132_8(tmp_path):  # AC-132.8
    from test_upgrade_121_ops import KEDA_LINE, rows_check
    root = rows_world(tmp_path, {"README.md": "x\n", "400-keda.changed.md": "**Keda.** Bumped.\n\n" + KEDA_LINE + "\n"})
    rc, out = rows_check(root)
    assert rc == 0, out


def test_a_row_missing_from_text_and_fragments_still_fails_ac_132_8(tmp_path):  # AC-132.8
    from test_upgrade_121_ops import rows_check
    root = rows_world(tmp_path, {"400-other.fixed.md": "**Other.** x.\n"})
    rc, out = rows_check(root)
    assert rc == 1 and "does not list - `operator keda` 2.19.0 → 2.20.0" in out, out


# ---------------- AC-132.9: the unreleased text for the proposal ----------------

def test_unreleased_text_includes_the_fragments_ac_132_9(tmp_path):  # AC-132.9
    import platrelease_changelog as cl
    (tmp_path / FRAG).mkdir(parents=True)
    (tmp_path / "docs" / "CHANGELOG.md").write_text("# CHANGELOG\n\n## [Unreleased]\n\n## [5.4.0] — 2026-05-01\n\nold\n")
    (tmp_path / FRAG / "README.md").write_text("x\n")
    (tmp_path / FRAG / "400-a.fixed.md").write_text("**Fix.** a.\n")
    text = cl.unreleased_text(tmp_path)
    assert re.findall(r"(?m)^### (.+)$", text) == ["Fixed"] and "**Fix.** a." in text
    (tmp_path / FRAG / "401-b.added.md").write_text("**Add.** b.\n")
    assert re.findall(r"(?m)^### (.+)$", cl.unreleased_text(tmp_path)) == ["Added", "Fixed"]


# ---------------- AC-132.10: guidance ----------------

@pytest.mark.parametrize("path", ["CONTRIBUTING.md", "CLAUDE.md", ".github/PULL_REQUEST_TEMPLATE.md"])
def test_the_guidance_names_a_fragment_ac_132_10(path):  # AC-132.10
    text = (ROOT / path).read_text()
    assert "docs/changelog.d/" in text and "<id>-<slug>.<added|changed|fixed>.md" in text
    assert not re.search(r"(?i)(add|has) a line under `?(## )?\[Unreleased\]", text), path


# ---------------- AC-132.11: changelog tests find their release by the version heading ----------------

NOISE = ("**A later entry (#999).** Since spec 115, spec 116, spec 117, spec 118, spec 119, spec 120, spec 121, spec 125, spec 128 and "
         "spec 130 (ADR-057, ADR-059, ADR-060, ADR-061, ADR-062, ADR-064, ADR-065, ADR-066, ADR-068, ADR-072, ADR-074, #316, "
         "checked nothing) something BREAKING changed.\n\n")

CHANGELOG_TESTS = [
    ("test_resources_115_cmds", "test_the_changelog_lists_the_change_in_a_minor_section_that_is_not_breaking_ac_115_16"),
    ("test_bucket_116_cmds", "test_the_changelog_lists_the_bucket_in_a_minor_section_that_is_not_breaking_ac_116_20"),
    ("test_backup_117_cmds", "test_the_changelog_announces_spec_117_as_a_minor_change_with_the_pins_ac_117_26"),
    ("test_cache_118_cmds", "test_the_changelog_lists_the_cache_in_a_minor_section_that_is_not_breaking_ac_118_22"),
    ("test_broker_119_cmds", "test_the_changelog_lists_the_broker_in_a_minor_section_that_is_not_breaking_ac_119_15"),
    ("test_scale_120_cmds", "test_the_changelog_lists_scaling_above_the_broker_in_a_minor_section_that_is_not_breaking_ac_120_25"),
    ("test_upgrade_121_ops", "test_the_changelog_lists_the_upgrade_entry_above_scaling_with_every_changed_row_ac_121_23"),
    ("test_cluster_125_delivery", "test_ac_125_18_the_changelog_announces_a_non_breaking_minor"),
    ("test_credentials_128_records", "test_the_changelog_entry_names_the_issue_and_the_symptom_ac_128_14"),
    ("test_credentials_128_records", "test_the_changelog_entry_names_the_resource_types_and_releases_ac_128_14"),
    ("test_credentials_128_records", "test_the_changelog_entry_names_the_fix_and_that_nothing_is_to_do_ac_128_14"),
    ("test_130_empty_gates", "test_the_changelog_lists_the_behaviour_change_with_symptom_and_fix_ac_130_16"),
]


@pytest.mark.parametrize("module, name", CHANGELOG_TESTS)
def test_old_changelog_tests_survive_a_new_entry_naming_their_spec_ac_132_11(monkeypatch, module, name):  # AC-132.11
    import importlib

    import release_support
    real = release_support.text()
    noisy = real.replace("## [Unreleased]\n", "## [Unreleased]\n\n" + NOISE, 1)
    assert noisy != real
    monkeypatch.setattr(release_support, "text", lambda: noisy)
    getattr(importlib.import_module(module), name)()


def test_section_reads_a_release_by_its_heading_ac_132_11(monkeypatch):  # AC-132.11
    import release_support
    monkeypatch.setattr(release_support, "text", lambda: "# C\n\n## [Unreleased]\n\nspec 9 new\n\n## [5.4.0] — 2026-10-28\n\nspec 9 old\n"
                                                          "\n## [5.3.0] — x\n\nolder\n")
    assert release_support.section("5.4.0") == "## [5.4.0] — 2026-10-28\n\nspec 9 old\n"
    with pytest.raises(AssertionError):
        release_support.section("9.9.9")


# ---------------- AC-132.12: plugin versions with >= ----------------

VERSION_TESTS = [
    ("test_backup_117_cmds", "test_the_resource_plugin_is_1_3_0_and_has_backup_and_restore_commands_ac_117_31"),
    ("test_backup_117_cmds", "test_the_system_plugin_is_1_1_0_and_has_the_restore_command_ac_117_19"),
    ("test_cache_118_cmds", "test_the_resource_plugin_is_1_4_0_in_both_places_ac_118_22"),
    ("test_broker_119_cmds", "test_the_resource_and_api_plugins_are_bumped_in_both_places_ac_119_4"),
    ("test_upgrade_121_ops", "test_the_resource_platform_and_system_plugins_are_bumped_in_both_places_ac_121_6"),
]


@pytest.mark.parametrize("module, name", VERSION_TESTS)
def test_plugin_version_tests_survive_a_later_bump_ac_132_12(monkeypatch, module, name):  # AC-132.12
    import importlib

    import release_support
    monkeypatch.setattr(release_support, "plugin_versions", lambda plugin: ("9.0.0", "9.0.0"))
    getattr(importlib.import_module(module), name)()


@pytest.mark.parametrize("module, name", VERSION_TESTS)
def test_plugin_version_tests_still_catch_a_mismatch_or_an_old_version_ac_132_12(monkeypatch, module, name):  # AC-132.12
    import importlib

    import release_support
    for got in (("9.0.0", "8.0.0"), ("1.0.0", "1.0.0")):
        monkeypatch.setattr(release_support, "plugin_versions", lambda plugin, got=got: got)
        with pytest.raises(AssertionError):
            getattr(importlib.import_module(module), name)()


def test_at_least_compares_versions_numerically_ac_132_12():  # AC-132.12
    import release_support
    assert release_support.at_least("1.10.0", "1.6.1") and release_support.at_least("1.6.1", "1.6.1")
    assert not release_support.at_least("1.6.0", "1.6.1")


# ---------------- AC-132.13: this change's own entry ----------------

def test_this_change_has_its_entry_and_it_is_a_fragment_until_released_ac_132_13():  # AC-132.13
    import platrelease_changelog as cl
    import release_support
    where, para = release_support.entry(r"#321\b")
    assert "fragment" in para.lower() and "docs/changelog.d" in para
    assert "#321" not in cl.unreleased_body(release_support.text()), "the entry is a fragment, not a line under [Unreleased]"
    if where.startswith("fragment"):
        assert re.fullmatch(r"fragment docs/changelog\.d/321-[a-z0-9-]+\.(added|changed|fixed)\.md", where), where
    else:
        assert re.fullmatch(r"\[\d+\.\d+\.\d+\]", where), where


def test_entry_searches_fragments_then_every_section_ac_132_13(monkeypatch):  # AC-132.13
    import release_support
    monkeypatch.setattr(release_support, "text", lambda: "# C\n\n## [Unreleased]\n\n## [5.4.0] — x\n\n**Old (#7).** a.\n\nother\n")
    monkeypatch.setattr(release_support, "fragments", lambda: [("8-b.fixed.md", "**New (#8).** b.\n")])
    assert release_support.entry(r"#8\b") == ("fragment docs/changelog.d/8-b.fixed.md", "**New (#8).** b.")
    assert release_support.entry(r"#7\b") == ("[5.4.0]", "**Old (#7).** a.")
    with pytest.raises(AssertionError):
        release_support.entry(r"#9\b")


def test_the_git_tree_has_no_stray_fragment_ac_132_7():  # AC-132.7
    import platrelease_changelog as cl
    names = subprocess.run(["git", "ls-files", FRAG], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    for n in names:
        name = n.split("/")[-1]
        if name != "README.md":
            cl.parse_fragment(name, (ROOT / n).read_text())


def test_fix_fragments_alone_propose_a_patch_346(tmp_path):
    """#346 with spec 132: the version proposal reads the fragments too; fix fragments alone make a patch."""
    import platrelease_state as st
    (tmp_path / "docs" / "changelog.d").mkdir(parents=True)
    (tmp_path / "docs" / "CHANGELOG.md").write_text("# CHANGELOG\n\n## [Unreleased]\n\n## [5.6.1] - 2026-11-03\n\nOld.\n")
    (tmp_path / "docs" / "changelog.d" / "1-a-fix.fixed.md").write_text("**A fix (#1).** Text.\n")
    assert st.proposal("v5.6.1", [], st._unreleased(tmp_path))[0] == "5.6.2"
    (tmp_path / "docs" / "changelog.d" / "2-a-feature.added.md").write_text("**A feature (#2).** Text.\n")
    assert st.proposal("v5.6.1", [], st._unreleased(tmp_path))[0] == "5.7.0"
