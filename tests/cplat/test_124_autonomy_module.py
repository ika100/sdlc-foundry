"""Spec 124 acceptance tests: the pure module `scripts/cplat/autonomy.py` (AC-124.1 .. AC-124.6, AC-124.14, AC-124.22).

Contract: design.md "Meaning of the levels", "Guardrails (AC-124.14)" and the plan's task t2. Names assumed beyond the written
contract (listed in the tester's report):
  * `effective(env, block, *, paused, promotion)` returns the environment object of `model show --json` (`declared`, `effective`,
    `cap`, `paused`, `engine`, `autoMerge`, ..., `undoWindow`, `promotion`). A "policy" below is such an object.
  * `compare(old, new)` and `tighten(old, new)` take two policies. The compared fields are named `level` (the `declared` level),
    `engine`, `autoMerge.routes`, `autoMerge.maxCriticality`, `riskGate.maxFiles`, `riskGate.maxLines`, `riskGate.regressionTest`,
    `riskGate.secondReview`, `budget.runsPerDay`, `budget.mergesPerDay`, `budget.perRun.<key>`, `window`, `undoWindow`.
    `tighten` returns a policy whose `declared` and `effective` are the tighter level.
  * `parse_duration` raises `ValueError` or `core.PlatformError` for a bad duration."""
import copy
import datetime as dt

import pytest

from core import PlatformError

UTC = dt.timezone.utc
WED_10 = dt.datetime(2026, 10, 28, 10, 0, tzinfo=UTC)       # a Wednesday, inside the default window


def amod():
    import autonomy
    return autonomy


def pol(level="act", env="dev", promotion="main", paused=False, **block):
    a = amod()
    return a.effective(env, {"level": level, **block}, paused=paused, promotion=promotion)


def fix(**kw):
    f = {"route": "fix", "criticality": "low", "change": {"files": 2, "lines": 40},
         "regression": {"test": "t", "before": "failed", "after": "passed"}, "second_review": {"result": "passed", "findings": []}}
    f.update(kw)
    return f


def outside(policy=None, f=None, merges=0, runs=1, now=WED_10):
    return amod().outside(policy or pol(), f or fix(), merges_today=merges, runs_today=runs, now=now)


# ---------------- AC-124.2: the levels ----------------

def test_the_levels_are_ordered_and_improve_is_the_last_ac_124_2():  # AC-124.2
    """AC-124.2: the levels are ordered and improve is the last."""
    assert amod().LEVELS == ("observe", "advise", "propose", "act", "improve")


def test_each_level_says_what_the_engine_may_do_and_includes_the_one_before_ac_124_2():  # AC-124.2
    """AC-124.2: each level says what the engine may do and includes the one before."""
    a = amod()
    texts = [a.allows(lv) for lv in a.LEVELS]
    assert "record issues from signals" in texts[0]
    assert "triage" in texts[1] and "notify" in texts[1]
    assert "fix pull requests" in texts[2] and "person merges" in texts[2]
    assert "merge fixes within the guardrails" in texts[3] and "roll back after a failed smoke" in texts[3] and "undo" in texts[3]
    assert "act as `act`" in texts[4] or "acts as `act`" in texts[4] or "as `act`" in texts[4]
    assert len(set(texts)) == 5


def test_improve_is_declared_improve_and_effective_act_ac_124_2():  # AC-124.2
    """AC-124.2: improve is declared improve and effective act."""
    p = pol("improve")
    assert p["declared"] == "improve" and p["effective"] == "act"


def test_an_unpaused_level_is_effective_as_declared_ac_124_2():  # AC-124.2
    """AC-124.2: an unpaused level is effective as declared."""
    for lv in ("observe", "advise", "propose", "act"):
        assert pol(lv)["effective"] == lv


def test_a_paused_environment_is_effectively_observe_ac_124_2():  # AC-124.2
    """AC-124.2: a paused environment is effectively observe."""
    p = pol("act", paused=True)
    assert p["declared"] == "act" and p["effective"] == "observe" and p["paused"] is True


def test_an_environment_without_autonomy_is_observe_ac_124_1():  # AC-124.1
    """AC-124.1: an environment without autonomy is observe."""
    p = amod().effective("dev", None, paused=False, promotion="main")
    assert p["declared"] == "observe" and p["effective"] == "observe" and p["engine"] is None


# ---------------- AC-124.3: the prod cap ----------------

