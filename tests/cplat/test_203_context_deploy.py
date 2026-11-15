"""Spec 203 acceptance test AC-203.1 (deploy side): the headless `ship deploy` without `--context` uses the context recorded at the
hand-off, checks Argo CD health, runs the dev smoke and records its result, so `ship status` never shows "not run" for a missing
context.

World of spec 105 (`test_deploy_checks`): fake `gh`, Argo and `devbox`; `cluster.running_digest` replaced. The ship state carries
`context` as `ship start --detach` writes it (design.md, "Contract"); no `--context` argument and no kube environment is given.
"""
import pytest

import ship
from test_autoissue import clk, tr, ai  # noqa: F401  (fixtures)
from test_deploy_checks import staged
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)
from test_ship_checks import gh  # noqa: F401  (fixture)
from test_smoke_091_run import FakeDevbox
from test_smoke_091_ship import PASS_ALL, lines_of, repo  # noqa: F401  (fixtures)
from test_staging_093_ship import SWorld


@pytest.fixture()
def sw(repo, gh, store, tr, tmp_path, monkeypatch):  # noqa: F811
    for name in ("CPLAT_KUBE_CONTEXT", "KUBE_CONTEXT"):
        monkeypatch.setenv(name, "x")
        monkeypatch.delenv(name)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    return SWorld(repo, gh, store, tr, FakeDevbox(tmp_path, monkeypatch), monkeypatch)


def record_context(sw, name):
    st = sw.state()
    st["context"] = {"name": name, "source": "--context"}
    ship.save_state(sw.repo, st)


def test_the_recorded_context_makes_deploy_check_argo_and_record_the_smoke_ac_203_1(sw, monkeypatch, capsys):  # AC-203.1
    dg = staged(sw, monkeypatch)
    record_context(sw, "lan")
    sw.fake.script([PASS_ALL])
    assert sw.deploy(context=None) == 0
    out = "\n".join(lines_of(capsys))
    assert "Argo CD shop-api-dev" in out and "Argo health not checked" not in out
    assert dg.running_calls and dg.running_calls[0][0] == "lan"
    st = sw.state()
    assert st["phase"] == "done" and st["smoke"]["outcome"] == "passed"
    assert sw.record()["smoke"]["outcome"] == "passed"            # recorded in the run, not "not run"
