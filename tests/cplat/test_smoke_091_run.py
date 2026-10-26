"""Spec 091 acceptance tests, `scripts/cplat/smoke.py`: run with retry and limit, outcomes, criteria, record section, dev URL,
issue draft and filing, `cplat smoke run`. Contract: design.md "Python API", "cplat smoke CLI", "Issue", "Run record section".

The smoke recipe is replaced by a fake `devbox` on PATH that prints scripted result lines, so `smoke.run_recipe` (process
group, limit, parser) is exercised for real. Clock and sleep go through the seams `smoke.sleep` / `smoke.monotonic`; GitHub
through `smoke.gh` and the autoissue fake tracker. `smoke` is imported inside the tests: it does not exist yet."""
import base64
import importlib
import json
import os
import stat
import subprocess
import time
from pathlib import Path

import pytest

import core
import spec as specmod
from test_autoissue import PLATFORM_REPO, SIG_LINE, Clock, FakeTracker, clk, tr, ai  # noqa: F401  (fixtures)
from test_spec import PLAN, SPEC as BASE_SPEC

SLUG = "acme/shop-api"
BASE = "http://shop-api.shop-dev.localhost:8088"
SECRET = "ghp_" + "a1b2c3d4e5" * 4
TEST_ID = "tests/test_alerts.py::test_ac_007_1_email_arrives"
HEALTH_ID = "tests/test_health.py::test_health"
GITOPS = "acme/shop-gitops"

SPEC_TEXT = BASE_SPEC.replace("then an email is sent.", "then an email is sent. (smoke)")
ALERTS_PY = "import pytest\n\n\n@pytest.mark.smoke\ndef test_ac_007_1_email_arrives(smoke_base_url):  # AC-007.1\n    ...\n"
HEALTH_PY = "import pytest\n\n\n@pytest.mark.smoke\ndef test_health(smoke_base_url):\n    ...\n"


