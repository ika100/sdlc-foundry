"""Spec 120 acceptance tests, the renderer part: `scale` on service and website components and their instances (AC-120.1 .. .4, .6 .. .16,
.19, .20, .23, .25 .. .28).

Contract: design.md "Contract: system.yaml", "Render errors", "Renderer API", "Contract: rendered documents", "versions table and
operators". The renderer runs as a script in a hand-built checkout (resources_fixtures); nothing touches the network or a cluster.
Criteria that need a cluster (AC-120.10, .12, .14, .15, .19 .. .23 behaviour) are covered by the rendered contract here and by the text
of tests/e2e/run.sh in test_scale_120_cmds.py. Missing symbols are guarded with getattr so each test fails on its own. Domain-like names
are matched with word-bounded regular expressions, never with `"a.b.c" in text`."""
import importlib.util
import re

import pytest
import yaml

from broker_fixtures import ext_comp, lib_comp, wide
from scale_fixtures import (AUTOSCALER_FILES, ENV_KEYS, INSTANCE_KEYS, KEDA, METRICS, ON_FORMS, P, RES, RETRY, SCALE_EXAMPLE, SERVICE_KEYS, cache,
                            cache_system, cpu, db, events, expected_hpa, expected_operator, expected_scaledobject, expected_trigger_auth, files_of,
                            ignore_entry, labels, lag, length, nats_trigger, odir, queue_system, redis_trigger, sdoc, shape, tree_digest)
from resources_fixtures import APP, ENVS, comp, fails, ok, platform_render_module, render5, sets, system, tree, y
from system_fixtures import ROOT, write_system
from test_broker_119 import _before_docs
from broker_fixtures import broker, bsys


def renderer(name="render_120"):
    return platform_render_module(name)


def loaded(tmp_path, doc, name="render_120_load") -> dict:
    return renderer(name).load_system(write_system(tmp_path, doc))


def eff(tmp_path, doc, component="api", env="dev", name="render_120_eff"):
    svc = next(s for s in loaded(tmp_path, doc, name)["services"] if s["name"] == component)
    return svc["_eff"][env]


def component_level(scale, **extra) -> dict:
    return system(None, {"api": comp("api", resources=RES, scale=scale, **extra)})


def instance_level(scale, env="dev") -> dict:
    c = comp("api", resources=RES)
    c["instances"][env] = {"scale": scale}
    return system(None, {"api": c})


def where(level: str) -> str:
    return "components.api.scale" if level == "component" else "components.api.instances.dev.scale"


def doc_at(level: str, scale) -> dict:
    return component_level(scale) if level == "component" else instance_level(scale)


LEVELS = ["component", "instance"]
MAPPING = " must be a mapping with min, max and on, e.g. " + SCALE_EXAMPLE


def apps_of(g) -> list[str]:
    return sorted(k.rsplit("/", 1)[-1] for k in g if k.startswith("operators/apps/"))


def with_answers(tmp_path, doc, **answers) -> dict:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / ".copier-answers.yml").write_text(yaml.safe_dump(answers))
    return ok(tmp_path, doc)


# ---------------- AC-120.1: schema ----------------

@pytest.mark.parametrize("level", LEVELS)
def test_a_full_scale_is_accepted_on_a_component_and_on_an_instance_ac_120_1(tmp_path, level):  # AC-120.1
    ok(tmp_path, doc_at(level, {"min": 2, "max": 6, "on": {"cpu": 70}}))


def test_scale_is_accepted_on_a_website_component_and_its_instances_ac_120_1(tmp_path):  # AC-120.1
    web = comp("web", type="website", lang="typescript", resources=RES, scale=cpu(3))
    web["instances"]["staging"] = {"scale": {"min": 2, "max": 4, "on": {"memory": 60}}}
    g = ok(tmp_path, system(None, {"web": web}))
    assert expected_hpa("web", 1, 3, "cpu", 70) == y(g, f"{odir('dev', 'web')}/hpa.yaml")
    assert expected_hpa("web", 2, 4, "memory", 60) == y(g, f"{odir('staging', 'web')}/hpa.yaml")


def test_min_defaults_to_1_and_the_effective_scale_names_its_source_ac_120_1(tmp_path):  # AC-120.1
    e = eff(tmp_path, sdoc(cpu(5)))
    assert e["scale"] == {"min": 1, "max": 5, "trigger": "cpu", "on": {"cpu": 70}, "source": "component"}


@pytest.mark.parametrize("scale", [{"min": 1, "max": 1, "on": {"cpu": 1}}, {"min": 20, "max": 20, "on": {"memory": 100}},
                                   {"min": 0, "max": 20, "on": {"consumes": "jobs", "lag": 1}}], ids=["smallest", "largest", "zero-to-twenty"])
def test_the_range_boundaries_are_accepted_ac_120_1(tmp_path, scale):  # AC-120.1
    ok(tmp_path, queue_system(scale) if "consumes" in scale["on"] else sdoc(scale))


BAD_STRUCTURE = [
    pytest.param(5, MAPPING, id="int"),
    pytest.param(None, MAPPING, id="null"),
    pytest.param([1, 2], MAPPING, id="list"),
    pytest.param("big", MAPPING, id="string"),
    pytest.param({"max": 5, "on": {"cpu": 70}, "bogus": 1}, ": unknown key 'bogus' (allowed: min, max, on)", id="unknown"),
    pytest.param({"max": 5, "on": {"cpu": 70}, "replicas": 2}, ": unknown key 'replicas' (allowed: min, max, on)", id="replicas-inside"),
    pytest.param({"on": {"cpu": 70}}, ": max is required: an integer from 1 to 20", id="no-max"),
    pytest.param({"min": 1}, ": max is required: an integer from 1 to 20", id="only-min"),
    *[pytest.param({"max": v, "on": {"cpu": 70}}, f".max must be an integer from 1 to 20, got {v}", id=f"max-{v}") for v in (0, 21, -1, True, 2.5)],
    *[pytest.param({"min": v, "max": 5, "on": {"cpu": 70}}, f".min must be an integer from 0 to max (5), got {v}", id=f"min-{v}") for v in (-1, 6, True, 1.5)],
    pytest.param({"max": 5}, f".on is required: exactly one of {ON_FORMS}", id="no-on"),
    pytest.param({"min": 0, "max": 5}, f".on is required: exactly one of {ON_FORMS}", id="no-on-min0"),
]


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("scale, text", BAD_STRUCTURE)
def test_a_malformed_scale_fails_naming_the_key_and_the_range_ac_120_1(tmp_path, level, scale, text):  # AC-120.1
    fails(tmp_path, doc_at(level, scale), P + where(level) + text)


def test_a_string_value_is_printed_in_the_message_ac_120_1(tmp_path):  # AC-120.1
    err = fails(tmp_path, component_level({"max": "x", "on": {"cpu": 70}}), P + "components.api.scale.max must be an integer from 1 to 20, got")
    assert re.search(r"got '?x'?\s*$", err.strip().splitlines()[-1])


def test_the_scale_and_replicas_check_comes_first_ac_120_1(tmp_path):  # AC-120.1
    fails(tmp_path, component_level({"bogus": 1}, replicas=2), P + "components.api: scale and replicas exclude each other")


def test_an_unknown_key_comes_before_a_missing_max_ac_120_1(tmp_path):  # AC-120.1
    fails(tmp_path, component_level({"bogus": 1}), P + "components.api.scale: unknown key 'bogus' (allowed: min, max, on)")


def test_max_is_checked_before_min_and_min_before_on_ac_120_1(tmp_path):  # AC-120.1
    fails(tmp_path, component_level({"min": 9, "max": 0}), P + "components.api.scale.max must be an integer from 1 to 20, got 0")
    fails(tmp_path / "b", component_level({"min": 9, "max": 5}), P + "components.api.scale.min must be an integer from 0 to max (5), got 9")


def test_the_component_level_is_read_before_its_instances_ac_120_1(tmp_path):  # AC-120.1
    c = comp("api", resources=RES, scale={"max": 0, "on": {"cpu": 70}})
    c["instances"]["dev"] = {"scale": {"max": 99, "on": {"cpu": 70}}}
    err = fails(tmp_path, system(None, {"api": c}), P + "components.api.scale.max must be an integer from 1 to 20, got 0")
    assert "instances.dev.scale" not in err


def test_on_is_required_even_though_the_spec_names_only_max_ac_120_1(tmp_path):  # AC-120.1 (design reading: a scale without a trigger has nothing to follow)
    fails(tmp_path, instance_level({"min": 1, "max": 5}), P + f"components.api.instances.dev.scale.on is required: exactly one of {ON_FORMS}")


# ---------------- AC-120.2: component default, whole replacement, replicas ----------------

