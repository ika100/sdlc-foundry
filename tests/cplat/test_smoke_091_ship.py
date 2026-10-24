"""Spec 091 acceptance tests, `cplat ship deploy` with smoke in dev: AC-091.6 to AC-091.9, AC-091.11, AC-091.12, AC-091.14 and
AC-091.15 as the user sees them (output lines, exit code, ship state, run record, filed issue).

Seams: `ship.gh` / `ship.sleep` / `ship.now` and kubectl as in test_ship_checks, `smoke.gh` (gitops-app contents), `smoke.sleep`,
`smoke.reachable`, `smoke.run_recipe` and a fake `devbox` on PATH, and the autoissue fake tracker. `smoke` is only imported
inside the tests: it does not exist yet. Contract: design.md "Deploy output"."""
import dataclasses
import importlib
import subprocess

import pytest

import autoissue
import core
import ship
from test_autoissue import clk, tr, ai  # noqa: F401  (fixtures)
from test_runs import clock as run_clock, mem, store, stored  # noqa: F401  (fixtures)
from test_ship import SHA
from test_ship_checks import GITOPS, HEALTHY, argo, gh, to_deploy  # noqa: F401  (gh is a fixture)
from test_smoke_091_run import (APP, BASE, EXPOSED, HEALTH_ID, HIDDEN, SECRET, SLUG, TEST_ID, FakeDevbox, GitopsApi, make_service,
                                result_lines)

SPEC_ID = "007-price-alerts"
REASON = f"smoke red in dev: 1 failing ({SPEC_ID})"
PASS_ALL = (result_lines(("PASS", TEST_ID), ("PASS", HEALTH_ID)), 0)
FAIL_ONE = (result_lines(("FAIL", TEST_ID), ("PASS", HEALTH_ID)), 1)


def smoke_mod():
    return importlib.import_module("smoke")


@pytest.fixture()
def repo(tmp_path):
    return make_service(tmp_path)


class World:
    def __init__(self, repo, gh, store, tr, fake, monkeypatch):
        self.repo, self.gh, self.store, self.tr, self.fake, self.mp = repo, gh, store, tr, fake, monkeypatch
        self.sleeps: list[float] = []

    def install(self, services=EXPOSED, reachable=None):
        smoke = smoke_mod()
        self.mp.setattr(smoke, "sleep", self.sleeps.append)
        self.mp.setattr(smoke, "reachable", lambda url, timeout=10.0: reachable)
        self.mp.setattr(smoke, "gh", GitopsApi(services, APP))
        self.mp.delenv("LOCAL_HTTP_PORT", raising=False)
        to_deploy(self.repo)
        self.gh.pin_prs[GITOPS] = [{"number": 9, "state": "MERGED", "url": f"https://github.com/{GITOPS}/pull/9"}]
        argo(self.mp, {"shop-api-dev": HEALTHY})
        return self

    def deploy(self, *args, context="lan"):
        ctx = ["--context", context] if context else []
        return ship.main(["--repo", str(self.repo), "deploy", "--timeout", "600", "--interval", "10", *ctx, *args])

    def state(self):
        return ship.load_state(self.repo)

    def record(self):
        return stored(self.store)[-1]


@pytest.fixture()
def world(repo, gh, store, tr, tmp_path, monkeypatch):
    return World(repo, gh, store, tr, FakeDevbox(tmp_path, monkeypatch), monkeypatch)


def lines_of(capsys):
    return capsys.readouterr().out.splitlines()


def in_order(lines, *needles):
    at = -1
    for n in needles:
        nxt = next((i for i, ln in enumerate(lines) if i > at and ln.startswith(n)), None)
        assert nxt is not None, f"{n!r} missing or out of order in:\n" + "\n".join(lines)
        at = nxt


# ---------------- AC-091.6: smoke runs after Argo says healthy ----------------

def test_deploy_runs_every_smoke_test_against_the_published_dev_url_ac_091_6(world, capsys):  # AC-091.6
    world.install()
    world.fake.script([PASS_ALL])
    assert world.deploy() == 0
    out = lines_of(capsys)
    in_order(out, "Argo CD shop-api-dev: Synced/Healthy", f"smoke (dev) against {BASE}:", f"PASS  {TEST_ID}", f"PASS  {HEALTH_ID}",
             "smoke: 2 passed, 0 failed, 0 skipped", "criterion AC-007.1 (smoke): passed", "Smoke (dev): 2/2 passed")
    ((args, url, cwd),) = world.fake.calls
    assert args == "run smoke" and url == BASE
    st = world.state()
    assert st["phase"] == "done" and st["deployed"] == f"sha-{SHA}"
    assert world.tr.calls == [] and "failing:" not in "\n".join(out)


