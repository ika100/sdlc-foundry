"""Spec 122 acceptance tests: what lies between two refs of a component (AC-122.34, AC-122.35, AC-122.47).

Contract: plan task t2 (scripts/cplat/releases.py). `releases.gh(args) -> str` is the one replaceable GitHub call; here it answers
`gh api repos/<r>/compare/<base>...<head>` with the GitHub compare document."""
import json

import pytest

PATCH_ADD = "@@ -0,0 +1,3 @@\n+def upgrade():\n+    op.add_column('cart', sa.Column('note', sa.Text()))\n"
PATCH_DROP = "@@ -0,0 +1,3 @@\n+def upgrade():\n+    op.drop_column('cart', 'legacy')\n"


def compare_doc(commits, files):
    return {"commits": [{"sha": f"{i:040d}", "commit": {"message": m}} for i, m in enumerate(commits)], "files": files}


@pytest.fixture()
def fake_gh(monkeypatch):
    import releases
    state = {"doc": compare_doc([], []), "calls": []}

    def gh(args):
        state["calls"].append(list(args))
        if any("compare" in a for a in args):
            return json.dumps(state["doc"])
        return ""

    monkeypatch.setattr(releases, "gh", gh)
    return state


def test_between_counts_commits_and_names_specs_and_fixes_ac_122_34(fake_gh):  # AC-122.34
    import releases
    fake_gh["doc"] = compare_doc(
        ["feat: checkout\n\nspec: 012-checkout", "fix: rounding in total (#57)", "chore: bump"],
        [{"filename": "docs/specs/012-checkout/spec.md", "status": "added", "patch": ""},
         {"filename": "src/cart.py", "status": "modified", "patch": ""}])
    r = releases.between("acme/shop-api", "1.3.0", "1.4.0")
    assert r["commits"] == 3 and "012-checkout" in r["specs"] and any("57" in str(f) for f in r["fixes"])
    assert any("compare/1.3.0...1.4.0" in a for a in fake_gh["calls"][0])


def test_an_additive_migration_is_marked_additive_ac_122_35(fake_gh):  # AC-122.35
    import releases
    fake_gh["doc"] = compare_doc(["feat: note"], [{"filename": "migrations/versions/0004_note.py", "status": "added", "patch": PATCH_ADD}])
    m = releases.between("acme/shop-api", "1.3.0", "1.4.0")["migrations"]
    assert [(x["file"], x["additive"]) for x in m] == [("migrations/versions/0004_note.py", True)]


def test_a_migration_that_drops_a_column_is_not_additive_ac_122_35(fake_gh):  # AC-122.35
    import releases
    fake_gh["doc"] = compare_doc(["feat: drop"], [{"filename": "migrations/versions/0005_drop.py", "status": "added", "patch": PATCH_DROP}])
    m = releases.between("acme/shop-api", "1.3.0", "1.4.0")["migrations"]
    assert [(x["file"], x["additive"]) for x in m] == [("migrations/versions/0005_drop.py", False)]


def test_between_never_raises_when_github_fails_ac_122_34(monkeypatch):  # AC-122.34
    import releases

    def boom(args):
        raise RuntimeError("offline")

    monkeypatch.setattr(releases, "gh", boom)
    r = releases.between("acme/shop-api", "1.3.0", "1.4.0")
    assert r["commits"] is None


@pytest.mark.parametrize("subjects, want", [
    (["fix: a", "chore: b"], "1.3.1"),
    (["fix: a", "feat: b"], "1.4.0"),
    (["feat!: break the api", "feat: b"], "2.0.0"),
    (["fix: a\n\nBREAKING CHANGE: gone"], "2.0.0"),
])
def test_the_next_version_follows_conventional_commits_ac_122_47(subjects, want):  # AC-122.47
    import releases
    assert releases.next_version("1.3.0", subjects).lstrip("v") == want
