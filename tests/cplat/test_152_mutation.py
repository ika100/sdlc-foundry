"""Spec 152 acceptance tests: `cplat spec mutate` (report only).

Seams: a real git repo under tmp_path with `src/` on main and a feature branch; `spec.repo_shape` set to service-python;
`mutation.run_tests` replaced by a check that loads the mutated module and runs the given assertions."""
import subprocess

import pytest

import mutation
import spec
from test_spec import make

BASE = "def is_adult(age):\n    return False\n"
CHANGED = "def is_adult(age):\n    return age >= 18\n"


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(spec, "repo_shape", lambda root: "service-python")
    (tmp_path / "src/app").mkdir(parents=True)
    (tmp_path / "src/app/rules.py").write_text(BASE)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_rules.py").write_text("def test_ac_007_1(): ...  # AC-007.1\n")
    make(tmp_path, plan=False)
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.name", "t")
    git(tmp_path, "config", "user.email", "t@t")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "base")
    git(tmp_path, "checkout", "-qb", "feature/007")
    (tmp_path / "src/app/rules.py").write_text(CHANGED)
    git(tmp_path, "commit", "-qam", "feature")
    return tmp_path


def passing_when(*cases):
    """A run_tests stand-in: the module passes when is_adult(age) == want for every (age, want)."""
    def run(root, files):
        ns: dict = {}
        exec((root / "src/app/rules.py").read_text(), ns)
        return all(ns["is_adult"](age) == want for age, want in cases)
    return run


# ---------------- AC-152.1 ----------------

def test_strong_tests_kill_every_mutant_of_the_changed_line_ac_152_1(repo, monkeypatch):  # AC-152.1
    monkeypatch.setattr(mutation, "run_tests", passing_when((18, True), (17, False)))
    r = mutation.mutate(repo, "007", base="main")
    assert r["status"] == "done" and r["mutants"] == 3 and r["killed"] == 3 and r["survivors"] == []
    assert (repo / "src/app/rules.py").read_text() == CHANGED          # restored


def test_a_weak_test_lets_the_boundary_mutant_survive_ac_152_1(repo, monkeypatch):  # AC-152.1
    monkeypatch.setattr(mutation, "run_tests", passing_when((30, True)))
    r = mutation.mutate(repo, "007", base="main")
    assert r["killed"] < r["mutants"] and "src/app/rules.py:2 18 → 19" in r["survivors"]
    assert (repo / "src/app/rules.py").read_text() == CHANGED


def test_only_changed_lines_are_mutated_and_the_count_is_capped_ac_152_1(repo, monkeypatch):  # AC-152.1
    (repo / "src/app/rules.py").write_text(CHANGED + "\n\ndef old():\n    return 1 == 2\n")
    git(repo, "commit", "-qam", "more")
    git(repo, "checkout", "-q", "main")
    (repo / "src/app/rules.py").write_text("def old():\n    return 1 == 2\n")
    git(repo, "commit", "-qam", "old on main")
    git(repo, "checkout", "-q", "feature/007")
    found = mutation.mutants(repo, mutation.changed_lines(repo, "main"), 50)
    assert {m.line for m in found} <= {1, 2, 3, 4, 5, 6}
    assert len(mutation.mutants(repo, mutation.changed_lines(repo, "main"), 2)) == 2


# ---------------- AC-152.2 ----------------

def test_write_puts_the_report_into_verification_md_once_ac_152_2(repo, monkeypatch):  # AC-152.2
    monkeypatch.setattr(mutation, "run_tests", passing_when((30, True)))
    vdir = spec.find(repo, "007").dir
    (vdir / "verification.md").write_text("# Verification\n\n**Result:** pass\n")
    for _ in range(2):
        assert spec.main(["--repo", str(repo), "mutate", "007", "--base", "main", "--write"]) == 0
    text = (vdir / "verification.md").read_text()
    assert text.startswith("# Verification") and text.count(mutation.HEADING) == 1
    assert "mutants of the changed code were caught" in text and "Survived" in text


# ---------------- AC-152.3 ----------------

def test_other_shapes_and_specs_without_tests_are_skipped_ac_152_3(repo, monkeypatch):  # AC-152.3
    md = spec.find(repo, "007").dir / "spec.md"
    md.write_text(md.read_text().replace("shape: service-python", "shape: web-nextjs"))
    assert mutation.mutate(repo, "007", base="main")["reason"] == "no mutation check for shape web-nextjs yet"
    md.write_text(md.read_text().replace("shape: web-nextjs", "shape: service-python"))
    (repo / "tests/test_rules.py").write_text("def test_x(): ...\n")
    r = mutation.mutate(repo, "007", base="main")
    assert r == {"spec": spec.find(repo, "007").id, "status": "skipped", "reason": "no test names a criterion of the spec"}


def test_red_tests_before_mutation_are_a_setup_error_ac_152_3(repo, monkeypatch):  # AC-152.3
    monkeypatch.setattr(mutation, "run_tests", lambda root, files: False)
    with pytest.raises(mutation.PlatformError, match="fail before any mutation"):
        mutation.mutate(repo, "007", base="main")
    assert (repo / "src/app/rules.py").read_text() == CHANGED


def test_the_build_runs_it_after_the_reviewer_and_never_stops_on_it_ac_152_3():  # AC-152.3
    from pathlib import Path
    build = (Path(__file__).resolve().parents[2] / "plugins/component/commands/build.md").read_text()
    verify = build[build.index("## Phase 4"):build.index("## Phase 5")]
    assert verify.index("reviewer") < verify.index("cplat spec mutate <id> --write") < verify.index("Commit `docs/specs")
    assert "cplat spec mutate" in verify
