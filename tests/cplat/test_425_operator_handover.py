"""Spec 146 (#425): one owner per operator. External Secrets or Kyverno left as k3s HelmCharts by an older cluster-up are handed over
to Argo CD (operators/apps/<op>.yaml) by scripts/operator-handover.sh, which cluster-up and bootstrap run before they apply
operators/root.yaml. A fake kubectl keeps the cluster state in files and logs every call."""
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
T = ROOT / "templates" / "gitops-app" / "scripts"
FINALIZER = "wrangler.cattle.io/on-helm-chart-remove"

FAKE_KUBECTL = r"""#!/usr/bin/env bash
S="$STATE"
echo "$*" >> "$S/log"
shift 2   # --context <ctx>
if [ "$1" = -n ]; then shift 2; fi
case "$1 $2" in
  "get crd")
    if [ "${3:-}" = helmcharts.helm.cattle.io ]; then [ -f "$S/helmcrd" ]; exit; fi
    cat "$S/crds" 2>/dev/null; exit 0 ;;
  "get helmcharts.helm.cattle.io")
    if [ -f "$S/hc-$3" ]; then
      case "$*" in *finalizers*) echo "FINALIZER" ;; *) echo "helmchart.helm.cattle.io/$3" ;; esac
    fi
    exit 0 ;;
  "get job") exit 0 ;;
  "delete helmcharts.helm.cattle.io")
    rm -f "$S/hc-$3"
    if [ -f "$S/lose" ]; then : > "$S/count-$(cat "$S/lose")"; fi
    exit 0 ;;
  "get "*) [ -f "$S/count-$2" ] || exit 1; cat "$S/count-$2"; exit 0 ;;
  *) exit 0 ;;
esac
""".replace("FINALIZER", FINALIZER)


@pytest.fixture()
def cluster(tmp_path):
    """A gitops repo rendering External Secrets, and a k3s cluster with the HelmChart CRD, two ExternalSecrets and the ESO CRDs."""
    repo, state, bin_dir = tmp_path / "repo", tmp_path / "state", tmp_path / "bin"
    for d in (repo / "scripts", repo / "operators" / "apps", state, bin_dir):
        d.mkdir(parents=True)
    shutil.copy(T / "operator-handover.sh", repo / "scripts" / "operator-handover.sh")
    (repo / "operators" / "root.yaml").write_text("kind: Application\n")
    (repo / "operators" / "apps" / "external-secrets.yaml").write_text("kind: Application\n")
    (state / "helmcrd").write_text("")
    (state / "crds").write_text("externalsecrets.external-secrets.io external-secrets external-secrets\n"
                                "clustersecretstores.external-secrets.io external-secrets external-secrets\n"
                                "clusterpolicies.kyverno.io kyverno kyverno\n"
                                "gateways.gateway.networking.k8s.io  \n")
    (state / "count-externalsecrets.external-secrets.io").write_text("dev a\nprod b\n")
    (state / "count-clustersecretstores.external-secrets.io").write_text(" platform-secrets\n")
    (bin_dir / "kubectl").write_text(FAKE_KUBECTL)
    (bin_dir / "kubectl").chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "KUBE_CONTEXT": "k3d-x-local", "STATE": str(state)}

    def run():
        p = subprocess.run(["bash", "scripts/operator-handover.sh"], cwd=repo, env=env, capture_output=True, text=True, timeout=60)
        log = (state / "log").read_text() if (state / "log").exists() else ""
        return p, log
    return repo, state, run


def test_without_a_helmchart_nothing_changes(cluster):  # AC-146.4
    _, _, run = cluster
    p, log = run()
    assert p.returncode == 0 and p.stdout == "" and p.stderr == "", p.stdout + p.stderr
    assert not re.search(r"(?m)\b(annotate|patch|delete|apply)\b", log), log


def test_a_cluster_without_the_k3s_helm_controller_is_left_alone(cluster):  # AC-146.4
    _, state, run = cluster
    (state / "helmcrd").unlink()
    (state / "hc-external-secrets").write_text("")
    p, log = run()
    assert p.returncode == 0 and p.stdout == "", p.stdout + p.stderr
    assert log.strip().splitlines() == ["--context k3d-x-local get crd helmcharts.helm.cattle.io"]


