"""Spec 086: the repo-owned `ci-extra` recipe and CI check, doctor's view of it, the shape contract, the notes file and CLAUDE.md section."""
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

import core
import gates
import newsvc
from test_ci_gates import recipe, workflow
from test_gates import by_name
from test_spec_driven import IDS, SHAPES, claude_md, template

ROOT = core.PLATFORM_ROOT
STEP = "if grep -qs '\"ci-extra\"[[:space:]]*:' devbox.json; then devbox run ci-extra; fi"


def ci_cmd(shape):
    """The decoded `ci` recipe of a template."""
    return json.loads(f'"{recipe(shape, "ci")}"')


def run_ci(shape, tmp_path, *, recipes, fail=None):
    """Run the template's `ci` under bash with a stub `devbox` that records `devbox run <name>` and fails `fail`."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    stub = bindir / "devbox"
    stub.write_text('#!/bin/bash\necho "$2" >> "$STUB_LOG"\n[ "$2" = "$STUB_FAIL" ] && exit 1\nexit 0\n')
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    (work / "devbox.json").write_text(json.dumps({"shell": {"scripts": recipes}}))
    log = tmp_path / "log"
    log.write_text("")
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "STUB_LOG": str(log), "STUB_FAIL": fail or "-"}
    rc = subprocess.run(["bash", "-c", ci_cmd(shape)], cwd=work, env=env, capture_output=True).returncode
    return rc, log.read_text().split()


def template_gates(shape):
    return re.findall(r"devbox run ([\w-]+)", ci_cmd(shape).split(" && if grep")[0])


# ---------------- ci recipe: AC-086.1, .2 ----------------

@pytest.mark.parametrize("shape", IDS)
def test_ci_runs_the_gates_then_ci_extra_and_stops_on_a_red_gate(shape, tmp_path):  # AC-086.1
    gates_ = template_gates(shape)
    rc, ran = run_ci(shape, tmp_path, recipes={"ci-extra": "devbox run chart-lint"})
    assert rc == 0 and ran == [*gates_, "ci-extra"]
    rc, ran = run_ci(shape, tmp_path, recipes={"ci-extra": "devbox run chart-lint"}, fail="ci-extra")
    assert rc != 0 and ran[-1] == "ci-extra"
    rc, ran = run_ci(shape, tmp_path, recipes={"ci-extra": "devbox run chart-lint"}, fail=gates_[-1])
    assert rc != 0 and "ci-extra" not in ran


@pytest.mark.parametrize("shape", IDS)
def test_ci_without_ci_extra_runs_exactly_the_template_gates(shape, tmp_path):  # AC-086.2
    assert ci_cmd(shape).endswith(" && " + STEP)             # the exact step of the design contract
    gates_ = template_gates(shape)
    rc, ran = run_ci(shape, tmp_path, recipes={"quality": "x"})
    assert rc == 0 and ran == gates_
    rc, ran = run_ci(shape, tmp_path, recipes={"quality": "x"}, fail=gates_[0])
    assert rc != 0


def test_the_step_is_the_same_in_gates_and_shapes():  # AC-086.2
    import shapes
    assert gates.CI_EXTRA_STEP == shapes.CI_EXTRA_STEP == STEP and gates.CI_EXTRA == "ci-extra"


@pytest.mark.parametrize("shape", IDS)
def test_no_template_defines_ci_extra(shape):  # AC-086.4
    text = (template(shape) / "devbox.json") if (template(shape) / "devbox.json").is_file() else template(shape) / "devbox.json.jinja"
    assert not re.search(r'"ci-extra"\s*:', text.read_text())
    assert recipe(shape, "ci")                               # and ci exists, ending with the step
    assert ci_cmd(shape).endswith(STEP)


# ---------------- CI workflow: AC-086.3 ----------------

@pytest.mark.parametrize("shape", IDS)
def test_workflow_has_a_ci_extra_check(shape, tmp_path):  # AC-086.3
    jobs = workflow(shape)["jobs"]
    job = jobs.get("ci-extra")
    assert job is not None and job["name"] == "ci-extra" and "needs" not in job and "if" not in job
    runs = [s for s in job["steps"] if str(s.get("run", "")).strip() == "devbox run ci-extra"]
    assert runs and "steps.recipe.outputs.defined == 'true'" in runs[0]["if"]
    entry = next(s for s in SHAPES if s["id"] == shape)
    assert "ci-extra" in entry["ci_checks"]
    detect = next(s for s in job["steps"] if s.get("id") == "recipe")["run"]
    out = tmp_path / "out"
    for body, expect in (('{"shell": {"scripts": {"ci-extra": "devbox run chart-lint"}}}', "defined=true"),
                         ('{"shell": {"scripts": {"ci": "x"}}}', "defined=false")):
        (tmp_path / "devbox.json").write_text(body)
        out.write_text("")
        p = subprocess.run(["bash", "-c", detect], cwd=tmp_path, env={**os.environ, "GITHUB_OUTPUT": str(out)}, capture_output=True, text=True)
        assert p.returncode == 0 and out.read_text().strip() == expect
        if expect == "defined=false":
            assert "::notice::" in p.stdout and "no ci-extra recipe" in p.stdout


# ---------------- doctor: AC-086.7 .. .9 ----------------

def repo_with(tmp_path, *, ci, extra, wf):
    r = tmp_path / "svc"
    (r / ".github" / "workflows").mkdir(parents=True)
    scripts = {"quality": "ruff", "test": "pytest", "security": "devbox run secrets-scan", "secrets-scan": "x", "secrets-baseline": "x", "ci": ci}
    if extra is not None:
        scripts["ci-extra"] = extra
    (r / "devbox.json").write_text(json.dumps({"packages": [], "shell": {"scripts": scripts}}))
    jobs = {g: {"steps": [{"run": f"devbox run {g}"}]} for g in wf}
    (r / ".github" / "workflows" / "ci.yml").write_text(json.dumps({"jobs": jobs}))
    return r


BASE = "devbox run quality && devbox run test && devbox run security"


@pytest.mark.parametrize("extra, shown", [("devbox run chart-lint", "chart-lint"), ("helm lint .", "helm lint .")])
def test_doctor_shows_what_ci_extra_runs(tmp_path, extra, shown):  # AC-086.7
    r = repo_with(tmp_path, ci=f"{BASE} && {STEP}", extra=extra, wf=["quality", "test", "security", "ci-extra"])
    c = by_name(gates.check_gates(r))["gate ci = CI workflow"]
    assert c["status"] == "ok" and c["detail"] == f"quality → test → security → ci-extra ({shown})"
    assert gates.chain(f"{BASE} && devbox run ci-extra") == ["quality", "test", "security", "ci-extra"]


def test_doctor_warns_when_ci_does_not_run_ci_extra(tmp_path):  # AC-086.8
    r = repo_with(tmp_path, ci=BASE, extra="devbox run chart-lint", wf=["quality", "test", "security"])
    c = by_name(gates.check_gates(r))["gate ci = CI workflow"]
    assert c["status"] == "warn" and "CI does not run ci-extra" in c["detail"] and "/platform:update" in c["fix"]


@pytest.mark.parametrize("extra, line", [
    (None, '"ci-extra": "devbox run chart-lint"'),
    ("devbox run helm-docs", '"ci-extra": "devbox run helm-docs && devbox run chart-lint"')])
def test_doctor_points_extra_ci_gates_to_ci_extra(tmp_path, extra, line):  # AC-086.9
    r = repo_with(tmp_path, ci=f"{BASE} && devbox run chart-lint", extra=extra, wf=["quality", "test", "security", *(["ci-extra"] if extra else [])])
    c = by_name(gates.check_gates(r))["gate ci = CI workflow"]
    assert c["status"] == "warn" and "move chart-lint into ci-extra" in c["fix"] and line in c["fix"]


# ---------------- shape contract: AC-086.5 ----------------

@pytest.fixture()
def broken_root(tmp_path, monkeypatch):
    import shapes
    entry = next(s for s in shapes.load() if s["id"] == "service-go")
    shutil.copytree(ROOT / "templates" / entry["template"], tmp_path / "templates" / entry["template"])
    for extra in ("scripts", "plugins"):
        shutil.copytree(ROOT / extra, tmp_path / extra, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(ROOT / "shapes.yml", tmp_path / "shapes.yml")
    monkeypatch.setattr(shapes, "ROOT", tmp_path)
    return shapes, entry, tmp_path / "templates" / entry["template"]


def new_errors(shapes, entry, tdir, edit):
    before = set(shapes.check_contract([entry]))
    edit(tdir)
    return set(shapes.check_contract([entry])) - before


def test_shape_check_rejects_a_template_that_defines_ci_extra(broken_root):  # AC-086.5
    shapes, entry, tdir = broken_root
    f = tdir / "devbox.json.jinja"
    errs = new_errors(shapes, entry, tdir, lambda t: f.write_text(f.read_text().replace('"ci":', '"ci-extra": "echo x",\n      "ci":', 1)))
    assert any("devbox.json defines ci-extra" in e for e in errs), errs


def test_shape_check_rejects_a_ci_that_does_not_end_with_the_step(broken_root):  # AC-086.5
    shapes, entry, tdir = broken_root
    f = tdir / "devbox.json.jinja"
    errs = new_errors(shapes, entry, tdir, lambda t: f.write_text(f.read_text().replace(" && " + STEP.replace('"', '\\"'), "")))
    assert any("the ci recipe must end with" in e for e in errs), errs


def test_shape_check_rejects_a_workflow_without_the_ci_extra_check(broken_root):  # AC-086.5
    shapes, entry, tdir = broken_root
    f = tdir / ".github" / "workflows" / "ci.yml"

    def drop(_):
        f.write_text(re.sub(r"^  ci-extra:\n(?:(?!  \S).*\n)*", "", f.read_text(), flags=re.M))
    errs = new_errors(shapes, entry, tdir, drop)
    assert any("ci.yml has no ci-extra job running devbox run ci-extra" in e for e in errs), errs


def test_cplat_shape_check_runs_the_shape_checks(capsys):  # AC-086.5
    import shapecmd
    assert shapecmd.main(["check"]) == 0
    assert "OK" in capsys.readouterr().out


def test_the_real_templates_meet_the_ci_extra_contract():  # AC-086.5
    import shapes
    assert shapes.check_contract(core.registry.load()) == []
    assert shapes.CI_EXTRA_STEP == STEP


# ---------------- notes file and CLAUDE.md: AC-086.15, .16 ----------------

SECTION_NAMES = ("ci-extra", "devbox.json", ".claude/settings.json", ".github/workflows/", ".claude/project-notes.md")


@pytest.mark.parametrize("shape", IDS)
def test_template_claude_md_says_where_additions_go(shape):  # AC-086.15
    text = claude_md(shape)
    assert "## Where your additions go" in text
    section = text.split("## Where your additions go", 1)[1].split("\n## ", 1)[0]
    for name in SECTION_NAMES:
        assert name in section, f"{shape}: {name}"


@pytest.mark.parametrize("shape", IDS)
def test_template_loads_an_empty_repo_owned_notes_file(shape):  # AC-086.16
    t = template(shape)
    assert (t / ".claude" / "project-notes.md").is_file() and (t / ".claude" / "project-notes.md").stat().st_size == 0
    assert ".claude/project-notes.md" in yaml.safe_load((t / "copier.yml").read_text())["_skip_if_exists"]
    text = claude_md(shape)
    assert re.search(r"^@\.claude/project-notes\.md$", text, re.M)
    assert text.rstrip().splitlines()[-1] == "@.claude/project-notes.md" and "## Project notes" in text


@pytest.mark.parametrize("shape", IDS)
def test_a_new_repo_has_the_section_and_an_empty_notes_file(shape, tmp_path):  # AC-086.15 AC-086.16
    newsvc.main([f"n-{shape}", "d", "--shape", shape, "--no-github", "--skip-tasks", "--dir", str(tmp_path), "--org", "acme"])
    repo = tmp_path / f"n-{shape}"
    notes = repo / ".claude" / "project-notes.md"
    assert notes.is_file() and notes.stat().st_size == 0
    text = (repo / "CLAUDE.md").read_text()
    assert "## Where your additions go" in text and re.search(r"^@\.claude/project-notes\.md$", text, re.M)
