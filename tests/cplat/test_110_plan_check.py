"""Spec 110 acceptance tests, AC-110.1 to AC-110.3 and the `plan.py contract` part of AC-110.4: plan-check refuses a multi-repo
plan whose contract has no valid `### Rules` part or `errors:` block (design 1), finished plans only warn, and
`plan.py contract <plan> <repo-id>` prints a repo's slice (design 2). Plans are built by support_110."""
import copy
import json

import pytest
from support_110 import (ERRORS, NO_RULES, RULES, contract_cmd, contract_text, error_lines, has_error, mutated, plan_file, plan_text,
                         validate, world)

NO_RULES_SECTION = ("the contract has no `### Rules` section: add `### Rules` under `## Contract` with a yaml block `rules:` of the "
                    "shared input rules, or the line `No shared rules: <reason>` (spec 110)")
NEITHER = "### Rules has neither a yaml block with `rules:` nor the line `No shared rules: <reason>` (spec 110)"
NO_ERRORS_BLOCK = ("### Errors has no yaml block with `errors:`: state the status code, the body fields (field, rule, message) and "
                   "`unlisted.message` (spec 110)")


@pytest.fixture()
def root(tmp_path):
    return world(tmp_path)


def test_a_plan_with_valid_rules_and_errors_passes_ac_110_1(root):  # AC-110.1
    proc = validate(root, plan_text())
    assert proc.returncode == 0, proc.stderr
    assert not error_lines(proc)
    assert validate(root, plan_text(contract_text(no_rules_section=True))).returncode == 1   # the same plan, without `### Rules`


def test_a_missing_rules_part_is_refused_ac_110_1(root):  # AC-110.1
    proc = validate(root, plan_text(contract_text(no_rules_section=True)))
    assert proc.returncode == 1 and has_error(proc, NO_RULES_SECTION), proc.stderr


def test_a_single_repo_plan_needs_no_rules_ac_110_1(root):  # AC-110.1
    one = plan_text(contract_text(no_rules_section=True)).replace(
        "  - {id: todo-web, shape: web-nextjs, summary: UI, acs: [AC-003.2], depends_on: [], done: false}\n", "").replace(
        "acs: [AC-003.1]", "acs: [AC-003.1, AC-003.2]")
    proc = validate(root, one)
    assert proc.returncode == 0, proc.stderr
    # the same plan with two repos is refused: the rule is about multi-repo plans, not an overall switch
    assert validate(root, plan_text(contract_text(no_rules_section=True))).returncode == 1


def test_no_shared_rules_with_a_reason_passes_and_the_errors_may_stay_prose_ac_110_1(root):  # AC-110.1
    text = plan_text(contract_text(rules_part=NO_RULES + "\n", errors_part="problem+json, status 4xx\n"))
    proc = validate(root, text)
    assert proc.returncode == 0, proc.stderr
    assert validate(root, plan_text(contract_text(no_rules_section=True))).returncode == 1


@pytest.mark.parametrize("part", ["No shared rules:\n", "No shared rules:   \n", "Rules are written in the spec.\n"])
def test_rules_without_a_block_or_a_reason_are_refused_ac_110_1(root, part):  # AC-110.1
    proc = validate(root, plan_text(contract_text(rules_part=part)))
    assert proc.returncode == 1 and has_error(proc, NEITHER), proc.stderr


def test_a_rules_block_that_does_not_parse_is_refused_with_the_parser_message_ac_110_1(root):  # AC-110.1
    proc = validate(root, plan_text(contract_text(rules_part="```yaml\nrules: [unclosed\n  - id: x\n```\n")))
    assert proc.returncode == 1 and has_error(proc, NEITHER), proc.stderr
    assert any(NEITHER in ln and ln.split(NEITHER, 1)[1].strip(" :;,.-()[]") for ln in error_lines(proc))   # the parser message is appended


def _drop(key):
    return lambda rules: rules[0].pop(key)