def test_a_helmchart_of_a_rendered_operator_is_handed_over_in_order(cluster):  # AC-146.1, AC-146.2, AC-146.4 (second run)
    _, state, run = cluster
    (state / "hc-external-secrets").write_text("")
    p, log = run()
    assert p.returncode == 0, p.stdout + p.stderr
    lines = log.splitlines()

    def at(pattern):
        hits = [i for i, line in enumerate(lines) if re.search(pattern, line)]
        assert hits, f"{pattern} not in\n{log}"
        return hits

    keep = at(r"annotate crd \S+ helm\.sh/resource-policy=keep --overwrite")
    assert len(keep) == 2 and "clusterpolicies.kyverno.io" not in "".join(lines[i] for i in keep)
    unmanaged = at(r"-n kube-system annotate helmcharts\.helm\.cattle\.io external-secrets helmcharts\.helm\.cattle\.io/unmanaged=true")[0]
    patch = at(r'-n kube-system patch helmcharts\.helm\.cattle\.io external-secrets --type=merge -p \{"metadata":\{"finalizers":\[\]\}\}')[0]
    delete = at(r"-n kube-system delete helmcharts\.helm\.cattle\.io external-secrets")[0]
    secrets = at(r"-n external-secrets delete secret -l owner=helm,name=external-secrets")[0]
    leftovers = at(r"-n kube-system delete job/helm-install-external-secrets serviceaccount/helm-external-secrets "
                   r"secret/chart-values-external-secrets configmap/chart-content-external-secrets")[0]
    crb = at(r"delete clusterrolebinding/helm-kube-system-external-secrets")[0]
    apply = at(r"apply -n argocd -f operators/root\.yaml")[0]
    assert max(keep) < unmanaged < patch < delete < secrets < leftovers < crb < apply, log
    assert not re.search(r"(annotate|patch|delete) helmcharts\.helm\.cattle\.io kyverno", log), log
    out = p.stdout
    for n in range(1, 6):
        assert re.search(rf"(?m)^  {n}/5 ", out), out
    assert f"removed the finalizer {FINALIZER}" in out and "sh.helm.release.v1.external-secrets.*" in out
    assert "externalsecrets.external-secrets.io=2" in out and "clustersecretstores.external-secrets.io=1" in out
    assert not (state / "hc-external-secrets").exists()

    p, log2 = run()   # idempotent: the second run finds no HelmChart
    assert p.returncode == 0 and p.stdout == "", p.stdout
    assert "apply" not in log2[len(log):]


def test_a_helmchart_of_an_operator_the_repo_does_not_render_is_kept(cluster):  # AC-146.1
    _, state, run = cluster
    (state / "hc-kyverno").write_text("")
    p, log = run()
    assert p.returncode == 0, p.stdout + p.stderr
    assert "Kyverno stays on its HelmChart kube-system/kyverno (this repo does not render operators/apps/kyverno.yaml)" in p.stdout
    assert not re.search(r"\b(annotate|patch|delete|apply)\b", log), log
    assert (state / "hc-kyverno").exists()


def test_a_lost_resource_fails_loudly_naming_it(cluster):  # AC-146.3
    _, state, run = cluster
    (state / "hc-external-secrets").write_text("")
    (state / "lose").write_text("externalsecrets.external-secrets.io")
    p, _ = run()
    assert p.returncode == 1, p.stdout + p.stderr
    assert "ERROR: the handover to Argo CD changed what the cluster holds:" in p.stderr
    assert "externalsecrets.external-secrets.io: 2 before, 0 after" in p.stderr
    assert "clustersecretstores" not in p.stderr and "5/5" not in p.stdout


def test_cluster_up_and_bootstrap_hand_over_before_applying_operators_root():  # AC-146.5
    for f, call in (("local-cluster.sh", 'KUBE_CONTEXT="$ctx" bash scripts/operator-handover.sh'),
                    ("bootstrap.sh", "bash scripts/operator-handover.sh")):
        text = (T / f).read_text()
        assert call in text, f
        assert text.index(call) < text.index("k apply -n argocd -f operators/root.yaml"), f
    cluster_copy = ROOT / "templates" / "cluster-gitops" / "scripts" / "operator-handover.sh"
    assert cluster_copy.read_bytes() == (T / "operator-handover.sh").read_bytes()


def test_the_handover_script_parses():  # AC-146.2
    assert subprocess.run(["bash", "-n", str(T / "operator-handover.sh")]).returncode == 0
