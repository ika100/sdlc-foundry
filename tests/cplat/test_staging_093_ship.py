"""Spec 093 acceptance tests, `cplat ship deploy` promoting to staging after a green dev smoke: the decision (`staging.decide`), the
dispatch, the wait for the self-merging pin PR, Argo health in staging, the staging smoke, its issue and run record, the resume and
the report lines. AC-093.1, .3, .4, .5, .6, .8, .9, .10 and .15 as the user sees them.

Seams: `staging.gh` (gitops-app files, compare, commits, the dispatch), `ship.gh` for the pin PR and its run (one fake answers both),
`smoke.gh`, `smoke.run_recipe` through a fake `devbox` on PATH, `smoke.sleep`, kubectl via `ship.run`, `ship.sleep`/`ship.now` and
the autoissue fake tracker, as in test_smoke_091_ship. `staging` and `staging_deploy` are imported inside the tests: they do not
exist yet. Contract: design.md "Decision", "Dispatch and the workflow", "Ship deploy", "State and resume", "Run record"."""
import base64
import importlib
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone

import pytest

import core
import ship
from test_autoissue import clk, tr, ai  # noqa: F401  (fixtures)
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)
from test_ship import SHA
from test_ship_checks import GITOPS, HEALTHY, argo, gh  # noqa: F401  (gh is a fixture)
from test_smoke_091_run import FakeDevbox, HEALTH_ID, SECRET, SLUG, TEST_ID, make_service, result_lines
from test_smoke_091_ship import FAIL_ONE, PASS_ALL, World, in_order, lines_of, repo, world  # noqa: F401  (fixtures)

SPEC_ID = "007-price-alerts"
OLD = "sha-" + "b" * 40                      # what staging runs before
TAG = f"sha-{SHA}"
PR_URL = f"https://github.com/{GITOPS}/pull/21"
RUN_URL = f"https://github.com/{GITOPS}/actions/runs/88"
STAGING_URL = "http://shop-api.shop-staging.localhost:8088"
WORKFLOW = ".github/workflows/pin-staging.yml"
KUSTOMIZATION = "applications/shop/overlays/staging/shop-api/kustomization.yaml"
APP_HOSTS = ('gateway: {name: traefik-gateway, namespace: kube-system}\nhosts:\n  dev: "{service}.{app}-dev.localhost"\n'
             '  staging: "{service}.{app}-staging.localhost"\n')


def staging_mod():
    return importlib.import_module("staging")


def services_text(envs="[dev, staging]", promotion="", expose=True):
    return ("services:\n  - name: shop-api\n    repo: acme/shop-api\n    shape: service-python\n    port: 8080\n"
            + ("    expose: {host: shop-api}\n" if expose else "") + f"    environments: {envs}\n" + promotion)


def kustomization(tag):
    return f"images:\n  - name: ghcr.io/acme/shop-api\n    newTag: {tag}\n"


def jq(expr, obj):
    expr = expr.strip()
    if re.fullmatch(r"\.\w+", expr):
        return str(obj[expr[1:]])
    return subprocess.run([shutil.which("jq") or "jq", "-r", expr], input=json.dumps(obj), capture_output=True, text=True).stdout.strip()


