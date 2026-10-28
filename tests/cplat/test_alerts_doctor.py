"""Spec 092: `cplat platform doctor` warns when a gitops-app with observability in an environment and service repos has no ALERTS_TOKEN secret (AC-092.25).
`ship.gh` is replaced; no GitHub call is made."""
import json
import subprocess

import pytest
import yaml

import doctor
import ship
from model_fixtures import system_doc

SLUG = "acme/shop-gitops"
GITOPS_SHAPE = "_src_path: gh:ika100/sdlc-foundry/templates/gitops-app\n"


def make_repo(tmp_path, *, addon="default", services=None, shape=GITOPS_SHAPE):
    r = tmp_path / "shop-gitops"
    (r / "applications" / "shop").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True)
    subprocess.run(["git", "remote", "add", "origin", f"https://github.com/{SLUG}.git"], cwd=r, check=True)
    (r / ".copier-answers.yml").write_text(shape)
    addons = {"observability": {"ui": "lgtm"}} if addon == "default" else addon
    svcs = [{"name": "shop-api", "repo": "acme/shop-api"}] if services is None else services
    # 5.0: one system.yaml; the observability of the 4.x addon is set on every environment
    (r / "applications" / "shop" / "system.yaml").write_text(yaml.safe_dump(system_doc(svcs, {"addons": addons} if addons else {}, "shop"), sort_keys=False))
    return r


def secrets(monkeypatch, names):
    calls = []

    def fake(args, *, cwd, check=True):
        calls.append(args)
        if args[:2] == ["secret", "list"]:
            if names is None:
                raise RuntimeError("no access")
            return json.dumps([{"name": n} for n in names])
        return ""

    monkeypatch.setattr(ship, "gh", fake)
    return calls


def test_a_missing_alerts_token_is_a_warning_with_the_fix(tmp_path, monkeypatch):
    """AC-092.25: WARN naming the secret, saying issues land in the gitops-app repo, and giving the command that sets it."""
    r = make_repo(tmp_path)
    secrets(monkeypatch, ["GITOPS_TOKEN"])
    (c,) = doctor.check_alerts_token(r)
    assert c["status"] == doctor.WARN and "ALERTS_TOKEN" in c["name"]
    assert SLUG in c["detail"] and "alert issues" in c["detail"]
    assert f"gh secret set ALERTS_TOKEN -R {SLUG}" in c["fix"] and "Issues" in c["fix"]


def test_an_unreadable_secret_list_is_a_warning(tmp_path, monkeypatch):
    """AC-092.25: a list that cannot be read is WARN, never FAIL, with the same fix."""
    r = make_repo(tmp_path)
    secrets(monkeypatch, None)
    (c,) = doctor.check_alerts_token(r)
    assert c["status"] == doctor.WARN and "ALERTS_TOKEN" in c["name"] and f"gh secret set ALERTS_TOKEN -R {SLUG}" in c["fix"]


def test_a_set_alerts_token_gives_no_warning(tmp_path, monkeypatch):
    """AC-092.25: with the secret set there is no warning."""
    r = make_repo(tmp_path)
    secrets(monkeypatch, ["ALERTS_TOKEN"])
    out = doctor.check_alerts_token(r)
    assert out and all(c["status"] == doctor.OK for c in out)


@pytest.mark.parametrize("kw", [
    {"addon": {}},                                                   # no observability addon
    {"addon": {"observability": {"ui": "lgtm", "alerts": False}}},   # alerts switched off
    {"services": [{"name": "shop-api"}]},                            # no service with a repo
    {"services": []},
    {"shape": "_src_path: gh:ika100/sdlc-foundry/templates/service-go\n"},
])
def test_no_warning_without_the_addon_or_service_repos_or_for_other_shapes(tmp_path, monkeypatch, kw):
    """AC-092.25: no addon (or alerts: false), no service repo, or another shape: no check line at all, and no secret is asked for."""
    r = make_repo(tmp_path, **kw)
    calls = secrets(monkeypatch, [])
    assert doctor.check_alerts_token(r) == []
    assert calls == []


def test_run_checks_includes_the_alerts_token_check(tmp_path, monkeypatch):
    """AC-092.25: `cplat doctor` shows the warning (run_checks calls the check after the service-repos token check)."""
    r = make_repo(tmp_path)
    secrets(monkeypatch, [])
    for name in ("check_tools", "check_gh", "check_docker", "check_kube", "check_plugins", "check_platform_source", "check_repo",
                 "check_gitops_token"):
        monkeypatch.setattr(doctor, name, lambda *a, **k: [])
    import gates
    monkeypatch.setattr(gates, "check_gates", lambda repo: [])
    checks = doctor.run_checks(r)
    names = [c["name"] for c in checks]
    assert any("ALERTS_TOKEN" in n for n in names)
    assert names.index(next(n for n in names if "ALERTS_TOKEN" in n)) > names.index(next(n for n in names if "SERVICE_REPOS_READ_TOKEN" in n))
