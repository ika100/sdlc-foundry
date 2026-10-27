"""Spec 115 acceptance tests, the renderer part: named, typed and external resources, the versions table and the operators
(AC-115.1 .. AC-115.12, AC-115.17, AC-115.18 render side).

Contract: design.md "Contract: system.yaml additions", its render-error tables and "Contract: render outputs". The renderer runs as a
script in a hand-built checkout (resources_fixtures); nothing touches the network or a cluster. The commands, the model, doctor, the
migration and the docs are in test_resources_115_cmds.py."""
import copy
import re

import pytest
import yaml

from resources_fixtures import (APP, ENVS, KEYS, LABELS, PIN_RE, SEMVER, TYPES_LINE, VARS, addon_names, cluster, comp, contract_vars, db, env_list,
                                external_secret, external_secret_path, fails, kustomization, ok, platform_render_module, render_50, secret_vars,
                                sets, system, tree, two_dbs, var_order, y, normalized)
from system_fixtures import FULL5, ROOT, component, full5, rich5, render5, tiny

P = "applications/shop/system.yaml: "


# ---------------- AC-115.1: type is required ----------------

def test_a_resource_without_type_fails_naming_the_resource_and_the_four_types_ac_115_1(tmp_path):  # AC-115.1
    fails(tmp_path, system({"orders-db": {"version": 17}}), P + f"resources.orders-db: type is required {TYPES_LINE}")


def test_a_resource_that_is_not_a_mapping_has_no_type_ac_115_1(tmp_path):  # AC-115.1
    fails(tmp_path, system({"orders-db": None}), P + f"resources.orders-db: type is required {TYPES_LINE}")


@pytest.mark.parametrize("value", ["queue", "Database", "postgres"])
def test_another_type_fails_naming_resource_value_and_types_ac_115_1(tmp_path, value):  # AC-115.1
    fails(tmp_path, system({"orders-db": {"type": value}}), P + f"resources.orders-db: type '{value}' is not a resource type {TYPES_LINE}")


def test_the_5_0_postgres_resource_needs_its_type_now_ac_115_1(tmp_path):  # AC-115.1
    fails(tmp_path, system({"postgres": {"version": 17}}), "resources.postgres: type is required")


# ---------------- AC-115.2: types that no release runs yet ----------------

@pytest.mark.parametrize("typ, spec", [("cache", 118), ("broker", 119)])  # spec 116: bucket is built
def test_a_type_that_is_not_built_yet_names_the_spec_and_writes_nothing_ac_115_2(tmp_path, typ, spec):  # AC-115.2
    err = fails(tmp_path, system({"store": {"type": typ}}), P + f"resources.store: type {typ} is not available yet: spec {spec} brings it")
    assert len(err.strip().splitlines()) == 1, "one line"


# ---------------- AC-115.3: names ----------------

@pytest.mark.parametrize("name", ["Orders", "1db", "my_db", "a" * 31, "-db", "db.1"])
def test_an_invalid_resource_name_fails_ac_115_3(tmp_path, name):  # AC-115.3
    fails(tmp_path, system({name: db()}), P + f"resources.{name}: the name must start with a lowercase letter and contain only lowercase "
          "letters, digits and hyphens (at most 30 characters)")


@pytest.mark.parametrize("name", ["a", "orders-db", "db2", "a" * 30])
def test_valid_resource_names_render_ac_115_3(tmp_path, name):  # AC-115.3
    g = ok(tmp_path, system({name: db()}, {"api": comp("api", [name])}))
    assert f"{APP}/addons/dev/{name}/cluster.yaml" in g


def test_a_resource_with_a_component_name_fails_naming_both_ac_115_3(tmp_path):  # AC-115.3
    fails(tmp_path, system({"orders": db()}, {"orders": comp("orders")}),
          P + "resources.orders: components.orders has the same name; a resource and a component need different names")


def test_a_resource_named_observability_points_to_the_environment_ac_115_3(tmp_path):  # AC-115.3
    fails(tmp_path, system({"observability": db()}), "resources.observability: observability is set per environment under environments.<env>.observability")


# ---------------- AC-115.4: several databases ----------------

