"""Regression tests found by the verification of spec 113: behaviour the model must keep as before the feature."""
import json

import pytest

import core
import secret
import status
from alerts_fakes import make_app
from model_fixtures import git_repo, model, write_app


@pytest.mark.parametrize("text", ["", "# only a comment\n", "null\n"])
def test_status_with_an_empty_services_file_has_no_rows_ac_113_11(tmp_path, monkeypatch, capsys, text):  # AC-113.11
    write_app(tmp_path, text, {})
    git_repo(tmp_path)
    monkeypatch.setattr(status, "sh", lambda cmd: None)
    monkeypatch.setattr(core, "platform_version", lambda: "4.8.0")
    assert status.main(["--repo-dir", str(tmp_path), "--context", "k3d-x", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"app": "shop", "rows": []}


@pytest.mark.parametrize("text", ["", "# only a comment\n"])
def test_secret_list_with_an_empty_services_file_says_so_ac_113_18(tmp_path, capsys, text):  # AC-113.18
    write_app(tmp_path, text, {})
    assert secret.main(["list", "--repo-dir", str(tmp_path)]) == 0
    assert "no `secrets:` declared" in capsys.readouterr().out


def test_load_dir_accepts_an_empty_services_file_but_not_a_list_ac_113_16(tmp_path):  # AC-113.16
    assert list(model().load_dir(write_app(tmp_path, "", {})).components) == []
    with pytest.raises(model().ModelError):
        model().load_dir(write_app(tmp_path / "b", "- a\n- b\n", {}))


def test_metrics_false_adds_no_service_down_rule_ac_113_11(tmp_path):  # AC-113.11
    import alertsources
    svc = [{"name": "shop-api", "repo": "acme/shop-api", "image": "ghcr.io/acme/shop-api", "metrics": False, "environments": ["dev"]},
           {"name": "web", "repo": "acme/web", "image": "ghcr.io/acme/web", "metrics": "/metrics", "environments": ["dev"]}]
    cfg = alertsources.load_app(make_app(tmp_path, addon={"ui": "lgtm"}, services=svc))
    assert [r.service for r in cfg.rules if r.name == "ServiceDown"] == ["web"]
    assert cfg.model.component("shop-api").metrics is None


def test_uses_keeps_only_declared_resources_ac_113_3():  # AC-113.3
    svc = [{"name": "api", "repo": "acme/api", "image": "i", "uses": ["postgres", "redis"], "environments": ["dev"]}]
    m = model().build("shop", svc, {"addons": {"postgres": {}, "observability": {}}})
    assert tuple(m.component("api").uses) == ("postgres",)
    assert not [r for r in m.relations() if r["type"] == "uses" and r["to"] == "resource:redis"]
