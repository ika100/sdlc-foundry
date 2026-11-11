"""Spec 179 acceptance tests: a system plan carries the instance settings its criteria state (AC-179.1, AC-179.2).

Seams: `templates/gitops-app/scripts/plan.py validate` on a gitops-app checkout with one system plan (the spec 045 and 053 world
of test_plan.py); `appship.entry_ops`; `cplat component set --resources` on the spec 114 gitops-app world; `spec.provided_by_system`;
the planner and ship-entry prompts. Contract: design.md section 1.
"""
import shutil
from pathlib import Path

import pytest
import yaml

import appship
import spec
from system_fixtures import files
from test_commands_114 import APP, commit, gitops5, run, sysdoc  # noqa: F401  (gitops5 is a fixture)
from test_plan import CONTRACT, SCRIPT, plan

ROOT = Path(__file__).resolve().parents[2]

SPEC = """---
spec_id: 200-shop
title: Shop
status: approved
priority: P1
shape: gitops-app
---

## Acceptance criteria

- **AC-200.1** checkout returns a URL
- **AC-200.2** Given the staging instance, then shop-api runs with 2 replicas
- **AC-200.3** Given the dev instance, then shop-api logs at debug level through its env LOG_LEVEL and its replicas stay 1
- ~~**AC-200.4**~~ withdrawn: shop-api gets 4 replicas
<!-- - **AC-200.9** an example in a comment names replicas and is no criterion -->

## Changelog
"""

PLAN_HEAD = """---
plan_id: 200-shop
spec: 200-shop
feature: shop
gitops_app: acme/shop-gitops
status: {status}
repos:
  - {{id: shop-api, shape: service-python, summary: API, acs: [AC-200.1], depends_on: [], done: {done}}}
  - id: shop-gitops
    shape: gitops-app
    summary: instance settings
{order}    acs: [{acs}]
    gitops:
{ops}    depends_on: []
    done: {done}
---
"""
OPS = ["{replicas: 2, component: shop-api, instance: staging}", "{env: {LOG_LEVEL: debug}, component: shop-api}"]


def plan_text(ops=OPS, acs="AC-200.2, AC-200.3", order="    order: before-merge\n", status="draft", done="false"):
    return PLAN_HEAD.format(status=status, done=done, order=order, acs=acs, ops="".join(f"      - {o}\n" for o in ops)) + CONTRACT


@pytest.fixture()
def shop(tmp_path):
    (tmp_path / "scripts").mkdir()
    shutil.copy(SCRIPT, tmp_path / "scripts" / "plan.py")
    (tmp_path / "docs" / "plan").mkdir(parents=True)
    (tmp_path / "docs" / "specs" / "200-shop").mkdir(parents=True)
    (tmp_path / "docs" / "specs" / "200-shop" / "spec.md").write_text(SPEC)
    return tmp_path


def check(shop, text):
    (shop / "docs" / "plan" / "200-shop.md").write_text(text)
    return plan(shop, "validate")


# ---------------- AC-179.1: the gitops entry holds replicas and resources, in order before-merge ----------------

def test_a_gitops_entry_with_instance_settings_and_before_merge_passes_ac_179_1(shop):  # AC-179.1
    out = check(shop, plan_text())
    assert out.returncode == 0, out.stderr


@pytest.mark.parametrize("op", [
    "{replicas: 3, component: shop-api}",
    "{replicas: 2, component: shop-api, instance: dev}",
    "{resources: {requests: {cpu: 100m, memory: 256Mi}, limits: {memory: 512Mi}}, component: shop-api}",
    "{resources: {requests: {cpu: 0.5}}, component: shop-api, instance: staging}",
])
def test_replicas_and_resources_are_gitops_operations_ac_179_1(shop, op):  # AC-179.1
    out = check(shop, plan_text([op, OPS[1]]))
    assert out.returncode == 0, out.stderr