def test_every_used_database_gets_its_own_cluster_with_its_own_values_ac_115_4(tmp_path):  # AC-115.4
    g = ok(tmp_path, two_dbs())
    o_dev, o_prod = cluster(g, "dev", "orders-db"), cluster(g, "prod", "orders-db")
    assert o_dev["metadata"]["name"] == "shop-orders-db" and o_dev["spec"]["instances"] == 2
    assert o_dev["spec"]["storage"]["size"] == "5Gi" and o_dev["spec"]["resources"]["requests"] == {"cpu": "200m", "memory": "512Mi"}
    assert PIN_RE.match(o_dev["spec"]["imageName"]).group(1) == "16"
    assert (o_prod["spec"]["instances"], o_prod["spec"]["storage"]["size"]) == (3, "50Gi")
    assert o_dev["spec"]["bootstrap"]["initdb"] == {"database": "shop", "owner": "shop"}
    u_dev, u_stg = cluster(g, "dev", "users-db"), cluster(g, "staging", "users-db")
    assert u_dev["metadata"]["name"] == "shop-users-db" and u_dev["spec"]["storage"]["size"] == "2Gi" and u_dev["spec"]["instances"] == 1
    assert u_stg["spec"]["storage"]["size"] == "3Gi" and PIN_RE.match(u_stg["spec"]["imageName"]).group(1) == "18"


def test_a_database_exists_only_where_a_running_component_uses_it_ac_115_4(tmp_path):  # AC-115.4
    g = ok(tmp_path, two_dbs())
    assert [k for k in g if "/addons/" in k and "users-db" in k] == [f"{APP}/addons/{e}/users-db/{f}" for e in ("dev", "staging")
                                                                      for f in ("cluster.yaml", "kustomization.yaml")]
    assert not [k for k in g if "idle-db" in k], "an unused database is rendered nowhere"
    assert addon_names(g, "dev") == ["orders-db", "users-db"] and addon_names(g, "prod") == ["orders-db"]


def test_changing_one_databases_values_changes_no_manifest_of_another_ac_115_4(tmp_path):  # AC-115.4
    before = ok(tmp_path / "a", two_dbs())
    doc = two_dbs()
    doc["resources"]["orders-db"]["storage"] = "9Gi"
    doc["resources"]["orders-db"]["replicas"] = 5
    after = ok(tmp_path / "b", doc)
    assert sorted(before) == sorted(after)
    changed = [k for k in before if before[k] != after[k]]
    assert changed and all("orders-db" in k for k in changed), changed


# ---------------- AC-115.5: object names ----------------

def test_postgres_keeps_its_5_0_names_ac_115_5(tmp_path):  # AC-115.5
    g = ok(tmp_path, system({"postgres": db(), "orders-db": db()}, {"api": comp("api", ["postgres"]), "orders": comp("orders", ["orders-db"])}))
    assert cluster(g, "dev", "postgres")["metadata"]["name"] == "shop-postgres"
    assert secret_vars(g, "dev", "api") == contract_vars("postgres")
    assert addon_names(g, "dev") == ["orders-db", "postgres"]
    assert sets(g)["shop-addons-dev"]["spec"]["template"]["metadata"]["name"] == "addon-{{name}}-dev"


def test_every_database_gets_the_secret_and_application_names_of_its_name_ac_115_5(tmp_path):  # AC-115.5
    g = ok(tmp_path, two_dbs())
    assert secret_vars(g, "dev", "orders") == contract_vars("orders-db")
    assert secret_vars(g, "dev", "users") == contract_vars("users-db")
    assert [e["name"] for e in sets(g)["shop-addons-dev"]["spec"]["generators"][0]["list"]["elements"]] == ["orders-db", "users-db"]
    assert cluster(g, "dev", "orders-db")["metadata"]["labels"]["app.kubernetes.io/name"] == "orders-db"


def test_an_external_resource_gets_the_same_secret_name_ac_115_5(tmp_path):  # AC-115.5
    g = ok(tmp_path, system({"ext": db(external=True)}, {"api": comp("api", ["ext"])}))
    assert secret_vars(g, "prod", "api") == contract_vars("ext")
    assert y(g, external_secret_path("prod", "api", "ext"))["metadata"]["name"] == "shop-ext-app"


def test_two_resources_that_would_share_a_cluster_object_name_fail_ac_115_5(tmp_path):  # AC-115.5
    fails(tmp_path, system({"a": db(), "a-app": db()}, {"api": comp("api", ["a", "a-app"])}),
          "resources.a and resources.a-app would both create the object shop-a-app; rename one")


def test_a_component_secret_may_not_take_a_connection_secrets_name_ac_115_5(tmp_path):  # AC-115.5
    doc = system({"orders-db": db()}, {"api": comp("api", ["orders-db"], secrets=[{"name": "shop-orders-db-app", "generate": ["K"]}])})
    fails(tmp_path, doc, "components.api: secret 'shop-orders-db-app' is the connection Secret of resources.orders-db; rename it")


