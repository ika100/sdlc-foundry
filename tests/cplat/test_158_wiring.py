"""Spec 158 acceptance tests: the commands post the milestone comments where design.md says (AC-158.1 to AC-158.3, AC-158.7).

Seams: the fake `milestones.gh` of `support_158`; the commands' own seams as their neighbouring tests fake them (`spec_pr.gh/git`
of spec 122's `World`, `ship.gh`, `land_merge.cleanup`, the gitops slot of `appship_merge`). Only a merge `cplat` makes, or finds
already made, posts; the exit code and the result of every command stay what they are without comments."""
import contextlib
import json
from types import SimpleNamespace

import pytest

import spec
from support_158 import FakeGh, SID, make_spec, marker, pr_body
from test_spec_pr import PR_URL, World

URL = "https://github.com/acme/shop/pull/5"


@pytest.fixture()
def gh(monkeypatch):
    fake = FakeGh()
    fake.issue(42).issue(7)
    return fake


def spec_world(tmp_path, monkeypatch, *, status):
    monkeypatch.setattr(spec, "repo_shape", lambda root: None)
    sp = make_spec(tmp_path, status=status)
    return sp, World(tmp_path, monkeypatch)


def run_spec(sp, root, cmd, *, json_out=False):
    import spec_pr
    return spec_pr.main(SimpleNamespace(cmd=cmd, json=json_out, request_changes=False, body_file=None), root, sp)


# ---------------- AC-158.1: spec publish ----------------

def test_publish_posts_the_written_comment_and_prints_its_line_ac_158_1(tmp_path, monkeypatch, gh, capsys):  # AC-158.1
    from support_158 import install
    install(monkeypatch, gh)
    sp, w = spec_world(tmp_path, monkeypatch, status="draft")
    assert run_spec(sp, tmp_path, "publish") == 0
    [body] = gh.posts(42)
    assert body.rstrip().splitlines()[-1] == marker("spec-written", SID) and PR_URL in body
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith(f"{SID}: {PR_URL}") and out[1:] == ["issue #42: spec-written comment posted"]


def test_publish_json_lists_the_comment_lines_ac_158_1(tmp_path, monkeypatch, gh, capsys):  # AC-158.1
    from support_158 import install
    install(monkeypatch, gh)
    sp, w = spec_world(tmp_path, monkeypatch, status="draft")
    assert run_spec(sp, tmp_path, "publish", json_out=True) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["pr"] == 41 and doc["issue_comments"] == ["issue #42: spec-written comment posted"]


def test_publish_twice_comments_once_ac_158_1(tmp_path, monkeypatch, gh, capsys):  # AC-158.1
    from support_158 import install
    install(monkeypatch, gh)
    sp, w = spec_world(tmp_path, monkeypatch, status="draft")
    run_spec(sp, tmp_path, "publish")
    run_spec(sp, tmp_path, "publish")
    assert len(gh.posts(42)) == 1


# ---------------- AC-158.2: spec land ----------------

def test_land_posts_the_approved_comment_after_the_merge_ac_158_2(tmp_path, monkeypatch, gh, capsys):  # AC-158.2
    import pr as prmod
    from support_158 import install
    install(monkeypatch, gh)
    sp, w = spec_world(tmp_path, monkeypatch, status="approved")
    monkeypatch.setattr(prmod, "wait", lambda *a, **k: (True, ["merged"]))
    assert run_spec(sp, tmp_path, "land") == 0
    keys = [b.rstrip().splitlines()[-1] for b in gh.posts(42)]
    assert keys == [marker("spec-written", SID), marker("spec-approved", SID)]   # publish ran first, as today
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "merged" and out[-1] == "issue #42: spec-approved comment posted"


def test_land_that_does_not_merge_says_nothing_of_approval_ac_158_2(tmp_path, monkeypatch, gh, capsys):  # AC-158.2
    import pr as prmod
    from support_158 import install
    install(monkeypatch, gh)
    sp, w = spec_world(tmp_path, monkeypatch, status="approved")
    monkeypatch.setattr(prmod, "wait", lambda *a, **k: (False, ["RED: ci"]))
    assert run_spec(sp, tmp_path, "land") == 1
    assert [b.rstrip().splitlines()[-1] for b in gh.posts(42)] == [marker("spec-written", SID)]


