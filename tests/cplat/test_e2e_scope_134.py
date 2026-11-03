"""Spec 134: scripts/e2e-scope.py decides whether a pull request needs the cluster e2e (AC-134.2, AC-134.3, AC-134.8).

The script is loaded inside each test, so each test fails on its own while it is missing.
"""
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from system_fixtures import ROOT, git

SCRIPT = ROOT / "scripts" / "e2e-scope.py"
FIXTURE = Path(__file__).parent / "fixtures" / "e2e_scope_134_prs.json"


def scope():
    spec = importlib.util.spec_from_file_location("e2e_scope", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def mini_root(tmp_path: Path) -> Path:
    """A copy of what the decision reads: scripts/cplat (Python files and packages), tests/e2e, the changelog."""
    root = tmp_path / "repo"
    shutil.copytree(ROOT / "scripts" / "cplat", root / "scripts" / "cplat", ignore=shutil.ignore_patterns("__pycache__", "benchmark", "assets"))
    shutil.copytree(ROOT / "tests" / "e2e", root / "tests" / "e2e")
    shutil.copy(SCRIPT, root / "scripts" / "e2e-scope.py")
    (root / "docs").mkdir()
    (root / "docs" / "CHANGELOG.md").write_text("# CHANGELOG\n\n## [Unreleased]\n\n## [5.6.1] — 2026-11-03\n\nx\n")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "base")
    return root


def decide(root: Path, *argv: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(root / "scripts" / "e2e-scope.py"), *argv], cwd=root, capture_output=True, text=True)


# ---------------- AC-134.3: the exercised set ----------------

def test_the_exercised_set_holds_the_modules_the_e2e_scripts_call_and_import_ac_134_3():  # AC-134.3
    got = scope().exercised(ROOT)
    called = {"cplat", "newapp", "addon", "compose", "ship", "promote", "secret", "smoke", "modelcmd", "doctor", "dbbackup",
              "dbrestore", "envrestore", "status", "spec"}   # system new, resource add|remove|backup|restore, component set|ship, ...
    imported = {"gitops", "core"}                             # the heredocs of run.sh import gitops, compose, core
    assert called | imported <= got, sorted((called | imported) - got)


def test_the_exercised_set_follows_imports_inside_functions_ac_134_3():  # AC-134.3
    mod = scope()
    got = mod.exercised(ROOT)
    # every module named by an import statement anywhere in a member (module level or inside a function) is a member too
    import ast
    cplat = ROOT / "scripts" / "cplat"
    names = {p.stem for p in cplat.glob("*.py")} | {p.name for p in cplat.iterdir() if (p / "__init__.py").is_file()}
    for m in got:
        path = cplat / f"{m}.py" if (cplat / f"{m}.py").is_file() else cplat / m / "__init__.py"
        for node in ast.walk(ast.parse(path.read_text())):
            deps = [a.name.split(".")[0] for a in node.names] if isinstance(node, ast.Import) else \
                [node.module.split(".")[0]] if isinstance(node, ast.ImportFrom) and node.module and node.level == 0 else []
            for d in deps:
                assert d not in names or d in got, f"{m} imports {d}, which is not in the exercised set"


def test_modules_the_e2e_never_reaches_are_not_in_the_set_ac_134_3():  # AC-134.3
    got = scope().exercised(ROOT)
    assert not {"retro", "retro_report", "platrelease", "platrelease_publish", "console", "fleet", "ui", "clusterrepo"} & got


def test_the_set_is_computed_from_the_scripts_at_head_not_a_list_ac_134_3(tmp_path):  # AC-134.3
    root = mini_root(tmp_path)
    mod = scope()
    assert "apilist" not in mod.exercised(root)
    run_sh = root / "tests" / "e2e" / "run.sh"
    run_sh.write_text(run_sh.read_text() + '\n$cplat api list --json >/dev/null\n')
    assert "apilist" in mod.exercised(root)
    cluster_sh = root / "tests" / "e2e" / "cluster.sh"
    cluster_sh.write_text(cluster_sh.read_text() + "\nuv run python - <<'PY'\nimport retro\nPY\n")
    assert "retro" in mod.exercised(root)


