"""Spec 114 acceptance tests: `render.py` reads `system.yaml` (AC-114.1 .. AC-114.22, AC-114.57, AC-114.58, AC-114.70).

Contract: design.md "Contract — system.yaml", its key table and the render-error table. The renderer is run as a script in a
hand-built checkout (system_fixtures.render5), exactly like `devbox run render`. The byte comparisons run the frozen 4.7
renderer (scripts/cplat/assets/render_v4.py, plan t1) on the same system written as app.yaml + services.yaml."""
import copy
import importlib.util
import subprocess
import sys

import pytest
import yaml

from system_fixtures import (ALLOWED_TOP, FULL4_APP, FULL4_SERVICES, FULL5, NOT_MIGRATED, PAIRS, PINS, PIN5, PROBES, RENDER4, SHA, ROOT,
                             component, docs, full5, generated, load, mod, render, render5, tiny, write_old, write_system)

APP = "applications/shop"


def fails(tmp_path, doc, *needles, name="shop"):
    """The render fails with exit 1, names every needle on stderr and writes nothing."""
    p = render5(tmp_path, doc, name=name)
    assert p.returncode == 1, f"expected a failed render, got {p.returncode}: {p.stdout}{p.stderr}"
    for n in needles:
        assert n in p.stderr, f"{n!r} not in: {p.stderr}"
    assert generated(tmp_path) == {}, "a failed render must not write files"
    return p.stderr


def ok(tmp_path, doc, pins=None):
    p = render5(tmp_path, doc, pins=pins)
    assert p.returncode == 0, p.stdout + p.stderr
    return generated(tmp_path)


def overlay(g, env, comp, fname):
    return yaml.safe_load(g[f"{APP}/overlays/{env}/{comp}/{fname}"])


def same_as_4x(tmp_path, doc5, app4=None, services4=None, pins=None):
    """Render the 5.0 document and the 4.7 files of the same system: the generated trees must be equal."""
    r4, r5 = tmp_path / "v4", tmp_path / "v5"
    r4.mkdir(), r5.mkdir()
    write_old(r4, app4, services4, pins=pins)
    p4 = render(r4, script=RENDER4)
    assert p4.returncode == 0, "the 4.7 side must render: " + p4.stderr
    p5 = render5(r5, doc5, pins=pins)
    assert p5.returncode == 0, p5.stdout + p5.stderr
    a, b = generated(r4), generated(r5)
    assert sorted(a) == sorted(b), f"files differ: only 4.7 {sorted(set(a) - set(b))}, only 5.0 {sorted(set(b) - set(a))}"
    first = next((k for k in sorted(a) if a[k] != b[k]), None)
    assert first is None, f"{first} differs between the 4.7 and the 5.0 render"
    return b


# ---------------- AC-114.1: system.yaml is the only description ----------------

def test_system_yaml_alone_renders_the_4x_paths_ac_114_1(tmp_path):  # AC-114.1
    g = ok(tmp_path, FULL5)
    assert not (tmp_path / APP / "app.yaml").exists() and not (tmp_path / APP / "services.yaml").exists()
    for path in (f"{APP}/applicationset.yaml", "bootstrap/shop-root.yaml", f"{APP}/overlays/dev/shop-api/deployment.yaml",
                 f"{APP}/overlays/staging/shop-web/kustomization.yaml", f"{APP}/addons/prod/postgres/cluster.yaml",
                 f"{APP}/policies/dev/policy.yaml"):
        assert path in g