def test_land_keeps_its_exit_code_when_gh_cannot_comment_ac_158_7(tmp_path, monkeypatch, gh, capsys):  # AC-158.7
    import pr as prmod
    from support_158 import install
    install(monkeypatch, gh)
    gh.offline = True
    sp, w = spec_world(tmp_path, monkeypatch, status="approved")
    monkeypatch.setattr(prmod, "wait", lambda *a, **k: (True, ["merged"]))
    assert run_spec(sp, tmp_path, "land") == 0
    out = capsys.readouterr()
    notes = [ln for ln in (out.out + out.err).splitlines() if ln.startswith("note: issue comment skipped: #42 ")]
    assert any(" spec-approved: " in ln for ln in notes)


def test_publish_keeps_its_exit_code_when_gh_cannot_comment_ac_158_7(tmp_path, monkeypatch, gh, capsys):  # AC-158.7
    from support_158 import install
    install(monkeypatch, gh)
    gh.issue(42, post_error="HTTP 403: locked")
    sp, w = spec_world(tmp_path, monkeypatch, status="draft")
    assert run_spec(sp, tmp_path, "publish") == 0
    assert "note: issue comment skipped: #42 spec-written: HTTP 403: locked" in capsys.readouterr().out.splitlines()


# ---------------- AC-158.3: the merges cplat makes ----------------

@pytest.fixture()
def merged(monkeypatch):
    import land_merge
    import ship
    monkeypatch.setattr(land_merge, "cleanup", lambda *a, **k: [])
    return ship


def test_pr_wait_merge_on_an_already_merged_pr_posts_ac_158_3(tmp_path, monkeypatch, gh, merged):  # AC-158.3
    import pr as prmod
    from support_158 import install
    install(monkeypatch, gh)
    gh.pr(5, body=pr_body([42]), url=URL)
    monkeypatch.setattr(merged, "gh", lambda args, *, cwd, check=True: json.dumps({"state": "MERGED", "url": URL}))
    ok, lines = prmod.wait(tmp_path, URL, True, 10, 1, 1)
    assert ok and lines[0] == f"{URL} is already merged" and lines[-1] == "issue #42: pr-merged comment posted"
    assert [b.rstrip().splitlines()[-1] for b in gh.posts(42)] == [marker("pr-merged", "5")]


def test_pr_wait_without_merge_never_posts_ac_158_3(tmp_path, monkeypatch, gh, merged):  # AC-158.3
    import pr as prmod
    from support_158 import install
    install(monkeypatch, gh)
    gh.pr(5, body=pr_body([42]), url=URL)
    monkeypatch.setattr(merged, "gh", lambda args, *, cwd, check=True: json.dumps({"state": "MERGED", "url": URL}))
    ok, lines = prmod.wait(tmp_path, URL, False, 10, 1, 1)      # merged by hand, only watched
    assert ok and not gh.posts()


def test_pr_wait_merge_ends_the_same_when_gh_cannot_comment_ac_158_7(tmp_path, monkeypatch, gh, merged):  # AC-158.7
    import pr as prmod
    from support_158 import install
    install(monkeypatch, gh)
    gh.pr(5, body=pr_body([42]), url=URL)
    gh.issue(42, post_error="HTTP 403: locked")
    monkeypatch.setattr(merged, "gh", lambda args, *, cwd, check=True: json.dumps({"state": "MERGED", "url": URL}))
    ok, lines = prmod.wait(tmp_path, URL, True, 10, 1, 1)
    assert ok is True and lines[0] == f"{URL} is already merged"
    assert lines[-1] == "note: issue comment skipped: #42 pr-merged: HTTP 403: locked"


def ship_world(monkeypatch, merged, state, tmp_path):
    saved = []
    monkeypatch.setattr(merged, "require_state", lambda repo: state)
    monkeypatch.setattr(merged, "save_state", lambda repo, st: saved.append(dict(st)))
    monkeypatch.setattr(merged, "gh", lambda args, *, cwd, check=True: json.dumps({"state": "MERGED", "mergeCommit": {"oid": "a" * 40}}))
    return saved


