"""Spec 116 acceptance tests, the platform side: `/resource:add|remove` for buckets (AC-116.12, AC-116.20), the model and `cplat model
show` (AC-116.2), `/platform:doctor` (AC-116.19), the `--uses` note (AC-116.4), the template's cluster scripts (AC-116.19), the e2e script
text (AC-116.14, AC-116.19), the docs and the plugin (AC-116.12, AC-116.16, AC-116.17, AC-116.20).

Contract: design.md "Contract: cplat resource", "model, doctor, compose" and "local cluster and bootstrap". Everything runs through
`cplat.main` or the modules on hand-built checkouts; `gh`, `kubectl` and the network are faked or not used. The e2e script is only read
(it needs a cluster): its text is asserted where the plan says so."""
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
from resources_fixtures import APP, comp, db, platform_render_module, system
from system_fixtures import RENDER5, ROOT, files, git, init_git, mod, write_system

SYS = f"{APP}/system.yaml"
BKEYS = "endpoint, bucket, region, forcePathStyle, accessKeyId, secretAccessKey"


def bucket(**kw) -> dict:
    return {"type": "bucket", **kw}


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


# ---------------- AC-116.12 / AC-116.20: resource add ----------------

def test_add_a_bucket_declares_it_with_the_defaults_and_renders_ac_116_12(repo):  # AC-116.12
    assert run("resource", "add", "files", "--type", "bucket", "--repo-dir", repo) == 0
    assert sysdoc(repo)["resources"]["files"] == {"type": "bucket", "storage": "10Gi", "versioning": False}
    assert "# the shop system (keep this comment)" in (repo / SYS).read_text()
    assert render_check(repo).returncode == 0


def test_add_a_bucket_with_storage_and_versioning_ac_116_12(repo):  # AC-116.12
    assert run("resource", "add", "files", "--type", "bucket", "--storage", "5Gi", "--versioning", "--repo-dir", repo) == 0
    assert sysdoc(repo)["resources"]["files"] == {"type": "bucket", "storage": "5Gi", "versioning": True}
    assert render_check(repo).returncode == 0


