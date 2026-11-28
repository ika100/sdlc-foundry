"""Spec 223 acceptance tests: a `fixed` changelog fragment ends in a checked `Caused by:` line (AC-223.1 to AC-223.3).

Seams: a real git repo under tmp_path shaped like the platform repo (as in the spec 150 tests), a fake `gh` first on PATH
(cq223_world), and for the CI check a copy of the scripts folder in that repo."""
import json
import re
import shutil
import subprocess
import sys

import pytest

import house_rules
import platrelease_changelog as cl
from changelog_support import ROOT
from cq223_world import SLUG, fake_gh, git  # noqa: F401  (fake_gh is a fixture)

FRAG = "docs/changelog.d"
FORM = "Caused by: #<PR> | v<X.Y.Z> | none | unknown"
FIXED = "**Fix the thing (#900).** The text of the fix.\n"


@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "platform"
    (r / ".claude-plugin").mkdir(parents=True)
    (r / "plugins/svc/.claude-plugin").mkdir(parents=True)
    (r / FRAG).mkdir(parents=True)
    (r / ".claude-plugin/marketplace.json").write_text(json.dumps({"plugins": [{"name": "svc", "version": "1.0.0"}]}))
    (r / "plugins/svc/.claude-plugin/plugin.json").write_text(json.dumps({"name": "svc", "version": "1.0.0"}))
    (r / FRAG / "README.md").write_text("fragments\n")
    git(r, "init", "-q", "-b", "main")
    git(r, "add", "-A")
    git(r, "commit", "-q", "-s", "-m", "base")
    git(r, "checkout", "-q", "-b", "feature/x")
    return r


def commit(repo, path, text="x\n"):
    f = repo / path
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-s", "-m", f"change {path}")


def check(repo, notes=None, rules=("fragment",)):
    return house_rules.check(repo, title="fix(cplat): a change", body="", labels=[], base="main", fix=False, rules=rules,
                             notes=notes if notes is not None else [])


def one_problem(repo):
    problems = check(repo)[1]
    assert len(problems) == 1, problems
    return problems[0]


def fixed(repo, cause, name="900-thing.fixed.md", text=FIXED):
    commit(repo, f"{FRAG}/{name}", text + (cause + "\n" if cause is not None else ""))
    return name


# ---------------- AC-223.1: the form ----------------

@pytest.mark.parametrize("line, kind", [("Caused by: #812", "prs"), ("Caused by: #812, #815", "prs"), ("Caused by: v5.23.0", "version"),
                                        ("Caused by: none", "none"), ("Caused by: unknown", "unknown")])
def test_parse_cause_reads_the_four_forms_ac_223_1(line, kind):  # AC-223.1
    import fixcause
    cause = fixcause.parse_cause(f"**Fix.** Text (#1).\n{line}\n")
    assert cause is not None and cause.kind == kind
    if kind == "prs":
        assert cause.prs == tuple(int(n) for n in re.findall(r"#(\d+)", line))
    if kind == "version":
        assert cause.version == "5.23.0"


@pytest.mark.parametrize("line", ["Caused by: 812", "Caused by: #812,#815", "Caused by: V5.1.0", "caused by: #1", "Caused by: v5.1",
                                  "Caused by: #12 and more", "Caused by:", "Caused by: maybe"])
def test_parse_cause_refuses_other_forms_ac_223_1(line):  # AC-223.1
    import fixcause
    assert fixcause.parse_cause(f"**Fix.** Text (#1).\n{line}\n") is None


def test_the_cause_line_must_be_the_last_line_ac_223_1():  # AC-223.1
    import fixcause
    assert fixcause.parse_cause("**Fix.** Text.\nCaused by: #812\nMore text.\n") is None
    assert fixcause.parse_cause("**Fix.** Text without any cause line.\n") is None


def test_form_error_is_none_for_added_and_changed_fragments_ac_223_1():  # AC-223.1
    import fixcause
    assert fixcause.form_error(f"{FRAG}/1-a.added.md", "**A.** Text.\n") is None
    assert fixcause.form_error(f"{FRAG}/1-a.changed.md", "**A.** Text.\n") is None
    assert fixcause.form_error(f"{FRAG}/1-a.fixed.md", FIXED + "Caused by: unknown\n") is None
    assert FORM in fixcause.form_error(f"{FRAG}/1-a.fixed.md", FIXED)