@pytest.mark.parametrize("op, msg", [
    ("{replicas: 0, component: shop-api}", "gitops operation 'replicas' needs a whole number of at least 1"),
    ("{replicas: two, component: shop-api}", "gitops operation 'replicas' needs a whole number of at least 1"),
    ("{replicas: 2.5, component: shop-api}", "gitops operation 'replicas' needs a whole number of at least 1"),
    ("{replicas: 2}", "needs a component"),
    ("{replicas: 2, component: shop-x}", "unknown component 'shop-x'"),
    ("{replicas: 2, component: shop-api, instance: prod}",
     "gitops operation 'replicas': instance must be dev or staging (prod changes go through its promotion)"),
    ("{resources: [cpu], component: shop-api}", "gitops operation 'resources' takes requests/limits of cpu and memory as quantities"),
    ("{resources: {requests: {disk: 1Gi}}, component: shop-api}", "gitops operation 'resources' takes requests/limits of cpu"),
    ("{resources: {limits: {memory: lots}}, component: shop-api}", "gitops operation 'resources' takes requests/limits of cpu"),
    ("{resources: {burst: {cpu: 1}}, component: shop-api}", "gitops operation 'resources' takes requests/limits of cpu"),
])
def test_an_invalid_instance_setting_operation_is_refused_with_its_message_ac_179_1(shop, op, msg):  # AC-179.1
    out = check(shop, plan_text([op, OPS[1]]))
    assert out.returncode == 1 and f"repo shop-gitops: {msg}" in out.stderr, out.stderr


def test_the_order_of_a_gitops_entry_can_only_be_before_merge_ac_179_1(shop):  # AC-179.1
    out = check(shop, plan_text(order="    order: after-release\n"))
    assert out.returncode == 1
    assert "repo shop-gitops: order must be before-merge (/system:ship applies the gitops entry before the components merge)" in out.stderr


def test_an_entry_without_order_is_still_valid_ac_179_1(shop):  # AC-179.1
    assert check(shop, plan_text(order="")).returncode == 0


def test_the_allowed_operations_in_the_messages_name_replicas_and_resources_ac_179_1(shop):  # AC-179.1
    err = check(shop, plan_text(["{scale: shop-api}"])).stderr
    assert "unknown gitops operation" in err and "replicas" in err and "resources" in err
    err = check(shop, plan_text([]).replace("    gitops:\n", "")).stderr
    assert "needs a `gitops:` list" in err and "replicas" in err and "resources" in err


def test_entry_ops_maps_replicas_to_component_set_ac_179_1():  # AC-179.1
    assert appship.entry_ops({"replicas": 2, "component": "shop-api"}) == ["component", "set", "shop-api", "--replicas", "2"]
    assert appship.entry_ops({"replicas": 2, "component": "shop-api", "instance": "staging"}) == [
        "component", "set", "shop-api", "--instance", "staging", "--replicas", "2"]


def test_entry_ops_maps_resources_to_repeated_resources_options_in_mapping_order_ac_179_1():  # AC-179.1
    op = {"resources": {"requests": {"cpu": "100m", "memory": "256Mi"}, "limits": {"memory": "512Mi"}}, "component": "shop-api"}
    assert appship.entry_ops(op) == ["component", "set", "shop-api", "--resources", "requests.cpu=100m", "--resources",
                                     "requests.memory=256Mi", "--resources", "limits.memory=512Mi"]


def test_the_slice_of_the_component_lists_the_replicas_and_resources_the_entry_sets_ac_179_1(tmp_path):  # AC-179.1
    repos = [{"id": "shop-gitops", "shape": "gitops-app", "gitops": [
        {"replicas": 2, "component": "shop-api", "instance": "staging"},
        {"replicas": 3, "component": "shop-api"},
        {"replicas": 5, "component": "shop-web"},
        {"resources": {"requests": {"cpu": "100m"}, "limits": {"memory": "512Mi"}}, "component": "shop-api"}]}]
    lines = spec.provided_by_system(tmp_path, repos, "shop-api")
    assert "- replicas `2` in `staging`" in lines
    assert "- replicas `3`" in lines
    assert "- resources `requests.cpu=100m, limits.memory=512Mi`" in lines
    assert not any("`5`" in ln for ln in lines)