def test_a_component_scale_applies_to_every_instance_without_scale_or_replicas_ac_120_2(tmp_path):  # AC-120.2
    g = ok(tmp_path, sdoc(cpu(4, min=2)))
    for env in ENVS:
        assert y(g, f"{odir(env)}/hpa.yaml") == expected_hpa("api", 2, 4), env
        assert y(g, f"{odir(env)}/deployment.yaml")["spec"]["replicas"] == 2


def test_an_instance_scale_replaces_the_component_scale_as_a_whole_ac_120_2(tmp_path):  # AC-120.2
    doc = sdoc(cpu(5, min=2), dev={"scale": {"max": 3, "on": {"memory": 60}}})
    g = ok(tmp_path, doc)
    assert y(g, f"{odir('dev')}/hpa.yaml") == expected_hpa("api", 1, 3, "memory", 60), "no key-by-key merge: min is the default 1, not the component's 2"
    assert y(g, f"{odir('staging')}/hpa.yaml") == expected_hpa("api", 2, 5, "cpu", 70)
    assert eff(tmp_path / "x", doc)["scale"] == {"min": 1, "max": 3, "trigger": "memory", "on": {"memory": 60}, "source": "instance"}
    assert eff(tmp_path / "y", doc, env="staging")["scale"]["source"] == "component"


def test_an_instance_replicas_runs_the_fixed_number_without_an_autoscaler_ac_120_2(tmp_path):  # AC-120.2
    doc = sdoc(cpu(5), prod={"replicas": 2})
    g = ok(tmp_path, doc)
    assert files_of(g, "prod") == ["deployment.yaml", "kustomization.yaml", "service.yaml"]
    assert y(g, f"{odir('prod')}/deployment.yaml")["spec"]["replicas"] == 2
    assert "hpa.yaml" in files_of(g, "dev") and "hpa.yaml" in files_of(g, "staging")
    e = eff(tmp_path / "x", doc, env="prod")
    assert e["scale"] is None and e["replicas"] == 2


def test_an_instance_scale_wins_over_a_component_replicas_ac_120_2(tmp_path):  # AC-120.2
    g = ok(tmp_path, sdoc(None, replicas=3, staging={"scale": cpu(4)}))
    assert y(g, f"{odir('staging')}/hpa.yaml") == expected_hpa("api", 1, 4)
    assert "hpa.yaml" not in files_of(g, "dev") and y(g, f"{odir('dev')}/deployment.yaml")["spec"]["replicas"] == 3


def test_a_scaled_instance_has_no_replicas_in_its_effective_settings_ac_120_2(tmp_path):  # AC-120.2
    e = eff(tmp_path, sdoc(cpu(5)))
    assert "replicas" not in e and e["scale"]["max"] == 5


def test_an_unscaled_instance_has_scale_none_in_its_effective_settings_ac_120_2(tmp_path):  # AC-120.2
    e = eff(tmp_path, sdoc(None, replicas=3))
    assert e["scale"] is None and e["replicas"] == 3


# ---------------- AC-120.3: scale and replicas on one level ----------------

EXCLUDE = "scale and replicas exclude each other; remove one (replicas is a fixed number, scale lets the autoscaler choose between min and max)"


def test_scale_and_replicas_on_the_component_fail_naming_both_ac_120_3(tmp_path):  # AC-120.3
    fails(tmp_path, sdoc(cpu(5), replicas=2), P + f"components.api: {EXCLUDE}")


def test_scale_and_replicas_on_one_instance_fail_naming_the_environment_ac_120_3(tmp_path):  # AC-120.3
    fails(tmp_path, sdoc(None, staging={"scale": cpu(5), "replicas": 2}), P + f"components.api.instances.staging: {EXCLUDE}")


def test_the_exclusivity_is_reported_before_the_scale_itself_is_checked_ac_120_3(tmp_path):  # AC-120.3
    c = comp("api", resources=RES, scale={"max": 0}, replicas=1)
    fails(tmp_path / "a", system(None, {"api": c}), P + f"components.api: {EXCLUDE}")
    c = comp("api", resources=RES)
    c["instances"]["dev"] = {"scale": {"max": 0}, "replicas": 1}
    fails(tmp_path / "b", system(None, {"api": c}), P + f"components.api.instances.dev: {EXCLUDE}")


def test_scale_on_the_component_with_replicas_on_an_instance_is_fine_ac_120_3(tmp_path):  # AC-120.3
    ok(tmp_path / "a", sdoc(cpu(5), dev={"replicas": 1}))
    ok(tmp_path / "b", sdoc(None, replicas=2, dev={"scale": cpu(5)}))


# ---------------- AC-120.4: the four trigger forms ----------------

def on_text(where_, got):
    return P + f"{where_}.on must be exactly one of {ON_FORMS}, got {got}"


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("on, got", [
    ({}, "{}"),
    (70, "70"),
    ({"cpu": 70, "memory": 70}, "{cpu, memory}"),
    ({"cpu": 70, "consumes": "jobs", "lag": 10}, "{cpu, consumes, lag}"),
    ({"consumes": "jobs"}, "{consumes}"),
    ({"lag": 10}, "{lag}"),
    ({"consumes": "jobs", "lag": 10, "length": 3}, "{consumes, lag, length}"),
    ({"cache": "sessions", "list": "jobs"}, "{cache, list}"),
    ({"cache": "sessions", "length": 3}, "{cache, length}"),
    ({"cache": "sessions", "list": "jobs", "length": 3, "cpu": 70}, "{cache, list, length, cpu}"),
    ({"cpuu": 70}, "{cpuu}"),
    ({"requests": 70}, "{requests}"),
], ids=["empty", "scalar", "two-triggers", "mixed", "consumes-no-lag", "lag-only", "consumes-lag-length", "cache-no-length", "cache-no-list",
        "cache-four-keys", "unknown", "request-rate"])
def test_an_invalid_trigger_fails_listing_the_four_forms_ac_120_4(tmp_path, level, on, got):  # AC-120.4
    fails(tmp_path, doc_at(level, {"max": 5, "on": on}), on_text(where(level), got))


def test_every_one_of_the_four_forms_is_accepted_ac_120_4(tmp_path):  # AC-120.4
    ok(tmp_path / "cpu", sdoc(cpu(5)))
    ok(tmp_path / "memory", sdoc({"max": 5, "on": {"memory": 70}}))
    ok(tmp_path / "queue", queue_system(lag()))
    ok(tmp_path / "cache", cache_system(length()))


def test_the_form_is_decided_by_the_key_set_not_by_the_key_order_ac_120_4(tmp_path):  # AC-120.4
    ok(tmp_path / "queue", queue_system({"max": 5, "on": {"lag": 10, "consumes": "jobs"}}))
    ok(tmp_path / "cache", cache_system({"max": 5, "on": {"length": 10, "list": "jobs", "cache": "sessions"}}))


def test_the_trigger_of_the_effective_scale_is_named_ac_120_4(tmp_path):  # AC-120.4
    assert eff(tmp_path / "a", sdoc({"max": 5, "on": {"memory": 70}}))["scale"]["trigger"] == "memory"
    assert eff(tmp_path / "b", queue_system(lag()), "worker")["scale"]["trigger"] == "consumes"
    assert eff(tmp_path / "c", cache_system(length()), "worker")["scale"]["trigger"] == "cache"
    assert eff(tmp_path / "d", queue_system(lag()), "worker")["scale"]["on"] == {"consumes": "jobs", "lag": 10}


# ---------------- AC-120.6: cpu and memory ----------------

@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("key, v", [("cpu", v) for v in (0, 101, -5, True, 70.5)] + [("memory", v) for v in (0, 101, True, 12.5)])
def test_a_cpu_or_memory_percent_out_of_range_fails_naming_the_range_ac_120_6(tmp_path, level, key, v):  # AC-120.6
    what = "CPU" if key == "cpu" else "memory"
    fails(tmp_path, doc_at(level, {"max": 5, "on": {key: v}}), P + f"{where(level)}.on.{key} must be an integer from 1 to 100 (percent of the {what} request), got {v}")


def test_cpu_scale_renders_one_horizontal_pod_autoscaler_and_no_keda_object_ac_120_6(tmp_path):  # AC-120.6
    g = ok(tmp_path, sdoc(cpu(5)))
    assert shape(y(g, f"{odir('dev')}/hpa.yaml")) == shape(expected_hpa("api", 1, 5, "cpu", 70))
    assert files_of(g, "dev") == ["deployment.yaml", "hpa.yaml", "kustomization.yaml", "service.yaml"]
    assert not [k for k in g if re.search(r"(scaledobject|triggerauthentication)\.yaml$", k)]
    assert "hpa.yaml" in y(g, f"{odir('dev')}/kustomization.yaml")["resources"]
    assert y(g, f"{odir('dev')}/kustomization.yaml")["resources"] == sorted(y(g, f"{odir('dev')}/kustomization.yaml")["resources"])


