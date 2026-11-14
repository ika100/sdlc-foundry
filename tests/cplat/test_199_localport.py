"""Spec 199 acceptance tests: the port rule and the cluster lookup (AC-199.4, AC-199.5), through `model.local_port`, `model.build`
and the `localport` module of design.md "Contract". A fake `docker` is first on PATH (docker199_support); `localport` is imported
inside the tests, so a missing module fails the test and never the collection."""
import importlib

import pytest

import model
from docker199_support import PORT, FakeDocker, no_docker

HOST = "{component}.{system}-dev.localhost"


def lp():
    return importlib.import_module("localport")


@pytest.fixture()
def docker(tmp_path, monkeypatch):
    return FakeDocker(tmp_path, monkeypatch)


def system_doc(dev=None):
    return {"system": "shop", "owner": "acme",
            "environments": {"dev": dev or {"host": HOST}, "staging": {"host": "{component}.{system}.example.com"}, "prod": {}},
            "components": {"shop-api": {"type": "service", "lang": "python", "repo": "acme/shop-api", "port": 8080, "expose": True,
                                        "instances": {"dev": {}, "staging": {}}}}}


# ---------------- AC-199.4: the port rule ----------------

def test_the_reported_port_is_used_ac_199_4(docker):  # AC-199.4
    docker.reports("shop-local")
    assert model.local_port("shop") == PORT
    assert docker.asked("shop-local") == [["port", "k3d-shop-local-serverlb", "80/tcp"]]


def test_component_urls_and_grafana_carry_the_reported_port_ac_199_4(docker):  # AC-199.4
    docker.reports("shop-local")
    m = model.build(system_doc(), "shop")
    assert m.url("shop-api", "dev")[0] == f"http://shop-api.shop-dev.localhost:{PORT}"
    assert model.grafana_url(HOST, "shop") == f"http://grafana.localhost:{PORT}/"
    assert model.grafana_location(HOST, "shop") == f"http://grafana.localhost:{PORT}/"


def test_local_http_port_wins_and_docker_is_not_asked_ac_199_4(docker, monkeypatch):  # AC-199.4
    docker.reports("shop-local")
    monkeypatch.setenv("LOCAL_HTTP_PORT", "9090")
    assert model.local_port("shop") == 9090
    assert model.grafana_url(HOST, "shop") == "http://grafana.localhost:9090/"
    assert model.build(system_doc(), "shop").url("shop-api", "dev")[0] == "http://shop-api.shop-dev.localhost:9090"
    assert docker.calls == []


@pytest.mark.parametrize("value", ["auto", "", "80a", "-1"])
def test_other_values_of_local_http_port_count_as_unset_ac_199_4(docker, monkeypatch, value):  # AC-199.4
    docker.reports("shop-local")
    monkeypatch.setenv("LOCAL_HTTP_PORT", value)
    assert model.local_port("shop") == PORT


@pytest.mark.parametrize("how", ["exit", "no-container", "empty", "garbage", "out-of-range", "missing"])
def test_no_answer_falls_back_to_8088_without_an_error_ac_199_4(docker, tmp_path, monkeypatch, how):  # AC-199.4
    if how == "exit":
        docker.reports("shop-local").fails(1)
    elif how == "empty":
        docker.says("shop-local", "")
    elif how == "garbage":
        docker.says("shop-local", "no port published here\n")
    elif how == "out-of-range":
        docker.says("shop-local", "0.0.0.0:99999\n")
    elif how == "missing":
        no_docker(tmp_path, monkeypatch)
    # "no-container": the fake knows no such container (exit 1)
    assert model.local_port("shop") == 8088
    assert model.grafana_url(HOST, "shop") == "http://grafana.localhost:8088/"
    assert model.build(system_doc(), "shop").url("shop-api", "dev")[0] == "http://shop-api.shop-dev.localhost:8088"


def test_a_non_local_environment_never_asks_docker_ac_199_4(docker):  # AC-199.4
    docker.reports("shop-local")
    m = model.build(system_doc(), "shop")
    assert m.url("shop-api", "staging")[0] == "https://shop-api.shop.example.com"
    assert model.grafana_url("{component}.shop.example.com", "shop") is None
    assert model.grafana_location("{component}.shop.example.com", "shop") == model.GRAFANA_ELSEWHERE
    assert model.grafana_url(None, "shop") is None
    assert docker.calls == []


def test_a_url_template_never_asks_docker_ac_199_4(docker):  # AC-199.4
    docker.reports("shop-local")
    m = model.build(system_doc({"host": HOST, "url": "http://{host}:8088"}), "shop")
    assert m.url("shop-api", "dev")[0] == "http://shop-api.shop-dev.localhost:8088"
    assert docker.calls == []


