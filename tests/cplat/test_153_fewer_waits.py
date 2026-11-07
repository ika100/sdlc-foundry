"""Spec 153 acceptance tests: one Argo CD refresh in the ship's deploy wait, and gh's offline wording retried.

Seams: `ship.run` (a scripted kubectl), `ship.now` / `ship.sleep` / `ship.say`; `core.subprocess.run` and `core.sleep`."""
import json
import subprocess

import pytest

import core
import ship

APP = "taskboard-api-dev"
IMG = "sha-4f2a91c"


class Argo:
    def __init__(self, monkeypatch, ready_after: int):
        self.t, self.polls, self.calls, self.said = 0.0, 0, [], []
        self.ready_after = ready_after
        monkeypatch.setattr(ship, "run", self.run)
        monkeypatch.setattr(ship, "now", lambda: self.t)
        monkeypatch.setattr(ship, "sleep", self.sleep)
        monkeypatch.setattr(ship, "say", self.said.append)

    def sleep(self, s):
        self.t += s

    def run(self, cmd, **kw):
        self.calls.append(cmd)
        if "annotate" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        self.polls += 1
        image = f"ghcr.io/acme/api:{IMG}" if self.polls > self.ready_after else "ghcr.io/acme/api:sha-0000000"
        st = {"summary": {"images": [image]}, "sync": {"status": "Synced", "revision": "abc"}, "health": {"status": "Healthy"}}
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"status": st}), "")

    def refreshes(self):
        return [c for c in self.calls if "annotate" in c]


def test_a_deploy_that_waits_gets_one_hard_refresh_after_45_seconds_ac_153_1(monkeypatch):  # AC-153.1
    argo = Argo(monkeypatch, ready_after=12)
    assert ship.argo_health("k3d-x", APP, 300, 10, images={IMG}) == "Synced/Healthy"
    [refresh] = argo.refreshes()
    assert refresh[-3:] == [APP, "argocd.argoproj.io/refresh=hard", "--overwrite"]
    assert argo.calls.index(refresh) >= 5 and any(f"hard refresh of {APP}" in s for s in argo.said)


def test_a_deploy_ready_sooner_gets_no_refresh_ac_153_1(monkeypatch):  # AC-153.1
    argo = Argo(monkeypatch, ready_after=2)
    assert ship.argo_health("k3d-x", APP, 300, 10, images={IMG}) == "Synced/Healthy" and argo.refreshes() == []


@pytest.mark.parametrize("stderr", ["error connecting to api.github.com\ncheck your internet connection or https://githubstatus.com"])
def test_gh_offline_wording_is_retried_ac_153_2(monkeypatch, stderr):  # AC-153.2
    monkeypatch.setattr(core, "NETWORK_RETRY_MAX_WAIT", 300)
    calls, slept = [], []

    def fake(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1 if len(calls) < 3 else 0, "", stderr if len(calls) < 3 else "")
    monkeypatch.setattr(core.subprocess, "run", fake)
    monkeypatch.setattr(core, "sleep", slept.append)
    assert core.run(["gh", "pr", "merge", "5", "--squash"]).returncode == 0 and len(calls) == 3 and slept == [10, 20]
