"""Spec 121 acceptance tests, the renderer part: the versions table (AC-121.1, .2, .22, .26), exact images per major (AC-121.3), the
per-environment `version` (AC-121.6, .7), held pins (AC-121.11), the Barman archive per major (AC-121.16) and the environment-property
operators (AC-121.17, .18).

Contract: design.md "Contract: the versions table", "Contract: `system.yaml`", "Contract: renderer behaviour", "Contract:
environment-property operators". The renderer runs as a script in a hand-built checkout (resources_fixtures); nothing touches the
network or a cluster. The byte-identity test follows the design: the render equals the pre-121 render after each new engine reference is
mapped back to the old one (`unpin`); it does not edit the digests of specs 114-120. Missing symbols are guarded so each test fails on
its own. Domain-like names are matched with word-bounded regular expressions or element equality, never with `"a.b.c" in text`."""
import json
import re
import subprocess
import sys

import pytest
import yaml

from backup_fixtures import bucket
from broker_fixtures import broker, bsys
from cache_fixtures import cache, csys
from resources_fixtures import APP, ENVS, comp, db, fails, ok, system, tree, y
from system_fixtures import ROOT, render, write_system
from upgrade_fixtures import (CLUSTER_PINS, COLLECTOR, DEPRECATED_MAJORS, DEV, IMAGE_ROWS, LGTM, NATS, NATS_CHART, OLD_PG, OPERATOR_NAMES, PG, ROW_KEYS,
                              ROW_ORDER, SEAWEED, SUPPORTED_MAJORS, UPGRADE_PATHS, VELERO_PLUGIN, VK, digest_of, doc_with_everything, render_module, row,
                              table_rows, unpin)

T = ROOT / "templates" / "gitops-app" / "scripts" / "render.py"
IMAGE_REF = re.compile(r"^[\w./-]+:[\w.-]+@sha256:[0-9a-f]{64}$")
FLOATING = {"latest", "stable", "edge", "main", "master", "nightly"}


def ddoc(version=16, **inst) -> dict:
    """orders-db (a database) used by api."""
    d = db(version=version) if version is not None else db()
    if inst:
        d["instances"] = inst
    return system({"orders-db": d}, {"api": comp("api", ["orders-db"])})


def kdoc(version=9, **inst) -> dict:
    c = cache(version=version) if version is not None else cache()
    if inst:
        c["instances"] = inst
    return csys({"sessions": c})


def bkdoc(version="2.15", **inst) -> dict:
    b = broker(version=version) if version is not None else broker()
    if inst:
        b["instances"] = inst
    return bsys({"bus": b})


def sdoc_bucket() -> dict:
    return system({"files": bucket()}, {"api": comp("api", ["files"])})


def cluster(g, env="dev", name="orders-db", file="cluster.yaml") -> dict:
    return y(g, f"{APP}/addons/{env}/{name}/{file}")


def valkey_image(g, env="dev") -> str:
    sts = y(g, f"{APP}/addons/{env}/sessions/statefulset.yaml")
    return next(c["image"] for c in sts["spec"]["template"]["spec"]["containers"] if c["name"] == "valkey")


def broker_image(g, env="dev") -> dict:
    return y(g, f"{APP}/addons/{env}/bus/server.yaml")["spec"]["source"]["helm"]["valuesObject"]["container"]["image"]


def broker_revision(g, env="dev") -> str:
    return y(g, f"{APP}/addons/{env}/bus/server.yaml")["spec"]["source"]["targetRevision"]


def seaweed_image(g, env="dev") -> str:
    return y(g, f"{APP}/addons/{env}/files/seaweed.yaml")["spec"]["image"]


def loaded(tmp_path, doc, name="render_121_load") -> dict:
    return render_module(name).load_system(write_system(tmp_path, doc))


# ---------------- AC-121.1: the versions table ----------------

def test_the_table_has_one_row_per_image_and_operator_in_the_designed_order_ac_121_1():  # AC-121.1
    assert [r["name"] for r in table_rows()] == ROW_ORDER


def test_every_row_has_exactly_the_designed_keys_ac_121_1():  # AC-121.1
    rows = table_rows()
    assert rows and all(list(r) == ROW_KEYS for r in rows)


def test_the_image_rows_carry_kind_engine_major_status_version_ref_and_digest_ac_121_1():  # AC-121.1
    rows = table_rows()
    want = {"postgres 15": ("database", 15, "deprecated", "15.19", "ghcr.io/cloudnative-pg/postgresql:15.19-202610260819-standard-trixie", PG[15]),
            "postgres 16": ("database", 16, "supported", "16.15", "ghcr.io/cloudnative-pg/postgresql:16.15-202610260820-standard-trixie", PG[16]),
            "postgres 17": ("database", 17, "supported", "17.11", "ghcr.io/cloudnative-pg/postgresql:17.11-202610260819-standard-trixie", PG[17]),
            "postgres 18": ("database", 18, "supported", "18.6", "ghcr.io/cloudnative-pg/postgresql:18.6-202610260820-standard-trixie", PG[18]),
            "valkey 8": ("cache", 8, "supported", "8.1.11", "valkey/valkey:8.1.11", VK[8]),
            "valkey 9": ("cache", 9, "supported", "9.1.3", "valkey/valkey:9.1.3", VK[9]),
            "nats 2.14": ("broker", "2.14", "supported", "2.14.9", "nats:2.14.9-alpine", NATS["2.14"]),
            "nats 2.15": ("broker", "2.15", "supported", "2.15.2", "nats:2.15.2-alpine", NATS["2.15"])}
    for name, (engine, major, status, version, ref, full) in want.items():
        r = row(rows, name)
        assert (r["kind"], r["engine"], r["major"], r["status"], r["version"], r["ref"], r["digest"]) == ("image", engine, major, status, version, ref, digest_of(full)), name
        assert (r["app_version"], r["crds"]) == (None, None), name


