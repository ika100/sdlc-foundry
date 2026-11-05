"""Spec 145 (#474): smoke tests that write data run only in dev; staging and prod run read-only smoke checks.

cplat side: `smoke.run_recipe` passes `SMOKE_ENV` and `SMOKE_READ_ONLY` (1 outside dev) to `devbox run smoke`, a read-only run in
which no test passed is `not-run` with a reason (never a pass), the record section says `read_only`, and `instance verify prod`
records that run. Template side: every deployable shape's `scripts/smoke.sh` leaves out the tests marked as writing when
`SMOKE_READ_ONLY=1`, its CLAUDE.md documents the mark, the sample smoke tests are read-only, and the service-python harness is run
for real (the sample smoke test plus a writing one) against a local http.server."""
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

import smoke
from test_smoke_091_templates import TEMPLATES, UV_SHIM, example_smoke_test, health_server  # noqa: F401  (fixture)

BASE = "http://shop-api.shop-prod.localhost:8088"
READ_ID = "tests/test_smoke_health.py::test_health_answers_at_the_base_url"
WRITE_ID = "tests/test_smoke_tasks.py::test_a_task_can_be_created"
SHAPES = ["service-python", "service-java", "service-go", "web-nextjs"]
CLAUDE = {"service-python": "CLAUDE.md", "service-java": "CLAUDE.md.jinja", "service-go": "CLAUDE.md.jinja",
          "web-nextjs": "CLAUDE.md.jinja"}
MARK = {"service-python": "@pytest.mark.writes", "service-java": '@Tag("writes")', "service-go": "TestSmokeWrites",
        "web-nextjs": "@writes"}
HOW = {"service-python": "@pytest.mark.writes", "service-java": "-DexcludedGroups=writes", "service-go": "-skip '^TestSmokeWrites'",
       "web-nextjs": "--grep-invert @writes"}


# ---------------- cplat: what the recipe gets and what a read-only run means ----------------

class Devbox:
    """A `devbox` on PATH that records SMOKE_ENV / SMOKE_READ_ONLY and prints the scripted contract lines."""

    def __init__(self, tmp: Path, monkeypatch):
        self.dir = tmp / "fake-devbox"
        self.dir.mkdir()
        exe = self.dir / "devbox"
        exe.write_text(f"#!/bin/bash\necho \"$SMOKE_ENV|$SMOKE_READ_ONLY|$SMOKE_BASE_URL\" >> '{self.dir}/calls'\n"
                       f"cat '{self.dir}/out'\nexit 0\n")
        exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
        monkeypatch.setenv("PATH", f"{self.dir}{os.pathsep}{os.environ['PATH']}")
        monkeypatch.setenv("SMOKE_READ_ONLY", "1")       # a stray value in the caller's shell never reaches dev
        monkeypatch.setattr(smoke, "sleep", lambda s: None)
        monkeypatch.setattr(smoke, "reachable", lambda url, timeout=10.0: None)
        monkeypatch.setattr(smoke, "status", lambda url, *a, **k: 200)

    def prints(self, *items):
        p, f, s = (sum(1 for k, _ in items if k == w) for w in ("PASS", "FAIL", "SKIP"))
        lines = [f"{k}  {i}" for k, i in items] + ([f"smoke: {p} passed, {f} failed, {s} skipped"] if items else ["0 smoke tests"])
        (self.dir / "out").write_text("\n".join(lines) + "\n")

    @property
    def calls(self):
        return [ln.split("|") for ln in (self.dir / "calls").read_text().splitlines()]


@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "shop-api"
    r.mkdir()
    (r / "devbox.json").write_text(json.dumps({"shell": {"scripts": {"smoke": "bash scripts/smoke.sh"}}}))
    return r


@pytest.fixture()
def devbox(tmp_path, monkeypatch):
    return Devbox(tmp_path, monkeypatch)


@pytest.mark.parametrize("env, read_only", [("dev", "0"), ("staging", "1"), ("prod", "1")])
def test_the_recipe_learns_the_environment_and_whether_it_may_write(repo, devbox, env, read_only):  # AC-145.1, AC-145.2
    devbox.prints(("PASS", READ_ID))
    res = smoke.run_smoke(repo, BASE, env=env)
    assert devbox.calls == [[env, read_only, BASE]]
    assert res.ok and res.section()["read_only"] is (read_only == "1")


def test_read_only_mode_is_everything_but_dev():  # AC-145.1
    assert not smoke.read_only("dev") and smoke.read_only("staging") and smoke.read_only("prod") and smoke.read_only("qa")


