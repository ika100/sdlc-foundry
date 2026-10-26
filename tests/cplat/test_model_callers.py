"""Spec 113 acceptance tests: the commands take their answers from the model and nothing observable changes
(AC-113.9 observed state, AC-113.11 status / promote / smoke / staging / alert poll, AC-113.18 secret / app-ship gate class).

Each test runs a caller on hand-built repo files (model_fixtures), checks that its output is what it was before, and that the caller
asks the model: `spy()` wraps the model function the design names (`model.load_dir`, `model.load_remote`, `model.build`,
`model.write_pin`) and records the calls; `alt_model()` replaces the loaded model by one built from other data and the caller
must follow it. The seams are the existing ones: `status.sh`, `promote.gh`, `smoke.gh`, `staging.gh`, `secret.kubectl`,
`appship_sched.run`. `model` does not exist before the feature, so it is imported inside the tests."""
import base64
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import core
import evidence
import gitops
import promote
import registry
import secret
import smoke
import staging
import status
from alerts_fakes import APP as ALERT_APP, make_app
from model_fixtures import SHA, SMALL_APP, SMALL_PINS, SMALL_SERVICES, clean, git, git_repo, model, snapshot, write_app
from test_smoke_091_run import APP as SMOKE_APP, EXPOSED, GITOPS, GitopsApi, HIDDEN, make_service

D1, D2 = "sha256:" + "1" * 64, "sha256:" + "2" * 64


def spy(monkeypatch, name):
    """Wrap model.<name>: calls are recorded as (args, kwargs) and passed through."""
    mod = model()
    real = getattr(mod, name)
    calls = []

    def wrapper(*args, **kwargs):
        calls.append((args, kwargs))
        return real(*args, **kwargs)
    monkeypatch.setattr(mod, name, wrapper)
    return calls


def alt_model(monkeypatch, name, services, app, pins=None):
    """model.<name> answers with a model built from `services` / `app` whatever the files say; returns the calls."""
    mod = model()
    calls = []
    build = mod.build  # the original, before `name` (possibly "build" itself) is replaced

    def replaced(*args, **kwargs):
        calls.append((args, kwargs))
        system = args[0].name if isinstance(args[0], Path) else args[0]
        return build(system, copy.deepcopy(services), copy.deepcopy(app), pins=pins)
    monkeypatch.setattr(mod, name, replaced)
    return calls


# ======================================================================================
# status (AC-113.11, AC-113.9)
# ======================================================================================

STATUS_ANSWERS = {
    ("gh", "run"): "completed success",
    ("gh", "api"): "platform: 4.0.0",
    ("git", "-C"): "https://github.com/acme/shop-gitops.git",
    ("gh", "pr"): json.dumps([{"number": 12, "headRefName": "pin/dev-shop-api-def5678"}]),
    ("kubectl", "--context"): json.dumps({"items": [
        {"metadata": {"name": "shop-api-dev"}, "status": {"sync": {"status": "Synced"}, "health": {"status": "Healthy"}}},
        {"metadata": {"name": "addon-postgres-dev"}, "status": {"sync": {"status": "Synced"}, "health": {"status": "Progressing"}}}]}),
}
STAGING_PIN = "sha-" + "b" * 40


def row(service, env, tag, argo, *, ci="ok", exposed=False, pin_pr="-", platform="4.0.0 (behind)"):
    return {"service": service, "env": env, "tag": tag, "ci": ci, "argo": argo, "exposed": exposed, "pin_pr": pin_pr, "platform": platform}


STATUS_ROWS = [
    row("shop-api", "dev", "sha-" + SHA, "Synced/Healthy", exposed=True, pin_pr="#12 sha-def5678"),
    row("shop-api", "staging", STAGING_PIN, "missing", exposed=True),
    row("stock", "dev", "sha-abc1234", "missing"),
    row("postgres (addon)", "dev", "-", "Synced/Progressing", ci="-", platform="-"),
    row("postgres (addon)", "staging", "-", "missing", ci="-", platform="-"),
    row("observability (addon)", "dev", "-", "missing", ci="-", platform="-"),
    row("observability (addon)", "staging", "-", "missing", ci="-", platform="-"),
]


