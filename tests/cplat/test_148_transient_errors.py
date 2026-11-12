"""Spec 148 acceptance tests: transient errors and slow progress never stop a run (#539–#545).

Seams: `core.subprocess.run` scripted per call and `core.sleep` (the network retry), `newsvc.run` / `newsvc.push_main`
(the repo create), `newapp.newsvc.resolve` and `newapp._published` (resume), the scripted Argo CD and clock of spec 143's
`system wait` tests, and the system ship world of spec 097 for `next --wait`."""
import subprocess
from pathlib import Path

import pytest
import yaml

import core
import newapp
import newsvc
import ship
from test_143_envwait import World as WaitWorld, app
from test_143_shipwait import GITOPS, World, running, tick  # noqa: F401  (fixtures)

DOWN = "Post \"https://api.github.com/graphql\": dial tcp 140.82.121.5:443: connect: network is down"
RESET = "read tcp 10.0.0.2:5512->140.82.121.5:443: read: connection reset by peer"
HTTP_502 = "HTTP 502: Bad Gateway (https://api.github.com/repos/acme/x)"


@pytest.fixture()
def scripted(monkeypatch):
    """`fail(n, stderr)`: the next n calls fail with stderr, then they succeed. `.calls`, `.slept`."""
    monkeypatch.setattr(core, "NETWORK_RETRY_MAX_WAIT", 300)

    class S:
        calls: list = []
        slept: list = []
        left = 0
        stderr = ""

        def fail(self, n, stderr):
            self.left, self.stderr = n, stderr

    s = S()
    s.calls, s.slept = [], []

    def fake_run(cmd, **kw):
        s.calls.append(cmd)
        if s.left:
            s.left -= 1
            return subprocess.CompletedProcess(cmd, 1, "", s.stderr)
        return subprocess.CompletedProcess(cmd, 0, "ok\n", "")
    monkeypatch.setattr(core.subprocess, "run", fake_run)
    monkeypatch.setattr(core, "sleep", s.slept.append)
    return s


# ---------------- AC-148.1 ----------------

@pytest.mark.parametrize("cmd", [["gh", "repo", "create", "acme/x", "--private"], ["gh", "pr", "merge", "5", "--squash"],
                                 ["gh", "api", "-X", "POST", "repos/acme/x/issues", "-f", "title=t"],
                                 ["git", "-C", "/tmp/x", "fetch", "origin"], ["git", "clone", "https://github.com/acme/x"]])
def test_a_call_that_never_reached_github_runs_again_ac_148_1(scripted, cmd, capsys):  # AC-148.1
    scripted.fail(2, DOWN)
    assert core.run(cmd).returncode == 0
    assert len(scripted.calls) == 3 and scripted.slept == [10, 20]
    assert "network error (dial tcp): trying again in 10 s" in capsys.readouterr().err


@pytest.mark.parametrize("cmd", [["gh", "pr", "view", "5", "--json", "state"], ["gh", "pr", "ready", "5"],
                                 ["gh", "repo", "edit", "acme/x", "--add-topic", "t"], ["gh", "api", "repos/acme/x"],
                                 ["gh", "api", "-X", "PUT", "repos/acme/x/topics", "-f", "names[]=t"], ["git", "pull", "--ff-only"]])
@pytest.mark.parametrize("stderr", [RESET, HTTP_502])
def test_a_call_safe_to_repeat_runs_again_after_a_reset_or_5xx_ac_148_1(scripted, cmd, stderr):  # AC-148.1
    scripted.fail(1, stderr)
    assert core.run(cmd).returncode == 0 and len(scripted.calls) == 2


@pytest.mark.parametrize("cmd", [["gh", "pr", "merge", "5"], ["gh", "pr", "create", "--title", "t"], ["gh", "issue", "comment", "3"],
                                 ["gh", "api", "-X", "POST", "repos/acme/x/issues"], ["gh", "api", "repos/acme/x/issues", "-f", "t=x"]])
@pytest.mark.parametrize("stderr", [RESET, HTTP_502])
def test_a_write_that_may_have_reached_github_fails_at_once_ac_148_1(scripted, cmd, stderr):  # AC-148.1
    scripted.fail(1, stderr)
    with pytest.raises(core.PlatformError):
        core.run(cmd)
    assert len(scripted.calls) == 1 and scripted.slept == []


@pytest.mark.parametrize("cmd, stderr", [(["gh", "pr", "view", "5"], "GraphQL: Could not resolve to a PullRequest with the number of 5."),
                                         (["gh", "api", "repos/acme/x"], "HTTP 404: Not Found"),
                                         (["git", "status"], DOWN), (["kubectl", "get", "pods"], DOWN)])
