"""Spec 100 step 2: `cplat pr open` commits, pushes and opens the PR in one command (AC-100.7 to AC-100.9)."""
import json
import re
import subprocess

import pytest

import core
import pr as prmod
import pr_open

ROOT = core.PLATFORM_ROOT
TITLE = "feat(api): add the thing"
URL = "https://github.com/acme/app/pull/9"


class Fake:
    """git and gh as the module sees them: every command goes through `pr_open.run` and lands here."""

    def __init__(self, repo):
        self.repo = repo
        self.calls: list[list[str]] = []
        self.branch = "feature/100-x"
        self.dirty = True
        self.ahead = 0
        self.log = ""
        self.open_issues: set[str] = set()
        self.open_pr: str | None = None
        self.push_ok = True
        self.create_ok = True
        self.gh_ok = True
        self.origin = True
        self.commits = 0

    def __call__(self, cmd, *, cwd=None, check=True, **kw):
        self.calls.append(list(cmd))
        c = list(cmd)
        while "-c" in c:
            i = c.index("-c")
            del c[i:i + 2]
        out, rc, err = "", 0, ""
        if c[:2] == ["git", "rev-parse"]:
            if "--is-inside-work-tree" in c:
                out = "true\n"
            elif "--abbrev-ref" in c:
                out = self.branch + "\n"
            elif "--short=7" in c:
                out = "1a2b3c4\n"
            elif "--verify" in c:
                rc = 0 if self.origin else 1
        elif c[:2] == ["git", "status"]:
            out = " M f.py\n" if self.dirty else ""
        elif c[:2] == ["git", "rev-list"]:
            out = f"{self.ahead}\n"
        elif c[:2] == ["git", "log"]:
            out = self.log
        elif c[:2] == ["git", "add"]:
            pass
        elif c[:2] == ["git", "commit"]:
            self.dirty, self.ahead, self.commits = False, self.ahead + 1, self.commits + 1
        elif c[:2] == ["git", "push"]:
            if not self.push_ok:
                rc, err = 1, "hint: x\n ! [rejected] feature/100-x (non-fast-forward)\n"
        elif c[:3] == ["gh", "issue", "view"]:
            out = "OPEN\n" if c[3].lstrip("#") in self.open_issues else "CLOSED\n"
        elif c[:3] == ["gh", "auth", "status"]:
            rc = 0 if self.gh_ok else 1
        elif c[:3] == ["gh", "pr", "list"]:
            out = json.dumps([{"url": self.open_pr}] if self.open_pr else [])
        elif c[:3] == ["gh", "pr", "create"]:
            if self.create_ok:
                self.open_pr = URL
                out = URL + "\n"
            else:
                rc, err = 1, "GraphQL: boom\n"
        return subprocess.CompletedProcess(cmd, rc, out, err)

    def has(self, *words) -> list[list[str]]:
        return [c for c in self.calls if all(w in c for w in words)]


@pytest.fixture
def env(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "PR_BODY.md").write_text("## Related issues\n\n{{CLOSES}}\n")
    fake = Fake(tmp_path)
    monkeypatch.setattr(pr_open, "run", fake)
    return fake


def allow(repo, allow=(), deny=(), ask=(), name="settings.json"):
    (repo / ".claude").mkdir(exist_ok=True)
    (repo / ".claude" / name).write_text(json.dumps({"permissions": {"allow": list(allow), "deny": list(deny), "ask": list(ask)}}))


def open_cmd(env, capsys, *extra, title=TITLE):
    code = prmod.main(["open", "--title", title, "--repo", str(env.repo), *extra])
    return code, capsys.readouterr().out


def body(env):
    return (env.repo / ".git" / "PR_BODY.md").read_text()


# ---------------- AC-100.7 ----------------

def test_one_command_commits_signed_off_pushes_and_opens_the_pr(env, capsys):
    """AC-100.7: commit -s, push -u, gh pr create in one invocation; three result lines."""
    allow(env.repo, ["Bash(gh pr create *)"])
    code, out = open_cmd(env, capsys)
    assert code == 0
    assert out.splitlines() == ["commit: done 1a2b3c4", "push: done", f"pr: opened {URL}"]
    commit = env.has("commit")[0]
    assert "-s" in commit and commit[-1] == TITLE and "--amend" not in commit
    assert env.has("push", "-u", "origin", "feature/100-x")
    create = env.has("gh", "pr", "create")[0]
    assert ["--title", TITLE] == create[create.index("--title"):create.index("--title") + 2]
    assert "--body-file" in create and "--base" in create and "--head" in create


def test_message_overrides_the_commit_subject(env, capsys):
    """AC-100.7: --message is the commit subject, the title stays the PR title."""
    allow(env.repo, ["Bash(gh pr create *)"])
    open_cmd(env, capsys, "--message", "feat(api): wip subject")
    assert env.has("commit")[0][-1] == "feat(api): wip subject"


