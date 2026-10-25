"""Specs 078 and 079: the full commit sha is the pin format; `cplat pr wait` and the transient rerun."""
import json
import subprocess

import pytest
import yaml

import core
import pr as prmod
import promote
import ship
from test_gitops import SHA, composed, gh as gitops_gh, gitops_repo, pin, run_pin  # noqa: F401  (fixtures)
from test_ship import FakeGh, check

ROOT = core.PLATFORM_ROOT
SERVICE_TEMPLATES = ("service-go", "service-java", "service-python", "web-nextjs")


# ---------------- spec 078 ----------------

@pytest.mark.parametrize("t", SERVICE_TEMPLATES)
def test_service_ci_publishes_and_dispatches_the_full_sha(t):
    """AC-078.1: `sha-<40>` is pushed (with `sha-<7>` for one release) and sent to pin-dev."""
    text = (ROOT / "templates" / t / ".github" / "workflows" / "ci.yml").read_text()
    assert "type=sha,prefix=sha-,format=long" in text and "type=sha,prefix=sha-,format=short" in text
    assert 'tag="sha-${GITHUB_SHA}"' in text and "GITHUB_SHA::7" not in text


def test_pin_dev_accepts_both_formats_and_keeps_the_short_branch():
    """AC-078.2: both formats pass the guard; the branch name uses the first 7 characters."""
    text = (ROOT / "templates" / "gitops-app" / ".github" / "workflows" / "pin-dev.yml").read_text()
    assert '^sha-([0-9a-f]{40}|[0-9a-f]{7})$' in text
    assert 'branch="pin/dev-$SERVICE-${sha::7}"' in text


def test_pin_accepts_the_full_sha(gitops_repo, gitops_gh):
    """AC-078.2: `pin.py` writes `sha-<40>` and still accepts `sha-<7>`."""
    composed(gitops_repo, "todo-api")
    out = run_pin(gitops_repo, "dev", "todo-api", "sha-" + "b" * 40)
    assert out.returncode == 0, out.stderr
    assert pin(gitops_repo, "dev", "todo-api") == "sha-" + "b" * 40
    assert run_pin(gitops_repo, "dev", "todo-api", "sha-abc1234").returncode == 0
    assert run_pin(gitops_repo, "dev", "todo-api", "sha-" + "b" * 39).returncode != 0


def test_promote_pins_the_full_sha_and_falls_back_to_the_short_one(gitops_repo, gitops_gh):
    """AC-078.2: staging gets `sha-<40>`; an image built before 4.4.0 only has `sha-<7>`, which is then used."""
    composed(gitops_repo, "todo-api")
    gitops_gh.image_tags["todo-api"] |= {"sha-" + SHA}
    promote.main(["todo-api", "dev", "staging", "--repo-dir", str(gitops_repo)])
    assert pin(gitops_repo, "staging", "todo-api") == "sha-" + SHA


def test_the_decision_is_recorded():
    """AC-078.3: ADR-030 exists and the agents document the full sha."""
    adr = (ROOT / "docs" / "adr" / "030-image-tags-are-the-full-commit-sha.md").read_text()
    assert "`sha-<40>`" in adr and "030" in (ROOT / "docs" / "adr" / "README.md").read_text()
    for plugin in ("svc", "svc-go", "svc-java", "web"):
        text = (ROOT / "plugins" / plugin / "agents" / "deployment.md").read_text()
        assert "`sha-<40>`" in text, plugin


# ---------------- spec 079 ----------------

