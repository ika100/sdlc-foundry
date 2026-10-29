"""Spec 116 acceptance tests, the renderer part: the `bucket` resource type (AC-116.1, .2, .4, .5, .6, .7, .8, .10, .12 render side,
.15, .16, .17, .18 render side, .19, .20 render side).

Contract: design.md "Contract: system.yaml", "what a using component gets", "in-cluster bucket instance", "external bucket instance" and
"operators". The renderer runs as a script in a hand-built checkout (resources_fixtures); nothing touches the network or a cluster.
Criteria that need a cluster (AC-116.5 cross-environment refusal, .6, .7, .8, .14, .18 behaviour) are covered here by the rendered
contract and in test_bucket_116_cmds.py by the text of tests/e2e/run.sh. The commands, the model, doctor and the template scripts
are in test_bucket_116_cmds.py. Missing symbols are guarded with getattr so each test fails on its own."""
import re
import subprocess
import sys

import pytest
import yaml

from resources_fixtures import (APP, ENVS, LABELS, addon_names, comp, db, env_list, external_secret, external_secret_path, fails, ok,
                                platform_render_module, render5, secret_vars, sets, system, tree, var_order, y)
from system_fixtures import ROOT, tiny

P = "applications/shop/system.yaml: "
BKEYS = ["endpoint", "bucket", "region", "forcePathStyle", "accessKeyId", "secretAccessKey"]
BVARS = {"S3_ENDPOINT": "endpoint", "S3_BUCKET": "bucket", "S3_REGION": "region", "S3_FORCE_PATH_STYLE": "forcePathStyle",
         "AWS_ACCESS_KEY_ID": "accessKeyId", "AWS_SECRET_ACCESS_KEY": "secretAccessKey", "AWS_REGION": "region", "AWS_ENDPOINT_URL_S3": "endpoint"}
ALLOWED_TOP = "type, external, remote, storage, versioning, instances"
ALLOWED_INST = "external, remote, storage, versioning"
S3_RULE = "3 to 63 characters, lowercase letters, digits and hyphens, starting and ending with a letter or digit"
ANN_KEEP = "argocd.argoproj.io/sync-options"
WAVE = "argocd.argoproj.io/sync-wave"
FILES = ["access-key-generator.yaml", "bucket.yaml", "credentials.yaml", "externalsecret.yaml", "identity.yaml", "kustomization.yaml",
         "seaweed.yaml", "secret-key-generator.yaml"]


def bucket(**kw) -> dict:
    return {"type": "bucket", **kw}


def bsys(resources=None, comps=None, **top) -> dict:
    if resources is None:
        resources = {"files": bucket()}
    if comps is None:
        comps = {"api": comp("api", ["files"])}
    return system(resources, comps, **top)


def contract(resource: str, prefix: str = "") -> dict:
    return {prefix + v: (f"shop-{resource}-app", k) for v, k in BVARS.items()}


def bdir(env: str, name: str = "files") -> str:
    return f"{APP}/addons/{env}/{name}"


def bdoc(g, env, file, name="files"):
    return y(g, f"{bdir(env, name)}/{file}")


def labels(name="files") -> dict:
    return {"app.kubernetes.io/name": name, **LABELS}


def keep(**more) -> dict:
    return {ANN_KEEP: "Delete=false", **more}


def image() -> str:
    r = platform_render_module("render_116")
    v = getattr(r, "SEAWEEDFS_IMAGE", None)
    assert v is not None, "render.py has SEAWEEDFS_IMAGE"
    return v


# ---------------- AC-116.1: schema ----------------

def test_a_bucket_with_all_its_keys_is_accepted_ac_116_1(tmp_path):  # AC-116.1
    res = {"files": bucket(storage="20Gi", versioning=True, instances={"dev": {"storage": "1Gi", "versioning": False}, "prod": {"external": True}})}
    ok(tmp_path, bsys(res))


def test_a_bucket_with_the_external_keys_of_spec_115_is_accepted_ac_116_1(tmp_path):  # AC-116.1
    res = {"files": bucket(external=True, remote={"path": "{env}/{resource}", "refreshInterval": "2h"})}
    ok(tmp_path, bsys(res))


def test_an_unknown_bucket_key_fails_naming_resource_key_and_allowed_keys_ac_116_1(tmp_path):  # AC-116.1
    fails(tmp_path, bsys({"files": bucket(replicas=2)}), P + f"resources.files: unknown key 'replicas' (allowed: {ALLOWED_TOP})")


def test_a_database_key_on_a_bucket_is_unknown_ac_116_1(tmp_path):  # AC-116.1
    fails(tmp_path, bsys({"files": bucket(version=17)}), P + f"resources.files: unknown key 'version' (allowed: {ALLOWED_TOP})")


def test_an_unknown_instance_key_fails_ac_116_1(tmp_path):  # AC-116.1
    fails(tmp_path, bsys({"files": bucket(instances={"dev": {"replicas": 2}})}),
          P + f"resources.files.instances.dev: unknown key 'replicas' (allowed: {ALLOWED_INST})")


@pytest.mark.parametrize("bad", ["true", "yes", 1, 0, None, "false"])
def test_versioning_must_be_true_or_false_ac_116_1(tmp_path, bad):  # AC-116.1
    fails(tmp_path, bsys({"files": bucket(versioning=bad)}), P + "resources.files: versioning must be true or false")


def test_an_instance_versioning_must_be_true_or_false_ac_116_1(tmp_path):  # AC-116.1
    fails(tmp_path, bsys({"files": bucket(instances={"staging": {"versioning": "on"}})}),
          P + "resources.files.instances.staging: versioning must be true or false")


