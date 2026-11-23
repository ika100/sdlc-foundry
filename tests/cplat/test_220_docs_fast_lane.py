"""Spec 220 acceptance tests: a docs-only land does not wait for a code PR's catch-up e2e (AC-220.1 to AC-220.10).

Contract: docs/specs/220-a-docs-only-land-does-not-wait-for-a/design.md (printed lines, `e2e-scope.py --diff`, `e2e_gate`, the claim
of `merge_lock`, `land_merge.record_land`, the `lands` run record item and the `runs report` block). Fakes: `gh`, the history of the
base and the clock are in land220_world.py; lands run through `pr._watch` (what `pr wait --merge` does after its first green), and
other lands run inside a hook of the clock while the land under test waits for its checks. No network, no git for the scenarios.
AC-220.9 is a measurement after the release; its two counts are tested through the report (AC-220.8 block).
"""
import subprocess
import sys

import pytest

import land_merge
import merge_lock
from hold_world_198 import OTHER_PID, SLUG, clock, drop_hold, lock_is_free, said, write_hold  # noqa: F401  (fixtures and helpers)
from land220_world import E2E_SECONDS, QUEUE_LINE, World, fast_lane_line, kept_line, read_claim, url_of, waiting_line
from system_fixtures import git
from test_e2e_scope_134 import mini_root


@pytest.fixture()
def world(monkeypatch, tmp_path, clock, said):
    return lambda: World(monkeypatch, tmp_path, clock, said)


def diff(root, frm, to, *extra):
    return subprocess.run([sys.executable, str(root / "scripts" / "e2e-scope.py"), "--diff", frm, to, *extra], cwd=root,
                          capture_output=True, text=True)


def commit(root, files, msg):
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    git(root, "add", "-A")
    git(root, "commit", "-qm", msg)
    return git(root, "rev-parse", "HEAD")


# ---------------- e2e-scope.py --diff and e2e_gate (AC-220.1, AC-220.2) ----------------

def test_diff_of_docs_commits_is_outside_the_e2e_scope_ac_220_1(tmp_path):  # AC-220.1
    root = mini_root(tmp_path)
    base = git(root, "rev-parse", "HEAD")
    commit(root, {"docs/specs/001-x/spec.md": "x\n"}, "docs: a spec")
    to = commit(root, {"docs/changelog.d/1-x.added.md": "a fragment\n"}, "docs: a fragment")
    res = diff(root, base, to)
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == "run=false" and "trigger:" not in res.stderr


def test_diff_of_an_e2e_file_is_inside_the_scope_and_names_the_path_ac_220_2(tmp_path):  # AC-220.2
    root = mini_root(tmp_path)
    base = git(root, "rev-parse", "HEAD")
    commit(root, {"docs/a.md": "a\n"}, "docs: a")
    to = commit(root, {"shapes.yml": "shapes: []\n"}, "feat: a shape")
    res = diff(root, base, to)
    assert res.returncode == 0 and res.stdout.strip() == "run=true"
    assert "trigger: shapes.yml" in res.stderr.splitlines()


def test_diff_sees_a_release_heading_that_the_range_adds_ac_220_2(tmp_path):  # AC-220.2
    root = mini_root(tmp_path)
    base = git(root, "rev-parse", "HEAD")
    to = commit(root, {"docs/CHANGELOG.md": "# CHANGELOG\n\n## [Unreleased]\n\n## [5.7.0] — 2026-11-10\n\ny\n\n## [5.6.1] — 2026-11-03\n\nx\n"},
                "release: 5.7.0")
    res = diff(root, base, to)
    assert res.stdout.strip() == "run=true"
    assert "trigger: release heading 5.7.0" in res.stderr.splitlines()


def test_diff_of_an_unknown_commit_is_an_error_not_a_decision_ac_220_2(tmp_path):  # AC-220.2
    root = mini_root(tmp_path)
    res = diff(root, "deadbeef" * 5, git(root, "rev-parse", "HEAD"))
    assert res.returncode == 1 and "run=" not in res.stdout
    assert any(ln.startswith("ERROR: ") for ln in res.stderr.splitlines())


def test_diff_and_base_together_are_an_argument_error_ac_220_2(tmp_path):  # AC-220.2
    root = mini_root(tmp_path)
    head = git(root, "rev-parse", "HEAD")
    res = diff(root, head, head, "--base", "main")
    assert res.returncode == 2 and "run=" not in res.stdout
    error = res.stderr.strip().splitlines()[-1]                                  # argparse's last line: `prog: error: ...`
    assert "--diff" in error and "--base" in error and "unrecognized" not in error


