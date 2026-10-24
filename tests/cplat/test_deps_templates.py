"""Spec 095: the deps-findings / deps-bump recipes of every template, the shape contract that requires them, and the prose of
/svc:build, /svc:ship and the security agent that calls `cplat deps`."""
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

import core

ROOT = core.PLATFORM_ROOT
TEMPLATES = ROOT / "templates"
SHAPES = ["service-python", "library-python", "service-java", "service-go", "web-nextjs"]
FINDINGS = r'"deps-findings":\s*"bash scripts/deps\.sh findings"'
BUMP = r'"deps-bump":\s*"bash scripts/deps\.sh bump"'


def devbox_file(template):
    for name in ("devbox.json", "devbox.json.jinja"):
        if (TEMPLATES / template / name).is_file():
            return TEMPLATES / template / name
    raise AssertionError(f"{template} has no devbox.json")


# ---------------- AC-095.3: the recipes exist in every template ----------------

@pytest.mark.parametrize("template", SHAPES)
def test_every_template_has_both_recipes_and_the_script(template):  # AC-095.3
    text = devbox_file(template).read_text()
    assert re.search(FINDINGS, text), f"{template}: no deps-findings recipe"
    assert re.search(BUMP, text), f"{template}: no deps-bump recipe"
    assert (TEMPLATES / template / "scripts" / "deps.sh").is_file()


def test_the_ci_and_security_recipes_are_unchanged_by_the_deps_recipes():  # AC-095.3
    for template in SHAPES:
        text = devbox_file(template).read_text()
        assert "devbox run deps" not in text.split('"ci"', 1)[1].split("\n", 1)[0], template  # the gate chain never calls the bump


def test_the_python_templates_ship_the_same_scripts_and_no_jinja_syntax():  # AC-095.3
    a, b = TEMPLATES / "service-python" / "scripts", TEMPLATES / "library-python" / "scripts"
    for name in ("deps.sh", "deps_pyproject.py"):
        assert (a / name).read_bytes() == (b / name).read_bytes(), name  # byte-identical
        text = (a / name).read_text()
        assert not any(tok in text for tok in ("{{", "{%", "{#")), f"{name} would be rendered by copier"


@pytest.mark.parametrize("template", ["gitops-app"])
def test_gitops_app_has_neither_recipe(template):  # AC-095.16
    text = devbox_file(template).read_text()
    assert "deps-findings" not in text and "deps-bump" not in text
    assert not (TEMPLATES / template / "scripts" / "deps.sh").exists()


# ---------------- AC-095.3: a package the repo does not depend on ----------------

def stub_tools(tmp_path):
    bindir = tmp_path / "stubs"
    bindir.mkdir()
    marker = tmp_path / "tool-called"
    for tool in ("uv", "pnpm", "go", "java", "npm", "pip-audit"):
        f = bindir / tool
        f.write_text(f'#!/bin/bash\necho "{tool} $*" >> "{marker}"\necho "stub {tool} must not run" >&2\nexit 99\n')
        f.chmod(f.stat().st_mode | stat.S_IEXEC)
    mvn = bindir / "mvn"  # `dependency:tree` lists nothing: the artifact is not a dependency
    mvn.write_text('#!/bin/bash\nexit 0\n')
    mvn.chmod(mvn.stat().st_mode | stat.S_IEXEC)
    return bindir, marker


REPOS = {
    "python": ("service-python", {
        "pyproject.toml": '[project]\nname = "app"\nversion = "0"\ndependencies = ["requests>=2"]\n',
        "uv.lock": 'version = 1\n\n[[package]]\nname = "requests"\nversion = "2.31.0"\n\n[[package]]\nname = "foo-bar"\nversion = "1.0.0"\n'}),
    "python-no-lock": ("library-python", {"pyproject.toml": '[project]\nname = "app"\nversion = "0"\ndependencies = []\n'}),
    "web": ("web-nextjs", {
        "package.json": '{"dependencies": {"next": "14.2.0"}}\n',
        "pnpm-workspace.yaml": "allowBuilds:\n  unrs-resolver: true\n",
        "pnpm-lock.yaml": "lockfileVersion: '9.0'\n\npackages:\n\n  next@14.2.0:\n    resolution: {integrity: sha512-x}\n"}),
    "go": ("service-go", {
        "go.mod": "module example.com/app\n\ngo 1.22\n\nrequire github.com/go-chi/chi/v5 v5.0.0\n",
        "go.sum": "github.com/go-chi/chi/v5 v5.0.0 h1:abc=\ngithub.com/go-chi/chi/v5 v5.0.0/go.mod h1:def=\n"}),
    "java": ("service-java", {
        "pom.xml": '<project xmlns="http://maven.apache.org/POM/4.0.0"><modelVersion>4.0.0</modelVersion><groupId>g</groupId>'
                   '<artifactId>a</artifactId><version>1</version></project>\n'}),
}