class Api:
    """`gh` for the gitops-app repo and the service repo: file contents, directory listing, compare, commits, the dispatch, the pin
    PR of the dispatched build and its run. One instance answers `smoke.gh`, `staging.gh` and the pin-staging parts of `ship.gh`."""

    def __init__(self, services: str, app: str):
        self.files = {"applications/shop/services.yaml": services, "applications/shop/app.yaml": app,
                      KUSTOMIZATION: kustomization(OLD), WORKFLOW: "name: pin-staging\n"}
        self.compare_status = "behind"          # compare/<build>...<staging commit>: the build is ahead of staging
        self.commits: dict[str, str] = {}       # ref -> full sha (tags)
        self.dispatches: list[dict] = []
        self.dispatch_error: str | None = None
        self.pr_states = ["MERGED"]             # successive `pr list` answers once dispatched ([] = no PR)
        self.run_views = [{"status": "completed", "conclusion": "success"}]
        self.dispatched = False
        self.calls: list[list[str]] = []

    # which of ship's gh calls this fake answers
    def handles(self, args) -> bool:
        joined = " ".join(args)
        return ((args[:2] == ["pr", "list"] and "pin/staging-" in joined) or (args[:2] == ["run", "list"] and "pin-staging" in joined)
                or (args[:2] == ["run", "view"] and args[2] == "88") or (args[0] == "api" and "/dispatches" in joined))

    def __call__(self, args, *, cwd=None, check=True):
        self.calls.append(args)
        assert len(self.calls) < 5000, "runaway wait loop"
        joined = " ".join(args)
        if args[:2] == ["pr", "list"]:
            if not self.dispatched or not self.pr_states:
                return "[]"
            state = self.pr_states.pop(0) if len(self.pr_states) > 1 else self.pr_states[0]
            return json.dumps([{"number": 21, "state": state, "url": PR_URL}])
        if args[:2] == ["run", "list"]:
            return json.dumps([{"databaseId": 88, "displayTitle": f"pin-staging shop-api {TAG}"}] if self.dispatched else [])
        if args[:2] == ["run", "view"]:
            if "--log-failed" in args:
                return "ci log line\n"
            v = self.run_views.pop(0) if len(self.run_views) > 1 else self.run_views[0]
            return json.dumps({**v, "url": RUN_URL})
        assert args[0] == "api", args
        path = next((a.lstrip("/").split("?")[0] for a in args[1:] if a.lstrip("/").startswith("repos/")), "")
        if path.endswith("/dispatches"):
            if self.dispatch_error:
                raise core.PlatformError(self.dispatch_error)
            fields = {}
            for i, a in enumerate(args):
                if a in {"-f", "-F", "--raw-field", "--field"} and "=" in args[i + 1]:
                    k, v = args[i + 1].split("=", 1)
                    fields[k] = v
            self.dispatches.append({"repo": path[len("repos/"):-len("/dispatches")], **fields})
            self.dispatched = True
            return ""
        if "/compare/" in path:
            return self._out({"status": self.compare_status}, args)
        if "/commits/" in path:
            ref = path.split("/commits/")[1]
            return self._out({"sha": self.commits.get(ref, ref)}, args)
        rel = path.split("/contents/")[1] if "/contents/" in path else None
        if rel == "applications" or (rel is None and "services.yaml" not in joined and "app.yaml" not in joined):
            return "shop\n" if "--jq" in args or "-q" in args else json.dumps([{"name": "shop", "type": "dir"}])
        for p, text in self.files.items():
            if rel == p or (rel is None and p in joined):
                if "raw" in joined.lower():
                    return text
                if "--jq" in args or "-q" in args:
                    return base64.b64encode(text.encode()).decode()
                return json.dumps({"content": base64.b64encode(text.encode()).decode(), "encoding": "base64"})
        raise core.PlatformError("HTTP 404: Not Found")

    @staticmethod
    def _out(obj, args):
        for flag in ("--jq", "-q"):
            if flag in args:
                return jq(args[args.index(flag) + 1], obj)
        return json.dumps(obj)


class SWorld(World):
    def stage(self, *, services=None, app=None, api=None, context="lan", tweak=None):
        services = services if services is not None else services_text(promotion="    promotion: {staging: auto}\n")
        app = app if app is not None else APP_HOSTS
        self.install(services=services)
        self.api = api or Api(services, app)
        if tweak:
            tweak(self.api)
        staging, staging_deploy = staging_mod(), importlib.import_module("staging_deploy")
        for mod in (staging, staging_deploy):
            self.mp.setattr(mod, "gh", self.api, raising=False)
            self.mp.setattr(mod, "sleep", ship.sleep, raising=False)
            self.mp.setattr(mod, "now", ship.now, raising=False)
        self.mp.setattr(importlib.import_module("smoke"), "gh", self.api)
        previous = ship.gh

        def routed(args, *, cwd, check=True):
            return self.api(args, cwd=cwd, check=check) if self.api.handles(args) else previous(args, cwd=cwd, check=check)
        self.mp.setattr(ship, "gh", routed)
        argo(self.mp, {"shop-api-dev": HEALTHY, "shop-api-staging": HEALTHY})
        return self

    def dispatches(self):
        return self.api.dispatches

    def staging_state(self):
        return self.state()["staging"]


