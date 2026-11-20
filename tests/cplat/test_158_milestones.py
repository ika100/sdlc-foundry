"""Spec 158 acceptance tests: the milestone comments of `milestones.py` (AC-158.1 to AC-158.3, AC-158.6, AC-158.7).

Seams: `milestones.gh(args, *, cwd, timeout)` and `milestones.clock()` are replaced by `support_158.FakeGh`; the entry points are
`spec_written`, `spec_approved`, `pr_merged` and `post` of design.md. Assertions read the parsed comment (its lines), never one
serialized string."""
import pytest

from support_158 import (FakeGh, SID, SLUG, SPEC_AT_BRANCH, SPEC_AT_MAIN, SPEC_PR, STORY, install, lines_of, make_spec, marker, pr_body)


@pytest.fixture()
def gh(monkeypatch):
    fake = FakeGh()
    fake.issue(42)
    return fake


def test_the_new_module_has_the_documented_interface(gh, monkeypatch):  # AC-158.6
    m = install(monkeypatch, gh)
    assert (m.ISSUE_LIMIT_S, m.STEP_LIMIT_S) == (20.0, 120.0)
    assert m.SKIP_LABELS == {"auto-filed", "notify", "retro"}


# ---------------- AC-158.1: spec written ----------------

def test_a_written_spec_is_announced_on_its_tracked_issue_ac_158_1(tmp_path, gh, monkeypatch):  # AC-158.1
    m = install(monkeypatch, gh)
    sp = make_spec(tmp_path, questions="- Which mail provider?\n- ~~Rate limit?~~ 10/min\n- Per user or global?")
    out = m.spec_written(tmp_path, sp, f"feature/{SID}", SPEC_PR)
    [body] = gh.posts(42)
    rows = lines_of(body)
    assert rows[0].startswith("Spec 007 for this issue is written:")
    assert f"[{SID}]({SPEC_AT_BRANCH})" in rows[0] and SPEC_PR in rows[0]
    assert f"Planned solution: {STORY} It has 2 acceptance criteria." in rows
    at = rows.index("Open questions you can answer here:")
    assert rows[at + 1:at + 3] == ["- Which mail provider?", "- Per user or global?"]
    assert out == ["issue #42: spec-written comment posted"]


def test_a_second_story_is_never_quoted_and_a_long_story_is_cut_to_400_ac_158_1(tmp_path, gh, monkeypatch):  # AC-158.1
    m = install(monkeypatch, gh)
    sp = make_spec(tmp_path, story="As someone watching prices, I want " + "an email " * 80 + "so that I am told.")
    m.spec_written(tmp_path, sp, f"feature/{SID}", SPEC_PR)
    [line] = [r for r in lines_of(gh.posts(42)[0]) if r.startswith("Planned solution: ")]
    story = line[len("Planned solution: "):].removesuffix(" It has 2 acceptance criteria.")
    assert len(story) <= 400 and story.endswith("…") and story.startswith("As someone")
    assert "second story" not in gh.posts(42)[0]


def test_at_most_five_open_questions_then_a_count_ac_158_1(tmp_path, gh, monkeypatch):  # AC-158.1
    m = install(monkeypatch, gh)
    sp = make_spec(tmp_path, questions="\n".join(f"- Question {i}?" for i in range(1, 8)))
    m.spec_written(tmp_path, sp, f"feature/{SID}", SPEC_PR)
    rows = lines_of(gh.posts(42)[0])
    at = rows.index("Open questions you can answer here:")
    assert rows[at + 1:at + 7] == [*(f"- Question {i}?" for i in range(1, 6)), "- … and 2 more"]


def test_without_open_questions_the_comment_says_so_ac_158_1(tmp_path, gh, monkeypatch):  # AC-158.1
    m = install(monkeypatch, gh)
    m.spec_written(tmp_path, make_spec(tmp_path, questions="None."), f"feature/{SID}", SPEC_PR)
    rows = lines_of(gh.posts(42)[0])
    assert "No open questions." in rows and "Open questions you can answer here:" not in rows


# ---------------- AC-158.2: spec approved ----------------

def test_an_approved_spec_is_announced_with_the_next_step_ac_158_2(tmp_path, gh, monkeypatch):  # AC-158.2
    m = install(monkeypatch, gh)
    gh.default = "trunk"
    out = m.spec_approved(tmp_path, make_spec(tmp_path, status="approved"))
    [body] = gh.posts(42)
    rows = lines_of(body)
    assert rows[0].startswith("Spec 007 approved on 2026-10-02:")
    assert f"[{SID}]({SPEC_AT_MAIN.replace('/blob/main/', '/blob/trunk/')})" in rows[0]
    assert f"Planned solution: {STORY} It has 2 acceptance criteria." in rows
    assert "Next: the build; you will hear here when its PR merges." in rows
    assert out == ["issue #42: spec-approved comment posted"]


