"""Spec 114 acceptance tests: the commands that edit a system or create repos
(AC-114.28, .29, .33, .34, .35, .36 and the command parts of AC-114.23 and AC-114.58).

Contract: design.md "Command arguments that change". Everything runs through `cplat.main` on hand-built gitops-app checkouts (real
render.py of the template, `gh` and the registry faked, nothing reaches GitHub)."""
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import cplat
import evidence
import gitops
import promote
import compose
import registry
from system_fixtures import (NOT_MIGRATED, PAIRS, RENDER5, SHA, files, git, init_git, tiny, write_old, write_system)
from test_gitops import FakeGh, JAVA_ANSWERS

APP = "applications/shop"


def sysdoc(repo):
    return yaml.safe_load((repo / APP / "system.yaml").read_text())


def run(*argv, capsys=None):
    rc = cplat.main([*map(str, argv)])
    if capsys is None:
        return rc
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def render_check(repo):
    return subprocess.run([sys.executable, "scripts/render.py", "--check"], cwd=repo, capture_output=True, text=True)


# ---------------- a gitops-app to compose into ----------------

@pytest.fixture()
def gitops5(tmp_path, monkeypatch):
    doc = tiny()
    doc["components"] = {}
    d = write_system(tmp_path, "# the shop system (keep this comment)\n" + yaml.safe_dump(doc, sort_keys=False))
    (tmp_path / "scripts").mkdir()
    shutil.copy(RENDER5, tmp_path / "scripts" / "render.py")
    (tmp_path / ".copier-answers.yml").write_text("github_org: acme\napp_name: shop\nproject_name: shop-gitops\n")
    init_git(tmp_path)
    fake = FakeGh()
    fake.topics["acme/bare"] = ["deployable-service"]
    monkeypatch.setattr(compose, "gh", fake)
    monkeypatch.setattr(promote, "gh", fake)
    return tmp_path


def commit(repo, msg="x"):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "--allow-empty", "-m", msg)


# ---------------- AC-114.35: component add | set | remove ----------------

def test_component_add_writes_a_type_lang_entry_with_a_dev_instance_and_renders_ac_114_35(gitops5, capsys):  # AC-114.35
    rc, out, err = run("component", "add", "todo-api", "--repo-dir", gitops5, capsys=capsys)
    assert rc == 0, err
    c = sysdoc(gitops5)["components"]["todo-api"]
    assert (c["type"], c["lang"]) == ("service", "java") and c["image"] == "ghcr.io/acme/todo-api" and c["port"] == 8080 and c["user"] == 65532
    assert c["instances"] == {"dev": {}} and c["probes"]["readiness"] == "/actuator/health/readiness"
    assert not {"shape", "environments", "name", "promotion"} & set(c)
    assert "# the shop system (keep this comment)" in (gitops5 / APP / "system.yaml").read_text()
    assert (gitops5 / APP / "overlays/dev/todo-api/deployment.yaml").is_file() and not (gitops5 / APP / "overlays/staging/todo-api").exists()
    assert render_check(gitops5).returncode == 0
    assert "/instance:promote" in out


def test_component_add_takes_type_and_lang_for_a_repo_without_answers_ac_114_35(gitops5):  # AC-114.35
    assert run("component", "add", "bare", "--type", "service", "--lang", "go", "--repo-dir", gitops5) == 0
    c = sysdoc(gitops5)["components"]["bare"]
    assert (c["type"], c["lang"]) == ("service", "go")


def test_component_add_from_k8s_seeds_the_entry_ac_114_35(gitops5, capsys):  # AC-114.35
    assert run("component", "add", "todo-web", "--from-k8s", "--repo-dir", gitops5) == 0
    c = sysdoc(gitops5)["components"]["todo-web"]
    assert (c["type"], c["lang"]) == ("website", "typescript") and c["port"] == 3000
    assert c["probes"] == {"liveness": "/api/health", "readiness": "/api/ready"} and c["instances"] == {"dev": {}}


def test_component_set_edits_env_expose_uses_and_replicas_ac_114_35(gitops5):  # AC-114.35
    run("component", "add", "todo-api", "--repo-dir", gitops5)
    commit(gitops5)
    assert run("resource", "add", "postgres", "--repo-dir", gitops5) == 0
    commit(gitops5)
    assert run("component", "set", "todo-api", "--env", "LOG_LEVEL=DEBUG", "--expose", "api", "--uses", "postgres", "--replicas", "2",
               "--repo-dir", gitops5) == 0
    c = sysdoc(gitops5)["components"]["todo-api"]
    assert c["env"]["LOG_LEVEL"] == "DEBUG" and c["expose"] == {"host": "api"} and c["uses"] == ["postgres"] and c["replicas"] == 2


