"""Spec 129 acceptance tests: the upgrade e2e on the merge commit, the gate, the tag stop, tagging, the GitHub release, the
release guard and the tag rules (AC-129.12 to AC-129.16, AC-129.19). Contract: design.md, section Contract."""
import sys

import pytest

from platrelease_world import NOTES, SLUG, run_entry, w  # noqa: F401  (w is a fixture)

TAG = "v5.5.0"
RELEASE_URL = f"https://github.com/{SLUG}/releases/tag/{TAG}"


def e2e_lists(w):
    return [c for c in w.gh.calls if c[:2] == ["run", "list"] and "e2e-upgrade.yml" in c]


# ---------------- AC-129.12 ----------------

def test_the_wait_keeps_going_until_the_e2e_run_appears(w):  # AC-129.12
    w.in_state("merged")
    w.e2e_seq = [[], [], [], [], [run_entry(100)]]
    r = w.run()
    assert r.rc == 3 and "CONFIRM: tag" in r.out, r.text
    first = e2e_lists(w)[0]
    assert first[first.index("--commit") + 1] == w.merge_sha
    assert first[first.index("--workflow") + 1] == "e2e-upgrade.yml" and first[first.index("--event") + 1] == "push"
    assert "databaseId,status,conclusion,url" in first
    assert len(e2e_lists(w)) >= 5 and w.clock["t"] >= 80


def test_of_two_runs_only_the_newest_counts(w):  # AC-129.12
    w.in_state("merged")
    w.e2e_seq = [[run_entry(10, conclusion="cancelled"), run_entry(11)]]
    r = w.run()
    assert r.rc == 3 and "CONFIRM: tag" in r.out, r.text


def test_a_red_newest_run_stops_before_any_tag(w):  # AC-129.12
    w.in_state("merged")
    w.e2e_seq = [[run_entry(10), run_entry(11, conclusion="failure")]]
    r = w.run()
    assert r.rc == 1 and w.merge_sha[:7] in r.err and "red: https://github.com/acme/shop/actions/runs/11" in r.err
    assert TAG not in w.origin_tags() and w.check_cmd("gate") == [] and w.gh.writes() == []


def test_a_run_that_never_appears_fails_after_ten_minutes_without_a_tag(w):  # AC-129.12
    import platrelease_publish
    assert platrelease_publish.APPEAR_WINDOW == 600
    w.in_state("merged")
    w.e2e_seq = [[]]
    r = w.run()
    assert r.rc == 1 and w.merge_sha[:7] in r.err and "did not start within 10 minutes" in r.err
    assert 600 <= w.clock["t"] < 5400
    assert TAG not in w.origin_tags() and w.check_cmd("gate") == [] and w.gh.writes() == []


# ---------------- AC-129.13 ----------------

def test_a_failing_gate_prints_its_output_and_tags_and_releases_nothing(w):  # AC-129.13
    w.in_state("merged")
    out = f"ERROR: {w.merge_sha} has no green upgrade e2e (none): do not tag it"
    w.results["gate"] = (1, out)
    r = w.run()
    assert r.rc == 1 and out in r.text and "release-check gate failed" in r.err
    cwd, cmd = w.check_calls[-1]
    assert cwd == w.repo and cmd[:3] == [sys.executable, "scripts/release-check.py", "gate"] and cmd[3] == w.merge_sha
    assert TAG not in w.origin_tags() and w.git("tag", "-l", TAG).strip() == "" and w.gh.writes() == []


# ---------------- AC-129.14 ----------------

def test_the_tag_stop_shows_what_it_will_publish_and_creates_nothing(w):  # AC-129.14
    w.in_state("merged")
    r = w.run()
    assert r.rc == 3, r.text
    for line in ("CONFIRM: tag", "  tag: v5.5.0", f"  merge commit: {w.merge_sha}", "  release notes:",
                 "  continue: cplat platform release --confirm tag"):
        assert line in r.out, (line, r.out)
    assert f"--- release notes ---\n{NOTES}\n--- end ---" in r.out
    assert TAG not in w.origin_tags() and w.git("tag", "-l", TAG).strip() == "" and w.gh.writes() == []


# ---------------- AC-129.15 ----------------

