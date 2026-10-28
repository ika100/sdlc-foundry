"""Spec 115 acceptance tests, the platform side: `/resource:add|remove`, the model and `cplat model show`, `/platform:doctor`, the
migration proof and the docs (AC-115.2 add part, AC-115.6 migration, AC-115.13 .. AC-115.16, AC-115.18 doctor).

Contract: design.md "Contract: cplat resource", "the model", "/platform:doctor" and "migration proof". Everything runs through `cplat.main`
or the modules on hand-built checkouts; `gh`, `kubectl` and the network are faked or not used."""
import contextlib
import io
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import cplat
import gitops
from resources_fixtures import (APP, ENVS, KEYS, PIN_RE, comp, db, normalized, platform_render_module, system, tree, unpin)
from system_fixtures import (FULL5, RENDER5, ROOT, build_old_gitops, files, generated, git, init_git, load, mod, write_system)

SYS = f"{APP}/system.yaml"
TYPES_LINE = "(database, bucket, cache or broker)"


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
    write_system(tmp_path, "# the shop system (keep this comment)\n" + yaml.safe_dump(doc, sort_keys=False))
    (tmp_path / "scripts").mkdir()
    shutil.copy(RENDER5, tmp_path / "scripts" / "render.py")
    (tmp_path / ".copier-answers.yml").write_text("github_org: acme\napp_name: shop\nproject_name: shop-gitops\n")
    done = subprocess.run([sys.executable, "scripts/render.py"], cwd=tmp_path, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return init_git(tmp_path)


@pytest.fixture()
def repo(tmp_path):
    return make_repo(tmp_path, system(None, {"api": comp("api"), "web": comp("web")}))


@pytest.fixture()
def repo_no_store(tmp_path):
    return make_repo(tmp_path, system(None, {"api": comp("api")}, store=False))


# ---------------- AC-115.13 / AC-115.2: resource add ----------------

def test_add_a_named_database_declares_and_renders_ac_115_13(repo):  # AC-115.13
    assert run("resource", "add", "orders-db", "--type", "database", "--repo-dir", repo) == 0
    assert sysdoc(repo)["resources"]["orders-db"] == {"type": "database", "version": 17, "replicas": 1, "storage": "1Gi",
                                                      "instances": {"prod": {"replicas": 3, "storage": "20Gi"}}}
    assert "# the shop system (keep this comment)" in (repo / SYS).read_text()
    assert render_check(repo).returncode == 0


def test_add_takes_a_version_ac_115_13(repo):  # AC-115.13
    assert run("resource", "add", "orders-db", "--type", "database", "--version", "16", "--repo-dir", repo) == 0
    assert sysdoc(repo)["resources"]["orders-db"]["version"] == 16


def test_add_an_external_database_writes_the_small_entry_ac_115_13(repo):  # AC-115.13
    assert run("resource", "add", "ext", "--type", "database", "--external", "--repo-dir", repo) == 0
    assert sysdoc(repo)["resources"]["ext"] == {"type": "database", "external": True}


def test_add_an_external_database_with_a_path_ac_115_13(repo):  # AC-115.13
    assert run("resource", "add", "ext", "--type", "database", "--external", "--path", "prod/{resource}", "--repo-dir", repo) == 0
    assert sysdoc(repo)["resources"]["ext"] == {"type": "database", "external": True, "remote": {"path": "prod/{resource}"}}


def test_add_postgres_without_type_still_adds_a_database_ac_115_13(repo):  # AC-115.13
    assert run("resource", "add", "postgres", "--repo-dir", repo) == 0
    assert sysdoc(repo)["resources"]["postgres"] == {"type": "database", "version": 17, "replicas": 1, "storage": "1Gi",
                                                     "instances": {"prod": {"replicas": 3, "storage": "20Gi"}}}


def test_add_prints_the_next_steps_ac_115_13(repo, capsys):  # AC-115.13
    rc, out, err = run("resource", "add", "orders-db", "--type", "database", "--repo-dir", repo, capsys=capsys)
    assert rc == 0, err
    assert "let components use it: /component:set <component> --uses orders-db (or uses: [orders-db] in system.yaml)" in out
    assert "operators/root.yaml" in out and "devbox run bootstrap" in out and "operators: owner" in out
    commit(repo)
    rc, out, _ = run("resource", "add", "ext", "--type", "database", "--external", "--repo-dir", repo, capsys=capsys)
    assert rc == 0 and "put the keys uri, host, port, dbname, user, password in the secret store platform-secrets" in out


def test_add_pr_uses_the_resource_branch_and_title_ac_115_13(repo, monkeypatch):  # AC-115.13
    seen = []
    monkeypatch.setattr(gitops, "open_pr", lambda r, branch, title, body: seen.append((branch, title)) or "https://github.com/acme/shop-gitops/pull/1")
    assert run("resource", "add", "orders-db", "--type", "database", "--pr", "--repo-dir", repo) == 0
    assert seen == [("resource/add-orders-db", "feat(resource): add orders-db")]


NAME_RULE = "must start with a lowercase letter and contain only lowercase letters, digits and hyphens (at most 30 characters)"


@pytest.mark.parametrize("argv, needle", [
    (["redis"], f"--type is required for redis {TYPES_LINE}"),
    (["redis", "--type", "queue"], f"unknown resource type 'queue' {TYPES_LINE}"),
    (["Bad_Name", "--type", "database"], f"resource name 'Bad_Name' {NAME_RULE}"),
    (["a" * 31, "--type", "database"], f"resource name '{'a' * 31}' {NAME_RULE}"),
    (["api", "--type", "database"], "api is a component of the system; a resource needs a name of its own"),
    (["d", "--type", "database", "--path", "x"], "--path needs --external"),
    (["d", "--type", "database", "--external", "--version", "16"], "an external resource runs nothing: --version does not apply"),
    (["d", "--type", "database", "--version", "14"], "version '14' is not a supported database version (15, 16, 17, 18)"),
    (["observability", "--type", "database"], "observability is set per environment under environments.<env>.observability in system.yaml"),
])
def test_add_errors_change_nothing_and_name_the_reason_ac_115_13(repo, capsys, argv, needle):  # AC-115.13
    before = files(repo)
    rc, _, err = run("resource", "add", *argv, "--repo-dir", repo, capsys=capsys)
    assert rc == 1 and needle in err, err
    assert files(repo) == before


@pytest.mark.parametrize("typ, spec", [])  # spec 119: broker is built, no type is planned (pytest skips the empty set)
def test_add_of_a_type_that_is_not_built_yet_names_the_spec_ac_115_2(repo, capsys, typ, spec):  # AC-115.2
    before = files(repo)
    rc, _, err = run("resource", "add", "store", "--type", typ, "--repo-dir", repo, capsys=capsys)
    assert rc == 1 and f"resource type {typ} is not available yet: spec {spec} brings it" in err
    assert files(repo) == before


def test_add_of_an_existing_name_changes_nothing_ac_115_13(repo, capsys):  # AC-115.13
    assert run("resource", "add", "orders-db", "--type", "database", "--repo-dir", repo) == 0
    commit(repo)
    before = files(repo)
    rc, _, err = run("resource", "add", "orders-db", "--type", "database", "--repo-dir", repo, capsys=capsys)
    assert rc == 1 and "orders-db is already declared" in err and files(repo) == before


def test_add_external_needs_the_secret_store_ac_115_13(repo_no_store, capsys):  # AC-115.13
    before = files(repo_no_store)
    rc, _, err = run("resource", "add", "ext", "--type", "database", "--external", "--repo-dir", repo_no_store, capsys=capsys)
    assert rc == 1 and "an external resource needs the system's secretStore" in err
    assert files(repo_no_store) == before


# ---------------- AC-115.14: resource remove ----------------

def build_used(tmp_path):
    """orders-db used by api and web, users-db used by web only, idle-db used by nobody; rendered."""
    res = {"orders-db": db(), "users-db": db(), "idle-db": db()}
    return make_repo(tmp_path, system(res, {"api": comp("api", ["orders-db"]), "web": comp("web", ["orders-db", "users-db"])}))


def test_remove_of_a_used_resource_names_every_user_and_changes_nothing_ac_115_14(tmp_path, capsys):  # AC-115.14
    used = build_used(tmp_path)
    before = files(tmp_path)
    rc, _, err = run("resource", "remove", "orders-db", "--repo-dir", used, capsys=capsys)
    assert rc == 1 and "orders-db is still used by api, web" in err and "/component:set" in err
    assert files(tmp_path) == before


def test_remove_of_an_unused_resource_removes_the_entry_and_its_instances_ac_115_14(tmp_path):  # AC-115.14
    used = build_used(tmp_path)
    doc = sysdoc(tmp_path)
    doc["components"]["web"]["uses"] = ["orders-db"]          # users-db was rendered, nobody uses it any more
    (used / SYS).write_text(yaml.safe_dump(doc, sort_keys=False))
    commit(tmp_path)
    assert (used / APP / "addons/dev/users-db/cluster.yaml").is_file()
    assert run("resource", "remove", "users-db", "--repo-dir", used) == 0
    assert "users-db" not in sysdoc(tmp_path)["resources"] and "orders-db" in sysdoc(tmp_path)["resources"]
    assert not (used / APP / "addons/dev/users-db").exists() and (used / APP / "addons/dev/orders-db/cluster.yaml").is_file()
    assert render_check(tmp_path).returncode == 0


def test_remove_of_the_last_resource_drops_the_empty_key_ac_115_14(tmp_path):  # AC-115.14
    repo = make_repo(tmp_path, system({"idle-db": db()}))
    assert run("resource", "remove", "idle-db", "--repo-dir", repo) == 0
    assert not (sysdoc(repo).get("resources"))


def test_remove_of_an_unknown_name_lists_the_resources_ac_115_14(tmp_path, capsys):  # AC-115.14
    used = build_used(tmp_path)
    before = files(tmp_path)
    rc, _, err = run("resource", "remove", "nope", "--repo-dir", used, capsys=capsys)
    assert rc == 1 and "nope is not a resource of the system (resources: orders-db, users-db, idle-db)" in err
    assert files(tmp_path) == before


def test_remove_pr_uses_the_resource_branch_ac_115_14(tmp_path, monkeypatch):  # AC-115.14
    used = build_used(tmp_path)
    seen = []
    monkeypatch.setattr(gitops, "open_pr", lambda r, branch, title, body: seen.append(branch) or "https://github.com/acme/shop-gitops/pull/1")
    assert run("resource", "remove", "idle-db", "--pr", "--repo-dir", used) == 0
    assert seen == ["resource/remove-idle-db"]


# ---------------- AC-115.15: the model ----------------

def model_doc():
    doc = system({"orders-db": db(instances={"prod": {"external": True}}), "ext": db(external=True, remote={"path": "{env}/{resource}"}), "idle-db": db()},
                 {"api": comp("api", ["orders-db", "ext"]), "web": comp("web", ["orders-db"], envs=("dev",))})
    doc["environments"]["dev"]["operators"] = "owner"
    return doc


@pytest.fixture()
def mrepo(tmp_path):
    write_system(tmp_path, model_doc())
    return tmp_path


def test_resources_carry_type_and_the_external_flag_ac_115_15(mrepo):  # AC-115.15
    m = mod("model").load_dir(mrepo / APP)
    got = {r.name: (r.type, r.external) for r in m.resources}
    assert got == {"orders-db": ("database", False), "ext": ("database", True), "idle-db": ("database", False)}


def test_resource_instances_carry_type_external_secret_application_and_store_key_ac_115_15(mrepo):  # AC-115.15
    m = mod("model").load_dir(mrepo / APP)
    ri = {(r.resource, r.environment): r for r in m.resource_instances}
    assert sorted(ri) == [("ext", "dev"), ("ext", "prod"), ("ext", "staging"), ("orders-db", "dev"), ("orders-db", "prod"), ("orders-db", "staging")]
    d = ri[("orders-db", "dev")]
    assert (d.type, d.external, d.argo_application, d.secret, d.store_key) == ("database", False, "addon-orders-db-dev", "shop-orders-db-app", None)
    assert dict(d.sizing) == {"replicas": 1, "version": 17, "storage": "1Gi"}
    p = ri[("orders-db", "prod")]
    assert (p.type, p.external, p.argo_application, p.secret, p.store_key) == ("database", True, None, "shop-orders-db-app", "shop-prod-orders-db")
    assert dict(p.sizing) == {}
    e = ri[("ext", "staging")]
    assert (e.external, e.argo_application, e.secret, e.store_key) == (True, None, "shop-ext-app", "staging/ext")


def test_the_environment_carries_operators_ac_115_15(mrepo):  # AC-115.15
    m = mod("model").load_dir(mrepo / APP)
    assert [e.operators for e in m.environments] == ["owner", None, None]


def test_the_json_keeps_schema_2_and_adds_the_fields_ac_115_15(mrepo, capsys):  # AC-115.15
    rc = cplat.main(["model", "show", "--repo-dir", str(mrepo), "--json"])
    d = json.loads(capsys.readouterr().out)
    assert rc == 0 and d["schema"] == 2
    res = {r["name"]: r for r in d["resources"]}
    assert res["orders-db"] == {"name": "orders-db", "type": "database", "external": False, "used_by": ["api", "web"]}
    assert res["ext"]["external"] is True and res["ext"]["used_by"] == ["api"] and res["idle-db"]["used_by"] == []
    ri = {(r["resource"], r["environment"]): r for r in d["resource_instances"]}
    assert ri[("orders-db", "prod")] == {"resource": "orders-db", "environment": "prod", "type": "database", "external": True, "argo_application": None,
                                         "secret": "shop-orders-db-app", "store_key": "shop-prod-orders-db", "sizing": {}, "backup": None}  # spec 117: backup field
    assert ri[("orders-db", "dev")]["argo_application"] == "addon-orders-db-dev" and ri[("orders-db", "dev")]["external"] is False
    assert {e["name"]: e.get("operators") for e in d["environments"]} == {"dev": "owner", "staging": None, "prod": None}


def test_the_text_lists_resources_and_instances_ac_115_15(mrepo, capsys):  # AC-115.15
    assert cplat.main(["model", "show", "--repo-dir", str(mrepo)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert "  orders-db  type database  external false  used by api,web" in lines
    assert "  ext  type database  external true  used by api" in lines
    assert "    dev  type database  external false  replicas 1  version 17  storage 1Gi  argo addon-orders-db-dev  secret shop-orders-db-app" in lines
    assert "    prod  type database  external true  argo -  secret shop-orders-db-app  store shop-prod-orders-db" in lines
    assert "    staging  type database  external true  argo -  secret shop-ext-app  store staging/ext" in lines
    env = {ln.split()[0]: ln for ln in lines if ln.startswith("  dev  host") or ln.startswith("  staging  host") or ln.startswith("  prod  host")}
    assert env["dev"].endswith("  operators owner") and "operators" not in env["staging"] and "operators" not in env["prod"]


def test_the_renderer_and_the_model_agree_on_resource_instances_ac_115_15(tmp_path):  # AC-115.15  (AC-114.70 check extended)
    from resources_fixtures import ok
    ok(tmp_path, model_doc())
    app_dir = tmp_path / APP
    import importlib.util
    spec = importlib.util.spec_from_file_location("render_under_test_115", tmp_path / "scripts" / "render.py")
    r = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(r)
    m = mod("model").load_dir(app_dir)
    loaded = r.load_system(app_dir)
    res = loaded["cfg"]["resources"]
    assert {n: (v["type"], v["external"]) for n, v in res.items()} == {n: (x.type, x.external) for n, x in ((x.name, x) for x in m.resources)}
    assert res["orders-db"]["envs"]["prod"]["external"] is True and res["orders-db"]["envs"]["dev"]["external"] is False
    renderer = sorted(r.resource_instances(loaded))
    modelled = sorted((ri.resource, ri.environment, ri.type, ri.external) for ri in m.resource_instances)
    assert renderer == modelled
    ran = sorted(p.relative_to(app_dir / "addons").parts[:2] for p in (app_dir / "addons").glob("*/*") if p.is_dir() and p.name != "observability")
    assert sorted((n, e) for e, n in ran) == sorted((ri.resource, ri.environment) for ri in m.resource_instances if not ri.external)


# ---------------- AC-115.18: doctor ----------------

def operator_rows(repo):
    import doctor
    rows = []
    for fn in ("check_addons", "check_operators"):
        if hasattr(doctor, fn):
            rows += getattr(doctor, fn)(repo)
    return [c for c in rows if c["name"] == "operator cloudnative-pg"]


def kube(monkeypatch, installed: str | None, kubectl: bool = True):
    import doctor
    monkeypatch.setattr(doctor.shutil, "which", lambda t: f"/usr/bin/{t}" if kubectl else None)
    calls = []

    def fake_run(cmd, *a, **k):
        calls.append(cmd)
        out = "" if installed is None else f"ghcr.io/cloudnative-pg/cloudnative-pg:{installed}@sha256:{'a' * 64}"
        return SimpleNamespace(stdout=out, stderr="", returncode=0)
    monkeypatch.setattr(doctor, "run", fake_run)
    return calls


def op_repo(tmp_path, owner=()):
    doc = system({"orders-db": db()}, {"api": comp("api", ["orders-db"])})
    for e in owner:
        doc["environments"][e]["operators"] = "owner"
    write_system(tmp_path, doc)
    return tmp_path


def expected():
    op = getattr(platform_render_module("render_115_doctor"), "OPERATORS", None)
    assert op is not None, "render.py has OPERATORS"
    return op["cloudnative-pg"]


def test_doctor_is_ok_when_the_platform_managed_operator_matches_ac_115_18(tmp_path, monkeypatch):  # AC-115.18
    op = expected()
    calls = kube(monkeypatch, op["operator_version"])
    [row] = operator_rows(op_repo(tmp_path))
    assert row["status"] == "ok"
    assert row["detail"] == f"installed {op['operator_version']}, expected {op['operator_version']} (Argo CD application operator-cloudnative-pg)"
    assert any("cloudnative-pg" in " ".join(c) and "deploy" in c for c in calls)


def test_doctor_warns_when_the_platform_managed_operator_is_missing_ac_115_18(tmp_path, monkeypatch):  # AC-115.18
    op = expected()
    kube(monkeypatch, None)
    [row] = operator_rows(op_repo(tmp_path))
    assert row["status"] == "warn"
    assert row["detail"] == f"not installed in the current kube context, expected {op['operator_version']} (Argo CD application operator-cloudnative-pg)"
    assert "apply operators/root.yaml once: KUBE_CONTEXT=" in row["fix"] and "devbox run bootstrap" in row["fix"]


def test_doctor_warns_when_the_platform_managed_operator_differs_ac_115_18(tmp_path, monkeypatch):  # AC-115.18
    op = expected()
    kube(monkeypatch, "0.0.1")
    [row] = operator_rows(op_repo(tmp_path))
    assert row["status"] == "warn" and row["detail"] == f"installed 0.0.1, expected {op['operator_version']} (Argo CD application operator-cloudnative-pg)"
    assert row["fix"] == "sync operator-cloudnative-pg in Argo CD"


def test_doctor_compares_the_versions_of_an_owner_managed_environment_ac_115_18(tmp_path, monkeypatch):  # AC-115.18
    op = expected()
    repo = op_repo(tmp_path, owner=ENVS)
    kube(monkeypatch, op["operator_version"])
    [ok_row] = operator_rows(repo)
    assert ok_row["status"] == "ok" and ok_row["detail"].startswith(f"installed {op['operator_version']}, expected {op['operator_version']} (operators: owner in dev")
    kube(monkeypatch, None)
    [missing] = operator_rows(repo)
    assert missing["status"] == "warn" and missing["detail"].startswith(f"not installed in the current kube context, expected {op['operator_version']} (operators: owner in dev")
    assert missing["fix"] == f"install the cloudnative-pg chart {op['chart_version']} (operator {op['operator_version']})"
    kube(monkeypatch, "0.0.1")
    [differs] = operator_rows(repo)
    assert differs["status"] == "warn" and differs["detail"].startswith(f"installed 0.0.1, expected {op['operator_version']} (operators: owner in dev")
    assert differs["fix"] == f"move the cloudnative-pg chart to {op['chart_version']} (operator {op['operator_version']})"


def test_doctor_has_no_operator_row_without_an_in_cluster_database_or_kubectl_ac_115_18(tmp_path, monkeypatch):  # AC-115.18
    kube(monkeypatch, None)
    assert len(operator_rows(op_repo(tmp_path / "with-db"))) == 1, "a row exists where a database runs in the cluster"
    write_system(tmp_path / "ext", system({"e": db(external=True)}, {"api": comp("api", ["e"])}))
    assert operator_rows(tmp_path / "ext") == []
    write_system(tmp_path / "none", system(None))
    assert operator_rows(tmp_path / "none") == []
    kube(monkeypatch, None, kubectl=False)
    assert operator_rows(op_repo(tmp_path / "db")) == []


def test_doctor_no_longer_has_the_never_matching_postgres_row_ac_115_18(tmp_path, monkeypatch):  # AC-115.18
    import doctor
    kube(monkeypatch, None)
    write_system(tmp_path, system({"postgres": db()}, {"api": comp("api", ["postgres"])}))
    assert not [c for c in doctor.check_addons(tmp_path) if c["name"] == "addon postgres"]
    assert len(operator_rows(tmp_path)) == 1


# ---------------- AC-115.6: the migration writes what 5.0 wrote ----------------

@pytest.fixture(scope="module")
def migrated(tmp_path_factory):
    import update
    base = build_old_gitops(tmp_path_factory.mktemp("old-gitops-115"))
    repo = tmp_path_factory.mktemp("migrated-115") / base.name
    shutil.copytree(base, repo, symlinks=True)
    before = generated(repo)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(update, "render_baseline", lambda *a, **k: None)
        mp.setattr(update, "refresh_devbox_lock", lambda *a, **k: None)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cplat.main(["platform", "update", "--repo", str(repo), "--migrate", "--skip-tasks", "--json"])
    data = json.loads(out.getvalue()) if out.getvalue().strip().startswith("{") else {}
    return SimpleNamespace(repo=repo, before=before, rc=rc, err=err.getvalue(), data=data)


def test_migrate_writes_the_same_system_yaml_as_5_0_ac_115_6(migrated):  # AC-115.6
    assert migrated.rc == 0, migrated.err
    assert load(migrated.repo / APP / "system.yaml") == FULL5


def test_migrate_renders_the_4_7_tree_except_the_pinned_image_ac_115_6(migrated):  # AC-115.6
    assert migrated.rc == 0, migrated.err
    after = generated(migrated.repo)
    assert sorted(after) == sorted(migrated.before)
    diff = [k for k in sorted(after) if after[k] != migrated.before[k]]
    assert diff, "the database image moves from the major-only tag to the pin (AC-115.17)"
    assert all(k.endswith(("/cluster.yaml", "/collector.yaml")) for k in diff), diff   # spec 121: the collector image carries a digest too
    for k in diff:
        if k.endswith("/cluster.yaml"):   # spec 121
            assert PIN_RE.match(yaml.safe_load(after[k])["spec"]["imageName"])
    assert next((k for k in sorted(after) if normalized(unpin({k: after[k]})[k]) != normalized(migrated.before[k])), None) is None   # spec 121: unpin maps the designed references back
    mig = migrated.data["migration"]
    assert mig["ran"] is True and mig["byte_identical"] is True


# ---------------- AC-115.16: docs, changelog, versions ----------------

def test_the_domain_model_guide_documents_the_resources_ac_115_16():  # AC-115.16
    text = (ROOT / "docs" / "DOMAIN-MODEL.md").read_text()
    for needle in ("resources.<name>", "database", "bucket", "cache", "broker", "spec 116", "spec 118", "spec 119", "external", "remote",
                   "instances.<env>", "ORDERS_DB_DATABASE_URL", "USERS_DB_PGHOST", "operators"):
        assert needle in text, f"DOMAIN-MODEL.md lacks {needle!r}"


def test_the_changelog_lists_the_change_in_a_minor_section_that_is_not_breaking_ac_115_16():  # AC-115.16
    text = (ROOT / "docs" / "CHANGELOG.md").read_text()
    sections = re.split(r"(?m)^(?=## \[)", text)
    hits = [s for s in sections if s.startswith("## [") and re.search(r"spec 115|ADR-057", s)]
    assert hits, "the change is listed"
    head = hits[0].splitlines()[0]
    assert re.match(r"## \[(Unreleased|5\.[1-9]\d*\.0)\]", head), head
    entry = next(e for e in re.split(r"\n\s*\n", hits[0]) if re.search(r"spec 115|ADR-057", e))  # spec 116: the 115 entry itself, not the section
    assert "BREAKING" not in entry


def test_the_resource_plugin_has_a_minor_bump_in_both_places_ac_115_16():  # AC-115.16
    manifest = json.loads((ROOT / "plugins/resource/.claude-plugin/plugin.json").read_text())["version"]
    market = next(p["version"] for p in json.loads((ROOT / ".claude-plugin/marketplace.json").read_text())["plugins"] if p["name"] == "resource")
    assert manifest == market  # spec 116: 1.2.0 supersedes 1.1.0; both places agree
    major, minor, patch = (int(x) for x in manifest.split("."))  # spec 116
    assert (major, minor) >= (1, 1) and major == 1, manifest  # spec 116: a minor bump at or above 1.1.0, no major bump