def test_memory_scale_renders_a_memory_utilization_target_ac_120_6(tmp_path):  # AC-120.6
    g = ok(tmp_path, sdoc({"min": 2, "max": 4, "on": {"memory": 60}}))
    assert shape(y(g, f"{odir('staging')}/hpa.yaml")) == shape(expected_hpa("api", 2, 4, "memory", 60))


@pytest.mark.parametrize("percent", [1, 100])
def test_the_percent_boundaries_render_ac_120_6(tmp_path, percent):  # AC-120.6
    g = ok(tmp_path, sdoc({"max": 3, "on": {"cpu": percent}}))
    assert y(g, f"{odir('dev')}/hpa.yaml")["spec"]["metrics"][0]["resource"]["target"]["averageUtilization"] == percent


def test_a_scaled_deployment_is_the_fixed_one_with_replicas_min_ac_120_6(tmp_path):  # AC-120.6
    scaled = ok(tmp_path / "a", sdoc({"min": 2, "max": 6, "on": {"cpu": 70}}))
    fixed = ok(tmp_path / "b", sdoc(None, replicas=2))
    for env in ENVS:
        assert scaled[f"{odir(env)}/deployment.yaml"] == fixed[f"{odir(env)}/deployment.yaml"], env
        assert scaled[f"{odir(env)}/service.yaml"] == fixed[f"{odir(env)}/service.yaml"]


def test_the_hpa_is_labelled_like_the_deployment_ac_120_6(tmp_path):  # AC-120.6
    g = ok(tmp_path, sdoc(cpu(5)))
    assert y(g, f"{odir('dev')}/hpa.yaml")["metadata"]["labels"] == y(g, f"{odir('dev')}/deployment.yaml")["metadata"]["labels"] == labels("api")


# ---------------- AC-120.7: the request must exist ----------------

def need_text(env, what, key):
    return P + (f"components.api.instances.{env}: scale on {what} needs a {'CPU' if what == 'cpu' else 'memory'} request; "
                f"set resources.requests.{key} on components.api or on this instance")


def test_a_cpu_trigger_without_a_cpu_request_fails_naming_component_environment_and_request_ac_120_7(tmp_path):  # AC-120.7
    c = comp("api", scale=cpu(5))
    fails(tmp_path / "a", system(None, {"api": c}), need_text("dev", "cpu", "cpu"))
    c = comp("api", scale=cpu(5), resources={"requests": {"memory": "64Mi"}})
    fails(tmp_path / "b", system(None, {"api": c}), need_text("dev", "cpu", "cpu"))
    fails(tmp_path / "c", system(None, {"api": comp("api", scale=cpu(5), resources={"limits": {"cpu": "1"}})}), need_text("dev", "cpu", "cpu"))


def test_a_memory_trigger_without_a_memory_request_fails_ac_120_7(tmp_path):  # AC-120.7
    c = comp("api", scale={"max": 5, "on": {"memory": 70}}, resources={"requests": {"cpu": "100m"}})
    fails(tmp_path, system(None, {"api": c}), need_text("dev", "memory", "memory"))


def test_the_instance_resources_replace_the_component_resources_ac_120_7(tmp_path):  # AC-120.7
    c = comp("api", resources=RES, scale=cpu(5))
    c["instances"]["staging"] = {"resources": {"limits": {"memory": "1Gi"}}}
    fails(tmp_path / "a", system(None, {"api": c}), need_text("staging", "cpu", "cpu"))
    c = comp("api", scale=cpu(5))
    c["instances"]["dev"] = {"resources": RES}
    c["instances"]["staging"] = {"resources": RES}
    c["instances"]["prod"] = {"resources": {"requests": {"memory": "64Mi"}}}
    fails(tmp_path / "b", system(None, {"api": c}), need_text("prod", "cpu", "cpu"))


def test_an_instance_scale_needs_the_request_of_its_own_environment_only_ac_120_7(tmp_path):  # AC-120.7
    c = comp("api")
    c["instances"]["prod"] = {"scale": cpu(5), "resources": RES}
    ok(tmp_path / "a", system(None, {"api": c}))
    c["instances"]["prod"] = {"scale": cpu(5)}
    fails(tmp_path / "b", system(None, {"api": c}), need_text("prod", "cpu", "cpu"))


def test_a_queue_trigger_needs_no_request_ac_120_7(tmp_path):  # AC-120.7
    worker = comp("worker", consumes=["jobs"], scale=lag())
    ok(tmp_path, queue_system(comps={"api": comp("api", provides=["jobs"]), "worker": worker}))


# ---------------- AC-120.8: scale to zero needs a queue ----------------

ZERO = "scale to zero (min: 0) needs a queue trigger (consumes or cache); a {} trigger has nothing to measure at zero replicas"


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("key", ["cpu", "memory"])
def test_min_zero_with_cpu_or_memory_fails_saying_a_queue_trigger_is_needed_ac_120_8(tmp_path, level, key):  # AC-120.8
    fails(tmp_path, doc_at(level, {"min": 0, "max": 5, "on": {key: 70}}), P + f"{where(level)}: {ZERO.format(key)}")


def test_the_range_checks_of_the_trigger_come_before_the_zero_check_ac_120_8(tmp_path):  # AC-120.8
    fails(tmp_path, component_level({"min": 0, "max": 5, "on": {"cpu": 0}}), P + "components.api.scale.on.cpu must be an integer from 1 to 100")


def test_min_zero_with_a_queue_trigger_renders_a_deployment_at_zero_ac_120_8(tmp_path):  # AC-120.8
    g = ok(tmp_path / "q", queue_system(lag(min=0)))
    assert y(g, f"{odir('dev', 'worker')}/deployment.yaml")["spec"]["replicas"] == 0
    g = ok(tmp_path / "c", cache_system(length(min=0)))
    assert y(g, f"{odir('dev', 'worker')}/deployment.yaml")["spec"]["replicas"] == 0


# ---------------- AC-120.9: the consumes trigger ----------------

def ref(where_, text):
    return P + f"{where_}.on.consumes: {text}"


W_SCALE, WI_SCALE = "components.worker.scale", "components.worker.instances.dev.scale"


def test_consumes_must_name_an_api_the_component_consumes_ac_120_9(tmp_path):  # AC-120.9
    doc = queue_system({"max": 5, "on": {"consumes": "audit", "lag": 10}})
    fails(tmp_path, doc, ref(W_SCALE, "worker does not consume 'audit' (consumes: jobs)"))


def test_the_consumed_apis_are_listed_or_none_ac_120_9(tmp_path):  # AC-120.9
    comps = {"api": comp("api", provides=["jobs", "audit"]), "worker": comp("worker", consumes=["jobs", "audit"], resources=RES)}
    comps["worker"]["instances"]["dev"] = {"scale": {"max": 5, "on": {"consumes": "other", "lag": 10}}}
    fails(tmp_path / "a", queue_system(comps=comps, apis=events("jobs", "audit")), ref(WI_SCALE, "worker does not consume 'other' (consumes: jobs, audit)"))
    worker = comp("worker", resources=RES, scale={"max": 5, "on": {"consumes": "jobs", "lag": 10}})
    fails(tmp_path / "b", queue_system(comps={"api": comp("api", provides=["jobs"]), "worker": worker}), ref(W_SCALE, "worker does not consume 'jobs' (consumes: none)"))


def test_only_an_events_api_has_a_queue_ac_120_9(tmp_path):  # AC-120.9
    comps = {"api": comp("api", provides=["jobs", "rest"]), "worker": comp("worker", consumes=["jobs", "rest"], resources=RES,
                                                                              scale={"max": 5, "on": {"consumes": "rest", "lag": 10}})}
    apis = {**events("jobs"), "rest": {"type": "openapi"}}
    fails(tmp_path, queue_system(comps=comps, apis=apis),
          ref(W_SCALE, "'rest' is a openapi API; only an events API carried by a broker has a queue to scale on"))


def test_an_events_api_carried_by_no_broker_is_refused_ac_120_9(tmp_path):  # AC-120.9
    fails(tmp_path, queue_system(lag(), resources={"d": db()}),
          ref(W_SCALE, "the events API 'jobs' is carried by no broker; add one with /resource:add <name> --type broker"))


def test_an_instance_scale_is_named_by_its_instance_path_ac_120_9(tmp_path):  # AC-120.9
    fails(tmp_path, queue_system(None, {"dev": {"scale": {"max": 5, "on": {"consumes": "audit", "lag": 10}}}}),
          ref(WI_SCALE, "worker does not consume 'audit' (consumes: jobs)"))


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("v", [0, -3, True, 1.5])
def test_lag_must_be_an_integer_of_at_least_one_ac_120_9(tmp_path, level, v):  # AC-120.9
    scale = {"max": 5, "on": {"consumes": "jobs", "lag": v}}
    doc = queue_system(scale) if level == "component" else queue_system(None, {"dev": {"scale": scale}})
    fails(tmp_path, doc, P + (W_SCALE if level == "component" else WI_SCALE) + f".on.lag must be an integer of at least 1, got {v}")


