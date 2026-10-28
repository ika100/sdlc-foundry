"""Spec 113 acceptance tests: the domain model core `scripts/cplat/model.py` (AC-113.1 .. AC-113.10).

Contract: design.md "Contract — model.py". The module does not exist before the feature, so it is imported inside the tests
(model_fixtures.model()): a missing module fails the test and never breaks collection. Files are built by hand
(model_fixtures.write_app), nothing renders, nothing reaches GitHub."""
import ast
import copy
import socket
import subprocess
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import yaml

import core
from model_fixtures import RICH_APP, RICH_SERVICES, SHA, model, reader, rich, small, system_doc, write_app

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def m(tmp_path):
    return model().load_dir(rich(tmp_path))


def names(items):
    return [i.name for i in items]


def build(services, app=None, *, system="shop", pins=None):
    return model().build(system_doc(services, app, system), system, pins=pins)


def entry(**kw):
    return {"name": "api", "repo": "acme/api", "image": "ghcr.io/acme/api", "shape": "service-python", **kw}


# ---------------- AC-113.1: the parts of a System ----------------

def test_one_system_one_component_per_entry_one_resource_per_addon_ac_113_1(tmp_path):  # AC-113.1
    m = model().load_dir(small(tmp_path))
    assert m.system == "shop"
    assert names(m.components) == ["shop-api", "stock"]
    assert names(m.resources) == ["postgres"]          # observability is never a Resource


def test_the_environments_are_dev_staging_prod_in_that_order_ac_113_1(m):  # AC-113.1
    assert names(m.environments) == ["dev", "staging", "prod"]
    assert [e.order for e in m.environments] == [0, 1, 2]
    assert tuple(model().ENVIRONMENTS) == ("dev", "staging", "prod")


def test_the_environment_order_equals_the_renderers_ac_113_1(m):  # AC-113.1
    tree = ast.parse((ROOT / "templates/gitops-app/scripts/render.py").read_text())
    renderer = next(ast.literal_eval(n.value) for n in tree.body
                    if isinstance(n, ast.Assign) and any(getattr(t, "id", None) == "ENVS" for t in n.targets))
    assert list(model().ENVIRONMENTS) == renderer == names(m.environments)


def test_every_component_and_resource_is_part_of_the_system_ac_113_1(m):  # AC-113.1
    rel = m.relations()
    for c in m.components:
        assert {"type": "part_of", "from": f"component:{c.name}", "to": "system:shop"} in rel
    assert {"type": "part_of", "from": "resource:postgres", "to": "system:shop"} in rel


def test_an_app_without_addons_or_services_is_an_empty_system_ac_113_1(tmp_path):  # AC-113.1
    m = model().load_dir(write_app(tmp_path, [], None))
    assert m.system == "shop" and list(m.components) == [] and list(m.resources) == [] and list(m.instances) == []
    assert names(m.environments) == ["dev", "staging", "prod"]


# ---------------- AC-113.2: a Component ----------------

@pytest.mark.parametrize("name, kind, lang, shape", [
    ("shop-api", "service", "python", "service-python"),
    ("shop-web", "website", "typescript", "web-nextjs"),
    ("ledger", "service", "java", "service-java"),
    ("batch", "service", "go", "service-go"),
    ("mystery", "service", "unknown", None),                 # 5.0: a shape the registry does not know is service/unknown
    ("plain", "service", "unknown", None),                   # no shape at all
])
def test_component_type_and_lang_come_from_the_shape_registry_ac_113_2(m, name, kind, lang, shape):  # AC-113.2
    c = m.component(name)
    entry_ = next(s for s in RICH_SERVICES if s["name"] == name)
    assert (c.type, c.lang, c.shape) == (kind, lang, shape)
    assert (c.name, c.repo, c.image) == (name, entry_["repo"], entry_["image"])


def test_an_external_entry_is_marked_with_its_package_kind_ac_113_2(m):  # AC-113.2
    stock, ops, api = m.component("stock"), m.component("ai-ops"), m.component("shop-api")
    assert (stock.external.kind, stock.external.namespace) == ("kustomize", "stock")
    assert (ops.external.kind, ops.external.namespace) == ("helm", None)
    assert api.external is None
    assert (stock.type, stock.lang) == ("service", "unknown")       # no shape


