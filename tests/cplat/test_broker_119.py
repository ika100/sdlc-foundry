"""Spec 119 acceptance tests, the renderer part: the `broker` resource type and `apis.<a>.broker` (AC-119.1 .. .3, .5 .. .12, .14, .16, .17,
.20 .. .24).

Contract: design.md "Contract: system.yaml", "Render errors", "Renderer API", "what a component gets", "in-cluster broker instance",
"external broker instance", "render notes" and "versions table". The renderer runs as a script in a hand-built checkout
(resources_fixtures); nothing touches the network or a cluster. Criteria that need a cluster (AC-119.13, .16 behaviour, .19) are covered by
the rendered contract here and by the text of tests/e2e/run.sh in test_broker_119_cmds.py. Missing symbols are guarded with getattr so each
test fails on its own."""
import re

import pytest
import yaml

from broker_fixtures import (ALLOWED_INST, ALLOWED_TOP, BKEYS, BVARS, CHART, CRED_FILES, DEFAULT_RESOURCES, FILES, NACK, NATS_IMAGES, P, RETRY, SIZING, bdir, bdoc, cplan,
                             broker, bsys, contract, events, expected_account, expected_consumer, expected_external_secret,
                             expected_kustomization, expected_nack_application, expected_plan, expected_server, expected_stream,
                             ext_comp, lib_comp, shape, tree_digest, upper, wide)
from cache_fixtures import cache
from resources_fixtures import (APP, ENVS, addon_names, comp, db, env_list, fails, ok, platform_render_module, render, render5, render_50,
                                secret_vars, sets, system, tree, unpin, var_order, y)  # spec 121: unpin
from system_fixtures import full5, rich5, write_system

USERS = [("api", ["orders"], []), ("web", [], ["orders"])]
WIDE_USERS = [("api", ["orders"], []), ("web", ["audit"], ["orders"]), ("worker", [], ["orders", "audit"])]


def renderer(name="render_119"):
    return platform_render_module(name)


def effective(tmp_path, doc, name="bus") -> dict:
    r = renderer("render_119_api")
    return r.load_system(write_system(tmp_path, doc))["cfg"]["resources"][name]["envs"]


def loaded(tmp_path, doc) -> dict:
    return renderer("render_119_load").load_system(write_system(tmp_path, doc))


def run_again(tmp_path, doc, *args):
    """Render a changed system.yaml into the same checkout (stale files, notes)."""
    return render5(tmp_path, doc, *args)


def lines(p) -> list[str]:
    return p.stdout.strip().splitlines()


def files_of(g, env, name="bus") -> list[str]:
    return sorted(k.rsplit("/", 1)[-1] for k in g if k.startswith(bdir(env, name) + "/"))


# ---------------- AC-119.1: schema ----------------

def test_a_broker_with_all_its_keys_is_accepted_ac_119_1(tmp_path):  # AC-119.1
    res = {"bus": broker(version="2.14", replicas=3, storage="5Gi", resources=DEFAULT_RESOURCES,
                         instances={"dev": {"replicas": 1, "storage": "2Gi"}, "prod": {"replicas": 3, "storage": "10Gi", "resources": DEFAULT_RESOURCES}})}
    ok(tmp_path, bsys(res))


def test_a_broker_with_the_external_keys_of_spec_115_is_accepted_ac_119_1(tmp_path):  # AC-119.1
    res = {"bus": broker(external=True, remote={"path": "{env}/{resource}/{component}", "refreshInterval": "2h"})}
    ok(tmp_path, bsys(res))


def test_an_unknown_broker_key_fails_naming_resource_key_and_allowed_keys_ac_119_1(tmp_path):  # AC-119.1
    fails(tmp_path, bsys({"bus": broker(memory="1Gi")}), P + f"resources.bus: unknown key 'memory' (allowed: {ALLOWED_TOP})")


@pytest.mark.parametrize("key", ["versioning", "persistence", "backup", "maxmemoryPolicy"])
def test_other_unknown_top_level_keys_fail_ac_119_1(tmp_path, key):  # AC-119.1
    fails(tmp_path, bsys({"bus": broker(**{key: 1})}), P + f"resources.bus: unknown key '{key}' (allowed: {ALLOWED_TOP})")


@pytest.mark.parametrize("key", ["backup", "bogus"])  # spec 121: version is an instance key
def test_an_unknown_instance_key_fails_ac_119_1(tmp_path, key):  # AC-119.1
    fails(tmp_path, bsys({"bus": broker(instances={"dev": {key: 1}})}), P + f"resources.bus.instances.dev: unknown key '{key}' (allowed: {ALLOWED_INST})")


def test_instances_must_be_a_mapping_ac_119_1(tmp_path):  # AC-119.1
    fails(tmp_path, bsys({"bus": broker(instances=["dev"])}),
          P + "resources.bus.instances must be a mapping of environments to {external, remote, replicas, storage, resources, version}")   # spec 121: version per environment


def test_an_unused_broker_is_validated_too_ac_119_1(tmp_path):  # AC-119.1
    fails(tmp_path, bsys({"bus": broker(bogus=1)}, {"api": comp("api")}, apis={}), "resources.bus: unknown key 'bogus'")


@pytest.mark.parametrize("key, value", [("replicas", 3), ("storage", "5Gi"), ("resources", DEFAULT_RESOURCES)])
def test_an_external_instance_may_not_set_sizing_ac_119_1(tmp_path, key, value):  # AC-119.1
    fails(tmp_path, bsys({"bus": broker(instances={"prod": {"external": True, key: value}})}),
          P + f"resources.bus.instances.prod: an external resource runs nothing (remove {key})")


def test_the_external_sizing_check_comes_before_the_unknown_key_check_ac_119_1(tmp_path):  # AC-119.1
    fails(tmp_path, bsys({"bus": broker(instances={"prod": {"external": True, "replicas": 3, "bogus": 1}})}),
          P + "resources.bus.instances.prod: an external resource runs nothing (remove replicas)")


@pytest.mark.parametrize("key, value", [("version", "2.15"), ("replicas", 3), ("storage", "5Gi"), ("resources", DEFAULT_RESOURCES)])
def test_top_level_sizing_of_a_broker_that_is_external_everywhere_fails_ac_119_1(tmp_path, key, value):  # AC-119.1
    fails(tmp_path, bsys({"bus": broker(external=True, **{key: value})}),
          P + f"resources.bus: external in every environment: an external resource runs nothing (remove {key})")


def test_top_level_sizing_is_fine_while_one_environment_runs_the_broker_ac_119_1(tmp_path):  # AC-119.1
    ok(tmp_path, bsys({"bus": broker(replicas=3, storage="2Gi", instances={"prod": {"external": True}})}))


def test_an_external_broker_needs_the_secret_store_ac_119_1(tmp_path):  # AC-119.1
    fails(tmp_path, bsys({"bus": broker(external=True)}, store=False), "secretStore")


def test_remote_path_of_a_broker_allows_the_component_placeholder_ac_119_1(tmp_path):  # AC-119.1
    ok(tmp_path, bsys({"bus": broker(external=True, remote={"path": "{system}/{env}/{resource}/{component}"})}))


def test_remote_path_of_a_broker_refuses_other_placeholders_ac_119_1(tmp_path):  # AC-119.1
    fails(tmp_path, bsys({"bus": broker(external=True, remote={"path": "{env}/{bogus}"})}),
          P + "resources.bus.remote.path: unknown placeholder {bogus} (allowed: {system}, {env}, {resource}, {component})")


def test_the_component_placeholder_is_a_broker_only_placeholder_ac_119_1(tmp_path):  # AC-119.1
    ok(tmp_path / "a", bsys({"bus": broker(external=True, remote={"path": "{env}/{component}"})}))
    err = fails(tmp_path / "b", system({"d": db(external=True, remote={"path": "{env}/{component}"})}, {"api": comp("api", ["d"])}), "unknown placeholder {component}")
    assert "{system}, {env}, {resource})" in err


def test_a_broker_is_no_longer_a_planned_type_ac_119_1(tmp_path):  # AC-119.1
    r = renderer("render_119_planned")
    assert getattr(r, "PLANNED_TYPES", None) == {}
    assert "broker" in r.TYPES and tuple(r.RESOURCE_TYPES) == ("database", "bucket", "cache", "broker")


def test_one_server_per_environment_where_a_running_component_uses_the_broker_ac_119_1(tmp_path):  # AC-119.1
    comps = {"api": comp("api", provides=["orders"], envs=("dev",)), "web": comp("web", consumes=["orders"], envs=("dev", "staging"))}
    g = ok(tmp_path, bsys(comps=comps))
    assert [e for e in ENVS if f"{bdir(e)}/server.yaml" in g] == ["dev", "staging"]
    assert not [k for k in g if k.startswith(bdir("prod"))]
    assert addon_names(g, "dev") == ["bus"] and addon_names(g, "staging") == ["bus"] and "bus" not in addon_names(g, "prod")


def test_an_unused_broker_renders_no_objects_ac_119_1(tmp_path):  # AC-119.1
    g = ok(tmp_path, bsys(comps={"api": comp("api")}, apis={}))
    assert not [k for k in g if "/addons/" in k] and not [k for k in g if k.startswith("operators/")]


def test_a_broker_directory_has_exactly_the_designed_files_in_every_environment_ac_119_1(tmp_path):  # AC-119.1
    g = ok(tmp_path, bsys())
    for env in ENVS:
        assert files_of(g, env) == FILES, env
        assert len([k for k in g if k.startswith(bdir(env) + "/")]) == len(FILES)


def test_the_addon_set_of_a_broker_environment_retries_its_sync_ac_119_1(tmp_path):  # AC-119.1
    comps = {"api": comp("api", provides=["orders"], envs=("dev", "staging")), "web": comp("web", consumes=["orders"], envs=("dev",))}
    g = ok(tmp_path, bsys(comps=comps))
    s = sets(g)["shop-addons-dev"]["spec"]
    assert s["template"]["spec"]["syncPolicy"]["retry"] == RETRY and s["template"]["spec"]["syncPolicy"]["automated"]["prune"] is False
    assert [e["name"] for e in s["generators"][0]["list"]["elements"]] == ["bus"]


def test_the_server_gets_the_replicas_and_storage_of_the_environment_ac_119_1(tmp_path):  # AC-119.1
    res = {"bus": broker(replicas=1, storage="2Gi", instances={"prod": {"replicas": 3, "storage": "10Gi"}})}
    g = ok(tmp_path, bsys(res))
    assert bdoc(g, "dev", "server.yaml") == expected_server(USERS, env="dev", storage="2Gi")
    assert bdoc(g, "prod", "server.yaml") == expected_server(USERS, env="prod", replicas=3, storage="10Gi")


