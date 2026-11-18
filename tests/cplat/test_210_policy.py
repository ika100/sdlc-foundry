"""Spec 210 acceptance tests: the policy file (AC-210.1).

Contract: design.md "Policy (`.platform/dispatch.yml`)" (keys, defaults, the error messages, `start`/`resume` refusal,
`Policy.values["budget"]`, `Policy.defaulted`, `Policy.unset`, `filler_match`). Seams: the dispatcher world (fake `gh`, a real clone),
`cplat.main(["dispatch", ...])`, and `dispatch_policy.load` for `filler_match`.
"""
import pytest

from dispatch_world import world  # noqa: F401  (fixture)
from support_210 import fresh

PLAN_DEFAULTS = {"weekly_target": 0.92, "window_stop": 0.8, "filler_only": ["priority:P2", "label:enhancement"],
                 "filler_tasks": [], "filler_drafts": True}
VERBS = [("plan",), ("status",), ("start", "--once")]


def _refused(world, text, message, verbs=VERBS):
    world.policy_text(text)
    world.issue(1)
    before = world.fingerprint()
    for verb in verbs:
        r = world.run(*verb)
        assert r.rc == 1, (verb, r)
        assert r.err.startswith("ERROR:") and f".platform/dispatch.yml: {message}" in r.err, (verb, r.err)
    assert world.calls() == [] and world.gh_writes() == [] and world.fingerprint() == before


def test_the_mode_is_cost_by_default_and_marked_as_a_default_ac_210_1(world):  # AC-210.1
    world.policy(budget={"usd_per_day": 5})
    pol = world.plan()["policy"]
    budget = pol["values"]["budget"]
    assert budget["mode"] == "cost" and budget["usd_per_day"] == 5 and budget["plan"] is None
    assert budget["usd_per_month"] is None and budget["tokens_per_day"] is None
    assert "budget.mode" in pol["defaulted"] and pol["unset"] == []


def test_without_a_file_every_default_is_shown_and_the_daily_usd_limit_is_unset_ac_210_1(world):  # AC-210.1
    pol = world.plan()["policy"]
    assert pol["file"] is None
    assert pol["values"]["budget"]["mode"] == "cost" and "budget.mode" in pol["defaulted"]
    assert pol["unset"] == ["budget.usd_per_day"]


def test_mode_plan_fills_the_plan_defaults_and_marks_each_one_ac_210_1(world):  # AC-210.1
    world.policy(budget={"mode": "plan"})
    pol = world.plan()["policy"]
    assert pol["values"]["budget"]["mode"] == "plan" and pol["values"]["budget"]["plan"] == PLAN_DEFAULTS
    assert "budget.mode" not in pol["defaulted"]
    assert {f"budget.plan.{k}" for k in PLAN_DEFAULTS} <= set(pol["defaulted"])
    assert pol["unset"] == []                                       # no USD or token key is required in mode plan


def test_a_given_plan_key_overrides_its_default_and_is_not_marked_ac_210_1(world):  # AC-210.1
    world.policy(budget={"mode": "plan", "plan": {"weekly_target": 0.8, "filler_tasks": [{"name": "bench", "command": "make bench"}]}})
    pol = world.plan()["policy"]
    plan = pol["values"]["budget"]["plan"]
    assert plan["weekly_target"] == 0.8 and plan["window_stop"] == 0.8 and plan["filler_tasks"] == [{"name": "bench", "command": "make bench"}]
    assert "budget.plan.weekly_target" not in pol["defaulted"] and "budget.plan.window_stop" in pol["defaulted"]


def test_a_usd_cap_in_mode_cost_is_a_valid_policy_ac_210_1(world):  # AC-210.1
    world.policy(budget={"usd_per_day": 5, "usd_per_month": 100.5})
    budget = world.plan()["policy"]["values"]["budget"]
    assert budget["usd_per_day"] == 5 and budget["usd_per_month"] == 100.5


