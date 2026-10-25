"""Spec 105 acceptance tests, a deploy counts only after its checks pass: the image digest in the smoke record (AC-105.1), the
digest match before a staging pin (AC-105.2) and in the prod evidence (AC-105.3), the failure class (AC-105.4), the retries per
class and the environment escalation (AC-105.5), `NOT VERIFIED` (AC-105.6) and replays (AC-105.7).

Seams (design.md "Contract"): `cluster.running_digest`, `registry.digest` / `registry.gh`, `smoke.classify` / `smoke.status`,
plus the ones of test_staging_093_ship (fake gitops-app, fake devbox, kubectl via `ship.run`, autoissue fake tracker).
`cluster`, `registry` and the new `smoke` symbols are only imported inside the tests: they do not exist yet."""
import importlib
import json
import os
import re
import stat
import subprocess

import pytest

import ship
import spec as specmod
from test_autoissue import clk, tr, ai  # noqa: F401  (fixtures)
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)
from test_ship_checks import GITOPS, HEALTHY, argo, gh  # noqa: F401  (gh is a fixture)
from test_smoke_091_run import BASE, SLUG, TEST_ID, HEALTH_ID, FakeDevbox, Seams, result_lines, svc, fake, seams, sp  # noqa: F401
from test_smoke_091_ship import FAIL_ONE, PASS_ALL, in_order, lines_of, repo  # noqa: F401  (fixtures)
from test_staging_093_ship import STAGING_URL, TAG, SWorld, sw  # noqa: F401  (fixtures)
from test_staging_093_evidence import E, SVC, dev_rec, stg, ev, summary  # noqa: F401  (fixtures)

SPEC_ID = "007-price-alerts"
D1 = "sha256:" + "1" * 64
D2 = "sha256:" + "2" * 64
IMAGE = "ghcr.io/acme/shop-api"
FAIL_ALL = (result_lines(("FAIL", TEST_ID), ("FAIL", HEALTH_ID)), 1)


def mod(name):
    return importlib.import_module(name)


class Digests:
    """`cluster.running_digest` and `registry.digest` replaced: what dev runs, and what the registry says per tag."""

    def __init__(self, mp, running=D1, registry=None):
        self.running = running
        self.registry = {TAG: D1} if registry is None else registry
        self.running_calls: list[tuple] = []
        self.registry_calls: list[tuple] = []
        self.unreadable = False
        mp.setattr(mod("cluster"), "running_digest", self._running)
        mp.setattr(mod("registry"), "digest", self._registry)

    def _running(self, context, namespace, service):
        self.running_calls.append((context, namespace, service))
        return self.running

    def _registry(self, image, tag):
        self.registry_calls.append((image, tag))
        if self.unreadable or tag not in self.registry:
            raise mod("registry").RegistryError(f"cannot read the digest of {image}:{tag}", "gh auth refresh -s read:packages")
        return self.registry[tag]


def staged(sw, monkeypatch, *, running=D1, registry=None, **kw):
    sw.stage(**kw)
    return Digests(monkeypatch, running, registry)


def all_text(sw, capsys):
    return "\n".join(lines_of(capsys))


# ---------------- AC-105.1: the digest of what dev runs ----------------

def test_the_smoke_record_holds_the_digest_dev_runs_ac_105_1(sw, capsys, monkeypatch):  # AC-105.1
    """AC-105.1: the smoke section of the record and of the state hold the digest read from the cluster."""
    dg = staged(sw, monkeypatch)
    sw.fake.script([PASS_ALL])
    assert sw.deploy() == 0
    assert sw.record()["smoke"]["digest"] == D1 and sw.state()["smoke"]["digest"] == D1
    context, _namespace, service = dg.running_calls[0]
    assert context == "lan" and service == "shop-api"


def test_an_unreadable_digest_is_not_run_not_passed_ac_105_1(sw, capsys, monkeypatch):  # AC-105.1
    """AC-105.1: no digest means smoke outcome not-run with the reason `image digest unknown`; nothing is promoted."""
    staged(sw, monkeypatch, running=None)
    sw.fake.script([PASS_ALL])
    assert sw.deploy() == 0
    sec = sw.record()["smoke"]
    assert sec["outcome"] == "not-run" and sec["reason"] == "image digest unknown"
    assert "smoke not run: image digest unknown" in lines_of(capsys)
    assert sw.dispatches() == []