def _set(key, value):
    def change(rules):
        rules[0][key] = value
    return change


def _second_is_a_duplicate(rules):
    rules[1]["id"] = "title-max"


def _decimal_without_step(rules):
    rules[0].update(kind="min_value", value=0.5)


def _consumer_is_provider(rules):
    rules[0]["consumers"] = ["todo-api"]


@pytest.mark.parametrize("change, message", [
    (_drop("id"), "rule #1: missing id"),
    (_second_is_a_duplicate, "rule title-max: duplicate id"),
    (_drop("endpoint"), "rule title-max: missing endpoint"),
    (_drop("field"), "rule title-max: missing field"),
    (_drop("kind"), "rule title-max: missing kind"),
    (_drop("provider"), "rule title-max: missing provider"),
    (_drop("consumers"), "rule title-max: missing consumers"),
    (_drop("value"), "rule title-max: no concrete value"),
    (_set("value", None), "rule title-max: no concrete value"),
    (_set("value", "long"), "rule title-max: no concrete value"),
    (_set("kind", "pattern"),
     "rule title-max: unknown kind 'pattern' (allowed: allowed, max_length, max_value, min_length, min_value, required)"),
    (_set("endpoint", "GET /todos"), "rule title-max: endpoint must be 'POST|PUT|PATCH /path', got 'GET /todos'"),
    (_decimal_without_step, "rule title-max: a decimal value needs `step`"),
    (_set("provider", "todo-x"), "rule title-max: provider 'todo-x' is not a repo of this plan"),
    (_set("consumers", ["todo-web", "todo-x"]), "rule title-max: consumer 'todo-x' is not a repo of this plan"),
    (_consumer_is_provider, "rule title-max: the provider 'todo-api' is also a consumer"),
])
def test_an_invalid_rule_is_refused_naming_it_ac_110_1(root, change, message):  # AC-110.1
    proc = validate(root, plan_text(contract_text(mutated(change))))
    assert proc.returncode == 1 and has_error(proc, message), proc.stderr


def test_every_kind_with_a_concrete_value_passes_ac_110_1(root):  # AC-110.1
    rules = [{"id": f"r-{kind}", "endpoint": "POST /todos", "field": f"f_{kind}", "kind": kind, "value": value,
              "provider": "todo-api", "consumers": ["todo-web"], **extra}
             for kind, value, extra in [("required", True, {}), ("min_length", 1, {}), ("max_length", 50, {}),
                                        ("min_value", 0, {}), ("max_value", 9.5, {"step": 0.5}), ("allowed", ["a", "b"], {})]]
    proc = validate(root, plan_text(contract_text(rules)))
    assert proc.returncode == 0, proc.stderr
    assert validate(root, plan_text(contract_text([{**rules[0], "kind": "pattern"}]))).returncode == 1   # only these six are checked


# ---------------- AC-110.2: the error contract ----------------

def _errors_without(*path):
    doc = copy.deepcopy(ERRORS)
    node = doc
    for key in path[:-1]:
        node = node[key]
    node.pop(path[-1])
    return doc


@pytest.mark.parametrize("errors, message", [
    (_errors_without("body", "field"), "### Errors: `body.field` is missing"),
    (_errors_without("body", "rule"), "### Errors: `body.rule` is missing"),
    (_errors_without("body", "message"), "### Errors: `body.message` is missing"),
    (_errors_without("unlisted", "message"), "### Errors: `unlisted.message` is missing"),
    ({**ERRORS, "status": 99}, "### Errors: status must be a code 400-599"),
    ({**ERRORS, "status": 200}, "### Errors: status must be a code 400-599"),
])
def test_an_incomplete_error_contract_is_refused_ac_110_2(root, errors, message):  # AC-110.2
    proc = validate(root, plan_text(contract_text(errors=errors)))
    assert proc.returncode == 1 and has_error(proc, message), proc.stderr


