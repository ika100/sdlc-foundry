"""Spec 114 acceptance tests: the migration to 5.0 (AC-114.40 .. AC-114.49, AC-114.67, AC-114.68).

Contract: design.md "Contract — migration". `migrate5.convert/dump` are the pure conversion; `cplat platform update --migrate` is
run on real 4.x checkouts (the pre-5.0 template rendered with copier, see system_fixtures.build_old_gitops); the fleet runs on the
fake GitHub of fleet_world with the platform version set to 5.0.0. The frozen 4.7 renderer is scripts/cplat/assets/render_v4.py.
Nothing reaches GitHub."""
import contextlib
import copy
import io
import json
import re
import shutil
import subprocess
from types import SimpleNamespace

import pytest
import yaml

import core
import cplat
import gitops
import update
from fleet_world import World, row
from system_fixtures import (FULL4_APP, FULL4_SERVICES, FULL5, NOT_MIGRATED, OTHER_PLUGIN, RENDER4, ROOT, V4_REF, archive_4x, build_old_component,
                             build_old_gitops, copier_render, files, generated, git, load, mod, stamp)

NOUNS_SYSTEM = ["system", "component", "api", "resource", "instance", "issue", "platform"]
NOUNS_COMPONENT = ["component", "api", "instance", "issue", "platform"]
APP = "applications/shop"
HEADER = [
    "# system.yaml of the shop system: the only hand-edited file of this system (sdlc-foundry 5.0).",
    "# Schema: https://github.com/ika100/sdlc-foundry/blob/main/docs/DOMAIN-MODEL.md#one-file-per-system",
    "# Written by `cplat platform update --migrate` from app.yaml and services.yaml; their comments were not carried over.",
]


def plugins(path) -> dict:
    return json.loads((path / ".claude" / "settings.json").read_text())["enabledPlugins"]


def at(names) -> set:
    return {f"{n}@sdlc-foundry" for n in names}


def convert(app=None, services=None, owner="acme", system="shop", **kw):
    return mod("migrate5").convert(system, copy.deepcopy(FULL4_APP if app is None else app),
                                   copy.deepcopy(FULL4_SERVICES if services is None else services), owner, **kw)


def one(**entry):
    base = {"name": "api", "repo": "acme/api", "image": "ghcr.io/acme/api", "shape": "service-python", "port": 8080,
            "probes": {"liveness": "/h", "readiness": "/r"}}
    base.update(entry)
    return {"services": [base]}


# ---------------- AC-114.41 / AC-114.67: the conversion ----------------

def test_the_47_files_convert_to_the_system_document_ac_114_41(tmp_path):  # AC-114.41
    c = convert()
    assert c.problems == []
    assert c.doc == FULL5


def test_hosts_urls_and_placeholders_become_environment_keys_ac_114_41():  # AC-114.41
    envs = convert().doc["environments"]
    assert envs["dev"]["host"] == "{component}.{system}-dev.localhost" and envs["dev"]["url"] == "http://{host}:8088"
    assert envs["staging"]["host"] == "{component}.{system}.example.com" and "url" not in envs["staging"] and "host" not in envs["prod"]
    app = {"hosts": {"dev": "{service}-{app}.x"}, "urls": {"dev": "https://{host}/{service}/{app}/{env}"}}
    dev = convert(app, one()).doc["environments"]["dev"]
    assert dev["host"] == "{component}-{system}.x" and dev["url"] == "https://{host}/{component}/{system}/{env}"


@pytest.mark.parametrize("app, modes", [
    ({}, ["off", "off", "off"]), ({"policies": False}, ["off", "off", "off"]),
    ({"policies": {}}, ["audit", "audit", "enforce"]),
    ({"policies": {"mode": "Enforce"}}, ["enforce", "enforce", "enforce"]),
    ({"policies": {"mode": {"dev": "Off", "prod": "Audit"}}}, ["off", "audit", "audit"]),
    ({"policies": {"mode": {"dev": "Audit", "staging": "Off", "prod": "Enforce"}}}, ["audit", "off", "enforce"]),
])
def test_policies_become_a_lowercase_policy_on_every_environment_ac_114_41(app, modes):  # AC-114.41
    c = convert(app, one())
    assert c.problems == []
    assert [c.doc["environments"][e]["policy"] for e in ("dev", "staging", "prod")] == modes


