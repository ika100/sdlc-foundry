"""Spec 183 acceptance tests: spec numbers shared across main, pushed branches and open PRs (AC-183.1, AC-183.2)."""
import pytest

import spec
from support_183 import add_spec, fake_gh, world


@pytest.fixture(autouse=True)
def no_shape(monkeypatch):
    monkeypatch.setattr(spec, "repo_shape", lambda root: None)


def new(repo, capsys, title="Fresh feature"):
    capsys.readouterr()
    rc = spec.main(["--repo", str(repo), "new", "--no-shape", title])
    out = capsys.readouterr()
    return rc, out.out, out.err


def test_new_takes_one_more_than_main_branches_and_open_prs_ac_183_1(tmp_path, monkeypatch, capsys):  # AC-183.1
    repo = world(tmp_path, main_specs=("175-base",), branches={"other/x": ["176-theirs"]})
    fake_gh(tmp_path, monkeypatch, prs={659: ["docs/specs/177-prspec/spec.md", "docs/specs/177-prspec/plan.md"]})
    rc, out, err = new(repo, capsys)
    assert rc == 0
    assert out.strip().splitlines()[0] == "docs/specs/178-fresh-feature/spec.md"
    assert (repo / "docs" / "specs" / "178-fresh-feature" / "spec.md").is_file()
    assert err.strip() == ""


def test_new_counts_a_number_only_an_open_pr_holds_ac_183_1(tmp_path, monkeypatch, capsys):  # AC-183.1
    repo = world(tmp_path, main_specs=("175-base",))
    fake_gh(tmp_path, monkeypatch, prs={12: ["docs/specs/190-far/spec.md"], 13: ["README.md"]})
    rc, out, _ = new(repo, capsys)
    assert rc == 0 and out.strip().splitlines()[0] == "docs/specs/191-fresh-feature/spec.md"


def test_unreadable_open_prs_warn_once_and_use_main_and_branches_ac_183_1(tmp_path, monkeypatch, capsys):  # AC-183.1
    repo = world(tmp_path, main_specs=("175-base",), branches={"other/x": ["176-theirs"]})
    fake_gh(tmp_path, monkeypatch, fail=True)
    rc, out, err = new(repo, capsys)
    assert rc == 0
    assert out.strip().splitlines()[0] == "docs/specs/177-fresh-feature/spec.md"
    lines = [ln for ln in err.splitlines() if ln.strip()]
    assert len(lines) == 1 and "open PRs were not checked" in lines[0]


def test_next_number_returns_the_number_and_the_warning_ac_183_1(tmp_path, monkeypatch):  # AC-183.1
    import specnumbers
    repo = world(tmp_path, main_specs=("175-base",), branches={"other/x": ["176-theirs"]})
    fake_gh(tmp_path, monkeypatch, prs={5: ["docs/specs/177-prspec/spec.md"]})
    assert specnumbers.next_number(repo) == (178, None)
    fake_gh(tmp_path, monkeypatch, fail=True)
    number, warning = specnumbers.next_number(repo)
    assert number == 177 and "open PRs were not checked" in warning


def test_a_branch_number_another_branch_holds_is_a_check_error_ac_183_2(tmp_path, monkeypatch, capsys):  # AC-183.2
    repo = world(tmp_path, main_specs=("175-base",), branches={"other/x": ["176-theirs"]})
    fake_gh(tmp_path, monkeypatch, prs={})
    add_spec(repo, "176-mine")
    capsys.readouterr()
    assert spec.main(["--repo", str(repo), "check"]) == 1
    out = capsys.readouterr().out
    assert "176" in out and "176-mine" in out and "176-theirs" in out and "origin/other/x" in out and "cplat spec new" in out


def test_a_number_an_open_pr_holds_is_a_check_error_ac_183_2(tmp_path, monkeypatch, capsys):  # AC-183.2
    repo = world(tmp_path, main_specs=("175-base",))
    fake_gh(tmp_path, monkeypatch, prs={659: ["docs/specs/176-prs/spec.md"]})
    add_spec(repo, "176-mine")
    capsys.readouterr()
    assert spec.main(["--repo", str(repo), "check"]) == 1
    out = capsys.readouterr().out
    assert "176-mine" in out and "176-prs" in out and "open PR #659" in out and "cplat spec new" in out


def test_clashes_names_each_place_once_and_a_free_number_passes_ac_183_2(tmp_path, monkeypatch):  # AC-183.2
    import specnumbers
    repo = world(tmp_path, main_specs=("175-base",), branches={"a/one": ["176-x"], "a/two": ["176-y"]})
    fake_gh(tmp_path, monkeypatch, prs={7: ["docs/specs/176-z/spec.md"]})
    add_spec(repo, "176-mine")
    errors, warning = specnumbers.clashes(repo)
    assert warning is None and len(errors) == 3
    assert any("origin/a/one" in e for e in errors) and any("origin/a/two" in e for e in errors) and any("open PR #7" in e for e in errors)
    add_spec(repo, "179-free")
    (repo / "docs" / "specs" / "176-mine" / "spec.md").unlink()
    (repo / "docs" / "specs" / "176-mine").rmdir()
    assert specnumbers.clashes(repo) == ([], None)


def test_unreadable_prs_warn_but_branches_are_still_checked_ac_183_2(tmp_path, monkeypatch):  # AC-183.2
    import specnumbers
    repo = world(tmp_path, main_specs=("175-base",), branches={"a/one": ["176-x"]})
    fake_gh(tmp_path, monkeypatch, fail=True)
    add_spec(repo, "176-mine")
    errors, warning = specnumbers.clashes(repo)
    assert len(errors) == 1 and "origin/a/one" in errors[0]
    assert warning and "open PRs were not checked" in warning
