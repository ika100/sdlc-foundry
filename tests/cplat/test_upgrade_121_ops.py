"""Spec 121 acceptance tests, operators and releases: doctor (AC-121.18, .19, .21, .22), the cluster scripts (AC-121.4, .17), the pin check
(AC-121.2), the release check and gate (AC-121.23, .24, .26), the workflows and the upgrade e2e script text (AC-121.8, .11, .17, .21, .22,
.24, .25), and the docs, plugins and changelog (AC-121.6, .17 .. .19, .23).

Contract: design.md "Contract: doctor", "Contract: local cluster", "Contract: pin check and release check", "Contract: the upgrade e2e".
Doctor runs through `doctor.main` with its `run` seam replaced by a fake cluster (selectors and the CRD read as design.md specifies); the
cluster script runs against fake k3d, kubectl, docker and gh binaries; the pin and release checks run in a throwaway copy of the platform
repository with a patched renderer; `gh` for the gate is a script on PATH. The upgrade e2e script is only read (it needs a cluster).
Domain-like names are matched with word-bounded regular expressions, never with `"a.b.c" in text`."""
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import cplat
from broker_fixtures import broker, bsys
from resources_fixtures import comp, db, system
from system_fixtures import ROOT, git, write_system
from upgrade_fixtures import CLUSTER_PINS, CTX, LGTM, NATS, VELERO_PLUGIN, doc_with_everything, render_module

T = ROOT / "templates" / "gitops-app"
CLUSTER_T = ROOT / "templates" / "cluster-gitops"


# ---------------- doctor (AC-121.18, .19, .21, .22) ----------------

CRD_KIND = "customresourcedefinitions.apiextensions.k8s.io"


class Cluster:
    """What doctor's kubectl sees: Deployments by selector (an image), CRDs by name (their served versions); `calls` records argv."""

    def __init__(self):
        self.deploys: dict[str, str] = {}
        self.crds: dict[str, list[str]] = {}
        self.calls: list[list[str]] = []

    @staticmethod
    def selector(op) -> str:
        return op.get("selector") or f"app.kubernetes.io/name={op['chart']}"

    def install(self, only=None):
        for n, op in render_module("render_121_doc").OPERATORS.items():
            if only is None or n in only:
                self.deploys[self.selector(op)] = f"registry.example/{op['chart']}:v{op['operator_version']}"
                self.crds.update({c: list(v) for c, v in (op.get("crds") or {}).items()})
        return self

    def op(self, name, version):
        op = render_module("render_121_doc2").OPERATORS[name]
        self.deploys[self.selector(op)] = f"registry.example/{op['chart']}:v{version}"
        return self


def ctx_of(cmd):
    return cmd[cmd.index("--context") + 1] if "--context" in cmd else None


def doctor_world(tmp_path, monkeypatch, doc, **answers):
    import doctor
    import gates
    import notify_config
    from resources_fixtures import render5
    from system_fixtures import init_git
    render5(tmp_path, doc)        # not asserted: a renderer that rejects the system fails the tests that read the rows
    (tmp_path / ".copier-answers.yml").write_text(yaml.safe_dump({"_src_path": "gh:ika100/sdlc-foundry/templates/gitops-app", "github_org": "acme", **answers}))
    init_git(tmp_path)
    cl = Cluster()
    real_run = doctor.run

    def fake_run(cmd, *a, **k):
        cmd = [str(c) for c in cmd]
        if cmd[0] != "kubectl":
            return real_run(cmd, *a, **k)
        cl.calls.append(cmd)
        out = SimpleNamespace(stdout="", stderr="", returncode=0)
        if "-l" in cmd:
            out.stdout = cl.deploys.get(cmd[cmd.index("-l") + 1], "")
        elif any(arg == CRD_KIND for arg in cmd):      # an argv element (CodeQL reads `in` as URL sanitizing)
            name = cmd[next(i for i, arg in enumerate(cmd) if arg == CRD_KIND) + 1]
            if name in cl.crds:
                out.stdout = " ".join(cl.crds[name])
            else:
                out.returncode = 1
        elif "current-context" in cmd:
            out.stdout = CTX + "\n"
        return out

    monkeypatch.setattr(doctor, "run", fake_run)
    monkeypatch.setattr(doctor.shutil, "which", lambda t: f"/usr/bin/{t}")
    for fn in ("check_tools", "check_gh", "check_docker", "check_kube", "check_plugins", "check_platform_source", "check_migration", "check_gitops_token",
               "check_service_repos_token", "check_alerts_token", "check_retro_schedule", "check_kube_envs"):
        monkeypatch.setattr(doctor, fn, lambda *a, **k: [])
    monkeypatch.setattr(doctor, "check_run_store", lambda *a, **k: {"status": "ok", "name": "run store", "detail": "", "fix": None})
    monkeypatch.setattr(gates, "check_gates", lambda repo: [])
    monkeypatch.setattr(notify_config, "doctor_checks", lambda: [])
    return SimpleNamespace(repo=tmp_path, cluster=cl)


def doctor_rows(w, capsys, *extra, context=True):
    rc = cplat.main(["platform", "doctor", "--repo", str(w.repo), "--json", *(["--context", CTX] if context else []), *extra])
    rows = json.loads(capsys.readouterr().out)
    return rc, {r["name"]: r for r in rows}


def dbdoc(**top):
    return system({"orders-db": db(version=17)}, {"api": comp("api", ["orders-db"])}, **top)


def op_row(rows, name):
    return rows[f"operator {name}"]


def test_every_operator_row_carries_its_state_versions_crds_and_environments_in_json_ac_121_19(tmp_path, monkeypatch, capsys):  # AC-121.19
    w = doctor_world(tmp_path, monkeypatch, dbdoc())
    w.cluster.install(["cloudnative-pg"])
    rc, rows = doctor_rows(w, capsys)
    assert rc == 0
    o = op_row(rows, "cloudnative-pg")["operator"]
    crds = render_module("render_121_doc4").OPERATORS["cloudnative-pg"]["crds"]
    assert list(o) == ["state", "expected", "installed", "crds", "shared"]
    assert (o["state"], o["expected"], o["installed"]) == ("ok", "1.30.1", "1.30.1")
    assert o["crds"] == {c: {"expected": v, "served": v} for c, v in crds.items()} and o["shared"] == ["dev", "staging", "prod"]


def test_with_a_context_the_detail_lists_the_crds_and_who_shares_the_operator_ac_121_21(tmp_path, monkeypatch, capsys):  # AC-121.21
    w = doctor_world(tmp_path, monkeypatch, dbdoc())
    w.cluster.install(["cloudnative-pg"])
    rc, rows = doctor_rows(w, capsys)
    r = op_row(rows, "cloudnative-pg")
    assert r["status"] == "ok"
    assert r["detail"].startswith("ok: installed 1.30.1, expected 1.30.1 (Argo CD application operator-cloudnative-pg); crds ")
    assert re.search(r"\bclusters\.postgresql\.cnpg\.io v1\b", r["detail"]) and r["detail"].endswith("; shared by dev, staging, prod")
    assert any(ctx_of(c) == CTX for c in w.cluster.calls), "every read uses the given context"