def test_docker_port_parses_the_first_line_ac_199_4(docker):  # AC-199.4
    docker.reports("shop-local", 8123)
    assert lp().docker_port("shop-local") == 8123
    assert lp().docker_port("other") is None


def test_docker_port_without_docker_is_none_ac_199_4(tmp_path, monkeypatch):  # AC-199.4
    no_docker(tmp_path, monkeypatch)
    assert lp().docker_port("shop-local") is None


# ---------------- AC-199.5: which cluster, and asked once ----------------

def test_local_cluster_names_the_cluster_ac_199_5(docker, monkeypatch):  # AC-199.5
    docker.reports("shop-local", 8001).reports("lab", 8002)
    monkeypatch.setenv("LOCAL_CLUSTER", " lab ")
    assert lp().cluster("shop") == "lab"
    assert model.local_port("shop") == 8002
    assert docker.asked("shop-local") == []


def test_a_k3d_kube_context_names_the_cluster_ac_199_5(docker, tmp_path, monkeypatch):  # AC-199.5
    docker.reports("shop-local", 8001).reports("mine", 8003)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CPLAT_KUBE_CONTEXT", "k3d-mine")
    assert lp().cluster("shop") == "mine"
    assert model.local_port("shop") == 8003


def test_the_kube_context_of_the_settings_file_names_the_cluster_ac_199_5(docker, tmp_path, monkeypatch):  # AC-199.5
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    repo = tmp_path / "gitops"
    repo.mkdir()
    (repo / ".platform-settings.yml").write_text("kube_context: k3d-fromfile\n")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert lp().cluster("shop") == "shop-local"            # the current directory has no settings
    lp().use_repo(repo)
    assert lp().cluster("shop") == "fromfile"
    lp().reset()
    assert lp().cluster("shop") == "shop-local"            # reset forgets the repo


@pytest.mark.parametrize("context", ["kind-shop", "k3d-", "minikube"])
def test_another_or_empty_context_falls_through_to_the_default_ac_199_5(docker, tmp_path, monkeypatch, context):  # AC-199.5
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CPLAT_KUBE_CONTEXT", context)
    assert lp().cluster("shop") == "shop-local"


def test_a_malformed_kube_context_setting_is_ignored_ac_199_5(docker, tmp_path, monkeypatch):  # AC-199.5
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    (tmp_path / ".platform-settings.yml").write_text("kube_context: [a, b]\n")
    lp().use_repo(tmp_path)
    assert lp().cluster("shop") == "shop-local"
    docker.reports("shop-local")
    assert model.local_port("shop") == PORT


def test_the_default_cluster_is_the_system_local_ac_199_5(docker, tmp_path, monkeypatch):  # AC-199.5
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.chdir(tmp_path)
    assert lp().cluster("shop") == "shop-local"
    assert lp().cluster(None) is None


def test_without_a_system_or_cluster_docker_is_not_asked_ac_199_5(docker, tmp_path, monkeypatch):  # AC-199.5
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.chdir(tmp_path)
    assert model.local_port() == 8088
    assert docker.calls == []


def test_without_a_system_local_cluster_is_still_asked_ac_199_5(docker, monkeypatch):  # AC-199.5
    docker.reports("lab", 8002)
    monkeypatch.setenv("LOCAL_CLUSTER", "lab")
    assert model.local_port() == 8002


def test_docker_is_asked_once_per_cluster_per_invocation_ac_199_5(docker):  # AC-199.5
    docker.reports("shop-local", 8001).reports("other-local", 8002)
    for _ in range(3):
        assert model.local_port("shop") == 8001
    assert model.grafana_url(HOST, "shop") == "http://grafana.localhost:8001/"
    assert model.local_port("other") == 8002
    assert len(docker.asked("shop-local")) == 1 and len(docker.asked("other-local")) == 1


def test_a_missing_answer_is_cached_too_ac_199_5(docker):  # AC-199.5
    for _ in range(3):
        assert model.local_port("shop") == 8088
    assert len(docker.asked("shop-local")) == 1


def test_the_next_invocation_asks_again_ac_199_5(docker):  # AC-199.5
    docker.reports("shop-local", 8001)
    assert model.local_port("shop") == 8001
    lp().reset()
    docker.reports("shop-local", 8002)                     # the cluster was recreated
    assert model.local_port("shop") == 8002
    assert len(docker.asked("shop-local")) == 2


def test_every_cplat_main_call_starts_with_an_empty_cache_ac_199_5(docker, tmp_path, monkeypatch, capsys):  # AC-199.5
    import cplat
    docker.reports("shop-local", 8001)
    assert model.local_port("shop") == 8001
    docker.reports("shop-local", 8002)
    assert model.local_port("shop") == 8001                # same invocation: cached
    cplat.main([])                                         # any invocation: the cache is cleared first thing
    capsys.readouterr()
    assert model.local_port("shop") == 8002                # a new invocation sees the recreated cluster
