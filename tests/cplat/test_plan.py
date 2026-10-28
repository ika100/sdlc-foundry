"""templates/gitops-app/scripts/plan.py: `ready` computes the next parallel wave of a multi-repo plan (ADR-011/023)."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "templates" / "gitops-app" / "scripts" / "plan.py"

PLAN = """---
plan_id: billing
feature: add billing
gitops_app: acme/shop-gitops
status: draft
repos:
  - {id: shop-api, shape: service-java, summary: billing API, arguments: "build the API", depends_on: [], done: false}
  - {id: shop-web, shape: web-nextjs, summary: billing UI, arguments: "build the UI", depends_on: [], done: false}
  - {id: shop-lib, shape: library-python, summary: shared lib, arguments: "bump lib", depends_on: [], done: false}
  - {id: shop-e2e, shape: service-python, summary: e2e checks, arguments: "add checks", depends_on: [shop-api, shop-web], done: false}
---
## body
"""


@pytest.fixture()
def repo(tmp_path):
    (tmp_path / "scripts").mkdir()
    shutil.copy(SCRIPT, tmp_path / "scripts" / "plan.py")
    (tmp_path / "docs" / "plan").mkdir(parents=True)
    (tmp_path / "docs" / "plan" / "billing.md").write_text(PLAN)
    return tmp_path


def plan(repo, *args):
    return subprocess.run([sys.executable, str(repo / "scripts" / "plan.py"), *args], capture_output=True, text=True)


def ready(repo):
    out = plan(repo, "ready", "billing", "--json")
    assert out.returncode == 0, out.stderr
    return [r["id"] for r in json.loads(out.stdout)]


def test_independent_repos_start_together_and_dependents_wait(repo):
    assert ready(repo) == ["shop-api", "shop-lib", "shop-web"]


def test_a_dependent_becomes_ready_only_after_all_its_dependencies_are_done(repo):
    plan(repo, "done", "billing", "shop-api")
    assert ready(repo) == ["shop-lib", "shop-web"]
    plan(repo, "done", "billing", "shop-web")
    assert ready(repo) == ["shop-e2e", "shop-lib"]


def test_done_repos_are_not_offered_again(repo):
    for r in ("shop-api", "shop-web", "shop-lib", "shop-e2e"):
        plan(repo, "done", "billing", r)
    assert plan(repo, "ready", "billing").returncode == 1        # the plan is completed


def test_json_carries_the_paste_ready_prompt(repo):
    out = json.loads(plan(repo, "ready", "billing", "--json").stdout)
    assert {"id": "shop-api", "shape": "service-java", "summary": "billing API", "acs": [], "arguments": "build the API"} in out


def test_text_output_names_the_wave(repo):
    out = plan(repo, "ready", "billing").stdout
    assert "3 repo(s) can start now" in out and "shop-web (web-nextjs)" in out


def test_ready_rejects_abandoned_plans(repo):
    plan(repo, "abandon", "billing")
    assert plan(repo, "ready", "billing").returncode == 1


# ---------------- plans made from a product spec (ADR-026) ----------------

SPEC = """---
spec_id: 012-billing
title: Billing
status: approved
priority: P0
shape: gitops-app
---

## Acceptance criteria

- **AC-012.1** checkout returns a URL
- **AC-012.2** webhook marks paid
- ~~**AC-012.3**~~ withdrawn
<!-- - **AC-012.9** an example in a comment is not a criterion -->

## Changelog
"""

SPEC_PLAN_BARE = """---
plan_id: 012-billing
spec: 012-billing
feature: billing
gitops_app: acme/shop-gitops
status: draft
repos:
  - {id: shop-api, shape: service-python, summary: API, acs: [AC-012.1], depends_on: [], done: false}
  - {id: shop-web, shape: web-nextjs, summary: UI, acs: [AC-012.2], depends_on: [], done: false}
