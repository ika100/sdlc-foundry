"""Spec 192 acceptance tests: the screen `cplat next` prints (AC-192.1, .2, .3, .4, .5, .9).

The sources (`gh`, run list, dispatcher files, notification state, clock) are faked in support_192; the screen is read
through `nextcmd.main`, so no test depends on the inner modules."""
import re
import subprocess

import pytest

import support_192 as s
from support_192 import World

BANNED = re.compile(r"\b(dispatchers?|slots?|escalat\w*|units?|claim\w*|held)\b", re.I)


@pytest.fixture
def world(tmp_path, monkeypatch):
    return World(tmp_path, monkeypatch)


def parts(screen):
    return screen.split("\n\n")


def two_drafts(world):
    world.add_draft("189-web-image", "A web image without the finding", issue=682, pr=690, created="2026-11-10")
    world.add_draft("190-second", "Second change", issue=683, pr=691, created="2026-11-11", assumptions=("A", "B", "C"))


# ---------------- AC-192.1 ----------------

def test_screen_has_three_parts_in_order(world, capsys):  # AC-192.1
    two_drafts(world)
    screen = world.screen(capsys)
    p = parts(screen)
    assert len(p) == 3
    assert "① Issue" in p[0]
    assert "2 specs are written and wait for your approval." in p[1]
    assert p[2].startswith("Your part:")


def test_nothing_state_ends_with_walk_away(world, capsys):  # AC-192.1
    last = parts(world.screen(capsys))[-1]
    assert last.startswith("Your part: nothing")
    assert "You can walk away" in last


def test_next_changes_nothing(world, capsys):  # AC-192.1
    two_drafts(world)
    world.add_issue(700, "An issue")
    world.stuck()
    before = world.snapshot()
    world.screen(capsys)
    world.doc(capsys)
    assert world.snapshot() == before
    assert world.writes() == []
    import runs
    assert runs.buffered_count() == 0


def test_same_screen_in_a_fresh_session_and_another_worktree(world, capsys, monkeypatch, tmp_path):  # AC-192.1
    two_drafts(world)
    other = tmp_path / "wt2"
    subprocess.run(["git", "-C", str(world.repo), "worktree", "add", "-q", "-b", "side", str(other)], check=True, capture_output=True)
    first = world.screen(capsys)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "another-session")
    assert world.screen(capsys) == first
    assert world.screen(capsys, repo=other) == first


def test_same_screen_after_an_interrupted_session(world, capsys):  # AC-192.1
    import dispatch_state
    two_drafts(world)
    first = world.screen(capsys)
    state_dir = dispatch_state.needs_path(world.slug).parent
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "needs.json.tmp").write_text('{"items": [{"id": "stuck:o/n:9", "kind": ')   # a write cut short
    (state_dir / "unit-189.partial").write_text("")
    (world.repo / "notes.txt").write_text("left over from the session that was cut off\n")        # untracked
    (world.repo / ".platform-settings.yml").write_text("shape: platform\n# half-edited\n")         # modified
    assert world.screen(capsys) == first
    assert world.doc(capsys)["waiting"]["items"] == ["approve:o/n:189-web-image", "approve:o/n:190-second"]


def test_headless_has_no_questions_but_the_same_screen(world, capsys, monkeypatch):  # AC-192.1
    two_drafts(world)
    attended = world.doc(capsys)
    monkeypatch.setenv("CPLAT_HEADLESS", "1")
    headless = world.doc(capsys)
    assert headless["attended"] is False and headless["questions"] == []
    assert headless["screen"] == attended["screen"]


# ---------------- AC-192.2 ----------------

def test_bar_in_a_platform_repo(world, capsys):  # AC-192.2
    two_drafts(world)
    doc = world.doc(capsys)
    steps = doc["bar"]["steps"]
    assert [x["name"] for x in steps] == ["Issue", "Spec", "Build", "Release"]
    assert [x["state"] for x in steps] == ["done", "here", "todo", "todo"]
    assert doc["bar"]["label"] == "you are here"
    import stages
    assert steps[3]["what"] == stages.explain("Release")["what"]
    bar_lines = parts(doc["screen"])[0].splitlines()
    assert "③ Build" in bar_lines[0] and "④ Release" in bar_lines[0]
    assert "Issue ✓" in bar_lines[0] and "Spec ●" in bar_lines[0]
    assert "you are here" in bar_lines[1]