def test_errors_without_a_yaml_block_are_refused_when_there_are_rules_ac_110_2(root):  # AC-110.2
    proc = validate(root, plan_text(contract_text(errors_part="problem+json\n")))
    assert proc.returncode == 1 and has_error(proc, NO_ERRORS_BLOCK), proc.stderr


def test_a_rule_whose_violation_has_no_status_code_is_refused_ac_110_2(root):  # AC-110.2
    no_status = {k: v for k, v in ERRORS.items() if k != "status"}
    proc = validate(root, plan_text(contract_text(errors=no_status)))
    assert proc.returncode == 1, proc.stderr
    for rule in RULES:
        assert has_error(proc, f"rule {rule['id']}: no status code for a violation: add `status:` to the `errors:` block or to the "
                                "rule (spec 110)"), proc.stderr


def test_a_status_on_every_rule_replaces_the_one_of_the_errors_block_ac_110_2(root):  # AC-110.2
    no_status = {k: v for k, v in ERRORS.items() if k != "status"}
    own = [{**r, "status": 400 + i} for i, r in enumerate(RULES)]
    proc = validate(root, plan_text(contract_text(own, no_status)))
    assert proc.returncode == 0, proc.stderr
    one_short = [{**r, "status": 422} for r in RULES[:2]] + [RULES[2]]
    assert has_error(validate(root, plan_text(contract_text(one_short, no_status))),
                     "rule status-values: no status code for a violation")


# ---------------- AC-110.3: finished plans warn only ----------------

def _warnings(proc):
    return [ln for ln in (proc.stdout + proc.stderr).splitlines() if ln.startswith("WARNING")]


@pytest.mark.parametrize("status", ["completed", "abandoned"])
def test_a_finished_plan_without_rules_warns_and_passes_ac_110_3(root, status):  # AC-110.3
    proc = validate(root, plan_text(contract_text(no_rules_section=True, errors_part="problem+json\n"), status=status))
    assert proc.returncode == 0, proc.stderr
    warnings = _warnings(proc)
    assert len(warnings) == 1 and "003-todos" in warnings[0] and "no `### Rules`" in warnings[0], warnings
    assert not error_lines(proc)


@pytest.mark.parametrize("status", ["draft", "in_progress"])
def test_an_active_plan_without_rules_still_fails_ac_110_3(root, status):  # AC-110.3
    proc = validate(root, plan_text(contract_text(no_rules_section=True), status=status))
    assert proc.returncode == 1 and has_error(proc, NO_RULES_SECTION)
    assert not _warnings(proc)


def test_an_invalid_rule_in_a_finished_plan_is_a_warning_ac_110_3(root):  # AC-110.3
    rules = mutated(_drop("value"))
    proc = validate(root, plan_text(contract_text(rules), status="completed"))
    assert proc.returncode == 0, proc.stderr
    warnings = _warnings(proc)
    assert len(warnings) == 1 and "title-max" in warnings[0] and not error_lines(proc), warnings


# ---------------- AC-110.4: `plan.py contract <plan-file> <repo-id>` ----------------

def _slice(root, repo):
    proc = contract_cmd(root, str(plan_file(root)), repo)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _rule(rule, role, **extra):
    return {**copy.deepcopy(rule), "status": 422, "role": role, **extra}


def test_contract_prints_the_slice_of_a_consumer_ac_110_4(root):  # AC-110.4
    doc = _slice(root, "todo-web")
    assert doc["plan_id"] == "003-todos" and doc["gitops_app"] == "acme/shop-gitops" and doc["repo"] == "todo-web"
    assert doc["rules"] == [_rule(r, "consumer") for r in sorted(RULES, key=lambda r: r["id"])]
    assert doc["errors"] == ERRORS                       # as written in the plan: `list` stays, nothing is added