def test_entries_and_numbers_of_a_fixed_section_ac_223_1():  # AC-223.1
    import fixcause
    section = "**A.** Text (#10).\nCaused by: #5\n\n**B.** Other (#11), (#12).\n\nCaused by: v5.1.0\n\n**C.** Third.\n"
    found = fixcause.entries(section)
    assert len(found) == 3
    one, two, three = found
    assert one.endswith("Caused by: #5") and two.endswith("Caused by: v5.1.0") and three.startswith("**C.**")
    assert fixcause.numbers(one) == {10} and fixcause.numbers(two) == {11, 12}
    assert fixcause.numbers(three, "900") == {900}


@pytest.mark.parametrize("cause", [None, "Caused by: 812", "Caused by: #812,#815", "Caused by: V5.1.0", "Caused by: v5.1", "caused by: #1"])
def test_a_fixed_fragment_without_a_valid_cause_line_is_one_error_ac_223_1(repo, fake_gh, cause):  # AC-223.1
    name = fixed(repo, cause)
    problem = one_problem(repo)
    assert problem.startswith("changelog fragment:") and name in problem and FORM in problem


def test_pr_check_prints_one_error_line_for_it_ac_223_1(repo, fake_gh, capsys):  # AC-223.1
    commit(repo, "scripts/a.py")
    name = fixed(repo, None)
    rc = house_rules.main(["--repo", str(repo), "--base", "main", "--title", "fix(cplat): a change"])
    out = capsys.readouterr().out.splitlines()
    errors = [ln for ln in out if ln.startswith("ERROR:") and "fragment" in ln]
    assert rc == 1 and len(errors) == 1 and name in errors[0] and FORM in errors[0]


@pytest.mark.parametrize("cause", ["Caused by: none", "Caused by: unknown"])
def test_none_and_unknown_pass_without_github_ac_223_1(repo, fake_gh, cause):  # AC-223.1
    import fixcause
    fixed(repo, cause)
    assert fixcause.parse_cause(FIXED + cause + "\n").kind in ("none", "unknown")
    assert check(repo)[1] == []
    assert not any(c[:1] == ["api"] for c in fake_gh.calls())


@pytest.mark.parametrize("kind", ["added", "changed"])
def test_added_and_changed_fragments_need_no_cause_line_ac_223_1(repo, fake_gh, kind):  # AC-223.1
    commit(repo, f"{FRAG}/901-new.{kind}.md", "**A change (spec 901).** Text.\n")
    assert check(repo)[1] == []
    name = fixed(repo, None)                       # only the fixed one is refused
    problem = one_problem(repo)
    assert name in problem and "901-new" not in problem


def test_a_fragment_already_on_the_base_is_never_checked_ac_223_1(repo, fake_gh):  # AC-223.1
    git(repo, "checkout", "-q", "main")
    commit(repo, f"{FRAG}/800-old.fixed.md", "**An old fix.** No cause line, merged before the rule.\n")
    git(repo, "checkout", "-q", "feature/x")
    git(repo, "rebase", "-q", "main")
    commit(repo, f"{FRAG}/901-new.added.md", "**New (spec 901).** Text.\n")
    assert check(repo)[1] == []
    name = fixed(repo, None)                       # a fragment this branch adds is checked, the old one is not
    problem = one_problem(repo)
    assert name in problem and "800-old" not in problem


def test_ci_fragment_check_fails_a_fixed_fragment_without_cause_ac_223_1(repo, tmp_path):  # AC-223.1
    run = ci_check(repo)
    assert run.returncode == 0 and re.search(r"OK: 0 added fixed fragment", run.stdout), run.stdout + run.stderr
    name = fixed(repo, None)
    run = ci_check(repo)
    lines = run.stdout.splitlines()
    errors = [ln for ln in lines if ln.startswith("ERROR:")]
    assert run.returncode == 1 and len(errors) == 1 and name in errors[0] and FORM in errors[0]
    assert "FAILED: 1 problem(s)" in lines


def test_ci_fragment_check_passes_a_valid_cause_without_network_ac_223_1(repo, fake_gh):  # AC-223.1
    fake_gh.set(down=True)
    fixed(repo, "Caused by: #812")
    run = ci_check(repo)
    assert run.returncode == 0 and "OK: 1 added fixed fragment(s) name a cause" in run.stdout, run.stdout + run.stderr
    assert fake_gh.calls() == []


def ci_check(repo):
    if not (repo / "scripts").exists():
        shutil.copytree(ROOT / "scripts", repo / "scripts", ignore=shutil.ignore_patterns("__pycache__", "node_modules"))
        (repo / ".gitignore").write_text("scripts/\n")
    return subprocess.run([sys.executable, "scripts/release-check.py", "fragments", "--base", "main"], cwd=repo, capture_output=True,
                          text=True, timeout=120)


