"""Spec 110 acceptance tests, AC-110.4 and AC-110.10 on the cplat side: `cplat spec new --from-plan <plan> <repo-id>` writes the
repo's copy `contract/<plan_id>.json` and lists the rules in `### Contract rules` of the System context (design 3); running it
again after the plan changed overwrites the copy. The gitops-app checkout is a git repo, as the copy carries its commit."""
import json

import pytest
from support_110 import RULES, contract_text, commit_all, git, mutated, plan_file, plan_text, resolved, world

import core
import spec

SHA7 = 7


@pytest.fixture()
def product(tmp_path):
    root = world(tmp_path)
    commit_all(root)
    return root


def run(repo, plan, repo_id, capsys):
    capsys.readouterr()
    rc = spec.main(["--repo", str(repo), "new", "--no-shape", "--from-plan", str(plan), repo_id])
    return rc, capsys.readouterr().out


def component(tmp_path, name):
    repo = tmp_path / name
    repo.mkdir()
    return repo


def copy_of(repo):
    return json.loads((repo / "contract" / "003-todos.json").read_text())


def test_the_repo_gets_a_copy_marked_with_the_plan_and_the_commit_ac_110_4(tmp_path, product, capsys):  # AC-110.4
    head = git(product, "rev-parse", "HEAD").strip()
    web = component(tmp_path, "todo-web")
    rc, out = run(web, plan_file(product), "todo-web", capsys)
    assert rc == 0
    doc = copy_of(web)
    assert doc["plan_id"] == "003-todos" and doc["repo"] == "todo-web" and doc["gitops_app"] == "acme/shop-gitops"
    assert doc["commit"] == head and len(head) == 40
    assert doc["rules"] == [resolved(r, "consumer") for r in sorted(RULES, key=lambda r: r["id"])]
    assert doc["errors"]["status"] == 422 and doc["errors"]["unlisted"]["message"].startswith("Something went wrong")
    text = (web / "contract" / "003-todos.json").read_text()
    assert text.endswith("\n") and json.dumps(doc, sort_keys=True, indent=2) + "\n" == text   # keys sorted, indent 2
    lines = out.strip().splitlines()
    assert lines[0].endswith("spec.md")
    assert lines[1] == f"contract copy: contract/003-todos.json (3 rules, acme/shop-gitops@{head[:SHA7]})"


def test_the_provider_copy_marks_its_role_ac_110_4(tmp_path, product, capsys):  # AC-110.4
    api = component(tmp_path, "todo-api")
    run(api, plan_file(product), "todo-api", capsys)
    assert {r["role"] for r in copy_of(api)["rules"]} == {"provider"}


def test_the_spec_lists_the_rules_in_its_system_context_ac_110_4(tmp_path, product, capsys):  # AC-110.4
    head = git(product, "rev-parse", "HEAD").strip()
    web = component(tmp_path, "todo-web")
    run(web, plan_file(product), "todo-web", capsys)
    (spec_dir,) = (web / "docs" / "specs").iterdir()
    ctx = spec.sections(spec.read(spec_dir).body)["system context"]
    assert "### Contract rules" in ctx
    assert ctx.index("### Contract") < ctx.index("### Contract rules")
    part = ctx[ctx.index("### Contract rules"):]
    assert "`contract/003-todos.json`" in part and f"`acme/shop-gitops@{head[:SHA7]}`" in part
    rows = [ln.strip() for ln in part.splitlines() if ln.startswith("|")]
    assert "| Rule | Endpoint | Field | Kind | Value | Status | Role |" in rows
    assert "| title-max | POST /todos | title | max_length | 200 | 422 | consumer |" in rows
    assert any(r.startswith("| status-values | PATCH /todos/{id} | status | allowed |") and r.endswith("| 422 | consumer |")
               for r in rows)
    assert "Something went wrong. Please try again." in part and "422" in part.split("Errors:", 1)[1]