def test_any_other_failure_fails_at_once_ac_148_1(scripted, cmd, stderr):  # AC-148.1
    scripted.fail(1, stderr)
    assert core.run(cmd, check=False).returncode == 1 and len(scripted.calls) == 1 and scripted.slept == []


def test_a_network_that_stays_down_fails_after_five_minutes_ac_148_1(scripted):  # AC-148.1
    scripted.fail(1000, DOWN)
    with pytest.raises(core.PlatformError, match="network is down"):
        core.run(["gh", "pr", "view", "5"])
    assert 4 * 60 <= sum(scripted.slept) <= 5 * 60 and max(scripted.slept) == 60


# ---------------- AC-148.2 ----------------

class GitHub:
    """newsvc.run for create_remote: `exists` says whether the repo is on GitHub, `create_rc` what `gh repo create` returns."""

    def __init__(self, monkeypatch, *, exists, create_rc, origin=False):
        self.calls, self.pushed = [], []
        self.exists, self.create_rc, self.origin = exists, create_rc, origin
        monkeypatch.setattr(newsvc, "run", self)
        monkeypatch.setattr(newsvc, "push_main", self.pushed.append)

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        rc = 0
        if cmd[:3] == ["gh", "repo", "create"]:
            rc = self.create_rc
            if rc == 0:
                self.exists = True
        elif cmd[:3] == ["gh", "repo", "view"]:
            rc = 0 if self.exists else 1
        elif cmd[:3] == ["git", "remote", "get-url"]:
            rc = 0 if self.origin else 2
        elif cmd[:2] == ["gh", "config"]:
            return subprocess.CompletedProcess(cmd, 0, "https\n", "")
        if rc and kw.get("check", True):
            raise core.PlatformError(f"{cmd[:3]} failed")
        return subprocess.CompletedProcess(cmd, rc, "", "i/o timeout" if rc else "")


def test_create_and_push_are_two_steps_ac_148_2(monkeypatch, tmp_path):  # AC-148.2
    gh = GitHub(monkeypatch, exists=False, create_rc=0)
    newsvc.create_remote("acme/x", "private", "d", tmp_path)
    create = next(c for c in gh.calls if c[:3] == ["gh", "repo", "create"])
    assert "--push" not in create and "--source=." in create and gh.pushed == [tmp_path]


def test_a_create_whose_answer_was_lost_goes_on_with_the_push_ac_148_2(monkeypatch, tmp_path):  # AC-148.2
    gh = GitHub(monkeypatch, exists=False, create_rc=1)
    real = gh.__call__

    def created_anyway(cmd, **kw):
        if cmd[:3] == ["gh", "repo", "create"]:
            gh.exists = True              # GitHub made the repo, the answer never arrived
        return real(cmd, **kw)
    monkeypatch.setattr(newsvc, "run", created_anyway)
    newsvc.create_remote("acme/x", "private", "d", tmp_path)
    assert ["git", "remote", "add", "origin", "https://github.com/acme/x.git"] in gh.calls and gh.pushed == [tmp_path]


def test_a_failed_create_of_a_repo_that_does_not_exist_fails_ac_148_2(monkeypatch, tmp_path):  # AC-148.2
    gh = GitHub(monkeypatch, exists=False, create_rc=1)
    with pytest.raises(core.PlatformError, match="gh repo create acme/x"):
        newsvc.create_remote("acme/x", "private", "d", tmp_path)
    assert gh.pushed == []


def test_a_stale_origin_is_replaced_ac_148_2(monkeypatch, tmp_path):  # AC-148.2
    gh = GitHub(monkeypatch, exists=False, create_rc=0, origin=True)
    newsvc.create_remote("acme/x", "private", "d", tmp_path)
    assert ["git", "remote", "remove", "origin"] in gh.calls
    assert gh.calls.index(["git", "remote", "remove", "origin"]) < next(i for i, c in enumerate(gh.calls) if c[:3] == ["gh", "repo", "create"])


# ---------------- AC-148.3 ----------------

MANIFEST = {"system": "shop", "owner": "team-shop",
            "components": [{"name": "shop-api", "description": "API", "type": "service", "lang": "python"}]}


def _manifest(tmp_path, **extra):
    f = tmp_path / "system.yml"
    f.write_text(yaml.safe_dump({**MANIFEST, **extra}))
    return str(f)


def _local_repo(out: Path, name: str, template: str) -> Path:
    d = out / name
    d.mkdir(parents=True)
    (d / ".copier-answers.yml").write_text(f"_src_path: gh:ika100/sdlc-foundry/templates/{template}\n")
    return d