def test_the_other_images_and_the_cluster_pins_are_rows_with_their_versions_ac_121_1():  # AC-121.1
    rows = table_rows()
    for name, version, ref, full, engine in (("seaweedfs", "4.51", "chrislusf/seaweedfs:4.51", SEAWEED, "bucket"),
                                             ("opentelemetry-collector", "0.162.0", "otel/opentelemetry-collector-contrib:0.162.0", COLLECTOR, None),
                                             ("lgtm", "0.35.0", "grafana/otel-lgtm:0.35.0", LGTM, None),
                                             ("velero-plugin-for-aws", "v1.14.4", "velero/velero-plugin-for-aws:v1.14.4", VELERO_PLUGIN, None),
                                             ("k3s", "v1.32.5-k3s1", "rancher/k3s:v1.32.5-k3s1", CLUSTER_PINS["k3s"]["image"], None)):
        r = row(rows, name)
        assert (r["kind"], r["engine"], r["major"], r["status"], r["version"], r["ref"], r["digest"]) == ("image", engine, None, None, version, ref, digest_of(full)), name


def test_the_chart_and_the_manifests_are_rows_without_a_digest_ac_121_1():  # AC-121.1
    rows = table_rows()
    nats = row(rows, "nats")
    assert (nats["kind"], nats["version"], nats["ref"], nats["digest"]) == ("chart", "2.15.1", f"{NATS_CHART['repo_url']} nats", None)
    for name, key in (("argo-cd", "argo-cd"), ("gateway-api", "gateway-api")):
        r = row(rows, name)
        assert (r["kind"], r["version"], r["ref"], r["digest"]) == ("manifest", CLUSTER_PINS[key]["version"], CLUSTER_PINS[key]["manifest"], None), name


def test_an_operator_row_is_the_chart_with_its_operator_version_and_crds_ac_121_1():  # AC-121.1
    r = render_module("render_121_ops")
    rows = table_rows()
    for n in OPERATOR_NAMES:
        op, got = r.OPERATORS[n], row(rows, f"operator {n}")
        assert (got["kind"], got["version"], got["ref"], got["app_version"], got["digest"]) == (
            "chart", op["chart_version"], f"{op['repo_url']} {op['chart']}", op["operator_version"], None), n
        assert got["crds"] == op["crds"], n


def test_the_renderer_prints_its_table_with_versions_and_does_not_read_applications_ac_121_1(tmp_path):  # AC-121.1
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "render.py").write_text(T.read_text())
    p = subprocess.run([sys.executable, "scripts/render.py", "--versions"], cwd=tmp_path, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    assert json.loads(p.stdout) == table_rows(), "render.py --versions prints json.dumps(versions_table(), indent=2)"
    assert not (tmp_path / "applications").exists()


def test_the_constants_are_the_designed_tags_and_digests_ac_121_1():  # AC-121.1
    r = render_module("render_121_consts")
    assert dict(r.POSTGRES_IMAGES) == PG and dict(r.VALKEY_IMAGES) == VK and dict(r.NATS_IMAGES) == NATS
    assert r.SEAWEEDFS_IMAGE == SEAWEED and r.VELERO_AWS_PLUGIN_IMAGE == VELERO_PLUGIN and r.COLLECTOR_IMAGE == COLLECTOR and r.LGTM_IMAGE == LGTM
    assert r.CLUSTER_PINS == CLUSTER_PINS and dict(r.NATS_CHART) == NATS_CHART
    assert r.ADDONS["observability"]["image"] == COLLECTOR


def test_supported_deprecated_majors_and_upgrade_paths_are_the_designed_ones_ac_121_1():  # AC-121.1
    r = render_module("render_121_majors")
    assert {k: tuple(v) for k, v in r.SUPPORTED_MAJORS.items()} == SUPPORTED_MAJORS
    assert {k: tuple(v) for k, v in r.DEPRECATED_MAJORS.items()} == DEPRECATED_MAJORS
    assert {k: {m: tuple(t) for m, t in v.items()} for k, v in r.UPGRADE_PATHS.items()} == UPGRADE_PATHS
    assert tuple(r.SUPPORTED_VERSIONS) == (15, 16, 17, 18) and tuple(r.CACHE_VERSIONS) == (8, 9) and tuple(r.BROKER_VERSIONS) == ("2.14", "2.15")


# ---------------- AC-121.2: every reference is exact and digested ----------------

def test_every_image_row_is_a_repository_an_exact_tag_and_a_digest_ac_121_2():  # AC-121.2
    rows = [r for r in table_rows() if r["kind"] == "image"]
    assert len(rows) == len(IMAGE_ROWS) + 5
    for r in rows:
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", r["digest"] or ""), r["name"]
        tag = r["ref"].rsplit(":", 1)[1]
        assert tag not in FLOATING and not re.fullmatch(r"v?\d+", tag), f"{r['name']}: floating tag {tag}"
        assert re.search(r"\d+\.\d+", tag), r["name"]


def test_every_chart_and_manifest_row_has_an_exact_three_part_version_ac_121_2():  # AC-121.2
    for r in table_rows():
        if r["kind"] in ("chart", "manifest"):
            assert re.fullmatch(r"v?\d+\.\d+\.\d+", r["version"]), r["name"]


def test_a_coverage_render_writes_only_references_from_the_table_ac_121_2(tmp_path):  # AC-121.2
    doc = doc_with_everything()
    doc["environments"]["dev"]["observability"] = {"ui": "lgtm"}
    doc["environments"]["staging"]["backup"] = dict(DEV)
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / ".copier-answers.yml").write_text(yaml.safe_dump({"property_operators": "install", "resource_metrics": "install"}))
    g = ok(tmp_path, doc)
    refs = set()
    for path, text in g.items():
        for m in re.finditer(r"(?:^|[\s\"'])((?:ghcr\.io|docker\.io|quay\.io|[\w.-]+)/[\w./-]+:[\w.-]+(?:@sha256:[0-9a-f]{64})?)(?=$|[\s\"'])", text, re.M):
            if re.match(r"(ghcr\.io/cloudnative-pg|valkey/|chrislusf/|otel/|velero/|grafana/|nats:)", m.group(1)):
                refs.add(m.group(1))
    table = {r["ref"] + "@" + r["digest"] for r in table_rows() if r["kind"] == "image"}
    assert refs, "the coverage render writes engine images"
    assert refs <= table, sorted(refs - table)


def test_the_rendered_engine_images_all_carry_a_digest_ac_121_2(tmp_path):  # AC-121.2
    g = ok(tmp_path, doc_with_everything())
    wanted = [(f"{APP}/addons/dev/orders-db/cluster.yaml", r"imageName: (\S+)"), (f"{APP}/addons/dev/sessions/statefulset.yaml", r"image: (valkey/\S+)"),
              (f"{APP}/addons/dev/backups/seaweed.yaml", r"image: (chrislusf/\S+)")]
    for path, pattern in wanted:
        m = re.search(pattern, g[path])
        assert m and IMAGE_REF.match(m.group(1)), f"{path}: {m and m.group(1)}"
    assert re.search(r"tag: \S+@sha256:[0-9a-f]{64}", g[f"{APP}/addons/dev/bus/server.yaml"])


