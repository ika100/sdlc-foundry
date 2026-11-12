"""#407: `detect what changed` in ci.yml turns the template smokes on only for the repository scripts they really run.

A pull request that changes only `scripts/cplat/` (or another check under `scripts/`) runs the cplat tests, not every smoke.
"""
import os
import re
import stat
from waiting import with_prelude
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CI = ROOT / ".github/workflows/ci.yml"
SMOKES = ("python", "gitops", "cluster", "web", "go", "java")


def ci() -> dict:
    return yaml.safe_load(CI.read_text())


def detect(tmp_path: Path, files: list[str] | None) -> dict[str, bool]:
    """Run the diff step as GitHub would, with `git diff` answering `files` (None: a push to main)."""
    step = next(s for s in ci()["jobs"]["changes"]["steps"] if s.get("id") == "diff")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    git = bin_dir / "git"
    git.write_text(with_prelude("#!/usr/bin/env bash\nprintf '%s\\n' " + " ".join(f"'{f}'" for f in files or []) + "\n"))
    git.chmod(git.stat().st_mode | stat.S_IEXEC)
    out = tmp_path / "out"
    out.write_text("")
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "GITHUB_OUTPUT": str(out),
           "EVENT": "push" if files is None else "pull_request", "BASE": "main"}
    p = subprocess.run(["bash", "-c", step["run"]], env=env, capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    return {k: v == "true" for k, v in (line.split("=", 1) for line in out.read_text().split())}


@pytest.mark.parametrize("path", [
    "scripts/cplat/ship.py", "scripts/cplat/assets/workflows/ci.yml", "scripts/check-links.py", "scripts/e2e-scope.py",
    "scripts/release-check.py", "scripts/ci-local.sh",
])
def test_a_scripts_change_the_smokes_do_not_run_leaves_them_off_but_runs_the_cplat_tests(tmp_path, path):
    out = detect(tmp_path, [path])
    assert out["code"], "the cplat tests must still run"
    assert not any(out[s] for s in SMOKES), {s: out[s] for s in SMOKES}


def test_a_cplat_change_still_builds_the_site(tmp_path):
    assert detect(tmp_path, ["scripts/cplat/ship.py"])["site"]


@pytest.mark.parametrize("path", [
    "scripts/detect-shape.sh", "scripts/sync-template-copies.py", "shapes.yml", ".github/workflows/ci.yml",
    "tests/fixtures/gitops/system.yaml",
])
def test_a_script_every_smoke_depends_on_turns_them_all_on(tmp_path, path):
    out = detect(tmp_path, [path])
    assert all(out[s] for s in SMOKES), {s: out[s] for s in SMOKES}


def test_the_plan_tests_turn_on_only_the_gitops_smoke(tmp_path):
    out = detect(tmp_path, ["scripts/test-plan.sh"])
    assert out["gitops"] and not any(out[s] for s in SMOKES if s != "gitops")


def test_a_push_to_main_runs_everything(tmp_path):
    out = detect(tmp_path, None)
    assert out["code"] and all(out[s] for s in SMOKES)


def test_a_template_change_turns_on_only_its_smoke(tmp_path):
    out = detect(tmp_path, ["templates/service-java/pom.xml.jinja"])
    assert out["java"] and not any(out[s] for s in SMOKES if s != "java")


def repo_scripts_run_by(job: dict) -> set[str]:
    """Repository scripts (`scripts/<file>` relative to the checkout) that a smoke job's steps call."""
    found: set[str] = set()
    for step in job["steps"]:
        run = step.get("run", "")
        if step.get("working-directory") or not run:
            continue
        for line in run.split("\n"):
            if re.match(r"\s*cd /tmp", line):
                break                                        # the rest of the step runs inside the generated repo
            found |= set(re.findall(r"(?<![\w/.-])scripts/[\w.-]+", line))
    return found


def test_every_repository_script_a_smoke_runs_turns_that_smoke_on(tmp_path):
    """Drift guard: a smoke that starts calling another script from scripts/ must also be turned on by a change to it."""
    seen = 0
    for name, job in ci()["jobs"].items():
        m = re.fullmatch(r"needs\.changes\.outputs\.(\w+) == 'true'", str(job.get("if", "")))
        if not name.startswith("smoke-test-") or not m:
            continue
        for script in repo_scripts_run_by(job):
            seen += 1
            assert (ROOT / script).is_file(), script
            assert detect(tmp_path, [script])[m.group(1)], f"{name} runs {script} but a change to it leaves the job off"
    assert seen >= 6   # detect-shape.sh in five smokes, test-plan.sh in the gitops one