class Gh(FakeGh):
    """FakeGh plus `pr view` by URL, run reruns and a failed log per run id."""

    def __init__(self):
        super().__init__()
        self.logs: dict[str, list[str]] = {}
        self.state = "OPEN"
        self.heads: list[str] = []            # successive headRefOid answers
        self.run_heads: dict[str, str] = {}   # run id -> commit it ran on

    def __call__(self, args, *, cwd, check=True):
        if args[:2] == ["pr", "view"] and "state,url" in args:
            self.calls.append(args)
            return json.dumps({"state": self.state, "url": "https://github.com/acme/other/pull/5"})
        if args[:2] == ["run", "view"] and "--log-failed" in args:
            self.calls.append(args)
            seq = self.logs.get(args[2], ["FAIL TestPriceAlert"])
            return seq.pop(0) if len(seq) > 1 else seq[0]
        if args[:2] == ["run", "rerun"]:
            self.calls.append(args)
            return ""
        if args[:2] == ["pr", "view"] and "headRefOid" in args:
            seq = self.heads
            return json.dumps({"headRefOid": seq.pop(0) if len(seq) > 1 else seq[0]}) if seq else "{}"
        if args[:2] == ["run", "view"] and "headSha" in args:
            return json.dumps({"headSha": self.run_heads[args[2]]}) if args[2] in self.run_heads else "{}"
        return super().__call__(args, cwd=cwd, check=check)


@pytest.fixture()
def fake(monkeypatch, tmp_path):
    g = Gh()
    monkeypatch.setattr(ship, "gh", g)
    clock = {"t": 0.0}
    monkeypatch.setattr(ship, "now", lambda: clock["t"])
    monkeypatch.setattr(ship, "sleep", lambda s: clock.__setitem__("t", clock["t"] + s))
    g.said, g.merges = [], []
    monkeypatch.setattr(ship, "say", g.said.append)

    def fake_run(cmd, **kw):
        if cmd[:3] == ["gh", "pr", "merge"]:
            g.merges.append(cmd[3])
            return subprocess.CompletedProcess(cmd, 0, "", "")
        raise AssertionError(cmd)
    monkeypatch.setattr(prmod, "run", fake_run)
    return g


def test_pr_wait_merges_on_green_and_resolves_numbers(fake, tmp_path):
    """AC-079.1: -R with a number builds the URL; green + --merge squash-merges."""
    assert prmod.url_of("5", "acme/other") == "https://github.com/acme/other/pull/5"
    assert prmod.url_of("https://github.com/x/y/pull/1", None) == "https://github.com/x/y/pull/1"
    fake.checks = [[check("quality", "pending")], [check("quality", "pass")]]
    ok, lines = prmod.wait(tmp_path, "https://github.com/acme/other/pull/5", True, 600, 10, 300)
    assert ok and fake.merges == ["https://github.com/acme/other/pull/5"] and lines[-1].startswith("merged")


def test_pr_wait_is_red_without_merging(fake, tmp_path):
    """AC-079.1: a red check → exit 1 with the log tail, no merge."""
    fake.checks = [[check("test", "fail")]]
    ok, lines = prmod.wait(tmp_path, "https://github.com/acme/other/pull/5", True, 600, 10, 300)
    assert not ok and fake.merges == [] and lines[0].startswith("RED")


def test_a_transient_failure_is_rerun_once(fake, tmp_path):
    """AC-079.2 AC-079.3: a Maven download error → `gh run rerun --failed` once; the rerun's green merges."""
    maven = "[ERROR] Failed to read artifact descriptor for org.apache.maven.shared:maven-shared-utils:jar:3.4.2"
    fake.checks = [[check("java", "fail")], [check("java", "fail")], [check("java", "pending")], [check("java", "pass")]]
    fake.logs["42"] = [maven]
    ok, _ = prmod.wait(tmp_path, "https://github.com/acme/other/pull/5", True, 600, 10, 300)
    assert ok and fake.merges
    assert [c for c in fake.calls if c[:2] == ["run", "rerun"]] == [["run", "rerun", "42", "-R", "acme/shop-api", "--failed"]]
    assert any("transient" in s for s in fake.said)


def test_a_transient_failure_that_fails_again_is_red(fake, tmp_path):
    """AC-079.2: only one rerun; a second red after the grace period is final."""
    fake.checks = [[check("java", "fail")]]
    fake.logs["42"] = ["connection reset by peer"]
    ok, lines = prmod.wait(tmp_path, "https://github.com/acme/other/pull/5", False, 3600, 30, 300)
    assert not ok and sum(c[:2] == ["run", "rerun"] for c in fake.calls) == 1