def test_the_velero_plugin_and_the_collector_are_pinned_with_digests_ac_121_2(tmp_path):  # AC-121.2
    doc = system({"d": db()}, {"api": comp("api", ["d"])})
    doc["environments"]["dev"]["observability"] = {"ui": "lgtm"}
    doc["environments"]["staging"]["backup"] = {"to": "backups"}
    doc["resources"]["backups"] = bucket()
    doc["components"]["api"]["uses"].append("backups")
    g = ok(tmp_path, doc)
    velero = y(g, "operators/apps/velero.yaml")["spec"]["source"]["helm"]["valuesObject"]["initContainers"][0]["image"]
    assert velero == VELERO_PLUGIN
    collector = [k for k in g if k.startswith(f"{APP}/addons/dev/observability/")]
    assert collector and any(re.search(rf"image: {re.escape(COLLECTOR)}\b", g[k]) for k in collector)


# ---------------- AC-121.3: exact image and digest per major ----------------

@pytest.mark.parametrize("major", [15, 16, 17, 18])
def test_a_database_major_renders_the_exact_image_in_every_environment_ac_121_3(tmp_path, major):  # AC-121.3
    g = ok(tmp_path, ddoc(major))
    assert [cluster(g, e)["spec"]["imageName"] for e in ENVS] == [PG[major]] * 3


@pytest.mark.parametrize("major", [8, 9])
def test_a_cache_major_renders_the_exact_image_in_every_environment_ac_121_3(tmp_path, major):  # AC-121.3
    g = ok(tmp_path, kdoc(major))
    assert [valkey_image(g, e) for e in ENVS] == [VK[major]] * 3


@pytest.mark.parametrize("line", ["2.14", "2.15"])
def test_a_broker_major_renders_the_exact_image_as_repository_and_tag_with_the_digest_ac_121_3(tmp_path, line):  # AC-121.3
    g = ok(tmp_path, bkdoc(line))
    repo, tag = NATS[line].split(":", 1)
    assert [broker_image(g, e) for e in ENVS] == [{"repository": repo, "tag": tag}] * 3


def test_a_bucket_renders_the_seaweedfs_image_of_the_release_ac_121_3(tmp_path):  # AC-121.3
    g = ok(tmp_path, sdoc_bucket())
    assert [seaweed_image(g, e) for e in ENVS] == [SEAWEED] * 3


def test_two_renders_of_the_same_release_produce_the_same_images_ac_121_3(tmp_path):  # AC-121.3
    a, b = ok(tmp_path / "a", doc_with_everything()), ok(tmp_path / "b", doc_with_everything())
    assert a == b and cluster(a)["spec"]["imageName"] == PG[17]


def test_a_database_without_a_version_runs_the_table_image_of_17_ac_121_3(tmp_path):  # AC-121.3
    assert cluster(ok(tmp_path, ddoc(None)))["spec"]["imageName"] == PG[17]


def test_the_table_maps_a_quoted_major_like_the_number_ac_121_3(tmp_path):  # AC-121.3
    assert cluster(ok(tmp_path, ddoc("18")))["spec"]["imageName"] == PG[18]


@pytest.mark.parametrize("doc, text", [
    (ddoc(19), "resources.orders-db: version '19' is not a supported database version (15, 16, 17, 18)"),
    (ddoc(dev={"version": 19}), "resources.orders-db.instances.dev: version '19' is not a supported database version (15, 16, 17, 18)"),
    (kdoc(dev={"version": 7}), "resources.sessions.instances.dev: version '7' is not a supported cache version (8, 9)"),
    (bkdoc(dev={"version": "2.13"}), "resources.bus.instances.dev: version '2.13' is not a supported broker version (2.14, 2.15)"),
], ids=["database", "database-instance", "cache-instance", "broker-instance"])
def test_a_major_that_is_not_in_the_table_fails_naming_the_supported_majors_ac_121_3(tmp_path, doc, text):  # AC-121.3
    fails(tmp_path, doc, "applications/shop/system.yaml: " + text)


# ---------------- AC-121.6 / .7: instances.<env>.version ----------------

def test_an_instance_version_moves_only_that_environment_ac_121_6(tmp_path):  # AC-121.6
    g = ok(tmp_path, ddoc(16, dev={"version": 17}))
    assert [cluster(g, e)["spec"]["imageName"] for e in ENVS] == [PG[17], PG[16], PG[16]]


def test_a_cache_and_a_broker_accept_an_instance_version_ac_121_6(tmp_path):  # AC-121.6
    g = ok(tmp_path / "c", kdoc(8, staging={"version": 9}))
    assert [valkey_image(g, e) for e in ENVS] == [VK[8], VK[9], VK[8]]
    g = ok(tmp_path / "b", bkdoc("2.14", prod={"version": "2.15"}))
    assert [broker_image(g, e)["tag"] for e in ENVS] == [NATS["2.14"].split(":", 1)[1]] * 2 + [NATS["2.15"].split(":", 1)[1]]


def test_the_effective_major_is_the_instance_version_else_the_resource_version_else_the_default_ac_121_6(tmp_path):  # AC-121.6
    doc = system({"a": db(version=16, instances={"dev": {"version": 18}}), "b": db(), "c": cache()}, {"api": comp("api", ["a", "b", "c"])})
    cfg = loaded(tmp_path / "x", doc)["cfg"]["resources"]
    assert [cfg["a"]["envs"][e]["version"] for e in ENVS] == [18, 16, 16]
    assert [cfg["b"]["envs"][e]["version"] for e in ENVS] == [17, 17, 17]
    assert [cfg["c"]["envs"][e]["version"] for e in ENVS] == [9, 9, 9]
    cfg = loaded(tmp_path / "y", bkdoc("2.14", prod={"version": "2.15"}))["cfg"]["resources"]
    assert [cfg["bus"]["envs"][e]["version"] for e in ENVS] == ["2.14", "2.14", "2.15"]


