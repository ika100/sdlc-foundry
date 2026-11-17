"""Spec 110 acceptance tests, AC-110.6, AC-110.7, AC-110.8 and AC-110.10 for the web-nextjs consumer check (design 5).

`lib/contract/engine.ts` is plain TypeScript with no dependency but node:fs, so node runs it directly (type stripping); a runner
(fixtures/contract_runner_110.mjs) gives it a small fake form as the adapter and prints each case's result as JSON. The
copy comes from `support_110` or from `cplat spec new --from-plan`."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from support_110 import ROOT, commit_all, contract_text, copy_doc, mutated, plan_file, plan_text, world, write_copy

import spec

TEMPLATE = ROOT / "templates" / "web-nextjs"
ENGINE = TEMPLATE / "lib" / "contract" / "engine.ts"
RUNNER = Path(__file__).parent / "fixtures" / "contract_runner_110.mjs"
P = "003-todos"
UNLISTED = "Something went wrong. Please try again."

VALIDATION = [f"{P}:title-max:at-limit", f"{P}:title-max:past-limit", f"{P}:title-required:present", f"{P}:title-required:missing",
              f"{P}:status-values:allowed=open", f"{P}:status-values:allowed=done", f"{P}:status-values:not-allowed"]
RESPONSES = [f"{P}:title-max:response", f"{P}:title-required:response", f"{P}:status-values:response",
             f"{P}:POST /todos:unlisted", f"{P}:PATCH /todos/{{id}}:unlisted"]


def run_engine(tmp_path, copy_root, **options):
    """{case name: null | failure message} of every case of `copy_root/contract` against the fake form.

    Requirement for the engine: node >= 22.18 (devbox nodejs) runs engine.ts directly by type stripping, so it may use only
    erasable TypeScript syntax (no enum, no namespace, no constructor parameter properties). There is no skip: without such a
    node these tests fail. `contractCases(dir)` gets the repo root (like the provider's `dir`) and reads `<dir>/contract/*.json`.
    """
    assert ENGINE.is_file(), "missing template file: templates/web-nextjs/lib/contract/engine.ts"
    work = tmp_path / "engine"
    work.mkdir(exist_ok=True)
    (work / "package.json").write_text('{"type": "module"}')
    shutil.copy(ENGINE, work / "engine.ts")
    proc = subprocess.run(["node", "--no-warnings", str(RUNNER), str(work / "engine.ts"), str(copy_root), json.dumps(options)],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return {r["name"]: r["result"] for r in json.loads(proc.stdout)}


@pytest.fixture()
def consumer(tmp_path):
    root = tmp_path / "todo-web"
    root.mkdir()
    write_copy(root, copy_doc("todo-web", "consumer"))
    return root


def test_the_cases_are_derived_from_the_consumer_rules_of_the_copy_ac_110_6(tmp_path, consumer):  # AC-110.6
    results = run_engine(tmp_path, consumer)
    assert sorted(n for n in results if not n.endswith((":response", ":unlisted"))) == sorted(VALIDATION)


def test_a_front_end_that_follows_the_contract_passes_every_case_ac_110_6(tmp_path, consumer):  # AC-110.6
    results = run_engine(tmp_path, consumer)
    assert set(results) == set(VALIDATION + RESPONSES)
    assert {n: r for n, r in results.items() if r is not None} == {}


def test_provider_rules_of_the_copy_are_not_checked_here_ac_110_6(tmp_path):  # AC-110.6
    api = tmp_path / "todo-api"
    api.mkdir()
    write_copy(api, copy_doc("todo-api", "provider"))
    assert run_engine(tmp_path, api) == {}


def test_a_front_end_that_accepts_what_the_contract_rejects_fails_naming_the_rule_ac_110_6(tmp_path, consumer):  # AC-110.6
    results = run_engine(tmp_path, consumer, titleMax=250, statuses=["open", "done", "open-not-allowed"], titleRequired=False)
    assert re.fullmatch(r"contract 003-todos rule title-max field title: past-limit \(.*\) on POST /todos: expected error at title, "
                        r"got valid", results[f"{P}:title-max:past-limit"] or "")
    assert re.fullmatch(r"contract 003-todos rule title-required field title: missing \(.*\) on POST /todos: expected error at title, "
                        r"got valid", results[f"{P}:title-required:missing"] or "")
    assert "rule status-values field status: not-allowed (open-not-allowed) on PATCH /todos/{id}: expected error at status" in \
        (results[f"{P}:status-values:not-allowed"] or "")
    assert results[f"{P}:title-max:at-limit"] is None


def test_a_front_end_that_rejects_what_the_contract_accepts_fails_naming_the_message_ac_110_6(tmp_path, consumer):  # AC-110.6
    results = run_engine(tmp_path, consumer, titleMax=120, statuses=["open"])
    assert re.fullmatch(r"contract 003-todos rule title-max field title: at-limit \(.*\) on POST /todos: expected valid, "
                        r'got error at title: "Title too long"', results[f"{P}:title-max:at-limit"] or "")
    assert "rule status-values field status: allowed=done (done) on PATCH /todos/{id}: expected valid, " \
           'got error at status: "Unknown status"' in (results[f"{P}:status-values:allowed=done"] or "")
    assert results[f"{P}:status-values:allowed=open"] is None


def test_decimal_limits_use_the_step_of_the_copy_ac_110_6(tmp_path):  # AC-110.6
    rule = {"id": "price-max", "endpoint": "POST /todos", "field": "price", "kind": "max_value", "value": 9.9, "step": 0.1,
            "provider": "todo-api", "consumers": ["todo-web"]}
    root = tmp_path / "todo-web"
    root.mkdir()
    write_copy(root, copy_doc("todo-web", "consumer", rules=[rule]))
    results = run_engine(tmp_path, root)           # the fake form validates no price: the past-limit case must fail, with 10
    assert results[f"{P}:price-max:at-limit"] is None
    assert "past-limit (10)" in results[f"{P}:price-max:past-limit"] or "past-limit (10.0)" in results[f"{P}:price-max:past-limit"]


# ---------------- AC-110.7: the error response ----------------

def test_the_contract_error_response_must_show_its_message_at_the_field_ac_110_7(tmp_path, consumer):  # AC-110.7
    results = run_engine(tmp_path, consumer, showAtField=False)
    for rule, field in (("title-max", "title"), ("title-required", "title"), ("status-values", "status")):
        message = results[f"{P}:{rule}:response"]
        assert message and message.startswith(f"contract 003-todos rule {rule} field {field}: response 422: expected message "
                                              f'"{rule} violated (contract check)" at {field}, got '), message


def test_an_unlisted_response_must_show_the_unlisted_message_ac_110_7(tmp_path, consumer):  # AC-110.7
    results = run_engine(tmp_path, consumer, unlisted="Oops")
    for endpoint in ("POST /todos", "PATCH /todos/{id}"):
        message = results[f"{P}:{endpoint}:unlisted"]
        assert message and message.startswith(f"contract 003-todos {endpoint}: unlisted response 500: expected form message "
                                              f'"{UNLISTED}", got '), message


def test_the_unlisted_status_is_one_the_copy_does_not_use_ac_110_7(tmp_path):  # AC-110.7
    doc = copy_doc("todo-web", "consumer")
    doc["rules"][0]["status"] = 500                                       # 500 is a listed status now: the engine takes 503
    root = tmp_path / "todo-web"
    root.mkdir()
    write_copy(root, doc)
    results = run_engine(tmp_path, root, unlisted="Oops")
    assert "unlisted response 503" in results[f"{P}:POST /todos:unlisted"]


# ---------------- AC-110.8: part of the repo's own test run, offline ----------------

def test_the_consumer_check_is_part_of_the_repos_vitest_run_ac_110_8():  # AC-110.8
    test_file = TEMPLATE / "tests" / "contract.test.ts"
    adapter = TEMPLATE / "tests" / "contract" / "adapter.ts"
    assert test_file.is_file() and adapter.is_file(), "missing template files tests/contract.test.ts, tests/contract/adapter.ts"
    assert "contractCases" in test_file.read_text()
    assert 'include: ["tests/**/*.test.{ts,tsx}"]' in (TEMPLATE / "vitest.config.mts").read_text()    # `devbox run test` runs it
    assert "wire tests/contract/adapter.ts to your form (spec 110)" in adapter.read_text()
    assert "contract: no copy in contract/ (nothing to check)" in test_file.read_text()


def test_the_consumer_check_needs_no_network_and_no_other_repo_ac_110_8():  # AC-110.8
    assert ENGINE.is_file(), "missing template file: templates/web-nextjs/lib/contract/engine.ts"
    source = ENGINE.read_text()
    assert not re.search(r"\bfetch\(|node:https?\b|node:net\b|XMLHttpRequest|SMOKE_BASE_URL", source)


def test_without_a_copy_there_is_nothing_to_check_ac_110_8(tmp_path):  # AC-110.8
    empty = tmp_path / "todo-web"
    empty.mkdir()
    assert run_engine(tmp_path, empty) == {}


# ---------------- AC-110.10: a contract change fails the check until the code follows ----------------

def test_a_changed_contract_fails_the_check_until_the_code_follows_ac_110_10(tmp_path, capsys):  # AC-110.10
    gitops = world(tmp_path)
    commit_all(gitops)
    web = tmp_path / "todo-web"
    web.mkdir()

    def rerun():
        capsys.readouterr()
        assert spec.main(["--repo", str(web), "new", "--no-shape", "--from-plan", str(plan_file(gitops)), "todo-web"]) == 0

    rerun()
    assert {n: r for n, r in run_engine(tmp_path, web, titleMax=200).items() if r} == {}
    plan_file(gitops).write_text(plan_text(contract_text(mutated(lambda rules: rules[0].update(value=120)))))
    commit_all(gitops, "title max 200 -> 120")
    rerun()
    failed = {n: r for n, r in run_engine(tmp_path, web, titleMax=200).items() if r}
    assert list(failed) == [f"{P}:title-max:past-limit"]
    assert {n: r for n, r in run_engine(tmp_path, web, titleMax=120).items() if r} == {}