@pytest.mark.parametrize("promotion, expected", [({"staging": "auto"}, "after-dev-smoke"), ({"staging": "manual"}, "manual"), ({"prod": "manual"}, None), ({}, None)])
def test_promotion_becomes_the_staging_promote_key_ac_114_41(promotion, expected):  # AC-114.41
    c = convert({"promotion": promotion}, one())
    assert c.problems == []
    assert c.doc["environments"]["staging"].get("promote") == expected
    assert "promote" not in c.doc["environments"]["prod"] and "promote" not in c.doc["environments"]["dev"]


@pytest.mark.parametrize("obs", [None, {}, {"ui": "lgtm"}, {"exportTo": "https://o.example.com", "queryURL": "https://q.example.com", "alerts": False}])
def test_observability_becomes_the_same_mapping_on_every_environment_ac_114_41(obs):  # AC-114.41
    c = convert({"addons": {"observability": obs}}, one())
    assert c.problems == []
    for e in ("dev", "staging", "prod"):
        assert c.doc["environments"][e]["observability"] == (obs or {})
    assert "resources" not in c.doc or "observability" not in c.doc.get("resources", {})


def test_no_observability_addon_leaves_the_environments_without_it_ac_114_41():  # AC-114.41
    assert all("observability" not in e for e in convert({}, one()).doc["environments"].values())


def test_postgres_becomes_a_database_resource_with_per_environment_instances_ac_114_41():  # AC-114.41
    pg = convert().doc["resources"]["postgres"]
    assert pg == {"type": "database", "version": 17, "instances": {"dev": {"replicas": 1, "storage": "1Gi"}, "prod": {"replicas": 3, "storage": "20Gi"}}}
    scalar = convert({"addons": {"postgres": {"version": 16, "instances": 2, "storage": "5Gi", "resources": {"limits": {"memory": "1Gi"}}}}}, one())
    assert scalar.doc["resources"]["postgres"] == {"type": "database", "version": 16, "replicas": 2, "storage": "5Gi",
                                                   "resources": {"limits": {"memory": "1Gi"}}}
    assert convert({"addons": {"postgres": {}}}, one()).doc["resources"]["postgres"] == {"type": "database"}


def test_a_service_becomes_a_component_with_type_lang_and_instances_ac_114_41():  # AC-114.41
    comps = convert().doc["components"]
    api = comps["shop-api"]
    assert (api["type"], api["lang"]) == ("service", "python") and "shape" not in api and "environments" not in api and "name" not in api
    assert api["instances"] == {"dev": {"replicas": 1}, "staging": {"replicas": 2, "promote": "manual"}, "prod": {"replicas": 3}}
    assert "replicas" not in api and "promotion" not in api
    assert (comps["shop-web"]["type"], comps["shop-web"]["lang"]) == ("website", "typescript")
    assert comps["shop-web"]["instances"] == {"dev": {}, "staging": {}}
    assert (comps["stock"]["type"], comps["stock"]["lang"]) == ("service", "unknown") and comps["stock"]["external"] == {"kustomize": "external/stock"}


def test_a_scalar_replicas_value_stays_and_no_environments_means_dev_ac_114_41():  # AC-114.41
    c = convert({}, one(replicas=3))
    api = c.doc["components"]["api"]
    assert api["replicas"] == 3 and api["instances"] == {"dev": {}}


def test_secret_path_placeholders_are_converted_ac_114_41():  # AC-114.41
    secrets = [{"name": "k", "remote": {"keys": ["A"], "path": "{app}/{service}/{env}/{secret}"}}]
    c = convert({}, one(secrets=secrets))
    assert c.doc["components"]["api"]["secrets"][0]["remote"]["path"] == "{system}/{component}/{env}/{secret}"


@pytest.mark.parametrize("app, services, needle", [
    ({"foo": 1}, None, "app.yaml: foo"),
    ({"addons": {"redis": {}}}, None, "addons.redis"),
    ({"hosts": {"qa": "x.example.com"}}, None, "qa"),
    ({"policies": {"mode": {"qa": "Audit"}}}, None, "qa"),
    ({}, one(nodeSelector={"a": "b"}), "nodeSelector"),
    ({}, one(environments=["dev", "qa"]), "qa"),
    ({}, one(replicas={"dev": 1, "prod": 2}), "replicas"),
    ({}, one(promotion={"staging": "manual"}), "promotion"),
    ({}, {"services": [{"name": "old", "repo": "acme/old", "image": "i", "shape": "service-python"}]}, "old"),
    ({"addons": {"postgres": {"version": {"dev": 16, "prod": 17}}}}, one(), "version"),
])
def test_a_key_without_a_5_0_place_is_a_problem_naming_it_ac_114_42(app, services, needle):  # AC-114.42
    c = convert(app, services)
    assert c.problems, "an unconvertible key must be listed"
    assert any(needle in p for p in c.problems), c.problems
    assert all(p.split(":")[0] in ("app.yaml", "services.yaml", "owner") for p in c.problems), c.problems


