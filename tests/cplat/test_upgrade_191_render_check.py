"""Spec 191 acceptance tests, the upgrade render check: the breaking rules, the OK line, the exit codes and the `Upgrade step:` acceptance
(AC-191.1, AC-191.2, AC-191.3), and the run mode's script text (AC-191.4).

Contract: design.md "Contract", `scripts/upgrade-render-check.py compare`. Each side is a small fixture repo: `src/` holds the YAML an
environment gets, and its own `scripts/render.py` copies `src/` to `applications/shop/` (the renderer of that release). The platform checkout
(`--repo`) is a directory with `docs/CHANGELOG.md` and `docs/changelog.d/`. Assertions read lines and the exit code, never a whole output.
Nothing here needs docker, k3d or the network."""
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from system_fixtures import ROOT

SCRIPT = ROOT / "scripts" / "upgrade-render-check.py"
TAG = "v5.3.0"
RENDER_PY = """import shutil, sys
from pathlib import Path
root = Path(__file__).resolve().parent.parent
if (root / "FAIL").is_file():
    print("starting the render")
    print((root / "FAIL").read_text().strip(), file=sys.stderr)
    sys.exit(1)
dest = root / "applications" / "shop"
shutil.copytree(root / "src", dest, dirs_exist_ok=True)
"""
ENVS = ("dev", "staging", "prod")


def K(kind, name, spec=None, api="v1", namespace=None, **top):
    meta = {"name": name, **({"namespace": namespace} if namespace else {}), **top.pop("metadata", {})}
    return {"apiVersion": api, "kind": kind, "metadata": meta, **({"spec": spec} if spec is not None else {}), **top}


def sel(app):
    return {"selector": {"matchLabels": {"app": app}}}


def with_image(app, image):
    return {**sel(app), "template": {"spec": {"containers": [{"name": "c", "image": image}]}}}


def vct(size):
    return [{"metadata": {"name": "data"}, "spec": {"resources": {"requests": {"storage": size}}}}]


CNPG = "postgresql.cnpg.io/v1"