def test_the_instance_key_lists_end_with_version_ac_121_6():  # AC-121.6
    r = render_module("render_121_keys")
    assert r.RESOURCE_INSTANCE_KEYS[-1] == "version" and r.CACHE_INSTANCE_KEYS[-1] == "version" and r.BROKER_INSTANCE_KEYS[-1] == "version"
    assert r.RESOURCE_INSTANCE_KEYS == ["external", "remote", "replicas", "storage", "resources", "backup", "version"]
    assert r.CACHE_INSTANCE_KEYS == ["external", "remote", "memory", "maxmemoryPolicy", "persistence", "storage", "version"]
    assert r.BROKER_INSTANCE_KEYS == ["external", "remote", "replicas", "storage", "resources", "version"]


def test_a_bucket_instance_has_no_version_key_ac_121_6(tmp_path):  # AC-121.6
    fails(tmp_path, system({"files": bucket(instances={"dev": {"version": 1}})}, {"api": comp("api", ["files"])}),
          "resources.files.instances.dev: unknown key 'version' (allowed: external, remote, storage, versioning)")


@pytest.mark.parametrize("doc, text", [
    (system({"d": db(instances={"prod": {"external": True, "version": 17}})}, {"api": comp("api", ["d"])}),
     "resources.d.instances.prod: an external resource runs nothing (remove version)"),
    (system({"k": cache(instances={"prod": {"external": True, "version": 9}})}, {"api": comp("api", ["k"])}),
     "resources.k.instances.prod: an external cache is sized and configured at its provider (remove version)"),
    (bkdoc(prod={"external": True, "version": "2.15"}), "resources.bus.instances.prod: an external resource runs nothing (remove version)"),
], ids=["database", "cache", "broker"])
def test_a_version_on_an_external_instance_fails_ac_121_6(tmp_path, doc, text):  # AC-121.6
    fails(tmp_path, doc, "applications/shop/system.yaml: " + text)


def test_an_unsupported_cache_or_broker_instance_version_names_the_key_ac_121_6(tmp_path):  # AC-121.6
    fails(tmp_path / "k", kdoc(dev={"version": 7}), "resources.sessions.instances.dev: version '7' is not a supported cache version (8, 9)")


def test_a_boolean_is_never_a_version_ac_121_6(tmp_path):  # AC-121.6
    text = yaml.safe_dump(ddoc(16, dev={"version": 17}), sort_keys=False).replace("version: 17", "version: yes")
    assert "version: yes" in text and yaml.safe_load(text)["resources"]["orders-db"]["instances"]["dev"]["version"] is True
    write_system(tmp_path, text)
    p = render(tmp_path)
    assert p.returncode == 1 and re.search(r"resources\.orders-db\.instances\.dev: version 'True' is not a supported database version \(15, 16, 17, 18\)", p.stderr)


def test_a_float_broker_version_that_is_no_supported_line_says_to_write_a_string_ac_121_6(tmp_path):  # AC-121.6
    fails(tmp_path, bkdoc(dev={"version": 2.1}),
          "resources.bus.instances.dev: version '2.1' is not a supported broker version (2.14, 2.15); write it as a string, e.g. \"2.15\"")
    fails(tmp_path / "s", bkdoc(dev={"version": "2.13"}), "resources.bus.instances.dev: version '2.13' is not a supported broker version (2.14, 2.15)")


def test_a_float_that_reads_as_a_supported_line_is_accepted_ac_121_6(tmp_path):  # AC-121.6
    g = ok(tmp_path, bkdoc("2.14", prod={"version": 2.15}))
    assert broker_image(g, "prod")["tag"] == NATS["2.15"].split(":", 1)[1]


def test_instance_versions_are_checked_in_environment_order_ac_121_6(tmp_path):  # AC-121.6
    err = fails(tmp_path, ddoc(16, prod={"version": 20}, dev={"version": 21}), "resources.orders-db.instances.dev: version '21'")
    assert not re.search(r"instances\.prod\b", err)


# ---------------- AC-121.7: the folded form ----------------

def test_the_folded_form_renders_the_same_as_per_environment_entries_of_that_major_ac_121_7(tmp_path):  # AC-121.7
    folded = ok(tmp_path / "a", ddoc(17))
    entries = ok(tmp_path / "b", ddoc(16, dev={"version": 17}, staging={"version": 17}, prod={"version": 17}))
    assert folded == entries


def test_a_resource_version_with_a_partial_set_of_entries_renders_each_environment_on_its_own_major_ac_121_7(tmp_path):  # AC-121.7
    g = ok(tmp_path, ddoc(16, dev={"version": 17}, staging={"version": 17}))
    assert [cluster(g, e)["spec"]["imageName"] for e in ENVS] == [PG[17], PG[17], PG[16]]


def test_the_env_entry_of_a_resource_carries_its_effective_major_and_pin_ac_121_7(tmp_path):  # AC-121.7
    envs = loaded(tmp_path, ddoc(16, dev={"version": 17}))["cfg"]["resources"]["orders-db"]["envs"]
    assert (envs["dev"]["version"], envs["dev"]["pin"]) == (17, PG[17])
    assert (envs["prod"]["version"], envs["prod"]["pin"]) == (16, PG[16])


def test_an_external_instance_has_no_pin_ac_121_7(tmp_path):  # AC-121.7
    envs = loaded(tmp_path, system({"d": db(instances={"prod": {"external": True}})}, {"api": comp("api", ["d"])}))["cfg"]["resources"]["d"]["envs"]
    assert envs["prod"]["pin"] is None and envs["dev"]["pin"] == PG[17]


# ---------------- AC-121.11: held pins ----------------

OLD_TAG_NATS = "2.15.1-alpine"


def rerender(root, *args):
    p = render(root, *args)
    assert p.returncode == 0, p.stdout + p.stderr
    return tree(root)


def edit(root, rel, old, new):
    p = root / rel
    text = p.read_text()
    assert old in text, f"{rel} does not contain the reference {old[:40]}…"
    p.write_text(text.replace(old, new))


def held(tmp_path, doc, files_old):
    """Render, put an older image in the staging and prod files (and dev's), render again; returns (first, second, before-bytes)."""
    first = ok(tmp_path, doc)
    for env in ENVS:
        for rel, old, new in files_old(env):
            edit(tmp_path, rel, old, new)
    before = tree(tmp_path)
    return first, rerender(tmp_path), before


def db_files(env):
    return [(f"{APP}/addons/{env}/orders-db/cluster.yaml", PG[16], OLD_PG[16])]