def test_an_external_broker_cannot_be_a_trigger_ac_120_9(tmp_path):  # AC-120.9 (design reading: no monitoring endpoint in the external contract)
    fails(tmp_path / "a", queue_system(lag(), resources={"bus": broker(external=True)}),
          P + "components.worker.instances.dev: scale on consumes 'jobs' needs the broker bus in the cluster, but it is external in dev; "
              "the platform cannot read the queue depth of an external broker")
    res = {"bus": broker(instances={"prod": {"external": True}})}
    fails(tmp_path / "b", queue_system(lag(), resources=res),
          P + "components.worker.instances.prod: scale on consumes 'jobs' needs the broker bus in the cluster, but it is external in prod; "
              "the platform cannot read the queue depth of an external broker")


def test_an_instance_that_does_not_run_in_the_external_environment_is_fine_ac_120_9(tmp_path):  # AC-120.9
    worker = comp("worker", consumes=["jobs"], resources=RES, envs=("dev", "staging"), scale=lag())
    ok(tmp_path, queue_system(comps={"api": comp("api", provides=["jobs"]), "worker": worker}, resources={"bus": broker(instances={"prod": {"external": True}})}))


# ---------------- AC-120.11: the cache trigger ----------------

def cref(where_, text):
    return P + f"{where_}.on.cache: {text}"


def test_the_cache_must_be_a_cache_resource_ac_120_11(tmp_path):  # AC-120.11
    scale = {"max": 5, "on": {"cache": "d", "list": "jobs", "length": 10}}
    res = {"sessions": cache(), "d": db()}
    fails(tmp_path / "a", cache_system(scale, resources=res), cref(W_SCALE, "'d' is not a cache resource of the system (caches: sessions)"))
    scale["on"]["cache"] = "nope"
    fails(tmp_path / "b", cache_system(scale, resources={"sessions": cache(), "other": cache()}),
          cref(W_SCALE, "'nope' is not a cache resource of the system (caches: sessions, other)"))
    worker = {**comp("worker", ["d"], resources=RES), "scale": scale}   # spec 120 slip: the worker must use an existing resource, or uses fails first
    fails(tmp_path / "c", system({"d": db()}, {"worker": worker}), cref(W_SCALE, "'nope' is not a cache resource of the system (caches: none)"))


def test_the_cache_must_be_listed_in_uses_ac_120_11(tmp_path):  # AC-120.11
    worker = comp("worker", resources=RES, scale=length())
    fails(tmp_path, system({"sessions": cache()}, {"worker": worker}), cref(W_SCALE, "worker does not use the cache 'sessions'; add it to components.worker.uses"))
    inst = comp("worker", resources=RES)
    inst["instances"]["dev"] = {"scale": length()}
    fails(tmp_path / "b", system({"sessions": cache()}, {"worker": inst}),
          cref(WI_SCALE, "worker does not use the cache 'sessions'; add it to components.worker.uses"))


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("v", [0, -1, True, 2.5])
def test_length_must_be_an_integer_of_at_least_one_ac_120_11(tmp_path, level, v):  # AC-120.11
    scale = {"max": 5, "on": {"cache": "sessions", "list": "jobs", "length": v}}
    doc = cache_system(scale) if level == "component" else cache_system(None, {"dev": {"scale": scale}})
    fails(tmp_path, doc, P + (W_SCALE if level == "component" else WI_SCALE) + f".on.length must be an integer of at least 1, got {v}")


@pytest.mark.parametrize("v", [5, True, 2.5, ["jobs"]])
def test_list_must_be_a_non_empty_string_ac_120_11(tmp_path, v):  # AC-120.11
    scale = {"max": 5, "on": {"cache": "sessions", "list": v, "length": 10}}
    fails(tmp_path, cache_system(scale), P + f"{W_SCALE}.on.list must be a non-empty string: the key of the list in the cache, got {v}")


def test_an_empty_list_name_fails_ac_120_11(tmp_path):  # AC-120.11
    fails(tmp_path, cache_system({"max": 5, "on": {"cache": "sessions", "list": "", "length": 10}}),
          P + f"{W_SCALE}.on.list must be a non-empty string: the key of the list in the cache, got")


def test_the_list_is_checked_before_the_length_ac_120_11(tmp_path):  # AC-120.11
    fails(tmp_path, cache_system({"max": 5, "on": {"cache": "sessions", "list": 5, "length": 0}}), P + f"{W_SCALE}.on.list must be a non-empty string")


def test_a_cache_trigger_on_an_external_cache_is_fine_ac_120_11(tmp_path):  # AC-120.11
    ok(tmp_path, cache_system(length(), resources={"sessions": cache(external=True)}))


# ---------------- AC-120.28: zero replicas cannot answer requests ----------------

ALL_APIS = {**events("jobs", "bus2"), "rest": {"type": "openapi"}, "feed": {"type": "graphql"}, "rpc": {"type": "grpc"}}


def zero_doc(**extra) -> dict:
    """worker consumes jobs and also serves what `extra` says; api provides every other API (each API has exactly one provider)."""
    mine = extra.get("provides", [])
    worker = comp("worker", consumes=["jobs"], resources=RES, **extra)
    api = comp("api", provides=[a for a in ALL_APIS if a not in mine])
    return queue_system(comps={"api": api, "worker": worker}, apis=dict(ALL_APIS))


def zero_text(where_, what, c="worker"):
    return P + f"{where_}: min 0 is not possible for {c}: an instance at zero replicas cannot answer requests ({what})"


ZSCALE = {"min": 0, "max": 5, "on": {"consumes": "jobs", "lag": 10}}


def test_min_zero_is_refused_for_an_exposed_component_naming_the_host_ac_120_28(tmp_path):  # AC-120.28
    fails(tmp_path / "a", zero_doc(scale=ZSCALE, expose={"host": "jobs-ui"}), zero_text(W_SCALE, "exposed at host jobs-ui"))
    fails(tmp_path / "b", zero_doc(scale=ZSCALE, expose=True), zero_text(W_SCALE, "exposed at host worker"))


@pytest.mark.parametrize("provided, what", [(["rest"], "provides rest (openapi)"), (["rest", "feed"], "provides rest (openapi), feed (graphql)"),
                                            (["rpc", "feed", "rest"], "provides rpc (grpc), feed (graphql), rest (openapi)")])
def test_min_zero_is_refused_for_a_provider_of_a_request_api_naming_the_apis_ac_120_28(tmp_path, provided, what):  # AC-120.28
    fails(tmp_path, zero_doc(scale=ZSCALE, provides=provided), zero_text(W_SCALE, what))


def test_exposure_and_apis_are_named_together_ac_120_28(tmp_path):  # AC-120.28
    fails(tmp_path, zero_doc(scale=ZSCALE, expose={"host": "api"}, provides=["rest"]), zero_text(W_SCALE, "exposed at host api; provides rest (openapi)"))


def test_the_instance_level_scale_is_named_by_its_path_ac_120_28(tmp_path):  # AC-120.28
    worker = comp("worker", consumes=["jobs"], resources=RES, expose={"host": "w"})
    worker["instances"]["staging"] = {"scale": ZSCALE}
    fails(tmp_path, queue_system(comps={"api": comp("api", provides=["jobs"]), "worker": worker}),
          zero_text("components.worker.instances.staging.scale", "exposed at host w"))


def test_min_one_is_fine_for_an_exposed_provider_ac_120_28(tmp_path):  # AC-120.28
    ok(tmp_path, zero_doc(scale={"min": 1, "max": 5, "on": {"consumes": "jobs", "lag": 10}}, expose={"host": "w"}, provides=["rest"]))


def test_a_provider_of_an_events_api_may_scale_to_zero_ac_120_28(tmp_path):  # AC-120.28
    g = ok(tmp_path, zero_doc(scale=ZSCALE, provides=["bus2"]))
    assert y(g, f"{odir('dev', 'worker')}/deployment.yaml")["spec"]["replicas"] == 0


# ---------------- AC-120.10 .. .15: the queue documents ----------------

def test_a_consumes_trigger_renders_a_scaledobject_on_the_durable_consumer_ac_120_10(tmp_path):  # AC-120.10
    g = ok(tmp_path, queue_system(lag(10)))
    want = expected_scaledobject(nats_trigger("worker", "jobs", "bus", "dev", 10), "worker", 1, 5)
    assert shape(y(g, f"{odir('dev', 'worker')}/scaledobject.yaml")) == shape(want)
    assert files_of(g, "dev", "worker") == ["deployment.yaml", "kustomization.yaml", "scaledobject.yaml", "service.yaml"]
    assert not [k for k in g if k.endswith("/hpa.yaml")]