def test_json_output_follows_the_contract(env, capsys):
    """AC-100.7: --json has commit, push, pr, closes and exit."""
    allow(env.repo, ["Bash(gh pr create *)"])
    code, out = open_cmd(env, capsys, "--json")
    data = json.loads(out)
    assert data["exit"] == 0 == code and data["closes"] == []
    assert data["commit"] == {"status": "done", "sha": "1a2b3c4", "detail": data["commit"]["detail"]}
    assert data["push"]["status"] == "done"
    assert data["pr"]["status"] == "opened" and data["pr"]["url"] == URL and data["pr"]["command"] is None


@pytest.mark.parametrize("rules", [
    {},
    {"allow": ["Bash(gh pr create *)"], "deny": ["Bash(gh pr create *)"]},
    {"allow": ["Bash(gh *)"], "ask": ["Bash(gh pr create *)"]},
])
def test_pr_not_allowed_ends_at_a_ready_pr(env, capsys, rules):
    """AC-100.7 (spec 051, ADR-037): no allowed `gh pr create` means a ready command as the last line, exit 0."""
    if rules:
        allow(env.repo, **rules)
    code, out = open_cmd(env, capsys)
    lines = out.splitlines()
    assert code == 0 and len(lines) == 3 and not env.has("gh", "pr", "create")
    assert lines[-1] == (f"pr: ready: gh pr create --base main --head feature/100-x --title '{TITLE}' "
                         f"--body-file .git/PR_BODY.md")
    assert env.has("push")


@pytest.mark.parametrize("rule", ["Bash(gh pr create *)", "Bash(gh pr create:*)", "Bash(gh pr *)", "Bash(gh pr:*)",
                                  "Bash(gh *)", "Bash(gh:*)"])
def test_each_listed_rule_allows_gh_pr_create(env, capsys, rule):
    """AC-100.7: the allow rules the design lists, in settings.local.json too."""
    allow(env.repo, [rule], name="settings.local.json")
    code, out = open_cmd(env, capsys)
    assert code == 0 and out.splitlines()[-1] == f"pr: opened {URL}"


def test_no_pr_flag_and_missing_gh_give_a_ready_pr(env, capsys):
    """AC-100.7: --no-pr and a gh that is not logged in are not errors."""
    allow(env.repo, ["Bash(gh *)"])
    code, out = open_cmd(env, capsys, "--no-pr")
    assert code == 0 and out.splitlines()[-1].startswith("pr: ready: gh pr create")
    env.gh_ok = False
    code, out = open_cmd(env, capsys)
    assert code == 0 and out.splitlines()[-1].startswith("pr: ready: gh pr create")
    assert not env.has("gh", "pr", "create")


def test_never_forces_or_amends(env, capsys):
    """AC-100.7 (ADR-037): no force push and no --amend, on any path."""
    allow(env.repo, ["Bash(gh *)"])
    open_cmd(env, capsys)
    flat = " ".join(" ".join(c) for c in env.calls)
    assert "--force" not in flat and "-f " not in flat and "--amend" not in flat and "+feature" not in flat


@pytest.mark.parametrize("name", ["fix", "build"])
def test_finishing_step_of_the_commands_is_one_cplat_pr_open(name):
    """AC-100.7: the coordinator commands finish with `cplat pr open`, not separate git push / gh pr create."""
    text = (ROOT / "plugins" / "component" / "commands" / f"{name}.md").read_text()
    assert text.count("cplat pr open") >= 1
    steps = "\n".join(ln for ln in text.splitlines() if "pr: ready" not in ln)  # the spec 051 paragraph names the command
    assert "git push" not in steps and "gh pr create" not in steps
    assert not re.search(r"git commit (?!-s)(-m|-q)", text), "every commit needs the DCO sign-off (-s)"


# ---------------- AC-100.8 ----------------

def test_nothing_to_commit_fails_and_runs_nothing_else(env, capsys):
    """AC-100.8: clean tree, nothing ahead: failed, push and pr not run, exit 1, no commit."""
    allow(env.repo, ["Bash(gh *)"])
    env.dirty = False
    code, out = open_cmd(env, capsys)
    assert code == 1
    assert out.splitlines() == ["commit: failed: nothing to commit", "push: not run", "pr: not run"]
    assert not env.has("commit") and not env.has("push")


def test_push_rejected_reports_the_parts_and_a_rerun_makes_no_second_commit(env, capsys):
    """AC-100.8: commit done, push failed (last stderr line), pr not run; the re-run skips the commit."""
    allow(env.repo, ["Bash(gh *)"])
    env.push_ok = False
    code, out = open_cmd(env, capsys)
    lines = out.splitlines()
    assert code == 1 and lines[0] == "commit: done 1a2b3c4"
    assert lines[1].startswith("push: failed:") and "rejected" in lines[1] and lines[2] == "pr: not run"
    assert not env.has("gh", "pr", "create")
    env.push_ok = True
    code, out = open_cmd(env, capsys)
    assert code == 0 and env.commits == 1
    assert out.splitlines()[0] == "commit: skipped (clean tree, 1 commits ahead)"
    assert len(env.has("gh", "pr", "create")) == 1


