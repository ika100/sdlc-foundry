"""Found in the 2026-11-05 journey: an organization-level GITOPS_TOKEN (visible to the repo) counts. `component ship start`
refused with "the secret GITOPS_TOKEN is not set" because only the repo's own secrets were read."""
import json

import ship


def fake(own, org, org_fails=False):
    def gh(args, *, cwd, check=True):
        if args[:2] == ["secret", "list"]:
            return json.dumps([{"name": n} for n in own])
        if args[0] == "api" and args[1].endswith("/actions/organization-secrets"):
            if org_fails:
                raise ship.PlatformError("HTTP 404")
            return json.dumps(org)
        raise AssertionError(args)
    return gh


def _linked(monkeypatch, tmp_path, gh):
    monkeypatch.setattr(ship, "gh", gh)
    monkeypatch.setattr(ship, "gitops_apps", lambda repo: ["acme/shop-gitops"])
    monkeypatch.setattr(ship, "service_slug", lambda repo: "acme/shop-api")


def test_an_org_secret_counts(monkeypatch, tmp_path):
    _linked(monkeypatch, tmp_path, fake([], ["GITOPS_TOKEN"]))
    assert not ship.missing_gitops_token(tmp_path)
    assert ship.secret_names(tmp_path) == {"GITOPS_TOKEN"}


def test_a_repo_secret_still_counts_and_none_is_missing(monkeypatch, tmp_path):
    _linked(monkeypatch, tmp_path, fake(["GITOPS_TOKEN"], [], org_fails=True))
    assert not ship.missing_gitops_token(tmp_path)
    _linked(monkeypatch, tmp_path, fake(["OTHER"], [], org_fails=True))
    assert ship.missing_gitops_token(tmp_path)


def test_new_repos_skip_the_token_step_when_the_org_secret_covers_them(monkeypatch):
    import subprocess

    import newsvc
    monkeypatch.setattr(newsvc, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, '["GITOPS_TOKEN"]', ""))
    assert newsvc.has_org_secret("acme/shop-api")
    monkeypatch.setattr(newsvc, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "HTTP 404"))
    assert not newsvc.has_org_secret("me/shop-api")