def test_one_environment_means_no_shared_by_note_ac_121_21(tmp_path, monkeypatch, capsys):  # AC-121.21
    doc = dbdoc()
    doc["components"]["api"]["instances"] = {"dev": {}}
    w = doctor_world(tmp_path, monkeypatch, doc)
    w.cluster.install(["cloudnative-pg"])
    rc, rows = doctor_rows(w, capsys)
    r = op_row(rows, "cloudnative-pg")
    assert r["operator"]["shared"] == ["dev"] and "shared by" not in r["detail"]


def test_a_missing_operator_fails_and_exits_non_zero_with_a_context_ac_121_19(tmp_path, monkeypatch, capsys):  # AC-121.19
    w = doctor_world(tmp_path, monkeypatch, dbdoc())
    rc, rows = doctor_rows(w, capsys)
    r = op_row(rows, "cloudnative-pg")
    assert rc == 1 and r["status"] == "fail"
    assert r["operator"]["state"] == "missing" and r["operator"]["installed"] is None
    assert r["detail"].startswith("missing: installed none, expected 1.30.1 (Argo CD application operator-cloudnative-pg); crds ")
    assert re.search(r"\bclusters\.postgresql\.cnpg\.io missing\b", r["detail"])


def test_without_a_context_a_missing_operator_stays_a_warning_with_the_old_text_ac_121_19(tmp_path, monkeypatch, capsys):  # AC-121.19
    w = doctor_world(tmp_path, monkeypatch, dbdoc())
    rc, rows = doctor_rows(w, capsys, context=False)
    r = op_row(rows, "cloudnative-pg")
    assert rc == 0 and r["status"] == "warn"
    assert r["detail"] == "not installed in the current kube context, expected 1.30.1 (Argo CD application operator-cloudnative-pg)"
    assert r["operator"]["state"] == "missing"


def test_without_a_context_an_installed_operator_keeps_its_old_detail_ac_121_19(tmp_path, monkeypatch, capsys):  # AC-121.19
    w = doctor_world(tmp_path, monkeypatch, dbdoc())
    w.cluster.install(["cloudnative-pg"])
    rc, rows = doctor_rows(w, capsys, context=False)
    r = op_row(rows, "cloudnative-pg")
    assert r["status"] == "ok" and r["detail"] == "installed 1.30.1, expected 1.30.1 (Argo CD application operator-cloudnative-pg)"
    assert r["operator"]["state"] == "ok"


@pytest.mark.parametrize("installed, state, status, rc_want", [
    ("1.30.0", "older", "warn", 0),        # older by a patch
    ("1.29.4", "older", "warn", 0),        # older by a minor
    ("0.9.0", "older", "fail", 1),         # older by a major
    ("1.31.0", "newer", "warn", 0),
], ids=["patch", "minor", "major", "newer"])
def test_doctor_marks_older_and_newer_and_fails_only_on_a_major_older_ac_121_19(tmp_path, monkeypatch, capsys, installed, state, status, rc_want):  # AC-121.19
    w = doctor_world(tmp_path, monkeypatch, dbdoc())
    w.cluster.install(["cloudnative-pg"]).op("cloudnative-pg", installed)
    rc, rows = doctor_rows(w, capsys)
    r = op_row(rows, "cloudnative-pg")
    assert (r["operator"]["state"], r["status"], rc) == (state, status, rc_want)
    assert r["detail"].startswith(f"{state}: installed {installed}, expected 1.30.1")


def test_for_a_zero_x_operator_the_second_number_decides_a_major_ac_121_19(tmp_path, monkeypatch, capsys):  # AC-121.19
    from scale_fixtures import cpu, sdoc
    w = doctor_world(tmp_path, monkeypatch, sdoc(cpu(5)), resource_metrics="install")
    w.cluster.install(["metrics-server"]).op("metrics-server", "0.8.0")
    rc, rows = doctor_rows(w, capsys)
    r = op_row(rows, "metrics-server")
    assert r["operator"]["state"] == "older" and r["status"] == "fail" and rc == 1


def test_a_crd_that_lacks_an_expected_version_makes_the_operator_older_ac_121_22(tmp_path, monkeypatch, capsys):  # AC-121.22
    w = doctor_world(tmp_path, monkeypatch, dbdoc())
    w.cluster.install(["cloudnative-pg"])
    w.cluster.crds["clusters.postgresql.cnpg.io"] = ["v1beta1"]
    rc, rows = doctor_rows(w, capsys)
    r = op_row(rows, "cloudnative-pg")
    assert r["operator"]["state"] == "older" and r["status"] == "warn" and rc == 0
    assert r["operator"]["crds"]["clusters.postgresql.cnpg.io"] == {"expected": ["v1"], "served": ["v1beta1"]}


def test_a_crd_that_is_gone_is_listed_as_missing_ac_121_22(tmp_path, monkeypatch, capsys):  # AC-121.22
    w = doctor_world(tmp_path, monkeypatch, dbdoc())
    w.cluster.install(["cloudnative-pg"])
    del w.cluster.crds["clusters.postgresql.cnpg.io"]
    rc, rows = doctor_rows(w, capsys)
    r = op_row(rows, "cloudnative-pg")
    assert r["operator"]["state"] == "older" and re.search(r"\bclusters\.postgresql\.cnpg\.io missing\b", r["detail"])
    assert r["operator"]["crds"]["clusters.postgresql.cnpg.io"]["served"] == []


def test_an_owner_environment_is_checked_the_same_way_ac_121_18(tmp_path, monkeypatch, capsys):  # AC-121.18
    doc = dbdoc()
    for e in ("dev", "staging", "prod"):
        doc["environments"][e]["operators"] = "owner"
    w = doctor_world(tmp_path, monkeypatch, doc)
    rc, rows = doctor_rows(w, capsys)
    r = op_row(rows, "cloudnative-pg")
    assert rc == 1 and r["status"] == "fail" and r["operator"]["state"] == "missing"
    assert r["detail"].startswith("missing: installed none, expected 1.30.1 (operators: owner in dev, staging, prod); crds ")
    w.cluster.install(["cloudnative-pg"])
    rc, rows = doctor_rows(w, capsys)
    assert rc == 0 and op_row(rows, "cloudnative-pg")["operator"]["state"] == "ok"


def doc_everything_for_doctor():
    d = doc_with_everything()
    d["environments"]["dev"]["observability"] = {"ui": "lgtm"}
    d["environments"]["dev"]["policy"] = "audit"
    d["environments"]["dev"]["backup"] = {"to": "backups"}  # spec 121 slip: velero is needed only where an environment has `backup` (spec 117); the fixture had instance backups only
    return d