def test_pr_already_open_is_a_failure_without_a_second_pr(env, capsys):
    """AC-100.8: an open PR for the branch: `failed: already open <url>`, exit 1, no gh pr create."""
    allow(env.repo, ["Bash(gh *)"])
    env.open_pr = URL
    code, out = open_cmd(env, capsys)
    assert code == 1 and out.splitlines()[-1] == f"pr: failed: already open {URL}"
    assert not env.has("gh", "pr", "create")


def test_gh_failure_then_rerun_leaves_one_commit_and_one_pr(env, capsys):
    """AC-100.8: gh pr create fails; the re-run neither commits again nor opens a second PR."""
    allow(env.repo, ["Bash(gh *)"])
    env.create_ok = False
    code, out = open_cmd(env, capsys)
    assert code == 1 and out.splitlines()[-1] == "pr: failed: GraphQL: boom"
    env.create_ok = True
    code, out = open_cmd(env, capsys)
    assert code == 0 and env.commits == 1 and out.splitlines()[-1] == f"pr: opened {URL}"
    code, out = open_cmd(env, capsys)
    assert code == 1 and "already open" in out and env.commits == 1
    assert len(env.has("gh", "pr", "create")) == 2  # one failed, one opened; none after the PR existed


def test_json_reports_the_failed_part(env, capsys):
    """AC-100.8: --json carries the failure and exit 1."""
    env.push_ok = False
    code, out = open_cmd(env, capsys, "--json")
    data = json.loads(out)
    assert code == 1 == data["exit"] and data["commit"]["status"] == "done"
    assert data["push"]["status"] == "failed" and data["pr"]["status"] == "not run"


# ---------------- AC-100.9 ----------------

@pytest.mark.parametrize("branch,title,drop_body", [
    ("main", TITLE, False),
    ("wip-thing", TITLE, False),
    ("feature/100-x", "add the thing", False),
    ("feature/100-x", TITLE, True),
])
def test_refused_before_anything_changes(env, capsys, branch, title, drop_body):
    """AC-100.9: base branch, bad branch name, bad title or missing body file: exit 2, no mutating command."""
    env.branch = branch
    if drop_body:
        (env.repo / ".git" / "PR_BODY.md").unlink()
    code, _ = open_cmd(env, capsys, title=title)
    assert code == 2
    assert not env.has("add") and not env.has("commit") and not env.has("push")


def test_closes_lines_replace_the_placeholder_from_every_source(env, capsys):
    """AC-100.9: --issues, the spec's tracks, the log and --message; only OPEN issues, ascending."""
    allow(env.repo, ["Bash(gh *)"])
    sdir = env.repo / "docs" / "specs" / "100-x"
    sdir.mkdir(parents=True)
    (sdir / "spec.md").write_text("---\nid: 100-x\ntitle: X\nstatus: building\ntracks: [30]\n---\n# X\n")
    env.log = "feat: a (#12)\n\nCloses #44\n"
    env.open_issues = {"7", "30", "44", "50"}  # 12 is closed, 8 is closed
    open_cmd(env, capsys, "--issues", "#7 #8", "--spec", "100-x", "--message", "feat(api): thing (#50)")
    assert "Closes #7\nCloses #30\nCloses #44\nCloses #50" in body(env)
    assert "{{CLOSES}}" not in body(env) and "#12" not in body(env) and "#8" not in body(env)


def test_no_open_issue_gives_na(env, capsys):
    """AC-100.9: without open issues the placeholder becomes N/A; without gh it does too."""
    allow(env.repo, ["Bash(gh *)"])
    open_cmd(env, capsys, "--issues", "#7")
    assert "N/A" in body(env) and "{{CLOSES}}" not in body(env)


def test_wip_commits_add_the_squash_note_once(env, capsys):
    """AC-100.9: a `wip(` subject adds the note to the body, and only once."""
    allow(env.repo, ["Bash(gh *)"])
    env.log = "wip(build): t1\nfeat: x\n"
    open_cmd(env, capsys)
    env.dirty = False
    env.open_pr = None
    open_cmd(env, capsys)
    note = "Contains WIP commits from an interrupted build: squash-merge."
    assert body(env).count(note) == 1


def test_base_is_origin_base_when_it_exists(env, capsys):
    """AC-100.9: clean tree is judged against origin/<base>, falling back to <base>."""
    allow(env.repo, ["Bash(gh *)"])
    env.dirty, env.ahead = False, 3
    code, out = open_cmd(env, capsys)
    assert code == 0 and out.splitlines()[0] == "commit: skipped (clean tree, 3 commits ahead)"
    assert env.has("rev-list", "origin/main..HEAD")
    env.origin = False
    open_cmd(env, capsys)
    assert env.has("rev-list", "main..HEAD")


def test_cplat_lists_pr_open():
    """AC-100.9: the usage line names the new subcommand."""
    assert "pr wait|open" in (ROOT / "scripts" / "cplat" / "cplat.py").read_text()