@pytest.fixture()
def status_repo(tmp_path, monkeypatch):
    write_app(tmp_path, SMALL_SERVICES, SMALL_APP, {**SMALL_PINS, ("staging", "shop-api"): STAGING_PIN})
    git_repo(tmp_path)
    monkeypatch.setattr(status, "sh", lambda cmd: STATUS_ANSWERS.get((cmd[0], cmd[1])))
    monkeypatch.setattr(core, "platform_version", lambda: "4.8.0")
    return tmp_path


def test_status_rows_come_from_the_models_instances_ac_113_11(status_repo, monkeypatch):  # AC-113.11
    calls = spy(monkeypatch, "load_dir")
    app, rows = status.collect(status_repo, None, "k3d-x")
    assert app == "shop" and rows == STATUS_ROWS
    assert [c[0][0].name for c in calls] == ["shop"]


def test_status_follows_the_model_not_the_files_ac_113_11(status_repo, monkeypatch):  # AC-113.11
    other = [{"name": "ledger", "repo": "acme/ledger", "image": "ghcr.io/acme/ledger", "shape": "service-java", "environments": ["dev"]}]
    alt_model(monkeypatch, "load_dir", other, {})
    _, rows = status.collect(status_repo, None, "k3d-x")
    assert [(r["service"], r["env"]) for r in rows] == [("ledger", "dev")]


def test_status_pinned_tag_stays_and_reads_the_overlay_ac_113_11(status_repo):  # AC-113.11
    d = status_repo / "applications/shop"
    assert status.pinned_tag(d, "dev", "shop-api") == "sha-" + SHA
    assert status.pinned_tag(d, "prod", "shop-api") is None
    assert not hasattr(status, "ENVS")


