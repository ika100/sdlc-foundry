"""Spec 201 acceptance tests, proof and delivery: the end-to-end script on two k3d clusters (AC-201.11, static: the script itself needs
Docker and runs in the e2e workflow) and the docs, the ADR, the changelog and the plugin version (AC-201.12).

Contract: design.md section 10 and the plan's tasks t12, t13 and t14."""
import json
import re
import subprocess

import yaml

from support_201 import ROOT

DOCS = ROOT / "docs"
SPEC = "201-one-cluster-repo-places-environments-on"


def read(path) -> str:
    assert path.exists(), f"{path.relative_to(ROOT)} exists"
    return path.read_text()


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


# ---------------- AC-201.11: the end-to-end test (static) ----------------

def test_ac_201_11_the_e2e_script_runs_one_repo_on_two_clusters_with_the_steps_of_the_design():  # AC-201.11
    path = ROOT / "tests" / "e2e" / "clusters.sh"
    t = read(path)
    assert subprocess.run(["bash", "-n", str(path)]).returncode == 0
    assert "set -euo pipefail" in t
    for needle in ("todo-gitops", "github_org=e2e", "e2e-clusters", "cloudnative-pg", "bootstrap/environments", "cluster-up", "LOCAL_HTTP_PORT",
                   "coredns-custom", "insecure", "api-dev", "api-staging", "api-prod", "sha-", "1.0.0", "E2E_KEEP", "E2E CLUSTERS OK"):
        assert needle in t, needle
    assert re.search(r"clusters:\s*\[one,\s*two\]", t), "the cluster repo lists two clusters"
    assert re.search(r"dev:\s*one", t) and re.search(r"staging:\s*one", t) and re.search(r"prod:\s*two", t), "dev and staging on the first, prod on the second"
    assert t.count("cluster-up") >= 2, "each cluster is built and bootstrapped"


def test_ac_201_11_the_e2e_script_compares_the_operator_versions_and_the_image_tags():  # AC-201.11
    t = read(ROOT / "tests" / "e2e" / "clusters.sh")
    assert re.search(r"cloudnative-pg|cnpg", t) and re.search(r"image|version", t, re.I), "both clusters' operator Deployments are compared"
    assert re.search(r"-n todo-dev", t) and re.search(r"-n todo-prod", t), "the image tag of dev and of prod is read from the cluster"
    negative = r"(!|\babsent\b|\bNotFound\b|not found|\bnot\b|\bno\b|\bnone\b|refute|-z\b)[^\n]*api-prod|api-prod[^\n]*(\babsent\b|\bNotFound\b|not found|\bnot\b|\bno\b|refute|-z\b)"
    assert re.search(negative, t, re.I), "cluster one is asserted to have no api-prod"


def test_ac_201_11_the_e2e_workflow_runs_the_clusters_script():  # AC-201.11
    wf = yaml.safe_load(read(ROOT / ".github" / "workflows" / "e2e.yml"))
    job = wf["jobs"]["e2e-clusters"]
    assert job["name"] == "e2e clusters (one repo, two clusters)" and job["timeout-minutes"] == 30
    assert any("bash tests/e2e/clusters.sh" in (step.get("run") or "") for step in job["steps"])
    assert "e2e-cluster" in wf["jobs"], "the existing job stays"


