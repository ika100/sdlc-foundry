"""Spec 122 verification round A: `cplat needs` lists untracked issues, and a promote item has a real `since` and verified digest."""
import json

import cplat
import status
from test_needs import issue, items, needs_json, status_rows, world  # noqa: F401


def test_issues_without_the_tracked_label_are_listed(world, capsys):
    plain, tracked = issue(5, ["bug"], title="Crash"), issue(6, ["tracked"], title="Planned")
    world.gh.issues["acme/shop-api"] = [plain, tracked]
    doc = needs_json(world, capsys)
    assert {i["number"] for i in doc["issues"]} == {5}
    found = doc["issues"][0]
    assert found["repo"] == "acme/shop-api" and found["labels"] == ["bug"] and found["state"] in ("open", "closed")
    assert {"title", "created_at", "closed_at", "url"} <= set(found)
    assert all(i["number"] != 6 for i in doc["issues"])


def test_promote_since_is_the_staging_smoke_time_and_the_verified_digest_is_the_smokes(world, capsys):
    world.monkeypatch.setattr(status, "collect", lambda *a, **k: status_rows(staging="verified"))
    world.monkeypatch.setattr(status, "_smoke", lambda repo, tag, env: {"at": "2026-10-21T09:00:00Z", "digest": "sha256:bbbb"})
    [p] = items(needs_json(world, capsys), "promote")
    assert p["since"] == "2026-10-21T09:00:00Z"
    assert p["consequence"]["verified_digest"] == "sha256:bbbb" and p["consequence"]["digest_matches"] is False


def test_promote_since_falls_back_to_the_pin_commit_time_and_is_never_empty(world, capsys):
    world.monkeypatch.setattr(status, "collect", lambda *a, **k: status_rows(staging="verified"))
    world.monkeypatch.setattr(status, "_smoke", lambda *a: None)
    orig = world.gh.__call__

    def gh(args):
        if args[:1] == ["api"] and "/commits/" in args[1]:
            return json.dumps({"commit": {"committer": {"date": "2026-10-19T07:00:00Z"}}})
        return orig(args)
    import needs
    world.monkeypatch.setattr(needs, "gh", gh)
    [p] = items(needs_json(world, capsys), "promote")
    assert p["since"] == "2026-10-19T07:00:00Z" and p["consequence"]["digest_matches"] is True
    world.monkeypatch.setattr(needs, "gh", orig)
    [p] = items(needs_json(world, capsys), "promote")
    assert p["since"]
