"""Spec 126 acceptance tests: checks before the push (AC-126.9 to AC-126.12) and titles that fit (AC-126.11).

`cplat component ship pr --title T --body-file F [--no-spec]` runs, in this order: branch and body checks, the title rule, the open PR,
the spec rule (platform repo only), the gitops tasks, `devbox run ci` with `PR_TITLE`, `PR_BODY` and `PR_LABELS` set, the push,
then `gh pr edit` / `gh pr create`. `cplat pr open` (finishing command of quick-task and fix-bug) follows the same rule. The
builders of spec draft PRs, product ship PRs, gitops PRs, cluster repo PRs and platform update PRs shorten their titles with
`pr_rules.fit`.
"""
import json
import subprocess

import pytest

import core
import pr as prmod
import pr_open
import ship
from test_pr_open import Fake, URL, allow, env  # noqa: F401  (fixtures, helpers)
from test_ship import git, repo  # noqa: F401  (fixtures, helpers)

PR_URL = "https://github.com/acme/shop-api/pull/7"
BRANCH = "feature/007-price-alerts"
TITLE = "feat(alerts): price alerts"
BODY = "## Summary\n\nCloses #5\n"
SPEC_MSG = "this PR closes an issue and changes 1 platform file(s) (scripts/x.py) but no spec under docs/specs/."


class Gh:
    """Scripted `gh` for `ship.gh`: the open PRs of the branch, create and edit calls."""

    def __init__(self):
        self.calls: list[list[str]] = []
        self.open: list[dict] = []

    def __call__(self, args, *, cwd, check=True):
        self.calls.append(list(args))
        if args[:2] == ["pr", "list"]:
            return json.dumps(self.open)
        if args[:2] == ["pr", "create"]:
            return PR_URL + "\n"
        if args[:2] == ["pr", "edit"]:
            return ""
        raise AssertionError(args)

    def has(self, *words):
        return [c for c in self.calls if all(w in c for w in words)]


@pytest.fixture()
def world(repo, monkeypatch):
    """A platform repo (declares `shape: platform`, has a `ci` script) on its feature branch, run in phase pr; git push and `devbox run ci` are recorded."""
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    (repo / ".copier-answers.yml").unlink()
    (repo / ".platform-settings.yml").write_text("shape: platform\n")
    (repo / "devbox.json").write_text(json.dumps({"shell": {"scripts": {"ci": "true"}}}))
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "platform")
    ship.start(repo, "7", True)
    git(repo, "checkout", "-q", "-b", BRANCH)
    ship.set_phase(repo, "pr")
    gh = Gh()
    events: list[tuple] = []
    real = ship.run

    def fake_run(cmd, **kw):
        if cmd[:3] == ["devbox", "run", "ci"]:
            events.append(("ci", kw.get("env") or {}))
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd[:2] == ["git", "push"]:
            events.append(("push",))
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return real(cmd, **kw)
    monkeypatch.setattr(ship, "gh", gh)
    monkeypatch.setattr(ship, "run", fake_run)
    w = type("W", (), {})()
    w.repo, w.gh, w.events = repo, gh, events
    w.body = repo / ".pr-body.md"
    w.body.write_text(BODY)

    def change(*files):
        for f in files:
            (repo / f).parent.mkdir(parents=True, exist_ok=True)
            (repo / f).write_text(f)
        git(repo, "add", "-A")
        git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "work")

    def pr(*extra, title=TITLE):
        return ship.main(["--repo", str(repo), "pr", "--title", title, "--body-file", str(w.body), *extra])
    w.change, w.pr = change, pr
    return w


def nothing_done(w):
    assert not [e for e in w.events if e[0] in ("ci", "push")]
    assert not w.gh.has("pr", "create") and not w.gh.has("pr", "edit")
    st = ship.load_state(w.repo)
    assert st["phase"] == "pr" and not st.get("pr")


# ---------------- AC-126.9: the spec rule before anything is pushed ----------------

def test_ac_126_9_a_closing_body_with_platform_code_and_no_spec_is_refused_before_ci_and_push(world):  # AC-126.9
    world.change("scripts/x.py")
    with pytest.raises(core.PlatformError) as e:
        world.pr()
    assert str(e.value).startswith(SPEC_MSG)
    assert "Write one with /component:spec" in str(e.value) and "`no-spec`" in str(e.value)
    nothing_done(world)