def test_the_broker_is_validated_and_defaulted_in_the_renderer_api_ac_119_1(tmp_path):  # AC-119.1
    envs = effective(tmp_path, bsys({"bus": broker(replicas=3, instances={"dev": {"replicas": 1}})}))
    assert envs["dev"]["replicas"] == 1 and envs["staging"]["replicas"] == 3 and envs["prod"]["replicas"] == 3


# ---------------- AC-119.2: replicas ----------------

@pytest.mark.parametrize("good", [1, 3])
def test_one_and_three_replicas_are_accepted_ac_119_2(tmp_path, good):  # AC-119.2
    ok(tmp_path, bsys({"bus": broker(replicas=good)}))


@pytest.mark.parametrize("bad", [0, 2, 4, 5, -1, 1.5])
def test_any_other_replica_count_fails_saying_a_broker_runs_with_1_or_3_replicas_ac_119_2(tmp_path, bad):  # AC-119.2
    err = fails(tmp_path, bsys({"bus": broker(replicas=bad)}), P + f"resources.bus: a broker runs with 1 or 3 replicas (replicas: {bad})")
    assert "at least 1" not in err


def test_an_instance_replica_count_fails_naming_the_instance_ac_119_2(tmp_path):  # AC-119.2
    fails(tmp_path, bsys({"bus": broker(instances={"prod": {"replicas": 2}})}), P + "resources.bus.instances.prod: a broker runs with 1 or 3 replicas (replicas: 2)")


def test_the_three_value_checks_run_resource_first_then_instances_and_replicas_storage_resources_ac_119_2(tmp_path):  # AC-119.2
    both = broker(replicas=2, storage="big", instances={"dev": {"replicas": 4}})
    fails(tmp_path / "a", bsys({"bus": both}), P + "resources.bus: a broker runs with 1 or 3 replicas (replicas: 2)")
    only_storage = broker(storage="big", instances={"dev": {"replicas": 4}})
    fails(tmp_path / "b", bsys({"bus": only_storage}), P + "resources.bus: storage must be a size such as 1Gi")


def test_a_default_broker_runs_one_replica_and_its_streams_one_ac_119_2(tmp_path):  # AC-119.2
    g = ok(tmp_path, bsys())
    for env in ENVS:
        assert bdoc(g, env, "server.yaml")["spec"]["source"]["helm"]["valuesObject"]["config"]["cluster"] == {"enabled": False}
        assert bdoc(g, env, "stream-orders.yaml")["spec"]["replicas"] == 1


def test_three_replicas_cluster_the_server_and_keep_every_stream_on_three_ac_119_2(tmp_path):  # AC-119.2
    g = ok(tmp_path, wide({"bus": broker(replicas=3)}))
    for env in ENVS:
        cfg = bdoc(g, env, "server.yaml")["spec"]["source"]["helm"]["valuesObject"]["config"]
        assert cfg["cluster"] == {"enabled": True, "replicas": 3} and list(cfg["cluster"]) == ["enabled", "replicas"]
        assert bdoc(g, env, "server.yaml") == expected_server(WIDE_USERS, env=env, replicas=3)
        for api in ("orders", "audit"):
            assert bdoc(g, env, f"stream-{api}.yaml") == expected_stream(api, replicas=3)


def test_replicas_follow_the_environment_ac_119_2(tmp_path):  # AC-119.2
    g = ok(tmp_path, bsys({"bus": broker(instances={"prod": {"replicas": 3}})}))
    assert bdoc(g, "dev", "stream-orders.yaml")["spec"]["replicas"] == 1 and bdoc(g, "prod", "stream-orders.yaml")["spec"]["replicas"] == 3
    assert bdoc(g, "dev", "server.yaml")["spec"]["source"]["helm"]["valuesObject"]["config"]["cluster"] == {"enabled": False}


# ---------------- AC-119.3: defaults and values ----------------

def test_the_effective_values_default_to_2_15_one_replica_1gi_and_no_resources_ac_119_3(tmp_path):  # AC-119.3
    envs = effective(tmp_path, bsys())
    assert sorted(envs) == sorted(ENVS)
    for e in ENVS:
        assert envs[e] == {"external": False, "version": "2.15", "replicas": 1, "storage": "1Gi", "resources": None, "store_key": None,
                           "refreshInterval": None, "pin": "nats:2.15.2-alpine@sha256:823e7f1d6d8ffe3b30dbd73d4a06bbb939acf94929f7fdf224404da7a05bafb5", "chart_version": "2.15.1"}, e   # spec 121: pin and chart_version
        assert isinstance(envs[e]["version"], str) and isinstance(envs[e]["replicas"], int)


def test_the_effective_values_follow_instance_then_resource_then_default_ac_119_3(tmp_path):  # AC-119.3
    res = {"bus": broker(version="2.14", replicas=3, storage="2Gi", resources=DEFAULT_RESOURCES,
                         instances={"dev": {"replicas": 1, "storage": "3Gi"}, "prod": {"resources": {"limits": {"memory": "1Gi"}}}})}
    envs = effective(tmp_path, bsys(res))
    assert (envs["dev"]["version"], envs["dev"]["replicas"], envs["dev"]["storage"], envs["dev"]["resources"]) == ("2.14", 1, "3Gi", DEFAULT_RESOURCES)
    assert (envs["staging"]["replicas"], envs["staging"]["storage"]) == (3, "2Gi")
    assert (envs["prod"]["replicas"], envs["prod"]["resources"]) == (3, {"limits": {"memory": "1Gi"}})


@pytest.mark.parametrize("given, text", [(2.15, "2.15"), (2.14, "2.14"), ("2.15", "2.15"), ("2.14", "2.14")])
def test_a_float_or_a_string_version_is_read_as_its_text_ac_119_3(tmp_path, given, text):  # AC-119.3
    assert effective(tmp_path, bsys({"bus": broker(version=given)}))["dev"]["version"] == text


def test_an_external_instance_has_no_sizing_and_keeps_the_component_placeholder_ac_119_3(tmp_path):  # AC-119.3
    envs = effective(tmp_path, bsys({"bus": broker(instances={"prod": {"external": True}})}))
    assert envs["prod"] == {"external": True, "version": None, "replicas": None, "storage": None, "resources": None,
                            "store_key": "shop-prod-bus-{component}", "refreshInterval": "1h", "pin": None}   # spec 121: pin
    assert envs["dev"]["external"] is False and envs["dev"]["version"] == "2.15"


def test_a_default_broker_uses_the_pinned_server_1gi_and_the_default_requests_and_limits_ac_119_3(tmp_path):  # AC-119.3
    g = ok(tmp_path, bsys())
    for env in ENVS:
        values = bdoc(g, env, "server.yaml")["spec"]["source"]["helm"]["valuesObject"]
        assert values["container"]["image"] == {"repository": "nats", "tag": "2.15.2-alpine@sha256:823e7f1d6d8ffe3b30dbd73d4a06bbb939acf94929f7fdf224404da7a05bafb5"}  # spec 121: digest
        assert values["config"]["jetstream"]["fileStore"]["pvc"]["size"] == "1Gi"
        assert values["container"]["merge"]["resources"] == DEFAULT_RESOURCES
        assert bdoc(g, env, "server.yaml") == expected_server(USERS, env=env)


def test_given_sizing_reaches_the_server_ac_119_3(tmp_path):  # AC-119.3
    res = {"bus": broker(version="2.14", storage="5Gi", resources={"requests": {"cpu": "200m", "memory": "512Mi"}, "limits": {"memory": "1Gi"}})}
    g = ok(tmp_path, bsys(res))
    want = expected_server(USERS, version="2.14", storage="5Gi", resources={"requests": {"cpu": "200m", "memory": "512Mi"}, "limits": {"memory": "1Gi"}})
    assert bdoc(g, "dev", "server.yaml") == want


@pytest.mark.parametrize("bad", [2.13, "2.16", 3, "latest", 2, "2.15.2", 2.1])
def test_an_unsupported_version_fails_listing_the_supported_ones_ac_119_3(tmp_path, bad):  # AC-119.3
    fails(tmp_path, bsys({"bus": broker(version=bad)}), P + f"resources.bus: version '{bad}' is not a supported broker version (2.14, 2.15)")


def test_the_version_is_only_checked_where_some_environment_is_in_cluster_ac_119_3(tmp_path):  # AC-119.3
    fails(tmp_path, bsys({"bus": broker(version="2.13", instances={"prod": {"external": True}})}), "version '2.13' is not a supported broker version (2.14, 2.15)")


@pytest.mark.parametrize("bad", ["big", "1 Gi", "1GB", 10, "", "-1Gi"])
def test_storage_must_be_a_size_ac_119_3(tmp_path, bad):  # AC-119.3
    fails(tmp_path, bsys({"bus": broker(storage=bad)}), P + "resources.bus: storage must be a size such as 1Gi")


def test_an_instance_storage_must_be_a_size_ac_119_3(tmp_path):  # AC-119.3
    fails(tmp_path, bsys({"bus": broker(instances={"dev": {"storage": "lots"}})}), P + "resources.bus.instances.dev: storage must be a size such as 1Gi")


@pytest.mark.parametrize("bad", ["lots", 5, ["a"]])
def test_resources_must_be_a_mapping_ac_119_3(tmp_path, bad):  # AC-119.3
    fails(tmp_path, bsys({"bus": broker(resources=bad)}), P + "resources.bus: resources must be a mapping with requests and limits, "
          "e.g. {requests: {cpu: 100m, memory: 256Mi}, limits: {memory: 512Mi}}")


def test_an_instance_resources_must_be_a_mapping_ac_119_3(tmp_path):  # AC-119.3
    fails(tmp_path, bsys({"bus": broker(instances={"staging": {"resources": "lots"}})}), P + "resources.bus.instances.staging: resources must be a mapping")


DIGESTS = {"2.14.9-alpine": "127c5ccbc538a93f53ebb19461dc193130df386c2d6dab8199661a28a30d85bd",   # spec 121
           "2.15.2-alpine": "823e7f1d6d8ffe3b30dbd73d4a06bbb939acf94929f7fdf224404da7a05bafb5"}


@pytest.mark.parametrize("version, tag", [("2.14", "2.14.9-alpine"), ("2.15", "2.15.2-alpine")])
def test_each_minor_line_runs_its_pinned_release_ac_119_3(tmp_path, version, tag):  # AC-119.3
    values = bdoc(ok(tmp_path, bsys({"bus": broker(version=version)})), "dev", "server.yaml")["spec"]["source"]["helm"]["valuesObject"]
    assert values["container"]["image"] == {"repository": "nats", "tag": tag + "@sha256:" + DIGESTS[tag]}   # spec 121: digest


def test_a_version_change_changes_only_the_server_image_ac_119_3(tmp_path):  # AC-119.3
    a = ok(tmp_path / "a", bsys({"bus": broker(version="2.14")}))
    b = ok(tmp_path / "b", bsys({"bus": broker(version="2.15")}))
    assert sorted(k for k in a if a[k] != b.get(k)) == sorted(f"{bdir(e)}/server.yaml" for e in ENVS)


