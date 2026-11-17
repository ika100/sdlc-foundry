"""Spec 110 acceptance tests, AC-110.5, AC-110.8 and AC-110.10 for the service-python provider check (design 4).

copier is not part of the platform's test-fast environment, so `scripts/contract_pytest.py` is rendered with its one Jinja
variable replaced and loaded by path; the app under test is a plain function `send(endpoint, body) -> (status, body)`, the same
shape as the engine's `contract_send` fixture. The copy is written by `support_110` (or by `cplat spec new --from-plan`)."""
import importlib.util
import json
import re
import sys
import types

import pytest
from support_110 import ROOT, commit_all, contract_text, copy_doc, mutated, plan_file, plan_text, world, write_copy

import spec

TEMPLATE = ROOT / "templates" / "service-python"
ENGINE = TEMPLATE / "scripts" / "contract_pytest.py"
PLAN = "003-todos"


def engine():
    assert ENGINE.is_file(), "missing template file: templates/service-python/scripts/contract_pytest.py"
    source = ENGINE.read_text()
    source = re.sub(r"\{%-?\s*if\b.*?%\}(.*?)\{%-?\s*else\s*-?%\}.*?\{%-?\s*endif\s*-?%\}", r"\1", source, flags=re.S)  # first branch
    source = re.sub(r"\{%.*?%\}", "", source, flags=re.S)
    source = re.sub(r"\{\{\s*module_name\s*\}\}", "demo_app", source)
    if "fastapi" not in sys.modules and importlib.util.find_spec("fastapi") is None:       # the default fixtures import it; the engine under test does not need it
        for name in ("fastapi", "fastapi.testclient"):
            sys.modules.setdefault(name, types.ModuleType(name))
        sys.modules["fastapi.testclient"].TestClient = object
    sys.modules.setdefault("demo_app", types.ModuleType("demo_app"))
    sys.modules.setdefault("demo_app.main", types.SimpleNamespace(app=object()))
    module = types.ModuleType("contract_pytest_110")
    module.__file__ = str(ENGINE)
    sys.modules["contract_pytest_110"] = module
    exec(compile(source, str(ENGINE), "exec"), module.__dict__)   # noqa: S102 (a template file of this repository)
    return module


def base(endpoint):
    return {"title": "x", "status": "open"}


def app(title_max=200, status=422, field_key="field", listed=True):
    """A small API that follows the contract (or, with the knobs, does not)."""
    def send(endpoint, body):
        found = None
        if endpoint == "POST /todos":
            title = body.get("title")
            if title is None:
                found = ("title", "title-required")
            elif len(title) > title_max:
                found = ("title", "title-max")
        if endpoint == "PATCH /todos/{id}" and body.get("status") not in ("open", "done"):
            found = ("status", "status-values")
        if not found:
            return 200, {}
        error = {field_key: found[0], "rule": found[1], "message": f"{found[1]} violated"}
        return status, {"errors": [error]} if listed else error
    return send


@pytest.fixture()
def provider(tmp_path):
    root = tmp_path / "todo-api"
    root.mkdir()
    write_copy(root, copy_doc("todo-api", "provider"))
    return root


def failure(case, send, mod):
    with pytest.raises(AssertionError) as err:
        mod.check_case(case, send, base)
    return str(err.value)


def by_id(mod, root):
    return {str(c): c for c in mod.contract_cases(root)}


def test_the_cases_are_derived_from_the_provider_rules_of_the_copy_ac_110_5(provider):  # AC-110.5
    mod = engine()
    assert sorted(by_id(mod, provider)) == sorted([
        f"{PLAN}:title-max:at-limit", f"{PLAN}:title-max:past-limit",
        f"{PLAN}:title-required:present", f"{PLAN}:title-required:missing",
        f"{PLAN}:status-values:allowed=open", f"{PLAN}:status-values:allowed=done", f"{PLAN}:status-values:not-allowed"])


def test_consumer_rules_and_a_missing_copy_give_no_cases_ac_110_5(tmp_path, provider):  # AC-110.5
    mod = engine()
    consumer = tmp_path / "todo-web"
    consumer.mkdir()
    write_copy(consumer, copy_doc("todo-web", "consumer"))
    assert mod.contract_cases(consumer) == []
    empty = tmp_path / "nothing"
    empty.mkdir()
    assert mod.contract_cases(empty) == []


def test_a_provider_that_follows_the_contract_passes_every_case_ac_110_5(provider):  # AC-110.5
    mod = engine()
    for case in mod.contract_cases(provider):
        mod.check_case(case, app(), base)