---
"""
CONTRACT = "\n## Contract\n\nPOST /x -> 201\n\n### Errors\n\nproblem+json\n\n### Timeouts\n\n3 s; 503 when down\n"
SPEC_PLAN = SPEC_PLAN_BARE + CONTRACT   # spec 053: two repos need errors and timeouts in the contract


@pytest.fixture()
def spec_repo(repo):
    (repo / "docs" / "plan" / "billing.md").unlink()
    (repo / "docs" / "specs" / "012-billing").mkdir(parents=True)
    (repo / "docs" / "specs" / "012-billing" / "spec.md").write_text(SPEC)
    return repo


def check(repo, text):
    (repo / "docs" / "plan" / "012-billing.md").write_text(text)
    return plan(repo, "validate")


def test_a_spec_plan_needs_criteria_not_prompts(spec_repo):
    out = check(spec_repo, SPEC_PLAN)
    assert out.returncode == 0, out.stderr


def test_every_active_criterion_is_assigned_to_a_repo(spec_repo):
    out = check(spec_repo, SPEC_PLAN.replace("acs: [AC-012.2]", "acs: []"))
    assert out.returncode == 1 and "AC-012.2 is not assigned to any repo" in out.stderr


def test_withdrawn_unknown_and_commented_criteria_are_rejected(spec_repo):
    out = check(spec_repo, SPEC_PLAN.replace("acs: [AC-012.1]", "acs: [AC-012.1, AC-012.3, AC-012.9]"))
    assert "criterion 'AC-012.3' is withdrawn" in out.stderr and "unknown criterion 'AC-012.9'" in out.stderr


def test_the_spec_must_exist(spec_repo):
    out = check(spec_repo, SPEC_PLAN.replace("spec: 012-billing", "spec: 013-nope"))
    assert "docs/specs/013-nope/spec.md not found" in out.stderr


def test_ready_hands_out_the_criteria(spec_repo):
    check(spec_repo, SPEC_PLAN)
    wave = json.loads(plan(spec_repo, "ready", "012-billing", "--json").stdout)
    assert {"id": "shop-api", "shape": "service-python", "summary": "API", "acs": ["AC-012.1"], "arguments": ""} in wave


# ---------------- spec 045: the gitops-app entry carries structured operations ----------------

GITOPS_ENTRY = """  - id: shop-gitops
    shape: gitops-app
    summary: wiring
    acs: [AC-012.1]
    gitops:
{ops}    depends_on: []
    done: false
