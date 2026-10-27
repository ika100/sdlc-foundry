"""Spec 124 acceptance tests: `cplat model show` reports the declared and effective autonomy (AC-124.1, AC-124.2, AC-124.4, AC-124.5,
AC-124.9, AC-124.22).

Contract: design.md "`cplat model show --json` additions". Run through `cplat.main` on a hand-built checkout; the equality test with
`autonomy.json` renders the same checkout with the real renderer."""
import json

import cplat
from autonomy_support import APP, DEV_URL, PROD_URL, component, read_json, rich_auto, tiny, tiny_auto
from system_fixtures import render5, write_system

LEVELS = ["observe", "advise", "propose", "act", "improve"]


def show(root, capsys, *args):
    rc = cplat.main(["model", "show", *args, "--repo-dir", str(root)])
    cap = capsys.readouterr()
    assert rc == 0, cap.err
    return cap.out


def doc(root, capsys):
    return json.loads(show(root, capsys, "--json"))


def env_of(d, name):
    return next(e for e in d["environments"] if e["name"] == name)


def inst_of(d, comp, env):
    return next(i for i in d["instances"] if i["component"] == comp and i["environment"] == env)


def test_the_json_always_carries_the_autonomy_keys_even_without_autonomy_ac_124_1(tmp_path, capsys):  # AC-124.1
    """AC-124.1: the json always carries the autonomy keys even without autonomy."""
    write_system(tmp_path, tiny())
    d = doc(tmp_path, capsys)
    assert d["schema"] == 2
    assert d["autonomy"] == {"paused": False, "levels": LEVELS}
    for name in ("dev", "staging", "prod"):
        a = env_of(d, name)["autonomy"]
        assert a["declared"] == "observe" and a["effective"] == "observe" and a["paused"] is False and a["engine"] is None
    assert all("autonomy" in i for i in d["instances"])


def test_each_environment_reports_level_and_guardrails_ac_124_2(tmp_path, capsys):  # AC-124.2
    """AC-124.2: each environment reports level and guardrails."""
    write_system(tmp_path, tiny_auto(dev={"level": "propose", "engine": DEV_URL, "riskGate": {"maxLines": 50}}))
    a = env_of(doc(tmp_path, capsys), "dev")["autonomy"]
    assert a["declared"] == "propose" and a["effective"] == "propose" and a["engine"] == DEV_URL
    assert a["riskGate"]["maxLines"] == 50 and a["riskGate"]["maxFiles"] == 5
    assert a["cap"] == "improve" and env_of(doc(tmp_path, capsys), "prod")["autonomy"]["cap"] == "act"


def test_improve_is_declared_improve_and_effective_act_ac_124_2(tmp_path, capsys):  # AC-124.2
    """AC-124.2: improve is declared improve and effective act."""
    write_system(tmp_path, tiny_auto(staging={"level": "improve"}))
    a = env_of(doc(tmp_path, capsys), "staging")["autonomy"]
    assert (a["declared"], a["effective"]) == ("improve", "act")


def test_a_paused_system_reports_paused_and_effective_observe_ac_124_2(tmp_path, capsys):  # AC-124.2
    """AC-124.2: a paused system reports paused and effective observe."""
    d0 = tiny_auto(dev={"level": "act"})
    d0["autonomy"] = {"paused": True}
    write_system(tmp_path, d0)
    d = doc(tmp_path, capsys)
    assert d["autonomy"]["paused"] is True
    a = env_of(d, "dev")["autonomy"]
    assert (a["declared"], a["effective"], a["paused"]) == ("act", "observe", True)


def test_the_effective_guardrail_values_include_the_defaults_ac_124_4(tmp_path, capsys):  # AC-124.4
    """AC-124.4: the effective guardrail values include the defaults."""
    write_system(tmp_path, tiny_auto(dev={"level": "act", "budget": {"perRun": {"cost": 5}}}))
    a = env_of(doc(tmp_path, capsys), "dev")["autonomy"]
    assert a["autoMerge"] == {"routes": ["fix"], "maxCriticality": "low"}
    assert a["riskGate"] == {"maxFiles": 5, "maxLines": 200, "regressionTest": True, "secondReview": True}
    assert a["budget"] == {"runsPerDay": 5, "mergesPerDay": 2, "perRun": {"minutes": 60, "invocations": 20, "reruns": 2, "cost": 5}}
    assert a["window"] == {"days": ["mon", "tue", "wed", "thu", "fri"], "from": "09:00", "to": "17:00", "timezone": "UTC"}
    assert a["undoWindow"] == "24h"