# ---------------- AC-113.3: Instances ----------------

def test_one_instance_per_listed_known_environment_ac_113_3(m):  # AC-113.3
    got = {(i.component, i.environment) for i in m.instances}
    assert got == {("shop-api", "dev"), ("shop-api", "staging"), ("shop-web", "dev"), ("shop-web", "staging"), ("shop-web", "prod"),
                   ("stock", "dev"), ("ai-ops", "dev"), ("ai-ops", "prod"), ("ledger", "dev"), ("batch", "dev"), ("mystery", "dev"),
                   ("plain", "dev")}
    assert m.instance("shop-api", "prod") is None


def test_instances_are_in_component_then_promotion_order_ac_113_3(m):  # AC-113.3
    order = [(i.component, i.environment) for i in m.instances]
    assert order[:5] == [("shop-api", "dev"), ("shop-api", "staging"), ("shop-web", "dev"), ("shop-web", "staging"), ("shop-web", "prod")]
    assert [i.environment for i in m.instances_of("shop-web")] == ["dev", "staging", "prod"]
    assert {i.component for i in m.instances_in("prod")} == {"shop-web", "ai-ops"}


def test_no_environments_key_or_an_empty_list_means_dev_ac_113_3(m):  # AC-113.3
    assert [i.environment for i in m.instances_of("ledger")] == ["dev"]
    assert [i.environment for i in m.instances_of("plain")] == ["dev"]
    assert m.component("ledger").environments == ("dev",)


def test_an_unknown_environment_creates_no_instance_but_a_warning_ac_113_3(m):  # AC-113.3
    assert [i.environment for i in m.instances_of("batch")] == ["dev"]
    assert m.component("batch").environments == ("dev",)
    assert list(m.warnings) == ["batch has instances in unknown environment 'qa': no Instance"]


@pytest.mark.parametrize("component, env, tag", [
    ("shop-api", "dev", "sha-" + SHA), ("shop-api", "staging", None),       # no overlay
    ("shop-web", "dev", "latest"), ("shop-web", "staging", None),           # overlay without newTag
    ("shop-web", "prod", "1.2.0"), ("ai-ops", "prod", None),
])
def test_the_pinned_tag_is_read_from_the_overlay_ac_113_3(m, component, env, tag):  # AC-113.3
    assert m.instance(component, env).tag == tag


@pytest.mark.parametrize("component, env, replicas", [
    ("shop-api", "dev", 1), ("shop-api", "staging", 2),        # per-environment map
    ("shop-web", "dev", 3), ("shop-web", "prod", 3),           # a single integer
    ("ledger", "dev", 1),                                      # default
    ("stock", "dev", None), ("ai-ops", "prod", None),          # external: the package sets them
])
def test_replicas_namespace_and_argo_application_ac_113_3(m, component, env, replicas):  # AC-113.3
    i = m.instance(component, env)
    assert i.replicas == replicas
    assert i.argo_application == f"{component}-{env}"
    ext = m.component(component).external
    assert i.namespace == ((ext.namespace if ext and ext.namespace else None) or f"shop-{env}")
    assert i.image == m.component(component).image


def test_a_per_environment_replica_map_defaults_missing_environments_to_one_ac_113_3():  # AC-113.3
    m = build([entry(environments=["dev", "staging", "prod"], replicas={"prod": 4})])
    assert [m.instance("api", e).replicas for e in ("dev", "staging", "prod")] == [1, 1, 4]


# ---------------- AC-113.4: Environment rules ----------------

def test_hosts_urls_policy_and_promotion_per_environment_ac_113_4(m):  # AC-113.4
    dev, staging, prod = (m.environment(n) for n in ("dev", "staging", "prod"))
    assert (dev.host, staging.host, prod.host) == ("{component}.{system}-dev.localhost", "{component}.staging.example.com", None)
    assert (dev.url_template, staging.url_template, prod.url_template) == (None, "https://{host}/{component}", None)
    assert (dev.policy, staging.policy, prod.policy) == ("audit", "off", "enforce")      # prod defaults to enforce
    assert (dev.promotion, staging.promotion, prod.promotion) == ("main", "after-dev-smoke", "manual")


