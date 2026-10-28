"""Kyverno guard rails (ADR-022, 5.0): `environments.<env>.policy` renders per environment; evaluation of rendered manifests with the Kyverno CLI."""
import copy
import shutil
import subprocess

import pytest
import yaml

from test_gitops import commit, gh, gitops_repo, render_check, run_compose, system_file  # noqa: F401  (fixtures)

APP = "applications/todo"
needs_kyverno = pytest.mark.skipif(shutil.which("kyverno") is None, reason="the Kyverno CLI is not installed (CI always has it)")


def cfg(repo, env_policy=None, observability=None, **top):
    """Edit system.yaml: `env_policy` maps environments to a policy (audit | enforce | off), `observability` is set on every environment
    (the 4.x addon), `top` are top-level keys (registries). Committed."""
    f = system_file(repo)
    doc = yaml.safe_load(f.read_text())
    for env, mode in (env_policy or {}).items():
        doc["environments"][env]["policy"] = mode
    if observability is not None:
        for env in doc["environments"].values():
            env["observability"] = dict(observability)
    doc.update(top)
    f.write_text(yaml.safe_dump(doc, sort_keys=False))
    commit(repo, "cfg")


ON = {"dev": "audit", "staging": "audit", "prod": "enforce"}      # what 4.x `policies: {}` meant


def render(repo):
    return subprocess.run(["uv", "run", "scripts/render.py"], cwd=repo, capture_output=True, text=True)


def policy(repo, env="dev"):
    return yaml.safe_load((repo / APP / "policies" / env / "policy.yaml").read_text())


def set_envs(repo, envs):
    f = system_file(repo)
    d = yaml.safe_load(f.read_text())
    d["components"]["todo-api"]["instances"] = {e: {} for e in envs}
    f.write_text(yaml.safe_dump(d, sort_keys=False))


def test_nothing_while_every_policy_is_off(gitops_repo, gh):
    run_compose(gitops_repo, "add", "todo-api")
    assert not (gitops_repo / APP / "policies").exists()
    assert "policies" not in (gitops_repo / APP / "applicationset.yaml").read_text().replace("# policies:", "")


def test_enabled_with_defaults_audit_in_dev_enforce_in_prod(gitops_repo, gh):
    cfg(gitops_repo, ON)
    run_compose(gitops_repo, "add", "todo-api")
    set_envs(gitops_repo, ["dev", "staging", "prod"])
    assert render(gitops_repo).returncode == 0
    modes = {e: policy(gitops_repo, e)["spec"]["validationActions"] for e in ("dev", "staging", "prod")}
    assert modes == {"dev": ["Audit"], "staging": ["Audit"], "prod": ["Deny"]}
    p = policy(gitops_repo, "prod")
    assert p["kind"] == "NamespacedValidatingPolicy" and p["metadata"]["namespace"] == "todo-prod"
    sets = [d["metadata"]["name"] for d in yaml.safe_load_all((gitops_repo / APP / "applicationset.yaml").read_text())]
    assert {"todo-policies-dev", "todo-policies-staging", "todo-policies-prod"} <= set(sets)
    assert render_check(gitops_repo).returncode == 0


def test_latest_is_only_forbidden_outside_dev(gitops_repo, gh):
    cfg(gitops_repo, ON)
    run_compose(gitops_repo, "add", "todo-api")
    set_envs(gitops_repo, ["dev", "staging"])
    assert render(gitops_repo).returncode == 0
    msgs = lambda env: [v["message"] for v in policy(gitops_repo, env)["spec"]["validations"]]  # noqa: E731
    assert not any("latest" in m for m in msgs("dev"))
    assert any("latest" in m for m in msgs("staging"))


def test_modes_per_environment_and_off_prunes(gitops_repo, gh):
    cfg(gitops_repo, {"dev": "enforce", "staging": "off"})
    run_compose(gitops_repo, "add", "todo-api")
    set_envs(gitops_repo, ["dev", "staging"])
    assert render(gitops_repo).returncode == 0
    assert policy(gitops_repo, "dev")["spec"]["validationActions"] == ["Deny"]
    assert not (gitops_repo / APP / "policies/staging").exists()


def test_allowed_registries_follow_the_images_and_addons(gitops_repo, gh):
    cfg(gitops_repo, {"dev": "audit"}, observability={}, registries=["registry.example.com/team/"])
    run_compose(gitops_repo, "add", "todo-api")
    regs = yaml.safe_load(policy(gitops_repo)["spec"]["variables"][1]["expression"])
    assert regs == ["ghcr.io/acme/", "otel/", "registry.example.com/team/"]


def test_switching_every_policy_off_prunes_the_files(gitops_repo, gh):
    cfg(gitops_repo, ON)
    run_compose(gitops_repo, "add", "todo-api")
    commit(gitops_repo)
    cfg(gitops_repo, {"dev": "off", "staging": "off", "prod": "off"})
    assert render(gitops_repo).returncode == 0
    assert not (gitops_repo / APP / "policies").exists()


