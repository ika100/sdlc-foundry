"""Spec 129 acceptance tests: preparing the release, the checks, the commit and PR, the CI wait and the merge stop
(AC-129.6 to AC-129.11). Contract: design.md, section Contract. Offline: see platrelease_world."""
import pytest

from platrelease_world import E2E, NOTES, USER, EMAIL, chk, moved_changelog, w  # noqa: F401  (w is a fixture)

BRANCH = "release/5.5.0"


@pytest.fixture()
def stopped(w):
    """A full run from `idle` to the merge stop."""
    r = w.run()
    assert r.rc == 3 and "CONFIRM: merge" in r.out, r.text
    return r


# ---------------- AC-129.6 ----------------

def test_the_changelog_moves_under_the_new_heading_on_a_release_branch(w, stopped):  # AC-129.6
    assert w.git("rev-parse", "--verify", f"refs/heads/{BRANCH}").strip()
    assert w.git("show", f"{BRANCH}:docs/CHANGELOG.md") == moved_changelog("5.5.0")
    text = w.git("show", f"{BRANCH}:docs/CHANGELOG.md")
    assert text.index("## [Unreleased]") < text.index("## [5.5.0] - 2026-06-15") < text.index("## [5.4.0]")
    assert text.split("## [Unreleased]")[1].split("## [5.5.0]")[0].strip() == ""     # the heading stays, empty


def test_no_other_file_changes_in_the_release(w, stopped):  # AC-129.6
    changed = w.git("diff", "--name-only", f"origin/main...origin/{BRANCH}").split()
    assert changed == ["docs/CHANGELOG.md"]


def test_the_date_is_the_date_of_the_run(w, monkeypatch):  # AC-129.6
    import datetime
    import platrelease_state
    monkeypatch.setattr(platrelease_state, "today", lambda: datetime.date(2031, 1, 2))
    w.run()
    assert "## [5.5.0] - 2031-01-02" in w.git("show", f"{BRANCH}:docs/CHANGELOG.md")


# ---------------- AC-129.7 ----------------

@pytest.mark.parametrize("key, name, output", [
    ("rows", "release-check rows", "ERROR: docs/CHANGELOG.md: [5.5.0] does not list - operator x 1 → 2\nFAILED: 1 problem(s)"),
    ("validate", "devbox run validate", "ERROR: marketplace.json is not valid JSON"),
])
def test_a_failing_check_prints_its_output_and_commits_and_pushes_nothing(w, key, name, output):  # AC-129.7
    w.results[key] = (1, output)
    r = w.run()
    assert r.rc == 1
    assert output in r.text and f"{name} failed" in r.err
    cwd, cmd = w.check_calls[-1]
    assert cwd == w.repo and key in cmd
    if key == "validate":
        assert cmd == ["devbox", "run", "validate"]
        assert w.check_cmd("rows")[0][2:] == ["rows", "--base", "v5.4.0"]
    if w.git("rev-parse", "--verify", "-q", f"refs/heads/{BRANCH}", check=False).strip():
        assert w.git("rev-list", "--count", f"main..{BRANCH}").strip() == "0"
    assert BRANCH not in w.git("ls-remote", "--heads", "origin")
    assert w.created == [] and w.merges == []


# ---------------- AC-129.8 ----------------

def test_one_signed_commit_is_pushed_and_the_pr_is_opened(w, stopped):  # AC-129.8
    assert w.ahead(f"origin/{BRANCH}") == 1
    body = w.git("log", "-1", "--format=%B", f"origin/{BRANCH}")
    assert body.splitlines()[0] == "chore: release 5.5.0"
    assert f"Signed-off-by: {USER} <{EMAIL}>" in body
    assert len(w.created) == 1
    a = w.created[0]
    assert a[:2] == ["pr", "create"]
    assert a[a.index("--base") + 1] == "main" and a[a.index("--head") + 1] == BRANCH
    assert a[a.index("--title") + 1] == "chore: release 5.5.0"
    assert f"PR: {w.pr_url}" in stopped.out


def test_the_pr_body_carries_no_changelog_text(w, stopped):  # AC-129.8
    a = w.created[0]
    body = a[a.index("--body") + 1]
    assert body == ("Release 5.5.0: [Unreleased] of docs/CHANGELOG.md moved under ## [5.5.0].\n"
                    "Opened by cplat platform release.")
    assert "Users notice it" not in body