def test_a_first_render_pins_the_table_in_every_environment_ac_121_11(tmp_path):  # AC-121.11
    g = ok(tmp_path, ddoc(16))
    assert [cluster(g, e)["spec"]["imageName"] for e in ENVS] == [PG[16]] * 3


def test_dev_moves_to_the_table_pin_while_staging_and_prod_keep_their_rendered_image_ac_121_11(tmp_path):  # AC-121.11
    first, second, before = held(tmp_path, ddoc(16), db_files)
    assert cluster(second, "dev")["spec"]["imageName"] == PG[16]
    for env in ("staging", "prod"):
        assert cluster(second, env)["spec"]["imageName"] == OLD_PG[16]
        assert second[f"{APP}/addons/{env}/orders-db/cluster.yaml"] == before[f"{APP}/addons/{env}/orders-db/cluster.yaml"], "byte for byte"
    assert second[f"{APP}/addons/dev/orders-db/cluster.yaml"] == first[f"{APP}/addons/dev/orders-db/cluster.yaml"]


def test_a_held_pin_is_stable_under_render_check_ac_121_11(tmp_path):  # AC-121.11
    held(tmp_path, ddoc(16), db_files)
    assert render(tmp_path, "--check").returncode == 0
    assert cluster(tree(tmp_path), "staging")["spec"]["imageName"] == OLD_PG[16]


def test_a_changed_major_takes_the_table_pin_even_when_a_file_is_held_ac_121_11(tmp_path):  # AC-121.11
    held(tmp_path, ddoc(16), db_files)
    write_system(tmp_path, ddoc(16, staging={"version": 17}))
    g = rerender(tmp_path)
    assert cluster(g, "staging")["spec"]["imageName"] == PG[17] and cluster(g, "prod")["spec"]["imageName"] == OLD_PG[16]


def test_a_file_that_does_not_parse_counts_as_absent_ac_121_11(tmp_path):  # AC-121.11
    ok(tmp_path, ddoc(16))
    (tmp_path / APP / "addons/staging/orders-db/cluster.yaml").write_text("{{{ not: [yaml")
    g = rerender(tmp_path)
    assert cluster(g, "staging")["spec"]["imageName"] == PG[16]


def test_a_released_hold_takes_the_table_pin_when_the_file_is_removed_ac_121_11(tmp_path):  # AC-121.11
    held(tmp_path, ddoc(16), db_files)
    (tmp_path / APP / "addons/staging/orders-db/cluster.yaml").unlink()
    assert cluster(rerender(tmp_path), "staging")["spec"]["imageName"] == PG[16]


def test_a_held_cache_image_is_kept_in_staging_and_prod_ac_121_11(tmp_path):  # AC-121.11
    old = "valkey/valkey:9.0.1"
    first, second, before = held(tmp_path, kdoc(9), lambda env: [(f"{APP}/addons/{env}/sessions/statefulset.yaml", VK[9], old)])
    assert valkey_image(second, "dev") == VK[9] and [valkey_image(second, e) for e in ("staging", "prod")] == [old, old]
    assert second[f"{APP}/addons/prod/sessions/statefulset.yaml"] == before[f"{APP}/addons/prod/sessions/statefulset.yaml"]


def test_a_held_broker_keeps_its_image_and_its_chart_version_ac_121_11(tmp_path):  # AC-121.11
    new_tag = NATS["2.15"].split(":", 1)[1]
    first, second, before = held(tmp_path, bkdoc("2.15"), lambda env: [(f"{APP}/addons/{env}/bus/server.yaml", new_tag, OLD_TAG_NATS),
                                                                       (f"{APP}/addons/{env}/bus/server.yaml", "targetRevision: " + NATS_CHART["chart_version"], "targetRevision: 2.14.0")])
    assert broker_image(second, "dev")["tag"] == new_tag and broker_revision(second, "dev") == NATS_CHART["chart_version"]
    for env in ("staging", "prod"):
        assert broker_image(second, env)["tag"] == OLD_TAG_NATS and broker_revision(second, env) == "2.14.0"
        assert second[f"{APP}/addons/{env}/bus/server.yaml"] == before[f"{APP}/addons/{env}/bus/server.yaml"]


def test_a_held_bucket_image_is_kept_in_staging_and_prod_ac_121_11(tmp_path):  # AC-121.11
    old = "chrislusf/seaweedfs:4.40"
    first, second, before = held(tmp_path, sdoc_bucket(), lambda env: [(f"{APP}/addons/{env}/files/seaweed.yaml", SEAWEED, old)])
    assert seaweed_image(second, "dev") == SEAWEED and [seaweed_image(second, e) for e in ("staging", "prod")] == [old, old]


def test_the_active_cluster_file_of_a_restored_generation_holds_the_pin_ac_121_11(tmp_path):  # AC-121.11
    doc = ddoc(16, dev={"backup": DEV}, staging={"backup": DEV})
    doc["resources"]["backups"] = bucket()
    doc["components"]["api"]["uses"].append("backups")
    state = {"next": 2, "clusters": [{"name": "shop-orders-db", "role": "previous", "until": "2026-10-27T11:02:13Z"},
                                     {"name": "shop-orders-db-g1", "role": "active", "from": {"server": "shop-orders-db", "to": "2026-10-27T09:59:00Z"}}]}
    ok(tmp_path, doc)
    d = tmp_path / APP / "addons/staging/orders-db"
    (d / "restore-state.yaml").write_text(yaml.safe_dump(state, sort_keys=False))
    rerender(tmp_path)
    edit(tmp_path, f"{APP}/addons/staging/orders-db/cluster-g1.yaml", PG[16], OLD_PG[16])
    g = rerender(tmp_path)
    assert cluster(g, "staging", file="cluster-g1.yaml")["spec"]["imageName"] == OLD_PG[16]


# ---------------- AC-121.16: a Barman archive per major ----------------

def backed_doc(version=17):
    doc = ddoc(version, dev={"backup": DEV}, staging={"backup": DEV})
    doc["resources"]["backups"] = bucket()
    doc["components"]["api"]["uses"].append("backups")
    return doc


def plugin_params(g, env="dev", file="cluster.yaml"):
    return cluster(g, env, file=file)["spec"]["plugins"][0]["parameters"]


ARCHIVES = [{"server": "shop-orders-db", "major": 16}, {"server": "shop-orders-db-pg17", "major": 17}]


def with_state(tmp_path, state, doc=None):
    ok(tmp_path, doc or backed_doc())
    (tmp_path / APP / "addons/dev/orders-db/restore-state.yaml").write_text("# Written by `cplat resource restore` (spec 117).\n" + yaml.safe_dump(state, sort_keys=False))
    return rerender(tmp_path)


