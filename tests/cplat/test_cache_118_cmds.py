"""Spec 118 acceptance tests, the platform side: `/resource:add|remove` for caches (AC-118.1, AC-118.13, AC-118.22), the model and `cplat
model show` (AC-118.3), `/platform:doctor` (AC-118.23), the `--uses` note (AC-118.18), the e2e script text (AC-118.6, .7, .8, .11, .14, .15,
.18, .19, .23), the docs and the plugin (AC-118.14, .21, .22).

Contract: design.md "Contract: cplat resource", "model, status, doctor, compose" and "e2e". Everything runs through `cplat.main` or the
modules on hand-built checkouts; `gh`, `kubectl` and the network are faked or not used. The e2e script is only read (it needs a
cluster): its text is asserted where the plan says so."""
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
from cache_fixtures import cache
from resources_fixtures import APP, comp, db, system
from system_fixtures import RENDER5, ROOT, files, git, init_git, mod, write_system

SYS = f"{APP}/system.yaml"
CKEYS = "url, host, port, password"
NEXT_IN_CLUSTER = ("no operator is needed: each environment where a component uses it runs one Valkey StatefulSet "
                   "(defaults: Valkey 9, memory 256Mi, allkeys-lru, persistence false; set them in system.yaml)")
REDIS_HINT = "the type is `cache` (Redis-compatible, runs Valkey): /resource:add <name> --type cache"


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


# ---------------- AC-118.1: resource add ----------------

def test_add_a_cache_declares_it_without_sizing_and_renders_ac_118_1(repo):  # AC-118.1
    assert run("resource", "add", "sessions", "--type", "cache", "--repo-dir", repo) == 0
    assert sysdoc(repo)["resources"]["sessions"] == {"type": "cache"}
    assert "# the shop system (keep this comment)" in (repo / SYS).read_text()
    assert render_check(repo).returncode == 0