def test_policies_absent_or_false_are_off_and_defaults_apply_when_on_ac_113_4():  # AC-113.4
    for app in (None, {}, {"policies": False}):
        assert [e.policy for e in build([entry()], app).environments] == ["off", "off", "off"]
    assert [e.policy for e in build([entry()], {"policies": {}}).environments] == ["audit", "audit", "enforce"]


def test_staging_promotion_defaults_to_manual_and_prod_is_always_manual_ac_113_4():  # AC-113.4
    for app, staging in ((None, "manual"), ({"promotion": {"staging": "auto"}}, "after-dev-smoke"), ({"promotion": {"staging": "manual"}}, "manual")):
        m = build([entry()], app)
        assert [e.promotion for e in m.environments] == ["main", staging, "manual"]


def test_observability_is_carried_as_declared_and_is_not_a_resource_ac_113_4(m):  # AC-113.4
    for env in m.environments:
        o = env.observability
        assert (o.ui, o.export_to, o.alerts, o.query_url, o.alertmanager_url) == (
            "lgtm", "https://otlp.example.com", False, "http://q.example.com", "http://am.example.com")
        assert list(o.rules) == RICH_APP["addons"]["observability"]["rules"]
    assert "observability" not in names(m.resources)
    assert all(r.resource != "observability" for r in m.resource_instances)


def test_observability_is_absent_when_not_declared_and_a_null_value_counts_as_declared_ac_113_4():  # AC-113.4
    assert all(e.observability is None for e in build([entry()], {"addons": {"postgres": {}}}).environments)
    declared = build([entry()], {"addons": {"observability": None}})
    assert all(e.observability is not None for e in declared.environments)
    assert declared.environments[0].observability.ui is None and names(declared.resources) == []


# ---------------- AC-113.5: an Instance's rules ----------------

def test_the_staging_promotion_of_an_instance_prefers_the_components_ac_113_5(m):  # AC-113.5
    assert m.instance("shop-api", "staging").staging_promotion == "manual"      # the entry's promotion.staging
    assert m.instance("shop-web", "staging").staging_promotion == "after-dev-smoke"        # the environment's
    assert m.staging_promotion(m.component("shop-api")) == "manual"
    assert m.staging_promotion(m.component("shop-web")) == "after-dev-smoke"


@pytest.mark.parametrize("component, env, url", [
    ("shop-api", "dev", "http://api.shop-dev.localhost:8088"),                  # expose.host, local fallback
    ("shop-api", "staging", "https://api.staging.example.com/shop-api"),        # url of staging with {host} and {component}
    ("shop-web", "dev", "http://shop-web.shop-dev.localhost:8088"),             # expose: true, the component name
    ("shop-web", "staging", "https://shop-web.staging.example.com/shop-web"),
])
def test_the_url_of_an_exposed_instance_ac_113_5(m, monkeypatch, component, env, url):  # AC-113.5
    monkeypatch.delenv("LOCAL_HTTP_PORT", raising=False)
    i = m.instance(component, env)
    assert i.url == url and i.exposed is True
    assert m.url(component, env) == (url, None)


@pytest.mark.parametrize("component, env", [
    ("stock", "dev"),            # no expose
    ("shop-web", "prod"),        # no host template for prod
    ("shop-api", "prod"),        # the component does not run in prod
])
def test_an_instance_that_is_not_exposed_has_no_url_and_says_why_ac_113_5(m, component, env):  # AC-113.5
    assert m.url(component, env) == (None, f"not exposed in {env}")
    i = m.instance(component, env)
    assert i is None or (i.url is None and i.exposed is False)


def test_the_local_url_follows_local_http_port_when_asked_ac_113_5(m, monkeypatch):  # AC-113.5
    monkeypatch.setenv("LOCAL_HTTP_PORT", "9090")
    assert m.instance("shop-api", "dev").url == "http://api.shop-dev.localhost:9090"
    monkeypatch.setenv("LOCAL_HTTP_PORT", "not-a-number")
    assert m.url("shop-api", "dev")[0] == "http://api.shop-dev.localhost:8088"


