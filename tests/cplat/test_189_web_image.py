"""Spec 189: the web-nextjs runtime image is distroless (static checks of the default render).

Docker is not available in tests, so the runtime parts (scan finds no CRITICAL, `sh` fails, /api/health answers, the
browser smoke, the running Node major) are proven by the PR's `smoke-test-web-nextjs` and `scan web-nextjs` jobs. These tests
check their static preconditions."""
import re

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
