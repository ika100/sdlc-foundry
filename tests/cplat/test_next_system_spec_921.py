"""#921: in a gitops (system) repo `cplat next` said "Nothing is waiting for you" right after a system spec was approved,
although it needs `/system:plan <n>` and then `/system:ship <n>`. An approved system spec now gives a `ship` item at Build:
`/system:plan <n>` without `docs/plan/<id>.md`, `/system:ship <n>` with the plan and no system ship run or a stopped one;
a running system ship or a done spec gives none."""
import json

import pytest

from support_192 import spec_text
from support_193 import BuildWorld

SPEC = "001-persistent-tasks"
SHAPE = "gitops-app"


def approved(world, status="approved"):
    text = spec_text(SPEC, "Persistent tasks").replace("status: draft", f"status: {status}").replace("shape: platform", f"shape: {SHAPE}")
    world.commit(f"docs/specs/{SPEC}/spec.md", text, f"docs(spec): {SPEC} (#8)")
    world.read_head()


def planned(world):
    world.commit(f"docs/plan/{SPEC}.md", f"---\nplan_id: {SPEC}\nspec: {SPEC}\nstatus: draft\nrepos: []\n---\n\n# Plan\n",
                 f"docs(plan): {SPEC} (#9)")
    world.read_head()


def ship_state(world, **fields):
    import appship_state
    st = {"spec": SPEC, "phase": "repos", "escalated": None, "repos": {}, **fields}
    appship_state.state_path(world.repo).write_text(json.dumps(st))


@pytest.fixture
def world(tmp_path, monkeypatch):
    w = BuildWorld(tmp_path, monkeypatch, shape=SHAPE)
    w.queue()
    return w


def ship_items(world):
    import nextstate
    return [i for i in nextstate.collect(world.repo)["items"] if i["kind"] == "ship"]


def test_an_approved_system_spec_without_a_plan_recommends_system_plan(world, capsys):
    approved(world)
    doc = world.doc(capsys)
    states = {s["name"]: s["state"] for s in doc["bar"]["steps"]}
    assert states["Build"] == "here"
    assert doc["waiting"]["group"] == "ship"
    q = doc["questions"][0]
    assert q["options"][0]["recommended"] is True and q["options"][0]["steps"] == ["/system:plan 1"]
    assert all("/component:" not in s for o in q["options"] for s in (o.get("steps") or []))


def test_a_planned_system_spec_recommends_system_ship(world, capsys):
    approved(world)
    planned(world)
    doc = world.doc(capsys)
    assert doc["waiting"]["group"] == "ship"
    assert doc["questions"][0]["options"][0]["steps"] == ["/system:ship 1"]


def test_a_stopped_system_ship_is_resumed_with_system_ship(world):
    approved(world)
    planned(world)
    ship_state(world, escalated="api: tests red")
    [item] = ship_items(world)
    assert item["command"] == "/system:ship 1" and item["resume"] is True


def test_a_running_system_ship_gives_no_item(world):
    approved(world)
    planned(world)
    ship_state(world)
    assert ship_items(world) == []


@pytest.mark.parametrize("status", ["done", "draft"])
def test_a_done_or_draft_system_spec_gives_no_item(world, status):
    approved(world, status)
    assert ship_items(world) == []


def test_reading_the_state_asks_github_nothing(world):
    approved(world)
    ship_items(world)
    assert world.writes() == []