def test_a_base_url_option_overrides_the_computed_url_ac_091_6(world, capsys):  # AC-091.6
    world.install()
    world.fake.script([PASS_ALL])
    assert world.deploy("--base-url", "http://127.0.0.1:18088") == 0
    assert "smoke (dev) against http://127.0.0.1:18088:" in lines_of(capsys)
    assert world.fake.calls[0][1] == "http://127.0.0.1:18088"


def test_deploy_succeeds_only_if_smoke_passes_ac_091_6(world, capsys):  # AC-091.6
    world.install()
    world.fake.script([FAIL_ONE])
    assert world.deploy() == 1
    assert world.state()["phase"] != "done"


def test_the_state_remembers_the_smoke_result_ac_091_15(world, capsys):  # AC-091.15
    world.install()
    world.fake.script([PASS_ALL])
    world.deploy()
    sm = world.state()["smoke"]
    assert sm["outcome"] == "passed" and sm["row"] == "2/2 passed" and sm["url"] == BASE and "signature" in sm
    assert "  smoke: 2/2 passed" in ship.describe(world.state())


def test_the_run_record_of_a_passed_run_has_the_smoke_section_ac_091_15(world, capsys):  # AC-091.15
    world.install()
    world.fake.script([PASS_ALL])
    world.deploy()
    r = world.record()
    assert r["outcome"] == "done"
    sec = r["smoke"]
    assert (sec["env"], sec["outcome"], sec["base_url"]) == ("dev", "passed", BASE)
    assert (sec["passed"], sec["failed"], sec["skipped"], sec["retried"]) == (2, 0, 0, False)
    assert sec["criteria"] == {"AC-007.1": "passed"} and sec["filed"] is None and isinstance(sec["duration_s"], (int, float))


# ---------------- AC-091.7: retry ----------------

def test_a_pass_on_retry_is_reported_and_recorded_as_flaky_ac_091_7(world, capsys):  # AC-091.7
    world.install()
    world.fake.script([FAIL_ONE, PASS_ALL])
    assert world.deploy() == 0
    out = lines_of(capsys)
    assert world.sleeps == [30] and len(world.fake.calls) == 2
    assert "Smoke (dev): passed on retry" in out
    assert world.state()["phase"] == "done" and world.tr.calls == []
    sec = world.record()["smoke"]
    assert sec["outcome"] == "passed-on-retry" and sec["retried"] is True and sec["flaky"] == [TEST_ID]


# ---------------- AC-091.9, AC-091.14, AC-091.15: red smoke ----------------

def red_output():
    noise = [f"line {i}" for i in range(1, 91)]
    noise[88] = f"Authorization: token {SECRET}"
    return (noise + result_lines(("FAIL", TEST_ID), ("PASS", HEALTH_ID)), 1)


def test_red_smoke_stops_the_run_with_evidence_and_an_issue_ac_091_9(world, capsys, ai):  # AC-091.9
    world.install()
    world.fake.script([red_output()])
    assert world.deploy() == 1
    out = lines_of(capsys)
    in_order(out, f"smoke (dev) against {BASE}:", f"FAIL  {TEST_ID}", "smoke: 1 passed, 1 failed, 0 skipped",
             "retried after 30s: 1 failing again", "criterion AC-007.1 (smoke): failed", f"failing: {TEST_ID}",
             "--- smoke output (last 60 lines, secrets redacted) ---", f"issue: https://github.com/{SLUG}/issues/1 new",
             f"ship {SPEC_ID}: escalated ({REASON}); dev keeps running sha-{SHA}. Resume with /svc:ship {SPEC_ID}",
             f"Smoke (dev): red (1 failing, issue https://github.com/{SLUG}/issues/1)")
    text = "\n".join(out)
    assert SECRET not in text and "line 88" not in text and "line 90" in text           # redacted, and cut to the last 60 lines
    assert world.sleeps == [30]


def test_red_smoke_escalates_as_code_and_rolls_nothing_back_ac_091_9(world, capsys):  # AC-091.9
    world.install()
    world.fake.script([red_output()])
    world.deploy()
    st = world.state()
    assert st["escalated"] == REASON and st["cause"] == "code" and st["phase"] == "deploy"
    assert st["deployed"] == f"sha-{SHA}" and world.gh.merges == []
    r = world.record()
    assert r["outcome"] == "escalated" and r["escalation"] == {"reason": REASON, "cause": "code"}
    assert len(stored(world.store)) == 1                                     # escalated once, not twice