def test_each_rule_is_sent_at_the_limit_past_it_and_with_every_allowed_value_ac_110_5(provider):  # AC-110.5
    mod = engine()
    sent = {}
    for case in mod.contract_cases(provider):
        def send(endpoint, body, case=case):
            sent[str(case)] = (endpoint, body)
            return app()(endpoint, body)
        mod.check_case(case, send, base)
    endpoint, body = sent[f"{PLAN}:title-max:at-limit"]
    assert endpoint == "POST /todos" and body["title"] == "x" * 200
    assert sent[f"{PLAN}:title-max:past-limit"][1]["title"] == "x" * 201
    assert "title" in sent[f"{PLAN}:title-required:present"][1]
    assert "title" not in sent[f"{PLAN}:title-required:missing"][1]
    assert sent[f"{PLAN}:status-values:allowed=open"] == ("PATCH /todos/{id}", {**base(""), "status": "open"})
    assert sent[f"{PLAN}:status-values:allowed=done"][1]["status"] == "done"
    assert sent[f"{PLAN}:status-values:not-allowed"][1]["status"] == "open-not-allowed"


def test_the_values_of_every_kind_follow_the_table_ac_110_5(tmp_path):  # AC-110.5
    rules = [{"id": "age-min", "endpoint": "POST /people", "field": "age", "kind": "min_value", "value": 18},
             {"id": "price-max", "endpoint": "POST /people", "field": "price", "kind": "max_value", "value": 9.9, "step": 0.1},
             {"id": "qty-max", "endpoint": "POST /people", "field": "qty", "kind": "max_value", "value": 10},
             {"id": "name-min", "endpoint": "POST /people", "field": "name", "kind": "min_length", "value": 3},
             {"id": "nick-min", "endpoint": "POST /people", "field": "nick", "kind": "min_length", "value": 0},
             {"id": "size-allowed", "endpoint": "POST /people", "field": "size", "kind": "allowed", "value": [1, 5]}]
    rules = [{**r, "provider": "todo-api", "consumers": ["todo-web"]} for r in rules]
    root = tmp_path / "people"
    root.mkdir()
    write_copy(root, copy_doc("todo-api", "provider", rules=rules))
    mod = engine()
    sent = {}
    for case in mod.contract_cases(root):
        def send(endpoint, body, case=case):
            sent[str(case)] = body
            return 200, {}
        try:
            mod.check_case(case, send, lambda endpoint: {})
        except AssertionError:
            pass                                    # a rejection case fails against an API that accepts everything
    assert sent[f"{PLAN}:age-min:at-limit"]["age"] == 18 and sent[f"{PLAN}:age-min:past-limit"]["age"] == 17
    assert sent[f"{PLAN}:price-max:at-limit"]["price"] == 9.9 and sent[f"{PLAN}:price-max:past-limit"]["price"] == 10.0
    assert sent[f"{PLAN}:qty-max:past-limit"]["qty"] == 11
    assert sent[f"{PLAN}:name-min:at-limit"]["name"] == "xxx" and sent[f"{PLAN}:name-min:past-limit"]["name"] == "xx"
    assert sent[f"{PLAN}:nick-min:at-limit"]["nick"] == "" and f"{PLAN}:nick-min:past-limit" not in sent
    assert sent[f"{PLAN}:size-allowed:not-allowed"]["size"] == 6                       # numbers: max + 1
    assert {sent[f"{PLAN}:size-allowed:allowed=1"]["size"], sent[f"{PLAN}:size-allowed:allowed=5"]["size"]} == {1, 5}


def test_a_limit_the_code_does_not_enforce_fails_naming_rule_field_expected_and_actual_ac_110_5(provider):  # AC-110.5
    mod = engine()
    case = by_id(mod, provider)[f"{PLAN}:title-max:past-limit"]
    message = failure(case, app(title_max=500), mod)       # the API accepts 201 characters
    assert re.search(r"contract 003-todos rule title-max field title: past-limit \(.*\) on POST /todos: "
                     r"expected rejected 422 with field=title rule=title-max and a message, got 200 ", message), message


def test_a_limit_the_code_enforces_too_early_fails_ac_110_5(provider):  # AC-110.5
    mod = engine()
    case = by_id(mod, provider)[f"{PLAN}:title-max:at-limit"]
    message = failure(case, app(title_max=120), mod)
    assert re.search(r"contract 003-todos rule title-max field title: at-limit \(.*\) on POST /todos: "
                     r"expected accepted \(2xx\), got 422 ", message), message