@pytest.mark.parametrize("bad", ["big", "10 Gi", "10GB", 10, "", "-1Gi"])
def test_storage_must_be_a_size_ac_116_1(tmp_path, bad):  # AC-116.1
    fails(tmp_path, bsys({"files": bucket(storage=bad)}), P + "resources.files: storage must be a size such as 10Gi")


def test_an_instance_storage_must_be_a_size_ac_116_1(tmp_path):  # AC-116.1
    fails(tmp_path, bsys({"files": bucket(instances={"dev": {"storage": "lots"}})}),
          P + "resources.files.instances.dev: storage must be a size such as 10Gi")


def test_an_unused_bucket_is_validated_too_ac_116_1(tmp_path):  # AC-116.1
    fails(tmp_path, bsys({"files": bucket(bogus=1)}, {"api": comp("api")}), "resources.files: unknown key 'bogus'")


# ---------------- AC-116.10: an external bucket is sized at its provider ----------------

@pytest.mark.parametrize("key, value", [("storage", "5Gi"), ("versioning", True)])
def test_an_external_instance_may_not_set_storage_or_versioning_ac_116_10(tmp_path, key, value):  # AC-116.10
    fails(tmp_path, bsys({"files": bucket(instances={"prod": {"external": True, key: value}})}),
          P + f"resources.files.instances.prod: an external bucket is sized and configured at its provider (remove {key})")


def test_an_instance_inheriting_external_may_not_set_sizing_ac_116_10(tmp_path):  # AC-116.10
    fails(tmp_path, bsys({"files": bucket(external=True, instances={"staging": {"storage": "5Gi"}})}),
          P + "resources.files.instances.staging: an external bucket is sized and configured at its provider (remove storage)")


@pytest.mark.parametrize("key, value", [("storage", "5Gi"), ("versioning", False)])
def test_top_level_sizing_of_a_bucket_that_is_external_everywhere_fails_ac_116_10(tmp_path, key, value):  # AC-116.10
    fails(tmp_path, bsys({"files": bucket(external=True, **{key: value})}),
          P + f"resources.files: external in every environment: an external bucket is sized and configured at its provider (remove {key})")


def test_top_level_sizing_is_fine_while_one_environment_runs_the_bucket_ac_116_10(tmp_path):  # AC-116.10
    ok(tmp_path, bsys({"files": bucket(storage="5Gi", versioning=True, instances={"prod": {"external": True}})}))


# ---------------- AC-116.2: one bucket per using environment ----------------

def test_each_using_environment_gets_exactly_one_bucket_named_system_dash_name_ac_116_2(tmp_path):  # AC-116.2
    g = ok(tmp_path, bsys({"files": bucket(storage="7Gi")}))
    for env in ENVS:
        assert sorted(k.rsplit("/", 1)[-1] for k in g if k.startswith(bdir(env) + "/")) == FILES, env
        b = bdoc(g, env, "bucket.yaml")
        assert (b["kind"], b["metadata"]["name"], b["spec"]["name"]) == ("Bucket", "shop-files", "shop-files")
        assert bdoc(g, env, "seaweed.yaml")["spec"]["volume"]["requests"]["storage"] == "7Gi"
    assert len([k for k in g if "/addons/" in k and k.endswith("/bucket.yaml")]) == 3


def test_defaults_are_10gi_and_unversioned_ac_116_2(tmp_path):  # AC-116.2
    g = ok(tmp_path, bsys())
    assert bdoc(g, "dev", "seaweed.yaml")["spec"]["volume"]["requests"]["storage"] == "10Gi"
    assert bdoc(g, "dev", "bucket.yaml")["spec"]["versioning"] == "Suspended"


def test_an_environment_without_a_running_user_gets_no_bucket_ac_116_2(tmp_path):  # AC-116.2
    doc = bsys(comps={"api": comp("api", ["files"], envs=("dev",)), "web": comp("web")})
    g = ok(tmp_path, doc)
    assert [k for k in g if "/addons/" in k and "files" in k] and not [k for k in g if "/addons/staging/files" in k or "/addons/prod/files" in k]
    assert addon_names(g, "dev") == ["files"] and "files" not in addon_names(g, "staging")


def test_an_unused_bucket_renders_nowhere_ac_116_2(tmp_path):  # AC-116.2
    g = ok(tmp_path, bsys({"files": bucket()}, {"api": comp("api")}))
    assert not [k for k in g if "files" in k and k.startswith(APP + "/addons")]
    assert not [k for k in g if k.startswith("operators/")]


def test_instance_values_override_storage_and_versioning_per_environment_ac_116_2(tmp_path):  # AC-116.2
    res = {"files": bucket(storage="5Gi", instances={"prod": {"storage": "100Gi", "versioning": True}, "staging": {"storage": "1Ti"}})}
    g = ok(tmp_path, bsys(res))
    got = {e: (bdoc(g, e, "seaweed.yaml")["spec"]["volume"]["requests"]["storage"], bdoc(g, e, "bucket.yaml")["spec"]["versioning"]) for e in ENVS}
    assert got == {"dev": ("5Gi", "Suspended"), "staging": ("1Ti", "Suspended"), "prod": ("100Gi", "Enabled")}


def test_the_bucket_is_an_element_of_the_environments_addon_set_ac_116_2(tmp_path):  # AC-116.2
    g = ok(tmp_path, bsys())
    assert addon_names(g, "dev") == ["files"]
    s = sets(g)["shop-addons-dev"]
    assert s["spec"]["template"]["metadata"]["name"] == "addon-{{name}}-dev"