def test_red_smoke_files_one_issue_in_the_service_repo_ac_091_14(world, capsys, ai):  # AC-091.14
    world.install()
    world.fake.script([red_output()])
    world.deploy()
    ((_, repo, title, body, labels),) = world.tr.created()
    assert repo == SLUG and not world.tr.commented()                         # nothing in the platform repo (cause code)
    assert title == f"[auto] Smoke red in dev: {TEST_ID}"
    assert set(labels) == {"triage", "auto-filed", "smoke-failure"}
    sig = ai.signature("smoke", SLUG, "dev", TEST_ID)
    assert body.splitlines().count(f"Signature: {sig}") == 1 and len(autoissue.SIGNATURE_LINE.findall(body)) == 1
    rid = world.record()["run_id"]
    for needle in (SPEC_ID, f"sha-{SHA}", TEST_ID, "line 90", rid):
        assert needle in body, needle
    assert SECRET not in body


def test_the_record_carries_the_red_section_and_the_filed_entry_ac_091_15(world, capsys, ai):  # AC-091.15
    world.install()
    world.fake.script([red_output()])
    world.deploy()
    r = world.record()
    sig = ai.signature("smoke", SLUG, "dev", TEST_ID)
    sec = r["smoke"]
    assert sec["outcome"] == "red" and (sec["passed"], sec["failed"], sec["skipped"]) == (1, 1, 0) and sec["retried"] is True
    assert sec["failing"] == [TEST_ID] and sec["criteria"] == {"AC-007.1": "failed"}
    assert sec["filed"] == {"signature": sig, "url": f"https://github.com/{SLUG}/issues/1", "result": "new"}
    assert [f["signature"] for f in r["filed"]] == [sig]
    assert world.state()["smoke"]["signature"] == sig and world.state()["smoke"]["outcome"] == "red"


def test_a_failing_filing_changes_nothing_about_the_run_ac_091_14(world, capsys, ai):  # AC-091.14
    world.install()
    world.tr.error = ai.TrackerError("no permission to create issues")
    world.fake.script([red_output()])
    assert world.deploy() == 1
    out = lines_of(capsys)
    assert any(ln.startswith("issue: not filed: no permission") for ln in out)
    assert world.state()["escalated"] == REASON
    assert f"Smoke (dev): red (1 failing, issue not filed: no permission to create issues)" in out or \
        any(ln.startswith("Smoke (dev): red (1 failing, issue not filed") for ln in out)
    assert world.record()["smoke"]["filed"]["result"] == "pending"


# ---------------- AC-091.8: the limit ----------------

def test_a_run_that_hits_the_limit_is_red_without_a_retry_ac_091_8(world, capsys, monkeypatch):  # AC-091.8
    world.install()
    smoke = smoke_mod()
    limits = []

    def endless(repo, base_url, timeout):
        limits.append(timeout)
        kw = {}
        for f in dataclasses.fields(smoke.Attempt):
            kw[f.name] = {"exit_code": None, "tests": [], "output": "", "duration_s": float(timeout)}.get(f.name, 0)
        return smoke.Attempt(**kw)
    monkeypatch.setattr(smoke, "run_recipe", endless)
    assert world.deploy() == 1
    out = lines_of(capsys)
    assert limits == [600] and world.sleeps == []
    assert any("timed out after 600s" in ln for ln in out)
    assert f"ship {SPEC_ID}: escalated ({REASON}); dev keeps running sha-{SHA}. Resume with /svc:ship {SPEC_ID}" in out
    assert world.record()["smoke"]["outcome"] == "timed-out"
    assert world.state()["cause"] == "code"


# ---------------- AC-091.11 / AC-091.15: smoke not run ----------------

def assert_not_run(world, capsys, reason):
    out = lines_of(capsys)
    in_order(out, f"smoke not run: {reason}", "unchecked (smoke) criteria: AC-007.1", f"Smoke (dev): not run: {reason}")
    assert world.fake.calls == [] and world.tr.calls == []
    st = world.state()
    assert st["phase"] == "done" and not st.get("escalated")
    r = world.record()
    assert r["outcome"] == "done"
    sec = r["smoke"]
    assert sec["outcome"] == "not-run" and sec["reason"] == reason and sec["criteria"] == {"AC-007.1": "unchecked"}
    assert (sec["passed"], sec["failed"], sec["skipped"]) == (0, 0, 0) and sec["filed"] is None


