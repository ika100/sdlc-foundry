"""Spec 199 acceptance tests AC-199.3: the Grafana line and `grafana_url` of `cplat system set --observability lgtm` and
`cplat system status` carry the port the k3d cluster's Gateway really got (fake `docker` first on PATH, LOCAL_HTTP_PORT unset).
Worlds: spec 197's `system set` gitops-app and `system status` system (test_197_seams)."""
import json

import pytest

import cplat
from docker199_support import PORT, FakeDocker
from test_197_seams import gitops, grafana_line, obs_cells, set_obs, system as status_system  # noqa: F401  (fixtures)

URL = f"http://grafana.localhost:{PORT}/"


@pytest.fixture()
def docker(tmp_path_factory, monkeypatch):
    return FakeDocker(tmp_path_factory.mktemp("docker"), monkeypatch).reports("shop-local")


@pytest.mark.parametrize("extra", [(), ("--dry-run",)])
def test_system_set_names_grafana_on_the_reported_port_ac_199_3(tmp_path, capsys, docker, extra):  # AC-199.3
    out = set_obs(gitops(tmp_path), capsys, "lgtm", "dev", *extra)
    assert grafana_line(out) == URL


def test_system_set_json_carries_the_reported_port_ac_199_3(tmp_path, capsys, docker):  # AC-199.3
    doc = json.loads(set_obs(gitops(tmp_path), capsys, "lgtm", "dev", "--json"))
    assert doc["grafana_url"] == URL


def test_a_second_identical_call_still_reports_the_port_ac_199_3(tmp_path, capsys, docker):  # AC-199.3
    repo = gitops(tmp_path)
    set_obs(repo, capsys, "lgtm")
    assert json.loads(set_obs(repo, capsys, "lgtm", "dev", "--json"))["grafana_url"] == URL


def test_system_set_follows_the_kube_context_of_its_repo_ac_199_3(tmp_path, capsys, docker, monkeypatch):  # AC-199.3
    docker.reports("mine", 8123)
    repo = gitops(tmp_path)
    (repo / ".platform-settings.yml").write_text("kube_context: k3d-mine\n")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    doc = json.loads(set_obs(repo, capsys, "lgtm", "dev", "--json", "--dry-run"))
    assert doc["grafana_url"] == "http://grafana.localhost:8123/"


def test_system_status_names_grafana_on_the_reported_port_ac_199_3(status_system, capsys, docker):  # AC-199.3
    cells = obs_cells(status_system, capsys)
    assert cells["dev"]["grafana_url"] == URL
    assert cells["staging"]["grafana_url"] is None


def test_the_status_table_prints_the_reported_port_ac_199_3(status_system, capsys, docker):  # AC-199.3
    assert cplat.main(["system", "status", "--repo-dir", str(status_system)]) == 0
    assert f"Grafana {URL}" in capsys.readouterr().out