@pytest.mark.parametrize("env_policy, top, msg", [
    ({"dev": "block"}, {}, "environments.dev.policy must be audit, enforce or off, got 'block'"),
    ({}, {"registries": "ghcr.io"}, "list of image prefixes"),
])
def test_invalid_policy_config_is_rejected(gitops_repo, gh, env_policy, top, msg):
    run_compose(gitops_repo, "add", "todo-api")
    commit(gitops_repo)
    cfg(gitops_repo, env_policy, **top)
    p = render(gitops_repo)
    assert p.returncode == 1 and msg in p.stderr


# ---- evaluation with the real Kyverno CLI (offline) ----

def evaluate(tmp_path, repo, resource, env="dev"):
    f = tmp_path / "resource.yaml"
    f.write_text(yaml.safe_dump(resource))
    out = subprocess.run(["kyverno", "apply", str(repo / APP / "policies" / env / "policy.yaml"), "--resource", str(f)], capture_output=True, text=True)
    return out.returncode == 0 and "fail: 0" in out.stdout and "error: 0" in out.stdout, out.stdout + out.stderr


def good_deployment(repo, env="dev"):
    d = yaml.safe_load((repo / APP / "overlays" / env / "todo-api" / "deployment.yaml").read_text())
    d["spec"]["template"]["spec"]["containers"][0]["image"] = "ghcr.io/acme/todo-api:sha-abc1234"
    return d


MUTATIONS = {
    "root user": ("non-root", lambda c, p, d: c["securityContext"].update(runAsUser=0)),
    "writable root fs": ("readOnlyRootFilesystem", lambda c, p, d: c["securityContext"].update(readOnlyRootFilesystem=False)),
    "privilege escalation": ("allowPrivilegeEscalation", lambda c, p, d: c["securityContext"].update(allowPrivilegeEscalation=True)),
    "capabilities kept": ("drop ALL", lambda c, p, d: c["securityContext"].pop("capabilities")),
    "privileged": ("privileged containers", lambda c, p, d: c["securityContext"].update(privileged=True)),
    "host network": ("privileged containers", lambda c, p, d: p.update(hostNetwork=True)),
    "hostPath": ("hostPath", lambda c, p, d: p.update(volumes=[{"name": "h", "hostPath": {"path": "/"}}])),
    "no memory limit": ("requests and a memory limit", lambda c, p, d: c.pop("resources")),
    "no part-of label": ("part-of", lambda c, p, d: d["metadata"]["labels"].pop("app.kubernetes.io/part-of")),
    "foreign registry": ("allowed registry", lambda c, p, d: c.update(image="docker.io/evil/x:1")),
}


@needs_kyverno
def test_a_rendered_deployment_passes_and_each_violation_is_caught(tmp_path, gitops_repo, gh):
    cfg(gitops_repo, ON)
    run_compose(gitops_repo, "add", "todo-api")
    ok, out = evaluate(tmp_path, gitops_repo, good_deployment(gitops_repo))
    assert ok, out
    for name, (expect, mutate) in MUTATIONS.items():
        d = copy.deepcopy(good_deployment(gitops_repo))
        mutate(d["spec"]["template"]["spec"]["containers"][0], d["spec"]["template"]["spec"], d)
        ok, out = evaluate(tmp_path, gitops_repo, d)
        assert not ok and expect in out, f"{name}: expected a violation mentioning '{expect}'\n{out}"


@needs_kyverno
def test_latest_and_untagged_images_fail_outside_dev(tmp_path, gitops_repo, gh):
    cfg(gitops_repo, ON)
    run_compose(gitops_repo, "add", "todo-api")
    set_envs(gitops_repo, ["dev", "staging"])
    assert render(gitops_repo).returncode == 0
    for image in ("ghcr.io/acme/todo-api:latest", "ghcr.io/acme/todo-api"):
        d = good_deployment(gitops_repo, "staging")
        d["spec"]["template"]["spec"]["containers"][0]["image"] = image
        ok, out = evaluate(tmp_path, gitops_repo, d, "staging")
        assert not ok and "latest" in out, image
    ok, out = evaluate(tmp_path, gitops_repo, good_deployment(gitops_repo, "staging"), "staging")
    assert ok, out


@needs_kyverno
def test_the_otel_collector_satisfies_the_guard_rails(tmp_path, gitops_repo, gh):
    cfg(gitops_repo, ON, observability={})
    run_compose(gitops_repo, "add", "todo-api")
    dep = yaml.safe_load((gitops_repo / APP / "addons/dev/observability/collector.yaml").read_text())
    ok, out = evaluate(tmp_path, gitops_repo, dep)
    assert ok, out
