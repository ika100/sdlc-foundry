"""Spec 182 acceptance tests, the renderer part: the environment's collector reads pod logs through the Kubernetes API with a log tailer
(AC-182.1 wiring, AC-182.3, AC-182.4).

Contract: docs/specs/182-logs-reach-loki/design.md "Rendered files". The renderer runs as a script in a hand-built checkout; nothing
touches a cluster. The tailer's behaviour is in test_log_tailer_182.py. A test names its criterion in a `# AC-182.n` comment."""
import copy
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest
import yaml

from resources_fixtures import APP, ok, system, tree
from system_fixtures import RENDER5, ROOT, render, write_system

OBS = f"{APP}/addons/dev/observability"
NS = "shop-dev"
BASELINE_COMMIT = "362b29ce"   # the commit before spec 182: the renderer as it was
NEW_FILES = ["serviceaccount.yaml", "role.yaml", "rolebinding.yaml", "tailer-configmap.yaml"]
EIGHT = sorted(["configmap.yaml", "collector.yaml", "service.yaml", "kustomization.yaml", *NEW_FILES])


def load_render():
    spec = importlib.util.spec_from_file_location("render_under_test_182", RENDER5)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def obs_system(ui="lgtm", policy="enforce"):
    doc = system()
    doc["environments"]["dev"]["observability"] = {"ui": ui} if ui else {}
    doc["environments"]["dev"]["policy"] = policy
    return doc


def y(g, name):
    return yaml.safe_load(g[f"{OBS}/{name}"])


def collector_pod(g):
    return y(g, "collector.yaml")["spec"]["template"]["spec"]


def tailer(g):
    return {c["name"]: c for c in collector_pod(g)["containers"]}["log-tailer"]


@pytest.fixture(scope="module")
def on(tmp_path_factory):
    return ok(tmp_path_factory.mktemp("obs-on"), obs_system())


# ---------------- AC-182.3: the access is namespaced and read-only ----------------

def test_the_observability_addon_renders_eight_sorted_files_ac_182_3(on):  # AC-182.3
    names = sorted(k.rsplit("/", 1)[1] for k in on if k.startswith(OBS + "/"))
    assert names == EIGHT
    assert y(on, "kustomization.yaml")["resources"] == [n for n in EIGHT if n != "kustomization.yaml"], "every other file, sorted"


def test_the_collector_has_its_own_service_account_without_a_mounted_token_ac_182_3(on):  # AC-182.3
    sa = y(on, "serviceaccount.yaml")
    assert (sa["kind"], sa["metadata"]["name"]) == ("ServiceAccount", "otel-collector")
    assert sa["automountServiceAccountToken"] is False
    assert sa["metadata"]["labels"]["app.kubernetes.io/name"] == "otel-collector"


def test_the_role_reads_only_pods_and_pod_logs_ac_182_3(on):  # AC-182.3
    role = y(on, "role.yaml")
    assert (role["kind"], role["metadata"]["name"]) == ("Role", "otel-collector-logs")
    assert role["rules"] == [{"apiGroups": [""], "resources": ["pods"], "verbs": ["get", "list", "watch"]},
                             {"apiGroups": [""], "resources": ["pods/log"], "verbs": ["get"]}]


def test_the_role_binding_binds_the_service_account_in_its_own_namespace_ac_182_3(on):  # AC-182.3
    rb = y(on, "rolebinding.yaml")
    assert (rb["kind"], rb["metadata"]["name"]) == ("RoleBinding", "otel-collector-logs")
    assert rb["roleRef"]["kind"] == "Role" and rb["roleRef"]["name"] == "otel-collector-logs"
    assert rb["subjects"] == [{"kind": "ServiceAccount", "name": "otel-collector", "namespace": NS}]