def test_the_promotion_rule_is_reported_and_autonomy_does_not_change_it_ac_124_5(tmp_path, capsys):  # AC-124.5
    """AC-124.5: the promotion rule is reported and autonomy does not change it."""
    write_system(tmp_path, tiny_auto(dev={"level": "act"}, staging={"level": "act"}, prod={"level": "act"}))
    d = doc(tmp_path, capsys)
    assert env_of(d, "dev")["autonomy"]["promotion"] == "main"
    assert env_of(d, "prod")["autonomy"]["promotion"] == "manual"
    assert env_of(d, "prod")["promote"] == "manual", "the existing key keeps its meaning"


def test_each_instance_reports_its_cap_and_effective_level_ac_124_22(tmp_path, capsys):  # AC-124.22
    """AC-124.22: each instance reports its cap and effective level."""
    d0 = tiny_auto(dev={"level": "act"}, prod={"level": "act"})
    component(d0, "api")["instances"] = {"dev": {}, "prod": {"autonomy": {"max": "propose"}}}
    write_system(tmp_path, d0)
    d = doc(tmp_path, capsys)
    assert inst_of(d, "api", "prod")["autonomy"] == {"max": "propose", "effective": "propose"}
    assert inst_of(d, "api", "dev")["autonomy"]["effective"] == "act" and inst_of(d, "api", "dev")["autonomy"].get("max") is None


def test_the_text_output_names_the_level_the_effective_level_and_the_engine_ac_124_2(tmp_path, capsys):  # AC-124.2
    """AC-124.2: the text output names the level the effective level and the engine."""
    d0 = tiny_auto(dev={"level": "improve", "engine": DEV_URL}, prod={"level": "act"})
    component(d0, "api")["instances"] = {"dev": {}, "prod": {"autonomy": {"max": "advise"}}}
    write_system(tmp_path, d0)
    out = show(tmp_path, capsys)
    assert f"autonomy improve (effective act) engine {DEV_URL}" in out
    assert "autonomy act engine -" in out
    assert "autonomy max advise (effective advise)" in out


def test_autonomy_json_equals_the_model_report_ac_124_9(tmp_path, capsys):  # AC-124.9
    """AC-124.9: autonomy json equals the model report."""
    d0 = rich_auto(dev={"level": "improve", "engine": DEV_URL, "window": {"timezone": "Europe/Berlin"}},
                   staging={"level": "propose", "riskGate": {"maxFiles": 2}}, prod={"level": "act", "engine": PROD_URL})
    component(d0, "shop-api")["instances"]["prod"]["autonomy"] = {"max": "propose"}
    p = render5(tmp_path, d0)
    assert p.returncode == 0, p.stderr
    d = doc(tmp_path, capsys)
    aj = read_json(tmp_path / APP / "autonomy.json")
    assert set(aj["environments"]) == {"dev", "staging", "prod"}
    for e in d["environments"]:
        assert aj["environments"][e["name"]] == e["autonomy"], e["name"]
    for i in d["instances"]:
        if i["component"] == "shop-lib":
            continue
        assert aj["instances"][f"{i['component']}/{i['environment']}"] == i["autonomy"], i
    assert aj["paused"] == d["autonomy"]["paused"] and aj["levels"] == d["autonomy"]["levels"]


def test_autonomy_json_equals_the_model_report_when_paused_ac_124_9(tmp_path, capsys):  # AC-124.9
    """AC-124.9: autonomy json equals the model report when paused."""
    d0 = tiny_auto(dev={"level": "act"})
    d0["autonomy"] = {"paused": True}
    assert render5(tmp_path, d0).returncode == 0
    d = doc(tmp_path, capsys)
    aj = read_json(tmp_path / APP / "autonomy.json")
    assert aj["environments"]["dev"] == env_of(d, "dev")["autonomy"] and aj["paused"] is True