@pytest.fixture()
def sw(repo, gh, store, tr, tmp_path, monkeypatch):
    return SWorld(repo, gh, store, tr, FakeDevbox(tmp_path, monkeypatch), monkeypatch)


# ---------------- AC-093.1, AC-093.8: green dev smoke, the pin PR, Argo, staging smoke ----------------

def test_a_green_dev_smoke_dispatches_the_pin_and_reports_the_promotion_ac_093_1(sw, capsys):  # AC-093.1
    sw.stage()
    sw.fake.script([PASS_ALL])
    assert sw.deploy() == 0
    out = lines_of(capsys)
    in_order(out, f"staging: dispatched pin-staging shop-api {TAG} to {GITOPS}", f"staging: pinned shop-api to {TAG} ({PR_URL}), was {OLD}",
             "Argo CD shop-api-staging: Synced/Healthy", f"smoke (staging) against {STAGING_URL}:", f"Promotion (staging): {TAG} ({PR_URL})",
             "Smoke (staging): 2/2 passed")
    (d,) = sw.dispatches()
    assert d["repo"] == GITOPS and d["event_type"] == "pin-staging"
    assert (d["client_payload[service]"], d["client_payload[tag]"], d["client_payload[spec]"]) == ("shop-api", TAG, SPEC_ID)
    assert "2/2 passed" in d["client_payload[smoke]"] and d["client_payload[record]"] == ""      # no run store: no record link
    assert sw.state()["phase"] == "done" and sw.tr.calls == []


def test_the_dispatch_names_the_run_record_when_a_store_is_configured_ac_093_1(sw, capsys):  # AC-093.1
    sw.stage()
    sw.fake.script([PASS_ALL])
    sw.deploy()
    (d,) = sw.dispatches()
    now = datetime.now(timezone.utc)
    rec = d["client_payload[record]"]
    assert rec.startswith("https://github.com/acme/runs/blob/HEAD/runs/") and rec.endswith(".json")
    assert f"{now:%Y/%m/%d}" in rec or f"{now:%Y/%m}" in rec


def test_record_url_is_none_without_a_store_and_a_blob_link_with_one_ac_093_7(monkeypatch):  # AC-093.7
    staging = staging_mod()
    assert staging.record_url("run-1") is None
    monkeypatch.setenv("CPLAT_RUNS_REPO", "acme/runs")
    url = staging.record_url("run-1")
    assert re.fullmatch(r"https://github\.com/acme/runs/blob/HEAD/runs/\d{4}/\d{2}/\d{2}/run-1\.json", url)


def test_staging_is_smoked_against_its_published_url_ac_093_8(sw, capsys):  # AC-093.8
    sw.stage()
    sw.fake.script([PASS_ALL])
    sw.deploy()
    (dev, stg) = sw.fake.calls
    assert dev[1] == "http://shop-api.shop-dev.localhost:8088" and stg[0] == "run smoke" and stg[1] == STAGING_URL


def test_staging_smoke_passed_on_retry_is_reported_like_dev_ac_093_8(sw, capsys):  # AC-093.8
    sw.stage()
    sw.fake.script([PASS_ALL, FAIL_ONE, PASS_ALL])
    assert sw.deploy() == 0
    assert "Smoke (staging): passed on retry" in lines_of(capsys)
    assert sw.sleeps == [30] and sw.record()["smoke"]["staging"]["outcome"] == "passed-on-retry"


