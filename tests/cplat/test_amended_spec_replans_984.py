"""#984: an approved amendment of a repo spec sets plan.md aside (plan.v1.md). The units file kept `plan` done (its commit is still
an ancestor of HEAD) and, without a plan, dropped every task unit, so the next unit was `verification` (journey 26: twice, then a
re-plan by hand). The done plan and the units built on it now open again, so the next unit is `plan`."""
from test_203_reschedule import entry, git, ids_of, one_task_per_unit, started, units  # noqa: F401  (autouse fixture)
from units131_support import SPEC_ID


def set_plan_aside(repo):
    d = repo / "docs" / "specs" / SPEC_ID
    git(repo, "mv", str(d / "plan.md"), str(d / "plan.v1.md"))
    git(repo, "commit", "-qm", "spec: approve the amendment")


def test_an_amendment_that_sets_the_plan_aside_makes_plan_the_next_unit_984(tmp_path):
    r = started(tmp_path)
    u = units()
    assert entry(u._read(r), "plan")["status"] == "done" and entry(u._read(r), "task:t1")["status"] == "done"
    red = entry(u._read(r), "red-tests")["status"]
    set_plan_aside(r)
    data = u.prepare(r, "ship", SPEC_ID)
    assert u.next_open(data) == "plan"
    assert entry(data, "plan")["commit"] is None
    assert "task:t1" not in ids_of(data), "the tasks come back from the new plan"
    assert entry(data, "red-tests")["status"] == red, "the amendment does not touch the acceptance tests' unit"


def test_a_new_plan_after_the_amendment_brings_the_task_units_back_984(tmp_path):
    r = started(tmp_path)
    u = units()
    set_plan_aside(r)
    u.prepare(r, "ship", SPEC_ID)
    d = r / "docs" / "specs" / SPEC_ID
    (d / "plan.md").write_text((d / "plan.v1.md").read_text())
    git(r, "add", "-A")
    git(r, "commit", "-qm", "plan: re-plan the amended spec")
    data = u.prepare(r, "ship", SPEC_ID)
    assert entry(data, "plan")["status"] == "done" and "task:t1" in ids_of(data)