def test_a_new_gitops_app_has_system_yaml_and_no_old_files_ac_114_1(tmp_path):  # AC-114.1
    import core
    out = tmp_path / "shop-gitops"
    subprocess.run([*core.find_copier(), "copy", str(ROOT / "templates" / "gitops-app"), str(out), "--defaults", "--trust", "--skip-tasks",
                    "--data", "project_name=shop-gitops", "--data", "app_name=shop", "--data", "github_org=acme", "--data", "owner=acme"],
                   check=True, capture_output=True, text=True)
    d = out / APP
    assert (d / "system.yaml").is_file() and not (d / "app.yaml").exists() and not (d / "services.yaml").exists()
    doc = load(d / "system.yaml")
    assert doc["system"] == "shop" and doc["owner"] == "acme" and list(doc["environments"]) == ["dev", "staging", "prod"]
    p = subprocess.run([sys.executable, "scripts/render.py", "--check"], cwd=out, capture_output=True, text=True)
    assert p.returncode in (0, 1) and "not migrated" not in p.stderr, p.stderr
    p = subprocess.run([sys.executable, "scripts/render.py"], cwd=out, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    assert subprocess.run([sys.executable, "scripts/render.py", "--check"], cwd=out, capture_output=True, text=True).returncode == 0


# ---------------- AC-114.2: top-level keys, system name ----------------

def test_an_unknown_top_level_key_fails_naming_it_and_the_allowed_keys_ac_114_2(tmp_path):  # AC-114.2
    fails(tmp_path, full5(addons={}), "unknown key 'addons'", f"(allowed: {ALLOWED_TOP})", "applications/shop/system.yaml")


@pytest.mark.parametrize("old", ["app", "hosts", "services", "policies"])
def test_4x_keys_are_unknown_top_level_keys_ac_114_2(tmp_path, old):  # AC-114.2
    fails(tmp_path, full5(**{old: {}}), f"unknown key '{old}'")


def test_every_allowed_top_level_key_is_accepted_ac_114_2(tmp_path):  # AC-114.2
    doc = full5(apis={})
    ok(tmp_path, doc)


def test_a_system_that_differs_from_the_directory_fails_naming_both_ac_114_2(tmp_path):  # AC-114.2
    err = fails(tmp_path, full5(system="other"), "'other'", "shop")
    assert "does not match the directory" in err


def test_a_missing_system_fails_ac_114_2(tmp_path):  # AC-114.2
    doc = full5()
    del doc["system"]
    fails(tmp_path, doc, "system is required")


# ---------------- AC-114.3: the environments ----------------

@pytest.mark.parametrize("envs", [["dev", "staging"], ["dev", "staging", "prod", "qa"], ["staging", "dev", "prod"], []])
def test_environments_must_be_dev_staging_prod_in_order_ac_114_3(tmp_path, envs):  # AC-114.3
    doc = full5()
    doc["environments"] = {e: {} for e in envs}
    fails(tmp_path, doc, "environments must be dev, staging, prod in this order")


def test_a_missing_environments_key_fails_ac_114_3(tmp_path):  # AC-114.3
    doc = full5()
    del doc["environments"]
    fails(tmp_path, doc, "dev, staging, prod")


# ---------------- AC-114.4: environment keys ----------------

def test_an_unknown_environment_key_fails_naming_environment_key_and_allowed_ac_114_4(tmp_path):  # AC-114.4
    doc = full5()
    doc["environments"]["staging"]["replicas"] = 2
    fails(tmp_path, doc, "environments.staging: unknown key 'replicas'", "(allowed: host, url, policy, promote, observability)")


@pytest.mark.parametrize("key", ["hosts", "urls", "mode", "addons"])
def test_4x_names_are_not_environment_keys_ac_114_4(tmp_path, key):  # AC-114.4
    doc = full5()
    doc["environments"]["dev"][key] = "x"
    fails(tmp_path, doc, f"environments.dev: unknown key '{key}'")


# ---------------- AC-114.5: host templates ----------------

def test_host_placeholders_are_filled_in_and_the_httproute_is_the_4x_one_ac_114_5(tmp_path):  # AC-114.5
    g = same_as_4x(tmp_path, FULL5, FULL4_APP, FULL4_SERVICES, pins=PINS)
    assert overlay(g, "dev", "shop-api", "httproute.yaml")["spec"]["hostnames"] == ["api.shop-dev.localhost"]    # {component} = expose.host
    assert overlay(g, "dev", "shop-web", "httproute.yaml")["spec"]["hostnames"] == ["shop-web.shop-dev.localhost"]   # {component} = the name
    assert overlay(g, "staging", "shop-api", "httproute.yaml")["spec"]["hostnames"] == ["api.shop.example.com"]


def test_an_environment_without_host_exposes_nothing_ac_114_5(tmp_path):  # AC-114.5
    g = ok(tmp_path, FULL5)
    assert not [k for k in g if "/overlays/prod/" in k and k.endswith("httproute.yaml")]
    doc = copy.deepcopy(FULL5)
    del doc["environments"]["dev"]["host"]
    g = ok(tmp_path / "again", doc)
    assert not [k for k in g if "/overlays/dev/" in k and k.endswith("httproute.yaml")]


@pytest.mark.parametrize("old, new", [("{service}", "{component}"), ("{app}", "{system}")])
def test_4x_placeholders_in_host_fail_naming_the_replacement_ac_114_5(tmp_path, old, new):  # AC-114.5
    doc = copy.deepcopy(FULL5)
    doc["environments"]["dev"]["host"] = old + ".example.com"
    fails(tmp_path, doc, "environments.dev.host", f"{old} is {new} in 5.0")


def test_an_unknown_host_placeholder_fails_ac_114_5(tmp_path):  # AC-114.5
    doc = copy.deepcopy(FULL5)
    doc["environments"]["dev"]["host"] = "{nope}.example.com"
    fails(tmp_path, doc, "unknown placeholder {nope}", "{component}, {system}, {env}")


# ---------------- AC-114.6: url is ignored by the render ----------------

def test_the_render_ignores_url_ac_114_6(tmp_path):  # AC-114.6
    a = ok(tmp_path / "a", FULL5)
    doc = copy.deepcopy(FULL5)
    doc["environments"]["dev"]["url"] = "https://changed.example.com/{component}"
    doc["environments"]["staging"]["url"] = "https://{host}/{component}/{system}/{env}"
    b = ok(tmp_path / "b", doc)
    assert a == b


# ---------------- AC-114.7: policy ----------------

def test_policies_audit_enforce_off_equal_the_4x_modes_ac_114_7(tmp_path):  # AC-114.7
    g = same_as_4x(tmp_path, FULL5, FULL4_APP, FULL4_SERVICES)
    assert docs(tmp_path / "v5" / f"{APP}/policies/dev/policy.yaml")[0]["spec"]["validationActions"] == ["Audit"]
    assert docs(tmp_path / "v5" / f"{APP}/policies/prod/policy.yaml")[0]["spec"]["validationActions"] == ["Deny"]
    assert f"{APP}/policies/staging/policy.yaml" not in g                                                  # off: nothing rendered


def test_an_absent_policy_is_audit_in_dev_and_staging_and_enforce_in_prod_ac_114_7(tmp_path):  # AC-114.7
    doc = tiny(instances={"dev": {}, "staging": {}, "prod": {}})
    ok(tmp_path, doc)
    modes = {e: docs(tmp_path / APP / "policies" / e / "policy.yaml")[0]["spec"]["validationActions"] for e in ("dev", "staging", "prod")}
    assert modes == {"dev": ["Audit"], "staging": ["Audit"], "prod": ["Deny"]}


def test_an_unquoted_off_is_off_in_both_yaml_spellings_ac_114_7(tmp_path):  # AC-114.7
    doc = tiny(instances={"dev": {}, "staging": {}, "prod": {}})
    text = yaml.safe_dump(doc, sort_keys=False).replace("  dev:\n    host:", "  dev:\n    policy: off\n    host:", 1)
    assert "policy: off" in text
    g = ok(tmp_path, text)
    assert f"{APP}/policies/dev/policy.yaml" not in g and f"{APP}/policies/staging/policy.yaml" in g


@pytest.mark.parametrize("value", ["Audit", "warn", "Enforce", True, 3])
def test_any_other_policy_fails_naming_the_three_values_ac_114_7(tmp_path, value):  # AC-114.7
    doc = copy.deepcopy(FULL5)
    doc["environments"]["dev"]["policy"] = value
    fails(tmp_path, doc, "environments.dev.policy must be audit, enforce or off")


# ---------------- AC-114.8: promote ----------------

@pytest.mark.parametrize("value", ["after-dev-smoke", "manual"])
def test_staging_accepts_after_dev_smoke_and_manual_ac_114_8(tmp_path, value):  # AC-114.8
    doc = copy.deepcopy(FULL5)
    doc["environments"]["staging"]["promote"] = value
    ok(tmp_path, doc)


def test_staging_rejects_other_promote_values_ac_114_8(tmp_path):  # AC-114.8
    doc = copy.deepcopy(FULL5)
    doc["environments"]["staging"]["promote"] = "auto"
    fails(tmp_path, doc, "environments.staging.promote must be after-dev-smoke or manual, got 'auto'")


@pytest.mark.parametrize("value", ["after-dev-smoke", "auto", "manual-ish"])
def test_prod_only_accepts_manual_and_says_it_is_promoted_by_hand_ac_114_8(tmp_path, value):  # AC-114.8
    doc = copy.deepcopy(FULL5)
    doc["environments"]["prod"]["promote"] = value
    fails(tmp_path, doc, "environments.prod.promote: prod is always promoted by hand")


def test_prod_accepts_manual_ac_114_8(tmp_path):  # AC-114.8
    doc = copy.deepcopy(FULL5)
    doc["environments"]["prod"]["promote"] = "manual"
    ok(tmp_path, doc)


def test_dev_accepts_no_promote_ac_114_8(tmp_path):  # AC-114.8
    doc = copy.deepcopy(FULL5)
    doc["environments"]["dev"]["promote"] = "manual"
    fails(tmp_path, doc, "environments.dev.promote: dev follows main and takes no promote")


def test_an_instance_promote_follows_the_same_rules_ac_114_8(tmp_path):  # AC-114.8
    doc = copy.deepcopy(FULL5)
    component(doc)["instances"]["prod"]["promote"] = "after-dev-smoke"
    fails(tmp_path, doc, "components.shop-api.instances.prod.promote: prod is always promoted by hand")


# ---------------- AC-114.9: observability ----------------

def test_observability_gives_the_collector_and_otel_variables_as_in_4x_ac_114_9(tmp_path):  # AC-114.9
    g = same_as_4x(tmp_path, FULL5, FULL4_APP, FULL4_SERVICES)
    names = {e["name"] for e in overlay(g, "dev", "shop-api", "deployment.yaml")["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert "OTEL_EXPORTER_OTLP_ENDPOINT" in names and f"{APP}/addons/dev/observability/collector.yaml" in g


def test_an_environment_without_observability_gets_neither_ac_114_9(tmp_path):  # AC-114.9
    doc = copy.deepcopy(FULL5)
    del doc["environments"]["staging"]["observability"]
    g = ok(tmp_path, doc)
    assert not [k for k in g if "/addons/staging/observability/" in k]
    staging = overlay(g, "staging", "shop-api", "deployment.yaml")["spec"]["template"]["spec"]["containers"][0]["env"]
    assert not [e for e in staging if e["name"].startswith("OTEL_")]
    dev = overlay(g, "dev", "shop-api", "deployment.yaml")["spec"]["template"]["spec"]["containers"][0]["env"]
    assert [e for e in dev if e["name"].startswith("OTEL_")]


@pytest.mark.parametrize("bad, text", [({"alerts": "yes"}, "environments.dev.observability"), ({"queryURL": "ftp://x"}, "environments.dev.observability.queryURL"),
                                       ({"ui": "grafana"}, "environments.dev.observability")])
def test_observability_is_validated_with_the_4x_checks_ac_114_9(tmp_path, bad, text):  # AC-114.9
    doc = copy.deepcopy(FULL5)
    doc["environments"]["dev"]["observability"] = bad
    fails(tmp_path, doc, text)


# ---------------- AC-114.12: service and website keys ----------------

def test_all_4x_service_keys_plus_the_new_ones_render_as_in_4x_ac_114_12(tmp_path):  # AC-114.12
    doc = copy.deepcopy(FULL5)
    c = component(doc)
    c.update({"replicas": 1, "provides": [], "consumes": [], "instances": {"dev": {}, "staging": {"replicas": 2, "promote": "manual"}, "prod": {"replicas": 3}}})
    c["instances"]["dev"] = {"replicas": 1}
    same_as_4x(tmp_path, doc, FULL4_APP, FULL4_SERVICES)


@pytest.mark.parametrize("key, value, replacement", [
    ("replicas", {"dev": 1, "prod": 2}, "per-environment replicas go under instances.<env>.replicas"),
    ("environments", ["dev"], "environments is replaced by instances in 5.0"),
    ("promotion", {"staging": "manual"}, "promotion is replaced by instances.<env>.promote in 5.0"),
])
def test_4x_per_environment_keys_fail_naming_instances_ac_114_12(tmp_path, key, value, replacement):  # AC-114.12
    doc = copy.deepcopy(FULL5)
    component(doc)[key] = value
    fails(tmp_path, doc, "components.shop-api", replacement)


def test_an_unknown_component_key_fails_listing_the_allowed_ones_ac_114_12(tmp_path):  # AC-114.12
    doc = copy.deepcopy(FULL5)
    component(doc)["nodeSelector"] = {}
    fails(tmp_path, doc, "components.shop-api: unknown key 'nodeSelector' (allowed:", "instances")


def test_an_external_component_keeps_its_package_rule_ac_114_12(tmp_path):  # AC-114.12
    doc = copy.deepcopy(FULL5)
    doc["components"]["stock"]["port"] = 80
    fails(tmp_path, doc, "components.stock is external: port belongs in its package, not in system.yaml")


# ---------------- AC-114.13: instances ----------------

def test_a_component_runs_exactly_where_it_has_an_instance_ac_114_13(tmp_path):  # AC-114.13
    g = ok(tmp_path, FULL5)
    runs = sorted({tuple(k.split("/")[3:5]) for k in g if "/overlays/" in k})
    assert runs == [("dev", "shop-api"), ("dev", "shop-web"), ("dev", "stock"), ("prod", "shop-api"), ("staging", "shop-api"), ("staging", "shop-web")]


def test_no_instances_means_dev_only_ac_114_13(tmp_path):  # AC-114.13
    g = ok(tmp_path, tiny())
    assert sorted({tuple(k.split("/")[3:5]) for k in g if "/overlays/" in k}) == [("dev", "api")]


def test_an_instance_key_that_is_not_an_environment_fails_ac_114_13(tmp_path):  # AC-114.13
    fails(tmp_path, tiny(instances={"dev": {}, "qa": {}}), "components.api.instances: 'qa' is not an environment (environments: dev, staging, prod)")


def test_instances_override_replicas_resources_and_merge_env_ac_114_13(tmp_path):  # AC-114.13
    doc = tiny(env={"LOG_LEVEL": "INFO", "KEEP": "1"}, replicas=1, resources={"requests": {"cpu": "10m"}},
               instances={"dev": {}, "prod": {"replicas": 4, "env": {"LOG_LEVEL": "WARN"}, "resources": {"requests": {"cpu": "500m"}}}})
    g = ok(tmp_path, doc)

    def dep(env):
        d = overlay(g, env, "api", "deployment.yaml")
        return d["spec"]["replicas"], {e["name"]: e.get("value") for e in d["spec"]["template"]["spec"]["containers"][0]["env"]}, \
            d["spec"]["template"]["spec"]["containers"][0]["resources"]
    dev, prod = dep("dev"), dep("prod")
    assert dev[0] == 1 and dev[1]["LOG_LEVEL"] == "INFO" and dev[2]["requests"]["cpu"] == "10m"
    assert prod[0] == 4 and prod[1]["LOG_LEVEL"] == "WARN" and prod[1]["KEEP"] == "1" and prod[2]["requests"]["cpu"] == "500m"


def test_an_unknown_instance_key_fails_listing_the_allowed_ones_ac_114_13(tmp_path):  # AC-114.13
    fails(tmp_path, tiny(instances={"dev": {"port": 9}}),
          "components.api.instances.dev: unknown key 'port' (allowed: replicas, resources, env, promote, secrets)")


# ---------------- AC-114.14: libraries ----------------

def lib_doc(**lib):
    doc = tiny()
    doc["components"]["lib"] = {"type": "library", "lang": "python", "repo": "acme/lib", **lib}
    return doc


def test_a_library_renders_no_manifests_ac_114_14(tmp_path):  # AC-114.14
    g = ok(tmp_path, lib_doc())
    assert not [k for k in g if "/lib" in k.split("overlays/")[-1] and "overlays" in k]
    assert not [k for k in g if "lib" in k.split("/")[3:5]]
    assert generated(tmp_path) == ok(tmp_path / "without", tiny())


@pytest.mark.parametrize("key, value", [("instances", {"dev": {}}), ("image", "ghcr.io/acme/lib"), ("port", 80), ("expose", True)])
def test_a_library_with_instances_image_port_or_expose_fails_ac_114_14(tmp_path, key, value):  # AC-114.14
    fails(tmp_path, lib_doc(**{key: value}), "components.lib: a library has no instances", key)


# ---------------- AC-114.15: uses ----------------

def test_uses_postgres_injects_the_operator_secret_as_in_4x_ac_114_15(tmp_path):  # AC-114.15
    g = same_as_4x(tmp_path, FULL5, FULL4_APP, FULL4_SERVICES)
    env = overlay(g, "dev", "shop-api", "deployment.yaml")["spec"]["template"]["spec"]["containers"][0]["env"]
    refs = {e["name"]: e["valueFrom"]["secretKeyRef"]["name"] for e in env if "valueFrom" in e and "secretKeyRef" in e["valueFrom"]}
    assert refs["DATABASE_URL"] == "shop-postgres-app" and refs["PGHOST"] == "shop-postgres-app"


def test_using_a_library_changes_no_manifest_ac_114_15(tmp_path):  # AC-114.15
    with_lib = lib_doc()
    component(with_lib, "api")["uses"] = ["lib"]
    assert ok(tmp_path / "a", with_lib) == ok(tmp_path / "b", tiny())


def test_uses_of_an_unknown_name_fails_listing_resources_and_libraries_ac_114_15(tmp_path):  # AC-114.15
    doc = lib_doc()
    component(doc, "api")["uses"] = ["redis"]
    fails(tmp_path, doc, "components.api: uses 'redis', which is neither a resource nor a library of the system", "resources: none", "libraries: lib")


def test_uses_postgres_without_the_resource_fails_ac_114_15(tmp_path):  # AC-114.15
    fails(tmp_path, tiny(uses=["postgres"]), "uses 'postgres'", "neither a resource nor a library")


# ---------------- AC-114.16: APIs ----------------

def api_doc(**over):
    doc = tiny(provides=["api-rest"])
    doc["components"]["web"] = {"type": "website", "lang": "typescript", "repo": "acme/web", "image": "ghcr.io/acme/web", "port": 3000,
                                "probes": dict(PROBES), "consumes": ["api-rest"]}
    doc["apis"] = {"api-rest": {"type": "openapi"}}
    doc.update(over)
    return doc


def test_apis_provides_and_consumes_change_no_manifest_ac_114_16(tmp_path):  # AC-114.16
    plain = tiny()
    plain["components"]["web"] = copy.deepcopy(api_doc()["components"]["web"])
    plain["components"]["web"].pop("consumes")
    assert ok(tmp_path / "a", api_doc()) == ok(tmp_path / "b", plain)


@pytest.mark.parametrize("kind", ["openapi", "grpc", "graphql", "events"])
def test_every_api_type_is_accepted_ac_114_16(tmp_path, kind):  # AC-114.16
    ok(tmp_path, api_doc(apis={"api-rest": {"type": kind}}))


def test_an_api_type_is_required_and_checked_ac_114_16(tmp_path):  # AC-114.16
    fails(tmp_path, api_doc(apis={"api-rest": {"type": "soap"}}), "apis.api-rest: type must be openapi, grpc, graphql or events")
    fails(tmp_path / "x", api_doc(apis={"api-rest": {}}), "apis.api-rest: type must be openapi, grpc, graphql or events")


def test_providing_an_undeclared_api_fails_naming_it_and_the_component_ac_114_16(tmp_path):  # AC-114.16
    doc = api_doc()
    component(doc, "api")["provides"].append("ghost")
    fails(tmp_path, doc, "components.api: provides 'ghost', which apis: does not declare")


def test_consuming_an_undeclared_api_fails_ac_114_16(tmp_path):  # AC-114.16
    doc = api_doc()
    component(doc, "web")["consumes"].append("ghost")
    fails(tmp_path, doc, "components.web: consumes 'ghost', which apis: does not declare")


def test_an_api_without_a_provider_fails_ac_114_16(tmp_path):  # AC-114.16
    doc = api_doc()
    component(doc, "api")["provides"] = []
    fails(tmp_path, doc, "apis.api-rest: provided by 0 components (none); an API has exactly one provider")


def test_an_api_with_two_providers_fails_naming_them_ac_114_16(tmp_path):  # AC-114.16
    doc = api_doc()
    component(doc, "web")["provides"] = ["api-rest"]
    fails(tmp_path, doc, "apis.api-rest: provided by 2 components (", "api", "web", "an API has exactly one provider")


# ---------------- AC-114.17 / AC-114.18: secrets ----------------

def test_secrets_render_as_in_4x_and_the_default_path_reads_the_4x_store_key_ac_114_17(tmp_path):  # AC-114.17
    g = same_as_4x(tmp_path, FULL5, FULL4_APP, FULL4_SERVICES)
    es = overlay(g, "staging", "shop-api", "externalsecret-api-keys.yaml")
    assert es["spec"]["data"][0]["remoteRef"] == {"key": "shop-staging-api-keys", "property": "STRIPE_KEY"}
    assert overlay(g, "dev", "shop-api", "externalsecret-api-pay.yaml")["spec"]["data"][0]["remoteRef"]["key"] == "shop-api/dev/api-pay"


@pytest.mark.parametrize("old, new", [("{service}", "{component}"), ("{app}", "{system}")])
def test_4x_placeholders_in_a_secret_path_fail_naming_the_replacement_ac_114_17(tmp_path, old, new):  # AC-114.17
    doc = copy.deepcopy(FULL5)
    component(doc)["secrets"][1]["remote"]["path"] = old + "/{env}/{secret}"
    fails(tmp_path, doc, "secrets.api-pay.remote.path", f"{old} is {new} in 5.0")


def test_an_instance_secret_replaces_the_declared_fields_in_that_environment_only_ac_114_18(tmp_path):  # AC-114.18
    doc = copy.deepcopy(FULL5)
    component(doc)["instances"]["prod"]["secrets"] = [{"name": "api-pay", "remote": {"keys": ["PAY_KEY"], "path": "prod/{secret}"}}]
    g = ok(tmp_path, doc)
    assert overlay(g, "prod", "shop-api", "externalsecret-api-pay.yaml")["spec"]["data"][0]["remoteRef"]["key"] == "prod/api-pay"
    assert overlay(g, "dev", "shop-api", "externalsecret-api-pay.yaml")["spec"]["data"][0]["remoteRef"]["key"] == "shop-api/dev/api-pay"
    assert overlay(g, "staging", "shop-api", "externalsecret-api-pay.yaml")["spec"]["data"][0]["remoteRef"]["key"] == "shop-api/staging/api-pay"


def test_an_instance_secret_the_component_does_not_declare_fails_ac_114_18(tmp_path):  # AC-114.18
    doc = copy.deepcopy(FULL5)
    component(doc)["instances"]["prod"]["secrets"] = [{"name": "ghost", "remote": {"keys": ["X"]}}]
    fails(tmp_path, doc, "components.shop-api.instances.prod.secrets: 'ghost' is not a secret of shop-api (declared: api-auth, api-pay, api-keys)")


# ---------------- AC-114.19: resources ----------------

def test_the_postgres_resource_renders_the_4x_cluster_ac_114_19(tmp_path):  # AC-114.19
    g = same_as_4x(tmp_path, FULL5, FULL4_APP, FULL4_SERVICES)
    prod = yaml.safe_load(g[f"{APP}/addons/prod/postgres/cluster.yaml"])
    assert prod["spec"]["instances"] == 3 and prod["spec"]["storage"]["size"] == "20Gi" and prod["metadata"]["name"] == "shop-postgres"


def test_the_resource_defaults_are_the_4x_defaults_ac_114_19(tmp_path):  # AC-114.19
    doc = tiny(uses=["postgres"])
    doc["resources"] = {"postgres": {"type": "database"}}
    app4 = {"hosts": {"dev": "{service}.{app}-dev.localhost"}, "addons": {"postgres": {}}}
    svc4 = {"services": [{"name": "api", "repo": "acme/api", "shape": "service-python", "image": "ghcr.io/acme/api", "port": 8080,
                          "probes": dict(PROBES), "uses": ["postgres"], "environments": ["dev"]}]}
    same_as_4x(tmp_path, doc, app4, svc4)


def test_the_resource_is_rendered_only_where_a_running_component_uses_it_ac_114_19(tmp_path):  # AC-114.19
    g = ok(tmp_path, FULL5)
    assert sorted(k.split("/")[3] for k in g if k.endswith("addons/dev/postgres/cluster.yaml") or "/postgres/cluster.yaml" in k) == ["dev", "prod", "staging"]
    doc = copy.deepcopy(FULL5)
    del component(doc)["uses"]
    g = ok(tmp_path / "unused", doc)
    assert not [k for k in g if "/postgres/" in k]


@pytest.mark.parametrize("resource", [{"redis": {"type": "database"}}, {"postgres": {"type": "queue"}}, {"postgres": {}}])
def test_another_resource_name_or_type_fails_ac_114_19(tmp_path, resource):  # AC-114.19
    doc = copy.deepcopy(FULL5)
    doc["resources"] = resource
    fails(tmp_path, doc, "5.0 supports one database resource named postgres (type: database)")


def test_a_resource_named_observability_points_to_the_environment_ac_114_19(tmp_path):  # AC-114.19
    doc = copy.deepcopy(FULL5)
    doc["resources"]["observability"] = {"type": "database"}
    fails(tmp_path, doc, "observability is set per environment under environments.<env>.observability")


def test_an_unknown_resource_key_fails_ac_114_19(tmp_path):  # AC-114.19
    doc = copy.deepcopy(FULL5)
    doc["resources"]["postgres"]["instances"] = 3
    doc["resources"]["postgres"]["size"] = "big"
    fails(tmp_path, doc, "resources.postgres: unknown key 'size' (allowed: type, version, replicas, storage, resources, instances)")


# ---------------- AC-114.20: versions live in the overlays ----------------

@pytest.mark.parametrize("edit, hint", [
    ({"image": "ghcr.io/acme/api:1.2.3"}, "image"),
    ({"tag": "1.2.3"}, "tag"),
    ({"version": "1.2.3"}, "version"),
])
def test_a_version_in_system_yaml_fails_saying_versions_are_pinned_in_the_overlays_ac_114_20(tmp_path, edit, hint):  # AC-114.20
    fails(tmp_path, tiny(**edit), "components.api: versions are pinned in the overlays, not in system.yaml", hint)


def test_a_re_render_keeps_every_pinned_tag_ac_114_20(tmp_path):  # AC-114.20
    ok(tmp_path, FULL5, pins=PINS)
    first = generated(tmp_path)
    p = render(tmp_path)
    assert p.returncode == 0, p.stderr
    again = generated(tmp_path)
    assert again == first
    assert yaml.safe_load(again[f"{APP}/overlays/dev/shop-api/kustomization.yaml"])["images"][0]["newTag"] == "sha-" + SHA
    assert yaml.safe_load(again[f"{APP}/overlays/staging/shop-api/kustomization.yaml"])["images"][0]["newTag"] == "1.2.0"


def test_a_dev_pin_changes_only_the_overlay_never_system_yaml_ac_114_20(tmp_path):  # AC-114.20
    ok(tmp_path, FULL5)
    before = (tmp_path / APP / "system.yaml").read_bytes()
    new = "sha-" + "b" * 40
    (tmp_path / "scripts" / "pin.py").write_text(PIN5.read_text())
    p = subprocess.run([sys.executable, "scripts/pin.py", "dev", "shop-api", new], cwd=tmp_path, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    assert (tmp_path / APP / "system.yaml").read_bytes() == before
    assert yaml.safe_load((tmp_path / APP / "overlays/dev/shop-api/kustomization.yaml").read_text())["images"][0]["newTag"] == new
    p = render(tmp_path)
    assert p.returncode == 0 and yaml.safe_load((tmp_path / APP / "overlays/dev/shop-api/kustomization.yaml").read_text())["images"][0]["newTag"] == new


# ---------------- AC-114.21: nothing in the cluster is renamed ----------------

def test_cluster_names_and_labels_are_the_4x_ones_ac_114_21(tmp_path):  # AC-114.21
    g = same_as_4x(tmp_path, FULL5, FULL4_APP, FULL4_SERVICES)
    sets = {d["metadata"]["name"]: d for d in docs(tmp_path / "v5" / f"{APP}/applicationset.yaml")}
    assert sorted(sets) == ["shop-dev", "shop-prod", "shop-staging"]
    assert sets["shop-staging"]["spec"]["template"]["metadata"]["name"] == "{{name}}-staging"
    assert sets["shop-staging"]["spec"]["template"]["spec"]["destination"]["namespace"] == "shop-staging"
    assert "shop-postgres-app" in g[f"{APP}/overlays/dev/shop-api/deployment.yaml"]
    assert "app.kubernetes.io/part-of: shop" in g[f"{APP}/overlays/dev/shop-api/deployment.yaml"]
    assert "addon-" in "".join(g.values())      # the Argo applications of the addons keep addon-<addon>-<env>


# ---------------- AC-114.22: unmigrated directories ----------------

@pytest.mark.parametrize("which", [("app.yaml",), ("services.yaml",), ("app.yaml", "services.yaml")])
@pytest.mark.parametrize("with_system", [False, True])
def test_a_directory_with_old_files_writes_nothing_and_says_so_ac_114_22(tmp_path, which, with_system):  # AC-114.22
    d = tmp_path / APP
    d.mkdir(parents=True)
    for f in which:
        (d / f).write_text("services: []\n" if f == "services.yaml" else "{}\n")
    if with_system:
        write_system(tmp_path, FULL5)
    for args in ([], ["--check"]):
        p = render(tmp_path, *args)
        assert p.returncode == 1 and f"ERROR: applications/shop: {NOT_MIGRATED}" in p.stderr, p.stderr
    assert generated(tmp_path) == {}


def test_one_unmigrated_directory_stops_the_render_of_the_others_ac_114_22(tmp_path):  # AC-114.22
    write_system(tmp_path, FULL5)
    write_old(tmp_path, name="legacy")
    p = render(tmp_path)
    assert p.returncode == 1 and "applications/legacy" in p.stderr and NOT_MIGRATED in p.stderr
    assert generated(tmp_path) == {}


# ---------------- AC-114.57: owner ----------------

@pytest.mark.parametrize("owner", [None, "", "   ", 7, ["acme"], {"name": "acme"}])
def test_owner_is_a_required_non_empty_string_ac_114_57(tmp_path, owner):  # AC-114.57
    doc = copy.deepcopy(FULL5)
    if owner is None:
        del doc["owner"]
    else:
        doc["owner"] = owner
    fails(tmp_path, doc, "owner is required: a non-empty string")


# ---------------- AC-114.58: type and lang ----------------

@pytest.mark.parametrize("type_, lang", [("service", "python"), ("service", "java"), ("service", "go"), ("website", "typescript"),
                                         ("library", "python"), ("service", "unknown")])
def test_the_valid_type_lang_pairs_render_ac_114_58(tmp_path, type_, lang):  # AC-114.58
    doc = tiny()
    c = component(doc, "api")
    c["type"], c["lang"] = type_, lang
    if type_ == "library":
        for k in ("image", "port", "probes"):
            del c[k]
    ok(tmp_path, doc)


@pytest.mark.parametrize("type_, lang", [("service", "typescript"), ("website", "python"), ("library", "go"), ("worker", "python"),
                                         ("website", "unknown"), ("library", "unknown")])
def test_another_pair_fails_listing_the_valid_ones_ac_114_58(tmp_path, type_, lang):  # AC-114.58
    doc = tiny()
    component(doc, "api").update(type=type_, lang=lang)
    fails(tmp_path, doc, f"components.api: {type_}/{lang} is not a valid type/lang pair", PAIRS)


@pytest.mark.parametrize("drop", ["type", "lang"])
def test_type_and_lang_are_required_ac_114_58(tmp_path, drop):  # AC-114.58
    doc = tiny()
    del component(doc, "api")[drop]
    fails(tmp_path, doc, "components.api: type and lang are required", PAIRS)


def test_a_shape_key_fails_saying_it_is_replaced_by_type_and_lang_ac_114_58(tmp_path):  # AC-114.58
    fails(tmp_path, tiny(shape="service-python"), "components.api: shape is replaced by type and lang in 5.0 (e.g. type: service, lang: python)")


# ---------------- AC-114.70: the renderer agrees with the model ----------------

def test_the_renderer_and_the_model_agree_ac_114_70(tmp_path):  # AC-114.70
    ok(tmp_path, FULL5, pins=PINS)
    app_dir = tmp_path / APP
    spec = importlib.util.spec_from_file_location("render_under_test", tmp_path / "scripts" / "render.py")
    r = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(r)
    m = mod("model").load_dir(app_dir)

    def first(label, a, b):
        assert a == b, f"{label}: the renderer has {a!r}, the model has {b!r}"
    first("environments", list(r.ENVS), [e.name for e in m.environments])
    first("environments (constant)", list(r.ENVS), list(mod("model").ENVIRONMENTS))
    ran = {tuple(p.relative_to(app_dir / "overlays").parts) for p in (app_dir / "overlays").glob("*/*") if p.is_dir()}
    first("instances", sorted(ran), sorted((i.environment, i.component) for i in m.instances))
    sets = {d["metadata"]["name"].removeprefix("shop-"): d for d in docs(app_dir / "applicationset.yaml")}
    for env in r.ENVS:
        names = [e["name"] for e in sets[env]["spec"]["generators"][0]["list"]["elements"]]
        first(f"argo applications in {env}", sorted(f"{n}-{env}" for n in names), sorted(i.argo_application for i in m.instances_in(env)))
        ns = sets[env]["spec"]["template"]["spec"]["destination"]["namespace"]
        first(f"namespace of {env}", ns, f"shop-{env}")
        assert all(i.namespace == ns for i in m.instances_in(env)), f"namespaces of {env}"
    pg = {p.relative_to(app_dir / "addons").parts[0] for p in (app_dir / "addons").glob("*/postgres")}
    first("resource instances", sorted(pg), sorted(ri.environment for ri in m.resource_instances_of("postgres")))
