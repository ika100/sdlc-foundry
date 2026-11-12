"""Spec 184 acceptance tests: a land settles a conflict in the ADR index (AC-184.6).

Both entries land: `cplat component ship land` (`ship`) and `cplat pr wait --merge` (`pr`). The world is the land world of spec 171 (a
bare repository for GitHub, a `gh` stub that answers from it); the index and the ADR files are seeded on `main` and on the branch,
then each side adds its own, so the merge of `main` into the branch conflicts in `docs/adr/README.md` and nowhere else.
"""
import re

import pytest

from land184_world import (adr_file, assert_landed_by_a_signed_merge_of_main, assert_stopped_clean, base_adrs, conflicts,
                           git, land, make_world, merged_head, on_branch, on_main, row, seed, show, with_rows)
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)

ENTRIES = ["ship", "pr"]
TABLE = re.compile(r"^\| \[(\d{3})\]\((\d{3}-[^)]+\.md)\) \| (.*) \|$", re.M)


@pytest.fixture()
def world(tmp_path, monkeypatch):
    w = make_world(tmp_path, monkeypatch)
    seed(w, base_adrs())
    return w


def rows_of(text):
    return [(n, f, d) for n, f, d in TABLE.findall(text)]


def main_adds(world, number, slug, extra=None):
    index = world.bare_git("show", "main:docs/adr/README.md")
    on_main(world, {"docs/adr/README.md": with_rows(index, row(number, slug, slug.capitalize())),
                    f"docs/adr/{number}-{slug}.md": adr_file(number, slug.capitalize()), **(extra or {})})


def branch_adds(world, number, slug, extra=None):
    index = (world.repo / "docs" / "adr" / "README.md").read_text()
    on_branch(world, {"docs/adr/README.md": with_rows(index, row(number, slug, slug.capitalize())),
                      f"docs/adr/{number}-{slug}.md": adr_file(number, slug.capitalize()), **(extra or {})})


def test_the_resolver_handles_the_adr_index_and_the_rule_registers_only_ac_184_6():  # AC-184.6
    import land_resolve
    assert land_resolve.handles("docs/adr/README.md")
    assert land_resolve.handles("docs/rules/plugins/svc/commands/demo.yml") and land_resolve.handles("docs/rules/register.yml")
    for path in ("docs/backlog.md", "f.txt", "docs/adr/001-first.md", "docs/rules/README.md", "plugins/svc/commands/demo.md"):
        assert not land_resolve.handles(path), path


# ---------------- the union of both sides ----------------

@pytest.mark.parametrize("entry", ENTRIES)
def test_both_sides_add_an_adr_and_the_index_is_the_union_sorted_by_number_ac_184_6(world, capsys, entry):  # AC-184.6
    branch_adds(world, "005", "branch-thing")
    main_adds(world, "004", "main-thing")
    assert conflicts(world), "the setup is a real conflict of the index"
    before = world.pr_head()
    rc, out, err = land(world, entry, capsys)
    assert rc == 0, out + err
    head = merged_head(world)
    assert_landed_by_a_signed_merge_of_main(world, before, head)
    text = show(world, head, "docs/adr/README.md")
    assert "<<<<<<<" not in text and ">>>>>>>" not in text
    assert [n for n, _, _ in rows_of(text)] == ["001", "002", "003", "004", "005"]
    assert dict((n, f) for n, f, _ in rows_of(text))["005"] == "005-branch-thing.md"
    assert text.startswith("# Architecture decision records\n\nIntro text of the index.\n\n| ADR | Decision |\n|---|---|\n")
    assert text.endswith("\nClosing note of the index.\n")
    for name in ("001-first", "004-main-thing", "005-branch-thing"):
        assert show(world, head, f"docs/adr/{name}.md") is not None
    assert not [ln for ln in out.splitlines() if ln.startswith("renumbered ")]          # no clash, no renumbering


@pytest.mark.parametrize("entry", ENTRIES)
def test_a_clash_renumbers_the_branchs_adr_everywhere_it_is_named_ac_184_6(world, capsys, entry):  # AC-184.6
    notes = ("ADR-004 is ours.\nSee docs/adr/004-branch-thing.md and ADR-004 again.\nADR-0041 is something else.\n")
    branch_adds(world, "004", "branch-thing", {"docs/notes.md": notes, "docs/untouched.md": "nothing to see\n"})
    main_adds(world, "004", "main-thing", {"docs/main-notes.md": "ADR-004 is the one of main.\n"})
    assert conflicts(world)
    before = world.pr_head()
    rc, out, err = land(world, entry, capsys)
    assert rc == 0, out + err
    head = merged_head(world)
    assert_landed_by_a_signed_merge_of_main(world, before, head)
    assert [ln for ln in out.splitlines() if ln.startswith("renumbered ")] == ["renumbered ADR-004 to ADR-005 (3 references)"]
    assert show(world, head, "docs/adr/004-branch-thing.md") is None
    assert show(world, head, "docs/adr/004-main-thing.md") == adr_file("004", "Main-thing")        # main's ADR keeps its number
    assert show(world, head, "docs/adr/005-branch-thing.md") == adr_file("005", "Branch-thing")    # file name and title
    index = show(world, head, "docs/adr/README.md")
    assert rows_of(index) == [("001", "001-first.md", "First decision"), ("002", "002-second.md", "Second decision"),
                              ("003", "003-third.md", "Third decision"), ("004", "004-main-thing.md", "Main-thing"),
                              ("005", "005-branch-thing.md", "Branch-thing")]
    assert show(world, head, "docs/notes.md") == ("ADR-005 is ours.\nSee docs/adr/005-branch-thing.md and ADR-005 again.\n"
                                                  "ADR-0041 is something else.\n")
    assert show(world, head, "docs/main-notes.md") == "ADR-004 is the one of main.\n"          # a file of main's is not rewritten
    assert show(world, head, "docs/untouched.md") == "nothing to see\n"


