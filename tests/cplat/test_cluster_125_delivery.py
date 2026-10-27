"""Spec 125 acceptance tests, the template, the registry and the delivery: the shape and the template's `cluster.yaml` (AC-125.1), the
takeover guide (AC-125.14), the end-to-end script (AC-125.16, static), the copied template passing its own checks and the shape's
treatment by detection, update and the fleet (AC-125.17), the docs, the plugin and the marketplace (AC-125.18).

Contract: design.md sections 9, 10, 11 and the plan's tasks t6, t7, t9, t11, t12. Tests that need kustomize or kubeconform skip when
the tool is missing."""
import json
import re
import shutil
import subprocess
import sys

import pytest
import yaml

from cluster_fixtures import ORG, ROOT, TEMPLATE, cluster_repo, render, script
from system_fixtures import mod

DOCS = ROOT / "docs"


def read(path) -> str:
    assert path.exists(), f"{path.relative_to(ROOT)} exists"
    return path.read_text()


@pytest.fixture()
def repo(shared_renders, tmp_path):
    return cluster_repo(shared_renders, tmp_path)


# ---------------- AC-125.1: the shape and the template's cluster.yaml ----------------

def test_ac_125_1_the_registry_lists_the_shape_cluster_gitops_with_the_plugin_cluster():  # AC-125.1
    shapes = {s["id"]: s for s in yaml.safe_load((ROOT / "shapes.yml").read_text())["shapes"]}
    s = shapes["cluster-gitops"]
    assert s["plugin"] == "cluster" and s["template"] == "cluster-gitops" and s["deployable"] is False and s["library"] is False
    assert s["detection"]["copier_src"] == "templates/cluster-gitops" and s["adr"] == [60] and s["status"] == "stable"
    assert s["ci_checks"] == ["quality (render-check + kustomize build + kubeconform)", "check (registered systems)", "security (detect-secrets)", "ci-extra"]