def test_a_bucket_name_that_is_not_a_valid_s3_name_fails_naming_name_and_rule_ac_116_2(tmp_path):  # AC-116.2
    fails(tmp_path, bsys({"files-": bucket()}, {"api": comp("api", ["files-"])}),
          P + f"resources.files-: 'shop-files-' is not a valid S3 bucket name ({S3_RULE})")


def test_the_s3_name_rule_is_not_checked_where_every_environment_is_external_ac_116_2(tmp_path):  # AC-116.2
    ok(tmp_path, bsys({"files-": bucket(external=True)}, {"api": comp("api", ["files-"])}))


def _long(tmp_path, n_system, n_name):
    doc = bsys({"f" * n_name: bucket()}, {"api": comp("api", ["f" * n_name])})
    doc["system"] = "s" * n_system
    return render5(tmp_path, doc, name="s" * n_system)


def test_a_name_over_45_characters_fails_the_render_ac_116_2(tmp_path):  # AC-116.2
    p = _long(tmp_path, 15, 30)                       # 15 + 1 + 30 = 46
    assert p.returncode == 1, p.stdout + p.stderr
    name = "s" * 15 + "-" + "f" * 30
    assert f"resources.{'f' * 30}: '{name}' is too long for the in-cluster store (at most 45 characters)" in p.stderr


def test_a_name_of_exactly_45_characters_renders_ac_116_2(tmp_path):  # AC-116.2
    p = _long(tmp_path, 15, 29)                       # 45
    assert p.returncode == 0, p.stdout + p.stderr


def test_the_45_character_rule_does_not_apply_to_external_buckets_ac_116_2(tmp_path):  # AC-116.2
    doc = bsys({"f" * 30: bucket(external=True)}, {"api": comp("api", ["f" * 30])})
    doc["system"] = "s" * 15
    p = render5(tmp_path, doc, name="s" * 15)
    assert p.returncode == 0, p.stdout + p.stderr


def test_object_names_of_the_store_may_not_clash_with_another_resource_ac_116_2(tmp_path):  # AC-116.2
    fails(tmp_path, bsys({"files": bucket(), "files-filer": bucket()}, {"api": comp("api", ["files", "files-filer"])}),
          "resources.files and resources.files-filer would both create the object shop-files-filer; rename one")


# ---------------- AC-116.16: what a using component gets ----------------

def test_the_bucket_type_contract_is_in_the_renderer_ac_116_16(tmp_path):  # AC-116.16
    r = platform_render_module("render_116_types")
    t = getattr(r, "TYPES", {}).get("bucket")
    assert t is not None, "TYPES has a bucket entry"
    assert t["keys"] == BKEYS and t["env"] == BVARS and list(t["env"]) == list(BVARS)


def test_one_bucket_gives_the_eight_variables_in_table_order_ac_116_16(tmp_path):  # AC-116.16
    g = ok(tmp_path, bsys())
    for env in ENVS:
        assert secret_vars(g, env, "api") == contract("files")
        assert var_order(g, env, "api") == list(BVARS)


def test_the_variables_come_after_the_literal_env_ac_116_16(tmp_path):  # AC-116.16
    g = ok(tmp_path, bsys(comps={"api": comp("api", ["files"], env={"LOG": "debug"})}))
    names = [e["name"] for e in env_list(g, "dev", "api")]
    literals = [n for n in names if n not in BVARS]      # LOG plus the literals every deployment gets (PORT)
    assert "LOG" in literals and names == literals + list(BVARS)


def test_a_bucket_and_a_database_both_give_bare_variables_ac_116_16(tmp_path):  # AC-116.16
    doc = bsys({"files": bucket(), "orders-db": db()}, {"api": comp("api", ["files", "orders-db"])})
    g = ok(tmp_path, doc)
    got = secret_vars(g, "dev", "api")
    assert got["S3_BUCKET"] == ("shop-files-app", "bucket") and got["DATABASE_URL"] == ("shop-orders-db-app", "uri")
    assert not [n for n in got if n.startswith(("FILES_", "ORDERS_DB_"))]


def test_the_secret_carries_the_six_keys_for_an_in_cluster_bucket_ac_116_16(tmp_path):  # AC-116.16
    g = ok(tmp_path, bsys())
    es = bdoc(g, "dev", "externalsecret.yaml")
    assert es["metadata"]["name"] == "shop-files-app" and es["spec"]["target"]["name"] == "shop-files-app"
    data = es["spec"]["target"]["template"]["data"]
    assert sorted(data) == sorted(BKEYS)
    assert data["endpoint"] == "http://shop-files-filer.shop-dev.svc:8333" and data["bucket"] == "shop-files"
    assert data["region"] == "us-east-1" and data["forcePathStyle"] == "true"
    assert bdoc(g, "staging", "externalsecret.yaml")["spec"]["target"]["template"]["data"]["endpoint"] == "http://shop-files-filer.shop-staging.svc:8333"


def test_the_names_are_the_same_in_every_environment_ac_116_16(tmp_path):  # AC-116.16
    g = ok(tmp_path, bsys())
    assert {bdoc(g, e, "bucket.yaml")["spec"]["name"] for e in ENVS} == {"shop-files"}
    assert {bdoc(g, e, "externalsecret.yaml")["metadata"]["name"] for e in ENVS} == {"shop-files-app"}


# ---------------- AC-116.4: several buckets ----------------

