"""Spec 184 acceptance tests: the dispatcher counts a manual `cplat headless` run against `slots` (AC-184.9).

The world of spec 167 (`dispatch_world`: fake `gh`, fake headless, a real clone `acme/shop-api`); the manual run is a second process
that holds a repo slot through `run_slot.held` (support_184), as every `cplat headless` run does. `plan` and `status` are read as
JSON and as text.
"""
import re

import pytest

from dispatch_world import world  # noqa: F401  (fixture)
from support_184 import Holders

COMMAND = "/component:ship 182"


@pytest.fixture()
def holders(tmp_path):
    h = Holders(tmp_path)
    yield h
    h.close()


def issues(world, n=2):
    for i in range(1, n + 1):
        world.issue(i, title=f"issue {i}", labels=["triaged", "bug"], created=f"2026-11-0{i}T08:00:00Z")


def manual_row(doc_slots, holder, world):
    (row,) = doc_slots["manual"]
    assert row["command"] == COMMAND and row["pid"] == holder.pid and row["checkout"] == str(world.repo.resolve())
    assert re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d", row["since"])
    return row


def test_no_unit_starts_while_a_manual_run_holds_the_only_slot_ac_184_9(world, holders):  # AC-184.9
    world.policy(slots=1)
    issues(world)
    world.behave(mode="wait")
    holder = holders.start(world.repo, COMMAND)
    r = world.run("start", "--once")
    assert r.rc == 0, r
    assert world.calls() == [] and not [ln for ln in r.lines if ln.startswith("started ")]
    holder.end()
    assert world.run("start", "--once").rc == 0
    assert [c["unit"] for c in world.calls()] == ["issue-1.1"]       # the slot is free again: the dispatcher uses it


def test_a_manual_run_leaves_the_other_slots_of_the_pool_to_the_dispatcher_ac_184_9(world, holders):  # AC-184.9
    world.policy(slots=2)
    issues(world, 3)
    world.behave(mode="wait")
    holders.start(world.repo, COMMAND)
    assert world.run("start", "--once").rc == 0
    assert [c["unit"] for c in world.calls()] == ["issue-1.1"]       # one slot manual, one dispatcher unit: no more
    assert world.run("start", "--once").rc == 0
    assert [c["unit"] for c in world.calls()] == ["issue-1.1"]


def test_plan_json_counts_the_manual_run_and_names_it_ac_184_9(world, holders):  # AC-184.9
    world.policy(slots=2)
    issues(world)
    holder = holders.start(world.repo, COMMAND)
    slots = world.plan()["slots"]
    assert (slots["total"], slots["running"], slots["free"]) == (2, 1, 1)
    manual_row(slots, holder, world)


def test_status_shows_the_slot_as_held_by_the_command_ac_184_9(world, holders):  # AC-184.9
    world.policy(slots=2)
    holder = holders.start(world.repo, COMMAND)
    doc = world.run("status", "--json").json()
    manual_row(doc["slots"], holder, world)
    assert doc["slots"]["units"] == []
    text = world.run("status").out
    assert "slots: 1 of 2 in use" in text.splitlines()
    assert re.search(rf"^  held by {re.escape(COMMAND)} \(manual\)  pid {holder.pid}  since \d{{4}}-\d\d-\d\d \d\d:\d\d  "
                     rf"{re.escape(str(world.repo.resolve()))}$", text, re.M)


def test_plan_text_shows_the_slot_as_held_by_the_command_ac_184_9(world, holders):  # AC-184.9
    world.policy(slots=1)
    holders.start(world.repo, COMMAND)
    assert f"held by {COMMAND} (manual)" in world.run("plan").out


def test_without_a_manual_run_plan_and_status_have_no_manual_slot_ac_184_9(world):  # AC-184.9
    world.policy(slots=1)
    assert world.plan()["slots"] == {"total": 1, "running": 0, "free": 1, "manual": []}
    assert world.run("status", "--json").json()["slots"]["manual"] == []
