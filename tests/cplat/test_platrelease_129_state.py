"""Spec 129 acceptance tests: dry run, version proposal, preflight, plugin check, resume and the release in flight
(AC-129.1 to AC-129.5, AC-129.17, AC-129.18). Contract: design.md, section Contract. Offline: see platrelease_world."""
import re
import subprocess
import sys

import pytest

from platrelease_world import CHANGELOG, DAY, E2E, NOTES, SLUG, w, run_entry  # noqa: F401  (w is a fixture)

ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]


def no_writes(w, before):
    assert w.snapshot() == before
    assert w.created == [] and w.merges == [] and w.gh.writes() == []


# ---------------- AC-129.1 ----------------

def test_dry_run_prints_state_version_and_steps_and_creates_nothing(w):  # AC-129.1
    before = w.snapshot()
    r = w.run("--dry-run")
    assert r.rc == 0, r.text
    for line in ("newest release tag: v5.4.0 (" + w.t540[:7] + ")", "release branch: absent", "release PR: absent",
                 "merged release commit: absent", "tag v5.5.0: absent", "GitHub release v5.5.0: absent", "phase: idle",
                 "version: 5.5.0 (minor after v5.4.0, no change needs a major release)", "steps:"):
        assert line in r.out, (line, r.out)
    steps = re.findall(r"^\s+(\d+)\. (.+)$", r.out, re.M)
    assert [int(n) for n, _ in steps] == list(range(1, 13))
    texts = [t for _, t in steps]
    assert texts[0] == "check the working tree, main and docs/CHANGELOG.md"
    assert texts[1] == f"create release/5.5.0 from main and move [Unreleased] under ## [5.5.0] - {DAY.isoformat()}"
    assert texts[2] == "run release-check rows and devbox run validate"
    assert texts[3] == 'commit "chore: release 5.5.0" (signed off), push release/5.5.0 and open the PR'
    assert texts[7] == "run release-check gate the merge commit"
    assert texts[11] == "wait for the release-guard run on v5.5.0"
    no_writes(w, before)
    assert w.check_cmd("rows") == [] and w.check_cmd("validate") == []


def test_dry_run_names_the_release_in_flight_and_starts_at_its_first_step(w):  # AC-129.1
    w.in_state("merged")
    before = w.snapshot()
    r = w.run("--dry-run")
    assert r.rc == 0, r.text
    assert f"merged release commit: {w.merge_sha[:7]} chore: release 5.5.0 (#7)" in r.out
    assert "tag v5.5.0: absent" in r.out and "phase: merged" in r.out and "version: 5.5.0 (release in flight)" in r.out
    steps = re.findall(r"^\s+(\d+)\. (.+)$", r.out, re.M)
    assert steps[0][0] == "1" and steps[0][1].startswith("wait for the upgrade e2e on ")
    assert not any(t.startswith("check the working tree") for _, t in steps)
    no_writes(w, before)


def test_dry_run_shows_the_open_pr_and_the_branch(w):  # AC-129.1
    w.in_state("pr-open")
    r = w.run("--dry-run")
    assert r.rc == 0, r.text
    assert "release branch: release/5.5.0" in r.out and f"release PR: {w.pr_url}" in r.out and "phase: pr-open" in r.out
    assert re.search(r"^\s+1\. wait for CI on the PR", r.out, re.M)


def test_dry_run_is_reached_through_the_cplat_dispatcher(w):  # AC-129.1
    import cplat
    assert cplat.main(["platform", "release", "--repo", str(w.repo), "--dry-run"]) == 0


# ---------------- AC-129.2 ----------------

def test_a_minor_is_proposed_when_no_change_needs_a_major(w):  # AC-129.2
    w.results["needs-major"] = (0, "")
    r = w.run("--dry-run")
    assert r.rc == 0 and "version: 5.5.0 (minor after v5.4.0, no change needs a major release)" in r.out
    cwd, cmd = w.check_calls[0]
    assert cwd == w.repo and cmd[0] == sys.executable and cmd[1] == "scripts/release-check.py"
    assert cmd[2:] == ["needs-major", "--base", "v5.4.0"]


def test_a_major_is_proposed_and_names_the_change(w):  # AC-129.2
    w.results["needs-major"] = (0, "operator cnpg 1 → 2\nresource postgres major 16 dropped\n")
    r = w.run("--dry-run")
    assert r.rc == 0, r.text
    assert "version: 6.0.0 (major after v5.4.0: operator cnpg 1 → 2; resource postgres major 16 dropped)" in r.out
    assert "tag v6.0.0: absent" in r.out


def test_a_failing_major_detection_stops_with_its_output(w):  # AC-129.2
    w.results["needs-major"] = (1, "ERROR: cannot read the base")
    r = w.run("--dry-run")
    assert r.rc == 1 and "cannot read the base" in r.text


