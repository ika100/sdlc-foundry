"""Spec 115, two behaviours the review found without a test: the prefixed-variables next step of `component set --uses` (AC-115.8)
and the `argo external` cell of `cplat system status` (AC-115.15). `gh` and `kubectl` are faked; nothing touches the network."""
import json
import shutil
import subprocess
import sys

import pytest
import yaml

import cplat
from resources_fixtures import comp, db, system
from system_fixtures import RENDER5, git, init_git, mod, write_system

STEP = "their variables are prefixed (<NAME>_DATABASE_URL, …) and DATABASE_URL, PG* are no longer injected"


def make_repo(tmp_path, doc):
    write_system(tmp_path, yaml.safe_dump(doc, sort_keys=False))
    (tmp_path / "scripts").mkdir()
    shutil.copy(RENDER5, tmp_path / "scripts" / "render.py")
    (tmp_path / ".copier-answers.yml").write_text("github_org: acme\napp_name: shop\nproject_name: shop-gitops\n")
    done = subprocess.run([sys.executable, "scripts/render.py"], cwd=tmp_path, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return init_git(tmp_path)


def run(*argv, capsys):
    rc = cplat.main([*map(str, argv)])
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


@pytest.fixture()
def repo(tmp_path):
    res = {"orders-db": db(), "users-db": db(), "cache": {"type": "database"}}
    return make_repo(tmp_path, system(res, {"api": comp("api"), "web": comp("web")}))


def test_two_databases_add_the_prefixed_variables_step_ac_115_8(repo, capsys):  # AC-115.8
    assert run("component", "set", "api", "--uses", "orders-db", "--repo-dir", repo, capsys=capsys)[0] == 0
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "x")
    rc, out, err = run("component", "set", "api", "--uses", "users-db", "--repo-dir", repo, capsys=capsys)
    assert rc == 0, err
    assert f"api now uses 2 database resources: {STEP}" in out


@pytest.mark.xfail(strict=True, reason="compose.py emits the dry-run report before prefix_notes are added to next_steps")
def test_two_databases_step_is_printed_with_dry_run_ac_115_8(repo, capsys):  # AC-115.8
    rc, out, err = run("component", "set", "api", "--uses", "orders-db", "--uses", "users-db", "--dry-run", "--repo-dir", repo, capsys=capsys)
    assert rc == 0, err
    assert f"api now uses 2 database resources: {STEP}" in out


def test_one_database_adds_no_prefixed_variables_step_ac_115_8(repo, capsys):  # AC-115.8
    rc, out, err = run("component", "set", "api", "--uses", "orders-db", "--repo-dir", repo, capsys=capsys)
    assert rc == 0, err
    assert "now uses" not in out and "are prefixed" not in out


# ---------------- AC-115.15: status ----------------

def fake_tools(monkeypatch):
    status = mod("status")

    def sh(cmd):
        if cmd[0] == "kubectl":
            items = [{"metadata": {"name": f"addon-{n}-{e}"}, "status": {"sync": {"status": "Synced"}, "health": {"status": "Healthy"}}}
                     for n in ("incl", "ext") for e in ("dev", "staging", "prod")]
            return json.dumps({"items": items})
        return None
    monkeypatch.setattr(status, "sh", sh)


def status_json(repo, capsys):
    rc, out, err = run("system", "status", "--repo-dir", repo, "--context", "ctx", "--json", capsys=capsys)
    assert rc == 0, err
    return {r["resource"]: r["cells"] for r in json.loads(out)["resources"]}


def test_status_shows_external_instance_without_argo_lookup_ac_115_15(tmp_path, monkeypatch, capsys):  # AC-115.15
    res = {"incl": db(), "ext": db(external=True)}
    doc = system(res, {"api": comp("api", ["incl", "ext"])})
    repo = make_repo(tmp_path, doc)
    fake_tools(monkeypatch)
    cells = status_json(repo, capsys)
    assert all(c == {"argo": "external"} for c in cells["ext"].values())
    assert all(c == {"argo": "Synced/Healthy"} for c in cells["incl"].values())
    rc, out, _ = run("system", "status", "--repo-dir", repo, "--context", "ctx", capsys=capsys)
    assert rc == 0 and "argo external" in out and "argo Synced/Healthy" in out


def test_status_external_in_one_environment_only_ac_115_15(tmp_path, monkeypatch, capsys):  # AC-115.15
    res = {"incl": db(instances={"prod": {"external": True}})}
    repo = make_repo(tmp_path, system(res, {"api": comp("api", ["incl"])}))
    fake_tools(monkeypatch)
    cells = status_json(repo, capsys)["incl"]
    assert cells["prod"] == {"argo": "external"}
    assert cells["dev"] == {"argo": "Synced/Healthy"} and cells["staging"] == {"argo": "Synced/Healthy"}
