"""Spec 118 acceptance tests, the renderer part: the `cache` resource type (AC-118.2 .. AC-118.8, .11, .14, .17 .. .20, .22, .23).

Contract: design.md "Contract: system.yaml", "Render errors", "Renderer API", "what a using component gets", "in-cluster cache
instance", "external cache instance" and "versions table". The renderer runs as a script in a hand-built checkout (resources_fixtures);
nothing touches the network or a cluster. Criteria that need a cluster (AC-118.6/.7/.11 behaviour, .15) are covered here by the rendered
contract and in test_cache_118_cmds.py by the text of tests/e2e/run.sh. Missing symbols are guarded with getattr so each test fails
on its own."""
import copy
import re

import pytest
import yaml

from backup_fixtures import bdoc
from cache_fixtures import (ALLOWED_INST, ALLOWED_TOP, CKEYS, CVARS, FILES, IMAGES, P, POLICIES, SIZING, WAVE, cache, cdir, cdoc, contract, csys,
                            cplan, expected_kustomization, expected_plan, expected_service, expected_statefulset, labels,
                            tree_digest)
from resources_fixtures import (APP, ENVS, LABELS, addon_names, comp, db, env_list, external_secret, external_secret_path, fails, ok,
                                platform_render_module, render5, secret_vars, sets, system, unpin, var_order, y)  # spec 121: unpin
from system_fixtures import full5, rich5, write_system

QUANTITY_MSG = "memory '{v}' must be a Kubernetes quantity of at least 64Mi, e.g. 256Mi"


def renderer(name="render_118"):
    return platform_render_module(name)


def effective(tmp_path, doc, name="sessions") -> dict:
    r = renderer("render_118_api")
    app_dir = write_system(tmp_path, doc)
    return r.load_system(app_dir)["cfg"]["resources"][name]["envs"]  # spec 118 slip: load_system keeps resources under cfg


# ---------------- AC-118.2: schema ----------------

def test_a_cache_with_all_its_keys_is_accepted_ac_118_2(tmp_path):  # AC-118.2
    res = {"sessions": cache(version=8, memory="512Mi", maxmemoryPolicy="volatile-ttl", persistence=True, storage="2Gi",
                             instances={"dev": {"memory": "128Mi", "maxmemoryPolicy": "noeviction", "persistence": False},
                                        "prod": {"persistence": True, "storage": "5Gi"}})}
    ok(tmp_path, csys(res))


def test_a_cache_with_the_external_keys_of_spec_115_is_accepted_ac_118_2(tmp_path):  # AC-118.2
    res = {"sessions": cache(external=True, remote={"path": "{env}/{resource}", "refreshInterval": "2h"})}
    ok(tmp_path, csys(res))


def test_an_unknown_cache_key_fails_naming_resource_key_and_allowed_keys_ac_118_2(tmp_path):  # AC-118.2
    fails(tmp_path, csys({"sessions": cache(replicas=2)}), P + f"resources.sessions: unknown key 'replicas' (allowed: {ALLOWED_TOP})")


@pytest.mark.parametrize("key", ["versioning", "cluster", "ttl"])
def test_other_unknown_top_level_keys_fail_ac_118_2(tmp_path, key):  # AC-118.2
    fails(tmp_path, csys({"sessions": cache(**{key: 1})}), P + f"resources.sessions: unknown key '{key}' (allowed: {ALLOWED_TOP})")


def test_an_unknown_instance_key_fails_ac_118_2(tmp_path):  # AC-118.2
    fails(tmp_path, csys({"sessions": cache(instances={"dev": {"replicas": 2}})}),
          P + f"resources.sessions.instances.dev: unknown key 'replicas' (allowed: {ALLOWED_INST})")


def test_an_unsupported_instance_version_fails_ac_118_2(tmp_path):  # AC-118.2  # spec 121: the key is allowed now
    fails(tmp_path, csys({"sessions": cache(instances={"dev": {"version": 7}})}),
          P + "resources.sessions.instances.dev: version '7' is not a supported cache version (8, 9)")  # spec 121: spec 121 adds the key


def test_instances_must_be_a_mapping_ac_118_2(tmp_path):  # AC-118.2
    fails(tmp_path, csys({"sessions": cache(instances=["dev"])}),
          P + "resources.sessions.instances must be a mapping of environments to {external, remote, memory, maxmemoryPolicy, persistence, storage, version}")   # spec 121: version per environment


def test_an_unused_cache_is_validated_too_ac_118_2(tmp_path):  # AC-118.2
    fails(tmp_path, csys({"sessions": cache(bogus=1)}, {"api": comp("api")}), "resources.sessions: unknown key 'bogus'")


def test_a_database_key_on_a_cache_is_unknown_ac_118_2(tmp_path):  # AC-118.2
    fails(tmp_path, csys({"sessions": cache(replicas=1)}), "unknown key 'replicas'")


@pytest.mark.parametrize("key, value", [("memory", "128Mi"), ("maxmemoryPolicy", "noeviction"), ("persistence", True), ("storage", "5Gi")])
def test_an_external_instance_may_not_set_sizing_ac_118_2(tmp_path, key, value):  # AC-118.2
    fails(tmp_path, csys({"sessions": cache(instances={"prod": {"external": True, key: value}})}),
          P + f"resources.sessions.instances.prod: an external cache is sized and configured at its provider (remove {key})")


def test_the_external_sizing_check_comes_before_the_unknown_key_check_ac_118_2(tmp_path):  # AC-118.2
    fails(tmp_path, csys({"sessions": cache(instances={"prod": {"external": True, "memory": "128Mi", "bogus": 1}})}),
          P + "resources.sessions.instances.prod: an external cache is sized and configured at its provider (remove memory)")


def test_an_instance_inheriting_external_may_not_set_sizing_ac_118_2(tmp_path):  # AC-118.2
    fails(tmp_path, csys({"sessions": cache(external=True, instances={"staging": {"memory": "128Mi"}})}),
          P + "resources.sessions.instances.staging: an external cache is sized and configured at its provider (remove memory)")


@pytest.mark.parametrize("key, value", [("version", 9), ("memory", "128Mi"), ("maxmemoryPolicy", "noeviction"), ("persistence", False), ("storage", "5Gi")])
def test_top_level_sizing_of_a_cache_that_is_external_everywhere_fails_ac_118_2(tmp_path, key, value):  # AC-118.2
    fails(tmp_path, csys({"sessions": cache(external=True, **{key: value})}),
          P + f"resources.sessions: external in every environment: an external cache is sized and configured at its provider (remove {key})")


def test_top_level_sizing_is_fine_while_one_environment_runs_the_cache_ac_118_2(tmp_path):  # AC-118.2
    ok(tmp_path, csys({"sessions": cache(memory="128Mi", persistence=True, storage="2Gi", instances={"prod": {"external": True}})}))


# ---------------- AC-118.3: defaults ----------------