def test_ac_201_11_the_e2e_scope_selects_the_script():  # AC-201.11
    import importlib.util
    spec = importlib.util.spec_from_file_location("e2e_scope_201", ROOT / "scripts" / "e2e-scope.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert "tests/e2e/clusters.sh" in mod.E2E_SCRIPTS and "tests/e2e/clusters.sh" in mod.FILES


# ---------------- AC-201.12: the docs ----------------

def test_ac_201_12_the_domain_model_says_an_environment_runs_on_the_cluster_its_system_assigns_it_to():  # AC-201.12
    text = flat(read(DOCS / "DOMAIN-MODEL.md"))
    assert re.search(r"environment runs on the cluster its system assigns it to", text, re.I)
    assert "systems.<s>.environments" in text and "environments.<env>.cluster" in text
    assert "adr/114-" in text and "/cluster:promote" in text


def several(text: str) -> str:
    assert re.search(r"^#+ Several clusters\s*$", text, re.M), "docs/CLUSTERS.md has a section 'Several clusters'"
    return text.split("Several clusters", 1)[1]


def test_ac_201_12_the_cluster_guide_describes_adding_a_second_cluster_and_assigning_environments():  # AC-201.12
    section = flat(several(read(DOCS / "CLUSTERS.md")))
    low = section.lower()
    for needle in ("add a second cluster", "clusters:", "clusters/<name>/cluster.yaml", "devbox run bootstrap", "kube_contexts",
                   "assign environments", "/platform:update", "systems.<s>.environments", "environments.<env>.cluster"):
        assert needle.lower() in low, needle
    assert low.index("add a second cluster") < low.index("assign environments")
    assert low.index("/platform:update") < low.index("systems.<s>.environments"), "the system repo is updated before the assignment"


def test_ac_201_12_the_cluster_guide_describes_promoting_an_upgrade_and_moving_an_environment():  # AC-201.12
    section = flat(several(read(DOCS / "CLUSTERS.md")))
    low = section.lower()
    for needle in ("promote an upgrade", "/cluster:promote", "behind", "move an environment", "moved:", "nothing is copied", "stay on"):
        assert needle.lower() in low, needle
    assert "kubectl --context <old> delete namespace" in section, "the person deletes the old namespace"
    assert "cplat system restore" not in section and "pg_dump" not in section, "no manual data-copy procedure (a later spec)"
    assert "platform:doctor" in section, "the doctor comparison"


def test_ac_201_12_an_adr_replaces_the_two_decisions():  # AC-201.12
    adr = next(iter((DOCS / "adr").glob("114-*.md")), None)
    assert adr is not None, "ADR-114 exists"
    text = flat(adr.read_text())
    assert "ADR-060" in text and "one gitops repo per cluster" in text and "one system runs all its environments on its cluster" in text
    assert "ADR-068" in text and "decision 7" in text
    index = read(DOCS / "adr" / "README.md")
    assert "114" in index and adr.name in index
    adr60 = flat(next((DOCS / "adr").glob("060-*.md")).read_text())
    assert "ADR-114" in adr60.split("## Context")[0], "the status line of ADR-060 points at ADR-114"
    adr68 = flat(next((DOCS / "adr").glob("068-*.md")).read_text())
    assert "ADR-114" in adr68


def test_ac_201_12_the_change_is_listed_in_a_minor_changelog_section_not_marked_breaking():  # AC-201.12
    fragments = sorted((DOCS / "changelog.d").glob("201-*.added.md"))
    if fragments:
        text = fragments[0].read_text()
        assert "(spec 201)." in text and not re.search(r"\bBREAKING\b", text), "no BREAKING marker (the sentence 'Not breaking: ...' is wanted)"
        assert "docs/CLUSTERS.md" in text or "CLUSTERS.md" in text, "the Action points at the guide"
        assert "1.5.0" in text, "the cluster plugin version is named"
        return
    changelog = read(DOCS / "CHANGELOG.md")
    hits = [m for m in re.finditer(r"^## \[(\d+)\.(\d+)\.(\d+)\][^\n]*\n(.*?)(?=^## \[)", changelog, re.M | re.S) if "spec 201" in m.group(4)]
    assert hits, "released: a version section of CHANGELOG.md lists spec 201"
    major, minor, patch, body = hits[0].groups()
    assert patch == "0" and not re.search(r"\bBREAKING\b", hits[0].group(0)), "no BREAKING marker"


def test_ac_201_12_every_changed_plugin_is_versioned_in_its_manifest_and_the_marketplace():  # AC-201.12
    manifest = json.loads(read(ROOT / "plugins" / "cluster" / ".claude-plugin" / "plugin.json"))
    market = json.loads(read(ROOT / ".claude-plugin" / "marketplace.json"))
    listed = next(p for p in market["plugins"] if p["name"] == "cluster")
    version = tuple(int(x) for x in manifest["version"].split("."))
    assert version >= (1, 5, 0), "the cluster plugin gets /cluster:promote: 1.4.0 -> 1.5.0"
    assert listed["version"] == manifest["version"]
    assert "promote" in manifest["description"]


def test_ac_201_12_the_cluster_plugin_has_the_promote_command_and_its_rules_entry():  # AC-201.12
    cmd = read(ROOT / "plugins" / "cluster" / "commands" / "promote.md")
    head = cmd.split("---")[1]
    description = yaml.safe_load(head)["description"]
    assert "/cluster:promote <cluster>" in description and len(description) <= 260
    assert "cplat cluster promote" in cmd and "--dry-run" in cmd and "NOT PROMOTED" in cmd
    assert (ROOT / "docs" / "rules" / "plugins" / "cluster" / "commands" / "promote.yml").is_file()
    add = read(ROOT / "plugins" / "cluster" / "commands" / "add.md")
    assert "cplat cluster wait" in add and "--envs" in add, "/cluster:add waits on each cluster that runs the system"
    assert "Several clusters" in read(ROOT / "plugins" / "cluster" / "README.md")