def test_ac_126_9_the_message_is_the_one_of_the_spec_required_job(world):  # AC-126.9
    import pr_rules
    world.change("scripts/x.py")
    with pytest.raises(core.PlatformError) as e:
        world.pr()
    assert str(e.value) == pr_rules.spec_error(BODY, [], ["scripts/x.py"])


@pytest.mark.parametrize("files, body", [
    (["scripts/x.py", "docs/specs/126-x/spec.md"], BODY),     # the diff touches a spec
    (["scripts/x.py"], "## Summary\n\nRelated to #5\n"),      # the body closes no issue
    (["docs/guide.md"], BODY),                                # no platform code
])
def test_ac_126_9_the_spec_rule_passes_when_it_is_satisfied(world, files, body):  # AC-126.9
    world.change(*files)
    world.body.write_text(body)
    assert world.pr() == 0
    assert ship.load_state(world.repo)["phase"] == "land"
    [(_, env_)] = [e for e in world.events if e[0] == "ci"]
    assert env_["PR_TITLE"] == TITLE and env_["PR_BODY"] == body       # the local check sees what CI will see


def test_ac_126_9_the_title_rule_comes_before_the_spec_rule(world):  # AC-126.9 AC-126.11
    world.change("scripts/x.py")
    with pytest.raises(core.PlatformError, match="Conventional Commits"):
        world.pr(title="Price alerts")
    nothing_done(world)


def test_ac_126_9_the_spec_rule_does_not_apply_outside_the_platform_repo(repo, monkeypatch):  # AC-126.9
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    ship.start(repo, "7", True)
    git(repo, "checkout", "-q", "-b", BRANCH)
    (repo / "scripts").mkdir()
    (repo / "scripts" / "x.py").write_text("x")
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "work")
    gh = Gh()
    monkeypatch.setattr(ship, "gh", gh)
    real = ship.run
    monkeypatch.setattr(ship, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "", "") if cmd[:2] == ["git", "push"] else real(cmd, **kw))
    body = repo / ".pr-body.md"
    body.write_text(BODY)
    assert ship.main(["--repo", str(repo), "pr", "--title", TITLE, "--body-file", str(body), "--no-spec"]) == 0
    create = gh.has("pr", "create")[0]
    assert "--label" not in create and "no-spec" not in create        # component repos have no such label


def test_ac_126_9_ci_runs_with_the_pull_request_handed_in_the_environment(world):  # AC-126.9 AC-126.13
    world.change("scripts/x.py", "docs/specs/126-x/spec.md")
    assert world.pr() == 0
    [(_, env_)] = [e for e in world.events if e[0] == "ci"]
    assert env_["PR_TITLE"] == TITLE and env_["PR_BODY"] == BODY and env_["PR_LABELS"] == ""


def test_ac_126_9_the_order_is_ci_then_push_then_create(world):  # AC-126.9
    world.change("scripts/x.py", "docs/specs/126-x/spec.md")
    world.pr()
    assert [e[0] for e in world.events] == ["ci", "push"]
    assert world.events[0][1].get("PR_TITLE") == TITLE
    assert world.gh.calls.index(world.gh.has("pr", "create")[0]) > world.gh.calls.index(world.gh.has("pr", "list")[0])


# ---------------- AC-126.10: --no-spec ----------------

def test_ac_126_10_no_spec_adds_the_label_when_the_pr_is_created_and_the_local_rule_passes(world):  # AC-126.10
    world.change("scripts/x.py")
    assert world.pr("--no-spec") == 0
    create = world.gh.has("pr", "create")[0]
    assert create[create.index("--label") + 1] == "no-spec"
    [(_, env_)] = [e for e in world.events if e[0] == "ci"]
    assert "no-spec" in env_["PR_LABELS"].split(",")
    assert ship.load_state(world.repo)["phase"] == "land"


def test_ac_126_10_no_spec_adds_the_label_to_an_open_pr_that_lacks_it(world):  # AC-126.10
    world.change("scripts/x.py")
    world.gh.open = [{"number": 7, "url": PR_URL, "title": TITLE, "labels": []}]
    assert world.pr("--no-spec") == 0
    edit = world.gh.has("pr", "edit", "--add-label")[0]
    assert edit[:3] == ["pr", "edit", PR_URL] and edit[edit.index("--add-label") + 1] == "no-spec"
    assert not world.gh.has("pr", "create")


