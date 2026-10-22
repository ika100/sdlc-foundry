"""Specs 072, 075 and 076: land fails fast and heals stuck checks, `devbox run ci` before a push, gitops tasks in a ship run."""
import json
import subprocess

import pytest
import yaml

import core
import ship
import spec
from test_ship import SHA, FakeGh, check, git, repo, to_land  # noqa: F401  (repo is a fixture)

GITOPS = "acme/shop-gitops"
GLINK = f"https://github.com/{GITOPS}/actions/runs/77/job/1"


class Gh(FakeGh):
    """FakeGh plus run status, rerun/cancel, runner labels and the gitops PRs of a ship run."""

    def __init__(self):
        super().__init__()
        self.run_status: dict[str, list[str]] = {}
        self.gitops_checks: list[list[dict]] = []
        self.gitops_state = {"state": "OPEN", "isDraft": True}

    def __call__(self, args, *, cwd, check=True):
        self.calls.append(args)
        if args[:2] == ["run", "view"] and "status" in args:
            seq = self.run_status.get(args[2], ["in_progress"])
            return seq.pop(0) if len(seq) > 1 else seq[0]
        if args[:2] in (["run", "rerun"], ["run", "cancel"], ["pr", "ready"]):
            return ""
        if args[0] == "api":
            return "lan-shop-api\n"
        if args[:2] == ["pr", "create"] and "-R" in args:
            return f"https://github.com/{GITOPS}/pull/3\n"
        if args[:2] == ["pr", "list"] and "-R" in args and "spec/" in " ".join(args):
            return "[]"
        if args[:2] == ["pr", "view"] and GITOPS in args[2]:
            return json.dumps(self.gitops_state)
        if args[:2] == ["pr", "checks"] and GITOPS in args[2]:
            return json.dumps(self.gitops_checks.pop(0) if len(self.gitops_checks) > 1 else self.gitops_checks[0])
        self.calls.pop()
        return super().__call__(args, cwd=cwd, check=check)