def test_the_caps_per_environment_ac_124_3():  # AC-124.3
    """AC-124.3: the caps per environment."""
    assert amod().CAP == {"dev": "improve", "staging": "improve", "prod": "act"}


def test_validate_refuses_improve_in_prod_ac_124_3():  # AC-124.3
    """AC-124.3: validate refuses improve in prod."""
    with pytest.raises(PlatformError) as e:
        amod().validate("prod", {"level": "improve"})
    assert "environments.prod.autonomy.level: act is the highest level allowed in prod, got 'improve'" in str(e.value)


def test_validate_accepts_act_in_prod_and_improve_elsewhere_ac_124_3():  # AC-124.3
    """AC-124.3: validate accepts act in prod and improve elsewhere."""
    a = amod()
    a.validate("prod", {"level": "act"})
    a.validate("dev", {"level": "improve"})
    a.validate("staging", {"level": "improve"})


def test_the_policy_reports_its_cap_ac_124_3():  # AC-124.3
    """AC-124.3: the policy reports its cap."""
    assert pol("act", env="prod", promotion="manual")["cap"] == "act" and pol("act")["cap"] == "improve"


# ---------------- AC-124.1 / AC-124.4: validation and defaults ----------------

@pytest.mark.parametrize("block, needle", [
    ({"mode": 1}, "environments.dev.autonomy: unknown key 'mode' (allowed: level, autoMerge, riskGate, budget, window, undoWindow, engine)"),
    ({"level": "turbo"}, "environments.dev.autonomy.level must be one of observe, advise, propose, act, improve, got 'turbo'"),
    ({"engine": "nope"}, "environments.dev.autonomy.engine must be an http(s) URL"),
    ({"autoMerge": {"routes": ["spec"]}}, "environments.dev.autonomy.autoMerge.routes: spec is refused: a spec always needs a person's approval (allowed: fix)"),
    ({"autoMerge": {"routes": ["x"]}}, "autoMerge.routes: 'x' is not a route (allowed: fix)"),
    ({"riskGate": {"maxFile": 1}}, "environments.dev.autonomy.riskGate: unknown key 'maxFile'"),
    ({"window": {"from": "9am"}}, "environments.dev.autonomy.window.from must be \"HH:MM\", got '9am'"),
    ({"undoWindow": "1 day"}, "environments.dev.autonomy.undoWindow must be a duration like 24h, 90m or 2d, got '1 day'"),
    ({"budget": {"perRun": {"hours": 1}}}, "budget.perRun: unknown key 'hours'"),
])
def test_validate_gives_the_renderers_messages_ac_124_1(block, needle):  # AC-124.1
    """AC-124.1: validate gives the renderers messages."""
    with pytest.raises(PlatformError) as e:
        amod().validate("dev", block)
    assert needle in str(e.value)


def test_validate_instance_and_top_follow_the_same_messages_ac_124_22():  # AC-124.22
    """AC-124.22: validate instance and top follow the same messages."""
    a = amod()
    with pytest.raises(PlatformError) as e:
        a.validate_instance("api", "dev", {"level": "act"})
    assert "components.api.instances.dev.autonomy: unknown key 'level' (allowed: max)" in str(e.value)
    with pytest.raises(PlatformError) as e:
        a.validate_instance("api", "dev", {"max": "turbo"})
    assert "components.api.instances.dev.autonomy.max must be one of observe, advise, propose, act, improve, got 'turbo'" in str(e.value)
    with pytest.raises(PlatformError) as e:
        a.validate_top({"paused": "maybe"})
    assert "autonomy.paused must be true or false" in str(e.value)
    with pytest.raises(PlatformError) as e:
        a.validate_top({"level": "act"})
    assert "autonomy: unknown key 'level' (allowed: paused)" in str(e.value)
    a.validate_instance("api", "dev", {"max": "propose"})
    a.validate_top({"paused": True})


def test_the_defaults_are_documented_and_effective_ac_124_4():  # AC-124.4
    """AC-124.4: the defaults are documented and effective."""
    p = amod().effective("dev", {"level": "act"}, paused=False, promotion="main")
    assert p["autoMerge"] == {"routes": ["fix"], "maxCriticality": "low"}
    assert p["riskGate"] == {"maxFiles": 5, "maxLines": 200, "regressionTest": True, "secondReview": True}
    assert p["budget"] == {"runsPerDay": 5, "mergesPerDay": 2, "perRun": {"minutes": 60, "invocations": 20, "reruns": 2, "cost": 3}}
    assert p["window"] == {"days": ["mon", "tue", "wed", "thu", "fri"], "from": "09:00", "to": "17:00", "timezone": "UTC"}
    assert p["undoWindow"] == "24h" and p["promotion"] == "main"
    assert amod().DEFAULTS is not None