def test_a_repo_in_no_rule_gets_no_copy_and_a_stale_one_is_removed_ac_110_4(tmp_path, product, capsys):  # AC-110.4
    docs = "  - {id: todo-docs, shape: library-python, summary: docs, acs: [], depends_on: [], done: false}\n"
    plan_file(product).write_text(plan_text().replace("  - {id: todo-web,", docs + "  - {id: todo-web,"))
    commit_all(product, "docs repo")
    other = component(tmp_path, "todo-docs")
    (other / "contract").mkdir()
    (other / "contract" / "003-todos.json").write_text("{}\n")
    rc, out = run(other, plan_file(product), "todo-docs", capsys)
    assert rc == 0
    assert not (other / "contract" / "003-todos.json").exists()
    assert "contract copy: none (todo-docs takes part in no rule of 003-todos)" in out.splitlines()
    (spec_dir,) = (other / "docs" / "specs").iterdir()
    assert "### Contract rules" not in spec.read(spec_dir).body


def test_a_plan_with_no_shared_rules_gives_no_copy_ac_110_4(tmp_path, product, capsys):  # AC-110.4
    plan_file(product).write_text(plan_text(contract_text(rules_part="No shared rules: free text only\n", errors_part="prose\n")))
    commit_all(product, "no rules")
    web = component(tmp_path, "todo-web")
    rc, out = run(web, plan_file(product), "todo-web", capsys)
    assert rc == 0 and not (web / "contract").exists()
    assert "contract copy: none (todo-web takes part in no rule of 003-todos)" in out.splitlines()


def test_a_contract_that_fails_plan_check_writes_no_spec_ac_110_4(tmp_path, product):  # AC-110.4
    plan_file(product).write_text(plan_text(contract_text(mutated(lambda rules: rules[0].pop("value")))))
    commit_all(product, "broken")
    web = component(tmp_path, "todo-web")
    with pytest.raises(core.PlatformError) as err:
        spec.new_from_plan(web, plan_file(product), "todo-web", shape=None)
    assert str(err.value).startswith("the contract of 003-todos does not pass plan-check: ")
    assert "rule title-max: no concrete value" in str(err.value)
    assert "docs/plan/003-todos.md" in (err.value.hint or "") and "devbox run plan-check" in (err.value.hint or "")
    assert not (web / "docs").exists() and not (web / "contract").exists()


def test_a_plan_outside_a_git_checkout_cannot_give_a_copy_ac_110_4(tmp_path):  # AC-110.4
    root = world(tmp_path)                                   # no git init
    web = component(tmp_path, "todo-web")
    with pytest.raises(core.PlatformError, match="cannot read the gitops-app commit of .*: the plan must be in a git checkout"):
        spec.new_from_plan(web, plan_file(root), "todo-web", shape=None)


# ---------------- AC-110.10: a contract change reaches the repo on the next run ----------------

def test_running_from_plan_again_updates_the_copy_to_the_new_values_ac_110_10(tmp_path, product, capsys):  # AC-110.10
    api = component(tmp_path, "todo-api")
    run(api, plan_file(product), "todo-api", capsys)
    before = copy_of(api)
    assert next(r for r in before["rules"] if r["id"] == "title-max")["value"] == 200
    rules = mutated(lambda rs: rs[0].update(value=120))
    plan_file(product).write_text(plan_text(contract_text(rules)))
    new_head = commit_all(product, "title max 200 -> 120")
    rc, out = run(api, plan_file(product), "todo-api", capsys)
    assert rc == 0
    after = copy_of(api)
    assert next(r for r in after["rules"] if r["id"] == "title-max")["value"] == 120
    assert after["commit"] == new_head and after["commit"] != before["commit"]
    assert [r for r in after["rules"] if r["id"] != "title-max"] == [r for r in before["rules"] if r["id"] != "title-max"]
    assert f"@{new_head[:SHA7]})" in out
