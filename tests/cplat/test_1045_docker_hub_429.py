"""#1045: a Docker Hub login (when the secrets exist) before every image build, and one retry of a build that hits a registry 429."""
import os
import stat
import subprocess
from pathlib import Path

import pytest
import yaml
from waiting import with_prelude

ROOT = Path(__file__).resolve().parents[2]
LOGIN = "docker/login-action@c94ce9fb468520275223c153574b00df6fe4bcc9"
BUILD_JOBS = {
    "e2e.yml": ["e2e", "e2e-cluster", "e2e-clusters"],
    "e2e-upgrade.yml": ["upgrade", "upgrade-oldest"],
    "e2e-upgrade-drill.yml": ["drill"],
    "ci.yml": ["smoke-test-web-nextjs", "smoke-test-service-go", "smoke-test-service-typescript",
               "smoke-test-service-dotnet", "smoke-test-service-java", "smoke-test-service-java-update"],
}


@pytest.mark.parametrize("name,job", [(n, j) for n, js in BUILD_JOBS.items() for j in js])
def test_docker_hub_login_is_conditional_and_precedes_the_build(name, job):
    jb = yaml.safe_load((ROOT / ".github/workflows" / name).read_text())["jobs"][job]
    steps = jb["steps"]
    idx = [i for i, s in enumerate(steps) if str(s.get("uses", "")).startswith("docker/login-action@")]
    assert len(idx) == 1, "one Docker Hub login step"
    login = steps[idx[0]]
    assert login["uses"] == LOGIN, "one pin everywhere"
    assert login["if"] == "env.DOCKERHUB_USERNAME != ''", "no login (and no failure) without the secrets"
    assert "secrets.DOCKERHUB_USERNAME" in jb["env"]["DOCKERHUB_USERNAME"]
    builds = [i for i, s in enumerate(steps) if "docker build" in s.get("run", "") or "tests/e2e/" in s.get("run", "")]
    assert builds and idx[0] < min(builds), "the login must come before the first image build"


def _build(tmp_path, outputs):
    """Run e2e_docker_build against a fake `docker` that fails with the next of `outputs` per call (an empty text passes)."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for n, text in enumerate(outputs):
        (tmp_path / f"out{n}").write_text(text)
    fake = bindir / "docker"
    fake.write_text(with_prelude(
        f'#!/bin/sh\nd="{tmp_path}"\nn=$(cat "$d/n" 2>/dev/null || echo 0)\necho $((n+1)) > "$d/n"\n'
        'f="$d/out$n"\n[ -s "$f" ] || exit 0\ncat "$f" >&2\nexit 1\n'
    ))
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "E2E_BUILD_RETRY_WAIT": "0"}
    lib = ROOT / "tests/e2e/lib/docker-build.sh"
    r = subprocess.run(["bash", "-c", f'. "{lib}"; e2e_docker_build -q -t x .'], env=env, capture_output=True, text=True)
    return r, int((tmp_path / "n").read_text())


def test_a_registry_429_is_retried_once_and_can_pass(tmp_path):
    r, calls = _build(tmp_path, ["ERROR: failed to solve: failed to load cache key: invalid response status 429\n", ""])
    assert r.returncode == 0 and calls == 2


def test_a_second_429_fails_after_exactly_one_retry(tmp_path):
    r, calls = _build(tmp_path, ["invalid response status 429\n", "invalid response status 429\n"])
    assert r.returncode != 0 and calls == 2


def test_another_build_failure_is_not_retried(tmp_path):
    r, calls = _build(tmp_path, ['ERROR: process "pip install" did not complete successfully\n'])
    assert r.returncode != 0 and calls == 1