def test_contract_prints_the_slice_of_a_provider_and_resolves_status_and_step_ac_110_4(root):  # AC-110.4
    own = [{**RULES[0], "status": 400}, RULES[1],
           {"id": "age-min", "endpoint": "POST /todos", "field": "age", "kind": "min_value", "value": 18,
            "provider": "todo-api", "consumers": ["todo-web"]},
           {"id": "price-max", "endpoint": "POST /todos", "field": "price", "kind": "max_value", "value": 9.9, "step": 0.1,
            "provider": "todo-api", "consumers": ["todo-web"]}]
    plan_file(root).write_text(plan_text(contract_text(own)))
    doc = _slice(root, "todo-api")
    by_id = {r["id"]: r for r in doc["rules"]}
    assert [r["id"] for r in doc["rules"]] == sorted(by_id)
    assert by_id["title-max"]["status"] == 400 and by_id["title-required"]["status"] == 422
    assert all(r["role"] == "provider" for r in doc["rules"])
    assert by_id["age-min"]["step"] == 1 and by_id["price-max"]["step"] == 0.1
    assert "step" not in by_id["title-max"]


def test_contract_only_lists_the_rules_of_the_repo_ac_110_4(root):  # AC-110.4
    third = plan_text(contract_text(RULES[:2] + [{**RULES[2], "consumers": ["todo-api"], "provider": "todo-web"}]))
    plan_file(root).write_text(third)
    assert [r["id"] for r in _slice(root, "todo-web")["rules"]] == ["status-values", "title-max", "title-required"]
    web_roles = {r["id"]: r["role"] for r in _slice(root, "todo-web")["rules"]}
    api_roles = {r["id"]: r["role"] for r in _slice(root, "todo-api")["rules"]}
    assert web_roles["status-values"] == "provider" and api_roles["status-values"] == "consumer"


def test_contract_of_a_plan_without_rules_is_empty_and_exits_0_ac_110_4(root):  # AC-110.4
    plan_file(root).write_text(plan_text(contract_text(rules_part=NO_RULES + "\n", errors_part="prose\n")))
    doc = _slice(root, "todo-web")
    assert doc["rules"] == [] and doc["errors"] is None


def test_contract_of_a_repo_in_no_rule_is_empty_ac_110_4(root):  # AC-110.4
    docs = "  - {id: todo-docs, shape: library-python, summary: docs, acs: [], depends_on: [], done: false}\n"
    plan_file(root).write_text(plan_text().replace("  - {id: todo-web,", docs + "  - {id: todo-web,"))
    doc = _slice(root, "todo-docs")
    assert doc["rules"] == [] and doc["errors"] is None


def test_contract_refuses_an_unknown_repo_and_an_invalid_contract_ac_110_4(root):  # AC-110.4
    proc = contract_cmd(root, str(plan_file(root)), "todo-x")
    assert proc.returncode == 1 and "ERROR: unknown repo id 'todo-x'" in proc.stderr
    plan_file(root).write_text(plan_text(contract_text(mutated(_drop("value")))))
    proc = contract_cmd(root, str(plan_file(root)), "todo-web")
    assert proc.returncode == 1 and "rule title-max: no concrete value" in proc.stderr and not proc.stdout.strip()


def test_contract_with_wrong_usage_exits_2_ac_110_4(root):  # AC-110.4
    assert contract_cmd(root, str(plan_file(root)), "todo-web").returncode == 0     # the subcommand exists
    assert contract_cmd(root).returncode == 2
    assert contract_cmd(root, str(plan_file(root))).returncode == 2


def test_the_contract_of_the_design_wins_over_the_plan_body_ac_110_4(root):  # AC-110.4
    design = root / "docs" / "specs" / "003-todos" / "design.md"
    design.write_text("# Design\n" + contract_text([{**RULES[0], "value": 120}]))
    plan_file(root).write_text(plan_text(contract_text(RULES)))
    title_max = next(r for r in _slice(root, "todo-web")["rules"] if r["id"] == "title-max")
    assert title_max["value"] == 120
