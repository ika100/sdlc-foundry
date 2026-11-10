"""dispatch_backlog (spec 167 t10): the snapshot and the candidate list, read with the fake `gh` and a temp git repo of `dispatch_world`."""
import datetime as dt

import dispatch_policy
import pytest

from dispatch_world import SLUG, git, world  # noqa: F401  (fixture)


def _backlog():
    import dispatch_backlog
    return dispatch_backlog


def _items(world, **policy):
    world.policy(**policy)
    pol = dispatch_policy.load(world.repo)
    snap = _backlog().snapshot(world.repo, SLUG, max_age=0)
    return [c.item for c in _backlog().candidates(snap, pol)]


def test_issues_are_candidates_by_label(world):
    world.issue(1, labels=["triaged", "bug"])
    world.issue(2, labels=["bug"])
    world.issue(3, labels=["triaged", "needs-decision"])
    world.issue(4, labels=["triaged", "wontfix"])
    world.issue(5, labels=["triaged", "bug", "blocked"])
    world.issue(6, labels=["triaged"])
    assert _items(world) == ["#1", "#5", "#6"]
    assert _items(world, ready={"labels": ["bug"], "exclude_labels": ["blocked"]}) == ["#1"]


def test_specs_by_status_and_sources(world):
    world.spec(7, "price-alerts", status="approved")
    world.spec(8, "refunds", status="draft")
    world.spec(9, "old", status="done")
    world.spec(10, "busy", status="building")
    world.issue(1)
    assert _items(world, sources=["specs"]) == ["spec-007", "spec-008", "spec-010"]
    assert _items(world, sources=["issues", "specs"]) == ["#1", "spec-007", "spec-008", "spec-010"]
    assert _items(world, sources=["issues"]) == ["#1"]


def test_a_spec_carries_the_issues_it_tracks_and_its_meta(world):
    world.issue(42, labels=["triaged", "tracked"])
    sid = world.spec(7, "price-alerts", tracks=(42,), priority="P0", created="2026-10-03")
    world.policy(sources=["issues", "specs"])
    snap = _backlog().snapshot(world.repo, SLUG, max_age=0)
    by = {c.item: c for c in _backlog().candidates(snap, dispatch_policy.load(world.repo))}
    spec = by["spec-007"]
    assert spec.kind == "ship" and spec.tracks == [42] and spec.spec_id == sid and spec.status == "approved"
    assert spec.spec["priority"] == "P0" and spec.created == "2026-10-03T00:00:00Z" and spec.spec["plan"]
    assert by["#42"].kind == "fix" and by["#42"].number == 42


def test_a_draft_spec_pr_is_a_candidate(world, monkeypatch):
    world.spec(8, "refunds", status="draft")
    text = git(world.repo, "show", "origin/main:docs/specs/008-refunds/spec.md").replace("008-refunds", "009-extra")
    world.pr(50, "spec/009-extra", body="<!-- cplat:spec 009-extra -->\nA draft.")
    mod = _backlog()
    monkeypatch.setattr(mod, "_contents", lambda repo, slug, path, ref: text if "009-extra" in path and ref == "spec/009-extra" else "")
    world.policy(sources=["specs"])
    snap = mod.snapshot(world.repo, SLUG, max_age=0)
    cands = {c.item: c for c in mod.candidates(snap, dispatch_policy.load(world.repo))}
    assert sorted(cands) == ["spec-008", "spec-009"]
    assert cands["spec-009"].status == "draft" and cands["spec-009"].pr["number"] == 50
    assert cands["spec-008"].pr is None


def test_a_snapshot_changes_nothing_on_github_or_in_git(world):
    world.issue(1, labels=["triaged", "in-progress"], comments=["<!-- cplat-claim -->\nClaimed for branch `fix/issue-1` (cplat dispatch)."])
    world.pr(40, "fix/by-hand", closes=[1])
    world.spec(7, "price-alerts")
    before = world.fingerprint()
    snap = _backlog().snapshot(world.repo, SLUG, max_age=0, fetch=False)
    assert world.fingerprint() == before and world.gh_writes() == []
    assert [i["number"] for i in snap.issues] == [1] and snap.issues[0]["comments"][0]["body"].startswith("<!-- cplat-claim")
    assert snap.prs[0]["number"] == 40 and snap.prs[0]["closingIssuesReferences"] == [{"number": 1}]
    assert snap.main_sha == git(world.repo, "rev-parse", "origin/main") and [s["id"] for s in snap.specs] == ["007-price-alerts"]


