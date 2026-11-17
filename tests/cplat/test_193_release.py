"""Spec 193 acceptance tests: the end of build (AC-193.6), the Release and deploy steps (AC-193.7) and the last screen (AC-193.8)."""
import pytest

from support_193 import BuildWorld, by_label, labels, question

FIXED = "**Fixed the label that came back (#755).** More text about what was wrong.\n"
ADDED = "**The build screen shows the queue (#756).** More text.\n"


@pytest.fixture
def world(tmp_path, monkeypatch):
    w = BuildWorld(tmp_path, monkeypatch)
    w.queue()
    return w


def finished_build(world, *, tokens=True):
    world.build(started="2026-11-14T09:00:00", slots=2)
    world.event("started", "#755", "2026-11-14T09:00:00", unit="issue-755.1")
    world.event("done", "#755", "2026-11-14T10:30:00", unit="issue-755.1", pr="https://github.com/o/n/pull/760")
    world.event("started", "spec-189", "2026-11-14T09:05:00", unit="spec-189.1")
    world.event("done", "spec-189", "2026-11-14T12:10:00", unit="spec-189.1", pr="https://github.com/o/n/pull/761")
    if tokens:
        world.counted("issue-755.1", 4_000_000)
        world.counted("spec-189.1", 8_400_000)


def fragments(world):
    world.fragment("755-label.fixed.md", FIXED)
    world.fragment("756-queue.added.md", ADDED)


# ---------------- AC-193.6: end of build ----------------

def test_end_of_build_prints_the_totals_from_the_records(world, capsys):  # AC-193.6
    finished_build(world)
    world.person("issue:o/n:755", "spec:o/n:189-progress", minutes=8.0)
    fragments(world)
    screen = world.screen(capsys)
    assert "The build is done." in screen
    assert "Wall time: 3 h 10 min" in screen
    assert "Tokens: 12,400,000" in screen
    assert "Questions to you: 2" in screen
    b = world.doc(capsys)["build"]
    assert b["ended"] is True and b["totals"] == {"wall_minutes": 190, "tokens": 12_400_000, "questions": 2}


def test_a_value_that_cannot_be_read_is_left_out(world, capsys):  # AC-193.6
    finished_build(world, tokens=False)
    screen = world.screen(capsys)
    assert "The build is done." in screen and "Tokens:" not in screen
    assert "tokens" not in world.doc(capsys)["build"]["totals"]


def test_ready_to_release_lists_the_fragment_summaries_by_section(world, capsys):  # AC-193.6
    finished_build(world)
    fragments(world)
    lines = world.screen(capsys).splitlines()
    i = lines.index("Ready to release:")
    assert lines[i + 1:i + 5] == ["  Fixed", "    Fixed the label that came back (#755)", "  Added", "    The build screen shows the queue (#756)"]
    assert "  Changed" not in lines


def test_the_release_step_follows_as_the_next_choice(world, capsys):  # AC-193.6
    finished_build(world)
    fragments(world)
    doc = world.doc(capsys)
    q = next(q for q in doc["questions"] if q["header"] == "Release")
    assert labels(q) == ["Release now", "Show details", "Collect more"]
    assert doc["waiting"]["group"] == "release"


def test_a_build_that_is_not_ended_shows_no_totals(world, capsys):  # AC-193.6
    finished_build(world)
    world.unit("issue-757", "running")
    screen = world.screen(capsys)
    assert "The build is done." not in screen and "Wall time" not in screen
    assert world.doc(capsys)["build"]["ended"] is False


def test_the_release_group_alone_lists_the_sections_without_totals(world, capsys):  # AC-193.6
    fragments(world)
    screen = world.screen(capsys)
    assert "A release is ready: 2 changes since" in screen
    assert "Ready to release:" in screen and "Wall time" not in screen


def test_each_section_is_cut_at_five(world, capsys):  # AC-193.6
    for i in range(7):
        world.fragment(f"8{i}-x.fixed.md", f"**Fix number {i} (#8{i}).** Text.\n")
    lines = world.screen(capsys).splitlines()
    i = lines.index("Ready to release:")
    assert len([ln for ln in lines[i + 2:] if ln.startswith("    Fix number")]) == 5
    assert any("and 2 more" in ln for ln in lines[i:])


