"""Static guards for the generated CI workflows (the publish path only runs on main/tags, so PR smoke tests never exercise it)."""
import re
from pathlib import Path

import pytest

TEMPLATES = Path(__file__).resolve().parents[2] / "templates"
IMAGE_TEMPLATES = ["service-python", "service-java", "service-go", "web-nextjs"]


def trivy_steps(template: str) -> list[str]:
    text = (TEMPLATES / template / ".github" / "workflows" / "ci.yml").read_text()
    steps = re.split(r"\n(?=      - )", text)
    return [s for s in steps if "aquasecurity/trivy-action" in s]


@pytest.mark.parametrize("template", IMAGE_TEMPLATES)
def test_trivy_resolves_the_digest_for_the_matrix_architecture(template):
    """Each per-arch job scans the digest it just pushed. Without TRIVY_PLATFORM Trivy looks for linux/amd64 and fails on the arm64 job
    ("no child with platform linux/amd64 in index"), so the multi-arch manifest would never be published."""
    steps = trivy_steps(template)
    assert len(steps) == 2, f"{template}: expected the scan and the SBOM step"
    for step in steps:
        assert re.search(r"TRIVY_PLATFORM: linux/\$\{\{ ('\{\{' \}\} )?matrix\.arch", step), f"{template}: a Trivy step has no TRIVY_PLATFORM"


# ---------------- spec 043: the Python templates pass their own quality gate ----------------

import shutil
import subprocess

ROOT = TEMPLATES.parent
CI = ROOT / ".github" / "workflows" / "ci.yml"


def _render(template: str, dest: Path, name: str) -> Path:
    module = name.replace("-", "_")
    subprocess.run(["uv", "tool", "run", "--from", "copier", "copier", "copy", str(TEMPLATES / template), str(dest),
                    "--defaults", "--trust", "--skip-tasks", "--data", f"project_name={name}", "--data", f"module_name={module}",
                    "--data", "description=check"], check=True, capture_output=True)
    return dest


@pytest.mark.slow
@pytest.mark.skipif(not shutil.which("uv"), reason="needs uv")
@pytest.mark.parametrize("template", ["service-python", "library-python"])
def test_rendered_python_templates_pass_ruff_and_mypy(template, tmp_path):
    """AC-043.1 AC-043.2 AC-043.4: a repo named like the run's todo-api starts lint- and type-clean."""
    repo = _render(template, tmp_path / "todo-api", "todo-api")
    for cmd in (["uv", "sync", "--all-extras", "-q"], ["uv", "run", "ruff", "check", "."], ["uv", "run", "ruff", "format", "--check", "."],
                ["uv", "run", "mypy", "src"]):
        out = subprocess.run(cmd, cwd=repo, capture_output=True, text=True)
        assert out.returncode == 0, f"{' '.join(cmd)}:\n{out.stdout[-2000:]}{out.stderr[-1000:]}"


def test_platform_ci_lints_types_and_tests_the_python_templates():
    """AC-043.3: the platform PR fails when a rendered Python template does not pass ruff, mypy or pytest."""
    job = CI.read_text().split("  smoke-test-templates:", 1)[1].split("\n  smoke-test-gitops-app:", 1)[0]
    for step in ("uv sync --all-extras", "uv run ruff check .", "uv run ruff format --check .", "uv run mypy src", "uv run pytest -q"):
        assert step in job, f"smoke-test-templates does not run `{step}`"


# ---------------- spec 059: the secrets scan scans ----------------

import json as _json

BASELINE_TEMPLATES = sorted(p.parent.name for p in TEMPLATES.glob("*/.secrets.baseline.json"))


def _baseline(t):
    return _json.loads((TEMPLATES / t / ".secrets.baseline.json").read_text())


@pytest.mark.parametrize("template", BASELINE_TEMPLATES)
def test_every_secrets_baseline_enables_the_default_plugins(template):
    """AC-059.1: an empty plugins_used makes detect-secrets print "No plugins to scan with!" and scan nothing."""
    names = {p["name"] for p in _baseline(template)["plugins_used"]}
    assert names == {p["name"] for p in _baseline("service-python")["plugins_used"]} and len(names) >= 20


@pytest.mark.skipif(not shutil.which("uvx"), reason="needs uvx")
def test_the_web_baseline_finds_a_planted_secret_quietly(tmp_path):
    """AC-059.1: no "No plugins" noise, and a real-looking key is reported."""
    shutil.copy(TEMPLATES / "web-nextjs" / ".secrets.baseline.json", tmp_path / ".secrets.baseline.json")
    (tmp_path / "clean.ts").write_text("export const greeting = 'hello';\n")
    (tmp_path / "leak.ts").write_text("const key = 'AKIAIOSFODNN7EXAMPLE';\n")
    def hook(*files):
        return subprocess.run(["uvx", "--from", "detect-secrets", "detect-secrets-hook", "--baseline", ".secrets.baseline.json", *files],
                              cwd=tmp_path, capture_output=True, text=True)
    clean = hook("clean.ts")
    assert clean.returncode == 0 and "No plugins" not in clean.stdout + clean.stderr
    leak = hook("leak.ts")
    assert leak.returncode == 1 and "AWS" in leak.stdout


