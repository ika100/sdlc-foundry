"""Spec 211 acceptance tests: `cplat spec test-diff` finds its base when none is given (AC-211.8).

Seam: `spec.main(["--repo", root, "test-diff", ...])` and `cplat.main(["spec", "test-diff"])` on a small git repo with one `building`
spec (spec 160's `g` helper, spec 007's files) and commits whose subject is "acceptance tests for <spec id>". The contract is
design.md section 6."""
import pytest

import cplat
import spec
from test_160_lint_suppressions import g
from test_spec import make

SPEC_ID = "007-price-alerts"
SUBJECT = f"test(price-alerts): acceptance tests for {SPEC_ID}"
ALERTS = "# AC-007.1\ndef test_alert():\n    password = 'x'\n    assert send(password)\n"


def commit(root, msg):
    g("add", "-A", cwd=root)
    g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", msg, cwd=root)
    return g("rev-parse", "HEAD", cwd=root).strip()


def world(tmp_path, subject=SUBJECT):
    """main: spec 007 `building`, then the commit `subject` with tests/test_alerts.py."""
    root = tmp_path / "r"
    root.mkdir(parents=True)
    g("init", "-q", "-b", "main", cwd=root)
    make(root, status="building")
    (root / "tests").mkdir()
    commit(root, "chore: init")
    (root / "tests" / "test_alerts.py").write_text(ALERTS)
    return root, commit(root, subject)


def weaken(root):
    t = root / "tests" / "test_alerts.py"
    t.write_text(t.read_text().replace("assert send(password)", "send(password)"))
    commit(root, "feat: the coder weakens a test")


def run(root, monkeypatch, capsys, *argv):
    monkeypatch.chdir(root)
    capsys.readouterr()
    rc = spec.main(["--repo", str(root), "test-diff", *argv])
    out = capsys.readouterr()
    return rc, out.out, out.err


def second_spec(root):
    src = root / "docs" / "specs" / SPEC_ID
    dst = root / "docs" / "specs" / "008-other-thing"
    dst.mkdir()
    for f in src.iterdir():
        dst.joinpath(f.name).write_text(f.read_text().replace(SPEC_ID, "008-other-thing").replace("AC-007", "AC-008"))
    commit(root, "docs: a second building spec")


# ---------------- AC-211.8 ----------------

def test_without_a_base_the_latest_acceptance_tests_commit_is_the_base_ac_211_8(tmp_path, monkeypatch, capsys):  # AC-211.8
    root, red = world(tmp_path)
    rc, out, _ = run(root, monkeypatch, capsys)
    assert rc == 0 and out.splitlines()[0] == f"base: {red[:7]} (acceptance tests for {SPEC_ID})"
    assert "no acceptance test changed" in out


def test_it_then_behaves_exactly_as_with_that_commit_given_ac_211_8(tmp_path, monkeypatch, capsys):  # AC-211.8
    root, red = world(tmp_path)
    weaken(root)
    rc_given, given, _ = run(root, monkeypatch, capsys, red)
    rc, found, _ = run(root, monkeypatch, capsys)
    assert rc == rc_given == 1 and "tests/test_alerts.py: changed" in given
    assert found == f"base: {red[:7]} (acceptance tests for {SPEC_ID})\n" + given


def test_the_latest_of_several_commits_is_taken_ac_211_8(tmp_path, monkeypatch, capsys):  # AC-211.8
    root, first = world(tmp_path)
    (root / "tests" / "test_more.py").write_text("# AC-007.2\ndef test_more():\n    assert 1\n")
    latest = commit(root, f"test(price-alerts): reviewed acceptance tests for {SPEC_ID}")
    rc, out, _ = run(root, monkeypatch, capsys)
    assert out.splitlines()[0] == f"base: {latest[:7]} (acceptance tests for {SPEC_ID})" and latest != first


OPTIONS = {
    "by": ["--by", "t1"],
    "task": ["--task", "t1"],
    "tighten": ["--tighten", "tests/test_alerts.py", "--task", "t1", "--reason", "harness fix"],
    "approve": ["--approve", "tests/test_alerts.py", "--task", "t1", "--reason", "the person approved it"],
}


@pytest.mark.parametrize("name", sorted(OPTIONS))
def test_the_options_work_without_a_base_too_ac_211_8(name, tmp_path, monkeypatch, capsys):  # AC-211.8
    """Each option, with and without the base, on its own copy of the repo (`--approve` and `--tighten` write their record)."""
    opts = OPTIONS[name]
    given_root, red = world(tmp_path / "given")
    weaken(given_root)
    rc_given, given, _ = run(given_root, monkeypatch, capsys, red, *opts)
    found_root, red2 = world(tmp_path / "found")
    weaken(found_root)
    rc, found, _ = run(found_root, monkeypatch, capsys, *opts)
    assert found.splitlines()[0] == f"base: {red2[:7]} (acceptance tests for {SPEC_ID})"
    assert rc == rc_given
    assert found.split("\n", 1)[1].replace(red2[:7], "BASE") == given.replace(red[:7], "BASE")


def test_a_given_base_behaves_as_today_and_prints_no_found_line_ac_211_8(tmp_path, monkeypatch, capsys):  # AC-211.8
    root, red = world(tmp_path)
    rc, out, _ = run(root, monkeypatch, capsys, red)
    assert rc == 0 and "(acceptance tests for" not in out


def test_no_such_commit_exits_2_and_checks_nothing_ac_211_8(tmp_path, monkeypatch, capsys):  # AC-211.8
    root, _ = world(tmp_path, subject="test: something else")
    monkeypatch.chdir(root)
    capsys.readouterr()
    assert cplat.main(["spec", "test-diff"]) == 2
    err = capsys.readouterr().err
    assert "ERROR: no base: " in err and f'no commit "acceptance tests for {SPEC_ID}"' in err
    assert "pass it: cplat spec test-diff <base>" in err


def test_more_than_one_building_spec_and_a_branch_naming_none_exits_2_ac_211_8(tmp_path, monkeypatch, capsys):  # AC-211.8
    root, _ = world(tmp_path)
    second_spec(root)
    monkeypatch.chdir(root)
    capsys.readouterr()
    assert cplat.main(["spec", "test-diff"]) == 2
    err = capsys.readouterr().err
    assert "ERROR: no base: 2 building specs and the branch main names none of them" in err
    assert "pass it: cplat spec test-diff <base>" in err


def test_the_branch_names_the_spec_among_several_ac_211_8(tmp_path, monkeypatch, capsys):  # AC-211.8
    root, red = world(tmp_path)
    second_spec(root)
    g("checkout", "-q", "-b", f"feature/{SPEC_ID}", cwd=root)
    rc, out, _ = run(root, monkeypatch, capsys)
    assert out.splitlines()[0] == f"base: {red[:7]} (acceptance tests for {SPEC_ID})"


def test_no_building_spec_exits_2_ac_211_8(tmp_path, monkeypatch, capsys):  # AC-211.8
    root, _ = world(tmp_path)
    md = root / "docs" / "specs" / SPEC_ID / "spec.md"
    md.write_text(md.read_text().replace("status: building", "status: approved"))
    commit(root, "docs: not building")
    monkeypatch.chdir(root)
    capsys.readouterr()
    assert cplat.main(["spec", "test-diff"]) == 2
    assert "ERROR: no base: no building spec" in capsys.readouterr().err