def smoke_mod():
    return importlib.import_module("smoke")


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def make_service(root: Path, name="shop-api") -> Path:
    """A python service repo with a spec that has one (smoke) criterion, smoke tests and a smoke recipe."""
    r = root / name
    r.mkdir(parents=True)
    git(r, "init", "-q", "-b", "main")
    (r / ".copier-answers.yml").write_text("_src_path: gh:ika100/sdlc-foundry/templates/service-python\nproject_name: shop-api\n")
    d = r / "docs" / "specs" / "007-price-alerts"
    d.mkdir(parents=True)
    (d / "spec.md").write_text(SPEC_TEXT.format(status="approved", questions="None."))
    (d / "plan.md").write_text(PLAN.format(hash=specmod.read(d).ac_hash()))
    (r / "tests").mkdir()
    (r / "tests" / "test_alerts.py").write_text(ALERTS_PY)
    (r / "tests" / "test_health.py").write_text(HEALTH_PY)
    (r / "devbox.json").write_text(json.dumps({"shell": {"scripts": {"smoke": "bash scripts/smoke.sh", "test": "true"}}}))
    git(r, "add", "-A")
    git(r, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
    git(r, "remote", "add", "origin", f"https://github.com/{SLUG}.git")
    return r


def result_lines(*items, p=None, f=None, s=0):
    """Lines of the output contract. items are ("PASS"|"FAIL"|"SKIP", id)."""
    p = p if p is not None else sum(1 for k, _ in items if k == "PASS")
    f = f if f is not None else sum(1 for k, _ in items if k == "FAIL")
    s = sum(1 for k, _ in items if k == "SKIP") or s
    return [f"{k}  {i}" for k, i in items] + [f"smoke: {p} passed, {f} failed, {s} skipped"]


class FakeDevbox:
    """A `devbox` on PATH: attempt n prints its scripted output and exits with its code (the last attempt repeats)."""

    def __init__(self, tmp: Path, monkeypatch):
        self.dir = tmp / "fake-devbox"
        self.dir.mkdir()
        exe = self.dir / "devbox"
        exe.write_text(
            "#!/bin/bash\n"
            f"d='{self.dir}'\n"
            "n=$(( $(cat \"$d/n\" 2>/dev/null || echo 0) + 1 )); echo $n > \"$d/n\"\n"
            "echo \"$*|$SMOKE_BASE_URL|$PWD\" >> \"$d/calls\"\n"
            "f=\"$d/attempt$n\"; [ -f \"$f.rc\" ] || f=\"$d/attempt_last\"\n"
            "cat \"$f.out\"\n"
            "[ -f \"$f.sleep\" ] && sleep \"$(cat \"$f.sleep\")\"\n"
            "exit \"$(cat \"$f.rc\")\"\n")
        exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
        monkeypatch.setenv("PATH", f"{self.dir}{os.pathsep}{os.environ['PATH']}")
        self.n_attempts = 0
        self.script([(["smoke: 0 passed, 0 failed, 0 skipped"], 0)])

    def script(self, attempts):
        """attempts: [(lines, rc)] or [(lines, rc, sleep_seconds)]"""
        for f in self.dir.glob("attempt*"):
            f.unlink()
        for f in ("n", "calls"):
            (self.dir / f).unlink(missing_ok=True)
        for n, att in enumerate(attempts, 1):
            lines, rc, *rest = att
            for name in (f"attempt{n}", "attempt_last") if n == len(attempts) else (f"attempt{n}",):
                (self.dir / f"{name}.out").write_text("\n".join(lines) + "\n")
                (self.dir / f"{name}.rc").write_text(str(rc))
                if rest:
                    (self.dir / f"{name}.sleep").write_text(str(rest[0]))

    @property
    def calls(self):
        f = self.dir / "calls"
        return [ln.split("|") for ln in f.read_text().splitlines()] if f.is_file() else []


class Seams:
    def __init__(self, monkeypatch):
        self.sleeps: list[float] = []
        smoke = smoke_mod()
        monkeypatch.setattr(smoke, "sleep", self.sleeps.append)
        monkeypatch.setattr(smoke, "reachable", lambda url, timeout=10.0: None)
        monkeypatch.setattr(smoke, "status", lambda url, *a, **k: 200)   # spec 105: no real network probe in unit tests


@pytest.fixture()
def svc(tmp_path):
    return make_service(tmp_path)


@pytest.fixture()
def fake(tmp_path, monkeypatch):
    return FakeDevbox(tmp_path, monkeypatch)


@pytest.fixture()
def seams(monkeypatch):
    return lambda: Seams(monkeypatch)


def sp(repo):
    return specmod.find(repo, "7")


# ---------------- AC-091.6: what a passing run reports ----------------

def test_a_passing_run_lists_every_test_and_the_criteria_ac_091_6(svc, fake, seams):  # AC-091.6
    s = seams()
    fake.script([(result_lines(("PASS", TEST_ID), ("PASS", HEALTH_ID)), 0)])
    smoke = smoke_mod()
    res = smoke.run_smoke(svc, BASE, spec=sp(svc))
    assert res.outcome == "passed" and res.ok and (res.passed, res.failed, res.skipped) == (2, 0, 0)
    assert res.env == "dev" and res.base_url == BASE and not res.retried and s.sleeps == []
    assert res.tests == [{"id": TEST_ID, "result": "passed"}, {"id": HEALTH_ID, "result": "passed"}]
    assert res.criteria == {"AC-007.1": "passed"} and res.failing == [] and res.tail == ""
    ((args, url, cwd),) = fake.calls
    assert args == "run smoke" and url == BASE and Path(cwd).resolve() == svc.resolve()
    lines = res.lines()
    assert f"PASS  {TEST_ID}" in lines and f"PASS  {HEALTH_ID}" in lines and "smoke: 2 passed, 0 failed, 0 skipped" in lines
    assert "criterion AC-007.1 (smoke): passed" in lines
    assert res.row() == "2/2 passed"


def test_a_failing_test_of_the_criterion_file_fails_the_criterion_ac_091_6(svc, fake, seams):  # AC-091.6
    seams()
    fake.script([(result_lines(("FAIL", TEST_ID), ("PASS", HEALTH_ID)), 1)])
    res = smoke_mod().run_smoke(svc, BASE, spec=sp(svc))
    assert res.criteria == {"AC-007.1": "failed"}
    assert "criterion AC-007.1 (smoke): failed" in res.lines()


def test_a_criterion_without_a_passed_test_is_unchecked_ac_091_6(svc, fake, seams):  # AC-091.6
    seams()
    fake.script([(result_lines(("PASS", HEALTH_ID), ("SKIP", TEST_ID)), 0)])
    res = smoke_mod().run_smoke(svc, BASE, spec=sp(svc))
    assert res.ok and res.criteria == {"AC-007.1": "unchecked"} and res.skipped == 1


# ---------------- AC-091.7: one retry after 30 seconds ----------------

def test_a_first_failure_is_retried_once_after_30_seconds_ac_091_7(svc, fake, seams):  # AC-091.7
    s = seams()
    fake.script([(result_lines(("FAIL", TEST_ID), ("PASS", HEALTH_ID)), 1), (result_lines(("FAIL", TEST_ID), ("PASS", HEALTH_ID)), 1)])
    res = smoke_mod().run_smoke(svc, BASE, spec=sp(svc))
    assert s.sleeps == [30] and len(fake.calls) == 2
    assert res.outcome == "red" and not res.ok and res.retried and res.failing == [TEST_ID] and res.failed == 1


def test_a_pass_on_the_retry_is_passed_on_retry_and_flaky_ac_091_7(svc, fake, seams):  # AC-091.7
    s = seams()
    fake.script([(result_lines(("FAIL", TEST_ID), ("PASS", HEALTH_ID)), 1), (result_lines(("PASS", TEST_ID), ("PASS", HEALTH_ID)), 0)])
    res = smoke_mod().run_smoke(svc, BASE, spec=sp(svc))
    assert s.sleeps == [30] and res.outcome == "passed-on-retry" and res.ok and res.retried
    assert res.flaky == [TEST_ID] and res.failing == [] and res.row() == "passed on retry"
    assert res.section()["outcome"] == "passed-on-retry" and res.section()["flaky"] == [TEST_ID]


def test_a_recipe_that_fails_without_result_lines_is_retried_too_ac_091_7(svc, fake, seams):  # AC-091.7
    s = seams()
    fake.script([(["error: browser missing"], 1)])
    res = smoke_mod().run_smoke(svc, BASE, spec=sp(svc))
    assert s.sleeps == [30] and res.outcome == "red" and not res.ok and "browser missing" in res.tail


def test_no_retry_option_runs_once_ac_091_7(svc, fake, seams):  # AC-091.7
    s = seams()
    fake.script([(result_lines(("FAIL", TEST_ID)), 1)])
    res = smoke_mod().run_smoke(svc, BASE, spec=sp(svc), retry=False)
    assert s.sleeps == [] and len(fake.calls) == 1 and res.outcome == "red" and not res.retried


# ---------------- AC-091.8: ten minutes at most ----------------

def test_a_run_that_does_not_finish_is_stopped_and_red_ac_091_8(svc, fake, seams):  # AC-091.8
    s = seams()
    fake.script([(["PASS  slow"], 0, 120)])
    t0 = time.monotonic()
    res = smoke_mod().run_smoke(svc, BASE, spec=sp(svc), timeout=5)
    assert time.monotonic() - t0 < 60                                  # killed, not waited for (120 s); slack for a loaded CI
    assert res.outcome == "timed-out" and not res.ok and res.failing == ["(timed out)"]
    assert "timed out after" in (res.reason or "")
    assert s.sleeps == [] and len(fake.calls) == 1                     # a timed-out attempt is not retried
    assert res.criteria == {"AC-007.1": "unchecked"}


def test_the_limit_defaults_are_ten_minutes_thirty_seconds_sixty_lines_ac_091_8():  # AC-091.8
    smoke = smoke_mod()
    assert (smoke.LIMIT_S, smoke.RETRY_DELAY_S, smoke.TAIL_LINES) == (600, 30, 60)
    assert smoke.OUTCOMES == ("passed", "passed-on-retry", "red", "timed-out", "not-run")


# ---------------- AC-091.9: the evidence of a red run ----------------

def test_the_tail_has_sixty_lines_and_no_secrets_ac_091_9(svc, fake, seams):  # AC-091.9
    seams()
    noise = [f"line {i}" for i in range(1, 101)]
    noise[95] = f"Authorization: token {SECRET}"
    fake.script([(noise + result_lines(("FAIL", TEST_ID)), 1)])
    res = smoke_mod().run_smoke(svc, BASE, spec=sp(svc))
    tail = res.tail.splitlines()
    assert len(tail) == 60 and tail[-1].startswith("smoke: ") and "line 1" not in tail and "line 2" not in tail
    assert SECRET not in res.tail
    assert SECRET not in "\n".join(res.lines())


# ---------------- AC-091.11: not run ----------------

def test_not_run_never_counts_as_passed_ac_091_11(svc):  # AC-091.11
    smoke = smoke_mod()
    res = smoke.not_run("dev", "no kube context, so Argo health was not checked (pass --context <kube-context>)", ["AC-007.1"])
    assert res.outcome == "not-run" and not res.ok and (res.passed, res.failed, res.skipped) == (0, 0, 0)
    assert res.criteria == {"AC-007.1": "unchecked"} and res.base_url is None
    assert res.row() == "not run: no kube context, so Argo health was not checked (pass --context <kube-context>)"


def test_a_repo_without_a_smoke_recipe_is_not_run_ac_091_11(svc, fake, seams):  # AC-091.11
    seams()
    (svc / "devbox.json").write_text(json.dumps({"shell": {"scripts": {"test": "true"}}}))
    smoke = smoke_mod()
    assert smoke.has_recipe(svc) is False
    res = smoke.run_smoke(svc, BASE, spec=sp(svc))
    assert res.outcome == "not-run" and "no smoke recipe" in res.reason and fake.calls == []
    assert res.criteria == {"AC-007.1": "unchecked"}


def test_has_recipe_reads_devbox_json_ac_091_11(svc):  # AC-091.11
    assert smoke_mod().has_recipe(svc) is True


def test_an_unreachable_dev_url_is_not_run_not_red_ac_091_11(svc, fake, monkeypatch):  # AC-091.11
    smoke = smoke_mod()
    seen = []
    monkeypatch.setattr(smoke, "sleep", lambda s: None)
    monkeypatch.setattr(smoke, "reachable", lambda url, timeout=10.0: seen.append(url) or "connection refused")
    res = smoke.run_smoke(svc, BASE, spec=sp(svc), probe="/health")
    assert seen == [BASE + "/health"] and fake.calls == []
    assert res.outcome == "not-run" and res.reason == f"dev URL {BASE} is not reachable: connection refused"


# ---------------- AC-091.11: the dev URL from the linked gitops-app ----------------

class GitopsApi:
    """`gh api` of the gitops-app repo: the application dirs, services.yaml and app.yaml of each."""

    def __init__(self, services: str, app: str, name="shop"):
        self.files = {f"applications/{name}/services.yaml": services, f"applications/{name}/app.yaml": app}
        self.name = name
        self.calls: list[list[str]] = []

    def __call__(self, args, *, cwd=None, check=True):
        self.calls.append(args)
        joined = " ".join(args)
        assert args[0] == "api", args
        if "services.yaml" not in joined and "app.yaml" not in joined:        # the listing of the application directories
            if "--jq" in args:
                return self.name + "\n"
            return json.dumps([{"name": self.name, "type": "dir"}])
        for path, text in self.files.items():
            if path in joined:
                if "raw" in joined.lower():
                    return text
                if "--jq" in args:
                    return base64.b64encode(text.encode()).decode()
                return json.dumps({"content": base64.b64encode(text.encode()).decode(), "encoding": "base64"})
        raise AssertionError(f"unexpected gh call {args}")


EXPOSED = "services:\n  - name: shop-api\n    repo: acme/shop-api\n    shape: service-python\n    port: 8080\n    expose: {host: shop-api}\n    environments: [dev]\n"
HIDDEN = "services:\n  - name: shop-api\n    repo: acme/shop-api\n    shape: service-python\n    port: 8080\n    environments: [dev]\n"
OTHER = "services:\n  - name: other\n    repo: acme/other\n    shape: service-python\n    port: 8080\n    expose: {host: other}\n"
APP = 'gateway: {name: traefik-gateway, namespace: kube-system}\nhosts:\n  dev: "{service}.{app}-dev.localhost"\n'


def link(repo):
    (repo / ".platform-app.yml").write_text(f"gitops_apps:\n  - {GITOPS}\n")


def test_dev_url_is_computed_from_the_gitops_app_ac_091_11(svc, monkeypatch):  # AC-091.11
    smoke = smoke_mod()
    api = GitopsApi(EXPOSED, APP)
    monkeypatch.setattr(smoke, "gh", api)
    monkeypatch.delenv("LOCAL_HTTP_PORT", raising=False)
    assert smoke.dev_url(svc, [GITOPS], "shop-api") == ("http://shop-api.shop-dev.localhost:8088", None)
    monkeypatch.setenv("LOCAL_HTTP_PORT", "9090")
    assert smoke.dev_url(svc, [GITOPS], "shop-api") == ("http://shop-api.shop-dev.localhost:9090", None)
    monkeypatch.setenv("LOCAL_HTTP_PORT", "not-a-number")
    assert smoke.dev_url(svc, [GITOPS], "shop-api")[0] == "http://shop-api.shop-dev.localhost:8088"


def test_dev_url_uses_https_for_real_hosts_and_urls_dev_wins_ac_091_11(svc, monkeypatch):  # AC-091.11
    smoke = smoke_mod()
    monkeypatch.setattr(smoke, "gh", GitopsApi(EXPOSED, 'hosts:\n  dev: "{service}.dev.example.com"\n'))
    assert smoke.dev_url(svc, [GITOPS], "shop-api") == ("https://shop-api.dev.example.com", None)
    monkeypatch.setattr(smoke, "gh", GitopsApi(EXPOSED, 'hosts:\n  dev: "{service}.dev.example.com"\nurls:\n  dev: "https://{host}/shop"\n'))
    assert smoke.dev_url(svc, [GITOPS], "shop-api") == ("https://shop-api.dev.example.com/shop", None)


@pytest.mark.parametrize("services, app, reason", [
    (HIDDEN, APP, "shop-api has no dev URL (not exposed in dev)"),
    (EXPOSED, "gateway: {name: g, namespace: kube-system}\n", "shop-api has no dev URL (not exposed in dev)"),
    (EXPOSED.replace("[dev]", "[staging]"), APP, "shop-api has no dev URL (not exposed in dev)"),
    (OTHER, APP, "shop-api has no dev URL (not in the linked gitops-app)"),
])
def test_dev_url_says_why_there_is_none_ac_091_11(svc, monkeypatch, services, app, reason):  # AC-091.11
    smoke = smoke_mod()
    monkeypatch.setattr(smoke, "gh", GitopsApi(services, app))
    assert smoke.dev_url(svc, [GITOPS], "shop-api") == (None, reason)


# ---------------- AC-091.15: the record section ----------------

def test_the_section_of_a_red_run_carries_the_contract_fields_ac_091_15(svc, fake, seams):  # AC-091.15
    seams()
    fake.script([(result_lines(("FAIL", TEST_ID), ("PASS", HEALTH_ID)), 1)])
    res = smoke_mod().run_smoke(svc, BASE, spec=sp(svc))
    filed = {"signature": "smoke:0123456789abcdef", "url": f"https://github.com/{SLUG}/issues/7", "result": "new"}
    sec = res.section(filed)
    assert sec["env"] == "dev" and sec["outcome"] == "red" and sec["base_url"] == BASE
    assert (sec["passed"], sec["failed"], sec["skipped"], sec["total"]) == (1, 1, 0, 2)
    assert sec["retried"] is True and sec["flaky"] == [] and sec["reason"] is None
    assert sec["criteria"] == {"AC-007.1": "failed"} and sec["failing"] == [TEST_ID] and sec["filed"] == filed
    assert isinstance(sec["duration_s"], (int, float))
    assert res.section()["filed"] is None
    assert res.row(f"https://github.com/{SLUG}/issues/7") == f"red (1 failing, issue https://github.com/{SLUG}/issues/7)"
    assert json.loads(json.dumps(sec)) == sec


def test_the_section_of_a_not_run_is_empty_and_unchecked_ac_091_15(svc):  # AC-091.15
    res = smoke_mod().not_run("dev", "the repo is not linked to a gitops-app", ["AC-007.1", "AC-007.2"])
    sec = res.section()
    assert sec["outcome"] == "not-run" and sec["reason"] == "the repo is not linked to a gitops-app"
    assert (sec["passed"], sec["failed"], sec["skipped"], sec["total"]) == (0, 0, 0, 0)
    assert sec["criteria"] == {"AC-007.1": "unchecked", "AC-007.2": "unchecked"} and sec["filed"] is None


def test_a_timed_out_row_and_section_ac_091_15(svc, fake, seams):  # AC-091.15
    seams()
    fake.script([(["x"], 0, 30)])
    res = smoke_mod().run_smoke(svc, BASE, spec=sp(svc), timeout=1)
    assert res.section()["outcome"] == "timed-out" and res.row(None).startswith("red (1 failing")


# ---------------- AC-091.14: the issue ----------------

def red(svc, fake, seams, ids=(TEST_ID,), output=None):
    seams()
    fake.script([((output or []) + result_lines(*[("FAIL", i) for i in ids]), 1)])
    return smoke_mod().run_smoke(svc, BASE, spec=sp(svc))


KW = dict(service_slug=SLUG, spec_id="007-price-alerts", image="sha-" + "ab" * 20, run_id="20261024T080000Z-aaaa1111", shape="service-python")


def test_the_draft_follows_the_convention_ac_091_14(svc, fake, seams, ai):  # AC-091.14
    smoke = smoke_mod()
    res = red(svc, fake, seams, ids=("tests/test_b.py::test_two", TEST_ID), output=["boom at line 4", f"TOKEN={SECRET}"])
    draft = smoke.issue_draft(res, **KW)
    assert (draft.kind, draft.repo, draft.command, draft.phase, draft.shape) == ("smoke", SLUG, "cplat ship deploy", "deploy", "service-python")
    assert draft.signature == ai.signature("smoke", SLUG, "dev", "\n".join(sorted(["tests/test_b.py::test_two", TEST_ID])))
    assert draft.run_id == KW["run_id"] and draft.names == {}
    assert draft.label_list() == ["triage", "auto-filed", "smoke-failure"]
    title, body = ai.render(draft)
    assert title.startswith("[auto] Smoke red in dev: ") and len(title) <= 100
    assert len(SIG_LINE.findall(body)) == 1 and body.splitlines()[-1] == f"Signature: {draft.signature}"
    assert draft.signature.startswith("smoke:")
    for needle in ("007-price-alerts", "sha-" + "ab" * 20, TEST_ID, "tests/test_b.py::test_two", KW["run_id"], "boom at line 4"):
        assert needle in body, needle
    assert SECRET not in body and SECRET not in "\n".join(draft.sections and [t for _, t in draft.sections])


def test_the_signature_depends_on_the_failing_ids_only_ac_091_14(svc, fake, seams, ai):  # AC-091.14
    smoke = smoke_mod()
    a = smoke.issue_draft(red(svc, fake, seams, ids=("tests/test_b.py::test_two", TEST_ID), output=["first run"]), **KW)
    b = smoke.issue_draft(red(svc, fake, seams, ids=(TEST_ID, "tests/test_b.py::test_two"), output=["other output 2026-10-25"]),
                          **{**KW, "run_id": "20261025T090000Z-bbbb2222", "image": "sha-" + "cd" * 20})
    c = smoke.issue_draft(red(svc, fake, seams, ids=(TEST_ID,)), **KW)
    assert a.signature == b.signature != c.signature


def test_a_red_run_is_filed_in_the_service_repo_and_repeats_are_counted_ac_091_14(svc, fake, seams, tr, ai):  # AC-091.14
    smoke = smoke_mod()
    draft_kw = KW
    out = smoke.file_issue(red(svc, fake, seams), **draft_kw)
    assert out.result == "new" and out.url == f"https://github.com/{SLUG}/issues/1"
    ((_, repo, title, body, labels),) = tr.created()
    assert repo == SLUG and title == f"[auto] Smoke red in dev: {TEST_ID}" and set(labels) == {"triage", "auto-filed", "smoke-failure"}
    out2 = smoke.file_issue(red(svc, fake, seams), **draft_kw)
    assert out2.result == "+1" and len(tr.created()) == 1 and len(tr.commented()) == 1
    assert "Occurrence 2" in tr.commented()[0][3]


def test_a_repeat_after_the_issue_was_closed_opens_a_new_one_unless_wontfix_ac_091_14(svc, fake, seams, tr, ai):  # AC-091.14
    smoke = smoke_mod()
    assert smoke.file_issue(red(svc, fake, seams), **KW).result == "new"
    tr.issues[SLUG][0].state, tr.issues[SLUG][0].closed_at = "closed", "2026-10-23T00:00:00Z"
    out = smoke.file_issue(red(svc, fake, seams), **KW)
    assert out.result == "new" and len(tr.created()) == 2 and "#1" in tr.created()[1][3]
    for i in tr.issues[SLUG]:
        i.state, i.closed_at = "closed", "2026-10-24T00:00:00Z"
        i.labels = [*i.labels, "wontfix"]
    assert smoke.file_issue(red(svc, fake, seams), **KW).result == "suppressed" and len(tr.created()) == 2


def test_the_cap_of_ten_new_issues_applies_ac_091_14(svc, fake, seams, tr, ai):  # AC-091.14
    smoke = smoke_mod()
    results = [smoke.file_issue(red(svc, fake, seams, ids=(f"tests/test_{c}.py::test_x",)), **KW).result for c in "abcdefghijkl"]
    assert results[:10] == ["new"] * 10 and results[10:] == ["pending", "pending"] and len(tr.created()) == 10


def test_a_filing_that_fails_says_not_filed_and_never_raises_ac_091_14(svc, fake, seams, tr, ai):  # AC-091.14
    smoke = smoke_mod()
    tr.error = ai.TrackerError("no permission to create issues")
    out = smoke.file_issue(red(svc, fake, seams), **KW)
    assert out.result == "pending" and any(ln.startswith("issue: not filed: no permission") for ln in out.lines)


def test_file_issue_survives_a_crash_in_filing_ac_091_14(svc, fake, seams, ai, monkeypatch):  # AC-091.14
    smoke = smoke_mod()

    def boom(*a, **k):
        raise RuntimeError("disk full")
    monkeypatch.setattr(ai, "file", boom)
    out = smoke.file_issue(red(svc, fake, seams), **KW)
    assert "issue: not filed: RuntimeError: disk full" in out.lines


# ---------------- `cplat smoke run` ----------------

def run_cli(svc, monkeypatch, *argv):
    monkeypatch.chdir(svc)
    return smoke_mod().main(["run", *argv])


def test_cli_exit_codes_and_lines_ac_091_6(svc, fake, seams, monkeypatch, capsys, tr):  # AC-091.6
    seams()
    fake.script([(result_lines(("PASS", TEST_ID)), 0)])
    assert run_cli(svc, monkeypatch, "--base-url", BASE, "--spec", "7") == 0
    out = capsys.readouterr().out.splitlines()
    assert f"PASS  {TEST_ID}" in out and "criterion AC-007.1 (smoke): passed" in out
    fake.script([(result_lines(("FAIL", TEST_ID)), 1)])
    assert run_cli(svc, monkeypatch, "--base-url", BASE, "--spec", "7", "--no-retry") == 1
    assert tr.calls == []                                               # the CLI files no issue
    (svc / "devbox.json").write_text("{}")
    assert run_cli(svc, monkeypatch, "--base-url", BASE) == 3


def test_cli_json_output_ac_091_15(svc, fake, seams, monkeypatch, capsys):  # AC-091.15
    seams()
    fake.script([(result_lines(("PASS", TEST_ID)), 0)])
    assert run_cli(svc, monkeypatch, "--base-url", BASE, "--spec", "7", "--json") == 0
    data = json.loads(capsys.readouterr().out)
    assert data["smoke"]["outcome"] == "passed" and data["tests"] == [{"id": TEST_ID, "result": "passed"}]


def test_cli_resolves_the_dev_url_without_base_url_ac_091_6(svc, fake, seams, monkeypatch, capsys):  # AC-091.6
    smoke = smoke_mod()
    seams()
    link(svc)
    monkeypatch.setattr(smoke, "gh", GitopsApi(EXPOSED, APP))
    monkeypatch.delenv("LOCAL_HTTP_PORT", raising=False)
    fake.script([(result_lines(("PASS", TEST_ID)), 0)])
    assert run_cli(svc, monkeypatch) == 0
    assert fake.calls[0][1] == BASE


def test_cli_not_exposed_is_not_run_ac_091_11(svc, fake, seams, monkeypatch, capsys):  # AC-091.11
    smoke = smoke_mod()
    seams()
    link(svc)
    monkeypatch.setattr(smoke, "gh", GitopsApi(HIDDEN, APP))
    assert run_cli(svc, monkeypatch, "--spec", "7") == 3
    out = capsys.readouterr().out
    assert "shop-api has no dev URL (not exposed in dev)" in out and fake.calls == []
