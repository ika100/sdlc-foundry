"""Spec 158 acceptance tests: the issues a release fixes (AC-158.4, AC-158.5, AC-158.7).

World: `support_158.ReleaseRepo`, a real git clone with a bare origin (tags v1.0.0 and v1.1.0, changelog and fragments) and the
fake `milestones.gh` that answers `gh pr list` with the merged PRs. `cplat component release issues` is driven through
`cplat.main`; `cplat platform release` through `platrelease_publish.continue_from` with its release and guard steps faked."""
import json
from types import SimpleNamespace

import pytest

import cplat
import platrelease_publish as pub
import platrelease_state as st
from support_158 import FakeGh, ReleaseRepo, SLUG, install, marker

PLATFORM_HOW = "run `/plugin marketplace update`, then `/platform:update`."


@pytest.fixture()
def world(tmp_path, monkeypatch):
    gh = FakeGh()
    repo = ReleaseRepo(tmp_path, gh)
    install(monkeypatch, gh)
    return gh, repo


def issues_cmd(repo, capsys, *extra, version="v1.1.0"):
    capsys.readouterr()
    rc = cplat.main(["component", "release", "issues", "--version", version, "--repo", str(repo.dir), *extra])
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def body_rows(gh, n):
    [body] = gh.posts(n)
    return body.rstrip("\n").splitlines()


# ---------------- AC-158.4 / AC-158.5: the subcommand ----------------

def test_the_release_comments_and_closes_the_linked_issues_ac_158_4(world, capsys):  # AC-158.4
    gh, repo = world
    rc, out, _ = issues_cmd(repo, capsys, "--json")
    doc = json.loads(out)
    assert rc == 0 and doc["version"] == "v1.1.0"
    assert {i["number"]: (i["comment"], i["closed"]) for i in doc["issues"]} == {
        5: ("posted", "now"), 6: ("posted", "before"), 7: ("posted", "now"), 77: ("posted", "now")}
    assert [i["number"] for i in doc["issues"]] == [5, 6, 7, 77]
    assert doc["notes"] == []
    assert sorted(gh.closes()) == [5, 7, 77]                # the closed #6 stays closed, and is not reopened
    assert gh.close_reasons() == ["completed"] * 3          # closed as completed
    for n in (5, 6, 7, 77):
        assert gh.posts(n)[0].startswith("Fixed in v1.1.0")
        assert body_rows(gh, n)[-1] == marker("released", "v1.1.0")


def test_only_closing_references_and_named_fragments_link_ac_158_4(world, capsys):  # AC-158.4
    gh, repo = world
    issues_cmd(repo, capsys)
    for n in (3, 9, 88, 8):      # 3: merged before the previous tag; 9: only mentioned; 88: a spec number; 8: another repository
        assert not gh.issue_calls(n) and n not in gh.closes()


def test_what_shipped_comes_from_changelog_then_changed_then_title_ac_158_4(world, capsys):  # AC-158.4
    gh, repo = world
    issues_cmd(repo, capsys)
    shipped = {n: next(r for r in body_rows(gh, n) if r.startswith("Shipped: ")) for n in (5, 6, 7, 77)}
    assert shipped[5] == "Shipped: Fixed the widget."                       # the changelog entry naming #5, not the PR's Changed
    assert shipped[6] == "Shipped: Six is fixed"                            # no entry: the Changed line of PR 11
    assert shipped[7] == "Shipped: Title of the PR without a summary block"  # no block: the PR's title
    assert shipped[77].startswith("Shipped: A widget for everyone")         # a fragment named by an issue number


def test_the_platform_gets_the_update_commands_ac_158_4(world, capsys):  # AC-158.4
    gh, repo = world
    issues_cmd(repo, capsys)
    assert f"Get it: {PLATFORM_HOW}" in body_rows(gh, 5)


def test_a_component_gets_the_release_page_ac_158_4(tmp_path, monkeypatch, capsys):  # AC-158.4
    gh = FakeGh()
    repo = ReleaseRepo(tmp_path, gh, shape="service-python")
    install(monkeypatch, gh)
    issues_cmd(repo, capsys)
    assert f"Get it: https://github.com/{SLUG}/releases/tag/v1.1.0" in body_rows(gh, 5)


def test_the_summary_line_is_the_phase_7_line_ac_158_5(world, capsys):  # AC-158.5
    gh, repo = world
    rc, out, _ = issues_cmd(repo, capsys)
    rows = out.splitlines()
    assert rc == 0 and rows[0] == "issue #5: released comment posted"
    assert rows[-1] == "## Phase 7 complete — issues closed: #5, #6, #7, #77 (3 closed, 1 already closed)"
    assert "summary" in json.loads(issues_cmd(repo, capsys, "--json")[1])


def test_no_linked_issues_is_said_so_ac_158_5(world, capsys):  # AC-158.5
    gh, repo = world
    gh.pr_list = []
    rc, out, _ = issues_cmd(repo, capsys, version="v1.0.0")
    assert rc == 0 and out.splitlines()[-1] == "## Phase 7 complete — no linked issues found"
    assert not gh.posts() and not gh.closes()


def test_the_first_release_links_what_its_history_merged_ac_158_4(world, capsys):  # AC-158.4
    gh, repo = world
    rc, out, _ = issues_cmd(repo, capsys, "--json", version="v1.0.0")
    assert [i["number"] for i in json.loads(out)["issues"]] == [3]


