"""Spec 124 acceptance tests: `render.py` validates the autonomy keys and writes `autonomy.json`
(AC-124.1, AC-124.2, AC-124.3, AC-124.4, AC-124.5, AC-124.9, AC-124.22).

Contract: design.md "system.yaml" (key table and render-error table) and "autonomy.json". The renderer runs as a script in a
hand-built checkout (system_fixtures.render5), as in the spec 114 render tests."""
import json

import pytest

from autonomy_support import APP, DEV_URL, PROD_URL, component, read_json, tiny, tiny_auto, with_autonomy
from system_fixtures import generated, render5

LEVEL_ERR = "must be one of observe, advise, propose, act, improve"


def fails(tmp_path, doc, *needles):
    p = render5(tmp_path, doc)
    assert p.returncode == 1, f"expected a failed render, got {p.returncode}: {p.stdout}{p.stderr}"
    for n in needles:
        assert n in p.stderr, f"{n!r} not in: {p.stderr}"
    assert "autonomy.json" not in " ".join(generated(tmp_path)), "a failed render must not write autonomy.json"
    return p.stderr


def ok(tmp_path, doc):
    p = render5(tmp_path, doc)
    assert p.returncode == 0, p.stdout + p.stderr
    return generated(tmp_path)


def auto_json(tmp_path):
    return read_json(tmp_path / APP / "autonomy.json")


# ---------------- AC-124.1: the accepted keys ----------------

def test_every_autonomy_key_is_accepted_ac_124_1(tmp_path):  # AC-124.1
    """AC-124.1: every autonomy key is accepted."""
    block = {"level": "act", "engine": DEV_URL, "autoMerge": {"routes": ["fix"], "maxCriticality": "medium"},
             "riskGate": {"maxFiles": 3, "maxLines": 100, "regressionTest": True, "secondReview": False},
             "budget": {"runsPerDay": 4, "mergesPerDay": 1, "perRun": {"minutes": 30, "invocations": 10, "reruns": 1, "cost": 2}},
             "window": {"days": ["mon", "tue"], "from": "08:00", "to": "18:00", "timezone": "Europe/Berlin"}, "undoWindow": "12h"}
    ok(tmp_path, tiny_auto(dev=block))
    env = auto_json(tmp_path)["environments"]["dev"]
    assert env["declared"] == "act" and env["engine"] == DEV_URL
    assert env["riskGate"]["maxFiles"] == 3 and env["window"]["timezone"] == "Europe/Berlin" and env["undoWindow"] == "12h"


@pytest.mark.parametrize("level", ["observe", "advise", "propose", "act", "improve"])
def test_each_of_the_five_levels_renders_in_dev_ac_124_1(tmp_path, level):  # AC-124.1
    """AC-124.1: each of the five levels renders in dev."""
    ok(tmp_path, tiny_auto(dev={"level": level}))
    assert auto_json(tmp_path)["environments"]["dev"]["declared"] == level


def test_an_unknown_autonomy_key_names_the_key_and_the_allowed_ones_ac_124_1(tmp_path):  # AC-124.1
    """AC-124.1: an unknown autonomy key names the key and the allowed ones."""
    fails(tmp_path, tiny_auto(dev={"level": "act", "mode": "fast"}),
          "environments.dev.autonomy: unknown key 'mode' (allowed: level, autoMerge, riskGate, budget, window, undoWindow, engine)")


@pytest.mark.parametrize("group, bad, allowed", [
    ("riskGate", "maxFile", "maxFiles, maxLines, regressionTest, secondReview"),
    ("autoMerge", "route", "routes, maxCriticality"),
    ("budget", "runs", "runsPerDay, mergesPerDay, perRun"),
    ("window", "tz", "days, from, to, timezone"),
])
def test_an_unknown_nested_key_names_the_group_the_key_and_the_allowed_ones_ac_124_1(tmp_path, group, bad, allowed):  # AC-124.1
    """AC-124.1: an unknown nested key names the group the key and the allowed ones."""
    err = fails(tmp_path, tiny_auto(dev={"level": "act", group: {bad: 1}}))
    assert f"environments.dev.autonomy.{group}: unknown key '{bad}'" in err and allowed.split(",")[0] in err