def test_the_rows_keep_the_designed_order_and_the_property_rows_need_the_answer_ac_121_19(tmp_path, monkeypatch, capsys):  # AC-121.19
    w = doctor_world(tmp_path / "install", monkeypatch, doc_everything_for_doctor(), property_operators="install")
    w.cluster.install().deploys["app=lgtm"] = "grafana/otel-lgtm:0.35.0@sha256:" + "a" * 64
    rc, rows = doctor_rows(w, capsys)
    want = ["cloudnative-pg", "seaweedfs", "plugin-barman-cloud", "cert-manager", "velero", "nack", "external-secrets", "kyverno", "lgtm"]
    names = [n.removeprefix("operator ") for n in rows if n.startswith("operator ")]
    assert [n for n in names if n in want] == want
    lg = op_row(rows, "lgtm")
    assert (lg["operator"]["state"], lg["operator"]["expected"], lg["operator"]["installed"], lg["operator"]["crds"]) == ("ok", "0.35.0", "0.35.0", {})


def test_without_the_answer_there_are_no_property_operator_rows_ac_121_19(tmp_path, monkeypatch, capsys):  # AC-121.19
    w = doctor_world(tmp_path, monkeypatch, doc_everything_for_doctor())
    w.cluster.install()
    rc, rows = doctor_rows(w, capsys)
    assert not {"operator external-secrets", "operator kyverno", "operator lgtm"} & set(rows)
    assert op_row(rows, "cloudnative-pg")["operator"]["state"] == "ok", "the other rows carry the operator key in every run"


def test_the_broker_rows_compare_without_digests_ac_121_19(tmp_path, monkeypatch):  # AC-121.19
    import doctor
    write_system(tmp_path, bsys({"bus": broker()}))
    plain, digest = NATS["2.15"].split("@")[0], NATS["2.15"]
    for image in (plain, digest):
        monkeypatch.setattr(doctor.shutil, "which", lambda t: f"/usr/bin/{t}")
        monkeypatch.setattr(doctor, "run", lambda cmd, *a, image=image, **k: SimpleNamespace(stdout=f"nats-2.15.1 {image}", stderr="", returncode=0))
        rows = doctor.check_brokers(tmp_path)
        assert rows and all(r["status"] == "ok" for r in rows), rows
        assert rows[0]["detail"] == f"nats chart 2.15.1, server {plain} (expected)"


# ---------------- the cluster scripts (AC-121.4, AC-121.17) ----------------

def local() -> str:
    return (T / "scripts" / "local-cluster.sh").read_text()


def test_the_script_defaults_are_the_table_rows_with_digests_ac_121_4():  # AC-121.4
    text = local()
    for needle in (r"ARGOCD_VERSION:-v3\.4\.12\}", re.escape("K3S_IMAGE:-" + CLUSTER_PINS["k3s"]["image"] + "}"), re.escape("VELERO_AWS_PLUGIN_IMAGE:-" + VELERO_PLUGIN + "}"),
                   r"GATEWAY_API_VERSION:-v1\.2\.1\}", re.escape(LGTM)):
        assert re.search(needle, text), needle
    assert not re.search(r"ARGOCD_VERSION:-stable", text)


def test_the_header_names_the_defaults_and_the_override_warning_ac_121_4():  # AC-121.4
    head = local().split("set -euo pipefail", 1)[0]
    assert re.search(r"(?m)^#\s+ARGOCD_VERSION\s+default v3\.4\.12", head)
    assert re.search(r"overrides the versions table", head) or re.search(r"(?i)warning", head)


def run_up(tmp_path, env):
    """Run `local-cluster.sh up` in a project with fake k3d, kubectl, docker and gh: they print FAKE lines and fail, so `k3d cluster create` ends the run."""
    root = tmp_path / "proj"
    (root / "scripts").mkdir(parents=True)
    shutil.copy(T / "scripts" / "local-cluster.sh", root / "scripts" / "local-cluster.sh")
    shutil.copy(T / "scripts" / "ports.sh", root / "scripts" / "ports.sh")
    write_system(root, system(None, {"api": comp("api")}))
    (root / ".copier-answers.yml").write_text("github_org: acme\n")
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    for tool, rc in (("k3d", 1), ("kubectl", 1), ("docker", 1), ("gh", 1), ("helm", 1)):
        p = bin_dir / tool
        p.write_text(f'#!/bin/sh\necho "FAKE {tool} $*"\nexit {rc}\n')
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
    full = {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "HOME": str(tmp_path), "WITH_ARGO": "0", "LOCAL_HTTP_PORT": "18088", **env}
    p = subprocess.run(["bash", "scripts/local-cluster.sh", "up"], cwd=root, capture_output=True, text=True, env=full, timeout=60)
    return p.stdout + p.stderr


OVERRIDES = [
    ("ARGOCD_VERSION", "v3.3.0", "argo-cd", "v3.4.12"),
    ("K3S_IMAGE", "rancher/k3s:v1.31.0-k3s1", "k3s", "v1.32.5-k3s1"),
    ("GATEWAY_API_VERSION", "v1.1.0", "gateway-api", "v1.2.1"),
    ("LGTM_VERSION", "0.30.0", "lgtm", "0.35.0"),
    ("VELERO_AWS_PLUGIN_IMAGE", "velero/velero-plugin-for-aws:v1.13.0", "velero-plugin-for-aws", "v1.14.4"),
    ("ESO_VERSION", "2.0.0", "operator external-secrets", "2.12.0"),
    ("KYVERNO_VERSION", "3.0.0", "operator kyverno", "3.9.1"),
    ("CNPG_VERSION", "0.20.0", "operator cloudnative-pg", "0.29.1"),
    ("SEAWEEDFS_OPERATOR_VERSION", "0.1.0", "operator seaweedfs", "0.1.45"),
    ("BARMAN_CLOUD_VERSION", "0.1.0", "operator plugin-barman-cloud", "0.8.1"),
    ("CERT_MANAGER_VERSION", "v1.0.0", "operator cert-manager", "v1.21.3"),
    ("VELERO_VERSION", "1.0.0", "operator velero", "12.2.1"),
    ("NACK_VERSION", "0.30.0", "operator nack", "0.35.0"),
    ("KEDA_VERSION", "2.10.0", "operator keda", "2.19.0"),
    ("METRICS_SERVER_VERSION", "3.0.0", "operator metrics-server", "3.14.0"),
]


@pytest.mark.parametrize("var, value, row, table", OVERRIDES, ids=[o[0] for o in OVERRIDES])
def test_an_overridden_version_prints_the_designed_warning_before_anything_is_created_ac_121_4(tmp_path, var, value, row, table):  # AC-121.4
    out = run_up(tmp_path, {var: value})
    warning = f"WARNING: {var}={value} overrides the versions table ({row} {table}); this cluster does not run what this platform release pins"
    lines = out.splitlines()
    assert warning in lines, out
    first_action = next((i for i, ln in enumerate(lines) if re.match(r"FAKE (kubectl|helm|docker|k3d cluster (create|start|delete))", ln)), len(lines))
    assert lines.index(warning) < first_action, "the warning comes before anything is created"


