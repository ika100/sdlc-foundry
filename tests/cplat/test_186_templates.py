"""Spec 186 acceptance tests: component CI builds the image alongside the gates (AC-186.6, AC-186.7) and a local Argo CD polls git
every 30 seconds (AC-186.8).

Seams: the four image templates' `ci.yml` parsed as YAML (the Jinja escapes of GitHub's `${{ }}` are unescaped first, which is all
copier does to this file), and the real `local-cluster.sh` of the gitops-app and cluster-gitops templates run against fake `k3d`,
`gh` and a `kubectl` that keeps the `argocd-cm` value in a file, as the cluster would.
"""
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from waiting import with_prelude

TEMPLATES = Path(__file__).resolve().parents[2] / "templates"
IMAGE_TEMPLATES = ["service-python", "service-java", "service-go", "web-nextjs"]
GATES = ["quality", "test", "security", "ci-extra"]


def workflow(template: str) -> dict:
    text = (TEMPLATES / template / ".github" / "workflows" / "ci.yml").read_text()
    return yaml.safe_load(text.replace("{{ '{{' }}", "{{").replace("{{ '}}' }}", "}}"))


def needs(job: dict) -> list[str]:
    n = job.get("needs") or []
    return [n] if isinstance(n, str) else list(n)


# ---------------- AC-186.6: docker alongside the gates ----------------

@pytest.mark.parametrize("template", IMAGE_TEMPLATES)
def test_the_docker_job_waits_for_no_gate_and_stays_a_required_check_ac_186_6(template):  # AC-186.6
    jobs = workflow(template)["jobs"]
    docker = jobs["docker"]
    assert needs(docker) == []                                         # builds each architecture while the gates run
    assert docker["name"] == "docker (${{ matrix.arch }})" and docker["if"] == "github.ref_type != 'tag'"
    assert "matrix" in docker["strategy"]
    assert [j for j in ("quality", "test", "security", "ci-extra", "docker", "pr-title", "branch-name", "release-image", "docker-publish", "pin-dev")
            if j not in jobs] == []                                    # no check is renamed or removed
    assert jobs["docker-publish"]["name"] == "docker (publish multi-arch manifest)"
    assert jobs["pin-dev"]["name"].startswith("pin-dev ")


@pytest.mark.parametrize("template", IMAGE_TEMPLATES)
def test_a_pull_request_pushes_no_image_ac_186_6(template):  # AC-186.6
    wf = workflow(template)
    publish = wf["env"]["PUBLISH"]
    assert "github.event_name == 'push'" in publish and "pull_request" not in publish      # a PR run never publishes
    assert needs(wf["jobs"]["docker"]) == []
    outs = [str(st["with"]["outputs"]) for st in wf["jobs"]["docker"]["steps"] if "push-by-digest=true" in str(st.get("with", {}).get("outputs", ""))]
    assert outs and all("push=${{ env.PUBLISH }}" in o for o in outs)


# ---------------- AC-186.7: the tags come after every gate ----------------

@pytest.mark.parametrize("template", IMAGE_TEMPLATES)
def test_the_manifest_and_tags_wait_for_every_gate_ac_186_7(template):  # AC-186.7
    jobs = workflow(template)["jobs"]
    publish = jobs["docker-publish"]
    assert sorted(needs(publish)) == sorted([*GATES, "docker"])             # the image scan is a step of `docker`
    cond = publish["if"]
    assert "github.event_name == 'push'" in cond and "github.ref == 'refs/heads/main'" in cond
    assert not re.search(r"always\(\)|!cancelled\(\)|failure\(\)", cond)       # a red or cancelled gate skips the publish
    tags = [s for s in publish["steps"] if "metadata-action" in str(s.get("uses"))][0]["with"]["tags"]
    assert "type=sha,prefix=sha-,format=long" in tags and "type=raw,value=latest,enable={{is_default_branch}}" in tags


@pytest.mark.parametrize("template", IMAGE_TEMPLATES)
def test_pin_dev_runs_only_after_the_publish_and_the_release_image_is_untouched_ac_186_7(template):  # AC-186.7
    jobs = workflow(template)["jobs"]
    assert needs(jobs["pin-dev"]) == ["docker-publish"]
    assert not re.search(r"always\(\)|!cancelled\(\)|failure\(\)", str(jobs["pin-dev"].get("if")))
    assert sorted(needs(jobs["release-image"])) == ["quality", "test"]
    assert sorted(needs(jobs["docker-publish"])) == sorted([*GATES, "docker"])     # nothing is tagged before every gate has passed