def setup_repo(tmp_path, case):
    template, files = REPOS[case]
    work = tmp_path / "work"
    work.mkdir()
    shutil.copytree(TEMPLATES / template / "scripts", work / "scripts")
    for name, body in files.items():
        (work / name).write_text(body)
    return work


def snapshot(work):
    return {str(p.relative_to(work)): p.read_bytes() for p in sorted(work.rglob("*")) if p.is_file() and "scripts" not in p.relative_to(work).parts}


def bump(work, tmp_path, *args):
    bindir, marker = stub_tools(tmp_path) if not (tmp_path / "stubs").exists() else (tmp_path / "stubs", tmp_path / "tool-called")
    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"}
    proc = subprocess.run(["bash", "scripts/deps.sh", "bump", *args], cwd=work, env=env, capture_output=True, text=True, timeout=120)
    return proc, marker


@pytest.mark.parametrize("case,package", [("python", "not-a-dep"), ("python", "Not_A.Dep"), ("python-no-lock", "requests"), ("web", "left-pad"),
                                          ("go", "golang.org/x/text"), ("java", "org.nothing:here")])
def test_bumping_a_package_the_repo_does_not_depend_on_fails_and_changes_nothing(tmp_path, case, package):  # AC-095.3
    work = setup_repo(tmp_path, case)
    before = snapshot(work)
    proc, marker = bump(work, tmp_path, package, "1.2.3")
    assert proc.returncode == 2, (proc.returncode, proc.stderr)
    assert f"deps-bump: {package} is not a dependency of this repo" in proc.stderr
    assert snapshot(work) == before
    assert not marker.exists(), "the membership check must run before any tool"


@pytest.mark.parametrize("case", ["python", "web", "go", "java"])
def test_bump_without_arguments_prints_the_usage(tmp_path, case):  # AC-095.3
    work = setup_repo(tmp_path, case)
    proc, _ = bump(work, tmp_path)
    assert proc.returncode == 2 and "usage: devbox run deps-bump <package> <version>" in proc.stderr


def test_python_membership_uses_the_pep503_normalised_name(tmp_path):  # AC-095.3
    work = setup_repo(tmp_path, "python")
    proc, marker = bump(work, tmp_path, "Foo_Bar", "2.0.0")
    assert "is not a dependency" not in proc.stderr and marker.exists()  # `Foo_Bar` is the locked `foo-bar`: the tool is reached


# ---------------- AC-095.2: a transitive bump moves the lock (needs the real tool and the network) ----------------

def sh(cmd, cwd, **kw):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=600, **kw)


def lock_version(text, name):
    m = re.search(rf'name = "{re.escape(name)}"\nversion = "([^"]+)"', text)
    return m.group(1) if m else None


@pytest.mark.slow
@pytest.mark.skipif(not shutil.which("uv"), reason="needs uv")
@pytest.mark.parametrize("template", ["service-python", "library-python"])
def test_python_transitive_bump_moves_the_lock_and_touches_only_the_python_files(tmp_path, template):  # AC-095.2
    work = tmp_path / "work"
    work.mkdir()
    shutil.copytree(TEMPLATES / template / "scripts", work / "scripts")
    (work / "pyproject.toml").write_text('[project]\nname = "app"\nversion = "0.1.0"\nrequires-python = ">=3.11"\ndependencies = ["httpx>=0.27"]\n')
    if sh(["uv", "lock"], work).returncode or sh(["uv", "lock", "--upgrade-package", "idna==3.4"], work).returncode:
        pytest.skip("cannot resolve with uv (offline?)")
    assert lock_version((work / "uv.lock").read_text(), "idna") == "3.4"
    pyproject = (work / "pyproject.toml").read_text()
    proc = sh(["bash", "scripts/deps.sh", "bump", "idna", "3.7"], work)
    assert proc.returncode == 0, proc.stderr
    assert tuple(int(x) for x in lock_version((work / "uv.lock").read_text(), "idna").split(".")) >= (3, 7)
    after = (work / "pyproject.toml").read_text()
    assert after == pyproject or ("constraint-dependencies" in after and "httpx>=0.27" in after and "idna>=3.7" in after)
    assert not [p for p in work.iterdir() if p.name not in ("scripts", "pyproject.toml", "uv.lock", ".venv")]