def test_defaults_and_overrides_equal_to_the_default_print_no_warning_ac_121_4(tmp_path):  # AC-121.4
    assert re.search(r"ARGOCD_VERSION:-v3\.4\.12\}", local()), "the default the second run sets explicitly is the table's"
    out = run_up(tmp_path, {})
    assert re.search(r"(?m)^FAKE k3d cluster create", out), "the script ran far enough to prove the run"
    assert not re.search(r"overrides the versions table", out), out
    out = run_up(tmp_path / "same", {"ARGOCD_VERSION": "v3.4.12", "KEDA_VERSION": "2.19.0"})
    assert re.search(r"(?m)^FAKE k3d cluster create", out) and not re.search(r"overrides the versions table", out), out


def test_several_overrides_print_one_warning_each_ac_121_4(tmp_path):  # AC-121.4
    out = run_up(tmp_path, {"ARGOCD_VERSION": "v3.3.0", "K3S_IMAGE": "rancher/k3s:v1.31.0-k3s1"})
    assert len(re.findall(r"(?m)^WARNING: \w+=\S+ overrides the versions table \(", out)) == 2


def test_under_argo_cd_the_property_operators_come_from_operators_apps_ac_121_17():  # AC-121.17
    text = local()
    for name in ("external-secrets", "kyverno", "lgtm"):
        assert re.search(rf"operators/apps/{name}\.yaml", text), name
    assert "External Secrets was installed by an older cluster-up (HelmChart kube-system/external-secrets); keeping it. Recreate the cluster to let Argo CD manage it" in text
    assert "Kyverno was installed by an older cluster-up (HelmChart kube-system/kyverno); keeping it. Recreate the cluster to let Argo CD manage it" in text
    assert re.search(r"deploy/lgtm\b.*300s", text) and re.search(r"clustersecretstores\.external-secrets\.io", text)
    assert re.search(r"namespacedvalidatingpolicies\.policies\.kyverno\.io", text)


def test_the_cluster_repo_copy_of_the_cluster_script_is_byte_equal_ac_121_4():  # AC-121.4
    src, dst = T / "scripts" / "local-cluster.sh", CLUSTER_T / "scripts" / "local-cluster.sh"
    assert re.search(r"ARGOCD_VERSION:-v3\.4\.12\}", dst.read_text()) and dst.read_bytes() == src.read_bytes()


def test_bootstrap_waits_for_the_external_secrets_and_kyverno_crds_ac_121_17():  # AC-121.17
    text = (T / "scripts" / "bootstrap.sh").read_text()
    assert re.search(r"(?m)^\s*external-secrets\) crd=clustersecretstores\.external-secrets\.io ;;", text)
    assert re.search(r"(?m)^\s*kyverno\) crd=namespacedvalidatingpolicies\.policies\.kyverno\.io ;;", text)
    assert not re.search(r"(?m)^\s*lgtm\)", text), "lgtm has no CRD and falls through"


def test_the_cluster_scripts_parse_ac_121_4():  # AC-121.4
    if not shutil.which("bash"):
        pytest.skip("no bash")
    for path in (T / "scripts" / "local-cluster.sh", T / "scripts" / "bootstrap.sh"):
        assert subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True).returncode == 0
    assert re.search(r"v3\.4\.12", local())


# ---------------- AC-121.2: the pin check ----------------

def mini_platform(tmp_path) -> Path:
    """A throwaway copy of the platform repository (scripts, templates, shapes.yml, a changelog) as a git repo tagged v5.3.0."""
    root = tmp_path / "platform"
    ignore = shutil.ignore_patterns("__pycache__", "node_modules")
    shutil.copytree(ROOT / "scripts", root / "scripts", ignore=ignore)
    shutil.copytree(T, root / "templates" / "gitops-app", ignore=ignore, symlinks=True)
    shutil.copytree(CLUSTER_T, root / "templates" / "cluster-gitops", ignore=ignore, symlinks=True)
    (root / "docs").mkdir()
    shutil.copy(ROOT / "shapes.yml", root / "shapes.yml")
    (root / "docs" / "CHANGELOG.md").write_text("# CHANGELOG\n\n## [5.3.0] — 2026-10-27\n\nthe base\n")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    git(root, "tag", "v5.3.0")
    return root


def patch_render(root: Path, code: str) -> None:
    p = root / "templates" / "gitops-app" / "scripts" / "render.py"
    p.write_text(p.read_text() + "\n" + code + "\n")


def edit_file(root: Path, rel: str, old: str, new: str) -> None:
    p = root / rel
    text = p.read_text()
    assert old in text, f"{rel} does not contain {old[:40]}…"
    p.write_text(text.replace(old, new, 1))


def run_script(root: Path, script: str, *argv, env=None):
    p = subprocess.run([sys.executable, f"scripts/{script}", *argv], cwd=root, capture_output=True, text=True, env={**os.environ, **(env or {})}, timeout=300)
    return p.returncode, p.stdout + p.stderr


def test_the_pin_check_passes_on_the_platform_tree_ac_121_2():  # AC-121.2
    rc, out = run_script(ROOT, "check-pins.py")
    assert rc == 0, out
    assert re.search(r"(?m)^OK: \d+ references, all from the versions table$", out)


def test_a_floating_image_tag_in_the_cluster_script_fails_naming_file_line_and_reference_ac_121_2(tmp_path):  # AC-121.2
    root = mini_platform(tmp_path)
    edit_file(root, "templates/gitops-app/scripts/local-cluster.sh", "K3S_IMAGE:-rancher/k3s:v1.32.5-k3s1@sha256:", "K3S_IMAGE:-rancher/k3s:latest@sha256:")
    rc, out = run_script(root, "check-pins.py")
    assert rc == 1
    assert re.search(r"(?m)^ERROR: templates/gitops-app/scripts/local-cluster\.sh:\d+: \S*rancher/k3s:latest\S*: floating tag 'latest'$", out), out
    assert re.search(r"(?m)^FAILED: \d+ reference\(s\)$", out)


def test_argo_cd_on_stable_fails_as_floating_ac_121_2(tmp_path):  # AC-121.2
    root = mini_platform(tmp_path)
    edit_file(root, "templates/gitops-app/scripts/local-cluster.sh", "ARGOCD_VERSION:-v3.4.12}", "ARGOCD_VERSION:-stable}")
    rc, out = run_script(root, "check-pins.py")
    assert rc == 1 and re.search(r"(?m)^ERROR: templates/gitops-app/scripts/local-cluster\.sh:\d+: .*stable.*: floating tag 'stable'$", out), out


def test_a_script_default_that_differs_from_its_row_fails_naming_the_row_ac_121_2(tmp_path):  # AC-121.2
    root = mini_platform(tmp_path)
    edit_file(root, "templates/gitops-app/scripts/local-cluster.sh", "GATEWAY_API_VERSION:-v1.2.1}", "GATEWAY_API_VERSION:-v1.1.0}")
    rc, out = run_script(root, "check-pins.py")
    assert rc == 1 and re.search(r"(?m)^ERROR: templates/gitops-app/scripts/local-cluster\.sh:\d+: .*v1\.1\.0.*: differs from the versions table \(gateway-api: v1\.2\.1\)$", out), out