@pytest.mark.parametrize("entry", ENTRIES)
def test_two_clashes_are_renumbered_lowest_first_to_the_next_free_numbers_ac_184_6(world, capsys, entry):  # AC-184.6
    notes = "ADR-004 and ADR-004 here.\nADR-005 and ADR-005 there.\n"
    branch_adds(world, "004", "first-branch", {"docs/notes.md": notes})
    branch_adds(world, "005", "second-branch")
    main_adds(world, "004", "main-one")
    main_adds(world, "005", "main-two")
    assert conflicts(world)
    rc, out, err = land(world, entry, capsys)
    assert rc == 0, out + err
    head = merged_head(world)
    assert [ln for ln in out.splitlines() if ln.startswith("renumbered ")] == [
        "renumbered ADR-004 to ADR-006 (2 references)", "renumbered ADR-005 to ADR-007 (2 references)"]
    assert show(world, head, "docs/notes.md") == "ADR-006 and ADR-006 here.\nADR-007 and ADR-007 there.\n"
    assert [n for n, _, _ in rows_of(show(world, head, "docs/adr/README.md"))] == ["001", "002", "003", "004", "005", "006", "007"]
    for old in ("004-first-branch", "005-second-branch"):
        assert show(world, head, f"docs/adr/{old}.md") is None
    assert show(world, head, "docs/adr/006-first-branch.md").startswith("# ADR-006: ")
    assert show(world, head, "docs/adr/007-second-branch.md").startswith("# ADR-007: ")


def test_a_row_that_one_side_removed_and_the_other_left_is_dropped_ac_184_6(world, capsys):  # AC-184.6
    index = (world.repo / "docs" / "adr" / "README.md").read_text()
    branch_adds(world, "004", "branch-thing")
    on_main(world, {"docs/adr/README.md": index.replace("| [003](003-third.md) | Third decision |\n", ""), "docs/adr/003-third.md": None})
    assert conflicts(world)
    rc, out, err = land(world, "ship", capsys)
    assert rc == 0, out + err
    text = show(world, merged_head(world), "docs/adr/README.md")
    assert [n for n, _, _ in rows_of(text)] == ["001", "002", "004"]


# ---------------- what stays a person's decision ----------------

@pytest.mark.parametrize("entry", ENTRIES)
def test_a_row_both_sides_changed_differently_stops_the_land_ac_184_6(world, capsys, entry):  # AC-184.6
    index = (world.repo / "docs" / "adr" / "README.md").read_text()
    on_branch(world, {"docs/adr/README.md": index.replace("Second decision", "Second decision, as the branch words it")})
    on_main(world, {"docs/adr/README.md": index.replace("Second decision", "Second decision, as main words it")})
    assert conflicts(world)
    tip, head = git(world.repo, "rev-parse", "HEAD"), world.pr_head()
    rc, out, err = land(world, entry, capsys)
    assert rc == 1
    assert_stopped_clean(world, tip, head, err)
    assert "docs/adr/README.md" in err


@pytest.mark.parametrize("entry", ENTRIES)
def test_a_conflict_in_the_text_around_the_table_stops_the_land_ac_184_6(world, capsys, entry):  # AC-184.6
    index = (world.repo / "docs" / "adr" / "README.md").read_text()
    on_branch(world, {"docs/adr/README.md": index.replace("Intro text", "Intro text, branch")})
    on_main(world, {"docs/adr/README.md": index.replace("Intro text", "Intro text, main")})
    assert conflicts(world)
    tip, head = git(world.repo, "rev-parse", "HEAD"), world.pr_head()
    rc, out, err = land(world, entry, capsys)
    assert rc == 1
    assert_stopped_clean(world, tip, head, err)
    assert "docs/adr/README.md outside its table" in err


@pytest.mark.parametrize("entry", ENTRIES)
def test_a_conflict_in_another_file_as_well_stops_the_land_ac_184_6(world, capsys, entry):  # AC-184.6
    branch_adds(world, "005", "branch-thing", {"f.txt": "one\nfeature line\nthree\n"})
    main_adds(world, "004", "main-thing", {"f.txt": "one\nmain line\nthree\n"})
    assert conflicts(world)
    tip, head = git(world.repo, "rev-parse", "HEAD"), world.pr_head()
    rc, out, err = land(world, entry, capsys)
    assert rc == 1
    assert_stopped_clean(world, tip, head, err)
    assert "f.txt" in err


@pytest.mark.parametrize("entry", ENTRIES)
def test_the_index_rounds_share_the_limit_of_three_per_land_ac_184_6(world, capsys, entry):  # AC-184.6
    branch_adds(world, "020", "branch-thing")                       # last in the table: every row main adds conflicts with it
    main_adds(world, "004", "main-thing")
    start = world.pr_head()
    numbers = iter(["010", "011", "012"])
    world.on_new_head_checks(lambda: main_adds(world, next(numbers), "later"), times=3)      # main moves after every pushed head
    rc, out, err = land(world, entry, capsys)
    assert rc == 1 and world.events("merged") == []
    assert "rebase is a human decision" in err
    assert int(world.bare_git("rev-list", "--merges", "--count", f"{start}..{world.pr_head()}")) == 3
    assert git(world.repo, "status", "--porcelain") == ""