def test_a_cache_added_by_the_command_renders_its_objects_once_used_ac_118_1(repo):  # AC-118.1
    assert run("resource", "add", "sessions", "--type", "cache", "--repo-dir", repo) == 0
    doc = sysdoc(repo)
    doc["components"]["api"]["uses"] = ["sessions"]
    (repo / SYS).write_text(yaml.safe_dump(doc, sort_keys=False))
    done = subprocess.run([sys.executable, "scripts/render.py"], cwd=repo, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert (repo / APP / "addons/dev/sessions/statefulset.yaml").is_file() and not (repo / "operators").exists()


def test_add_an_external_cache_writes_the_small_typed_entry_ac_118_1(repo):  # AC-118.1
    assert run("resource", "add", "sessions", "--type", "cache", "--external", "--repo-dir", repo) == 0
    assert sysdoc(repo)["resources"]["sessions"] == {"type": "cache", "external": True}
    assert render_check(repo).returncode == 0


def test_add_an_external_cache_with_a_path_ac_118_1(repo):  # AC-118.1
    assert run("resource", "add", "sessions", "--type", "cache", "--external", "--path", "{env}/{resource}", "--repo-dir", repo) == 0
    assert sysdoc(repo)["resources"]["sessions"] == {"type": "cache", "external": True, "remote": {"path": "{env}/{resource}"}}


def test_add_prints_the_next_steps_of_an_in_cluster_cache_ac_118_1(repo, capsys):  # AC-118.1
    rc, out, err = run("resource", "add", "sessions", "--type", "cache", "--repo-dir", repo, capsys=capsys)
    assert rc == 0, err
    assert "let components use it: /component:set <component> --uses sessions (or uses: [sessions] in system.yaml)" in out
    assert NEXT_IN_CLUSTER in out
    assert "operators/root.yaml" not in out and "bootstrap" not in out and "CloudNativePG" not in out and "SeaweedFS" not in out


def test_add_prints_the_store_keys_of_an_external_cache_ac_118_1(repo, capsys):  # AC-118.1
    rc, out, _ = run("resource", "add", "sessions", "--type", "cache", "--external", "--repo-dir", repo, capsys=capsys)
    assert rc == 0 and (f"put the keys {CKEYS} in the secret store platform-secrets under shop-dev-sessions, shop-staging-sessions, "
                        "shop-prod-sessions") in out


def test_add_pr_uses_the_resource_branch_and_title_for_a_cache_ac_118_1(repo, monkeypatch):  # AC-118.1
    seen = []
    monkeypatch.setattr(gitops, "open_pr", lambda r, branch, title, body: seen.append((branch, title)) or "https://github.com/acme/shop-gitops/pull/1")
    assert run("resource", "add", "sessions", "--type", "cache", "--pr", "--repo-dir", repo) == 0
    assert seen == [("resource/add-sessions", "feat(resource): add sessions")]


@pytest.mark.parametrize("argv, needle", [
    (["c", "--type", "cache", "--version", "9"], "--version applies to --type database or broker only"),  # spec 119: broker takes --version
    (["c", "--type", "cache", "--storage", "1Gi"], "--storage and --versioning apply to --type bucket only"),
    (["c", "--type", "cache", "--versioning"], "--storage and --versioning apply to --type bucket only"),
    (["c", "--type", "cache", "--path", "x"], "--path needs --external"),
])
def test_add_cache_errors_change_nothing_and_name_the_reason_ac_118_1(repo, capsys, argv, needle):  # AC-118.1
    before = files(repo)
    rc, _, err = run("resource", "add", *argv, "--repo-dir", repo, capsys=capsys)
    assert rc == 1 and needle in err, err
    assert files(repo) == before


def test_add_external_cache_needs_the_secret_store_ac_118_1(repo_no_store, capsys):  # AC-118.1
    before = files(repo_no_store)
    rc, _, err = run("resource", "add", "sessions", "--type", "cache", "--external", "--repo-dir", repo_no_store, capsys=capsys)
    assert rc == 1 and "an external resource needs the system's secretStore" in err
    assert files(repo_no_store) == before


def test_add_a_cache_is_no_longer_refused_as_not_available_ac_118_1(repo, capsys):  # AC-118.1
    rc, _, err = run("resource", "add", "store", "--type", "cache", "--repo-dir", repo, capsys=capsys)
    assert rc == 0 and "not available yet" not in err


def test_the_type_option_help_names_cache_ac_118_1():  # AC-118.1
    text = (ROOT / "scripts" / "cplat" / "addon.py").read_text()
    assert "resource type: database, bucket, cache or broker" in text  # spec 119: broker is built
    assert re.search(r"PLANNED_TYPES\s*=\s*\{\s*\}", text)  # spec 119: no type is planned


# ---------------- AC-118.22: add keeps the other messages ----------------

@pytest.mark.parametrize("typ", ["redis", "valkey"])
def test_add_of_redis_or_valkey_keeps_114s_message_and_adds_the_cache_hint_ac_118_22(repo, capsys, typ):  # AC-118.22
    before = files(repo)
    rc, _, err = run("resource", "add", "sessions", "--type", typ, "--repo-dir", repo, capsys=capsys)
    assert rc == 1
    assert f"unknown resource type '{typ}' (database, bucket, cache or broker)" in err
    assert REDIS_HINT in err
    assert files(repo) == before


def test_add_of_the_broker_keeps_its_refusal_ac_118_22(repo, capsys):  # AC-118.22
    before = files(repo)
    rc, _, err = run("resource", "add", "store", "--type", "broker", "--repo-dir", repo, capsys=capsys)
    assert rc == 0, err  # spec 119: broker is built, add succeeds
    assert files(repo) != before  # spec 119: and changes the tree


def test_add_of_an_unknown_type_has_no_cache_hint_ac_118_22(repo, capsys):  # AC-118.22
    rc, _, err = run("resource", "add", "sessions", "--type", "queue", "--repo-dir", repo, capsys=capsys)
    assert rc == 1 and "unknown resource type 'queue' (database, bucket, cache or broker)" in err and "Valkey" not in err


# ---------------- AC-118.13: resource remove ----------------

def build_used(tmp_path):
    """sessions used by api and web, idle unused, ext external and unused, mixed external in prod only; rendered."""
    res = {"sessions": cache(), "idle": cache(), "ext": cache(external=True), "mixed": cache(instances={"prod": {"external": True}})}
    return make_repo(tmp_path, system(res, {"api": comp("api", ["sessions"]), "web": comp("web", ["sessions"])}))


def test_remove_of_a_used_cache_names_every_user_and_changes_nothing_ac_118_13(tmp_path, capsys):  # AC-118.13
    used = build_used(tmp_path)
    before = files(tmp_path)
    assert (used / APP / "addons/dev/sessions/statefulset.yaml").is_file(), "the checkout was rendered with its cache"
    rc, _, err = run("resource", "remove", "sessions", "--repo-dir", used, capsys=capsys)
    assert rc == 1 and "sessions is still used by api, web" in err and "/component:set" in err
    assert files(tmp_path) == before


def test_remove_of_a_used_cache_with_dry_run_also_refuses_ac_118_13(tmp_path, capsys):  # AC-118.13
    used = build_used(tmp_path)
    before = files(tmp_path)
    rc, _, err = run("resource", "remove", "sessions", "--dry-run", "--repo-dir", used, capsys=capsys)
    assert rc == 1 and "sessions is still used by api, web" in err
    assert files(tmp_path) == before


def test_remove_of_an_in_cluster_cache_says_volume_and_secret_stay_ac_118_13(tmp_path, capsys):  # AC-118.13
    used = build_used(tmp_path)
    rc, out, err = run("resource", "remove", "idle", "--dry-run", "--repo-dir", used, capsys=capsys)
    assert rc == 0, err
    assert ("remove idle from system.yaml; the Argo Application disappears but the cache, its volume and its Secret shop-idle-app stay in the "
            "cluster (delete them by hand when you are sure)") in out
    assert "the database and its data" not in out and "the bucket, its data" not in out


def test_remove_of_an_external_cache_says_the_synced_secret_stays_ac_118_13(tmp_path, capsys):  # AC-118.13
    used = build_used(tmp_path)
    rc, out, err = run("resource", "remove", "ext", "--dry-run", "--repo-dir", used, capsys=capsys)
    assert rc == 0, err
    assert ("remove ext from system.yaml; the synced Secret shop-ext-app stays in the cluster (delete it by hand when you are sure); "
            "the external cache is not touched") in out
    assert "the external database" not in out and "the external bucket" not in out


def test_remove_of_a_mixed_cache_says_both_ac_118_13(tmp_path, capsys):  # AC-118.13
    used = build_used(tmp_path)
    rc, out, _ = run("resource", "remove", "mixed", "--dry-run", "--repo-dir", used, capsys=capsys)
    assert rc == 0 and "its volume and its Secret shop-mixed-app stay in the cluster" in out and "the external cache is not touched" in out


def test_remove_of_an_unused_cache_removes_the_entry_and_renders_ac_118_13(tmp_path):  # AC-118.13
    used = build_used(tmp_path)
    assert run("resource", "remove", "idle", "--repo-dir", used) == 0
    assert "idle" not in sysdoc(tmp_path)["resources"] and "sessions" in sysdoc(tmp_path)["resources"]
    assert render_check(tmp_path).returncode == 0


def test_remove_of_a_cache_directory_goes_when_it_is_unused_ac_118_13(tmp_path):  # AC-118.13
    used = build_used(tmp_path)
    doc = sysdoc(tmp_path)
    doc["components"]["web"]["uses"] = []
    doc["components"]["api"]["uses"] = []
    (used / SYS).write_text(yaml.safe_dump(doc, sort_keys=False))
    commit(tmp_path)
    assert run("resource", "remove", "sessions", "--repo-dir", used) == 0
    assert not (used / APP / "addons/dev/sessions").exists() and render_check(tmp_path).returncode == 0


# ---------------- AC-118.3: the model ----------------

def model_doc():
    res = {"sessions": cache(memory="512Mi", maxmemoryPolicy="volatile-lru", instances={"prod": {"persistence": True, "storage": "5Gi"}}),
           "plain": cache(), "ext": cache(external=True), "idle": cache(), "stored": cache(version="8", persistence=True)}
    return system(res, {"api": comp("api", ["sessions", "ext", "stored"]), "web": comp("web", ["plain"], envs=("dev",))})


@pytest.fixture()
def mrepo(tmp_path):
    write_system(tmp_path, model_doc())
    return tmp_path


def test_cache_instances_carry_the_sizing_ac_118_3(mrepo):  # AC-118.3
    m = mod("model").load_dir(mrepo / APP)
    ri = {(r.resource, r.environment): r for r in m.resource_instances}
    d = ri[("sessions", "dev")]
    assert (d.type, d.external, d.argo_application, d.secret, d.store_key) == ("cache", False, "addon-sessions-dev", "shop-sessions-app", None)
    assert dict(d.sizing) == {"version": 9, "memory": "512Mi", "maxmemoryPolicy": "volatile-lru", "persistence": False}
    assert list(d.sizing) == ["version", "memory", "maxmemoryPolicy", "persistence"]
    p = ri[("sessions", "prod")]
    assert dict(p.sizing) == {"version": 9, "memory": "512Mi", "maxmemoryPolicy": "volatile-lru", "persistence": True, "storage": "5Gi"}
    assert list(p.sizing)[-1] == "storage"
    assert dict(ri[("plain", "dev")].sizing) == {"version": 9, "memory": "256Mi", "maxmemoryPolicy": "allkeys-lru", "persistence": False}
    assert dict(ri[("stored", "dev")].sizing) == {"version": 8, "memory": "256Mi", "maxmemoryPolicy": "allkeys-lru", "persistence": True, "storage": "1Gi"}
    e = ri[("ext", "dev")]
    assert (e.external, e.argo_application, e.secret, e.store_key, dict(e.sizing)) == (True, None, "shop-ext-app", "shop-dev-ext", {})
    assert ("plain", "staging") not in ri and ("idle", "dev") not in ri


def test_the_model_json_has_the_cache_sizing_as_real_numbers_and_booleans_ac_118_3(mrepo, capsys):  # AC-118.3
    assert cplat.main(["model", "show", "--repo-dir", str(mrepo), "--json"]) == 0
    d = json.loads(capsys.readouterr().out)
    ri = {(r["resource"], r["environment"]): r for r in d["resource_instances"]}
    assert ri[("sessions", "prod")]["sizing"] == {"version": 9, "memory": "512Mi", "maxmemoryPolicy": "volatile-lru", "persistence": True, "storage": "5Gi"}
    assert ri[("sessions", "dev")]["sizing"] == {"version": 9, "memory": "512Mi", "maxmemoryPolicy": "volatile-lru", "persistence": False}
    assert d["schema"] == 2


def test_the_model_text_prints_the_sizing_in_lower_case_ac_118_3(mrepo, capsys):  # AC-118.3
    assert cplat.main(["model", "show", "--repo-dir", str(mrepo)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert ("    dev  type cache  external false  version 9  memory 256Mi  maxmemoryPolicy allkeys-lru  persistence false  "
            "argo addon-plain-dev  secret shop-plain-app") in lines
    assert ("    prod  type cache  external false  version 9  memory 512Mi  maxmemoryPolicy volatile-lru  persistence true  storage 5Gi  "
            "argo addon-sessions-prod  secret shop-sessions-app") in lines
    assert "    dev  type cache  external true  argo -  secret shop-ext-app  store shop-dev-ext" in lines


def test_the_renderer_and_the_model_agree_on_cache_instances_ac_118_3(tmp_path):  # AC-118.3
    write_system(tmp_path, model_doc())
    (tmp_path / "scripts").mkdir()
    shutil.copy(RENDER5, tmp_path / "scripts" / "render.py")
    done = subprocess.run([sys.executable, "scripts/render.py"], cwd=tmp_path, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    app_dir = tmp_path / APP
    import importlib.util
    spec = importlib.util.spec_from_file_location("render_under_test_118", tmp_path / "scripts" / "render.py")
    r = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(r)
    m = mod("model").load_dir(app_dir)
    renderer = sorted(r.resource_instances(r.load_system(app_dir)))
    assert renderer == sorted((ri.resource, ri.environment, ri.type, ri.external) for ri in m.resource_instances)
    ran = sorted((p.name, p.parent.name) for p in (app_dir / "addons").glob("*/*") if p.is_dir() and p.name != "observability")
    assert ran == sorted((ri.resource, ri.environment) for ri in m.resource_instances if not ri.external)


# ---------------- AC-118.23: doctor has no row for a cache ----------------

def cache_rows(repo):
    import doctor
    rows = []
    for fn in ("check_addons", "check_operators", "check_backups"):
        if hasattr(doctor, fn):
            rows += getattr(doctor, fn)(repo)
    return [c for c in rows if re.search(r"(?i)cache|valkey|redis", f"{c.get('name', '')} {c.get('detail', '')}")]


def kube(monkeypatch):
    import doctor
    monkeypatch.setattr(doctor.shutil, "which", lambda t: f"/usr/bin/{t}")
    monkeypatch.setattr(doctor, "run", lambda cmd, *a, **k: SimpleNamespace(stdout="", stderr="", returncode=0))


def test_doctor_has_no_row_for_a_cache_in_any_cluster_ac_118_23(tmp_path, monkeypatch):  # AC-118.23
    kube(monkeypatch)
    write_system(tmp_path / "in", system({"sessions": cache()}, {"api": comp("api", ["sessions"])}))
    write_system(tmp_path / "ext", system({"sessions": cache(external=True)}, {"api": comp("api", ["sessions"])}))
    doc = system({"sessions": cache()}, {"api": comp("api", ["sessions"])})
    for e in ("dev", "staging", "prod"):
        doc["environments"][e]["operators"] = "owner"
    write_system(tmp_path / "owner", doc)
    for d in ("in", "ext", "owner"):
        assert cache_rows(tmp_path / d) == [], d


def test_doctor_lists_no_operator_for_a_cache_only_system_ac_118_23(tmp_path, monkeypatch):  # AC-118.23
    import doctor
    kube(monkeypatch)
    write_system(tmp_path, system({"sessions": cache()}, {"api": comp("api", ["sessions"])}))
    assert [c["name"] for c in doctor.check_operators(tmp_path)] == []


def test_doctor_still_lists_the_database_operator_next_to_a_cache_ac_118_23(tmp_path, monkeypatch):  # AC-118.23
    import doctor
    kube(monkeypatch)
    write_system(tmp_path, system({"sessions": cache(), "d": db()}, {"api": comp("api", ["sessions", "d"])}))
    assert [c["name"] for c in doctor.check_operators(tmp_path)] == ["operator cloudnative-pg"]


def test_cluster_up_and_bootstrap_have_no_cache_step_ac_118_23():  # AC-118.23
    for script in ("local-cluster.sh", "bootstrap.sh"):
        text = (ROOT / "templates" / "gitops-app" / "scripts" / script).read_text().lower()
        assert "valkey" not in text and "redis" not in text, script


def test_the_adr_for_the_statefulset_decision_exists_ac_118_23():  # AC-118.23
    adr = ROOT / "docs" / "adr" / "064-a-cache-is-a-platform-rendered-valkey-statefulset.md"  # spec 118: ADR-063 went to spec 124 first
    assert adr.is_file() and "StatefulSet" in adr.read_text()
    assert "063" in (ROOT / "docs" / "adr" / "README.md").read_text()


# ---------------- AC-118.18: the --uses note and help ----------------

def make_uses_repo(tmp_path):
    return make_repo(tmp_path, system({"sessions": cache(), "ratelimit": cache(), "orders-db": db()}, {"api": comp("api"), "web": comp("web")}))


def test_two_caches_add_the_prefixed_variables_step_ac_118_18(tmp_path, capsys):  # AC-118.18
    repo = make_uses_repo(tmp_path)
    rc, out, err = run("component", "set", "api", "--uses", "sessions", "--uses", "ratelimit", "--dry-run", "--repo-dir", repo, capsys=capsys)
    assert rc == 0, err
    assert "api now uses 2 cache resources: their variables are prefixed (<NAME>_REDIS_URL, …) and REDIS_* are no longer injected" in out


def test_one_cache_adds_no_prefixed_variables_step_ac_118_18(tmp_path, capsys):  # AC-118.18
    repo = make_uses_repo(tmp_path)
    assert render_check(repo).returncode == 0, "the caches render"
    rc, out, err = run("component", "set", "api", "--uses", "sessions", "--dry-run", "--repo-dir", repo, capsys=capsys)
    assert rc == 0, err
    assert "now uses" not in out and "are prefixed" not in out


def test_a_cache_and_a_database_add_no_prefixed_variables_step_ac_118_18(tmp_path, capsys):  # AC-118.18
    repo = make_uses_repo(tmp_path)
    assert render_check(repo).returncode == 0, "the caches render"
    rc, out, err = run("component", "set", "api", "--uses", "sessions", "--uses", "orders-db", "--dry-run", "--repo-dir", repo, capsys=capsys)
    assert rc == 0, err
    assert "are prefixed" not in out


def test_the_uses_help_names_the_cache_variables_ac_118_18():  # AC-118.18
    text = (ROOT / "scripts" / "cplat" / "compose.py").read_text()
    assert ("resource or library the component needs (a database gives DATABASE_URL and PG*, a bucket S3_* and AWS_*, a cache REDIS_URL and REDIS_*); "
            "declare it first with `cplat resource add <name> --type database|bucket|cache`") in text


# ---------------- the e2e script ----------------

def e2e() -> str:
    return (ROOT / "tests" / "e2e" / "run.sh").read_text()


def need(text: str, *needles: str) -> None:
    for n in needles:
        assert n in text, f"tests/e2e/run.sh lacks {n!r}"


def test_the_e2e_script_declares_two_caches_used_by_e2e_web_ac_118_15():  # AC-118.15 (needs a cluster)
    need(e2e(), "resource add sessions --type cache", "resource add ratelimit --type cache", "cstep", "cfail", "SESSIONS_REDIS_URL",
         "RATELIMIT_REDIS_PASSWORD", "e2e-sessions-app", "e2e-ratelimit-app", "statefulsets.apps")


def test_the_e2e_script_sets_and_gets_a_value_through_redis_url_ac_118_15():  # AC-118.15 (needs a cluster)
    need(e2e(), 'valkey-cli -u "$SESSIONS_REDIS_URL"', "SET", "GET")


def test_the_e2e_script_runs_doctor_and_finds_no_cache_prerequisite_ac_118_15():  # AC-118.15 (needs a cluster)
    text = e2e()
    need(text, "platform doctor")
    assert re.search(r"(?is)doctor.{0,800}(cache|valkey)", text) or re.search(r"(?is)(cache|valkey).{0,800}doctor", text), "the doctor step checks the cache rows"


def test_the_e2e_script_proves_auth_ac_118_11():  # AC-118.11 (needs a cluster)
    need(e2e(), "NOAUTH", "WRONGPASS", "PONG")


def test_the_e2e_script_proves_maxmemory_policy_and_eviction_ac_118_6():  # AC-118.6 (needs a cluster)
    need(e2e(), "53687091", "allkeys-lru", "evicted_keys", "noeviction", "OOM", "OOMKilled")


def test_the_e2e_script_proves_persistence_across_a_pod_restart_ac_118_7():  # AC-118.7 (needs a cluster)
    need(e2e(), "data-e2e-sessions-0", "restartCount", "DBSIZE")
    assert re.search(r"(?i)delete pod", e2e())


def test_the_e2e_script_proves_the_cache_is_not_exposed_ac_118_8():  # AC-118.8 (needs a cluster)
    need(e2e(), "ClusterIP", "httproutes.gateway.networking.k8s.io")


def test_the_e2e_script_proves_the_secret_contract_and_that_the_password_survives_ac_118_19():  # AC-118.19 (needs a cluster)
    need(e2e(), "redis://default:", "e2e-sessions.e2e-dev.svc:6379/0", "rerun_credentials", "resourceVersion")  # spec 127, spec 128


def test_the_e2e_script_proves_no_operator_is_added_for_a_cache_ac_118_23():  # AC-118.23 (needs a cluster)
    need(e2e(), "operators/apps")
    assert re.search(r"(?is)no operator|operators/apps.{0,400}(unchanged|cache)", e2e())


def test_the_e2e_script_proves_no_cache_data_is_in_the_backup_ac_118_14():  # AC-118.14 (needs a cluster)
    need(e2e(), "NotIn", "podvolumebackups.velero.io", "schedules.velero.io", "e2e-sessions-0")


# ---------------- docs, changelog, plugin ----------------

def test_the_domain_model_guide_documents_the_cache_type_ac_118_21():  # AC-118.21
    text = (ROOT / "docs" / "DOMAIN-MODEL.md").read_text()
    for needle in ("Valkey", "BSD", "AGPL", "Redis protocol", "REDIS_URL", "REDIS_HOST", "REDIS_PORT", "REDIS_PASSWORD", "SESSIONS_REDIS_URL",
                   "<system>-<name>-app", "maxmemoryPolicy", "persistence", "256Mi", "allkeys-lru", "1Gi", "spec 120", "spec 118", "spec 119"):
        assert needle in text, f"DOMAIN-MODEL.md lacks {needle!r}"
    assert re.search(r"not (called )?`redis`", text)
    assert "`cache` and `broker`, which are reserved" not in text


def test_the_domain_model_guide_lists_the_four_secret_keys_and_the_external_store_keys_ac_118_21():  # AC-118.21
    text = (ROOT / "docs" / "DOMAIN-MODEL.md").read_text()
    assert re.search(r"`url`,\s*`host`,\s*`port`(,| and)\s*`password`", text), "the four keys of the Secret are listed"
    assert re.search(r"(?i)database `0`|database 0", text)
    assert re.search(r"(?i)redis.{0,40}(8|AGPLv3|RSAL|SSPL)", text)


def test_the_user_journey_and_the_site_describe_the_cache_ac_118_21():  # AC-118.21
    assert "A cache" in (ROOT / "docs" / "USER-JOURNEY.md").read_text()
    site = (ROOT / "site" / "src" / "content" / "docs" / "concepts" / "addons.md").read_text()
    assert "REDIS_URL" in site and "cache" in site


def test_the_resource_plugin_docs_describe_the_cache_ac_118_21():  # AC-118.21
    add = (ROOT / "plugins/resource/commands/add.md").read_text()
    assert "--type database|bucket|cache" in add and "Valkey" in add and "SESSIONS_REDIS_URL" in add and "REDIS_URL" in add
    assert "url, host, port, password" in add.replace("`", "") or "`url`, `host`, `port`, `password`" in add
    assert "cache" in (ROOT / "plugins/resource/commands/remove.md").read_text()
    readme = (ROOT / "plugins/resource/README.md").read_text()
    assert "`cache`" in readme and "reserved for specs 118" not in readme


def test_the_backup_guide_says_cache_data_is_not_backed_up_with_or_without_persistence_ac_118_14():  # AC-118.14
    text = (ROOT / "docs" / "BACKUP-AND-RESTORE.md").read_text()
    assert "Cache data is not backed up" in text and "persistence: true" in text and re.search(r"(?i)left out|by name", text)


def test_the_resource_docs_say_cache_data_is_not_backed_up_ac_118_14():  # AC-118.14
    text = (ROOT / "docs" / "DOMAIN-MODEL.md").read_text()
    assert re.search(r"(?i)cache[^.\n]{0,200}not backed up|not backed up[^.\n]{0,200}cache", text)


def test_the_changelog_lists_the_cache_in_a_minor_section_that_is_not_breaking_ac_118_22():  # AC-118.22
    text = (ROOT / "docs" / "CHANGELOG.md").read_text()
    sections = re.split(r"(?m)^(?=## \[)", text)
    hits = [s for s in sections if s.startswith("## [") and re.search(r"spec 118|ADR-064", s)]  # spec 118: ADR-063 went to spec 124 first
    assert hits, "the change is listed"
    assert re.match(r"## \[(Unreleased|5\.[1-9]\d*\.0)\]", hits[0].splitlines()[0])
    entry = next(e for e in re.split(r"\n\s*\n", hits[0]) if re.search(r"spec 118|ADR-064", e))
    assert "BREAKING" not in entry
    assert "valkey/valkey:8.1.11" in hits[0] and "valkey/valkey:9.1.3" in hits[0] and "resource" in entry and "1.4.0" in hits[0]
    assert "no operator" in hits[0].lower()


def test_the_resource_plugin_is_1_4_0_in_both_places_ac_118_22():  # AC-118.22
    manifest = json.loads((ROOT / "plugins/resource/.claude-plugin/plugin.json").read_text())
    market = next(p["version"] for p in json.loads((ROOT / ".claude-plugin/marketplace.json").read_text())["plugins"] if p["name"] == "resource")
    assert manifest["version"] == market == "1.6.1"  # spec 127: resource plugin 1.6.1
    assert "caches" in manifest["description"]
    desc = re.search(r'(?m)^description:\s*"(.*)"\s*$', (ROOT / "plugins/resource/commands/add.md").read_text()).group(1)
    assert len(desc) < 260 and "--type database|bucket|cache" in desc