def test_a_missing_owner_is_a_problem_ac_114_42():  # AC-114.42
    c = convert(owner=None)
    assert any(p.startswith("owner") for p in c.problems)


def test_the_owner_is_written_and_the_shapes_map_ac_114_67():  # AC-114.67
    c = convert(owner="globex")
    assert c.doc["owner"] == "globex"
    for shape, pair in {"service-python": ("service", "python"), "service-java": ("service", "java"), "service-go": ("service", "go"),
                        "web-nextjs": ("website", "typescript"), "service-cobol": ("service", "unknown"), None: ("service", "unknown")}.items():
        entry = {"name": "x", "repo": "acme/x", "image": "ghcr.io/acme/x", "port": 80, "probes": {"liveness": "/", "readiness": "/"}}
        if shape:
            entry["shape"] = shape
        d = convert({}, {"services": [entry]}).doc["components"]["x"]
        assert (d["type"], d["lang"]) == pair, shape


def test_gateway_secret_store_and_registries_become_top_level_keys_ac_114_67():  # AC-114.67
    doc = convert().doc
    assert doc["gateway"] == FULL4_APP["gateway"] and doc["secretStore"] == FULL4_APP["secretStore"] and doc["registries"] == ["ghcr.io/acme/"]
    assert "gateway" not in convert({}, one()).doc and "registries" not in convert({"policies": {}}, one()).doc


# ---------------- AC-114.48: the header and the comments ----------------

def test_dump_starts_with_the_generated_header_and_round_trips_ac_114_48():  # AC-114.48
    m5 = mod("migrate5")
    text = m5.dump(convert().doc)
    assert text.splitlines()[:3] == HEADER
    assert yaml.safe_load(text) == FULL5
    assert list(yaml.safe_load(text)) == ["system", "owner", "gateway", "secretStore", "registries", "environments", "components", "resources"]


def test_has_comments_sees_comments_in_either_old_file_ac_114_48():  # AC-114.48
    m5 = mod("migrate5")
    assert m5.has_comments("# hand-written\nservices: []\n") and m5.has_comments("hosts: {}  # trailing\n")
    assert not m5.has_comments("services: []\n") and not m5.has_comments("name: 'a # b'\n")


# ---------------- AC-114.45: the plugin switch (settingsmerge) ----------------

TEMPLATE_5 = {"enabledPlugins": {f"{n}@sdlc-foundry": True for n in [*NOUNS_SYSTEM, "svc", "shared"]}, "permissions": {"allow": []}}


def test_merge_settings_switches_the_plugins_and_keeps_the_repos_own_ac_114_45():  # AC-114.45
    import settingsmerge
    project = {"enabledPlugins": {"app@sdlc-foundry": True, "gitops@sdlc-foundry": True, "svc@sdlc-foundry": True, "shared@sdlc-foundry": True,
                                  OTHER_PLUGIN: True, "off@elsewhere": False}, "permissions": {"allow": []}}
    merged, report = settingsmerge.merge_settings(project, copy.deepcopy(TEMPLATE_5), None)
    assert set(merged["enabledPlugins"]) == at([*NOUNS_SYSTEM, "svc", "shared"]) | {OTHER_PLUGIN, "off@elsewhere"}
    assert merged["enabledPlugins"]["off@elsewhere"] is False
    assert set(report["plugins"]["added"]) == at(NOUNS_SYSTEM) and set(report["plugins"]["removed"]) == at(["app", "gitops"])
    assert "enabledPlugins" not in [r["key"] for r in report["replaced"]]


def test_merge_settings_reports_nothing_when_the_plugins_are_current_ac_114_45():  # AC-114.45
    import settingsmerge
    _, report = settingsmerge.merge_settings(copy.deepcopy(TEMPLATE_5), copy.deepcopy(TEMPLATE_5), None)
    assert report["plugins"] == {"added": [], "removed": []}