def make_repo(root: Path, items, extra=None, fail=None) -> Path:
    """items: (env, doc) or (env, doc, folder); extra: {path under applications/shop: text}."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "scripts").mkdir()
    (root / "scripts" / "render.py").write_text(RENDER_PY)
    if fail:
        (root / "FAIL").write_text(fail)
    base = root / "src"
    (base / "system.yaml").parent.mkdir(parents=True, exist_ok=True)
    (base / "system.yaml").write_text("name: shop\n")
    for it in items:
        env, doc, folder = (*it, "overlays")[:3]
        path = base / folder / env / f"{doc['kind']}-{doc['metadata']['name']}.yaml".lower()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(doc))
    for rel, text in (extra or {}).items():
        (base / rel).parent.mkdir(parents=True, exist_ok=True)
        (base / rel).write_text(text)
    return root


def make_platform(root: Path, unreleased="", released=None, fragments=None) -> Path:
    (root / "docs" / "changelog.d").mkdir(parents=True)
    text = "# CHANGELOG\n\n## [Unreleased]\n\n" + unreleased + "\n"
    for version, body in (released or {}).items():
        text += f"\n## [{version}] — 2026-10-28\n\n{body}\n"
    (root / "docs" / "CHANGELOG.md").write_text(text + "\n## [5.3.0] — 2026-10-27\n\nthe base\n")
    for name, body in (fragments or {}).items():
        (root / "docs" / "changelog.d" / name).write_text(body)
    return root


def compare(tmp_path, before, after, plat=None, env=None, **repo_kw):
    b = make_repo(tmp_path / "before", before, **({"fail": repo_kw["fail_before"]} if "fail_before" in repo_kw else {}))
    a = make_repo(tmp_path / "after", after, **({"fail": repo_kw["fail_after"]} if "fail_after" in repo_kw else {}))
    plat = plat or make_platform(tmp_path / "platform")
    p = subprocess.run([sys.executable, str(SCRIPT), "compare", "--from-tag", TAG, "--repo", str(plat), str(b), str(a)],
                       capture_output=True, text=True, timeout=300, env={**os.environ, **(env or {})})
    return p.returncode, (p.stdout + p.stderr).splitlines()


def j(v):
    return v if isinstance(v, str) else json.dumps(v, sort_keys=True, separators=(",", ":"))


HINT = ' (accept it with a changelog line "Upgrade step: {kind} {field}: ...")'
IMMUTABLE = "immutable: Kubernetes refuses the change"


def breaking(env, kind, ns, name, field, old, new, reason=IMMUTABLE):
    return f"BREAKING {env} {kind} {ns}/{name} {field}: {j(old)} -> {j(new)} ({reason})" + HINT.format(kind=kind, field=field)


# ---------------- AC-191.1: the breaking rules ----------------

CHANGES = [
    ("deployment-selector", K("Deployment", "w", sel("x"), "apps/v1"), K("Deployment", "w", sel("y"), "apps/v1"),
     "Deployment", "spec.selector", {"matchLabels": {"app": "x"}}, {"matchLabels": {"app": "y"}}),
    ("statefulset-selector", K("StatefulSet", "w", sel("x"), "apps/v1"), K("StatefulSet", "w", sel("y"), "apps/v1"),
     "StatefulSet", "spec.selector", {"matchLabels": {"app": "x"}}, {"matchLabels": {"app": "y"}}),
    ("daemonset-selector", K("DaemonSet", "w", sel("x"), "apps/v1"), K("DaemonSet", "w", sel("y"), "apps/v1"),
     "DaemonSet", "spec.selector", {"matchLabels": {"app": "x"}}, {"matchLabels": {"app": "y"}}),
    ("job-selector", K("Job", "w", sel("x"), "batch/v1"), K("Job", "w", sel("y"), "batch/v1"),
     "Job", "spec.selector", {"matchLabels": {"app": "x"}}, {"matchLabels": {"app": "y"}}),
    ("statefulset-claim-templates", K("StatefulSet", "w", {"volumeClaimTemplates": vct("1Gi")}, "apps/v1"),
     K("StatefulSet", "w", {"volumeClaimTemplates": vct("2Gi")}, "apps/v1"),
     "StatefulSet", "spec.volumeClaimTemplates", vct("1Gi"), vct("2Gi")),
    ("statefulset-service-name", K("StatefulSet", "w", {"serviceName": "a"}, "apps/v1"), K("StatefulSet", "w", {"serviceName": "b"}, "apps/v1"),
     "StatefulSet", "spec.serviceName", "a", "b"),
    ("pvc-storage-class", K("PersistentVolumeClaim", "w", {"storageClassName": "fast"}), K("PersistentVolumeClaim", "w", {"storageClassName": "slow"}),
     "PersistentVolumeClaim", "spec.storageClassName", "fast", "slow"),
    ("pvc-access-modes", K("PersistentVolumeClaim", "w", {"accessModes": ["ReadWriteOnce"]}),
     K("PersistentVolumeClaim", "w", {"accessModes": ["ReadWriteMany"]}),
     "PersistentVolumeClaim", "spec.accessModes", ["ReadWriteOnce"], ["ReadWriteMany"]),
    ("pvc-smaller", K("PersistentVolumeClaim", "w", {"resources": {"requests": {"storage": "10Gi"}}}),
     K("PersistentVolumeClaim", "w", {"resources": {"requests": {"storage": "5Gi"}}}),
     "PersistentVolumeClaim", "spec.resources.requests.storage", "10Gi", "5Gi"),
    ("pvc-smaller-across-suffixes", K("PersistentVolumeClaim", "w", {"resources": {"requests": {"storage": "1Ti"}}}),
     K("PersistentVolumeClaim", "w", {"resources": {"requests": {"storage": "900Gi"}}}),
     "PersistentVolumeClaim", "spec.resources.requests.storage", "1Ti", "900Gi"),
    ("cluster-storage-class", K("Cluster", "w", {"storage": {"storageClass": "fast", "size": "10Gi"}}, CNPG),
     K("Cluster", "w", {"storage": {"storageClass": "slow", "size": "10Gi"}}, CNPG),
     "Cluster", "spec.storage.storageClass", "fast", "slow"),
    ("cluster-smaller", K("Cluster", "w", {"storage": {"size": "10Gi"}}, CNPG), K("Cluster", "w", {"storage": {"size": "5Gi"}}, CNPG),
     "Cluster", "spec.storage.size", "10Gi", "5Gi"),
    ("service-cluster-ip", K("Service", "w", {"clusterIP": "10.0.0.1"}), K("Service", "w", {"clusterIP": "10.0.0.2"}),
     "Service", "spec.clusterIP", "10.0.0.1", "10.0.0.2"),
    ("service-type", K("Service", "w", {"type": "ClusterIP"}), K("Service", "w", {"type": "NodePort"}),
     "Service", "spec.type", "ClusterIP", "NodePort"),
]


@pytest.mark.parametrize("old, new, kind, field, was, now", [c[1:] for c in CHANGES], ids=[c[0] for c in CHANGES])
def test_a_change_kubernetes_refuses_is_reported_as_one_breaking_line_ac_191_1(tmp_path, old, new, kind, field, was, now):  # AC-191.1
    rc, lines = compare(tmp_path, [("dev", old)], [("dev", new)])
    assert rc == 1, lines
    assert [ln for ln in lines if ln.startswith("BREAKING")] == [breaking("dev", kind, "shop-dev", "w", field, was, now)], lines
    assert lines[-1] == f"FAILED: 1 breaking change(s), {TAG} -> candidate", lines


REMOVALS = [
    ("pvc", K("PersistentVolumeClaim", "data", {"resources": {"requests": {"storage": "1Gi"}}}), "PersistentVolumeClaim", "data"),
    ("externalsecret", K("ExternalSecret", "creds", {"target": {"name": "creds"}}, "external-secrets.io/v1"), "ExternalSecret", "creds"),
    ("cluster", K("Cluster", "db", {"storage": {"size": "1Gi"}}, CNPG), "Cluster", "db"),
    ("statefulset-with-claims", K("StatefulSet", "cache", {"volumeClaimTemplates": vct("1Gi")}, "apps/v1"), "StatefulSet", "cache"),
    ("secret", K("Secret", "token", None, data={"k": "dg=="}), "Secret", "token"),
]


@pytest.mark.parametrize("old, kind, name", [r[1:] for r in REMOVALS], ids=[r[0] for r in REMOVALS])
def test_an_object_that_holds_data_and_is_gone_is_reported_as_loses_data_ac_191_1(tmp_path, old, kind, name):  # AC-191.1
    rc, lines = compare(tmp_path, [("dev", old), ("dev", K("ConfigMap", "keep"))], [("dev", K("ConfigMap", "keep"))])
    assert rc == 1, lines
    assert [ln for ln in lines if ln.startswith("BREAKING")] == [breaking("dev", kind, "shop-dev", name, "object", "present", "removed", "loses data")], lines
    assert lines[-1] == f"FAILED: 1 breaking change(s), {TAG} -> candidate"


def test_a_renamed_claim_counts_as_removed_ac_191_1(tmp_path):  # AC-191.1
    old = K("PersistentVolumeClaim", "data", {"resources": {"requests": {"storage": "1Gi"}}})
    new = K("PersistentVolumeClaim", "data-v2", {"resources": {"requests": {"storage": "1Gi"}}})
    rc, lines = compare(tmp_path, [("dev", old)], [("dev", new)])
    assert rc == 1
    assert [ln for ln in lines if ln.startswith("BREAKING")] == [breaking("dev", "PersistentVolumeClaim", "shop-dev", "data", "object", "present", "removed", "loses data")]


def plan_map(*names):
    plan = {"secrets": [{"name": n, "data": {"k": "v"}} for n in names]}
    return K("ConfigMap", "db-credentials", None, data={"create.py": "pass\n", "plan.json": json.dumps(plan)})


def test_a_generated_secret_that_the_credentials_plan_no_longer_names_is_reported_ac_191_1(tmp_path):  # AC-191.1
    folder = "addons"
    rc, lines = compare(tmp_path, [("dev", plan_map("shop-db-app", "shop-db-admin"), folder)], [("dev", plan_map("shop-db-app-v2", "shop-db-admin"), folder)])
    assert rc == 1, lines
    assert [ln for ln in lines if ln.startswith("BREAKING")] == [breaking("dev", "Secret", "shop-dev", "shop-db-app", "object", "present", "removed", "loses data")], lines


def test_the_namespace_comes_from_the_object_else_the_nearest_kustomization_else_system_env_ac_191_1(tmp_path):  # AC-191.1
    a, b = K("Deployment", "k", sel("x"), "apps/v1"), K("Deployment", "k", sel("y"), "apps/v1")
    c, d = K("Deployment", "e", sel("x"), "apps/v1", namespace="explicit"), K("Deployment", "e", sel("y"), "apps/v1", namespace="explicit")
    kust = {"overlays/dev/kustomization.yaml": "namespace: custom-ns\nresources: []\n"}
    b_repo = make_repo(tmp_path / "before", [("dev", a), ("dev", c)], extra=kust)
    a_repo = make_repo(tmp_path / "after", [("dev", b), ("dev", d)], extra=kust)
    plat = make_platform(tmp_path / "platform")
    p = subprocess.run([sys.executable, str(SCRIPT), "compare", "--from-tag", TAG, "--repo", str(plat), str(b_repo), str(a_repo)],
                       capture_output=True, text=True, timeout=300)
    names = [ln.split()[3] for ln in p.stdout.splitlines() if ln.startswith("BREAKING")]
    assert sorted(names) == ["custom-ns/k", "explicit/e"], p.stdout


def test_findings_are_sorted_by_environment_then_object_and_counted_ac_191_1(tmp_path):  # AC-191.1
    old = [("prod", K("Deployment", "w", sel("x"), "apps/v1")), ("dev", K("Deployment", "w", sel("x"), "apps/v1")), ("staging", K("Service", "s", {"type": "ClusterIP"}))]
    new = [("prod", K("Deployment", "w", sel("y"), "apps/v1")), ("dev", K("Deployment", "w", sel("y"), "apps/v1")), ("staging", K("Service", "s", {"type": "NodePort"}))]
    rc, lines = compare(tmp_path, old, new)
    assert rc == 1
    assert [ln.split()[1] for ln in lines if ln.startswith("BREAKING")] == ["dev", "staging", "prod"]
    assert lines[-1] == f"FAILED: 3 breaking change(s), {TAG} -> candidate"


# ---------------- AC-191.2: no breaking change, and a render that fails ----------------

def base_items():
    out = [("dev", K("Deployment", "api", with_image("api", "img:1"), "apps/v1", metadata={"labels": {"a": "1"}})),
           ("dev", K("StatefulSet", "db", {"serviceName": "db"}, "apps/v1")),
           ("dev", K("PersistentVolumeClaim", "data", {"resources": {"requests": {"storage": "10Gi"}}})),
           ("dev", K("Service", "svc", {"type": "ClusterIP"})),
           ("dev", K("ConfigMap", "cfg")), ("dev", K("Deployment", "gone", sel("g"), "apps/v1")), ("dev", K("Service", "gone-svc", {"type": "ClusterIP"})),
           ("staging", K("Deployment", "api", sel("api"), "apps/v1")), ("prod", K("Deployment", "api", sel("api"), "apps/v1"))]
    return out


def harmless_after():
    return [("dev", K("Deployment", "api", with_image("api", "img:2"), "apps/v1", metadata={"labels": {"a": "2", "b": "x"}, "annotations": {"n": "1"}})),
            ("dev", K("PersistentVolumeClaim", "data", {"resources": {"requests": {"storage": "20Gi"}}})),
            ("dev", K("Service", "svc", {"type": "ClusterIP", "clusterIP": "10.0.0.9"})),
            ("dev", K("ConfigMap", "new")), ("dev", K("Cluster", "fresh", {"storage": {"size": "1Gi"}}, CNPG)),
            ("staging", K("Deployment", "api", sel("api"), "apps/v1")), ("prod", K("Deployment", "api", sel("api"), "apps/v1"))]


def fake_runtime(tmp_path):
    """docker, podman, k3d and kubectl that record a call and fail: a check that needs one leaves the marker."""
    bin_dir, marker = tmp_path / "fakebin", tmp_path / "runtime-called"
    bin_dir.mkdir()
    for tool in ("docker", "podman", "k3d", "kubectl"):
        f = bin_dir / tool
        f.write_text(f"#!/bin/sh\ntouch {marker}\nexit 99\n")
        f.chmod(f.stat().st_mode | stat.S_IEXEC)
    return {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}, marker


def test_harmless_differences_pass_with_the_ok_line_and_no_container_runtime_ac_191_2(tmp_path):  # AC-191.2
    env, marker = fake_runtime(tmp_path)
    rc, lines = compare(tmp_path, base_items(), harmless_after(), env=env)
    assert rc == 0, lines
    assert lines[-1] == f"OK: 9 objects in dev, staging, prod compared, {TAG} -> candidate, no breaking change", lines
    assert not [ln for ln in lines if ln.startswith("BREAKING")]
    assert not marker.exists(), "the check called a container runtime or a cluster"


@pytest.mark.parametrize("side, kw, want", [
    ("from-release", "fail_before", f"ERROR: from-release {TAG} does not render: boom: bad template"),
    ("candidate", "fail_after", "ERROR: candidate does not render: boom: bad template"),
])
def test_a_side_that_does_not_render_exits_2_naming_the_side_and_the_error_ac_191_2(tmp_path, side, kw, want):  # AC-191.2
    rc, lines = compare(tmp_path, base_items(), base_items(), **{kw: "boom: bad template"})
    assert rc == 2, lines
    assert lines[-1] == want, lines


# ---------------- AC-191.3: Upgrade step lines accept a finding ----------------

SEL_OLD, SEL_NEW = [("dev", K("Deployment", "w", sel("x"), "apps/v1"))], [("dev", K("Deployment", "w", sel("y"), "apps/v1"))]
STEP = "Upgrade step: Deployment spec.selector: delete the Deployment w once, Argo CD recreates it"
ACCEPTED = "ACCEPTED dev Deployment shop-dev/w spec.selector (upgrade step: delete the Deployment w once, Argo CD recreates it)"


@pytest.mark.parametrize("where", ["fragment", "unreleased", "released-after-tag"])
def test_a_matching_upgrade_step_line_accepts_the_finding_ac_191_3(tmp_path, where):  # AC-191.3
    kw = {"fragment": {"fragments": {"191-x.changed.md": f"**Changed.** (#1).\n\n- {STEP}\n"}},
          "unreleased": {"unreleased": f"### Changed\n\n- {STEP}\n"},
          "released-after-tag": {"released": {"5.4.0": f"### Changed\n\n- {STEP}\n"}}}[where]
    rc, lines = compare(tmp_path, SEL_OLD, SEL_NEW, plat=make_platform(tmp_path / "platform", **kw))
    assert rc == 0, lines
    assert ACCEPTED in lines, lines
    assert not [ln for ln in lines if ln.startswith("BREAKING")]
    assert lines[-1].startswith("OK: ") and lines[-1].endswith("no breaking change (1 accepted)"), lines


def test_a_line_in_a_release_not_after_the_from_release_does_not_accept_ac_191_3(tmp_path):  # AC-191.3
    plat = make_platform(tmp_path / "platform")
    text = (plat / "docs" / "CHANGELOG.md").read_text().replace("the base", f"- {STEP}")
    (plat / "docs" / "CHANGELOG.md").write_text(text)
    rc, lines = compare(tmp_path, SEL_OLD, SEL_NEW, plat=plat)
    assert rc == 1 and not [ln for ln in lines if ln.startswith("ACCEPTED")], lines


def test_an_unaccepted_finding_fails_and_ends_with_the_accept_hint_ac_191_3(tmp_path):  # AC-191.3
    other = "Upgrade step: Deployment spec.template: not the same field"
    plat = make_platform(tmp_path / "platform", fragments={"191-x.changed.md": f"- {other}\n"})
    rc, lines = compare(tmp_path, SEL_OLD, SEL_NEW, plat=plat)
    assert rc == 1, lines
    found = [ln for ln in lines if ln.startswith("BREAKING")]
    assert len(found) == 1 and found[0].endswith('(accept it with a changelog line "Upgrade step: Deployment spec.selector: ...")'), lines
    assert lines[-1] == f"FAILED: 1 breaking change(s), {TAG} -> candidate"


def test_a_step_accepts_its_kind_and_field_for_every_object_and_environment_ac_191_3(tmp_path):  # AC-191.3
    old = SEL_OLD + [("prod", K("Deployment", "z", sel("x"), "apps/v1")), ("prod", K("Service", "s", {"type": "ClusterIP"}))]
    new = SEL_NEW + [("prod", K("Deployment", "z", sel("y"), "apps/v1")), ("prod", K("Service", "s", {"type": "NodePort"}))]
    plat = make_platform(tmp_path / "platform", fragments={"191-x.changed.md": f"- {STEP}\n"})
    rc, lines = compare(tmp_path, old, new, plat=plat)
    accepted = [ln.split()[1:4] for ln in lines if ln.startswith("ACCEPTED")]
    assert accepted == [["dev", "Deployment", "shop-dev/w"], ["prod", "Deployment", "shop-prod/z"]], lines
    assert rc == 1 and lines[-1] == f"FAILED: 1 breaking change(s), {TAG} -> candidate", lines


# ---------------- AC-191.4: the run mode (script text; it needs git tags, uv and copier) ----------------

def test_the_run_mode_compares_from_both_releases_each_in_its_section_ac_191_4():  # AC-191.4
    assert SCRIPT.is_file(), "scripts/upgrade-render-check.py exists"
    text = SCRIPT.read_text()
    for needle in ("from-tag", "previous", "oldest", "compared once", "oldest supported release: skipped:", "upgrade render check: OK",
                   "upgrade render check: FAILED", "--from", "--work", "upgrade-system.sh", "does not render"):
        assert needle in text, f"upgrade-render-check.py lacks {needle!r}"
    assert not re.search(r"\bdocker\b|\bk3d\b|local-cluster", text.replace("container runtime", "")), "no container runtime"