def test_the_effective_values_default_to_valkey_9_256mi_allkeys_lru_no_persistence_ac_118_3(tmp_path):  # AC-118.3
    envs = effective(tmp_path, csys())
    assert sorted(envs) == sorted(ENVS)  # spec 118 slip: compared a sorted list with ENVS order
    for e in ENVS:
        assert envs[e] == {"external": False, "version": 9, "replicas": None, "storage": None, "resources": None, "memory": "256Mi",
                           "maxmemory": 214748364, "maxmemoryPolicy": "allkeys-lru", "persistence": False, "store_key": None,
                           "refreshInterval": None, "pin": "valkey/valkey:9.1.3@sha256:3add1a336a920ea54770a001ab6feb3da5fceea96a40373a3a2cd469b815f0b7"}, e   # spec 121: pin
        assert isinstance(envs[e]["version"], int) and envs[e]["persistence"] is False


def test_the_effective_values_follow_instance_then_resource_then_default_ac_118_3(tmp_path):  # AC-118.3
    res = {"sessions": cache(version="8", memory="512Mi", maxmemoryPolicy="volatile-lru", persistence=True,
                             instances={"dev": {"memory": "128Mi", "persistence": False}, "prod": {"storage": "5Gi", "maxmemoryPolicy": "noeviction"}})}
    envs = effective(tmp_path, csys(res))
    assert envs["dev"] | {} == {"external": False, "version": 8, "replicas": None, "storage": None, "resources": None, "memory": "128Mi",
                               "maxmemory": 107374182, "maxmemoryPolicy": "volatile-lru", "persistence": False, "store_key": None, "refreshInterval": None,
                               "pin": "valkey/valkey:8.1.11@sha256:8f836008e0986c36adf50da714c7060cf689dbb335f61fe077939d90fa650809"}   # spec 121: pin
    assert (envs["staging"]["memory"], envs["staging"]["persistence"], envs["staging"]["storage"], envs["staging"]["maxmemory"]) == ("512Mi", True, "1Gi", 429496729)
    assert (envs["prod"]["storage"], envs["prod"]["maxmemoryPolicy"], envs["prod"]["persistence"]) == ("5Gi", "noeviction", True)


def test_an_external_instance_has_no_sizing_in_the_renderer_api_ac_118_3(tmp_path):  # AC-118.3
    envs = effective(tmp_path, csys({"sessions": cache(instances={"prod": {"external": True}})}))
    assert envs["prod"] == {"external": True, "version": None, "replicas": None, "storage": None, "resources": None, "memory": None,
                            "maxmemory": None, "maxmemoryPolicy": None, "persistence": None, "store_key": "shop-prod-sessions", "refreshInterval": "1h", "pin": None}   # spec 121: pin
    assert envs["dev"]["external"] is False and envs["dev"]["version"] == 9


def test_a_default_cache_renders_one_valkey_node_with_the_defaults_ac_118_3(tmp_path):  # AC-118.3
    g = ok(tmp_path, csys())
    for env in ENVS:
        assert cdoc(g, env, "statefulset.yaml") == expected_statefulset(), env
        assert cdoc(g, env, "statefulset.yaml")["spec"]["replicas"] == 1


def test_the_defaults_in_the_statefulset_are_256mi_allkeys_lru_and_no_volume_ac_118_3(tmp_path):  # AC-118.3
    sts = cdoc(ok(tmp_path, csys()), "dev", "statefulset.yaml")
    c = sts["spec"]["template"]["spec"]["containers"][0]
    assert c["resources"]["limits"] == {"memory": "256Mi"} and c["resources"]["requests"] == {"cpu": "50m", "memory": "256Mi"}
    assert c["args"][c["args"].index("--maxmemory-policy") + 1] == "allkeys-lru" and c["args"][c["args"].index("--appendonly") + 1] == "no"
    assert "volumeMounts" not in c and "volumeClaimTemplates" not in sts["spec"]


# ---------------- AC-118.4: value checks ----------------

@pytest.mark.parametrize("bad", [7, 10, "latest", 9.1, "7", 0])
def test_an_unsupported_version_fails_ac_118_4(tmp_path, bad):  # AC-118.4
    fails(tmp_path, csys({"sessions": cache(version=bad)}), P + f"resources.sessions: version '{bad}' is not a supported cache version (8, 9)")


@pytest.mark.parametrize("good", [8, 9, "8", "9"])
def test_a_supported_version_is_accepted_ac_118_4(tmp_path, good):  # AC-118.4
    ok(tmp_path, csys({"sessions": cache(version=good)}))


def test_the_version_is_only_checked_where_some_environment_is_in_cluster_ac_118_4(tmp_path):  # AC-118.4
    fails(tmp_path, csys({"sessions": cache(version=7, instances={"prod": {"external": True}})}), "version '7' is not a supported cache version (8, 9)")


@pytest.mark.parametrize("bad", ["lots", "256 Mi", "256MB", "-1Gi", "1e3", "256m", "", "1.5.2Gi", "Mi", "63Mi", "1Ki", "67108863", 1000])
def test_a_memory_that_is_no_quantity_or_below_64mi_fails_ac_118_4(tmp_path, bad):  # AC-118.4
    fails(tmp_path, csys({"sessions": cache(memory=bad)}), P + "resources.sessions: " + QUANTITY_MSG.format(v=bad))


@pytest.mark.parametrize("good", ["64Mi", "256Mi", "0.5Gi", "1Gi", "100M", "2G", "67108864", 134217728, "65536Ki"])
def test_a_valid_memory_is_accepted_ac_118_4(tmp_path, good):  # AC-118.4
    ok(tmp_path, csys({"sessions": cache(memory=good)}))


def test_an_instance_memory_fails_naming_the_instance_ac_118_4(tmp_path):  # AC-118.4
    fails(tmp_path, csys({"sessions": cache(instances={"dev": {"memory": "10Mi"}})}),
          P + "resources.sessions.instances.dev: " + QUANTITY_MSG.format(v="10Mi"))


@pytest.mark.parametrize("bad", ["lru", "allkeys", "ALLKEYS-LRU", "", 1])
def test_a_policy_outside_the_eight_fails_ac_118_4(tmp_path, bad):  # AC-118.4
    fails(tmp_path, csys({"sessions": cache(maxmemoryPolicy=bad)}),
          P + f"resources.sessions: maxmemoryPolicy '{bad}' is not allowed (" + ", ".join(POLICIES) + ")")


@pytest.mark.parametrize("good", POLICIES)
def test_each_of_the_eight_policies_is_accepted_ac_118_4(tmp_path, good):  # AC-118.4
    g = ok(tmp_path, csys({"sessions": cache(maxmemoryPolicy=good)}))
    args = cdoc(g, "dev", "statefulset.yaml")["spec"]["template"]["spec"]["containers"][0]["args"]
    assert args[args.index("--maxmemory-policy") + 1] == good