def test_list_prints_the_set_one_name_per_line_ac_134_3():  # AC-134.3
    p = subprocess.run([sys.executable, str(SCRIPT), "--list"], cwd=ROOT, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    lines = p.stdout.splitlines()
    assert lines == sorted(scope().exercised(ROOT)) and "gitops" in lines


# ---------------- AC-134.2: the trigger rule ----------------

RUNS = ["templates/gitops-app/scripts/render.py", "templates/gitops-app/devbox.json", "templates/gitops-app/copier.yml",
        "templates/gitops-app/CLAUDE.md.jinja", "templates/gitops-app/.github/workflows/ci.yml.jinja",
        "templates/cluster-gitops/scripts/system_render.py", "templates/service-java/Dockerfile", "templates/web-nextjs/Dockerfile",
        "templates/service-python/Dockerfile.jinja", "tests/e2e/run.sh", "tests/e2e/cluster.sh", ".github/workflows/e2e.yml",
        "scripts/e2e-scope.py", "shapes.yml", "scripts/cplat/gitops.py", "scripts/cplat/ship.py", "scripts/cplat/cplat.py",
        "scripts/cplat/failsum/core.py", "scripts/cplat/prices.json", "scripts/cplat/assets/render_v4.py"]
SKIPS = ["docs/CHANGELOG.md", "docs/guide.md", "README.md", "plugins/component/commands/ship.md", "scripts/cplat/retro.py",
         "scripts/cplat/platrelease.py", "scripts/cplat/console/server.py", "scripts/release-check.py", "tests/cplat/test_x.py",
         "tests/e2e/upgrade.sh", ".github/workflows/ci.yml", ".github/workflows/e2e-upgrade.yml",
         "templates/gitops-app/.github/workflows/pin-dev.yml", "templates/gitops-app/README.md", "templates/cluster-gitops/docs/x.md",
         "templates/web-nextjs/package.json.jinja", "templates/service-java/pom.xml.jinja"]


@pytest.mark.parametrize("path", RUNS)
def test_a_path_the_e2e_exercises_triggers_it_ac_134_2(path):  # AC-134.2
    assert scope().triggers(ROOT, [path]) == [path]


@pytest.mark.parametrize("path", SKIPS)
def test_a_path_the_e2e_does_not_exercise_does_not_trigger_it_ac_134_2(path):  # AC-134.2
    assert scope().triggers(ROOT, [path]) == []


@pytest.mark.parametrize("old, new, want", [
    ("## [Unreleased]\n\n## [5.6.1] — x\n", "## [Unreleased]\n\n## [5.7.0] — y\n\n## [5.6.1] — x\n", True),
    ("## [Unreleased]\n\n## [5.6.1] — x\n", "## [Unreleased]\n\nnew entry\n\n## [5.6.1] — x\n", False),
    ("## [Unreleased]\n\n## [5.6.1] — x\n", "## [Unreleased]\n\n## [Next] — y\n\n## [5.6.1] — x\n", False),
], ids=["release", "entry", "not-a-version"])
def test_a_new_release_heading_is_the_release_pull_request_ac_134_2(old, new, want):  # AC-134.2
    assert scope().adds_release_heading(old, new) is want


def test_the_cli_decides_on_the_diff_against_base_ac_134_2(tmp_path):  # AC-134.2
    root = mini_root(tmp_path)
    base = git(root, "rev-parse", "HEAD").strip()
    (root / "docs" / "guide.md").write_text("x")
    (root / "scripts" / "cplat" / "retro.py").write_text((root / "scripts" / "cplat" / "retro.py").read_text() + "\n# x\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "docs and retro")
    p = decide(root, "--base", base)
    assert p.returncode == 0 and p.stdout == "run=false\n", (p.stdout, p.stderr)
    (root / "scripts" / "cplat" / "gitops.py").write_text((root / "scripts" / "cplat" / "gitops.py").read_text() + "\n# x\n")
    git(root, "commit", "-qam", "gitops")
    p = decide(root, "--base", base)
    assert p.returncode == 0 and p.stdout == "run=true\n", (p.stdout, p.stderr)
    assert "trigger: scripts/cplat/gitops.py" in p.stderr.splitlines()


def test_the_cli_runs_for_a_release_heading_ac_134_2(tmp_path):  # AC-134.2
    root = mini_root(tmp_path)
    base = git(root, "rev-parse", "HEAD").strip()
    cl = root / "docs" / "CHANGELOG.md"
    cl.write_text(cl.read_text().replace("## [5.6.1]", "## [5.7.0] — 2026-11-04\n\ny\n\n## [5.6.1]"))
    git(root, "commit", "-qam", "release")
    p = decide(root, "--base", base)
    assert p.stdout == "run=true\n" and "trigger: release heading 5.7.0" in p.stderr.splitlines(), (p.stdout, p.stderr)


def test_an_unknown_base_is_one_error_line_not_a_traceback_ac_134_2(tmp_path):  # AC-134.2
    root = mini_root(tmp_path)
    p = decide(root, "--base", "no-such-ref")
    assert p.returncode == 1 and p.stdout.startswith("ERROR: ") and "Traceback" not in p.stdout + p.stderr


# ---------------- AC-134.8: fewer pull requests start the cluster e2e ----------------

def test_fewer_of_the_last_40_pull_requests_start_the_cluster_e2e_ac_134_8():  # AC-134.8
    data = json.loads(FIXTURE.read_text())
    mod = scope()
    assert len(data["prs"]) == 40
    started = [p["pr"] for p in data["prs"] if p["release"] or mod.triggers(ROOT, p["files"])]
    assert len(started) < data["old_rule_started"] == 23, started