def test_an_image_in_a_script_that_is_not_in_the_table_fails_ac_121_2(tmp_path):  # AC-121.2
    root = mini_platform(tmp_path)
    p = root / "templates" / "gitops-app" / "scripts" / "bootstrap.sh"
    p.write_text(p.read_text() + "\nkubectl run probe --image=example/probe:1.0.0@sha256:" + "a" * 64 + "\n")
    rc, out = run_script(root, "check-pins.py")
    assert rc == 1 and re.search(r"(?m)^ERROR: templates/gitops-app/scripts/bootstrap\.sh:\d+: example/probe:1\.0\.0\S*: not in the versions table$", out), out


@pytest.mark.parametrize("patch, pattern", [
    ('POSTGRES_IMAGES[17] = POSTGRES_IMAGES[17].split("@")[0]', r"postgresql:17\.11-202610260819-standard-trixie: no digest"),
    ('VALKEY_IMAGES[9] = "valkey/valkey:9@sha256:" + "b" * 64', r"valkey/valkey:9\S*: floating tag '9'"),
    ('OPERATORS["keda"]["chart_version"] = "2.19"', r"chart without an exact version"),
], ids=["no-digest", "bare-major", "inexact-chart"])
def test_a_bad_row_of_the_renderer_fails_naming_it_ac_121_2(tmp_path, patch, pattern):  # AC-121.2
    root = mini_platform(tmp_path)
    patch_render(root, patch)
    rc, out = run_script(root, "check-pins.py")
    assert rc == 1 and re.search(r"(?m)^ERROR: .*" + pattern, out), out
    assert re.search(r"(?m)^FAILED: \d+ reference\(s\)$", out)


def test_the_root_validate_recipe_and_ci_run_the_pin_check_ac_121_2():  # AC-121.2
    recipe = json.loads((ROOT / "devbox.json").read_text())["shell"]["scripts"]["validate"]
    assert "scripts/check-pins.py" in (recipe if isinstance(recipe, str) else " ".join(recipe))
    ci = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text())
    step = next((s for s in ci["jobs"]["validate-shapes"]["steps"] if s.get("name") == "every image and chart comes from the versions table"), None)
    assert step is not None and step["run"] == "python3 scripts/check-pins.py"


# ---------------- AC-121.23 / .26: the release check ----------------

def release_world(tmp_path, patch: str, changelog: str) -> Path:
    root = mini_platform(tmp_path)
    patch_render(root, patch)
    (root / "docs" / "CHANGELOG.md").write_text(changelog)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "candidate")
    return root


def changelog_with(unreleased="", released=None) -> str:
    out = "# CHANGELOG\n\n## [Unreleased]\n\n" + unreleased + "\n"
    for version, body in (released or {}).items():
        out += f"\n## [{version}] — 2026-10-28\n\n{body}\n"
    return out + "\n## [5.3.0] — 2026-10-27\n\nthe base\n"


KEDA_PATCH = 'OPERATORS["keda"]["chart_version"] = "2.20.0"\nOPERATORS["keda"]["operator_version"] = "2.20.0"'
KEDA_LINE = "- `operator keda` 2.19.0 → 2.20.0"
CNPG_PATCH = 'OPERATORS["cloudnative-pg"]["chart_version"] = "0.30.0"'
CNPG_LINE = "- `operator cloudnative-pg` 0.29.1 → 0.30.0 **(major)**"


def rows_check(root):
    return run_script(root, "release-check.py", "rows", "--base", "v5.3.0")


def test_a_changed_row_missing_from_the_changelog_fails_naming_the_line_ac_121_23(tmp_path):  # AC-121.23
    root = release_world(tmp_path, KEDA_PATCH, changelog_with("nothing about keda"))
    rc, out = rows_check(root)
    assert rc == 1 and re.search(r"(?m)^ERROR: docs/CHANGELOG\.md: .*Unreleased.* does not list - `operator keda` 2\.19\.0 → 2\.20\.0$", out), out


def test_a_changelog_that_lists_every_changed_row_passes_ac_121_23(tmp_path):  # AC-121.23
    root = release_world(tmp_path, KEDA_PATCH, changelog_with(KEDA_LINE))
    rc, out = rows_check(root)
    assert rc == 0, out


def test_the_section_of_the_release_is_the_first_heading_newer_than_the_base_ac_121_23(tmp_path):  # AC-121.23
    root = release_world(tmp_path / "a", KEDA_PATCH, changelog_with("", {"5.4.0": KEDA_LINE}))
    assert rows_check(root)[0] == 0
    root = release_world(tmp_path / "b", KEDA_PATCH, changelog_with(KEDA_LINE, {"5.4.0": "something else"}))
    rc, out = rows_check(root)
    assert rc == 1 and re.search(r"(?m)^ERROR: docs/CHANGELOG\.md: .*5\.4\.0.* does not list ", out), out


def test_an_unchanged_table_needs_no_changelog_lines_ac_121_23(tmp_path):  # AC-121.23
    root = release_world(tmp_path, "pass", changelog_with(""))
    rc, out = rows_check(root)
    assert rc == 0, out


def test_an_operator_major_move_fails_on_a_minor_release_ac_121_26(tmp_path):  # AC-121.26
    root = release_world(tmp_path, CNPG_PATCH, changelog_with("", {"5.4.0": CNPG_LINE}))
    rc, out = rows_check(root)
    assert rc == 1 and re.search(r"(?m)^ERROR: .*operator cloudnative-pg.* needs a major platform release \(v?5\.3\.0 → 5\.4\.0\)$", out), out


def test_an_operator_major_move_passes_on_a_major_release_ac_121_26(tmp_path):  # AC-121.26
    root = release_world(tmp_path, CNPG_PATCH, changelog_with("", {"6.0.0": CNPG_LINE}))
    rc, out = rows_check(root)
    assert rc == 0, out


CRD_PATCH = 'OPERATORS["cloudnative-pg"]["crds"]["clusters.postgresql.cnpg.io"] = ["v1beta2"]'


def test_a_removed_crd_version_fails_on_a_minor_release_and_passes_on_a_major_one_ac_121_26(tmp_path):  # AC-121.26
    root = release_world(tmp_path / "minor", CRD_PATCH, changelog_with("", {"5.4.0": "x"}))
    rc, out = rows_check(root)
    assert rc == 1 and re.search(r"(?m)^ERROR: .*clusters\.postgresql\.cnpg\.io v1\b.* needs a major platform release", out), out
    root = release_world(tmp_path / "major", CRD_PATCH, changelog_with("", {"6.0.0": "x"}))
    assert rows_check(root)[0] == 0


DROP_PATCH = 'del POSTGRES_IMAGES[16]\nSUPPORTED_MAJORS["database"] = (17, 18)'