def test_a_real_host_gets_https_and_urls_wins_over_the_fallback_ac_113_5():  # AC-113.5
    app = {"hosts": {"dev": "{service}.dev.example.com"}}
    assert build([entry(expose=True)], app).url("api", "dev") == ("https://api.dev.example.com", None)
    app["urls"] = {"dev": "https://{host}/shop/{app}/{env}/{service}"}
    assert build([entry(expose=True)], app).url("api", "dev") == ("https://api.dev.example.com/shop/shop/dev/api", None)


def test_expose_without_a_host_template_is_not_exposed_ac_113_5():  # AC-113.5
    assert build([entry(expose=True)], {}).url("api", "dev") == (None, "not exposed in dev")
    assert build([entry(expose=True)], None).url("api", "dev") == (None, "not exposed in dev")


def test_the_default_local_port_is_8088_ac_113_5():  # AC-113.5
    assert model().DEFAULT_LOCAL_PORT == 8088


# ---------------- AC-113.6: secrets ----------------

def test_a_component_declares_its_secrets_and_references_ac_113_6(m):  # AC-113.6
    c = m.component("shop-api")
    assert [(s.name, s.kind, tuple(s.keys), s.path) for s in c.secrets] == [
        ("api-keys", "remote", ("STRIPE_KEY", "STRIPE_HOOK"), None),
        ("api-pay", "remote", ("PAY_KEY",), "{component}/{env}/{secret}"),
        ("api-auth", "generate", ("DB_PASSWORD", "JWT_KEY"), None)]
    assert tuple(c.secret_refs) == ("shared-config",)
    assert m.component("stock").secrets == ()


def test_an_instance_resolves_the_store_key_for_its_environment_ac_113_6(m):  # AC-113.6
    got = {s.name: (s.kind, tuple(s.keys), s.store_key) for s in m.instance("shop-api", "staging").secrets}
    assert got == {"api-keys": ("remote", ("STRIPE_KEY", "STRIPE_HOOK"), "shop-staging-api-keys"),
                   "api-pay": ("remote", ("PAY_KEY",), "shop-api/staging/api-pay"),
                   "api-auth": ("generate", ("DB_PASSWORD", "JWT_KEY"), None)}
    assert m.instance("shop-api", "dev").secrets[0].store_key == "shop-dev-api-keys"


def test_every_instances_secrets_equal_its_components_ac_113_6(m):  # AC-113.6
    c = m.component("shop-api")
    for i in m.instances_of("shop-api"):
        assert [(s.name, s.kind, tuple(s.keys)) for s in i.secrets] == [(s.name, s.kind, tuple(s.keys)) for s in c.secrets]


def test_the_store_key_of_an_environment_without_an_instance_follows_the_same_rule_ac_113_6(m):  # AC-113.6
    assert [s.store_key for s in m.secrets("shop-api", "prod")] == ["shop-prod-api-keys", "shop-api/prod/api-pay", None]


# ---------------- AC-113.7: Resources and Resource instances ----------------

def test_a_component_uses_the_resource_it_lists_ac_113_7(m):  # AC-113.7
    assert tuple(m.component("shop-api").uses) == ("postgres",)
    assert tuple(m.component("shop-web").uses) == ()
    assert {"type": "uses", "from": "component:shop-api", "to": "resource:postgres"} in m.relations()


def test_resource_instances_exist_where_a_using_component_has_an_instance_ac_113_7(m):  # AC-113.7
    ris = m.resource_instances_of("postgres")
    assert [r.environment for r in ris] == ["dev", "staging"]                 # shop-api runs in dev and staging, not in prod
    assert [r.argo_application for r in ris] == ["addon-postgres-dev", "addon-postgres-staging"]
    assert {r.secret for r in ris} == {"shop-postgres-app"}