@pytest.fixture()
def gh(monkeypatch):
    fake = Gh()
    monkeypatch.setattr(ship, "gh", fake)
    clock = {"t": 0.0}
    monkeypatch.setattr(ship, "now", lambda: clock["t"])
    monkeypatch.setattr(ship, "sleep", lambda s: clock.__setitem__("t", clock["t"] + s))
    fake.said = []
    monkeypatch.setattr(ship, "say", fake.said.append)
    fake.merges, fake.ci, fake.pushes = [], [], []
    real_run = ship.run

    def fake_run(cmd, **kw):
        if cmd[:3] == ["gh", "pr", "merge"]:
            fake.merges.append(cmd[3])
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd[:2] == ["devbox", "run"]:
            fake.ci.append(kw.get("cwd"))
            rc = fake.ci_rc if hasattr(fake, "ci_rc") else 0
            return subprocess.CompletedProcess(cmd, rc, "lint ok\nsecurity: Potential secret in a.py:3\n", "")
        if cmd[:2] == ["git", "push"]:
            fake.pushes.append(kw.get("cwd"))
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd[:2] == ["git", "pull"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd[:3] == ["gh", "repo", "clone"]:
            d = cmd[4]
            subprocess.run(["git", "init", "-q", "-b", "main", d], check=True)
            git(d, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init")
            git(d, "update-ref", "refs/remotes/origin/main", "HEAD")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd[:2] == ["git", "fetch"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return real_run(cmd, **kw)
    monkeypatch.setattr(ship, "run", fake_run)
    return fake


def running(name, run="42"):
    return {"name": name, "state": "IN_PROGRESS", "bucket": "pending",
            "link": f"https://github.com/acme/shop-api/actions/runs/{run}/job/{name}"}


def queued(name, run="42"):
    return {**running(name, run), "state": "QUEUED"}


# ---------------- spec 072 ----------------

def test_the_first_red_check_ends_the_wait(repo, gh):
    """AC-072.1: a failed check while others are still queued → RED at once, its log, no merge."""
    to_land(repo, gh)
    gh.checks = [[check("security", "fail"), queued("docker"), check("quality", "pass")]]
    ok, lines = ship.land(repo, timeout=3600, interval=20)
    assert not ok and gh.merges == []
    assert lines[0].startswith("RED: 1 of 3") and "security" in lines[0]
    assert any("FAIL TestPriceAlert" in ln for ln in lines)
    assert ["run", "view", "42", "-R", "acme/shop-api", "--log-failed"] in gh.calls
    assert not any(c[:2] == ["run", "rerun"] for c in gh.calls)


def test_a_stale_check_is_rerun_once_then_an_error(repo, gh):
    """AC-072.2: in progress while its run completed (on two polls) → one rerun; stale again → error naming the run."""
    to_land(repo, gh)
    gh.checks = [[running("quality"), check("test", "pass")]]
    gh.run_status["42"] = ["completed"]
    with pytest.raises(core.PlatformError, match=r"run 42 .*also after a rerun"):
        ship.land(repo, timeout=3600, interval=20)
    assert [c for c in gh.calls if c[:2] == ["run", "rerun"]] == [["run", "rerun", "42", "-R", "acme/shop-api"]]
    assert any("stale" in s for s in gh.said)


def test_a_rerun_stale_check_that_recovers_merges(repo, gh):
    """AC-072.2: the rerun clears the stale check, then land merges."""
    to_land(repo, gh)
    gh.checks = [[running("quality")]] * 2 + [[running("quality")]] * 3 + [[check("quality", "pass")]]
    gh.run_status["42"] = ["completed", "completed", "in_progress"]
    ok, _ = ship.land(repo, timeout=3600, interval=20)
    assert ok and gh.merges and sum(c[:2] == ["run", "rerun"] for c in gh.calls) == 1


def test_a_stuck_queue_is_cancelled_and_rerun_once_then_escalated(repo, gh):
    """AC-072.3: only queued jobs beyond --queue-timeout → cancel + rerun; queued that long again → error with labels."""
    to_land(repo, gh)
    gh.checks = [[queued("test"), queued("docker")]]
    gh.run_status["42"] = ["queued", "completed", "queued"]
    with pytest.raises(core.PlatformError, match=r"run 42 .*runner set lan-shop-api picks up no jobs"):
        ship.land(repo, timeout=7200, interval=20, queue_timeout=300)
    assert [c[:2] for c in gh.calls if c[0] == "run" and c[1] in {"cancel", "rerun"}] == [["run", "cancel"], ["run", "rerun"]]


def test_a_check_cancelled_for_the_rerun_is_not_red(repo, gh):
    """AC-072.3: the healing's own cancel is not a red check; the rerun's green result merges."""
    to_land(repo, gh)
    stuck = [[queued("test")]] * 18
    gh.checks = stuck + [[check("test", "cancel")], [running("test")], [check("test", "pass")]]
    gh.run_status["42"] = ["completed"]
    ok, lines = ship.land(repo, timeout=7200, interval=20, queue_timeout=300)
    assert ok and gh.merges, lines
    assert not any("cancel" in s and "test" in s and "rerun" not in s for s in gh.said)


def test_a_busy_runner_is_not_stuck(repo, gh):
    """AC-072.3: queued jobs while another job of the PR runs are just waiting for a runner."""
    to_land(repo, gh)
    gh.checks = [[running("test"), queued("docker", run="43")]] * 30 + [[check("test", "pass"), check("docker", "pass")]]
    ok, _ = ship.land(repo, timeout=7200, interval=20, queue_timeout=300)
    assert ok and not any(c[:2] in (["run", "cancel"], ["run", "rerun"]) for c in gh.calls)


def test_each_conclusion_is_printed_once_as_it_happens(repo, gh):
    """AC-072.4: one progress line per concluded check."""
    to_land(repo, gh)
    gh.checks = [[check("quality", "pass"), queued("test")], [check("quality", "pass"), queued("test")],
                 [check("quality", "pass"), check("test", "pass"), check("branch-name", "skipping")]]
    ship.land(repo, timeout=600, interval=10)
    assert [s.split() for s in gh.said] == [["pass", "quality"], ["pass", "test"], ["skipping", "branch-name"]]


def to_deploy(repo):
    (repo / ".platform-app.yml").write_text(f"gitops_apps:\n  - {GITOPS}\n")
    st = ship.start(repo, "7", True)
    st.update(phase="deploy", merge_sha=SHA)
    ship.save_state(repo, st)


def test_deploy_fails_at_once_on_a_red_pin_dev_run(repo, gh):
    """AC-077.1 (replaces the PR-check version of AC-072.5): pin PRs carry no checks; the pin-dev run found by its name
    fails the deploy at once with its log."""
    to_deploy(repo)
    gh.pin_prs[GITOPS] = [{"number": 9, "state": "OPEN", "url": f"https://github.com/{GITOPS}/pull/9"}]
    gh.pin_runs[GITOPS] = [{"databaseId": 77, "displayTitle": f"pin-dev other sha-{SHA}"},
                           {"databaseId": 78, "displayTitle": f"pin-dev shop-api sha-{SHA}"}]
    gh.run_views["78"] = [{"status": "in_progress"}, {"status": "completed", "conclusion": "failure"}]
    ok, lines = ship.deploy(repo, timeout=1800, interval=20, context=None)
    assert not ok and "pin-dev run for 0123456 failed" in " ".join(lines)
    assert ["run", "view", "78", "-R", GITOPS, "--log-failed"] in gh.calls


def test_a_stuck_pin_dev_run_is_rerun_once(repo, gh):
    """AC-077.1: a pin-dev run queued beyond the queue timeout is cancelled and rerun once, then it is an error."""
    to_deploy(repo)
    gh.pin_runs[GITOPS] = [{"databaseId": 78, "displayTitle": f"pin-dev shop-api sha-{SHA}"}]
    gh.run_views["78"] = [{"status": "queued"}]
    gh.run_status["78"] = ["completed"]
    with pytest.raises(core.PlatformError, match="picks up no jobs"):
        ship.deploy(repo, timeout=7200, interval=20, context=None, queue_timeout=300)
    assert [c[:2] for c in gh.calls if c[:2] in (["run", "cancel"], ["run", "rerun"])] == [["run", "cancel"], ["run", "rerun"]]


def test_a_red_main_ci_fails_the_deploy_at_once(repo, gh):
    """AC-077.2: the service's own CI on main failed → nothing will be pinned; say so now."""
    to_deploy(repo)
    gh.main_runs = [{"databaseId": 5, "status": "completed", "conclusion": "failure"}]
    ok, lines = ship.deploy(repo, timeout=1800, interval=20, context=None)
    assert not ok and "CI on main is red" in lines[0]


def test_no_pin_dev_run_after_a_green_main_names_the_token(repo, gh):
    """AC-077.2: main CI green but no pin-dev run within the grace period → the GITOPS_TOKEN step."""
    to_deploy(repo)
    gh.main_runs = [{"databaseId": 5, "status": "completed", "conclusion": "success"}]
    with pytest.raises(core.PlatformError, match="no pin-dev run") as e:
        ship.deploy(repo, timeout=1800, interval=20, context=None)
    assert "GITOPS_TOKEN" in e.value.hint


def test_ship_start_refuses_a_linked_repo_without_gitops_token(repo, gh):
    """AC-077.4: linked to a gitops-app and no GITOPS_TOKEN → start stops with the fix; an unreadable list is not a no."""
    (repo / ".platform-app.yml").write_text(f"gitops_apps:\n  - {GITOPS}\n")
    gh.secrets = []
    with pytest.raises(core.PlatformError, match="GITOPS_TOKEN is not set") as e:
        ship.start(repo, "7", True)
    assert "gh secret set GITOPS_TOKEN -R acme/shop-api" in e.value.hint
    gh.secrets = ["GITOPS_TOKEN"]
    assert ship.start(repo, "7", True)["phase"] == "build"


def test_templates_warn_when_the_token_is_missing():
    """AC-077.4: the service CI's pin-dev job warns, not a notice nobody sees."""
    for t in ("service-go", "service-java", "service-python", "web-nextjs"):
        text = (core.PLATFORM_ROOT / "templates" / t / ".github" / "workflows" / "ci.yml").read_text()
        assert '::warning::GITOPS_TOKEN is not set' in text, t


def test_pin_dev_names_its_run_for_deploy():
    """AC-077.1: ship deploy finds the run by `pin-dev <service> <tag>`."""
    text = (core.PLATFORM_ROOT / "templates" / "gitops-app" / ".github" / "workflows" / "pin-dev.yml").read_text()
    assert "run-name: pin-dev ${{ github.event.client_payload.service }} ${{ github.event.client_payload.tag }}" in text


def test_argo_old_image_is_waiting_not_healthy(monkeypatch):
    """AC-077.3: Synced/Healthy on the old image is not done; the new image then is."""
    seq = [{"sync": {"status": "Synced"}, "health": {"status": "Healthy"}, "summary": {"images": ["ghcr.io/a/b:sha-old0000"]}},
           {"sync": {"status": "Synced"}, "health": {"status": "Healthy"}, "summary": {"images": [f"ghcr.io/a/b:sha-{SHA}"]}}]
    clock = {"t": 0.0}
    monkeypatch.setattr(ship, "now", lambda: clock["t"])
    monkeypatch.setattr(ship, "sleep", lambda s: clock.__setitem__("t", clock["t"] + s))
    calls = []
    monkeypatch.setattr(ship, "run", lambda cmd, **kw: calls.append(cmd) or subprocess.CompletedProcess(
        cmd, 0, json.dumps({"status": seq.pop(0) if len(seq) > 1 else seq[0]}), ""))
    new = seq.pop()                                   # Argo has not polled yet: the old image for the whole wait
    assert ship.argo_health("lan", "b-dev", 40, 20, images={f"sha-{SHA}"}).startswith("waiting for")
    seq[:] = [new]
    assert ship.argo_health("lan", "b-dev", 600, 20, images={f"sha-{SHA}"}) == "Synced/Healthy"


def test_argo_revision_must_reach_the_gitops_merge(monkeypatch, gh):
    """AC-077.3: a named app counts only once it is at, or past, the merged gitops commit."""
    st = {"sync": {"status": "Synced", "revision": "aaa1111"}, "health": {"status": "Healthy"}}
    monkeypatch.setattr(ship, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, json.dumps({"status": st}), ""))
    assert ship.argo_health("lan", "cfg", 0, 20, revision="bbb2222", slug=GITOPS).startswith("waiting for revision")
    st["sync"]["revision"] = "bbb2222"
    assert ship.argo_health("lan", "cfg", 0, 20, revision="bbb2222", slug=GITOPS) == "Synced/Healthy"


# ---------------- spec 075 ----------------

def test_ship_pr_runs_devbox_ci_first_and_never_pushes_red(repo, gh):
    """AC-075.2: with a `ci` recipe, red `devbox run ci` → nothing pushed, the output's tail in the error."""
    (repo / "devbox.json").write_text('{"shell": {"scripts": {"ci": "devbox run quality"}}}')
    ship.start(repo, "7", True)
    git(repo, "checkout", "-qb", "feature/007-price-alerts")
    (repo / "body.md").write_text("b")
    gh.ci_rc = 1
    with pytest.raises(core.PlatformError, match=r"devbox run ci. is red(.|\n)*Potential secret"):
        ship.open_pr(repo, "feat(alerts): price alerts", repo / "body.md")
    assert gh.pushes == [] and len(gh.ci) == 1
    gh.ci_rc = 0
    assert ship.open_pr(repo, "feat(alerts): price alerts", repo / "body.md")["pr"].endswith("/pull/7")
    assert gh.pushes == [repo]


# ---------------- spec 076 ----------------

def gitops_plan(repo, *, order="before-merge", apps=None, human=None):
    sp = spec.find(repo, "7")
    meta, body = sp.plan
    task = {"id": "g1", "title": "Component", "repo": GITOPS, "order": order, "files": ["applications/shop/services.yaml"],
            "covers": [], "parallel_safe": False, "depends_on": []}
    if apps:
        task["apps"] = apps
    meta["tasks"] = [*meta["tasks"], task]
    if human:
        meta["human_steps"] = human
    spec.save(sp.dir / "plan.md", meta, body)
    (repo / ".platform-app.yml").write_text(f"gitops_apps:\n  - {GITOPS}\n")


def test_spec_check_validates_gitops_tasks(repo):
    """AC-076.1: order and files are required, and the repo must be a linked gitops-app."""
    gitops_plan(repo)
    sp = spec.find(repo, "7")
    assert spec.check_plan(sp, *sp.plan) == []
    meta, body = sp.plan
    meta["tasks"][-1].update(order="later", files=[], repo="acme/other")
    meta["human_steps"] = [""]
    errs = " | ".join(spec.check_plan(sp, meta, body))
    assert "order: before-merge | after-release" in errs and "needs the files" in errs
    assert "acme/other is not a gitops-app" in errs and "human_steps" in errs


def test_gitops_prepare_and_pr_open_a_draft_pr(repo, gh):
    """AC-076.2: a checkout on spec/<spec>-<task>, then a pushed branch and a draft PR recorded in the state."""
    gitops_plan(repo)
    ship.start(repo, "7", True)
    d = ship.gitops_prepare(repo, "g1")
    assert git(d, "symbolic-ref", "--short", "HEAD") == f"spec/{spec.find(repo, '7').id}-g1"
    (repo / "body.md").write_text("b")
    with pytest.raises(core.PlatformError, match="has no commit"):
        ship.gitops_pr(repo, "g1", "feat(shop): component", repo / "body.md")
    (d / "x.yaml").write_text("a: 1\n")
    git(d, "add", "-A")
    git(d, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "c")
    info = ship.gitops_pr(repo, "g1", "feat(shop): component", repo / "body.md")
    assert info["pr"] == f"https://github.com/{GITOPS}/pull/3" and info["order"] == "before-merge"
    create = next(c for c in gh.calls if c[:2] == ["pr", "create"] and "-R" in c)
    assert "--draft" in create and ship.load_state(repo)["gitops"]["g1"]["pr"] == info["pr"]
    with pytest.raises(core.PlatformError, match="not a gitops task"):
        ship.gitops_prepare(repo, "t1")


def _with_gitops_pr(repo, order, **kw):
    gitops_plan(repo, order=order, **kw)
    ship.start(repo, "7", True)
    st = ship.load_state(repo)
    st["gitops"] = {"g1": {"repo": GITOPS, "order": order, "branch": "spec/x-g1", "pr": f"https://github.com/{GITOPS}/pull/3"}}
    ship.save_state(repo, st)


def test_land_merges_before_merge_gitops_prs_first_and_stops_on_red(repo, gh):
    """AC-076.3: green service PR → ready + checks + merge of the gitops PR, then the service PR; red gitops → nothing."""
    _with_gitops_pr(repo, "before-merge")
    git(repo, "checkout", "-qb", "feature/007-price-alerts")
    (repo / "body.md").write_text("b")
    ship.open_pr(repo, "feat(alerts): price alerts", repo / "body.md")
    gh.checks = [[check("test", "pass")]]
    gh.gitops_checks = [[{"name": "quality", "state": "FAILURE", "bucket": "fail", "link": GLINK}]]
    ok, lines = ship.land(repo, timeout=600, interval=10)
    assert not ok and gh.merges == [] and any("g1" in ln for ln in lines)
    assert ["pr", "ready", f"https://github.com/{GITOPS}/pull/3"] in gh.calls
    gh.gitops_checks = [[{"name": "quality", "state": "SUCCESS", "bucket": "pass", "link": GLINK}]]
    ok, _ = ship.land(repo, timeout=600, interval=10)
    assert ok and gh.merges == [f"https://github.com/{GITOPS}/pull/3", "https://github.com/acme/shop-api/pull/7"]


def test_a_missing_gitops_pr_blocks_the_pr(repo, gh):
    """AC-076.3: a gitops task without a PR stops `ship pr` before anything is pushed."""
    gitops_plan(repo)
    ship.start(repo, "7", True)
    git(repo, "checkout", "-qb", "feature/007-price-alerts")
    (repo / "body.md").write_text("b")
    with pytest.raises(core.PlatformError, match="without a PR: g1"):
        ship.open_pr(repo, "feat(alerts): price alerts", repo / "body.md")
    assert gh.pushes == []


def argo(monkeypatch, states):
    real = ship.run

    def fake(cmd, **kw):
        if cmd[0] == "kubectl":
            app = cmd[cmd.index("application") + 1]
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"status": states[app]}), "")
        return real(cmd, **kw)
    monkeypatch.setattr(ship, "run", fake)