def test_e2e_workflows_are_the_ones_that_run_the_scope_script_ac_220_1(tmp_path):  # AC-220.1
    import e2e_gate
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "e2e.yml").write_text("name: e2e\non: pull_request\njobs:\n  scope:\n    runs-on: x\n    steps:\n"
                                "      - run: python3 scripts/e2e-scope.py --base origin/main\n")
    (wf / "ci.yml").write_text("name: ci\non: pull_request\njobs:\n  t:\n    runs-on: x\n    steps:\n      - run: devbox run test\n")
    (wf / "e2e-upgrade.yml").write_text("name: e2e-upgrade\non:\n  pull_request:\n    paths: [templates/**]\njobs:\n  u:\n    runs-on: x\n"
                                        "    steps:\n      - run: release-check.py needs-upgrade-e2e\n")
    assert e2e_gate.workflows(tmp_path) == frozenset({"e2e"})
    assert e2e_gate.workflows(tmp_path / "nowhere") == frozenset()


def test_an_e2e_ran_only_when_every_check_of_its_workflow_passed_and_none_was_skipped_ac_220_1(tmp_path):  # AC-220.1
    import e2e_gate
    names = frozenset({"e2e"})
    ci = {"name": "ci / test", "bucket": "pass", "workflow": "ci"}

    def e2e(*buckets):
        return [{"name": f"e2e / {i}", "bucket": b, "workflow": "e2e"} for i, b in enumerate(buckets)]
    assert e2e_gate.ran([ci, *e2e("pass", "pass")], names) is True
    assert e2e_gate.ran([ci, *e2e("pass", "skipping")], names) is False
    assert e2e_gate.ran([ci, *e2e("pass", "pending")], names) is False
    assert e2e_gate.ran([ci, *e2e("pass", "fail")], names) is False
    assert e2e_gate.ran([ci], names) is False                       # no e2e check at all: it did not run


def test_a_scope_that_cannot_be_read_is_undecidable_and_never_raises_ac_220_2(tmp_path):  # AC-220.2
    import e2e_gate
    got = e2e_gate.range_scope(tmp_path, url_of(805), "main", "abc1234")          # not the PR's checkout, not a git repo
    assert got.scope.run is None and got.scope.error and "\n" not in got.scope.error
    assert e2e_gate.change_scope(tmp_path, url_of(805), "main").run is None


# ---------------- AC-220.1 and AC-220.3: a kept e2e ----------------

def kept_scenario(w):
    """A code PR whose green e2e ran; main moved by two docs commits since."""
    a = w.add_pr(805, ["scripts/cplat/foo.py"])
    w.base_moves("docs/a.md")
    w.base_moves("docs/changelog.d/805-b.changed.md")
    return a


def test_a_catch_up_behind_only_out_of_scope_commits_keeps_the_green_e2e_ac_220_1(world, said):  # AC-220.1, AC-220.10
    w = world()
    a = kept_scenario(w)
    old = w.head_of(a).sha
    ok, lines, _ = w.land(a)
    assert ok, lines
    new = w.updates[0][2]
    assert len(w.updates) == 1 and w.merges[0]["head"] == new                   # updated as today, merged on the new head
    assert kept_line(old, 2) in said
    assert w.clock.t < E2E_SECONDS / 2                                         # the e2e of the new head (25 min) was not waited for
    assert w.merges[0]["e2e_pending"] is True and w.range_calls and w.range_calls[0][0] == a


def test_the_e2e_run_of_a_kept_head_is_cancelled_after_the_merge_ac_220_3(world, said):  # AC-220.3, AC-220.10
    w = world()
    a = kept_scenario(w)
    ok, lines, _ = w.land(a)
    assert ok
    new_head = w.heads[w.updates[0][2]]
    run_id = w.rid(new_head, "e2e")
    assert w.cancels == [run_id]                                               # the e2e run, not the ci run
    assert f"e2e: cancelled run {run_id} (e2e) on {new_head.sha[:7]}: the kept e2e covers it" in [*said, *lines]
    assert w.events.index(("merge", 805)) < w.events.index(("cancel", run_id))  # cancelled once the merge was accepted


def test_a_red_non_e2e_check_of_the_new_head_still_stops_a_kept_land_ac_220_3(world, said):  # AC-220.3
    w = world()
    a = kept_scenario(w)
    w.after_update[a] = {"ci": "fail"}
    ok, lines, _ = w.land(a)
    assert not ok
    assert w.merges == [] and w.cancels == []
    assert any(ln.startswith("RED") or "ci / test" in ln for ln in lines)


# ---------------- AC-220.2: in scope or undecidable ----------------