def fake_kubectl(tmp_path, monkeypatch, pods):
    d = tmp_path / "fake-kubectl"
    d.mkdir()
    (d / "pods.json").write_text(json.dumps({"items": pods}))
    exe = d / "kubectl"
    exe.write_text(f"#!/bin/bash\necho \"$*\" >> '{d}/calls'\ncat '{d}/pods.json'\n")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{d}{os.pathsep}{os.environ['PATH']}")
    return d


def pod(digest, ready=True, name="shop-api"):
    return {"status": {"conditions": [{"type": "Ready", "status": "True" if ready else "False"}],
                       "containerStatuses": [{"name": name, "ready": ready, "imageID": f"{IMAGE}@{digest}"}]}}


@pytest.mark.parametrize("pods, want", [
    ([pod(D1)], D1),
    ([pod(D1), pod(D1)], D1),
    ([pod(D1), pod(D2, ready=False)], D1),
    ([pod(D1), pod(D2)], None),
    ([], None),
    ([pod(D1, ready=False)], None),
])
def test_running_digest_reads_the_image_id_of_ready_pods_ac_105_1(tmp_path, monkeypatch, pods, want):  # AC-105.1
    """AC-105.1: `cluster.running_digest` takes the imageID digest of the Ready pods; several digests or none give None."""
    d = fake_kubectl(tmp_path, monkeypatch, pods)
    assert mod("cluster").running_digest("lan", "shop-dev", "shop-api") == want
    call = (d / "calls").read_text()
    assert "--context lan" in call and "-n shop-dev" in call and "app.kubernetes.io/name=shop-api" in call


def test_registry_digest_reads_the_version_that_holds_the_tag_ac_105_1(monkeypatch):  # AC-105.1
    """AC-105.1: `registry.digest` finds the package version whose tags hold the tag (through the `registry.gh` seam)."""
    registry = mod("registry")
    versions = [{"name": D2, "metadata": {"container": {"tags": ["sha-other"]}}},
                {"name": D1, "metadata": {"container": {"tags": [TAG, "latest"]}}}]
    monkeypatch.setattr(registry, "gh", lambda args, **kw: json.dumps(versions))
    assert registry.digest(IMAGE, TAG) == D1
    with pytest.raises(registry.RegistryError):
        registry.digest(IMAGE, "sha-missing")


def test_registry_digest_failure_is_a_registry_error_ac_105_1(monkeypatch):  # AC-105.1
    """AC-105.1: a failing gh call raises RegistryError, never a bare exception."""
    import core
    registry = mod("registry")

    def boom(args, **kw):
        raise core.PlatformError("HTTP 403")
    monkeypatch.setattr(registry, "gh", boom)
    with pytest.raises(registry.RegistryError):
        registry.digest(IMAGE, TAG)


# ---------------- AC-105.2: the digest must still match before staging is pinned ----------------

def test_a_matching_digest_lets_the_pin_go_ahead_ac_105_2(sw, capsys, monkeypatch):  # AC-105.2
    """AC-105.2: the registry digest of the tag equals the smoked digest: the pin is dispatched."""
    dg = staged(sw, monkeypatch)
    sw.fake.script([PASS_ALL])
    assert sw.deploy() == 0
    assert len(sw.dispatches()) == 1 and (IMAGE, TAG) in dg.registry_calls


def test_a_changed_digest_pins_nothing_and_says_so_ac_105_2(sw, capsys, monkeypatch):  # AC-105.2
    """AC-105.2: a tag re-pushed after the smoke pins nothing; the report names both digests; escalation cause decision."""
    staged(sw, monkeypatch, registry={TAG: D2})
    sw.fake.script([PASS_ALL])
    assert sw.deploy() == 1
    text = all_text(sw, capsys) + "\n" + (sw.state().get("escalated") or "")
    assert f"digest changed since smoke: {D1} -> {D2}" in text
    assert sw.dispatches() == [] and sw.state()["cause"] == "decision"


# ---------------- AC-105.3: the prod evidence names the checked digest ----------------

def test_the_evidence_shows_the_checked_digest_ac_105_3(ev, monkeypatch):  # AC-105.3
    """AC-105.3: the dev smoke line carries the digest that was checked; no flag when staging runs the same digest."""
    ev.records["runs/2026/10/24/r1.json"] = {**dev_rec("r1", f"sha-{E}", staging=stg("passed", f"sha-{E}"))}
    ev.records["runs/2026/10/24/r1.json"]["smoke"]["digest"] = D1
    Digests(monkeypatch, registry={f"sha-{E}": D1})
    text = "\n".join(summary().lines())
    assert D1 in text and "digest differs from what staging runs" not in text