def test_component_set_instance_replicas_writes_the_instances_key_ac_114_35(gitops5):  # AC-114.35
    run("component", "add", "todo-api", "--repo-dir", gitops5)
    doc = sysdoc(gitops5)
    doc["components"]["todo-api"]["instances"]["staging"] = {}
    (gitops5 / APP / "system.yaml").write_text(yaml.safe_dump(doc, sort_keys=False))
    commit(gitops5)
    assert run("component", "set", "todo-api", "--instance", "staging", "--replicas", "3", "--repo-dir", gitops5) == 0
    c = sysdoc(gitops5)["components"]["todo-api"]
    assert c["instances"]["staging"] == {"replicas": 3} and "replicas" not in c


def test_component_set_instance_errors_change_nothing_ac_114_35(gitops5, capsys):  # AC-114.35
    run("component", "add", "todo-api", "--repo-dir", gitops5)
    commit(gitops5)
    before = files(gitops5)
    rc, _, err = run("component", "set", "todo-api", "--instance", "prod", "--replicas", "3", "--repo-dir", gitops5, capsys=capsys)
    assert rc == 1 and "todo-api has no instance in prod" in err
    rc, _, err = run("component", "set", "todo-api", "--instance", "dev", "--env", "A=1", "--repo-dir", gitops5, capsys=capsys)
    assert rc == 1 and "--instance" in err
    assert files(gitops5) == before


def test_component_remove_deletes_the_entry_and_its_overlays_ac_114_35(gitops5):  # AC-114.35
    run("component", "add", "todo-api", "--repo-dir", gitops5)
    commit(gitops5)
    assert run("component", "remove", "todo-api", "--repo-dir", gitops5) == 0
    assert "todo-api" not in (sysdoc(gitops5).get("components") or {}) and not (gitops5 / APP / "overlays/dev/todo-api").exists()


def test_component_add_pr_uses_the_component_branch_and_title_ac_114_35(gitops5, monkeypatch):  # AC-114.35
    seen = []
    monkeypatch.setattr(gitops, "open_pr", lambda repo, branch, title, body: seen.append((branch, title, body)) or "https://github.com/acme/shop-gitops/pull/1")
    assert run("component", "add", "todo-api", "--pr", "--repo-dir", gitops5) == 0
    [(branch, title, body)] = seen
    assert branch == "component/add-todo-api" and title == "feat(component): add todo-api" and "/component:add" in body


@pytest.mark.parametrize("flag", [["--shape", "service-java"], ["--app", "shop"]])
def test_the_4x_compose_flags_are_gone_ac_114_35(gitops5, flag):  # AC-114.35
    assert run("component", "add", "bare", "--type", "service", "--lang", "go", "--dry-run", "--repo-dir", gitops5) == 0
    with pytest.raises(SystemExit) as e:
        cplat.main(["component", "add", "todo-api", *flag, "--repo-dir", str(gitops5)])
    assert e.value.code == 2


# ---------------- AC-114.36: resource add | remove ----------------

def test_resource_add_postgres_declares_the_default_database_ac_114_36(gitops5):  # AC-114.36
    assert run("resource", "add", "postgres", "--repo-dir", gitops5) == 0
    assert sysdoc(gitops5)["resources"]["postgres"] == {"type": "database", "version": 17, "replicas": 1, "storage": "1Gi",
                                                        "instances": {"prod": {"replicas": 3, "storage": "20Gi"}}}
    assert "# the shop system (keep this comment)" in (gitops5 / APP / "system.yaml").read_text()


def test_resource_add_postgres_takes_a_version_ac_114_36(gitops5):  # AC-114.36
    assert run("resource", "add", "postgres", "--version", "16", "--repo-dir", gitops5) == 0
    assert sysdoc(gitops5)["resources"]["postgres"]["version"] == 16


def test_resource_add_observability_changes_nothing_and_points_to_the_environment_ac_114_36(gitops5, capsys):  # AC-114.36
    before = files(gitops5)
    rc, _, err = run("resource", "add", "observability", "--repo-dir", gitops5, capsys=capsys)
    assert rc == 1 and "observability is set per environment under environments.<env>.observability in system.yaml" in err
    assert files(gitops5) == before


def test_resource_add_another_name_is_refused_ac_114_36(gitops5, capsys):  # AC-114.36
    rc, _, err = run("resource", "add", "redis", "--repo-dir", gitops5, capsys=capsys)
    # spec 115 (AC-115.1): the type is no longer implied for other names
    assert rc == 1 and "--type is required for redis (database, bucket, cache or broker)" in err