# ---------------- AC-115.6: 5.0 systems render byte-identically except the image ----------------

def _5_0_documents():
    pg = lambda **kw: system({"postgres": db(**kw)}, {"api": comp("api", ["postgres"])})
    return [("full5", FULL5), ("rich5", rich5()), ("postgres", pg()), ("postgres-15", pg(version=15)), ("postgres-16-sized", pg(version=16, replicas=2, storage="3Gi")),
            ("postgres-18", pg(version=18, instances={"prod": {"replicas": 3, "storage": "20Gi"}}))]


@pytest.mark.parametrize("label, doc", _5_0_documents(), ids=[d[0] for d in _5_0_documents()])
def test_a_5_0_system_renders_as_5_0_did_except_the_pinned_image_ac_115_6(tmp_path, label, doc):  # AC-115.6
    old = render_50(tmp_path, doc)
    p = render5(tmp_path / "new", copy.deepcopy(doc))
    assert p.returncode == 0, p.stderr
    from system_fixtures import generated
    new = generated(tmp_path / "new")
    assert sorted(old) == sorted(new), f"files differ: {sorted(set(old) ^ set(new))}"
    for k in old:
        assert normalized(old[k]) == normalized(new[k]), f"{k} differs from the 5.0 render beyond the image"
    clusters = [k for k in new if k.endswith("/cluster.yaml")]
    assert clusters
    for k in clusters:
        image = yaml.safe_load(new[k])["spec"]["imageName"]
        assert PIN_RE.match(image), f"{k}: {image} is not an exact pin (AC-115.17)"
        assert image != yaml.safe_load(old[k])["spec"]["imageName"], f"{k}: the image must move from the major-only tag to the pin"


# ---------------- AC-115.7 / AC-115.8: what a using component gets ----------------

def test_one_database_of_any_name_gives_the_unprefixed_variables_ac_115_7(tmp_path):  # AC-115.7
    g = ok(tmp_path, system({"main-db": db()}, {"api": comp("api", ["main-db"], env={"LOG_LEVEL": "INFO"})}))
    for e in ENVS:
        assert secret_vars(g, e, "api") == contract_vars("main-db")
    assert var_order(g, "dev", "api") == list(VARS)
    names = [x["name"] for x in env_list(g, "dev", "api")]
    assert names.index("LOG_LEVEL") < names.index("DATABASE_URL"), "after the literal env entries"
    assert {k for _, k in secret_vars(g, "dev", "api").values()} == set(KEYS)


def test_the_contract_table_of_the_database_type_is_in_the_renderer_ac_115_7(tmp_path):  # AC-115.7
    r = platform_render_module("render_115_types")
    types = getattr(r, "TYPES", None)
    assert types is not None, "render.py has the TYPES table"
    assert types["database"]["keys"] == KEYS and types["database"]["env"] == VARS
    assert tuple(getattr(r, "RESOURCE_TYPES", ())) == ("database", "bucket", "cache", "broker")
    assert dict(getattr(r, "PLANNED_TYPES", {})) == {"cache": 118, "broker": 119}  # spec 116


def test_two_databases_of_a_component_get_prefixed_variables_ac_115_8(tmp_path):  # AC-115.8
    comps = {"api": comp("api", ["orders-db", "users-db", "shop-lib"], env={"LOG_LEVEL": "INFO"}),
             "shop-lib": {"type": "library", "lang": "python", "repo": "acme/shop-lib"},
             "reports": comp("reports", ["users-db"])}
    g = ok(tmp_path, system({"orders-db": db(), "users-db": db()}, comps))
    for e in ENVS:
        assert secret_vars(g, e, "api") == {**contract_vars("orders-db", "ORDERS_DB_"), **contract_vars("users-db", "USERS_DB_")}
    assert var_order(g, "dev", "api") == [f"ORDERS_DB_{v}" for v in VARS] + [f"USERS_DB_{v}" for v in VARS]
    assert not {"DATABASE_URL", "PGHOST", "PGPASSWORD"} & {x["name"] for x in env_list(g, "dev", "api")}
    assert secret_vars(g, "dev", "reports") == contract_vars("users-db"), "a component with one database keeps the bare names"


