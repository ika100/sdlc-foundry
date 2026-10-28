"""Spec 113 acceptance tests: the structural guard (AC-113.13) and the unchanged existing tests (AC-113.12).

AC-113.13: no part of cplat other than `scripts/cplat/model.py` defines its own list of the environments `dev, staging, prod` or
reads or writes an overlay image pin. The check is an AST walk (design.md "The guard") with positive controls, so a detector that
silently finds nothing fails here. Docstrings are not code and are skipped; comments are not in the AST."""
import ast
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CPLAT = ROOT / "scripts" / "cplat"
ENVS = {"dev", "staging", "prod"}


def _docstrings(tree) -> set[int]:
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
                out.add(id(body[0].value))
    return out


def _strings(node, skip: set[int]) -> list[ast.Constant]:
    return [n for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in skip]


def findings(source: str) -> list[tuple[str, int]]:
    """(rule, line): rule 1 an own environment list, rule 2 `newTag` in a string, rule 3 an overlay pin path built in one scope."""
    tree = ast.parse(source)
    skip = _docstrings(tree)
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            items = {e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}
            if ENVS <= items:
                found.append(("environment list", node.lineno))
    for const in _strings(tree, skip):
        if "newTag" in const.value:
            found.append(("overlay pin (newTag)", const.lineno))
    scopes = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    module_level = ast.Module(body=[n for n in tree.body if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))], type_ignores=[])
    for scope in [*scopes, module_level]:
        text = _strings(scope, skip)
        if any("overlays" in c.value for c in text) and any("kustomization.yaml" in c.value for c in text):
            found.append(("overlay pin path", getattr(scope, "lineno", 1)))
    return found


# ---------------- positive controls: the detector sees the code this spec removes ----------------

OLD_STATUS = '''
def pinned_tag(app_dir, env, name):
    f = app_dir / "overlays" / env / name / "kustomization.yaml"
    for img in (yaml.safe_load(f.read_text()) or {}).get("images", []):
        if img.get("newTag"):
            return img["newTag"]
'''
OLD_STAGING = '''
def staging_tag(slug, app_dir, svc, repo=None):
    doc = _read(slug, f"{app_dir}/overlays/staging/{svc}/kustomization.yaml", repo)
    return str(doc["images"][0]["newTag"])
'''


@pytest.mark.parametrize("source, rule", [
    ('ENVS = ["dev", "staging", "prod"]\n', "environment list"),
    ('ORDER = ("dev", "staging", "prod")\n', "environment list"),
    ('for e in {"prod", "dev", "staging"}:\n    pass\n', "environment list"),
    (OLD_STATUS, "overlay pin (newTag)"),
    (OLD_STATUS, "overlay pin path"),
    (OLD_STAGING, "overlay pin (newTag)"),
    (OLD_STAGING, "overlay pin path"),
    ('doc["images"][0]["newTag"] = tag\n', "overlay pin (newTag)"),
])
def test_the_detector_finds_what_the_model_replaces_ac_113_13(source, rule):  # AC-113.13
    assert rule in {r for r, _ in findings(source)}


@pytest.mark.parametrize("source", [
    'raise PlatformError("unknown", hint="dev, staging or prod")\n',                    # prose, one string
    'ok = ("dev", "staging")\n',                                                         # not all three
    'def f(app_dir, env):\n    return (app_dir / "overlays" / env).is_dir()\n',         # compose.py's directory check
    'def f():\n    """Reads overlays/<env>/<svc>/kustomization.yaml and its newTag."""\n    return 1\n',   # a docstring
    'x = "kustomization.yaml"\n',
])
def test_the_detector_leaves_harmless_code_alone_ac_113_13(source):  # AC-113.13
    assert findings(source) == []


# ---------------- the guard itself ----------------

def modules():
    return sorted(p for p in CPLAT.glob("*.py") if p.name != "model.py")


def test_the_guard_scans_the_commands_and_the_helpers_ac_113_13():  # AC-113.13
    names = {p.name for p in modules()}
    assert len(names) > 40 and {"status.py", "promote.py", "smoke.py", "staging.py", "alertsources.py", "secret.py", "appship_sched.py",
                                "gitops.py", "compose.py"} <= names
    assert "model.py" not in names


def test_the_model_is_where_the_environments_and_pins_live_ac_113_13():  # AC-113.13
    src = CPLAT / "model.py"
    assert src.is_file(), "scripts/cplat/model.py does not exist"
    rules = {r for r, _ in findings(src.read_text())}
    assert {"environment list", "overlay pin (newTag)", "overlay pin path"} <= rules


def test_no_other_module_defines_its_own_environment_list_or_reads_a_pin_ac_113_13():  # AC-113.13
    bad = []
    for path in modules():
        for rule, line in findings(path.read_text()):
            bad.append(f"{path.relative_to(ROOT)}:{line}: {rule}")
    assert not bad, "environment lists and overlay pins belong to scripts/cplat/model.py:\n" + "\n".join(bad)


# ---------------- AC-113.12: the existing tests are not changed ----------------

def _git(*args: str) -> str | None:
    p = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return p.stdout if p.returncode == 0 else None


def test_no_existing_test_file_is_changed_ac_113_12():  # AC-113.12
    # spec 113's own commits only: its parent (after the 112 test changes) and its merge commit (later PRs may change tests)
    first, last = "8e8ea82", "d6bd290"
    if any(_git("cat-file", "-e", f"{c}^{{commit}}") is None for c in (first, last)):
        pytest.skip(f"commits {first}/{last} are not in this clone (shallow checkout)")
    diff = _git("diff", "--name-status", first, last, "--", "tests/")
    assert diff is not None
    changed = [ln for ln in diff.splitlines() if ln and ln[0] in "MDR"]
    assert changed == [], "existing test files must not change in this spec:\n" + "\n".join(changed)
