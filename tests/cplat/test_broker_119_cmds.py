"""Spec 119 acceptance tests, the platform side: `/resource:add|remove` for brokers (AC-119.4, AC-119.17), the model, `cplat model show` and
`cplat api list` (AC-119.15, .17), `/platform:doctor` (AC-119.22, .23), the cluster scripts and the cluster-repo check (AC-119.19, .22,
.23), the e2e script text (AC-119.4, .9 .. .14, .16, .19 .. .22), the docs, plugins and changelog (AC-119.4, .14, .15, .17, .25).

Contract: design.md "Contract: cplat resource", "model, /api:list, status, doctor", "local cluster", "docs" and "e2e". Everything runs
through `cplat.main` or the modules on hand-built checkouts; `gh`, `kubectl` and the network are faked or not used. The e2e script is only
read (it needs a cluster): its text is asserted where the plan says so."""
import json
import re
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest
import yaml

import cplat
import gitops
from broker_fixtures import bdir, broker, bsys, expected_nack_application
from cluster_fixtures import base, cluster_repo, render_ok, script, stubs, sys_doc, system_repo, write_cluster
from resources_fixtures import APP, comp, db, platform_render_module, system
from system_fixtures import RENDER5, ROOT, files, git, init_git, mod, write_system

SYS = f"{APP}/system.yaml"
T = ROOT / "templates" / "gitops-app"
BKEYS = "url, user, password"
BIND = ("bind events APIs to it: an events API uses the system's only broker, or set apis.<api>.broker: <name>; its provider and consumers then get "
        "NATS_URL, NATS_USER, NATS_PASSWORD and EVENTS_<API>_* (no uses: needed)")
NACK_STEP = ("the platform installs the NACK controller through operators/ (apply operators/root.yaml once per cluster: KUBE_CONTEXT=<ctx> devbox run bootstrap); "
             "environments with operators: owner need it installed by their owner")
CREATE_STEP = "create on the external broker the streams and durable consumers that devbox run render prints (the platform creates none there)"


def sysdoc(repo):
    return yaml.safe_load((repo / APP / "system.yaml").read_text())


def run(*argv, capsys=None):
    rc = cplat.main([*map(str, argv)])
    if capsys is None:
        return rc
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def commit(repo, msg="x"):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "--allow-empty", "-m", msg)


def render_check(repo):
    return subprocess.run([sys.executable, "scripts/render.py", "--check"], cwd=repo, capture_output=True, text=True)


def make_repo(tmp_path, doc):
    """A checkout with the renderer; the first render is not asserted here, so a missing renderer feature fails the test, not the setup."""
    write_system(tmp_path, "# the shop system (keep this comment)\n" + yaml.safe_dump(doc, sort_keys=False))
    (tmp_path / "scripts").mkdir()
    shutil.copy(RENDER5, tmp_path / "scripts" / "render.py")
    (tmp_path / ".copier-answers.yml").write_text("github_org: acme\napp_name: shop\nproject_name: shop-gitops\n")
    subprocess.run([sys.executable, "scripts/render.py"], cwd=tmp_path, capture_output=True, text=True)
    return init_git(tmp_path)


@pytest.fixture()
def repo(tmp_path):
    return make_repo(tmp_path, system(None, {"api": comp("api"), "web": comp("web")}))


@pytest.fixture()
def repo_no_store(tmp_path):
    return make_repo(tmp_path, system(None, {"api": comp("api")}, store=False))


# ---------------- AC-119.4: resource add ----------------

def test_add_a_broker_declares_it_without_sizing_and_renders_ac_119_4(repo):  # AC-119.4
    assert run("resource", "add", "bus", "--type", "broker", "--repo-dir", repo) == 0
    assert sysdoc(repo)["resources"]["bus"] == {"type": "broker"}
    assert "# the shop system (keep this comment)" in (repo / SYS).read_text()
    assert render_check(repo).returncode == 0


def test_add_a_broker_with_version_and_replicas_writes_a_string_version_ac_119_4(repo):  # AC-119.4
    assert run("resource", "add", "bus", "--type", "broker", "--version", "2.14", "--replicas", "3", "--repo-dir", repo) == 0
    entry = sysdoc(repo)["resources"]["bus"]
    assert entry == {"type": "broker", "version": "2.14", "replicas": 3} and isinstance(entry["version"], str) and isinstance(entry["replicas"], int)
    assert list(entry) == ["type", "version", "replicas"] and render_check(repo).returncode == 0


def test_add_a_broker_with_only_a_version_or_only_replicas_ac_119_4(tmp_path):  # AC-119.4
    a = make_repo(tmp_path / "a", system(None, {"api": comp("api")}))
    assert run("resource", "add", "bus", "--type", "broker", "--version", "2.15", "--repo-dir", a) == 0
    assert sysdoc(a)["resources"]["bus"] == {"type": "broker", "version": "2.15"}
    b = make_repo(tmp_path / "b", system(None, {"api": comp("api")}))
    assert run("resource", "add", "bus", "--type", "broker", "--replicas", "1", "--repo-dir", b) == 0
    assert sysdoc(b)["resources"]["bus"] == {"type": "broker", "replicas": 1}