HEALTHY = {"sync": {"status": "Synced"}, "health": {"status": "Healthy"}, "summary": {"images": [f"ghcr.io/acme/shop-api:sha-{SHA}"]}}


def _to_deploy(repo, gh, **kw):
    _with_gitops_pr(repo, "after-release", **kw)
    st = ship.load_state(repo)
    st.update(phase="deploy", merge_sha=SHA)
    ship.save_state(repo, st)
    gh.pin_prs[GITOPS] = [{"number": 9, "state": "MERGED", "url": f"https://github.com/{GITOPS}/pull/9"}]
    gh.gitops_checks = [[{"name": "quality", "state": "SUCCESS", "bucket": "pass", "link": GLINK}]]


def test_deploy_merges_after_release_prs_and_waits_for_every_named_app(repo, gh, monkeypatch):
    """AC-076.4 AC-076.5: after the pin: merge the after-release PR, check every app, end with the human steps."""
    _to_deploy(repo, gh, apps=["shop-config"], human=["delete the old push token"])
    argo(monkeypatch, {"shop-api-dev": HEALTHY, "shop-config": HEALTHY})
    ok, lines = ship.deploy(repo, timeout=600, interval=10, context="lan")
    assert ok and gh.merges == [f"https://github.com/{GITOPS}/pull/3"]
    assert "Argo CD shop-config: Synced/Healthy" in lines
    assert lines[-2:] == ["Human steps (the run cannot do these):", "- [ ] delete the old push token"]
    assert ship.load_state(repo)["phase"] == "done"


