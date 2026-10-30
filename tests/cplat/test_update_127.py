"""Spec 127 acceptance test, AC-127.2: `cplat platform update` on a gitops-app whose cache ExternalSecret still has the 5.3 url form
lists one `url` row per cache and environment (report, JSON, fleet PR body) and says the existing Secret keeps its url.

The fixture renders a system with two caches, rewrites the url templates back to the 5.3 form (`redis://:`) and commits; the update
re-renders with this checkout's renderer through a copier stub (same pattern as test_update_121_fleet.py)."""
import json
import os
import re
import stat
import sys

import cplat
import yaml
import fleet_pr
import pytest

from cache_fixtures import cache, csys
from resources_fixtures import APP, ENVS, comp
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
OLD = "redis://:{{ .password }}@"
NEW = "redis://default:{{ .password }}@"


GEN_API = "generators.external-secrets.io/v1alpha1"


def write_54_form(repo, name, env, url):
    """What 5.4 rendered for a cache: the generator-backed ExternalSecret and the Password generator (no credentials files)."""
    d = repo / APP / "addons" / env / name
    n, ns = f"shop-{name}", f"shop-{env}"
    (d / "externalsecret.yaml").write_text(yaml.safe_dump({
        "apiVersion": "external-secrets.io/v1", "kind": "ExternalSecret", "metadata": {"name": f"{n}-app"},
        "spec": {"refreshPolicy": "CreatedOnce",
                 "target": {"name": f"{n}-app", "creationPolicy": "Owner", "deletionPolicy": "Retain",
                            "template": {"engineVersion": "v2", "data": {"url": url + f"{n}.{ns}.svc:6379/0", "host": f"{n}.{ns}.svc",
                                                                         "port": "6379", "password": "{{ .password }}"}}},  # pragma: allowlist secret
                 "dataFrom": [{"sourceRef": {"generatorRef": {"apiVersion": GEN_API, "kind": "Password", "name": f"{n}-password"}}}]}}))
    (d / "password-generator.yaml").write_text(yaml.safe_dump({
        "apiVersion": GEN_API, "kind": "Password", "metadata": {"name": f"{n}-password"}, "spec": {"length": 32}}))
    for f in d.glob("credentials-*.yaml"):
        f.unlink()
    k = yaml.safe_load((d / "kustomization.yaml").read_text())
    k["resources"] = sorted([r for r in k["resources"] if not r.startswith("credentials-")] + ["externalsecret.yaml", "password-generator.yaml"])
    (d / "kustomization.yaml").write_text(yaml.safe_dump(k))


def make_repo(tmp_path, monkeypatch, old_form=True, caches=("ratelimit", "sessions")):
    import update
    repo = tmp_path / "gitops"
    (repo / "scripts").mkdir(parents=True)
    res = {n: cache() for n in caches}
    write_system(repo, csys(res, {"api": comp("api", list(caches))}))
    (repo / ".copier-answers.yml").write_text("_src_path: gh:ika100/sdlc-foundry/templates/gitops-app\ngithub_org: acme\napp_name: shop\nproject_name: shop-gitops\n")
    (repo / ".platform-version").write_text("platform: 5.3.0\nshape: gitops-app\nref: main\n")
    (repo / "devbox.json").write_text(json.dumps({"shell": {"scripts": {"ci": "true"}}}))
    p = render(repo, script=T / "scripts" / "render.py")
    assert p.returncode == 0, p.stdout + p.stderr
    for n in caches:
        for env in ENVS:
            write_54_form(repo, n, env, OLD if old_form else NEW)
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


def text_of(env, name, old="redis://:<password>@", new="redis://default:<password>@", system="shop"):
    host = f"{system}-{name}.{system}-{env}.svc:6379/0"
    return (f"{env:<8} {name}: url {new}{host} (was {old}{host}); the Secret {system}-{name}-app was written once and keeps its url, "
            "which authenticates as the same user default: running pods need nothing, new Secrets get the new form")


def url_rows(d):
    return [r for r in (d.get("versions") or {}).get("rows", []) if r.get("kind") == "url"]


def plan_url(repo, env, name):
    cm = yaml.safe_load((repo / APP / "addons" / env / name / "credentials-configmap.yaml").read_text())
    return next(s for s in json.loads(cm["data"]["plan.json"])["secrets"] if s["name"].endswith("-app"))["data"]["url"]


def test_the_update_lists_a_url_row_per_cache_and_environment_ac_127_2(tmp_path, monkeypatch, capsys):  # AC-127.2
    d = run_json(make_repo(tmp_path, monkeypatch), capsys)
    rows = url_rows(d)
    want = [(env, name) for name in ("ratelimit", "sessions") for env in ENVS]
    assert [(r["env"], r["resource"]) for r in rows] == want, rows
    assert all(r["moves"] is False for r in rows)
    assert all(set(r) == {"env", "resource", "kind", "from", "to", "moves", "text"} for r in rows)


def test_a_url_row_has_the_designed_from_to_and_text_ac_127_2(tmp_path, monkeypatch, capsys):  # AC-127.2
    d = run_json(make_repo(tmp_path, monkeypatch), capsys)
    row = next(r for r in url_rows(d) if (r["env"], r["resource"]) == ("dev", "sessions"))
    assert row["from"] == "redis://:<password>@shop-sessions.shop-dev.svc:6379/0"
    assert row["to"] == "redis://default:<password>@shop-sessions.shop-dev.svc:6379/0"
    assert row["text"] == text_of("dev", "sessions")
    assert row["text"] in d["versions"]["lines"]


def test_the_change_list_says_the_existing_secret_keeps_its_url_and_nothing_is_to_do_ac_127_2(tmp_path, monkeypatch, capsys):  # AC-127.2
    d = run_json(make_repo(tmp_path, monkeypatch), capsys)
    for row in url_rows(d):
        line = row["text"]
        assert "keeps its url" in line and "same user default" in line and "running pods need nothing" in line, line
        assert "written once" in line


def test_a_cache_with_only_url_rows_still_returns_versions_and_counts_them_ac_127_2(tmp_path, monkeypatch, capsys):  # AC-127.2
    repo = make_repo(tmp_path, monkeypatch, caches=("sessions",))
    rc = cplat.main(["platform", "update", "--repo", str(repo)])
    cap = capsys.readouterr()
    assert rc == 0, cap.out + cap.err
    assert "re-rendered with the new renderer; 4 version change(s) listed below" in cap.out, cap.out
    assert "versions in this system" in cap.out and text_of("prod", "sessions") in cap.out


def test_the_fleet_pr_body_lists_the_url_rows_ac_127_2(tmp_path, monkeypatch, capsys):  # AC-127.2
    d = run_json(make_repo(tmp_path, monkeypatch), capsys)
    body = fleet_pr.pr_body("5.3.0", "5.4.0", d, [])
    assert text_of("staging", "ratelimit") in body


def test_the_re_render_writes_the_new_form_to_the_credentials_plan_ac_127_2(tmp_path, monkeypatch, capsys):  # AC-127.2
    repo = make_repo(tmp_path, monkeypatch)
    run_json(repo, capsys)
    for env in ENVS:
        url = plan_url(repo, env, "sessions")
        assert url.startswith(NEW) and not url.startswith(OLD), env


def test_no_url_row_when_the_template_already_has_the_new_form_ac_127_2(tmp_path, monkeypatch, capsys):  # AC-127.2
    d = run_json(make_repo(tmp_path, monkeypatch, old_form=False), capsys)
    assert url_rows(d) == [], d.get("versions")
    assert not re.search(r"url redis://", json.dumps(d.get("versions") or {}))