def test_a_dropped_resource_major_fails_on_a_minor_release_naming_the_row_ac_121_26(tmp_path):  # AC-121.26
    root = release_world(tmp_path / "minor", DROP_PATCH, changelog_with("", {"5.4.0": "- `postgres 16` 16.15 (removed)"}))
    rc, out = rows_check(root)
    assert rc == 1 and re.search(r"(?m)^ERROR: .*postgres 16.* needs a major platform release", out), out
    root = release_world(tmp_path / "major", DROP_PATCH, changelog_with("", {"6.0.0": "- `postgres 16` 16.15 (removed)"}))
    assert rows_check(root)[0] == 0


def test_the_release_check_is_green_on_this_branch_ac_121_23():  # AC-121.23
    rc, out = run_script(ROOT, "release-check.py", "rows", "--base", "v5.3.0")
    assert rc == 0, out


def needs_e2e(root) -> str:
    rc, out = run_script(root, "release-check.py", "needs-upgrade-e2e", "--base", "v5.3.0")
    assert rc == 0, out
    return out.strip().splitlines()[-1] if out.strip() else ""


def test_needs_upgrade_e2e_is_true_for_a_changed_row_a_release_heading_or_the_e2e_files_ac_121_24(tmp_path):  # AC-121.24
    root = mini_platform(tmp_path / "none")
    assert needs_e2e(root) == "run=false"
    root = release_world(tmp_path / "row", KEDA_PATCH, changelog_with(KEDA_LINE))
    assert needs_e2e(root) == "run=true"
    root = mini_platform(tmp_path / "heading")
    (root / "docs" / "CHANGELOG.md").write_text("# CHANGELOG\n\n## [5.4.0] — 2026-10-28\n\nx\n\n## [5.3.0] — 2026-10-27\n\nthe base\n")
    git(root, "commit", "-qam", "heading")
    assert needs_e2e(root) == "run=true"


@pytest.mark.parametrize("rel", ["tests/e2e/upgrade.sh", ".github/workflows/e2e-upgrade.yml", "scripts/cplat/upgrade.py", "scripts/cplat/upgradeverify.py", "scripts/cplat/update.py"])
def test_needs_upgrade_e2e_is_true_when_an_e2e_file_changes_ac_121_24(tmp_path, rel):  # AC-121.24
    root = mini_platform(tmp_path)
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text((p.read_text() if p.is_file() else "") + "\n# changed\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "touch")
    assert needs_e2e(root) == "run=true"


def test_a_docs_only_change_does_not_need_the_upgrade_e2e_ac_121_24(tmp_path):  # AC-121.24
    root = mini_platform(tmp_path)
    (root / "docs" / "other.md").write_text("x")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "docs")
    assert needs_e2e(root) == "run=false"


GH_CHECKS = """#!{python}
import os, subprocess, sys
data = open(os.environ["GH_CHECKRUNS"]).read()
args = sys.argv[1:]
if args[:2] == ["repo", "view"]:
    print('{"nameWithOwner": "acme/platform"}' if "--json" in args else "acme/platform")
elif "--jq" in args:
    print(subprocess.run(["jq", "-r", args[args.index("--jq") + 1]], input=data, capture_output=True, text=True).stdout, end="")
else:
    print(data, end="")
"""
E2E_NAME = "e2e upgrade (previous release → candidate)"


def gate(tmp_path, runs, sha="abc1234"):
    root = mini_platform(tmp_path)
    bin_dir = tmp_path / "ghbin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(GH_CHECKS.replace("{python}", sys.executable))
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    data = tmp_path / "checkruns.json"
    data.write_text(json.dumps({"total_count": len(runs), "check_runs": runs}))
    env = {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "GH_CHECKRUNS": str(data), "GITHUB_REPOSITORY": "acme/platform", "GH_TOKEN": "x"}
    return run_script(root, "release-check.py", "gate", sha, env=env)


def test_the_gate_passes_for_a_green_upgrade_e2e_ac_121_24(tmp_path):  # AC-121.24
    rc, out = gate(tmp_path, [{"name": "ci-success", "conclusion": "success"}, {"name": E2E_NAME, "conclusion": "success"}])
    assert rc == 0, out


@pytest.mark.parametrize("runs, shown", [
    ([{"name": E2E_NAME, "conclusion": "failure"}], "failure"),
    ([{"name": E2E_NAME, "conclusion": "skipped"}], "skipped"),
    ([{"name": E2E_NAME, "conclusion": None, "status": "in_progress"}], "none"),
    ([{"name": "ci-success", "conclusion": "success"}], "none"),
], ids=["failure", "skipped", "running", "missing"])
def test_the_gate_refuses_a_tag_without_a_green_upgrade_e2e_ac_121_24(tmp_path, runs, shown):  # AC-121.24
    rc, out = gate(tmp_path, runs, sha="abc1234")
    assert rc == 1
    assert f"ERROR: abc1234 has no green upgrade e2e ({shown}): do not tag it" in out.splitlines(), out


# ---------------- the workflows (AC-121.24, AC-121.25, AC-121.26) ----------------

def workflow(name: str) -> dict:
    path = ROOT / ".github" / "workflows" / name
    assert path.is_file(), f"{name} exists"
    return yaml.safe_load(path.read_text())


def triggers(wf: dict) -> dict:
    return wf.get("on") or wf.get(True)      # YAML 1.1 reads the key `on` as True


E2E_PATHS = {"templates/gitops-app/scripts/render.py", "templates/gitops-app/scripts/local-cluster.sh", "scripts/cplat/upgrade*.py", "scripts/cplat/update.py",
             "scripts/cplat/versions.py", "scripts/release-check.py", "tests/e2e/upgrade.sh", ".github/workflows/e2e-upgrade.yml", "docs/CHANGELOG.md"}


def test_the_upgrade_e2e_workflow_has_the_designed_triggers_and_permissions_ac_121_24():  # AC-121.24
    wf = workflow("e2e-upgrade.yml")
    on = triggers(wf)
    assert set(on) >= {"pull_request", "push", "schedule", "workflow_dispatch"}
    assert set(on["pull_request"]["paths"]) == E2E_PATHS and set(on["push"]["paths"]) == E2E_PATHS and on["push"]["branches"] == ["main"]
    assert wf["permissions"] == {"contents": "read"}


def test_the_upgrade_e2e_workflow_has_a_decide_job_and_the_gated_upgrade_job_ac_121_24():  # AC-121.24
    jobs = workflow("e2e-upgrade.yml")["jobs"]
    assert jobs["decide"]["timeout-minutes"] == 2
    assert any("release-check.py needs-upgrade-e2e" in s.get("run", "") for s in jobs["decide"]["steps"])
    up = jobs["upgrade"]
    assert up["name"] == E2E_NAME and up["timeout-minutes"] == 75 and "decide" in (up["needs"] if isinstance(up["needs"], list) else [up["needs"]])
    assert re.search(r"needs\.decide\.outputs\.run", up["if"]) and "schedule" in up["if"] and "workflow_dispatch" in up["if"]
    checkout = next(s for s in up["steps"] if str(s.get("uses", "")).startswith("actions/checkout"))
    assert checkout["with"]["fetch-depth"] == 0
    runs = " ".join(s.get("run", "") for s in up["steps"])
    assert re.search(r"bash tests/e2e/upgrade\.sh", runs) and re.search(r"TAG=v5\.8\.3\b", runs) and re.search(r"\bcopier\b", runs)