def test_a_sync_error_in_a_named_app_stops_the_deploy(repo, gh, monkeypatch):
    """AC-076.4: a SyncError of an affected app is an error with its message."""
    _to_deploy(repo, gh, apps=["shop-config"])
    broken = {**HEALTHY, "conditions": [{"type": "SyncError", "message": 'namespaces "shop-build" not found'}]}
    argo(monkeypatch, {"shop-api-dev": HEALTHY, "shop-config": broken})
    with pytest.raises(core.PlatformError, match='shop-config is SyncError: namespaces "shop-build" not found'):
        ship.deploy(repo, timeout=600, interval=10, context="lan")


def test_architect_and_plan_command_plan_gitops_tasks_with_expand_contract():
    """AC-076.6: the guidance exists where plans are written."""
    root = core.PLATFORM_ROOT / "plugins" / "svc"
    for f in (root / "agents" / "architect.md", root / "commands" / "plan.md"):
        text = f.read_text()
        assert "order: before-merge" in text and "after-release" in text and "expand/contract" in text, f
    ref = yaml.safe_load((core.PLATFORM_ROOT / "plugins" / "svc" / "skills" / "spec-format" / "references" / "plan.md")
                         .read_text().split("```yaml", 1)[1].split("```", 1)[0].strip().strip("-")) or {}
    assert any("repo" in t for t in ref.get("tasks", [])), "the plan reference shows a gitops task"
