"""Spec 128 acceptance tests, existing systems (AC-128.9): `/platform:update` on a system rendered by 5.4.x lists, per resource type, what
changed and says existing passwords and keys are kept; the migration proof ignores the generator files and the credentials files.

Contract: design.md "/platform:update change list", "Migration proof". The 5.4 side is the renderer of the git tag v5.4.0 (skipped when the
tag is not in the checkout); the 5.5 side is this checkout's renderer through a copier stub (the pattern of test_update_127.py)."""
import json
import os
import stat
import subprocess
import sys

import pytest
import yaml

import cplat
import fleet_pr
from broker_fixtures import broker
from cache_fixtures import cache
from resources_fixtures import APP, ENVS, comp, system
from system_fixtures import ROOT, init_git, render, write_system

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
ENV_LIST = "dev,staging,prod"
TEXTS = {
    "cache": f"{ENV_LIST} cache sessions: the password is written once by a credentials Job (create if absent) instead of an ExternalSecret with a Password generator; "
             "existing Secrets keep their passwords, nothing to do; a server whose password differs from its Secret restarts once (#316)",
    "broker": f"{ENV_LIST} broker bus: the user passwords are written once by a credentials Job (create if absent) instead of ExternalSecrets with a Password generator; "
              "existing Secrets keep their passwords, nothing to do; a server that refuses a password of its Secrets restarts once (#316)",
    "bucket": f"{ENV_LIST} bucket files: the keys are written once by a credentials Job (create if absent) instead of an ExternalSecret with two Password generators; "
              "existing Secrets keep their keys, nothing to do (#316)",
    "component": f"{ENV_LIST} component api: generated secrets are written once by a credentials Job (create if absent) instead of ExternalSecrets with a Password generator; "
                 "existing Secrets keep their values, nothing to do (#316)",
}


def doc_all():
    return system({"sessions": cache(), "bus": broker(), "files": {"type": "bucket"}},
                  {"api": comp("api", ["sessions", "files"], provides=["orders"], secrets=[{"name": "api-auth", "generate": ["JWT_KEY"]}]),
                   "web": comp("web", consumes=["orders"])}, apis={"orders": {"type": "events"}})


def old_renderer(tmp_path):
    got = subprocess.run(["git", "show", "v5.4.0:templates/gitops-app/scripts/render.py"], cwd=ROOT, capture_output=True, text=True)
    if got.returncode != 0:
        pytest.skip("tag v5.4.0 is not available in this checkout")
    path = tmp_path / "render_v54.py"
    path.write_text(got.stdout)
    return path


