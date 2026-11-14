"""Spec 199 acceptance test AC-199.1: `cplat component ship deploy` smokes dev on the port the k3d cluster's Gateway really got.

World of specs 091/093: the ship deploy of test_staging_093_ship (fake `gh`, Argo, `devbox`), here with a fake `docker` first on
PATH that reports 8089 for the load balancer of `k3d-shop-local`, LOCAL_HTTP_PORT unset, and an environment that answers only on
that port (`smoke.reachable`), as the developer's cluster did in journey 15: on 8088 the smoke was "not run" and staging was
never promoted."""
import pytest

import smoke
from docker199_support import PORT, FakeDocker
from test_autoissue import clk, tr, ai  # noqa: F401  (fixtures)
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)
from test_ship_checks import gh  # noqa: F401  (fixture)
from test_smoke_091_run import FakeDevbox
from test_smoke_091_ship import PASS_ALL, lines_of, repo  # noqa: F401  (fixtures)
from test_staging_093_ship import SWorld, TAG

DEV = f"http://shop-api.shop-dev.localhost:{PORT}"
STAGING = f"http://shop-api.shop-staging.localhost:{PORT}"


@pytest.fixture()
def sw(repo, gh, store, tr, tmp_path, monkeypatch):  # noqa: F811
    return SWorld(repo, gh, store, tr, FakeDevbox(tmp_path, monkeypatch), monkeypatch)


@pytest.fixture()
def staged(sw, tmp_path, monkeypatch):
    sw.stage()
    docker = FakeDocker(tmp_path, monkeypatch).reports("shop-local")
    monkeypatch.setattr(smoke, "reachable", lambda url, timeout=10.0: None if f":{PORT}" in url else "connection refused")
    sw.docker = docker
    return sw


def test_the_dev_smoke_runs_on_the_reported_port_and_is_recorded_ac_199_1(staged, capsys):  # AC-199.1
    staged.fake.script([PASS_ALL])
    assert staged.deploy() == 0
    assert f"smoke (dev) against {DEV}:" in lines_of(capsys)
    assert staged.fake.calls[0][1] == DEV
    st = staged.state()
    assert st["phase"] == "done" and st["smoke"]["outcome"] == "passed" and st["smoke"]["url"] == DEV
    sec = staged.record()["smoke"]
    assert (sec["env"], sec["outcome"], sec["base_url"]) == ("dev", "passed", DEV)
    assert staged.docker.asked("shop-local")


def test_staging_is_promoted_and_smoked_on_the_reported_port_ac_199_1(staged, capsys):  # AC-199.1
    staged.fake.script([PASS_ALL])
    assert staged.deploy() == 0
    (d,) = staged.dispatches()
    assert d["event_type"] == "pin-staging" and d["client_payload[tag]"] == TAG
    (dev, stg) = staged.fake.calls
    assert stg[1] == STAGING
    stg_sec = staged.record()["smoke"]["staging"]
    assert (stg_sec["env"], stg_sec["outcome"], stg_sec["base_url"]) == ("staging", "passed", STAGING)
    assert staged.record()["promotion"]["staging"]["result"] == "promoted"


def test_a_passing_smoke_is_not_reported_as_not_run_ac_199_1(staged, capsys):  # AC-199.1
    staged.fake.script([PASS_ALL])
    staged.deploy()
    text = "\n".join(lines_of(capsys))
    assert "not reachable" not in text and "NOT VERIFIED" not in text
    assert staged.record()["smoke"]["outcome"] != "not-run"
