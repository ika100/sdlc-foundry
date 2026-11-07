"""Spec 150 acceptance tests: `cplat platform pr-check` and the house rules of `cplat pr open`.

Seams: a real git repo under tmp_path shaped like the platform repo (marketplace, one plugin, docs/changelog.d) with a base
commit on `main` and a feature branch; nothing is pushed."""
import json
import subprocess

import pytest

import core
import house_rules

LONG = "feat(cplat): " + "a very long subject that keeps going " * 3


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "platform"
    (r / ".claude-plugin").mkdir(parents=True)
    (r / "plugins/svc/.claude-plugin").mkdir(parents=True)
    (r / "docs/changelog.d").mkdir(parents=True)
    (r / "scripts").mkdir()
    (r / ".claude-plugin/marketplace.json").write_text(json.dumps({"plugins": [{"name": "svc", "version": "1.0.0"}]}))
    (r / "plugins/svc/.claude-plugin/plugin.json").write_text(json.dumps({"name": "svc", "version": "1.0.0"}))
    (r / "docs/changelog.d/README.md").write_text("fragments\n")
    git(r, "init", "-q", "-b", "main")
    git(r, "config", "user.name", "t")
    git(r, "config", "user.email", "t@t")
    git(r, "add", "-A")
    git(r, "commit", "-q", "-s", "-m", "base")
    git(r, "checkout", "-q", "-b", "feature/x")
    return r


def commit(repo, path, text="x\n", signed=True):
    f = repo / path
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", *(["-s"] if signed else []), "-m", f"change {path}")


def check(repo, title="feat(cplat): a change", body="", fix=False, rules=house_rules.RULES):
    return house_rules.check(repo, title=title, body=body, labels=[], base="main", fix=fix, rules=rules)


# ---------------- AC-150.1 ----------------

def test_a_clean_branch_passes_every_rule_ac_150_1(repo, capsys):  # AC-150.1
    commit(repo, "scripts/a.py")
    commit(repo, "docs/changelog.d/150-a.added.md", "**A change (spec 150).** Text.\n")
    assert check(repo)[1] == []
    assert house_rules.main(["--repo", str(repo), "--base", "main", "--title", "feat(cplat): a change"]) == 0
    assert capsys.readouterr().out.startswith("OK: the house rules pass")


def test_each_broken_rule_is_one_error_line_ac_150_1(repo, capsys):  # AC-150.1
    commit(repo, "scripts/a.py", signed=False)
    (repo / "plugins/svc/.claude-plugin/plugin.json").write_text(json.dumps({"name": "svc", "version": "1.1.0"}))
    body = repo / "body.md"
    body.write_text("Closes #12\n")
    rc = house_rules.main(["--repo", str(repo), "--base", "main", "--title", "bad title", "--body-file", str(body)])
    out = capsys.readouterr().out.splitlines()
    assert rc == 1
    kinds = {ln.split(":")[1].strip() for ln in out if ln.startswith("ERROR:")}
    assert {"pr-title", "spec-required", "validate", "dco"} <= kinds
    assert any("git commit --amend -s" in ln for ln in out) and any("bump both plugin.json" in ln for ln in out)


# ---------------- AC-150.2 ----------------

def test_a_feat_that_changes_code_needs_a_fragment_ac_150_2(repo):  # AC-150.2
    commit(repo, "scripts/a.py")
    [problem] = check(repo)[1]
    assert problem.startswith("changelog fragment:") and "<id>-<slug>.<added|changed|fixed>.md" in problem


@pytest.mark.parametrize("title", ["docs: a guide", "chore(plugins): bump", "test: more"])
def test_other_kinds_need_no_fragment_ac_150_2(repo, title):  # AC-150.2
    commit(repo, "scripts/a.py")
    assert check(repo, title=title)[1] == []


@pytest.mark.parametrize("name, text", [("bad-name.md", "x"), ("150-x.added.md", "  \n")])
def test_a_bad_fragment_is_named_ac_150_2(repo, name, text):  # AC-150.2
    commit(repo, "scripts/a.py")
    commit(repo, f"docs/changelog.d/{name}", text)
    assert any(p.startswith("changelog fragment:") and name in p for p in check(repo)[1])


# ---------------- AC-150.3 ----------------

def test_fix_shortens_a_long_title_and_checks_that_one_ac_150_3(repo, capsys):  # AC-150.3
    commit(repo, "docs/guide.md")
    title, problems = check(repo, title=LONG, fix=True)
    assert len(title.split(": ", 1)[1]) <= 72 and title.endswith("...") and problems == []
    assert check(repo, title=LONG)[1] and check(repo, title=LONG)[1][0].startswith("pr-title:")
    assert house_rules.main(["--repo", str(repo), "--base", "main", "--title", LONG, "--fix"]) == 0
    assert capsys.readouterr().out.startswith(f"TITLE: {title}")


# ---------------- AC-150.4 ----------------

def test_pr_open_runs_only_the_fragment_and_version_rules_ac_150_4(repo):  # AC-150.4
    commit(repo, "scripts/a.py", signed=False)
    problems = check(repo, title="feat(cplat): a change", body="Closes #3\n", rules=house_rules.PR_OPEN_RULES)[1]
    assert [p.split(":")[0] for p in problems] == ["changelog fragment"]


def test_pr_open_refuses_before_the_push_ac_150_4():  # AC-150.4
    import inspect

    import pr_open
    src = inspect.getsource(pr_open.open_pr)
    assert src.index("house_rules.check(") < src.index('push = run(["git", "push"')
    assert "PR_OPEN_RULES" in src and "pr_rules.fit" not in src      # spec 126: a caller's title is never shortened


# ---------------- AC-150.5 ----------------

def test_outside_the_platform_repo_it_points_to_pr_open_ac_150_5(tmp_path):  # AC-150.5
    with pytest.raises(core.PlatformError) as e:
        house_rules.main(["--repo", str(tmp_path), "--title", "feat: x"])
    assert "cplat pr open" in e.value.hint
