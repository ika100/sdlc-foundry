"""Spec 109 acceptance tests, `cplat spec ci` and the shared orphan scan (AC-109.13). Contract: docs/specs/109-*/design.md,
"Orphan tests". Fixture repos use the scratch specs 901 and 902, so this file names no orphan of a real spec."""
from pathlib import Path

import pytest
from chain_support import CRITERIA, spec_text

import spec

S901 = "901-demo-chain"
S902 = "902-second"


def make_repo(root: Path, *, answers: str | None = None, tests: dict | None = None, status="approved") -> Path:
    for sid, crit in ((S901, CRITERIA), (S902, "- **AC-902.1** Given a, when b, then c.\n")):
        d = root / "docs" / "specs" / sid
        d.mkdir(parents=True)
        (d / "spec.md").write_text(spec_text(spec_id=sid, status=status, tracks=(), shape=answers or "service-python", criteria=crit))
    if answers:
        (root / ".copier-answers.yml").write_text(f"_src_path: templates/{answers}\n")
    for rel, text in (tests or {}).items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    return root


TESTS = {
    "tests/test_ok.py": "def test_a():  # AC-901.1\n    ...\n\n\ndef test_b():  # AC-901.2\n    ...\n\n\ndef test_c():  # AC-901.3\n    ...\n\n\ndef test_d():  # AC-902.1\n    ...\n",
    "tests/test_orphans.py": ("def test_old():  # AC-901.4\n    ...\n\n\ndef test_old_again():  # AC-901.4\n    ...\n\n\n"
                              "def test_typo():  # AC-901.9\n    ...\n\n\ndef test_elsewhere():  # AC-777.1\n    ...\n"),
}


def ci(capsys, root: Path, *flags: str) -> tuple[int, list[str]]:
    capsys.readouterr()
    rc = spec.main(["--repo", str(root), "ci", *flags])
    return rc, capsys.readouterr().out.splitlines()


def test_ci_warns_once_per_orphan_naming_file_id_and_kind_ac_109_13(tmp_path, capsys):  # AC-109.13
    root = make_repo(tmp_path, tests=TESTS)
    rc, lines = ci(capsys, root)
    warnings = [ln for ln in lines if "orphan" in ln or "names " in ln]
    assert f"::warning file=tests/test_orphans.py,title=spec {S901}::tests/test_orphans.py names withdrawn criterion AC-901.4" in lines
    assert f"::warning file=tests/test_orphans.py,title=spec {S901}::tests/test_orphans.py names unknown criterion AC-901.9" in lines
    assert len([ln for ln in lines if ln.startswith("::") and " names " in ln]) == 2     # AC-901.4 twice in one file: one warning
    assert "spec-check: 2 orphan test reference(s) (warnings only)" in lines
    assert not any("AC-777" in ln for ln in lines)         # no spec 777 in this repo: not reported
    assert rc == 0, warnings


def test_the_orphan_warning_stays_a_warning_with_strict_and_never_changes_the_exit_code_ac_109_13(tmp_path, capsys):  # AC-109.13
    clean = make_repo(tmp_path / "clean", tests={"tests/test_ok.py": TESTS["tests/test_ok.py"]})
    dirty = make_repo(tmp_path / "dirty", tests=TESTS)
    rc_clean, lines_clean = ci(capsys, clean, "--strict")
    rc_dirty, lines_dirty = ci(capsys, dirty, "--strict")
    assert rc_clean == 0 and rc_dirty == rc_clean
    assert not any(" names " in ln for ln in lines_clean)
    assert [ln for ln in lines_dirty if ln.startswith("::") and " names " in ln]       # the orphans are reported ...
    assert not [ln for ln in lines_dirty if ln.startswith("::error")]                  # ... as warnings only
    assert "spec-check: 2 orphan test reference(s) (warnings only)" in lines_dirty
    # the existing summary line is the same as without orphans: orphans are not counted as problems
    assert [ln for ln in lines_dirty if ln.startswith("spec-check: 2 spec(s)")] == [ln for ln in lines_clean if ln.startswith("spec-check: 2 spec(s)")]


def test_it_works_in_a_repo_of_any_shape_using_the_shapes_test_globs_ac_109_13(tmp_path, capsys):  # AC-109.13
    root = make_repo(tmp_path, answers="web-nextjs", tests={
        "tests/page.test.ts": "it('x', () => {})  // AC-901.4\n",
        "tests/helper.py": "# AC-901.9 is not in this shape's test globs\n"})
    _, lines = ci(capsys, root)
    assert f"::warning file=tests/page.test.ts,title=spec {S901}::tests/page.test.ts names withdrawn criterion AC-901.4" in lines
    assert not any("helper.py" in ln for ln in lines)


def test_the_shared_scan_returns_sorted_orphans_with_spec_and_kind_ac_109_13(tmp_path):  # AC-109.13
    root = make_repo(tmp_path, tests=TESTS)
    specs = spec.all_specs(root)
    found = spec.orphan_tests(root, specs, ["tests/**/*.py"])
    assert [(o.file, o.id, o.spec_id, o.kind) for o in found] == [
        ("tests/test_orphans.py", "AC-901.4", S901, "withdrawn"),
        ("tests/test_orphans.py", "AC-901.9", S901, "unknown")]
    only_902 = spec.orphan_tests(root, [s for s in specs if s.id == S902], ["tests/**/*.py"])
    assert only_902 == []        # ids of a spec that was not given are not examined
    assert spec.orphan_tests(root, specs, ["nothing/**/*"]) == []


@pytest.mark.parametrize("ignored", ["node_modules/x/test_n.py", ".venv/lib/test_v.py", "tests/__pycache__/test_p.py"])
def test_ignored_paths_are_not_scanned_ac_109_13(tmp_path, ignored):  # AC-109.13
    root = make_repo(tmp_path, tests={ignored: "# AC-901.9\n"})
    assert spec.orphan_tests(root, spec.all_specs(root), ["**/*.py"]) == []