def test_a_spec_without_tracked_issues_gets_no_call_ac_158_2(tmp_path, gh, monkeypatch):  # AC-158.2
    m = install(monkeypatch, gh)
    assert m.spec_approved(tmp_path, make_spec(tmp_path, status="approved", tracks="[]")) == []
    assert not gh.posts()


# ---------------- AC-158.3: PR merged ----------------

def test_a_merged_pr_tells_its_closing_issues_what_changed_ac_158_3(gh, monkeypatch, tmp_path):  # AC-158.3
    m = install(monkeypatch, gh)
    gh.issue(7, state="closed")           # GitHub has already closed it: it still hears
    url = gh.pr(5, body=pr_body([42, 7], changed="Alerts are emailed", why="Traders missed moves"))
    out = m.pr_merged(tmp_path, url)
    for n in (42, 7):
        rows = lines_of(gh.posts(n)[0])
        assert rows[0] == f"Merged: {url}"
        assert "- **Changed:** Alerts are emailed" in rows and "- **Why:** Traders missed moves" in rows
        assert "Ships with the next release; you will hear here when it does." in rows
        assert rows[-1] == marker("pr-merged", "5")
    assert out == ["issue #7: pr-merged comment posted", "issue #42: pr-merged comment posted"]


def test_a_pr_without_a_summary_block_gives_its_title_and_not_recorded_ac_158_3(gh, monkeypatch, tmp_path):  # AC-158.3
    m = install(monkeypatch, gh)
    gh.pr(5, body="Closes #42\n", title="Add the alert mail")
    m.pr_merged(tmp_path, "5")
    rows = lines_of(gh.posts(42)[0])
    assert "- **Changed:** Add the alert mail" in rows and "- **Why:** not recorded" in rows


@pytest.mark.parametrize("keyword", ["Closes", "closes", "Fixed", "fixes:", "Resolves"])
def test_every_closing_keyword_counts_ac_158_3(gh, monkeypatch, tmp_path, keyword):  # AC-158.3
    m = install(monkeypatch, gh)
    gh.pr(5, body=f"{keyword} #42\n")
    m.pr_merged(tmp_path, "5")
    assert len(gh.posts(42)) == 1


def test_a_pr_without_a_closing_reference_comments_nowhere_ac_158_3(gh, monkeypatch, tmp_path):  # AC-158.3
    m = install(monkeypatch, gh)
    gh.pr(5, body="Part of #42, see also acme/other#7\n")
    assert m.pr_merged(tmp_path, "5") == [] and not gh.posts()


# ---------------- AC-158.6: marker, dedup, who gets nothing ----------------

def test_every_milestone_comment_ends_with_its_marker_ac_158_6(tmp_path, gh, monkeypatch):  # AC-158.6
    m = install(monkeypatch, gh)
    m.spec_written(tmp_path, make_spec(tmp_path), f"feature/{SID}", SPEC_PR)
    m.spec_approved(tmp_path, make_spec(tmp_path, status="approved"))
    gh.pr(9, body="Closes #42\n")
    m.pr_merged(tmp_path, "9")
    keys = [lines_of(b)[-1] for b in gh.posts(42)]
    assert keys == [marker("spec-written", SID), marker("spec-approved", SID), marker("pr-merged", "9")]


def test_a_comment_with_the_marker_is_not_posted_again_ac_158_6(tmp_path, gh, monkeypatch):  # AC-158.6
    m = install(monkeypatch, gh)
    gh.issue(42, comments=["thanks!", f"Merged\n\n{marker('pr-merged', '9')}"])
    gh.pr(9, body="Closes #42\n")
    assert m.pr_merged(tmp_path, "9") == [] and not gh.posts()


def test_the_same_milestone_twice_posts_once_ac_158_6(tmp_path, gh, monkeypatch):  # AC-158.6
    m = install(monkeypatch, gh)
    sp = make_spec(tmp_path)
    m.spec_written(tmp_path, sp, f"feature/{SID}", SPEC_PR)
    assert m.spec_written(tmp_path, sp, f"feature/{SID}", SPEC_PR) == []
    assert len(gh.issues[42]["comments"]) == 1