def test_ac_125_1_the_shape_registry_check_passes():  # AC-125.1
    assert "cluster-gitops" in (ROOT / "shapes.yml").read_text()
    p = subprocess.run([sys.executable, "scripts/shapes.py", "check"], cwd=ROOT, capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr


def test_ac_125_1_a_new_cluster_repo_names_the_cluster_and_its_owner_and_lists_no_systems(repo):  # AC-125.1
    doc = yaml.safe_load((repo / "cluster.yaml").read_text())
    assert doc["cluster"] == "home" and doc["owner"] == ORG and doc["org"] == ORG
    assert doc.get("operators") == [] and not doc.get("systems")
    assert set(doc) <= {"cluster", "owner", "server", "org", "operators", "secretStore", "systems"}
    text = (repo / "cluster.yaml").read_text()
    for key in ("cluster", "owner", "server", "org", "operators", "secretStore", "systems"):
        assert key in text, f"cluster.yaml documents {key}"
    assert yaml.safe_load((repo / ".copier-answers.yml").read_text())["github_org"] == ORG


def test_ac_125_1_the_template_rejects_a_bad_cluster_name():  # AC-125.1
    assert TEMPLATE.is_dir(), "templates/cluster-gitops exists"
    copier = (TEMPLATE / "copier.yml").read_text()
    assert "^[a-z]([a-z0-9-]{0,38}[a-z0-9])?$" in copier and "_templates_suffix: .jinja" in copier
    for k in (".secrets.baseline.json", "cluster.yaml", "cluster/**"):
        assert k in copier


def test_ac_125_1_the_detect_shape_script_finds_a_cluster_repo(repo):  # AC-125.1
    det = lambda: subprocess.run(["bash", str(ROOT / "scripts" / "detect-shape.sh"), str(repo)], capture_output=True, text=True)   # noqa: E731
    assert det().stdout.strip() == "cluster-gitops"                 # through _src_path
    (repo / ".copier-answers.yml").unlink()
    assert det().stdout.strip() == "cluster-gitops"                 # through the sniff (cluster.yaml + cluster/operators-root.yaml)


def test_ac_125_1_component_commands_do_not_apply_to_a_cluster_repo(repo):  # AC-125.1
    import shapecmd
    r = shapecmd.route(repo)
    assert r["plugin"] == "cluster" and r["shape"] == "cluster-gitops"
    assert r["unsupported"] == ("/component:* commands do not apply to a cluster repo; use /cluster:add, /cluster:remove, "
                                "/platform:update or /platform:doctor")


# ---------------- AC-125.14: the takeover guide ----------------

def moving_section() -> str:
    text = read(DOCS / "CLUSTERS.md")
    m = re.search(r"^#+ .*Moving an existing cluster.*$", text, re.M)
    assert m, "docs/CLUSTERS.md has a 'Moving an existing cluster' section"
    rest = text[m.end():]
    nxt = re.search(r"^## ", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


def test_ac_125_14_the_guide_describes_the_takeover_steps_in_order():  # AC-125.14
    s = moving_section()
    order = ["operators/apps", "bootstrap", "operators: owner", "/cluster:add", "/platform:doctor"]
    pos = [s.find(o) for o in order]
    assert all(p >= 0 for p in pos), dict(zip(order, pos))
    assert pos == sorted(pos), f"steps out of order: {dict(zip(order, pos))}"
    assert len(re.findall(r"^\s*[1-5]\. ", s, re.M)) >= 5, "numbered steps"
    assert "platform-operators" in s and "operator-cloudnative-pg" in s and "finalizer" in s
    assert "no data is lost" in s or "no data is lost" in s.replace("\n", " ")


def test_ac_125_14_the_guide_has_three_sections():  # AC-125.14
    text = read(DOCS / "CLUSTERS.md")
    for h in ("Create a cluster repo", "Install a system", "Moving an existing cluster"):
        assert re.search(rf"^#+ .*{h}", text, re.M), h
    for needle in ("/cluster:new", "SYSTEMS_TOKEN", "REPO_TOKEN", "/cluster:add", "/cluster:remove", "cluster-up", "operators: owner"):
        assert needle in text, needle


# ---------------- AC-125.16: the end-to-end script (static) ----------------

def test_ac_125_16_the_e2e_script_has_the_steps_and_assertions_of_the_design():  # AC-125.16
    path = ROOT / "tests" / "e2e" / "cluster.sh"
    t = read(path)
    assert subprocess.run(["bash", "-n", str(path)]).returncode == 0
    for needle in ("alpha-gitops", "beta-gitops", "e2e-cluster", "github_org=e2e", "cloudnative-pg", "external-secrets", "type: database",
                   "operators: owner", "LOCAL_CLUSTER=e2e-cluster-local", "E2E_CLUSTER_PORT:-8098", "WITH_ARGO=0", "WITH_CNPG=1", "CNPG_VERSION=",
                   "WITH_ESO=1", "ESO_VERSION=", "WITH_KYVERNO=0", "WITH_LGTM=0", "WITH_SEAWEEDFS=0", "scripts/local-cluster.sh", "addons/dev/db",
                   "Cluster in healthy state", "400", "app.kubernetes.io/name=cloudnative-pg", "wc -l", "E2E_KEEP", "E2E CLUSTER OK",
                   "targetRevision"):
        assert needle in t, needle
    assert "set -euo pipefail" in t and "beta-dev" in t and "down" in t


def test_ac_125_16_the_e2e_workflow_runs_the_cluster_script():  # AC-125.16
    wf = yaml.safe_load(read(ROOT / ".github" / "workflows" / "e2e.yml"))
    job = wf["jobs"]["e2e-cluster"]
    assert job["name"] == "e2e cluster (two systems, one operator)" and job["timeout-minutes"] == 20
    assert any("bash tests/e2e/cluster.sh" in (step.get("run") or "") for step in job["steps"])
    on = wf.get("on") or wf.get(True)
    assert "templates/cluster-gitops/**" in on["pull_request"]["paths"]
    assert "e2e" in wf["jobs"], "the existing job stays"


# ---------------- AC-125.17: the copied template passes its own checks ----------------

def test_ac_125_17_a_copy_with_defaults_has_nothing_to_render(repo):  # AC-125.17
    p = render(repo, None, "--check")
    assert p.returncode == 0 and p.stdout.strip() == "OK: up to date", p.stdout + p.stderr
    before = {f.relative_to(repo).as_posix(): f.read_bytes() for f in (repo / "cluster").rglob("*") if f.is_file()}
    assert render(repo).returncode == 0
    assert {f.relative_to(repo).as_posix(): f.read_bytes() for f in (repo / "cluster").rglob("*") if f.is_file()} == before


def test_ac_125_17_a_copy_with_defaults_passes_check_with_no_systems(repo):  # AC-125.17
    p = script(repo, "check.py")
    assert p.returncode == 0 and p.stdout.strip() == "OK: no systems registered", p.stdout + p.stderr


def test_ac_125_17_the_system_renderer_link_is_a_regular_file_with_the_systems_content(repo):  # AC-125.17
    link = repo / "scripts" / "system_render.py"
    assert link.is_file() and not link.is_symlink()
    assert link.read_bytes() == (ROOT / "templates" / "gitops-app" / "scripts" / "render.py").read_bytes()
    for f in ("local-cluster.sh", "ports.sh"):
        assert not (repo / "scripts" / f).is_symlink() and (repo / "scripts" / f).read_bytes() == (ROOT / "templates" / "gitops-app" / "scripts" / f).read_bytes()


def test_ac_125_17_the_manifests_build_with_kustomize_and_pass_kubeconform(repo):  # AC-125.17
    if not shutil.which("kustomize") or not shutil.which("kubeconform"):
        pytest.skip("kustomize or kubeconform is not installed")
    built = subprocess.run(["kustomize", "build", "cluster"], cwd=repo, capture_output=True, text=True)
    assert built.returncode == 0, built.stderr
    conf = subprocess.run(["kubeconform", "-strict", "-ignore-missing-schemas", "-"], input=built.stdout, capture_output=True, text=True)
    assert conf.returncode == 0, conf.stdout + conf.stderr


def test_ac_125_17_the_devbox_recipes_and_ci_of_the_template(repo):  # AC-125.17
    dev = json.loads((repo / "devbox.json").read_text())
    scripts = dev["shell"]["scripts"]
    for name in ("render", "render-check", "check", "bootstrap", "cluster-up", "cluster-down", "validate", "lint", "lint-fix", "quality", "test",
                 "test-fast", "secrets-scan", "secrets-baseline", "security", "ci"):
        assert name in scripts, name
    assert "cluster-ui" not in scripts and not [k for k in scripts if k.startswith("deps")]
    ci = scripts["ci"] if isinstance(scripts["ci"], str) else " && ".join(scripts["ci"])
    assert "devbox run validate" in ci and "devbox run check" in ci and "devbox run security" in ci
    for pkg in ("uv", "kustomize", "kubeconform", "k3d", "detect-secrets", "jq", "git", "gh", "kubectl", "k9s"):
        assert any(p.startswith(pkg) for p in dev["packages"]), pkg
    wf = yaml.safe_load((repo / ".github" / "workflows" / "ci.yml").read_text())
    names = [j.get("name") for j in wf["jobs"].values()]
    for n in ("quality (render-check + kustomize build + kubeconform)", "check (registered systems)", "security (detect-secrets)", "ci-extra"):
        assert n in names, n
    check_job = next(j for j in wf["jobs"].values() if j.get("name") == "check (registered systems)")
    assert "${{ secrets.SYSTEMS_TOKEN }}" in json.dumps(check_job)


def test_ac_125_17_the_claude_files_of_the_template(repo):  # AC-125.17
    settings = json.loads((repo / ".claude" / "settings.json").read_text())
    enabled = settings["enabledPlugins"]
    for p in ("cluster", "platform", "issue", "shared"):
        assert enabled.get(f"{p}@sdlc-foundry") is True, p
    assert "Bash(git push -u origin cluster/*)" in json.dumps(settings)
    claude = (repo / "CLAUDE.md").read_text()
    assert "## Where your additions go" in claude and "@.claude/project-notes.md" in claude


def test_ac_125_17_update_archives_the_whole_templates_folder_so_links_resolve(tmp_path, monkeypatch):  # AC-125.17
    update = mod("update")
    seen = []

    def fake(tag, path, root):
        seen.append(path)
        raise RuntimeError("stop")
    monkeypatch.setattr(update, "_archive", fake)
    assert update.render_baseline("cluster-gitops", "5.0.0", "project_name: x\n", tmp_path) is None
    assert seen == ["templates"]


def test_ac_125_17_the_fleet_treats_a_cluster_repo_like_any_platform_repo():  # AC-125.17
    import core
    import fleet
    templates = {s["template"] for s in core.registry.load()}
    assert "cluster-gitops" in templates
    assert fleet.is_platform("_src_path: gh:ika100/sdlc-foundry/templates/cluster-gitops\n", templates)


def test_ac_125_17_the_platform_ci_smokes_the_cluster_template():  # AC-125.17
    ci = yaml.safe_load(read(ROOT / ".github" / "workflows" / "ci.yml"))
    assert "smoke-test-cluster-gitops" in ci["jobs"] and "smoke-test-cluster-gitops" in ci["jobs"]["ci-success"]["needs"]


def test_ac_125_17_the_detect_shape_test_script_covers_the_shape():  # AC-125.17
    assert "cluster-gitops" in read(ROOT / "scripts" / "test-detect-shape.sh")
    assert "cluster-gitops" in read(DOCS / "requirements" / "platform-vision.md")


# ---------------- AC-125.18: docs, plugin, marketplace ----------------

def test_ac_125_18_the_domain_model_adds_the_cluster():  # AC-125.18
    t = read(DOCS / "DOMAIN-MODEL.md")
    assert re.search(r"^#+ .*\bCluster\b", t, re.M), "a Cluster noun heading"
    for needle in ("operators", "secret store", "060", "/cluster:"):
        assert needle in t, needle


def test_ac_125_18_adr_060_records_the_decision_and_amends_adr_058():  # AC-125.18
    adr = read(DOCS / "adr" / "060-a-cluster-repo-owns-shared-services.md")
    assert "ADR-058" in adr or "058" in adr
    assert "060" in read(DOCS / "adr" / "README.md")
    assert "060" in read(DOCS / "adr" / "058-pinned-versions-and-platform-installed-operators.md")


def test_ac_125_18_the_changelog_announces_a_non_breaking_minor():  # AC-125.18
    t = read(DOCS / "CHANGELOG.md")
    section = t.split("## [Unreleased]", 1)[1].split("\n## [", 1)[0]
    assert "cluster" in section.lower() and "`cluster` 1.0.0" in section and "ADR-060" in section and "spec 125" in section
    block = section[section.lower().index("a cluster repo hosts several systems"):]
    assert "BREAKING" not in block.split("\n**Resources are named", 1)[0]
    assert "external-secrets" in section and "kyverno" in section and "CLUSTERS.md" in section


def test_ac_125_18_the_cluster_plugin_is_versioned_in_manifest_and_marketplace():  # AC-125.18
    manifest = json.loads(read(ROOT / "plugins" / "cluster" / ".claude-plugin" / "plugin.json"))
    assert manifest["name"] == "cluster" and manifest["version"] == "1.0.0"
    market = json.loads(read(ROOT / ".claude-plugin" / "marketplace.json"))
    entry = next(p for p in market["plugins"] if p["name"] == "cluster")
    assert entry["version"] == "1.0.0" and entry["source"] == "./plugins/cluster" and entry["category"] == "agents"
    for p in market["plugins"]:           # every plugin: marketplace version == manifest version
        m = json.loads((ROOT / p["source"] / ".claude-plugin" / "plugin.json").read_text())
        assert m["version"] == p["version"], p["name"]


def test_ac_125_18_the_cluster_commands_are_thin_wrappers_over_cplat_cluster():  # AC-125.18
    for verb in ("new", "add", "remove"):
        t = read(ROOT / "plugins" / "cluster" / "commands" / f"{verb}.md")
        front = yaml.safe_load(t.split("---", 2)[1])
        assert 0 < len(front["description"]) <= 260
        assert f"cplat cluster {verb}" in t and "$ARGUMENTS" in t and "/issue:report" in t
    assert "nothing is deleted" in read(ROOT / "plugins" / "cluster" / "commands" / "remove.md").lower() or \
        "stay" in read(ROOT / "plugins" / "cluster" / "commands" / "remove.md").lower()
    assert "docs/CLUSTERS.md" in read(ROOT / "plugins" / "cluster" / "README.md")


def test_ac_125_18_the_templates_guide_lists_the_cluster_template():  # AC-125.18
    assert "cluster-gitops" in read(DOCS / "templates.md")