def test_two_buckets_get_prefixed_variables_and_no_bare_ones_ac_116_4(tmp_path):  # AC-116.4
    doc = bsys({"uploads": bucket(), "exports": bucket()}, {"api": comp("api", ["uploads", "exports"])})
    g = ok(tmp_path, doc)
    got = secret_vars(g, "dev", "api")
    assert got == {**contract("uploads", "UPLOADS_"), **contract("exports", "EXPORTS_")}
    assert got["UPLOADS_S3_BUCKET"] == ("shop-uploads-app", "bucket")
    assert not [n for n in got if n.startswith(("S3_", "AWS_"))]
    assert var_order(g, "dev", "api") == [f"{p}{v}" for p in ("UPLOADS_", "EXPORTS_") for v in BVARS]


def test_the_prefix_is_the_upper_cased_name_with_underscores_ac_116_4(tmp_path):  # AC-116.4
    doc = bsys({"my-files": bucket(), "other": bucket()}, {"api": comp("api", ["my-files", "other"])})
    got = secret_vars(ok(tmp_path, doc), "dev", "api")
    assert got["MY_FILES_AWS_REGION"] == ("shop-my-files-app", "region") and got["OTHER_AWS_ENDPOINT_URL_S3"] == ("shop-other-app", "endpoint")


def test_a_second_component_with_one_bucket_keeps_bare_names_ac_116_4(tmp_path):  # AC-116.4
    doc = bsys({"uploads": bucket(), "exports": bucket()}, {"api": comp("api", ["uploads", "exports"]), "web": comp("web", ["exports"])})
    g = ok(tmp_path, doc)
    assert secret_vars(g, "dev", "web") == contract("exports")


def test_prefixed_names_follow_external_buckets_too_ac_116_4(tmp_path):  # AC-116.4
    doc = bsys({"uploads": bucket(), "exports": bucket(external=True, instances={"dev": {"external": False}})},
               {"api": comp("api", ["uploads", "exports"])})
    g = ok(tmp_path, doc)
    assert secret_vars(g, "prod", "api") == {**contract("uploads", "UPLOADS_"), **contract("exports", "EXPORTS_")}


def test_an_env_name_that_clashes_with_a_bucket_variable_fails_ac_116_4(tmp_path):  # AC-116.4
    p = render5(tmp_path, bsys(comps={"api": comp("api", ["files"], env={"S3_BUCKET": "x"})}))
    assert p.returncode == 1 and "S3_BUCKET" in p.stderr, p.stderr


# ---------------- AC-116.5: no credential in git ----------------

def _strings(node, path=()):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _strings(v, path + (k,))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _strings(v, path + (str(i),))
    elif isinstance(node, str):
        yield path, node


def test_no_credential_value_appears_in_the_rendered_tree_ac_116_5(tmp_path):  # AC-116.5
    g = ok(tmp_path, bsys({"files": bucket(), "ext": bucket(instances={"prod": {"external": True}})}, {"api": comp("api", ["files", "ext"])}))
    assert [k for k in g if "/addons/" in k and "/files/" in k]
    for path, text in g.items():
        if not path.endswith((".yaml", ".yml")):
            continue
        for doc in yaml.safe_load_all(text):
            for where, s in _strings(doc):
                last = where[-1] if where else ""
                if last in ("accessKeyId", "secretAccessKey") and "template" in where:
                    assert s in ("{{ .accessKeyId }}", "{{ .secretAccessKey }}"), f"{path}: literal credential at {where}"
                if last in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY") or (last == "value" and "env" in where and "KEY" in "".join(where)):
                    raise AssertionError(f"{path}: a credential variable with a literal value at {where}")


def test_the_credential_variables_are_only_secret_references_ac_116_5(tmp_path):  # AC-116.5
    g = ok(tmp_path, bsys())
    for e in env_list(g, "dev", "api"):
        if e["name"] in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
            assert "value" not in e and set(e["valueFrom"]) == {"secretKeyRef"}


def test_in_cluster_credentials_are_generated_by_two_password_generators_per_environment_ac_116_5(tmp_path):  # AC-116.5
    g = ok(tmp_path, bsys())
    for env in ("dev", "staging"):
        for fname, suffix, length, digits in (("access-key-generator.yaml", "access-key", 20, 5), ("secret-key-generator.yaml", "secret-key", 40, 10)):
            gen = bdoc(g, env, fname)
            assert gen == {"apiVersion": "generators.external-secrets.io/v1alpha1", "kind": "Password",
                           "metadata": {"name": f"shop-files-{suffix}", "labels": labels(), "annotations": keep(**{WAVE: "-1"})},
                           "spec": {"length": length, "digits": digits, "symbols": 0, "noUpper": False, "allowRepeat": True}}


def test_each_environment_has_its_own_store_and_identity_so_keys_do_not_cross_ac_116_5(tmp_path):  # AC-116.5
    g = ok(tmp_path, bsys())
    for env in ("dev", "staging", "prod"):
        ident = bdoc(g, env, "identity.yaml")
        seaweed = bdoc(g, env, "seaweed.yaml")
        assert ident["kind"] == "S3Identity" and ident["spec"] == {"seaweedRef": {"name": "shop-files"}}
        assert seaweed["kind"] == "Seaweed" and seaweed["metadata"]["name"] == "shop-files"
        b = bdoc(g, env, "bucket.yaml")["spec"]
        assert b["clusterRef"] == {"name": "shop-files"} and b["access"] == [{"user": "shop-files", "actions": ["Read", "Write", "List", "Tagging"]}]
    # the endpoint (and so the store) differs per namespace
    eps = {bdoc(g, e, "externalsecret.yaml")["spec"]["target"]["template"]["data"]["endpoint"] for e in ENVS}
    assert len(eps) == 3