@pytest.mark.slow
@pytest.mark.skipif(not shutil.which("go"), reason="needs go")
def test_go_transitive_bump_adds_one_indirect_require(tmp_path):  # AC-095.2
    work = tmp_path / "work"
    work.mkdir()
    shutil.copytree(TEMPLATES / "service-go" / "scripts", work / "scripts")
    (work / "go.mod").write_text("module example.com/app\n\ngo 1.22\n\nrequire golang.org/x/net v0.20.0\n")
    (work / "main.go").write_text('package main\n\nimport _ "golang.org/x/net/html/charset"\n\nfunc main() {}\n')
    if sh(["go", "mod", "tidy"], work).returncode:
        pytest.skip("cannot resolve with go (offline?)")
    proc = sh(["bash", "scripts/deps.sh", "bump", "golang.org/x/text", "v0.16.0"], work)
    assert proc.returncode == 0, proc.stderr
    mod = (work / "go.mod").read_text()
    assert len(re.findall(r"golang\.org/x/text v0\.(1[6-9]|[2-9]\d)\.\d+ // indirect", mod)) == 1
    assert "golang.org/x/net v0.20.0" in mod


@pytest.mark.slow
@pytest.mark.skipif(not shutil.which("pnpm"), reason="needs pnpm")
def test_pnpm_transitive_bump_adds_exactly_one_override(tmp_path):  # AC-095.2
    work = tmp_path / "work"
    work.mkdir()
    shutil.copytree(TEMPLATES / "web-nextjs" / "scripts", work / "scripts")
    (work / "package.json").write_text('{"name": "app", "version": "0.0.0", "dependencies": {"express": "4.18.2"}}\n')
    (work / "pnpm-workspace.yaml").write_text("allowBuilds: {}\n")
    if sh(["pnpm", "install", "--lockfile-only"], work).returncode:
        pytest.skip("cannot resolve with pnpm (offline?)")
    proc = sh(["bash", "scripts/deps.sh", "bump", "qs", "6.12.0"], work)
    assert proc.returncode == 0, proc.stderr
    ws = (work / "pnpm-workspace.yaml").read_text()
    assert ws.count("overrides:") == 1 and len(re.findall(r"^\s+qs: ['\"]?6\.12\.0", ws, re.M)) == 1
    assert "qs@6.12.0" in (work / "pnpm-lock.yaml").read_text()


@pytest.mark.slow
@pytest.mark.skipif(not (shutil.which("mvn") and shutil.which("java")), reason="needs mvn and java")
def test_maven_transitive_bump_adds_one_dependency_management_entry(tmp_path):  # AC-095.2
    work = tmp_path / "work"
    work.mkdir()
    shutil.copytree(TEMPLATES / "service-java" / "scripts", work / "scripts")
    (work / "pom.xml").write_text(
        '<project xmlns="http://maven.apache.org/POM/4.0.0"><modelVersion>4.0.0</modelVersion><groupId>g</groupId><artifactId>a</artifactId>'
        '<version>1</version><dependencies><dependency><groupId>org.apache.commons</groupId><artifactId>commons-text</artifactId>'
        '<version>1.10.0</version></dependency></dependencies></project>\n')
    if sh(["mvn", "-B", "-q", "dependency:resolve"], work).returncode:
        pytest.skip("cannot resolve with mvn (offline?)")
    proc = sh(["bash", "scripts/deps.sh", "bump", "org.apache.commons:commons-lang3", "3.14.0"], work)
    assert proc.returncode == 0, proc.stderr
    pom = (work / "pom.xml").read_text()
    assert pom.count("<dependencyManagement>") == 1 and pom.count("<artifactId>commons-lang3</artifactId>") == 1 and "3.14.0" in pom
    assert "<version>1.10.0</version>" in pom


# ---------------- AC-095.3 / AC-095.16: the shape contract ----------------

