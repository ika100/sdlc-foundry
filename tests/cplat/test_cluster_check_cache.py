"""Spec 119 (gap from 118): `devbox run check` needs External Secrets for an in-cluster cache (its password comes from there)."""
import re

import pytest

from cluster_fixtures import ORG, base, cluster_repo, render_ok, script, stubs, sys_doc, system_repo, write_cluster

ALPHA = f"{ORG}/alpha-gitops"


@pytest.fixture()
def world(shared_renders, tmp_path, monkeypatch):
    repo = cluster_repo(shared_renders, tmp_path)
    s = stubs(tmp_path, monkeypatch)
    (repo / ".platform-version").write_text("platform: 5.1.0\n")
    return repo, s


def test_an_in_cluster_cache_needs_external_secrets(world):
    repo, s = world
    doc = sys_doc("alpha")
    doc["resources"] = {"sessions": {"type": "cache"}}
    doc["components"]["api"]["uses"] = ["sessions"]
    system_repo(s["fixtures"], ALPHA, doc)
    write_cluster(repo, base(operators=[], systems={"alpha": {"repo": ALPHA}}))
    render_ok(repo, repo.joinpath("cluster.yaml").read_text())
    p = script(repo, "check.py")
    out = p.stdout + p.stderr
    assert p.returncode == 1, out
    assert re.search(r"ERROR: alpha \(dev\): needs external-secrets, which cluster.yaml does not list in operators", out), out