def test_the_credentials_object_adopts_the_generated_secret_ac_116_5(tmp_path):  # AC-116.5
    g = ok(tmp_path, bsys())
    assert bdoc(g, "dev", "credentials.yaml") == {
        "apiVersion": "seaweed.seaweedfs.com/v1", "kind": "S3Credentials",
        "metadata": {"name": "shop-files", "labels": labels(), "annotations": keep(**{WAVE: "1"})},
        "spec": {"seaweedRef": {"name": "shop-files"}, "identityRef": {"name": "shop-files"},
                 "secretRef": {"name": "shop-files-app", "accessKeyField": "accessKeyId", "secretKeyField": "secretAccessKey"},
                 "reclaimPolicy": "Retain"}}


def test_the_e2e_script_proves_the_cross_environment_refusal_ac_116_5():  # AC-116.5 (needs a cluster: covered by tests/e2e/run.sh)
    text = (ROOT / "tests" / "e2e" / "run.sh").read_text()
    assert "access denied" in text and "staging" in text and "--type bucket" in text


# ---------------- AC-116.6 / AC-116.7 / AC-116.8: rendered contract (behaviour needs a cluster) ----------------

def test_every_using_component_shares_one_store_and_one_secret_ac_116_6(tmp_path):  # AC-116.6
    doc = bsys(comps={"api": comp("api", ["files"]), "web": comp("web", ["files"])})
    g = ok(tmp_path, doc)
    assert secret_vars(g, "dev", "api") == secret_vars(g, "dev", "web") == contract("files")
    assert len([k for k in g if k.startswith(bdir("dev") + "/")]) == len(FILES)
    es = [k for k in g if k.endswith("externalsecret-shop-files-app.yaml")]
    assert es == [], "an in-cluster bucket's Secret comes from the addon directory only"


def test_the_identity_has_read_write_list_and_tagging_on_its_bucket_only_ac_116_6(tmp_path):  # AC-116.6
    b = bdoc(ok(tmp_path, bsys()), "dev", "bucket.yaml")
    assert b == {"apiVersion": "seaweed.seaweedfs.com/v1", "kind": "Bucket",
                 "metadata": {"name": "shop-files", "labels": labels(), "annotations": keep()},
                 "spec": {"name": "shop-files", "clusterRef": {"name": "shop-files"}, "reclaimPolicy": "Retain", "versioning": "Suspended",
                          "owner": "shop-files", "access": [{"user": "shop-files", "actions": ["Read", "Write", "List", "Tagging"]}]}}
    assert list(b["spec"]) == ["name", "clusterRef", "reclaimPolicy", "versioning", "owner", "access"]


def test_versioning_true_renders_enabled_and_false_suspended_ac_116_7(tmp_path):  # AC-116.7
    g = ok(tmp_path, bsys({"files": bucket(versioning=True, instances={"staging": {"versioning": False}})}))
    assert [bdoc(g, e, "bucket.yaml")["spec"]["versioning"] for e in ENVS] == ["Enabled", "Suspended", "Enabled"]


def test_the_e2e_script_proves_versions_and_restart_ac_116_7_and_ac_116_8():  # AC-116.7, AC-116.8 (need a cluster: covered by tests/e2e/run.sh)
    text = (ROOT / "tests" / "e2e" / "run.sh").read_text()
    for needle in ("versioning", "version-id", "--type bucket"):
        assert needle in text, f"tests/e2e/run.sh lacks {needle!r}"


def test_the_store_keeps_its_data_on_persistent_volumes_ac_116_8(tmp_path):  # AC-116.8
    s = bdoc(ok(tmp_path, bsys()), "dev", "seaweed.yaml")["spec"]
    assert s["master"]["persistence"]["enabled"] is True and s["filer"]["persistence"]["enabled"] is True
    assert s["volume"]["requests"]["storage"] == "10Gi" and s["volumeServerDiskCount"] == 1
    assert s["filer"]["s3"] == {"enabled": True}


def test_the_seaweed_object_is_exactly_the_designed_document_ac_116_8(tmp_path):  # AC-116.8
    sw = bdoc(ok(tmp_path, bsys({"files": bucket(storage="3Gi")})), "dev", "seaweed.yaml")
    assert sw == {"apiVersion": "seaweed.seaweedfs.com/v1", "kind": "Seaweed",
                  "metadata": {"name": "shop-files", "labels": labels(), "annotations": keep()},
                  "spec": {"image": image(), "volumeServerDiskCount": 1,
                           "master": {"replicas": 1, "volumeSizeLimitMB": 1024, "persistence": {"enabled": True, "resources": {"requests": {"storage": "1Gi"}}}},
                           "volume": {"replicas": 1, "requests": {"storage": "3Gi"}},
                           "filer": {"replicas": 1, "persistence": {"enabled": True, "resources": {"requests": {"storage": "1Gi"}}},
                                     "s3": {"enabled": True}, "config": '[leveldb2]\nenabled = true\ndir = "/data/filerldb2"\n'}}}
    assert list(sw["spec"]) == ["image", "volumeServerDiskCount", "master", "volume", "filer"]