def test_comments_are_read_only_for_issues_with_in_progress_or_stale_premise(world):
    world.issue(1, labels=["triaged"], comments=["hello"])
    world.issue(2, labels=["triaged", "in-progress"], comments=["hello"])
    world.issue(3, labels=["triaged", "stale-premise"], comments=["hello"])
    snap = _backlog().snapshot(world.repo, SLUG, max_age=0)
    assert ["comments" in i for i in snap.issues] == [False, True, True]
    viewed = [a[2] for a in world.gh_calls() if a[:2] == ["issue", "view"]]
    assert viewed == ["2", "3"]


def test_the_snapshot_is_cached_for_max_age_seconds_and_plan_does_not_store_it(world):
    world._patch_clock()
    world.issue(1)
    mod = _backlog()
    mod.snapshot(world.repo, SLUG, fetch=False)                       # plan: reads, stores nothing
    reads = len(world.gh_calls())
    mod.snapshot(world.repo, SLUG, fetch=False)
    assert len(world.gh_calls()) == 2 * reads
    first = mod.snapshot(world.repo, SLUG)                            # the loop: stores
    reads = len(world.gh_calls())
    world.issue(2)
    world.set_now(world.now + dt.timedelta(seconds=299))
    again = mod.snapshot(world.repo, SLUG)
    assert len(world.gh_calls()) == reads and again.read_at == first.read_at and [i["number"] for i in again.issues] == [1]
    assert [i["number"] for i in mod.snapshot(world.repo, SLUG, fetch=False).issues] == [1]   # plan uses the fresh cache too
    world.set_now(world.now + dt.timedelta(seconds=2))
    assert [i["number"] for i in mod.snapshot(world.repo, SLUG).issues] == [1, 2]


def test_a_failing_source_is_unavailable_and_keeps_the_cached_value(world, monkeypatch):
    world._patch_clock()
    world.issue(1)
    mod = _backlog()
    assert mod.snapshot(world.repo, SLUG).unavailable == {}
    real = mod.gh

    def broken(args, *, cwd):
        if args[:2] == ["issue", "list"]:
            raise mod.PlatformError("gh: rate limited\nmore")
        return real(args, cwd=cwd)
    monkeypatch.setattr(mod, "gh", broken)
    snap = mod.snapshot(world.repo, SLUG, max_age=0)
    assert snap.unavailable == {"issues": "gh: rate limited"} and [i["number"] for i in snap.issues] == [1]
    assert snap.prs == [] and snap.main_sha


def test_worktrees_list_path_and_branch(world, tmp_path):
    git(world.repo, "worktree", "add", "-q", "-b", "fix/issue-3", str(tmp_path / "wt"))
    wts = _backlog().worktrees(world.repo)
    assert {w["branch"] for w in wts} == {"main", "fix/issue-3"}
    assert any(w["path"].endswith("wt") and w["branch"] == "fix/issue-3" for w in wts)
    assert [w["branch"] for w in _backlog().snapshot(world.repo, SLUG, max_age=0).worktrees if w["path"].endswith("wt")] == ["fix/issue-3"]


@pytest.mark.parametrize("text,count", [("---\nstatus: approved\n---\n", 1), ("no front matter", 0)])
def test_a_spec_without_readable_front_matter_is_skipped(world, text, count):
    d = world.repo / "docs" / "specs" / "011-odd"
    d.mkdir(parents=True)
    (d / "spec.md").write_text(text)
    git(world.repo, "add", "-A")
    git(world.repo, "commit", "-qm", "odd")
    git(world.repo, "push", "-q", "origin", "main")
    git(world.repo, "fetch", "-q", "origin")
    assert len(_backlog().snapshot(world.repo, SLUG, max_age=0).specs) == count
