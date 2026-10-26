"""Spec 104: generated repos build strictly and record every request (static checks on rendered templates)."""
import fnmatch
import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "templates"
CI = ROOT / ".github" / "workflows" / "ci.yml"


def _render(template: str, dest: Path, name: str, **data: str) -> Path:
    cmd = ["uv", "tool", "run", "--from", "copier", "copier", "copy", str(TEMPLATES / template), str(dest), "--defaults", "--trust",
           "--skip-tasks", "--data", f"project_name={name}", "--data", f"module_name={name.replace('-', '_')}", "--data", "description=check"]
    for k, v in data.items():
        cmd += ["--data", f"{k}={v}"]
    subprocess.run(cmd, check=True, capture_output=True)
    return dest


def _copy(shared_renders, tmp_path: Path, template: str, name: str, **data: str) -> Path:
    """A private copy of the render of `template` with `data` (rendered once per process)."""
    key = f"{template} {name} {sorted(data.items())}"
    return shared_renders.copy(key, lambda workdir: _render(template, workdir / name, name, **data), tmp_path / name)


@pytest.fixture()
def py_on(shared_renders, tmp_path):
    return _copy(shared_renders, tmp_path, "service-python", "svc-on", needs_observability="true")


@pytest.fixture()
def py_off(shared_renders, tmp_path):
    return _copy(shared_renders, tmp_path, "service-python", "svc-off", needs_observability="false")


@pytest.fixture()
def web(shared_renders, tmp_path):
    return _copy(shared_renders, tmp_path, "web-nextjs", "web-app")


def _lines(path: Path) -> list[str]:
    return [ln.strip() for ln in path.read_text().splitlines()]


def test_python_dockerfile_installs_strictly():  # AC-104.1
    """AC-104.1: the image build fails on a stale lock: --locked, no fallback, the lock file is required."""
    text = (TEMPLATES / "service-python" / "Dockerfile").read_text()
    installs = [ln for ln in text.splitlines() if "uv sync" in ln]
    assert len(installs) == 2
    for ln in installs:
        assert "--locked" in ln and "--frozen" not in ln, ln
        assert "||" not in ln and "2>/dev/null" not in ln, ln
    copy = next(ln for ln in text.splitlines() if ln.startswith("COPY pyproject.toml"))
    assert "uv.lock" in copy and "*" not in copy


def test_python_rendered_dockerfile_is_strict(py_on, py_off):  # AC-104.1
    """AC-104.1: the rendered Dockerfile (both observability variants) has the strict install."""
    for repo in (py_on, py_off):
        text = (repo / "Dockerfile").read_text()
        assert text.count("uv sync --locked") == 2 and "||" not in text.replace("|| exit 1", "")
        assert "uv.lock*" not in text


def test_web_dockerfile_installs_strictly(web):  # AC-104.2
    """AC-104.2: pnpm install --frozen-lockfile without a fallback; the lock file is required."""
    text = (web / "Dockerfile").read_text()
    installs = [ln for ln in text.splitlines() if "pnpm install" in ln]
    assert installs == ["RUN pnpm install --frozen-lockfile"]
    copy = next(ln for ln in text.splitlines() if ln.startswith("COPY package.json"))
    assert "pnpm-lock.yaml" in copy and "pnpm-lock.yaml*" not in copy


@pytest.mark.parametrize("template", ["service-python", "web-nextjs"])
def test_dockerfile_is_template_owned(template):  # AC-104.3
    """AC-104.3: /shared:update-service must bring the strict install, so the Dockerfile is not in _skip_if_exists."""
    conf = yaml.safe_load((TEMPLATES / template / "copier.yml").read_text())
    for pattern in conf["_skip_if_exists"]:
        assert not fnmatch.fnmatch("Dockerfile", pattern), f"{template}: {pattern} protects the Dockerfile"
    for forbidden in ("Dockerfile", "Dockerfile.jinja"):
        assert forbidden not in conf["_skip_if_exists"]


def test_main_registers_the_metrics_middleware_and_ping_does_not_count(py_on):  # AC-104.8
    """AC-104.8: the middleware records every request; /ping has no hand-written REQUEST_COUNT; no declared-but-unrecorded metric."""
    main = (py_on / "src" / "svc_on" / "main.py").read_text()
    assert "MetricsMiddleware" in main and "add_middleware" in main
    assert "REQUEST_COUNT" not in main
    metrics = (py_on / "src" / "svc_on" / "metrics.py").read_text()
    assert "class MetricsMiddleware" in metrics
    for name in ("REQUEST_COUNT", "REQUEST_LATENCY", "ERROR_COUNT"):
        assert len(re.findall(rf"\b{name}\b", metrics)) >= 2, f"{name} is declared but never recorded"
    assert '"route"' in metrics and '"endpoint"' not in metrics and "unmatched" in metrics


def test_observability_off_has_no_metrics_code(py_off):  # AC-104.9
    """AC-104.9: no metrics.py and no prometheus anywhere when observability is off."""
    assert not (py_off / "src" / "svc_off" / "metrics.py").exists()
    offenders = []
    for f in py_off.rglob("*"):
        if f.is_file() and ".git" not in f.relative_to(py_off).parts and "prometheus" in f.read_text(errors="ignore").lower():
            offenders.append(str(f.relative_to(py_off)))
    assert offenders == []


def _job(name: str, next_name: str) -> str:
    return CI.read_text().split(f"  {name}:", 1)[1].split(f"\n  {next_name}:", 1)[0]


def test_ci_checks_the_lockfile_mismatch_for_python():  # AC-104.10
    """AC-104.10: the template smoke job fails if the strict uv install no longer rejects a stale lock."""
    job = _job("smoke-test-templates", "smoke-test-gitops-app")
    assert "uv sync --locked --no-dev --no-install-project" in job


def test_ci_checks_the_lockfile_mismatch_for_web():  # AC-104.10
    """AC-104.10: the web smoke job fails if pnpm install --frozen-lockfile no longer rejects a stale lock."""
    job = CI.read_text().split("  smoke-test-web-nextjs:", 1)[1].split("\n  smoke-test-", 1)[0]
    assert "pnpm@11.22.0 install --frozen-lockfile" in job or "pnpm install --frozen-lockfile" in job