def test_the_prefix_is_the_upper_cased_name_with_underscores_ac_115_8(tmp_path):  # AC-115.8
    g = ok(tmp_path, system({"a-b-c": db(), "x1": db()}, {"api": comp("api", ["a-b-c", "x1"])}))
    names = set(secret_vars(g, "dev", "api"))
    assert {"A_B_C_DATABASE_URL", "A_B_C_PGHOST", "X1_PGPORT", "X1_PGPASSWORD"} <= names and len(names) == 12


def test_the_prefix_follows_uses_order_ac_115_8(tmp_path):  # AC-115.8
    g = ok(tmp_path, system({"orders-db": db(), "users-db": db()}, {"api": comp("api", ["users-db", "orders-db"])}))
    assert var_order(g, "dev", "api")[0] == "USERS_DB_DATABASE_URL"


def test_the_env_clash_check_compares_the_effective_names_ac_115_8(tmp_path):  # AC-115.8
    two = {"orders-db": db(), "users-db": db()}
    ok(tmp_path / "free", system(two, {"api": comp("api", ["orders-db", "users-db"], env={"PGHOST": "x"})}))     # bare name is free with two
    fails(tmp_path / "clash", system(two, {"api": comp("api", ["orders-db", "users-db"], env={"ORDERS_DB_PGHOST": "x"})}),
          "components.api: env ORDERS_DB_PGHOST is provided by the 'orders-db' resource")


# ---------------- AC-115.9: external resources ----------------

def ext_doc(**ext):
    return system({"ext": db(external=True, **ext)}, {"alpha": comp("alpha", ["ext"]), "zeta": comp("zeta", ["ext"])})


def test_an_external_resource_runs_nothing_and_is_synced_from_the_store_ac_115_9(tmp_path):  # AC-115.9
    g = ok(tmp_path, ext_doc())
    assert not [k for k in g if "/addons/" in k], "no cluster, no addon directory"
    assert not [k for k in g if k.endswith("cluster.yaml")]
    assert all(addon_names(g, e) == [] for e in ENVS)
    for e in ENVS:
        assert y(g, external_secret_path(e, "alpha", "ext")) == external_secret("ext", f"shop-{e}-ext")
    assert tree(tmp_path).get("operators/root.yaml") is None, "an external database needs no operator"


def test_the_external_secret_lives_in_the_first_using_overlay_only_ac_115_9(tmp_path):  # AC-115.9
    g = ok(tmp_path, ext_doc())
    assert not [k for k in g if "externalsecret-shop-ext-app" in k and "/zeta/" in k]
    assert "externalsecret-shop-ext-app.yaml" in kustomization(g, "dev", "alpha")["resources"]
    res = kustomization(g, "dev", "alpha")["resources"]
    assert res == sorted(res)
    assert "externalsecret-shop-ext-app.yaml" not in kustomization(g, "dev", "zeta")["resources"]


def test_the_owner_is_the_first_component_that_runs_in_the_environment_ac_115_9(tmp_path):  # AC-115.9
    doc = system({"ext": db(external=True)}, {"alpha": comp("alpha", ["ext"], envs=("dev",)), "zeta": comp("zeta", ["ext"])})
    g = ok(tmp_path, doc)
    assert external_secret_path("dev", "alpha", "ext") in g
    assert external_secret_path("prod", "zeta", "ext") in g and external_secret_path("prod", "alpha", "ext") not in g


def test_the_using_component_gets_the_same_variables_as_for_a_cluster_database_ac_115_9(tmp_path):  # AC-115.9
    g = ok(tmp_path, system({"ext": db(external=True), "other": db(external=True)}, {"api": comp("api", ["ext", "other"]), "web": comp("web", ["ext"])}))
    assert secret_vars(g, "dev", "web") == contract_vars("ext")
    assert secret_vars(g, "dev", "api") == {**contract_vars("ext", "EXT_"), **contract_vars("other", "OTHER_")}


def test_remote_path_and_refresh_interval_are_used_ac_115_9(tmp_path):  # AC-115.9
    g = ok(tmp_path, ext_doc(remote={"path": "{system}/{env}/{resource}", "refreshInterval": "30m"}))
    assert y(g, external_secret_path("staging", "alpha", "ext")) == external_secret("ext", "shop/staging/ext", "30m")


def test_the_store_comes_from_the_systems_secret_store_ac_115_9(tmp_path):  # AC-115.9
    store = {"name": "vault", "kind": "SecretStore"}
    doc = ext_doc()
    doc["secretStore"] = store
    g = ok(tmp_path, doc)
    assert y(g, external_secret_path("dev", "alpha", "ext")) == external_secret("ext", "shop-dev-ext", store=store)