@pytest.fixture()
def contract_root(tmp_path, monkeypatch):
    import shapes

    def factory(shape_id):
        entry = next(s for s in shapes.load() if s["id"] == shape_id)
        shutil.copytree(ROOT / "templates" / entry["template"], tmp_path / "templates" / entry["template"], dirs_exist_ok=True)
        for extra in ("scripts", "plugins"):
            if not (tmp_path / extra).exists():
                shutil.copytree(ROOT / extra, tmp_path / extra, ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy(ROOT / "shapes.yml", tmp_path / "shapes.yml")
        monkeypatch.setattr(shapes, "ROOT", tmp_path)
        return shapes, entry, tmp_path / "templates" / entry["template"]
    return factory


def new_errors(shapes, entry, edit):
    before = set(shapes.check_contract([entry]))
    edit()
    return set(shapes.check_contract([entry])) - before


def test_the_contract_names_both_recipes():  # AC-095.3
    import shapes
    assert shapes.DEPS_RECIPES == ["deps-findings", "deps-bump"]


@pytest.mark.parametrize("shape_id", SHAPES)
@pytest.mark.parametrize("recipe", ["deps-findings", "deps-bump"])
def test_shape_check_rejects_a_template_without_a_deps_recipe(contract_root, shape_id, recipe):  # AC-095.3
    shapes, entry, tdir = contract_root(shape_id)
    f = devbox_file(entry["template"]).relative_to(TEMPLATES / entry["template"])
    f = tdir / f

    def drop():
        f.write_text(re.sub(rf'^.*"{recipe}".*\n', "", f.read_text(), flags=re.M))
    errs = new_errors(shapes, entry, drop)
    assert any(f"devbox.json missing deps recipe '{recipe}' (spec 095)" in e for e in errs), errs


def test_shape_check_rejects_a_template_without_the_script(contract_root):  # AC-095.3
    shapes, entry, tdir = contract_root("service-go")
    errs = new_errors(shapes, entry, lambda: (tdir / "scripts" / "deps.sh").unlink(missing_ok=True))
    assert any("deps.sh" in e for e in errs), errs


@pytest.mark.parametrize("recipe", ["deps-findings", "deps-bump"])
def test_shape_check_rejects_a_gitops_app_that_defines_a_deps_recipe(contract_root, recipe):  # AC-095.16
    shapes, entry, tdir = contract_root("gitops-app")
    f = tdir / "devbox.json"
    errs = new_errors(shapes, entry, lambda: f.write_text(f.read_text().replace('"scripts": {', f'"scripts": {{\n      "{recipe}": "echo x",', 1)))
    assert any(f"gitops-app: devbox.json must not define '{recipe}'" in e for e in errs), errs


# ---------------- prose: build, ship, security ----------------

def plugin(rel):
    return (ROOT / "plugins" / rel).read_text()


def section(text, heading):
    start = text.index(heading)
    nxt = re.search(r"^## ", text[start + len(heading):], re.M)
    return text[start:start + len(heading) + nxt.start()] if nxt else text[start:]


def test_build_calls_cplat_deps_patch_on_a_red_security_gate_and_acts_on_its_exit_code():  # AC-095.12
    text = plugin("svc/commands/build.md")
    assert "cplat deps patch" in text
    near = text[text.index("cplat deps patch"):][:1500]
    assert "ESCALATE" in near and "--cause" in near and "cplat ship escalate" in near and "cplat runs end --outcome escalated" in near
    assert "a CRITICAL finding stops the build" not in text


def test_build_never_hands_a_red_gate_after_a_bump_to_a_coder_and_keeps_acceptance_tests_fixed():  # AC-095.6
    text = plugin("svc/commands/build.md")
    near = text[text.index("cplat deps patch"):][:2000].lower()
    assert "coder" in near and "never" in near and "acceptance test" in near


def test_build_puts_the_patch_table_in_the_pr_body_and_the_final_report():  # AC-095.4 AC-095.17
    text = plugin("svc/commands/build.md")
    assert "cplat deps report" in text
    assert "Dependency patches" in text and "(no CRITICAL findings)" not in text


def test_ship_build_phase_escalates_only_on_what_cplat_deps_patch_cannot_fix():  # AC-095.13
    text = plugin("svc/commands/ship.md")
    assert "a CRITICAL security finding" not in text
    assert "a security finding `cplat deps patch` cannot fix" in text


def test_ship_pr_phase_adds_the_patch_section_to_the_body():  # AC-095.4
    text = plugin("svc/commands/ship.md")
    assert "cplat deps report --body-file .git/PR_BODY.md" in section(text, "## Phase `pr`")


def test_ship_land_patches_a_red_security_check_and_counts_it_as_a_fix_round():  # AC-095.15
    land = section(plugin("svc/commands/ship.md"), "## Phase `land`")
    assert "cplat deps patch" in land
    assert "cplat deps report --body-file .git/PR_BODY.md --update-pr" in land
    assert "cplat ship escalate" in land and "--cause" in land
    assert "security check" in land and "fix_rounds" in land


def test_ship_finish_lists_the_bumps_and_marks_major_bumps():  # AC-095.17
    text = plugin("svc/commands/ship.md")
    assert "major bump" in text and "cplat deps report" in text.split("Finish", 1)[-1]


def test_security_agent_never_bumps_and_leaves_patching_to_the_run():  # AC-095.12
    text = plugin("shared/agents/security.md")
    assert "cplat deps patch" in text and "never bumps" in text
    assert "/svc:release" in text and "/shared:check-quality" in text
    assert "**CRITICAL findings block release** — escalate to user immediately." not in text


def test_security_agent_keeps_the_base_image_summary_unchanged():  # AC-095.16
    text = plugin("shared/agents/security.md")
    assert "**Base image, no fix released:** findings in the base image's OS packages without a fixed version." in text
    assert "no fix released yet — rebuild when the base image updates" in text


def test_no_command_tells_an_agent_to_bump_a_dependency():  # AC-095.16
    for f in list((ROOT / "plugins").glob("*/commands/*.md")) + list((ROOT / "plugins").glob("*/agents/*.md")):
        assert "deps-bump" not in f.read_text(), f"{f.name} must leave bumping to `cplat deps patch`"