def test_the_evidence_flags_a_staging_digest_that_differs_ac_105_3(ev, monkeypatch):  # AC-105.3
    """AC-105.3: staging runs another digest than the checked one: flagged."""
    ev.records["runs/2026/10/24/r1.json"] = dev_rec("r1", f"sha-{E}", staging=stg("passed", f"sha-{E}"))
    ev.records["runs/2026/10/24/r1.json"]["smoke"]["digest"] = D1
    Digests(monkeypatch, registry={f"sha-{E}": D2})
    text = "\n".join(summary().lines())
    assert D1 in text and "digest differs from what staging runs" in text


def test_an_unreadable_staging_digest_never_breaks_the_summary_ac_105_3(ev, monkeypatch):  # AC-105.3
    """AC-105.3: the summary never blocks (093): an unreadable staging digest leaves the digest line and no flag."""
    ev.records["runs/2026/10/24/r1.json"] = dev_rec("r1", f"sha-{E}", staging=stg("passed", f"sha-{E}"))
    ev.records["runs/2026/10/24/r1.json"]["smoke"]["digest"] = D1
    Digests(monkeypatch).unreadable = True
    text = "\n".join(summary().lines())
    assert D1 in text and "digest differs from what staging runs" not in text


# ---------------- AC-105.4: environment or application ----------------

def attempt(*kinds):
    smoke = mod("smoke")
    tests = [(k, f"t{i}") for i, k in enumerate(kinds)]
    return smoke.Attempt(1, tests, kinds.count("PASS"), kinds.count("FAIL"), 0, "", 0.0)


def probe(monkeypatch, answer):
    monkeypatch.setattr(mod("smoke"), "status", lambda url, *a, **k: answer)


@pytest.mark.parametrize("answer", ["Connection refused", "[Errno -2] Name or service not known", "timed out", 502, 503, 504])
def test_an_unreachable_base_url_with_every_test_failing_is_environment_ac_105_4(monkeypatch, answer):  # AC-105.4
    """AC-105.4: refused / DNS / timeout / 502 / 503 / 504 and every test failing: environment."""
    probe(monkeypatch, answer)
    assert mod("smoke").classify(BASE, attempt("FAIL", "FAIL")) == "environment"


@pytest.mark.parametrize("answer", [200, 401, 404, 500])
def test_a_reachable_base_url_is_application_ac_105_4(monkeypatch, answer):  # AC-105.4
    """AC-105.4: the URL answers (any other status): application."""
    probe(monkeypatch, answer)
    assert mod("smoke").classify(BASE, attempt("FAIL", "FAIL")) == "application"


@pytest.mark.parametrize("answer", ["Connection refused", 503])
def test_one_passing_test_means_application_ac_105_4(monkeypatch, answer):  # AC-105.4
    """AC-105.4: the gateway symptom must hit every test; a test that passed makes it an application failure."""
    probe(monkeypatch, answer)
    assert mod("smoke").classify(BASE, attempt("PASS", "FAIL")) == "application"


def test_the_result_carries_the_class_and_the_attempts_ac_105_4(svc, fake, seams, monkeypatch):  # AC-105.4
    """AC-105.4: SmokeResult.failure_class / attempts and the record section class / attempts."""
    seams()
    probe(monkeypatch, "Connection refused")
    fake.script([FAIL_ALL])
    res = mod("smoke").run_smoke(svc, BASE, spec=sp(svc))
    assert res.failure_class == "environment" and res.attempts == 3
    sec = res.section()
    assert sec["class"] == "environment" and sec["attempts"] == 3


def test_a_passing_run_has_no_class_ac_105_4(svc, fake, seams, monkeypatch):  # AC-105.4
    """AC-105.4: no failure, no class; one attempt."""
    seams()
    probe(monkeypatch, 200)
    fake.script([PASS_ALL])
    res = mod("smoke").run_smoke(svc, BASE, spec=sp(svc))
    assert res.failure_class is None and res.attempts == 1 and res.section()["class"] is None


def test_the_class_is_in_the_deploy_output_the_record_and_the_issue_ac_105_4(sw, capsys, monkeypatch):  # AC-105.4
    """AC-105.4: an application failure names its class in the output, the record and the filed issue."""
    staged(sw, monkeypatch)
    probe(monkeypatch, 200)
    sw.fake.script([FAIL_ONE])
    assert sw.deploy() == 1
    assert re.search(r"\bapplication\b", all_text(sw, capsys))
    assert sw.record()["smoke"]["class"] == "application"
    ((_, repo_slug, _title, body, _labels),) = sw.tr.created()
    assert repo_slug == SLUG and re.search(r"\bapplication\b", body)


