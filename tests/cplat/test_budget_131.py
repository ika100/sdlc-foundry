"""Spec 131 acceptance tests: budgets that scale with the plan (AC-131.13, AC-131.14), the $0 rule (AC-131.12), the
verification grace (AC-131.15, AC-131.16) and the cost that is never a lower figure (AC-131.17).

Formula: T open and done tasks, C active criteria; cost max(15, 10 + 1.5T + 0.5C), minutes max(180, 60 + 15T + 5C),
invocations max(60, 20 + 5T + C), reruns 6. Spec 128 (T=8, C=14) is a fixed case: $29, 250 minutes, 74 invocations, 6 reruns.
"""
import json
import re
import shutil

import pytest

import budget
import headless
import runs
import spec
from test_budget import Usage, usage  # noqa: F401  (fixtures)
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)
from units131_support import BRANCH, SPEC_ID, World, git, make_repo, plan_for

SPEC128 = {"minutes": 250, "invocations": 74, "reruns": 6, "cost": 29}


# ---------------- AC-131.13: the formula ----------------

def test_the_limits_of_spec_128():  # AC-131.13
    assert budget.plan_limits(8, 14, budget.DEFAULTS) == SPEC128


@pytest.mark.parametrize("t, c, expected", [
    (1, 1, {"minutes": 180, "invocations": 60, "reruns": 6, "cost": 15}),
    (3, 2, {"minutes": 180, "invocations": 60, "reruns": 6, "cost": 15.5}),
    (20, 30, {"minutes": 510, "invocations": 150, "reruns": 6, "cost": 55}),
])
def test_floors_for_small_plans_and_growth_for_large_ones(t, c, expected):  # AC-131.13
    assert budget.plan_limits(t, c, budget.DEFAULTS) == expected


def test_a_floor_from_the_settings_files_and_off():  # AC-131.13
    got = budget.plan_limits(8, 14, {**budget.DEFAULTS, "cost": 40, "minutes": None})
    assert got["cost"] == 40 and got["minutes"] is None and got["invocations"] == 74


def test_the_plan_size_counts_open_and_done_tasks_and_active_criteria(tmp_path):  # AC-131.13
    r = make_repo(tmp_path)
    assert budget.plan_size(r, SPEC_ID) == (3, 2)
    spec.task_done(spec.find(r, "7"), "t1")
    assert budget.plan_size(r, SPEC_ID) == (3, 2)
    assert budget.plan_size(make_repo(tmp_path, plan=False, name="other"), SPEC_ID) is None


def test_a_ship_without_options_gets_the_scaled_limits(tmp_path, monkeypatch, capsys):  # AC-131.13
    w = World(tmp_path, monkeypatch, plan=True, tasks=8, acs=14)
    w.run("--max-runs", "1")
    out = capsys.readouterr().out
    assert "budget: minutes 250, invocations 74, reruns 6, cost $29 (plan: T=8, C=14)  (cplat budget show)" in out
    (ledger,) = w.ledgers()
    assert ledger["limits"] == SPEC128
    (part,) = ledger["parts"].values()
    assert part["T"] == 8 and part["C"] == 14 and part["limits"] == SPEC128


def test_a_limit_given_as_an_option_replaces_its_default(tmp_path, monkeypatch):  # AC-131.13
    w = World(tmp_path, monkeypatch, plan=True, tasks=8, acs=14)
    w.run("--max-runs", "1", "--budget", "cost=40", "--budget", "reruns=off")
    (ledger,) = w.ledgers()
    assert ledger["limits"] == {"minutes": 250, "invocations": 74, "reruns": None, "cost": 40}
    assert "cost" in ledger["fixed"] and "reruns" in ledger["fixed"]


def test_a_floor_in_the_settings_files_replaces_the_platform_floor(tmp_path, monkeypatch):  # AC-131.13
    w = World(tmp_path, monkeypatch, plan=True)
    (w.repo / ".platform-settings.yml").write_text("budget:\n  cost: 20\n")
    w.run("--max-runs", "1")
    (ledger,) = w.ledgers()
    assert ledger["limits"]["cost"] == 20 and ledger["limits"]["minutes"] == 180


