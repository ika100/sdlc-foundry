"""Spec 110 (AC-110.4, AC-110.10): the repo's copy `contract/<plan_id>.json` of the shared rules and the error contract.

`cplat spec new --from-plan` asks `plan.py contract` (the gitops-app's own check) for the repo's slice, marks it with the
gitops-app commit and writes it; a repo in no rule gets no copy and loses a stale one (design 3)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import core
from core import PlatformError

PLAN_PY = core.PLATFORM_ROOT / "templates" / "gitops-app" / "scripts" / "plan.py"
SHA_LEN = 7


def slice(plan_path: Path, repo_id: str) -> dict:  # noqa: A001 - the name of design 3
    """The slice of `plan.py contract`; a contract that fails plan-check is a PlatformError."""
    proc = subprocess.run([sys.executable, str(PLAN_PY), "contract", str(plan_path), repo_id],
                          capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        lines = [ln.strip() for ln in proc.stderr.splitlines() if ln.strip()]
        first = lines[0] if lines else f"plan.py exited {proc.returncode}"
        first = first.removeprefix("ERROR: ")
        plan_id = plan_path.stem
        raise PlatformError(f"the contract of {plan_id} does not pass plan-check: {first}",
                            hint=f"fix docs/plan/{plan_id}.md in the gitops-app repo (devbox run plan-check)")
    return json.loads(proc.stdout)


def commit(plan_path: Path) -> str:
    """HEAD of the checkout the plan lives in."""
    proc = subprocess.run(["git", "-C", str(plan_path.resolve().parent), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=False)
    sha = proc.stdout.strip()
    if proc.returncode != 0 or len(sha) != 40:
        raise PlatformError(f"cannot read the gitops-app commit of {plan_path}: the plan must be in a git checkout")
    return sha


def path_of(root: Path, plan_id: str) -> Path:
    return root / "contract" / f"{plan_id}.json"


def write(root: Path, doc: dict) -> str:
    """Write (or, without rules, remove) the copy; returns the line the CLI prints."""
    target = path_of(root, doc["plan_id"])
    if not doc["rules"]:
        target.unlink(missing_ok=True)
        return f"contract copy: none ({doc['repo']} takes part in no rule of {doc['plan_id']})"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(doc, sort_keys=True, indent=2) + "\n")
    return (f"contract copy: contract/{doc['plan_id']}.json ({len(doc['rules'])} rules, "
            f"{doc['gitops_app']}@{doc['commit'][:SHA_LEN]})")


def _cell(value) -> str:
    return json.dumps(value) if isinstance(value, (list, dict)) else str(value)


def section(doc: dict) -> str:
    """`### Contract rules` of the System context; empty when the repo takes part in no rule."""
    if not doc["rules"]:
        return ""
    errors = doc.get("errors") or {}
    body = errors.get("body") or {}
    names = ", ".join(f"`{body.get(k, k)}`" for k in ("field", "rule", "message"))
    shape = f"`{body['list']}[]` of objects" if body.get("list") else "one object"
    unlisted = (errors.get("unlisted") or {}).get("message", "")
    rows = "\n".join(f"| {r['id']} | {r['endpoint']} | {r['field']} | {r['kind']} | {_cell(r['value'])} | "
                     f"{r.get('status', '')} | {r['role']} |" for r in doc["rules"])
    sha = doc["commit"][:SHA_LEN]
    return (f"### Contract rules\n\nCopy: `contract/{doc['plan_id']}.json`, from plan `{doc['plan_id']}` at "
            f"`{doc['gitops_app']}@{sha}`. The repo's contract check reads it.\n\n"
            "| Rule | Endpoint | Field | Kind | Value | Status | Role |\n|---|---|---|---|---|---|---|\n"
            f"{rows}\n\nErrors: status {errors.get('status', '')}; body {shape} with {names}; responses the contract "
            f"does not list: show \"{unlisted}\".")