# ---------------- AC-119.5: binding ----------------

def test_an_explicit_broker_is_accepted_ac_119_5(tmp_path):  # AC-119.5
    g = ok(tmp_path, bsys(apis={"orders": {"type": "events", "broker": "bus"}}))
    assert f"{bdir('dev')}/stream-orders.yaml" in g


def test_a_broker_that_is_no_resource_fails_naming_the_api_and_the_brokers_ac_119_5(tmp_path):  # AC-119.5
    fails(tmp_path, bsys(apis={"orders": {"type": "events", "broker": "nope"}}),
          P + "apis.orders: broker 'nope' is not a broker resource of the system (brokers: bus)")


def test_a_resource_of_another_type_is_no_broker_ac_119_5(tmp_path):  # AC-119.5
    fails(tmp_path, bsys({"bus": broker(), "d": db()}, apis={"orders": {"type": "events", "broker": "d"}}),
          P + "apis.orders: broker 'd' is not a broker resource of the system (brokers: bus)")


def test_without_any_broker_the_choices_read_none_ac_119_5(tmp_path):  # AC-119.5
    fails(tmp_path, bsys({"d": db()}, apis={"orders": {"type": "events", "broker": "bus"}}),
          P + "apis.orders: broker 'bus' is not a broker resource of the system (brokers: none)")


def test_the_choices_list_every_broker_in_resource_order_ac_119_5(tmp_path):  # AC-119.5
    fails(tmp_path, bsys({"queue": broker(), "bus": broker()}, apis={"orders": {"type": "events", "broker": "nope"}}),
          P + "apis.orders: broker 'nope' is not a broker resource of the system (brokers: queue, bus)")


@pytest.mark.parametrize("bad", [5, ["bus"], True])
def test_a_broker_that_is_not_a_string_fails_the_same_way_ac_119_5(tmp_path, bad):  # AC-119.5
    fails(tmp_path, bsys(apis={"orders": {"type": "events", "broker": bad}}), f"apis.orders: broker '{bad}' is not a broker resource of the system (brokers: bus)")


def test_an_api_carried_by_a_broker_needs_a_dns_label_name_ac_119_5(tmp_path):  # AC-119.5
    comps = {"api": comp("api", provides=["Orders"]), "web": comp("web", consumes=["Orders"])}
    ok(tmp_path / "unbound", bsys({"d": db()}, comps, events("Orders")))      # no broker: the API stays unbound and may have any name
    fails(tmp_path, bsys(comps=comps, apis=events("Orders")),
          P + "apis.Orders: an events API carried by a broker needs a lowercase DNS label as its name "
          "(it names the stream shop-Orders and the subjects shop.Orders.>)")


def test_every_bound_api_gets_its_stream_in_the_chosen_broker_ac_119_5(tmp_path):  # AC-119.5
    comps = {"api": comp("api", provides=["orders", "jobs"]), "web": comp("web", consumes=["orders"]), "worker": comp("worker", consumes=["jobs"])}
    apis = {"orders": {"type": "events", "broker": "bus"}, "jobs": {"type": "events", "broker": "queue"}}
    g = ok(tmp_path, bsys({"bus": broker(), "queue": broker()}, comps, apis))
    assert f"{bdir('dev')}/stream-orders.yaml" in g and f"{bdir('dev', 'queue')}/stream-jobs.yaml" in g
    assert f"{bdir('dev')}/stream-jobs.yaml" not in g and f"{bdir('dev', 'queue')}/stream-orders.yaml" not in g
    assert addon_names(g, "dev") == ["bus", "queue"]


# ---------------- AC-119.6: the default binding ----------------

def test_an_events_api_without_broker_uses_the_only_broker_ac_119_6(tmp_path):  # AC-119.6
    g = ok(tmp_path, bsys())
    assert bdoc(g, "dev", "stream-orders.yaml") == expected_stream("orders")
    assert bdoc(g, "dev", "consumer-orders.web.yaml") == expected_consumer("orders", "web")


def test_an_explicit_broker_equals_the_default_when_there_is_only_one_ac_119_6(tmp_path):  # AC-119.6
    a = ok(tmp_path / "a", bsys())
    b = ok(tmp_path / "b", bsys(apis={"orders": {"type": "events", "broker": "bus"}}))
    assert a == b


def test_several_brokers_without_a_choice_fail_listing_them_ac_119_6(tmp_path):  # AC-119.6
    fails(tmp_path, bsys({"bus": broker(), "queue": broker()}),
          P + "apis.orders: the system has several brokers (bus, queue): choose one with apis.orders.broker")


def test_several_brokers_with_a_choice_render_ac_119_6(tmp_path):  # AC-119.6
    ok(tmp_path, bsys({"bus": broker(), "queue": broker()}, apis={"orders": {"type": "events", "broker": "queue"}}))


NOTE = "note: applications/shop: events API {a} is carried by no broker yet: add one with /resource:add <name> --type broker"


def test_an_events_api_with_no_broker_stays_unbound_and_prints_a_note_ac_119_6(tmp_path):  # AC-119.6
    p = render5(tmp_path, bsys({"d": db()}))
    assert p.returncode == 0, p.stderr
    assert len(lines(p)) == 2 and lines(p)[0] == NOTE.format(a="orders") and lines(p)[-1].startswith("rendered (")
    assert not [k for k in tree(tmp_path) if "/addons/" in k and "stream" in k]
    for c in ("api", "web"):    # an unbound API gives its components no variables
        assert [e["name"] for e in env_list(tree(tmp_path), "dev", c)] == ["PORT"]
    assert render5(tmp_path / "bound", bsys()).returncode == 0, "the same system with a broker renders"


def test_the_note_names_every_unbound_api_in_apis_order_ac_119_6(tmp_path):  # AC-119.6
    comps = {"api": comp("api", provides=["zeta", "alpha"]), "web": comp("web", consumes=["zeta"])}
    p = render5(tmp_path, bsys({"d": db()}, comps, events("zeta", "alpha")))
    assert lines(p)[:2] == [NOTE.format(a="zeta"), NOTE.format(a="alpha")] and lines(p)[-1].startswith("rendered (")


def test_the_note_also_prints_with_check_ac_119_6(tmp_path):  # AC-119.6
    doc = bsys({"d": db()})
    assert render5(tmp_path, doc).returncode == 0
    p = render5(tmp_path, doc, "--check")
    assert p.returncode == 0 and lines(p) == [NOTE.format(a="orders"), "OK: up to date"]


def test_no_note_when_the_api_is_bound_and_none_for_other_api_types_ac_119_6(tmp_path):  # AC-119.6
    p = render5(tmp_path / "a", bsys())
    assert p.returncode == 0 and "note:" not in p.stdout
    comps = {"api": comp("api", provides=["rest"]), "web": comp("web", consumes=["rest"])}
    q = render5(tmp_path / "b", bsys({"d": db()}, comps, {"rest": {"type": "openapi"}}))
    assert q.returncode == 0 and "note:" not in q.stdout


def test_notes_follow_the_system_order_ac_119_6(tmp_path):  # AC-119.6
    for name in ("beta", "alpha"):
        doc = bsys({"d": db()})
        doc["system"] = name
        write_system(tmp_path, doc, name)
    p = render(tmp_path)
    assert p.returncode == 0, p.stderr
    assert lines(p)[:2] == [f"note: applications/{n}: events API orders is carried by no broker yet: add one with /resource:add <name> --type broker"
                            for n in ("alpha", "beta")]


# ---------------- AC-119.7: implicit use ----------------

def test_a_provider_and_a_consumer_use_the_broker_without_listing_it_ac_119_7(tmp_path):  # AC-119.7
    g = ok(tmp_path, bsys())
    assert secret_vars(g, "dev", "api") == contract("bus", "api") and secret_vars(g, "dev", "web") == contract("bus", "web")


def test_the_effective_uses_of_a_service_end_with_the_brokers_of_its_apis_ac_119_7(tmp_path):  # AC-119.7
    sys_ = loaded(tmp_path, bsys({"bus": broker(), "d": db()}, {"api": comp("api", ["d"], provides=["orders"]), "web": comp("web", consumes=["orders"]),
                                                              "jobs": comp("jobs", ["d"])}))
    assert {s["name"]: s["uses"] for s in sys_["services"]} == {"api": ["d", "bus"], "web": ["bus"], "jobs": ["d"]}


def test_listing_the_broker_changes_nothing_for_a_participant_ac_119_7(tmp_path):  # AC-119.7
    plain = bsys({"bus": broker(), "d": db()}, {"api": comp("api", ["d"], provides=["orders"]), "web": comp("web", consumes=["orders"])})
    listed = bsys({"bus": broker(), "d": db()}, {"api": comp("api", ["bus", "d"], provides=["orders"]), "web": comp("web", ["bus"], consumes=["orders"])})
    assert ok(tmp_path / "a", plain) == ok(tmp_path / "b", listed)
    assert {s["name"]: s["uses"] for s in loaded(tmp_path / "c", listed)["services"]} == {"api": ["d", "bus"], "web": ["bus"]}


def test_a_component_that_lists_a_broker_without_an_api_fails_ac_119_7(tmp_path):  # AC-119.7
    comps = {"api": comp("api", provides=["orders"]), "web": comp("web", consumes=["orders"]), "jobs": comp("jobs", ["bus"])}
    fails(tmp_path, bsys(comps=comps), P + "components.jobs: uses 'bus', a broker; a component reaches a broker through an events API it provides "
          "or consumes, and none of jobs's is carried by bus")


def test_a_component_on_the_other_brokers_api_may_not_list_this_broker_ac_119_7(tmp_path):  # AC-119.7
    comps = {"api": comp("api", provides=["orders", "jobs"]), "web": comp("web", ["bus"], consumes=["jobs"]), "worker": comp("worker", consumes=["orders"])}
    apis = {"orders": {"type": "events", "broker": "bus"}, "jobs": {"type": "events", "broker": "queue"}}
    fails(tmp_path, bsys({"bus": broker(), "queue": broker()}, comps, apis), "components.web: uses 'bus', a broker; a component reaches a broker "
          "through an events API it provides or consumes, and none of web's is carried by bus")


def test_a_component_with_two_brokers_gets_them_in_provides_then_consumes_order_ac_119_7(tmp_path):  # AC-119.7
    comps = {"api": comp("api", provides=["orders"], consumes=["jobs"]), "web": comp("web", consumes=["orders"]), "worker": comp("worker", provides=["jobs"])}
    apis = {"orders": {"type": "events", "broker": "bus"}, "jobs": {"type": "events", "broker": "queue"}}
    doc = bsys({"queue": broker(), "bus": broker()}, comps, apis)
    assert {s["name"]: s["uses"] for s in loaded(tmp_path / "x", doc)["services"]}["api"] == ["bus", "queue"]
    g = ok(tmp_path / "y", doc)
    assert var_order(g, "dev", "api") == [f"{p}{v}" for p in ("BUS_", "QUEUE_") for v in BVARS]