def test_an_environment_failure_is_named_in_the_output_and_the_record_ac_105_4(sw, capsys, monkeypatch):  # AC-105.4
    """AC-105.4: an environment failure names its class in the output and the record."""
    staged(sw, monkeypatch)
    probe(monkeypatch, 503)
    sw.fake.script([FAIL_ALL])
    assert sw.deploy() == 1
    assert re.search(r"\benvironment\b", all_text(sw, capsys)) and sw.record()["smoke"]["class"] == "environment"


# ---------------- AC-105.5: retries per class ----------------

def test_an_environment_failure_is_tried_three_times_30_seconds_apart_ac_105_5(svc, fake, seams, monkeypatch):  # AC-105.5
    """AC-105.5: three attempts in total for an environment failure, 30 s apart."""
    s = seams()
    probe(monkeypatch, "Connection refused")
    fake.script([FAIL_ALL])
    res = mod("smoke").run_smoke(svc, BASE, spec=sp(svc))
    assert res.outcome == "red" and res.attempts == 3 and len(fake.calls) == 3 and s.sleeps == [30, 30]


def test_an_environment_failure_that_clears_passes_on_retry_ac_105_5(svc, fake, seams, monkeypatch):  # AC-105.5
    """AC-105.5: the third attempt passes: passed on retry after two waits."""
    s = seams()
    probe(monkeypatch, 502)
    fake.script([FAIL_ALL, FAIL_ALL, PASS_ALL])
    res = mod("smoke").run_smoke(svc, BASE, spec=sp(svc))
    assert res.outcome == "passed-on-retry" and res.attempts == 3 and s.sleeps == [30, 30]


def test_environment_retries_stay_inside_the_limit_ac_105_5(svc, fake, seams, monkeypatch):  # AC-105.5
    """AC-105.5: no attempt starts past the limit (AC-091.8): with 50 s left only two attempts fit."""
    s = seams()
    clock = [0.0]
    smoke = mod("smoke")
    monkeypatch.setattr(smoke, "sleep", lambda sec: (s.sleeps.append(sec), clock.__setitem__(0, clock[0] + sec)))
    monkeypatch.setattr(smoke, "monotonic", lambda: clock[0])
    probe(monkeypatch, "Connection refused")
    fake.script([FAIL_ALL])
    res = smoke.run_smoke(svc, BASE, spec=sp(svc), timeout=50)
    assert res.attempts == 2 and len(fake.calls) == 2 and sum(s.sleeps) <= 50


def test_an_application_failure_keeps_the_single_retry_ac_105_5(svc, fake, seams, monkeypatch):  # AC-105.5
    """AC-105.5: an application failure is retried once after 30 s, as in AC-091.7."""
    s = seams()
    probe(monkeypatch, 200)
    fake.script([FAIL_ONE])
    res = mod("smoke").run_smoke(svc, BASE, spec=sp(svc))
    assert res.outcome == "red" and res.attempts == 2 and len(fake.calls) == 2 and s.sleeps == [30]
    assert res.failure_class == "application"


def test_a_persistent_environment_failure_escalates_without_an_issue_ac_105_5(sw, capsys, monkeypatch):  # AC-105.5
    """AC-105.5: cause environment, `smoke red in dev: environment (<url>)`, no issue, no staging promotion."""
    staged(sw, monkeypatch)
    probe(monkeypatch, "Connection refused")
    sw.fake.script([FAIL_ALL])
    assert sw.deploy() == 1
    st = sw.state()
    assert st["escalated"] == f"smoke red in dev: environment ({sw_url(sw)})" and st["cause"] == "environment"
    assert len(sw.fake.calls) == 3 and sw.sleeps == [30, 30]
    assert sw.tr.created() == [] and sw.tr.calls == []
    assert sw.dispatches() == []
    rec = sw.record()["smoke"]
    assert rec["class"] == "environment" and rec["attempts"] == 3 and rec["outcome"] == "red"


def sw_url(sw):
    return "http://shop-api.shop-dev.localhost:8088"