def test_nested_mappings_merge_key_by_key_ac_124_4():  # AC-124.4
    """AC-124.4: nested mappings merge key by key."""
    p = pol("act", budget={"perRun": {"cost": 5}})
    assert p["budget"]["perRun"] == {"minutes": 60, "invocations": 20, "reruns": 2, "cost": 5} and p["budget"]["runsPerDay"] == 5


def test_durations_ac_124_4():  # AC-124.4
    """AC-124.4: durations."""
    a = amod()
    assert a.parse_duration("24h") == dt.timedelta(hours=24)
    assert a.parse_duration("90m") == dt.timedelta(minutes=90)
    assert a.parse_duration("2d") == dt.timedelta(days=2)
    for bad in ("1 day", "0h", "h", "10000h", "-1h"):
        with pytest.raises((ValueError, PlatformError)):
            a.parse_duration(bad)


def test_windows_ac_124_4():  # AC-124.4
    """AC-124.4: windows."""
    a = amod()
    w = {"days": ["mon", "tue", "wed", "thu", "fri"], "from": "09:00", "to": "17:00", "timezone": "UTC"}
    assert a.in_window(w, WED_10) is True
    assert a.in_window(w, dt.datetime(2026, 10, 28, 9, 0, tzinfo=UTC)) is True, "from is inclusive"
    assert a.in_window(w, dt.datetime(2026, 10, 28, 17, 0, tzinfo=UTC)) is False, "to is exclusive"
    assert a.in_window(w, dt.datetime(2026, 10, 31, 10, 0, tzinfo=UTC)) is False, "a Saturday"
    night = {**w, "from": "22:00", "to": "06:00", "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]}
    assert a.in_window(night, dt.datetime(2026, 10, 28, 23, 30, tzinfo=UTC)) is True
    assert a.in_window(night, dt.datetime(2026, 10, 28, 3, 0, tzinfo=UTC)) is True
    assert a.in_window(night, dt.datetime(2026, 10, 28, 12, 0, tzinfo=UTC)) is False
    berlin = {**w, "timezone": "Europe/Berlin"}
    assert a.in_window(berlin, dt.datetime(2026, 10, 28, 7, 30, tzinfo=UTC)) is False       # 08:30 in Berlin
    assert a.in_window(berlin, dt.datetime(2026, 10, 28, 8, 30, tzinfo=UTC)) is True        # 09:30 in Berlin


# ---------------- AC-124.22: the per-component cap ----------------

def test_an_instance_acts_at_the_lower_of_the_environment_and_its_max_ac_124_22():  # AC-124.22
    """AC-124.22: an instance acts at the lower of the environment and its max."""
    a = amod()
    assert a.instance(pol("act"), "propose") == {"max": "propose", "effective": "propose"}
    assert a.instance(pol("propose"), "act") == {"max": "act", "effective": "propose"}, "max never raises above the environment"
    assert a.instance(pol("improve"), "act")["effective"] == "act"
    assert a.instance(pol("act"), None)["effective"] == "act"
    assert a.instance(pol("act", paused=True), "act")["effective"] == "observe"


# ---------------- AC-124.5: promotion is not autonomy ----------------

def test_the_policy_keeps_the_promotion_rule_next_to_the_level_ac_124_5():  # AC-124.5
    """AC-124.5: the policy keeps the promotion rule next to the level."""
    assert pol("act", env="prod", promotion="manual")["promotion"] == "manual"
    assert pol("act", env="staging", promotion="after-dev-smoke")["promotion"] == "after-dev-smoke"
    assert "promote" not in amod().allows("act") and "forward" not in amod().allows("act").lower()


# ---------------- AC-124.6: tighter and looser ----------------

def cmp(old, new):
    return amod().compare(pol(**old) if isinstance(old, dict) else old, pol(**new) if isinstance(new, dict) else new)


def test_a_lower_level_is_tighter_a_higher_one_looser_ac_124_6():  # AC-124.6
    """AC-124.6: a lower level is tighter a higher one looser."""
    assert cmp({"level": "act"}, {"level": "propose"})["level"] == "tighter"
    assert cmp({"level": "propose"}, {"level": "act"})["level"] == "looser"
    assert cmp({"level": "act"}, {"level": "act"})["level"] == "same"


@pytest.mark.parametrize("field, old, new, verdict", [
    ("riskGate.maxLines", {"riskGate": {"maxLines": 200}}, {"riskGate": {"maxLines": 100}}, "tighter"),
    ("riskGate.maxLines", {"riskGate": {"maxLines": 100}}, {"riskGate": {"maxLines": 200}}, "looser"),
    ("riskGate.maxFiles", {"riskGate": {"maxFiles": 5}}, {"riskGate": {"maxFiles": 3}}, "tighter"),
    ("riskGate.regressionTest", {"riskGate": {"regressionTest": False}}, {"riskGate": {"regressionTest": True}}, "tighter"),
    ("riskGate.regressionTest", {"riskGate": {"regressionTest": True}}, {"riskGate": {"regressionTest": False}}, "looser"),
    ("riskGate.secondReview", {"riskGate": {"secondReview": True}}, {"riskGate": {"secondReview": False}}, "looser"),
    ("autoMerge.maxCriticality", {"autoMerge": {"maxCriticality": "high"}}, {"autoMerge": {"maxCriticality": "low"}}, "tighter"),
    ("autoMerge.maxCriticality", {"autoMerge": {"maxCriticality": "low"}}, {"autoMerge": {"maxCriticality": "medium"}}, "looser"),
    ("autoMerge.routes", {"autoMerge": {"routes": ["fix"]}}, {"autoMerge": {"routes": []}}, "tighter"),
    ("autoMerge.routes", {"autoMerge": {"routes": []}}, {"autoMerge": {"routes": ["fix"]}}, "looser"),
    ("budget.runsPerDay", {"budget": {"runsPerDay": 5}}, {"budget": {"runsPerDay": 3}}, "tighter"),
    ("budget.mergesPerDay", {"budget": {"mergesPerDay": 2}}, {"budget": {"mergesPerDay": 4}}, "looser"),
    ("undoWindow", {"undoWindow": "24h"}, {"undoWindow": "48h"}, "tighter"),
    ("undoWindow", {"undoWindow": "24h"}, {"undoWindow": "12h"}, "looser"),
    ("window", {}, {"window": {"days": ["mon", "tue"]}}, "tighter"),
    ("window", {"window": {"days": ["mon", "tue"]}}, {}, "looser"),
    ("window", {}, {"window": {"from": "10:00", "to": "16:00"}}, "tighter"),
    ("window", {}, {"window": {"from": "08:00"}}, "looser"),
    ("window", {}, {"window": {"timezone": "Europe/Berlin"}}, "looser"),
    ("engine", {"engine": "https://a.example.com"}, {"engine": "https://b.example.com"}, "looser"),
])
def test_compare_classifies_each_field_ac_124_6(field, old, new, verdict):  # AC-124.6
    """AC-124.6: compare classifies each field."""
    assert cmp({"level": "act", **old}, {"level": "act", **new})[field] == verdict


def test_tighten_takes_the_tighter_of_each_field_and_never_loosens_ac_124_6():  # AC-124.6
    """AC-124.6: tighten takes the tighter of each field and never loosens."""
    a = amod()
    old = pol("act", riskGate={"maxLines": 200, "maxFiles": 5}, budget={"runsPerDay": 5})
    new = pol("propose", riskGate={"maxLines": 100, "maxFiles": 9}, budget={"runsPerDay": 8})
    t = a.tighten(old, new)
    assert t["declared"] == "propose" and t["effective"] == "propose"
    assert t["riskGate"]["maxLines"] == 100, "tighter: taken from the new value"
    assert t["riskGate"]["maxFiles"] == 5, "looser: the old value stays"
    assert t["budget"]["runsPerDay"] == 5
    assert all(v != "looser" for v in a.compare(old, t).values())


def test_tighten_never_raises_the_level_ac_124_6():  # AC-124.6
    """AC-124.6: tighten never raises the level."""
    old, new = pol("propose"), pol("act")
    assert amod().tighten(old, new)["declared"] == "propose"


# ---------------- AC-124.14: the guardrails ----------------

def test_a_fix_within_every_guardrail_is_outside_none_ac_124_14():  # AC-124.14
    """AC-124.14: a fix within every guardrail is outside none."""
    assert outside() == []


def test_a_route_not_in_the_list_is_outside_ac_124_14():  # AC-124.14
    """AC-124.14: a route not in the list is outside."""
    assert outside(f=fix(route="spec")) == ["autoMerge.routes"]
    assert outside(pol("act", autoMerge={"routes": []})) == ["autoMerge.routes"]


def test_a_criticality_above_the_maximum_is_outside_ac_124_14():  # AC-124.14
    """AC-124.14: a criticality above the maximum is outside."""
    assert outside(f=fix(criticality="medium")) == ["autoMerge.maxCriticality"]
    assert outside(pol("act", autoMerge={"maxCriticality": "high"}), fix(criticality="high")) == []
    assert outside(pol("act", autoMerge={"maxCriticality": "medium"}), fix(criticality="high")) == ["autoMerge.maxCriticality"]


def test_more_files_or_lines_than_allowed_are_outside_ac_124_14():  # AC-124.14
    """AC-124.14: more files or lines than allowed are outside."""
    assert outside(f=fix(change={"files": 6, "lines": 10})) == ["riskGate.maxFiles"]
    assert outside(f=fix(change={"files": 5, "lines": 200})) == []
    assert outside(f=fix(change={"files": 1, "lines": 201})) == ["riskGate.maxLines"]


def test_a_regression_test_must_fail_before_and_pass_after_ac_124_14():  # AC-124.14
    """AC-124.14: a regression test must fail before and pass after."""
    for reg in ({"test": "t", "before": "passed", "after": "passed"}, {"test": "t", "before": "failed", "after": "failed"}, None):
        assert outside(f=fix(regression=reg)) == ["riskGate.regressionTest"], reg
    assert outside(pol("act", riskGate={"regressionTest": False}), fix(regression=None)) == []


def test_a_second_review_finding_is_outside_ac_124_14():  # AC-124.14
    """AC-124.14: a second review finding is outside."""
    assert outside(f=fix(second_review={"result": "findings", "findings": ["x"]})) == ["riskGate.secondReview"]
    assert outside(f=fix(second_review={"result": "not-run", "findings": []})) == ["riskGate.secondReview"]
    assert outside(pol("act", riskGate={"secondReview": False}), fix(second_review={"result": "findings"})) == []


def test_the_budget_of_the_day_is_checked_for_merges_and_runs_ac_124_14():  # AC-124.14
    """AC-124.14: the budget of the day is checked for merges and runs."""
    assert outside(merges=2) == ["budget.mergesPerDay"]
    assert outside(merges=1) == []
    assert outside(runs=5) == [], "this run is included: the 5th of 5 is still inside"
    assert outside(runs=6) == ["budget.runsPerDay"]


def test_outside_the_window_is_outside_ac_124_14():  # AC-124.14
    """AC-124.14: outside the window is outside."""
    assert outside(now=dt.datetime(2026, 10, 28, 20, 0, tzinfo=UTC)) == ["window"]
    assert outside(now=dt.datetime(2026, 10, 31, 10, 0, tzinfo=UTC)) == ["window"]


def test_every_guardrail_is_named_in_the_documented_order_ac_124_14():  # AC-124.14
    """AC-124.14: every guardrail is named in the documented order."""
    f = fix(route="spec", criticality="high", change={"files": 9, "lines": 900}, regression=None,
            second_review={"result": "findings", "findings": ["x"]})
    got = outside(f=f, merges=2, runs=6, now=dt.datetime(2026, 10, 31, 3, 0, tzinfo=UTC))
    assert got == ["autoMerge.routes", "autoMerge.maxCriticality", "riskGate.maxFiles", "riskGate.maxLines", "riskGate.regressionTest",
                   "riskGate.secondReview", "budget.mergesPerDay", "budget.runsPerDay", "window"]


def test_a_missing_fact_counts_as_outside_ac_124_14():  # AC-124.14
    """AC-124.14: a missing fact counts as outside."""
    f = fix()
    del f["change"]
    assert outside(f=f) == ["riskGate.maxFiles", "riskGate.maxLines"]
    f = fix()
    del f["second_review"]
    assert outside(f=f) == ["riskGate.secondReview"]
    f = fix()
    del f["criticality"]
    assert "autoMerge.maxCriticality" in outside(f=f)


def test_outside_does_not_change_its_inputs_ac_124_14():  # AC-124.14
    """AC-124.14: outside does not change its inputs."""
    p, f = pol(), fix(route="spec")
    before = copy.deepcopy((p, f))
    outside(p, f)
    assert (p, f) == before