def test_an_instance_policy_fails_naming_the_instance_ac_118_4(tmp_path):  # AC-118.4
    fails(tmp_path, csys({"sessions": cache(instances={"prod": {"maxmemoryPolicy": "fifo"}})}),
          P + "resources.sessions.instances.prod: maxmemoryPolicy 'fifo' is not allowed (" + ", ".join(POLICIES) + ")")


@pytest.mark.parametrize("bad", ["true", "yes", 1, 0, None, "false"])
def test_persistence_must_be_true_or_false_ac_118_4(tmp_path, bad):  # AC-118.4
    fails(tmp_path, csys({"sessions": cache(persistence=bad)}), P + "resources.sessions: persistence must be true or false")


def test_an_instance_persistence_must_be_true_or_false_ac_118_4(tmp_path):  # AC-118.4
    fails(tmp_path, csys({"sessions": cache(instances={"staging": {"persistence": "on"}})}),
          P + "resources.sessions.instances.staging: persistence must be true or false")


@pytest.mark.parametrize("bad", ["big", "1 Gi", "1GB", 10, "", "-1Gi"])
def test_storage_must_be_a_size_ac_118_4(tmp_path, bad):  # AC-118.4
    fails(tmp_path, csys({"sessions": cache(persistence=True, storage=bad)}), P + "resources.sessions: storage must be a size such as 1Gi")


def test_an_instance_storage_must_be_a_size_ac_118_4(tmp_path):  # AC-118.4
    fails(tmp_path, csys({"sessions": cache(persistence=True, instances={"dev": {"storage": "lots"}})}),
          P + "resources.sessions.instances.dev: storage must be a size such as 1Gi")


def test_a_malformed_storage_is_reported_as_a_size_before_the_persistence_rule_ac_118_4(tmp_path):  # AC-118.4
    fails(tmp_path, csys({"sessions": cache(storage="big")}), P + "resources.sessions: storage must be a size such as 1Gi")


def test_an_instance_storage_without_persistence_fails_naming_the_environment_ac_118_4(tmp_path):  # AC-118.4
    fails(tmp_path, csys({"sessions": cache(instances={"dev": {"storage": "2Gi"}})}),
          P + "resources.sessions.instances.dev: storage needs persistence: true (persistence is false in dev)")


def test_an_instance_storage_with_persistence_switched_off_in_that_environment_fails_ac_118_4(tmp_path):  # AC-118.4
    fails(tmp_path, csys({"sessions": cache(persistence=True, instances={"staging": {"storage": "2Gi", "persistence": False}})}),
          P + "resources.sessions.instances.staging: storage needs persistence: true (persistence is false in staging)")


def test_the_storage_rule_reports_environments_in_the_order_dev_staging_prod_ac_118_4(tmp_path):  # AC-118.4
    err = fails(tmp_path, csys({"sessions": cache(instances={"prod": {"storage": "2Gi"}, "dev": {"storage": "2Gi"}})}),
                P + "resources.sessions.instances.dev: storage needs persistence: true (persistence is false in dev)")
    assert "instances.prod: storage needs persistence" not in err


def test_a_resource_storage_without_persistence_anywhere_fails_ac_118_4(tmp_path):  # AC-118.4
    fails(tmp_path, csys({"sessions": cache(storage="2Gi")}), P + "resources.sessions: storage needs persistence: true in at least one environment")


@pytest.mark.parametrize("res", [
    cache(storage="2Gi", persistence=True),
    cache(storage="2Gi", instances={"prod": {"persistence": True}}),
    cache(persistence=True, instances={"dev": {"storage": "2Gi"}}),
    cache(instances={"prod": {"persistence": True, "storage": "2Gi"}}),
])
def test_storage_with_persistence_in_a_running_environment_is_accepted_ac_118_4(tmp_path, res):  # AC-118.4
    ok(tmp_path, csys({"sessions": res}))


# ---------------- AC-118.5: redis and valkey are not the type ----------------

@pytest.mark.parametrize("typ", ["redis", "valkey"])
def test_type_redis_or_valkey_fails_naming_cache_ac_118_5(tmp_path, typ):  # AC-118.5
    err = fails(tmp_path, system({"store": {"type": typ}}),
                P + f"resources.store: type '{typ}' is not a resource type: the type is `cache` (Redis-compatible, runs Valkey)")
    assert len(err.strip().splitlines()) == 1


@pytest.mark.parametrize("typ", ["redis", "valkey"])
def test_a_used_redis_or_valkey_resource_fails_the_same_way_and_writes_nothing_ac_118_5(tmp_path, typ):  # AC-118.5
    fails(tmp_path, system({"sessions": {"type": typ}}, {"api": comp("api", ["sessions"])}),
          "the type is `cache` (Redis-compatible, runs Valkey)")


def test_the_redis_text_replaces_the_types_line_ac_118_5(tmp_path):  # AC-118.5
    err = fails(tmp_path, system({"store": {"type": "redis"}}))
    assert "(database, bucket, cache or broker)" not in err


# ---------------- AC-118.17: pins ----------------

def test_the_valkey_pins_are_exact_per_major_ac_118_17(tmp_path):  # AC-118.17
    r = renderer("render_118_pins")
    pins = getattr(r, "VALKEY_IMAGES", None)
    assert pins == IMAGES, "render.py has VALKEY_IMAGES"
    assert getattr(r, "CACHE_VERSIONS", None) == (8, 9)
    for major, image in pins.items():
        assert re.fullmatch(r"valkey/valkey:\d+\.\d+\.\d+(@sha256:[0-9a-f]{64})?", image) and image.split(":")[1].startswith(f"{major}.")


@pytest.mark.parametrize("version", [8, 9])
def test_the_statefulset_runs_the_pinned_release_of_its_major_ac_118_17(tmp_path, version):  # AC-118.17
    g = ok(tmp_path, csys({"sessions": cache(version=version)}))
    assert cdoc(g, "dev", "statefulset.yaml")["spec"]["template"]["spec"]["containers"][0]["image"] == IMAGES[version]


def test_no_floating_tag_is_rendered_ac_118_17(tmp_path):  # AC-118.17
    blob = "\n".join(t for k, t in ok(tmp_path, csys()).items() if "/addons/dev/sessions/" in k and "/credentials-" not in k)   # the Job's python image is spec 128's
    images = re.findall(r"image:\s*(\S+)", blob)
    assert images and all(re.fullmatch(r"valkey/valkey:\d+\.\d+\.\d+@sha256:[0-9a-f]{64}", i) for i in images)   # spec 121: digest
    assert "latest" not in blob


def test_a_version_change_changes_only_the_statefulset_image_ac_118_17(tmp_path):  # AC-118.17
    a = ok(tmp_path / "a", csys({"sessions": cache(version=8)}))
    b = ok(tmp_path / "b", csys({"sessions": cache(version=9)}))
    changed = sorted(k for k in a if a[k] != b.get(k))
    assert changed == sorted(f"{cdir(e)}/statefulset.yaml" for e in ENVS)  # spec 118 slip: both sides sorted