def test_the_release_guard_turns_red_on_a_tag_without_a_green_upgrade_e2e_ac_121_24():  # AC-121.24
    wf = workflow("release-guard.yml")
    assert triggers(wf) == {"push": {"tags": ["v*"]}} and wf["permissions"] == {"contents": "read", "checks": "read"}
    job = next(iter(wf["jobs"].values()))
    assert job["name"] == "release gate (upgrade e2e green)"
    assert re.search(r"scripts/release-check\.py gate \$\{\{ github\.sha \}\}", " ".join(s.get("run", "") for s in job["steps"]))
    assert any(s.get("env", {}).get("GH_TOKEN") == "${{ github.token }}" for s in job["steps"]) or job.get("env", {}).get("GH_TOKEN") == "${{ github.token }}"


def test_no_workflow_tags_releases_or_deletes_tags_ac_121_24():  # AC-121.24
    for name in ("e2e-upgrade.yml", "release-guard.yml", "ci.yml"):
        path = ROOT / ".github" / "workflows" / name
        assert path.is_file(), name
        assert not re.search(r"git tag\b|gh release\b|git push\b.*--delete|git push\b.*:refs/tags", path.read_text()), name


def test_ci_runs_the_release_check_job_and_waits_for_it_ac_121_26():  # AC-121.26
    ci = workflow("ci.yml")
    job_id, job = next(((k, j) for k, j in ci["jobs"].items() if j.get("name") == "release-check (versions table)"), (None, None))
    assert job is not None, "a job named 'release-check (versions table)'"
    checkout = next(s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/checkout"))
    assert checkout["with"]["fetch-depth"] == 0
    assert any("scripts/release-check.py rows" in s.get("run", "") for s in job["steps"])
    assert job_id in ci["jobs"]["ci-success"]["needs"]


def test_contributing_names_the_release_gate_ac_121_24():  # AC-121.24
    text = (ROOT / "CONTRIBUTING.md").read_text()
    assert "scripts/release-check.py gate" in text and re.search(r"release-check\.py rows", text)
    assert re.search(r"(?i)delete(s)? that tag|delete the tag", text) and re.search(r"(?i)release gate", text)


# ---------------- the upgrade e2e script (AC-121.24, AC-121.25 and the cluster halves) ----------------

def e2e() -> str:
    p = ROOT / "tests" / "e2e" / "upgrade.sh"
    assert p.is_file(), "tests/e2e/upgrade.sh exists"
    return p.read_text()


def need(text: str, *needles: str) -> None:
    for n in needles:
        assert n in text, f"upgrade.sh lacks {n!r}"


def test_the_e2e_script_starts_from_the_previous_release_ac_121_24():  # AC-121.24 (needs a cluster)
    t = e2e()
    need(t, "E2E_UPGRADE_FROM", "v5.0.*", "scripts/cplat/versions.py", "git worktree add", 'fail "no previous release tag found (v5.0.*)"')
    assert re.search(r"RESOURCE_TYPES", t) and re.search(r"PLANNED_TYPES", t) and re.search(r"\bast\b", t) and re.search(r"skip: \S+ is not in ", t)


def test_the_e2e_script_records_the_resolved_floating_references_ac_121_24():  # AC-121.24 (needs a cluster)
    t = e2e()
    need(t, "imageID", "resolved ", " -> ", "resolved-")
    assert re.search(r"helmcharts\.helm\.cattle\.io", t)


def test_the_e2e_script_creates_the_system_and_the_data_ac_121_24():  # AC-121.24 (needs a cluster)
    t = e2e()
    need(t, "upg-api", "upg_check", "-before", "after-dev-smoke", "WITH_ARGO=0", "upg/")
    assert re.search(r"--version 16\b", t)


def test_the_e2e_script_updates_to_the_candidate_and_moves_operators_once_ac_121_21():  # AC-121.21 (needs a cluster)
    t = e2e()
    need(t, "platform update", "--verify", "--context k3d-", "--component-dir upg-api=", "overrides the versions table")
    assert re.search(r"(?s)local-cluster\.sh.{0,400}up", t)


def test_the_e2e_script_keeps_staging_and_prod_on_the_held_pin_until_moved_ac_121_11():  # AC-121.11 (needs a cluster)
    t = e2e()
    need(t, "imageName", "--to 16 --env prod", "--to 16 --env staging")


def test_the_e2e_script_refuses_an_upgrade_without_a_recent_backup_and_changes_nothing_ac_121_25():  # AC-121.25 (needs a cluster)
    t = e2e()
    need(t, "resource upgrade postgres --to 17", "never", "/resource:backup postgres --env dev", ".metadata.generation", "last_success")
    assert re.search(r"git rev-parse HEAD", t) and re.search(r"git status --porcelain", t)


def test_the_e2e_script_forces_a_failed_verification_and_keeps_staging_and_prod_readable_ac_121_25():  # AC-121.25 (needs a cluster)
    t = e2e()
    need(t, "FAIL forced", "upg-api-failing", "/resource:restore postgres --env dev", "failed its verification", "pgDataImageInfo", "smoke upg-api")


def test_the_e2e_script_upgrades_through_the_three_environments_and_folds_the_entries_ac_121_8():  # AC-121.8 (needs a cluster)
    t = e2e()
    need(t, "--to 17 --env prod", "--verify --env dev", "instances", "version: 17")


def test_the_e2e_script_checks_data_doctor_status_and_crds_at_the_end_ac_121_22():  # AC-121.22 (needs a cluster)
    t = e2e()
    need(t, "server_version", "17.11", "UPGRADE E2E OK", "platform doctor --context", "upgrade.state", "verified", "apply --dry-run=server -k")
    assert re.search(r"state\W+==\W+.ok", t) or '"state"' in t


def test_the_e2e_script_uses_full_kind_names_and_bounded_waits_ac_121_24():  # AC-121.24 (needs a cluster)
    t = e2e()
    for kind in (r"clusters\.postgresql\.cnpg\.io", r"statefulsets\.apps", r"deployments\.apps", r"configmaps", r"secrets", r"customresourcedefinitions\.apiextensions\.k8s\.io"):
        assert re.search(rf"\b{kind}\b", t), kind
    assert re.search(r"tee /dev/stderr", t) and re.search(r"yaml\.safe_load", t) and re.search(r"grep -w", t)
    assert not re.search(r"kubectl[^\n]* get (cluster|statefulset|deployment|configmap|secret)s? ", t), "full kind names only"


def test_the_e2e_script_header_names_the_criteria_and_the_budget_ac_121_24():  # AC-121.24
    head = e2e().split("set -", 1)[0]
    for needle in ("AC-121.24", "AC-121.25", "40 minutes"):
        assert needle in head, needle


def test_the_existing_e2e_declares_the_owner_answer_and_reads_the_nats_image_from_the_table_ac_121_17():  # AC-121.17
    t = (ROOT / "tests" / "e2e" / "run.sh").read_text()
    assert re.search(r"property_operators", t) and re.search(r"\bowner\b", t)
    assert re.search(r"NATS_IMAGES", t), "the NATS image assertion reads the table"


# ---------------- docs, plugins and the changelog ----------------

def read(rel: str) -> str:
    return (ROOT / rel).read_text()


def plugin_versions(name):
    manifest = json.loads(read(f"plugins/{name}/.claude-plugin/plugin.json"))["version"]
    market = next(p["version"] for p in json.loads(read(".claude-plugin/marketplace.json"))["plugins"] if p["name"] == name)
    return manifest, market


def description(path) -> str:
    return re.search(r'(?m)^description:\s*"(.*)"\s*$', read(path)).group(1)


def test_the_resource_platform_and_system_plugins_are_bumped_in_both_places_ac_121_6():  # AC-121.6
    assert plugin_versions("resource") == ("1.6.0", "1.6.0")
    assert plugin_versions("platform") == ("1.3.0", "1.3.0")
    system = plugin_versions("system")   # later specs bump system again; 1.5.0 is the bump of spec 121
    assert system[0] == system[1] and tuple(map(int, system[0].split("."))) >= (1, 5, 0)


def test_the_upgrade_command_runs_cplat_with_pr_and_wait_ac_121_6():  # AC-121.6
    text = read("plugins/resource/commands/upgrade.md")
    assert len(description("plugins/resource/commands/upgrade.md")) < 260
    assert "/resource:upgrade <name> --to <major> [--env <env>]" in text
    assert "cplat resource upgrade <ARGS> --pr --wait" in text
    for needle in ("one environment", "60 minutes", "/resource:restore", "/resource:backup", "/issue:report"):
        assert needle in text, needle
    assert re.search(r"(?i)staging", text) and re.search(r"(?i)prod", text) and "upgrade" in read("plugins/resource/README.md")


def test_the_doctor_update_and_status_docs_describe_the_new_behaviour_ac_121_19():  # AC-121.19
    doctor = read("plugins/platform/commands/doctor.md")
    for needle in ("--context", "missing", "older", "newer", "CRD"):
        assert needle in doctor, needle
    update = read("plugins/platform/commands/update.md")
    for needle in ("--verify", "cplat platform versions", "/resource:upgrade"):
        assert needle in update, needle
    assert "Resource versions" in read("plugins/system/commands/status.md")
    for rel in ("plugins/platform/commands/doctor.md", "plugins/platform/commands/update.md", "plugins/system/commands/status.md"):
        assert len(description(rel)) < 260, rel
    assert "versions" in read("plugins/platform/README.md")


def test_the_upgrade_guide_covers_the_whole_procedure_ac_121_17():  # AC-121.17
    text = read("docs/UPGRADES.md")
    for needle in ("cplat platform versions", "/resource:upgrade", "/resource:backup", "/resource:restore", "cplat platform update --verify", "doctor --context",
                   "property_operators", "operators: owner", "60 minutes", "15 minutes", "release gate", "--env staging", "--env prod", "held"):
        assert needle in text, needle
    for pattern in (r"(?i)verified", r"(?i)one environment", r"(?i)after-dev-smoke", r"(?i)shared cluster|one cluster", r"(?i)CloudNativePG",
                    r"(?i)pg_upgrade|in place|in-place", r"(?i)external"):
        assert re.search(pattern, text), pattern
    assert re.search(r"(?i)separate clusters", text), "AC-121.20 is stated for a later spec"


def test_the_domain_model_lists_the_instance_version_and_links_the_guide_ac_121_17():  # AC-121.17
    lines = read("docs/DOMAIN-MODEL.md").splitlines()
    for prefix in ("| database `resources.<name>.instances.<env>`", "| cache `resources.<name>.instances.<env>`", "| broker `resources.<name>.instances.<env>`"):
        row = next(ln for ln in lines if ln.startswith(prefix))
        assert row.endswith("`version` |"), prefix
    text = "\n".join(lines)
    m = re.search(r"(?m)^(#{2,4}) Upgrading a resource\s*$", text)
    assert m, "DOMAIN-MODEL.md has a section 'Upgrading a resource'"
    assert re.search(r"UPGRADES\.md", text[m.end():]) and "/resource:upgrade" in text[m.end():]


def test_the_journey_clusters_site_and_adr_index_describe_upgrades_ac_121_18():  # AC-121.18
    assert "Upgrade a database or a cache" in read("docs/USER-JOURNEY.md")
    clusters = read("docs/CLUSTERS.md")
    assert re.search(r"\bproperty_operators\b", clusters) and re.search(r"\blgtm\b", clusters) and re.search(r"operators: owner", clusters)
    site = read("site/src/content/docs/concepts/domain-model.md")
    assert re.search(r"`version`", site) and re.search(r"UPGRADES", site)
    index = read("docs/adr/README.md")
    for n, slug in (("068", "resource-and-operator-upgrades-roll-through-environments-in-verified-steps"),
                    ("069", "one-versions-table-pins-everything-and-every-release-proves-the-upgrade")):
        assert re.search(rf"(?m)^\| \[{n}\]\({n}-{slug}\.md\) \|", index), n


def test_the_renderer_docstring_documents_the_version_the_archives_and_the_answer_ac_121_17():  # AC-121.17
    doc = render_module("render_121_docstring").__doc__
    assert re.search(r"instances\.<env>\.version|version:\s*17", doc) and re.search(r"property_operators", doc) and re.search(r"archives", doc)


def test_the_changelog_lists_the_upgrade_entry_above_scaling_with_every_changed_row_ac_121_23():  # AC-121.23
    text = read("docs/CHANGELOG.md")
    sections = re.split(r"(?m)^(?=## \[)", text)
    hits = [s for s in sections if s.startswith("## [") and re.search(r"(?i)spec 121|ADR-068", s)]
    assert hits, "the change is listed"
    assert re.match(r"## \[(Unreleased|5\.[1-9]\d*\.0)\]", hits[0].splitlines()[0])
    entry = next(e for e in re.split(r"\n\s*\n", hits[0]) if re.search(r"(?i)spec 121|ADR-068", e))
    assert "BREAKING" not in entry
    for needle in ("ADR-068", "ADR-069", "/resource:upgrade", "property_operators", "1.6.0", "1.3.0", "1.5.0", "Versions", "Action", "/platform:update"):
        assert needle in hits[0], needle
    assert re.search(r"(?i)spec 121", hits[0]).start() < re.search(r"(?i)spec 120", hits[0]).start(), "the 121 entry sits above the 120 entry"
    for line in ("- `argo-cd` v3.4.12 (new)", "- `k3s` v1.32.5-k3s1 (new)"):
        assert line in hits[0].splitlines(), line
