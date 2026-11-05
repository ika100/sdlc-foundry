"""Found in the 2026-11-05 journey: in the system flow, a repo's spec is published as a draft PR on `feature/<spec>`, and the
ship reuses that PR as the code PR. It stayed a draft, so GitHub refused the merge (and the error blamed merge conflicts).
`ship pr` now marks a reused draft ready, and `land` does so before it merges."""
import json

import ship
from test_ship import gh, repo  # noqa: F401  (pytest fixtures)


def test_a_reused_draft_pr_is_marked_ready(repo, gh, monkeypatch):  # noqa: F811
    calls = []
    real = ship.gh

    def fake(args, *, cwd, check=True):
        calls.append(args)
        if args[:2] == ["pr", "list"] and "--head" in args:
            return json.dumps([{"number": 7, "url": "https://github.com/acme/shop-api/pull/7", "title": "docs(spec): 007",
                                "labels": [], "isDraft": True}])
        if args[:2] in (["pr", "ready"], ["pr", "edit"]):
            return ""
        return real(args, cwd=cwd, check=check)
    monkeypatch.setattr(ship, "gh", fake)
    monkeypatch.setattr(ship, "nothing_to_merge", lambda _repo: False)
    ship.start(repo, "7", True)
    from test_ship import git
    git(repo, "checkout", "-qb", "feature/007-price-alerts")
    body = repo / ".git" / "PR_BODY.md"
    body.write_text("## Summary\n")
    ship.open_pr(repo, "feat(alerts): price alerts", body)
    assert ["pr", "ready", "https://github.com/acme/shop-api/pull/7"] in calls