def test_without_archives_the_plugin_has_no_server_name_ac_121_16(tmp_path):  # AC-121.16
    g = ok(tmp_path, backed_doc())
    assert plugin_params(g) == {"barmanObjectName": "shop-orders-db"} and list(plugin_params(g)) == ["barmanObjectName"]


def test_archives_add_the_server_name_of_the_last_archive_after_the_object_store_ac_121_16(tmp_path):  # AC-121.16
    g = with_state(tmp_path, {"next": 1, "clusters": [{"name": "shop-orders-db", "role": "active"}], "archives": ARCHIVES})
    assert list(plugin_params(g).items()) == [("barmanObjectName", "shop-orders-db"), ("serverName", "shop-orders-db-pg17")]
    assert list(plugin_params(g, "staging")) == ["barmanObjectName"], "only the environment with archives"


def test_an_archive_that_is_the_cluster_itself_adds_no_server_name_ac_121_16(tmp_path):  # AC-121.16
    g = with_state(tmp_path, {"next": 1, "clusters": [{"name": "shop-orders-db", "role": "active"}], "archives": [ARCHIVES[0]]})
    assert plugin_params(g) == {"barmanObjectName": "shop-orders-db"}


def test_a_restored_generation_from_an_older_archive_runs_that_major_ac_121_16(tmp_path):  # AC-121.16
    state = {"next": 2, "clusters": [{"name": "shop-orders-db", "role": "active"},
                                     {"name": "shop-orders-db-g1", "role": "restored", "from": {"server": "shop-orders-db", "to": "2026-10-27T09:59:00Z"}}],
             "archives": ARCHIVES}
    g = with_state(tmp_path, state)
    assert cluster(g, "dev")["spec"]["imageName"] == PG[17]
    assert cluster(g, "dev", file="cluster-g1.yaml")["spec"]["imageName"] == PG[16], "the data of a physical backup only starts on its own major"


def test_a_restored_generation_from_the_current_archive_runs_the_effective_major_ac_121_16(tmp_path):  # AC-121.16
    state = {"next": 2, "clusters": [{"name": "shop-orders-db", "role": "active"},
                                     {"name": "shop-orders-db-g1", "role": "restored", "from": {"server": "shop-orders-db-pg17", "to": "latest"}}],
             "archives": ARCHIVES}
    assert cluster(with_state(tmp_path, state), "dev", file="cluster-g1.yaml")["spec"]["imageName"] == PG[17]


def test_a_switched_active_generation_on_an_older_major_prints_the_note_ac_121_16(tmp_path):  # AC-121.16
    state = {"next": 2, "clusters": [{"name": "shop-orders-db", "role": "previous", "until": "2026-10-27T11:02:13Z"},
                                     {"name": "shop-orders-db-g1", "role": "active", "from": {"server": "shop-orders-db", "to": "2026-10-27T09:59:00Z"}}],
             "archives": ARCHIVES}
    ok(tmp_path, backed_doc())
    (tmp_path / APP / "addons/dev/orders-db/restore-state.yaml").write_text(yaml.safe_dump(state, sort_keys=False))
    p = render(tmp_path)
    assert p.returncode == 0, p.stderr
    note = ("note: applications/shop: orders-db in dev runs shop-orders-db-g1 on 16 (restored from before the upgrade to 17); set "
            "resources.orders-db.instances.dev.version: 16, then /resource:upgrade orders-db --to 17 --env dev")  # spec 121 review: one working way forward
    assert note in (p.stdout + p.stderr).splitlines()
    assert cluster(tree(tmp_path), "dev", file="cluster-g1.yaml")["spec"]["imageName"] == PG[16]


def test_no_note_is_printed_when_the_active_generation_runs_the_effective_major_ac_121_16(tmp_path):  # AC-121.16
    ok(tmp_path, backed_doc())
    (tmp_path / APP / "addons/dev/orders-db/restore-state.yaml").write_text(yaml.safe_dump(
        {"next": 1, "clusters": [{"name": "shop-orders-db", "role": "active"}], "archives": ARCHIVES}, sort_keys=False))
    p = render(tmp_path)
    assert p.returncode == 0 and not re.search(r"(?m)^note: applications/shop: orders-db in dev runs", p.stdout + p.stderr)


@pytest.mark.parametrize("archives, why", [
    ("x", "archives: must be a list"),
    ([{"server": "", "major": 16}], "archives: every archive needs a server and a major"),
    ([{"server": "a", "major": 16}, {"server": "a", "major": 17}], "archives: servers must be unique"),
    ([{"server": "a", "major": 19}], "archives: major 19 is not in the versions table"),
    ([{"server": "a", "major": "16"}], "archives: every archive needs a server and a major"),
], ids=["not-a-list", "empty-server", "duplicate", "major-not-in-table", "major-not-int"])
def test_invalid_archives_fail_with_the_restore_state_form_ac_121_16(tmp_path, archives, why):  # AC-121.16
    ok(tmp_path, backed_doc())
    (tmp_path / APP / "addons/dev/orders-db/restore-state.yaml").write_text(yaml.safe_dump(
        {"next": 1, "clusters": [{"name": "shop-orders-db", "role": "active"}], "archives": archives}, sort_keys=False))
    p = render(tmp_path)
    assert p.returncode == 1
    head = "applications/shop/addons/dev/orders-db/restore-state.yaml is not valid (archives: "
    assert head in p.stderr and p.stderr.strip().endswith("); take it from git history"), p.stderr


# ---------------- AC-121.17 / .18: environment-property operators ----------------

def with_answers(tmp_path, doc, **answers) -> dict:
    tmp_path.mkdir(parents=True, exist_ok=True)
    if answers:
        (tmp_path / ".copier-answers.yml").write_text(yaml.safe_dump(answers))
    return ok(tmp_path, doc)


def apps_of(g) -> list[str]:
    return sorted(k.rsplit("/", 1)[-1].removesuffix(".yaml") for k in g if k.startswith("operators/apps/"))


def plain(**top) -> dict:
    return system(None, {"api": comp("api")}, **top)


