"""Spec 114 acceptance tests: `cplat` grouped by noun and the commands that read system.yaml
(AC-114.6, .8, .10, .23, .26, .28 .. .32, .38, .39, .60, .61).

Contract: design.md "Contract — cplat", "cplat system status", "cplat api list", "cplat platform doctor", "Alert poll per
environment". Dispatch is tested with stub modules in sys.modules (a moved name must not import its module); the commands run on
hand-built checkouts with their existing seams faked, as in spec 113's tests."""
import json
import subprocess
import sys
import types
from urllib.parse import urlsplit

import pytest
import yaml

import core
import cplat
from alerts_fakes import NOW, FakeNet
from system_fixtures import (FULL5, NOT_MIGRATED, PINS, ROOT, SHA, component, git, init_git, mod, rich5, tiny, write_old, write_system)

# ---------------- AC-114.26 / AC-114.60: the dispatcher ----------------

MOVED = {"new-app": "system new", "status": "system status", "app-ship": "system ship", "new-service": "component new",
         "compose": "component add|set|remove", "ship": "component ship", "build": "component build", "addon": "resource add|remove",
         "promote": "instance promote", "secret": "instance secret", "smoke": "instance verify", "triage": "issue triage",
         "doctor": "platform doctor", "update-service": "platform update", "fleet": "platform fleet", "runs": "platform runs",
         "retro": "platform retro"}
MODULE_OF_OLD = {"new-app": "newapp", "status": "status", "app-ship": "appship", "new-service": "newsvc", "compose": "compose", "ship": "ship",
                 "build": "buildcmd", "addon": "addon", "promote": "promote", "secret": "secret", "smoke": "smoke", "triage": "triage",
                 "doctor": "doctor", "update-service": "update", "fleet": "fleet", "runs": "runs", "retro": "retro"}


def stubs(monkeypatch):
    calls = []
    for name in set(MODULE_OF_OLD.values()) | {"apilist", "spec", "pr", "headless", "budget", "quiet", "validate", "deps", "shapecmd",
                                               "feedback", "adopt", "alerts", "modelcmd"}:
        m = types.ModuleType(name)
        m.main = lambda argv, name=name: calls.append((name, list(argv))) or 0
        monkeypatch.setitem(sys.modules, name, m)
    return calls


@pytest.mark.parametrize("old, new", sorted(MOVED.items()))
def test_a_4x_name_exits_2_with_one_line_naming_the_new_form_ac_114_26(monkeypatch, capsys, old, new):  # AC-114.26
    calls = stubs(monkeypatch)
    assert cplat.main([old, "anything"]) == 2
    cap = capsys.readouterr()
    assert cap.err.strip() == f"`cplat {old}` is `cplat {new}` in 5.0" and cap.out == ""
    assert calls == []


def test_promote_is_instance_promote_in_the_spec_example_ac_114_26(monkeypatch, capsys):  # AC-114.26
    stubs(monkeypatch)
    assert cplat.main(["promote", "x", "dev", "staging"]) == 2
    assert capsys.readouterr().err.strip() == "`cplat promote` is `cplat instance promote` in 5.0"


NOUN_ROUTES = [
    (["system", "new", "m.yml", "--no-github"], "newapp", ["m.yml", "--no-github"]),
    (["system", "status", "--json"], "status", ["--json"]),
    (["system", "ship", "start", "p.md"], "appship", ["start", "p.md"]),
    (["component", "new", "api", "desc"], "newsvc", ["api", "desc"]),
    (["component", "add", "api", "--pr"], "compose", ["add", "api", "--pr"]),
    (["component", "set", "api", "--replicas", "2"], "compose", ["set", "api", "--replicas", "2"]),
    (["component", "remove", "api"], "compose", ["remove", "api"]),
    (["component", "ship", "gate"], "ship", ["gate"]),
    (["component", "build", "schedule"], "buildcmd", ["schedule"]),
    (["api", "list", "--json"], "apilist", ["--json"]),
    (["resource", "add", "postgres"], "addon", ["add", "postgres"]),
    (["resource", "remove", "postgres"], "addon", ["remove", "postgres"]),
    (["instance", "promote", "api", "--to", "staging"], "promote", ["api", "--to", "staging"]),
    (["instance", "secret", "set", "api/dev", "s", "K"], "secret", ["set", "api/dev", "s", "K"]),
    (["instance", "verify", "staging", "--base-url", "http://x"], "smoke", ["run", "staging", "--base-url", "http://x"]),
    (["instance", "verify"], "smoke", ["run"]),
    (["issue", "triage", "list"], "triage", ["list"]),
    (["platform", "doctor", "--json"], "doctor", ["--json"]),
    (["platform", "update", "--migrate"], "update", ["--migrate"]),
    (["platform", "fleet", "update", "--dry-run"], "fleet", ["update", "--dry-run"]),
    (["platform", "runs", "report"], "runs", ["report"]),
    (["platform", "retro", "--week", "W"], "retro", ["--week", "W"]),
]


