"""Spec 096: the pure parts of `fleet_pr` (PR body, comment, the routine check, follow-up filter)."""
import core

LOST = [{"kind": "recipe", "file": "devbox.json", "entry": "test", "was": "go test ./... -v", "where": "re-add it under a new name"},
        {"kind": "file", "file": ".golangci.yml", "entry": None, "was": None, "where": "copy it back from git history"}]
DATA = {"changed": [".platform-version", "devbox.json"], "modified": [], "new_answers": [], "changelog": "## [4.4.0]\n- a change",
        "baseline": "4.3.0", "devbox": {"kept": ["recipe lint"], "replaced": [{"entry": "test", "was": "go test ./... -v"}],
                                         "moved_to_ci_extra": [], "dropped_gates": []}, "settings": {}, "lost": LOST}


def test_routine_means_no_lost_entries_and_the_same_major():  # AC-096.15
    import fleet_pr
    assert fleet_pr.pre_wait_reasons("4.3.0", "4.4.0", {**DATA, "lost": []}) == []
    assert fleet_pr.pre_wait_reasons("4.3.0", "4.4.0", {"lost": []}) == []


def test_lost_entries_and_major_changes_are_reasons_before_any_wait():  # AC-096.16
    import fleet_pr
    assert fleet_pr.pre_wait_reasons("4.3.0", "4.4.0", DATA) == ["local customisation"]
    assert fleet_pr.pre_wait_reasons("3.9.0", "4.4.0", {"lost": []}) == ["major version 3 → 4"]        # AC-096.7
    assert fleet_pr.pre_wait_reasons("3.9.0", "4.4.0", DATA) == ["local customisation", "major version 3 → 4"]
    assert fleet_pr.pre_wait_reasons(None, "4.4.0", {"lost": []}) == ["major version unknown → 4"]


def test_the_pr_body_follows_the_documented_layout():  # AC-096.3
    import fleet_pr
    body = fleet_pr.pr_body("4.3.0", "4.4.0", DATA, ["set the secret X"])
    assert body.startswith("<!-- cplat-fleet -->\nPlatform update **4.3.0 → 4.4.0** by `cplat fleet update` (spec 096)")
    assert "### Changed files (2)\n- `.platform-version`\n- `devbox.json`" in body
    assert "- kept: recipe lint" in body and "- replaced by the template: `test` (was `go test ./... -v`)" in body
    assert "### Overwritten customisations (spec 086)" in body and "`devbox.json` `test`:" in body and "`.golangci.yml`:" in body
    assert "### Follow-up steps\n- set the secret X" in body
    assert "### Platform changes 4.3.0 → 4.4.0\n## [4.4.0]\n- a change" in body


def test_the_pr_body_says_none_and_flags_a_missing_baseline():  # AC-096.3
    import fleet_pr
    data = {**DATA, "lost": [], "baseline": None, "changelog": "", "devbox": {"kept": [], "replaced": [], "moved_to_ci_extra": [],
                                                                              "dropped_gates": []}}
    body = fleet_pr.pr_body("4.3.0", "4.4.0", data, [])
    assert "No baseline for 4.3.0: every difference counts as overwritten." in body
    assert "none recorded" in body and "### Follow-up steps\n- none" in body
    assert "moved to ci-extra" not in body and "dropped gates" not in body


def test_a_huge_changelog_is_cut_first_to_stay_under_the_limit():  # AC-096.3
    import fleet_pr
    body = fleet_pr.pr_body("4.3.0", "4.4.0", {**DATA, "changelog": "x" * 200000}, [])
    assert len(body) <= 60000 and "… (cut; see docs/CHANGELOG.md of sdlc-foundry)" in body
    assert "### Changed files" in body and "### Follow-up steps" in body


def test_the_comment_names_each_customisation_and_each_major():  # AC-096.16
    import fleet_pr
    text = fleet_pr.comment_body("acme/todo", "3.9.0", "5.1.0", ["local customisation", "major version 3 → 5"], LOST)
    assert text.startswith("<!-- cplat-fleet -->\n**The platform fleet update left this PR open:** local customisation; major version 3")
    assert "This update overwrote what the repo added (spec 086):" in text
    assert "- `devbox.json` `test`: re-add it under a new name" in text and "- `.golangci.yml`: copy it back from git history" in text
    for k in (4, 5):                                                                                        # AC-096.7
        assert f"migration notes for {k}.0.0 in https://github.com/ika100/sdlc-foundry/blob/v5.1.0/docs/CHANGELOG.md" in text
    assert "migration notes for 3.0.0" not in text
    assert text.rstrip().endswith("Review and merge it by hand, or run `cplat fleet update --only acme/todo` again after a fix.")


def test_other_reasons_are_the_reason_line_alone():  # AC-096.6
    import fleet_pr
    text = fleet_pr.comment_body("acme/todo", "4.3.0", "4.4.0", ["red CI: build"], [])
    assert "left this PR open:** red CI: build" in text and "overwrote" not in text and "Major" not in text


def test_follow_ups_drop_the_steps_fleet_does_itself():  # AC-096.14
    import fleet_pr
    r = core.Report(title="t", next_steps=["set the secret X", "platform changes since your version are in docs/CHANGELOG.md",
                                           "new template answers took their defaults: a, b",
                                           "run the repo's checks: devbox run quality && devbox run test-fast, then push the branch"])
    assert fleet_pr.follow_ups(r) == ["set the secret X", "new template answers took their defaults: a, b"]


def test_constants():  # AC-096.6
    import fleet_pr
    assert fleet_pr.LABEL == "platform-update: needs review" and fleet_pr.MARKER == "<!-- cplat-fleet -->"
    assert fleet_pr.BRANCH_PREFIX == "chore/platform-update-" and fleet_pr.UPDATE_SUBJECT == "chore: update skeleton from platform "
