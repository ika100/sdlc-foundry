"""Spec 126, AC-126.11: the title each opener really sends (`gh pr create` / `gh pr edit` argv, `git commit -m` subject) passes the
PR title rule when the platform builds a title longer than 72 characters, and a bad caller title is refused before the push."""
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import clusterrepo
import core
import fleet_pr
import gitops
import pr_rules
import test_appship_097 as t97
import upgrade

LONG_ID = "012-shop-with-a-remarkably-long-product-name-that-never-ends"
LONG = "feat(cluster): install " + "a-very-long-system-name-" * 4 + "from acme/some-long-repository-name"
URL = "https://github.com/acme/x/pull/1"


def assert_sent(title: str, subject: str | None = None) -> None:
    assert pr_rules.title_error(title) is None, title
    body = title.split(": ", 1)[1]
    assert len(body) <= 72 and len(body.encode()) <= 72
    if subject is not None:
        assert subject == title or pr_rules.title_error(subject) is None
        sbody = subject.split(": ", 1)[1]
        assert len(sbody) <= 72 and len(sbody.encode()) <= 72


def arg_after(argv: list[str], flag: str) -> str:
    return argv[argv.index(flag) + 1]


class Recorder:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, cmd, cwd=None, check=True, **kw):
        self.calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout=URL + "\n", stderr="")

    def first(self, *prefix: str) -> list[str]:
        return next(c for c in self.calls if c[: len(prefix)] == list(prefix))


def commit_subject(rec: Recorder) -> str:
    commit = next(c for c in rec.calls if "commit" in c and "-m" in c)
    return arg_after(commit, "-m")


@pytest.fixture()
def rec(monkeypatch):
    r = Recorder()
    monkeypatch.setattr(core, "git_identity", lambda repo: [])
    monkeypatch.setattr(gitops, "run", r)
    monkeypatch.setattr(clusterrepo, "run", r)
    monkeypatch.setattr(core, "run", r)
    return r


def test_gitops_open_pr_sends_a_fitted_title(rec):  # AC-126.11
    gitops.open_pr(Path("."), "b", LONG, "body")
    sent = arg_after(rec.first("gh", "pr", "create"), "--title")
    assert_sent(sent, commit_subject(rec))
    assert sent != LONG


def test_cluster_repo_pr_sends_a_fitted_title(rec):  # AC-126.11
    clusterrepo._pr(Path("."), "cluster/add-x", LONG, "body")
    sent = arg_after(rec.first("gh", "pr", "create"), "--title")
    assert_sent(sent, commit_subject(rec))
    assert sent != LONG


def test_upgrade_open_pr_sends_a_fitted_title(rec):  # AC-126.11
    title = "chore(resource): upgrade " + "postgres-with-a-long-name-" * 4 + "from 15.4 to 16.1 in every environment"
    upgrade.open_pr(Path("."), "resource/upgrade-x", title, "body")
    sent = arg_after(rec.first("gh", "pr", "create"), "--title")
    assert_sent(sent, commit_subject(rec))
    assert sent != title


class FleetWorld:
    def __init__(self, monkeypatch, existing):
        self.calls: list[list[str]] = []
        monkeypatch.setattr(fleet_pr, "_git", lambda ctx, *a, **k: "")
        monkeypatch.setattr(fleet_pr, "open_fleet_pr", lambda ctx: existing)
        monkeypatch.setattr(fleet_pr, "new_branch", lambda ctx: "fleet/platform-update-x")
        monkeypatch.setattr(fleet_pr, "_run_update", lambda ctx, ref, old=None, target=None: SimpleNamespace(data={"k": 1}))
        monkeypatch.setattr(fleet_pr, "follow_ups", lambda report: [])
        monkeypatch.setattr(fleet_pr, "pr_body", lambda *a: "body")
        monkeypatch.setattr(fleet_pr, "_decide", lambda *a: fleet_pr.Result("left open", "test", URL, []))
        self.ctx = fleet_pr.Ctx("acme/x", Path("."), "main", self.gh, lambda s: None, 1.0)

    def gh(self, args, input=None):
        self.calls.append(list(args))
        return 0, URL + "\n", ""


OLD = "5.0.0-" + "release-candidate-" * 5