def test_the_externalsecret_of_an_in_cluster_bucket_is_exactly_the_designed_document_ac_116_8(tmp_path):  # AC-116.8
    es = bdoc(ok(tmp_path, bsys()), "dev", "externalsecret.yaml")
    ref = lambda n: {"sourceRef": {"generatorRef": {"apiVersion": "generators.external-secrets.io/v1alpha1", "kind": "Password", "name": f"shop-files-{n}"}},
                     "rewrite": [{"regexp": {"source": "^password$", "target": "accessKeyId" if n == "access-key" else "secretAccessKey"}}]}
    assert es == {"apiVersion": "external-secrets.io/v1", "kind": "ExternalSecret",
                  "metadata": {"name": "shop-files-app", "labels": labels(), "annotations": keep(**{WAVE: "-1"})},
                  "spec": {"refreshInterval": "0",
                           "target": {"name": "shop-files-app", "creationPolicy": "Owner", "deletionPolicy": "Retain",
                                      "template": {"engineVersion": "v2", "data": {
                                          "endpoint": "http://shop-files-filer.shop-dev.svc:8333", "bucket": "shop-files", "region": "us-east-1",
                                          "forcePathStyle": "true", "accessKeyId": "{{ .accessKeyId }}", "secretAccessKey": "{{ .secretAccessKey }}"}}},
                           "dataFrom": [ref("access-key"), ref("secret-key")]}}


# ---------------- AC-116.12: Argo CD never deletes a bucket (render side) ----------------

def test_every_object_of_an_in_cluster_bucket_is_kept_when_argo_prunes_ac_116_12(tmp_path):  # AC-116.12
    g = ok(tmp_path, bsys())
    for f in FILES:
        if f == "kustomization.yaml":
            continue
        doc = bdoc(g, "dev", f)
        assert doc["metadata"]["annotations"][ANN_KEEP] == "Delete=false", f


def test_buckets_and_credentials_are_retained_ac_116_12(tmp_path):  # AC-116.12
    g = ok(tmp_path, bsys())
    assert bdoc(g, "dev", "bucket.yaml")["spec"]["reclaimPolicy"] == "Retain"
    assert bdoc(g, "dev", "credentials.yaml")["spec"]["reclaimPolicy"] == "Retain"
    assert bdoc(g, "dev", "externalsecret.yaml")["spec"]["target"]["deletionPolicy"] == "Retain"


def test_the_addon_set_does_not_prune_and_the_directory_has_the_designed_kustomization_ac_116_12(tmp_path):  # AC-116.12
    g = ok(tmp_path, bsys())
    assert bdoc(g, "dev", "kustomization.yaml") == {
        "apiVersion": "kustomize.config.k8s.io/v1beta1", "kind": "Kustomization",
        "resources": ["access-key-generator.yaml", "bucket.yaml", "credentials.yaml", "externalsecret.yaml", "identity.yaml", "seaweed.yaml",
                      "secret-key-generator.yaml"]}
    assert sets(g)["shop-addons-dev"]["spec"]["template"]["spec"]["syncPolicy"].get("automated", {}).get("prune") is False


