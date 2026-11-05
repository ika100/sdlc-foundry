"""Spec 142 (AC-142.4): staging set to `after-dev-smoke` followed only a ship's dev smoke; a fix build and a release build
that passed `instance verify dev` each needed a manual promotion (journey 2026-11-05). A green `instance verify dev` now
promotes staging the way a ship does: same decision, digest check, pin-staging dispatch."""
import subprocess
from types import SimpleNamespace

import pytest
import smoke

D = "sha256:" + "1" * 64


class Res:
    outcome, ok, env, digest = "passed", True, "dev", D

    def row(self):
        return "passed 3/3"

    def section(self):
        return {"env": "dev", "outcome": "passed"}

    def lines(self):
        return ["smoke: 3 passed"]


@pytest.fixture()
def wired(monkeypatch):
    import registry
    import ship
    import staging
    calls = []
    monkeypatch.setattr(staging, "decide", lambda repo, st, apps, svc, dev: SimpleNamespace(
        action="promote", reason=None, app="acme/shop-gitops", service="shop-api", tag=st["deployed"]))
    monkeypatch.setattr(staging, "_find", lambda repo, apps, svc: (None, None, SimpleNamespace(image="ghcr.io/acme/shop-api")))
    monkeypatch.setattr(staging, "record_url", lambda rid: f"https://example.com/{rid}")
    monkeypatch.setattr(staging, "gh", lambda args, **kw: calls.append(args) or "")
    monkeypatch.setattr(registry, "image_name", lambda found, slug: "ghcr.io/acme/shop-api")
    monkeypatch.setattr(ship, "service_slug", lambda repo: "acme/shop-api")
    return calls, registry, monkeypatch


def test_a_green_dev_verify_dispatches_pin_staging_ac_142_4(wired, tmp_path):  # AC-142.4
    calls, registry, mp = wired
    mp.setattr(registry, "digest", lambda image, tag: D)
    lines = smoke.follow_staging(tmp_path, ["acme/shop-gitops"], "shop-api", Res(), "sha-" + "a" * 40, "rid1")
    assert "dispatched pin-staging shop-api sha-" in lines[0]
    assert calls and calls[0][:2] == ["api", "repos/acme/shop-gitops/dispatches"] and "event_type=pin-staging" in calls[0]


def test_a_changed_digest_promotes_nothing_ac_142_4(wired, tmp_path):  # AC-142.4
    calls, registry, mp = wired
    mp.setattr(registry, "digest", lambda image, tag: "sha256:" + "2" * 64)
    lines = smoke.follow_staging(tmp_path, ["acme/shop-gitops"], "shop-api", Res(), "sha-" + "a" * 40, "rid1")
    assert "not promoted" in lines[0] and not calls


def test_verify_in_staging_or_red_never_promotes_ac_142_4(monkeypatch, tmp_path):  # AC-142.4
    import ship
    called = []
    monkeypatch.setattr(smoke, "follow_staging", lambda *a, **kw: called.append(a) or [])
    monkeypatch.setattr(smoke, "record", lambda *a, **kw: "rid")
    monkeypatch.setattr(smoke, "pinned_image", lambda *a, **kw: "sha-x")
    monkeypatch.setattr(smoke, "dev_url", lambda *a, **kw: ("http://x", None))
    monkeypatch.setattr(ship, "gitops_apps", lambda repo: ["acme/shop-gitops"])
    monkeypatch.setattr(ship, "service_name", lambda repo: "shop-api")
    monkeypatch.setattr(smoke, "liveness_probe", lambda repo: None)
    monkeypatch.setattr(smoke, "run_smoke", lambda *a, **kw: Res())
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    assert smoke.main(["run", "--repo", str(tmp_path), "staging"]) == 0 and called == []
    assert smoke.main(["run", "--repo", str(tmp_path), "dev"]) == 0 and len(called) == 1