def test_an_unknown_per_run_key_is_refused_ac_124_1(tmp_path):  # AC-124.1
    """AC-124.1: an unknown per run key is refused."""
    fails(tmp_path, tiny_auto(dev={"level": "act", "budget": {"perRun": {"hours": 2}}}),
          "environments.dev.autonomy.budget.perRun: unknown key 'hours'")


def test_an_invalid_level_names_the_values_ac_124_1(tmp_path):  # AC-124.1
    """AC-124.1: an invalid level names the values."""
    fails(tmp_path, tiny_auto(dev={"level": "turbo"}), f"environments.dev.autonomy.level {LEVEL_ERR}, got 'turbo'")


@pytest.mark.parametrize("engine", ["ai-ops.example.com", "ftp://x.example.com", 5])
def test_the_engine_must_be_an_http_url_ac_124_1(tmp_path, engine):  # AC-124.1
    """AC-124.1: the engine must be an http url."""
    fails(tmp_path, tiny_auto(dev={"level": "act", "engine": engine}), "environments.dev.autonomy.engine must be an http(s) URL")


def test_without_autonomy_an_environment_is_observe_ac_124_1(tmp_path):  # AC-124.1
    """AC-124.1: without autonomy an environment is observe."""
    doc = tiny()
    doc["environments"]["dev"]["autonomy"] = {"engine": DEV_URL}      # declared, but without a level
    ok(tmp_path, doc)
    envs = auto_json(tmp_path)["environments"]
    assert envs["dev"]["declared"] == "observe" and envs["dev"]["effective"] == "observe"
    assert envs["staging"]["declared"] == "observe" and envs["prod"]["declared"] == "observe"


def test_a_system_without_autonomy_renders_as_before_and_has_no_autonomy_json_ac_124_1(tmp_path):  # AC-124.1
    """AC-124.1: a system without autonomy renders as before and has no autonomy json."""
    without = ok(tmp_path / "a", tiny())
    withit = ok(tmp_path / "b", tiny_auto(dev={"level": "act"}))
    assert not any(k.endswith("autonomy.json") for k in without)
    assert {k: v for k, v in withit.items() if not k.endswith("autonomy.json")} == without, "autonomy changes no Kubernetes manifest"


# ---------------- AC-124.2: improve acts as act ----------------

def test_improve_is_accepted_and_effective_act_ac_124_2(tmp_path):  # AC-124.2
    """AC-124.2: improve is accepted and effective act."""
    ok(tmp_path, tiny_auto(dev={"level": "improve"}))
    dev = auto_json(tmp_path)["environments"]["dev"]
    assert (dev["declared"], dev["effective"]) == ("improve", "act")
    assert auto_json(tmp_path)["levels"] == ["observe", "advise", "propose", "act", "improve"]


def test_a_pause_makes_every_environment_effectively_observe_ac_124_2(tmp_path):  # AC-124.2
    """AC-124.2: a pause makes every environment effectively observe."""
    doc = tiny_auto(dev={"level": "act"}, staging={"level": "propose"})
    doc["autonomy"] = {"paused": True}
    ok(tmp_path, doc)
    aj = auto_json(tmp_path)
    assert aj["paused"] is True
    assert aj["environments"]["dev"]["declared"] == "act" and aj["environments"]["dev"]["effective"] == "observe"
    assert aj["environments"]["dev"]["paused"] is True


# ---------------- AC-124.3: prod is capped at act ----------------

def test_prod_improve_fails_naming_act_as_the_highest_level_ac_124_3(tmp_path):  # AC-124.3
    """AC-124.3: prod improve fails naming act as the highest level."""
    fails(tmp_path, tiny_auto(prod={"level": "improve"}), "environments.prod.autonomy.level: act is the highest level allowed in prod, got 'improve'")


def test_prod_act_and_dev_staging_improve_render_ac_124_3(tmp_path):  # AC-124.3
    """AC-124.3: prod act and dev staging improve render."""
    ok(tmp_path, tiny_auto(prod={"level": "act"}, dev={"level": "improve"}, staging={"level": "improve"}))
    envs = auto_json(tmp_path)["environments"]
    assert envs["prod"]["cap"] == "act" and envs["dev"]["cap"] == "improve" and envs["staging"]["cap"] == "improve"


# ---------------- AC-124.4: the guardrail keys, values and defaults ----------------