def test_listing_the_broker_does_not_move_its_variables_ac_119_7(tmp_path):  # AC-119.7
    base = {"api": comp("api", ["d"], provides=["orders"]), "web": comp("web", consumes=["orders"])}
    first = {"api": comp("api", ["bus", "d"], provides=["orders"]), "web": comp("web", consumes=["orders"])}
    a = ok(tmp_path / "a", bsys({"bus": broker(), "d": db()}, base))
    b = ok(tmp_path / "b", bsys({"bus": broker(), "d": db()}, first))
    assert var_order(a, "dev", "api") == var_order(b, "dev", "api") == ["DATABASE_URL", "PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD", *BVARS]


# ---------------- AC-119.8: only events APIs ----------------

@pytest.mark.parametrize("kind", ["openapi", "grpc", "graphql"])
def test_broker_on_a_non_events_api_fails_naming_the_api_ac_119_8(tmp_path, kind):  # AC-119.8
    comps = {"api": comp("api", provides=["rest"]), "web": comp("web", consumes=["rest"])}
    fails(tmp_path, bsys(comps=comps, apis={"rest": {"type": kind, "broker": "bus"}}),
          P + f"apis.rest: only events APIs are carried by a broker (remove broker from this {kind} API)")


def test_the_broker_key_check_comes_before_the_resources_are_read_ac_119_8(tmp_path):  # AC-119.8
    comps = {"api": comp("api", provides=["rest"]), "web": comp("web", consumes=["rest"])}
    fails(tmp_path, bsys({"bus": broker(bogus=1)}, comps, {"rest": {"type": "openapi", "broker": "bus"}}), "apis.rest: only events APIs are carried by a broker")


def test_unknown_api_keys_name_the_allowed_ones_per_type_ac_119_8(tmp_path):  # AC-119.8
    fails(tmp_path / "a", bsys(apis={"orders": {"type": "events", "bogus": 1}}), P + "apis.orders: unknown key 'bogus' (allowed: type, broker)")
    comps = {"api": comp("api", provides=["rest"]), "web": comp("web", consumes=["rest"])}
    fails(tmp_path / "b", bsys(comps=comps, apis={"rest": {"type": "openapi", "bogus": 1}}), P + "apis.rest: unknown key 'bogus' (allowed: type)")


# ---------------- AC-119.9: streams ----------------

def test_the_stream_is_the_designed_document_in_every_environment_ac_119_9(tmp_path):  # AC-119.9
    g = ok(tmp_path, bsys())
    for env in ENVS:
        got = bdoc(g, env, "stream-orders.yaml")
        assert got == expected_stream("orders"), env
        assert shape(got) == shape(expected_stream("orders")), env


def test_a_stream_captures_exactly_its_subjects_and_keeps_messages_for_7_days_ac_119_9(tmp_path):  # AC-119.9
    spec = bdoc(ok(tmp_path, bsys()), "dev", "stream-orders.yaml")["spec"]
    assert spec["name"] == "shop-orders" and spec["subjects"] == ["shop.orders.>"] and spec["maxAge"] == "168h"
    assert spec["storage"] == "file" and spec["retention"] == "limits" and spec["discard"] == "old"


def test_one_stream_per_bound_api_whether_or_not_its_provider_runs_there_ac_119_9(tmp_path):  # AC-119.9
    comps = {"api": comp("api", provides=["orders"], envs=("prod",)), "web": comp("web", consumes=["orders"], provides=["audit"]),
             "worker": comp("worker", consumes=["audit"], envs=("prod",))}
    g = ok(tmp_path, bsys(comps=comps, apis=events("orders", "audit")))
    assert bdoc(g, "dev", "stream-orders.yaml") == expected_stream("orders") and bdoc(g, "dev", "stream-audit.yaml") == expected_stream("audit")
    assert sorted(k.rsplit("/", 1)[-1] for k in g if k.startswith(bdir("dev") + "/") and "/stream-" in k) == ["stream-audit.yaml", "stream-orders.yaml"]


def test_a_stream_name_is_unique_per_system_and_api_ac_119_9(tmp_path):  # AC-119.9
    g = ok(tmp_path, wide())
    names = [bdoc(g, "dev", f"stream-{a}.yaml")["metadata"]["name"] for a in ("orders", "audit")]
    assert names == ["shop-orders", "shop-audit"]


# ---------------- AC-119.10: durable consumers ----------------

def test_a_consumer_is_the_designed_document_ac_119_10(tmp_path):  # AC-119.10
    g = ok(tmp_path, bsys())
    for env in ENVS:
        got = bdoc(g, env, "consumer-orders.web.yaml")
        assert got == expected_consumer("orders", "web") and shape(got) == shape(expected_consumer("orders", "web")), env
        assert got["spec"]["ackPolicy"] == "explicit" and got["spec"]["ackWait"] == "30s" and got["spec"]["durableName"] == "web"


def test_each_consuming_component_has_its_own_consumer_and_a_provider_has_none_ac_119_10(tmp_path):  # AC-119.10
    g = ok(tmp_path, wide())
    consumers = sorted(k.rsplit("/", 1)[-1] for k in g if k.startswith(bdir("dev") + "/") and "/consumer-" in k)
    assert consumers == ["consumer-audit.worker.yaml", "consumer-orders.web.yaml", "consumer-orders.worker.yaml"]
    assert bdoc(g, "dev", "consumer-orders.worker.yaml") == expected_consumer("orders", "worker")
    assert bdoc(g, "dev", "consumer-audit.worker.yaml") == expected_consumer("audit", "worker")


def test_a_consuming_component_without_an_instance_has_no_consumer_there_ac_119_10(tmp_path):  # AC-119.10
    comps = {"api": comp("api", provides=["orders"]), "web": comp("web", consumes=["orders"], envs=("dev",))}
    g = ok(tmp_path, bsys(comps=comps))
    assert f"{bdir('dev')}/consumer-orders.web.yaml" in g
    for env in ("staging", "prod"):
        assert files_of(g, env) == ["account.yaml", *CRED_FILES, "kustomization.yaml", "server.yaml", "stream-orders.yaml"], env   # spec 128: no ExternalSecret files
        assert [x["name"] for x in cplan(g, env)["secrets"]] == ["shop-bus-nack", "shop-bus-api-app"], env


def test_the_consumers_are_pull_consumers_that_start_at_the_first_message_ac_119_10(tmp_path):  # AC-119.10
    spec = bdoc(ok(tmp_path, bsys()), "dev", "consumer-orders.web.yaml")["spec"]
    assert "deliverSubject" not in spec and spec["deliverPolicy"] == "all" and spec["maxDeliver"] == -1


def test_an_external_component_counts_as_a_consumer_ac_119_10(tmp_path):  # AC-119.10
    comps = {"api": comp("api", provides=["orders"]), "stock": ext_comp("stock", consumes=["orders"])}
    g = ok(tmp_path, bsys(comps=comps))
    assert bdoc(g, "dev", "consumer-orders.stock.yaml") == expected_consumer("orders", "stock")
    assert "shop-bus-stock-app" in [x["name"] for x in cplan(g)["secrets"]]   # spec 128: the credentials Job writes it


# ---------------- AC-119.11: the environment contract ----------------

def test_the_broker_type_contract_is_in_the_renderer_ac_119_11(tmp_path):  # AC-119.11
    t = getattr(renderer("render_119_types"), "TYPES", {}).get("broker")
    assert t is not None, "TYPES has a broker entry"
    assert t["keys"] == BKEYS and t["env"] == BVARS and list(t["env"]) == list(BVARS)


def test_a_participant_gets_the_three_variables_from_its_own_secret_in_table_order_ac_119_11(tmp_path):  # AC-119.11
    g = ok(tmp_path, bsys())
    for env in ENVS:
        for c in ("api", "web"):
            assert secret_vars(g, env, c) == contract("bus", c), (env, c)
            assert var_order(g, env, c) == list(BVARS)


def test_the_variables_are_secret_key_references_in_the_designed_form_ac_119_11(tmp_path):  # AC-119.11
    got = [e for e in env_list(ok(tmp_path, bsys()), "dev", "web") if e["name"] in BVARS]
    assert got == [{"name": v, "valueFrom": {"secretKeyRef": {"name": "shop-bus-web-app", "key": k}}} for v, k in BVARS.items()]


def test_a_provider_gets_the_stream_and_prefix_and_a_consumer_also_the_consumer_name_ac_119_11(tmp_path):  # AC-119.11
    g = ok(tmp_path, bsys())
    api = {e["name"]: e["value"] for e in env_list(g, "dev", "api") if "value" in e}
    web = {e["name"]: e["value"] for e in env_list(g, "dev", "web") if "value" in e}
    assert api == {"PORT": "8080", "EVENTS_ORDERS_STREAM": "shop-orders", "EVENTS_ORDERS_SUBJECT_PREFIX": "shop.orders", "NATS_INBOX_PREFIX": "_INBOX.api"}
    assert web == {"PORT": "8080", "EVENTS_ORDERS_STREAM": "shop-orders", "EVENTS_ORDERS_SUBJECT_PREFIX": "shop.orders",
                   "EVENTS_ORDERS_CONSUMER": "web", "NATS_INBOX_PREFIX": "_INBOX.web"}


def test_the_literal_variables_are_sorted_and_the_secret_variables_follow_ac_119_11(tmp_path):  # AC-119.11
    comps = {"api": comp("api", provides=["orders"], env={"LOG": "debug"}), "web": comp("web", consumes=["orders"])}
    names = [e["name"] for e in env_list(ok(tmp_path, bsys(comps=comps)), "dev", "api")]
    literals = [n for n in names if n not in BVARS]
    assert literals == sorted(literals) and "LOG" in literals and "NATS_INBOX_PREFIX" in literals and names == literals + list(BVARS)


def test_the_api_name_is_upper_cased_with_underscores_ac_119_11(tmp_path):  # AC-119.11
    comps = {"api": comp("api", provides=["order-events"]), "web": comp("web", consumes=["order-events"])}
    g = ok(tmp_path, bsys(comps=comps, apis=events("order-events")))
    web = {e["name"]: e["value"] for e in env_list(g, "dev", "web") if "value" in e}
    assert web["EVENTS_ORDER_EVENTS_STREAM"] == "shop-order-events" and web["EVENTS_ORDER_EVENTS_SUBJECT_PREFIX"] == "shop.order-events"
    assert web["EVENTS_ORDER_EVENTS_CONSUMER"] == "web"
    assert bdoc(g, "dev", "stream-order-events.yaml") == expected_stream("order-events")