def test_no_cluster_wide_role_no_daemon_set_no_host_path_ac_182_3(on):  # AC-182.3
    assert "serviceaccount.yaml" in {k.rsplit("/", 1)[1] for k in on if k.startswith(OBS + "/")}, "the namespaced access is rendered"
    for path, text in on.items():
        if not path.endswith((".yaml", ".yml")):
            continue
        for doc in yaml.safe_load_all(text):
            kind = (doc or {}).get("kind")
            assert kind not in ("ClusterRole", "ClusterRoleBinding", "DaemonSet"), f"{path} renders a {kind}"
            pod = (doc or {}).get("spec", {})                    # no workload mounts a host path (the policy text may name it)
            pod = pod.get("jobTemplate", {}).get("spec", pod).get("template", {}).get("spec", pod) if isinstance(pod, dict) else {}
            vols = pod.get("volumes", []) if isinstance(pod, dict) else []
            assert not [v for v in vols or [] if isinstance(v, dict) and "hostPath" in v], f"{path} mounts a host path"


def test_the_collector_pod_uses_the_service_account_and_mounts_no_default_token_ac_182_3(on):  # AC-182.3
    pod = collector_pod(on)
    assert pod["serviceAccountName"] == "otel-collector"
    assert pod["automountServiceAccountToken"] is False
    assert "checksum/tailer" in y(on, "collector.yaml")["spec"]["template"]["metadata"]["annotations"]


def test_the_tailer_container_is_unprivileged_and_reads_only_what_it_needs_ac_182_3(on):  # AC-182.3
    c = tailer(on)
    render = load_render()
    assert c["image"] == render.CREDENTIALS_IMAGE
    assert c["command"] == ["python3", "/tailer/tail.py"]
    assert c["securityContext"] == {"runAsNonRoot": True, "runAsUser": 65534, "allowPrivilegeEscalation": False,
                                    "readOnlyRootFilesystem": True, "capabilities": {"drop": ["ALL"]}}
    assert c["resources"]["requests"]["cpu"] and c["resources"]["requests"]["memory"] and c["resources"]["limits"]["memory"]
    mounts = {m["name"]: m for m in c["volumeMounts"]}
    assert mounts["tailer"]["mountPath"] == "/tailer" and mounts["tailer"]["readOnly"] is True
    assert mounts["sa-token"]["mountPath"] == "/var/run/secrets/kubernetes.io/serviceaccount" and mounts["sa-token"]["readOnly"] is True


def test_the_tailer_environment_names_its_namespace_pod_environment_system_and_target_ac_182_1(on):  # AC-182.1
    env = {e["name"]: e for e in tailer(on)["env"]}
    assert env["PYTHONDONTWRITEBYTECODE"]["value"] == "1"
    assert env["TAILER_NAMESPACE"]["valueFrom"]["fieldRef"]["fieldPath"] == "metadata.namespace"
    assert env["TAILER_POD"]["valueFrom"]["fieldRef"]["fieldPath"] == "metadata.name"
    assert env["TAILER_ENVIRONMENT"]["value"] == "dev"
    assert env["TAILER_SYSTEM"]["value"] == "shop"
    assert env["TAILER_OTLP_URL"]["value"] == "http://127.0.0.1:4318/v1/logs"


def test_the_collector_container_is_unchanged_and_only_the_tailer_mounts_the_token_ac_182_3(on):  # AC-182.3
    pod = collector_pod(on)
    by = {c["name"]: c for c in pod["containers"]}
    assert set(by) == {"collector", "log-tailer"}
    assert [m["name"] for m in by["collector"]["volumeMounts"]] == ["conf"]
    vols = {v["name"]: v for v in pod["volumes"]}
    assert vols["tailer"]["configMap"]["name"] == "otel-collector-tailer"
    proj = vols["sa-token"]["projected"]["sources"]
    assert any(s.get("serviceAccountToken", {}).get("path") == "token" for s in proj)
    assert any(s.get("configMap", {}).get("name") == "kube-root-ca.crt" for s in proj)
    assert any("downwardAPI" in s for s in proj)