def test_ac_126_10_a_label_the_open_pr_already_has_satisfies_the_rule_and_is_not_added_again(world):  # AC-126.9 AC-126.10
    world.change("scripts/x.py")
    world.gh.open = [{"number": 7, "url": PR_URL, "title": TITLE, "labels": [{"name": "no-spec"}]}]
    assert world.pr("--no-spec") == 0
    assert not world.gh.has("--add-label")
    world.gh.calls.clear()
    world.body.write_text(BODY)
    assert world.pr() == 0                                            # the open PR's label counts without the flag


# ---------------- AC-126.11: caller titles are checked, built titles fit ----------------

@pytest.mark.parametrize("title", ["Price alerts", "feat(alerts): " + "a" * 73, "feat(alerts):", "feat: "])
def test_ac_126_11_a_caller_title_that_breaks_the_rule_is_refused_before_the_push_with_the_rule(world, title):  # AC-126.11
    world.change("docs/guide.md")
    with pytest.raises(core.PlatformError) as e:
        world.pr(title=title)
    assert "PR title does not follow Conventional Commits." in str(e.value)
    assert f"Got:     {title}" in str(e.value) and "Pattern: type(scope): description (≤72 chars)" in str(e.value)
    nothing_done(world)


def test_ac_126_11_a_caller_title_of_72_characters_is_accepted_and_never_shortened(world):  # AC-126.11
    t = "feat(alerts): " + "a" * 72
    world.change("docs/guide.md")
    assert world.pr(title=t) == 0
    assert world.gh.has("pr", "create")[0][world.gh.has("pr", "create")[0].index("--title") + 1] == t
    assert [e for e in world.events if e[0] == "ci"][0][1].get("PR_TITLE") == t


def test_ac_126_11_ship_gitops_pr_refuses_a_bad_caller_title(world):  # AC-126.11
    with pytest.raises(core.PlatformError, match="Conventional Commits"):
        ship.main(["--repo", str(world.repo), "gitops", "pr", "t1", "--title", "bad title", "--body-file", str(world.body)])


# ---------------- AC-126.12: an open PR gets the checked title ----------------

def test_ac_126_12_an_open_pr_under_another_title_is_retitled(world):  # AC-126.12
    world.change("docs/guide.md")
    world.gh.open = [{"number": 7, "url": PR_URL, "title": "old title", "labels": []}]
    assert world.pr() == 0
    edit = world.gh.has("pr", "edit", "--title")[0]
    assert edit[:3] == ["pr", "edit", PR_URL] and edit[edit.index("--title") + 1] == TITLE
    assert not world.gh.has("pr", "create")
    assert ship.load_state(world.repo)["pr"] == PR_URL


def test_ac_126_12_an_open_pr_with_the_same_title_is_not_edited(world):  # AC-126.12
    world.change("docs/guide.md")
    world.gh.open = [{"number": 7, "url": PR_URL, "title": TITLE, "labels": []}]
    assert world.pr() == 0
    assert not world.gh.has("pr", "edit") and not world.gh.has("pr", "create")
    assert [e for e in world.events if e[0] == "ci"][0][1].get("PR_TITLE") == TITLE


# ---------------- `cplat pr open` (AC-126.9 to AC-126.11) ----------------

class Fake2(Fake):
    """The pr_open fake, with the diff of the branch and the porcelain status under the test's control."""

    def __init__(self, repo):
        super().__init__(repo)
        self.diff_files: list[str] = []
        self.porcelain: list[str] | None = None

    def __call__(self, cmd, *, cwd=None, check=True, **kw):
        c = [a for i, a in enumerate(cmd) if a != "-c" and (i == 0 or cmd[i - 1] != "-c")]
        if c[:2] == ["git", "diff"] and "--name-only" in c:
            self.calls.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0, "\n".join(self.diff_files) + "\n", "")
        if c[:2] == ["git", "status"] and self.porcelain is not None:
            self.calls.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0, "".join(f" M {p}\n" for p in self.porcelain), "")
        return super().__call__(cmd, cwd=cwd, check=check, **kw)


@pytest.fixture()
def pro(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "PR_BODY.md").write_text("## Related issues\n\n{{CLOSES}}\n")
    (tmp_path / ".platform-settings.yml").write_text("shape: platform\n")
    fake = Fake2(tmp_path)
    fake.open_issues = {"5"}
    monkeypatch.setattr(pr_open, "run", fake)
    allow(tmp_path, ["Bash(gh pr create *)"])
    return fake