def test_resource_remove_refuses_while_used_then_removes_ac_114_36(gitops5, capsys):  # AC-114.36
    assert run("component", "add", "todo-api", "--repo-dir", gitops5) == 0
    commit(gitops5)
    assert run("resource", "add", "postgres", "--repo-dir", gitops5) == 0
    commit(gitops5)
    assert run("component", "set", "todo-api", "--uses", "postgres", "--repo-dir", gitops5) == 0
    commit(gitops5)
    rc, _, err = run("resource", "remove", "postgres", "--repo-dir", gitops5, capsys=capsys)
    assert rc == 1 and "todo-api" in err
    doc = sysdoc(gitops5)
    doc["components"]["todo-api"]["uses"] = []
    (gitops5 / APP / "system.yaml").write_text(yaml.safe_dump(doc, sort_keys=False))
    commit(gitops5)
    assert run("resource", "remove", "postgres", "--repo-dir", gitops5) == 0
    assert "postgres" not in (sysdoc(gitops5).get("resources") or {})


def test_resource_add_pr_uses_the_resource_branch_ac_114_36(gitops5, monkeypatch):  # AC-114.36
    seen = []
    monkeypatch.setattr(gitops, "open_pr", lambda repo, branch, title, body: seen.append(branch) or "https://github.com/acme/shop-gitops/pull/1")
    assert run("resource", "add", "postgres", "--pr", "--repo-dir", gitops5) == 0
    assert seen == ["resource/add-postgres"]


def test_there_is_no_resource_list_ac_114_36(gitops5):  # AC-114.36
    assert run("resource", "add", "postgres", "--repo-dir", gitops5) == 0
    assert run("resource", "list", "--repo-dir", gitops5) == 2


# ---------------- AC-114.28 / AC-114.29: instance promote ----------------

STAGING_SHA = "sha-" + "c" * 40
D1 = "sha256:" + "1" * 64


@pytest.fixture()
def promote_repo(tmp_path, monkeypatch):
    doc = tiny()
    doc["components"] = {
        "api": {**tiny()["components"]["api"], "instances": {"dev": {}, "staging": {}}},
        "web": {"type": "website", "lang": "typescript", "repo": "acme/web", "image": "ghcr.io/acme/web", "port": 3000,
                "probes": {"liveness": "/h", "readiness": "/r"}},
        "lib": {"type": "library", "lang": "python", "repo": "acme/lib"},
    }
    write_system(tmp_path, "# promote keeps this comment\n" + yaml.safe_dump(doc, sort_keys=False),
                 pins={("dev", "api"): "latest", ("staging", "api"): STAGING_SHA, ("dev", "web"): "latest"})
    init_git(tmp_path)
    monkeypatch.setattr(promote, "gh", lambda args: (_ for _ in ()).throw(AssertionError(f"unexpected gh call {args}")))
    monkeypatch.setattr(promote, "image_tags", lambda image: {"1.3.0"})
    monkeypatch.setattr(evidence, "summary", lambda svc, version, tag: evidence.Evidence(service=svc["name"], version=version, staging_tag=tag))
    monkeypatch.setattr(registry, "digests", lambda image, tags: {t: D1 for t in tags})

    def render(repo):
        d = Path(repo) / APP
        for name, c in (yaml.safe_load((d / "system.yaml").read_text())["components"] or {}).items():
            if c.get("type") == "library":
                continue
            for env in (c.get("instances") or {"dev": {}}):
                k = d / "overlays" / env / name / "kustomization.yaml"
                if not k.exists():
                    k.parent.mkdir(parents=True, exist_ok=True)
                    k.write_text(yaml.safe_dump({"images": [{"name": c["image"], "newTag": "latest"}]}))
    monkeypatch.setattr(gitops, "render", render)
    return tmp_path


def pin(repo, env, comp):
    return yaml.safe_load((repo / APP / "overlays" / env / comp / "kustomization.yaml").read_text())["images"][0]["newTag"]


def test_promote_to_staging_adds_the_instance_and_pins_the_source_image_ac_114_28(promote_repo, capsys):  # AC-114.28
    sha = "d" * 40
    rc, out, err = run("instance", "promote", "web", "--to", "staging", "--sha", sha, "--no-verify", "--repo-dir", promote_repo, capsys=capsys)
    assert rc == 0, err
    assert "staging" in sysdoc(promote_repo)["components"]["web"]["instances"]
    assert pin(promote_repo, "staging", "web") == "sha-" + sha
    assert "# promote keeps this comment" in (promote_repo / APP / "system.yaml").read_text()