def test_the_tailer_script_is_shipped_byte_equal_in_a_config_map_ac_182_3(on):  # AC-182.3
    render = load_render()
    cm = y(on, "tailer-configmap.yaml")
    assert (cm["kind"], cm["metadata"]["name"]) == ("ConfigMap", "otel-collector-tailer")
    assert cm["data"]["tail.py"] == render.LOG_TAILER_SCRIPT
    ann = y(on, "collector.yaml")["spec"]["template"]["metadata"]["annotations"]
    assert ann["checksum/tailer"] == hashlib.sha256(render.LOG_TAILER_SCRIPT.encode()).hexdigest()[:16]


def test_the_guard_rail_policy_admits_the_tailer_image_in_enforce_ac_182_3(on):  # AC-182.3
    render = load_render()
    pol = yaml.safe_load(on[f"{APP}/policies/dev/policy.yaml"])
    assert pol["spec"]["validationActions"] in (["Enforce"], ["Deny"])
    regs = json.loads({v["name"]: v for v in pol["spec"]["variables"]}["registries"]["expression"])
    image = render.CREDENTIALS_IMAGE
    assert any(image.startswith(r) for r in regs), f"{image} is not under any of {regs}"
    assert render.CREDENTIALS_IMAGE.split("@")[0] in regs


def test_every_tailer_object_carries_the_collector_labels_ac_182_3(on):  # AC-182.3
    for name in NEW_FILES:
        labels = y(on, name)["metadata"]["labels"]
        assert labels["app.kubernetes.io/name"] == "otel-collector"
        assert labels["app.kubernetes.io/part-of"] == "shop"
        assert labels["app.kubernetes.io/managed-by"] == "gitops-app"


# ---------------- AC-182.4: off is unchanged, on skips the collector ----------------

def test_without_observability_nothing_about_log_collection_is_rendered_ac_182_4(tmp_path):  # AC-182.4
    doc = obs_system()
    del doc["environments"]["dev"]["observability"]
    g = ok(tmp_path, doc)
    assert not [k for k in g if "/observability/" in k]
    for text in g.values():
        assert "otel-collector" not in text and "log-tailer" not in text
    pol = yaml.safe_load(g[f"{APP}/policies/dev/policy.yaml"])
    regs = json.loads({v["name"]: v for v in pol["spec"]["variables"]}["registries"]["expression"])
    assert load_render().CREDENTIALS_IMAGE.split("@")[0] not in regs


def test_the_render_with_observability_off_is_byte_identical_to_the_render_before_this_change_ac_182_4(tmp_path):  # AC-182.4
    probe = subprocess.run(["git", "show", f"{BASELINE_COMMIT}:templates/gitops-app/scripts/render.py"], cwd=ROOT, capture_output=True)
    if probe.returncode != 0:
        pytest.skip("the baseline commit is not in this clone")
    old = tmp_path / "old-render.py"
    old.write_bytes(probe.stdout)
    doc = obs_system()
    del doc["environments"]["dev"]["observability"]
    outs = []
    for name, script in (("before", old), ("after", RENDER5)):
        root = tmp_path / name
        root.mkdir()
        write_system(root, copy.deepcopy(doc))
        p = render(root, script=Path(script))
        assert p.returncode == 0, p.stderr
        outs.append(tree(root))
    assert outs[0] == outs[1]
    assert outs[0], "the render wrote files"


def test_the_collector_tailer_never_collects_its_own_pod_ac_182_4(on):  # AC-182.4
    pod_label = y(on, "collector.yaml")["spec"]["template"]["metadata"]["labels"]
    assert pod_label["app.kubernetes.io/name"] == "otel-collector", "the label the tailer skips is on the collector's pod"
    assert {e["name"] for e in tailer(on)["env"]} >= {"TAILER_POD", "TAILER_NAMESPACE"}, "the tailer knows its own pod"