def test_merge_settings_file_writes_the_merged_plugins_ac_114_45(tmp_path):  # AC-114.45
    import settingsmerge
    f = tmp_path / ".claude" / "settings.json"
    f.parent.mkdir()
    old = {"enabledPlugins": {"app@sdlc-foundry": True, "gitops@sdlc-foundry": True, OTHER_PLUGIN: True}, "permissions": {"allow": []}}
    f.write_text(json.dumps(TEMPLATE_5, indent=2) + "\n")      # the template step wrote its file over the repo's
    settings, _ = settingsmerge.merge_settings_file(tmp_path, json.dumps(old), None)
    assert OTHER_PLUGIN in plugins(tmp_path) and "app@sdlc-foundry" not in plugins(tmp_path)
    assert set(settings["plugins"]["removed"]) == at(["app", "gitops"])


@pytest.mark.parametrize("template, expected", [
    ("gitops-app/.claude/settings.json.jinja", [*NOUNS_SYSTEM, "svc", "shared"]),
    ("service-python/.claude/settings.json", [*NOUNS_COMPONENT, "svc", "shared"]),
    ("library-python/.claude/settings.json", [*NOUNS_COMPONENT, "svc", "shared"]),
    ("service-java/.claude/settings.json.jinja", [*NOUNS_COMPONENT, "svc", "shared", "svc-java"]),
    ("service-go/.claude/settings.json.jinja", [*NOUNS_COMPONENT, "svc", "shared", "svc-go"]),
    ("web-nextjs/.claude/settings.json.jinja", [*NOUNS_COMPONENT, "svc", "shared", "web"]),
])
def test_the_templates_enable_the_5_0_noun_plugins_ac_114_45(template, expected):  # AC-114.45
    text = (ROOT / "templates" / template).read_text()
    block = re.search(r'"enabledPlugins":\s*\{(.*?)\}', text, re.S).group(1)
    assert set(re.findall(r'"([\w-]+@sdlc-foundry)":\s*true', block)) == at(expected)


# ---------------- the frozen renderer (AC-114.40) ----------------

def test_render_v4_is_the_4_7_renderer_verbatim_ac_114_40(tmp_path):  # AC-114.40
    assert RENDER4.is_file(), "scripts/cplat/assets/render_v4.py is the frozen 4.7 renderer"
    src = archive_4x(["templates/gitops-app/scripts/render.py"], tmp_path / "ref")
    assert RENDER4.read_bytes() == (src / "templates/gitops-app/scripts/render.py").read_bytes()


# ---------------- platform update --migrate on a real 4.x gitops-app ----------------

@pytest.fixture(scope="module")
def old_base(tmp_path_factory):
    return build_old_gitops(tmp_path_factory.mktemp("old-gitops"))


def clone(base, dest_parent):
    dest = dest_parent / base.name
    shutil.copytree(base, dest, symlinks=True)
    return dest