def test_the_trigger_reads_the_endpoint_stream_and_consumer_of_the_environment_ac_120_10(tmp_path):  # AC-120.10
    g = ok(tmp_path, queue_system(lag(7, min=2)))
    for env in ENVS:
        so = y(g, f"{odir(env, 'worker')}/scaledobject.yaml")
        assert so["spec"]["triggers"] == [nats_trigger("worker", "jobs", "bus", env, 7)], env
        assert so["spec"]["minReplicaCount"] == 2 and so["spec"]["maxReplicaCount"] == 5


def test_the_trigger_names_the_consumer_and_the_stream_the_broker_creates_ac_120_10(tmp_path):  # AC-120.10
    g = ok(tmp_path, queue_system(lag()))
    consumer = y(g, f"{APP}/addons/dev/bus/consumer-jobs.worker.yaml")["spec"]
    stream = y(g, f"{APP}/addons/dev/bus/stream-jobs.yaml")["spec"]
    meta = y(g, f"{odir('dev', 'worker')}/scaledobject.yaml")["spec"]["triggers"][0]["metadata"]
    assert (meta["stream"], meta["consumer"]) == (consumer["streamName"], consumer["durableName"]) and meta["stream"] == stream["name"]


def test_the_broker_and_api_names_come_from_the_binding_ac_120_10(tmp_path):  # AC-120.10
    res = {"bus": broker(), "queue": broker()}
    doc = queue_system(lag(), resources=res, apis={"jobs": {"type": "events", "broker": "queue"}})
    g = ok(tmp_path, doc)
    meta = y(g, f"{odir('dev', 'worker')}/scaledobject.yaml")["spec"]["triggers"][0]["metadata"]
    assert meta["natsServerMonitoringEndpoint"] == "shop-queue.shop-dev.svc:8222" and meta["stream"] == "shop-jobs"


def test_the_lag_threshold_is_a_string_and_the_max_bounds_the_replicas_ac_120_10(tmp_path):  # AC-120.10
    so = y(ok(tmp_path, queue_system({"min": 1, "max": 5, "on": {"consumes": "jobs", "lag": 10}})), f"{odir('dev', 'worker')}/scaledobject.yaml")
    meta = so["spec"]["triggers"][0]["metadata"]
    assert meta["lagThreshold"] == "10" and all(isinstance(v, str) for v in meta.values())
    assert so["spec"]["maxReplicaCount"] == 5 and so["spec"]["minReplicaCount"] == 1


def test_a_cache_trigger_renders_a_scaledobject_on_the_list_length_ac_120_12(tmp_path):  # AC-120.12
    g = ok(tmp_path, cache_system(length(10, "jobs")))
    want = expected_scaledobject(redis_trigger("worker", "jobs", 10), "worker", 1, 5)
    assert shape(y(g, f"{odir('dev', 'worker')}/scaledobject.yaml")) == shape(want)
    assert files_of(g, "dev", "worker") == ["deployment.yaml", "kustomization.yaml", "scaledobject.yaml", "service.yaml", "triggerauthentication.yaml"]
    assert not [k for k in g if k.endswith("/hpa.yaml")]


def test_the_list_and_length_are_the_declared_ones_ac_120_12(tmp_path):  # AC-120.12
    g = ok(tmp_path, cache_system(length(25, "work:queue", min=0)))
    meta = y(g, f"{odir('staging', 'worker')}/scaledobject.yaml")["spec"]["triggers"][0]["metadata"]
    assert meta == {"listName": "work:queue", "listLength": "25", "activationListLength": "0", "databaseIndex": "0"}


def test_the_scaler_authenticates_with_the_secret_the_instance_reads_ac_120_13(tmp_path):  # AC-120.13
    g = ok(tmp_path, cache_system(length()))
    ta = y(g, f"{odir('dev', 'worker')}/triggerauthentication.yaml")
    assert shape(ta) == shape(expected_trigger_auth("worker", "sessions"))
    deployment = y(g, f"{odir('dev', 'worker')}/deployment.yaml")["spec"]["template"]["spec"]["containers"][0]["env"]
    read = {e["valueFrom"]["secretKeyRef"]["name"] for e in deployment if "valueFrom" in e}
    assert read == {t["name"] for t in ta["spec"]["secretTargetRef"]} == {"shop-sessions-app"}


def test_an_external_cache_is_read_through_the_same_secret_ac_120_13(tmp_path):  # AC-120.13
    g = ok(tmp_path, cache_system(length(), resources={"sessions": cache(external=True)}))
    assert shape(y(g, f"{odir('dev', 'worker')}/triggerauthentication.yaml")) == shape(expected_trigger_auth("worker", "sessions"))


def test_the_secret_follows_the_resource_name_not_a_fixed_name_ac_120_13(tmp_path):  # AC-120.13
    worker = comp("worker", ["store"], resources=RES, scale={"max": 5, "on": {"cache": "store", "list": "q", "length": 3}})
    g = ok(tmp_path, system({"store": cache()}, {"worker": worker}))
    assert shape(y(g, f"{odir('dev', 'worker')}/triggerauthentication.yaml")) == shape(expected_trigger_auth("worker", "store"))


def test_a_broker_trigger_needs_no_credentials_and_renders_no_trigger_authentication_ac_120_13(tmp_path):  # AC-120.13
    g = ok(tmp_path, queue_system(lag()))
    assert not [k for k in g if k.endswith("triggerauthentication.yaml")]
    so = y(g, f"{odir('dev', 'worker')}/scaledobject.yaml")
    assert "authenticationRef" not in so["spec"]["triggers"][0]


def test_no_credential_value_is_rendered_ac_120_13(tmp_path):  # AC-120.13
    g = ok(tmp_path, cache_system(length()))
    base = odir("dev", "worker")
    text = g[f"{base}/scaledobject.yaml"].lower()
    assert "password" not in text and "secret" not in text
    ta = y(g, f"{base}/triggerauthentication.yaml")
    assert all(set(t) == {"parameter", "name", "key"} for t in ta["spec"]["secretTargetRef"])
    assert [t["parameter"] for t in ta["spec"]["secretTargetRef"]] == ["host", "port", "password"]
    q = ok(tmp_path / "q", queue_system(lag()))
    assert "password" not in q[f"{odir('dev', 'worker')}/scaledobject.yaml"].lower()


def test_the_queue_trigger_is_woken_by_one_item_and_polls_every_15_seconds_ac_120_14(tmp_path):  # AC-120.14
    q = y(ok(tmp_path / "q", queue_system(lag(min=0))), f"{odir('dev', 'worker')}/scaledobject.yaml")["spec"]
    c = y(ok(tmp_path / "c", cache_system(length(min=0))), f"{odir('dev', 'worker')}/scaledobject.yaml")["spec"]
    assert q["minReplicaCount"] == 0 and c["minReplicaCount"] == 0
    assert q["triggers"][0]["metadata"]["activationLagThreshold"] == "0" and c["triggers"][0]["metadata"]["activationListLength"] == "0"
    assert q["pollingInterval"] == c["pollingInterval"] == 15 and 15 + 40 <= 60, "one poll plus a pod start of 40 s fits the 60 seconds"


def test_the_timings_give_zero_replicas_five_to_seven_minutes_after_the_queue_empties_ac_120_15(tmp_path):  # AC-120.15
    spec = y(ok(tmp_path, queue_system(lag(min=0))), f"{odir('dev', 'worker')}/scaledobject.yaml")["spec"]
    poll, cooldown = spec["pollingInterval"], spec["cooldownPeriod"]
    assert (poll, cooldown) == (15, 315)
    assert 5 * 60 <= cooldown - poll and cooldown + poll <= 7 * 60, "the last active poll is at most one poll old, the check one poll late"


def test_the_scale_down_window_returns_to_min_within_five_to_seven_minutes_ac_120_15(tmp_path):  # AC-120.15
    spec = y(ok(tmp_path, queue_system(lag(min=1))), f"{odir('dev', 'worker')}/scaledobject.yaml")["spec"]
    down = spec["advanced"]["horizontalPodAutoscalerConfig"]["behavior"]["scaleDown"]
    assert down["stabilizationWindowSeconds"] == 345 and down["policies"] == [{"type": "Percent", "value": 100, "periodSeconds": 15}]
    assert 5 * 60 <= down["stabilizationWindowSeconds"] - spec["pollingInterval"] and down["stabilizationWindowSeconds"] + spec["pollingInterval"] <= 7 * 60


def test_the_scaledobject_syncs_in_wave_one_without_a_dry_run_on_a_missing_crd_ac_120_15(tmp_path):  # AC-120.15
    meta = y(ok(tmp_path, queue_system(lag())), f"{odir('dev', 'worker')}/scaledobject.yaml")["metadata"]
    assert meta["annotations"] == {"argocd.argoproj.io/sync-wave": "1", "argocd.argoproj.io/sync-options": "SkipDryRunOnMissingResource=true"}
    assert list(meta["annotations"]) == ["argocd.argoproj.io/sync-wave", "argocd.argoproj.io/sync-options"]


# ---------------- AC-120.16: autoscaling is derived ----------------