def test_release_check_needs_major_prints_nothing_without_a_major_change():  # AC-129.2
    p = subprocess.run([sys.executable, str(ROOT / "scripts/release-check.py"), "needs-major", "--base", "HEAD"],
                       capture_output=True, text=True, cwd=ROOT)
    assert p.returncode == 0, p.stderr + p.stdout
    assert p.stdout.strip() == ""


def test_release_check_needs_major_fails_readably_for_an_unreadable_base():  # AC-129.2
    p = subprocess.run([sys.executable, str(ROOT / "scripts/release-check.py"), "needs-major", "--base", "no-such-ref-129"],
                       capture_output=True, text=True, cwd=ROOT)
    assert p.returncode == 1 and "ERROR:" in p.stdout
    assert "Traceback" not in p.stdout + p.stderr


# ---------------- AC-129.3 ----------------

def test_a_valid_newer_version_replaces_the_proposal(w):  # AC-129.3
    r = w.run("--dry-run", "--version", "5.7.0")
    assert r.rc == 0, r.text
    assert "version: 5.7.0 (--version)" in r.out and "tag v5.7.0: absent" in r.out


def test_a_major_version_is_accepted_when_a_major_is_required(w):  # AC-129.3
    w.results["needs-major"] = (0, "operator cnpg 1 → 2\n")
    r = w.run("--dry-run", "--version", "7.0.0")
    assert r.rc == 0 and "version: 7.0.0 (--version)" in r.out


@pytest.mark.parametrize("bad", ["5.5", "v5.5.0", "five", "5.5.0.1"])
def test_a_version_that_is_not_semver_is_refused(w, bad):  # AC-129.3
    before = w.snapshot()
    r = w.run("--version", bad)
    assert r.rc != 0 and "semver" in r.text and bad in r.text
    no_writes(w, before)


@pytest.mark.parametrize("old", ["5.4.0", "5.3.9", "4.0.0"])
def test_a_version_that_is_not_newer_than_the_newest_tag_is_refused(w, old):  # AC-129.3
    before = w.snapshot()
    r = w.run("--version", old)
    assert r.rc == 1 and f"--version {old} is not newer than v5.4.0" in r.err
    no_writes(w, before)


def test_a_non_major_version_is_refused_when_a_major_is_required_and_names_the_change(w):  # AC-129.3
    w.results["needs-major"] = (0, "operator cnpg 1 → 2\n")
    before = w.snapshot()
    r = w.run("--version", "5.6.0")
    assert r.rc == 1
    assert "--version 5.6.0 is not a major release; needs a major: operator cnpg 1 → 2" in r.err
    no_writes(w, before)


# ---------------- AC-129.4 ----------------

def test_uncommitted_changes_stop_the_run_before_a_branch(w):  # AC-129.4
    (w.repo / "scratch.txt").write_text("x")
    before = w.snapshot()
    r = w.run()
    assert r.rc == 1 and "uncommitted changes" in r.err and "scratch.txt" in r.err
    no_writes(w, before)


def test_a_local_main_that_differs_from_origin_stops_the_run(w):  # AC-129.4
    (w.repo / "README.md").write_text("local only\n")
    w.git("commit", "-q", "-am", "local only")
    before = w.snapshot()
    r = w.run()
    assert r.rc == 1 and "local main" in r.err and "differs from origin/main" in r.err
    assert w.git("rev-parse", "main").strip() in r.err or w.git("rev-parse", "main")[:7] in r.err
    no_writes(w, before)


def test_an_empty_unreleased_section_stops_the_run(w):  # AC-129.4
    text = CHANGELOG.replace(NOTES, "")
    (w.repo / "docs/CHANGELOG.md").write_text(text)
    w.git("commit", "-q", "-am", "docs: empty unreleased")
    w.git("push", "-q", "origin", "main")
    before = w.snapshot()
    r = w.run()
    assert r.rc == 1 and "## [Unreleased] in docs/CHANGELOG.md has no content" in r.err
    no_writes(w, before)
    assert not [b for b in w.git("branch", "--list").split() if b.startswith("release/")]


# ---------------- AC-129.5 ----------------

def test_a_plugin_whose_versions_differ_is_named_and_nothing_is_edited(w):  # AC-129.5
    plugin = w.repo / "plugins/alpha/.claude-plugin/plugin.json"
    plugin.write_text(plugin.read_text().replace("1.0.0", "1.0.1"))
    market = (w.repo / ".claude-plugin/marketplace.json").read_text()
    before, plugin_text = w.snapshot(), plugin.read_text()
    for argv in ((), ("--dry-run",)):
        r = w.run(*argv)
        assert r.rc == 1 and "alpha: marketplace 1.0.0, plugin.json 1.0.1" in r.err, r.text
    assert plugin.read_text() == plugin_text and (w.repo / ".claude-plugin/marketplace.json").read_text() == market
    no_writes(w, before)