def test_another_milestone_of_the_same_issue_is_not_a_duplicate_ac_158_6(tmp_path, gh, monkeypatch):  # AC-158.6
    m = install(monkeypatch, gh)
    gh.issue(42, comments=[f"x\n{marker('pr-merged', '8')}"])
    gh.pr(9, body="Closes #42\n")
    m.pr_merged(tmp_path, "9")
    assert len(gh.posts(42)) == 1


@pytest.mark.parametrize("what", [{"labels": ["auto-filed"]}, {"labels": ["notify"]}, {"labels": ["retro"]},
                                  {"pull_request": True}])
def test_platform_issues_and_pull_requests_get_nothing_and_no_note_ac_158_6(tmp_path, gh, monkeypatch, what):  # AC-158.6
    m = install(monkeypatch, gh)
    gh.issue(42, **what)
    gh.pr(9, body="Closes #42\n")
    assert m.pr_merged(tmp_path, "9") == [] and not gh.posts()


def test_tracked_issues_of_another_repository_are_dropped_ac_158_6(tmp_path, gh, monkeypatch):  # AC-158.6
    m = install(monkeypatch, gh)
    gh.issue(43)
    m.spec_approved(tmp_path, make_spec(tmp_path, status="approved", tracks='[42, "#43", "other/repo#5", "acme/other#6"]'))
    assert sorted(n for n, _ in gh.posted) == [42, 43]
    assert all("other" not in " ".join(a) for a, _ in gh.calls if a[0] == "api")


def test_post_reports_what_it_did_per_issue_ac_158_6(tmp_path, gh, monkeypatch):  # AC-158.6
    m = install(monkeypatch, gh)
    gh.issue(1, comments=[marker("pr-merged", "9")]).issue(2, labels=["retro"]).issue(3, pull_request=True)
    lines, how = m.post(tmp_path, SLUG, [1, 2, 3, 42], "pr-merged", "9", f"Merged\n\n{marker('pr-merged', '9')}")
    assert how == {1: "present", 2: "ignored", 3: "ignored", 42: "posted"}
    assert lines == ["issue #42: pr-merged comment posted"]


def test_post_with_close_closes_an_open_issue_even_when_its_comment_was_present_ac_158_4(tmp_path, gh, monkeypatch):  # AC-158.4
    m = install(monkeypatch, gh)
    gh.issue(1, comments=[marker("released", "v1.1.0")]).issue(2, state="closed")
    m.post(tmp_path, SLUG, [1, 2, 42], "released", "v1.1.0", f"Fixed in v1.1.0.\n\n{marker('released', 'v1.1.0')}", close=True)
    assert sorted(gh.closes()) == [1, 42]
    assert gh.close_reasons() == ["completed"] * 2


# ---------------- AC-158.7: failing, slow, refused ----------------

def test_a_gh_that_fails_costs_one_note_per_issue_and_never_raises_ac_158_7(tmp_path, gh, monkeypatch):  # AC-158.7
    m = install(monkeypatch, gh)
    gh.issue(7)
    gh.offline = True
    lines, how = m.post(tmp_path, SLUG, [7, 42], "pr-merged", "9", "body")
    assert how == {7: "skipped", 42: "skipped"}
    assert lines == ["note: issue comment skipped: #7 pr-merged: error connecting to api.github.com",
                     "note: issue comment skipped: #42 pr-merged: error connecting to api.github.com"]


def test_an_entry_point_with_a_dead_gh_returns_lines_and_never_raises_ac_158_7(tmp_path, gh, monkeypatch):  # AC-158.7
    m = install(monkeypatch, gh)
    gh.pr(9, body="Closes #7\n")
    gh.offline = True
    out = m.pr_merged(tmp_path, "9")
    assert isinstance(out, list) and out and all(ln.startswith("note: issue comment skipped: #") for ln in out)
    [line] = m.spec_approved(tmp_path, make_spec(tmp_path, status="approved"))
    assert line.startswith("note: issue comment skipped: #42 spec-approved: ")


def test_a_gh_that_raises_is_caught_ac_158_7(tmp_path, gh, monkeypatch):  # AC-158.7
    m = install(monkeypatch, gh)
    gh.raises = True
    assert isinstance(m.spec_approved(tmp_path, make_spec(tmp_path, status="approved")), list)
    lines, how = m.post(tmp_path, SLUG, [42], "pr-merged", "9", "x")
    assert how == {42: "skipped"} and lines[0].startswith("note: issue comment skipped: #42 pr-merged: ")