# ---------------- spec 064: self-hosted CI runners through repository variables ----------------

ALL_TEMPLATES = ["service-python", "library-python", "service-java", "service-go", "web-nextjs", "gitops-app"]
RUNNER = re.compile(r"runs-on: \$\{\{ ('\{\{' \}\} )?vars\.CI_RUNNER \|\| 'ubuntu-latest' ")


def _workflows(template: str) -> list[Path]:
    return sorted((TEMPLATES / template / ".github" / "workflows").glob("*.yml"))


@pytest.mark.parametrize("template", ALL_TEMPLATES)
def test_jobs_run_on_the_ci_runner_variable(template):
    """AC-064.1: no job is pinned to ubuntu-latest; the repository variable CI_RUNNER picks the runner, GitHub-hosted by default."""
    for wf in _workflows(template):
        text = wf.read_text()
        assert "runs-on: ubuntu-latest" not in text, f"{wf.relative_to(TEMPLATES)} still pins ubuntu-latest"
        for line in re.findall(r"^\s*runs-on: .*$", text, re.M):
            bare = line.strip() == "runs-on: ${{ vars.CI_RUNNER }}" and "if: vars.CI_RUNNER != ''" in text  # spec 092: self-hosted only
            assert RUNNER.search(line) or "matrix.runner" in line or bare, f"{wf.relative_to(TEMPLATES)}: {line.strip()}"


@pytest.mark.parametrize("template", ALL_TEMPLATES)
def test_devbox_is_installed_only_on_github_hosted_runners(template):
    """AC-064.2: self-hosted runner images ship devbox; the install action (systemd Nix daemon) only runs on GitHub-hosted runners."""
    for wf in _workflows(template):
        steps = re.split(r"\n(?=\s+- )", wf.read_text())
        for step in (s for s in steps if "jetify-com/devbox-install-action" in s):
            assert "if: runner.environment == 'github-hosted'" in step, f"{wf.relative_to(TEMPLATES)}: devbox install without the guard"


@pytest.mark.parametrize("template", IMAGE_TEMPLATES)
def test_docker_matrix_can_come_from_a_repository_variable(template):
    """AC-064.3: CI_DOCKER_MATRIX replaces the docker job's architecture matrix; without it the default (amd64, + arm64 on main/tags) stays."""
    text = (TEMPLATES / template / ".github" / "workflows" / "ci.yml").read_text()
    include = re.search(r"^\s*include: (.*)$", text, re.M).group(1)
    assert "fromJSON(vars.CI_DOCKER_MATRIX || (github.event_name == 'push'" in include, include
    assert '"arch":"arm64","runner":"ubuntu-24.04-arm"' in include and include.count("(") == include.count(")")


@pytest.mark.parametrize("template", IMAGE_TEMPLATES)
def test_docker_cache_only_on_github_hosted_runners(template):
    """AC-064.5: the docker job reads and writes the GitHub Actions cache only on GitHub-hosted runners."""
    text = (TEMPLATES / template / ".github" / "workflows" / "ci.yml").read_text()
    lines = re.findall(r"^\s*cache-(?:from|to): .*$", text, re.M)
    assert len(lines) == 2, lines
    for line in lines:
        assert "runner.environment == 'github-hosted' && format('type=gha," in line and "|| ''" in line, line


@pytest.mark.slow
@pytest.mark.skipif(not shutil.which("uv"), reason="needs uv")
@pytest.mark.parametrize("template", ["service-python", "library-python", "service-go"])
def test_rendered_workflows_keep_the_expressions(template, tmp_path):
    """AC-064.1 AC-064.2 AC-064.3 AC-064.5: the Jinja escaping survives rendering, both for templates that render every file and for `.jinja` ones."""
    import yaml

    repo = _render(template, tmp_path / "todo-api", "todo-api")
    text = (repo / ".github" / "workflows" / "ci.yml").read_text()
    yaml.safe_load(text)
    assert "runs-on: ${{ vars.CI_RUNNER || 'ubuntu-latest' }}" in text and "'{{'" not in text
    assert "if: runner.environment == 'github-hosted'" in text
    if template != "library-python":
        assert "fromJSON(vars.CI_DOCKER_MATRIX || (github.event_name" in text
        assert "cache-from: ${{ runner.environment == 'github-hosted' && format('type=gha,scope={0}', matrix.arch) || '' }}" in text


def test_self_hosted_runner_guide_covers_variables_image_and_arc():
    """AC-064.4: the guide names the variables, the runner image's needs and the ARC lessons."""
    guide = (ROOT / "docs" / "self-hosted-runners.md").read_text()
    for needle in ("CI_RUNNER", "CI_DOCKER_MATRIX", "single-user Nix", "`xz`", "`gh`", "Docker in Docker",
                   "runner-image/Dockerfile", "repository-level runners", "runnerScaleSetName", "Administration: read and write",
                   "`/nix`", "/var/lib/docker", "`/tmp` as a memory", "Isolation"):
        assert needle in guide, needle