def test_a_run_over_several_specs_gets_the_sum_of_each_specs_defaults(tmp_path, monkeypatch):  # AC-131.13
    w = World(tmp_path, monkeypatch, plan=True)
    d8 = w.repo / "docs" / "specs" / "008-other"
    shutil.copytree(w.repo / "docs" / "specs" / SPEC_ID, d8)
    for f in ("spec.md", "plan.md"):
        t = (d8 / f).read_text().replace("007-price-alerts", "008-other").replace("AC-007", "AC-008")
        (d8 / f).write_text(t)
    (d8 / "plan.md").write_text(re.sub(r"spec_hash: \w+", f"spec_hash: {spec.read(d8).ac_hash()}", (d8 / "plan.md").read_text()))
    git(w.repo, "add", "-A")
    git(w.repo, "commit", "-qm", "second spec")
    w.run("--max-runs", "1", prompt="/component:ship 7 8")
    (ledger,) = w.ledgers()
    assert ledger["limits"] == {"minutes": 360, "invocations": 120, "reruns": 12, "cost": 31}
    assert len(ledger["parts"]) == 2


# ---------------- AC-131.14: raised when the plan appears ----------------

def open_headless_root(repo):
    rid = runs.start("headless", repo="acme/shop-api", mode="headless")
    budget.open_root(rid, budget.work_key(repo, ["7"], "x"), ships=1, repo=repo)
    return rid


def test_rescale_raises_the_limits_notes_the_change_and_never_lowers(tmp_path):  # AC-131.14
    r = make_repo(tmp_path, plan=False, tasks=8, acs=14)
    rid = open_headless_root(r)
    assert budget.find(rid)[1]["limits"] == budget.DEFAULTS
    (r / "docs" / "specs" / SPEC_ID / "plan.md").write_text(plan_for(8, 14, spec.read(r / "docs" / "specs" / SPEC_ID).ac_hash()))
    changes = budget.rescale(rid, r, [SPEC_ID])
    data = budget.find(rid)[1]
    assert data["limits"] == SPEC128 and changes
    reasons = {(c["limit"], c["from"], c["to"], c["reason"]) for c in data["changes"]}
    assert ("cost", 15, 29, f"plan of {SPEC_ID}: T=8, C=14") in reasons
    assert ("minutes", 180, 250, f"plan of {SPEC_ID}: T=8, C=14") in reasons
    assert all({"at", "limit", "from", "to", "reason"} <= set(c) for c in data["changes"])
    n = len(data["changes"])
    assert budget.rescale(rid, r, [SPEC_ID]) == [] and len(budget.find(rid)[1]["changes"]) == n     # nothing to raise
    (r / "docs" / "specs" / SPEC_ID / "plan.md").write_text(plan_for(1, 14, spec.read(r / "docs" / "specs" / SPEC_ID).ac_hash()))
    budget.rescale(rid, r, [SPEC_ID])
    assert budget.find(rid)[1]["limits"] == SPEC128                                                 # never lowered


def test_rescale_leaves_a_limit_given_as_an_option_alone(tmp_path):  # AC-131.14
    r = make_repo(tmp_path, plan=False, tasks=8, acs=14)
    rid = runs.start("headless", repo="acme/shop-api", mode="headless")
    budget.open_root(rid, budget.work_key(r, ["7"], "x"), ships=1, options={"cost": 16}, repo=r)
    (r / "docs" / "specs" / SPEC_ID / "plan.md").write_text(plan_for(8, 14, spec.read(r / "docs" / "specs" / SPEC_ID).ac_hash()))
    budget.rescale(rid, r, [SPEC_ID])
    limits = budget.find(rid)[1]["limits"]
    assert limits["cost"] == 16 and limits["invocations"] == 74


def test_rescale_never_raises_an_error_for_an_unknown_run_or_spec(tmp_path):  # AC-131.14
    r = make_repo(tmp_path)
    assert budget.rescale("no-such-run", r, [SPEC_ID]) in (None, [])
    rid = open_headless_root(r)
    assert budget.rescale(rid, r, ["999-nothing"]) in (None, [])