def test_removing_the_resource_removes_the_addon_directory_but_nothing_in_the_cluster_ac_116_12(tmp_path):  # AC-116.12
    ok(tmp_path, bsys())
    assert (tmp_path / APP / "addons" / "dev" / "files" / "bucket.yaml").is_file()
    (tmp_path / APP / "system.yaml").write_text(yaml.safe_dump(bsys({}, {"api": comp("api")}), sort_keys=False))
    done = subprocess.run([sys.executable, "scripts/render.py"], cwd=tmp_path, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert not (tmp_path / APP / "addons" / "dev" / "files").exists()


# ---------------- AC-116.15: pins ----------------

def test_the_store_image_is_pinned_to_an_exact_version_ac_116_15(tmp_path):  # AC-116.15
    img = image()
    assert re.match(r"^chrislusf/seaweedfs:\d+\.\d+(@sha256:[0-9a-f]{64})?$", img), img
    assert img == "chrislusf/seaweedfs:4.51@sha256:f7a49e3f3972ebed5be2ed4befa4a0c68eb7bdddba6e692d42729ceb545134b8"  # spec 121: the designed digest
    assert bdoc(ok(tmp_path, bsys()), "dev", "seaweed.yaml")["spec"]["image"] == img


def test_the_operator_is_pinned_in_the_versions_table_ac_116_15(tmp_path):  # AC-116.15
    op = getattr(platform_render_module("render_116_ops"), "OPERATORS", {}).get("seaweedfs")
    op = {k: v for k, v in op.items() if k != "crds"}   # spec 121: the table gains a crds key
    assert op == {"repo_url": "https://seaweedfs.github.io/seaweedfs-operator", "chart": "seaweedfs-operator", "chart_version": "0.1.45",
                  "operator_version": "1.0.42", "namespace": "seaweedfs-operator", "release": "seaweedfs-operator",
                  "crd": "buckets.seaweed.seaweedfs.com"}
    assert re.match(r"^\d+\.\d+\.\d+$", op["chart_version"]) and re.match(r"^\d+\.\d+\.\d+$", op["operator_version"])


def test_nothing_in_the_rendered_tree_floats_ac_116_15(tmp_path):  # AC-116.15
    g = ok(tmp_path, bsys())
    store_files = [t for k, t in g.items() if "/addons/" in k and "/files/" in k or k == "operators/apps/seaweedfs.yaml"]
    assert len(store_files) >= 8
    blob = "\n".join(store_files)
    assert "latest" not in blob and not re.search(r"(targetRevision|image):\s*[\"']?[~^*>]|\.x\b|\*", blob.replace("{{", "").replace("}}", ""))
    for m in re.finditer(r"image:\s*(\S+)", blob):
        assert re.search(r":\d+\.\d+", m.group(1)), m.group(1)


# ---------------- AC-116.17: external buckets ----------------

def test_an_external_bucket_instance_renders_no_store_and_the_six_key_externalsecret_ac_116_17(tmp_path):  # AC-116.17
    res = {"files": bucket(instances={"prod": {"external": True}})}
    g = ok(tmp_path, bsys(res))
    assert not [k for k in g if k.startswith(bdir("prod"))], "no in-cluster store or bucket in prod"
    assert "files" not in addon_names(g, "prod") and "files" in addon_names(g, "dev")
    want = external_secret("files", "shop-prod-files")
    want["spec"]["data"] = [{"secretKey": k, "remoteRef": {"key": "shop-prod-files", "property": k}} for k in BKEYS]
    got = y(g, external_secret_path("prod", "api", "files"))
    assert got == want
    assert "dataFrom" not in got["spec"] and "template" not in got["spec"]["target"]


def test_the_external_store_path_follows_the_default_and_remote_overrides_ac_116_17(tmp_path):  # AC-116.17
    res = {"files": bucket(external=True, remote={"path": "buckets/{env}/{resource}", "refreshInterval": "30m"})}
    g = ok(tmp_path, bsys(res))
    es = y(g, external_secret_path("dev", "api", "files"))
    assert es["spec"]["refreshInterval"] == "30m"
    assert {d["remoteRef"]["key"] for d in es["spec"]["data"]} == {"buckets/dev/files"}
    assert [d["secretKey"] for d in es["spec"]["data"]] == BKEYS


def test_an_external_bucket_gives_the_same_variables_as_an_in_cluster_one_ac_116_17(tmp_path):  # AC-116.17
    g = ok(tmp_path, bsys({"files": bucket(instances={"prod": {"external": True}})}))
    assert secret_vars(g, "prod", "api") == secret_vars(g, "dev", "api") == contract("files")


def test_an_external_everywhere_bucket_renders_no_operator_and_no_addon_ac_116_17(tmp_path):  # AC-116.17
    g = ok(tmp_path, bsys({"files": bucket(external=True)}))
    assert not [k for k in g if "/addons/" in k] and not [k for k in g if k.startswith("operators/")]
    assert all(external_secret_path(e, "api", "files") in g for e in ENVS)


def test_the_external_secret_lives_in_the_overlay_of_the_first_running_user_ac_116_17(tmp_path):  # AC-116.17
    doc = bsys({"files": bucket(external=True)}, {"web": comp("web", ["files"], envs=("staging", "prod")), "api": comp("api", ["files"])})
    g = ok(tmp_path, doc)
    assert external_secret_path("dev", "api", "files") in g and external_secret_path("staging", "api", "files") in g
    assert external_secret_path("staging", "web", "files") not in g


def test_an_external_bucket_needs_the_secret_store_ac_116_17(tmp_path):  # AC-116.17
    fails(tmp_path, bsys({"files": bucket(external=True)}, store=False), "secretStore")


# ---------------- AC-116.18: a missing key creates no Secret (render side) ----------------

def test_the_external_secret_has_no_defaults_so_a_missing_key_creates_no_secret_ac_116_18(tmp_path):  # AC-116.18
    g = ok(tmp_path, bsys({"files": bucket(external=True)}))
    es = y(g, external_secret_path("dev", "api", "files"))
    assert es["spec"]["target"]["creationPolicy"] == "Orphan"
    assert len(es["spec"]["data"]) == 6
    for d in es["spec"]["data"]:
        assert set(d) == {"secretKey", "remoteRef"} and set(d["remoteRef"]) == {"key", "property"}, "no defaults, no conversion"


def test_the_e2e_script_proves_the_missing_key_of_a_bucket_ac_116_18():  # AC-116.18 (needs a cluster: covered by tests/e2e/run.sh)
    text = (ROOT / "tests" / "e2e" / "run.sh").read_text()
    assert "ext-files" in text and "secretAccessKey" in text


# ---------------- AC-116.19: the SeaweedFS operator ----------------

def op_doc(**envs):
    doc = bsys()
    for e, v in envs.items():
        doc["environments"][e]["operators"] = v
    return doc


def test_an_in_cluster_bucket_renders_the_seaweedfs_operator_once_ac_116_19(tmp_path):  # AC-116.19
    g = ok(tmp_path, op_doc())
    assert sorted(k for k in g if k.startswith("operators/")) == ["operators/apps/seaweedfs.yaml", "operators/root.yaml"]
    server = sets(g)["shop-dev"]["spec"]["template"]["spec"]["destination"]["server"]
    assert y(g, "operators/apps/seaweedfs.yaml") == {
        "apiVersion": "argoproj.io/v1alpha1", "kind": "Application",
        "metadata": {"name": "operator-seaweedfs", "namespace": "argocd",
                     "labels": {"app.kubernetes.io/managed-by": "gitops-app", "app.kubernetes.io/component": "operator"},
                     "annotations": {"argocd.argoproj.io/compare-options": "ServerSideDiff=true"}},
        "spec": {"project": "default",
                 "source": {"repoURL": "https://seaweedfs.github.io/seaweedfs-operator", "chart": "seaweedfs-operator", "targetRevision": "0.1.45",
                            "helm": {"releaseName": "seaweedfs-operator"}},
                 "destination": {"server": server, "namespace": "seaweedfs-operator"},
                 "syncPolicy": {"automated": {"prune": True, "selfHeal": True}, "syncOptions": ["CreateNamespace=true", "ServerSideApply=true"]}}}
    assert not [k for k in g if k.startswith(APP) and "operator" in k.lower()], "applications/<system>/ carries no operator"


def test_several_buckets_still_render_one_operator_ac_116_19(tmp_path):  # AC-116.19
    g = ok(tmp_path, bsys({"a": bucket(), "b": bucket()}, {"api": comp("api", ["a", "b"])}))
    assert sorted(k for k in g if k.startswith("operators/")) == ["operators/apps/seaweedfs.yaml", "operators/root.yaml"]


def test_no_in_cluster_bucket_means_no_store_application_ac_116_19(tmp_path):  # AC-116.19
    for label, doc in (("none", system(None)), ("unused", bsys({"files": bucket()}, {"api": comp("api")})),
                       ("external", bsys({"files": bucket(external=True)})), ("database", system({"d": db()}, {"api": comp("api", ["d"])}))):
        g = ok(tmp_path / label, doc)
        assert "operators/apps/seaweedfs.yaml" not in g, label


def test_a_database_and_a_bucket_render_both_operators_ac_116_19(tmp_path):  # AC-116.19
    g = ok(tmp_path, bsys({"files": bucket(), "d": db()}, {"api": comp("api", ["files", "d"])}))
    assert sorted(k for k in g if k.startswith("operators/")) == ["operators/apps/cloudnative-pg.yaml", "operators/apps/seaweedfs.yaml", "operators/root.yaml"]


def test_the_cloudnative_pg_document_is_unchanged_by_buckets_ac_116_19(tmp_path):  # AC-116.19
    a = ok(tmp_path / "a", system({"d": db()}, {"api": comp("api", ["d"])}))
    b = ok(tmp_path / "b", bsys({"files": bucket(), "d": db()}, {"api": comp("api", ["files", "d"])}))
    assert a["operators/apps/cloudnative-pg.yaml"] == b["operators/apps/cloudnative-pg.yaml"]
    assert a["operators/root.yaml"] == b["operators/root.yaml"]


def test_owner_managed_environments_get_no_store_application_ac_116_19(tmp_path):  # AC-116.19
    g = ok(tmp_path / "all", op_doc(dev="owner", staging="owner", prod="owner"))
    assert not [k for k in g if k.startswith("operators/")]
    assert [k for k in g if k.startswith(bdir("dev"))], "the bucket itself is still rendered"
    g = ok(tmp_path / "some", op_doc(prod="owner"))
    assert "operators/apps/seaweedfs.yaml" in g, "dev and staging are still platform-managed"
    doc = bsys({"files": bucket(instances={"prod": {"external": True}})})
    doc["environments"]["dev"]["operators"] = doc["environments"]["staging"]["operators"] = "owner"
    assert not [k for k in ok(tmp_path / "ext", doc) if k.startswith("operators/")], "prod is external, dev and staging are owner-managed"


def test_the_store_application_goes_with_the_last_bucket_ac_116_19(tmp_path):  # AC-116.19
    ok(tmp_path, op_doc())
    assert (tmp_path / "operators" / "apps" / "seaweedfs.yaml").is_file()
    (tmp_path / APP / "system.yaml").write_text(yaml.safe_dump(system(None), sort_keys=False))
    subprocess.run([sys.executable, "scripts/render.py"], cwd=tmp_path, check=True, capture_output=True)
    assert not (tmp_path / "operators").exists()


def test_check_mode_covers_the_store_application_ac_116_19(tmp_path):  # AC-116.19
    ok(tmp_path, op_doc())
    check = lambda: subprocess.run([sys.executable, "scripts/render.py", "--check"], cwd=tmp_path, capture_output=True, text=True)
    assert check().returncode == 0
    f = tmp_path / "operators" / "apps" / "seaweedfs.yaml"
    f.write_text(f.read_text() + "# hand edit\n")
    assert check().returncode == 1


# ---------------- AC-116.20: bucket joins the closed lists ----------------

def test_a_component_may_use_a_bucket_and_type_bucket_renders_ac_116_20(tmp_path):  # AC-116.20
    g = ok(tmp_path, bsys())
    assert f"{bdir('dev')}/bucket.yaml" in g


def test_bucket_is_no_longer_a_planned_type_ac_116_20(tmp_path):  # AC-116.20
    r = platform_render_module("render_116_planned")
    assert getattr(r, "PLANNED_TYPES", None) == {}  # spec 119: broker is built, no type is planned


@pytest.mark.parametrize("typ, spec", [])  # spec 119: broker is built, no type is planned (pytest skips the empty set)
def test_the_other_planned_types_keep_their_messages_ac_116_20(tmp_path, typ, spec):  # AC-116.20
    err = fails(tmp_path, system({"store": {"type": typ}}), P + f"resources.store: type {typ} is not available yet: spec {spec} brings it")
    assert len(err.strip().splitlines()) == 1


@pytest.mark.parametrize("value", ["queue", "Bucket", "s3"])
def test_every_other_type_is_refused_with_the_same_message_ac_116_20(tmp_path, value):  # AC-116.20
    fails(tmp_path, system({"x": {"type": value}}), P + f"resources.x: type '{value}' is not a resource type (database, bucket, cache or broker)")


def test_a_component_may_not_use_an_undeclared_resource_still_ac_116_20(tmp_path):  # AC-116.20
    p = render5(tmp_path, bsys({"files": bucket()}, {"api": comp("api", ["nope"])}))
    assert p.returncode == 1 and "nope" in p.stderr


def test_a_system_without_buckets_renders_unchanged_ac_116_20(tmp_path):  # AC-116.20
    a = ok(tmp_path / "a", system({"d": db()}, {"api": comp("api", ["d"])}))
    b = ok(tmp_path / "b", system({"d": db(), "idle": bucket()}, {"api": comp("api", ["d"])}))
    assert a == b, "an unused bucket changes nothing in the tree"
