"""Spec 103: `cplat validate plan|run|final` (change-aware validation in the inner loop). Tiny git repos in tmp_path, a fake
`devbox` on PATH that logs its arguments; no network, no real tool run."""
import json
import os
import re
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import core
import runs
import ship
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)
from test_runs_usage_bench import benchmark_records, world  # noqa: F401  (fixtures)
from usage_support import projects  # noqa: F401  (fixture)

COPIER = "_src_path: gh:ika100/sdlc-foundry/templates/{shape}\nproject_name: demo\n"
DEVBOX = {"shell": {"scripts": {"lint": "ruff check .", "test": "pytest --cov", "test-fast": "pytest -x",
                                 "security": "bandit -r src", "ci": "devbox run lint && devbox run test && devbox run security"}}}
SPEC = """---
spec_id: 900-x
title: X
status: approved
priority: P1
shape: service-python
tracks: [1]
---

# 900 — X

## Problem

P.

## Acceptance criteria

- **AC-900.1** Given a, when b, then c.

## Non-goals

- none

## Open questions

None.

## Changelog

- 2026-10-01 created
"""
PLAN = """---
spec_id: 900-x
shape: service-python
spec_hash: {hash}
tasks:
  - {{id: t1, title: mod, files: [src/pkg/mod.py], covers: [AC-900.1], parallel_safe: true, depends_on: []}}
---

## t1 — mod
"""
LOGMARK = "LOGMARKER-8f3a"


def git(repo, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=repo, check=True,
                          capture_output=True, text=True).stdout


def write(repo, files):
    for rel, text in files.items():
        p = Path(repo) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


def make_repo(root, shape="service-python"):
    repo = Path(root) / "demo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    import spec as specmod
    d = repo / "docs" / "specs" / "900-x"
    d.mkdir(parents=True)
    (d / "spec.md").write_text(SPEC)
    write(repo, {
        ".copier-answers.yml": COPIER.format(shape=shape),
        "devbox.json": json.dumps(DEVBOX), "devbox.lock": "{}", "pyproject.toml": "[project]\nname='demo'\n", "uv.lock": "v1\n",
        "src/pkg/__init__.py": "", "src/pkg/mod.py": "def f():\n    return 1\n", "src/pkg/other.py": "def g():\n    return 2\n",
        "tests/test_mod.py": "def test_f():\n    assert 1\n", "tests/test_other.py": "def test_g():\n    assert 1\n",
        "tests/test_acc.py": "def test_criterion():  # AC-900.1\n    assert 1\n",
        "README.md": "# demo\n", "docs/guide.md": "guide\n",
        "docs/specs/900-x/plan.md": PLAN.format(hash=specmod.read(d).ac_hash()),
    })
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "init")
    git(repo, "switch", "-q", "-c", "work")
    return repo


@pytest.fixture()
def env(tmp_path, monkeypatch, store, clock):  # noqa: F811
    """A service-python repo as cwd, a fake devbox on PATH (log in DEVBOX_LOG; DEVBOX_FAIL=<substring> makes a call red), a run."""
    repo = make_repo(tmp_path)
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    log = tmp_path / "devbox.log"
    log.write_text("")
    fake = bin_ / "devbox"
    fake.write_text(f'#!/bin/sh\necho "$@" >> "{log}"\necho {LOGMARK}\n'
                    'if [ -n "$DEVBOX_FAIL" ] && echo "$*" | grep -q "$DEVBOX_FAIL"; then exit 1; fi\nexit 0\n')
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.delenv("DEVBOX_FAIL", raising=False)
    monkeypatch.delenv("CPLAT_VALIDATION", raising=False)
    monkeypatch.chdir(repo)
    rid = runs.start("build", repo="acme/demo")
    monkeypatch.setenv("CPLAT_RUN_PARENT", rid)
    return SimpleNamespace(repo=repo, log=log, rid=rid, tmp=tmp_path, mp=monkeypatch)


def calls(env):
    return [ln for ln in env.log.read_text().splitlines() if ln.strip()]


def plan(capsys, *args):
    import validate
    capsys.readouterr()
    assert validate.main(["plan", "--base", "main", "--json", *args]) == 0
    return json.loads(capsys.readouterr().out)


def by_name(p):
    return {c["name"]: c for c in p["checks"]}


def vrun(*args):
    import validate
    return validate.main(["run", "--base", "main", *args])