def test_bar_in_a_service_repo(tmp_path, monkeypatch, capsys):  # AC-192.2
    w = World(tmp_path, monkeypatch, shape="service-python")
    w.add_issue(700, "An issue")
    doc = w.doc(capsys)
    assert [x["name"] for x in doc["bar"]["steps"]] == ["Issue", "Spec", "Build", "Dev", "Staging", "Prod"]
    assert [x["state"] for x in doc["bar"]["steps"]][:2] == ["here", "todo"]


def test_running_work_marks_its_step_as_running_on_its_own(world, capsys):  # AC-192.2
    world.running("189-x", "build")
    doc = world.doc(capsys)
    assert [x["state"] for x in doc["bar"]["steps"]] == ["done", "done", "running", "todo"]
    assert doc["bar"]["label"] == "running on its own"
    assert "running on its own" in parts(doc["screen"])[0]


def test_nothing_waiting_has_no_marked_step(world, capsys):  # AC-192.2
    doc = world.doc(capsys)
    assert doc["bar"]["label"] is None
    assert not [x for x in doc["bar"]["steps"] if x["state"] in ("here", "running")]


# ---------------- AC-192.3 ----------------

def test_stopped_run_comes_before_specs_and_issues(world, capsys):  # AC-192.3
    two_drafts(world)
    world.add_issue(700, "An issue")
    world.stuck(500)
    doc = world.doc(capsys)
    assert doc["waiting"]["group"] == "stopped"
    assert doc["waiting"]["also"] == {"approve": 2, "triage": 1}
    last = parts(doc["screen"])[1].splitlines()[-1]
    assert last.startswith("Also waiting:")
    assert "Also waiting: 2 specs to approve, 1 new issue" in last


def test_group_order_of_the_also_waiting_line(tmp_path, monkeypatch, capsys):  # AC-192.3
    w = World(tmp_path, monkeypatch, shape="gitops-app")
    w.stuck(500)
    w.dispatch_item({"id": "escalation:o/n:501", "kind": "escalation", "stage": "Build", "since": "2026-11-13T09:00:00Z",
                     "reason": "the run for #501 needs a decision", "command": "cplat dispatch resume 501",
                     "object": {"type": "issue", "repo": "o/n", "issue": 501, "spec": None, "run_id": None, "component": None,
                                "version": None, "pr": None, "url": None}, "cwd_repo": "o/n", "consequence": None, "way_back": None})
    w.dispatch_item({"id": "promote:o/n:web:1.2.0", "kind": "promote", "stage": "Prod", "since": "2026-11-13T10:00:00Z",
                     "reason": "web 1.2.0 is verified in staging", "command": "cplat promote web",
                     "object": {"type": "component", "repo": "o/n", "issue": None, "spec": None, "run_id": None, "component": "web",
                                "version": "1.2.0", "pr": None, "url": None}, "cwd_repo": "o/n", "consequence": None,
                     "way_back": {"command": "cplat promote web --back", "warning": None}})
    w.add_issue(700, "An issue")
    doc = w.doc(capsys)
    assert doc["waiting"]["group"] == "stopped"
    assert len(doc["waiting"]["items"]) == 2
    assert list(doc["waiting"]["also"]) == ["triage", "promote"]
    last = parts(doc["screen"])[1].splitlines()[-1]
    assert last.index("new issue") < last.index("to promote")


def test_daily_budget_is_in_the_first_group(world, capsys):  # AC-192.3
    two_drafts(world)
    world.budget()
    assert world.doc(capsys)["waiting"]["group"] == "stopped"


def test_specs_come_before_issues_and_issues_before_a_release(world, capsys):  # AC-192.3
    world.add_issue(700, "An issue")
    (world.repo / "docs" / "changelog.d").mkdir(parents=True)
    (world.repo / "docs" / "changelog.d" / "9-x.added.md").write_text("**x** (spec 9).\n")
    world._git("add", "-A")
    world._git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "fragment")
    doc = world.doc(capsys)
    assert doc["waiting"]["group"] == "issues"
    assert doc["waiting"]["also"] == {"release": 1}
    world.add_draft("189-web-image", "A web image", issue=682, pr=690)
    assert world.doc(capsys)["waiting"]["group"] == "specs"