# ---------------- AC-186.8: Argo CD polls git every 30 seconds ----------------

SCRIPT = "local-cluster.sh"
FAKE_KUBECTL = """#!/bin/sh
echo "$*" >> "$KLOG"
case "$*" in
  *"get configmap argocd-cm"*) cat "$CM_STATE" 2>/dev/null; exit 0 ;;
  *"patch configmap argocd-cm"*)
    case "$*" in *timeout.reconciliation*30s*) printf 30s > "$CM_STATE" ;; esac
    exit 0 ;;
  *metrics.k8s.io*) echo True ;;
esac
exit 0
"""


def local_cluster(tmp_path, template, cm=None):
    """Run `local-cluster.sh up` on a reused cluster; returns (output, the kubectl calls). `cm` is the existing reconciliation value."""
    skeleton = tmp_path / "gitops"
    (skeleton / "applications" / "demo").mkdir(parents=True)
    (skeleton / "scripts").mkdir()
    for f in (SCRIPT, "ports.sh"):
        shutil.copy(TEMPLATES / template / "scripts" / f, skeleton / "scripts" / f)
    (skeleton / ".copier-answers.yml").write_text("github_org: acme\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    state, klog = tmp_path / "cm-state", tmp_path / "kubectl.log"
    if cm:
        state.write_text(cm)
    klog.touch()
    for tool in ("k3d", "gh", "helm"):
        (bin_dir / tool).write_text(with_prelude("#!/bin/sh\nexit 0\n"))
    (bin_dir / "kubectl").write_text(with_prelude(FAKE_KUBECTL))
    (bin_dir / "docker").write_text(with_prelude('#!/bin/sh\n[ "$1" = port ] && echo "0.0.0.0:8123" && exit 0\nexit 0\n'))
    for f in bin_dir.iterdir():
        f.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k != "LOCAL_HTTP_PORT"}
    env |= {"PATH": f"{bin_dir}:{os.environ['PATH']}", "GH_TOKEN": "x", "WITH_ESO": "0", "WITH_CNPG": "0", "WITH_LGTM": "0", "WITH_ARGO": "1",
            "KLOG": str(klog), "CM_STATE": str(state)}
    run = subprocess.run(["bash", str(skeleton / "scripts" / SCRIPT), "up"], capture_output=True, text=True, env=env, cwd=skeleton)
    return run.stdout + run.stderr, klog.read_text().splitlines()


@pytest.mark.parametrize("template", ["gitops-app", "cluster-gitops"])
def test_a_fresh_install_sets_the_reconciliation_timeout_and_restarts_the_controller_ac_186_8(tmp_path, template):  # AC-186.8
    out, calls = local_cluster(tmp_path, template)
    patches = [c for c in calls if "patch configmap argocd-cm" in c]
    assert len(patches) == 1 and "timeout.reconciliation" in patches[0] and "30s" in patches[0], out[-1500:]
    restarts = [i for i, c in enumerate(calls) if "rollout restart" in c and "argocd-application-controller" in c]
    assert len(restarts) == 1 and restarts[0] > calls.index(patches[0])                # the controller reads the key only at start
    assert "Argo CD polls git every 30s" in out
    assert not [c for c in calls if "jitter" in c]


@pytest.mark.parametrize("template", ["gitops-app", "cluster-gitops"])
def test_a_rerun_over_an_install_that_has_it_changes_nothing_ac_186_8(tmp_path, template):  # AC-186.8
    out, calls = local_cluster(tmp_path, template, cm="30s")
    assert [c for c in calls if "get configmap argocd-cm" in c], out[-1500:]           # it looked
    assert not [c for c in calls if "patch configmap argocd-cm" in c or "rollout restart" in c]
    assert "Argo CD polls git every 30s" in out


@pytest.mark.parametrize("template", ["gitops-app", "cluster-gitops"])
def test_a_rerun_over_another_value_sets_it_again_ac_186_8(tmp_path, template):  # AC-186.8
    out, calls = local_cluster(tmp_path, template, cm="180s")
    assert len([c for c in calls if "patch configmap argocd-cm" in c]) == 1, out[-1500:]


def test_both_templates_ship_the_same_script_ac_186_8():  # AC-186.8
    a = (TEMPLATES / "gitops-app" / "scripts" / SCRIPT).read_bytes()
    b = (TEMPLATES / "cluster-gitops" / "scripts" / SCRIPT).read_bytes()
    assert a == b and b"timeout.reconciliation" in a