# ---------------- AC-118.6: memory, maxmemory, policy ----------------

@pytest.mark.parametrize("memory, maxmemory", [("256Mi", 214748364), ("64Mi", 53687091), ("1Gi", 858993459), ("0.5Gi", 429496729),
                                              ("100M", 80000000), (134217728, 107374182), ("2G", 1600000000), ("65536Ki", 53687091)])
def test_maxmemory_is_80_percent_of_the_memory_limit_floored_ac_118_6(tmp_path, memory, maxmemory):  # AC-118.6
    g = ok(tmp_path, csys({"sessions": cache(memory=memory)}))
    c = cdoc(g, "dev", "statefulset.yaml")["spec"]["template"]["spec"]["containers"][0]
    assert c["resources"]["limits"]["memory"] == str(memory) and c["resources"]["requests"]["memory"] == str(memory)
    assert c["args"][c["args"].index("--maxmemory") + 1] == str(maxmemory)
    assert effective(tmp_path / "api", csys({"sessions": cache(memory=memory)}))["dev"]["maxmemory"] == maxmemory


def test_the_container_has_a_memory_limit_equal_to_its_request_and_no_cpu_limit_ac_118_6(tmp_path):  # AC-118.6
    r = cdoc(ok(tmp_path, csys({"sessions": cache(memory="64Mi")})), "dev", "statefulset.yaml")["spec"]["template"]["spec"]["containers"][0]["resources"]
    assert r == {"requests": {"cpu": "50m", "memory": "64Mi"}, "limits": {"memory": "64Mi"}}


def test_the_sized_statefulset_is_exactly_the_designed_document_ac_118_6(tmp_path):  # AC-118.6
    g = ok(tmp_path, csys({"sessions": cache(memory="64Mi", maxmemoryPolicy="noeviction")}))
    assert cdoc(g, "dev", "statefulset.yaml") == expected_statefulset(memory="64Mi", maxmemory=53687091, policy="noeviction")


def test_memory_and_policy_are_set_per_environment_ac_118_6(tmp_path):  # AC-118.6
    res = {"sessions": cache(memory="512Mi", instances={"dev": {"memory": "64Mi", "maxmemoryPolicy": "noeviction"}})}
    g = ok(tmp_path, csys(res))
    assert cdoc(g, "dev", "statefulset.yaml") == expected_statefulset(memory="64Mi", maxmemory=53687091, policy="noeviction")
    assert cdoc(g, "staging", "statefulset.yaml") == expected_statefulset(memory="512Mi", maxmemory=429496729)


# ---------------- AC-118.7: persistence ----------------

def test_persistence_false_renders_no_volume_at_all_ac_118_7(tmp_path):  # AC-118.7
    g = ok(tmp_path, csys())
    text = "\n".join(t for k, t in g.items() if k.startswith(cdir("dev")) and "/credentials-" not in k)   # the Job mounts its own ConfigMap
    for needle in ("volumeClaimTemplates", "volumeMounts", "emptyDir", "persistentVolumeClaim", "PersistentVolumeClaim", "volumes:"):
        assert needle not in text, needle


def test_persistence_true_renders_the_aof_args_a_mount_and_a_1gi_claim_by_default_ac_118_7(tmp_path):  # AC-118.7
    g = ok(tmp_path, csys({"sessions": cache(persistence=True)}))
    for env in ENVS:
        assert cdoc(g, env, "statefulset.yaml") == expected_statefulset(persistence=True), env


def test_the_storage_size_is_taken_from_the_instance_then_the_resource_ac_118_7(tmp_path):  # AC-118.7
    res = {"sessions": cache(persistence=True, storage="2Gi", instances={"prod": {"storage": "5Gi"}})}
    g = ok(tmp_path, csys(res))
    got = {e: cdoc(g, e, "statefulset.yaml")["spec"]["volumeClaimTemplates"][0]["spec"]["resources"]["requests"]["storage"] for e in ENVS}
    assert got == {"dev": "2Gi", "staging": "2Gi", "prod": "5Gi"}
    assert cdoc(g, "prod", "statefulset.yaml") == expected_statefulset(persistence=True, storage="5Gi")


def test_persistence_can_differ_per_environment_ac_118_7(tmp_path):  # AC-118.7
    g = ok(tmp_path, csys({"sessions": cache(instances={"prod": {"persistence": True}})}))
    assert cdoc(g, "dev", "statefulset.yaml") == expected_statefulset()
    assert cdoc(g, "prod", "statefulset.yaml") == expected_statefulset(persistence=True)


def test_rdb_snapshots_are_off_in_both_modes_ac_118_7(tmp_path):  # AC-118.7
    for persistence in (False, True):
        args = cdoc(ok(tmp_path / str(persistence), csys({"sessions": cache(persistence=persistence)})), "dev", "statefulset.yaml")["spec"]["template"]["spec"]["containers"][0]["args"]
        assert args[args.index("--save") + 1] == ""


def test_a_sync_never_replaces_the_statefulset_ac_118_7(tmp_path):  # AC-118.7
    sts = cdoc(ok(tmp_path, csys({"sessions": cache(persistence=True)})), "dev", "statefulset.yaml")
    assert "annotations" not in sts["metadata"]  # spec 118 review: Force/Replace recreated the cache on every sync (design decision 8)


# ---------------- AC-118.8: not reachable from outside ----------------

def test_a_cache_directory_has_exactly_the_five_designed_files_ac_118_8(tmp_path):  # AC-118.8
    g = ok(tmp_path, csys())
    for env in ENVS:
        assert sorted(k.rsplit("/", 1)[-1] for k in g if k.startswith(cdir(env) + "/")) == FILES, env


def test_the_only_service_is_a_clusterip_on_6379_ac_118_8(tmp_path):  # AC-118.8
    g = ok(tmp_path, csys({"sessions": cache(persistence=True)}))
    assert cdoc(g, "dev", "service.yaml") == expected_service()
    assert cdoc(g, "dev", "service.yaml")["spec"]["ports"] == [{"name": "redis", "port": 6379, "targetPort": "redis"}]
    docs = [yaml.safe_load(t) for k, t in g.items() if k.startswith(cdir("dev") + "/") and k.endswith(".yaml")]
    assert [d["kind"] for d in docs if d["kind"] == "Service"] == ["Service"]
    blob = "\n".join(t for k, t in g.items() if k.startswith(cdir("dev") + "/"))
    for needle in ("LoadBalancer", "NodePort", "HTTPRoute", "Ingress", "hostPort", "hostNetwork", "nodePort"):
        assert needle not in blob, needle