def test_the_run_record_has_both_outcomes_and_the_promotion_ac_093_8(sw, capsys):  # AC-093.8
    sw.stage()
    sw.fake.script([PASS_ALL])
    sw.deploy()
    sec = sw.record()["smoke"]
    assert (sec["env"], sec["outcome"], sec["image"]) == ("dev", "passed", TAG) and isinstance(sec["at"], str)
    stg = sec["staging"]
    assert (stg["env"], stg["outcome"], stg["image"], stg["base_url"]) == ("staging", "passed", TAG, STAGING_URL)
    assert (stg["passed"], stg["failed"]) == (2, 0) and isinstance(stg["at"], str) and stg["filed"] is None
    p = sw.record()["promotion"]["staging"]
    assert (p["result"], p["tag"], p["previous"]) == ("promoted", TAG, OLD) and PR_URL in json.dumps(p)


def test_the_state_and_describe_carry_the_staging_result_ac_093_8(sw, capsys):  # AC-093.8
    sw.stage()
    sw.fake.script([PASS_ALL])
    sw.deploy()
    st = sw.staging_state()
    assert st["state"] == "smoked" and st["tag"] == TAG and st["previous"] == OLD and st["pr"] == PR_URL
    assert st["smoke"]["outcome"] == "passed" and st["smoke"]["url"] == STAGING_URL
    row = next(ln for ln in ship.describe(sw.state()).splitlines() if ln.startswith("  staging: "))
    assert row.startswith("  staging: Promotion") or "Promotion" in row
    assert row.endswith("smoke 2/2 passed")


def test_a_pin_that_changes_nothing_is_not_an_error_ac_093_1(sw, capsys):  # AC-093.1
    sw.stage(tweak=lambda a: setattr(a, "pr_states", []))
    sw.fake.script([PASS_ALL])
    assert sw.deploy() == 0
    assert f"Promotion (staging): staging already runs {TAG}" in lines_of(capsys)
    assert len(sw.fake.calls) == 1                                               # no staging smoke: nothing changed


def test_the_staging_window_is_fifteen_minutes_ac_093_1():  # AC-093.1
    assert importlib.import_module("staging_deploy").STAGING_WINDOW_S == 900


def test_a_pin_that_does_not_land_in_fifteen_minutes_escalates_ac_093_1(sw, capsys):  # AC-093.1
    sw.stage(tweak=lambda a: (setattr(a, "pr_states", ["OPEN"]), setattr(a, "run_views", [{"status": "in_progress"}])))
    sw.fake.script([PASS_ALL])
    assert sw.deploy() == 1
    st = sw.state()
    assert st["escalated"].startswith(f"staging did not run {TAG} within 15 minutes of the green dev smoke") and st["cause"] == "environment"
    assert len(sw.fake.calls) == 1


def test_a_staging_that_is_not_healthy_on_the_tag_escalates_ac_093_1(sw, capsys):  # AC-093.1
    sw.stage()
    degraded = {**HEALTHY, "health": {"status": "Degraded"}, "summary": {"images": [f"ghcr.io/acme/shop-api:{TAG}"]}}
    argo(sw.mp, {"shop-api-dev": HEALTHY, "shop-api-staging": degraded})
    sw.fake.script([PASS_ALL])
    assert sw.deploy() == 1
    st = sw.state()
    assert st["escalated"].startswith("shop-api-staging is ") and st["escalated"].endswith(f" on {TAG}") and st["cause"] == "environment"
    assert len(sw.fake.calls) == 1


def test_a_dispatch_that_gh_refuses_escalates_with_its_message_ac_093_1(sw, capsys):  # AC-093.1
    sw.stage(tweak=lambda a: setattr(a, "dispatch_error", "HTTP 403: Resource not accessible"))
    sw.fake.script([PASS_ALL])
    assert sw.deploy() == 1
    st = sw.state()
    assert st["escalated"].startswith("could not start the staging promotion: ") and "HTTP 403" in st["escalated"]
    assert st["cause"] == "environment"


# ---------------- AC-093.3: red or not-run dev smoke never promotes ----------------