"""
VALID_OPS = ["{addon: postgres}", "{uses: postgres, service: shop-api}", "{expose: shop-web, host: shop}",
             "{env: {API_URL: 'http://shop-api'}, service: shop-web}"]


def _with_gitops(ops):
    entry = GITOPS_ENTRY.format(ops="".join(f"      - {o}\n" for o in ops))
    return SPEC_PLAN.replace("\n---\n", "\n" + entry + "---\n", 1)   # keeps the contract body


def test_a_gitops_entry_with_valid_operations_passes(spec_repo):
    """AC-045.2"""
    out = check(spec_repo, _with_gitops(VALID_OPS))
    assert out.returncode == 0, out.stderr


@pytest.mark.parametrize("ops, msg", [
    (["{scale: shop-api}"], "unknown gitops operation"),
    (["{env: {A: b}, service: shop-x}"], "unknown component 'shop-x'"),
    (["{uses: postgres}"], "needs a component"),
    (["{addon: redis}"], "unknown resource 'redis'"),
])
def test_invalid_gitops_operations_are_rejected(spec_repo, ops, msg):
    """AC-045.2"""
    out = check(spec_repo, _with_gitops(ops))
    assert out.returncode == 1 and msg in out.stderr, out.stderr


def test_a_gitops_entry_needs_operations(spec_repo):
    """AC-045.2"""
    out = check(spec_repo, _with_gitops([]).replace("    gitops:\n", ""))
    assert out.returncode == 1 and "needs a `gitops:` list" in out.stderr


# ---------------- spec 053: multi-repo contracts state errors and timeouts ----------------


def test_a_multi_repo_contract_needs_errors_and_timeouts(spec_repo):
    """AC-053.1"""
    out = check(spec_repo, SPEC_PLAN_BARE)                 # two repos, no contract at all
    assert out.returncode == 1 and "## Contract" in out.stderr
    out = check(spec_repo, SPEC_PLAN_BARE + CONTRACT.replace("### Timeouts", "### Other"))
    assert out.returncode == 1 and "### Timeouts" in out.stderr and "### Errors" not in out.stderr
    assert check(spec_repo, SPEC_PLAN).returncode == 0


def test_a_single_repo_plan_needs_no_contract(spec_repo):
    """AC-053.1"""
    one = SPEC_PLAN_BARE.replace("  - {id: shop-web, shape: web-nextjs, summary: UI, acs: [AC-012.2], depends_on: [], done: false}\n", "")
    out = check(spec_repo, one.replace("acs: [AC-012.1]", "acs: [AC-012.1, AC-012.2]"))
    assert out.returncode == 0, out.stderr


# ---------------- spec 061: plan checks leave completed plans alone ----------------

FIXTURES = Path(__file__).parent / "fixtures"
OLD_STYLE = (SPEC_PLAN_BARE + "\n## Contract\n\nPOST /x -> 201\n\n### Error format\n\nproblem+json\n")   # pre-v4: no ### Errors / ### Timeouts


@pytest.mark.parametrize("status", ["completed", "abandoned"])
def test_a_finished_plan_without_the_v4_sections_passes_with_one_warning(spec_repo, status):
    """AC-061.1"""
    done = "done: true" if status == "completed" else "done: false"
    text = _with_gitops([]).replace("    gitops:\n", "").replace("status: draft", f"status: {status}").replace("done: false", done)
    text = text.replace("\n### Errors\n", "\n### Error format\n").replace("\n### Timeouts\n", "\n### Limits\n")
    out = check(spec_repo, text)
    assert out.returncode == 0, out.stderr
    warnings = [ln for ln in (out.stdout + out.stderr).splitlines() if ln.startswith("WARNING")]
    assert len(warnings) == 1 and "012-billing" in warnings[0], warnings
    assert "gitops" in warnings[0] and "### Errors" in warnings[0] and "### Timeouts" in warnings[0]


@pytest.mark.parametrize("status", ["draft", "in_progress"])
def test_an_active_plan_without_the_v4_sections_still_fails(spec_repo, status):
    """AC-061.2"""
    out = check(spec_repo, OLD_STYLE.replace("status: draft", f"status: {status}"))
    assert out.returncode == 1 and "### Timeouts" in out.stderr


def test_the_error_shows_the_heading_line_to_add(spec_repo):
    """AC-061.3"""
    out = check(spec_repo, SPEC_PLAN_BARE + CONTRACT.replace("### Timeouts", "### Other"))
    assert out.returncode == 1
    assert "add a line `### Timeouts` under `## Contract`" in out.stderr
    out = check(spec_repo, SPEC_PLAN_BARE)
    assert "add `## Contract` with the headings `### Errors` and `### Timeouts`" in out.stderr


def test_the_todo_plan_written_before_v4_passes(repo):
    """AC-061.4: ika100/todo's completed plan 001 (b7feaf8), as it was before the run-2 hand edit."""
    (repo / "docs" / "plan" / "billing.md").unlink()
    shutil.copy(FIXTURES / "plans" / "001-todo-list.md", repo / "docs" / "plan" / "001-todo-list.md")
    shutil.copytree(FIXTURES / "specs", repo / "docs" / "specs")
    out = plan(repo, "validate")
    assert out.returncode == 0, out.stderr
    assert "WARNING: docs/plan/001-todo-list.md" in out.stdout + out.stderr