def autoscaling(tmp_path, doc, name="render_120_cfg") -> dict:
    return loaded(tmp_path, doc, name)["cfg"].get("autoscaling")


def test_an_environment_with_a_queue_trigger_derives_keda_ac_120_16(tmp_path):  # AC-120.16
    doc = queue_system(None, {"staging": {"scale": lag()}, "dev": {"replicas": 1}, "prod": {"replicas": 2}})
    assert autoscaling(tmp_path, doc) == {"dev": None, "staging": "keda", "prod": None}


def test_a_cache_trigger_derives_keda_too_ac_120_16(tmp_path):  # AC-120.16
    assert autoscaling(tmp_path, cache_system(length())) == {"dev": "keda", "staging": "keda", "prod": "keda"}


def test_cpu_and_memory_triggers_and_unscaled_systems_derive_null_ac_120_16(tmp_path):  # AC-120.16
    assert autoscaling(tmp_path / "a", sdoc(cpu(5))) == {"dev": None, "staging": None, "prod": None}
    assert autoscaling(tmp_path / "b", sdoc({"max": 3, "on": {"memory": 60}})) == {"dev": None, "staging": None, "prod": None}
    assert autoscaling(tmp_path / "c", sdoc(None, replicas=2)) == {"dev": None, "staging": None, "prod": None}


def test_only_a_running_instance_counts_ac_120_16(tmp_path):  # AC-120.16
    worker = comp("worker", consumes=["jobs"], resources=RES, envs=("dev",), scale=lag())
    doc = queue_system(comps={"api": comp("api", provides=["jobs"]), "worker": worker})
    assert autoscaling(tmp_path, doc) == {"dev": "keda", "staging": None, "prod": None}


def test_one_queue_instance_among_cpu_instances_makes_the_environment_keda_ac_120_16(tmp_path):  # AC-120.16
    comps = {"api": comp("api", provides=["jobs"], resources=RES, scale=cpu(4)),
             "worker": comp("worker", consumes=["jobs"], resources=RES, envs=("staging",), scale=lag())}
    assert autoscaling(tmp_path, queue_system(comps=comps)) == {"dev": None, "staging": "keda", "prod": None}


def test_an_autoscaling_key_under_an_environment_is_an_unknown_key_ac_120_16(tmp_path):  # AC-120.16
    assert autoscaling(tmp_path / "derived", queue_system(lag()))["dev"] == "keda", "the value is derived from the instances"
    doc = queue_system(lag())
    doc["environments"]["dev"]["autoscaling"] = "keda"
    fails(tmp_path, doc, P + f"environments.dev: unknown key 'autoscaling' (allowed: {ENV_KEYS})")


def test_scaled_instances_lists_the_scaled_components_running_in_an_environment_ac_120_16(tmp_path):  # AC-120.16
    comps = {"api": comp("api", provides=["jobs"], resources=RES, scale=cpu(4)), "web": comp("web", resources=RES),
             "worker": comp("worker", consumes=["jobs"], resources=RES, scale=lag(), envs=("dev", "prod"))}
    comps["web"]["instances"]["prod"] = {"scale": cpu(2)}
    r = renderer("render_120_scaled")
    system_ = r.load_system(write_system(tmp_path, queue_system(comps=comps)))
    assert r.scaled_instances(system_["services"], "dev") == ["api", "worker"]
    assert r.scaled_instances(system_["services"], "staging") == ["api"]
    assert r.scaled_instances(system_["services"], "prod") == ["api", "web", "worker"]


def test_scaled_instances_skips_instances_with_a_fixed_count_ac_120_16(tmp_path):  # AC-120.16
    r = renderer("render_120_scaled2")
    system_ = r.load_system(write_system(tmp_path, sdoc(cpu(5), staging={"replicas": 2})))
    assert r.scaled_instances(system_["services"], "staging") == [] and r.scaled_instances(system_["services"], "dev") == ["api"]


# ---------------- AC-120.19: Argo CD leaves the count alone ----------------

def template_spec(g, env):
    return sets(g)[f"shop-{env}"]["spec"]["template"]["spec"]


def test_the_environment_set_ignores_the_replica_count_of_scaled_deployments_ac_120_19(tmp_path):  # AC-120.19
    g = ok(tmp_path, sdoc(cpu(5), staging={"replicas": 2}))
    spec = template_spec(g, "dev")
    assert shape(spec["ignoreDifferences"]) == shape([ignore_entry("api")])
    assert spec["syncPolicy"]["syncOptions"] == ["CreateNamespace=true", "RespectIgnoreDifferences=true"]
    assert list(spec) == ["project", "source", "destination", "syncPolicy", "ignoreDifferences"]
    assert "ignoreDifferences" not in template_spec(g, "staging")
    assert template_spec(g, "staging")["syncPolicy"]["syncOptions"] == ["CreateNamespace=true"]


def test_an_environment_with_a_keda_instance_retries_ac_120_19(tmp_path):  # AC-120.19
    g = ok(tmp_path, queue_system(None, {"dev": {"scale": lag()}}))
    sync = template_spec(g, "dev")["syncPolicy"]
    assert list(sync) == ["automated", "syncOptions", "retry"] and sync["retry"] == RETRY
    assert sync["automated"] == {"prune": True, "selfHeal": True}
    assert "retry" not in template_spec(g, "staging")["syncPolicy"]


def test_an_hpa_only_environment_does_not_retry_ac_120_19(tmp_path):  # AC-120.19
    sync = template_spec(ok(tmp_path, sdoc(cpu(5))), "dev")["syncPolicy"]
    assert list(sync) == ["automated", "syncOptions"] and sync["syncOptions"][-1] == "RespectIgnoreDifferences=true"


def test_one_entry_per_scaled_deployment_in_components_order_ac_120_19(tmp_path):  # AC-120.19
    comps = {"api": comp("api", provides=["jobs"], resources=RES), "zeta": comp("zeta", resources=RES, scale=cpu(3)),
             "worker": comp("worker", consumes=["jobs"], resources=RES, scale=lag())}
    comps["zeta"]["instances"]["staging"] = {"replicas": 1}
    g = ok(tmp_path, queue_system(comps=comps))
    assert shape(template_spec(g, "dev")["ignoreDifferences"]) == shape([ignore_entry("zeta"), ignore_entry("worker")])
    assert shape(template_spec(g, "staging")["ignoreDifferences"]) == shape([ignore_entry("worker")])


def test_the_ignore_rule_needs_neither_replace_nor_prune_last_ac_120_19(tmp_path):  # AC-120.19
    g = ok(tmp_path, queue_system(lag()))
    text = g[f"{APP}/applicationset.yaml"]
    assert "Replace=true" not in text and "PruneLast" not in text


def test_the_scaled_deployment_keeps_replicas_min_for_the_first_sync_ac_120_19(tmp_path):  # AC-120.19
    g = ok(tmp_path, queue_system(lag(min=0), None))
    assert y(g, f"{odir('dev', 'worker')}/deployment.yaml")["spec"]["replicas"] == 0
    g = ok(tmp_path / "b", queue_system(lag(min=3)))
    assert y(g, f"{odir('dev', 'worker')}/deployment.yaml")["spec"]["replicas"] == 3


def test_unscaled_environments_keep_their_application_set_ac_120_19(tmp_path):  # AC-120.19
    plain = ok(tmp_path / "a", system(None, {"api": comp("api", resources=RES)}))
    scaled = ok(tmp_path / "b", sdoc(None, staging={"scale": cpu(5)}))
    p, s = sets(plain), sets(scaled)
    assert p["shop-dev"] == s["shop-dev"] and p["shop-prod"] == s["shop-prod"] and p["shop-staging"] != s["shop-staging"]


# ---------------- AC-120.20: switching ----------------

def render_again(tmp_path, doc):
    p = render5(tmp_path, doc)
    assert p.returncode == 0, p.stdout + p.stderr
    return tree(tmp_path)


def test_switching_from_replicas_to_scale_never_drops_below_the_new_min_ac_120_20(tmp_path):  # AC-120.20
    first = ok(tmp_path, sdoc(None, replicas=4))
    assert y(first, f"{odir('dev')}/deployment.yaml")["spec"]["replicas"] == 4 and "hpa.yaml" not in files_of(first, "dev")
    second = render_again(tmp_path, sdoc({"min": 3, "max": 8, "on": {"cpu": 70}}))
    assert y(second, f"{odir('dev')}/deployment.yaml")["spec"]["replicas"] == 3 and "hpa.yaml" in files_of(second, "dev")