def test_a_removed_field_and_a_value_outside_the_allowed_set_are_reported_as_such_ac_110_5(provider):  # AC-110.5
    mod = engine()
    cases = by_id(mod, provider)
    lenient = lambda endpoint, body: (200, {})                                          # noqa: E731
    missing = failure(cases[f"{PLAN}:title-required:missing"], lenient, mod)
    assert "rule title-required field title: missing (field removed) on POST /todos: expected rejected 422" in missing
    outside = failure(cases[f"{PLAN}:status-values:not-allowed"], lenient, mod)
    assert "rule status-values field status: not-allowed (open-not-allowed) on PATCH /todos/{id}: expected rejected 422" in outside


@pytest.mark.parametrize("send, why", [
    (app(status=400), "wrong status code"),
    (app(field_key="name"), "the field is not named under body.field"),
    (app(listed=False), "the error is not in the body list"),
    (lambda endpoint, body: (422, {"errors": [{"field": "title", "rule": "other", "message": "m"}]}), "wrong rule id"),
    (lambda endpoint, body: (422, {"errors": [{"field": "title", "rule": "title-max", "message": ""}]}), "no message"),
])
def test_every_rejection_has_the_status_and_error_body_of_the_contract_ac_110_5(provider, send, why):  # AC-110.5
    mod = engine()
    case = by_id(mod, provider)[f"{PLAN}:title-max:past-limit"]
    assert "contract 003-todos rule title-max field title" in failure(case, send, mod), why


def test_the_actual_body_in_the_message_is_cut_at_200_characters_ac_110_5(provider):  # AC-110.5
    mod = engine()
    case = by_id(mod, provider)[f"{PLAN}:title-max:past-limit"]
    message = failure(case, lambda endpoint, body: (200, {"x": "y" * 500}), mod)
    assert 0 < len(message.split("got 200 ", 1)[1]) <= 200


# ---------------- AC-110.8: the check runs in the repo's own tests, offline ----------------

def test_the_provider_check_is_part_of_the_repos_test_run_ac_110_8():  # AC-110.8
    text = re.sub(r"\{\{.*?\}\}", "x", re.sub(r"\{%.*?%\}", "", (TEMPLATE / "devbox.json").read_text(), flags=re.S))
    recipes = json.loads(text)["shell"]["scripts"]
    for name in ("test", "test-fast"):
        assert "-p scripts.contract_pytest" in recipes[name], name
    test_file = TEMPLATE / "tests" / "test_contract.py"
    assert test_file.is_file(), "missing template file: templates/service-python/tests/test_contract.py"
    text = test_file.read_text()
    assert "contract_cases" in text and "check_case" in text and "parametrize" in text


def test_the_provider_check_needs_no_other_repo_and_no_network_ac_110_8():  # AC-110.8
    assert ENGINE.is_file(), "missing template file: templates/service-python/scripts/contract_pytest.py"
    source = ENGINE.read_text()
    assert not re.search(r"^\s*(import|from)\s+(httpx|requests|urllib|socket|aiohttp)\b", source, re.M)
    assert "TestClient" in source and "SMOKE_BASE_URL" not in source        # in-process, never a deployment


# ---------------- AC-110.10: a contract change fails the check until the code follows ----------------

def test_a_changed_contract_fails_the_check_until_the_code_follows_ac_110_10(tmp_path, capsys):  # AC-110.10
    gitops = world(tmp_path)
    commit_all(gitops)
    api = tmp_path / "todo-api"
    api.mkdir()
    mod = engine()

    def rerun():
        capsys.readouterr()
        assert spec.main(["--repo", str(api), "new", "--no-shape", "--from-plan", str(plan_file(gitops)), "todo-api"]) == 0

    def failures(send):
        out = []
        for case in mod.contract_cases(api):
            try:
                mod.check_case(case, send, base)
            except AssertionError as e:
                out.append(str(e))
        return out

    rerun()
    assert failures(app(title_max=200)) == []                               # built against 200
    plan_file(gitops).write_text(plan_text(contract_text(mutated(lambda rules: rules[0].update(value=120)))))
    commit_all(gitops, "title max 200 -> 120")
    rerun()
    broken = failures(app(title_max=200))                                   # the code still says 200
    assert len(broken) == 1 and "rule title-max field title: past-limit" in broken[0]
    assert failures(app(title_max=120)) == []                               # the code follows: green again