def test_a_component_on_two_apis_gets_each_once_and_one_inbox_prefix_ac_119_11(tmp_path):  # AC-119.11
    g = ok(tmp_path, wide())
    web = [e for e in env_list(g, "dev", "web") if "value" in e]
    assert sorted(e["name"] for e in web) == sorted(["PORT", "EVENTS_ORDERS_STREAM", "EVENTS_ORDERS_SUBJECT_PREFIX", "EVENTS_ORDERS_CONSUMER",
                                                     "EVENTS_AUDIT_STREAM", "EVENTS_AUDIT_SUBJECT_PREFIX", "NATS_INBOX_PREFIX"])
    worker = {e["name"] for e in env_list(g, "dev", "worker") if "value" in e}
    assert {"EVENTS_ORDERS_CONSUMER", "EVENTS_AUDIT_CONSUMER"} <= worker and "EVENTS_ORDERS_STREAM" in worker
    api = {e["name"] for e in env_list(g, "dev", "api") if "value" in e}
    assert not [n for n in api if "AUDIT" in n]


def test_a_component_outside_the_events_apis_gets_no_broker_variables_ac_119_11(tmp_path):  # AC-119.11
    comps = {"api": comp("api", provides=["orders"]), "web": comp("web", consumes=["orders"]), "jobs": comp("jobs")}
    g = ok(tmp_path, bsys(comps=comps))
    assert [e["name"] for e in env_list(g, "dev", "jobs")] == ["PORT"]
    assert not [k for k in g if k.endswith("externalsecret-jobs.yaml")]


def test_a_broker_next_to_a_database_gives_bare_variables_ac_119_11(tmp_path):  # AC-119.11
    comps = {"api": comp("api", ["d"], provides=["orders"]), "web": comp("web", consumes=["orders"])}
    got = secret_vars(ok(tmp_path, bsys({"bus": broker(), "d": db()}, comps)), "dev", "api")
    assert got["DATABASE_URL"] == ("shop-d-app", "uri") and got["NATS_URL"] == ("shop-bus-api-app", "url") and not [n for n in got if n.startswith("BUS_")]


def test_two_brokers_get_prefixed_variables_and_their_own_secrets_ac_119_11(tmp_path):  # AC-119.11
    comps = {"api": comp("api", provides=["orders"], consumes=["jobs"]), "web": comp("web", consumes=["orders"]), "worker": comp("worker", provides=["jobs"])}
    apis = {"orders": {"type": "events", "broker": "bus"}, "jobs": {"type": "events", "broker": "queue"}}
    g = ok(tmp_path, bsys({"bus": broker(), "queue": broker()}, comps, apis))
    assert secret_vars(g, "dev", "api") == {**contract("bus", "api", "BUS_"), **contract("queue", "api", "QUEUE_")}
    assert secret_vars(g, "dev", "web") == contract("bus", "web")
    literals = {e["name"] for e in env_list(g, "dev", "api") if "value" in e}
    assert {"EVENTS_ORDERS_STREAM", "EVENTS_JOBS_STREAM", "EVENTS_JOBS_CONSUMER"} <= literals and "EVENTS_ORDERS_CONSUMER" not in literals


def test_each_component_has_its_own_user_secret_per_environment_ac_119_11(tmp_path):  # AC-119.11
    g = ok(tmp_path, bsys())
    for env in ENVS:
        assert cplan(g, env) == expected_plan(["api", "web"], env), env   # spec 128: one Secret per user in the Job's plan, not an ExternalSecret
        assert not [k for k in g if k.startswith(bdir(env)) and "externalsecret" in k]
    assert cplan(g, "staging")["secrets"][2]["data"]["url"] == "nats://shop-bus.shop-staging.svc:4222"


def test_the_credentials_job_and_the_admin_secret_are_the_designed_documents_ac_119_11(tmp_path):  # AC-119.11
    g = ok(tmp_path, bsys())
    for env in ENVS:
        plan = cplan(g, env)
        assert plan == expected_plan(["api", "web"], env) and list(plan["secrets"][0]["data"]) == ["user"]   # spec 128: `_nack` and its generated password
        assert plan["secrets"][0]["generate"] == {"password": 32} and plan["retire"]["generators"] == ["shop-bus-password"]
        assert not [k for k in g if k.startswith(bdir(env)) and ("password-generator" in k or "nack-secret" in k)]
        assert bdoc(g, env, "credentials-job.yaml")["kind"] == "Job"
    assert [list(x["data"]) for x in cplan(g)["secrets"][1:]] == [["url", "user"]] * 2


def test_the_secret_names_never_change_with_the_sizing_ac_119_11(tmp_path):  # AC-119.11
    a = ok(tmp_path / "a", bsys())
    b = ok(tmp_path / "b", bsys({"bus": broker(version="2.14", replicas=3, storage="5Gi")}))
    for env in ENVS:
        assert [x["name"] for x in cplan(a, env)["secrets"]] == [x["name"] for x in cplan(b, env)["secrets"]], env   # spec 128: the plan's Secrets
        assert cplan(b, env)["verify"]["pods"] == ["shop-bus-0", "shop-bus-1", "shop-bus-2"]
        assert a[f"{bdir(env)}/account.yaml"] == b[f"{bdir(env)}/account.yaml"], env


def test_no_password_value_appears_in_the_rendered_tree_ac_119_11(tmp_path):  # AC-119.11
    g = ok(tmp_path, wide())
    broker_files = {k: t for k, t in g.items() if "/addons/" in k}
    assert broker_files
    for k, t in broker_files.items():
        for m in re.finditer(r"(?im)^[ \t]*(password|user)[ \t]*:[ \t]*(.+)$", t):  # spec 119 slip: \s* crossed the newline after a mapping key
            assert re.fullmatch(r"""["']?(\{\{ \.password \}\}|<< \$[A-Z_]+ >>|password|[a-z_-]+)["']?""", m.group(2).strip()), f"{k}: {m.group(0)!r}"
    for e in env_list(g, "dev", "api"):
        if "NATS_PASSWORD" in e["name"]:
            assert "value" not in e


@pytest.mark.parametrize("name", ["NATS_URL", "NATS_USER", "NATS_PASSWORD", "NATS_INBOX_PREFIX", "EVENTS_ORDERS_STREAM", "EVENTS_ORDERS_SUBJECT_PREFIX"])
def test_an_env_name_that_clashes_with_a_broker_variable_fails_ac_119_11(tmp_path, name):  # AC-119.11
    comps = {"api": comp("api", provides=["orders"], env={name: "x"}), "web": comp("web", consumes=["orders"])}
    err = fails(tmp_path, bsys(comps=comps), P + f"components.api: env {name} is provided by the 'bus' resource; remove it from `env`")
    assert "not available yet" not in err


def test_the_consumer_variable_clashes_only_for_a_consumer_ac_119_11(tmp_path):  # AC-119.11
    comps = {"api": comp("api", provides=["orders"], env={"EVENTS_ORDERS_CONSUMER": "x"}), "web": comp("web", consumes=["orders"])}
    ok(tmp_path / "a", bsys(comps=comps))
    comps = {"api": comp("api", provides=["orders"]), "web": comp("web", consumes=["orders"], env={"EVENTS_ORDERS_CONSUMER": "x"})}
    fails(tmp_path / "b", bsys(comps=comps), "components.web: env EVENTS_ORDERS_CONSUMER is provided by the 'bus' resource")


def test_a_component_secret_named_like_a_user_secret_fails_ac_119_11(tmp_path):  # AC-119.11
    comps = {"api": comp("api", provides=["orders"], secrets=[{"name": "shop-bus-api-app", "generate": ["K"]}]), "web": comp("web", consumes=["orders"])}
    fails(tmp_path, bsys(comps=comps), "components.api: secret 'shop-bus-api-app' is the connection Secret of resources.bus; rename it")


@pytest.mark.parametrize("suffix", ["headless", "config", "nack", "password"])
def test_a_resource_that_would_create_a_broker_object_fails_ac_119_11(tmp_path, suffix):  # AC-119.11
    fails(tmp_path, bsys({"bus": broker(), f"bus-{suffix}": cache()}), f"would both create the object shop-bus-{suffix}; rename one")


def test_a_resource_named_like_a_user_secret_object_fails_ac_119_11(tmp_path):  # AC-119.11
    fails(tmp_path, bsys({"bus": broker(), "bus-api": cache()}), "would both create the object shop-bus-api-app; rename one")


def test_a_library_and_an_external_component_get_no_variables_ac_119_11(tmp_path):  # AC-119.11
    comps = {"api": comp("api", provides=["orders"]), "stock": ext_comp("stock", consumes=["orders"]), "lib": lib_comp("lib", consumes=["orders"])}
    g = ok(tmp_path, bsys(comps=comps))
    assert not [k for k in g if "/overlays/" in k and k.endswith("deployment.yaml") and "/lib/" in k]
    stock = [k for k in g if "/overlays/dev/stock/" in k]
    assert stock and not [k for k in stock if "NATS_" in g[k]]
    assert files_of(g, "dev") == ["account.yaml", "consumer-orders.stock.yaml", *CRED_FILES, "kustomization.yaml", "server.yaml", "stream-orders.yaml"]
    assert [x["name"] for x in cplan(g)["secrets"]] == ["shop-bus-nack", "shop-bus-api-app", "shop-bus-stock-app"]


# ---------------- AC-119.12: users and rights ----------------

def test_the_server_is_the_designed_document_with_one_user_per_component_ac_119_12(tmp_path):  # AC-119.12
    g = ok(tmp_path, wide())
    for env in ENVS:
        got = bdoc(g, env, "server.yaml")
        assert got == expected_server(WIDE_USERS, env=env), env
        assert shape(got) == shape(expected_server(WIDE_USERS, env=env)), env


def test_the_provider_may_publish_on_its_subjects_and_a_consumer_only_through_its_consumer_ac_119_12(tmp_path):  # AC-119.12
    users = {u["user"]: u for u in bdoc(ok(tmp_path, wide()), "dev", "server.yaml")["spec"]["source"]["helm"]["valuesObject"]["config"]["merge"]["authorization"]["users"]}
    assert users["api"]["permissions"]["publish"]["allow"] == ["shop.orders.>"]
    assert users["web"]["permissions"]["publish"]["allow"] == ["shop.audit.>", "$JS.API.CONSUMER.INFO.shop-orders.web", "$JS.API.CONSUMER.MSG.NEXT.shop-orders.web",
                                                              "$JS.ACK.shop-orders.web.>", "$JS.ACK.*.*.shop-orders.web.>"]
    assert "shop.orders.>" not in users["web"]["permissions"]["publish"]["allow"] and not [s for s in users["worker"]["permissions"]["publish"]["allow"] if s.startswith("shop.")]


def test_a_component_outside_an_api_has_no_right_to_its_subjects_ac_119_12(tmp_path):  # AC-119.12
    users = {u["user"]: u for u in bdoc(ok(tmp_path, wide()), "dev", "server.yaml")["spec"]["source"]["helm"]["valuesObject"]["config"]["merge"]["authorization"]["users"]}
    assert not [s for s in users["api"]["permissions"]["publish"]["allow"] if "audit" in s]
    for u, d in users.items():
        if u != "_nack":
            assert d["permissions"]["subscribe"]["allow"] == [f"_INBOX.{u}.>"], u