def test_a_red_dev_smoke_promotes_nothing_and_says_why_ac_093_3(sw, capsys, ai):  # AC-093.3
    sw.stage()
    sw.fake.script([FAIL_ONE])
    assert sw.deploy() == 1
    assert "Promotion (staging): not promoted: dev smoke red" in lines_of(capsys)
    assert sw.dispatches() == [] and sw.staging_state()["state"] == "skipped"
    assert sw.state()["escalated"] == f"smoke red in dev: 1 failing ({SPEC_ID})"


def test_a_dev_smoke_that_was_not_run_promotes_nothing_ac_093_3(sw, capsys):  # AC-093.3
    sw.stage()
    assert sw.deploy(context=None) == 0
    reason = "dev smoke not run: no kube context, so Argo health was not checked (pass --context <kube-context>)"
    assert f"Promotion (staging): not promoted: {reason}" in lines_of(capsys)
    assert sw.dispatches() == [] and sw.staging_state()["reason"] == reason


def test_the_record_says_skipped_with_the_reason_ac_093_3(sw, capsys):  # AC-093.3
    sw.stage()
    sw.deploy(context=None)
    p = sw.record()["promotion"]["staging"]
    assert p["result"] == "skipped" and p["reason"].startswith("dev smoke not run: ")


# ---------------- AC-093.4: the first entry into staging stays manual ----------------

def test_a_service_not_yet_in_staging_is_not_promoted_and_the_first_step_is_named_ac_093_4(sw, capsys):  # AC-093.4
    sw.stage(services=services_text(envs="[dev]", promotion="    promotion: {staging: auto}\n"))
    sw.fake.script([PASS_ALL])
    assert sw.deploy() == 0
    assert ("Promotion (staging): not promoted: shop-api is not in staging yet: the first promotion is manual: "
            "/gitops:promote shop-api dev staging") in lines_of(capsys)
    assert sw.dispatches() == [] and len(sw.fake.calls) == 1


# ---------------- AC-093.5: staging already newer / older PR superseded ----------------

def test_a_staging_that_already_runs_the_build_is_left_alone_ac_093_5(sw, capsys):  # AC-093.5
    def same(a):
        a.files[KUSTOMIZATION] = kustomization(TAG)
    sw.stage(tweak=same)
    sw.fake.script([PASS_ALL])
    assert sw.deploy() == 0
    assert f"Promotion (staging): not promoted: staging already runs {TAG}: nothing pinned" in lines_of(capsys)
    assert sw.dispatches() == []


def test_a_staging_that_runs_a_later_commit_is_left_alone_ac_093_5(sw, capsys):  # AC-093.5
    sw.stage(tweak=lambda a: setattr(a, "compare_status", "ahead"))
    sw.fake.script([PASS_ALL])
    assert sw.deploy() == 0
    assert ("Promotion (staging): not promoted: staging already runs a newer build of shop-api (bbbbbbb): nothing pinned"
            in lines_of(capsys))
    assert sw.dispatches() == [] and len(sw.fake.calls) == 1


# ---------------- AC-093.15: the off switch, at both levels ----------------

def test_nothing_set_means_off_and_the_report_says_so_ac_093_15(sw, capsys):  # AC-093.15
    sw.stage(services=services_text())
    sw.fake.script([PASS_ALL])
    assert sw.deploy() == 0
    assert "Promotion (staging): not promoted: automatic promotion to staging is off for shop-api" in lines_of(capsys)
    assert sw.dispatches() == []


def test_a_service_can_switch_it_off_under_an_app_that_has_it_on_ac_093_15(sw, capsys):  # AC-093.15
    sw.stage(services=services_text(promotion="    promotion: {staging: manual}\n"), app=APP_HOSTS + "promotion: {staging: auto}\n")
    sw.fake.script([PASS_ALL])
    assert sw.deploy() == 0
    assert "automatic promotion to staging is off for shop-api" in "\n".join(lines_of(capsys)) and sw.dispatches() == []


