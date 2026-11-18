"""Shared helpers of the spec 110 acceptance tests (not a test module, never collected).

The contract is docs/specs/110-a-product-s-repos-agree-on-the-contract/design.md, `## Contract`: the plan's `### Rules` and
`### Errors` blocks (1), `plan.py contract` (2), the copy `contract/<plan_id>.json` (3). Plans are built as data and dumped, so a
test changes one key and keeps the rest valid. Nothing here imports a module of the feature."""
import copy
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
PLAN_SCRIPT = ROOT / "templates" / "gitops-app" / "scripts" / "plan.py"
PLAN_ID = "003-todos"
GITOPS_APP = "acme/shop-gitops"

SPEC = """---
spec_id: 003-todos
title: Todos
status: approved
priority: P0
shape: gitops-app
---

## Acceptance criteria

- **AC-003.1** a todo can be created
- **AC-003.2** the form shows what the API refuses

## Changelog
"""

HEAD = """---
plan_id: 003-todos
spec: 003-todos
feature: todos
gitops_app: acme/shop-gitops
status: draft
repos:
  - {id: todo-api, shape: service-python, summary: API, acs: [AC-003.1], depends_on: [], done: false}
  - {id: todo-web, shape: web-nextjs, summary: UI, acs: [AC-003.2], depends_on: [], done: false}
---
"""

RULES = [
    {"id": "title-max", "endpoint": "POST /todos", "field": "title", "kind": "max_length", "value": 200,
     "provider": "todo-api", "consumers": ["todo-web"]},
    {"id": "title-required", "endpoint": "POST /todos", "field": "title", "kind": "required", "value": True,
     "provider": "todo-api", "consumers": ["todo-web"]},
    {"id": "status-values", "endpoint": "PATCH /todos/{id}", "field": "status", "kind": "allowed", "value": ["open", "done"],
     "provider": "todo-api", "consumers": ["todo-web"]},
]
ERRORS = {"status": 422,
          "body": {"list": "errors", "field": "field", "rule": "rule", "message": "message"},
          "unlisted": {"message": "Something went wrong. Please try again."}}
NO_RULES = "No shared rules: the form sends free text and the API takes anything"


def block(key, value) -> str:
    return "```yaml\n" + yaml.safe_dump({key: value}, sort_keys=False) + "```\n"


def contract_text(rules=RULES, errors=ERRORS, *, rules_part=None, errors_part=None, no_rules_section=False) -> str:
    """The plan body: `## Contract` with `### Rules` (the dumped rules, or `rules_part` as written), `### Errors`, `### Timeouts`."""
    out = "\n## Contract\n\n`POST /todos` creates a todo; `PATCH /todos/{id}` changes it.\n\n"
    if not no_rules_section:
        out += "### Rules\n\n" + (rules_part if rules_part is not None else block("rules", rules)) + "\n"
    out += "### Errors\n\n" + (errors_part if errors_part is not None else block("errors", errors))
    out += "\nAny other non-2xx: the UI shows the unlisted message above the form.\n\n### Timeouts\n\n3 s; 503 when down\n"
    return out


def plan_text(contract=None, status="draft") -> str:
    text = HEAD + (contract if contract is not None else contract_text())
    if status != "draft":
        text = text.replace("status: draft", f"status: {status}")
    if status == "completed":
        text = text.replace("done: false", "done: true")
    return text


def mutated(change, **kw) -> list[dict]:
    """The three rules with `change(rules)` applied to a deep copy."""
    rules = copy.deepcopy(RULES)
    change(rules)
    return rules


def world(tmp_path: Path, text: str | None = None) -> Path:
    """A gitops-app checkout: scripts/plan.py, docs/plan/003-todos.md and the product spec."""
    root = tmp_path / "shop-gitops"
    (root / "scripts").mkdir(parents=True)
    shutil.copy(PLAN_SCRIPT, root / "scripts" / "plan.py")
    (root / "docs" / "plan").mkdir(parents=True)
    (root / "docs" / "specs" / PLAN_ID).mkdir(parents=True)
    (root / "docs" / "specs" / PLAN_ID / "spec.md").write_text(SPEC)
    (root / "docs" / "plan" / f"{PLAN_ID}.md").write_text(text if text is not None else plan_text())
    return root


def plan_file(root: Path) -> Path:
    return root / "docs" / "plan" / f"{PLAN_ID}.md"


def validate(root: Path, text: str) -> subprocess.CompletedProcess:
    plan_file(root).write_text(text)
    return subprocess.run([sys.executable, str(root / "scripts" / "plan.py"), "validate"], capture_output=True, text=True)


def contract_cmd(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(root / "scripts" / "plan.py"), "contract", *args], capture_output=True, text=True)


def error_lines(proc: subprocess.CompletedProcess) -> list[str]:
    return [ln for ln in proc.stderr.splitlines() if ln.startswith("ERROR")]


def has_error(proc: subprocess.CompletedProcess, message: str) -> bool:
    return any(message in ln for ln in error_lines(proc))


def git(root: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.com"}
    return subprocess.run(["git", *args], cwd=root, env=env, check=True, capture_output=True, text=True).stdout


def commit_all(root: Path, message: str = "plan") -> str:
    """Make `root` a git checkout (if it is not one) and commit everything; returns HEAD."""
    if not (root / ".git").exists():
        git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message)
    return git(root, "rev-parse", "HEAD").strip()


def resolved(rule: dict, role: str, status: int = 422) -> dict:
    out = {**copy.deepcopy(rule), "status": status, "role": role}
    if rule["kind"] in ("min_value", "max_value"):
        out.setdefault("step", 1)
    return out


def copy_doc(repo: str = "todo-web", role: str = "consumer", *, rules=None, errors=ERRORS, commit: str = "a" * 40) -> dict:
    """The copy of design 3: what `cplat spec new --from-plan` writes into a component repo."""
    return {"plan_id": PLAN_ID, "gitops_app": GITOPS_APP, "repo": repo, "commit": commit,
            "rules": [resolved(r, role) for r in (RULES if rules is None else rules)], "errors": copy.deepcopy(errors)}


def write_copy(root: Path, doc: dict) -> Path:
    path = root / "contract" / f"{doc['plan_id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, sort_keys=True, indent=2) + "\n")
    return path