@pytest.fixture()
def resolving(monkeypatch):
    seen = []
    monkeypatch.setattr(newapp.newsvc, "resolve", lambda argv: seen.append(argv) or {"name": argv[0], "argv": argv})
    monkeypatch.setattr(newapp.newsvc, "plan", lambda req: core.Report(title="x"))
    monkeypatch.setattr(newapp.core, "has_gh", lambda: True)
    monkeypatch.setattr(newapp, "_remote_exists", lambda slug: slug.endswith("-gitops"))
    return seen


def test_resume_publishes_a_local_repo_that_never_reached_github_ac_148_3(tmp_path, monkeypatch, resolving):  # AC-148.3
    out = tmp_path / "out"
    _local_repo(out, "shop-gitops", "gitops-app")
    monkeypatch.setattr(newapp, "_published", lambda slug: False)
    req = newapp.resolve([_manifest(tmp_path), "--org", "acme", "--dir", str(out), "--resume"])
    gitops = req["entries"][0]
    assert gitops["publish"] and "--publish-only" in gitops["req"]["argv"]
    assert any("exists here but not on GitHub: create acme/shop-gitops and push" in ln for ln in newapp.plan(req).will_do)


def test_resume_skips_a_repo_that_is_on_github_with_a_commit_ac_148_3(tmp_path, monkeypatch, resolving):  # AC-148.3
    out = tmp_path / "out"
    _local_repo(out, "shop-gitops", "gitops-app")
    monkeypatch.setattr(newapp, "_published", lambda slug: True)
    req = newapp.resolve([_manifest(tmp_path), "--org", "acme", "--dir", str(out), "--resume"])
    assert req["entries"][0]["req"] is None and not req["entries"][0]["publish"]


def test_publish_only_keeps_the_bootstrap_commit_and_needs_one_ac_148_3(tmp_path):  # AC-148.3
    target = tmp_path / "svc-a"
    target.mkdir()
    with pytest.raises(core.PlatformError, match="no bootstrap commit"):
        newsvc.resolve(["svc-a", "d", "--dir", str(tmp_path), "--org", "acme", "--publish-only"])
    for args in (["init", "-q", "-b", "main"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "boot"]):
        subprocess.run(["git", *args], cwd=target, check=True)
    req = newsvc.resolve(["svc-a", "d", "--dir", str(tmp_path), "--org", "acme", "--publish-only"])
    assert req["publish_only"] is True


# ---------------- AC-148.4 ----------------

def _orgs(monkeypatch, orgs):
    def fake(cmd, **kw):
        ok = cmd[:2] == ["gh", "api"] and cmd[2].startswith("orgs/") and cmd[2][5:] in orgs
        return subprocess.CompletedProcess(cmd, 0 if ok else 1, "", "")
    monkeypatch.setattr(newapp, "run", fake)
    monkeypatch.setattr(newapp.core, "gh_login", lambda: "eike")


def test_an_owner_that_is_an_organisation_sets_the_org_ac_148_4(tmp_path, monkeypatch, resolving):  # AC-148.4
    _orgs(monkeypatch, {"acme-demo"})
    monkeypatch.setattr(newapp, "_remote_exists", lambda slug: False)
    req = newapp.resolve([_manifest(tmp_path, owner="acme-demo"), "--dir", str(tmp_path / "out")])
    assert req["org"] == "acme-demo" and req["entries"][0]["slug"] == "acme-demo/shop-gitops"


def test_an_owner_that_is_a_team_name_keeps_the_login_and_org_wins_ac_148_4(tmp_path, monkeypatch, resolving):  # AC-148.4
    _orgs(monkeypatch, {"acme-demo"})
    monkeypatch.setattr(newapp, "_remote_exists", lambda slug: False)
    assert newapp.resolve([_manifest(tmp_path, owner="Team Shop"), "--dir", str(tmp_path / "o1")])["org"] == "eike"
    assert newapp.resolve([_manifest(tmp_path, owner="acme-demo", org="other"), "--dir", str(tmp_path / "o2")])["org"] == "other"


# ---------------- AC-148.5 ----------------

@pytest.fixture()
def w(tmp_path, monkeypatch, capsys):
    return WaitWorld(tmp_path, monkeypatch, capsys)


def test_a_root_app_with_a_comparison_error_gets_one_hard_refresh_ac_148_5(w):  # AC-148.5
    err = {"type": "ComparisonError", "message": "Failed to load target state: rpc error: code = Unknown desc = repo-server timed out"}
    stuck = {"shop-root": app(w.old, conditions=[err]), "addon-postgres-dev": app(w.head)}
    w.argo.polls = [stuck] * 6 + [{**w.ready(), "shop-root": app(w.head)}]
    rc, out, _, _ = w.wait("--env", "dev", "--timeout", "300")
    assert rc == 0 and w.argo.refreshed == ["shop-root"]
    assert any("asked Argo CD for a hard refresh of shop-root" in ln for ln in out)