def test_add_parts_raises_the_sum_for_placeholder_parts(tmp_path):  # AC-131.14
    r = make_repo(tmp_path)
    rid = open_headless_root(r)
    before = dict(budget.find(rid)[1]["limits"])
    budget.add_parts(rid, {"acme/shop-lib:*": dict(budget.DEFAULTS)})
    after = budget.find(rid)[1]["limits"]
    assert after["invocations"] == before["invocations"] + 60 and after["cost"] == before["cost"] + 15


def test_the_limits_line_lists_each_planned_part(tmp_path):  # AC-131.14
    r = make_repo(tmp_path, plan=False, tasks=8, acs=14)
    rid = open_headless_root(r)
    assert "(plan:" not in budget.limits_line(rid)
    (r / "docs" / "specs" / SPEC_ID / "plan.md").write_text(plan_for(8, 14, spec.read(r / "docs" / "specs" / SPEC_ID).ac_hash()))
    budget.rescale(rid, r, [SPEC_ID])
    assert budget.limits_line(rid) == "budget: minutes 250, invocations 74, reruns 6, cost $29 (plan: T=8, C=14)  (cplat budget show)"


def test_the_section_has_the_parts(tmp_path):  # AC-131.14
    r = make_repo(tmp_path, plan=False, tasks=8, acs=14)
    rid = open_headless_root(r)
    (r / "docs" / "specs" / SPEC_ID / "plan.md").write_text(plan_for(8, 14, spec.read(r / "docs" / "specs" / SPEC_ID).ac_hash()))
    budget.rescale(rid, r, [SPEC_ID])
    sec = budget.section(budget.find(rid)[1], None, None, None)
    assert sec["parts"] == {f"acme/shop-api:{SPEC_ID}": {"T": 8, "C": 14}} and sec["grace"] is None


# ---------------- AC-131.12: the $0 rule ----------------

def test_a_headless_run_that_started_no_session_costs_zero(tmp_path, usage):  # AC-131.12
    r = make_repo(tmp_path)
    usage.cost = 3.7
    rid = open_headless_root(r)
    data = budget.find(rid)[1]
    assert budget.used_of(data)["invocations"] == 0 and budget.used_of(data)["cost"] == 0
    budget.count_invocation(rid)
    assert budget.used_of(budget.find(rid)[1])["cost"] == pytest.approx(3.7)


# ---------------- AC-131.17: never a lower figure ----------------

def test_an_incomplete_cost_is_unknown_whatever_the_number_of_calls(tmp_path, monkeypatch):  # AC-131.17
    import runs_usage
    r = make_repo(tmp_path)
    rid = open_headless_root(r)
    budget.count_invocation(rid)
    for calls in (0, 1, 40):
        totals = {"calls": calls, "failed_calls": 0, "input": 1, "output": 1, "cache_read": 0, "cache_write": 0, "cost_usd": 2.5,
                  "cost_complete": False, "models_without_price": []}
        monkeypatch.setattr(runs_usage, "for_run", lambda rec, totals=totals, **kw: {
            "sessions": ["s"], "price_table": "x", "incomplete": "time budget of 10 s used up", "totals": totals,
            "by_phase": {}, "by_role": {}, "by_model": {}})
        assert budget.used_of(budget.find(rid)[1])["cost"] == "unknown", calls


# ---------------- AC-131.15, AC-131.16: the grace ----------------

def build_world(tmp_path, *, open_tasks=0, options=None):
    """A repo whose units file has every unit before verification done (open_tasks of the tasks left open),
    and the headless root of a run with the budget option."""
    r = make_repo(tmp_path)
    git(r, "checkout", "-qb", BRANCH)
    import units
    units.prepare(r, "ship", SPEC_ID)
    f = r / ".git" / "cplat-units.json"
    data = json.loads(f.read_text())
    tasks = [u for u in data["units"] if u["id"].startswith("task:")]
    for u in data["units"]:
        if u["id"] in {"verification", "land"} or u in tasks[len(tasks) - open_tasks:]:
            continue
        u.update(status="done", commit=git(r, "rev-parse", "HEAD"))
    f.write_text(json.dumps(data))
    rid = runs.start("headless", repo="acme/shop-api", mode="headless")
    budget.open_root(rid, budget.work_key(r, ["7"], "x"), ships=1, options=options or {"invocations": 4}, repo=r)
    return r, rid