def make_repo(tmp_path, monkeypatch, doc=None):
    import update
    repo = tmp_path / "gitops"
    (repo / "scripts").mkdir(parents=True)
    write_system(repo, doc or doc_all())
    (repo / ".copier-answers.yml").write_text("_src_path: gh:ika100/sdlc-foundry/templates/gitops-app\ngithub_org: acme\napp_name: shop\nproject_name: shop-gitops\n")
    (repo / ".platform-version").write_text("platform: 5.4.0\nshape: gitops-app\nref: main\n")
    (repo / "devbox.json").write_text(json.dumps({"shell": {"scripts": {"ci": "true"}}}))
    p = render(repo, script=old_renderer(tmp_path))
    assert p.returncode == 0, p.stdout + p.stderr
    init_git(repo)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    copier = bin_dir / "copier"
    copier.write_text(COPIER.format(python=sys.executable, new=str(T / "scripts" / "render.py")))
    copier.chmod(copier.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(update, "render_baseline", lambda *a, **k: None)
    return repo


def run_json(repo, capsys):
    rc = cplat.main(["platform", "update", "--repo", str(repo), "--json"])
    cap = capsys.readouterr()
    assert rc == 0, cap.out + cap.err
    return json.loads(cap.out)


def cred_rows(d):
    return [r for r in (d.get("versions") or {}).get("rows", []) if r.get("kind") == "credentials"]


def test_the_update_lists_one_credentials_row_per_resource_type_in_order_ac_128_9(tmp_path, monkeypatch, capsys):  # AC-128.9
    d = run_json(make_repo(tmp_path, monkeypatch), capsys)
    rows = cred_rows(d)
    assert [r["resource"] for r in rows] == ["cache", "broker", "bucket", "component"], rows
    assert (d["versions"]["rows"])[-4:] == rows, "the credentials rows come after all other rows"


def test_a_credentials_row_has_the_designed_fields_and_text_ac_128_9(tmp_path, monkeypatch, capsys):  # AC-128.9
    d = run_json(make_repo(tmp_path, monkeypatch), capsys)
    assert len(cred_rows(d)) == 4, cred_rows(d)
    for r in cred_rows(d):
        assert r == {"env": ENV_LIST, "resource": r["resource"], "kind": "credentials", "from": "ExternalSecret + Password generator",
                     "to": "credentials Job (create if absent)", "moves": False, "text": TEXTS[r["resource"]]}, r
        assert r["text"] in d["versions"]["lines"]


def test_the_change_list_says_existing_passwords_and_keys_are_kept_and_nothing_is_to_do_ac_128_9(tmp_path, monkeypatch, capsys):  # AC-128.9
    d = run_json(make_repo(tmp_path, monkeypatch), capsys)
    lines = [r["text"] for r in cred_rows(d)]
    assert len(lines) == 4
    for line, word in zip(lines, ("passwords", "passwords", "keys", "values")):
        assert f"existing Secrets keep their {word}, nothing to do" in line and "(#316)" in line


def test_the_printed_block_and_the_fleet_pr_body_carry_the_rows_ac_128_9(tmp_path, monkeypatch, capsys):  # AC-128.9
    repo = make_repo(tmp_path, monkeypatch)
    rc = cplat.main(["platform", "update", "--repo", str(repo)])
    cap = capsys.readouterr()
    assert rc == 0, cap.out + cap.err
    assert "versions in this system" in cap.out and TEXTS["cache"] in cap.out and TEXTS["component"] in cap.out
    repo2 = make_repo(tmp_path / "again", monkeypatch)
    d = run_json(repo2, capsys)
    assert TEXTS["bucket"] in fleet_pr.pr_body("5.4.0", "5.5.0", d, [])


def test_a_type_without_instances_gets_no_row_ac_128_9(tmp_path, monkeypatch, capsys):  # AC-128.9
    d = run_json(make_repo(tmp_path, monkeypatch, system({"sessions": cache()}, {"api": comp("api", ["sessions"])})), capsys)
    assert [r["resource"] for r in cred_rows(d)] == ["cache"]


def test_the_re_render_replaces_the_generator_files_with_the_credentials_files_ac_128_9(tmp_path, monkeypatch, capsys):  # AC-128.9
    repo = make_repo(tmp_path, monkeypatch)
    assert (repo / APP / "addons" / "dev" / "sessions" / "password-generator.yaml").is_file()
    run_json(repo, capsys)
    for env in ENVS:
        d = repo / APP / "addons" / env / "sessions"
        assert not (d / "password-generator.yaml").exists() and not (d / "externalsecret.yaml").exists()
        assert (d / "credentials-job.yaml").is_file()
    assert (repo / APP / "overlays" / "dev" / "api" / "credentials-job.yaml").is_file()
    assert not (repo / APP / "overlays" / "dev" / "api" / "password-generator.yaml").exists()


def test_the_migration_proof_ignores_the_generator_and_credentials_files_ac_128_9(tmp_path):  # AC-128.9
    import update
    doc = system(None, {"api": comp("api", secrets=[{"name": "api-auth", "generate": ["JWT_KEY"]}, {"name": "api-pay", "remote": {"keys": ["PAY_KEY"]}}])})
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    new.mkdir()
    write_system(old, doc)
    assert render(old, script=old_renderer(tmp_path)).returncode == 0
    write_system(new, doc)
    assert render(new).returncode == 0
    assert (new / APP / "overlays" / "dev" / "api" / "credentials-job.yaml").is_file(), "the new render has the Job"
    assert (old / APP / "overlays" / "dev" / "api" / "password-generator.yaml").is_file()
    reference = update._tree(old)
    init_git(new)
    update.apply_systems(new, [], reference)       # raises PlatformError when the two trees differ beyond the dropped files
