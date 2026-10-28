"""Spec 126 acceptance tests: one rule module for PR titles and the spec rule, run by CI and by the local checks.

`scripts/cplat/pr_rules.py` (stdlib only), `scripts/check-pr-title.py` (the `pr-title` job), `scripts/check-spec-required.py`
(the `spec-required` job) and `scripts/check-pr-local.py` (a step of `devbox run ci`) as design.md "Contract" describes them.
AC-126.11 (built titles fit), AC-126.13 (local check, skip lines), AC-126.14 (one table, same verdict everywhere).
"""
import importlib
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

import core

ROOT = core.PLATFORM_ROOT
SCRIPTS = ROOT / "scripts"
TITLE_ERR = "PR title does not follow Conventional Commits."


@pytest.fixture()
def pr_rules():
    return importlib.import_module("pr_rules")


def git(repo, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=repo, check=True,
                          capture_output=True, text=True).stdout.strip()


def make_repo(tmp_path, files):
    """A repo with main (README) and a branch `feature/x` that adds `files`; returns (repo, base_sha, head_sha)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "README.md").write_text("x")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "init")
    base = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "-b", "feature/x")
    for f in files or ["docs/notes.md"]:
        (repo / f).parent.mkdir(parents=True, exist_ok=True)
        (repo / f).write_text(f)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "work")
    return repo, base, git(repo, "rev-parse", "HEAD")


def script(name, repo, env):
    full = {k: v for k, v in os.environ.items() if k not in {"PR_TITLE", "PR_BODY", "PR_LABELS", "BASE_SHA", "HEAD_SHA"}}
    full.update(env)
    p = subprocess.run([sys.executable, str(SCRIPTS / name)], cwd=repo, env=full, capture_output=True, text=True)
    return p.returncode, p.stdout


# ---------------- AC-126.14: titles ----------------

M = "é"
TITLE_SAMPLES = [
    # id, title, valid
    ("valid", "feat(alerts): add price alerts", True),
    ("valid-no-scope", "fix: handle the empty case", True),
    ("valid-breaking", "feat(api)!: drop v1", True),
    ("invalid-no-type", "Price alerts", False),
    ("invalid-type", "feature(x): add", False),
    ("invalid-no-space", "feat(x):add", False),
    ("invalid-empty-subject", "feat(x): ", False),
    ("subject-72", "feat(x): " + "a" * 72, True),
    ("subject-73", "feat(x): " + "a" * 73, False),
    ("multibyte-72-chars", "docs(spec): " + M * 72, True),
    ("multibyte-73-chars", "docs(spec): " + M * 73, False),
    ("em-dash", "docs(spec): 126-x — Unattended runs stop wasting turns", True),
]


@pytest.mark.parametrize("sid, title, valid", TITLE_SAMPLES, ids=[s[0] for s in TITLE_SAMPLES])
def test_ac_126_14_title_samples_have_the_same_verdict_in_pr_rules_ci_and_the_local_check(pr_rules, tmp_path, sid, title, valid):  # AC-126.14
    err = pr_rules.title_error(title)
    assert (err is None) is valid
    if not valid:
        assert err == f"{TITLE_ERR}\n  Got:     {title}\n  Pattern: type(scope): description (≤72 chars)"

    repo, _, _ = make_repo(tmp_path, None)
    rc, out = script("check-pr-title.py", repo, {"PR_TITLE": title})
    assert (rc == 0) is valid
    assert out == ("OK: PR title is valid.\n" if valid else f"ERROR: {err}\n")

    rc, out = script("check-pr-local.py", repo, {"PR_TITLE": title, "PR_BODY": "", "PR_LABELS": ""})
    lines = out.splitlines()
    assert (rc == 0) is valid
    if valid:
        assert lines[0] == "pr-title: OK: PR title is valid."
    else:
        assert out.startswith("pr-title: ERROR: " + TITLE_ERR) and f"  Got:     {title}" in out
    assert "spec-required: OK: spec rule satisfied" in lines     # both checks run, also when the title is red


def test_ac_126_14_the_title_pattern_is_the_pr_title_jobs_pattern(pr_rules):  # AC-126.14
    assert pr_rules.TITLE_PATTERN == r"^(feat|fix|docs|style|refactor|perf|test|chore|ci|build|revert)(\(.+\))?!?: .{1,72}$"
    assert pr_rules.MAX_SUBJECT == 72 and pr_rules.NO_SPEC == "no-spec"


# ---------------- AC-126.14: the spec rule ----------------

SPEC_SAMPLES = [
    # id, body, labels, files, error
    ("closing-code-no-spec", "Closes #5", [], ["scripts/x.py"], True),
    ("closing-plugin-no-spec", "Fixes #5", [], ["plugins/a/agents/b.md"], True),
    ("closing-template-no-spec", "resolved #12", [], ["templates/service-python/x.jinja"], True),
    ("closing-code-with-spec", "Closes #5", [], ["scripts/x.py", "docs/specs/126-x/spec.md"], False),
    ("closing-code-no-spec-label", "Closes #5", ["no-spec"], ["scripts/x.py"], False),
    ("closing-code-other-label", "Closes #5", ["bug"], ["scripts/x.py"], True),
    ("not-closing-code-no-spec", "Related to #5", [], ["scripts/x.py"], False),
    ("empty-body", "", [], ["scripts/x.py"], False),
    ("closing-docs-only", "Closes #5", [], ["docs/guide.md"], False),
]


@pytest.mark.parametrize("sid, body, labels, files, error", SPEC_SAMPLES, ids=[s[0] for s in SPEC_SAMPLES])
def test_ac_126_14_spec_samples_have_the_same_verdict_in_pr_rules_ci_and_the_local_check(pr_rules, tmp_path, sid, body, labels, files, error):  # AC-126.14
    msg = pr_rules.spec_error(body, labels, files)
    assert (msg is not None) is error

    repo, base, head = make_repo(tmp_path, files)
    ci_env = {"PR_BODY": body, "PR_LABELS": ",".join(labels), "BASE_SHA": base, "HEAD_SHA": head}
    rc, out = script("check-spec-required.py", repo, ci_env)
    assert (rc == 1) is error
    assert out == (f"ERROR: {msg}\n" if error else "OK: spec rule satisfied\n")

    rc, out = script("check-pr-local.py", repo, {"PR_TITLE": "feat(x): valid", "PR_BODY": body, "PR_LABELS": ",".join(labels)})
    assert (rc == 1) is error
    assert "pr-title: OK: PR title is valid." in out.splitlines()
    want = f"spec-required: ERROR: {msg}" if error else "spec-required: OK: spec rule satisfied"
    assert want in out.splitlines()


def test_ac_126_14_the_spec_rule_message_is_the_one_ci_always_printed(pr_rules):  # AC-126.14
    msg = pr_rules.spec_error("Closes #5", [], ["scripts/a.py", "scripts/b.py", "plugins/c", "templates/d"])
    assert msg == ("this PR closes an issue and changes 4 platform file(s) (scripts/a.py, scripts/b.py, plugins/c …) "
                   "but no spec under docs/specs/. Write one with /component:spec (CLAUDE.md: platform changes start with a spec), "
                   "or add the label `no-spec` for a one-line fix or docs.")
    assert pr_rules.CODE == ("scripts/", "plugins/", "templates/")
    assert pr_rules.CLOSES.search("this Closes #5")


def test_ac_126_14_check_spec_required_keeps_verdict_as_an_alias(pr_rules):  # AC-126.14
    legacy = importlib.import_module("check-spec-required")
    assert legacy.verdict("Closes #5", [], ["scripts/x.py"]) == pr_rules.spec_error("Closes #5", [], ["scripts/x.py"])
    assert legacy.verdict("Closes #5", ["no-spec"], ["scripts/x.py"]) is None


def test_ac_126_14_changed_files_is_the_three_dot_diff(pr_rules, tmp_path):  # AC-126.14
    repo, base, head = make_repo(tmp_path, ["scripts/a.py", "docs/b.md"])
    assert sorted(pr_rules.changed_files(repo, "main")) == ["docs/b.md", "scripts/a.py"]
    assert sorted(pr_rules.changed_files(repo, base, head)) == ["docs/b.md", "scripts/a.py"]


def test_ac_126_14_ci_runs_the_same_code_the_pr_title_job_calls_the_script():  # AC-126.14
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text())
    runs = [s.get("run", "") for s in wf["jobs"]["pr-title"]["steps"]]
    assert any("python3 scripts/check-pr-title.py" in r for r in runs)
    assert not any("grep" in r for r in runs)
    env = {k: v for s in wf["jobs"]["pr-title"]["steps"] for k, v in (s.get("env") or {}).items()}
    assert "PR_TITLE" in env and "pull_request.title" in env["PR_TITLE"]
    assert any(s.get("uses", "").startswith("actions/checkout") for s in wf["jobs"]["pr-title"]["steps"])
    spec_runs = [s.get("run", "") for s in wf["jobs"]["spec-required"]["steps"]]
    assert any("python3 scripts/check-spec-required.py" in r for r in spec_runs)


def test_ac_126_14_the_scripts_do_not_import_cplat_by_sys_path(pr_rules):  # AC-126.14
    for name in ("check-pr-title.py", "check-spec-required.py"):
        text = (SCRIPTS / name).read_text()
        assert "spec_from_file_location" in text and "pr_rules" in text
        assert "sys.path" not in text


# ---------------- AC-126.11: titles the platform builds fit ----------------

def ok(pr_rules, t):
    assert pr_rules.title_error(t) is None, t
    subject = t.split(": ", 1)[1]
    assert 1 <= len(subject) <= 72 and len(subject.encode()) <= 72
    return subject


def test_ac_126_11_fit_leaves_a_fitting_title_alone(pr_rules):  # AC-126.11
    for t in ("feat(x): short", "fix: ok", "docs(spec): " + "a" * 72, "feat(api)!: drop v1"):
        assert pr_rules.fit(t) == t


def test_ac_126_11_fit_collapses_whitespace_in_the_subject(pr_rules):  # AC-126.11
    assert pr_rules.fit("feat(x):   two   words \n here") == "feat(x): two words here"


def test_ac_126_11_fit_shortens_an_ascii_subject_to_72_with_dots(pr_rules):  # AC-126.11
    out = pr_rules.fit("docs(spec): " + "a" * 100)
    assert out == "docs(spec): " + "a" * 69 + "..."
    ok(pr_rules, out)


def test_ac_126_11_fit_respects_72_bytes_for_multibyte_subjects(pr_rules):  # AC-126.11
    out = pr_rules.fit("docs(spec): " + "é" * 100)
    assert out == "docs(spec): " + "é" * 34 + "..."
    ok(pr_rules, out)
    out = pr_rules.fit("docs(spec): " + "—" * 100)
    assert out == "docs(spec): " + "—" * 23 + "..."
    ok(pr_rules, out)


def test_ac_126_11_fit_strips_trailing_separators_before_the_dots(pr_rules):  # AC-126.11
    out = pr_rules.fit("docs(spec): " + "a" * 68 + " — " + "b" * 30)
    assert out.endswith("a...") and "— ..." not in out
    ok(pr_rules, out)


def test_ac_126_11_the_draft_pr_title_of_a_long_spec_is_valid(pr_rules):  # AC-126.11
    sid = "126-unattended-runs-stop-wasting-turns-and"
    title = f"docs(spec): {sid} — Unattended runs stop wasting turns and CI rounds in every repo"
    ok(pr_rules, pr_rules.fit(title))


@pytest.mark.parametrize("bad", ["no type here", "feat(unclosed: x", "", "feat:"])
def test_ac_126_11_fit_refuses_what_is_not_a_conventional_title(pr_rules, bad):  # AC-126.11
    with pytest.raises(ValueError):
        pr_rules.fit(bad)


# ---------------- AC-126.13: the local check without a PR ----------------

def fake_gh(tmp_path, pr):
    """A `gh` that answers `pr view --json …` with `pr` (a dict) or fails when pr is None; logs its calls."""
    d = tmp_path / "bin"
    d.mkdir(exist_ok=True)
    exe = d / "gh"
    exe.write_text(f"#!{sys.executable}\nimport json, sys\n"
                   f"open({str(tmp_path / 'gh.log')!r}, 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n"
                   + ("sys.exit('no pull requests found for branch')\n" if pr is None else f"print(json.dumps({pr!r}))\n"))
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return d


def local(repo, tmp_path, pr, handed=None, no_gh=False):
    git_bin = Path(shutil.which("git")).parent
    if no_gh:
        iso = tmp_path / "gitonly"
        iso.mkdir(exist_ok=True)
        (iso / "git").symlink_to(shutil.which("git"))
        path = str(iso)
    else:
        path = f"{fake_gh(tmp_path, pr)}{os.pathsep}{git_bin}"
    env = {"PATH": path, **(handed or {})}
    full = {k: v for k, v in os.environ.items() if k not in {"PR_TITLE", "PR_BODY", "PR_LABELS", "PATH"}}
    full.update(env)
    p = subprocess.run([sys.executable, str(SCRIPTS / "check-pr-local.py")], cwd=repo, env=full, capture_output=True, text=True)
    return p.returncode, p.stdout


SKIPPED = ["pr-title: skipped (no pull request yet)", "spec-required: skipped (no pull request yet)"]


def test_ac_126_13_without_a_pull_request_both_checks_are_skipped_and_do_not_fail(tmp_path):  # AC-126.13
    repo, _, _ = make_repo(tmp_path, ["scripts/x.py"])
    rc, out = local(repo, tmp_path, None)
    assert rc == 0 and out.splitlines() == SKIPPED


def test_ac_126_13_a_missing_gh_means_no_pull_request(tmp_path):  # AC-126.13
    repo, _, _ = make_repo(tmp_path, ["scripts/x.py"])
    rc, out = local(repo, tmp_path, None, no_gh=True)
    assert rc == 0 and out.splitlines() == SKIPPED


@pytest.mark.parametrize("state", ["MERGED", "CLOSED"])
def test_ac_126_13_a_pull_request_that_is_not_open_means_no_pull_request(tmp_path, state):  # AC-126.13
    repo, _, _ = make_repo(tmp_path, ["scripts/x.py"])
    pr = {"title": "Bad title", "body": "Closes #5", "labels": [], "baseRefName": "main", "state": state}
    rc, out = local(repo, tmp_path, pr)
    assert rc == 0 and out.splitlines() == SKIPPED


def test_ac_126_13_an_open_pull_request_is_checked_with_the_ci_messages(tmp_path, pr_rules):  # AC-126.13
    repo, _, _ = make_repo(tmp_path, ["scripts/x.py"])
    pr = {"title": "Bad title", "body": "Closes #5", "labels": [], "baseRefName": "main", "state": "OPEN"}
    rc, out = local(repo, tmp_path, pr)
    assert rc == 1                                       # both checks ran, both are red
    assert f"pr-title: ERROR: {TITLE_ERR}" in out and "  Got:     Bad title" in out
    assert f"spec-required: ERROR: {pr_rules.spec_error('Closes #5', [], ['scripts/x.py'])}" in out.splitlines()
    gh_calls = [json.loads(ln) for ln in (tmp_path / "gh.log").read_text().splitlines()]
    assert any(c[:2] == ["pr", "view"] and "title,body,labels,baseRefName,state" in c for c in gh_calls)


def test_ac_126_13_an_open_pull_request_with_the_no_spec_label_and_a_valid_title_passes(tmp_path):  # AC-126.13
    repo, _, _ = make_repo(tmp_path, ["scripts/x.py"])
    pr = {"title": "fix(x): one-line fix", "body": "Closes #5", "labels": [{"name": "no-spec"}], "baseRefName": "main", "state": "OPEN"}
    rc, out = local(repo, tmp_path, pr)
    assert rc == 0
    assert out.splitlines() == ["pr-title: OK: PR title is valid.", "spec-required: OK: spec rule satisfied"]


def test_ac_126_13_handed_values_win_over_the_open_pull_request(tmp_path):  # AC-126.13
    repo, _, _ = make_repo(tmp_path, ["scripts/x.py"])
    pr = {"title": "Bad title", "body": "", "labels": [], "baseRefName": "main", "state": "OPEN"}
    rc, out = local(repo, tmp_path, pr, handed={"PR_TITLE": "fix(x): handed", "PR_BODY": "no issue", "PR_LABELS": ""})
    assert rc == 0 and out.splitlines() == ["pr-title: OK: PR title is valid.", "spec-required: OK: spec rule satisfied"]


def test_ac_126_13_devbox_run_ci_has_a_step_for_the_pull_request_checks():  # AC-126.13
    text = (SCRIPTS / "ci-local.sh").read_text()
    assert "pull request title and spec rule" in text and "check-pr-local.py" in text
    dev = json.loads((ROOT / "devbox.json").read_text())
    assert "ci-local.sh" in json.dumps(dev["shell"]["scripts"]["ci"])