@pytest.mark.parametrize("argv, module, rest", NOUN_ROUTES, ids=[" ".join(r[0][:2]) for r in NOUN_ROUTES])
def test_noun_verb_runs_the_module_of_the_4x_command_ac_114_60(monkeypatch, argv, module, rest):  # AC-114.60
    calls = stubs(monkeypatch)
    assert cplat.main(argv) == 0
    assert calls == [(module, rest)]


@pytest.mark.parametrize("name, module", [("spec", "spec"), ("pr", "pr"), ("headless", "headless"), ("budget", "budget"), ("quiet", "quiet"),
                                          ("validate", "validate"), ("deps", "deps"), ("shape", "shapecmd"), ("feedback", "feedback"),
                                          ("adopt", "adopt"), ("alerts", "alerts"), ("model", "modelcmd")])
def test_plumbing_commands_keep_their_names_ac_114_60(monkeypatch, name, module):  # AC-114.60
    calls = stubs(monkeypatch)
    assert cplat.main([name, "x", "--y"]) == 0
    assert cplat.main(["component", "ship", "gate"]) == 0          # the nouns exist next to the plumbing
    assert calls == [(module, ["x", "--y"]), ("ship", ["gate"])]


@pytest.mark.parametrize("argv, verbs", [(["component"], "new add set remove ship build"), (["instance", "nope"], "promote secret verify"),
                                         (["resource", "list"], "add remove"), (["api", "check"], "list"),
                                         (["platform"], "doctor update fleet runs retro")])
def test_a_noun_without_a_known_verb_prints_its_verbs_and_exits_2_ac_114_60(monkeypatch, capsys, argv, verbs):  # AC-114.60
    calls = stubs(monkeypatch)
    assert cplat.main(argv) == 2 and calls == []
    cap = capsys.readouterr()
    text = cap.out + cap.err
    assert len(text.splitlines()) <= 12, "only the noun's verbs are printed, not the whole usage"
    assert f"cplat {argv[0]}" in text
    for v in verbs.split():
        assert v in text, v


def test_help_lists_every_noun_line_ac_114_60(capsys):  # AC-114.60
    assert cplat.main(["--help"]) == 0
    out = capsys.readouterr().out
    for line in ("cplat system new", "cplat system status", "cplat system ship", "cplat component new", "cplat component add", "cplat component ship",
                 "cplat component build", "cplat api list", "cplat resource add", "cplat instance promote", "cplat instance secret",
                 "cplat instance verify", "cplat issue triage", "cplat platform doctor", "cplat platform update", "cplat platform fleet",
                 "cplat platform runs", "cplat platform retro"):
        assert line in out, line
    assert "new-service" not in out and "app-ship" not in out


# ---------------- AC-114.61: api list ----------------

def api_list(tmp_path, capsys, *args):
    rc = cplat.main(["api", "list", "--repo-dir", str(tmp_path), *args])
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def test_api_list_prints_type_provider_and_consumers_ac_114_61(tmp_path, capsys):  # AC-114.61
    doc = rich5()
    doc["apis"]["events-bus"] = {"type": "events"}
    component(doc, "shop-web")["provides"] = ["events-bus"]
    write_system(tmp_path, doc)
    rc, out, err = api_list(tmp_path, capsys)
    assert rc == 0 and err == ""
    assert out.splitlines() == ["shop-api-rest  type openapi  provider shop-api  consumers shop-web",
                                "events-bus  type events  provider shop-web  consumers -"]