def cmd(capsys, *argv):
    """`cplat <argv>` -> (exit code, stdout, stderr); an argument the parser refuses is exit 2."""
    capsys.readouterr()
    try:
        rc = run(*argv)
    except SystemExit as e:
        rc = e.code
    out = capsys.readouterr()
    return rc, out.out, out.err


def _rendered_resources(repo, name):
    for p in sorted((repo / "applications").rglob("*.yaml")):
        if p.name == "system.yaml":
            continue
        try:
            docs = list(yaml.safe_load_all(p.read_text()))
        except yaml.YAMLError:
            continue
        for d in docs:
            if isinstance(d, dict) and d.get("kind") == "Deployment" and (d.get("metadata") or {}).get("name") == name:
                return d["spec"]["template"]["spec"]["containers"][0].get("resources")
    return None


def test_component_set_resources_merges_into_system_yaml_and_renders_ac_179_1(gitops5):  # AC-179.1
    assert run("component", "add", "todo-api", "--repo-dir", gitops5) == 0
    commit(gitops5)
    assert run("component", "set", "todo-api", "--resources", "requests.cpu=100m", "--resources", "requests.memory=256Mi",
               "--repo-dir", gitops5) == 0
    commit(gitops5)
    assert run("component", "set", "todo-api", "--resources", "limits.memory=512Mi", "--repo-dir", gitops5) == 0
    res = sysdoc(gitops5)["components"]["todo-api"]["resources"]
    assert res["requests"] == {"cpu": "100m", "memory": "256Mi"} and res["limits"]["memory"] == "512Mi"   # earlier keys stay
    assert _rendered_resources(gitops5, "todo-api") == res                    # rendered as set; the seeded limits.cpu stays too


@pytest.mark.parametrize("bad", ["requests.disk=1Gi", "cpu=100m", "requests.cpu=lots", "requests.cpu", "limits.cpu="])
def test_component_set_resources_refuses_a_bad_key_or_value_and_changes_nothing_ac_179_1(gitops5, capsys, bad):  # AC-179.1
    run("component", "add", "todo-api", "--repo-dir", gitops5)
    commit(gitops5)
    before = files(gitops5)
    rc, _, err = cmd(capsys, "component", "set", "todo-api", "--resources", bad, "--repo-dir", gitops5)
    assert rc == 1 and "--resources" in err and "requests.cpu=100m" in err
    assert files(gitops5) == before


def test_component_set_resources_is_refused_with_an_instance_ac_179_1(gitops5, capsys):  # AC-179.1
    run("component", "add", "todo-api", "--repo-dir", gitops5)
    commit(gitops5)
    before = files(gitops5)
    rc, _, err = cmd(capsys, "component", "set", "todo-api", "--instance", "dev", "--resources", "requests.cpu=100m", "--repo-dir",
                     gitops5)
    assert rc == 1 and "--instance" in err
    assert files(gitops5) == before


def read(rel):
    return (ROOT / rel).read_text()


def test_the_planner_turns_a_stated_instance_setting_into_a_before_merge_gitops_task_ac_179_1():  # AC-179.1
    text = read("plugins/system/agents/planner.md")
    step = text.split("4. **The gitops part is data.**")[1].split("\n5. ")[0]
    assert "replicas" in step and "resources" in step and "order: before-merge" in step
    assert "separate gitops PR" in step or "never a separate" in step.lower()


def test_ship_entry_lists_the_replicas_and_resources_operations_ac_179_1():  # AC-179.1
    text = read("plugins/system/references/ship-entry.md")
    assert "--replicas" in text and "--resources" in text and "before-merge" in text


def test_component_set_documents_resources_ac_179_1():  # AC-179.1
    assert "--resources" in read("plugins/component/commands/set.md")


# ---------------- AC-179.2: the plan check names a criterion whose setting no gitops task carries ----------------