def test_switching_back_to_replicas_removes_the_autoscaler_and_the_ignore_entry_ac_120_20(tmp_path):  # AC-120.20
    first = ok(tmp_path, queue_system(lag()))
    assert "scaledobject.yaml" in files_of(first, "dev", "worker") and "ignoreDifferences" in template_spec(first, "dev")
    second = render_again(tmp_path, queue_system(None, {e: {"replicas": 2} for e in ENVS}))
    for env in ENVS:
        assert files_of(second, env, "worker") == ["deployment.yaml", "kustomization.yaml", "service.yaml"], env
        assert y(second, f"{odir(env, 'worker')}/deployment.yaml")["spec"]["replicas"] == 2
        assert "ignoreDifferences" not in template_spec(second, env)
        assert "RespectIgnoreDifferences=true" not in template_spec(second, env)["syncPolicy"]["syncOptions"]
        assert not [r for r in y(second, f"{odir(env, 'worker')}/kustomization.yaml")["resources"] if r in AUTOSCALER_FILES]


def test_a_cache_trigger_loses_its_trigger_authentication_with_the_scale_ac_120_20(tmp_path):  # AC-120.20
    first = ok(tmp_path, cache_system(length()))
    assert "triggerauthentication.yaml" in files_of(first, "dev", "worker")
    second = render_again(tmp_path, cache_system(None))
    assert not [k for k in second if k.endswith(AUTOSCALER_FILES)]


def test_switching_between_cpu_and_a_queue_swaps_the_autoscaler_files_ac_120_20(tmp_path):  # AC-120.20
    first = ok(tmp_path, queue_system(None, {"dev": {"scale": lag()}}, comps=None))
    assert "scaledobject.yaml" in files_of(first, "dev", "worker")
    comps = {"api": comp("api", provides=["jobs"]), "worker": comp("worker", consumes=["jobs"], resources=RES, scale=cpu(4))}
    second = render_again(tmp_path, queue_system(comps=comps))
    assert "hpa.yaml" in files_of(second, "dev", "worker") and "scaledobject.yaml" not in files_of(second, "dev", "worker")
    assert "retry" not in template_spec(second, "dev")["syncPolicy"]
    third = render_again(tmp_path, queue_system(lag()))
    assert "scaledobject.yaml" in files_of(third, "dev", "worker") and "hpa.yaml" not in files_of(third, "dev", "worker")


def test_the_autoscaler_objects_are_ordered_so_that_a_switch_prunes_the_old_autoscaler_first_ac_120_20(tmp_path):  # AC-120.20
    so = y(ok(tmp_path, queue_system(lag())), f"{odir('dev', 'worker')}/scaledobject.yaml")["metadata"]["annotations"]
    assert so["argocd.argoproj.io/sync-wave"] == "1"
    hpa = y(ok(tmp_path / "h", sdoc(cpu(5))), f"{odir('dev')}/hpa.yaml")["metadata"]
    assert "annotations" not in hpa, "the HPA is in the default wave 0, pruned or created before the ScaledObject"


# ---------------- AC-120.23: the end-to-end system ----------------

def test_the_e2e_system_renders_the_scaled_consumer_and_its_ignore_rule_ac_120_23(tmp_path):  # AC-120.23
    worker = comp("e2e-worker", ["sessions"], consumes=["jobs"], resources=RES, port=8080)
    worker["instances"] = {"dev": {"scale": {"min": 0, "max": 5, "on": {"consumes": "jobs", "lag": 10}}}}
    doc = system({"bus": broker(), "sessions": cache()}, {"e2e-api": comp("e2e-api", provides=["jobs"], envs=("dev",)), "e2e-worker": worker}, apis=events("jobs"))
    doc["system"] = "shop"
    g = ok(tmp_path, doc)
    base = odir("dev", "e2e-worker")
    assert shape(y(g, f"{base}/scaledobject.yaml")) == shape(expected_scaledobject(nats_trigger("e2e-worker", "jobs", "bus", "dev", 10), "e2e-worker", 0, 5))
    assert y(g, f"{base}/deployment.yaml")["spec"]["replicas"] == 0
    assert shape(template_spec(g, "dev")["ignoreDifferences"]) == shape([ignore_entry("e2e-worker")])
    assert template_spec(g, "dev")["syncPolicy"]["syncOptions"][-1] == "RespectIgnoreDifferences=true" and template_spec(g, "dev")["syncPolicy"]["retry"] == RETRY
    assert apps_of(g) == ["keda.yaml", "nack.yaml"]


# ---------------- AC-120.25 / .27 / .17: operators ----------------

def test_keda_and_metrics_server_are_pinned_in_the_versions_table_ac_120_25(tmp_path):  # AC-120.25
    r = renderer("render_120_table")
    assert r.OPERATORS.get("keda") == KEDA and r.OPERATORS.get("metrics-server") == METRICS
    assert list(r.OPERATORS)[-3:] == ["nack", "keda", "metrics-server"]
    assert r.OPERATOR_OF_TYPE == {"database": "cloudnative-pg", "bucket": "seaweedfs", "broker": "nack"}


def test_every_pin_is_an_exact_version_no_range_no_latest_ac_120_25(tmp_path):  # AC-120.25
    r = renderer("render_120_exact")
    for name in ("keda", "metrics-server"):
        op = r.OPERATORS[name]
        assert re.fullmatch(r"v?\d+\.\d+\.\d+", op["chart_version"]) and re.fullmatch(r"\d+\.\d+\.\d+", op["operator_version"]), name
        assert not re.search(r"latest|[\^~*<>=x]", op["chart_version"]), name


