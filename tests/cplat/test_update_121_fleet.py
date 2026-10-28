"""Spec 121 (AC-121.23): what the update's own re-render writes is generated output, never a "lost local customisation".

A gitops-app with a broker and an environment backup is rendered, its digests are taken out (the state a 5.3 checkout has), and
`cplat platform update` re-renders it with this checkout's renderer: operators/apps/velero.yaml and the broker's server.yaml gain
their digests. Those files must not reach `lost`, so the fleet update PR is not held open; a real hand edit still is."""
import json
import os
import re
import stat
import sys

import cplat
import fleet_pr
import pytest
from backup_fixtures import bdoc
from broker_fixtures import bdir, broker
from resources_fixtures import APP, comp
from system_fixtures import ROOT, git, init_git, render, write_system

T = ROOT / "templates" / "gitops-app"
COPIER = """#!{python}
import shutil, sys
from pathlib import Path
args = sys.argv[1:]
if args[:1] == ["copy"] and len(args) > 2 and args[2] == ".":
    shutil.copy({new!r}, Path("scripts") / "render.py")      # the template brings the new renderer
elif args[:1] == ["copy"] and len(args) > 2:
    Path(args[2]).mkdir(parents=True, exist_ok=True)
"""
DIGEST = re.compile(r"@sha256:[0-9a-f]{64}")


@pytest.fixture()
def fleet_repo(tmp_path, monkeypatch):
    """A rendered, committed gitops-app (broker `bus`, backups in every environment) whose pins carry no digest yet."""
    import update
    repo = tmp_path / "gitops"
    (repo / "scripts").mkdir(parents=True)
    doc = bdoc(envb={e: {"to": "backups"} for e in ("dev", "staging", "prod")},
               comps={"api": comp("api", ["orders-db", "backups", "bus"], provides=["orders"]), "web": comp("web", consumes=["orders"])},
               resources={"bus": broker()})
    doc["apis"] = {"orders": {"type": "events"}}
    write_system(repo, doc)
    (repo / ".copier-answers.yml").write_text("_src_path: gh:ika100/sdlc-foundry/templates/gitops-app\ngithub_org: acme\napp_name: shop\nproject_name: shop-gitops\n")
    (repo / ".platform-version").write_text("platform: 5.3.0\nshape: gitops-app\nref: main\n")
    (repo / "devbox.json").write_text(json.dumps({"shell": {"scripts": {"ci": "true"}}}))
    p = render(repo, script=T / "scripts" / "render.py")
    assert p.returncode == 0, p.stdout + p.stderr
    stripped = []
    for path in [*(repo / "operators").rglob("*.yaml"), *(repo / APP / "addons").rglob("*.yaml")]:
        text = path.read_text()
        if DIGEST.search(text):
            path.write_text(DIGEST.sub("", text))
            stripped.append(path.relative_to(repo).as_posix())
    assert "operators/apps/velero.yaml" in stripped and f"{bdir()}/server.yaml" in stripped, stripped
    init_git(repo)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    copier = bin_dir / "copier"
    copier.write_text(COPIER.format(python=sys.executable, new=str(T / "scripts" / "render.py")))
    copier.chmod(copier.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(update, "render_baseline", lambda *a, **k: None)
    return repo


def run_update(repo, capsys):
    rc = cplat.main(["platform", "update", "--repo", str(repo), "--json"])
    cap = capsys.readouterr()
    assert rc == 0, cap.out + cap.err
    return json.loads(cap.out)


def test_files_the_rerender_wrote_are_not_lost_and_the_fleet_pr_is_not_held_ac_121_23(fleet_repo, capsys):  # AC-121.23
    d = run_update(fleet_repo, capsys)
    assert "operators/apps/velero.yaml" in d["modified"] and f"{bdir()}/server.yaml" in d["modified"], d["modified"]
    assert DIGEST.search((fleet_repo / "operators/apps/velero.yaml").read_text())
    assert d["lost"] == []
    assert "local customisation" not in fleet_pr.pre_wait_reasons("5.3.0", "5.4.0", d)


def test_a_hand_edit_outside_the_generated_files_is_still_lost_ac_121_23(fleet_repo, capsys):  # AC-121.23
    mine = fleet_repo / "scripts" / "render.py"   # not generated: the template overwrites it, so a local edit is lost
    mine.write_text(mine.read_text() + "# my own tweak\n")
    git(fleet_repo, "add", "-A")
    git(fleet_repo, "commit", "-qm", "own edit")
    d = run_update(fleet_repo, capsys)
    assert [e["file"] for e in d["lost"]] == ["scripts/render.py"], d["lost"]
    assert "local customisation" in fleet_pr.pre_wait_reasons("5.3.0", "5.4.0", d)