def test_the_app_setting_alone_switches_it_on_ac_093_15(sw, capsys):  # AC-093.15
    sw.stage(services=services_text(), app=APP_HOSTS + "promotion: {staging: auto}\n")
    sw.fake.script([PASS_ALL])
    assert sw.deploy() == 0
    assert len(sw.dispatches()) == 1


def test_a_service_can_switch_it_on_under_an_app_that_has_it_off_ac_093_15(sw, capsys):  # AC-093.15
    sw.stage(services=services_text(promotion="    promotion: {staging: auto}\n"), app=APP_HOSTS + "promotion: {staging: manual}\n")
    sw.fake.script([PASS_ALL])
    assert sw.deploy() == 0
    assert len(sw.dispatches()) == 1


def test_an_app_without_the_workflow_is_not_promoted_and_told_to_update_ac_093_15(sw, capsys):  # AC-093.15
    sw.stage(tweak=lambda a: a.files.pop(WORKFLOW))
    sw.fake.script([PASS_ALL])
    assert sw.deploy() == 0
    assert (f"Promotion (staging): not promoted: the gitops-app shop has no pin-staging workflow "
            "(update it with /shared:update-service)") in lines_of(capsys)
    assert sw.dispatches() == []


# ---------------- AC-093.6: the CI of the pin PR fails ----------------

def test_a_failed_gitops_ci_leaves_staging_and_escalates_with_the_run_ac_093_6(sw, capsys):  # AC-093.6
    sw.stage(tweak=lambda a: (setattr(a, "pr_states", ["OPEN"]), setattr(a, "run_views", [{"status": "completed", "conclusion": "failure"}])))
    sw.fake.script([PASS_ALL])
    assert sw.deploy() == 1
    st = sw.state()
    assert st["escalated"] == f"staging pin failed for shop-api: gitops-app CI failure ({RUN_URL}); staging keeps {OLD}"
    assert st["cause"] == "environment" and sw.staging_state()["state"] == "pin-failed"
    assert len(sw.fake.calls) == 1 and "Argo CD shop-api-staging: Synced/Healthy" not in lines_of(capsys)
    assert sw.record()["promotion"]["staging"]["result"] == "failed"


def test_a_pr_closed_without_merging_escalates_ac_093_6(sw, capsys):  # AC-093.6
    sw.stage(tweak=lambda a: setattr(a, "pr_states", ["OPEN", "CLOSED"]))
    sw.fake.script([PASS_ALL])
    assert sw.deploy() == 1
    assert sw.state()["escalated"] == f"staging pin failed for shop-api: {PR_URL} was closed without merging; staging keeps {OLD}"


def failed_ci(a):
    a.pr_states = ["OPEN"]
    a.run_views = [{"status": "completed", "conclusion": "failure"}]


def test_a_resume_after_the_pr_was_merged_by_hand_continues_with_staging_ac_093_6(sw, capsys):  # AC-093.6
    sw.stage(tweak=failed_ci)
    sw.fake.script([PASS_ALL])
    sw.deploy()
    sw.api.pr_states = ["MERGED"]
    sw.fake.script([PASS_ALL])
    assert sw.deploy() == 0
    out = lines_of(capsys)
    assert "Smoke (staging): 2/2 passed" in out and len(sw.dispatches()) == 1       # not dispatched twice
    assert sw.state()["phase"] == "done"


def test_a_resume_with_the_pr_still_open_escalates_again_ac_093_6(sw, capsys):  # AC-093.6
    sw.stage(tweak=failed_ci)
    sw.fake.script([PASS_ALL])
    sw.deploy()
    assert sw.deploy() == 1
    assert sw.state()["escalated"].endswith(f"; fix the gitops-app CI and merge {PR_URL}, or close it")