def test_no_route_or_gateway_object_names_the_cache_ac_118_8(tmp_path):  # AC-118.8
    g = ok(tmp_path, csys())
    for k, t in g.items():
        if any(k.startswith(cdir(e) + "/") for e in ENVS):  # spec 118 slip: the cache's own Service lives in every environment's addon dir
            continue
        for doc in yaml.safe_load_all(t) if k.endswith((".yaml", ".yml")) else []:
            if isinstance(doc, dict) and doc.get("kind") in ("HTTPRoute", "Service", "Ingress", "Gateway"):
                assert "sessions" not in yaml.safe_dump(doc), k


def test_the_cache_serves_on_the_redis_port_inside_the_cluster_ac_118_8(tmp_path):  # AC-118.8
    c = cdoc(ok(tmp_path, csys()), "dev", "statefulset.yaml")["spec"]["template"]["spec"]["containers"][0]
    assert c["ports"] == [{"name": "redis", "containerPort": 6379}] and c["args"][:2] == ["--port", "6379"]


# ---------------- AC-118.11: password ----------------

def test_valkey_requires_the_password_from_the_secret_ac_118_11(tmp_path):  # AC-118.11
    c = cdoc(ok(tmp_path, csys()), "dev", "statefulset.yaml")["spec"]["template"]["spec"]["containers"][0]
    assert c["args"][c["args"].index("--requirepass") + 1] == "$(VALKEY_PASSWORD)"
    assert c["env"] == [{"name": "VALKEY_PASSWORD", "valueFrom": {"secretKeyRef": {"name": "shop-sessions-app", "key": "password"}}}]
    assert "value" not in c["env"][0]


def test_the_probes_authenticate_with_the_password_ac_118_11(tmp_path):  # AC-118.11
    c = cdoc(ok(tmp_path, csys()), "dev", "statefulset.yaml")["spec"]["template"]["spec"]["containers"][0]
    assert c["readinessProbe"]["exec"]["command"] == ["sh", "-c", 'valkey-cli --no-auth-warning -a "$VALKEY_PASSWORD" ping | grep -q PONG']
    assert c["livenessProbe"] == {"tcpSocket": {"port": "redis"}, "initialDelaySeconds": 10, "periodSeconds": 10}


def test_the_container_is_hardened_like_the_guard_rails_demand_ac_118_11(tmp_path):  # AC-118.11
    sts = cdoc(ok(tmp_path, csys()), "dev", "statefulset.yaml")
    pod = sts["spec"]["template"]["spec"]
    assert pod["automountServiceAccountToken"] is False
    assert pod["securityContext"] == {"runAsNonRoot": True, "runAsUser": 999, "runAsGroup": 999, "fsGroup": 999, "seccompProfile": {"type": "RuntimeDefault"}}
    assert pod["containers"][0]["securityContext"] == {"runAsNonRoot": True, "runAsUser": 999, "allowPrivilegeEscalation": False,
                                                       "readOnlyRootFilesystem": True, "capabilities": {"drop": ["ALL"]}}


# ---------------- AC-118.18: what a using component gets ----------------

def test_the_cache_type_contract_is_in_the_renderer_ac_118_18(tmp_path):  # AC-118.18
    t = getattr(renderer("render_118_types"), "TYPES", {}).get("cache")
    assert t is not None, "TYPES has a cache entry"
    assert t["keys"] == CKEYS and t["env"] == CVARS and list(t["env"]) == list(CVARS)


def test_one_cache_gives_the_four_variables_in_table_order_ac_118_18(tmp_path):  # AC-118.18
    g = ok(tmp_path, csys())
    for env in ENVS:
        assert secret_vars(g, env, "api") == contract("sessions")
        assert var_order(g, env, "api") == list(CVARS)


def test_the_variables_are_secret_key_references_in_the_designed_form_ac_118_18(tmp_path):  # AC-118.18
    g = ok(tmp_path, csys())
    got = [e for e in env_list(g, "dev", "api") if e["name"] in CVARS]
    assert got == [{"name": v, "valueFrom": {"secretKeyRef": {"name": "shop-sessions-app", "key": k}}} for v, k in CVARS.items()]


def test_the_variables_come_after_the_literal_env_ac_118_18(tmp_path):  # AC-118.18
    g = ok(tmp_path, csys(comps={"api": comp("api", ["sessions"], env={"LOG": "debug"})}))
    names = [e["name"] for e in env_list(g, "dev", "api")]
    literals = [n for n in names if n not in CVARS]
    assert "LOG" in literals and names == literals + list(CVARS)


def test_a_cache_next_to_a_database_and_a_bucket_gives_bare_variables_ac_118_18(tmp_path):  # AC-118.18
    res = {"sessions": cache(), "orders-db": db(), "files": {"type": "bucket"}}
    g = ok(tmp_path, csys(res, {"api": comp("api", ["sessions", "orders-db", "files"])}))
    got = secret_vars(g, "dev", "api")
    assert got["REDIS_URL"] == ("shop-sessions-app", "url") and got["DATABASE_URL"] == ("shop-orders-db-app", "uri") and got["S3_BUCKET"] == ("shop-files-app", "bucket")
    assert not [n for n in got if n.startswith(("SESSIONS_", "ORDERS_DB_", "FILES_"))]


def test_two_caches_get_prefixed_variables_and_no_bare_ones_ac_118_18(tmp_path):  # AC-118.18
    res = {"sessions": cache(), "ratelimit": cache()}
    g = ok(tmp_path, csys(res, {"api": comp("api", ["sessions", "ratelimit"])}))
    got = secret_vars(g, "dev", "api")
    assert got == {**contract("sessions", "SESSIONS_"), **contract("ratelimit", "RATELIMIT_")}
    assert got["SESSIONS_REDIS_URL"] == ("shop-sessions-app", "url") and got["RATELIMIT_REDIS_PASSWORD"] == ("shop-ratelimit-app", "password")
    assert not [n for n in got if n.startswith("REDIS_")]
    assert var_order(g, "dev", "api") == [f"{p}{v}" for p in ("SESSIONS_", "RATELIMIT_") for v in CVARS]


def test_the_prefix_is_the_upper_cased_name_with_underscores_ac_118_18(tmp_path):  # AC-118.18
    res = {"my-cache": cache(), "other": cache()}
    got = secret_vars(ok(tmp_path, csys(res, {"api": comp("api", ["my-cache", "other"])})), "dev", "api")
    assert got["MY_CACHE_REDIS_PORT"] == ("shop-my-cache-app", "port") and got["OTHER_REDIS_HOST"] == ("shop-other-app", "host")


def test_two_caches_next_to_a_database_prefix_only_the_caches_ac_118_18(tmp_path):  # AC-118.18
    res = {"sessions": cache(), "ratelimit": cache(), "orders-db": db()}
    got = secret_vars(ok(tmp_path, csys(res, {"api": comp("api", ["sessions", "ratelimit", "orders-db"])})), "dev", "api")
    assert got["DATABASE_URL"] == ("shop-orders-db-app", "uri") and "SESSIONS_REDIS_URL" in got and "REDIS_URL" not in got