@pytest.mark.parametrize("text,message", [
    ("budget:\n  mode: tokens\n  usd_per_day: 5\n", "budget.mode: tokens is not allowed (allowed: cost, plan)"),
    ("budget:\n  mode: free\n", "budget.mode: free is not allowed (allowed: cost, plan)"),
])
def test_another_budget_mode_fails_naming_the_key_and_the_allowed_values_ac_210_1(world, text, message):  # AC-210.1
    _refused(world, text, message)


@pytest.mark.parametrize("text,key,allowed", [
    ("budget:\n  usd_per_day: 5\n  limit: 3\n", "budget.limit", ["mode", "usd_per_day", "usd_per_month", "tokens_per_day", "per_unit", "plan"]),
    ("budget:\n  mode: plan\n  plan:\n    pace: 1\n", "budget.plan.pace",
     ["weekly_target", "window_stop", "filler_only", "filler_tasks", "filler_drafts"]),
    ("budget:\n  mode: plan\n  plan:\n    filler_tasks:\n      - {name: a, command: b, cwd: c}\n", "budget.plan.filler_tasks", ["name", "command"]),
])
def test_an_unknown_budget_key_fails_naming_it_and_the_allowed_keys_ac_210_1(world, text, key, allowed):  # AC-210.1
    world.policy_text(text)
    r = world.run("plan")
    assert r.rc == 1, r
    assert key in r.err and "unknown key" in r.err and all(a in r.err for a in allowed), r.err


@pytest.mark.parametrize("text,key,value", [
    ("budget:\n  usd_per_day: 0\n", "budget.usd_per_day", "0"),
    ("budget:\n  usd_per_day: five\n", "budget.usd_per_day", "five"),
    ("budget:\n  usd_per_day: 5\n  usd_per_month: -1\n", "budget.usd_per_month", "-1"),
    ("budget:\n  mode: plan\n  plan:\n    weekly_target: 0.3\n", "budget.plan.weekly_target", "0.3"),
    ("budget:\n  mode: plan\n  plan:\n    weekly_target: 1.2\n", "budget.plan.weekly_target", "1.2"),
    ("budget:\n  mode: plan\n  plan:\n    window_stop: 0.49\n", "budget.plan.window_stop", "0.49"),
    ("budget:\n  mode: plan\n  plan:\n    window_stop: high\n", "budget.plan.window_stop", "high"),
    ("budget:\n  mode: plan\n  plan:\n    filler_only: [priority:P3]\n", "budget.plan.filler_only", "priority:P3"),
    ("budget:\n  mode: plan\n  plan:\n    filler_drafts: maybe\n", "budget.plan.filler_drafts", "maybe"),
])
def test_a_value_outside_the_allowed_ones_fails_naming_the_key_and_the_value_ac_210_1(world, text, key, value):  # AC-210.1
    world.policy_text(text)
    for verb in VERBS:
        r = world.run(*verb)
        assert r.rc == 1, (verb, r)
        assert f".platform/dispatch.yml: {key}: {value} is not allowed (allowed: " in r.err, r.err
    assert world.calls() == [] and world.gh_writes() == []


def test_the_weekly_target_message_names_the_range_ac_210_1(world):  # AC-210.1
    _refused(world, "budget:\n  mode: plan\n  plan:\n    weekly_target: 0.3\n",
             "budget.plan.weekly_target: 0.3 is not allowed (allowed: a number 0.50..1.00)")


def test_filler_tasks_need_a_name_and_a_command_and_unique_names_ac_210_1(world):  # AC-210.1
    _refused(world, "budget:\n  mode: plan\n  plan:\n    filler_tasks:\n      - {name: a, command: x}\n      - {name: a, command: y}\n",
             "budget.plan.filler_tasks: a is not allowed (allowed: unique names)")
    world.policy_text("budget:\n  mode: plan\n  plan:\n    filler_tasks:\n      - {name: a}\n")
    r = world.run("plan")
    assert r.rc == 1 and "budget.plan.filler_tasks" in r.err and "command" in r.err, r


@pytest.mark.parametrize("plan_text,key", [
    ("  plan:\n    weekly_target: 0.9\n", "budget.plan.weekly_target"),
    ("  plan:\n    filler_drafts: false\n", "budget.plan.filler_drafts"),
    ("  plan: {}\n", "budget.plan"),
])
def test_a_plan_key_in_mode_cost_names_the_key_and_the_mode_it_needs_ac_210_1(world, plan_text, key):  # AC-210.1
    _refused(world, "budget:\n  usd_per_day: 5\n" + plan_text, f"{key}: needs budget.mode: plan")