def test_an_in_scope_commit_in_the_range_waits_for_every_check_and_names_the_path_ac_220_2(world, said):  # AC-220.2, AC-220.10
    w = world()
    a = w.add_pr(805, ["scripts/cplat/foo.py"])
    w.base_moves("scripts/cplat/ship.py")
    w.base_moves("docs/a.md")
    w.base_moves("tests/e2e/run.sh")
    ok, lines, _ = w.land(a)
    assert ok
    new = w.updates[0][2]
    assert waiting_line(new, "scripts/cplat/ship.py is inside the e2e scope (and 1 more)") in said
    assert w.clock.t >= E2E_SECONDS and w.merges[0]["e2e_pending"] is False    # the e2e of the new head was waited for
    assert w.cancels == [] and not any(ln.startswith("e2e: kept") for ln in said)


def test_an_undecidable_scope_waits_for_every_check_and_says_so_ac_220_2(world, said):  # AC-220.2, AC-220.10
    w = world()
    a = kept_scenario(w)
    w.undecidable = "unknown base 1234567"
    ok, lines, _ = w.land(a)
    assert ok
    new = w.updates[0][2]
    assert waiting_line(new, "the e2e scope could not be decided (unknown base 1234567)") in said
    assert w.clock.t >= E2E_SECONDS and w.merges[0]["e2e_pending"] is False and w.cancels == []


# ---------------- AC-220.4 and AC-220.5: the fast lane ----------------

def fast_lane_scenario(w):
    """A is a code PR that must wait for its e2e (an in-scope commit came in); B is a docs PR; B lands while A waits."""
    a = w.add_pr(805, ["scripts/cplat/foo.py"])
    b = w.add_pr(806, ["docs/specs/220-x/spec.md"], e2e="skipping")
    w.base_moves("scripts/cplat/ship.py")
    hook = w.at(100, lambda: w.land(b, run_id="run-b"))
    ok, lines, _ = w.land(a, run_id="run-a")
    return a, b, hook, ok, lines


def test_a_docs_land_merges_while_a_code_land_waits_on_its_checks_ac_220_4(world, said):  # AC-220.4, AC-220.10
    w = world()
    a, b, hook, ok, lines = fast_lane_scenario(w)
    assert ok and hook.result and hook.result[0] is True, (lines, hook.result)
    claim = hook.claim
    assert claim and claim["pr"] == a and claim["who"] == merge_lock.who_of(a) and isinstance(claim["pid"], int) and claim["since"]
    assert hook.lock_free is True                                              # the wait of A holds no flock, only the claim
    assert said.count(fast_lane_line(a, b)) == 1
    first_head = w.updates[0][2]
    assert w.order()[0] == 806 and w.merged(806)[0]["t"] < w.heads[first_head].born + E2E_SECONDS     # B did not wait for A's e2e
    assert w.merged(806)[0]["t"] - hook.at < 600
    assert w.merge_under_lock == [True, True]                                  # each merge step is inside the merge lock
    assert read_claim() is None and lock_is_free()


def test_the_code_land_catches_up_again_after_the_fast_lane_merge_ac_220_5(world, said):  # AC-220.5, AC-220.10
    w = world()
    a, b, hook, ok, lines = fast_lane_scenario(w)
    assert ok and w.order() == [806, 805]
    first, last = w.updates[0][2], w.updates[-1][2]
    assert len([u for u in w.updates if u[1] == a]) == 2 and last != first    # a second update after B's merge
    merged = w.merged(805)[0]
    assert merged["head"] == last and merged["behind"] == 0                    # merged on a base its checks saw
    assert kept_line(first, 1) in said                                         # B's docs commit is outside the scope: the e2e of round 1 holds
    assert w.cancels == [w.rid(w.heads[last], "e2e")]


# ---------------- AC-220.6: in-scope and undecidable lands queue ----------------

@pytest.mark.parametrize("kind", ["in scope", "undecidable"])
def test_a_land_in_scope_or_undecidable_waits_for_the_lock_ac_220_6(world, said, kind):  # AC-220.6, AC-220.10
    w = world()
    a = w.add_pr(805, ["scripts/cplat/foo.py"])
    if kind == "in scope":
        b = w.add_pr(806, ["scripts/cplat/bar.py"])
    else:
        b = w.add_pr(806, ["docs/specs/x/spec.md"], e2e="skipping")
        w.change_undecidable = "unknown base"
    w.base_moves("scripts/cplat/ship.py")
    hook = w.at(100, lambda: w.land(b), queue_probe=True)
    ok, lines, _ = w.land(a)
    assert ok and hook.queued and hook.result is None
    queue = [ln for ln in said if QUEUE_LINE.match(ln)]
    assert queue and QUEUE_LINE.match(queue[0]).group(1) == merge_lock.who_of(a)
    assert fast_lane_line(a, b) not in said
    assert w.order() == [805]                                                  # B never merged while A waited on its checks
    assert [u for u in w.updates if u[1] == b] == []                           # and never started a catch-up of its own