def test_postgres_sizing_is_per_environment_with_defaults_ac_113_7(m):  # AC-113.7
    dev, staging = m.resource_instances_of("postgres")
    assert (dev.sizing["replicas"], str(dev.sizing["version"]), dev.sizing["storage"]) == (1, "17", "1Gi")
    assert (staging.sizing["replicas"], str(staging.sizing["version"]), staging.sizing["storage"]) == (1, "17", "1Gi")   # map without staging


def test_prod_sizing_comes_from_the_declared_maps_ac_113_7():  # AC-113.7
    m = build([entry(uses=["postgres"], environments=["dev", "prod"])], RICH_APP)
    prod = next(r for r in m.resource_instances_of("postgres") if r.environment == "prod")
    assert (prod.sizing["replicas"], prod.sizing["storage"]) == (3, "20Gi")


def test_a_single_value_sizing_applies_everywhere_ac_113_7():  # AC-113.7
    m = build([entry(uses=["postgres"], environments=["dev", "staging"])], {"addons": {"postgres": {"version": 16, "instances": 2, "storage": "5Gi"}}})
    for r in m.resource_instances_of("postgres"):
        assert (r.sizing["replicas"], str(r.sizing["version"]), r.sizing["storage"]) == (2, "16", "5Gi")


def test_a_declared_postgres_nobody_uses_has_no_resource_instance_ac_113_7():  # AC-113.7
    m = build([entry()], {"addons": {"postgres": {}}})
    assert names(m.resources) == ["postgres"] and list(m.resource_instances) == []
    assert m.resource_instances_of("postgres") == []


# ---------------- AC-113.8: relations ----------------

def test_every_instance_runs_in_exactly_one_environment_ac_113_8(m):  # AC-113.8
    rel = m.relations()
    for i in m.instances:
        ours = [r for r in rel if r["type"] == "runs_in" and r["from"] == f"instance:{i.component}/{i.environment}"]
        assert ours == [{"type": "runs_in", "from": f"instance:{i.component}/{i.environment}", "to": f"environment:{i.environment}"}]
        assert {"type": "instance_of", "from": f"instance:{i.component}/{i.environment}", "to": f"component:{i.component}"} in rel
    for r in m.resource_instances:
        assert {"type": "runs_in", "from": f"resource_instance:{r.resource}/{r.environment}", "to": f"environment:{r.environment}"} in rel
        assert {"type": "instance_of", "from": f"resource_instance:{r.resource}/{r.environment}", "to": f"resource:{r.resource}"} in rel


def test_staging_is_promoted_from_dev_and_prod_from_staging_ac_113_8(m):  # AC-113.8
    staging = m.promoted_from(m.instance("shop-web", "staging"))
    prod = m.promoted_from(m.instance("shop-web", "prod"))
    assert (staging.component, staging.environment) == ("shop-web", "dev")
    assert (prod.component, prod.environment) == ("shop-web", "staging")
    rel = m.relations()
    assert {"type": "promoted_from", "from": "instance:shop-web/staging", "to": "instance:shop-web/dev"} in rel
    assert {"type": "promoted_from", "from": "instance:shop-web/prod", "to": "instance:shop-web/staging"} in rel


def test_dev_has_no_promoted_from_ac_113_8(m):  # AC-113.8
    assert m.promoted_from(m.instance("shop-web", "dev")) is None


def test_only_the_directly_preceding_environment_counts_ac_113_8(m):  # AC-113.8
    # ai-ops runs in dev and prod, not in staging: its prod Instance has no promoted-from Instance
    assert m.promoted_from(m.instance("ai-ops", "prod")) is None
    assert not [r for r in m.relations() if r["type"] == "promoted_from" and r["from"] == "instance:ai-ops/prod"]


def test_environments_promote_to_the_next_one_ac_113_8(m):  # AC-113.8
    promotes = sorted((r for r in m.relations() if r["type"] == "promotes_to"), key=lambda r: r["from"])
    assert promotes == [{"type": "promotes_to", "from": "environment:dev", "to": "environment:staging"},
                        {"type": "promotes_to", "from": "environment:staging", "to": "environment:prod"}]


# ---------------- AC-113.9: only declared state ----------------