def run_cplat(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = cplat.main([*argv])
    return rc, out.getvalue(), err.getvalue()


def no_baseline(mp):
    mp.setattr(update, "render_baseline", lambda *a, **k: None)
    mp.setattr(update, "refresh_devbox_lock", lambda *a, **k: None)


@pytest.fixture(scope="module")
def migrated(old_base, tmp_path_factory):
    repo = clone(old_base, tmp_path_factory.mktemp("migrated"))
    before = generated(repo)
    with pytest.MonkeyPatch.context() as mp:
        no_baseline(mp)
        rc, out, err = run_cplat("platform", "update", "--repo", str(repo), "--migrate", "--skip-tasks", "--json")
    return SimpleNamespace(repo=repo, before=before, rc=rc, out=out, err=err, data=json.loads(out) if out.strip().startswith("{") else {})


def test_migrate_writes_system_yaml_and_deletes_the_old_files_ac_114_40(migrated):  # AC-114.40
    assert migrated.rc == 0, migrated.err
    d = migrated.repo / APP
    assert (d / "system.yaml").is_file() and not (d / "app.yaml").exists() and not (d / "services.yaml").exists()
    assert load(d / "system.yaml") == FULL5
    assert git(migrated.repo, "status", "--porcelain").strip() == ""


def test_the_rendered_tree_is_byte_identical_to_what_4_7_rendered_ac_114_40(migrated):  # AC-114.40
    assert migrated.rc == 0, migrated.err
    # spec 115 (AC-115.6): the database image is pinned to a patch release; imageName is compared at its major version
    pin = re.compile(r"(imageName: ghcr\.io/cloudnative-pg/postgresql:)(\d+)\S*")
    after = {k: pin.sub(r"\1\2", v) for k, v in generated(migrated.repo).items()}
    before = {k: pin.sub(r"\1\2", v) for k, v in migrated.before.items()}
    assert sorted(after) == sorted(before)
    assert next((k for k in sorted(after) if after[k] != before[k]), None) is None
    assert len(after) > 50


def test_the_report_proves_the_identity_and_lists_the_deleted_files_ac_114_40(migrated):  # AC-114.40
    assert migrated.rc == 0, migrated.err
    mig = migrated.data["migration"]
    assert mig["ran"] is True and mig["kind"] == "system" and mig["byte_identical"] is True
    assert mig["compared"] >= len(migrated.before)
    assert mig["system_yaml"].endswith("applications/shop/system.yaml")
    assert sorted(mig["deleted"]) == [f"{APP}/app.yaml", f"{APP}/services.yaml"]
    assert any(f"the 5.0 render is byte-identical to 4.7 ({mig['compared']} files compared)" in s for s in migrated.data["did"])
    assert any(s.startswith(f"deleted {APP}/app.yaml") and f"{APP}/services.yaml" in s for s in migrated.data["did"])


def test_the_written_system_yaml_is_not_reported_as_left_out(migrated):   # #238
    assert migrated.rc == 0, migrated.err
    assert not any(s.startswith("left out") and "system.yaml" in s for s in migrated.data["did"])


def test_a_repo_without_project_notes_gets_the_file_claude_md_imports(old_base, tmp_path, monkeypatch):   # #239
    repo = clone(old_base, tmp_path)
    (repo / ".claude" / "project-notes.md").unlink(missing_ok=True)
    git(repo, "commit", "-qam", "repo from before spec 086")
    no_baseline(monkeypatch)
    rc, out, err = run_cplat("platform", "update", "--repo", str(repo), "--migrate", "--skip-tasks", "--json")
    assert rc == 0, err
    assert "@.claude/project-notes.md" in (repo / "CLAUDE.md").read_text()
    assert (repo / ".claude" / "project-notes.md").is_file()


def test_migrate_writes_the_header_and_drops_the_comments_and_says_so_ac_114_48(migrated):  # AC-114.48
    assert migrated.rc == 0, migrated.err
    text = (migrated.repo / APP / "system.yaml").read_text()
    assert text.splitlines()[:3] == HEADER
    assert "hand-written comment" not in text and "the shop application" not in text
    assert migrated.data["migration"]["comments_dropped"] is True
    assert any("the comments of app.yaml and services.yaml were not carried over" in s for s in migrated.data["did"])


def test_migrate_switches_the_plugins_and_reports_each_entry_ac_114_45(migrated):  # AC-114.45
    assert migrated.rc == 0, migrated.err
    assert plugins(migrated.repo).keys() == at([*NOUNS_SYSTEM, "svc", "shared"]) | {OTHER_PLUGIN}
    p = migrated.data["migration"]["plugins"]
    assert set(p["added"]) == at(NOUNS_SYSTEM) and set(p["removed"]) == at(["app", "gitops"])
    line = next(s for s in migrated.data["did"] if s.startswith("plugins added:"))
    assert "removed:" in line and "app@sdlc-foundry" in line and "system@sdlc-foundry" in line


def test_migrate_commits_the_migration_with_the_update_ac_114_40(migrated):  # AC-114.40
    assert migrated.rc == 0, migrated.err
    assert git(migrated.repo, "rev-list", "--count", "HEAD").strip() == "2"
    assert git(migrated.repo, "branch", "--show-current").strip().startswith("chore/platform-update-")


def test_a_dry_run_prints_the_plan_and_changes_nothing_ac_114_43(old_base, tmp_path, monkeypatch):  # AC-114.43
    repo = clone(old_base, tmp_path)
    no_baseline(monkeypatch)
    before = files(repo)
    rc, out, err = run_cplat("platform", "update", "--repo", str(repo), "--migrate", "--skip-tasks", "--dry-run")
    assert rc == 0, err
    assert f"would write {APP}/system.yaml:" in out
    body = out.split(f"would write {APP}/system.yaml:", 1)[1]
    for line in HEADER + ["system: shop", "owner: acme"]:
        assert "\n    " + line in body, line
    assert re.search(rf"would delete .*{APP}/app.yaml.*{APP}/services.yaml", out)
    assert re.search(r"plugins: would add .*system@sdlc-foundry.*; would remove .*app@sdlc-foundry.*gitops@sdlc-foundry", out)
    assert files(repo) == before and git(repo, "status", "--porcelain").strip() == ""


def test_update_without_migrate_refuses_naming_the_flag_ac_114_44(old_base, tmp_path, monkeypatch):  # AC-114.44
    repo = clone(old_base, tmp_path)
    no_baseline(monkeypatch)
    before, head = files(repo), git(repo, "rev-parse", "HEAD")
    rc, out, err = run_cplat("platform", "update", "--repo", str(repo), "--skip-tasks")
    assert rc == 1 and out == ""
    assert "this repo is on platform 4.7.0: 5.0 changes its files and plugins" in err and "cplat platform update --migrate" in err
    assert files(repo) == before and git(repo, "rev-parse", "HEAD") == head


def test_migrate_on_a_migrated_repo_reports_already_migrated_ac_114_44(migrated, tmp_path, monkeypatch):  # AC-114.44
    assert migrated.rc == 0, migrated.err
    repo = clone(migrated.repo, tmp_path)
    no_baseline(monkeypatch)
    system = (repo / APP / "system.yaml").read_bytes()
    rc, out, err = run_cplat("platform", "update", "--repo", str(repo), "--migrate", "--skip-tasks", "--json")
    assert rc == 0, err
    assert (repo / APP / "system.yaml").read_bytes() == system
    data = json.loads(out)
    assert data["migration"] == {"ran": False, "already_migrated": True}
    assert not (repo / APP / "app.yaml").exists()


def test_unconvertible_keys_stop_the_migration_and_leave_everything_ac_114_42(old_base, tmp_path, monkeypatch):  # AC-114.42
    repo = clone(old_base, tmp_path)
    app = repo / APP / "app.yaml"
    app.write_text(app.read_text() + "foo: 1\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "unconvertible")
    no_baseline(monkeypatch)
    before, head, branches = files(repo), git(repo, "rev-parse", "HEAD"), git(repo, "branch", "--format=%(refname:short)")
    rc, out, err = run_cplat("platform", "update", "--repo", str(repo), "--migrate", "--skip-tasks")
    assert rc == 1
    assert "app.yaml" in err and "foo" in err
    assert files(repo) == before and git(repo, "rev-parse", "HEAD") == head and git(repo, "branch", "--format=%(refname:short)") == branches
    assert (repo / APP / "app.yaml").exists() and (repo / APP / "services.yaml").exists() and not (repo / APP / "system.yaml").exists()


def test_a_render_that_differs_by_a_byte_rolls_everything_back_ac_114_42(old_base, tmp_path, monkeypatch):  # AC-114.42
    repo = clone(old_base, tmp_path)
    no_baseline(monkeypatch)
    real = gitops.render

    def drifting(r):
        real(r)
        f = r / APP / "overlays" / "dev" / "shop-api" / "service.yaml"
        f.write_text(f.read_text() + "# drift\n")
    monkeypatch.setattr(gitops, "render", drifting)
    before, head = files(repo), git(repo, "rev-parse", "HEAD")
    rc, out, err = run_cplat("platform", "update", "--repo", str(repo), "--migrate", "--skip-tasks")
    assert rc == 1
    assert "cannot migrate applications/shop to 5.0: the 5.0 render differs from 4.7:" in err
    assert f"{APP}/overlays/dev/shop-api/service.yaml (changed)" in err
    assert "nothing was changed" in err
    assert files(repo) == before and git(repo, "rev-parse", "HEAD") == head
    assert git(repo, "status", "--porcelain").strip() == "" and git(repo, "branch", "--show-current").strip() == "main"
    assert git(repo, "branch", "--format=%(refname:short)").split() == ["main"]


# ---------------- component repos (AC-114.45, AC-114.46, AC-114.47) ----------------

@pytest.fixture(scope="module")
def old_component(tmp_path_factory):
    return build_old_component(tmp_path_factory.mktemp("old-component"))


def test_a_component_repo_gets_the_template_and_the_plugin_switch_only_ac_114_46(old_component, tmp_path, monkeypatch):  # AC-114.46
    repo = clone(old_component, tmp_path)
    no_baseline(monkeypatch)
    before = files(repo)
    rc, out, err = run_cplat("platform", "update", "--repo", str(repo), "--migrate", "--skip-tasks", "--json")
    assert rc == 0, err
    after = files(repo)
    assert not (repo / "applications").exists() and not [p for p in after if p.endswith("system.yaml")]
    assert (repo / "README.md").read_bytes() == before["README.md"]
    assert [p for p in after if p.startswith(("cmd/", "internal/")) and after[p] != before.get(p)] == []
    assert re.search(r"^_src_path: .*templates/service-go$", (repo / ".copier-answers.yml").read_text(), re.M)
    data = json.loads(out)["migration"]
    assert data["ran"] is True and data["kind"] == "component" and data["byte_identical"] is None and data["system_yaml"] is None and data["deleted"] == []


def test_a_component_repo_enables_the_component_plugins_ac_114_45(old_component, tmp_path, monkeypatch):  # AC-114.45
    repo = clone(old_component, tmp_path)
    no_baseline(monkeypatch)
    rc, out, err = run_cplat("platform", "update", "--repo", str(repo), "--migrate", "--skip-tasks", "--json")
    assert rc == 0, err
    assert set(plugins(repo)) == at([*NOUNS_COMPONENT, "svc", "shared", "svc-go"]) | {OTHER_PLUGIN}
    p = json.loads(out)["migration"]["plugins"]
    assert set(p["added"]) == at(NOUNS_COMPONENT) and set(p["removed"]) == at(["app", "gitops"])


def test_the_v1_to_v2_step_is_part_of_the_same_migration_ac_114_47(old_component, tmp_path, monkeypatch):  # AC-114.47
    repo = clone(old_component, tmp_path)
    (repo / "k8s" / "base").mkdir(parents=True)
    (repo / "k8s" / "base" / "deployment.yaml").write_text("kind: Deployment\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "v1 manifests")
    no_baseline(monkeypatch)
    rc, out, err = run_cplat("platform", "update", "--repo", str(repo), "--migrate", "--skip-tasks")
    assert rc == 0, err
    assert not (repo / "k8s").exists()
    assert "app@sdlc-foundry" not in plugins(repo) and "component@sdlc-foundry" in plugins(repo)
    assert "removed k8s/" in out


# ---------------- the fleet (AC-114.49, AC-114.68) ----------------

@pytest.fixture()
def v5(monkeypatch):
    monkeypatch.setattr(core, "platform_version", lambda *a, **k: "5.0.0")
    import fleet_pr
    argvs = []
    real = fleet_pr.upd.resolve

    def spy(argv):
        argvs.append(list(argv))
        return real(argv)
    monkeypatch.setattr(fleet_pr.upd, "resolve", spy)
    monkeypatch.setattr(update, "refresh_devbox_lock", lambda *a, **k: None)
    return argvs


def branch_file(world, slug, path):
    r = world.repos[slug]
    branch = next(b for b in world.branches(slug) if b.startswith("chore/platform-update-"))
    p = subprocess.run(["git", "show", f"{branch}:{path}"], cwd=r["bare"], text=True, capture_output=True)
    return p.stdout if p.returncode == 0 else None


def v4_baseline(root, template, **data):
    """The pre-5.0 template rendered with the repo's answers: what the fleet's update compares against (spec 086)."""
    src = archive_4x([f"templates/{template}"], root / "tpl")
    return copier_render(src / "templates" / template, root / "baseline", **data)


def fleet_of(tmp_path, base, monkeypatch, capsys, baseline=None):
    return World(tmp_path, (base, baseline), monkeypatch, capsys)


def test_the_fleet_migrates_a_gitops_app_and_merges_the_proved_pr_ac_114_68(old_base, tmp_path, monkeypatch, capsys, v5):  # AC-114.68
    base = v4_baseline(tmp_path / "bl", "gitops-app", project_name="shop-gitops", app_name="shop", github_org="acme")
    w = fleet_of(tmp_path, old_base, monkeypatch, capsys, baseline=base)
    w.add("acme/shop-gitops", "4.7.0", mutate=lambda d: stamp(d, "4.7.0", "gitops-app"))
    rc, doc, err = w.json()
    r = row(doc, "acme/shop-gitops")
    assert rc == 0 and r["outcome"] == "merged", (r, err)
    assert any("--migrate" in a for a in v5)
    assert branch_file(w, "acme/shop-gitops", f"{APP}/system.yaml") and branch_file(w, "acme/shop-gitops", f"{APP}/services.yaml") is None
    p = w.pr_for("acme/shop-gitops")
    assert p["labels"] == [] and w.waits and w.waits[0][2] is True               # CI green -> squash-merged by itself
    assert w.comments("acme/shop-gitops") == []


def test_the_fleet_migrates_a_component_repo_and_merges_it_ac_114_49(old_component, tmp_path, monkeypatch, capsys, v5):  # AC-114.49
    base = v4_baseline(tmp_path / "bl", "service-go", project_name="svc", github_org="acme")
    w = fleet_of(tmp_path, old_component, monkeypatch, capsys, baseline=base)
    w.add("acme/svc", "4.7.0", mutate=lambda d: stamp(d, "4.7.0", "service-go"))
    rc, doc, err = w.json()
    r = row(doc, "acme/svc")
    assert rc == 0 and r["outcome"] == "merged", (r, err)
    assert any("--migrate" in a for a in v5)
    settings = json.loads(branch_file(w, "acme/svc", ".claude/settings.json"))["enabledPlugins"]
    assert "app@sdlc-foundry" not in settings and "component@sdlc-foundry" in settings and OTHER_PLUGIN in settings
    assert branch_file(w, "acme/svc", f"{APP}/system.yaml") is None


def test_a_failed_migration_is_a_failed_row_without_a_pr_ac_114_49(old_base, tmp_path, monkeypatch, capsys, v5):  # AC-114.49
    def break_it(d):
        stamp(d, "4.7.0", "gitops-app")
        a = d / APP / "app.yaml"
        a.write_text(a.read_text() + "foo: 1\n")
    w = fleet_of(tmp_path, old_base, monkeypatch, capsys)
    w.add("acme/shop-gitops", "4.7.0", mutate=break_it)
    rc, doc, err = w.json()
    r = row(doc, "acme/shop-gitops")
    assert r["outcome"] == "failed" and "foo" in r["reason"], r
    assert not w.prs("acme/shop-gitops") and not w.calls_for("acme/shop-gitops", "pr", "create")
    assert w.branches("acme/shop-gitops") == ["main"]


def test_the_dry_run_announces_the_migration_instead_of_a_stuck_pr_ac_114_49(old_base, tmp_path, monkeypatch, capsys, v5):  # AC-114.49
    w = fleet_of(tmp_path, old_base, monkeypatch, capsys)
    w.add("acme/shop-gitops", "4.7.0", mutate=lambda d: stamp(d, "4.7.0", "gitops-app"))
    rc, doc, _ = w.json("--dry-run")
    r = row(doc, "acme/shop-gitops")
    assert rc == 0 and r["outcome"] == "would update"
    assert "5.0 migration: merges on green CI when proved" in r["next"]
    assert "major version: the PR will stay open" not in r["next"]


def test_a_major_version_still_waits_for_a_person_when_it_is_not_the_migration_ac_114_68():  # AC-114.68
    import fleet_pr
    proved = {"lost": [], "migration": {"ran": True, "kind": "system", "byte_identical": True}}
    assert fleet_pr.pre_wait_reasons("4.7.0", "5.0.0", proved) == []
    assert fleet_pr.pre_wait_reasons("4.7.0", "5.0.0", {"lost": [], "migration": {"ran": True, "kind": "component", "byte_identical": None}}) == []
    assert fleet_pr.pre_wait_reasons("4.2.0", "5.0.0", proved) == []        # any 4.x repo
    unproved = {"lost": [], "migration": {"ran": True, "kind": "system", "byte_identical": None}}
    assert fleet_pr.pre_wait_reasons("4.7.0", "5.0.0", unproved) == ["major version 4 → 5"]
    assert fleet_pr.pre_wait_reasons("4.7.0", "5.0.0", {"lost": []}) == ["major version 4 → 5"]
    assert fleet_pr.pre_wait_reasons("4.7.0", "5.0.0", {"lost": [], "migration": {"ran": False, "already_migrated": True}}) == ["major version 4 → 5"]
    assert fleet_pr.pre_wait_reasons("3.9.0", "5.0.0", proved) == ["major version 3 → 5"]
    assert fleet_pr.pre_wait_reasons("5.0.0", "6.0.0", proved) == ["major version 5 → 6"]
    lost = [{"file": ".claude/settings.json", "entry": "x", "where": "w"}]          # overwritten repo additions: a person looks
    assert fleet_pr.pre_wait_reasons("4.7.0", "5.0.0", {**proved, "lost": lost})[0] == "local customisation"