# ---------------- AC-220.7: the release hold and RELEASE mode ----------------

def test_a_fast_lane_merge_still_waits_for_a_release_hold_ac_220_7(world, said, clock):  # AC-220.7, AC-220.10
    w = world()
    a = w.add_pr(805, ["scripts/cplat/foo.py"])
    b = w.add_pr(806, ["docs/specs/220-x/spec.md"], e2e="skipping")
    w.base_moves("scripts/cplat/ship.py")
    dropped = []

    def b_lands_under_a_hold():
        write_hold()
        clock.live.add(OTHER_PID)
        clock.at(clock.t + 120, lambda: (dropped.append(clock.t), drop_hold()))
        return w.land(b)
    hook = w.at(100, b_lands_under_a_hold)
    ok, lines, _ = w.land(a)
    assert ok and hook.result and hook.result[0] is True
    assert any(ln.startswith(f"waiting for the release hold of {SLUG}") for ln in said)
    assert dropped and w.merged(806)[0]["t"] >= dropped[0]                     # the hold was checked right before the fast-lane merge
    assert fast_lane_line(a, b) in said


def test_a_release_mode_land_queues_behind_a_claim_and_takes_no_fast_lane_ac_220_7(world, said):  # AC-220.7, AC-220.10
    w = world()
    a = w.add_pr(805, ["scripts/cplat/foo.py"])
    b = w.add_pr(806, ["docs/specs/220-x/spec.md"], e2e="skipping")
    w.base_moves("scripts/cplat/ship.py")
    hook = w.at(100, lambda: w.land(b, mode=land_merge.RELEASE), queue_probe=True)
    ok, lines, _ = w.land(a)
    assert ok and hook.queued
    assert any(QUEUE_LINE.match(ln) for ln in said)
    assert fast_lane_line(a, b) not in said and b not in w.change_calls         # RELEASE mode never asks for the fast lane
    assert w.order() == [805]


def test_a_release_mode_land_behind_main_does_not_catch_up_or_keep_an_e2e_ac_220_7(world, said):  # AC-220.7, AC-220.10
    w = world()
    a = kept_scenario(w)
    with pytest.raises(land_merge.BaseMoved):
        w.land(a, mode=land_merge.RELEASE)
    assert w.updates == [] and w.merges == [] and w.cancels == []
    assert w.range_calls == []
    assert not any(ln.startswith("e2e:") or ln.startswith("fast lane:") for ln in said)


# ---------------- AC-220.8: the land records its waits ----------------

LANDS_KEYS = {"pr", "mode", "scope", "lock_wait_min", "lock_wait_catch_up_min", "catch_up_min", "catch_up_e2e", "range_scope",
              "fast_lane", "e2e_kept"}


def test_a_land_that_kept_an_e2e_records_its_waits_ac_220_8(world, said):  # AC-220.8
    w = world()
    a = kept_scenario(w)
    ok, lines, _ = w.land(a, run_id="run-a")
    assert ok
    item = w.lands_item("run-a")
    assert LANDS_KEYS <= set(item)
    assert item["pr"] == 805 and item["mode"] == "catch-up" and item["scope"] == "code"
    assert item["e2e_kept"] is True and item["fast_lane"] is False and item["range_scope"] == "out" and item["catch_up_e2e"] is False
    assert item["lock_wait_min"] == 0 and item["lock_wait_catch_up_min"] == 0
    assert 0 < item["catch_up_min"] < 5 and item["catch_up_min"] == round(item["catch_up_min"], 1)


def test_the_fast_lane_and_the_catch_up_e2e_are_recorded_for_both_lands_ac_220_8(world, said):  # AC-220.8
    w = world()
    a, b, hook, ok, lines = fast_lane_scenario(w)
    assert ok
    docs, code = w.lands_item("run-b"), w.lands_item("run-a")
    assert docs["pr"] == 806 and docs["scope"] == "docs" and docs["fast_lane"] is True and docs["e2e_kept"] is False
    assert docs["lock_wait_min"] < 1
    assert code["pr"] == 805 and code["scope"] == "code" and code["fast_lane"] is False
    assert code["catch_up_e2e"] is True and code["e2e_kept"] is True and code["catch_up_min"] >= 25
    assert code["lock_wait_min"] < 1 and code["lock_wait_catch_up_min"] < 1


def test_a_land_that_ends_red_is_recorded_too_ac_220_8(world, said):  # AC-220.8
    w = world()
    a = kept_scenario(w)
    w.after_update[a] = {"ci": "fail"}
    ok, lines, _ = w.land(a, run_id="run-a")
    assert not ok
    item = w.lands_item("run-a")
    assert item["pr"] == 805 and item["e2e_kept"] is False