def test_a_component_repo_reads_the_merged_titles_since_the_last_tag(tmp_path, monkeypatch, capsys):  # AC-193.6  (A9)
    w = BuildWorld(tmp_path, monkeypatch, shape="library-python")
    w.queue()
    w.tag("v1.0.0", "2026-11-01T09:00:00")
    w.commit("a.txt", "a", "fix: stop the loop from dying (#755)")
    w.commit("b.txt", "b", "feat: add the queue screen (#756)")
    w.commit("c.txt", "c", "chore: tidy the tests")
    lines = w.screen(capsys).splitlines()
    i = lines.index("Ready to release:")
    assert lines[i + 1:i + 7] == ["  Fixed", "    fix: stop the loop from dying (#755)", "  Added", "    feat: add the queue screen (#756)",
                                  "  Changed", "    chore: tidy the tests"]
    q = next(q for q in w.doc(capsys)["questions"] if q["header"] == "Release")
    assert by_label(q, "Release now")["steps"] == ["/component:release"]


# ---------------- AC-193.7: release and promote ----------------

def test_release_choice_in_the_platform_repo(world, capsys):  # AC-193.7
    fragments(world)
    q = question(world.doc(capsys), "release:o/n:first")
    assert q["header"] == "Release" and labels(q) == ["Release now", "Show details", "Collect more"]
    assert q["options"][0]["recommended"] is True
    assert q["options"][0]["steps"] == ["/platform:release"]


def test_collect_more_leaves_the_release_as_a_waiting_item(world, capsys):  # AC-193.7
    fragments(world)
    more = by_label(question(world.doc(capsys), "release:o/n:first"), "Collect more")
    assert not more["steps"] and "release:o/n:first" in more["then"] and "--later" in more["then"]
    world.stuck(500)                                   # something else is shown first: the release is counted
    assert "Release: 2 changes ready" in world.screen(capsys)
    nothing = world.doc(capsys, "--later", "release:o/n:first")
    assert nothing["waiting"]["later"] == 1


def deployable(tmp_path, monkeypatch, promotion, staging_runs_head):
    """A service repo whose model and staging reads are replaced by the seams the design names (`staging._find`, `staging.resolve`)."""
    import staging
    w = BuildWorld(tmp_path, monkeypatch, shape="service-python")
    w.queue()
    w.tag("v1.0.0", "2026-11-01T09:00:00")
    w.commit("a.txt", "a", "fix: stop the loop from dying (#755)")
    head = w.read_head()

    class Model:
        def staging_promotion(self, component):
            return promotion

    class Comp:
        name = "shop-api"

    monkeypatch.setattr(staging, "_find", lambda repo, apps, svc: ("o/gitops", "applications/shop", Comp(), Model(), "o/n"), raising=False)
    monkeypatch.setattr(staging, "resolve", lambda slug, tag, repo=None: head if staging_runs_head else "0" * 40, raising=False)
    return w


def test_manual_staging_is_promoted_before_the_release(tmp_path, monkeypatch, capsys):  # AC-193.7
    w = deployable(tmp_path, monkeypatch, "manual", staging_runs_head=False)
    doc = w.doc(capsys)
    assert doc["build"]["deploy"]["staging"] == "manual" and doc["build"]["deploy"]["step"] == "staging"
    assert doc["waiting"]["group"] == "release" and len(doc["waiting"]["items"]) == 1 and doc["waiting"]["items"][0].startswith("promote:")
    q = doc["questions"][0]
    assert q["header"] == "Staging" and labels(q) == ["Promote to Staging", "Show details", "Not now"]
    assert q["options"][0]["recommended"] is True and q["options"][0]["steps"] == ["/instance:promote shop-api --to staging"]
    assert "can go to staging." in doc["screen"] and "Your part: promote, or hold it back." in doc["screen"]


def test_after_staging_runs_the_head_the_release_is_offered(tmp_path, monkeypatch, capsys):  # AC-193.7
    w = deployable(tmp_path, monkeypatch, "manual", staging_runs_head=True)
    doc = w.doc(capsys)
    assert doc["build"]["deploy"]["step"] == "release"
    q = doc["questions"][0]
    assert q["header"] == "Release" and by_label(q, "Release now")["steps"] == ["/component:release"]