# ---------------- AC-129.9 ----------------

def test_the_wait_covers_every_check_including_the_upgrade_e2e(w):  # AC-129.9
    w.in_state("pr-open")
    w.check_seq = [[chk("quality", "pass"), chk(E2E, "pending", 43)], [chk("quality", "pass"), chk(E2E, "pending", 43)],
                   [chk("quality", "pass"), chk(E2E, "pass", 43)]]
    r = w.run()
    assert r.rc == 3 and "CONFIRM: merge" in r.out, r.text
    assert len([c for c in w.gh.calls if c[:2] == ["pr", "checks"]]) >= 3
    assert w.merges == [] and w.clock["t"] >= 40                  # it slept on the interval while the e2e ran


def test_a_cancelled_older_run_of_a_workflow_does_not_count_as_red(w):  # AC-129.9
    w.in_state("pr-open")
    w.workflow.update({"41": "500", "42": "500"})
    w.check_seq = [[chk("test", "cancel", 41), chk("test", "pass", 42), chk(E2E, "pass", 43)]]
    r = w.run()
    assert r.rc == 3 and "CONFIRM: merge" in r.out, r.text


def test_a_green_pr_without_the_upgrade_e2e_is_not_mergeable(w):  # AC-129.9
    w.in_state("pr-open")
    w.check_seq = [[chk("quality", "pass")]]
    r = w.run("--confirm", "merge")
    assert r.rc == 1 and f"the upgrade e2e did not run on {w.pr_url}" in r.err
    assert w.merges == []


# ---------------- AC-129.10 ----------------

@pytest.mark.parametrize("argv", [(), ("--confirm", "merge")])
def test_a_red_check_names_the_check_and_its_link_and_does_not_merge(w, argv):  # AC-129.10
    w.in_state("pr-open")
    w.check_seq = [[chk("quality", "fail", 42), chk(E2E, "pending", 43)]]
    r = w.run(*argv)
    assert r.rc == 1
    assert "quality" in r.text and "https://github.com/acme/shop/actions/runs/42" in r.text
    assert f"CI is red on {w.pr_url}: not merged" in r.err
    assert w.merges == []


# ---------------- AC-129.11 ----------------

def test_a_green_pr_stops_before_the_merge_with_the_continue_command(w):  # AC-129.11
    w.in_state("pr-open")
    r = w.run()
    assert r.rc == 3 and w.merges == []
    for line in ("CONFIRM: merge", "  version: 5.5.0", f"  PR: {w.pr_url}", "  checks: 2 passed (newest run of each workflow)",
                 "e2e upgrade (previous release → candidate): pass", "  continue: cplat platform release --confirm merge"):
        assert line in r.out, (line, r.out)
    assert w.git("log", "-1", "--format=%s", "origin/main").strip() == "chore: init"


def test_only_the_confirmation_squash_merges_the_pr(w):  # AC-129.11
    w.in_state("pr-open")
    r = w.run("--confirm", "merge")
    assert len(w.merges) == 1
    m = w.merges[0]
    assert m[:3] == ["gh", "pr", "merge"] and m[3] == w.pr_url and "--squash" in m
    assert "--match-head-commit" in m and m[m.index("--match-head-commit") + 1] == w.head
    assert w.git("log", "-1", "--format=%s", "origin/main").strip() == "chore: release 5.5.0 (#7)"
    assert r.rc == 3 and "CONFIRM: tag" in r.out, r.text                    # it goes on to the next stop, not past it
    assert "v5.5.0" not in w.origin_tags() and w.git("branch", "--show-current").strip() == "main"


@pytest.mark.parametrize("state, flag", [("idle", "merge"), ("branch", "merge"), ("pr-open", "tag"), ("merged", "merge")])
def test_a_confirmation_is_refused_where_its_step_is_not_next(w, state, flag):  # AC-129.11
    w.in_state(state)
    before = w.snapshot()
    r = w.run("--confirm", flag)
    assert r.rc == 1 and "ERROR:" in r.err
    assert w.snapshot() == before and w.created == [] and w.merges == []