def test_a_resume_with_the_pr_closed_ends_the_run_ac_093_6(sw, capsys):  # AC-093.6
    sw.stage(tweak=failed_ci)
    sw.fake.script([PASS_ALL])
    sw.deploy()
    sw.api.pr_states = ["CLOSED"]
    assert sw.deploy() == 0
    assert f"Promotion (staging): {PR_URL} closed without merging; staging keeps {OLD}" in lines_of(capsys)
    assert sw.state()["phase"] == "done"


# ---------------- AC-093.9: red staging smoke ----------------

def red_staging(sw):
    sw.stage()
    sw.fake.script([PASS_ALL, (['Authorization: token ' + SECRET] + result_lines(("FAIL", TEST_ID), ("PASS", HEALTH_ID)), 1)])


def test_a_red_staging_smoke_escalates_as_code_and_keeps_the_build_ac_093_9(sw, capsys, ai):  # AC-093.9
    red_staging(sw)
    assert sw.deploy() == 1
    out = lines_of(capsys)
    reason = f"smoke red in staging: 1 failing ({SPEC_ID})"
    st = sw.state()
    assert st["escalated"] == reason and st["cause"] == "code" and st["phase"] != "done"
    line = next(ln for ln in out if ln.startswith(f"ship {SPEC_ID}: escalated ({reason}); staging keeps running {TAG} "))
    assert f"(no automatic rollback: revert {PR_URL} to go back to {OLD}" in line and line.endswith(f"Resume with /svc:ship {SPEC_ID}")
    assert len(sw.dispatches()) == 1 and SECRET not in "\n".join(out)           # nothing was pinned back
    assert any(ln.startswith("Smoke (staging): red (1 failing") for ln in out)
    assert sw.record()["smoke"]["staging"]["outcome"] == "red"
    assert sw.record()["promotion"]["staging"]["result"] == "promoted"


def test_the_staging_issue_follows_the_091_convention_ac_093_9(sw, capsys, ai):  # AC-093.9
    red_staging(sw)
    sw.deploy()
    ((_, repo_, title, body, labels),) = sw.tr.created()
    assert repo_ == SLUG and title == f"[auto] Smoke red in staging: {TEST_ID}"
    assert set(labels) == {"triage", "auto-filed", "smoke-failure"}
    sig = ai.signature("smoke", SLUG, "staging", TEST_ID)
    assert body.splitlines().count(f"Signature: {sig}") == 1 and SECRET not in body
    assert ai.signature("smoke", SLUG, "dev", TEST_ID) != sig


def test_an_open_issue_with_the_same_signature_gets_a_comment_ac_093_9(sw, capsys, ai):  # AC-093.9
    red_staging(sw)
    sig = ai.signature("smoke", SLUG, "staging", TEST_ID)
    sw.tr.add(SLUG, body=f"Signature: {sig}\n", title="[auto] Smoke red in staging", labels=("triage", "auto-filed", "smoke-failure"))
    sw.deploy()
    assert sw.tr.created() == [] and len(sw.tr.commented()) == 1


def test_resuming_after_a_red_staging_smoke_runs_the_staging_smoke_only_ac_093_9(sw, capsys, ai):  # AC-093.9
    red_staging(sw)
    sw.deploy()
    sw.fake.script([PASS_ALL])
    assert sw.deploy() == 0
    out = lines_of(capsys)
    assert "resuming: staging smoke only, against what staging runs now" in out and len(sw.dispatches()) == 1
    assert sw.fake.calls[0][1] == STAGING_URL and len(sw.fake.calls) == 1
    assert sw.state()["phase"] == "done"


# ---------------- AC-093.10: no staging URL ----------------

def test_a_service_without_a_staging_url_is_not_run_not_passed_and_not_escalated_ac_093_10(sw, capsys):  # AC-093.10
    sw.stage(services=services_text(promotion="    promotion: {staging: auto}\n", expose=False))
    sw.fake.script([PASS_ALL])
    assert sw.deploy() == 0
    out = lines_of(capsys)
    assert "Smoke (staging): not run: no staging URL for shop-api" in out
    assert len(sw.fake.calls) == 1 and sw.state()["phase"] == "done" and not sw.state().get("escalated")
    stg = sw.record()["smoke"]["staging"]
    assert stg["outcome"] == "not-run" and stg["env"] == "staging"