def test_an_explicit_previous_tag_bounds_the_range_ac_158_4(world, capsys):  # AC-158.4
    gh, repo = world
    rc, out, _ = issues_cmd(repo, capsys, "--json", "--previous", "v1.0.0")
    assert [i["number"] for i in json.loads(out)["issues"]] == [5, 6, 7, 77]


def test_an_unknown_tag_is_a_usage_error_ac_158_5(world, capsys):  # AC-158.5
    gh, repo = world
    rc, out, err = issues_cmd(repo, capsys, version="v9.9.9")
    assert rc == 2 and "tag v9.9.9 not found" in out + err and not gh.posts()


def test_running_the_release_step_again_posts_nothing_twice_ac_158_7(world, capsys):  # AC-158.7
    gh, repo = world
    issues_cmd(repo, capsys)
    rc, out, _ = issues_cmd(repo, capsys, "--json")
    doc = json.loads(out)
    assert rc == 0 and {i["comment"] for i in doc["issues"]} == {"present"} and {i["closed"] for i in doc["issues"]} == {"before"}
    assert all(len(gh.posts(n)) == 1 for n in (5, 6, 7, 77)) and len(gh.closes()) == 3


def test_a_refused_comment_is_a_note_and_the_exit_code_stays_0_ac_158_7(world, capsys):  # AC-158.7
    gh, repo = world
    gh.issue(5, post_error="HTTP 403: Unable to create comment because issue is locked.")
    rc, out, _ = issues_cmd(repo, capsys, "--json")
    doc = json.loads(out)
    assert rc == 0
    assert doc["notes"] == ["note: issue comment skipped: #5 released: HTTP 403: Unable to create comment because issue is locked."]
    assert {i["number"]: i["comment"] for i in doc["issues"]}[5] == "skipped"
    assert doc["summary"].startswith("## Phase 7 complete — issues closed: #5, #6, #7, #77 (") and doc["summary"].endswith(", 1 skipped)")
    gh.issues[5]["post_error"] = None
    rc, out, _ = issues_cmd(repo, capsys, "--json")
    assert rc == 0 and len(gh.issues[5]["comments"]) == 1 and len(gh.posts(7)) == 1


def test_a_hanging_issue_is_cut_at_20_seconds_and_the_others_still_hear_ac_158_7(world, capsys):  # AC-158.7
    gh, repo = world
    gh.hang = {5}
    rc, out, _ = issues_cmd(repo, capsys, "--json")
    doc = json.loads(out)
    assert rc == 0 and doc["notes"] == ["note: issue comment skipped: #5 released: timed out after 20s"]
    assert len(gh.posts(6)) == len(gh.posts(7)) == len(gh.posts(77)) == 1
    assert gh.clock.now - 1000.0 <= 20.0


# ---------------- cplat platform release ----------------

class Events:
    def __init__(self, gh):
        self.log = []
        self.gh = gh

    def __call__(self, args, *, cwd=None, timeout=20.0):
        out = self.gh(args, cwd=cwd, timeout=timeout)
        if args[:3] == ["api", "-X", "POST"] or args[:2] == ["issue", "close"]:
            self.log.append("issue-write")
        return out


@pytest.fixture()
def publish(world, monkeypatch):
    gh, repo = world
    ev = Events(gh)
    import milestones
    monkeypatch.setattr(milestones, "gh", ev)
    monkeypatch.setattr(pub, "_release", lambda *a, **k: "https://github.com/acme/shop/releases/tag/v1.1.0")
    monkeypatch.setattr(pub, "_guard", lambda *a, **k: ev.log.append("guard"))
    state = st.State(phase=st.TAGGED, version="1.1.0", tag="v1.1.0")
    return gh, repo, ev, state


def go(repo, state):
    return pub.continue_from(repo.dir, state, "1.1.0", repo.sha[13], SimpleNamespace(confirm="tag", timeout=5, interval=1))


def test_cplat_platform_release_posts_and_closes_before_the_guard_ac_158_4(publish, capsys):  # AC-158.4
    gh, repo, ev, state = publish
    assert go(repo, state) == 0
    rows = capsys.readouterr().out.splitlines()
    assert sorted(gh.closes()) == [5, 7, 77] and all(len(gh.posts(n)) == 1 for n in (5, 6, 7, 77))
    assert ev.log.index("guard") > max(i for i, e in enumerate(ev.log) if e == "issue-write")
    at = rows.index("release: https://github.com/acme/shop/releases/tag/v1.1.0")
    assert "issue #5: released comment posted" in rows[at:]
    assert "release issues — issues closed: #5, #6, #7, #77 (3 closed, 1 already closed)" in rows[at:]


def test_cplat_platform_release_keeps_its_result_when_a_comment_fails_ac_158_7(publish, capsys):  # AC-158.7
    gh, repo, ev, state = publish
    gh.issue(5, post_error="HTTP 403: locked")
    assert go(repo, state) == 0 and "guard" in ev.log
    rows = capsys.readouterr().out.splitlines()
    assert "note: issue comment skipped: #5 released: HTTP 403: locked" in rows
    assert "  post the missing ones: cplat component release issues --version v1.1.0" in rows
    assert any(r.startswith("RELEASED: v1.1.0") for r in rows)


def test_cplat_platform_release_with_gh_down_still_releases_ac_158_7(publish, capsys):  # AC-158.7
    gh, repo, ev, state = publish
    gh.offline = True
    assert go(repo, state) == 0 and "guard" in ev.log
    assert any(r.startswith("RELEASED: v1.1.0") for r in capsys.readouterr().out.splitlines())
