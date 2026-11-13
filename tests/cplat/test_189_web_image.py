"""Spec 189: the web-nextjs runtime image is distroless (static checks of the default render).

Docker is not available in tests, so the runtime parts (scan finds no CRITICAL, `sh` fails, /api/health answers, the
browser smoke, the running Node major) are proven by the PR's `smoke-test-web-nextjs` and `scan web-nextjs` jobs. These tests
check their static preconditions."""
import re
from pathlib import Path

import pytest
from test_generated_repos import _copy


@pytest.fixture()
def web(shared_renders, tmp_path):
    return _copy(shared_renders, tmp_path, "web-nextjs", "web-app")


def _stages(text: str) -> dict[str, list[str]]:
    """Dockerfile lines (comments dropped) by stage name."""
    stages: dict[str, list[str]] = {}
    current = ""
    for ln in text.splitlines():
        if ln.lstrip().startswith("#") or not ln.strip():
            continue
        m = re.match(r"FROM\s+(\S+)\s+AS\s+(\S+)", ln)
        if m:
            current = m.group(2)
            stages[current] = [ln]
        elif current:
            stages[current].append(ln)
    return stages


def test_runtime_stage_is_distroless_node_of_the_pinned_major(web):  # AC-189.1
    """AC-189.1/2: runtime FROM gcr.io/distroless/nodejs<node_major>-debian13; the build stages stay on node:<major>-slim."""
    stages = _stages((web / "Dockerfile").read_text())
    assert stages["runtime"][0] == "FROM gcr.io/distroless/nodejs24-debian13 AS runtime"
    assert stages["deps"][0] == "FROM node:24-slim AS deps"
    assert stages["builder"][0] == "FROM node:24-slim AS builder"


def test_runtime_stage_has_no_shell_package_manager_or_npm(web):  # AC-189.1
    """AC-189.1: no RUN (so no apt, npm, corepack, shell) in the runtime stage."""
    runtime = "\n".join(_stages((web / "Dockerfile").read_text())["runtime"])
    assert not re.search(r"^\s*RUN\b", runtime, re.M)
    for banned in ("apt-get", "apt ", "npm", "npx", "corepack", "pnpm", "/bin/sh", "bash"):
        assert banned not in runtime, banned


def test_runtime_entrypoint_is_node_with_server_js(web):  # AC-189.1
    """AC-189.1: distroless's entrypoint is node, so the command is only server.js and `sh` as command runs `node sh`."""
    runtime = _stages((web / "Dockerfile").read_text())["runtime"]
    assert 'CMD ["server.js"]' in runtime
    assert not any(ln.startswith("ENTRYPOINT") for ln in runtime)


def test_runtime_runs_as_uid_1000_and_copies_are_chowned_numerically(web):  # AC-189.2
    """AC-189.2: started as UID 1000; distroless has no `node` user name, so the COPYs use --chown=1000:1000."""
    runtime = _stages((web / "Dockerfile").read_text())["runtime"]
    assert "USER 1000:1000" in runtime
    copies = [ln for ln in runtime if ln.startswith("COPY")]
    assert len(copies) == 3
    for ln in copies:
        assert "--chown=1000:1000" in ln, ln
        assert "node:node" not in ln, ln


def test_healthcheck_is_exec_form_with_the_distroless_node(web):  # AC-189.2
    """AC-189.2: the image has no shell, so the health check is exec form with /nodejs/bin/node on the app port and /api/health."""
    text = (web / "Dockerfile").read_text()
    runtime = _stages(text)["runtime"]
    joined = re.sub(r"\\\s*\n\s*", " ", "\n".join(runtime))
    health = next(ln for ln in joined.splitlines() if ln.startswith("HEALTHCHECK"))
    m = re.search(r'\bCMD (\["/nodejs/bin/node", "-e", ".*)$', health)
    assert m, health
    assert "http://localhost:3000/api/health" in m.group(1)
    assert "PORT=3000" in joined and "EXPOSE 3000" in joined


CI = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"


def _web_smoke_job() -> str:
    """The text of the `smoke-test-web-nextjs` job in ci.yml (up to the next top-level job)."""
    lines = CI.read_text().splitlines()
    start = next(i for i, ln in enumerate(lines) if ln == "  smoke-test-web-nextjs:")
    end = next((i for i in range(start + 1, len(lines)) if re.match(r"  \S[^ ]*:\s*$", lines[i])), len(lines))
    return "\n".join(lines[start:end])


def test_ci_smoke_job_requires_the_image_to_fail_with_sh_as_command():  # AC-189.1
    """AC-189.1: the web smoke job starts the built image with `sh` as the command and requires a non-zero exit."""
    job = _web_smoke_job()
    assert re.search(r"(?:\bif\b|!)\s+docker run\b[^\n]*\bsmoke:web sh\b", job), "no negated `docker run ... smoke:web sh`"


def test_ci_smoke_job_runs_the_image_read_only_and_answers_health_within_60s():  # AC-189.2
    """AC-189.2: read-only root fs, /api/health polled for 60 s, browser smoke result checked."""
    job = _web_smoke_job()
    assert re.search(r"docker run\b[^\n]*--read-only[^\n]*smoke:web\s*$", job, re.M)
    assert re.search(r"seq 1 30\b", job) and "sleep 2" in job and "localhost:3000/api/health" in job
    assert "smoke: 1 passed, 0 failed, 0 skipped" in job


def test_ci_smoke_job_waits_for_the_health_check_to_report_healthy():  # AC-189.2
    """AC-189.2: the job reads the container's health status through `docker inspect` and requires `healthy`."""
    job = _web_smoke_job()
    assert re.search(r"docker inspect\b[^\n]*State\.Health\.Status", job), "no docker inspect of the health status"
    assert "healthy" in job.split("State.Health.Status", 1)[-1], "healthy is never required"


def test_ci_smoke_job_compares_the_running_node_major_with_the_pinned_major(web):  # AC-189.2
    """AC-189.2: the running Node's process.versions.node major equals the Dockerfile's pinned node_major (ADR-005)."""
    major = re.search(r"distroless/nodejs(\d+)-", (web / "Dockerfile").read_text()).group(1)
    job = _web_smoke_job()
    assert "process.versions.node" in job, "the running Node version is never read"
    assert major in job.split("process.versions.node", 1)[-1] or "node_major" in job