def test_a_locked_issue_gives_the_first_line_of_gh_stderr_ac_158_7(tmp_path, gh, monkeypatch):  # AC-158.7
    m = install(monkeypatch, gh)
    gh.issue(42, locked=True, post_error="HTTP 403: Unable to create comment because issue is locked.\nsecond line")
    gh.issue(43)
    lines, how = m.post(tmp_path, SLUG, [42, 43], "pr-merged", "9", f"Merged\n\n{marker('pr-merged', '9')}")
    assert lines == ["note: issue comment skipped: #42 pr-merged: HTTP 403: Unable to create comment because issue is locked.",
                     "issue #43: pr-merged comment posted"]
    assert how == {42: "skipped", 43: "posted"}


def test_a_deleted_issue_is_a_note_not_an_error_ac_158_7(tmp_path, gh, monkeypatch):  # AC-158.7
    m = install(monkeypatch, gh)
    lines, how = m.post(tmp_path, SLUG, [404, 42], "pr-merged", "9", "body")
    assert lines[0].startswith("note: issue comment skipped: #404 pr-merged: ") and how == {404: "skipped", 42: "posted"}


def test_one_issue_takes_at_most_20_seconds_and_the_next_still_gets_its_comment_ac_158_7(tmp_path, gh, monkeypatch):  # AC-158.7
    m = install(monkeypatch, gh)
    gh.issue(1).hang = {1}
    lines, how = m.post(tmp_path, SLUG, [1, 42], "pr-merged", "9", "body")
    assert lines[0] == "note: issue comment skipped: #1 pr-merged: timed out after 20s"
    assert lines[1] == "issue #42: pr-merged comment posted" and how == {1: "skipped", 42: "posted"}
    assert gh.clock.now - 1000.0 <= 20.0
    assert all(0 < t <= 20.0 for _, t in gh.calls)


def test_a_slow_issue_leaves_the_rest_of_its_20_seconds_to_the_next_call_ac_158_7(tmp_path, gh, monkeypatch):  # AC-158.7
    m = install(monkeypatch, gh)
    seen = []

    def slow(args, *, cwd=None, timeout=20.0):
        seen.append(timeout)
        gh.clock.now += 8.0
        return gh(args, cwd=cwd, timeout=timeout)
    monkeypatch.setattr(m, "gh", slow)
    m.post(tmp_path, SLUG, [42], "pr-merged", "9", "body")
    assert seen[0] <= 20.0 and seen[1] <= 12.0 + 1e-6 and all(t > 0 for t in seen)


def test_the_whole_step_takes_at_most_120_seconds_and_the_rest_is_skipped_ac_158_7(tmp_path, gh, monkeypatch):  # AC-158.7
    m = install(monkeypatch, gh)
    issues = list(range(100, 110))
    for n in issues:
        gh.issue(n)
    gh.hang = set(issues)
    lines, how = m.post(tmp_path, SLUG, issues, "pr-merged", "9", "body")
    assert gh.clock.now - 1000.0 <= 120.0 and all(0 < t <= 20.0 for _, t in gh.calls)
    assert set(how.values()) == {"skipped"} and len(lines) == 10
    assert all(f"#{n} pr-merged:" in ln for n, ln in zip(issues, lines))
    assert lines[-1].endswith("comment step time limit (120s) reached")
    assert not gh.issue_calls(109)       # a call with no time left is not started


def test_the_step_budget_is_shared_by_every_entry_point_of_the_process_ac_158_7(tmp_path, gh, monkeypatch):  # AC-158.7
    m = install(monkeypatch, gh)
    for n in range(100, 106):
        gh.issue(n)
    gh.hang = set(range(100, 106))
    m.post(tmp_path, SLUG, list(range(100, 106)), "pr-merged", "9", "body")      # six issues use the 120 seconds
    lines, how = m.post(tmp_path, SLUG, [42], "pr-merged", "5", "body")
    assert not gh.posts(42) and how == {42: "skipped"}
    assert lines == ["note: issue comment skipped: #42 pr-merged: comment step time limit (120s) reached"]


def test_running_again_posts_the_missing_comments_and_no_duplicates_ac_158_7(tmp_path, gh, monkeypatch):  # AC-158.7
    m = install(monkeypatch, gh)
    gh.issue(7, post_error="HTTP 403: locked")
    gh.pr(9, body="Closes #7\nCloses #42\n")
    first = m.pr_merged(tmp_path, "9")
    assert any(ln.startswith("note: issue comment skipped: #7 ") for ln in first) and len(gh.posts(42)) == 1
    gh.issues[7]["post_error"] = None
    m.reset()
    second = m.pr_merged(tmp_path, "9")
    assert second == ["issue #7: pr-merged comment posted"]
    assert len(gh.posts(42)) == 1 and len(gh.issues[7]["comments"]) == 1