def test_the_admin_user_has_no_permissions_and_the_passwords_come_from_the_secrets_ac_119_12(tmp_path):  # AC-119.12
    values = bdoc(ok(tmp_path, wide()), "dev", "server.yaml")["spec"]["source"]["helm"]["valuesObject"]
    users = values["config"]["merge"]["authorization"]["users"]
    assert users[0] == {"user": "_nack", "password": "<< $ADMIN_PASSWORD >>"} and [u["user"] for u in users] == ["_nack", "api", "web", "worker"]
    assert list(values["container"]["env"]) == ["ADMIN_PASSWORD", "USER_API_PASSWORD", "USER_WEB_PASSWORD", "USER_WORKER_PASSWORD"]
    assert values["container"]["env"]["USER_WORKER_PASSWORD"] == {"valueFrom": {"secretKeyRef": {"name": "shop-bus-worker-app", "key": "password"}}}


def test_the_users_of_an_environment_are_the_components_running_there_ac_119_12(tmp_path):  # AC-119.12
    comps = {"api": comp("api", provides=["orders"]), "web": comp("web", consumes=["orders"], envs=("dev",))}
    g = ok(tmp_path, bsys(comps=comps))
    assert bdoc(g, "dev", "server.yaml") == expected_server(USERS, env="dev")
    assert bdoc(g, "staging", "server.yaml") == expected_server([("api", ["orders"], [])], env="staging")
    assert "shop-bus-web-app" not in [x["name"] for x in cplan(g, "staging")["secrets"]]


def test_a_consumer_never_names_another_components_secret_ac_119_12(tmp_path):  # AC-119.12
    g = ok(tmp_path, wide())
    for c in ("api", "web", "worker"):
        secrets = {name for name, _ in secret_vars(g, "dev", c).values()}
        assert secrets == {f"shop-bus-{c}-app"}, c


def test_a_component_name_with_a_dash_gets_an_upper_case_password_variable_ac_119_12(tmp_path):  # AC-119.12
    comps = {"order-api": comp("order-api", provides=["orders"]), "web": comp("web", consumes=["orders"])}
    values = bdoc(ok(tmp_path, bsys(comps=comps)), "dev", "server.yaml")["spec"]["source"]["helm"]["valuesObject"]
    assert "USER_ORDER_API_PASSWORD" in values["container"]["env"]
    assert values["container"]["env"]["USER_ORDER_API_PASSWORD"]["valueFrom"]["secretKeyRef"]["name"] == "shop-bus-order-api-app"


def test_the_account_of_the_controller_is_the_designed_document_ac_119_12(tmp_path):  # AC-119.12
    g = ok(tmp_path, bsys())
    for env in ENVS:
        got = bdoc(g, env, "account.yaml")
        assert got == expected_account(env) and shape(got) == shape(expected_account(env)), env


# ---------------- AC-119.14: nothing is deleted, the render says what is no longer declared ----------------

def retired(env, kind, *names) -> str:
    path = f"note: applications/shop/addons/{env}/bus: "
    if kind == "stream":
        return path + f"stream shop-{names[0]} is no longer declared; it and its messages stay on the broker until you delete them"
    return path + f"durable consumer {names[1]} of stream shop-{names[0]} is no longer declared; it stays on the broker until you delete it"


def test_streams_and_consumers_never_get_deleted_by_a_sync_ac_119_14(tmp_path):  # AC-119.14
    g = ok(tmp_path, bsys())
    for env in ENVS:
        for f in ("stream-orders.yaml", "consumer-orders.web.yaml"):
            spec = bdoc(g, env, f)
            assert spec["spec"]["preventDelete"] is True
            assert "Delete=false" in spec["metadata"]["annotations"]["argocd.argoproj.io/sync-options"]
            assert spec["metadata"]["annotations"]["argocd.argoproj.io/compare-options"] == "IgnoreExtraneous"
    s = sets(g)["shop-addons-dev"]
    assert s["spec"]["template"]["spec"]["syncPolicy"]["automated"]["prune"] is False


def test_a_removed_consumer_loses_its_files_and_the_render_prints_it_ac_119_14(tmp_path):  # AC-119.14
    assert render5(tmp_path, bsys()).returncode == 0
    comps = {"api": comp("api", provides=["orders"]), "web": comp("web")}
    p = run_again(tmp_path, bsys(comps=comps))
    assert p.returncode == 0, p.stderr
    g = tree(tmp_path)
    for env in ENVS:
        assert f"{bdir(env)}/consumer-orders.web.yaml" not in g and "shop-bus-web-app" not in [x["name"] for x in cplan(g, env)["secrets"]]
        assert f"{bdir(env)}/stream-orders.yaml" in g and f"{bdir(env)}/server.yaml" in g
    assert lines(p)[:-1] == [retired(e, "consumer", "orders", "web") for e in ("dev", "prod", "staging")]
    assert lines(p)[-1].startswith("rendered (")


def test_a_consumer_that_loses_its_instance_is_retired_in_that_environment_only_ac_119_14(tmp_path):  # AC-119.14
    assert render5(tmp_path, bsys()).returncode == 0
    comps = {"api": comp("api", provides=["orders"]), "web": comp("web", consumes=["orders"], envs=("dev", "prod"))}
    p = run_again(tmp_path, bsys(comps=comps))
    g = tree(tmp_path)
    assert f"{bdir('staging')}/consumer-orders.web.yaml" not in g and f"{bdir('dev')}/consumer-orders.web.yaml" in g and f"{bdir('prod')}/consumer-orders.web.yaml" in g
    assert lines(p)[:-1] == [retired("staging", "consumer", "orders", "web")]


def test_a_removed_events_api_retires_its_stream_and_consumers_ac_119_14(tmp_path):  # AC-119.14
    assert render5(tmp_path, wide()).returncode == 0
    comps = {"api": comp("api", provides=["orders"]), "web": comp("web", consumes=["orders"]), "worker": comp("worker", consumes=["orders"])}
    p = run_again(tmp_path, bsys(comps=comps))
    g = tree(tmp_path)
    for env in ENVS:
        assert f"{bdir(env)}/stream-audit.yaml" not in g and f"{bdir(env)}/consumer-audit.worker.yaml" not in g
        assert f"{bdir(env)}/stream-orders.yaml" in g and f"{bdir(env)}/consumer-orders.worker.yaml" in g
    want = [retired(e, k, "audit", "worker") for e in ("dev", "prod", "staging") for k in ("consumer", "stream")]
    assert lines(p)[:-1] == want


def test_a_broker_nothing_uses_any_more_retires_everything_in_it_ac_119_14(tmp_path):  # AC-119.14
    assert render5(tmp_path, bsys()).returncode == 0
    p = run_again(tmp_path, bsys(comps={"api": comp("api"), "web": comp("web")}, apis={}))
    assert p.returncode == 0, p.stderr
    assert not [k for k in tree(tmp_path) if "/addons/" in k]
    want = [retired(e, k, "orders", "web") for e in ("dev", "prod", "staging") for k in ("consumer", "stream")]
    assert lines(p)[:-1] == want


def test_the_notes_also_print_with_check_and_nothing_is_removed_ac_119_14(tmp_path):  # AC-119.14
    assert render5(tmp_path, bsys()).returncode == 0
    p = run_again(tmp_path, bsys(comps={"api": comp("api", provides=["orders"]), "web": comp("web")}), "--check")
    assert p.returncode == 1 and retired("dev", "consumer", "orders", "web") in p.stdout
    assert f"{bdir('dev')}/consumer-orders.web.yaml" in tree(tmp_path)


def test_an_unchanged_render_prints_no_note_ac_119_14(tmp_path):  # AC-119.14
    assert render5(tmp_path, bsys()).returncode == 0
    p = run_again(tmp_path, bsys())
    assert "note:" not in p.stdout and lines(p) == ["rendered (0 file(s) changed)"]


def test_a_stale_sweep_inside_a_broker_directory_leaves_foreign_files_alone_ac_119_14(tmp_path):  # AC-119.14
    assert render5(tmp_path, bsys()).returncode == 0
    keep = tmp_path / bdir("dev") / "keep.txt"
    keep.write_text("mine\n")
    run_again(tmp_path, bsys(comps={"api": comp("api", provides=["orders"]), "web": comp("web")}))
    assert keep.read_text() == "mine\n"


def test_the_notes_read_the_names_from_the_stale_files_ac_119_14(tmp_path):  # AC-119.14
    assert render5(tmp_path, bsys()).returncode == 0
    path = tmp_path / bdir("dev") / "consumer-orders.web.yaml"
    doc = yaml.safe_load(path.read_text())
    doc["spec"]["durableName"] = "web-old"
    path.write_text(yaml.safe_dump(doc, sort_keys=False))
    p = run_again(tmp_path, bsys(comps={"api": comp("api", provides=["orders"]), "web": comp("web")}))
    assert retired("dev", "consumer", "orders", "web-old") in p.stdout


# ---------------- AC-119.16: the monitoring endpoint ----------------

def test_the_server_exposes_the_monitoring_port_on_the_cluster_ip_service_ac_119_16(tmp_path):  # AC-119.16
    values = bdoc(ok(tmp_path, bsys()), "dev", "server.yaml")["spec"]["source"]["helm"]["valuesObject"]
    assert values["config"]["monitor"] == {"enabled": True, "port": 8222}
    assert values["service"] == {"ports": {"monitor": {"enabled": True}}} and values["natsBox"] == {"enabled": False}


def test_nothing_exposes_the_broker_outside_the_cluster_ac_119_16(tmp_path):  # AC-119.16
    g = ok(tmp_path, bsys())
    blob = "\n".join(t for k, t in g.items() if k.startswith(bdir("dev") + "/"))
    for needle in ("LoadBalancer", "NodePort", "HTTPRoute", "Ingress", "hostPort", "hostNetwork", "nodePort"):
        assert needle not in blob, needle
    for k, t in g.items():
        if "/addons/" in k:
            continue
        for doc in yaml.safe_load_all(t) if k.endswith(".yaml") else []:
            if isinstance(doc, dict) and doc.get("kind") in ("HTTPRoute", "Service", "Ingress", "Gateway"):
                assert "shop-bus" not in yaml.safe_dump(doc), k


# ---------------- AC-119.17: external brokers ----------------

def test_an_external_instance_renders_no_server_and_one_secret_per_component_ac_119_17(tmp_path):  # AC-119.17
    g = ok(tmp_path, bsys({"bus": broker(instances={"prod": {"external": True}})}))
    assert not [k for k in g if k.startswith(bdir("prod"))], "no in-cluster NATS in prod"
    assert "bus" not in addon_names(g, "prod") and "bus" in addon_names(g, "dev")
    for c in ("api", "web"):
        path = f"{APP}/overlays/prod/{c}/externalsecret-shop-bus-{c}-app.yaml"
        assert y(g, path) == expected_external_secret(c, f"shop-prod-bus-{c}")
    assert f"{APP}/overlays/prod/api/externalsecret-shop-bus-app.yaml" not in g