def test_the_property_operators_are_not_rendered_without_the_answer_ac_121_17(tmp_path):  # AC-121.17
    assert "external-secrets" in apps_of(with_answers(tmp_path / "control", doc_with_everything(), property_operators="install")), "the answer install does render it"
    g = with_answers(tmp_path / "none", doc_with_everything())
    assert not {"external-secrets", "kyverno", "lgtm"} & set(apps_of(g))
    g = with_answers(tmp_path / "owner", doc_with_everything(), property_operators="owner")
    assert not {"external-secrets", "kyverno", "lgtm"} & set(apps_of(g))


def test_a_cache_broker_or_bucket_needs_external_secrets_for_its_generated_credentials_ac_121_17(tmp_path):  # AC-121.17
    for label, doc in (("cache", kdoc(9)), ("broker", bkdoc("2.15")), ("bucket", sdoc_bucket())):
        g = with_answers(tmp_path / label, doc, property_operators="install")
        assert "external-secrets" in apps_of(g), label


def test_a_component_with_secrets_or_secret_refs_needs_external_secrets_ac_121_17(tmp_path):  # AC-121.17
    g = with_answers(tmp_path / "refs", system(None, {"api": comp("api", secretRefs=["shared"])}), property_operators="install")
    assert "external-secrets" in apps_of(g)
    g = with_answers(tmp_path / "secrets", system(None, {"api": comp("api", secrets=[{"name": "api-auth", "generate": ["JWT_KEY"]}])}), property_operators="install")
    assert "external-secrets" in apps_of(g)


def test_an_external_resource_and_an_environment_backup_need_external_secrets_ac_121_17(tmp_path):  # AC-121.17
    ext = system({"d": db(external=True)}, {"api": comp("api", ["d"])})
    assert "external-secrets" in apps_of(with_answers(tmp_path / "ext", ext, property_operators="install"))
    bk = system({"backups": bucket()}, {"api": comp("api", ["backups"])})   # spec 121 slip: 117 requires the target bucket to be used there
    bk["environments"]["staging"]["backup"] = {"to": "backups"}
    assert "external-secrets" in apps_of(with_answers(tmp_path / "bk", bk, property_operators="install"))


def test_a_plain_system_needs_no_external_secrets_ac_121_17(tmp_path):  # AC-121.17
    g = with_answers(tmp_path, plain(), property_operators="install")
    assert "external-secrets" not in apps_of(g)


def test_kyverno_is_rendered_where_a_policy_is_not_off_and_a_component_runs_ac_121_17(tmp_path):  # AC-121.17
    doc = plain()
    doc["environments"]["dev"]["policy"] = "audit"
    assert "kyverno" in apps_of(with_answers(tmp_path / "on", doc, property_operators="install"))
    off = plain()
    for e in ENVS:
        off["environments"][e]["policy"] = "off"
    assert "kyverno" not in apps_of(with_answers(tmp_path / "off", off, property_operators="install"))


def test_lgtm_is_an_application_over_plain_manifests_ac_121_17(tmp_path):  # AC-121.17
    doc = plain()
    doc["environments"]["dev"]["observability"] = {"ui": "lgtm"}
    g = with_answers(tmp_path, doc, property_operators="install", github_org="acme", project_name="shop-gitops")
    app = y(g, "operators/apps/lgtm.yaml")
    assert app["apiVersion"] == "argoproj.io/v1alpha1" and app["kind"] == "Application"
    assert app["metadata"]["name"] == "operator-lgtm" and app["metadata"]["namespace"] == "argocd"
    assert app["metadata"]["labels"] == {"app.kubernetes.io/managed-by": "gitops-app", "app.kubernetes.io/component": "operator"}
    assert "finalizers" not in app["metadata"]
    assert app["spec"]["source"] == {"repoURL": "https://github.com/acme/shop-gitops", "targetRevision": "main", "path": "operators/lgtm"}
    assert app["spec"]["destination"]["namespace"] == "observability"
    assert app["spec"]["syncPolicy"]["syncOptions"] == ["CreateNamespace=true", "ServerSideApply=true"]
    assert sorted(k.rsplit("/", 1)[-1] for k in g if k.startswith("operators/lgtm/")) == ["deployment.yaml", "kustomization.yaml", "service.yaml"]
    dep = y(g, "operators/lgtm/deployment.yaml")
    assert dep["spec"]["template"]["spec"]["containers"][0]["image"] == LGTM
    assert y(g, "operators/lgtm/kustomization.yaml")["resources"] == ["deployment.yaml", "service.yaml"]


def test_lgtm_needs_a_ui_and_a_running_instance_and_is_listed_after_the_chart_operators_ac_121_17(tmp_path):  # AC-121.17
    assert "lgtm" not in apps_of(with_answers(tmp_path / "no-ui", doc_with_everything(), property_operators="install"))
    doc = doc_with_everything()
    doc["environments"]["dev"]["observability"] = {"ui": "lgtm"}
    g = with_answers(tmp_path / "ui", doc, property_operators="install")
    assert {"external-secrets", "kyverno", "lgtm"} <= set(apps_of(g))
    assert [k for k in g if k.startswith("operators/lgtm/")]


def test_one_operator_application_serves_all_environments_and_systems_ac_121_17(tmp_path):  # AC-121.17
    for name in ("alpha", "beta"):
        write_system(tmp_path, {**kdoc(9), "system": name}, name)
    (tmp_path / ".copier-answers.yml").write_text(yaml.safe_dump({"property_operators": "install"}))
    assert render(tmp_path).returncode == 0
    names = [k for k in tree(tmp_path) if k.startswith("operators/apps/")]
    assert names.count("operators/apps/external-secrets.yaml") == 1


def test_an_operator_nothing_needs_any_more_is_removed_ac_121_17(tmp_path):  # AC-121.17
    with_answers(tmp_path, kdoc(9), property_operators="install")
    assert (tmp_path / "operators/apps/external-secrets.yaml").is_file()
    write_system(tmp_path, plain())
    assert render(tmp_path).returncode == 0
    assert not (tmp_path / "operators/apps/external-secrets.yaml").exists()


def test_the_lgtm_directory_goes_with_its_application_ac_121_17(tmp_path):  # AC-121.17
    doc = plain()
    doc["environments"]["dev"]["observability"] = {"ui": "lgtm"}
    with_answers(tmp_path, doc, property_operators="install")
    assert (tmp_path / "operators/lgtm/deployment.yaml").is_file()
    write_system(tmp_path, plain())
    assert render(tmp_path).returncode == 0
    assert not (tmp_path / "operators/lgtm").exists() and not (tmp_path / "operators/apps/lgtm.yaml").exists()