def test_a_second_component_with_one_cache_keeps_bare_names_and_shares_the_secret_ac_118_18(tmp_path):  # AC-118.18
    res = {"sessions": cache(), "ratelimit": cache()}
    g = ok(tmp_path, csys(res, {"api": comp("api", ["sessions", "ratelimit"]), "web": comp("web", ["sessions"]), "jobs": comp("jobs", ["sessions"])}))
    assert secret_vars(g, "dev", "web") == secret_vars(g, "dev", "jobs") == contract("sessions")
    assert secret_vars(g, "dev", "api")["SESSIONS_REDIS_PASSWORD"] == secret_vars(g, "dev", "web")["REDIS_PASSWORD"]
    assert len([k for k in g if k.startswith(cdir("dev", "sessions") + "/")]) == len(FILES)


@pytest.mark.parametrize("name", ["REDIS_URL", "REDIS_HOST", "REDIS_PORT", "REDIS_PASSWORD"])
def test_an_env_name_that_clashes_with_a_cache_variable_fails_ac_118_18(tmp_path, name):  # AC-118.18
    p = render5(tmp_path, csys(comps={"api": comp("api", ["sessions"], env={name: "x"})}))
    assert p.returncode == 1 and name in p.stderr and "not available yet" not in p.stderr, p.stderr


def test_the_url_names_database_zero_and_the_secret_is_the_same_in_every_environment_ac_118_18(tmp_path):  # AC-118.18
    g = ok(tmp_path, csys())
    for env in ENVS:
        secret = cplan(g, env)["secrets"][0]      # spec 128: the credentials Job writes the Secret from this plan
        assert secret["data"]["url"] == "redis://default:{{ .password }}@" + f"shop-sessions.shop-{env}.svc:6379/0"  # spec 127
        assert secret["name"] == "shop-sessions-app"


# ---------------- AC-118.19: the generated password ----------------

def test_the_credentials_plan_is_the_designed_document_ac_118_19(tmp_path):  # AC-118.19 (spec 128: a Job writes the Secret, no generator)
    g = ok(tmp_path, csys())
    for env in ENVS:
        assert cplan(g, env) == expected_plan(env), env
    secret = cplan(g, "dev")["secrets"][0]
    assert secret["generate"] == {"password": 32} and sorted(secret["data"]) == ["host", "port", "url"]


def test_the_secret_is_written_by_the_job_and_no_externalsecret_or_generator_is_rendered_ac_118_19(tmp_path):  # AC-118.19
    g = ok(tmp_path, csys())
    for env in ENVS:
        names = [k.rsplit("/", 1)[-1] for k in g if k.startswith(cdir(env) + "/")]
        assert "externalsecret.yaml" not in names and "password-generator.yaml" not in names, env
        job = cdoc(g, env, "credentials-job.yaml")
        assert job["metadata"]["annotations"][WAVE] == "1" and job["metadata"]["annotations"]["argocd.argoproj.io/hook"] == "PreSync"
        assert not [k for k in g if k.startswith(cdir(env) + "/") and "kind: Password" in g[k]]


def test_the_kustomization_lists_the_files_sorted_ac_118_19(tmp_path):  # AC-118.19
    assert cdoc(ok(tmp_path, csys()), "dev", "kustomization.yaml") == expected_kustomization()


def test_no_password_value_appears_in_the_rendered_tree_ac_118_19(tmp_path):  # AC-118.19
    g = ok(tmp_path, csys({"sessions": cache(persistence=True), "ratelimit": cache()}, {"api": comp("api", ["sessions", "ratelimit"])}))
    cache_files = {k: t for k, t in g.items() if "/sessions/" in k or "/ratelimit/" in k}
    assert len(cache_files) == 2 * len(FILES) * len(ENVS)  # spec 118 slip: both caches render in every environment
    for k, t in cache_files.items():
        for m in re.finditer(r"(?im)^\s*(password|url)\s*:\s*(.+)$", t):
            assert "{{ .password }}" in m.group(2), f"{k}: a literal credential in {m.group(0)!r}"
        assert not re.search(r"redis://(?:default)?:[^{\s\"']", t), k  # spec 127
    for e in env_list(g, "dev", "api"):
        if "REDIS" in e["name"]:
            assert "value" not in e


def test_renders_keep_the_same_secret_name_keys_and_documents_ac_118_19(tmp_path):  # AC-118.19
    a = ok(tmp_path / "a", csys())
    b = ok(tmp_path / "b", csys({"sessions": cache(version=8, memory="512Mi", persistence=True)}))
    for env in ENVS:
        for f in ("service.yaml", "credentials-configmap.yaml", "credentials-role.yaml", "credentials-job.yaml"):
            assert a[f"{cdir(env)}/{f}"] == b[f"{cdir(env)}/{f}"], (env, f)


def test_an_environment_has_its_own_host_but_the_same_plan_ac_118_19(tmp_path):  # AC-118.19
    g = ok(tmp_path, csys())
    hosts = {cplan(g, e)["secrets"][0]["data"]["host"] for e in ENVS}
    assert hosts == {f"shop-sessions.shop-{e}.svc" for e in ENVS}


# ---------------- AC-118.20: external caches ----------------

def external(resource, store_key):
    es = external_secret(resource, store_key)
    es["spec"]["data"] = [{"secretKey": k, "remoteRef": {"key": store_key, "property": k}} for k in CKEYS]
    return es


def test_an_external_instance_renders_no_valkey_and_the_four_key_externalsecret_ac_118_20(tmp_path):  # AC-118.20
    g = ok(tmp_path, csys({"sessions": cache(instances={"prod": {"external": True}})}))
    assert not [k for k in g if k.startswith(cdir("prod"))], "no in-cluster Valkey in prod"
    assert "sessions" not in addon_names(g, "prod") and "sessions" in addon_names(g, "dev")
    got = y(g, external_secret_path("prod", "api", "sessions"))
    assert got == external("sessions", "shop-prod-sessions")
    assert "dataFrom" not in got["spec"] and "template" not in got["spec"]["target"]


def test_the_external_store_path_follows_the_default_and_remote_overrides_ac_118_20(tmp_path):  # AC-118.20
    g = ok(tmp_path, csys({"sessions": cache(external=True, remote={"path": "caches/{env}/{resource}", "refreshInterval": "30m"})}))
    es = y(g, external_secret_path("dev", "api", "sessions"))
    assert es["spec"]["refreshInterval"] == "30m"
    assert {d["remoteRef"]["key"] for d in es["spec"]["data"]} == {"caches/dev/sessions"}
    assert [d["secretKey"] for d in es["spec"]["data"]] == CKEYS