def test_a_broker_added_by_the_command_renders_its_objects_once_an_api_is_bound_ac_119_4(repo):  # AC-119.4
    assert run("resource", "add", "bus", "--type", "broker", "--repo-dir", repo) == 0
    doc = sysdoc(repo)
    doc["apis"] = {"orders": {"type": "events"}}
    doc["components"]["api"]["provides"] = ["orders"]
    doc["components"]["web"]["consumes"] = ["orders"]
    (repo / SYS).write_text(yaml.safe_dump(doc, sort_keys=False))
    done = subprocess.run([sys.executable, "scripts/render.py"], cwd=repo, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert (repo / bdir("dev") / "server.yaml").is_file() and (repo / "operators/apps/nack.yaml").is_file()


def test_add_an_external_broker_writes_the_small_typed_entry_ac_119_4(repo):  # AC-119.4
    assert run("resource", "add", "bus", "--type", "broker", "--external", "--repo-dir", repo) == 0
    assert sysdoc(repo)["resources"]["bus"] == {"type": "broker", "external": True}
    assert render_check(repo).returncode == 0


def test_add_an_external_broker_with_a_path_ac_119_4(repo):  # AC-119.4
    assert run("resource", "add", "bus", "--type", "broker", "--external", "--path", "{env}/{resource}/{component}", "--repo-dir", repo) == 0
    assert sysdoc(repo)["resources"]["bus"] == {"type": "broker", "external": True, "remote": {"path": "{env}/{resource}/{component}"}}
    assert render_check(repo).returncode == 0


def test_add_prints_the_next_steps_of_an_in_cluster_broker_ac_119_4(repo, capsys):  # AC-119.4
    rc, out, err = run("resource", "add", "bus", "--type", "broker", "--repo-dir", repo, capsys=capsys)
    assert rc == 0, err
    assert BIND in out and NACK_STEP in out
    assert out.index(BIND) < out.index(NACK_STEP)
    assert "let components use it" not in out and "CloudNativePG" not in out and "SeaweedFS" not in out


def test_add_prints_the_store_keys_and_the_create_step_of_an_external_broker_ac_119_4(repo, capsys):  # AC-119.4
    rc, out, err = run("resource", "add", "bus", "--type", "broker", "--external", "--repo-dir", repo, capsys=capsys)
    assert rc == 0, err
    keys = f"put the keys {BKEYS} in the secret store platform-secrets under shop-dev-bus-<component>, shop-staging-bus-<component>, shop-prod-bus-<component>"
    assert BIND in out and keys in out and CREATE_STEP in out and out.index(keys) < out.index(CREATE_STEP)
    assert NACK_STEP not in out


def test_add_formats_a_custom_path_with_the_component_placeholder_ac_119_4(repo, capsys):  # AC-119.4
    rc, out, _ = run("resource", "add", "bus", "--type", "broker", "--external", "--path", "{env}/{resource}/{component}", "--repo-dir", repo, capsys=capsys)
    assert rc == 0 and f"put the keys {BKEYS} in the secret store platform-secrets under dev/bus/<component>, staging/bus/<component>, prod/bus/<component>" in out


def test_add_pr_uses_the_resource_branch_and_title_for_a_broker_ac_119_4(repo, monkeypatch):  # AC-119.4
    seen = []
    monkeypatch.setattr(gitops, "open_pr", lambda r, branch, title, body: seen.append((branch, title)) or "https://github.com/acme/shop-gitops/pull/1")
    assert run("resource", "add", "bus", "--type", "broker", "--pr", "--repo-dir", repo) == 0
    assert seen == [("resource/add-bus", "feat(resource): add bus")]


@pytest.mark.parametrize("argv, needle", [
    (["c", "--type", "cache", "--version", "9"], "--version applies to --type database or broker only"),
    (["c", "--type", "bucket", "--version", "9"], "--version applies to --type database or broker only"),
    (["c", "--type", "cache", "--replicas", "3"], "--replicas applies to --type broker only"),
    (["c", "--type", "bucket", "--replicas", "3"], "--replicas applies to --type broker only"),
    (["c", "--type", "database", "--replicas", "3"], "--replicas applies to --type broker only"),
    (["b", "--type", "broker", "--external", "--replicas", "3"], "an external resource runs nothing: --replicas does not apply"),
    (["b", "--type", "broker", "--external", "--version", "2.15"], "an external resource runs nothing: --version does not apply"),
    (["b", "--type", "broker", "--version", "3"], "version '3' is not a supported broker version (2.14, 2.15)"),
    (["b", "--type", "broker", "--version", "2.16"], "version '2.16' is not a supported broker version (2.14, 2.15)"),
    (["b", "--type", "broker", "--version", "latest"], "version 'latest' is not a supported broker version (2.14, 2.15)"),
    (["b", "--type", "broker", "--replicas", "2"], "--replicas must be 1 or 3: a broker runs with 1 or 3 replicas"),
    (["b", "--type", "broker", "--replicas", "0"], "--replicas must be 1 or 3: a broker runs with 1 or 3 replicas"),
    (["b", "--type", "broker", "--replicas", "5"], "--replicas must be 1 or 3: a broker runs with 1 or 3 replicas"),
    (["b", "--type", "broker", "--storage", "1Gi"], "--storage and --versioning apply to --type bucket only"),
    (["b", "--type", "broker", "--path", "x"], "--path needs --external"),
])
def test_add_broker_errors_change_nothing_and_name_the_reason_ac_119_4(repo, capsys, argv, needle):  # AC-119.4
    before = files(repo)
    rc, _, err = run("resource", "add", *argv, "--repo-dir", repo, capsys=capsys)
    assert rc == 1 and needle in err, err
    assert files(repo) == before


def test_add_external_broker_needs_the_secret_store_ac_119_4(repo_no_store, capsys):  # AC-119.4
    before = files(repo_no_store)
    rc, _, err = run("resource", "add", "bus", "--type", "broker", "--external", "--repo-dir", repo_no_store, capsys=capsys)
    assert rc == 1 and "an external resource needs the system's secretStore" in err
    assert files(repo_no_store) == before


def test_add_a_broker_is_no_longer_refused_as_not_available_ac_119_4(repo, capsys):  # AC-119.4
    rc, _, err = run("resource", "add", "store", "--type", "broker", "--repo-dir", repo, capsys=capsys)
    assert rc == 0 and "not available yet" not in err


def test_the_option_help_names_the_broker_ac_119_4():  # AC-119.4
    text = (ROOT / "scripts" / "cplat" / "addon.py").read_text()
    assert "resource type: database, bucket, cache or broker" in text
    assert re.search(r"PLANNED_TYPES\s*=\s*\{\s*\}", text)
    assert "database major (15, 16, 17, 18) or broker version (2.14, 2.15)" in text
    assert "broker replicas: 1 or 3 (default 1)" in text
    assert "secret store key template for --external ({system}, {env}, {resource}; a broker also {component})" in text


def test_resource_add_names_the_same_store_keys_and_versions_as_the_renderer_ac_119_4():  # AC-119.4
    import addon
    r = platform_render_module("render_119_keys")
    assert sorted(addon.TYPE_KEYS) == sorted(r.TYPES) and r.PLANNED_TYPES == {}
    for t in r.TYPES:
        assert addon.TYPE_KEYS[t] == ", ".join(r.TYPES[t]["keys"]), t
    assert addon.BROKER_VERSIONS == r.BROKER_VERSIONS == ("2.14", "2.15")


# ---------------- AC-119.4: resource remove ----------------

def build_bound(tmp_path):
    """bus carries orders and audit (explicit), idle/ext/mixed carry nothing; web consumes orders and provides audit."""
    res = {"bus": broker(), "idle": broker(), "ext": broker(external=True), "mixed": broker(instances={"prod": {"external": True}})}
    comps = {"api": comp("api", provides=["orders"]), "web": comp("web", consumes=["orders"], provides=["audit"])}
    apis = {"orders": {"type": "events", "broker": "bus"}, "audit": {"type": "events", "broker": "bus"}}
    return make_repo(tmp_path, bsys(res, comps, apis))


def test_remove_of_a_bound_broker_names_the_apis_and_changes_nothing_ac_119_4(tmp_path, capsys):  # AC-119.4
    used = build_bound(tmp_path)
    before = files(tmp_path)
    rc, _, err = run("resource", "remove", "bus", "--repo-dir", used, capsys=capsys)
    assert rc == 1 and "bus carries the events APIs orders, audit" in err and "bind them to another broker (apis.<api>.broker) or remove them first" in err
    assert files(tmp_path) == before


def test_remove_of_a_bound_broker_with_dry_run_also_refuses_ac_119_4(tmp_path, capsys):  # AC-119.4
    used = build_bound(tmp_path)
    before = files(tmp_path)
    rc, _, err = run("resource", "remove", "bus", "--dry-run", "--repo-dir", used, capsys=capsys)
    assert rc == 1 and "bus carries the events APIs orders, audit" in err
    assert files(tmp_path) == before


def test_remove_names_only_the_apis_bound_to_that_broker_ac_119_4(tmp_path, capsys):  # AC-119.4
    res = {"bus": broker(), "queue": broker()}
    comps = {"api": comp("api", provides=["orders", "jobs"]), "web": comp("web", consumes=["orders"]), "worker": comp("worker", consumes=["jobs"])}
    apis = {"orders": {"type": "events", "broker": "bus"}, "jobs": {"type": "events", "broker": "queue"}}
    used = make_repo(tmp_path, bsys(res, comps, apis))
    rc, _, err = run("resource", "remove", "queue", "--repo-dir", used, capsys=capsys)
    assert rc == 1 and "queue carries the events APIs jobs" in err and "orders" not in err.split("carries the events APIs", 1)[1].splitlines()[0]


def test_remove_of_the_only_broker_counts_the_apis_without_a_broker_key_ac_119_4(tmp_path, capsys):  # AC-119.4
    used = make_repo(tmp_path, bsys())
    before = files(tmp_path)
    rc, _, err = run("resource", "remove", "bus", "--repo-dir", used, capsys=capsys)
    assert rc == 1 and "bus carries the events APIs orders" in err
    assert files(tmp_path) == before


def test_the_bound_check_comes_before_the_still_used_check_ac_119_4(tmp_path, capsys):  # AC-119.4
    comps = {"api": comp("api", ["bus"], provides=["orders"]), "web": comp("web", consumes=["orders"])}
    used = make_repo(tmp_path, bsys(comps=comps))
    rc, _, err = run("resource", "remove", "bus", "--repo-dir", used, capsys=capsys)
    assert rc == 1 and "bus carries the events APIs orders" in err and "still used by" not in err


def test_remove_of_an_in_cluster_broker_says_what_stays_ac_119_4(tmp_path, capsys):  # AC-119.4
    used = build_bound(tmp_path)
    rc, out, err = run("resource", "remove", "idle", "--dry-run", "--repo-dir", used, capsys=capsys)
    assert rc == 0, err
    assert ("remove idle from system.yaml; the Argo Application disappears but the broker, its volumes, streams, consumers and Secrets "
            "shop-idle-<component>-app stay in the cluster (delete them by hand when you are sure)") in out
    assert "the database and its data" not in out and "the cache, its volume" not in out and "the bucket, its data" not in out


def test_remove_of_an_external_broker_says_the_synced_secrets_stay_ac_119_4(tmp_path, capsys):  # AC-119.4
    used = build_bound(tmp_path)
    rc, out, err = run("resource", "remove", "ext", "--dry-run", "--repo-dir", used, capsys=capsys)
    assert rc == 0, err
    assert ("remove ext from system.yaml; the synced Secrets shop-ext-<component>-app stay in the cluster (delete them by hand when you are sure); "
            "the external broker is not touched") in out
    assert "the external database" not in out and "the external cache" not in out


def test_remove_of_a_mixed_broker_says_both_ac_119_4(tmp_path, capsys):  # AC-119.4
    used = build_bound(tmp_path)
    rc, out, _ = run("resource", "remove", "mixed", "--dry-run", "--repo-dir", used, capsys=capsys)
    assert rc == 0 and "streams, consumers and Secrets shop-mixed-<component>-app stay in the cluster" in out and "the external broker is not touched" in out


def test_remove_of_an_unbound_broker_removes_the_entry_and_renders_ac_119_4(tmp_path):  # AC-119.4
    used = build_bound(tmp_path)
    assert run("resource", "remove", "idle", "--repo-dir", used) == 0
    assert "idle" not in sysdoc(tmp_path)["resources"] and "bus" in sysdoc(tmp_path)["resources"]
    assert render_check(tmp_path).returncode == 0


# ---------------- AC-119.15 / .17 / .3: the model ----------------

def model_doc():
    res = {"bus": broker(version=2.14, replicas=3, storage="5Gi", instances={"prod": {"external": True}}), "idle": broker()}
    comps = {"api": comp("api", provides=["orders", "rest"]), "web": comp("web", consumes=["orders"], provides=["audit"], envs=("dev", "prod")),
             "worker": comp("worker", consumes=["audit", "rest"], envs=("dev",))}
    return bsys(res, comps, {"orders": {"type": "events", "broker": "bus"}, "audit": {"type": "events", "broker": "bus"}, "rest": {"type": "openapi"}})


@pytest.fixture()
def mrepo(tmp_path):
    write_system(tmp_path, model_doc())
    return tmp_path


# per environment: the components running there (users) and the consumers of each stream
BROKER_SHAPE = {"dev": (["api", "web", "worker"], {"orders": ["web"], "audit": ["worker"]}),
                "staging": (["api"], {"orders": [], "audit": []}),
                "prod": (["api", "web"], {"orders": ["web"], "audit": []})}


def expected_broker(env):
    ext = env == "prod"
    users, consumers = BROKER_SHAPE[env]
    return {"address": None if ext else f"nats://shop-bus.shop-{env}.svc:4222", "monitoring": None if ext else f"http://shop-bus.shop-{env}.svc:8222",
            "users": [{"component": c, "secret": f"shop-bus-{c}-app", "store_key": f"shop-{env}-bus-{c}" if ext else None} for c in users],
            "streams": [{"api": a, "stream": f"shop-{a}", "subjects": f"shop.{a}.>", "subject_prefix": f"shop.{a}",
                         "consumers": [{"name": c, "component": c} for c in consumers[a]]} for a in ("orders", "audit")]}


def test_broker_instances_carry_address_monitoring_users_and_streams_ac_119_15(mrepo):  # AC-119.15
    m = mod("model").load_dir(mrepo / APP)
    ri = {(r.resource, r.environment): r for r in m.resource_instances}
    for env in ("dev", "staging"):
        d = ri[("bus", env)]
        assert (d.type, d.external, d.argo_application, d.secret, d.store_key) == ("broker", False, f"addon-bus-{env}", None, None)
        assert d.broker == expected_broker(env), env
    assert ("idle", "dev") not in ri


def test_a_stream_lists_only_the_consumers_with_an_instance_ac_119_15(mrepo):  # AC-119.15
    ri = {(r.resource, r.environment): r for r in mod("model").load_dir(mrepo / APP).resource_instances}
    streams = {s["api"]: [c["name"] for c in s["consumers"]] for s in ri[("bus", "staging")].broker["streams"]}
    assert streams == {"orders": [], "audit": []}
    assert [u["component"] for u in ri[("bus", "dev")].broker["users"]] == ["api", "web", "worker"]
    assert [u["component"] for u in ri[("bus", "staging")].broker["users"]] == ["api"]


def test_the_model_json_has_the_broker_per_instance_and_the_api_broker_ac_119_15(mrepo, capsys):  # AC-119.15
    assert cplat.main(["model", "show", "--repo-dir", str(mrepo), "--json"]) == 0
    d = json.loads(capsys.readouterr().out)
    ri = {(r["resource"], r["environment"]): r for r in d["resource_instances"]}
    assert ri[("bus", "dev")]["broker"] == expected_broker("dev") and ri[("bus", "dev")]["secret"] is None
    assert d["schema"] == 2
    apis = {a["name"]: a for a in d["apis"]}
    assert apis["orders"]["broker"] == "bus" and apis["audit"]["broker"] == "bus" and "broker" not in apis["rest"]
    assert all("broker" not in r for k, r in ri.items() if r["type"] != "broker")


def test_the_sizing_of_a_broker_instance_is_version_replicas_and_storage_ac_119_3(mrepo):  # AC-119.3
    ri = {(r.resource, r.environment): r for r in mod("model").load_dir(mrepo / APP).resource_instances}
    assert dict(ri[("bus", "dev")].sizing) == {"version": "2.14", "replicas": 3, "storage": "5Gi"}
    assert list(ri[("bus", "dev")].sizing) == ["version", "replicas", "storage"]


def test_the_default_sizing_of_a_broker_instance_ac_119_3(tmp_path):  # AC-119.3
    write_system(tmp_path, bsys())
    ri = {(r.resource, r.environment): r for r in mod("model").load_dir(tmp_path / APP).resource_instances}
    assert dict(ri[("bus", "prod")].sizing) == {"version": "2.15", "replicas": 1, "storage": "1Gi"}


def test_an_external_instance_lists_the_names_the_owner_must_create_ac_119_17(mrepo):  # AC-119.17
    ri = {(r.resource, r.environment): r for r in mod("model").load_dir(mrepo / APP).resource_instances}
    e = ri[("bus", "prod")]
    assert (e.external, e.argo_application, e.secret, e.store_key, dict(e.sizing)) == (True, None, None, "shop-prod-bus-{component}", {})
    assert e.broker == expected_broker("prod")
    assert e.broker["address"] is None and e.broker["monitoring"] is None


def test_the_model_text_prints_the_broker_lines_ac_119_15(mrepo, capsys):  # AC-119.15
    assert cplat.main(["model", "show", "--repo-dir", str(mrepo)]) == 0
    out = capsys.readouterr().out.splitlines()
    i = out.index("    dev  type broker  external false  version 2.14  replicas 3  storage 5Gi  argo addon-bus-dev  secret -")
    assert out[i + 1:i + 4] == ["      address nats://shop-bus.shop-dev.svc:4222  monitoring http://shop-bus.shop-dev.svc:8222",
                                "      users api (shop-bus-api-app), web (shop-bus-web-app), worker (shop-bus-worker-app)",
                                "      stream shop-orders  subjects shop.orders.>  consumers web"]
    assert out[i + 4] == "      stream shop-audit  subjects shop.audit.>  consumers worker"


def test_the_model_text_prints_an_external_broker_and_empty_consumers_ac_119_17(mrepo, capsys):  # AC-119.17
    assert cplat.main(["model", "show", "--repo-dir", str(mrepo)]) == 0
    out = capsys.readouterr().out.splitlines()
    i = out.index("    prod  type broker  external true  argo -  secret -  store shop-prod-bus-{component}")
    assert out[i + 1] == "      address -  monitoring -"
    assert out[i + 2] == "      users api (shop-bus-api-app), web (shop-bus-web-app)"
    assert out[i + 4] == "      stream shop-audit  subjects shop.audit.>  consumers -"


def test_the_model_text_ends_an_events_api_line_with_its_broker_ac_119_15(mrepo, capsys):  # AC-119.15
    assert cplat.main(["model", "show", "--repo-dir", str(mrepo)]) == 0
    out = capsys.readouterr().out.splitlines()
    assert "  orders  type events  provider api  consumers web  broker bus" in out
    assert "  audit  type events  provider web  consumers worker  broker bus" in out
    assert "  rest  type openapi  provider api  consumers worker" in out


def test_components_use_their_broker_implicitly_in_the_model_ac_119_15(mrepo):  # AC-119.15
    m = mod("model").load_dir(mrepo / APP)
    uses = {c.name: tuple(c.uses) for c in m.components}
    assert uses == {"api": ("bus",), "web": ("bus",), "worker": ("bus",)}
    res = {r.name: r for r in m.resources}
    assert set(res) == {"bus", "idle"}
    d = m.to_dict()
    assert next(r for r in d["resources"] if r["name"] == "bus")["used_by"] == ["api", "web", "worker"]
    assert next(r for r in d["resources"] if r["name"] == "idle")["used_by"] == []


def test_the_api_broker_is_the_only_broker_or_none_ac_119_15(tmp_path):  # AC-119.15
    write_system(tmp_path / "a", bsys())
    assert {a.name: a.broker for a in mod("model").load_dir(tmp_path / "a" / APP).apis} == {"orders": "bus"}
    write_system(tmp_path / "b", bsys({"d": db()}))
    assert {a.name: a.broker for a in mod("model").load_dir(tmp_path / "b" / APP).apis} == {"orders": None}
    write_system(tmp_path / "c", bsys({"bus": broker(), "queue": broker()}, apis={"orders": {"type": "events", "broker": "queue"}}))
    assert {a.name: a.broker for a in mod("model").load_dir(tmp_path / "c" / APP).apis} == {"orders": "queue"}


def test_the_renderer_and_the_model_agree_on_broker_instances_ac_119_15(tmp_path):  # AC-119.15
    write_system(tmp_path, model_doc())
    (tmp_path / "scripts").mkdir()
    shutil.copy(RENDER5, tmp_path / "scripts" / "render.py")
    done = subprocess.run([sys.executable, "scripts/render.py"], cwd=tmp_path, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    app_dir = tmp_path / APP
    import importlib.util
    spec = importlib.util.spec_from_file_location("render_under_test_119", tmp_path / "scripts" / "render.py")
    r = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(r)
    m = mod("model").load_dir(app_dir)
    renderer = sorted(r.resource_instances(r.load_system(app_dir)))
    assert renderer == sorted((ri.resource, ri.environment, ri.type, ri.external) for ri in m.resource_instances)
    ran = sorted((p.name, p.parent.name) for p in (app_dir / "addons").glob("*/*") if p.is_dir() and p.name != "observability")
    assert ran == sorted((ri.resource, ri.environment) for ri in m.resource_instances if not ri.external)


# ---------------- AC-119.15: /api:list ----------------

def api_repo(tmp_path):
    write_system(tmp_path, model_doc())
    return tmp_path


def test_api_list_text_ends_bound_events_apis_with_their_broker_ac_119_15(tmp_path, capsys):  # AC-119.15
    repo = api_repo(tmp_path)
    assert cplat.main(["api", "list", "--repo-dir", str(repo)]) == 0
    assert capsys.readouterr().out.splitlines() == ["orders  type events  provider api  consumers web  broker bus",
                                                    "audit  type events  provider web  consumers worker  broker bus",
                                                    "rest  type openapi  provider api  consumers worker"]


def test_api_list_text_leaves_other_lines_unchanged_ac_119_15(tmp_path, capsys):  # AC-119.15
    repo = api_repo(tmp_path)
    assert cplat.main(["api", "list", "--repo-dir", str(repo)]) == 0
    out = capsys.readouterr().out.splitlines()
    assert "orders  type events  provider api  consumers web  broker bus" in out and "audit  type events  provider web  consumers worker  broker bus" in out
    assert "rest  type openapi  provider api  consumers worker" in out
    assert not [ln for ln in out if ln.startswith("rest") and "broker" in ln]


def test_api_list_json_adds_broker_to_events_apis_only_ac_119_15(tmp_path, capsys):  # AC-119.15
    repo = api_repo(tmp_path)
    assert cplat.main(["api", "list", "--repo-dir", str(repo), "--json"]) == 0
    apis = {a["name"]: a for a in json.loads(capsys.readouterr().out)["apis"]}
    assert apis["orders"] == {"name": "orders", "type": "events", "provider": "api", "consumers": ["web"], "broker": "bus"}
    assert apis["rest"] == {"name": "rest", "type": "openapi", "provider": "api", "consumers": ["worker"]}


def test_api_list_json_says_null_for_an_events_api_no_broker_carries_ac_119_15(tmp_path, capsys):  # AC-119.15
    write_system(tmp_path, bsys({"d": db()}))
    assert cplat.main(["api", "list", "--repo-dir", str(tmp_path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["apis"] == [{"name": "orders", "type": "events", "provider": "api", "consumers": ["web"], "broker": None}]
    assert cplat.main(["api", "list", "--repo-dir", str(tmp_path)]) == 0
    assert capsys.readouterr().out.splitlines() == ["orders  type events  provider api  consumers web"]


# ---------------- AC-119.22 / .23: doctor ----------------

def kube(monkeypatch, nack=None, brokers=None, kubectl=True):
    """Fakes doctor's kubectl: the NACK controller image and, per namespace, the broker StatefulSet's chart label and server image."""
    import doctor
    monkeypatch.setattr(doctor.shutil, "which", lambda t: f"/usr/bin/{t}" if kubectl else None)
    brokers = brokers or {}

    def fake_run(cmd, *a, **k):
        text = " ".join(str(c) for c in cmd)
        if "statefulsets.apps" in text:
            ns = cmd[cmd.index("-n") + 1] if "-n" in cmd else ""
            have = brokers.get(ns)
            return SimpleNamespace(stdout=have or "", stderr="", returncode=0 if have else 1)
        if "app.kubernetes.io/name=nack" in text and nack:
            return SimpleNamespace(stdout=f"natsio/jetstream-controller:{nack}", stderr="", returncode=0)
        return SimpleNamespace(stdout="", stderr="", returncode=0)
    monkeypatch.setattr(doctor, "run", fake_run)


def want(name="nack"):
    return platform_render_module("render_119_doctor").OPERATORS[name]


def nack_rows(repo):
    import doctor
    return [c for c in doctor.check_operators(repo) if c["name"] == "operator nack"]


def test_doctor_is_ok_when_nack_matches_ac_119_22(tmp_path, monkeypatch):  # AC-119.22
    kube(monkeypatch, nack=want()["operator_version"])
    write_system(tmp_path, bsys())
    [row] = nack_rows(tmp_path)
    assert row["status"] == "ok" and row["detail"] == "installed 0.24.0, expected 0.24.0 (Argo CD application operator-nack)"


def test_doctor_warns_naming_a_missing_nack_ac_119_22(tmp_path, monkeypatch):  # AC-119.22
    kube(monkeypatch)
    write_system(tmp_path, bsys())
    [row] = nack_rows(tmp_path)
    assert row["status"] == "warn" and row["detail"] == "not installed in the current kube context, expected 0.24.0 (Argo CD application operator-nack)"
    assert "apply operators/root.yaml once: KUBE_CONTEXT=" in row["fix"]


def test_doctor_warns_naming_both_versions_when_nack_differs_ac_119_22(tmp_path, monkeypatch):  # AC-119.22
    kube(monkeypatch, nack="0.23.0")
    write_system(tmp_path, bsys())
    [row] = nack_rows(tmp_path)
    assert row["status"] == "warn" and row["detail"] == "installed 0.23.0, expected 0.24.0 (Argo CD application operator-nack)"
    assert row["fix"] == "sync operator-nack in Argo CD"


def test_doctor_checks_owner_managed_environments_too_ac_119_23(tmp_path, monkeypatch):  # AC-119.23
    doc = bsys()
    for e in ("dev", "staging", "prod"):
        doc["environments"][e]["operators"] = "owner"
    write_system(tmp_path, doc)
    kube(monkeypatch)
    [row] = nack_rows(tmp_path)
    assert row["status"] == "warn" and row["detail"] == ("not installed in the current kube context, expected 0.24.0 "
                                                          "(operators: owner in dev, prod, staging)")
    assert row["fix"] == "install the nack chart 0.35.0 (operator 0.24.0)"
    kube(monkeypatch, nack="0.23.0")
    [row] = nack_rows(tmp_path)
    assert row["status"] == "warn" and "installed 0.23.0, expected 0.24.0" in row["detail"] and row["fix"] == "move the nack chart to 0.35.0 (operator 0.24.0)"
    kube(monkeypatch, nack="0.24.0")
    [row] = nack_rows(tmp_path)
    assert row["status"] == "ok" and "operators: owner in" in row["detail"]


def test_doctor_has_no_nack_row_without_an_in_cluster_broker_or_kubectl_ac_119_23(tmp_path, monkeypatch):  # AC-119.23
    kube(monkeypatch)
    write_system(tmp_path / "in", bsys())
    assert [c["name"] for c in nack_rows(tmp_path / "in")] == ["operator nack"]
    write_system(tmp_path / "ext", bsys({"bus": broker(external=True)}))
    write_system(tmp_path / "none", system({"d": db()}, {"api": comp("api", ["d"])}))
    write_system(tmp_path / "unused", bsys(comps={"api": comp("api")}, apis={}))
    for d in ("ext", "none", "unused"):
        assert nack_rows(tmp_path / d) == [], d
    kube(monkeypatch, kubectl=False)
    write_system(tmp_path / "plain", bsys())
    assert nack_rows(tmp_path / "plain") == []


def test_doctor_lists_nack_after_the_other_operators_ac_119_22(tmp_path, monkeypatch):  # AC-119.22
    import doctor
    kube(monkeypatch)
    comps = {"api": comp("api", ["d"], provides=["orders"]), "web": comp("web", consumes=["orders"])}
    write_system(tmp_path, bsys({"bus": broker(), "d": db()}, comps))
    assert [c["name"] for c in doctor.check_operators(tmp_path)] == ["operator cloudnative-pg", "operator nack"]


def test_doctor_has_one_row_per_in_cluster_broker_instance_ac_119_22(tmp_path, monkeypatch):  # AC-119.22
    import doctor
    ok = "nats-2.15.1 nats:2.15.2-alpine"
    kube(monkeypatch, brokers={"shop-dev": ok, "shop-staging": ok, "shop-prod": ok})
    write_system(tmp_path, bsys({"bus": broker(instances={"prod": {"external": True}})}))
    rows = doctor.check_brokers(tmp_path)
    assert [c["name"] for c in rows] == ["broker bus (dev)", "broker bus (staging)"]
    assert all(c["status"] == "ok" and c["detail"] == "nats chart 2.15.1, server nats:2.15.2-alpine (expected)" for c in rows)


def test_doctor_warns_when_a_broker_is_not_running_ac_119_22(tmp_path, monkeypatch):  # AC-119.22
    import doctor
    kube(monkeypatch, brokers={})
    write_system(tmp_path, bsys())
    rows = doctor.check_brokers(tmp_path)
    assert [c["name"] for c in rows] == ["broker bus (dev)", "broker bus (staging)", "broker bus (prod)"]
    assert rows[0]["status"] == "warn"
    assert rows[0]["detail"] == "not running in the current kube context; expected nats chart 2.15.1, server nats:2.15.2-alpine"
    assert rows[0]["fix"] == "sync the Argo CD application shop-bus-dev-nats (local: devbox run cluster-up)"


def test_doctor_warns_naming_both_when_a_broker_differs_ac_119_22(tmp_path, monkeypatch):  # AC-119.22
    import doctor
    kube(monkeypatch, brokers={"shop-dev": "nats-2.14.0 nats:2.14.9-alpine", "shop-staging": "nats-2.15.1 nats:2.15.2-alpine", "shop-prod": "nats-2.15.1 nats:2.15.2-alpine"})
    write_system(tmp_path, bsys())
    rows = {c["name"]: c for c in doctor.check_brokers(tmp_path)}
    dev = rows["broker bus (dev)"]
    assert dev["status"] == "warn"
    assert dev["detail"] == "nats chart 2.14.0, server nats:2.14.9-alpine; expected nats chart 2.15.1, server nats:2.15.2-alpine"
    assert dev["fix"] == "sync the Argo CD application shop-bus-dev-nats"
    assert rows["broker bus (staging)"]["status"] == "ok"


def test_doctor_reads_the_statefulset_of_the_broker_in_its_namespace_ac_119_22(tmp_path, monkeypatch):  # AC-119.22
    import doctor
    seen = []
    kube(monkeypatch)

    def spy(cmd, *a, **k):
        seen.append([str(c) for c in cmd])
        return SimpleNamespace(stdout="", stderr="", returncode=1)
    monkeypatch.setattr(doctor, "run", spy)
    write_system(tmp_path, bsys(comps={"api": comp("api", provides=["orders"], envs=("dev",)), "web": comp("web", consumes=["orders"], envs=("dev",))}))
    doctor.check_brokers(tmp_path)
    [cmd] = [c for c in seen if "statefulsets.apps" in c]
    assert cmd[:2] == ["kubectl", "-n"] and cmd[2] == "shop-dev" and "shop-bus" in cmd


def test_doctor_has_no_broker_rows_without_kubectl_and_none_for_external_ones_ac_119_22(tmp_path, monkeypatch):  # AC-119.22
    import doctor
    kube(monkeypatch, kubectl=False)
    write_system(tmp_path / "a", bsys())
    assert doctor.check_brokers(tmp_path / "a") == []
    kube(monkeypatch)
    write_system(tmp_path / "b", bsys({"bus": broker(external=True)}))
    assert doctor.check_brokers(tmp_path / "b") == []


# ---------------- AC-119.19 / .22 / .23: the cluster scripts ----------------

def test_bootstrap_waits_for_the_nack_crd_ac_119_22():  # AC-119.22
    text = (T / "scripts" / "bootstrap.sh").read_text()
    assert "nack) crd=streams.jetstream.nats.io ;;" in text
    assert "velero) crd=schedules.velero.io ;;" in text and "cloudnative-pg) crd=clusters.postgresql.cnpg.io ;;" in text


def test_cluster_up_installs_or_waits_for_nack_ac_119_22():  # AC-119.22
    text = (T / "scripts" / "local-cluster.sh").read_text()
    for needle in ("WITH_NACK", "NACK_VERSION", "operators/apps/nack.yaml", "0.35.0", "https://nats-io.github.io/k8s/helm/charts", "streams.jetstream.nats.io",
                   "deploy/nack", "app.kubernetes.io/name=nack", 'with_nack" = 1', "operators/root.yaml", "targetNamespace: nack", "name: nack"):
        assert needle in text, f"local-cluster.sh lacks {needle!r}"


def test_cluster_up_forces_nack_only_when_asked_and_defaults_to_the_operator_file_ac_119_19():  # AC-119.19
    text = (T / "scripts" / "local-cluster.sh").read_text()
    assert re.search(r"(?m)^#\s+WITH_NACK\s+1 = ", text) and re.search(r"(?m)^#\s+NACK_VERSION\s", text)
    assert "exists" in re.search(r"(?m)^#\s+WITH_NACK.*$", text).group(0)


def test_the_cluster_script_default_pin_matches_the_versions_table_ac_119_22():  # AC-119.22
    r = platform_render_module("render_119_scripts")
    text = (T / "scripts" / "local-cluster.sh").read_text()
    assert r.OPERATORS["nack"]["chart_version"] in text and r.OPERATORS["nack"]["repo_url"] in text


def test_the_cluster_repo_copy_of_the_cluster_script_is_byte_equal_ac_119_22():  # AC-119.22
    src, dst = T / "scripts" / "local-cluster.sh", ROOT / "templates" / "cluster-gitops" / "scripts" / "local-cluster.sh"
    assert "WITH_NACK" in dst.read_text() and dst.read_bytes() == src.read_bytes()


@pytest.mark.parametrize("name", ["bootstrap.sh", "local-cluster.sh"])
def test_the_cluster_scripts_parse_ac_119_22(name):  # AC-119.22
    if not shutil.which("bash"):
        pytest.skip("no bash")
    assert "nack" in (T / "scripts" / name).read_text()
    p = subprocess.run(["bash", "-n", str(T / "scripts" / name)], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr


# ---------------- AC-119.22 / .23: cluster repos ----------------

@pytest.fixture()
def world(shared_renders, tmp_path, monkeypatch):
    crepo = cluster_repo(shared_renders, tmp_path)
    s = stubs(tmp_path, monkeypatch)
    (crepo / ".platform-version").write_text("platform: 5.1.0\n")
    return crepo, s


def broker_doc(name="alpha"):
    doc = sys_doc(name)
    doc["resources"] = {"bus": {"type": "broker"}}
    doc["apis"] = {"orders": {"type": "events"}}
    doc["components"]["api"]["provides"] = ["orders"]
    doc["components"]["web"] = comp("web", consumes=["orders"])
    return doc


def test_a_cluster_repo_may_list_nack_and_renders_the_same_application_ac_119_22(shared_renders, tmp_path):  # AC-119.22
    crepo = cluster_repo(shared_renders, tmp_path)
    got = render_ok(crepo, base(operators=["nack"]))
    assert yaml.safe_load(got["cluster/operators/nack.yaml"]) == expected_nack_application()


def test_the_cluster_check_asks_for_nack_and_external_secrets_for_a_broker_ac_119_22(world):  # AC-119.22
    crepo, s = world
    system_repo(s["fixtures"], "acme/alpha-gitops", broker_doc())
    write_cluster(crepo, base(systems={"alpha": {"repo": "acme/alpha-gitops"}}))
    render_ok(crepo, crepo.joinpath("cluster.yaml").read_text())
    p = script(crepo, "check.py")
    out = p.stdout + p.stderr
    assert p.returncode == 1
    assert "ERROR: alpha (dev): needs nack, which cluster.yaml does not list in operators" in out
    assert "ERROR: alpha (dev): needs external-secrets, which cluster.yaml does not list in operators" in out


def test_the_cluster_check_is_quiet_when_the_operators_are_listed_ac_119_22(world):  # AC-119.22
    crepo, s = world
    system_repo(s["fixtures"], "acme/alpha-gitops", broker_doc())
    write_cluster(crepo, base(operators=["nack", "external-secrets"], systems={"alpha": {"repo": "acme/alpha-gitops"}}))
    render_ok(crepo, crepo.joinpath("cluster.yaml").read_text())
    p = script(crepo, "check.py")
    assert "needs nack" not in p.stdout + p.stderr


def test_the_cluster_check_asks_for_no_nack_for_an_external_broker_ac_119_23(world):  # AC-119.23
    crepo, s = world
    doc = broker_doc()
    doc["resources"] = {"bus": {"type": "broker", "external": True}}
    system_repo(s["fixtures"], "acme/alpha-gitops", doc)
    write_cluster(crepo, base(systems={"alpha": {"repo": "acme/alpha-gitops"}}))
    render_ok(crepo, crepo.joinpath("cluster.yaml").read_text())
    out = script(crepo, "check.py")
    assert "needs nack" not in out.stdout + out.stderr and "needs external-secrets" in out.stdout + out.stderr


# ---------------- the e2e script ----------------

def e2e() -> str:
    return (ROOT / "tests" / "e2e" / "run.sh").read_text()


def need(text: str, *needles: str) -> None:
    for n in needles:
        assert n in text, f"tests/e2e/run.sh lacks {n!r}"


def test_the_e2e_script_declares_a_broker_with_two_events_apis_ac_119_19():  # AC-119.19 (needs a cluster)
    need(e2e(), "nstep", "nfail", "resource add bus --type broker", "apis.orders", "apis.audit", "e2e-orders", "e2e-audit", "WITH_NACK=1",
         "e2e-natsprobe:1", "nats-py==2.16.0")


def test_the_e2e_script_header_budgets_the_broker_steps_and_the_job_gets_75_minutes_ac_119_19():  # AC-119.19 (needs a cluster)
    assert re.search(r"(?is)broker.{0,300}5 minutes", e2e()[:6000])
    assert re.search(r"(?m)^\s*timeout-minutes:\s*75\b", (ROOT / ".github" / "workflows" / "e2e.yml").read_text())


def test_the_e2e_script_delivers_one_message_within_30_seconds_ac_119_13():  # AC-119.13 (needs a cluster)
    need(e2e(), "pull_subscribe_bind", "js.publish", "fetch", "m1", "e2e-natsprobe", "30")


def test_the_e2e_script_delivers_a_message_published_while_the_consumer_was_stopped_ac_119_13():  # AC-119.13 (needs a cluster)
    need(e2e(), "m2", "m3", "while no consumer")


def test_the_e2e_script_checks_that_an_acknowledged_message_is_not_delivered_again_ac_119_13():  # AC-119.13 (needs a cluster)
    need(e2e(), "ack()", "again")
    assert re.search(r"(?is)(not|never) (re)?deliver|no redeliver|only m2 and m3|exactly m2", e2e())


def test_the_e2e_script_proves_the_stream_and_consumer_settings_ac_119_9():  # AC-119.9 (needs a cluster)
    need(e2e(), "/jsz?accounts=true&streams=true&consumers=true", "e2e.orders.>", "max_age", "file")


def test_the_e2e_script_proves_the_consumer_settings_ac_119_10():  # AC-119.10 (needs a cluster)
    need(e2e(), "consumers.jetstream.nats.io", "e2e-orders.e2e-web", "ack_wait", "explicit")


def test_the_e2e_script_proves_the_secret_and_variable_contract_ac_119_11():  # AC-119.11 (needs a cluster)
    need(e2e(), "e2e-bus-e2e-web-app", "kubectl kustomize", "EVENTS_ORDERS_", "EVENTS_AUDIT_", "_INBOX.e2e-web", "NATS_INBOX_PREFIX", "nats://e2e-bus.e2e-dev.svc:4222")


def test_the_e2e_script_proves_the_refusals_ac_119_12():  # AC-119.12 (needs a cluster)
    need(e2e(), "Permissions Violation", "e2e.orders.created", "e2e.audit.done", "e2e.audit.>", "e2e.orders.>")


def test_the_e2e_script_reads_the_pending_counts_ac_119_16():  # AC-119.16 (needs a cluster)
    need(e2e(), "num_pending", "num_ack_pending", "8222")


def test_the_e2e_script_proves_the_pins_and_the_declared_objects_ac_119_20():  # AC-119.20 (needs a cluster)
    need(e2e(), "operators/apps/nack.yaml", "0.35.0", "0.24.0", "2.15.1", "2.15.2-alpine")


def test_the_e2e_script_applies_the_declared_objects_with_full_kind_names_ac_119_21():  # AC-119.21 (needs a cluster)
    need(e2e(), "streams.jetstream.nats.io", "consumers.jetstream.nats.io", "accounts.jetstream.nats.io", "helmcharts.helm.cattle.io",
         "statefulsets.apps", "externalsecrets.external-secrets.io", "passwords.generators.external-secrets.io", "persistentvolumeclaims")


def test_the_e2e_script_runs_doctor_and_expects_the_nack_and_broker_rows_ac_119_22():  # AC-119.22 (needs a cluster)
    need(e2e(), "platform doctor", "operator nack", "broker bus (dev)")


def test_the_e2e_script_refuses_the_removal_while_apis_are_bound_ac_119_4():  # AC-119.4 (needs a cluster)
    need(e2e(), "resource remove bus", "orders, audit")


def test_the_e2e_script_checks_the_retired_names_and_that_the_stream_stays_ac_119_14():  # AC-119.14 (needs a cluster)
    need(e2e(), "is no longer declared", "e2e-orders", "e2e-audit")
    assert re.search(r"(?is)no longer declared.{0,3000}(jsz|messages)", e2e())


# ---------------- docs, changelog, plugins ----------------

def domain_model() -> str:
    return (ROOT / "docs" / "DOMAIN-MODEL.md").read_text()


def design_example() -> str:
    text = (ROOT / "docs" / "specs" / "119-a-message-broker-resource-behind-events" / "design.md").read_text()
    # spec 119 slip: design.md has three python blocks; the documented example is the one that connects
    return next(b for b in re.findall(r"```python\n(.*?)```", text, re.S) if "nats.connect" in b)


def test_the_domain_model_documents_the_broker_and_its_environment_contract_ac_119_25():  # AC-119.25
    text = domain_model()
    for needle in ("JetStream", "NATS_URL", "NATS_USER", "NATS_PASSWORD", "NATS_INBOX_PREFIX", "EVENTS_<API>_STREAM", "EVENTS_<API>_SUBJECT_PREFIX",
                   "EVENTS_<API>_CONSUMER", "<system>-<name>-<component>-app", "/jsz", "spec 120", "spec 119", "apis.<api>.broker"):
        assert needle in text, f"DOMAIN-MODEL.md lacks {needle!r}"
    assert "`broker`, which is reserved" not in text and "spec 119 delivers it" not in text
    assert re.search(r"7 days", text) and re.search(r"30 s(econds)?", text)


def test_the_domain_model_has_exactly_the_one_python_example_ac_119_25():  # AC-119.25
    text = domain_model()
    blocks = re.findall(r"```python\n(.*?)```", text, re.S)
    assert len(blocks) == 1, "exactly one Python example"
    assert blocks[0].strip() == design_example().strip()
    for needle in ('os.environ["NATS_URL"]', 'os.environ["NATS_USER"]', 'os.environ["NATS_PASSWORD"]', 'os.environ["NATS_INBOX_PREFIX"]',
                   'os.environ["EVENTS_ORDERS_SUBJECT_PREFIX"]', 'os.environ["EVENTS_ORDERS_CONSUMER"]', 'os.environ["EVENTS_ORDERS_STREAM"]'):
        assert needle in blocks[0]


def test_no_template_ships_publisher_or_subscriber_code_ac_119_25():  # AC-119.25
    assert "```python" in domain_model(), "the docs example exists"
    for p in (ROOT / "templates").rglob("*"):
        if p.is_file() and p.suffix in (".py", ".jinja", ".java", ".go", ".ts", ".tsx", ".js") and p.name != "render.py" and p.name != "system_render.py":
            t = p.read_text(errors="ignore")
            assert "pull_subscribe" not in t and "nats.connect" not in t and "import nats" not in t, p


def test_the_docs_say_streams_and_consumers_stay_after_a_removal_ac_119_14():  # AC-119.14
    text = domain_model()
    assert re.search(r"(?is)(stream|consumer)[^.]{0,200}(never deleted|not deleted|stays?|until (you|a person|a human|someone) delete)", text)
    assert re.search(r"(?i)no longer declared", text)


def test_the_docs_describe_the_external_broker_and_the_names_to_create_ac_119_17():  # AC-119.17
    text = domain_model()
    assert re.search(r"(?is)external broker.{0,500}(create|owner)", text)
    assert "{component}" in text and "url" in text and re.search(r"(?i)synadia|nats service", text)


def test_the_user_journey_and_the_site_describe_the_broker_ac_119_25():  # AC-119.25
    assert "Events between components" in (ROOT / "docs" / "USER-JOURNEY.md").read_text()
    site = (ROOT / "site" / "src" / "content" / "docs" / "concepts" / "addons.md").read_text()
    assert "NATS_URL" in site and "broker" in site


def test_the_backup_guide_says_broker_volumes_are_in_the_environment_backup_ac_119_14():  # AC-119.14
    text = (ROOT / "docs" / "BACKUP-AND-RESTORE.md").read_text()
    assert re.search(r"(?is)broker[^|\n]{0,300}(volume|JetStream)", text) and "Cache data is not backed up" in text


def test_the_cluster_guide_lists_nack_among_the_operators_ac_119_22():  # AC-119.22
    text = (ROOT / "docs" / "CLUSTERS.md").read_text()
    assert "nack" in text and re.search(r"(?i)broker", text)


def test_the_resource_plugin_docs_describe_the_broker_ac_119_4():  # AC-119.4
    add = (ROOT / "plugins/resource/commands/add.md").read_text()
    for needle in ("--type database|bucket|cache|broker", "--replicas", "NATS_URL", "EVENTS_ORDERS_STREAM", "apis.<api>.broker", "NACK", "{component}"):
        assert needle in add, needle
    assert "exits 1 and names the spec that brings it" not in add and "`broker` are built" not in add
    remove = (ROOT / "plugins/resource/commands/remove.md").read_text()
    assert "broker" in remove and re.search(r"(?i)events API", remove)
    readme = (ROOT / "plugins/resource/README.md").read_text()
    assert "`broker`" in readme and "reserved for spec 119" not in readme


def test_the_api_plugin_docs_describe_the_broker_column_ac_119_15():  # AC-119.15
    listing = (ROOT / "plugins/api/commands/list.md").read_text()
    assert "broker" in listing and "  broker <b>" in listing.replace("`", "")
    assert "broker" in (ROOT / "plugins/api/README.md").read_text()


def test_the_changelog_lists_the_broker_in_a_minor_section_that_is_not_breaking_ac_119_15():  # AC-119.15
    text = (ROOT / "docs" / "CHANGELOG.md").read_text()
    sections = re.split(r"(?m)^(?=## \[)", text)
    hits = [s for s in sections if s.startswith("## [") and re.search(r"spec 119|ADR-065", s)]
    assert hits, "the change is listed"
    assert re.match(r"## \[(Unreleased|5\.[1-9]\d*\.0)\]", hits[0].splitlines()[0])
    entry = next(e for e in re.split(r"\n\s*\n", hits[0]) if re.search(r"spec 119|ADR-065", e))
    assert "BREAKING" not in entry
    for needle in ("nats:2.14.9-alpine", "nats:2.15.2-alpine", "2.15.1", "0.35.0", "0.24.0", "1.5.0", "1.1.0"):
        assert needle in hits[0], needle


def plugin_versions(name):
    manifest = json.loads((ROOT / f"plugins/{name}/.claude-plugin/plugin.json").read_text())["version"]
    market = next(p["version"] for p in json.loads((ROOT / ".claude-plugin/marketplace.json").read_text())["plugins"] if p["name"] == name)
    return manifest, market


def test_the_resource_and_api_plugins_are_bumped_in_both_places_ac_119_4():  # AC-119.4
    assert plugin_versions("resource") == ("1.5.0", "1.5.0")
    assert plugin_versions("api") == ("1.1.0", "1.1.0")
    manifest = json.loads((ROOT / "plugins/resource/.claude-plugin/plugin.json").read_text())
    assert "brokers" in manifest["description"]
    desc = re.search(r'(?m)^description:\s*"(.*)"\s*$', (ROOT / "plugins/resource/commands/add.md").read_text()).group(1)
    assert len(desc) < 260 and "--type database|bucket|cache|broker" in desc and "--replicas" in desc
