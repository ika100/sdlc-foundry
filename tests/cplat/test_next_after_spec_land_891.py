"""#891: right after `cplat spec land` of an approved spec (no plan, no build) `cplat next` showed Build and Dev as done, put
"you are here" at Staging and recommended a release of the spec docs; it also waited 20 s for the run queue. An approved spec
nothing builds now places the bar at Build with `/component:ship <n>` first, a commit of spec documents only is no release
change, and the run queue's run read asks for this repo's runs only."""
import pytest

from support_192 import spec_text
from support_193 import BuildWorld, entry

SPEC = "001-tasks"
SHAPE = "service-python"


def approved(world, spec_id=SPEC, title="Create and list tasks", msg=None):
    text = spec_text(spec_id, title).replace("status: draft", "status: approved").replace("shape: platform", f"shape: {SHAPE}")
    world.commit(f"docs/specs/{spec_id}/spec.md", text, msg or f"docs(spec): {spec_id} (#3)")


@pytest.fixture
def world(tmp_path, monkeypatch):
    w = BuildWorld(tmp_path, monkeypatch, shape=SHAPE)
    w.queue()
    w._git("add", "-A")
    w._git(*w._git_id, "commit", "-qm", "chore: run policy")
    w.tag("v0.1.0")
    approved(w)
    w.read_head()
    return w


def kinds(doc):
    return [i.split(":", 1)[0] for i in doc["waiting"]["items"]]


def test_an_approved_spec_places_the_bar_at_build_and_recommends_ship(world, capsys):
    doc = world.doc(capsys)
    states = {s["name"]: s["state"] for s in doc["bar"]["steps"]}
    assert states["Build"] == "here" and states["Dev"] == "todo" and states["Staging"] == "todo"
    assert doc["waiting"]["group"] == "ship" and kinds(doc) == ["ship"]
    q = doc["questions"][0]
    assert q["options"][0]["recommended"] is True and q["options"][0]["steps"] == ["/component:ship 1"]
    assert ["/component:plan 1"] in [o["steps"] for o in q["options"]]


def test_a_spec_docs_only_commit_is_no_release_change(world, capsys):
    doc = world.doc(capsys)
    assert "release" not in doc["waiting"]["also"]
    assert all(not str(o.get("steps") or "").count("/component:release") for q in doc["questions"] for o in q["options"])


def test_a_code_commit_after_the_spec_is_still_a_release_change(world, capsys):
    world.commit("src/app.py", "x = 1\n", "feat(tasks): create and list tasks (#4)")
    world.read_head()
    doc = world.doc(capsys)
    assert doc["waiting"]["also"].get("release") == 1
    release = next(i for i in world_state(world)["items"] if i["kind"] == "release")
    assert release["consequence"]["changes"] == ["feat(tasks): create and list tasks (#4)"]


def world_state(world):
    import nextstate
    return nextstate.collect(world.repo)


def test_a_running_spec_gets_no_ship_item(world, capsys):
    world.running(SPEC)
    assert all(i["kind"] != "ship" for i in world_state(world)["items"])


def test_a_queued_spec_is_left_to_the_run_queue(world, capsys):
    world.queue(entry(1, "spec 1", kind="ship", title="Create and list tasks", spec=SPEC))
    state = world_state(world)
    assert all(i["kind"] != "ship" for i in state["items"])


def test_a_planned_spec_offers_ship_without_plan_only(world, capsys):
    world.commit(f"docs/specs/{SPEC}/plan.md", "---\nspec_id: 001-tasks\n---\n\n# Plan\n", "docs(plan): 001")
    world.read_head()
    item = next(i for i in world_state(world)["items"] if i["kind"] == "ship")
    assert item["command"] == "/component:ship 1" and item["plan_command"] is None


def test_the_platform_repo_gets_no_ship_item(tmp_path, monkeypatch):
    w = BuildWorld(tmp_path, monkeypatch)
    w.queue()
    approved(w)
    import nextstate
    assert all(i["kind"] != "ship" for i in nextstate.collect(w.repo)["items"])


def test_the_run_queue_reads_only_this_repos_runs(monkeypatch):
    import dispatch_backlog
    import runlist
    asked = []
    monkeypatch.setattr(runlist, "collect", lambda *a, **k: asked.append(k) or {"runs": []})
    dispatch_backlog._read_runs("o/n")
    assert asked and asked[0].get("repo") == "o/n"