def test_an_unused_external_resource_renders_nothing_ac_115_9(tmp_path):  # AC-115.9
    g = ok(tmp_path, system({"ext": db(external=True)}))
    assert not [k for k in g if "ext" in k.split("/")[-1] and "externalsecret" in k]


# ---------------- AC-115.10: per-environment override ----------------

def test_prod_can_be_external_while_dev_and_staging_run_the_database_ac_115_10(tmp_path):  # AC-115.10
    g = ok(tmp_path, system({"orders-db": db(instances={"prod": {"external": True}})}, {"api": comp("api", ["orders-db"])}))
    assert cluster(g, "dev", "orders-db")["metadata"]["name"] == "shop-orders-db" and cluster(g, "staging", "orders-db")
    assert f"{APP}/addons/prod/orders-db/cluster.yaml" not in g and addon_names(g, "prod") == []
    assert addon_names(g, "dev") == ["orders-db"] and addon_names(g, "staging") == ["orders-db"]
    assert y(g, external_secret_path("prod", "api", "orders-db")) == external_secret("orders-db", "shop-prod-orders-db")
    assert not [k for k in g if "externalsecret-shop-orders-db-app" in k and ("/dev/" in k or "/staging/" in k)]
    for e in ENVS:
        assert secret_vars(g, e, "api") == contract_vars("orders-db")


def test_an_instance_can_run_a_database_that_the_resource_declares_external_ac_115_10(tmp_path):  # AC-115.10
    doc = system({"orders-db": db(external=True, instances={"dev": {"external": False, "storage": "2Gi"}})}, {"api": comp("api", ["orders-db"])})
    g = ok(tmp_path, doc)
    assert cluster(g, "dev", "orders-db")["spec"]["storage"]["size"] == "2Gi"
    assert f"{APP}/addons/staging/orders-db/cluster.yaml" not in g and external_secret_path("staging", "api", "orders-db") in g


def test_the_instance_remote_overrides_the_resources_remote_per_key_ac_115_10(tmp_path):  # AC-115.10
    doc = system({"ext": db(external=True, remote={"path": "{system}-{env}-{resource}", "refreshInterval": "5m"},
                            instances={"prod": {"remote": {"path": "prod/{resource}"}}})}, {"api": comp("api", ["ext"])})
    g = ok(tmp_path, doc)
    assert y(g, external_secret_path("prod", "api", "ext")) == external_secret("ext", "prod/ext", "5m")
    assert y(g, external_secret_path("dev", "api", "ext")) == external_secret("ext", "shop-dev-ext", "5m")


# ---------------- AC-115.11: external errors ----------------

def test_external_without_a_secret_store_fails_naming_the_first_environment_ac_115_11(tmp_path):  # AC-115.11
    fails(tmp_path, system({"ext": db(external=True)}, {"api": comp("api", ["ext"])}, store=False),
          P + "resources.ext: external in dev needs the system's secretStore (declare secretStore: {name, kind})")


def test_an_external_prod_instance_without_a_secret_store_fails_ac_115_11(tmp_path):  # AC-115.11
    fails(tmp_path, system({"ext": db(instances={"prod": {"external": True}})}, {"api": comp("api", ["ext"])}, store=False),
          "resources.ext: external in prod needs the system's secretStore")


@pytest.mark.parametrize("key, value", [("version", 17), ("replicas", 2), ("storage", "1Gi"), ("resources", {"limits": {"memory": "1Gi"}})])
def test_an_external_instance_may_not_set_sizing_ac_115_11(tmp_path, key, value):  # AC-115.11
    doc = system({"ext": db(external=True, instances={"prod": {key: value}})}, {"api": comp("api", ["ext"])})
    fails(tmp_path, doc, P + f"resources.ext.instances.prod: an external resource runs nothing (remove {key})")


def test_an_instance_that_turns_external_on_may_not_set_sizing_ac_115_11(tmp_path):  # AC-115.11
    doc = system({"ext": db(instances={"prod": {"external": True, "storage": "9Gi"}})}, {"api": comp("api", ["ext"])})
    fails(tmp_path, doc, "resources.ext.instances.prod: an external resource runs nothing (remove storage)")