def test_a_version_mismatch_also_stops_a_release_in_flight(w):  # AC-129.5
    w.in_state("pr-open")
    plugin = w.repo / "plugins/alpha/.claude-plugin/plugin.json"
    plugin.write_text(plugin.read_text().replace("1.0.0", "2.0.0"))
    before = w.snapshot()
    r = w.run("--confirm", "merge")
    assert r.rc == 1 and "alpha: marketplace 1.0.0, plugin.json 2.0.0" in r.err
    no_writes(w, before)


# ---------------- AC-129.17 ----------------

def test_a_release_branch_without_a_pr_continues_by_opening_the_pr(w):  # AC-129.17
    sha = w.in_state("branch") or w.git("rev-parse", "origin/release/5.5.0").strip()
    r = w.run()
    assert "phase: branch" in r.out and "release branch: release/5.5.0" in r.out
    assert len(w.created) == 1 and w.created[0][w.created[0].index("--head") + 1] == "release/5.5.0"
    assert w.git("rev-parse", "origin/release/5.5.0").strip() == sha          # no second commit
    assert w.ahead("origin/release/5.5.0") == 1
    assert w.merges == [] and r.rc == 3, r.text                                # on to the merge stop


def test_an_open_release_pr_continues_by_waiting_for_ci(w):  # AC-129.17
    w.in_state("pr-open")
    w.check_seq = [[chk_("quality", "pending"), chk_(E2E, "pending", 43)], [chk_("quality", "pass"), chk_(E2E, "pass", 43)]]
    r = w.run()
    assert "phase: pr-open" in r.out and w.created == [] and r.rc == 3, r.text
    assert len([c for c in w.gh.calls if c[:2] == ["pr", "checks"]]) >= 2
    assert w.check_cmd("rows") == [] and w.check_cmd("validate") == []         # nothing is prepared again
    assert w.ahead("origin/release/5.5.0") == 1


def test_a_merged_release_commit_without_a_tag_continues_with_the_upgrade_e2e(w):  # AC-129.17
    w.in_state("merged")
    r = w.run()
    assert "phase: merged" in r.out and r.rc == 3 and "CONFIRM: tag" in r.out, r.text
    runs = [c for c in w.gh.calls if c[:2] == ["run", "list"] and "--workflow" in c]
    assert runs and w.merge_sha in runs[0] and "e2e-upgrade.yml" in runs[0]
    assert w.check_cmd("gate")[-1][-1] == w.merge_sha
    assert w.check_cmd("rows") == [] and w.created == [] and w.merges == []
    assert "v5.5.0" not in w.origin_tags()


def test_a_tag_without_a_github_release_continues_by_creating_the_release(w):  # AC-129.17
    w.in_state("tagged")
    w.guard_seq = [[run_entry(200, branch="v5.5.0")]]
    r = w.run()
    assert "phase: tagged" in r.out and "tag v5.5.0: on " + w.merge_sha[:7] in r.out
    assert r.rc == 0 and "RELEASED: v5.5.0" in r.out, r.text
    assert [c[:3] for c in w.gh.calls if c[:2] == ["release", "create"]] == [["release", "create", "v5.5.0"]]
    assert w.origin_tags()["v5.5.0"] == w.merge_sha


def test_a_tag_and_a_release_continue_with_the_release_guard(w):  # AC-129.17
    w.in_state("released")
    w.guard_seq = [[run_entry(200, "in_progress", None, "v5.5.0")]]
    w.views["200"] = [{"status": "in_progress"}, {"status": "completed", "conclusion": "success"}]
    r = w.run()
    assert "phase: guarding" in r.out and f"GitHub release v5.5.0: https://github.com/{SLUG}/releases/tag/v5.5.0" in r.out
    assert r.rc == 0 and "RELEASED: v5.5.0" in r.out, r.text
    assert w.gh.writes() == [] and w.merges == []


# ---------------- AC-129.18 ----------------

@pytest.mark.parametrize("phase", ["branch", "pr-open", "merged"])
def test_a_version_naming_another_release_than_the_one_in_flight_is_refused(w, phase):  # AC-129.18
    w.in_state(phase)
    before = w.snapshot()
    r = w.run("--version", "5.6.0")
    assert r.rc == 1 and f"release 5.5.0 is in flight ({phase}): finish it first" in r.err
    no_writes(w, before)


def test_the_same_version_as_the_release_in_flight_is_accepted(w):  # AC-129.18
    w.in_state("pr-open")
    r = w.run("--dry-run", "--version", "5.5.0")
    assert r.rc == 0 and "phase: pr-open" in r.out


def chk_(name, bucket, run=42):
    from platrelease_world import chk
    return chk(name, bucket, run)