def test_the_spec_route_is_refused_ac_124_4(tmp_path):  # AC-124.4
    """AC-124.4: the spec route is refused."""
    fails(tmp_path, tiny_auto(dev={"level": "act", "autoMerge": {"routes": ["fix", "spec"]}}),
          "environments.dev.autonomy.autoMerge.routes: spec is refused: a spec always needs a person's approval (allowed: fix)")


def test_any_other_route_is_not_a_route_ac_124_4(tmp_path):  # AC-124.4
    """AC-124.4: any other route is not a route."""
    fails(tmp_path, tiny_auto(dev={"level": "act", "autoMerge": {"routes": ["deploy"]}}),
          "autoMerge.routes: 'deploy' is not a route (allowed: fix)")


def test_the_routes_may_be_empty_or_fix_ac_124_4(tmp_path):  # AC-124.4
    """AC-124.4: the routes may be empty or fix."""
    ok(tmp_path, tiny_auto(dev={"level": "act", "autoMerge": {"routes": []}}))
    assert auto_json(tmp_path)["environments"]["dev"]["autoMerge"]["routes"] == []


@pytest.mark.parametrize("block, needle", [
    ({"autoMerge": {"maxCriticality": "critical"}}, "autoMerge.maxCriticality"),
    ({"riskGate": {"maxFiles": 0}}, "riskGate.maxFiles"),
    ({"riskGate": {"maxLines": "many"}}, "riskGate.maxLines"),
    ({"riskGate": {"regressionTest": "sometimes"}}, "riskGate.regressionTest"),
    ({"budget": {"runsPerDay": -1}}, "budget.runsPerDay"),
    ({"budget": {"perRun": {"cost": 0}}}, "budget.perRun.cost"),
    ({"window": {"days": []}}, "window.days"),
    ({"window": {"days": ["mon", "mon"]}}, "window.days"),
    ({"window": {"days": ["someday"]}}, "window.days"),
    ({"window": {"from": "9am"}}, "window.from must be \"HH:MM\", got '9am'"),
    ({"window": {"from": "10:00", "to": "10:00"}}, "window"),
    ({"window": {"timezone": "Mars/Base"}}, "window.timezone"),
    ({"undoWindow": "1 day"}, "undoWindow must be a duration like 24h, 90m or 2d, got '1 day'"),
    ({"undoWindow": "0h"}, "undoWindow"),
])
def test_a_wrong_value_names_the_key_and_the_form_ac_124_4(tmp_path, block, needle):  # AC-124.4
    """AC-124.4: a wrong value names the key and the form."""
    fails(tmp_path, tiny_auto(dev={"level": "act", **block}), f"environments.dev.autonomy.{needle}")


def test_every_omitted_field_has_its_documented_default_ac_124_4(tmp_path):  # AC-124.4
    """AC-124.4: every omitted field has its documented default."""
    ok(tmp_path, tiny_auto(dev={"level": "act"}))
    env = auto_json(tmp_path)["environments"]["dev"]
    assert env["autoMerge"] == {"routes": ["fix"], "maxCriticality": "low"}
    assert env["riskGate"] == {"maxFiles": 5, "maxLines": 200, "regressionTest": True, "secondReview": True}
    assert env["budget"] == {"runsPerDay": 5, "mergesPerDay": 2, "perRun": {"minutes": 60, "invocations": 20, "reruns": 2, "cost": 3}}
    assert env["window"] == {"days": ["mon", "tue", "wed", "thu", "fri"], "from": "09:00", "to": "17:00", "timezone": "UTC"}
    assert env["undoWindow"] == "24h"


def test_a_nested_mapping_is_merged_key_by_key_with_its_defaults_ac_124_4(tmp_path):  # AC-124.4
    """AC-124.4: a nested mapping is merged key by key with its defaults."""
    ok(tmp_path, tiny_auto(dev={"level": "act", "budget": {"perRun": {"cost": 5}}, "riskGate": {"maxLines": 50}}))
    env = auto_json(tmp_path)["environments"]["dev"]
    assert env["budget"]["perRun"] == {"minutes": 60, "invocations": 20, "reruns": 2, "cost": 5}
    assert env["budget"]["runsPerDay"] == 5
    assert env["riskGate"] == {"maxFiles": 5, "maxLines": 50, "regressionTest": True, "secondReview": True}