def test_promote_to_prod_pins_the_release_whose_digest_staging_verified_ac_114_28(promote_repo, capsys):  # AC-114.28
    rc, out, err = run("instance", "promote", "api", "--to", "prod", "--version", "v1.3.0", "--repo-dir", promote_repo, capsys=capsys)
    assert rc == 0, err
    assert "prod" in sysdoc(promote_repo)["components"]["api"]["instances"] and pin(promote_repo, "prod", "api") == "1.3.0"
    assert "match" in out or "digest" in out.lower()


def test_promote_all_takes_every_component_with_a_source_instance_ac_114_28(promote_repo, capsys):  # AC-114.28
    rc, out, err = run("instance", "promote", "--all", "--to", "staging", "--sha", "a" * 40, "--no-verify", "--dry-run", "--repo-dir", promote_repo, capsys=capsys)
    assert rc == 0, err
    assert "api" in out and "web" in out and "lib" not in out
    assert "staging" not in sysdoc(promote_repo)["components"]["web"].get("instances", {})


def test_promote_pr_is_one_pull_request_ac_114_28(promote_repo, monkeypatch):  # AC-114.28
    seen = []
    monkeypatch.setattr(gitops, "open_pr", lambda repo, branch, title, body: seen.append((branch, title)) or "https://github.com/acme/shop-gitops/pull/3")
    assert run("instance", "promote", "web", "api", "--to", "staging", "--sha", "a" * 40, "--no-verify", "--pr", "--repo-dir", promote_repo) == 0
    assert len(seen) == 1


@pytest.mark.parametrize("argv, message", [
    (["web"], "promote names its target with --to: cplat instance promote <component...|--all> --to <env>"),
    (["web", "dev", "staging"], "promote names its target with --to"),
    (["web", "--to", "dev"], "dev is the first environment: nothing is promoted to it (dev follows main)"),
    (["web", "--to", "qa"], "unknown environment 'qa' (environments: dev, staging, prod)"),
    (["web", "--to", "prod", "--version", "v1.3.0"], "web has no instance in staging (it runs in: dev)"),
    (["lib", "--to", "staging"], "lib has no instance in dev"),
])
def test_promote_refuses_and_changes_nothing_ac_114_29(promote_repo, capsys, argv, message):  # AC-114.29
    before = files(promote_repo)
    rc, out, err = run("instance", "promote", *argv, "--repo-dir", promote_repo, capsys=capsys)
    assert rc == 1 and message in err
    assert files(promote_repo) == before and git(promote_repo, "status", "--porcelain").strip() == ""


def test_a_dry_run_refuses_the_same_way_ac_114_29(promote_repo, capsys):  # AC-114.29
    rc, _, err = run("instance", "promote", "web", "--to", "dev", "--dry-run", "--repo-dir", promote_repo, capsys=capsys)
    assert rc == 1 and "first environment" in err


# ---------------- AC-114.33: component new ----------------

def new_component(tmp_path, capsys, *args):
    rc = cplat.main(["component", "new", "api", "A", "description", *args, "--no-github", "--org", "acme", "--dir", str(tmp_path), "--dry-run"])
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


@pytest.mark.parametrize("args, template", [
    ([], "service-python"), (["--type", "service", "--lang", "java"], "service-java"), (["--type", "service", "--lang", "go"], "service-go"),
    (["--type", "website", "--lang", "typescript"], "web-nextjs"), (["--type", "library", "--lang", "python"], "library-python"),
    (["--type", "website"], "web-nextjs"), (["--lang", "go"], "service-go"), (["--lang", "typescript"], "web-nextjs"), (["--type", "library"], "library-python")])
def test_component_new_maps_the_pair_to_its_template_ac_114_33(tmp_path, capsys, args, template):  # AC-114.33
    rc, out, err = new_component(tmp_path, capsys, *args)
    assert rc == 0, err
    assert f"templates/{template}" in out


@pytest.mark.parametrize("args", [["--type", "service", "--lang", "typescript"], ["--type", "worker"], ["--lang", "unknown"], ["--type", "service", "--lang", "unknown"]])
def test_an_invalid_pair_fails_listing_the_valid_ones_ac_114_33(tmp_path, capsys, args):  # AC-114.33
    rc, out, err = new_component(tmp_path, capsys, *args)
    assert rc == 1 and "is not a valid component type" in err and PAIRS in err
    assert not (tmp_path / "api").exists()