@pytest.mark.parametrize("verb", ["start", "resume"])
@pytest.mark.parametrize("text", ["slots: 2\n", "slots: 2\nbudget:\n  per_unit:\n    cost: 20\n", "budget:\n  usd_per_month: 100\n"])
def test_mode_cost_without_a_daily_limit_is_refused_by_start_and_resume_naming_usd_per_day_ac_210_1(world, verb, text):  # AC-210.1
    world.issue(1)
    world.policy_text(text)
    before = world.fingerprint()
    r = world.run(verb, "--once") if verb == "start" else world.run(verb)
    assert r.rc == 1, r
    assert "ERROR: .platform/dispatch.yml: budget.usd_per_day is required in mode cost" in r.err, r.err
    assert world.calls() == [] and world.gh_writes() == [] and world.fingerprint() == before


@pytest.mark.parametrize("verb", ["start", "resume"])
def test_a_repo_without_the_policy_file_is_refused_by_start_and_resume_naming_the_file_ac_210_1(world, verb):  # AC-210.1
    world.issue(1)
    assert not (world.repo / ".platform" / "dispatch.yml").exists()
    before = world.fingerprint()
    r = world.run(verb, "--once") if verb == "start" else world.run(verb)
    assert r.rc == 1, r
    assert any(f"no .platform/dispatch.yml in {p}" in r.err for p in (world.repo, world.repo.resolve())), r.err
    assert world.calls() == [] and world.gh_writes() == [] and world.claude_calls() == [] and world.fingerprint() == before


def test_mode_plan_needs_no_usd_or_token_key_to_start_ac_210_1(world):  # AC-210.1
    world.policy(budget={"mode": "plan"})
    fresh(world, five=10, week=30)
    world.issue(1)
    world.behave(mode="wait")
    r = world.run("start", "--once")
    assert r.rc == 0, r
    assert [c["unit"] for c in world.calls()] == ["issue-1.1"]


def test_in_mode_plan_a_usd_cap_applies_as_an_extra_cap_ac_210_1(world):  # AC-210.1
    from support_210 import ledger
    world.policy(budget={"mode": "plan", "usd_per_day": 5})
    fresh(world, five=10, week=30)
    world.issue(1)
    ledger(world, usd={"issue-9.1": 5.0})
    r = world.run("start", "--once")
    assert r.rc == 0 and "no starts: daily budget reached: $5.00 of $5.00" in r.out, r
    assert world.calls() == [] and world.claude_calls() == []


def test_filler_match_follows_the_filler_only_rules_in_mode_plan_only_ac_210_1(world, tmp_path):  # AC-210.1
    import dispatch_policy
    world.policy(budget={"mode": "plan"})
    plan = dispatch_policy.load(world.repo)
    assert dispatch_policy.filler_match(plan, ["Enhancement"]) is True                    # label: case-insensitive
    assert dispatch_policy.filler_match(plan, ["bug", "p2"]) is True                      # priority:P2 through the most urgent label
    assert dispatch_policy.filler_match(plan, ["bug", "p1", "p2"]) is False               # the most urgent is P1
    assert dispatch_policy.filler_match(plan, ["bug"]) is False
    world.policy(budget={"mode": "plan", "plan": {"filler_only": []}})
    assert dispatch_policy.filler_match(dispatch_policy.load(world.repo), ["enhancement", "p2"]) is False
    world.policy(budget={"mode": "plan", "plan": {"filler_only": ["label:chore"]}})
    custom = dispatch_policy.load(world.repo)
    assert dispatch_policy.filler_match(custom, ["chore"]) is True and dispatch_policy.filler_match(custom, ["enhancement"]) is False
    world.policy(budget={"usd_per_day": 5})
    assert dispatch_policy.filler_match(dispatch_policy.load(world.repo), ["enhancement"]) is False    # mode cost has no filler queue
