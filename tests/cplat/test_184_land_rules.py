"""Spec 184 acceptance tests: a land settles a conflict in a prompt's rule register (AC-184.7).

The land world of spec 171, with a small platform tree seeded on `main` and on the branch (a prompt, its register file
`docs/rules/plugins/svc/commands/demo.yml` and `docs/rules/register.yml`, as in spec 168's tests). Main adds a rule sentence at the top
of the prompt and an entry at the end of the register file, the branch a sentence at the bottom and an entry at the end: the prompt
merges as text, the register file conflicts, and nothing else does.
"""
import subprocess
from pathlib import Path

import pytest
import yaml

from land184_world import (assert_landed_by_a_signed_merge_of_main, assert_stopped_clean, conflicts, git, land, make_world, merged_head,
                           on_branch, on_main, seed, show)
from rules_support import R1, R2, e, entries_text, prompt_text, register_text
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)

ENTRIES = ["ship", "pr"]
PROMPT = "plugins/svc/commands/demo.md"
YML = "docs/rules/plugins/svc/commands/demo.yml"
REGISTER = "docs/rules/register.yml"
BODY = f"{R1}\n\n- {R2}\n"
M = "Always run the lint step before committing, because a red lint job blocks the merge."
F = "Always write the report last, since the reader starts from its final lines."
BASE = [e("R1", "Always run the tests first", "practice", source="#476"), e("R2", "Never skip the lint step", "practice", source="#478")]
R_MAIN = e("R3", "Always run the lint step before committing", "practice", source="#900")
R_BRANCH = e("R3", "Always write the report last", "practice", source="#901")
NOTES = "Rule R3 asks for the report.\nSee R3 and R30 and XR3.\n"


def base_files(header=""):
    return {PROMPT: prompt_text(BODY), YML: header + entries_text(BASE), REGISTER: register_text({}, 10_000_000)}


@pytest.fixture()
def world(tmp_path, monkeypatch):
    w = make_world(tmp_path, monkeypatch)
    seed(w, base_files())
    return w


def main_adds(world, entry=R_MAIN, sentence=M):
    on_main(world, {PROMPT: prompt_text(sentence + "\n\n" + BODY), YML: entries_text([*BASE, entry])})


def branch_adds(world, entry=R_BRANCH, sentence=F, extra=None):
    on_branch(world, {PROMPT: prompt_text(BODY + "\n" + sentence + "\n"), YML: entries_text([*BASE, entry]), **(extra or {})})


def entries_in(world, head):
    return [(r["id"], r["text"]) for r in yaml.safe_load(show(world, head, YML))["rules"]]


def rules_check_passes(world, head, tmp_path):
    import rulescheck
    clone = tmp_path / "check"
    subprocess.run(["git", "clone", "-q", str(world.bare), str(clone)], check=True)
    git(clone, "checkout", "-q", head)
    result = rulescheck.check(Path(clone))
    assert result.ok, rulescheck.render(result)


@pytest.mark.parametrize("entry", ENTRIES)
def test_an_id_both_sides_added_is_renumbered_with_its_references_and_the_check_passes_ac_184_7(world, capsys, entry, tmp_path):  # AC-184.7
    branch_adds(world, extra={"docs/notes.md": NOTES})
    main_adds(world)
    on_main(world, {"docs/main-notes.md": "R3 is the rule of main.\n", "docs/untouched.md": "R3 is not ours here\n"})  # not a branch file
    assert conflicts(world), "the setup is a real conflict of the register file"
    before = world.pr_head()
    rc, out, err = land(world, entry, capsys)
    assert rc == 0, out + err
    head = merged_head(world)
    assert_landed_by_a_signed_merge_of_main(world, before, head)
    assert entries_in(world, head) == [("R1", "Always run the tests first"), ("R2", "Never skip the lint step"),
                                       ("R3", "Always run the lint step before committing"), ("R4", "Always write the report last")]
    assert [ln for ln in out.splitlines() if ln.startswith("renumbered ")] == ["renumbered R3 to R4 in docs/notes.md (2 references)"]
    assert show(world, head, "docs/notes.md") == "Rule R4 asks for the report.\nSee R4 and R30 and XR3.\n"     # word-bounded, branch files only
    assert show(world, head, "docs/untouched.md") == "R3 is not ours here\n"
    assert show(world, head, "docs/main-notes.md") == "R3 is the rule of main.\n"
    prompt = show(world, head, PROMPT)
    assert M in prompt and F in prompt and "<<<<<<<" not in prompt
    rules_check_passes(world, head, tmp_path)


@pytest.mark.parametrize("entry", ENTRIES)
def test_entries_with_different_ids_are_kept_without_a_renumbering_ac_184_7(world, capsys, entry, tmp_path):  # AC-184.7
    branch_adds(world, entry=e("R4", "Always write the report last", "practice", source="#901"))
    main_adds(world)
    assert conflicts(world)
    rc, out, err = land(world, entry, capsys)
    assert rc == 0, out + err
    head = merged_head(world)
    assert [i for i, _ in entries_in(world, head)] == ["R1", "R2", "R3", "R4"]
    assert dict(entries_in(world, head))["R4"] == "Always write the report last"
    assert not [ln for ln in out.splitlines() if ln.startswith("renumbered ")]
    rules_check_passes(world, head, tmp_path)


# ---------------- what stays a person's decision ----------------