@pytest.mark.parametrize("args, message", [
    (["--web"], "`--web` is `--type website --lang typescript` in 5.0"),
    (["--library"], "`--library` is `--type library --lang python` in 5.0"),
    (["--gitops"], "`--gitops` is `cplat system new <manifest>` (/system:new) in 5.0"),
    (["--type", "service-java"], "`--type service-java` is `--type service --lang java` in 5.0"),
    (["--app", "acme/x"], "`--app` is `--system` in 5.0"),
])
def test_the_4x_flags_fail_naming_their_replacement_ac_114_33(tmp_path, capsys, args, message):  # AC-114.33
    rc, out, err = new_component(tmp_path, capsys, *args)
    assert rc == 1 and message in err


def test_component_new_system_writes_the_link_file_ac_114_33(tmp_path):  # AC-114.33
    rc = cplat.main(["component", "new", "api", "A", "description", "--type", "service", "--lang", "go", "--system", "acme/shop-gitops",
                     "--no-github", "--skip-tasks", "--org", "acme", "--dir", str(tmp_path)])
    assert rc == 0
    assert "acme/shop-gitops" in (tmp_path / "api" / ".platform-app.yml").read_text()
    assert "templates/service-go" in (tmp_path / "api" / ".copier-answers.yml").read_text()


# ---------------- AC-114.34 / AC-114.58: system new ----------------

MANIFEST = {"system": "shop", "owner": "globex", "components": [
    {"name": "shop-api", "description": "API", "type": "service", "lang": "go"},
    {"name": "shop-web", "description": "Frontend", "type": "website", "lang": "typescript"}]}


def manifest(tmp_path, **over):
    m = {**MANIFEST, **over}
    f = tmp_path / "system.yml"
    f.write_text(yaml.safe_dump(m))
    return str(f)


def new_system(tmp_path, capsys, *extra, **over):
    rc = cplat.main(["system", "new", manifest(tmp_path, **over), "--no-github", "--org", "acme", "--dir", str(tmp_path / "out"), *extra])
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def test_system_new_creates_the_gitops_app_with_system_yaml_and_every_component_ac_114_34(tmp_path, capsys, monkeypatch):  # AC-114.34
    calls = []
    monkeypatch.setattr(compose, "main", lambda argv: calls.append(argv) or 0)
    rc, out, err = new_system(tmp_path, capsys, "--skip-tasks")
    assert rc == 0, err
    out_dir = tmp_path / "out"
    doc = yaml.safe_load((out_dir / "shop-gitops" / APP / "system.yaml").read_text())
    assert doc["system"] == "shop" and doc["owner"] == "globex" and not (out_dir / "shop-gitops" / APP / "app.yaml").exists()
    assert "templates/service-go" in (out_dir / "shop-api" / ".copier-answers.yml").read_text()
    assert "templates/web-nextjs" in (out_dir / "shop-web" / ".copier-answers.yml").read_text()
    assert len(calls) == 1 and calls[0][0] == "add" and {"shop-api", "shop-web"} <= set(calls[0]) and "--pr" in calls[0]
    assert "/component:add" in out and "/gitops:" not in out


@pytest.mark.parametrize("over, message", [
    ({"app": "shop", "system": None}, "`app` is `system` in 5.0"),
    ({"owner": None}, "owner"),
    ({"components": [{"name": "x", "description": "d", "shape": "service-go"}]}, "component 'x': shape is replaced by type and lang in 5.0"),
    ({"components": [{"name": "x", "description": "d", "type": "service", "lang": "unknown"}]}, "unknown"),
    ({"components": [{"name": "x", "description": "d", "type": "service", "lang": "typescript"}]}, "valid"),
])
def test_bad_system_manifests_fail_before_anything_happens_ac_114_34(tmp_path, capsys, over, message):  # AC-114.34
    m = {k: v for k, v in {**MANIFEST, **over}.items() if v is not None}
    f = tmp_path / "bad.yml"
    f.write_text(yaml.safe_dump(m))
    rc = cplat.main(["system", "new", str(f), "--no-github", "--org", "acme", "--dir", str(tmp_path / "out"), "--dry-run"])
    assert rc == 1 and message in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_system_new_dry_run_plans_system_yaml_and_the_pairs_ac_114_58(tmp_path, capsys):  # AC-114.58
    rc, out, err = new_system(tmp_path, capsys, "--dry-run")
    assert rc == 0, err
    assert "shop-gitops" in out and "templates/service-go" in out and "templates/web-nextjs" in out
    assert not (tmp_path / "out").exists()