@pytest.mark.parametrize("key, value", [("version", 17), ("replicas", 2), ("storage", "1Gi"), ("resources", {"limits": {"memory": "1Gi"}})])
def test_top_level_sizing_of_a_resource_that_is_external_everywhere_fails_ac_115_11(tmp_path, key, value):  # AC-115.11
    fails(tmp_path, system({"ext": db(external=True, **{key: value})}, {"api": comp("api", ["ext"])}),
          P + f"resources.ext: external in every environment: an external resource runs nothing (remove {key})")


def test_top_level_sizing_is_fine_while_one_environment_runs_the_database_ac_115_11(tmp_path):  # AC-115.11
    g = ok(tmp_path, system({"d": db(storage="4Gi", instances={"prod": {"external": True}})}, {"api": comp("api", ["d"])}))
    assert cluster(g, "dev", "d")["spec"]["storage"]["size"] == "4Gi"


def test_remote_on_a_resource_that_is_not_external_fails_ac_115_11(tmp_path):  # AC-115.11
    fails(tmp_path, system({"d": db(remote={"path": "x"})}, {"api": comp("api", ["d"])}), P + "resources.d: remote needs external: true")


def test_remote_on_an_instance_that_is_not_external_fails_ac_115_11(tmp_path):  # AC-115.11
    fails(tmp_path, system({"d": db(instances={"prod": {"remote": {"path": "x"}}})}, {"api": comp("api", ["d"])}),
          P + "resources.d.instances.prod: remote needs external: true in prod")


@pytest.mark.parametrize("bad", ["yes", "true", "False"])
def test_external_must_be_true_or_false_ac_115_11(tmp_path, bad):  # AC-115.11
    fails(tmp_path, system({"d": db(external=bad)}, {"api": comp("api", ["d"])}), P + "resources.d: external must be true or false")


def test_an_instance_external_must_be_true_or_false_ac_115_11(tmp_path):  # AC-115.11
    fails(tmp_path, system({"d": db(instances={"prod": {"external": "yes"}})}, {"api": comp("api", ["d"])}),
          P + "resources.d.instances.prod: external must be true or false")


def test_the_remote_keys_are_checked_ac_115_11(tmp_path):  # AC-115.11
    fails(tmp_path / "key", system({"d": db(external=True, remote={"url": "x"})}, {"api": comp("api", ["d"])}),
          "resources.d.remote: unknown key 'url' (allowed: path, refreshInterval)")
    fails(tmp_path / "ph", system({"d": db(external=True, remote={"path": "{component}/x"})}, {"api": comp("api", ["d"])}),
          "resources.d.remote.path")
    fails(tmp_path / "ri", system({"d": db(external=True, remote={"refreshInterval": 5})}, {"api": comp("api", ["d"])}),
          "resources.d.remote.refreshInterval must be a string, e.g. 1h")


def test_an_unknown_resource_key_and_an_unknown_instance_key_fail_ac_115_11(tmp_path):  # AC-115.11
    fails(tmp_path / "a", system({"d": db(size="big")}, {"api": comp("api", ["d"])}),
          "resources.d: unknown key 'size' (allowed: type, external, remote, version, replicas, storage, resources, instances)")
    fails(tmp_path / "b", system({"d": db(instances={"dev": {"size": 1}})}, {"api": comp("api", ["d"])}),
          "resources.d.instances.dev: unknown key 'size' (allowed: external, remote, replicas, storage, resources)")


# ---------------- AC-115.12: an incomplete store entry makes no Secret ----------------

def test_the_external_secret_asks_for_every_key_one_by_one_without_defaults_ac_115_12(tmp_path):  # AC-115.12
    g = ok(tmp_path, ext_doc())
    es = y(g, external_secret_path("dev", "alpha", "ext"))
    assert [d["secretKey"] for d in es["spec"]["data"]] == KEYS
    assert "dataFrom" not in es["spec"] and "template" not in es["spec"]["target"], "a partial store entry must not become a partial Secret"
    assert es["spec"]["target"]["creationPolicy"] == "Orphan"
    assert all(set(d["remoteRef"]) == {"key", "property"} and d["remoteRef"]["property"] == d["secretKey"] for d in es["spec"]["data"])
    assert not any("defaultValue" in str(d) or "default" in d["remoteRef"] for d in es["spec"]["data"])


def test_the_e2e_script_proves_the_missing_key_behaviour_in_a_cluster_ac_115_12():  # AC-115.12 (needs a cluster: covered by tests/e2e/run.sh)
    text = (ROOT / "tests" / "e2e" / "run.sh").read_text()
    assert "ext-db" in text and "password" in text and "ExternalSecret" in text


# ---------------- AC-115.17: exact pins ----------------