def test_the_cluster_repo_copy_of_the_renderer_has_the_same_pins_ac_120_25(tmp_path):  # AC-120.25
    path = ROOT / "templates" / "cluster-gitops" / "scripts" / "system_render.py"
    spec = importlib.util.spec_from_file_location("system_render_120", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert m.OPERATORS.get("keda") == KEDA and m.OPERATORS.get("metrics-server") == METRICS
    assert hasattr(m, "scaled_instances")


def test_the_application_is_the_one_the_operator_builder_makes_and_pins_the_table_ac_120_25(tmp_path):  # AC-120.25
    g = ok(tmp_path, cache_system(length()))
    r = renderer("render_120_app")
    got = yaml.safe_load(g["operators/apps/keda.yaml"])
    assert got == expected_operator(KEDA) and got == r.operator_application("keda", "https://kubernetes.default.svc")
    assert shape(got) == shape(expected_operator(KEDA))
    assert got["spec"]["source"]["targetRevision"] == "2.19.0" and "retry" not in got["spec"]["syncPolicy"]


def test_a_queue_instance_installs_keda_once_per_cluster_ac_120_27(tmp_path):  # AC-120.27
    g = ok(tmp_path, cache_system(length()))
    assert apps_of(g) == ["keda.yaml"] and "operators/root.yaml" in g
    assert yaml.safe_load(g["operators/root.yaml"])["spec"]["source"]["path"] == "operators/apps"


def test_several_keda_environments_still_render_one_application_ac_120_27(tmp_path):  # AC-120.27
    doc = cache_system(length())
    assert autoscaling(tmp_path / "l", doc) == {"dev": "keda", "staging": "keda", "prod": "keda"}
    g = ok(tmp_path, doc)
    assert [k for k in g if re.search(r"keda", k)] == ["operators/apps/keda.yaml"]


def test_no_keda_application_without_a_queue_trigger_ac_120_27(tmp_path):  # AC-120.27
    assert not [k for k in ok(tmp_path / "a", sdoc(cpu(5))) if k.startswith("operators/")]
    assert not [k for k in ok(tmp_path / "b", system(None, {"api": comp("api")})) if k.startswith("operators/")]
    assert apps_of(ok(tmp_path / "c", queue_system(None, {"dev": {"replicas": 1}, "staging": {"replicas": 1}, "prod": {"replicas": 1}}))) == ["nack.yaml"]


def test_environments_that_own_their_operators_get_no_keda_application_ac_120_27(tmp_path):  # AC-120.27
    doc = cache_system(length())
    for e in ENVS:
        doc["environments"][e]["operators"] = "owner"
    g = ok(tmp_path, doc)
    assert not [k for k in g if k.startswith("operators/")]
    assert loaded(tmp_path / "l", doc)["cfg"]["autoscaling"] == {"dev": "keda", "staging": "keda", "prod": "keda"}, "the need is still derived"


def test_keda_is_installed_while_one_keda_environment_is_not_owner_managed_ac_120_27(tmp_path):  # AC-120.27
    doc = cache_system(length())
    doc["environments"]["dev"]["operators"] = "owner"
    doc["environments"]["staging"]["operators"] = "owner"
    assert apps_of(ok(tmp_path, doc)) == ["keda.yaml"]


def test_metrics_server_is_rendered_only_for_the_install_answer_and_a_cpu_or_memory_instance_ac_120_27(tmp_path):  # AC-120.27
    cpu_doc = sdoc(cpu(5))
    g = with_answers(tmp_path / "a", cpu_doc, resource_metrics="install")
    assert apps_of(g) == ["metrics-server.yaml"]
    assert yaml.safe_load(g["operators/apps/metrics-server.yaml"]) == expected_operator(METRICS)
    assert shape(yaml.safe_load(g["operators/apps/metrics-server.yaml"])) == shape(expected_operator(METRICS))
    assert apps_of(with_answers(tmp_path / "b", sdoc({"max": 3, "on": {"memory": 50}}), resource_metrics="install")) == ["metrics-server.yaml"]
    assert not [k for k in with_answers(tmp_path / "c", cpu_doc, resource_metrics="provided") if k.startswith("operators/")]
    assert not [k for k in ok(tmp_path / "d", cpu_doc) if k.startswith("operators/")], "a repo without the answer means provided"
    assert not [k for k in with_answers(tmp_path / "e", sdoc(None, replicas=2), resource_metrics="install") if k.startswith("operators/")]
    assert apps_of(with_answers(tmp_path / "f", cache_system(length()), resource_metrics="install")) == ["keda.yaml"]


def test_metrics_server_is_not_installed_into_an_owner_managed_environment_ac_120_27(tmp_path):  # AC-120.27
    doc = sdoc(None, dev={"scale": cpu(5)})
    doc["environments"]["dev"]["operators"] = "owner"
    assert not [k for k in with_answers(tmp_path / "a", doc, resource_metrics="install") if k.startswith("operators/")]
    doc["environments"]["dev"].pop("operators")
    assert apps_of(with_answers(tmp_path / "b", doc, resource_metrics="install")) == ["metrics-server.yaml"]


def test_keda_and_metrics_server_come_in_the_order_of_the_table_ac_120_27(tmp_path):  # AC-120.27
    comps = {"api": comp("api", resources=RES, scale=cpu(3)), "worker": comp("worker", ["sessions"], resources=RES, scale=length())}
    g = with_answers(tmp_path, system({"sessions": cache()}, comps), resource_metrics="install")
    assert apps_of(g) == ["keda.yaml", "metrics-server.yaml"]


def test_the_render_half_of_the_local_cluster_files_exists_exactly_when_keda_is_derived_ac_120_17(tmp_path):  # AC-120.17
    assert "operators/apps/keda.yaml" in ok(tmp_path / "a", queue_system(lag()))
    assert "operators/apps/keda.yaml" not in ok(tmp_path / "b", queue_system(None, {e: {"replicas": 1} for e in ENVS}))


# ---------------- AC-120.26: additive ----------------

def test_scale_is_the_last_key_of_both_lists_ac_120_26(tmp_path):  # AC-120.26
    r = renderer("render_120_keys")
    assert r.SERVICE_KEYS[-1] == "scale" and ", ".join(r.SERVICE_KEYS) == SERVICE_KEYS
    assert ", ".join(r.INSTANCE_KEYS) == INSTANCE_KEYS
    assert "scale" not in r.EXTERNAL_KEYS and "scale" not in r.LIBRARY_KEYS and "scale" not in r.ENV_KEYS


def test_every_other_unknown_key_still_fails_with_the_extended_lists_ac_120_26(tmp_path):  # AC-120.26
    fails(tmp_path / "a", system(None, {"api": comp("api", bogus=1)}), P + f"components.api: unknown key 'bogus' (allowed: {SERVICE_KEYS})")
    c = comp("api")
    c["instances"]["dev"] = {"bogus": 1}
    fails(tmp_path / "b", system(None, {"api": c}), P + f"components.api.instances.dev: unknown key 'bogus' (allowed: {INSTANCE_KEYS})")


def test_a_library_an_external_component_and_its_instance_still_refuse_scale_ac_120_26(tmp_path):  # AC-120.26
    ok(tmp_path / "service", sdoc(cpu(3)))      # a service takes it
    fails(tmp_path / "a", system(None, {"lib": lib_comp("lib", scale=cpu(3))}), P + "components.lib: unknown key 'scale' (allowed: type, lang, repo, provides, consumes)")
    fails(tmp_path / "b", system(None, {"stock": ext_comp("stock", scale=cpu(3))}), P + "components.stock is external: scale belongs in its package, not in system.yaml")
    ext = ext_comp("stock")
    ext["instances"]["dev"] = {"scale": cpu(3)}
    fails(tmp_path / "c", system(None, {"stock": ext}), P + "components.stock.instances.dev: unknown key 'scale' (allowed: promote, autonomy)")


def test_an_environment_without_scale_changes_nothing_next_to_one_with_it_ac_120_26(tmp_path):  # AC-120.26
    plain = ok(tmp_path / "a", system(None, {"api": comp("api", resources=RES), "web": comp("web", resources=RES)}))
    one = ok(tmp_path / "b", system(None, {"api": comp("api", resources=RES, scale=cpu(3)), "web": comp("web", resources=RES)}))
    assert {k: v for k, v in plain.items() if "/web/" in k} == {k: v for k, v in one.items() if "/web/" in k}


BEFORE_120 = {"full5": ("bf4c5ffc245db1166768f726cdbf9b29618a050bfed682499ad3a4de22037cb4", 58),
              "rich5": ("54e93234734051c4df2494a3383b27954e5eeeaeaf58d76c10c545562b403cae", 58),
              "db-bucket": ("db23d5c3c8f752510fee7396f719342b8706b13370c0ffa997fbd48f15cdc9ed", 50),
              "cache": ("c5b6a29786bb58cb84e281c6a0fab65cce0862dfbc45bf61a0ca59e802587077", 40),
              "events": ("9fe3842825e291f58f1e33aac03f53edf98df7c9053eefbeae7882d3ad3f57e4", 26),
              "events-multi": ("32cf57fc7f192b4e17858f16716f6a82553103c51173c9e45e1d5b28c2d779e7", 61),
              "broker": ("22a18e5cb8bd47fdfa8288a09efdef76feb5a73ae99acbba664bac9ae7e91fad", 55),
              "broker-wide": ("ebc671dd740f12dfcdf9b4ef9fb4f389d01f8d5148f00c441fd81b416d82a2f6", 76),
              "broker-ext": ("f552152670af57260faddf29750116121f184baa8d535c57b48330e234546ba2", 48),
              "expose-openapi": ("8e44481de7f03dce36be3bc90398e7f3f610bb60c578eb1373d9eb4fa77b85ab", 35)}   # taken from the renderer before spec 120


def _before_120_docs() -> dict:
    docs = dict(_before_docs())
    docs["broker"] = bsys()
    docs["broker-wide"] = wide()
    docs["broker-ext"] = bsys({"bus": broker(instances={"prod": {"external": True}}), "d": db()})
    docs["expose-openapi"] = system({"d": db()}, {"api": comp("api", ["d"], expose={"host": "api"}, provides=["rest"], replicas=2),
                                                    "web": comp("web", consumes=["rest"], resources={"requests": {"cpu": "100m"}})}, apis={"rest": {"type": "openapi"}})
    return docs


@pytest.mark.parametrize("label", list(BEFORE_120))
def test_a_5x_system_without_scale_renders_byte_identically_to_before_ac_120_26(tmp_path, label):  # AC-120.26
    g = ok(tmp_path, _before_120_docs()[label])
    digest, count = BEFORE_120[label]
    assert (len(g), tree_digest(g)) == (count, digest), f"{label}: the render changed although the system has no scale"


def test_no_autoscaler_file_and_no_ignore_rule_appear_without_scale_ac_120_26(tmp_path):  # AC-120.26
    with_scale = ok(tmp_path / "with", sdoc(cpu(5)))
    assert [k for k in with_scale if k.endswith("/hpa.yaml")], "the same renderer does write them for a scaled instance"
    for label, doc in _before_120_docs().items():
        g = ok(tmp_path / label, doc)
        assert not [k for k in g if k.endswith(AUTOSCALER_FILES)], label
        assert "ignoreDifferences" not in g[f"{APP}/applicationset.yaml"] and "RespectIgnoreDifferences" not in g[f"{APP}/applicationset.yaml"], label
        assert "operators/apps/keda.yaml" not in g and "operators/apps/metrics-server.yaml" not in g, label


def test_an_unquoted_on_key_is_read_as_on_ac_120_1(tmp_path):  # AC-120.1
    # YAML 1.1 reads `on:` as true; people write it unquoted
    text = yaml.safe_dump(cache_system({"max": 4, "on": {"cpu": 70}}), sort_keys=False).replace("'on':", "on:")
    assert "'on'" not in text
    doc = yaml.safe_load(text)
    assert True in doc["components"]["worker"]["scale"]
    ok(tmp_path, doc)


@pytest.mark.parametrize("mangle, needle", [
    (lambda d: d.update(components=["worker"]), "must be a mapping"),
    (lambda d: d["components"]["worker"].update(instances=["dev"]), "instances"),
])
def test_a_malformed_tree_still_fails_with_its_own_message_ac_120_26(tmp_path, mangle, needle):  # AC-120.26
    # spec 120 review: reading an unquoted `on:` must not crash on a non-mapping components or instances
    doc = cache_system({"max": 4, "on": {"cpu": 70}})
    mangle(doc)
    err = fails(tmp_path, doc)
    assert needle in err and "Traceback" not in err