def test_an_external_cache_gives_the_same_variables_as_an_in_cluster_one_ac_118_20(tmp_path):  # AC-118.20
    g = ok(tmp_path, csys({"sessions": cache(instances={"prod": {"external": True}})}))
    assert secret_vars(g, "prod", "api") == secret_vars(g, "dev", "api") == contract("sessions")
    g = ok(tmp_path / "two", csys({"sessions": cache(external=True), "ratelimit": cache(instances={"dev": {"external": True}})},
                                  {"api": comp("api", ["sessions", "ratelimit"])}))
    assert secret_vars(g, "dev", "api") == {**contract("sessions", "SESSIONS_"), **contract("ratelimit", "RATELIMIT_")}


def test_an_external_everywhere_cache_renders_no_addon_and_no_operator_ac_118_20(tmp_path):  # AC-118.20
    g = ok(tmp_path, csys({"sessions": cache(external=True)}))
    assert not [k for k in g if "/addons/" in k] and not [k for k in g if k.startswith("operators/")]
    assert all(external_secret_path(e, "api", "sessions") in g for e in ENVS)


def test_the_external_secret_has_no_template_so_a_rediss_url_is_passed_unchanged_ac_118_20(tmp_path):  # AC-118.20
    es = y(ok(tmp_path, csys({"sessions": cache(external=True)})), external_secret_path("dev", "api", "sessions"))
    assert "template" not in es["spec"]["target"] and es["spec"]["target"]["name"] == "shop-sessions-app"
    assert all(set(d) == {"secretKey", "remoteRef"} and set(d["remoteRef"]) == {"key", "property"} for d in es["spec"]["data"])


def test_an_external_cache_needs_the_secret_store_ac_118_20(tmp_path):  # AC-118.20
    fails(tmp_path, csys({"sessions": cache(external=True)}, store=False), "secretStore")


# ---------------- AC-118.14: labels and the backup exclusion ----------------

def _excluded(lbls: dict, exprs: list) -> bool:
    for e in exprs:
        if e["operator"] == "NotIn" and lbls.get(e["key"]) in e["values"]:
            return True
        if e["operator"] == "DoesNotExist" and e["key"] in lbls:
            return True
    return False


def backup_system(uses_ratelimit=False, **cache_kw):
    comps = {"api": comp("api", ["orders-db", "backups", "sessions", *(["ratelimit"] if uses_ratelimit else [])])}  # spec 118 slip: an unused cache renders no objects
    return bdoc(envb={"dev": {"to": "backups"}}, resources={"sessions": cache(**cache_kw), "ratelimit": cache(persistence=True)}, comps=comps)


def test_every_cache_object_carries_the_name_label_ac_118_14(tmp_path):  # AC-118.14
    g = ok(tmp_path, csys({"sessions": cache(persistence=True)}))
    for f in FILES:
        if f == "kustomization.yaml":
            continue
        doc = cdoc(g, "dev", f)
        assert doc["metadata"]["labels"] == labels(), f
    sts = cdoc(g, "dev", "statefulset.yaml")
    assert sts["spec"]["template"]["metadata"]["labels"] == labels()
    assert sts["spec"]["volumeClaimTemplates"][0]["metadata"]["labels"] == labels()
    assert cplan(g)["secrets"][0]["labels"] == labels()
    assert sts["spec"]["selector"]["matchLabels"] == {"app.kubernetes.io/name": "sessions", "app.kubernetes.io/part-of": "shop"}


def test_the_schedule_leaves_out_every_cache_by_name_used_or_not_ac_118_14(tmp_path):  # AC-118.14
    g = ok(tmp_path, backup_system())
    t = y(g, f"{APP}/backup/dev/schedule.yaml")["spec"]["template"]
    exprs = t["labelSelector"]["matchExpressions"]
    assert {"key": "app.kubernetes.io/name", "operator": "NotIn", "values": ["backups", "ratelimit", "sessions"]} in exprs


def test_no_cache_object_pod_or_volume_is_selected_by_the_schedule_with_or_without_persistence_ac_118_14(tmp_path):  # AC-118.14
    for persistence in (False, True):
        g = ok(tmp_path / str(persistence), backup_system(uses_ratelimit=True, persistence=persistence))
        exprs = y(g, f"{APP}/backup/dev/schedule.yaml")["spec"]["template"]["labelSelector"]["matchExpressions"]
        for name in ("sessions", "ratelimit"):
            sts = cdoc(g, "dev", "statefulset.yaml", name)
            lbl = [sts["metadata"]["labels"], sts["spec"]["template"]["metadata"]["labels"]]
            lbl += [v["metadata"]["labels"] for v in sts["spec"].get("volumeClaimTemplates", [])]
            lbl += [cdoc(g, "dev", f, name)["metadata"]["labels"] for f in ("service.yaml", "credentials-job.yaml", "credentials-configmap.yaml")]
            lbl += [cplan(g, "dev", name)["secrets"][0]["labels"]]
            assert all(_excluded(l, exprs) for l in lbl), (name, persistence)
        assert cdoc(g, "dev", "statefulset.yaml", "sessions")["spec"]["template"]["metadata"]["labels"]["app.kubernetes.io/name"] == "sessions"


def test_the_schedule_still_selects_other_objects_ac_118_14(tmp_path):  # AC-118.14
    g = ok(tmp_path, backup_system())
    exprs = y(g, f"{APP}/backup/dev/schedule.yaml")["spec"]["template"]["labelSelector"]["matchExpressions"]
    assert not _excluded({"app.kubernetes.io/name": "api", **LABELS}, exprs)


def test_a_cache_adds_no_backup_object_ac_118_14(tmp_path):  # AC-118.14
    a = ok(tmp_path / "a", bdoc(envb={"dev": {"to": "backups"}}))
    b = ok(tmp_path / "b", backup_system())
    assert sorted(k for k in a if "/backup/" in k) == sorted(k for k in b if "/backup/" in k)
    assert not [k for k in b if "/backup" in k and "sessions" in k]


# ---------------- AC-118.22: additive, nothing else changes ----------------

def test_cache_is_no_longer_a_planned_type_and_broker_still_is_ac_118_22(tmp_path):  # AC-118.22
    r = renderer("render_118_planned")
    assert getattr(r, "PLANNED_TYPES", None) == {}  # spec 119: broker is built, no type is planned
    assert "cache" in r.RESOURCE_TYPES and tuple(r.RESOURCE_TYPES) == ("database", "bucket", "cache", "broker")


def test_a_cache_resource_is_not_refused_as_not_available_ac_118_22(tmp_path):  # AC-118.22
    p = render5(tmp_path, system({"store": {"type": "cache"}}))
    assert p.returncode == 0, p.stdout + p.stderr


def test_the_broker_keeps_its_message_ac_118_22(tmp_path):  # AC-118.22
    g = ok(tmp_path, system({"store": {"type": "broker"}}))  # spec 119: an unused broker renders
    assert not [k for k in g if "/addons/" in k]  # spec 119: and writes no addon path


@pytest.mark.parametrize("value", ["queue", "Bucket", "s3", "memcached"])
def test_every_other_type_is_refused_with_the_same_message_ac_118_22(tmp_path, value):  # AC-118.22
    fails(tmp_path, system({"x": {"type": value}}), P + f"resources.x: type '{value}' is not a resource type (database, bucket, cache or broker)")