def test_release_group_alone(world, capsys):  # AC-192.3
    (world.repo / "docs" / "changelog.d").mkdir(parents=True)
    (world.repo / "docs" / "changelog.d" / "9-x.added.md").write_text("**x** (spec 9).\n")
    world._git("add", "-A")
    world._git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "fragment")
    doc = world.doc(capsys)
    assert doc["waiting"]["group"] == "release"
    assert "A release is ready" in doc["screen"]


def test_oldest_first_within_a_group(world, capsys):  # AC-192.3
    world.add_draft("191-newer", "Newer spec", pr=692, created="2026-11-13")
    world.add_draft("189-older", "Older spec", pr=690, created="2026-11-09")
    doc = world.doc(capsys)
    assert doc["waiting"]["items"] == ["approve:o/n:189-older", "approve:o/n:191-newer"]
    text = doc["screen"]
    assert text.index("Older spec") < text.index("Newer spec")


def test_notified_item_shows_its_age(world, capsys):  # AC-192.3
    world.add_issue(700, "An issue")
    world.notified("triage:o/n:700", 42)
    assert "waiting 42 min" in world.screen(capsys)


def test_unnotified_item_shows_no_age(world, capsys):  # AC-192.3
    world.add_issue(700, "An issue")
    assert "waiting 4" not in world.screen(capsys) and re.search(r"waiting \d", world.screen(capsys)) is None


# ---------------- AC-192.4 ----------------

def test_nothing_waits_nothing_runs(world, capsys, monkeypatch):  # AC-192.4
    import dispatch_state
    orig = dispatch_state.load

    def load(slug):
        d = orig(slug)
        d["steering"]["skipped"] = {"x1": {"at": "2026-11-13T08:00:00Z"}, "x2": {"at": "2026-11-13T08:00:00Z"}}
        return d
    monkeypatch.setattr(dispatch_state, "load", load)
    screen = world.screen(capsys)
    assert "Nothing is waiting for you." in screen
    assert "2 parked" in screen
    assert "New issues will show up here." in screen


def test_runs_going_nothing_waiting(world, capsys):  # AC-192.4
    world.local_spec("189-x", "A web image without the finding", 3)
    world.running("189-x", "build")
    screen = world.screen(capsys)
    assert "189" in parts(screen)[1]
    assert "building" in parts(screen)[1]
    assert parts(screen)[2].startswith("Your part: nothing")
    assert "on the desktop" in parts(screen)[2]


def test_channels_of_the_notification_settings(world, capsys):  # AC-192.4
    world.running("189-x", "build")
    world.notify_yaml("events:\n  escalation:\n    desktop: instant\n    github: instant\n    slack: instant\n    email: instant\n")
    last = parts(world.screen(capsys))[2]
    assert last.index("on the desktop") < last.index("on GitHub") < last.index("in Slack") < last.index("by e-mail")


def test_notifications_off(world, capsys):  # AC-192.4
    world.running("189-x", "build")
    world.notify_yaml("events:\n  escalation:\n    desktop: off\n    github: off\n    slack: off\n    email: off\n")
    last = parts(world.screen(capsys))[2]
    assert "notifications are off" in last and "look here again" in last


def test_unreadable_source_is_named_and_never_nothing(world, capsys):  # AC-192.4
    world.gh_fail = "gh: not logged in"
    doc = world.doc(capsys)
    assert "Nothing is waiting" not in doc["screen"]
    assert "GitHub" in doc["screen"] and "Could not read" in doc["screen"]
    assert doc["unavailable"][0]["source"] == "github"
    assert doc["questions"][-1]["options"][0]["label"] == "Try again"
    assert world.next(capsys)[0] == 0


def test_bad_notification_file_is_a_named_source(world, capsys):  # AC-192.4
    world.notify_yaml("bogus: 1\n")
    doc = world.doc(capsys)
    assert "notification" in doc["screen"].lower()
    assert [u["source"] for u in doc["unavailable"]] == ["notifications"]
    assert "Nothing is waiting" not in doc["screen"]


# ---------------- AC-192.5 ----------------

def judgement(world, tmp_path, **by_spec):
    import json
    path = tmp_path / "judgement.json"
    path.write_text(json.dumps({"specs": by_spec}))
    return str(path)