def test_the_grace_is_granted_once_when_only_verification_is_left(tmp_path, capsys):  # AC-131.15
    r, rid = build_world(tmp_path)
    budget.count_invocation(rid, 4)
    capsys.readouterr()
    assert budget.check(rid, "session", repo=r) is None
    assert capsys.readouterr().out.count("budget grace: verification") == 1
    grace = budget.find(rid)[1]["grace"]
    assert grace["for"] == "verification" and grace["limit"] == "invocations" and grace["state"] == "active"
    add = grace["add"]
    assert (add["minutes"], add["invocations"], add["reruns"]) == (36, 10, 2)
    assert add["cost"] in (3, 3.1)                                           # 20% of $15 or of the $15.5 of this plan, at least $3
    assert budget.check(rid, "session", repo=r) is None                      # still inside the grace, nothing printed again
    assert "budget grace" not in capsys.readouterr().out
    assert budget.section(budget.find(rid)[1], None, None, None)["grace"]["for"] == "verification"


def test_the_grace_has_floors(tmp_path):  # AC-131.15
    r, rid = build_world(tmp_path, options={"invocations": 1, "minutes": 10, "cost": 1})
    budget.count_invocation(rid, 1)
    assert budget.check(rid, "session", repo=r) is None
    add = budget.find(rid)[1]["grace"]["add"]
    assert add["invocations"] == 10 and add["minutes"] == 30 and add["cost"] == 3


def test_no_grace_while_an_earlier_unit_is_open(tmp_path, capsys):  # AC-131.15
    r, rid = build_world(tmp_path, open_tasks=1)
    budget.count_invocation(rid, 4)
    assert budget.check(rid, "session", repo=r) == "invocations"
    assert budget.find(rid)[1]["grace"] is None and "budget grace" not in capsys.readouterr().out


def test_no_grace_without_a_repo_to_look_at(tmp_path):  # AC-131.15
    r, rid = build_world(tmp_path)
    budget.count_invocation(rid, 4)
    assert budget.check(rid, "session") == "invocations"


def test_ending_the_grace_gives_the_base_limits_back_and_it_is_never_granted_again(tmp_path):  # AC-131.15
    r, rid = build_world(tmp_path)
    budget.count_invocation(rid, 4)
    budget.check(rid, "session", repo=r)
    budget.end_grace(rid)
    assert budget.find(rid)[1]["grace"]["state"] == "ended"
    assert budget.check(rid, "session", repo=r) == "invocations"             # land never runs on the grace
    assert budget.find(rid)[1]["grace"]["state"] == "ended"


def test_a_grace_that_is_used_up_stops_with_its_reason(tmp_path):  # AC-131.16
    r, rid = build_world(tmp_path)
    budget.count_invocation(rid, 4)
    budget.check(rid, "session", repo=r)
    budget.count_invocation(rid, 10)                                         # 14 = 4 + the grace of 10
    assert budget.check(rid, "session", repo=r) == "invocations"
    assert budget.find(rid)[1]["grace"]["state"] == "used"
    assert budget.stop(rid, "invocations", "session") == "budget exhausted: invocations (grace used)"
    assert runs.active(rid)["budget"]["verification_left"] is True


def test_the_grace_does_not_touch_stages_or_rerun_counts(tmp_path):  # AC-131.16
    r, rid = build_world(tmp_path)
    before = budget.find(rid)[1]
    budget.count_invocation(rid, 4)
    budget.check(rid, "session", repo=r)
    after = budget.find(rid)[1]
    assert after["stages"] == before["stages"] and after["attempts"] == before["attempts"]
    assert after["used"]["reruns"] == before["used"]["reruns"]