def test_an_external_broker_gives_the_same_variables_as_an_in_cluster_one_ac_119_17(tmp_path):  # AC-119.17
    g = ok(tmp_path, bsys({"bus": broker(instances={"prod": {"external": True}})}))
    for c in ("api", "web"):
        assert secret_vars(g, "prod", c) == secret_vars(g, "dev", c) == contract("bus", c)
    prod = {e["name"]: e["value"] for e in env_list(g, "prod", "web") if "value" in e}
    assert prod["EVENTS_ORDERS_CONSUMER"] == "web" and prod["NATS_INBOX_PREFIX"] == "_INBOX.web"


def test_the_store_path_follows_the_default_and_remote_overrides_with_the_component_ac_119_17(tmp_path):  # AC-119.17
    res = {"bus": broker(external=True, remote={"path": "brokers/{env}/{resource}/{component}", "refreshInterval": "30m"})}
    g = ok(tmp_path, bsys(res))
    es = y(g, f"{APP}/overlays/dev/web/externalsecret-shop-bus-web-app.yaml")
    assert es == expected_external_secret("web", "brokers/dev/bus/web", refresh="30m")
    assert [d["secretKey"] for d in es["spec"]["data"]] == BKEYS


def test_a_path_without_the_component_makes_every_component_read_one_key_ac_119_17(tmp_path):  # AC-119.17
    g = ok(tmp_path, bsys({"bus": broker(external=True, remote={"path": "shared/{env}"})}))
    keys = {d["remoteRef"]["key"] for c in ("api", "web") for d in y(g, f"{APP}/overlays/dev/{c}/externalsecret-shop-bus-{c}-app.yaml")["spec"]["data"]}
    assert keys == {"shared/dev"}


def test_an_external_everywhere_broker_renders_no_addon_and_no_operator_ac_119_17(tmp_path):  # AC-119.17
    g = ok(tmp_path, bsys({"bus": broker(external=True)}))
    assert not [k for k in g if "/addons/" in k] and not [k for k in g if k.startswith("operators/")]
    assert all(f"{APP}/overlays/{e}/api/externalsecret-shop-bus-api-app.yaml" in g for e in ENVS)


def test_an_external_component_gets_no_externalsecret_on_an_external_broker_ac_119_17(tmp_path):  # AC-119.17
    comps = {"api": comp("api", provides=["orders"]), "stock": ext_comp("stock", consumes=["orders"])}
    g = ok(tmp_path, bsys({"bus": broker(external=True)}, comps))
    assert not [k for k in g if "/overlays/dev/stock/" in k and "externalsecret" in k]


def test_a_component_without_an_instance_gets_no_secret_in_that_environment_ac_119_17(tmp_path):  # AC-119.17
    comps = {"api": comp("api", provides=["orders"]), "web": comp("web", consumes=["orders"], envs=("dev",))}
    g = ok(tmp_path, bsys({"bus": broker(external=True)}, comps))
    assert f"{APP}/overlays/staging/api/externalsecret-shop-bus-api-app.yaml" in g
    assert not [k for k in g if "/overlays/staging/web/" in k]


def test_the_render_prints_the_names_the_external_owner_must_create_ac_119_17(tmp_path):  # AC-119.17
    p = render5(tmp_path, bsys({"bus": broker(external=True)}))
    assert p.returncode == 0, p.stderr
    want = [f"note: applications/shop: broker bus is external in {e}: create stream shop-orders (subjects shop.orders.>, file storage, max age 7d) "
            "with the durable consumers web (pull, explicit ack, ack wait 30s); the platform creates none on an external broker" for e in ENVS]
    assert lines(p)[:-1] == want and lines(p)[-1].startswith("rendered (")


def test_the_external_note_lists_the_consumers_with_an_instance_and_every_api_ac_119_17(tmp_path):  # AC-119.17
    comps = {"api": comp("api", provides=["orders"]), "web": comp("web", consumes=["orders"], provides=["audit"], envs=("dev",)),
             "worker": comp("worker", consumes=["orders", "audit"])}
    doc = bsys({"bus": broker(instances={"dev": {"external": True}, "staging": {"external": True}})}, comps, events("orders", "audit"))
    got = lines(render5(tmp_path, doc))
    assert got[:4] == [
        "note: applications/shop: broker bus is external in dev: create stream shop-orders (subjects shop.orders.>, file storage, max age 7d) "
        "with the durable consumers web, worker (pull, explicit ack, ack wait 30s); the platform creates none on an external broker",
        "note: applications/shop: broker bus is external in dev: create stream shop-audit (subjects shop.audit.>, file storage, max age 7d) "
        "with the durable consumers worker (pull, explicit ack, ack wait 30s); the platform creates none on an external broker",
        "note: applications/shop: broker bus is external in staging: create stream shop-orders (subjects shop.orders.>, file storage, max age 7d) "
        "with the durable consumers worker (pull, explicit ack, ack wait 30s); the platform creates none on an external broker",
        "note: applications/shop: broker bus is external in staging: create stream shop-audit (subjects shop.audit.>, file storage, max age 7d) "
        "with the durable consumers worker (pull, explicit ack, ack wait 30s); the platform creates none on an external broker"]
    assert len(got) == 5


def test_the_external_note_leaves_out_the_consumers_when_none_runs_there_ac_119_17(tmp_path):  # AC-119.17
    comps = {"api": comp("api", provides=["orders"]), "web": comp("web", consumes=["orders"], envs=("dev",))}
    got = lines(render5(tmp_path, bsys({"bus": broker(instances={"prod": {"external": True}})}, comps)))
    assert got[0] == ("note: applications/shop: broker bus is external in prod: create stream shop-orders (subjects shop.orders.>, file storage, max age 7d); "
                      "the platform creates none on an external broker")
    assert len(got) == 2


def test_the_notes_come_in_the_designed_order_unbound_then_external_then_retired_ac_119_17(tmp_path):  # AC-119.17
    alpha = bsys()
    alpha["system"] = "alpha"
    write_system(tmp_path, alpha, "alpha")
    assert render(tmp_path).returncode == 0
    alpha = bsys({"bus": broker(instances={"prod": {"external": True}})}, {"api": comp("api", provides=["orders"]), "web": comp("web")})
    alpha["system"] = "alpha"
    zeta = bsys({"d": db()})
    zeta["system"] = "zeta"
    write_system(tmp_path, alpha, "alpha")
    write_system(tmp_path, zeta, "zeta")
    p = render(tmp_path)
    assert p.returncode == 0, p.stderr
    gone = "is no longer declared; it stays on the broker until you delete it"
    want = ["note: applications/zeta: events API orders is carried by no broker yet: add one with /resource:add <name> --type broker",
            "note: applications/alpha: broker bus is external in prod: create stream alpha-orders (subjects alpha.orders.>, file storage, max age 7d); "
            "the platform creates none on an external broker",
            f"note: applications/alpha/addons/dev/bus: durable consumer web of stream alpha-orders {gone}",
            f"note: applications/alpha/addons/prod/bus: durable consumer web of stream alpha-orders {gone}",
            "note: applications/alpha/addons/prod/bus: stream alpha-orders is no longer declared; it and its messages stay on the broker until you delete them",
            f"note: applications/alpha/addons/staging/bus: durable consumer web of stream alpha-orders {gone}"]
    assert lines(p)[:-1] == want and lines(p)[-1].startswith("rendered (")


# ---------------- AC-119.20: pins ----------------

def test_the_nats_pins_are_exact_in_the_versions_table_ac_119_20(tmp_path):  # AC-119.20
    r = renderer("render_119_pins")
    assert getattr(r, "NATS_CHART", None) == CHART
    assert getattr(r, "NATS_IMAGES", None) == NATS_IMAGES and getattr(r, "BROKER_VERSIONS", None) == ("2.14", "2.15")
    for minor, image in r.NATS_IMAGES.items():
        assert re.fullmatch(r"nats:\d+\.\d+\.\d+-alpine(@sha256:[0-9a-f]{64})?", image) and image.split(":")[1].startswith(f"{minor}.")
    assert re.fullmatch(r"\d+\.\d+\.\d+", r.NATS_CHART["chart_version"])


def test_the_nack_operator_is_pinned_exactly_ac_119_20(tmp_path):  # AC-119.20
    r = renderer("render_119_nack")
    assert {k: v for k, v in getattr(r, "OPERATORS", {}).get("nack", {}).items() if k != "crds"} == NACK   # spec 121: the table gains a crds key
    assert list(r.OPERATORS).index("nack") == 7 and r.OPERATOR_OF_TYPE == {"database": "cloudnative-pg", "bucket": "seaweedfs", "broker": "nack"}  # spec 120: nack stays the eighth entry (keda and metrics-server follow)
    assert r.BROKER_DEFAULT_RESOURCES == DEFAULT_RESOURCES


@pytest.mark.parametrize("version", ["2.14", "2.15"])
def test_no_floating_tag_is_rendered_ac_119_20(tmp_path, version):  # AC-119.20
    g = ok(tmp_path, wide({"bus": broker(version=version)}))
    blob = "\n".join(t for k, t in g.items() if "/addons/" in k)
    assert "latest" not in blob
    server = bdoc(g, "dev", "server.yaml")["spec"]["source"]
    assert server["targetRevision"] == "2.15.1" and server["chart"] == "nats" and server["repoURL"] == "https://nats-io.github.io/k8s/helm/charts"
    image = server["helm"]["valuesObject"]["container"]["image"]
    assert re.fullmatch(r"\d+\.\d+\.\d+-alpine@sha256:[0-9a-f]{64}", image["tag"])   # spec 121: digest
    assert image["repository"] == "nats"


def test_the_nack_application_pins_the_chart_exactly_ac_119_20(tmp_path):  # AC-119.20
    app = y(ok(tmp_path, bsys()), "operators/apps/nack.yaml")
    assert app["spec"]["source"]["targetRevision"] == "0.35.0" and not app["spec"]["source"]["helm"].get("valuesObject")


# ---------------- AC-119.21: the official chart and declared objects ----------------

def test_the_server_is_an_argo_application_of_the_official_chart_ac_119_21(tmp_path):  # AC-119.21
    g = ok(tmp_path, bsys())
    app = bdoc(g, "dev", "server.yaml")
    assert app["kind"] == "Application" and app["metadata"] == {"name": "shop-bus-dev-nats", "namespace": "argocd",
                                                                 "labels": {"app.kubernetes.io/name": "bus", "app.kubernetes.io/part-of": "shop",
                                                                            "app.kubernetes.io/managed-by": "gitops-app"}}
    assert app["spec"]["source"]["helm"]["releaseName"] == "shop-bus" and app["spec"]["destination"] == {"server": "https://kubernetes.default.svc", "namespace": "shop-dev"}
    assert app["spec"]["syncPolicy"] == {"automated": {"prune": True, "selfHeal": True}}