def test_draft_block_with_judgement(world, capsys, tmp_path):  # AC-192.5
    two_drafts(world)
    j = judgement(world, tmp_path, **{"189-web-image": {"you_get": "Web images without the finding.", "assumption": "Scan at build time"}})
    screen = world.screen(capsys, "--judgement", j)
    assert "A web image without the finding" in screen
    assert "#682" in screen
    assert "You get:" in screen and "Web images without the finding." in screen
    assert "I assumed: Scan at build time (1 assumptions in all)" in screen or "I assumed: Scan at build time (1 assumption" in screen
    assert re.search(r"Size:\s+small", screen)
    assert "criteria" not in parts(screen)[1].lower()


def test_assumption_without_judgement_is_the_first_unstruck_one(world, capsys):  # AC-192.5
    world.add_draft("190-second", "Second change", pr=691, assumptions=("Use the store", "Second one"))
    screen = world.screen(capsys)
    assert "I assumed: Use the store (2 assumptions in all)" in screen
    assert "**A1**" not in screen and "other option" not in screen


def test_draft_without_judgement_has_no_empty_field(world, capsys):  # AC-192.5
    world.add_draft("189-web-image", "A web image without the finding", pr=690)
    doc = world.doc(capsys)
    assert doc["judgement_wanted"] is True
    for line in doc["screen"].splitlines():
        assert not line.rstrip().endswith("You get:")
    assert "A web image without the finding" in doc["screen"]
    assert doc["drafts"][0]["title"] == "A web image without the finding"


@pytest.mark.parametrize("criteria,size", [(1, "small"), (4, "small"), (5, "medium"), (8, "medium"), (9, "large"), (12, "large")])
def test_size_classes(world, capsys, criteria, size):  # AC-192.5
    world.add_draft("189-x", "Some change", pr=690, criteria=criteria)
    assert re.search(rf"Size:\s+{size}\b", world.screen(capsys))


def test_size_has_a_time_only_from_three_comparable_runs(world, capsys):  # AC-192.5
    world.add_draft("189-x", "Some change", pr=690, criteria=3)
    for i, minutes in enumerate((40, 45, 50)):
        sid = f"10{i}-old"
        world.local_spec(sid, f"Old {i}", 2)
        world.done_run(sid, minutes)
    assert re.search(r"Size:\s+small, about 45 min", world.screen(capsys))


def test_size_has_no_number_with_two_runs(world, capsys):  # AC-192.5
    world.add_draft("189-x", "Some change", pr=690, criteria=3)
    for i, minutes in enumerate((40, 45)):
        sid = f"10{i}-old"
        world.local_spec(sid, f"Old {i}", 2)
        world.done_run(sid, minutes)
    size_line = next(ln for ln in world.screen(capsys).splitlines() if ln.strip().startswith("Size:"))
    assert "about" not in size_line and not re.search(r"\d", size_line)


# ---------------- AC-192.9 ----------------

def busy(world):
    two_drafts(world)
    world.add_draft("192-long", "A very long title " + "that goes on and on " * 8, issue=684, pr=692, created="2026-11-12")
    for n in range(701, 708):
        world.add_issue(n, f"Issue number {n} " + "with words " * 10)
    world.stuck(500)
    world.running("189-x", "build")


def test_no_line_is_wider_than_80_columns(world, capsys):  # AC-192.9
    busy(world)
    for args in ((), ("--ascii",)):
        for line in world.screen(capsys, *args).splitlines():
            assert len(line) <= 80, line


def test_width_of_the_issue_and_release_screens(world, capsys):  # AC-192.9
    for n in range(701, 708):
        world.add_issue(n, f"Issue number {n} " + "with words " * 10)
    assert all(len(ln) <= 80 for ln in world.screen(capsys).splitlines())


def test_width_of_a_release_screen(world, capsys):  # AC-192.9
    d = world.repo / "docs" / "changelog.d"
    d.mkdir(parents=True)
    for n in range(1, 8):
        (d / f"{n}-{'very-long-name-' * 6}.added.md").write_text(f"**{'A long change ' * 12}** (spec {n}).\n")
    world._git("add", "-A")
    world._git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "fragments")
    doc = world.doc(capsys)
    assert doc["waiting"]["group"] == "release"
    for args in ((), ("--ascii",)):
        screen = world.screen(capsys, *args)
        assert "A release is ready" in screen
        assert all(len(ln) <= 80 for ln in screen.splitlines())