def test_without_a_kube_context_smoke_is_not_run_ac_091_11(world, capsys):  # AC-091.11
    world.install()
    assert world.deploy(context=None) == 0
    assert_not_run(world, capsys, "no kube context, so Argo health was not checked (pass --context <kube-context>)")


def test_a_service_not_exposed_in_dev_is_not_run_ac_091_11(world, capsys):  # AC-091.11
    world.install(services=HIDDEN)
    assert world.deploy() == 0
    assert_not_run(world, capsys, "shop-api has no dev URL (not exposed in dev)")


def test_an_unreachable_dev_url_is_not_run_and_not_escalated_ac_091_11(world, capsys):  # AC-091.11
    world.install(reachable="connection refused")
    assert world.deploy() == 0
    assert_not_run(world, capsys, f"dev URL {BASE} is not reachable: connection refused")


def test_a_repo_not_linked_to_a_gitops_app_is_not_run_ac_091_11(world, capsys, gh):  # AC-091.11
    smoke = smoke_mod()
    world.mp.setattr(smoke, "sleep", lambda s: None)
    st = ship.start(world.repo, "7", True)
    st.update(phase="deploy", merge_sha=SHA)
    ship.save_state(world.repo, st)
    assert world.deploy(context=None) == 0
    assert_not_run(world, capsys, "the repo is not linked to a gitops-app")


def test_not_run_never_counts_as_passed_in_the_row_ac_091_15(world, capsys):  # AC-091.15
    world.install(services=HIDDEN)
    world.deploy()
    rows = [ln for ln in lines_of(capsys) if ln.startswith("Smoke (dev):")]
    assert rows and all("passed" not in ln for ln in rows)
    assert world.state()["smoke"]["outcome"] == "not-run" and "  smoke: not run:" in ship.describe(world.state())


# ---------------- AC-091.12: resume ----------------

def refuse_kube(monkeypatch):
    inner = ship.run

    def run(cmd, **kw):
        assert cmd[0] != "kubectl", "a resumed run must not check Argo again"
        return inner(cmd, **kw)
    monkeypatch.setattr(ship, "run", run)


def resume(world):
    refuse_kube(world.mp)
    world.gh.calls.clear()
    ship.start(world.repo, "7", True)
    assert ship.load_state(world.repo)["phase"] == "deploy" and "escalated" not in ship.load_state(world.repo)


def test_resuming_after_red_smoke_runs_only_smoke_again_ac_091_12(world, capsys):  # AC-091.12
    world.install()
    world.fake.script([FAIL_ONE])
    assert world.deploy() == 1
    first = world.record()["run_id"]
    capsys.readouterr()
    world.fake.script([PASS_ALL])
    resume(world)
    assert world.deploy(context=None) == 0
    out = lines_of(capsys)
    assert "resuming: smoke only, against what dev runs now" in out and "Smoke (dev): 2/2 passed" in out
    assert not any(ln.startswith("Argo CD") for ln in out) and not any(c[:2] == ["pr", "list"] for c in world.gh.calls)
    assert world.state()["phase"] == "done"
    r = world.record()
    assert r["outcome"] == "done" and r["resumes"] == first and r["smoke"]["outcome"] == "passed"


def test_a_resumed_red_result_files_again_as_a_plus_one_ac_091_12(world, capsys):  # AC-091.12
    world.install()
    world.fake.script([FAIL_ONE])
    world.deploy()
    capsys.readouterr()
    resume(world)
    assert world.deploy(context=None) == 1
    out = lines_of(capsys)
    assert f"issue: https://github.com/{SLUG}/issues/1 +1" in out
    assert len(world.tr.created()) == 1 and len(world.tr.commented()) == 1
    assert world.state()["escalated"] == REASON and world.state()["cause"] == "code"
    assert f"ship {SPEC_ID}: escalated ({REASON}); dev keeps running sha-{SHA}. Resume with /svc:ship {SPEC_ID}" in out


# ---------------- AC-091.15: the final report ----------------

def test_the_ship_command_reports_the_smoke_row_ac_091_15():  # AC-091.15
    text = (core.PLATFORM_ROOT / "plugins/svc/commands/ship.md").read_text()
    assert "Smoke (dev)" in text and "passed on retry" in text and "not run" in text
    assert "(smoke)" in text and "unchecked" in text


def test_the_ship_command_does_not_escalate_red_smoke_twice_ac_091_9():  # AC-091.9
    text = (core.PLATFORM_ROOT / "plugins/svc/commands/ship.md").read_text()
    assert "smoke red in dev" in text and "--base-url" in text