def test_the_new_operator_applications_match_the_table_rows_ac_121_17(tmp_path):  # AC-121.17
    r = render_module("render_121_opapps")
    doc = doc_with_everything()
    doc["environments"]["dev"]["policy"] = "audit"
    g = with_answers(tmp_path, doc, property_operators="install")
    for n in ("external-secrets", "kyverno"):
        src = y(g, f"operators/apps/{n}.yaml")["spec"]["source"]
        assert (src["chart"], src["targetRevision"], src["repoURL"]) == (r.OPERATORS[n]["chart"], r.OPERATORS[n]["chart_version"], r.OPERATORS[n]["repo_url"])


# ---------------- AC-121.18: operators: owner ----------------

def test_an_owner_environment_gets_no_operator_application_ac_121_18(tmp_path):  # AC-121.18
    doc = doc_with_everything()
    doc["environments"]["dev"]["observability"] = {"ui": "lgtm"}
    doc["environments"]["dev"]["policy"] = "audit"
    assert {"external-secrets", "kyverno", "lgtm"} <= set(apps_of(with_answers(tmp_path / "control", doc, property_operators="install"))), "the same system without owner"
    for e in ENVS:
        doc["environments"][e]["operators"] = "owner"
    g = with_answers(tmp_path / "owner", doc, property_operators="install")
    assert apps_of(g) == []
    assert not [k for k in g if k.startswith("operators/")] or set(k for k in g if k.startswith("operators/")) == {"operators/root.yaml"}


def test_only_the_non_owner_environments_count_for_the_property_operators_ac_121_18(tmp_path):  # AC-121.18
    doc = kdoc(9)
    doc["components"]["api"]["instances"] = {"dev": {}}
    doc["environments"]["dev"]["operators"] = "owner"
    assert "external-secrets" not in apps_of(with_answers(tmp_path / "all-owner", doc, property_operators="install"))
    doc2 = kdoc(9)
    doc2["environments"]["dev"]["operators"] = "owner"
    assert "external-secrets" in apps_of(with_answers(tmp_path / "some", doc2, property_operators="install"))


def test_any_other_operators_value_fails_naming_owner_ac_121_18(tmp_path):  # AC-121.18
    doc = kdoc(9)
    doc["environments"]["dev"]["operators"] = "platform"
    fails(tmp_path, doc, "environments.dev.operators must be owner")


# ---------------- AC-121.22 / .26: the data the checks read ----------------

def test_every_operator_row_lists_the_crds_of_its_chart_with_served_versions_ac_121_22():  # AC-121.22
    r = render_module("render_121_crds")
    for n in OPERATOR_NAMES:
        crds = r.OPERATORS[n]["crds"]
        assert isinstance(crds, dict), n
        for name, versions in crds.items():
            assert re.fullmatch(r"[a-z0-9.-]+", name) and versions and all(isinstance(v, str) and re.fullmatch(r"v\d+(alpha\d+|beta\d+)?", v) for v in versions), (n, name)
        if r.OPERATORS[n]["crd"]:
            assert r.OPERATORS[n]["crd"] in crds, f"{n}: the CRD bootstrap waits for is one of its CRDs"
    assert r.OPERATORS["metrics-server"]["crds"] == {}


@pytest.mark.parametrize("operator, crd", [("cloudnative-pg", "clusters.postgresql.cnpg.io"), ("plugin-barman-cloud", "objectstores.barmancloud.cnpg.io"),
                                           ("velero", "schedules.velero.io"), ("keda", "scaledobjects.keda.sh"), ("nack", "streams.jetstream.nats.io"),
                                           ("external-secrets", "clustersecretstores.external-secrets.io"),
                                           ("kyverno", "namespacedvalidatingpolicies.policies.kyverno.io"), ("cert-manager", "certificates.cert-manager.io"),
                                           ("seaweedfs", "buckets.seaweed.seaweedfs.com")])
def test_the_crd_an_operator_is_waited_for_is_in_its_table_row_ac_121_22(operator, crd):  # AC-121.22
    served = render_module("render_121_crd_" + operator.replace("-", "_")).OPERATORS[operator]["crds"].get(crd)
    assert served, f"{operator} serves {crd}"
    assert any(re.fullmatch(r"v\d+.*", v) for v in served)


def test_the_cnpg_cluster_crd_serves_v1_ac_121_22():  # AC-121.22
    assert "v1" in render_module("render_121_cnpg").OPERATORS["cloudnative-pg"]["crds"]["clusters.postgresql.cnpg.io"]


# ---------------- AC-121.2 / .3: everything else renders as before except the engine references ----------------

def _before():
    from test_scale_120 import BEFORE_120, _before_120_docs
    return BEFORE_120, _before_120_docs()


@pytest.mark.parametrize("label", ["full5", "rich5", "db-bucket", "cache", "events", "events-multi", "broker", "broker-wide", "broker-ext", "expose-openapi"])
def test_a_system_without_the_new_keys_renders_as_before_after_the_references_are_mapped_back_ac_121_3(tmp_path, label):  # AC-121.3
    digests, docs = _before()
    g = ok(tmp_path, docs[label])
    digest, count = digests[label]
    from broker_fixtures import tree_digest
    assert (len(g), tree_digest(unpin(g))) == (count, digest), f"{label}: something besides the engine references changed"


@pytest.mark.parametrize("label", ["full5", "db-bucket", "cache", "broker"])
def test_the_engine_references_do_gain_a_digest_ac_121_3(tmp_path, label):  # AC-121.3
    _, docs = _before()
    g = ok(tmp_path, docs[label])
    assert unpin(g) != g and re.search(r"@sha256:[0-9a-f]{64}", "\n".join(g.values())), f"{label}: the references are exact and digested now"


def test_the_collector_reference_gains_its_digest_and_nothing_else_changes_ac_121_3(tmp_path):  # AC-121.3
    _, docs = _before()
    g = ok(tmp_path, docs["full5"])
    text = "\n".join(g.values())
    assert re.search(rf"image: {re.escape(COLLECTOR)}\b", text)
    assert COLLECTOR.split("@")[0] in unpin(g)[f"{APP}/addons/dev/observability/collector.yaml"]
    assert len(re.findall(SHA_COLLECTOR, text)) >= 1


SHA_COLLECTOR = r"opentelemetry-collector-contrib:0\.162\.0@sha256:[0-9a-f]{64}"