def test_a_component_may_not_use_an_undeclared_resource_still_ac_118_22(tmp_path):  # AC-118.22
    p = render5(tmp_path, csys({"sessions": cache()}, {"api": comp("api", ["nope"])}))
    assert p.returncode == 1 and "nope" in p.stderr


def test_the_database_and_bucket_texts_are_unchanged_ac_118_22(tmp_path):  # AC-118.22
    fails(tmp_path, system({"d": {"type": "database", "bogus": 1}}), "resources.d: unknown key 'bogus'")
    fails(tmp_path, system({"b": {"type": "bucket", "version": 17}}), "resources.b: unknown key 'version' (allowed: type, external, remote, storage, versioning, instances)")


def test_object_names_of_a_cache_may_not_clash_with_another_resource_ac_118_22(tmp_path):  # AC-118.22
    fails(tmp_path, csys({"sessions": cache(), "sessions-app": cache()}, {"api": comp("api", ["sessions", "sessions-app"])}),
          "would both create the object shop-sessions-app; rename one")


def test_a_cache_name_clashing_with_its_password_object_fails_ac_118_22(tmp_path):  # AC-118.22
    fails(tmp_path, csys({"sessions": cache(), "sessions-password": cache()}, {"api": comp("api", ["sessions", "sessions-password"])}),
          "would both create the object shop-sessions-password; rename one")


# byte-identical guarantee: digests of the trees the 5.x renderer wrote before spec 118 (full tree, sha256 of sorted path and content)
BEFORE_118 = {"full5": ("327d41a6f2cdc9c46124f7b088b13b2bcfe154dfb878ebfb87b3845bd048cf02", 67),   # spec 128: a generated component secret gets a credentials Job
              "rich5": ("fe1543fc8b668272d474fb2a3c81de372ae673a2023c1dae8521a3143d7473be", 67),   # spec 128: a generated component secret gets a credentials Job
              "db-bucket": ("ae098881e7b6a57b03e99b36924de150f513b06e1dad3c42b303e79400e930d8", 56)}   # spec 128: the credentials Job replaces the bucket's generators and ExternalSecret


def _before_docs():
    return {"full5": full5(), "rich5": rich5(),
            "db-bucket": system({"orders-db": db(version=16, replicas=2), "files": {"type": "bucket", "storage": "5Gi", "versioning": True}},
                                {"api": comp("api", ["orders-db", "files"])})}


@pytest.mark.parametrize("label", list(BEFORE_118))
def test_a_5x_system_without_a_cache_renders_byte_identically_to_before_ac_118_22(tmp_path, label):  # AC-118.22
    g = ok(tmp_path, _before_docs()[label])
    digest, count = BEFORE_118[label]
    assert (len(g), tree_digest(unpin(g))) == (count, digest), f"{label}: the render changed although the system has no cache"  # spec 121: only the engine references changed


def test_an_unused_cache_changes_nothing_in_the_tree_ac_118_22(tmp_path):  # AC-118.22
    a = ok(tmp_path / "a", system({"d": db()}, {"api": comp("api", ["d"])}))
    b = ok(tmp_path / "b", system({"d": db(), "idle": cache()}, {"api": comp("api", ["d"])}))
    assert a == b


# ---------------- AC-118.23: a platform-rendered StatefulSet, no operator ----------------

def test_a_cache_renders_only_plain_kinds_ac_118_23(tmp_path):  # AC-118.23
    g = ok(tmp_path, csys({"sessions": cache(persistence=True)}))
    kinds = sorted(cdoc(g, "dev", f)["kind"] for f in FILES)
    assert kinds == ["ConfigMap", "Job", "Kustomization", "Role", "RoleBinding", "Service", "ServiceAccount", "StatefulSet"]
    assert cdoc(g, "dev", "statefulset.yaml")["spec"]["template"]["spec"]["containers"][0]["image"].startswith("valkey/valkey:")


@pytest.mark.parametrize("mode", ["default", "owner"])
def test_a_cache_adds_no_operator_with_or_without_operators_owner_ac_118_23(tmp_path, mode):  # AC-118.23
    doc = csys()
    if mode == "owner":
        for e in ENVS:
            doc["environments"][e]["operators"] = "owner"
    g = ok(tmp_path, doc)
    assert not [k for k in g if k.startswith("operators/")], "a cache needs no operator"
    assert [k for k in g if k.startswith(cdir("dev"))], "the cache itself is rendered"


def test_owner_managed_environments_still_render_the_same_cache_ac_118_23(tmp_path):  # AC-118.23
    plain = ok(tmp_path / "a", csys())
    doc = csys()
    doc["environments"]["dev"]["operators"] = "owner"
    owner = ok(tmp_path / "b", doc)
    assert {k: v for k, v in plain.items() if k.startswith(cdir("dev"))} == {k: v for k, v in owner.items() if k.startswith(cdir("dev"))}


def test_a_cache_next_to_a_database_leaves_the_operators_as_they_were_ac_118_23(tmp_path):  # AC-118.23
    a = ok(tmp_path / "a", system({"d": db()}, {"api": comp("api", ["d"])}))
    b = ok(tmp_path / "b", system({"d": db(), "sessions": cache()}, {"api": comp("api", ["d", "sessions"])}))
    assert {k: v for k, v in a.items() if k.startswith("operators/")} == {k: v for k, v in b.items() if k.startswith("operators/")}


def test_the_cache_is_an_element_of_the_environments_addon_set_ac_118_23(tmp_path):  # AC-118.23
    g = ok(tmp_path, csys())
    assert addon_names(g, "dev") == ["sessions"]
    s = sets(g)["shop-addons-dev"]
    assert s["spec"]["template"]["metadata"]["name"] == "addon-{{name}}-dev"
    assert s["spec"]["template"]["spec"]["syncPolicy"].get("automated", {}).get("prune") is False


def test_an_environment_without_a_running_user_gets_no_cache_ac_118_23(tmp_path):  # AC-118.23
    g = ok(tmp_path, csys(comps={"api": comp("api", ["sessions"], envs=("dev",)), "web": comp("web")}))
    assert addon_names(g, "dev") == ["sessions"] and "sessions" not in addon_names(g, "staging")
    assert not [k for k in g if "/addons/staging/sessions" in k or "/addons/prod/sessions" in k]


def test_resource_add_names_the_same_store_keys_as_the_renderer_ac_118_1():  # AC-118.1
    # spec 118 review: addon.py keeps its own copy of each built type's store keys; it must match the renderer's TYPES
    import addon
    r = renderer("render_118_keys")
    built = [t for t in r.TYPES if t not in r.PLANNED_TYPES]
    assert sorted(addon.TYPE_KEYS) == sorted(built)
    for t in built:
        assert addon.TYPE_KEYS[t] == ", ".join(r.TYPES[t]["keys"]), t