def test_an_app_without_a_staging_host_is_also_not_run_ac_093_10(sw, capsys):  # AC-093.10
    only_dev = 'gateway: {name: traefik-gateway, namespace: kube-system}\nhosts:\n  dev: "{service}.{app}-dev.localhost"\n'
    sw.stage(app=only_dev)
    sw.fake.script([PASS_ALL])
    assert sw.deploy() == 0
    assert "Smoke (staging): not run: no staging URL for shop-api" in lines_of(capsys)


# ---------------- decide(): the table of reasons, called directly ----------------

class Dev:
    """A dev smoke outcome as the decision sees it (smoke.SmokeResult)."""

    @staticmethod
    def of(outcome, reason=None):
        import smoke
        return smoke.SmokeResult(env="dev", outcome=outcome, base_url=None, reason=reason, passed=2 if outcome.startswith("passed") else 0)


def decide(sw, dev, services=None, tweak=None, st=None):
    sw.stage(services=services, tweak=tweak)
    return staging_mod().decide(sw.repo, st or {"deployed": TAG}, [GITOPS], "shop-api", dev)


def test_decide_promotes_with_everything_ship_needs_ac_093_1(sw):  # AC-093.1
    d = decide(sw, Dev.of("passed"))
    assert (d.action, d.reason, d.service, d.tag, d.previous) == ("promote", None, "shop-api", TAG, OLD)
    assert d.app == GITOPS and d.app_dir == "applications/shop" and d.workflow is True


@pytest.mark.parametrize("outcome", ["passed", "passed-on-retry"])
def test_both_green_outcomes_promote_ac_093_1(sw, outcome):  # AC-093.1
    assert decide(sw, Dev.of(outcome)).action == "promote"


@pytest.mark.parametrize("outcome", ["red", "timed-out"])
def test_red_and_timed_out_dev_skip_with_dev_smoke_red_ac_093_3(sw, outcome):  # AC-093.3
    d = decide(sw, Dev.of(outcome))
    assert (d.action, d.reason) == ("skip", "dev smoke red")


def test_not_run_dev_skips_with_its_reason_ac_093_3(sw):  # AC-093.3
    d = decide(sw, Dev.of("not-run", "dev URL http://x is not reachable: refused"))
    assert (d.action, d.reason) == ("skip", "dev smoke not run: dev URL http://x is not reachable: refused")


def test_a_service_that_is_not_in_the_gitops_app_skips_ac_093_3(sw):  # AC-093.3
    other = "services:\n  - name: other\n    repo: acme/other\n    shape: service-python\n    port: 8080\n"
    d = decide(sw, Dev.of("passed"), services=other)
    assert (d.action, d.reason) == ("skip", "shop-api is not in the linked gitops-app")


def test_a_staging_tag_of_seven_characters_resolves_to_the_build_ac_093_5(sw):  # AC-093.5
    def short(a):
        a.files[KUSTOMIZATION] = kustomization("sha-" + SHA[:7])
        a.commits[SHA[:7]] = SHA
    d = decide(sw, Dev.of("passed"), tweak=short)
    assert d.action == "skip" and d.reason == f"staging already runs {TAG}: nothing pinned"


def test_a_release_tag_in_staging_resolves_through_the_tag_commit_ac_093_5(sw):  # AC-093.5
    def release(a):
        a.files[KUSTOMIZATION] = kustomization("1.4.0")
        a.commits["v1.4.0"] = "c" * 40
        a.compare_status = "ahead"
    d = decide(sw, Dev.of("passed"), tweak=release)
    assert d.action == "skip" and d.reason == "staging already runs a newer build of shop-api (ccccccc): nothing pinned"


def test_a_diverged_history_still_promotes_ac_093_5(sw):  # AC-093.5
    assert decide(sw, Dev.of("passed"), tweak=lambda a: setattr(a, "compare_status", "diverged")).action == "promote"