def test_the_loaders_make_no_subprocess_network_or_socket_call_ac_113_9(tmp_path, monkeypatch):  # AC-113.9
    d = rich(tmp_path)

    def refuse(*a, **k):
        raise AssertionError("the model made an outside call")
    for target, attr in ((subprocess, "run"), (subprocess, "Popen"), (subprocess, "check_output"), (urllib.request, "urlopen"),
                         (socket, "create_connection"), (core, "run")):
        monkeypatch.setattr(target, attr, refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    m = model().load_dir(d)
    m.to_dict()
    assert model().load_remote("shop", reader(tmp_path)).to_dict() == m.to_dict()


def test_model_py_imports_nothing_that_could_call_out_ac_113_9():  # AC-113.9
    src = ROOT / "scripts/cplat/model.py"
    assert src.is_file(), "scripts/cplat/model.py does not exist"
    tree = ast.parse(src.read_text())
    imported = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            imported |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            imported.add(n.module.split(".")[0])
    forbidden = {"subprocess", "urllib", "socket", "http", "requests", "httpx", "gitops", "status", "promote", "smoke", "staging",
                 "secret", "alertsources", "appship_sched", "compose", "evidence", "registry"}
    assert not (imported & forbidden), imported & forbidden


def test_observed_state_is_attached_per_run_and_never_part_of_the_model_ac_113_9(tmp_path):  # AC-113.9
    d = rich(tmp_path)
    a, b = model().load_dir(d), model().load_dir(d)
    inst = a.instance("shop-api", "dev")
    assert inst.observed == {}
    before = a.to_dict()
    inst.observed["argo"] = "Synced/Healthy"
    assert a.to_dict() == before                                   # never serialized
    assert a.instance("shop-api", "dev") == b.instance("shop-api", "dev")      # not compared
    assert model().load_dir(d).instance("shop-api", "dev").observed == {}      # a new load starts empty


def test_pins_are_read_lazily_and_at_most_once_ac_113_9():  # AC-113.9
    calls = []

    def pins(env, component):
        calls.append((env, component))
        return "t-" + env
    m = build([entry(environments=["dev", "staging"]), entry(name="web", repo="acme/web")], None, pins=pins)
    assert calls == []                                              # nothing read by building the model
    i = m.instance("api", "staging")
    assert i.tag == "t-staging" and i.tag == "t-staging"
    assert calls == [("staging", "api")]
    m.to_dict()                                                     # resolves every pin
    assert sorted(calls) == [("dev", "api"), ("dev", "web"), ("staging", "api")]


def test_build_without_a_pins_callback_pins_nothing_ac_113_9():  # AC-113.9
    assert all(i.tag is None for i in build([entry()]).instances)


# ---------------- pins: read and write (contract) ----------------

def test_pin_path_is_relative_to_the_app_dir_ac_113_3():  # AC-113.3
    assert model().pin_path("staging", "shop-api") == "overlays/staging/shop-api/kustomization.yaml"


@pytest.mark.parametrize("doc, tag", [
    ({"images": [{"name": "a", "newTag": "x"}]}, "x"),
    ({"images": [{"name": "a"}, {"name": "b", "newTag": "y"}]}, "y"),
    ({"images": [{"name": "a", "newTag": ""}, {"name": "b", "newTag": "z"}]}, "z"),
    ({"images": [{"name": "a", "newTag": 123}]}, "123"),
    ({"images": []}, None), ({}, None), (None, None), ({"images": [{"name": "a"}]}, None),
])
def test_pin_of_takes_the_first_image_with_a_tag_as_text_ac_113_3(doc, tag):  # AC-113.3
    assert model().pin_of(doc) == tag


def test_read_pin_is_none_for_a_missing_or_unparseable_overlay_ac_113_3(tmp_path):  # AC-113.3
    d = write_app(tmp_path, [entry()], None, {("dev", "api"): "sha-1"})
    assert model().read_pin(d, "dev", "api") == "sha-1"
    assert model().read_pin(d, "staging", "api") is None
    (d / "overlays/dev/api/kustomization.yaml").write_text("images: [unclosed\n")
    assert model().read_pin(d, "dev", "api") is None


def test_write_pin_sets_the_first_images_tag_and_dumps_like_promote_ac_113_3(tmp_path):  # AC-113.3
    d = write_app(tmp_path, [entry()], None, {("staging", "api"): "latest"})
    f = d / "overlays/staging/api/kustomization.yaml"
    doc = yaml.safe_load(f.read_text())
    model().write_pin(d, "staging", "api", "sha-" + SHA)
    doc["images"][0]["newTag"] = "sha-" + SHA
    assert f.read_text() == yaml.safe_dump(doc, sort_keys=False, default_flow_style=False)
    assert model().read_pin(d, "staging", "api") == "sha-" + SHA


# ---------------- AC-113.10: GitHub equals the checkout ----------------

def test_the_model_read_through_github_equals_the_one_from_a_checkout_ac_113_10(tmp_path):  # AC-113.10
    d = rich(tmp_path)
    assert model().load_remote("shop", reader(tmp_path)).to_dict() == model().load_dir(d).to_dict()


def test_load_remote_reads_the_file_once_and_pins_lazily_ac_113_10(tmp_path):  # AC-113.10
    rich(tmp_path)
    log = []
    r = model().load_remote("shop", reader(tmp_path, log))
    assert log == ["applications/shop/system.yaml"]                 # 5.0: one file
    u = urlsplit(r.url("shop-api", "dev")[0])
    assert (u.scheme, u.hostname) == ("http", "api.shop-dev.localhost")
    assert len(log) == 1                                            # a URL needs no pin
    assert r.instance("shop-api", "dev").tag == "sha-" + SHA
    assert log[1:] == ["applications/shop/overlays/dev/shop-api/kustomization.yaml"]


def test_a_gitops_app_that_cannot_be_read_is_an_empty_model_ac_113_10():  # AC-113.10
    r = model().load_remote("shop", lambda path: None)
    assert list(r.components) == [] and list(r.instances) == []
    assert r.find_component("acme/shop-api", "shop-api") is None
    assert r.url("shop-api", "dev") == (None, "not exposed in dev") or r.url("shop-api", "dev")[0] is None


def test_the_component_is_found_by_repo_first_and_by_name_second_ac_113_10(tmp_path):  # AC-113.10
    services = [entry(name="x", repo="acme/other"), entry(name="y", repo="acme/x")]
    m = model().load_dir(write_app(tmp_path, services, None))
    assert m.find_component("acme/x", "x").name == "y"             # the repo wins over the name
    assert m.find_component("acme/none", "x").name == "x"          # then the name
    assert m.find_component("acme/none", "none") is None


# ---------------- loading: strict from a checkout, entries that are not mappings ----------------

@pytest.mark.parametrize("fname", ["system.yaml"])         # 5.0: the one file (services.yaml and app.yaml are the 4.x pair)
@pytest.mark.parametrize("text", ["components: [unclosed\n", "- just\n- a list\n"])
def test_load_dir_names_an_unparseable_file_ac_113_16(tmp_path, fname, text):  # AC-113.16
    d = small(tmp_path)
    (d / fname).write_text(text)
    with pytest.raises(model().ModelError) as e:
        model().load_dir(d)
    assert f"applications/shop/{fname}" in str(e.value)
    assert isinstance(e.value, core.PlatformError) and e.value.hint


def test_entries_that_are_not_mappings_or_have_no_name_are_skipped_ac_113_2():  # AC-113.2
    api = system_doc([entry()])["components"]["api"]
    m = model().build({"components": {"junk": "x", "empty": None, "list": [], "api": api}}, "shop")
    assert names(m.components) == ["api"]


def test_a_system_without_environment_settings_has_bare_environments_ac_113_4(tmp_path):  # AC-113.4
    m = model().load_dir(write_app(tmp_path, [entry()], None))
    assert all(e.host is None and e.observability is None for e in m.environments)


def test_the_model_does_not_mutate_what_it_is_given_ac_113_9():  # AC-113.9
    doc = system_doc(RICH_SERVICES, RICH_APP)
    before = copy.deepcopy(doc)
    model().build(doc, "shop").to_dict()
    assert doc == before