def section(env):
    return runs.active(env.rid)["validation"]


def evidence(env):
    common = git(env.repo, "rev-parse", "--git-common-dir").strip()
    return (env.repo / common if not os.path.isabs(common) else Path(common)) / "cplat-evidence"


def mapped_change(env):
    write(env.repo, {"src/pkg/mod.py": "def f():\n    return 11\n"})


# ---------------- AC-103.1 ----------------

def test_the_plan_lists_every_check_with_decision_rule_reason_and_is_deterministic(env, capsys):
    """AC-103.1: every check of the repo is run/reused/skipped with a rule and a reason; the same input gives the same plan."""
    mapped_change(env)
    p = plan(capsys)
    names = by_name(p)
    assert {"lint", "test", "security"} <= set(names)
    for c in p["checks"]:
        assert c["decision"] in ("run", "reused", "skipped")
        assert isinstance(c["rule"], str) and c["rule"] and isinstance(c["reason"], str) and c["reason"]
    assert "src/pkg/mod.py" in p["files"] and p["base"]
    assert plan(capsys) == p


def test_validate_is_a_cplat_command(env, capsys):
    """AC-103.1: `cplat validate plan` is reachable through the cplat launcher."""
    import cplat
    mapped_change(env)
    assert cplat.main(["validate", "plan", "--base", "main", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["checks"]


# ---------------- AC-103.2 ----------------

def test_a_mapped_change_runs_the_criterions_tests_and_the_components_unit_tests(env, capsys):
    """AC-103.2: a change to a declared component runs the tests naming its criteria plus its unit tests, not the rest."""
    mapped_change(env)
    c = by_name(plan(capsys))
    assert c["acceptance"]["decision"] == "run" and c["acceptance"]["rule"] == "mapped"
    assert "tests/test_acc.py" in c["acceptance"]["targets"]
    assert c["test"]["decision"] == "run" and c["test"]["rule"] == "mapped"
    assert "tests/test_mod.py" in c["test"]["targets"] and "tests/test_other.py" not in c["test"]["targets"]
    assert c["lint"]["decision"] == "run" and c["security"]["decision"] == "run"


def test_a_docs_only_change_skips_tests_and_still_runs_lint(env, capsys):
    """AC-103.2: only documentation changed: tests skipped, lint runs."""
    write(env.repo, {"README.md": "# demo\nmore\n", "docs/guide.md": "guide 2\n"})
    c = by_name(plan(capsys))
    assert c["lint"]["decision"] == "run"
    for name in ("test", "acceptance"):
        assert c[name]["decision"] == "skipped" and c[name]["rule"] == "docs-only"


# ---------------- AC-103.3 ----------------

MANDATORY = [
    ("service-python", "Dockerfile"), ("service-python", "uv.lock"), ("service-python", "pyproject.toml"),
    ("service-python", "package.json"), ("service-python", "pnpm-lock.yaml"), ("service-python", ".github/workflows/ci.yml"),
    ("service-python", ".secrets.baseline.json"), ("service-python", "src/pkg/auth.py"),
    ("service-python", "docs/specs/900-x/spec.md"), ("service-python", "tests/test_acc.py"),
    ("service-python", "migrations/0001_init.sql"), ("service-python", "src/pkg/openapi.yaml"), ("service-python", "src/pkg/api/items.py"),
    ("gitops-app", "environments/prod/values.yaml"),
    ("web-nextjs", "next.config.js"), ("web-nextjs", "app/items/page.tsx"),
]


@pytest.mark.parametrize("shape,path", MANDATORY)
def test_mandatory_categories_force_full_tests_and_security_even_with_low_risk(tmp_path, monkeypatch, capsys, shape, path):
    """AC-103.3: a Dockerfile / manifest / lock / workflow / secrets / spec / acceptance-test change, and the per-shape categories,
    run the full test suite and the security scan whatever the reported risk."""
    repo = make_repo(tmp_path, shape)
    monkeypatch.chdir(repo)
    write(repo, {path: (repo / path).read_text() + "\n# changed\n" if (repo / path).exists() else "changed\n"})
    c = by_name(plan(capsys, "--risk", "low"))
    for name in ("test", "security"):
        assert c[name]["decision"] == "run", name
        assert c[name]["rule"].startswith("mandatory:"), (name, c[name]["rule"])
    assert c["test"]["targets"] is None


def test_shapes_declare_the_validation_selector_and_mandatory_globs():
    """AC-103.3: shapes.yml has validation.selector (pytest for python shapes, vitest for web) and mandatory globs per shape."""
    shapes = {s["id"]: s for s in core.registry.load()}
    assert shapes["service-python"]["validation"]["selector"] == "pytest"
    assert shapes["library-python"]["validation"]["selector"] == "pytest"
    assert shapes["web-nextjs"]["validation"]["selector"] == "vitest"
    for sid in ("service-python", "gitops-app", "web-nextjs"):
        mandatory = shapes[sid]["validation"]["mandatory"]
        assert mandatory and all(globs for globs in mandatory.values())


# ---------------- AC-103.4 ----------------

def assert_full_no_rule(p):
    assert p["checks"]
    for c in p["checks"]:
        assert c["decision"] == "run" and c["rule"] == "no rule", c


def test_an_unmapped_file_runs_the_full_set_with_reason_no_rule(env, capsys):
    """AC-103.4: a changed file nothing maps: every check runs, rule `no rule`."""
    write(env.repo, {"src/pkg/new.py": "x = 1\n"})
    assert_full_no_rule(plan(capsys))


def test_an_unreadable_diff_runs_the_full_set(env, capsys):
    """AC-103.4: a base ref that does not resolve: full default set, `no rule`, no failure."""
    import validate
    capsys.readouterr()
    assert validate.main(["plan", "--base", "no-such-ref", "--json"]) == 0
    assert_full_no_rule(json.loads(capsys.readouterr().out))


def test_a_missing_plan_runs_the_full_set(env, capsys):
    """AC-103.4: missing mapping data (no plan.md): full default set, `no rule`."""
    (env.repo / "docs/specs/900-x/plan.md").unlink()
    git(env.repo, "commit", "-qam", "drop plan")
    mapped_change(env)
    assert_full_no_rule(plan(capsys))


# ---------------- AC-103.5 ----------------

def test_a_high_risk_level_only_adds_checks_and_is_noted(env, capsys):
    """AC-103.5: risk high adds checks and removes none; the plan records the level and a note."""
    mapped_change(env)
    low, high = plan(capsys, "--risk", "low"), plan(capsys, "--risk", "high")
    assert low["risk"]["added"] == [] and high["risk"]["added"]
    assert high["risk"]["level"] == "high" and high["risk"]["note"]
    for name, c in by_name(low).items():
        if c["decision"] == "run":
            assert by_name(high)[name]["decision"] == "run"


def test_a_low_risk_never_removes_a_required_check_and_the_plan_says_so(env, capsys):
    """AC-103.5: low risk on a mandatory change is ignored, and the plan notes that."""
    write(env.repo, {"Dockerfile": "FROM python\n"})
    p = plan(capsys, "--risk", "low")
    assert by_name(p)["test"]["decision"] == "run" and by_name(p)["security"]["decision"] == "run"
    assert "ignored" in p["risk"]["note"].lower()


# ---------------- AC-103.6 ----------------

def test_a_passed_check_with_byte_identical_inputs_is_reused_and_names_its_run(env, capsys):
    """AC-103.6: after a green run, the same inputs give `reused` with the run it comes from; evidence stays in the git dir."""
    mapped_change(env)
    assert vrun() == 0
    d = evidence(env)
    assert d.is_dir() and json.loads((d / "test.json").read_text())["result"] == "passed"
    assert "cplat-evidence" not in git(env.repo, "ls-files", "-o")
    c = by_name(plan(capsys))
    for name in ("test", "acceptance"):
        assert c[name]["decision"] == "reused" and c[name]["from_run"] == env.rid


def test_a_changed_input_runs_the_check_again(env, capsys):
    """AC-103.6: a source file changed after the evidence: the check runs and the old pass does not count."""
    mapped_change(env)
    assert vrun() == 0
    write(env.repo, {"src/pkg/mod.py": "def f():\n    return 12\n"})
    assert by_name(plan(capsys))["test"]["decision"] == "run"


def test_a_changed_tool_version_runs_the_check_again(env, capsys):
    """AC-103.6: devbox.lock (the tool versions) changed: no reuse."""
    mapped_change(env)
    assert vrun() == 0
    write(env.repo, {"devbox.lock": '{"packages": "new"}'})
    assert by_name(plan(capsys))["test"]["decision"] == "run"


@pytest.mark.parametrize("damage", ["failed", "skipped", "missing", "garbage"])
def test_failed_skipped_missing_or_unreadable_evidence_is_not_a_pass(env, capsys, damage):
    """AC-103.6: a failed, skipped, missing or unreadable earlier result is never reused."""
    mapped_change(env)
    assert vrun() == 0
    f = evidence(env) / "test.json"
    if damage == "missing":
        f.unlink()
    elif damage == "garbage":
        f.write_text("{not json")
    else:
        rec = json.loads(f.read_text())
        rec["result"] = damage
        f.write_text(json.dumps(rec))
    assert by_name(plan(capsys))["test"]["decision"] == "run"


def test_a_red_run_leaves_no_passing_evidence(env, capsys):
    """AC-103.6: a check that failed is run again next time."""
    mapped_change(env)
    env.mp.setenv("DEVBOX_FAIL", "test")
    assert vrun() == 1
    env.mp.delenv("DEVBOX_FAIL")
    assert by_name(plan(capsys))["test"]["decision"] == "run"


# ---------------- AC-103.7 ----------------

def test_the_run_record_holds_a_validation_section_without_logs(env, capsys):
    """AC-103.7: the run record gets checks (decision, rule, reason) and counts per decision, and no log output."""
    write(env.repo, {"README.md": "# demo\nmore\n"})
    assert vrun() == 0
    v = section(env)
    names = {c["name"]: c for c in v["checks"]}
    assert names["test"]["decision"] == "skipped" and names["test"]["rule"] == "docs-only" and names["test"]["reason"]
    assert names["lint"]["decision"] == "run"
    assert v["counts"] == {d: sum(c["decision"] == d for c in v["checks"]) for d in ("run", "reused", "skipped")}
    assert v["misses"] == []
    assert LOGMARK not in json.dumps(v)
    out = capsys.readouterr().out
    assert "lint" in out and "skipped" in out


def test_runs_report_shows_counts_per_rule(env, store, capsys):  # noqa: F811
    """AC-103.7: `cplat runs report` prints the decision counts per rule."""
    mapped_change(env)
    assert vrun() == 0
    runs.finish(env.rid, "done")
    capsys.readouterr()
    assert runs.main(["report"]) == 0
    out = capsys.readouterr().out
    assert any("mapped" in ln and "run" in ln for ln in out.splitlines()), out


# ---------------- AC-103.8 ----------------

def test_the_loop_never_runs_the_whole_ci_script(env):
    """AC-103.8: `validate run` runs the selected checks only; `devbox run ci` stays with the final gate."""
    mapped_change(env)
    assert vrun() == 0
    assert calls(env) and not any(re.match(r"run ci\b", ln) for ln in calls(env))


def test_ship_run_ci_runs_the_full_ci_whatever_the_loop_skipped(env, monkeypatch):
    """AC-103.8: `ship.run_ci` before a push runs the whole `devbox run ci`, also after a docs-only loop plan."""
    write(env.repo, {"README.md": "# demo\nmore\n"})
    assert vrun() == 0
    seen = []
    monkeypatch.setattr(ship, "run", lambda cmd, **kw: seen.append(list(cmd)) or SimpleNamespace(returncode=0, stdout="", stderr=""))
    ship.run_ci(env.repo)
    assert ["devbox", "run", "ci"] in seen


# ---------------- AC-103.9 ----------------

def test_full_flag_runs_every_check_and_says_why(env, capsys):
    """AC-103.9: --full: every check runs under rule `full`, the reason names the flag."""
    write(env.repo, {"README.md": "# demo\nmore\n"})
    p = plan(capsys, "--full")
    for c in p["checks"]:
        assert c["decision"] == "run" and c["rule"] == "full" and "--full" in c["reason"]


def test_the_repo_can_opt_out_in_its_settings(env, capsys):
    """AC-103.9: `validation: full` in .platform-settings.yml runs everything and says so."""
    write(env.repo, {".platform-settings.yml": "validation: full\n", "README.md": "# demo\nmore\n"})
    p = plan(capsys)
    for c in p["checks"]:
        assert c["decision"] == "run" and c["rule"] == "full" and "settings" in c["reason"].lower()


def test_selective_is_the_default_and_the_env_switch_forces_full(env, capsys):
    """AC-103.9: selective by default; CPLAT_VALIDATION=full (used by the benchmark) forces the full plan."""
    write(env.repo, {"README.md": "# demo\nmore\n"})
    assert by_name(plan(capsys))["test"]["decision"] == "skipped"
    env.mp.setenv("CPLAT_VALIDATION", "full")
    assert by_name(plan(capsys))["test"]["rule"] == "full"


# ---------------- AC-103.10 ----------------

def final(*args):
    import validate
    return validate.main(["final", *args])


def test_a_skipped_check_failing_in_the_final_gate_counts_a_miss_for_its_rule(env, store, capsys):  # noqa: F811
    """AC-103.10: skipped in the loop, red in the final gate: one miss for the deciding rule; the report shows it."""
    write(env.repo, {"README.md": "# demo\nmore\n"})
    assert vrun() == 0
    assert final("--check", "test", "failed") == 0
    assert section(env)["misses"] == [{"check": "test", "rule": "docs-only"}]
    runs.finish(env.rid, "done")
    capsys.readouterr()
    assert runs.main(["report"]) == 0
    assert any("docs-only" in ln and re.search(r"miss\w*\D*1", ln, re.I) for ln in capsys.readouterr().out.splitlines())


def test_a_reused_check_failing_in_the_final_gate_counts_a_miss(env):
    """AC-103.10: reused in the loop, red in the final gate: a miss for the rule that decided it."""
    mapped_change(env)
    assert vrun() == 0
    assert vrun() == 0
    rule = {c["name"]: c for c in section(env)["checks"]}["test"]["rule"]
    assert {c["name"]: c for c in section(env)["checks"]}["test"]["decision"] == "reused"
    assert final("--check", "test", "failed") == 0
    assert section(env)["misses"] == [{"check": "test", "rule": rule}]


def test_a_passing_or_a_run_check_is_no_miss(env):
    """AC-103.10: a skipped check that passes, or a check that ran in the loop and fails, counts no miss."""
    write(env.repo, {"README.md": "# demo\nmore\n"})
    assert vrun() == 0
    final("--check", "test", "passed")
    final("--check", "lint", "failed")
    assert section(env)["misses"] == []


# ---------------- AC-103.11 ----------------

@pytest.fixture()
def compare(world, monkeypatch):  # noqa: F811
    """The benchmark's fake headless run also records a child build run whose validation section depends on the mode."""
    import headless
    inner = headless.main
    seen = SimpleNamespace(envs=[], security="run")

    def fake(argv):
        full = os.environ.get("CPLAT_VALIDATION") == "full"
        seen.envs.append(os.environ.get("CPLAT_VALIDATION"))
        code = inner(argv)
        rid = runs.start("build", repo="ika100/todo-api")
        decision = "run" if full else seen.security
        checks = [{"name": "test", "decision": "run", "rule": "mapped", "reason": "x"},
                  {"name": "security", "decision": decision, "rule": "mandatory:lockfile", "reason": "x"}]
        runs.set_section(rid, "validation", {"base": "main", "checks": checks, "misses": [],
                                             "counts": {"run": sum(c["decision"] == "run" for c in checks), "reused": 0,
                                                        "skipped": sum(c["decision"] == "skipped" for c in checks)}})
        runs.finish(rid, "done")
        return code
    monkeypatch.setattr(headless, "main", fake)
    monkeypatch.delenv("CPLAT_VALIDATION", raising=False)
    return seen


def test_compare_validation_runs_twice_reports_both_and_records_them(compare, store, capsys):  # noqa: F811
    """AC-103.11: the task runs with selection on and again with CPLAT_VALIDATION=full; both are reported and recorded."""
    assert runs.main(["benchmark", "quick-task", "--compare-validation"]) == 0
    assert compare.envs.count("full") >= 1 and compare.envs.count(None) + compare.envs.count("") >= 1
    (r,) = benchmark_records(store)
    text = json.dumps(r["benchmark"]["validation_compare"]).lower()
    assert all(w in text for w in ("duration", "tokens", "cost", "mapped"))
    assert "full" in capsys.readouterr().out.lower()


def test_compare_validation_fails_when_a_required_check_did_not_run(compare, store, capsys):  # noqa: F811
    """AC-103.11: a check that a rule requires was skipped in the change-aware run: non-zero exit, still recorded."""
    compare.security = "skipped"
    assert runs.main(["benchmark", "quick-task", "--compare-validation"]) != 0
    (r,) = benchmark_records(store)
    assert r["benchmark"]["validation_compare"]