def test_an_app_behind_the_revision_is_refreshed_once_after_45_seconds_ac_148_5(w):  # AC-148.5
    behind = {"todo-api-dev": app(w.old, images=[w.image]), "addon-postgres-dev": app(w.head)}
    w.argo.polls = [behind] * 12 + [w.ready()]
    rc, out, _, _ = w.wait("--env", "dev", "--timeout", "300")
    assert rc == 0 and w.argo.refreshed == ["todo-api-dev"]
    assert w.argo.calls.index(next(c for c in w.argo.calls if "annotate" in c)) > 4     # not before 45 s


def test_a_wait_that_is_ready_at_once_refreshes_nothing_ac_148_5(w):  # AC-148.5
    w.argo.polls = [w.ready()]
    assert w.wait("--env", "dev")[0] == 0 and w.argo.refreshed == []


# ---------------- AC-148.6 ----------------

def test_land_stops_when_the_pr_cannot_be_marked_ready_ac_148_6(tmp_path, monkeypatch):  # AC-148.6
    import spec
    import spec_pr
    from test_spec import make
    from test_spec_pr import MARKER, PR_URL, SPEC_ID, World as SpecWorld, run as spec_run
    monkeypatch.setattr(spec, "repo_shape", lambda root: None)
    make(tmp_path, status="approved")
    sw = SpecWorld(tmp_path, monkeypatch, existing={"number": 41, "url": PR_URL, "body": MARKER, "isDraft": True})
    real = sw.gh

    def not_ready(args, *, cwd=None):
        if args[:2] == ["pr", "ready"]:
            spec_pr._last_error = DOWN
            return 1, ""
        return real(args, cwd=cwd)
    monkeypatch.setattr(spec_pr, "gh", not_ready)
    with pytest.raises(core.PlatformError, match="marking spec PR #41 ready failed") as e:
        spec_run(sw, "land", SPEC_ID)
    assert "still a draft" in e.value.hint and not sw.waits


# ---------------- AC-148.7 ----------------

@pytest.fixture()
def sw(tmp_path, monkeypatch, capsys):
    world = World(tmp_path, monkeypatch, capsys)
    monkeypatch.setattr(ship, "argo_health", lambda *a, **k: "Synced/Healthy")
    return world


def test_progress_extends_the_wait_beyond_its_timeout_ac_148_7(sw, tick):  # AC-148.7
    sw.started(states={GITOPS: "passed", "shop-lib": "passed", "shop-api": "running", "shop-worker": "passed"})
    running(sw, "shop-api", "build")
    noop = lambda: None  # noqa: E731
    tick.script = [noop] * 4 + [lambda: running(sw, "shop-api", "verify")] + [noop] * 4 + \
                  [lambda: running(sw, "shop-api", "land")] + [noop] * 3 + [lambda: sw.ship_state("shop-api")]
    r = sw.app("next", "--wait", "--timeout", "60")
    assert r.rc == 0 and "action: start" in r.out and tick.slept > 60


def test_a_timeout_says_no_repo_made_progress_ac_148_7(sw, tick):  # AC-148.7
    sw.started(states={GITOPS: "passed", "shop-lib": "passed", "shop-api": "running", "shop-worker": "passed"})
    running(sw, "shop-api", "build")
    r = sw.app("next", "--wait", "--timeout", "60")
    first = next(ln for ln in r.out.splitlines() if ln.startswith("TIMEOUT:"))
    assert r.rc == 2 and "no repo made progress for 60s" in first and tick.slept == 60


def test_progress_cannot_extend_one_wait_forever_ac_148_7(sw, tick):  # AC-148.7
    sw.started(states={GITOPS: "passed", "shop-lib": "passed", "shop-api": "running", "shop-worker": "passed"})
    running(sw, "shop-api", "p0")
    tick.script = [(lambda k=k: running(sw, "shop-api", f"p{k}")) for k in range(1, 200)]
    r = sw.app("next", "--wait", "--timeout", "60")
    assert r.rc == 2 and tick.slept <= 7 * 60


# ---------------- AC-148.8 ----------------

ROOT = Path(__file__).resolve().parents[2]


def test_the_release_gate_names_the_recipes_tool_and_runs_the_image_scan_ac_148_8():  # AC-148.8
    release = (ROOT / "plugins/component/commands/release.md").read_text()
    gate = release[release.index("## Phase 4"):release.index("## Phase 5")]
    assert "devbox run image-scan" in gate and "skipped" in gate and "pnpm audit" in gate
    assert "devbox run image-scan" in gate and "skipped" in gate
    security = (ROOT / "plugins/shared/agents/security.md").read_text()
    assert "devbox.json" in security