def test_a_bucket_added_by_the_command_renders_its_objects_once_used_ac_116_12(repo):  # AC-116.12
    assert run("resource", "add", "files", "--type", "bucket", "--repo-dir", repo) == 0
    doc = sysdoc(repo)
    doc["components"]["api"]["uses"] = ["files"]
    (repo / SYS).write_text(yaml.safe_dump(doc, sort_keys=False))
    done = subprocess.run([sys.executable, "scripts/render.py"], cwd=repo, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert (repo / APP / "addons/dev/files/bucket.yaml").is_file() and (repo / "operators/apps/seaweedfs.yaml").is_file()


def test_add_an_external_bucket_writes_the_small_typed_entry_ac_116_12(repo):  # AC-116.12
    assert run("resource", "add", "files", "--type", "bucket", "--external", "--repo-dir", repo) == 0
    assert sysdoc(repo)["resources"]["files"] == {"type": "bucket", "external": True}
    assert render_check(repo).returncode == 0


def test_add_an_external_bucket_with_a_path_ac_116_12(repo):  # AC-116.12
    assert run("resource", "add", "files", "--type", "bucket", "--external", "--path", "{env}/{resource}", "--repo-dir", repo) == 0
    assert sysdoc(repo)["resources"]["files"] == {"type": "bucket", "external": True, "remote": {"path": "{env}/{resource}"}}


def test_add_an_external_database_still_writes_a_database_ac_116_12(repo):  # AC-116.12
    assert run("resource", "add", "ext", "--type", "database", "--external", "--repo-dir", repo) == 0
    assert sysdoc(repo)["resources"]["ext"] == {"type": "database", "external": True}


def test_add_prints_the_next_steps_of_a_bucket_ac_116_12(repo, capsys):  # AC-116.12
    rc, out, err = run("resource", "add", "files", "--type", "bucket", "--repo-dir", repo, capsys=capsys)
    assert rc == 0, err
    assert "let components use it: /component:set <component> --uses files (or uses: [files] in system.yaml)" in out
    assert ("the platform installs the SeaweedFS operator through operators/ (apply operators/root.yaml once per cluster: "
            "KUBE_CONTEXT=<ctx> devbox run bootstrap); environments with operators: owner need it installed by their owner") in out
    assert "CloudNativePG" not in out
    commit(repo)
    rc, out, _ = run("resource", "add", "ext", "--type", "bucket", "--external", "--repo-dir", repo, capsys=capsys)
    assert rc == 0 and f"put the keys {BKEYS} in the secret store platform-secrets under shop-dev-ext, shop-staging-ext, shop-prod-ext" in out


def test_add_pr_uses_the_resource_branch_and_title_for_a_bucket_ac_116_12(repo, monkeypatch):  # AC-116.12
    seen = []
    monkeypatch.setattr(gitops, "open_pr", lambda r, branch, title, body: seen.append((branch, title)) or "https://github.com/acme/shop-gitops/pull/1")
    assert run("resource", "add", "files", "--type", "bucket", "--pr", "--repo-dir", repo) == 0
    assert seen == [("resource/add-files", "feat(resource): add files")]


@pytest.mark.parametrize("argv, needle", [
    (["d", "--type", "database", "--storage", "5Gi"], "--storage and --versioning apply to --type bucket only"),
    (["d", "--type", "database", "--versioning"], "--storage and --versioning apply to --type bucket only"),
    (["b", "--type", "bucket", "--version", "16"], "--version applies to --type database or broker only"),  # spec 119: broker takes --version
    (["b", "--type", "bucket", "--external", "--storage", "5Gi"], "an external bucket is sized and configured at its provider: --storage does not apply"),
    (["b", "--type", "bucket", "--external", "--versioning"], "an external bucket is sized and configured at its provider: --versioning does not apply"),
    (["b", "--type", "bucket", "--storage", "lots"], "storage 'lots' is not a size, e.g. 10Gi"),
    (["b", "--type", "bucket", "--storage", "10 Gi"], "storage '10 Gi' is not a size, e.g. 10Gi"),
    (["b", "--type", "bucket", "--path", "x"], "--path needs --external"),
])
def test_add_bucket_errors_change_nothing_and_name_the_reason_ac_116_12(repo, capsys, argv, needle):  # AC-116.12
    before = files(repo)
    rc, _, err = run("resource", "add", *argv, "--repo-dir", repo, capsys=capsys)
    assert rc == 1 and needle in err, err
    assert files(repo) == before


def test_add_external_bucket_needs_the_secret_store_ac_116_12(repo_no_store, capsys):  # AC-116.12
    before = files(repo_no_store)
    rc, _, err = run("resource", "add", "files", "--type", "bucket", "--external", "--repo-dir", repo_no_store, capsys=capsys)
    assert rc == 1 and "an external resource needs the system's secretStore" in err
    assert files(repo_no_store) == before


def test_add_a_bucket_is_no_longer_refused_as_not_available_ac_116_20(repo, capsys):  # AC-116.20
    rc, _, err = run("resource", "add", "store", "--type", "bucket", "--repo-dir", repo, capsys=capsys)
    assert rc == 0 and "not available yet" not in err


@pytest.mark.parametrize("typ, spec", [])  # spec 119: broker is built, no type is planned (pytest skips the empty set)
def test_add_of_the_other_planned_types_keeps_its_refusal_ac_116_20(repo, capsys, typ, spec):  # AC-116.20
    before = files(repo)
    rc, _, err = run("resource", "add", "store", "--type", typ, "--repo-dir", repo, capsys=capsys)
    assert rc == 1 and f"resource type {typ} is not available yet: spec {spec} brings it" in err
    assert files(repo) == before


# ---------------- AC-116.12: resource remove ----------------

def build_used(tmp_path):
    """files used by api and web, idle unused, ext external and unused; rendered."""
    res = {"files": bucket(), "idle": bucket(), "ext": bucket(external=True), "ext2": bucket(instances={"prod": {"external": True}})}
    return make_repo(tmp_path, system(res, {"api": comp("api", ["files"]), "web": comp("web", ["files"])}))


def test_remove_of_a_used_bucket_names_every_user_and_changes_nothing_ac_116_12(tmp_path, capsys):  # AC-116.12
    used = build_used(tmp_path)
    before = files(tmp_path)
    assert (used / APP / "addons/dev/files/bucket.yaml").is_file(), "the checkout was rendered with its bucket"
    rc, _, err = run("resource", "remove", "files", "--repo-dir", used, capsys=capsys)
    assert rc == 1 and "files is still used by api, web" in err and "/component:set" in err
    assert files(tmp_path) == before


def test_remove_of_an_in_cluster_bucket_says_data_and_secret_stay_ac_116_12(tmp_path, capsys):  # AC-116.12
    used = build_used(tmp_path)
    rc, out, err = run("resource", "remove", "idle", "--dry-run", "--repo-dir", used, capsys=capsys)
    assert rc == 0, err
    assert ("remove idle from system.yaml; the Argo Application disappears but the bucket, its data and its Secret shop-idle-app stay in the cluster "
            "(delete them by hand when you are sure)") in out
    assert "the database and its data" not in out


def test_remove_of_an_external_bucket_says_the_synced_secret_stays_ac_116_12(tmp_path, capsys):  # AC-116.12
    used = build_used(tmp_path)
    rc, out, err = run("resource", "remove", "ext", "--dry-run", "--repo-dir", used, capsys=capsys)
    assert rc == 0, err
    assert ("remove ext from system.yaml; the synced Secret shop-ext-app stays in the cluster (delete it by hand when you are sure); "
            "the external bucket is not touched") in out
    assert "the external database" not in out


def test_remove_of_a_mixed_bucket_says_both_ac_116_12(tmp_path, capsys):  # AC-116.12
    used = build_used(tmp_path)
    rc, out, _ = run("resource", "remove", "ext2", "--dry-run", "--repo-dir", used, capsys=capsys)
    assert rc == 0 and "its data and its Secret shop-ext2-app stay in the cluster" in out and "the external bucket is not touched" in out


def test_remove_of_an_unused_bucket_removes_the_entry_and_renders_ac_116_12(tmp_path):  # AC-116.12
    used = build_used(tmp_path)
    assert run("resource", "remove", "idle", "--repo-dir", used) == 0
    assert "idle" not in sysdoc(tmp_path)["resources"] and "files" in sysdoc(tmp_path)["resources"]
    assert (used / APP / "addons/dev/files/bucket.yaml").is_file()
    assert render_check(tmp_path).returncode == 0


def test_remove_of_a_used_bucket_directory_survives_until_it_is_unused_ac_116_12(tmp_path):  # AC-116.12
    used = build_used(tmp_path)
    doc = sysdoc(tmp_path)
    doc["components"]["web"]["uses"] = []
    doc["components"]["api"]["uses"] = []
    (used / SYS).write_text(yaml.safe_dump(doc, sort_keys=False))
    commit(tmp_path)
    assert run("resource", "remove", "files", "--repo-dir", used) == 0
    assert not (used / APP / "addons/dev/files").exists() and render_check(tmp_path).returncode == 0


# ---------------- AC-116.2: the model ----------------

def model_doc():
    res = {"files": bucket(storage="5Gi", instances={"prod": {"storage": "50Gi", "versioning": True}}), "plain": bucket(),
           "ext": bucket(external=True), "idle": bucket()}
    return system(res, {"api": comp("api", ["files", "ext"]), "web": comp("web", ["plain"], envs=("dev",))})


@pytest.fixture()
def mrepo(tmp_path):
    write_system(tmp_path, model_doc())
    return tmp_path


def test_bucket_instances_carry_storage_and_versioning_ac_116_2(mrepo):  # AC-116.2
    m = mod("model").load_dir(mrepo / APP)
    ri = {(r.resource, r.environment): r for r in m.resource_instances}
    d = ri[("files", "dev")]
    assert (d.type, d.external, d.argo_application, d.secret, d.store_key) == ("bucket", False, "addon-files-dev", "shop-files-app", None)
    assert dict(d.sizing) == {"storage": "5Gi", "versioning": False}
    assert dict(ri[("files", "prod")].sizing) == {"storage": "50Gi", "versioning": True}
    assert dict(ri[("plain", "dev")].sizing) == {"storage": "10Gi", "versioning": False}
    e = ri[("ext", "dev")]
    assert (e.external, e.argo_application, e.secret, e.store_key, dict(e.sizing)) == (True, None, "shop-ext-app", "shop-dev-ext", {})
    assert ("plain", "staging") not in ri and ("idle", "dev") not in ri


def test_the_model_json_has_the_bucket_sizing_as_real_booleans_ac_116_2(mrepo, capsys):  # AC-116.2
    assert cplat.main(["model", "show", "--repo-dir", str(mrepo), "--json"]) == 0
    d = json.loads(capsys.readouterr().out)
    ri = {(r["resource"], r["environment"]): r for r in d["resource_instances"]}
    assert ri[("files", "prod")]["sizing"] == {"storage": "50Gi", "versioning": True}
    assert ri[("files", "dev")]["sizing"] == {"storage": "5Gi", "versioning": False}


def test_the_model_text_prints_storage_and_versioning_in_lower_case_ac_116_2(mrepo, capsys):  # AC-116.2
    assert cplat.main(["model", "show", "--repo-dir", str(mrepo)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert "    dev  type bucket  external false  storage 5Gi  versioning false  argo addon-files-dev  secret shop-files-app" in lines
    assert "    prod  type bucket  external false  storage 50Gi  versioning true  argo addon-files-prod  secret shop-files-app" in lines
    assert "    dev  type bucket  external true  argo -  secret shop-ext-app  store shop-dev-ext" in lines


def test_the_renderer_and_the_model_agree_on_bucket_instances_ac_116_2(tmp_path):  # AC-116.2
    write_system(tmp_path, model_doc())
    (tmp_path / "scripts").mkdir()
    shutil.copy(RENDER5, tmp_path / "scripts" / "render.py")
    done = subprocess.run([sys.executable, "scripts/render.py"], cwd=tmp_path, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    app_dir = tmp_path / APP
    import importlib.util
    spec = importlib.util.spec_from_file_location("render_under_test_116", tmp_path / "scripts" / "render.py")
    r = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(r)
    m = mod("model").load_dir(app_dir)
    renderer = sorted(r.resource_instances(r.load_system(app_dir)))
    assert renderer == sorted((ri.resource, ri.environment, ri.type, ri.external) for ri in m.resource_instances)
    ran = sorted((p.name, p.parent.name) for p in (app_dir / "addons").glob("*/*") if p.is_dir() and p.name != "observability")
    assert ran == sorted((ri.resource, ri.environment) for ri in m.resource_instances if not ri.external)


# ---------------- AC-116.19: doctor ----------------

def seaweed_rows(repo):
    import doctor
    rows = []
    for fn in ("check_addons", "check_operators"):
        if hasattr(doctor, fn):
            rows += getattr(doctor, fn)(repo)
    return [c for c in rows if c["name"] == "operator seaweedfs"]


def kube(monkeypatch, installed: str | None, kubectl: bool = True):
    import doctor
    monkeypatch.setattr(doctor.shutil, "which", lambda t: f"/usr/bin/{t}" if kubectl else None)
    calls = []

    def fake_run(cmd, *a, **k):
        calls.append(cmd)
        out = "" if installed is None else f"ghcr.io/seaweedfs/seaweedfs-operator:{installed}@sha256:{'a' * 64}"
        return SimpleNamespace(stdout=out, stderr="", returncode=0)
    monkeypatch.setattr(doctor, "run", fake_run)
    return calls


def op_repo(tmp_path, owner=()):
    doc = system({"files": bucket()}, {"api": comp("api", ["files"])})
    for e in owner:
        doc["environments"][e]["operators"] = "owner"
    write_system(tmp_path, doc)
    return tmp_path


def expected():
    op = getattr(platform_render_module("render_116_doctor"), "OPERATORS", {}).get("seaweedfs")
    assert op is not None, "render.py has OPERATORS['seaweedfs']"
    return op


def test_doctor_is_ok_when_the_platform_managed_store_operator_matches_ac_116_19(tmp_path, monkeypatch):  # AC-116.19
    op = expected()
    calls = kube(monkeypatch, op["operator_version"])
    [row] = seaweed_rows(op_repo(tmp_path))
    assert row["status"] == "ok"
    assert row["detail"] == f"installed {op['operator_version']}, expected {op['operator_version']} (Argo CD application operator-seaweedfs)"
    assert any("app.kubernetes.io/name=seaweedfs-operator" in " ".join(c) and "deploy" in c for c in calls)


def test_doctor_warns_when_the_platform_managed_store_operator_is_missing_ac_116_19(tmp_path, monkeypatch):  # AC-116.19
    op = expected()
    kube(monkeypatch, None)
    [row] = seaweed_rows(op_repo(tmp_path))
    assert row["status"] == "warn"
    assert row["detail"] == f"not installed in the current kube context, expected {op['operator_version']} (Argo CD application operator-seaweedfs)"
    assert "apply operators/root.yaml once: KUBE_CONTEXT=" in row["fix"] and "devbox run bootstrap" in row["fix"]


def test_doctor_warns_naming_both_versions_when_the_store_operator_differs_ac_116_19(tmp_path, monkeypatch):  # AC-116.19
    op = expected()
    kube(monkeypatch, "0.0.1")
    [row] = seaweed_rows(op_repo(tmp_path))
    assert row["status"] == "warn" and row["detail"] == f"installed 0.0.1, expected {op['operator_version']} (Argo CD application operator-seaweedfs)"
    assert row["fix"] == "sync operator-seaweedfs in Argo CD"


def test_doctor_compares_the_versions_of_an_owner_managed_environment_ac_116_19(tmp_path, monkeypatch):  # AC-116.19
    op = expected()
    repo = op_repo(tmp_path, owner=("dev", "staging", "prod"))
    kube(monkeypatch, op["operator_version"])
    [ok_row] = seaweed_rows(repo)
    assert ok_row["status"] == "ok" and ok_row["detail"].startswith(f"installed {op['operator_version']}, expected {op['operator_version']} (operators: owner in dev")
    kube(monkeypatch, None)
    [missing] = seaweed_rows(repo)
    assert missing["status"] == "warn" and missing["detail"].startswith(f"not installed in the current kube context, expected {op['operator_version']} (operators: owner in dev")
    assert missing["fix"] == f"install the seaweedfs-operator chart {op['chart_version']} (operator {op['operator_version']})"
    kube(monkeypatch, "1.0.41")
    [differs] = seaweed_rows(repo)
    assert differs["status"] == "warn" and differs["detail"].startswith(f"installed 1.0.41, expected {op['operator_version']} (operators: owner in dev")
    assert differs["fix"] == f"move the seaweedfs-operator chart to {op['chart_version']} (operator {op['operator_version']})"


def test_doctor_has_no_store_row_without_an_in_cluster_bucket_or_kubectl_ac_116_19(tmp_path, monkeypatch):  # AC-116.19
    kube(monkeypatch, None)
    assert len(seaweed_rows(op_repo(tmp_path / "with"))) == 1, "a row exists where a bucket runs in the cluster"
    write_system(tmp_path / "ext", system({"e": bucket(external=True)}, {"api": comp("api", ["e"])}))
    assert seaweed_rows(tmp_path / "ext") == []
    write_system(tmp_path / "db", system({"d": db()}, {"api": comp("api", ["d"])}))
    assert seaweed_rows(tmp_path / "db") == []
    kube(monkeypatch, None, kubectl=False)
    assert seaweed_rows(op_repo(tmp_path / "nokubectl")) == []


def test_doctor_lists_cloudnative_pg_before_seaweedfs_ac_116_19(tmp_path, monkeypatch):  # AC-116.19
    import doctor
    kube(monkeypatch, None)
    write_system(tmp_path, system({"files": bucket(), "d": db()}, {"api": comp("api", ["files", "d"])}))
    names = [c["name"] for c in doctor.check_operators(tmp_path)]
    assert names == ["operator cloudnative-pg", "operator seaweedfs"]


# ---------------- AC-116.4: the --uses note and help ----------------

def make_uses_repo(tmp_path):
    return make_repo(tmp_path, system({"uploads": bucket(), "exports": bucket(), "orders-db": db()}, {"api": comp("api"), "web": comp("web")}))


def test_two_buckets_add_the_prefixed_variables_step_ac_116_4(tmp_path, capsys):  # AC-116.4
    repo = make_uses_repo(tmp_path)
    rc, out, err = run("component", "set", "api", "--uses", "uploads", "--uses", "exports", "--dry-run", "--repo-dir", repo, capsys=capsys)
    assert rc == 0, err
    assert "api now uses 2 bucket resources: their variables are prefixed (<NAME>_S3_ENDPOINT, …) and S3_*, AWS_* are no longer injected" in out


def test_one_bucket_adds_no_prefixed_variables_step_ac_116_4(tmp_path, capsys):  # AC-116.4
    repo = make_uses_repo(tmp_path)
    assert render_check(repo).returncode == 0, "the buckets render"
    rc, out, err = run("component", "set", "api", "--uses", "uploads", "--dry-run", "--repo-dir", repo, capsys=capsys)
    assert rc == 0, err
    assert "now uses" not in out and "are prefixed" not in out


def test_a_bucket_and_a_database_add_no_prefixed_variables_step_ac_116_4(tmp_path, capsys):  # AC-116.4
    repo = make_uses_repo(tmp_path)
    assert render_check(repo).returncode == 0, "the buckets render"
    rc, out, err = run("component", "set", "api", "--uses", "uploads", "--uses", "orders-db", "--dry-run", "--repo-dir", repo, capsys=capsys)
    assert rc == 0, err
    assert "are prefixed" not in out


def test_the_uses_help_names_the_bucket_variables_ac_116_4():  # AC-116.4
    text = (ROOT / "scripts" / "cplat" / "compose.py").read_text()
    assert ("resource or library the component needs (a database gives DATABASE_URL and PG*, a bucket S3_* and AWS_*, a cache REDIS_URL and REDIS_*); "  # spec 118: caches named
            "declare it first with `cplat resource add <name> --type database|bucket|cache`") in text  # spec 118: cache type


# ---------------- AC-116.19: the template's cluster scripts ----------------

T = ROOT / "templates" / "gitops-app"


def test_bootstrap_waits_for_the_seaweedfs_crd_ac_116_19():  # AC-116.19
    text = (T / "scripts" / "bootstrap.sh").read_text()
    assert "seaweedfs) crd=buckets.seaweed.seaweedfs.com ;;" in text
    assert "cloudnative-pg) crd=clusters.postgresql.cnpg.io ;;" in text


def test_cluster_up_installs_or_waits_for_the_seaweedfs_operator_ac_116_19():  # AC-116.19
    text = (T / "scripts" / "local-cluster.sh").read_text()
    for needle in ("WITH_SEAWEEDFS", "SEAWEEDFS_OPERATOR_VERSION", "operators/apps/seaweedfs.yaml", "0.1.45", "seaweedfs-operator",
                   "https://seaweedfs.github.io/seaweedfs-operator", "buckets.seaweed.seaweedfs.com", "operators/root.yaml"):
        assert needle in text, f"local-cluster.sh lacks {needle!r}"
    assert "SeaweedFS (operators/apps/seaweedfs.yaml) is not installed either; recreate the cluster" in text
    assert "CloudNativePG was installed by an older cluster-up (HelmChart kube-system/cnpg); keeping it. Recreate the cluster to let Argo CD manage it" in text


def test_the_gitops_claude_md_names_the_seaweedfs_operator_ac_116_19():  # AC-116.19
    text = (T / "CLAUDE.md.jinja").read_text()
    assert "SeaweedFS" in text and "operators/" in text and "CloudNativePG" in text


@pytest.mark.parametrize("script", ["bootstrap.sh", "local-cluster.sh"])
def test_the_cluster_scripts_parse_ac_116_19(script):  # AC-116.19
    if not shutil.which("bash"):
        pytest.skip("no bash")
    p = subprocess.run(["bash", "-n", str(T / "scripts" / script)], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr


# ---------------- AC-116.14 and friends: the e2e script ----------------

def e2e() -> str:
    return (ROOT / "tests" / "e2e" / "run.sh").read_text()


def test_the_e2e_script_writes_and_reads_an_object_through_the_component_variables_ac_116_14():  # AC-116.14 (needs a cluster)
    text = e2e()
    for needle in ("resource add files --type bucket", "WITH_SEAWEEDFS", "operators/apps/seaweedfs.yaml", "S3_FORCE_PATH_STYLE",
                   "endpoint unreachable", "access denied", "content differs"):
        assert needle in text, f"tests/e2e/run.sh lacks {needle!r}"


def test_the_e2e_script_lets_two_components_share_the_bucket_ac_116_6():  # AC-116.6 (needs a cluster)
    text = e2e()
    assert "e2e-api" in text and "e2e-web" in text
    assert re.search(r"files", text) and re.search(r"(?i)\blist\b", text) and re.search(r"(?i)\bdelete\b|\brm\b", text)


def test_the_e2e_script_restarts_the_store_and_reads_again_ac_116_8():  # AC-116.8 (needs a cluster)
    text = e2e()
    assert re.search(r"(?i)restart|delete pod", text) and "seaweed" in text.lower()


def test_the_e2e_script_applies_the_bucket_in_sync_wave_order_ac_116_14():  # AC-116.14 (needs a cluster)
    text = e2e()
    assert "externalsecret.yaml" in text and "credentials.yaml" in text


# ---------------- docs, changelog, plugin ----------------

def test_the_domain_model_guide_documents_the_bucket_contract_ac_116_16():  # AC-116.16
    text = (ROOT / "docs" / "DOMAIN-MODEL.md").read_text()
    for needle in ("S3_ENDPOINT", "S3_FORCE_PATH_STYLE", "AWS_ENDPOINT_URL_S3", "UPLOADS_S3_BUCKET", "versioning", "storage", "spec 116"):
        assert needle in text, f"DOMAIN-MODEL.md lacks {needle!r}"


def test_the_domain_model_guide_documents_the_external_bucket_keys_ac_116_17():  # AC-116.17
    text = (ROOT / "docs" / "DOMAIN-MODEL.md").read_text()
    assert "secretAccessKey" in text and "forcePathStyle" in text and "accessKeyId" in text


def test_the_changelog_lists_the_bucket_in_a_minor_section_that_is_not_breaking_ac_116_20():  # AC-116.20
    text = (ROOT / "docs" / "CHANGELOG.md").read_text()
    sections = re.split(r"(?m)^(?=## \[)", text)
    hits = [s for s in sections if s.startswith("## [") and re.search(r"spec 116|ADR-059", s)]
    assert hits, "the change is listed"
    assert re.match(r"## \[(Unreleased|5\.[1-9]\d*\.0)\]", hits[0].splitlines()[0])
    entry = next(e for e in re.split(r"\n\s*\n", hits[0]) if re.search(r"spec 116|ADR-059", e))  # spec 117: the 116 entry itself, not the section
    assert "BREAKING" not in entry


def test_the_resource_plugin_is_1_2_0_in_both_places_and_describes_buckets_ac_116_12():  # AC-116.12
    manifest = json.loads((ROOT / "plugins/resource/.claude-plugin/plugin.json").read_text())["version"]
    market = next(p["version"] for p in json.loads((ROOT / ".claude-plugin/marketplace.json").read_text())["plugins"] if p["name"] == "resource")
    assert manifest == market  # spec 117: 1.3.0 supersedes 1.2.0; both places agree
    major, minor, patch = (int(x) for x in manifest.split("."))  # spec 117
    assert major == 1 and (major, minor) >= (1, 2), manifest  # spec 117: a minor bump at or above 1.2.0, no major bump
    add = (ROOT / "plugins/resource/commands/add.md").read_text()
    assert "--type database|bucket" in add and "--storage" in add and "--versioning" in add
    assert "bucket" in (ROOT / "plugins/resource/commands/remove.md").read_text()