def test_status_table_and_json_are_unchanged_ac_113_11(status_repo, monkeypatch, capsys):  # AC-113.11
    calls = spy(monkeypatch, "load_dir")
    assert status.main(["--repo-dir", str(status_repo), "--context", "k3d-x", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"app": "shop", "rows": STATUS_ROWS}
    assert status.main(["--repo-dir", str(status_repo), "--context", "k3d-x"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("## shop (gitops-app) — platform 4.8.0 available, repo stamped none")
    assert "  shop-api               dev      sha-" + SHA + "  ok  Synced/Healthy      #12 sha-def5678  4.0.0 (behind)" in out
    assert "  observability (addon)  staging  -" in out and len(calls) == 2


def test_status_with_a_context_leaves_the_working_tree_unchanged_ac_113_9(status_repo, capsys):  # AC-113.9
    before = snapshot(status_repo)
    assert status.main(["--repo-dir", str(status_repo), "--context", "k3d-x"]) == 0
    assert clean(status_repo) and snapshot(status_repo) == before


def test_status_does_not_leave_observed_state_in_a_later_model_ac_113_9(status_repo):  # AC-113.9
    status.collect(status_repo, None, "k3d-x")
    m = model().load_dir(status_repo / "applications/shop")
    assert all(i.observed == {} for i in m.instances)


# ======================================================================================
# promote (AC-113.11, AC-113.9)
# ======================================================================================

STAGING_SHA = "sha-" + "c" * 40


@pytest.fixture()
def promote_repo(tmp_path, monkeypatch):
    services = [
        {"name": "api", "repo": "acme/api", "image": "ghcr.io/acme/api", "shape": "service-python", "port": 8080, "environments": ["dev", "staging"]},
        {"name": "web", "repo": "acme/web", "image": "ghcr.io/acme/web", "shape": "web-nextjs", "port": 3000, "environments": ["dev"]}]
    write_app(tmp_path, services, {"hosts": {}}, {("dev", "api"): "latest", ("staging", "api"): STAGING_SHA, ("dev", "web"): "latest"})
    git_repo(tmp_path)
    monkeypatch.setattr(promote, "gh", lambda args: (_ for _ in ()).throw(AssertionError(f"unexpected gh call {args}")))
    monkeypatch.setattr(promote, "image_tags", lambda image: {"1.3.0"})
    monkeypatch.setattr(evidence, "summary", lambda svc, version, tag: evidence.Evidence(service=svc["name"], version=version, staging_tag=tag))
    seen = []

    def digests(image, tags):
        seen.append((image, list(tags)))
        return {t: D1 for t in tags}
    monkeypatch.setattr(registry, "digests", digests)

    def render(repo):
        d = Path(repo) / "applications/shop"
        for s in yaml.safe_load((d / "services.yaml").read_text())["services"]:
            for env in s.get("environments") or ["dev"]:
                k = d / "overlays" / env / s["name"] / "kustomization.yaml"
                if not k.exists():
                    k.parent.mkdir(parents=True, exist_ok=True)
                    k.write_text(yaml.safe_dump({"images": [{"name": s["image"], "newTag": "latest"}]}))
    monkeypatch.setattr(gitops, "render", render)
    return SimpleNamespace(root=tmp_path, digests=seen)


def prod_argv(repo, *extra):
    return ["api", "staging", "prod", "--version", "v1.3.0", "--repo-dir", str(repo.root), *extra]


def test_the_digest_check_uses_the_staging_instances_pin_ac_113_11(promote_repo, monkeypatch, capsys):  # AC-113.11
    calls = spy(monkeypatch, "load_dir")
    assert promote.main(prod_argv(promote_repo, "--dry-run", "--json")) == 0
    d = json.loads(capsys.readouterr().out)["digests"]["api"]
    assert d == {"staging_tag": STAGING_SHA, "staging_digest": D1, "release_tag": "1.3.0", "release_digest": D1, "result": "match"}
    assert promote_repo.digests == [("ghcr.io/acme/api", [STAGING_SHA, "1.3.0"])]
    assert len(calls) == 1


def test_the_staging_tag_is_the_models_not_the_files_ac_113_11(promote_repo, monkeypatch, capsys):  # AC-113.11
    other = "sha-" + "e" * 40
    services = yaml.safe_load((promote_repo.root / "applications/shop/services.yaml").read_text())["services"]
    alt_model(monkeypatch, "load_dir", services, {}, pins=lambda env, c: other if env == "staging" else None)
    assert promote.main(prod_argv(promote_repo, "--dry-run", "--json")) == 0
    assert promote_repo.digests == [("ghcr.io/acme/api", [other, "1.3.0"])]
    assert json.loads(capsys.readouterr().out)["digests"]["api"]["staging_tag"] == other


def test_a_dry_run_changes_nothing_ac_113_9(promote_repo, capsys):  # AC-113.9
    before = snapshot(promote_repo.root)
    assert promote.main(prod_argv(promote_repo, "--dry-run")) == 0
    assert clean(promote_repo.root) and snapshot(promote_repo.root) == before
    assert "[PRODUCTION]" in capsys.readouterr().out


def test_promote_dev_to_staging_pins_through_the_model_ac_113_11(promote_repo, monkeypatch, capsys):  # AC-113.11
    sha = "d" * 40
    writes = spy(monkeypatch, "write_pin")
    calls = spy(monkeypatch, "load_dir")
    assert promote.main(["web", "dev", "staging", "--sha", sha, "--no-verify", "--repo-dir", str(promote_repo.root)]) == 0
    d = promote_repo.root / "applications/shop"
    assert [w[0][1:] for w in writes] == [("staging", "web", "sha-" + sha)] and writes[0][0][0] == d
    k = d / "overlays/staging/web/kustomization.yaml"
    assert k.read_text() == yaml.safe_dump({"images": [{"name": "ghcr.io/acme/web", "newTag": "sha-" + sha}]}, sort_keys=False, default_flow_style=False)
    assert yaml.safe_load((d / "services.yaml").read_text())["services"][1]["environments"] == ["dev", "staging"]
    out = capsys.readouterr().out
    assert f"pinned web=sha-{sha}" in out and len(calls) >= 1


def test_promote_all_takes_the_services_that_are_in_the_source_environment_ac_113_11(promote_repo, monkeypatch, capsys):  # AC-113.11
    calls = spy(monkeypatch, "load_dir")
    assert promote.main(["--all", "dev", "staging", "--sha", "a" * 40, "--no-verify", "--dry-run", "--repo-dir", str(promote_repo.root)]) == 0
    out = capsys.readouterr().out
    assert f"api: staging → ghcr.io/acme/api:sha-{'a' * 40}" in out and f"web: staging → ghcr.io/acme/web:sha-{'a' * 40}" in out
    assert len(calls) == 1


def test_a_service_that_is_not_in_the_source_environment_is_refused_ac_113_11(promote_repo, monkeypatch):  # AC-113.11
    spy(monkeypatch, "load_dir")
    with pytest.raises(core.PlatformError, match="web is not in staging yet") as e:
        promote.main(["web", "staging", "prod", "--version", "v1.3.0", "--no-verify", "--repo-dir", str(promote_repo.root)])
    assert e.value.hint == "promote it through the earlier environment first"


@pytest.mark.parametrize("argv, message", [
    (["api", "dev", "qa"], "unknown environment 'qa'"),
    (["api", "prod", "staging"], "cannot promote prod → staging"),
])
def test_the_environment_checks_keep_their_messages_ac_113_11(promote_repo, argv, message):  # AC-113.11
    assert not hasattr(promote, "ORDER")
    with pytest.raises(core.PlatformError, match=message):
        promote.main([*argv, "--repo-dir", str(promote_repo.root)])


# ======================================================================================
# smoke: the dev and staging URL (AC-113.11, AC-113.10)
# ======================================================================================

@pytest.fixture()
def svc(tmp_path):
    return make_service(tmp_path)


def test_dev_url_is_read_through_the_model_ac_113_11(svc, monkeypatch):  # AC-113.11
    monkeypatch.setattr(smoke, "gh", GitopsApi(EXPOSED, SMOKE_APP))
    monkeypatch.delenv("LOCAL_HTTP_PORT", raising=False)
    calls = spy(monkeypatch, "load_remote")
    assert smoke.dev_url(svc, [GITOPS], "shop-api") == ("http://shop-api.shop-dev.localhost:8088", None)
    assert [c[0][0] for c in calls] == ["shop"]


def test_dev_url_follows_the_model_ac_113_11(svc, monkeypatch):  # AC-113.11
    monkeypatch.setattr(smoke, "gh", GitopsApi(HIDDEN, SMOKE_APP))          # the files expose nothing
    exposed = [{"name": "shop-api", "repo": "acme/shop-api", "expose": True, "environments": ["dev"]}]
    alt_model(monkeypatch, "load_remote", exposed, {"hosts": {"dev": "{service}.alt.example.com"}})
    assert smoke.dev_url(svc, [GITOPS], "shop-api") == ("https://shop-api.alt.example.com", None)


def test_the_staging_url_and_its_reasons_ac_113_11(svc, monkeypatch):  # AC-113.11
    both = EXPOSED.replace("[dev]", "[dev, staging]")
    app = SMOKE_APP + '  staging: "{service}.staging.example.com"\nurls:\n  staging: "https://{host}/x"\n'
    monkeypatch.setattr(smoke, "gh", GitopsApi(both, app))
    calls = spy(monkeypatch, "load_remote")
    assert smoke.dev_url(svc, [GITOPS], "shop-api", env="staging") == ("https://shop-api.staging.example.com/x", None)
    monkeypatch.setattr(smoke, "gh", GitopsApi(EXPOSED, app))                 # not in staging
    assert smoke.dev_url(svc, [GITOPS], "shop-api", env="staging") == (None, "shop-api has no staging URL (not exposed in staging)")
    monkeypatch.setattr(smoke, "gh", GitopsApi(both, SMOKE_APP))              # no staging host
    assert smoke.dev_url(svc, [GITOPS], "shop-api", env="staging") == (None, "shop-api has no staging URL (not exposed in staging)")
    assert len(calls) == 3


def test_a_gitops_app_that_cannot_be_read_gives_the_same_reasons_ac_113_10(svc, monkeypatch):  # AC-113.10
    spy(monkeypatch, "load_remote")

    def broken(args, *, cwd=None, check=True):
        raise core.PlatformError("gh: HTTP 404")
    monkeypatch.setattr(smoke, "gh", broken)
    assert smoke.dev_url(svc, [GITOPS], "shop-api") == (None, f"shop-api has no dev URL (could not read the gitops-app {GITOPS})")
    other = "services:\n  - name: other\n    repo: acme/other\n    shape: service-python\n    port: 8080\n"
    monkeypatch.setattr(smoke, "gh", GitopsApi(other, SMOKE_APP))
    assert smoke.dev_url(svc, [GITOPS], "shop-api") == (None, "shop-api has no dev URL (not in the linked gitops-app)")


def test_the_service_is_found_by_its_repo_first_ac_113_10(svc, monkeypatch):  # AC-113.10
    two = ("services:\n  - name: shop-api\n    repo: acme/else\n    shape: service-python\n    port: 8080\n"
           "  - name: renamed\n    repo: acme/shop-api\n    shape: service-python\n    port: 8080\n    expose: true\n    environments: [dev]\n")
    monkeypatch.setattr(smoke, "gh", GitopsApi(two, SMOKE_APP))
    spy(monkeypatch, "load_remote")
    monkeypatch.delenv("LOCAL_HTTP_PORT", raising=False)
    assert smoke.dev_url(svc, [GITOPS], "shop-api") == ("http://renamed.shop-dev.localhost:8088", None)


# ======================================================================================
# the staging promotion decision of `cplat ship deploy` (AC-113.11)
# ======================================================================================

TAG = "sha-" + SHA
OLD = "sha-" + "d" * 40
STAGING_APP = 'hosts:\n  dev: "{service}.{app}-dev.localhost"\n'
STAGING_SERVICES = ("services:\n  - name: shop-api\n    repo: acme/shop-api\n    image: ghcr.io/acme/shop-api\n    shape: service-python\n"
                    "    port: 8080\n    expose: true\n    environments: [dev, staging]\n{promotion}")


class StagingGh:
    def __init__(self, services, app=STAGING_APP, old=OLD):
        self.files = {"applications/shop/services.yaml": services, "applications/shop/app.yaml": app,
                      ".github/workflows/pin-staging.yml": "name: pin-staging\n"}
        if old:
            self.files["applications/shop/overlays/staging/shop-api/kustomization.yaml"] = yaml.safe_dump({"images": [{"name": "i", "newTag": old}]})
        self.calls = []

    def __call__(self, args, *, cwd=None, check=False):
        self.calls.append(args)
        path = args[1]
        if "/compare/" in path:
            return "behind\n"
        if path.endswith("/contents/applications"):
            return json.dumps([{"name": "shop", "type": "dir"}])
        rel = path.split("/contents/", 1)[1]
        if rel in self.files:
            return self.files[rel]
        raise core.PlatformError("404")


@pytest.fixture()
def shop_repo(tmp_path):
    r = tmp_path / "shop-api"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    git(r, "remote", "add", "origin", "https://github.com/acme/shop-api.git")
    return r


def decide(shop_repo, monkeypatch, services, app=STAGING_APP, old=OLD):
    monkeypatch.setattr(staging, "gh", StagingGh(services, app, old))
    dev = smoke.SmokeResult(env="dev", outcome="passed", base_url=None, reason=None, passed=2)
    return staging.decide(shop_repo, {"deployed": TAG}, [GITOPS], "shop-api", dev)


def test_auto_promotion_reads_its_answers_from_the_model_ac_113_11(shop_repo, monkeypatch):  # AC-113.11
    calls = spy(monkeypatch, "load_remote")
    d = decide(shop_repo, monkeypatch, STAGING_SERVICES.format(promotion="    promotion: {staging: auto}\n"))
    assert (d.action, d.reason, d.service, d.tag, d.previous, d.app, d.app_dir, d.workflow) == (
        "promote", None, "shop-api", TAG, OLD, GITOPS, "applications/shop", True)
    assert [c[0][0] for c in calls] == ["shop"]


def test_the_components_promotion_beats_the_apps_ac_113_11(shop_repo, monkeypatch):  # AC-113.11
    spy(monkeypatch, "load_remote")
    manual = decide(shop_repo, monkeypatch, STAGING_SERVICES.format(promotion="    promotion: {staging: manual}\n"), STAGING_APP + "promotion: {staging: auto}\n")
    assert (manual.action, manual.reason) == ("skip", "automatic promotion to staging is off for shop-api")
    auto = decide(shop_repo, monkeypatch, STAGING_SERVICES.format(promotion="    promotion: {staging: auto}\n"))
    assert auto.action == "promote"
    app_auto = decide(shop_repo, monkeypatch, STAGING_SERVICES.format(promotion=""), STAGING_APP + "promotion: {staging: auto}\n")
    assert app_auto.action == "promote"
    default = decide(shop_repo, monkeypatch, STAGING_SERVICES.format(promotion=""))
    assert default.reason == "automatic promotion to staging is off for shop-api"


def test_a_component_that_is_not_in_staging_yet_skips_ac_113_11(shop_repo, monkeypatch):  # AC-113.11
    spy(monkeypatch, "load_remote")
    d = decide(shop_repo, monkeypatch, STAGING_SERVICES.format(promotion="    promotion: {staging: auto}\n").replace("[dev, staging]", "[dev]"))
    assert d.reason == "shop-api is not in staging yet: the first promotion is manual: /gitops:promote shop-api dev staging"


def test_the_decision_follows_the_model_for_the_rule_and_the_staging_pin_ac_113_11(shop_repo, monkeypatch):  # AC-113.11
    files_say_manual = STAGING_SERVICES.format(promotion="")
    auto = [{"name": "shop-api", "repo": "acme/shop-api", "image": "ghcr.io/acme/shop-api", "environments": ["dev", "staging"]}]
    other = "sha-" + "f" * 40
    alt_model(monkeypatch, "load_remote", auto, {"promotion": {"staging": "auto"}}, pins=lambda env, c: other if env == "staging" else None)
    d = decide(shop_repo, monkeypatch, files_say_manual)
    assert (d.action, d.previous) == ("promote", other)


def test_find_hands_staging_deploy_the_component_ac_113_11(shop_repo, monkeypatch):  # AC-113.11
    monkeypatch.setattr(staging, "gh", StagingGh(STAGING_SERVICES.format(promotion="")))
    found = staging._find(shop_repo, [GITOPS], "shop-api")
    assert found[0] == GITOPS and found[1] == "applications/shop" and found[4] == "acme/shop-api"
    assert (found[2].name, found[2].image) == ("shop-api", "ghcr.io/acme/shop-api")
    assert staging._find(shop_repo, [GITOPS], "nobody") is None


# ======================================================================================
# the alert poll (AC-113.11)
# ======================================================================================

def test_the_polled_environments_and_service_down_come_from_the_model_ac_113_11(tmp_path, monkeypatch):  # AC-113.11
    import alertsources
    calls = spy(monkeypatch, "build")
    cfg = alertsources.load_app(make_app(tmp_path, addon={"ui": "lgtm"}))
    assert cfg.envs == ["dev", "prod"] and cfg.skip is None
    down = [(r.service, r.environment) for r in cfg.rules if r.name == "ServiceDown"]
    assert down == [("shop-api", "dev"), ("shop-api", "prod")]
    assert len(calls) == 1 and calls[0][0][0] == ALERT_APP
    assert cfg.model is not None and cfg.model.system == ALERT_APP
    assert {(i.component, i.environment) for i in cfg.model.instances} == {
        ("shop-api", "dev"), ("shop-api", "prod"), ("shop-web", "dev"), ("shop-batch", "dev")}


def test_the_alert_poll_follows_the_model_ac_113_11(tmp_path, monkeypatch):  # AC-113.11
    import alertsources
    only_staging = [{"name": "shop-api", "repo": "acme/shop-api", "metrics": "/metrics", "environments": ["dev", "staging"]}]
    alt_model(monkeypatch, "build", only_staging, {"addons": {"observability": {"ui": "lgtm"}}})
    cfg = alertsources.load_app(make_app(tmp_path, addon={"ui": "lgtm"}))
    assert cfg.envs == ["dev", "staging"]
    assert [(r.service, r.environment) for r in cfg.rules if r.name == "ServiceDown"] == [("shop-api", "dev"), ("shop-api", "staging")]


def test_an_unreadable_file_still_skips_instead_of_failing_ac_113_11(tmp_path, monkeypatch):  # AC-113.11
    import alertsources
    calls = spy(monkeypatch, "build")
    d = make_app(tmp_path, addon={"ui": "lgtm"})
    (d / "services.yaml").write_text("services: [unclosed\n")
    cfg = alertsources.load_app(d)
    assert cfg.skip == "no service runs in any environment" and cfg.envs == [] and len(calls) == 1
    assert alertsources.AppConfig(app="x", app_dir=d, services=[], envs=[], rules=[], prometheus_url=None, alertmanager_url=None,
                                  query_secret=None, skip=None).model is None


@pytest.mark.parametrize("labels, env", [
    ({"environment": "staging"}, "staging"), ({"env": "prod"}, "prod"), ({"namespace": "shop-prod"}, "prod"),
    ({"instance": "shop-api.shop-staging.svc:9090"}, "staging"), ({"namespace": "shop-qa"}, "unknown"), ({}, "unknown"),
])
def test_a_series_maps_to_its_environment_ac_113_11(tmp_path, monkeypatch, labels, env):  # AC-113.11
    import alertsources
    spy(monkeypatch, "build")
    cfg = alertsources.load_app(make_app(tmp_path, addon={"ui": "lgtm"}))
    got, notes = alertsources._env_of(cfg, labels)
    assert got == env and (notes == [] if env != "unknown" else len(notes) == 1)
    assert not hasattr(alertsources, "ENVS")


# ======================================================================================
# secret (AC-113.18)
# ======================================================================================

SECRET_SERVICES = [
    {"name": "shop-api", "repo": "acme/shop-api", "image": "ghcr.io/acme/shop-api", "shape": "service-python",
     "secrets": [{"name": "api-keys", "remote": {"keys": ["STRIPE_KEY", "HOOK_KEY"]}},
                 {"name": "api-pay", "remote": {"keys": ["PAY_KEY"], "path": "pay-{env}-{app}-{secret}"}},
                 {"name": "api-auth", "generate": ["DB_PASSWORD", "JWT_KEY"]}]},
    {"name": "plain", "repo": "acme/plain", "image": "ghcr.io/acme/plain", "shape": "service-python"},
]


class Kubectl:
    def __init__(self, secrets=None):
        self.secrets = secrets or {}
        self.calls = []

    def __call__(self, args, input_text=None):
        self.calls.append(args)
        if "get" in args:
            name = args[args.index("secret") + 1]
            if name not in self.secrets:
                raise core.PlatformError("NotFound")
            return json.dumps({"data": {k: base64.b64encode(v.encode()).decode() for k, v in self.secrets[name].items()}})
        if "create" in args:
            self.secrets.setdefault(args[-1], {})
            return ""
        if "patch" in args:
            self.secrets[args[args.index("secret") + 1]].update(json.loads(input_text)["stringData"])
            return ""
        raise AssertionError(args)


@pytest.fixture()
def secret_repo(tmp_path):
    write_app(tmp_path, SECRET_SERVICES, {})
    return tmp_path


def test_secret_list_resolves_store_keys_through_the_model_ac_113_18(secret_repo, monkeypatch, capsys):  # AC-113.18
    calls = spy(monkeypatch, "load_dir")
    k = Kubectl({"shop-staging-api-keys": {"STRIPE_KEY": "x"}})
    monkeypatch.setattr(secret, "kubectl", k)
    assert secret.main(["list", "--env", "staging", "--repo-dir", str(secret_repo)]) == 0
    out = capsys.readouterr().out
    assert "shop-api/api-keys.STRIPE_KEY: set" in out
    assert "shop-api/api-keys.HOOK_KEY: MISSING → cplat secret set shop-api api-keys HOOK_KEY --env staging" in out
    assert "shop-api/api-pay.PAY_KEY: MISSING → cplat secret set shop-api api-pay PAY_KEY --env staging" in out
    assert "shop-api/api-auth: generated by External Secrets Operator (DB_PASSWORD, JWT_KEY)" in out
    assert out.index("api-keys.STRIPE_KEY") < out.index("api-pay.PAY_KEY") < out.index("api-auth")
    got = [a[a.index("secret") + 1] for a in k.calls]
    assert got == ["shop-staging-api-keys", "pay-staging-shop-api-pay"]
    assert len(calls) == 1 and calls[0][0][0].name == "shop"


def test_secret_set_writes_to_the_resolved_store_key_ac_113_18(secret_repo, monkeypatch, capsys):  # AC-113.18
    spy(monkeypatch, "load_dir")
    k = Kubectl()
    monkeypatch.setattr(secret, "kubectl", k)
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("sk_test_1\n"))
    argv = ["--repo-dir", str(secret_repo), "--env", "staging"]
    assert secret.main(["set", "shop-api", "api-pay", "PAY_KEY", "--value-stdin", *argv]) == 0
    assert k.secrets == {"pay-staging-shop-api-pay": {"PAY_KEY": "sk_test_1"}}
    out = capsys.readouterr().out
    assert "stored in secrets-store/pay-staging-shop-api-pay" in out and "sk_test_1" not in out


@pytest.mark.parametrize("argv, message", [
    (["set", "shop-api", "nope", "K", "--value-stdin"], "shop-api has no secret 'nope'"),
    (["set", "shop-api", "api-auth", "DB_PASSWORD", "--value-stdin"], "'api-auth' is generated by External Secrets Operator; there is nothing to set"),
    (["set", "shop-api", "api-keys", "NOPE", "--value-stdin"], "'NOPE' is not a key of 'api-keys'"),
])
def test_secret_errors_keep_their_messages_ac_113_18(secret_repo, monkeypatch, argv, message):  # AC-113.18
    spy(monkeypatch, "load_dir")
    monkeypatch.setattr(secret, "kubectl", Kubectl())
    with pytest.raises(core.PlatformError, match=message) as e:
        secret.main([*argv, "--repo-dir", str(secret_repo)])
    if "has no secret" in message:
        assert e.value.hint == "declared: shop-api/api-keys, shop-api/api-pay, shop-api/api-auth"


def test_secret_list_without_secrets_says_so_ac_113_18(tmp_path, monkeypatch, capsys):  # AC-113.18
    write_app(tmp_path, SECRET_SERVICES[1:], {})
    spy(monkeypatch, "load_dir")
    assert secret.main(["list", "--repo-dir", str(tmp_path)]) == 0
    assert "no `secrets:` declared" in capsys.readouterr().out


def test_secret_follows_the_model_ac_113_18(secret_repo, monkeypatch, capsys):  # AC-113.18
    only = [{"name": "ledger", "repo": "acme/ledger", "secrets": [{"name": "led", "remote": {"keys": ["K"], "path": "led-{env}"}}]}]
    alt_model(monkeypatch, "load_dir", only, {})
    k = Kubectl()
    monkeypatch.setattr(secret, "kubectl", k)
    assert secret.main(["list", "--repo-dir", str(secret_repo)]) == 0
    out = capsys.readouterr().out
    assert "ledger/led.K: MISSING" in out and "shop-api" not in out and "led-dev" in " ".join(k.calls[0])


# ======================================================================================
# the app-ship gate class (AC-113.18)
# ======================================================================================

def gate(monkeypatch, services, app, repo=None):
    import appship_sched
    docs = {"applications/shop/services.yaml": {"services": services}, "applications/shop/app.yaml": app}
    monkeypatch.setattr(appship_sched, "run", lambda cmd, **k: SimpleNamespace(stdout="applications/shop\n" if cmd[:2] == ["git", "ls-tree"] else "", returncode=0))
    monkeypatch.setattr(appship_sched, "_show", lambda gitops_dir, path: copy.deepcopy(docs.get(path, {})))
    return appship_sched.gate_class(Path("/gitops"), repo or {"id": "shop-api", "shape": "service-python"})


HOSTS = {"hosts": {"dev": "{service}.{app}-dev.localhost"}}
ENTRY = {"name": "shop-api", "repo": "acme/shop-api"}


@pytest.mark.parametrize("entry, app, expected", [
    ({**ENTRY, "expose": True}, HOSTS, "exposed"),
    ({**ENTRY, "expose": {"host": "api"}, "environments": ["dev", "staging"]}, HOSTS, "exposed"),
    ({**ENTRY, "expose": True}, {}, "internal"),                                   # no dev host
    ({**ENTRY, "expose": True, "environments": ["staging"]}, HOSTS, "internal"),   # not in dev
    ({**ENTRY}, HOSTS, "internal"),                                                # no expose
    ({"name": "other", "repo": "acme/other", "expose": True}, HOSTS, "internal"),  # not in the gitops-app
])
def test_exposed_in_dev_comes_from_the_dev_instance_ac_113_18(monkeypatch, entry, app, expected):  # AC-113.18
    calls = spy(monkeypatch, "build")
    assert gate(monkeypatch, [entry], app) == expected
    assert len(calls) == (0 if entry["name"] == "other" else 1)
    assert not calls or calls[0][0][0] == "shop"


def test_the_gate_class_follows_the_model_ac_113_18(monkeypatch):  # AC-113.18
    exposed = [{**ENTRY, "expose": True}]
    alt_model(monkeypatch, "build", exposed, HOSTS)
    assert gate(monkeypatch, [{**ENTRY}], {}) == "exposed"           # the files say internal


def test_entry_and_library_gate_classes_do_not_need_the_model_ac_113_18(monkeypatch):  # AC-113.18
    assert gate(monkeypatch, [], {}, {"id": "shop-gitops", "shape": "gitops-app"}) == "entry"
    assert gate(monkeypatch, [], {}, {"id": "shop-lib", "shape": "library-python"}) == "library"
    assert model().ENVIRONMENTS