def open_cmd(env_, capsys, *extra, title=TITLE):
    code = prmod.main(["open", "--title", title, "--issues", "#5", "--repo", str(env_.repo), *extra])
    cap = capsys.readouterr()
    return code, cap.out + cap.err


def untouched(fake):
    assert not fake.has("add") and not fake.has("commit") and not fake.has("push") and not fake.has("gh", "pr", "create")
    assert "{{CLOSES}}" in (fake.repo / ".git" / "PR_BODY.md").read_text()


def test_ac_126_9_pr_open_refuses_a_closing_pr_with_platform_changes_and_no_spec(pro, capsys):  # AC-126.9
    pro.diff_files, pro.porcelain = ["scripts/x.py"], []
    code, out = open_cmd(pro, capsys)
    assert code == 2 and f"ERROR: {SPEC_MSG}" in out
    untouched(pro)                                       # body file and tree stay as they were


def test_ac_126_9_pr_open_counts_the_uncommitted_paths_that_git_add_would_commit(pro, capsys):  # AC-126.9
    pro.diff_files, pro.porcelain = [], ["scripts/x.py"]
    code, out = open_cmd(pro, capsys)
    assert code == 2 and SPEC_MSG in out
    untouched(pro)


def test_ac_126_9_pr_open_passes_when_a_spec_is_in_the_diff_or_the_uncommitted_paths(pro, capsys):  # AC-126.9
    pro.diff_files, pro.porcelain = ["scripts/x.py"], ["docs/specs/126-x/spec.md"]
    code, out = open_cmd(pro, capsys)
    assert code == 0 and "pr: opened" in out
    assert any("--name-only" in c for c in pro.has("git", "diff"))    # the rule looked at the files of the branch


def test_ac_126_10_pr_open_no_spec_adds_the_label_to_the_create_command(pro, capsys):  # AC-126.10
    pro.diff_files, pro.porcelain = ["scripts/x.py"], []
    code, out = open_cmd(pro, capsys, "--no-spec")
    assert code == 0
    create = pro.has("gh", "pr", "create")[0]
    assert create[create.index("--label") + 1] == "no-spec"


def test_ac_126_10_pr_open_no_spec_is_in_the_printed_command_of_a_ready_pr(pro, capsys):  # AC-126.10
    pro.diff_files, pro.porcelain = ["scripts/x.py"], []
    code, out = open_cmd(pro, capsys, "--no-spec", "--no-pr")
    assert code == 0 and "--label no-spec" in out and not pro.has("gh", "pr", "create")


@pytest.mark.parametrize("title", ["Price alerts", "feat(api): " + "a" * 73])
def test_ac_126_11_pr_open_refuses_a_bad_title_with_the_rule_before_anything_changes(pro, capsys, title):  # AC-126.11
    pro.diff_files, pro.porcelain = [], []
    code, out = open_cmd(pro, capsys, title=title)
    assert code == 2
    assert "PR title does not follow Conventional Commits." in out and f"Got:     {title}" in out
    untouched(pro)


# ---------------- AC-126.11: built titles ----------------

def test_ac_126_11_the_draft_pr_of_a_spec_with_a_long_title_gets_a_valid_title(tmp_path, monkeypatch):  # AC-126.11
    import pr_rules
    import spec
    import spec_pr
    from test_spec import make
    from test_spec_pr import PR_URL as DRAFT_URL, World
    monkeypatch.setattr(spec, "repo_shape", lambda root: None)
    sp = make(tmp_path, status="draft")
    long_title = "Unattended runs stop wasting turns and CI rounds in every repository that ships"
    f = sp.dir / "spec.md"
    f.write_text(f.read_text().replace("title: Price alerts", f"title: {long_title}", 1))
    assert long_title in f.read_text()
    w = World(tmp_path, monkeypatch)
    assert spec.main(["--repo", str(tmp_path), "publish", sp.id]) == 0
    [create] = w.calls("pr", "create")
    title = create[create.index("--title") + 1]
    assert title.startswith("docs(spec): 007-price-alerts") and pr_rules.title_error(title) is None
    assert len(title.split(": ", 1)[1].encode()) <= 72
    commits = [c for c in w.git_calls if "commit" in c]
    assert commits and all(title in c for c in commits)             # the commit subject is the same shortened title