@pytest.mark.parametrize("version", [15, 16, 17, 18, "17"])
def test_the_cluster_runs_the_exact_pinned_image_ac_115_17(tmp_path, version):  # AC-115.17
    g = ok(tmp_path, system({"d": db(version=version)}, {"api": comp("api", ["d"])}))
    image = cluster(g, "dev", "d")["spec"]["imageName"]
    m = PIN_RE.match(image)
    assert m, f"{image} is not an exact pin (major.minor.patch-level tag, optionally a digest)"
    assert m.group(1) == str(version)
    r = platform_render_module("render_115_pins")
    assert image == r.POSTGRES_IMAGES[int(version)]


def test_the_default_version_is_17_and_pinned_ac_115_17(tmp_path):  # AC-115.17
    g = ok(tmp_path, system({"d": db()}, {"api": comp("api", ["d"])}))
    assert PIN_RE.match(cluster(g, "dev", "d")["spec"]["imageName"]).group(1) == "17"


@pytest.mark.parametrize("version", [14, 19, 9, "latest", "17.2", 17.5])
def test_an_unsupported_version_fails_naming_the_supported_majors_ac_115_17(tmp_path, version):  # AC-115.17
    fails(tmp_path, system({"d": db(version=version)}, {"api": comp("api", ["d"])}),
          P + f"resources.d: version '{version}' is not a supported database version (15, 16, 17, 18)")


def test_the_versions_table_is_exact_ac_115_17():  # AC-115.17
    r = platform_render_module("render_115_table")
    images = getattr(r, "POSTGRES_IMAGES", None)
    ops = getattr(r, "OPERATORS", None)
    assert images is not None and ops is not None, "render.py holds POSTGRES_IMAGES and OPERATORS"
    assert sorted(images) == [15, 16, 17, 18]
    for major, image in images.items():
        m = PIN_RE.match(image)
        assert m and m.group(1) == str(major), image
    op = ops["cloudnative-pg"]
    assert set(op) >= {"repo_url", "chart", "chart_version", "operator_version", "namespace", "release", "crd"}
    assert SEMVER.match(op["chart_version"]) and SEMVER.match(op["operator_version"])
    assert (op["repo_url"], op["chart"], op["namespace"], op["release"], op["crd"]) == (
        "https://cloudnative-pg.github.io/charts", "cloudnative-pg", "cnpg-system", "cnpg", "clusters.postgresql.cnpg.io")


# ---------------- AC-115.18: operators ----------------

def op_doc(**envs):
    doc = system({"orders-db": db()}, {"api": comp("api", ["orders-db"])})
    for e, v in envs.items():
        doc["environments"][e]["operators"] = v
    return doc


def test_a_database_renders_the_operator_once_outside_the_system_tree_ac_115_18(tmp_path):  # AC-115.18
    g = ok(tmp_path, op_doc())
    assert sorted(k for k in g if k.startswith("operators/")) == ["operators/apps/cloudnative-pg.yaml", "operators/root.yaml"]
    r = platform_render_module("render_115_ops")
    op = r.OPERATORS["cloudnative-pg"]
    server = sets(g)["shop-dev"]["spec"]["template"]["spec"]["destination"]["server"]
    repo = sets(g)["shop-dev"]["spec"]["template"]["spec"]["source"]["repoURL"]
    assert y(g, "operators/root.yaml") == {
        "apiVersion": "argoproj.io/v1alpha1", "kind": "Application", "metadata": {"name": "platform-operators", "namespace": "argocd"},
        "spec": {"project": "default", "source": {"repoURL": repo, "targetRevision": "main", "path": "operators/apps"},
                 "destination": {"server": server, "namespace": "argocd"}, "syncPolicy": {"automated": {"prune": True, "selfHeal": True}}}}
    assert y(g, "operators/apps/cloudnative-pg.yaml") == {
        "apiVersion": "argoproj.io/v1alpha1", "kind": "Application",
        "metadata": {"name": "operator-cloudnative-pg", "namespace": "argocd",
                     "labels": {"app.kubernetes.io/managed-by": "gitops-app", "app.kubernetes.io/component": "operator"}},
        "spec": {"project": "default",
                 "source": {"repoURL": op["repo_url"], "chart": "cloudnative-pg", "targetRevision": op["chart_version"], "helm": {"releaseName": "cnpg"}},
                 "destination": {"server": server, "namespace": "cnpg-system"},
                 "syncPolicy": {"automated": {"prune": True, "selfHeal": True}, "syncOptions": ["CreateNamespace=true", "ServerSideApply=true"]}}}
    assert not [k for k in g if k.startswith(APP) and "operator" in k.lower()], "applications/<system>/ carries no operator"