# ---------------- AC-223.2: verified on GitHub ----------------

def test_a_merged_pr_and_an_existing_tag_pass_ac_223_2(repo, fake_gh):  # AC-223.2
    fake_gh.merged(812, 815).set(tags=["v5.23.0"])
    fixed(repo, "Caused by: #812, #815", name="900-a.fixed.md")
    fixed(repo, "Caused by: v5.23.0", name="901-b.fixed.md")
    notes: list = []
    assert check(repo, notes)[1] == [] and notes == []
    name = fixed(repo, "Caused by: #999", name="902-c.fixed.md")       # not merged: only this one fails
    problem = one_problem(repo)
    assert name in problem and "#999" in problem


@pytest.mark.parametrize("state", [{}, {"813": {"merged_at": None, "merge_commit_sha": None}}])
def test_a_pr_that_is_not_merged_is_an_error_ac_223_2(repo, fake_gh, state):  # AC-223.2
    fake_gh.set(prs=state)
    name = fixed(repo, "Caused by: #813")
    problem = one_problem(repo)
    assert problem.startswith("changelog fragment:") and name in problem
    assert "#813" in problem and "is not a merged PR of " + SLUG in problem


def test_a_tag_that_does_not_exist_is_an_error_ac_223_2(repo, fake_gh):  # AC-223.2
    fake_gh.set(tags=["v5.23.0"])
    name = fixed(repo, "Caused by: v9.9.9")
    problem = one_problem(repo)
    assert name in problem and "v9.9.9" in problem and f"names no tag of {SLUG}" in problem


def test_unreachable_github_is_one_warning_and_no_failure_ac_223_2(repo, fake_gh, capsys):  # AC-223.2
    fake_gh.set(down=True)
    commit(repo, "scripts/a.py")
    fixed(repo, "Caused by: #812")
    notes: list = []
    assert check(repo, notes)[1] == []
    assert len(notes) == 1 and "#812" in notes[0] and "was not checked" in notes[0]
    rc = house_rules.main(["--repo", str(repo), "--base", "main", "--title", "fix(cplat): a change"])
    out = capsys.readouterr().out.splitlines()
    warnings = [ln for ln in out if ln.startswith("WARNING:")]
    assert rc == 0 and len(warnings) == 1 and "#812" in warnings[0] and "was not checked" in warnings[0]
    assert not any(ln.startswith("ERROR:") for ln in out)


def test_unreachable_github_for_a_tag_is_a_warning_too_ac_223_2(repo, fake_gh):  # AC-223.2
    fake_gh.set(down=True)
    fixed(repo, "Caused by: v5.23.0")
    notes: list = []
    assert check(repo, notes)[1] == [] and len(notes) == 1 and "v5.23.0" in notes[0]


def test_verify_returns_errors_and_warnings_ac_223_2(fake_gh):  # AC-223.2
    import fixcause
    fake_gh.merged(812)
    ok = fixcause.parse_cause("x\nCaused by: #812\n")
    bad = fixcause.parse_cause("x\nCaused by: #999\n")
    assert fixcause.verify(SLUG, ok) == ([], [])
    errors, warnings = fixcause.verify(SLUG, bad)
    assert len(errors) == 1 and "#999" in errors[0] and warnings == []
    fake_gh.set(down=True)
    errors, warnings = fixcause.verify(SLUG, ok)
    assert errors == [] and len(warnings) == 1


# ---------------- AC-223.3: the cause survives the release ----------------

def test_the_released_entry_keeps_the_cause_line_ac_223_3():  # AC-223.3
    import fixcause
    text = "# CHANGELOG\n\n## [Unreleased]\n\n## [5.4.0] - 2026-05-01\n\nOld notes.\n"
    fragment = "**Fix the price (#900).** It was wrong, see [the spec](../specs/1-x/spec.md).\nCaused by: #812\n"
    out = cl.move_unreleased(text, "5.5.0", "2026-06-15", [("900-price.fixed.md", fragment)])
    body = cl.section_body(out, "5.5.0")
    assert "### Fixed" in body
    section = body.split("### Fixed", 1)[1]
    found = fixcause.entries(section)
    assert len(found) == 1
    entry = found[0]
    assert entry.strip().splitlines()[-1] == "Caused by: #812"
    assert fixcause.parse_cause(entry).prs == (812,)
