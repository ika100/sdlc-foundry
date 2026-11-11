"""Spec 178 acceptance tests: a release whose branch is behind `main` stops (AC-178.1).

The world is the spec 129 release world (a bare origin, a scripted `gh` behind `ship.gh`, a fake clock). `main` moves by a commit that
a person pushes from `other`, and GitHub's compare answer (`behind_by`) says so, as it does for the merge lock.
"""
import pytest

import ship
from platrelease_world import w  # noqa: F401  (w is a fixture)

VERSION = "5.5.0"
FIRST = "main moved: start the release again"


def fix_line(w):
    return (f"  fix: close the release PR (gh pr close {w.pr_url}), delete the release branch "
            f"(git push origin --delete release/{VERSION}; git branch -D release/{VERSION}), run cplat platform release")


def main_moves(w):
    """A person merges another pull request into main."""
    o = w.other
    w.git("fetch", "-q", "origin", cwd=o)
    w.git("checkout", "-q", "main", cwd=o)
    w.git("merge", "-q", "--ff-only", "origin/main", cwd=o)
    (o / "another.txt").write_text("a change on main\n")
    w.git("add", "-A", cwd=o)
    w.git("commit", "-q", "-m", "feat: another change", cwd=o)
    w.git("push", "-q", "origin", "main", cwd=o)


def behind_when(w, monkeypatch, moves_at):
    """GitHub says the branch is behind main from the `moves_at`-th `gh pr checks` on (0: from the start); main moves then."""
    seen = {"checks": 0, "behind": 0}
    if moves_at == 0:
        main_moves(w)
        seen["behind"] = 1

    def gh(args, *, cwd, check=True):
        if args[:2] == ["pr", "checks"]:
            seen["checks"] += 1
            if seen["checks"] == moves_at:
                main_moves(w)
                seen["behind"] = 1
        if args[:1] == ["api"] and "/compare/" in args[1]:
            w.gh.calls.append(list(args))
            return f"{seen['behind']}\n"
        return w.gh(args, cwd=cwd, check=check)
    monkeypatch.setattr(ship, "gh", gh)


def release_branch(w):
    return w.git("ls-remote", "origin", f"refs/heads/release/{VERSION}").split()[0]


@pytest.mark.parametrize("moves_at", [0, 2], ids=["before-the-waits", "while-it-waits-for-the-checks"])
def test_a_release_behind_main_stops_changes_nothing_and_says_what_to_do(w, monkeypatch, moves_at):  # AC-178.1
    w.in_state("pr-open", VERSION)
    branch_before = release_branch(w)
    behind_when(w, monkeypatch, moves_at)
    r = w.run("--confirm", "merge")
    assert r.rc == 1, r.text
    lines = [ln for ln in r.err.splitlines() if not ln.startswith("WARNING: run record buffered")]   # the test world has no run store
    assert lines[:2] == [FIRST, fix_line(w)], r.err
    assert w.merges == [] and w.merge_sha is None
    assert release_branch(w) == branch_before                           # nothing pushed to the release branch
    assert [c for c in w.gh.calls if c[:2] in (["pr", "update-branch"], ["pr", "merge"])] == []
    assert w.git("rev-parse", "--abbrev-ref", "HEAD").strip() == "main"


def test_a_release_that_is_not_behind_main_still_merges(w):  # AC-178.1
    w.in_state("pr-open", VERSION)
    r = w.run("--confirm", "merge")
    assert r.rc != 1 or FIRST not in r.err, r.text
    assert len(w.merges) == 1 and FIRST not in r.err