def test_a_registry_rate_limit_is_transient(fake, tmp_path):
    """AC-079.2: a registry 429 (`invalid response status 429`) is rerun once like any other transient failure."""
    assert ship.TRANSIENT.search("ERROR: failed to solve: ghcr.io/acme/base: invalid response status 429 Too Many Requests")
    fake.checks = [[check("image", "fail")], [check("image", "fail")], [check("image", "pending")], [check("image", "pass")]]
    fake.logs["42"] = ["error: unexpected status from HEAD request: invalid response status 429"]
    ok, _ = prmod.wait(tmp_path, "https://github.com/acme/other/pull/5", True, 600, 10, 300)
    assert ok and sum(c[:2] == ["run", "rerun"] for c in fake.calls) == 1


def test_a_real_failure_is_not_rerun(fake, tmp_path):
    """AC-079.2: an assertion failure is the change's fault: red at once."""
    fake.checks = [[check("test", "fail")]]
    fake.logs["42"] = ["--- FAIL: TestPriceAlert (0.00s)", "expected 3, got 4"]
    ok, _ = prmod.wait(tmp_path, "https://github.com/acme/other/pull/5", False, 600, 10, 300)
    assert not ok and not any(c[:2] == ["run", "rerun"] for c in fake.calls)


def test_cplat_knows_pr_wait():
    """AC-079.1: the command is registered."""
    import cplat
    assert cplat.COMMANDS["pr"] == "pr" and "pr wait" in cplat.__doc__


def _run_check(name, bucket, run):
    return {**check(name, bucket), "link": f"https://github.com/acme/shop-api/actions/runs/{run}/job/{name}"}


PR = "https://github.com/acme/other/pull/5"


def test_old_head_red_while_new_head_is_pending_is_not_red(fake, tmp_path):
    """AC-079.1: right after a push the previous commit's red check is ignored; the new head's green ends GREEN."""
    fake.heads, fake.run_heads = ["new"], {"41": "old", "42": "new"}
    fake.checks = [[_run_check("test", "fail", 41), _run_check("test", "pending", 42)],
                   [_run_check("test", "fail", 41), _run_check("test", "pass", 42)]]
    ok, lines = prmod.wait(tmp_path, PR, False, 600, 10, 300)
    assert ok and lines[0].startswith("GREEN: all 1 check(s)")


def test_a_new_head_without_checks_yet_is_pending_not_no_checks(fake, tmp_path):
    """AC-079.1: only the old head's checks exist → keep waiting (no 'no checks' error, no stale verdict)."""
    fake.heads, fake.run_heads = ["new"], {"41": "old", "42": "new"}
    fake.checks = [[_run_check("test", "fail", 41)]] * 3 + [[_run_check("test", "fail", 41), _run_check("test", "pass", 42)]]
    ok, lines = prmod.wait(tmp_path, PR, False, 600, 10, 300)
    assert ok and lines[0].startswith("GREEN")


def test_a_head_change_mid_wait_restarts_for_the_newest_head(fake, tmp_path):
    """AC-079.1: a push while waiting → the result is the newest head's, not the first head's red."""
    fake.heads, fake.run_heads = ["a", "a", "b"], {"41": "a", "42": "b"}
    fake.checks = [[_run_check("test", "pending", 41)], [_run_check("test", "pending", 42)], [_run_check("test", "pass", 42)]]
    ok, lines = prmod.wait(tmp_path, PR, False, 600, 10, 300)
    assert ok and lines[0].startswith("GREEN")


def test_merge_never_acts_on_the_old_heads_green(fake, tmp_path):
    """AC-079.1: the old head is green, the new head red → no merge."""
    fake.heads, fake.run_heads = ["new"], {"41": "old", "42": "new"}
    fake.checks = [[_run_check("test", "pass", 41)], [_run_check("test", "pass", 41), _run_check("test", "fail", 42)]]
    ok, lines = prmod.wait(tmp_path, PR, True, 600, 10, 300)
    assert not ok and fake.merges == [] and lines[0].startswith("RED")