def test_no_colour_codes(world, capsys, monkeypatch):  # AC-192.9
    busy(world)
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.delenv("NO_COLOR", raising=False)
    for args in ((), ("--ascii",)):
        assert "\x1b" not in world.screen(capsys, *args)
    assert "\x1b" not in world.doc(capsys)["screen"]


def test_every_state_symbol_comes_with_a_word(world, capsys):  # AC-192.9
    busy(world)
    utf8 = parts(world.screen(capsys))[0].splitlines()[0]
    for mark in ("✓", "●"):
        assert re.search(rf"[A-Za-z]{{3,}} {mark}", utf8)
    plain = world.screen(capsys, "--ascii")
    bar = parts(plain)[0].splitlines()[0]
    for mark in ("[x]", "[>]"):
        assert re.search(rf"[A-Za-z]{{3,}} {re.escape(mark)}", bar)
    assert any(re.search(r"\[!\] \w+", ln) for ln in plain.splitlines())
    assert any(re.search(r"^\s*! \w+", ln) for ln in world.screen(capsys).splitlines())


def test_ascii_step_numbers_on_a_six_step_bar(tmp_path, monkeypatch, capsys):  # AC-192.9
    w = World(tmp_path, monkeypatch, shape="service-python")
    w.add_issue(700, "An issue")
    bar = parts(w.screen(capsys, "--ascii"))[0].splitlines()[0]
    for num, name in ((1, "Issue"), (2, "Spec"), (3, "Build"), (4, "Dev"), (5, "Staging"), (6, "Prod")):
        assert f"{num}. {name}" in bar
    assert " -- " in bar and all(ord(c) < 128 for c in bar) and len(bar) <= 80


def test_ascii_mode_has_no_symbols(world, capsys):  # AC-192.9
    two_drafts(world)
    screen = world.screen(capsys, "--ascii")
    assert all(ord(c) < 128 for c in screen)
    assert "1. Issue [x]" in screen and "2. Spec [>]" in screen and "3. Build" in screen and "4. Release" in screen


def test_utf8_mode_has_the_symbols(world, capsys):  # AC-192.9
    two_drafts(world)
    screen = world.screen(capsys)
    for symbol in ("①", "②", "✓", "●"):
        assert symbol in screen


@pytest.mark.parametrize("env", [{"LANG": "C"}, {"LC_ALL": "POSIX"}])
def test_a_terminal_that_is_not_utf8_gets_ascii(world, capsys, monkeypatch, env):  # AC-192.9
    two_drafts(world)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert all(ord(c) < 128 for c in world.screen(capsys))


def test_ascii_stuck_marker(world, capsys):  # AC-192.9
    world.stuck(500)
    assert "[!]" in world.screen(capsys, "--ascii")


def test_long_lists_show_five_and_the_rest(world, capsys):  # AC-192.9
    for n in range(701, 708):
        world.add_issue(n, f"Issue number {n}")
    screen = world.screen(capsys)
    assert "and 2 more" in screen
    assert len(re.findall(r"Issue number 70\d", screen)) == 5


def test_ids_follow_the_description(world, capsys):  # AC-192.9
    world.add_draft("189-web-image", "A web image without the finding", issue=682, pr=690)
    line = next(ln for ln in world.screen(capsys).splitlines() if "A web image without the finding" in ln)
    assert line.strip().startswith("A web image without the finding")
    assert line.index("spec 189") > line.index("finding") and "#682" in line


def test_internal_words_do_not_appear(world, capsys):  # AC-192.9
    world.stuck(500)
    world.dispatch_item({"id": "stuck:o/n:501", "kind": "stuck", "stage": "Build", "since": "2026-11-13T09:00:00Z",
                         "reason": "the dispatcher claimed a slot; the escalation is held by this unit", "command": "cplat dispatch resume 501",
                         "object": {"type": "issue", "repo": "o/n", "issue": 501, "spec": None, "run_id": None, "component": None,
                                    "version": None, "pr": None, "url": None}, "cwd_repo": "o/n", "consequence": None, "way_back": None})
    world.running("189-x", "build")
    doc = world.doc(capsys)
    assert not BANNED.search(doc["screen"])
    for q in doc["questions"]:
        assert not BANNED.search(q["question"])
    assert {"schema", "bar", "screen", "waiting", "running", "drafts", "questions", "page", "unavailable", "how"} <= set(doc)