def test_a_resumed_component_ship_land_on_a_merged_pr_posts_ac_158_3(tmp_path, monkeypatch, gh, merged):  # AC-158.3
    from support_158 import install
    install(monkeypatch, gh)
    gh.pr(5, body=pr_body([42, 7]), url=URL)
    saved = ship_world(monkeypatch, merged, {"pr": URL, "phase": "land"}, tmp_path)
    ok, lines = merged.land(tmp_path, 10, 1)
    assert ok and lines[0] == "already merged"
    assert lines[-2:] == ["issue #7: pr-merged comment posted", "issue #42: pr-merged comment posted"]
    assert saved and saved[-1]["merge_sha"] == "a" * 40          # the merge is recorded whatever the comments do


def test_a_component_ship_land_that_just_merged_posts_ac_158_3(tmp_path, monkeypatch, gh, merged):  # AC-158.3
    from support_158 import install
    install(monkeypatch, gh)
    gh.pr(5, body=pr_body([42]), url=URL)
    ship_world(monkeypatch, merged, {"pr": URL, "phase": "land"}, tmp_path)
    ok, lines = merged._merged(tmp_path, {"pr": URL, "phase": "land"}, "b" * 40, ["merged"])
    assert ok and lines[0] == "merged" and lines[-1] == "issue #42: pr-merged comment posted"


def test_a_component_ship_land_keeps_its_result_when_gh_fails_ac_158_7(tmp_path, monkeypatch, gh, merged):  # AC-158.7
    from support_158 import install
    install(monkeypatch, gh)
    gh.offline = True
    saved = ship_world(monkeypatch, merged, {"pr": URL, "phase": "land"}, tmp_path)
    ok, lines = merged._merged(tmp_path, {"pr": URL, "phase": "land"}, "b" * 40, ["merged"])
    assert ok is True and lines[0] == "merged" and saved[-1]["merge_sha"] == "b" * 40
    assert all(ln == "merged" or ln.startswith("note: issue comment skipped: #") for ln in lines)


def appship_world(monkeypatch, view, tmp_path):
    import appship_merge
    import ship
    monkeypatch.setattr(ship, "gh", lambda args, *, cwd, check=True: json.dumps(view))
    monkeypatch.setattr(ship, "CheckWatch", lambda *a, **k: None)
    monkeypatch.setattr(ship, "wait_checks", lambda *a, **k: ("green", [], []))
    monkeypatch.setattr(appship_merge, "slot", lambda *a, **k: contextlib.nullcontext())
    monkeypatch.setattr(appship_merge, "merge", lambda *a, **k: None)
    monkeypatch.setattr(appship_merge, "plan_index", lambda *a, **k: 0)
    return appship_merge


def test_the_system_ship_posts_for_a_gitops_pr_it_merges_ac_158_3(tmp_path, monkeypatch, gh):  # AC-158.3
    from support_158 import install
    install(monkeypatch, gh)
    gh.pr(5, body=pr_body([42]), url=URL)
    mod = appship_world(monkeypatch, {"state": "OPEN", "isDraft": False}, tmp_path)
    ok, lines = mod.land(tmp_path, URL, "shop-gitops", 10, 1)
    assert ok and lines == [f"merged {URL}", "issue #42: pr-merged comment posted"]


def test_the_system_ship_posts_for_a_gitops_pr_found_merged_ac_158_3(tmp_path, monkeypatch, gh):  # AC-158.3
    from support_158 import install
    install(monkeypatch, gh)
    gh.pr(5, body=pr_body([42]), url=URL)
    mod = appship_world(monkeypatch, {"state": "MERGED"}, tmp_path)
    ok, lines = mod.land(tmp_path, URL, "shop-gitops", 10, 1)
    assert ok and lines == [f"{URL} is already merged", "issue #42: pr-merged comment posted"]


def test_the_system_ship_result_is_unchanged_when_gh_fails_ac_158_7(tmp_path, monkeypatch, gh):  # AC-158.7
    from support_158 import install
    install(monkeypatch, gh)
    gh.offline = True
    mod = appship_world(monkeypatch, {"state": "OPEN", "isDraft": False}, tmp_path)
    ok, lines = mod.land(tmp_path, URL, "shop-gitops", 10, 1)
    assert ok is True and lines[0] == f"merged {URL}"