def test_an_unquoted_time_which_yaml_reads_as_a_number_is_accepted_ac_124_4(tmp_path):  # AC-124.4
    """AC-124.4: an unquoted time which yaml reads as a number is accepted."""
    text = ("system: shop\nowner: acme\nenvironments:\n  dev:\n    host: '{component}.{system}-dev.localhost'\n    autonomy:\n"
            "      level: act\n      window: {from: 09:00, to: 17:00}\n  staging: {}\n  prod: {}\ncomponents:\n"
            "  api: {type: service, lang: python, repo: acme/api, image: ghcr.io/acme/api, port: 8080, "
            "probes: {liveness: /health, readiness: /ready}}\n")
    p = render5(tmp_path / "x", text)
    assert p.returncode == 0, p.stderr
    assert auto_json(tmp_path / "x")["environments"]["dev"]["window"]["from"] == "09:00"
    assert auto_json(tmp_path / "x")["environments"]["dev"]["window"]["to"] == "17:00"


def test_an_overnight_window_is_accepted_ac_124_4(tmp_path):  # AC-124.4
    """AC-124.4: an overnight window is accepted."""
    ok(tmp_path, tiny_auto(dev={"level": "act", "window": {"from": "22:00", "to": "06:00"}}))
    assert auto_json(tmp_path)["environments"]["dev"]["window"]["to"] == "06:00"


# ---------------- AC-124.5: promote stays with the promote rule ----------------

def test_autonomy_does_not_change_the_promotion_rule_ac_124_5(tmp_path):  # AC-124.5
    """AC-124.5: autonomy does not change the promotion rule."""
    ok(tmp_path, tiny_auto(dev={"level": "act"}, staging={"level": "act"}, prod={"level": "act"}))
    envs = auto_json(tmp_path)["environments"]
    assert envs["dev"]["promotion"] == "main" and envs["prod"]["promotion"] == "manual"


def test_a_staging_promote_rule_is_reported_next_to_the_policy_ac_124_5(tmp_path):  # AC-124.5
    """AC-124.5: a staging promote rule is reported next to the policy."""
    doc = tiny_auto(staging={"level": "act"})
    doc["environments"]["staging"]["promote"] = "manual"
    ok(tmp_path, doc)
    assert auto_json(tmp_path)["environments"]["staging"]["promotion"] == "manual"


# ---------------- AC-124.9: autonomy.json ----------------

def test_autonomy_json_is_sorted_two_space_indented_with_a_trailing_newline_ac_124_9(tmp_path):  # AC-124.9
    """AC-124.9: autonomy json is sorted two space indented with a trailing newline."""
    ok(tmp_path, tiny_auto(dev={"level": "act", "engine": DEV_URL}))
    text = (tmp_path / APP / "autonomy.json").read_text()
    doc = json.loads(text)
    assert text == json.dumps(doc, indent=2, sort_keys=True) + "\n"
    assert doc["schema"] == 1 and doc["system"] == "shop" and doc["paused"] is False
    assert set(doc["environments"]) == {"dev", "staging", "prod"}


def test_autonomy_json_carries_the_instances_with_their_effective_level_ac_124_9(tmp_path):  # AC-124.9
    """AC-124.9: autonomy json carries the instances with their effective level."""
    doc = tiny_auto(prod={"level": "act"}, dev={"level": "act"})
    component(doc, "api")["instances"] = {"dev": {}, "prod": {"autonomy": {"max": "propose"}}}
    ok(tmp_path, doc)
    inst = auto_json(tmp_path)["instances"]
    assert inst["api/prod"] == {"max": "propose", "effective": "propose"}
    assert inst["api/dev"]["effective"] == "act"


def test_a_system_with_only_paused_or_an_instance_cap_gets_the_file_ac_124_9(tmp_path):  # AC-124.9
    """AC-124.9: a system with only paused or an instance cap gets the file."""
    doc = tiny()
    doc["autonomy"] = {"paused": False}
    ok(tmp_path / "a", doc)
    assert (tmp_path / "a" / APP / "autonomy.json").is_file()
    doc = tiny()
    component(doc, "api")["instances"] = {"dev": {"autonomy": {"max": "observe"}}}
    ok(tmp_path / "b", doc)
    assert (tmp_path / "b" / APP / "autonomy.json").is_file()