def test_a_criterion_with_a_setting_and_no_gitops_task_is_refused_naming_id_and_key_ac_179_2(shop):  # AC-179.2
    out = check(shop, plan_text(["{env: {LOG_LEVEL: debug}, component: shop-api}"], acs="AC-200.3")
                .replace("acs: [AC-200.1]", "acs: [AC-200.1, AC-200.2]"))
    assert out.returncode == 1
    assert ("AC-200.2 names the instance setting `replicas` but no gitops-app entry lists it in acs: add the operation to the "
            "gitops entry and AC-200.2 to its acs (spec 179)") in out.stderr


def test_every_key_of_the_criterion_is_named_in_order_of_appearance_ac_179_2(shop):  # AC-179.2
    out = check(shop, plan_text(["{replicas: 2, component: shop-api}"], acs="AC-200.2")
                .replace("acs: [AC-200.1]", "acs: [AC-200.1, AC-200.3]"))
    assert out.returncode == 1
    assert "AC-200.3 names the instance setting `env`, `replicas` but no gitops-app entry lists it in acs" in out.stderr
    assert "AC-200.2 names" not in out.stderr


def test_a_plan_whose_setting_criteria_each_have_a_gitops_task_passes_ac_179_2(shop):  # AC-179.2
    assert check(shop, plan_text()).returncode == 0


def test_withdrawn_and_commented_criteria_name_no_setting_ac_179_2(shop):  # AC-179.2
    out = check(shop, plan_text())
    assert out.returncode == 0 and "AC-200.4" not in out.stderr and "AC-200.9" not in out.stderr


def test_a_word_that_only_contains_a_key_is_not_a_setting_ac_179_2(shop):
    """AC-179.2: `environment`, `hostname` and `resource` are not the keys `env`, `host` and `resources`."""
    (shop / "docs" / "specs" / "200-shop" / "spec.md").write_text(
        SPEC.replace("checkout returns a URL", "the environment shows the hostname and one resource"))
    out = check(shop, plan_text())
    assert out.returncode == 0, out.stderr


def test_a_criterion_that_names_host_needs_a_gitops_task_too_ac_179_2(shop):  # AC-179.2
    (shop / "docs" / "specs" / "200-shop" / "spec.md").write_text(
        SPEC.replace("checkout returns a URL", "the web is reachable at the host shop"))
    out = check(shop, plan_text())
    assert out.returncode == 1 and "AC-200.1 names the instance setting `host` but no gitops-app entry lists it in acs" in out.stderr
    ok = plan_text().replace("acs: [AC-200.1]", "acs: []").replace("acs: [AC-200.2, AC-200.3]", "acs: [AC-200.1, AC-200.2, AC-200.3]")
    assert check(shop, ok).returncode == 0


@pytest.mark.parametrize("status", ["completed", "abandoned"])
def test_a_finished_plan_gets_a_warning_not_an_error_ac_179_2(shop, status):  # AC-179.2
    text = plan_text(["{env: {LOG_LEVEL: debug}, component: shop-api}"], acs="AC-200.3", status=status,
                     done="true" if status == "completed" else "false")
    text = text.replace("acs: [AC-200.1]", "acs: [AC-200.1, AC-200.2]")
    out = check(shop, text)
    assert out.returncode == 0, out.stderr
    assert any(ln.startswith("WARNING") and "AC-200.2" in ln for ln in out.stdout.splitlines()), out.stdout


@pytest.mark.parametrize("status", ["draft", "in_progress"])
def test_a_plan_in_progress_gets_the_error_ac_179_2(shop, status):  # AC-179.2
    text = plan_text(["{env: {LOG_LEVEL: debug}, component: shop-api}"], acs="AC-200.3", status=status)
    out = check(shop, text.replace("acs: [AC-200.1]", "acs: [AC-200.1, AC-200.2]"))
    assert out.returncode == 1 and "AC-200.2 names the instance setting `replicas`" in out.stderr
