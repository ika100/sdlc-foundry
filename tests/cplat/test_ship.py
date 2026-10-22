"""Specs 066 and 067: /svc:ship's state, land-on-green, deploy wait, and the Stop hook gate."""
import json
import subprocess

import pytest

import core
import ship
import spec
from test_spec import PASSING, make

SHA = "0123456789abcdef0123456789abcdef01234567"


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "shop-api"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    (r / ".copier-answers.yml").write_text("_src_path: gh:ika100/sdlc-foundry/templates/service-go\nproject_name: shop-api\n")
    make(r, status="approved")
    git(r, "add", "-A")
    git(r, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
    git(r, "remote", "add", "origin", "https://github.com/acme/shop-api.git")
    return r


class FakeGh:
    """Scripted `gh`: PR list/create/view, checks sequence, pin PRs in gitops repos, failed logs."""

    def __init__(self):
        self.checks: list[list[dict]] = []
        self.pr_state = "OPEN"
        self.pin_prs: dict[str, list[dict]] = {}
        self.calls: list[list[str]] = []

    def __call__(self, args, *, cwd, check=True):
        self.calls.append(args)
        if args[:2] == ["pr", "list"] and "-R" in args:
            return json.dumps(self.pin_prs.get(args[args.index("-R") + 1], []))
        if args[:2] == ["pr", "list"]:
            return "[]"
        if args[:2] == ["pr", "create"]:
            return "https://github.com/acme/shop-api/pull/7\n"
        if args[:2] == ["pr", "view"] and "state,mergeCommit" in args:
            return json.dumps({"state": self.pr_state, "mergeCommit": None})
        if args[:2] == ["pr", "view"]:
            return json.dumps({"mergeCommit": {"oid": SHA}})
        if args[:2] == ["pr", "checks"]:
            return json.dumps(self.checks.pop(0) if len(self.checks) > 1 else self.checks[0])
        if args[:2] == ["run", "view"]:
            return "step 1\nFAIL TestPriceAlert\nexit status 1\n"
        raise AssertionError(args)


@pytest.fixture()
def gh(monkeypatch):
    fake = FakeGh()
    monkeypatch.setattr(ship, "gh", fake)
    clock = {"t": 0.0}
    monkeypatch.setattr(ship, "now", lambda: clock["t"])
    monkeypatch.setattr(ship, "sleep", lambda s: clock.__setitem__("t", clock["t"] + s))
    merges = []
    real_run = ship.run

    def fake_run(cmd, **kw):
        if cmd[:3] == ["gh", "pr", "merge"]:
            merges.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd[:2] == ["git", "push"] or cmd[:2] == ["git", "pull"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return real_run(cmd, **kw)
    monkeypatch.setattr(ship, "run", fake_run)
    fake.merges = merges
    return fake


def check(name, bucket):
    return {"name": name, "state": bucket.upper(), "bucket": bucket, "link": f"https://github.com/acme/shop-api/actions/runs/42/job/{name}"}


def to_land(repo, gh, merge=True):
    ship.start(repo, "7", merge)
    git(repo, "checkout", "-qb", "feature/007-price-alerts")
    body = repo / ".git" / "PR_BODY.md"
    body.write_text("## Summary\n")
    return ship.open_pr(repo, "feat(alerts): price alerts", body)


# ---------------- spec 067: state and resume ----------------

def test_start_resumes_and_refuses_unapproved_specs(repo):
    """AC-067.1: an approved spec starts at plan or build; a second start resumes the same run; drafts are refused."""
    st = ship.start(repo, "7", True)
    assert st["phase"] == "build" and st["branch"] == "feature/007-price-alerts"   # the fixture's plan is valid
    ship.set_phase(repo, "pr")
    assert ship.start(repo, "007", True)["phase"] == "pr"                            # resume, not restart
    assert ship.state_path(repo).parent.name == ".git"                              # local, never committed
    ship.finish(repo)
    spec.set_status(spec.find(repo, "7"), "draft", "amend")
    with pytest.raises(core.PlatformError, match="only an approved spec"):
        ship.start(repo, "7", True)


def test_a_spec_without_a_valid_plan_starts_with_planning(repo):
    make(repo, status="approved", hash_="stale")
    assert ship.start(repo, "7", True)["phase"] == "plan"


def test_pr_is_opened_from_the_feature_branch_with_a_conventional_title(repo, gh):
    """AC-067.2: the PR is opened (or reused) from the spec's feature branch."""
    ship.start(repo, "7", True)
    with pytest.raises(core.PlatformError, match="expected the feature branch"):
        ship.open_pr(repo, "feat(alerts): price alerts", repo / "x")
    git(repo, "checkout", "-qb", "feature/007-price-alerts")
    (repo / "body.md").write_text("b")
    with pytest.raises(core.PlatformError, match="Conventional Commit"):
        ship.open_pr(repo, "Price alerts", repo / "body.md")
    st = ship.open_pr(repo, "feat(alerts): price alerts", repo / "body.md")
    assert st["pr"].endswith("/pull/7") and st["phase"] == "land"


# ---------------- spec 065 / 067: land only on green ----------------

def test_land_waits_for_pending_checks_and_merges_when_all_pass(repo, gh):
    """AC-065.5 AC-067.2: no merge while a check is pending; all green → squash merge, then the deploy phase."""
    to_land(repo, gh)
    gh.checks = [[check("test", "pending"), check("quality", "pass")], [check("test", "pass"), check("quality", "pass"), check("lint", "skipping")]]
    ok, lines = ship.land(repo, timeout=600, interval=10)
    assert ok and gh.merges == [["gh", "pr", "merge", "https://github.com/acme/shop-api/pull/7", "--squash", "--delete-branch"]]
    st = ship.load_state(repo)
    assert st["phase"] == "deploy" and st["merge_sha"] == SHA


def test_a_red_check_is_never_merged_and_its_log_is_returned(repo, gh):
    """AC-065.5 AC-067.3: one failed check → no merge, the failing log tail for the fix loop, a counted fix round."""
    to_land(repo, gh)
    gh.checks = [[check("test", "fail"), check("quality", "pass")]]
    ok, lines = ship.land(repo, timeout=600, interval=10)
    assert not ok and gh.merges == []
    assert "RED: 1 of 2" in lines[0] and any("FAIL TestPriceAlert" in ln for ln in lines)
    assert ship.load_state(repo)["fix_rounds"] == 1 and ship.load_state(repo)["phase"] == "land"


def test_a_pr_without_any_check_is_never_merged(repo, gh):
    """AC-065.5: no reported check is not green."""
    to_land(repo, gh)
    gh.checks = [[]]
    with pytest.raises(core.PlatformError, match="no CI checks were reported"):
        ship.land(repo, timeout=3600, interval=30)
    assert gh.merges == []


def test_no_merge_stops_at_a_green_pr(repo, gh):
    """AC-067.4: --no-merge ends the run at a green PR."""
    to_land(repo, gh, merge=False)
    gh.checks = [[check("test", "pass")]]
    ok, lines = ship.land(repo, timeout=60, interval=10)
    assert ok and gh.merges == [] and ship.load_state(repo)["phase"] == "done"


# ---------------- spec 067: deploy ----------------

def test_deploy_waits_for_the_pin_pr_of_the_merge_commit(repo, gh):
    """AC-067.5: dev is reached when the gitops-app merged pin/dev-<service>-<sha7>."""
    (repo / ".platform-app.yml").write_text("# gitops-app repos\n- acme/shop-gitops\n")
    to_land(repo, gh)
    gh.checks = [[check("test", "pass")]]
    ship.land(repo, timeout=60, interval=10)
    gh.pin_prs = {"acme/shop-gitops": [{"number": 3, "state": "OPEN", "url": "u3"}]}
    calls = {"n": 0}
    real = ship.sleep

    def tick(s):
        calls["n"] += 1
        gh.pin_prs["acme/shop-gitops"][0]["state"] = "MERGED"
        real(s)
    ship.sleep = tick
    try:
        ok, lines = ship.deploy(repo, timeout=600, interval=10, context=None)
    finally:
        ship.sleep = real
    assert ok and "dev pinned to shop-api:sha-0123456" in lines[0]
    assert any(a[:2] == ["pr", "list"] and "pin/dev-shop-api-0123456" in a for a in gh.calls)
    assert ship.load_state(repo)["phase"] == "done" and ship.load_state(repo)["deployed"] == "sha-0123456"


def test_a_closed_pin_pr_fails_the_deploy(repo, gh):
    (repo / ".platform-app.yml").write_text("- acme/shop-gitops\n")
    to_land(repo, gh)
    gh.checks = [[check("test", "pass")]]
    ship.land(repo, timeout=60, interval=10)
    gh.pin_prs = {"acme/shop-gitops": [{"number": 3, "state": "CLOSED", "url": "u3"}]}
    with pytest.raises(core.PlatformError, match="closed without merging"):
        ship.deploy(repo, timeout=600, interval=10, context=None)


def test_unlinked_repos_finish_without_waiting(repo, gh):
    """AC-067.5: no .platform-app.yml → nothing to wait for; the report says why."""
    to_land(repo, gh)
    gh.checks = [[check("test", "pass")]]
    ship.land(repo, timeout=60, interval=10)
    ok, lines = ship.deploy(repo, timeout=600, interval=10, context=None)
    assert ok and "not linked to a gitops-app" in lines[0]


# ---------------- spec 066: Stop hook ----------------

def test_no_run_never_blocks(repo):
    """AC-066.3: sessions without a ship run stop as before."""
    assert ship.gate(repo, {}, 8, run_tests=False) is None


def test_an_unfinished_run_blocks_with_the_next_step(repo):
    """AC-066.1: an unfinished run blocks the stop and says what to do next."""
    ship.start(repo, "7", True)
    ship.set_phase(repo, "land")
    ans = ship.gate(repo, {"stop_hook_active": True}, 8, run_tests=False)
    assert ans["decision"] == "block" and "cplat ship land" in ans["reason"] and "cplat ship escalate" in ans["reason"]


def test_the_build_phase_reports_what_is_still_red(repo):
    """AC-066.1: in the build phase the reason names untraced criteria."""
    ship.start(repo, "7", True)
    ans = ship.gate(repo, {}, 8, run_tests=True)
    assert "Criteria without a test" in ans["reason"] and "AC-007.1" in ans["reason"]


def test_escalation_finish_and_the_block_cap_let_the_session_stop(repo):
    """AC-066.2: escalated or done runs stop; after N blocked stops the gate gives up and records why."""
    ship.start(repo, "7", True)
    for _ in range(3):
        assert ship.gate(repo, {}, 3, run_tests=False)["decision"] == "block"
    final = ship.gate(repo, {}, 3, run_tests=False)
    assert "decision" not in final and "stopped after 3" in final["systemMessage"]
    assert "gave up" in ship.load_state(repo)["escalated"]
    assert ship.gate(repo, {}, 3, run_tests=False) is None
    st = ship.start(repo, "7", True)                       # resume clears the escalation and the counter
    assert "escalated" not in st and st["blocks"] == 0
    ship.escalate(repo, "merge conflict in alerts.go")
    assert ship.gate(repo, {}, 3, run_tests=False) is None
    ship.start(repo, "7", True)
    ship.set_phase(repo, "done")
    assert ship.gate(repo, {}, 3, run_tests=False) is None


def test_the_stop_hook_only_starts_cplat_when_a_run_exists():
    """AC-066.3: the hook command exits before starting Python when there is no state file."""
    hooks = json.loads((core.PLATFORM_ROOT / "plugins" / "shared" / "hooks" / "hooks.json").read_text())
    cmd = hooks["hooks"]["Stop"][0]["hooks"][0]["command"]
    assert cmd.index("cplat-ship.json") < cmd.index("ship gate") and "|| exit 0" in cmd


def test_gate_cli_reads_the_hook_input(repo, capsys, monkeypatch):
    ship.start(repo, "7", True)
    ship.set_phase(repo, "deploy")
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"cwd": str(repo), "stop_hook_active": False})))
    assert ship.main(["gate"]) == 0
    assert json.loads(capsys.readouterr().out)["decision"] == "block"


def test_done_spec_resumes_at_the_pr(repo):
    s = spec.find(repo, "7")
    spec.set_status(s, "building", None)
    (s.dir / "verification.md").write_text(PASSING)
    spec.set_status(spec.find(repo, "7"), "done", None)
    assert ship.start(repo, "7", True)["phase"] == "pr"