def test_fleet_pr_create_sends_a_fitted_title(monkeypatch):  # AC-126.11
    fw = FleetWorld(monkeypatch, None)
    fleet_pr.update(fw.ctx, OLD, "5.1.0", None)
    sent = arg_after(next(c for c in fw.calls if c[:2] == ["pr", "create"]), "--title")
    assert_sent(sent)
    assert OLD not in sent


def test_fleet_pr_edit_sends_a_fitted_title(monkeypatch):  # AC-126.11
    fw = FleetWorld(monkeypatch, {"url": URL, "headRefName": "fleet/platform-update-x", "labels": []})
    fleet_pr.update(fw.ctx, OLD, "5.1.0", None)
    sent = arg_after(next(c for c in fw.calls if c[:2] == ["pr", "edit"]), "--title")
    assert_sent(sent)
    assert OLD not in sent


# ---- the product ship (appship), over the spec 097 world with a long spec id

@pytest.fixture()
def lw(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(t97, "SPEC", LONG_ID)
    monkeypatch.setattr(t97, "PRODUCT_SPEC", t97.PRODUCT_SPEC.replace("012-shop", LONG_ID))
    monkeypatch.setattr(t97, "PLAN_HEAD", t97.PLAN_HEAD.replace("012-shop", LONG_ID))
    return t97.World(tmp_path, monkeypatch, capsys)


def created_titles(w) -> list[str]:
    return [arg_after(c, "--title") for c in w.made("pr", "create")]


def test_appship_publish_sends_a_fitted_title_and_subject(lw):  # AC-126.11
    w = lw
    w.started()
    plan = w.gitops / "docs" / "plan" / f"{LONG_ID}.md"
    plan.write_text(plan.read_text() + "\nA new paragraph.\n")
    r = w.app("publish")
    assert r.rc == 0, r.out
    (sent,) = created_titles(w)
    assert len(f"docs(spec): {LONG_ID} — product spec and plan") > 72 + len("docs(spec): ")
    subject = t97.git(w.gitops, "log", "-1", "--format=%s", "origin/main")
    assert_sent(sent, subject)
    assert subject.startswith("docs(spec): ")


def test_appship_complete_sends_a_fitted_title_and_subject(lw):  # AC-126.11
    w = lw
    t97.all_passed(w)
    r = w.app("complete")
    assert r.rc == 0, r.out
    (sent,) = created_titles(w)
    subject = t97.git(w.gitops, "log", "-1", "--format=%s", "origin/main")
    assert_sent(sent, subject)
    assert subject.startswith("docs(spec): ")


def test_appship_open_pr_fits_the_title(lw):  # AC-126.11
    import appship
    w = lw
    appship.open_pr(w.gitops, "feature/x", f"docs(spec): {LONG_ID} — something quite a bit longer than allowed", "body")
    (sent,) = created_titles(w)
    assert_sent(sent)


@pytest.mark.parametrize("title", ["feat(shop): " + "x" * 80, "no conventional commit here"])
def test_entry_pr_refuses_a_bad_title_before_anything_is_pushed(w, title):  # AC-126.11
    w.started()
    r = w.app("repo", "start", t97.GITOPS)
    assert r.rc == 0, r.out
    wt = Path(r.out.strip().splitlines()[-1].split()[-1])
    (wt / "applications" / "shop" / "entry.yaml").write_text("entry: true\n")
    t97.git(wt, "add", "-A")
    t97.git(wt, "commit", "-qm", "feat(shop): gitops entry")
    body = w.root / "body.md"
    body.write_text("## Summary\n")
    r = w.app("entry", "pr", t97.GITOPS, "--title", title, "--body-file", str(body))
    assert r.rc == 1
    assert "PR title does not follow Conventional Commits" in r.out and "≤72 chars" in r.out
    assert w.made("pr", "create") == []
    branch = f"compose/{t97.SPEC}"
    assert subprocess.run(["git", "--git-dir", str(w.origin), "rev-parse", branch], capture_output=True).returncode != 0


from test_appship_097 import w  # noqa: E402,F401  (fixture)
from test_runs import clock, mem, store, stored  # noqa: E402,F401  (fixtures the world's run store needs)