def test_a_read_only_run_with_a_passing_check_passes_and_says_read_only(repo, devbox):  # AC-145.2
    devbox.prints(("PASS", READ_ID), ("SKIP", WRITE_ID))
    res = smoke.run_smoke(repo, BASE, env="staging")
    assert res.outcome == "passed" and (res.passed, res.skipped) == (1, 1)
    lines = res.lines()
    assert "read-only (staging): smoke tests marked as writing data are not run outside dev" in lines
    assert f"SKIP  {WRITE_ID}" in lines and res.row() == "1/2 passed"


@pytest.mark.parametrize("items", [(("SKIP", WRITE_ID),), ()], ids=["only-writing-tests", "no-smoke-test"])
def test_outside_dev_a_run_that_checked_nothing_is_not_run_never_passed(repo, devbox, items):  # AC-145.3
    devbox.prints(*items)
    res = smoke.run_smoke(repo, BASE, env="prod")
    assert res.outcome == "not-run" and not res.ok and res.base_url == BASE
    assert res.reason.startswith("no read-only smoke test ran in prod: smoke tests that write data run only in dev")
    assert "add a read-only smoke check" in res.reason
    assert res.row() == f"not run: {res.reason}"
    assert res.lines()[0] == f"smoke not run: {res.reason}"
    sec = res.section()
    assert sec["outcome"] == "not-run" and sec["read_only"] is True and sec["skipped"] == len(items)


def test_in_dev_a_run_without_passing_tests_still_passes_as_before(repo, devbox):  # AC-145.3
    devbox.prints(("SKIP", WRITE_ID))
    res = smoke.run_smoke(repo, BASE, env="dev")
    assert res.outcome == "passed" and res.section()["read_only"] is False
    assert not any(ln.startswith("read-only") for ln in res.lines())


def test_instance_verify_prod_records_a_run_without_read_only_test_and_exits_3(repo, devbox, monkeypatch, capsys):  # AC-145.3, AC-145.4
    import ship
    recorded = []
    monkeypatch.setattr(ship, "gitops_apps", lambda r: ["acme/shop-gitops"])
    monkeypatch.setattr(ship, "service_name", lambda r: "shop-api")
    monkeypatch.setattr(smoke, "dev_url", lambda r, apps, svc, env="dev": (BASE, None))
    monkeypatch.setattr(smoke, "pinned_image", lambda *a: "1.2.3")
    monkeypatch.setattr(smoke, "liveness_probe", lambda r: None)
    monkeypatch.setattr(smoke, "record", lambda r, res, image, spec_id: recorded.append((res.section(), image)) or "rid")
    devbox.prints(("SKIP", WRITE_ID))
    assert smoke.main(["run", "--repo", str(repo), "prod"]) == 3
    out = capsys.readouterr().out
    assert "smoke not run: no read-only smoke test ran in prod" in out and f"SKIP  {WRITE_ID}" in out
    ((sec, image),) = recorded
    assert sec["env"] == "prod" and sec["outcome"] == "not-run" and sec["read_only"] is True and image == "1.2.3"
    assert devbox.calls == [["prod", "1", BASE]]


# ---------------- templates: the harness, the docs and the samples ----------------

@pytest.mark.parametrize("shape", SHAPES)
def test_each_smoke_script_leaves_out_writing_tests_when_read_only(shape):  # AC-145.5
    text = (TEMPLATES / shape / "scripts" / "smoke.sh").read_text()
    assert '"${SMOKE_READ_ONLY:-}" = "1"' in text and "SMOKE_ENV" in text
    helper = (TEMPLATES / shape / "scripts" / "smoke_pytest.py").read_text() if shape == "service-python" else ""
    assert HOW[shape] in text or ("writes" in helper and "SMOKE_READ_ONLY" in helper)


@pytest.mark.parametrize("shape", SHAPES)
def test_each_claude_md_documents_the_writing_mark_and_the_read_only_rule(shape):  # AC-145.6
    text = (TEMPLATES / shape / CLAUDE[shape]).read_text()
    sec = text.split("## Smoke tests", 1)[1].split("\n## ", 1)[0]
    assert MARK[shape] in sec and "SMOKE_READ_ONLY=1" in sec and "SMOKE_ENV" in sec
    assert "read-only smoke check" in sec and "not run" in sec


@pytest.mark.parametrize("shape", SHAPES)
def test_the_sample_smoke_test_is_read_only_so_it_runs_everywhere(shape):  # AC-145.6
    text = example_smoke_test(shape).read_text()
    assert "#474" in text and MARK[shape] in text           # it names the mark ...
    code = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("//"))
    if shape == "service-python":
        assert "@pytest.mark.writes\ndef" not in text and "@pytest.mark.smoke\ndef" in text    # ... but does not carry it
    elif shape == "service-java":
        assert '@Tag("writes")\n' not in text and '@Tag("smoke")\n' in text
    elif shape == "service-go":
        assert "func TestSmokeWrites" not in code
    else:
        assert "@writes" not in "\n".join(ln for ln in text.splitlines() if ln.startswith("test("))