def test_the_directory_declares_every_object_and_the_kustomization_lists_them_sorted_ac_119_21(tmp_path):  # AC-119.21
    g = ok(tmp_path, bsys())
    for env in ENVS:
        assert bdoc(g, env, "kustomization.yaml") == expected_kustomization([f for f in FILES if f != "kustomization.yaml"])
        kinds = sorted(bdoc(g, env, f)["kind"] for f in FILES)
        assert kinds == ["Account", "Application", "ConfigMap", "Consumer", "Job", "Kustomization", "Role", "RoleBinding", "ServiceAccount", "Stream"]   # spec 128


def test_the_streams_and_consumers_are_ordered_by_sync_waves_after_the_account_ac_119_21(tmp_path):  # AC-119.21
    g = ok(tmp_path, bsys())
    wave = lambda f: bdoc(g, "dev", f)["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"]  # noqa: E731
    assert [wave(f) for f in ("account.yaml", "stream-orders.yaml", "consumer-orders.web.yaml")] == ["1", "2", "3"]
    assert [wave(f) for f in CRED_FILES] == ["0", "1", "0", "0", "0"]   # spec 128: the credentials hook objects (wave 0, the Job wave 1) replace the wave -1 objects
    assert not [k for k in g if k.startswith(bdir("dev")) and ("password-generator" in k or "nack-secret" in k or "externalsecret" in k)]


def test_every_broker_object_carries_the_name_label_ac_119_21(tmp_path):  # AC-119.21
    g = ok(tmp_path, bsys())
    for f in FILES:
        if f == "kustomization.yaml":
            continue
        assert bdoc(g, "dev", f)["metadata"]["labels"] == {"app.kubernetes.io/name": "bus", "app.kubernetes.io/part-of": "shop", "app.kubernetes.io/managed-by": "gitops-app"}, f
    values = bdoc(g, "dev", "server.yaml")["spec"]["source"]["helm"]["valuesObject"]
    assert values["nameOverride"] == "bus" and values["fullnameOverride"] == "shop-bus"


# ---------------- AC-119.22 / .23: the NACK controller (render half) ----------------

def owner(doc, *envs):
    for e in envs:
        doc["environments"][e]["operators"] = "owner"
    return doc


def apps_of(g) -> list[str]:
    return sorted(k.rsplit("/", 1)[-1] for k in g if k.startswith("operators/apps/"))


def test_an_in_cluster_broker_installs_nack_as_one_application_per_cluster_ac_119_22(tmp_path):  # AC-119.22
    g = ok(tmp_path, bsys())
    assert apps_of(g) == ["nack.yaml"] and "operators/root.yaml" in g
    assert y(g, "operators/apps/nack.yaml") == expected_nack_application()
    assert shape(y(g, "operators/apps/nack.yaml")) == shape(expected_nack_application())


def test_nack_comes_next_to_the_other_operators_ac_119_22(tmp_path):  # AC-119.22
    comps = {"api": comp("api", ["d"], provides=["orders"]), "web": comp("web", consumes=["orders"])}
    assert apps_of(ok(tmp_path / "a", bsys({"bus": broker(), "d": db()}, comps))) == ["cloudnative-pg.yaml", "nack.yaml"]
    assert apps_of(ok(tmp_path / "b", system({"d": db()}, {"api": comp("api", ["d"])}))) == ["cloudnative-pg.yaml"]


def test_the_cluster_repo_copy_of_the_renderer_knows_nack_ac_119_22(tmp_path):  # AC-119.22
    from system_fixtures import ROOT
    for path in ("templates/gitops-app/scripts/render.py", "templates/cluster-gitops/scripts/system_render.py"):
        text = (ROOT / path).read_text()
        assert '"nack"' in text and re.search(r"\bstreams\.jetstream\.nats\.io\b", text), path  # a CRD name, matched as a word


def test_a_cluster_with_only_external_brokers_gets_no_nack_ac_119_22(tmp_path):  # AC-119.22
    g = ok(tmp_path, bsys({"bus": broker(external=True)}))
    assert not [k for k in g if k.startswith("operators/")]


def test_one_in_cluster_environment_is_enough_for_nack_ac_119_22(tmp_path):  # AC-119.22
    g = ok(tmp_path, bsys({"bus": broker(instances={"dev": {"external": True}, "staging": {"external": True}})}))
    assert apps_of(g) == ["nack.yaml"]


def test_an_unused_broker_installs_no_nack_ac_119_22(tmp_path):  # AC-119.22
    assert not [k for k in ok(tmp_path, bsys(comps={"api": comp("api")}, apis={})) if k.startswith("operators/")]


def test_operators_owner_in_every_broker_environment_installs_nothing_ac_119_23(tmp_path):  # AC-119.23
    g = ok(tmp_path, owner(bsys(), *ENVS))
    assert not [k for k in g if k.startswith("operators/")]
    assert [k for k in g if k.startswith(bdir("dev"))], "the broker itself is still rendered"


def test_nack_stays_while_another_environment_still_needs_it_ac_119_23(tmp_path):  # AC-119.23
    assert apps_of(ok(tmp_path, owner(bsys(), "dev"))) == ["nack.yaml"]


def test_owner_managed_environments_render_the_same_broker_ac_119_23(tmp_path):  # AC-119.23
    plain = ok(tmp_path / "a", bsys())
    owned = ok(tmp_path / "b", owner(bsys(), "dev"))
    assert {k: v for k, v in plain.items() if k.startswith(bdir("dev"))} == {k: v for k, v in owned.items() if k.startswith(bdir("dev"))}


# ---------------- AC-119.24: additive, nothing else changes ----------------

# digests of the trees the 5.x renderer wrote before spec 119 (full tree, sha256 of sorted path and content)
BEFORE_119 = {"full5": ("327d41a6f2cdc9c46124f7b088b13b2bcfe154dfb878ebfb87b3845bd048cf02", 67),   # spec 128: a generated component secret gets a credentials Job
              "rich5": ("fe1543fc8b668272d474fb2a3c81de372ae673a2023c1dae8521a3143d7473be", 67),   # spec 128: a generated component secret gets a credentials Job
              "db-bucket": ("ae098881e7b6a57b03e99b36924de150f513b06e1dad3c42b303e79400e930d8", 56),   # spec 128: the credentials Job replaces the bucket's generators and ExternalSecret
              "cache": ("c5e5809f484b7fddca7c2189f68c58b6e4a713331a035bca6aa2424dbad243df", 49),   # spec 128: the credentials Job replaces the generator files
              "events": ("9fe3842825e291f58f1e33aac03f53edf98df7c9053eefbeae7882d3ad3f57e4", 26),
              "events-multi": ("ebca4dedef644e88bafb98a92819385874af6b9771570478b38a2551b788e4ef", 70)}


def _before_docs():
    ev_comps = {"api": comp("api", provides=["orders"]), "web": comp("web", consumes=["orders"])}
    multi = {"api": comp("api", ["d"], provides=["orders", "audit"]), "web": comp("web", consumes=["orders"], envs=("dev",)),
             "worker": comp("worker", consumes=["audit"]), "w2": comp("w2", ["sessions"])}
    return {"full5": full5(), "rich5": rich5(),
            "db-bucket": system({"orders-db": db(version=16, replicas=2), "files": {"type": "bucket", "storage": "5Gi", "versioning": True}},
                                {"api": comp("api", ["orders-db", "files"])}),
            "cache": system({"sessions": cache(persistence=True), "d": db()}, {"api": comp("api", ["sessions", "d"])}),
            "events": system({"d": db()}, ev_comps, apis=events("orders")),
            "events-multi": system({"d": db(), "sessions": cache()}, multi, apis=events("orders", "audit"))}


@pytest.mark.parametrize("label", list(BEFORE_119))
def test_a_5x_system_without_a_broker_renders_byte_identically_to_before_ac_119_24(tmp_path, label):  # AC-119.24
    g = ok(tmp_path, _before_docs()[label])
    digest, count = BEFORE_119[label]
    assert (len(g), tree_digest(unpin(g))) == (count, digest), f"{label}: the render changed although the system has no broker"  # spec 121: only the engine references changed


def _events_only() -> dict:
    comps = {"api": comp("api", provides=["orders", "audit"]), "web": comp("web", consumes=["orders"], envs=("dev",)), "worker": comp("worker", consumes=["audit"])}
    return system(None, comps, apis=events("orders", "audit"))


def _events_library() -> dict:
    comps = {"api": comp("api", provides=["orders"]), "web": comp("web", consumes=["orders"]), "lib": lib_comp("lib", consumes=["orders"])}
    return system(None, comps, apis=events("orders"))


@pytest.mark.parametrize("label", ["events-only", "events-library"])
def test_a_system_with_events_apis_and_no_broker_equals_the_5_0_render_ac_119_24(tmp_path, label):  # AC-119.24
    doc = _events_only() if label == "events-only" else _events_library()
    now = ok(tmp_path / "now", doc)
    assert now == render_50(tmp_path, doc)
    assert not [k for k in now if "/addons/" in k] and not [k for k in now if k.startswith("operators/")]


def test_an_unused_broker_changes_nothing_in_the_tree_ac_119_24(tmp_path):  # AC-119.24
    a = ok(tmp_path / "a", system({"d": db()}, {"api": comp("api", ["d"])}))
    b = ok(tmp_path / "b", system({"d": db(), "idle": broker()}, {"api": comp("api", ["d"])}))
    assert a == b


def test_a_broker_changes_only_the_files_it_owns_ac_119_24(tmp_path):  # AC-119.24
    plain = ok(tmp_path / "a", system({"d": db()}, {"api": comp("api", ["d"], provides=["orders"]), "web": comp("web", consumes=["orders"])}, apis=events("orders")))
    with_bus = ok(tmp_path / "b", system({"d": db(), "bus": broker()}, {"api": comp("api", ["d"], provides=["orders"]), "web": comp("web", consumes=["orders"])},
                                         apis=events("orders")))
    changed = {k for k in with_bus if plain.get(k) != with_bus[k]}
    allowed = {f"{APP}/applicationset.yaml", "operators/root.yaml", "operators/apps/nack.yaml"}
    for e in ENVS:
        allowed |= {f"{APP}/overlays/{e}/api/deployment.yaml", f"{APP}/overlays/{e}/web/deployment.yaml", f"{APP}/overlays/{e}/api/kustomization.yaml",
                    f"{APP}/overlays/{e}/web/kustomization.yaml"}
    assert all(k in allowed or k.startswith(f"{APP}/addons/") for k in changed), sorted(changed - allowed)
    assert all(plain[k] == with_bus[k] for k in plain if k.startswith(f"{APP}/addons/") or k.startswith(f"{APP}/policies") or k.startswith("bootstrap/"))