def test_autonomy_json_is_a_managed_file_and_check_notices_a_stale_one_ac_124_9(tmp_path):  # AC-124.9
    """AC-124.9: autonomy json is a managed file and check notices a stale one."""
    ok(tmp_path, tiny_auto(dev={"level": "act"}))
    assert (tmp_path / APP / "autonomy.json").is_file()
    stale = tmp_path / APP / "autonomy.json"
    stale.write_text("{}\n")
    from system_fixtures import render
    check = render(tmp_path, "--check")
    assert check.returncode != 0, "--check must compare autonomy.json"
    ok(tmp_path, tiny())                                  # the autonomy keys are gone: the file goes too
    assert not (tmp_path / APP / "autonomy.json").exists()


def test_a_failed_render_leaves_the_existing_autonomy_json_alone_ac_124_9(tmp_path):  # AC-124.9
    """AC-124.9: a failed render leaves the existing autonomy json alone."""
    ok(tmp_path, tiny_auto(dev={"level": "act"}))
    before = (tmp_path / APP / "autonomy.json").read_text()
    p = render5(tmp_path, tiny_auto(dev={"level": "nope"}))
    assert p.returncode == 1 and (tmp_path / APP / "autonomy.json").read_text() == before


# ---------------- the top-level pause ----------------

def test_the_top_level_autonomy_takes_only_paused_ac_124_7(tmp_path):  # AC-124.7
    """AC-124.7: the top level autonomy takes only paused."""
    doc = tiny()
    doc["autonomy"] = {"paused": True, "level": "act"}
    fails(tmp_path, doc, "autonomy: unknown key 'level' (allowed: paused)")


def test_paused_must_be_true_or_false_ac_124_7(tmp_path):  # AC-124.7
    """AC-124.7: paused must be true or false."""
    doc = tiny()
    doc["autonomy"] = {"paused": "yes please"}
    fails(tmp_path, doc, "autonomy.paused must be true or false")


# ---------------- AC-124.22: the per-component cap ----------------

def test_a_component_may_cap_its_instance_ac_124_22(tmp_path):  # AC-124.22
    """AC-124.22: a component may cap its instance."""
    doc = tiny_auto(prod={"level": "act"})
    component(doc, "api")["instances"] = {"dev": {}, "prod": {"autonomy": {"max": "advise"}}}
    ok(tmp_path, doc)
    assert auto_json(tmp_path)["instances"]["api/prod"] == {"max": "advise", "effective": "advise"}


def test_max_never_raises_an_instance_above_its_environment_ac_124_22(tmp_path):  # AC-124.22
    """AC-124.22: max never raises an instance above its environment."""
    doc = tiny_auto(prod={"level": "advise"})
    component(doc, "api")["instances"] = {"prod": {"autonomy": {"max": "act"}}}
    ok(tmp_path, doc)
    assert auto_json(tmp_path)["instances"]["api/prod"]["effective"] == "advise"


def test_any_other_key_under_a_components_autonomy_names_max_ac_124_22(tmp_path):  # AC-124.22
    """AC-124.22: any other key under a components autonomy names max."""
    doc = tiny()
    component(doc, "api")["instances"] = {"dev": {"autonomy": {"level": "act"}}}
    fails(tmp_path, doc, "components.api.instances.dev.autonomy: unknown key 'level' (allowed: max)")


def test_an_invalid_max_names_the_levels_ac_124_22(tmp_path):  # AC-124.22
    """AC-124.22: an invalid max names the levels."""
    doc = tiny()
    component(doc, "api")["instances"] = {"dev": {"autonomy": {"max": "turbo"}}}
    fails(tmp_path, doc, f"components.api.instances.dev.autonomy.max {LEVEL_ERR}, got 'turbo'")


def test_an_external_component_instance_takes_autonomy_too_ac_124_22(tmp_path):  # AC-124.22
    """AC-124.22: an external component instance takes autonomy too."""
    doc = tiny_auto(dev={"level": "act"})
    doc["components"]["stock"] = {"type": "service", "lang": "unknown", "repo": "acme/stock", "image": "ghcr.io/acme/stock",
                                  "external": {"kustomize": "external/stock"}, "instances": {"dev": {"autonomy": {"max": "propose"}}}}
    ok(tmp_path, doc)
    assert auto_json(tmp_path)["instances"]["stock/dev"] == {"max": "propose", "effective": "propose"}