WRITING = '''import urllib.request

import pytest


@pytest.mark.smoke
@pytest.mark.writes
def test_a_task_can_be_created(smoke_base_url):
    with urllib.request.urlopen(smoke_base_url + "/health") as r:
        assert r.status == 200
'''


def run_template_smoke(tmp_path, url, **env_extra):
    """The service-python harness as `devbox run smoke` runs it, with the template's sample smoke test and a writing one."""
    shutil.copytree(TEMPLATES / "service-python" / "scripts", tmp_path / "scripts", dirs_exist_ok=True)
    (tmp_path / "tests").mkdir(exist_ok=True)
    shutil.copy(TEMPLATES / "service-python" / "tests" / "test_smoke_health.py", tmp_path / "tests")
    (tmp_path / "tests" / "test_smoke_tasks.py").write_text(WRITING)
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    (bindir / "uv").write_text(UV_SHIM)
    (bindir / "uv").chmod(0o755)
    env = {k: v for k, v in os.environ.items()
           if k not in ("SMOKE_BASE_URL", "SMOKE_ENV", "SMOKE_READ_ONLY", "PYTEST_ADDOPTS", "PYTEST_CURRENT_TEST")}
    env.update(PATH=f"{bindir}{os.pathsep}{env['PATH']}", SMOKE_BASE_URL=url, **env_extra)
    return subprocess.run(["bash", "scripts/smoke.sh"], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)


def test_python_harness_skips_writing_tests_when_read_only(tmp_path, health_server):  # noqa: F811  AC-145.5
    res = run_template_smoke(tmp_path, health_server, SMOKE_ENV="prod", SMOKE_READ_ONLY="1")
    lines = res.stdout.splitlines()
    assert f"PASS  {READ_ID}" in lines and f"SKIP  {WRITE_ID}" in lines, res.stdout + res.stderr
    assert "smoke: 1 passed, 0 failed, 1 skipped" in lines and res.returncode == 0
    assert "read-only smoke in prod: tests marked @pytest.mark.writes are skipped" in res.stderr


@pytest.mark.parametrize("extra", [{"SMOKE_ENV": "dev", "SMOKE_READ_ONLY": "0"}, {}], ids=["dev", "by-hand"])
def test_python_harness_runs_writing_tests_in_dev(tmp_path, health_server, extra):  # noqa: F811  AC-145.5
    res = run_template_smoke(tmp_path, health_server, **extra)
    lines = res.stdout.splitlines()
    assert f"PASS  {READ_ID}" in lines and f"PASS  {WRITE_ID}" in lines, res.stdout + res.stderr
    assert "smoke: 2 passed, 0 failed, 0 skipped" in lines and res.returncode == 0


def test_the_writes_marker_is_registered_for_test_and_ci(tmp_path):  # AC-145.5
    """`devbox run test` loads the plugin too: a strict-markers run knows `writes`."""
    shutil.copytree(TEMPLATES / "service-python" / "scripts", tmp_path / "scripts")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_smoke_tasks.py").write_text(WRITING)
    env = {k: v for k, v in os.environ.items() if k not in ("PYTEST_ADDOPTS", "PYTEST_CURRENT_TEST", "SMOKE_READ_ONLY")}
    env["SMOKE_BASE_URL"] = ""
    import sys
    res = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-p", "scripts.smoke_pytest", "-p", "no:cacheprovider", "-q",
                          "--strict-markers"], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    assert res.returncode == 0 and "1 skipped" in res.stdout, res.stdout + res.stderr


TESTERS = {"svc": "@pytest.mark.writes", "svc-java": '@Tag("writes")', "svc-go": "TestSmokeWrites", "web": "@writes"}


@pytest.mark.parametrize("plugin", sorted(TESTERS))
def test_the_tester_agents_mark_writing_smoke_tests_and_keep_read_only_checks(plugin):  # AC-145.7
    text = (TEMPLATES.parent / "plugins" / plugin / "agents" / "tester.md").read_text()
    sec = text.split("## Smoke criteria", 1)[1].split("\n## ", 1)[0]
    assert TESTERS[plugin] in sec and "SMOKE_READ_ONLY=1" in sec and "SMOKE_ENV" in sec
    assert "creates, changes or deletes data" in sec and "read-only check" in sec and "not run" in sec


def test_the_testing_reference_names_every_mark():  # AC-145.7
    text = (TEMPLATES.parent / "plugins/svc/skills/spec-format/references/testing.md").read_text()
    assert "SMOKE_READ_ONLY=1" in text and all(mark in text for mark in TESTERS.values())
    assert "read-only smoke checks" in text.lower() or "keep read-only" in text.lower()