def test_api_list_json_ac_114_61(tmp_path, capsys):  # AC-114.61
    write_system(tmp_path, rich5())
    rc, out, _ = api_list(tmp_path, capsys, "--json")
    assert rc == 0
    assert json.loads(out) == {"system": "shop", "apis": [{"name": "shop-api-rest", "type": "openapi", "provider": "shop-api", "consumers": ["shop-web"]}]}


def test_api_list_without_apis_says_so_and_exits_0_ac_114_61(tmp_path, capsys):  # AC-114.61
    write_system(tmp_path, tiny())
    rc, out, _ = api_list(tmp_path, capsys)
    assert rc == 0 and out.strip() == "no APIs declared"


def test_api_list_in_an_unmigrated_repo_exits_1_ac_114_61(tmp_path, capsys):  # AC-114.61
    write_old(tmp_path)
    rc, out, err = api_list(tmp_path, capsys)
    assert rc == 1 and NOT_MIGRATED in err


# ---------------- AC-114.32: system status ----------------

ANSWERS = {
    ("gh", "run"): "completed success", ("gh", "api"): "platform: 5.0.0", ("git", "-C"): "https://github.com/acme/shop-gitops.git",
    ("gh", "pr"): json.dumps([{"number": 12, "headRefName": "pin/dev-shop-api-def5678"}]),
    ("kubectl", "--context"): json.dumps({"items": [
        {"metadata": {"name": "shop-api-dev"}, "status": {"sync": {"status": "Synced"}, "health": {"status": "Healthy"}}},
        {"metadata": {"name": "addon-postgres-dev"}, "status": {"sync": {"status": "Synced"}, "health": {"status": "Healthy"}}}]}),
}


@pytest.fixture()
def status_repo(tmp_path, monkeypatch):
    import status
    write_system(tmp_path, FULL5, pins={**PINS, ("dev", "shop-web"): "latest"})
    init_git(tmp_path)
    monkeypatch.setattr(status, "sh", lambda cmd: ANSWERS.get((cmd[0], cmd[1])))
    monkeypatch.setattr(core, "platform_version", lambda *a, **k: "5.0.0")
    return tmp_path