def test_a_staging_that_moves_after_the_dev_smoke_is_never_a_step(tmp_path, monkeypatch, capsys):  # AC-193.7  (A10)
    w = deployable(tmp_path, monkeypatch, "after-dev-smoke", staging_runs_head=False)
    doc = w.doc(capsys)
    assert doc["build"]["deploy"]["staging"] == "after-dev-smoke" and doc["build"]["deploy"]["step"] == "release"
    assert doc["questions"][0]["header"] == "Release"
    assert not any(i.startswith("promote:") and ":staging" in i for i in doc["waiting"]["items"])


def test_the_prod_promotion_item_offers_promote_to_prod_and_not_now(world, capsys):  # AC-193.7
    world.dispatch_item({"id": "promote:web:1.2.0", "kind": "promote", "stage": "Prod", "since": "2026-11-13T10:00:00Z",
                         "reason": "web 1.2.0 is verified in staging", "command": "/instance:promote web --to prod --version v1.2.0",
                         "object": {"type": "component", "repo": "o/n", "issue": None, "spec": None, "run_id": None, "component": "web",
                                    "version": "1.2.0", "pr": None, "url": None}, "cwd_repo": "o/n", "consequence": None, "way_back": None})
    doc = world.doc(capsys)
    q = next(q for q in doc["questions"] if q["header"] == "Prod")
    assert labels(q) == ["Promote to Prod", "Show details", "Not now"]
    assert q["options"][0]["recommended"] is True and q["options"][0]["steps"] == ["/instance:promote web --to prod --version v1.2.0"]
    assert "web 1.2.0 can go to prod." in doc["screen"] and "Your part: promote, or hold it back." in doc["screen"]


# ---------------- AC-193.8: the last screen ----------------

def done_flow(world, *, parked=True, closed=True):
    finished_build(world)
    world.local_spec("189-progress", "The progress screen", 3)
    if closed:
        world.closed_issue(755)
    world.tag("v5.24.0", "2026-11-14T09:50:00")
    world.person("issue:o/n:755", "spec:o/n:189-progress", minutes=14.0)
    if parked:
        world.skipped("spec-190", "stopped by you")


def test_last_screen_lines(world, capsys):  # AC-193.8
    done_flow(world)
    screen = world.screen(capsys)
    lines = screen.splitlines()
    assert "Issues closed: #755" in lines and "Released: v5.24.0" in lines and "Your time: 14 min" in lines
    assert "Nothing is waiting for you." in lines
    assert "Parked: spec 190 (stopped by you)" in lines
    assert lines[-1].startswith("Your part: nothing. You can walk away.") or "Your part: nothing. You can walk away." in screen
    assert "New issues show up here in /platform:next" in lines
    assert lines.index("Issues closed: #755") < lines.index("Released: v5.24.0") < lines.index("Your time: 14 min") \
        < lines.index("Nothing is waiting for you.") < lines.index("Parked: spec 190 (stopped by you)") \
        < lines.index("New issues show up here in /platform:next")


def test_last_screen_with_nothing_closed_and_nothing_parked(world, capsys):  # AC-193.8
    done_flow(world, parked=False, closed=False)
    lines = world.screen(capsys).splitlines()
    assert "Issues closed: none" in lines and "Parked: none" in lines


def test_last_screen_leaves_out_an_unreadable_time(world, capsys):  # AC-193.8
    finished_build(world)
    world.tag("v5.24.0", "2026-11-14T09:50:00")
    screen = world.screen(capsys)
    assert "Released: v5.24.0" in screen and "Your time" not in screen


def test_the_last_screen_has_no_questions_and_the_flow_document(world, capsys):  # AC-193.8
    done_flow(world)
    doc = world.doc(capsys)
    assert doc["questions"] == []
    flow = doc["build"]["flow"]
    assert flow["done"] is True and flow["released"] == "v5.24.0" and flow["issues_closed"] == [755]
    assert flow["your_minutes"] == 14.0 and flow["parked"] == [{"ref": "spec 190", "reason": "stopped by you"}]


def test_the_flow_is_not_done_while_nothing_was_released(world, capsys):  # AC-193.8
    finished_build(world)
    world.fragment("755-label.fixed.md", FIXED)
    doc = world.doc(capsys)
    assert doc["build"]["flow"]["done"] is False and doc["build"]["flow"]["released"] is None
    assert "Nothing is waiting for you." not in doc["screen"]


def test_the_flow_is_not_done_while_something_waits(world, capsys):  # AC-193.8
    done_flow(world)
    world.stuck(500)
    doc = world.doc(capsys)
    assert doc["build"]["flow"]["done"] is False and "Released: v5.24.0" not in doc["screen"]