def test_the_confirmation_tags_the_merge_commit_and_publishes_the_section_as_notes(w):  # AC-129.15
    w.in_state("merged")
    r = w.run("--confirm", "tag")
    assert r.rc == 0, r.text
    assert w.origin_tags()[TAG] == w.merge_sha
    assert w.git("cat-file", "-t", f"refs/tags/{TAG}").strip() == "tag"
    assert w.git("cat-file", "-t", f"refs/tags/{TAG}", cwd=w.origin).strip() == "tag"
    create = [c for c in w.gh.calls if c[:2] == ["release", "create"]]
    assert len(create) == 1
    c = create[0]
    assert c[2] == TAG and "--verify-tag" in c and c[c.index("-R") + 1] == SLUG and c[c.index("--title") + 1] == TAG
    assert c[c.index("--notes-file") + 1].endswith("RELEASE_NOTES.md")
    assert w.release_notes.strip() == NOTES
    assert "## [5.5.0]" not in w.release_notes and "Old notes" not in w.release_notes


def test_the_release_notes_are_taken_from_the_merge_commit(w):  # AC-129.15
    w.in_state("merged")
    w.run("--confirm", "tag")
    assert w.release_notes.strip() == w.git("show", f"{w.merge_sha}:docs/CHANGELOG.md").split("## [5.5.0] - 2026-06-15\n")[1].split("\n## [")[0].strip()


# ---------------- AC-129.16 ----------------

def test_a_green_release_guard_finishes_the_release_with_both_urls(w):  # AC-129.16
    w.in_state("merged")
    w.guard_seq = [[], [], [run_entry(200, branch=TAG), run_entry(300, "completed", "failure", "v5.4.0")]]
    r = w.run("--confirm", "tag")
    assert r.rc == 0, r.text
    assert "RELEASED: v5.5.0" in r.out and f"  tag: https://github.com/{SLUG}/tree/v5.5.0" in r.out
    assert f"  release: {RELEASE_URL}" in r.out
    guard = [c for c in w.gh.calls if c[:2] == ["run", "list"] and "release-guard.yml" in c]
    assert len(guard) >= 3 and w.clock["t"] >= 40
    g = guard[0]
    assert g[g.index("--event") + 1] == "push" and g[g.index("--limit") + 1] == "50" and g[g.index("-R") + 1] == SLUG


def test_a_red_release_guard_exits_non_zero_and_leaves_tag_and_release(w):  # AC-129.16
    w.in_state("merged")
    w.guard_seq = [[run_entry(201, "completed", "failure", TAG)]]
    r = w.run("--confirm", "tag")
    assert r.rc == 1
    assert f"release-guard on {TAG} is red: https://github.com/{SLUG}/actions/runs/201; the tag and the release stay" in r.err
    assert w.origin_tags()[TAG] == w.merge_sha and w.release_url == RELEASE_URL
    assert [c for c in w.gh.calls if c[:2] == ["release", "delete"]] == []
    assert w.git("tag", "-l", TAG).strip() == TAG


def test_a_red_release_guard_is_reported_again_on_a_rerun_without_touching_the_tag(w):  # AC-129.16
    w.in_state("released")
    w.guard_seq = [[run_entry(201, "completed", "failure", TAG)]]
    r = w.run()
    assert r.rc == 1 and f"release-guard on {TAG} is red" in r.err
    assert w.origin_tags()[TAG] == w.merge_sha and w.gh.writes() == []


# ---------------- AC-129.19 ----------------

@pytest.mark.parametrize("argv", [(), ("--confirm", "tag")])
def test_a_tag_on_another_commit_stops_the_run_naming_both_commits(w, argv):  # AC-129.19
    w.in_state("merged")
    w.tag("5.5.0", sha=w.t540)
    w.git("fetch", "-q", "origin", "--tags")
    r = w.run(*argv)
    assert r.rc == 1
    assert f"tag {TAG} is on {w.t540}, not on the release's merge commit {w.merge_sha}" in r.err
    assert w.origin_tags()[TAG] == w.t540 and w.git("rev-parse", f"{TAG}^{{commit}}").strip() == w.t540
    assert w.gh.writes() == []


def test_a_local_tag_on_another_commit_is_never_moved(w):  # AC-129.19
    w.in_state("merged")
    w.tag("5.5.0", sha=w.t540, push=False)
    r = w.run("--confirm", "tag")
    assert r.rc == 1 and w.t540[:7] in r.err and w.merge_sha[:7] in r.err
    assert TAG not in w.origin_tags() and w.git("rev-parse", f"{TAG}^{{commit}}").strip() == w.t540
    assert w.gh.writes() == []


def test_a_local_tag_on_the_merge_commit_is_pushed_not_recreated(w):  # AC-129.19
    w.in_state("merged")
    w.tag("5.5.0", push=False)
    obj = w.git("rev-parse", f"refs/tags/{TAG}").strip()
    r = w.run("--confirm", "tag")
    assert r.rc == 0, r.text
    assert w.origin_tags()[TAG] == w.merge_sha and w.git("rev-parse", f"refs/tags/{TAG}").strip() == obj