def test_system_status_is_a_component_by_environment_table_ac_114_32(status_repo, capsys):  # AC-114.32
    assert cplat.main(["system", "status", "--repo-dir", str(status_repo), "--context", "k3d-x"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("## shop (system) — platform 5.0.0 available")
    head = lines[2].split()
    assert head[:4] == ["component", "dev", "staging", "prod"] and head[-1] == "platform"
    api = next(ln for ln in lines if ln.strip().startswith("shop-api "))
    assert f"sha-{SHA[:7]} ci ok argo Synced/Healthy" in api and "pin PR #12 sha-def5678" in api
    assert "1.2.0 ci ok argo missing" in api
    web = next(ln for ln in lines if ln.strip().startswith("shop-web "))
    assert web.split()[-2] == "-"                                       # no prod instance
    res = [ln for ln in lines if ln.strip().startswith(("postgres ", "observability "))]
    assert len(res) == 2 and any("argo Synced/Healthy" in ln for ln in res)


def test_system_status_json_ac_114_32(status_repo, capsys):  # AC-114.32
    assert cplat.main(["system", "status", "--repo-dir", str(status_repo), "--context", "k3d-x", "--json"]) == 0
    d = json.loads(capsys.readouterr().out)
    assert d["system"] == "shop" and d["environments"] == ["dev", "staging", "prod"]
    rows = {r["component"]: r for r in d["rows"]}
    assert set(rows["shop-api"]["cells"]) == {"dev", "staging", "prod"} and rows["shop-web"]["cells"]["prod"] is None
    assert rows["shop-api"]["cells"]["dev"]["argo"] == "Synced/Healthy" and rows["shop-api"]["cells"]["dev"]["ci"] == "ok"
    assert {r["resource"] for r in d["resources"]} == {"postgres", "observability"}


def test_system_status_without_components_points_to_component_add_ac_114_32(tmp_path, monkeypatch, capsys):  # AC-114.32
    import status
    doc = tiny()
    doc["components"] = {}
    write_system(tmp_path, doc)
    init_git(tmp_path)
    monkeypatch.setattr(status, "sh", lambda cmd: None)
    assert cplat.main(["system", "status", "--repo-dir", str(tmp_path)]) == 0
    assert "(no components yet — /component:add <component>)" in capsys.readouterr().out


# ---------------- AC-114.30: instance secret ----------------

class Kubectl:
    def __init__(self, secrets=None):
        self.secrets, self.calls = secrets or {}, []

    def __call__(self, args, input_text=None):
        import base64
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
def secret_repo(tmp_path, monkeypatch):
    import secret
    write_system(tmp_path, rich5())
    k = Kubectl()
    monkeypatch.setattr(secret, "kubectl", k)
    return tmp_path, k


def test_instance_secret_set_writes_the_instances_store_key_ac_114_30(secret_repo, monkeypatch, capsys):  # AC-114.30
    repo, k = secret_repo
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("sk_1\n"))
    assert cplat.main(["instance", "secret", "set", "shop-api/prod", "api-pay", "PAY_KEY", "--value-stdin", "--repo-dir", str(repo)]) == 0
    assert k.secrets == {"prod/api-pay": {"PAY_KEY": "sk_1"}}                     # the prod instance overrides the path
    assert "sk_1" not in capsys.readouterr().out


def test_instance_secret_list_shows_each_instance_with_the_new_hint_ac_114_30(secret_repo, capsys):  # AC-114.30
    repo, k = secret_repo
    assert cplat.main(["instance", "secret", "list", "--env", "staging", "--repo-dir", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "shop-api/api-keys.STRIPE_KEY: MISSING → cplat instance secret set shop-api/staging api-keys STRIPE_KEY" in out
    assert "shop-api/api-auth: generated by External Secrets Operator (JWT_KEY)" in out
    assert [a[a.index("secret") + 1] for a in k.calls] == ["shop-api/staging/api-pay", "shop-staging-api-keys"] or \
        sorted(a[a.index("secret") + 1] for a in k.calls) == ["shop-api/staging/api-pay", "shop-staging-api-keys"]


@pytest.mark.parametrize("secret_name, key", [("nope", "K"), ("api-auth", "JWT_KEY")])
def test_instance_secret_set_refuses_undeclared_and_generated_secrets_ac_114_30(secret_repo, capsys, secret_name, key):  # AC-114.30
    repo, _ = secret_repo
    rc = cplat.main(["instance", "secret", "set", "shop-api/dev", secret_name, key, "--value-stdin", "--repo-dir", str(repo)])
    assert rc == 1
    assert f"shop-api has no remote secret '{secret_name}' (remote secrets: api-pay, api-keys)" in capsys.readouterr().err


# ---------------- AC-114.31 / AC-114.6: instance verify, dev url ----------------

def test_instance_verify_defaults_to_dev_and_resolves_any_environment_from_the_system_ac_114_31(tmp_path, monkeypatch):  # AC-114.31
    import ship
    import smoke
    seen = []
    monkeypatch.setattr(ship, "gitops_apps", lambda repo: ["acme/shop-gitops"])
    monkeypatch.setattr(ship, "service_name", lambda repo: "shop-api")
    monkeypatch.setattr(smoke, "dev_url", lambda repo, apps, svc, *, env="dev": seen.append(env) or (None, "no url in test"))
    (tmp_path / "svc").mkdir()
    assert smoke.main(["run", "--repo", str(tmp_path / "svc")]) == 3
    assert smoke.main(["run", "staging", "--repo", str(tmp_path / "svc")]) == 3       # 4.7 refused: --env staging needs --base-url
    assert seen == ["dev", "staging"]


def test_the_url_of_any_environment_comes_from_the_linked_system_ac_114_6(tmp_path, monkeypatch):  # AC-114.6
    import smoke
    write_system(tmp_path, FULL5)
    monkeypatch.setattr(smoke, "_slug", lambda repo: "acme/shop-api")
    monkeypatch.setattr(smoke, "_app_dirs", lambda slug, repo: ["shop"])
    monkeypatch.setattr(smoke, "_read", lambda slug, path, repo: yaml.safe_load((tmp_path / path).read_text()) if (tmp_path / path).is_file() else None)
    assert smoke.dev_url(tmp_path, ["acme/shop-gitops"], "shop-api", env="staging") == ("https://api.shop.example.com", None)
    assert smoke.dev_url(tmp_path, ["acme/shop-gitops"], "shop-api", env="dev") == ("http://api.shop-dev.localhost:8088", None)


def test_the_dev_url_in_an_unmigrated_gitops_app_fails_with_the_message_ac_114_23(tmp_path, monkeypatch):  # AC-114.23
    import smoke
    write_old(tmp_path)
    monkeypatch.setattr(smoke, "_slug", lambda repo: "acme/shop-api")
    monkeypatch.setattr(smoke, "_app_dirs", lambda slug, repo: ["shop"])
    monkeypatch.setattr(smoke, "_read", lambda slug, path, repo: yaml.safe_load((tmp_path / path).read_text()) if (tmp_path / path).is_file() else None)
    with pytest.raises(core.PlatformError, match="not migrated to 5.0"):
        smoke.dev_url(tmp_path, ["acme/shop-gitops"], "shop-api")


# ---------------- AC-114.8: staging promotion after the dev smoke ----------------

@pytest.mark.parametrize("env_promote, instance_promote, promotes", [
    ("after-dev-smoke", None, True), ("manual", None, False), (None, None, False),
    ("after-dev-smoke", "manual", False), ("manual", "after-dev-smoke", True)])
def test_staging_promotes_after_a_green_dev_smoke_per_the_promote_keys_ac_114_8(tmp_path, monkeypatch, env_promote, instance_promote, promotes):  # AC-114.8
    import staging
    doc = tiny(instances={"dev": {}, "staging": {} if not instance_promote else {"promote": instance_promote}})
    doc["components"]["api"]["repo"] = "acme/api"
    if env_promote:
        doc["environments"]["staging"]["promote"] = env_promote
    write_system(tmp_path, doc)
    monkeypatch.setattr(staging.smoke, "_slug", lambda repo: "acme/api")
    monkeypatch.setattr(staging, "_app_dirs", lambda slug, repo: ["shop"])
    monkeypatch.setattr(staging, "_read", lambda slug, path, repo: yaml.safe_load((tmp_path / path).read_text()) if (tmp_path / path).is_file() else None)
    monkeypatch.setattr(staging, "resolve", lambda *a, **k: None)
    monkeypatch.setattr(staging, "has_workflow", lambda *a, **k: True)
    dev = types.SimpleNamespace(outcome="green", reason=None)
    d = staging.decide(tmp_path, {"deployed": "sha-" + SHA}, ["acme/shop-gitops"], "api", dev)
    assert d.promote is promotes, d.reason
    if not promotes:
        assert "off" in d.reason


def test_a_component_without_a_staging_instance_is_told_the_first_promotion_is_manual_ac_114_8(tmp_path, monkeypatch):  # AC-114.8
    import staging
    doc = tiny()
    doc["environments"]["staging"]["promote"] = "after-dev-smoke"
    write_system(tmp_path, doc)
    monkeypatch.setattr(staging.smoke, "_slug", lambda repo: "acme/api")
    monkeypatch.setattr(staging, "_app_dirs", lambda slug, repo: ["shop"])
    monkeypatch.setattr(staging, "_read", lambda slug, path, repo: yaml.safe_load((tmp_path / path).read_text()) if (tmp_path / path).is_file() else None)
    d = staging.decide(tmp_path, {"deployed": "sha-" + SHA}, ["acme/shop-gitops"], "api", types.SimpleNamespace(outcome="green", reason=None))
    assert not d.promote and "/instance:promote api --to staging" in d.reason


# ---------------- AC-114.10: the alert poll per environment ----------------

def obs_system():
    doc = tiny(metrics="/metrics", instances={"dev": {}, "staging": {}, "prod": {}})
    rule = lambda n: {"name": n, "query": f"up == {n.lower()}", "severity": "warning"}
    doc["environments"]["dev"]["observability"] = {"ui": "lgtm", "rules": [rule("RDEV")]}
    doc["environments"]["staging"]["observability"] = {"queryURL": "http://q.example.com", "alertmanagerURL": "http://am.example.com", "rules": [rule("RSTG")]}
    doc["environments"]["prod"]["observability"] = {"ui": "lgtm", "alerts": False}
    return doc


@pytest.fixture()
def net(monkeypatch):
    import alertsources
    fake = FakeNet()
    monkeypatch.setattr(alertsources, "http_get", fake)
    monkeypatch.setattr(alertsources, "kubectl", lambda args, *, timeout=10.0: (1, "", "no kubectl in tests"))
    return fake


def test_each_environment_with_alerts_is_a_source_with_its_own_rules_and_endpoints_ac_114_10(tmp_path):  # AC-114.10
    import alertsources
    cfg = alertsources.load_app(write_system(tmp_path, obs_system()))
    assert cfg.skip is None
    assert [s.env for s in cfg.sources] == ["dev", "staging"]                       # prod: alerts: false
    dev, stg = cfg.sources
    assert {r.name for r in dev.rules} == {"RDEV", "ServiceDown"} and {r.name for r in stg.rules} == {"RSTG", "ServiceDown"}
    assert all(r.environment == "dev" for r in dev.rules if r.name == "ServiceDown")
    assert dev.prometheus_url and "lgtm" in dev.prometheus_url and dev.alertmanager_url is None
    assert stg.prometheus_url == "http://q.example.com" and stg.alertmanager_url == "http://am.example.com"


def test_collect_queries_each_source_with_its_own_rules_only_ac_114_10(tmp_path, net):  # AC-114.10
    import alertsources
    net.on(lambda q: "up == rdev" in q, [{"job": "api", "namespace": "shop-dev"}])
    net.on(lambda q: "up == rstg" in q, [{"job": "api", "namespace": "shop-staging"}])
    cfg = alertsources.load_app(write_system(tmp_path, obs_system()))
    alerts, errors = alertsources.collect(cfg, now=NOW)
    assert errors == []
    got = {(a.name, a.environment) for a in alerts}
    assert got == {("RDEV", "dev"), ("RSTG", "staging")}
    q = net.queries()
    assert any(urlsplit(u).hostname == "q.example.com" and "rstg" in u for u in q) and not any(urlsplit(u).hostname == "q.example.com" and "rdev" in u for u in q)
    assert any("lgtm" in u and "rdev" in u for u in q) and not any("lgtm" in u and "rstg" in u for u in q)


def test_no_environment_with_observability_skips_the_app_ac_114_10(tmp_path):  # AC-114.10
    import alertsources
    cfg = alertsources.load_app(write_system(tmp_path, tiny()))
    assert cfg.skip and "no environment declares observability" in cfg.skip and cfg.sources == []


def test_an_unmigrated_app_is_a_source_error_ac_114_23(tmp_path):  # AC-114.23
    import alertsources
    with pytest.raises(alertsources.SourceError) as e:
        alertsources.load_app(write_old(tmp_path))
    assert "not migrated to 5.0" in str(e.value)


# ---------------- AC-114.23: every command that read the old files refuses an unmigrated repo ----------------

@pytest.mark.parametrize("argv", [
    ["system", "status"], ["api", "list"], ["instance", "secret", "list"], ["instance", "promote", "shop-api", "--to", "staging", "--dry-run"],
    ["component", "add", "x", "--dry-run"], ["component", "set", "shop-api", "--replicas", "2", "--dry-run"], ["component", "remove", "shop-api", "--dry-run"],
    ["resource", "add", "postgres", "--dry-run"], ["resource", "remove", "postgres", "--dry-run"], ["model", "show"]])
def test_unmigrated_repos_exit_1_with_the_one_message_ac_114_23(tmp_path, capsys, argv):  # AC-114.23
    write_old(tmp_path)
    init_git(tmp_path)
    assert cplat.main([*argv, "--repo-dir", str(tmp_path)]) == 1
    assert NOT_MIGRATED in capsys.readouterr().err


# ---------------- AC-114.38: runs name /component:ship and /system:ship ----------------

OLD_NAMES = ("/svc:", "/app:", "/gitops:", "/shared:", "cplat ship ", "cplat app-ship", "cplat smoke", "cplat promote", "cplat compose", "cplat addon", "cplat build ")


@pytest.mark.parametrize("fname", ["ship.py", "appship.py", "appship_state.py", "appship_sched.py", "appship_report.py", "appship_merge.py", "budget.py"])
def test_the_run_modules_never_print_a_4x_command_ac_114_38(fname):  # AC-114.38
    text = (ROOT / "scripts" / "cplat" / fname).read_text()
    hits = [(i, n) for i, line in enumerate(text.splitlines(), 1) for n in OLD_NAMES if n in line]
    assert hits == [], f"{fname}: {hits[:5]}"


def test_the_stop_hooks_run_the_5_0_gates_ac_114_38():  # AC-114.38
    hooks = json.dumps(json.loads((ROOT / "plugins/shared/hooks/hooks.json").read_text()))
    assert "cplat\\\" component ship gate" in hooks or "bin/cplat\\\" component ship gate" in hooks
    assert "system ship gate" in hooks and " ship gate" in hooks and "app-ship gate" not in hooks and '\\" ship gate' not in hooks


# ---------------- AC-114.39: platform doctor ----------------

def doctor_checks(repo, monkeypatch, home):
    import doctor
    monkeypatch.setenv("HOME", str(home))
    return {c["name"]: c for c in doctor.run_checks(repo)}


def test_doctor_warns_while_the_old_plugins_are_enabled_ac_114_39(tmp_path, monkeypatch):  # AC-114.39
    repo = tmp_path / "r"
    (repo / ".claude").mkdir(parents=True)
    (repo / ".claude" / "settings.json").write_text(json.dumps({"enabledPlugins": {"app@sdlc-foundry": True, "gitops@sdlc-foundry": True, "svc@sdlc-foundry": True}}))
    checks = doctor_checks(repo, monkeypatch, tmp_path / "home")
    c = checks["plugins (4.x)"]
    assert c["status"] == "warn" and "app@sdlc-foundry" in c["detail"] and "gitops@sdlc-foundry" in c["detail"] and "tombstones" in c["detail"]
    assert c["fix"] == "cplat platform update --migrate"


def test_doctor_warns_while_the_old_files_exist_ac_114_39(tmp_path, monkeypatch):  # AC-114.39
    write_old(tmp_path / "r")
    checks = doctor_checks(tmp_path / "r", monkeypatch, tmp_path / "home")
    c = checks["system.yaml"]
    assert c["status"] == "warn" and "app.yaml" in c["detail"] and "services.yaml" in c["detail"] and c["fix"] == "cplat platform update --migrate"


def test_doctor_is_quiet_on_a_migrated_repo_ac_114_39(tmp_path, monkeypatch):  # AC-114.39
    repo = tmp_path / "r"
    write_system(repo, FULL5)
    (repo / ".claude").mkdir()
    (repo / ".claude" / "settings.json").write_text(json.dumps({"enabledPlugins": {"system@sdlc-foundry": True}}))
    checks = doctor_checks(repo, monkeypatch, tmp_path / "home")
    assert "plugins (4.x)" not in checks or checks["plugins (4.x)"]["status"] == "ok"
    assert "system.yaml" not in checks or checks["system.yaml"]["status"] == "ok"
    assert doctor_has_5_0_checks()


def doctor_has_5_0_checks():
    import doctor
    return "plugins (4.x)" in (ROOT / "scripts/cplat/doctor.py").read_text() and hasattr(doctor, "run_checks")
