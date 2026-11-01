"""upgrade-check compares a system that has an external kustomize component.

The check used to load the base from a temporary copy of system.yaml alone, so render's validate_external did not find the component's
kustomize package there, and building that error message crashed (`relative_to(ROOT)` of a temporary path): every pull request of such a
system failed the check. The base is now the app directory at the base ref, external packages included."""
import re
import shutil
import subprocess
import sys

from backup_fixtures import make_repo
from system_fixtures import ROOT
from upgrade_fixtures import APP, commit_all, put_system, upgrade_doc

T = ROOT / "templates" / "gitops-app"

STOCK = {"type": "service", "lang": "unknown", "repo": "acme/stock-manager", "image": "ghcr.io/acme/stock-manager",
         "external": {"kustomize": "external/stock-manager/{env}", "namespace": "stock-manager"}, "instances": {"dev": {}}}


def doc(**inst):
    d = upgrade_doc(16, backup=False, instances=inst)
    d["components"]["stock-manager"] = STOCK
    return d


def repo_with_external(tmp_path):
    pkg = tmp_path / APP / "external" / "stock-manager" / "dev"
    pkg.mkdir(parents=True)
    (pkg / "kustomization.yaml").write_text("apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources: []\n")
    repo = make_repo(tmp_path, doc())
    shutil.copy(T / "scripts" / "upgrade-check.py", repo / "scripts" / "upgrade-check.py")
    commit_all(repo, "base")
    return repo


def check(repo, d):
    put_system(repo, d)
    p = subprocess.run([sys.executable, "scripts/upgrade-check.py", "--base", "HEAD"], cwd=repo, capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def test_one_environment_at_a_time_passes_with_an_external_component(tmp_path):
    rc, out = check(repo_with_external(tmp_path), doc(dev={"version": 17}))
    assert rc == 0, out
    assert "OK: no resource changes its major in more than one environment" in out.splitlines()
    assert not re.search(r"(?m)^WARNING: ", out), "the base renders: nothing is skipped"
    assert "Traceback" not in out


def test_two_environments_at_once_still_fail_with_an_external_component(tmp_path):
    rc, out = check(repo_with_external(tmp_path), doc(dev={"version": 17}, staging={"version": 17}))
    assert rc == 1, out
    assert "resources.orders-db: the major changes in dev, staging at once (16 → 17)" in out