@pytest.mark.parametrize("entry", ENTRIES)
def test_a_conflict_in_the_header_of_a_register_file_stops_the_land_ac_184_7(tmp_path, monkeypatch, capsys, entry):  # AC-184.7
    world = make_world(tmp_path, monkeypatch)
    seed(world, base_files(header="# register of the demo prompt\n"))
    text = (world.repo / YML).read_text()
    on_branch(world, {YML: text.replace("demo prompt", "demo prompt, branch")})
    on_main(world, {YML: text.replace("demo prompt", "demo prompt, main")})
    assert conflicts(world)
    tip, head = git(world.repo, "rev-parse", "HEAD"), world.pr_head()
    rc, out, err = land(world, entry, capsys)
    assert rc == 1
    assert_stopped_clean(world, tip, head, err)
    assert f"{YML} outside its id-keyed entries" in err


@pytest.mark.parametrize("entry", ENTRIES)
def test_an_entry_both_sides_changed_differently_stops_the_land_ac_184_7(world, capsys, entry):  # AC-184.7
    text = (world.repo / YML).read_text()
    on_branch(world, {YML: text.replace("Always run the tests first", "Always run the tests first, on the branch")})
    on_main(world, {YML: text.replace("Always run the tests first", "Always run the tests first, on main")})
    assert conflicts(world)
    tip, head = git(world.repo, "rev-parse", "HEAD"), world.pr_head()
    rc, out, err = land(world, entry, capsys)
    assert rc == 1
    assert_stopped_clean(world, tip, head, err)
    assert "R1" in err


@pytest.mark.parametrize("entry", ENTRIES)
def test_a_conflict_in_the_baseline_of_register_yml_stops_the_land_ac_184_7(world, capsys, entry):  # AC-184.7
    text = (world.repo / REGISTER).read_text()
    on_branch(world, {REGISTER: text.replace("10000000", "10000001")})
    on_main(world, {REGISTER: text.replace("10000000", "10000002")})
    assert conflicts(world)
    tip, head = git(world.repo, "rev-parse", "HEAD"), world.pr_head()
    rc, out, err = land(world, entry, capsys)
    assert rc == 1
    assert_stopped_clean(world, tip, head, err)
    assert REGISTER in err


@pytest.mark.parametrize("entry", ENTRIES)
def test_a_conflict_in_another_file_as_well_stops_the_land_ac_184_7(world, capsys, entry):  # AC-184.7
    branch_adds(world, extra={"f.txt": "one\nfeature line\nthree\n"})
    main_adds(world)
    on_main(world, {"f.txt": "one\nmain line\nthree\n"})
    assert conflicts(world)
    tip, head = git(world.repo, "rev-parse", "HEAD"), world.pr_head()
    rc, out, err = land(world, entry, capsys)
    assert rc == 1
    assert_stopped_clean(world, tip, head, err)
    assert "f.txt" in err


@pytest.mark.parametrize("entry", ENTRIES)
def test_generated_block_adr_index_and_rule_register_rounds_share_one_limit_of_three_ac_184_7(tmp_path, monkeypatch, capsys, entry):  # AC-184.7
    from land184_world import adr_file, base_adrs, row, with_rows
    world = make_world(tmp_path, monkeypatch)
    seed(world, {**base_adrs(), **base_files()})
    world.feature_adds_spec(199)                                                          # the branch: a spec, an ADR, a rule
    index = (world.repo / "docs" / "adr" / "README.md").read_text()
    branch_adds(world, extra={"docs/adr/README.md": with_rows(index, row("005", "branch-thing", "Branch-thing")),
                              "docs/adr/005-branch-thing.md": adr_file("005", "Branch-thing")})
    world.other_adds_spec(108)                                                            # round 1: the backlog index conflicts
    assert conflicts(world)
    start = world.pr_head()

    def main_adds_an_adr():                                                               # round 2: the ADR index
        text = world.bare_git("show", "main:docs/adr/README.md")
        on_main(world, {"docs/adr/README.md": with_rows(text, row("004", "main-thing", "Main-thing")),
                        "docs/adr/004-main-thing.md": adr_file("004", "Main-thing")})

    moves = iter([main_adds_an_adr, lambda: main_adds(world), lambda: world.other_adds_spec(110)])   # rounds 2, 3 (rule), 4 (backlog)
    world.on_new_head_checks(lambda: next(moves)(), times=3)
    tip = git(world.repo, "rev-parse", "HEAD")
    rc, out, err = land(world, entry, capsys)
    assert rc == 1 and world.events("merged") == []
    assert "rebase is a human decision" in err
    assert int(world.bare_git("rev-list", "--merges", "--count", f"{start}..{world.pr_head()}")) == 3     # three rounds of three kinds, no fourth
    assert git(world.repo, "status", "--porcelain") == ""
    assert git(world.repo, "rev-parse", "HEAD") == world.pr_head() != tip


@pytest.mark.parametrize("entry", ENTRIES)
def test_a_result_the_rules_check_refuses_stops_the_land_naming_its_first_failure_ac_184_7(world, capsys, entry):  # AC-184.7
    on_branch(world, {YML: entries_text([*BASE, R_BRANCH])})          # an entry for a sentence the prompt does not have
    main_adds(world)
    assert conflicts(world)
    tip, head = git(world.repo, "rev-parse", "HEAD"), world.pr_head()
    rc, out, err = land(world, entry, capsys)
    assert rc == 1
    assert_stopped_clean(world, tip, head, err)
    assert "stale-entry" in err or "matches no rule sentence" in err
