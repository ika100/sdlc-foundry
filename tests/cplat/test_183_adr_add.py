"""Spec 183 acceptance tests: `cplat adr add <slug> --decision "<one line>"` (AC-183.3)."""
import datetime

import pytest

import core
import cplat
import spec
from support_183 import commit_all, git

INDEX = """# Architecture decision records

Intro text.

| ADR | Decision |
|---|---|
| [001](001-first.md) | First decision |
| [002](002-second.md) | Second decision |

Closing note without a table.
"""


def repo_with_adrs(tmp_path, index=INDEX):
    repo = tmp_path / "repo"
    git(tmp_path, "init", "-q", "-b", "main", str(repo))
    adr = repo / "docs" / "adr"
    adr.mkdir(parents=True)
    (adr / "001-first.md").write_text("# ADR-001: First\n")
    (adr / "002-second.md").write_text("# ADR-002: Second\n")
    if index is not None:
        (adr / "README.md").write_text(index)
    commit_all(repo, "init")
    return repo


def add(repo, capsys, *args):
    capsys.readouterr()
    rc = cplat.main(["adr", "add", "--repo", str(repo), "--offline", *args])
    out = capsys.readouterr()
    return rc, out.out, out.err


def snapshot(repo):
    return {str(p.relative_to(repo)): p.read_bytes() for p in sorted(repo.rglob("*")) if p.is_file() and ".git" not in p.parts}


def test_the_template_asset_exists_ac_183_3():  # AC-183.3
    assert (core.PLATFORM_ROOT / "scripts" / "cplat" / "assets" / "adr-template.md").is_file()


def test_adr_add_writes_the_adr_and_one_index_row_ac_183_3(tmp_path, capsys):  # AC-183.3
    repo = repo_with_adrs(tmp_path)
    assert spec.main(["--repo", str(repo), "adr-next", "--offline"]) == 0
    expected_number = capsys.readouterr().out.strip()
    assert expected_number == "003"
    rc, out, err = add(repo, capsys, "use-fast-cache", "--decision", "Use a fast cache")
    assert rc == 0, err
    assert out.strip() == "docs/adr/003-use-fast-cache.md"
    text = (repo / "docs" / "adr" / "003-use-fast-cache.md").read_text()
    assert text.startswith("# ADR-003: Use fast cache\n")
    assert f"**Status:** Proposed ({datetime.date.today().isoformat()})" in text
    assert "## Context" in text and "## Consequences" in text
    assert "## Decision\n\nUse a fast cache\n" in text
    new_index = (repo / "docs" / "adr" / "README.md").read_text()
    row = "| [003](003-use-fast-cache.md) | Use a fast cache |\n"
    assert new_index == INDEX.replace("| Second decision |\n", "| Second decision |\n" + row)


def test_a_pipe_and_a_newline_in_the_decision_are_made_safe_ac_183_3(tmp_path, capsys):  # AC-183.3
    repo = repo_with_adrs(tmp_path)
    rc, _, err = add(repo, capsys, "split-it", "--decision", "a | b\n  and   c")
    assert rc == 0, err
    assert "| [003](003-split-it.md) | a \\| b and c |\n" in (repo / "docs" / "adr" / "README.md").read_text()


def test_an_index_without_a_table_gets_one_and_a_missing_index_is_created_ac_183_3(tmp_path, capsys):  # AC-183.3
    repo = repo_with_adrs(tmp_path, index="# ADRs\n\nNo table yet.\n")
    rc, _, err = add(repo, capsys, "first-row", "--decision", "D")
    assert rc == 0, err
    assert (repo / "docs" / "adr" / "README.md").read_text() == (
        "# ADRs\n\nNo table yet.\n\n| ADR | Decision |\n|---|---|\n| [003](003-first-row.md) | D |\n")
    other = tmp_path / "other"
    other.mkdir()
    repo2 = repo_with_adrs(other, index=None)
    rc, _, err = add(repo2, capsys, "no-index", "--decision", "D2")
    assert rc == 0, err
    assert (repo2 / "docs" / "adr" / "README.md").read_text() == (
        "# Architecture decision records\n\n| ADR | Decision |\n|---|---|\n| [003](003-no-index.md) | D2 |\n")


@pytest.mark.parametrize("args, reason", [
    (["Bad_Slug", "--decision", "D"], "lowercase words joined by hyphens"),
    (["two--hyphens", "--decision", "D"], "lowercase words joined by hyphens"),
    (["fine-slug", "--decision", "  \n "], "--decision is empty"),
    (["first", "--decision", "D"], "already used"),
])
def test_a_bad_slug_decision_or_used_slug_writes_nothing_ac_183_3(tmp_path, capsys, args, reason):  # AC-183.3
    repo = repo_with_adrs(tmp_path)
    before = snapshot(repo)
    rc, out, err = add(repo, capsys, *args)
    assert rc != 0 and reason in err and err.startswith("ERROR")
    assert out.strip() == ""
    assert snapshot(repo) == before


def test_a_missing_decision_is_a_usage_error_ac_183_3(tmp_path, capsys):  # AC-183.3
    repo = repo_with_adrs(tmp_path)
    before = snapshot(repo)
    with pytest.raises(SystemExit) as exc:
        add(repo, capsys, "some-slug")
    assert exc.value.code == 2
    assert snapshot(repo) == before