def test_several_databases_still_render_one_operator_ac_115_18(tmp_path):  # AC-115.18
    g = ok(tmp_path, two_dbs())
    assert sorted(k for k in g if k.startswith("operators/")) == ["operators/apps/cloudnative-pg.yaml", "operators/root.yaml"]


def test_no_database_means_no_operators_folder_ac_115_18(tmp_path):  # AC-115.18
    for label, doc in (("none", system(None)), ("external", ext_doc()), ("unused", system({"d": db()})), ("5.0 without resources", tiny())):
        g = ok(tmp_path / label, doc)
        assert not [k for k in g if k.startswith("operators/")], label
        assert not (tmp_path / label / "operators").exists(), label


def test_owner_managed_environments_get_no_operator_ac_115_18(tmp_path):  # AC-115.18
    g = ok(tmp_path / "all", op_doc(dev="owner", staging="owner", prod="owner"))
    assert not [k for k in g if k.startswith("operators/")]
    g = ok(tmp_path / "some", op_doc(prod="owner"))
    assert "operators/apps/cloudnative-pg.yaml" in g, "dev and staging are still platform-managed"
    doc = system({"d": db(instances={"prod": {"external": True}})}, {"api": comp("api", ["d"])})
    doc["environments"]["dev"]["operators"] = doc["environments"]["staging"]["operators"] = "owner"
    assert not [k for k in ok(tmp_path / "ext", doc) if k.startswith("operators/")], "prod is external, dev and staging are owner-managed"


@pytest.mark.parametrize("value", ["platform", "Owner", True, "", "none"])
def test_any_operators_value_but_owner_fails_naming_environment_and_owner_ac_115_18(tmp_path, value):  # AC-115.18
    doc = op_doc()
    doc["environments"]["staging"]["operators"] = value
    fails(tmp_path, doc, P + f"environments.staging.operators must be owner, got '{value}'")


def test_operators_is_an_allowed_environment_key_ac_115_18(tmp_path):  # AC-115.18 (adds to AC-114.4)
    doc = op_doc()
    doc["environments"]["staging"]["replicas"] = 2
    fails(tmp_path, doc, "environments.staging: unknown key 'replicas' (allowed: host, url, policy, promote, observability, operators, autonomy)")  # spec 124: autonomy


def test_check_mode_covers_the_operators_and_stale_ones_go_ac_115_18(tmp_path):  # AC-115.18
    import subprocess
    import sys
    ok(tmp_path, op_doc())
    check = lambda: subprocess.run([sys.executable, "scripts/render.py", "--check"], cwd=tmp_path, capture_output=True, text=True)
    assert check().returncode == 0
    f = tmp_path / "operators" / "apps" / "cloudnative-pg.yaml"
    f.write_text(f.read_text() + "# hand edit\n")
    assert check().returncode == 1
    subprocess.run([sys.executable, "scripts/render.py"], cwd=tmp_path, check=True, capture_output=True)
    assert check().returncode == 0
    (tmp_path / "applications" / "shop" / "system.yaml").write_text(yaml.safe_dump(system(None), sort_keys=False))
    subprocess.run([sys.executable, "scripts/render.py"], cwd=tmp_path, check=True, capture_output=True)
    assert not (tmp_path / "operators").exists(), "operators/ is removed when no environment needs an operator"


def test_the_template_applies_the_operators_before_the_systems_ac_115_18():  # AC-115.18
    t = ROOT / "templates" / "gitops-app"
    boot = t / "scripts" / "bootstrap.sh"
    assert boot.is_file(), "scripts/bootstrap.sh is new"
    text = boot.read_text()
    assert "operators/root.yaml" in text and re.search(r"\bclusters\.postgresql\.cnpg\.io\b", text) and "KUBE_CONTEXT" in text
    assert text.index("operators/root.yaml") < text.index("bootstrap/")
    assert "bash scripts/bootstrap.sh" in (t / "devbox.json").read_text()
    local = (t / "scripts" / "local-cluster.sh").read_text()
    assert "operators/apps/cloudnative-pg.yaml" in local and "operators/root.yaml" in local
    assert "CloudNativePG was installed by an older cluster-up (HelmChart kube-system/cnpg); keeping it. Recreate the cluster to let Argo CD manage it" in local