def test_an_application_failure_still_escalates_with_cause_code_ac_105_5(sw, capsys, monkeypatch):  # AC-105.5
    """AC-105.5: application: one retry, cause code, the issue is filed (unchanged from 091)."""
    staged(sw, monkeypatch)
    probe(monkeypatch, 200)
    sw.fake.script([FAIL_ONE])
    assert sw.deploy() == 1
    st = sw.state()
    assert st["escalated"] == f"smoke red in dev: 1 failing ({SPEC_ID})" and st["cause"] == "code"
    assert len(sw.fake.calls) == 2 and sw.sleeps == [30] and len(sw.tr.created()) == 1


# ---------------- AC-105.6: not-run is NOT VERIFIED and never promotes ----------------

def test_a_not_run_smoke_reports_not_verified_and_promotes_nothing_ac_105_6(sw, capsys, monkeypatch):  # AC-105.6
    """AC-105.6: no kube context: smoke not run, NOT VERIFIED, the (smoke) criteria unchecked, no staging pin."""
    staged(sw, monkeypatch)
    sw.fake.script([PASS_ALL])
    assert sw.deploy(context=None) == 0
    out = lines_of(capsys)
    assert any("NOT VERIFIED" in ln for ln in out)
    assert "unchecked (smoke) criteria: AC-007.1" in out
    assert sw.dispatches() == [] and sw.state()["phase"] == "done"


def test_an_unknown_digest_is_not_verified_and_promotes_nothing_ac_105_6(sw, capsys, monkeypatch):  # AC-105.6
    """AC-105.6: the same rule when the digest cannot be read."""
    staged(sw, monkeypatch, running=None)
    sw.fake.script([PASS_ALL])
    assert sw.deploy() == 0
    out = lines_of(capsys)
    assert any("NOT VERIFIED" in ln for ln in out) and "unchecked (smoke) criteria: AC-007.1" in out
    assert sw.dispatches() == []
    assert sw.record()["promotion"]["staging"]["result"] == "skipped"


def test_a_passed_smoke_is_not_reported_as_not_verified_ac_105_6(sw, capsys, monkeypatch):  # AC-105.6
    """AC-105.6: a verified deploy does not say NOT VERIFIED."""
    staged(sw, monkeypatch)
    sw.fake.script([PASS_ALL])
    assert sw.deploy() == 0
    assert not any("NOT VERIFIED" in ln for ln in lines_of(capsys))


# ---------------- AC-105.7: a replay re-smokes unless it passed for the same digest ----------------

def first_run_that_fails_at_the_pin(sw, monkeypatch, **kw):
    dg = staged(sw, monkeypatch, tweak=lambda a: setattr(a, "dispatch_error", "HTTP 403: Resource not accessible"), **kw)
    sw.fake.script([PASS_ALL])
    assert sw.deploy() == 1
    assert len(sw.fake.calls) == 1 and sw.state()["smoke"]["outcome"] == "passed"
    sw.api.dispatch_error = None
    return dg


def test_a_replay_with_the_same_digest_does_not_smoke_dev_again_ac_105_7(sw, capsys, monkeypatch):  # AC-105.7
    """AC-105.7: passed for D1 and dev still runs D1: only the staging smoke runs after the replay."""
    first_run_that_fails_at_the_pin(sw, monkeypatch)
    assert sw.deploy() == 0
    urls = [c[1] for c in sw.fake.calls]
    assert urls == ["http://shop-api.shop-dev.localhost:8088", STAGING_URL]
    assert len(sw.dispatches()) == 1


def test_a_replay_with_another_digest_smokes_dev_again_ac_105_7(sw, capsys, monkeypatch):  # AC-105.7
    """AC-105.7: dev runs D2 now: a pass for D1 does not count, dev is smoked again and D2 is recorded."""
    dg = first_run_that_fails_at_the_pin(sw, monkeypatch)
    dg.running, dg.registry[TAG] = D2, D2
    assert sw.deploy() == 0
    urls = [c[1] for c in sw.fake.calls]
    assert urls == ["http://shop-api.shop-dev.localhost:8088"] * 2 + [STAGING_URL]
    assert sw.record()["smoke"]["digest"] == D2


def test_a_replay_without_a_recorded_digest_smokes_dev_again_ac_105_7(sw, capsys, monkeypatch):  # AC-105.7
    """AC-105.7: a passed outcome with no digest (an older record) does not count."""
    first_run_that_fails_at_the_pin(sw, monkeypatch)
    st = sw.state()
    st["smoke"].pop("digest", None)
    ship.save_state(sw.repo, st)
    assert sw.deploy() == 0
    assert [c[1] for c in sw.fake.calls] == ["http://shop-api.shop-dev.localhost:8088"] * 2 + [STAGING_URL]
