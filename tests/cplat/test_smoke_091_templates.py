"""Spec 091 acceptance tests, template side: `devbox run smoke` in every deployable shape (AC-091.2, AC-091.3, AC-091.4)
and the standard Playwright scaffold of web-nextjs (AC-091.16).

Nothing here needs Maven, Go, pnpm, a browser or a cluster: the recipes and files are checked statically, the guard of
every `scripts/smoke.sh` is executed, and the service-python runner is executed for real against a local http.server
(its `uv run` is replaced by a shim that runs the platform's own interpreter). Contract: design.md "devbox run smoke"."""
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
import yaml

import core
import newsvc
import update

TEMPLATES = core.PLATFORM_ROOT / "templates"
SHAPES = ["service-python", "service-java", "service-go", "web-nextjs"]
DEVBOX = {"service-python": "devbox.json", "service-java": "devbox.json.jinja", "service-go": "devbox.json.jinja",
          "web-nextjs": "devbox.json.jinja"}
HELPERS = {"service-python": "smoke_pytest.py", "service-java": "SmokeSummary.java", "service-go": "smoke-summary.go",
           "web-nextjs": "smoke-summary.mjs"}
TAGS = {"service-python": r"pytest\.mark\.smoke\b", "service-java": r'@Tag\(\s*"smoke"\s*\)',
        "service-go": r"func\s+TestSmoke\w*\s*\(", "web-nextjs": r"@smoke\b"}
GUARD = ("ERROR: SMOKE_BASE_URL is not set: devbox run smoke runs the smoke tests against a running deployment, "
         "e.g. SMOKE_BASE_URL=https://<host> devbox run smoke")


def recipe(shape: str, name: str) -> str | None:
    text = (TEMPLATES / shape / DEVBOX[shape]).read_text()
    m = re.search(rf'^\s*"{re.escape(name)}":\s*"((?:[^"\\]|\\.)*)"', text, re.M)
    return m.group(1) if m else None


def example_smoke_test(shape: str) -> Path | None:
    patterns = {"service-python": "tests/test_smoke_health.py", "service-go": "internal/server/smoke_test.go",
                "web-nextjs": "e2e/smoke.spec.ts*", "service-java": "src/test/java/**/SmokeHealthTest.java*"}
    hit = sorted((TEMPLATES / shape).glob(patterns[shape]))
    return hit[0] if hit else None


# ---------------- AC-091.2: the recipe and the platform-owned script ----------------

@pytest.mark.parametrize("shape", SHAPES)
def test_every_deployable_shape_has_the_smoke_recipe_ac_091_2(shape):  # AC-091.2
    assert recipe(shape, "smoke") == "bash scripts/smoke.sh"


@pytest.mark.parametrize("shape", SHAPES)
def test_smoke_script_and_helper_are_delivered_by_update_service_ac_091_2(shape):  # AC-091.2
    assert (TEMPLATES / shape / "scripts" / "smoke.sh").is_file()
    assert (TEMPLATES / shape / "scripts" / HELPERS[shape]).is_file()
    owned = update.project_owned_patterns(shape)
    for rel in ("scripts/smoke.sh", f"scripts/{HELPERS[shape]}"):
        assert not any(core_match(rel, p) for p in owned), f"{rel} is project-owned: an update would not refresh it"


def core_match(path: str, pattern: str) -> bool:
    import fnmatch
    return fnmatch.fnmatch(path, pattern) or (pattern.endswith("/**") and path.startswith(pattern[:-2]))


@pytest.mark.parametrize("shape", SHAPES)
def test_smoke_script_prints_the_contract_lines_ac_091_2(shape):  # AC-091.2
    text = (TEMPLATES / shape / "scripts" / "smoke.sh").read_text()
    assert "0 smoke tests" in text or "0 smoke tests" in (TEMPLATES / shape / "scripts" / HELPERS[shape]).read_text()
    helper = (TEMPLATES / shape / "scripts" / HELPERS[shape]).read_text()
    for token in ("PASS", "FAIL", "SKIP", "smoke:", "passed", "failed", "skipped"):
        assert token in text + helper, f"{shape}: no {token}"
    assert "SMOKE_BASE_URL" in text


@pytest.mark.parametrize("shape", SHAPES)
def test_each_fresh_skeleton_has_one_example_smoke_test_ac_091_4(shape):  # AC-091.4
    f = example_smoke_test(shape)
    assert f is not None, f"{shape}: no example smoke test"
    text = f.read_text()
    assert re.search(TAGS[shape], text), f"{shape}: the example carries no smoke tag"
    assert "SMOKE_BASE_URL" in text or "smoke_base_url" in text
    paths = {"service-python": "/health", "service-java": "/actuator/health/liveness", "service-go": "/health", "web-nextjs": '"/"'}
    assert paths[shape] in text


def test_python_example_reaches_the_service_only_through_the_url_ac_091_4():  # AC-091.4
    text = (TEMPLATES / "service-python/tests/test_smoke_health.py").read_text()
    assert "smoke_base_url" in text and "TestClient" not in text and not re.search(r"^\s*(from|import) (src|app)\b", text, re.M)


@pytest.mark.parametrize("shape", SHAPES)
def test_test_and_ci_never_send_smoke_tests_to_a_deployment_ac_091_4(shape):  # AC-091.4
    test = recipe(shape, "test")
    assert test is not None and re.search(r"SMOKE_BASE_URL=(?=\s)", test), f"{shape}: `test` does not empty SMOKE_BASE_URL"
    ci = recipe(shape, "ci")
    assert ci is not None and "devbox run smoke" not in ci and not re.search(r"SMOKE_BASE_URL=\S", ci)


def test_python_test_fast_and_web_e2e_empty_the_url_too_ac_091_4():  # AC-091.4
    assert re.search(r"SMOKE_BASE_URL=(?=\s)", recipe("service-python", "test-fast") or "")
    assert "-p scripts.smoke_pytest" in (recipe("service-python", "test") or "")
    assert re.search(r"SMOKE_BASE_URL=(?=\s)", recipe("web-nextjs", "e2e") or "")


def test_go_and_java_tests_skip_without_a_base_url_ac_091_4():  # AC-091.4
    go = example_smoke_test("service-go").read_text()
    assert 'os.Getenv("SMOKE_BASE_URL") == ""' in go and "t.Skip" in go
    java = example_smoke_test("service-java").read_text()
    assert "EnabledIfEnvironmentVariable" in java and "SMOKE_BASE_URL" in java and "java.net.http.HttpClient" in java


def test_web_example_skips_without_a_base_url_ac_091_4():  # AC-091.4
    assert "test.skip(!process.env.SMOKE_BASE_URL" in example_smoke_test("web-nextjs").read_text()


# ---------------- AC-091.3: no base URL, no test ----------------

@pytest.mark.parametrize("value", [None, ""])
@pytest.mark.parametrize("shape", SHAPES)
def test_smoke_without_a_base_url_runs_nothing_and_names_the_variable_ac_091_3(shape, value, tmp_path):  # AC-091.3
    shutil.copytree(TEMPLATES / shape / "scripts", tmp_path / "scripts")
    env = {k: v for k, v in os.environ.items() if k != "SMOKE_BASE_URL"}
    if value is not None:
        env["SMOKE_BASE_URL"] = value
    # a marker that proves nothing was started: every runner is replaced by a shim that records its call
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for tool in ("uv", "mvn", "go", "pnpm", "node", "java", "python", "python3"):
        shim = bindir / tool
        shim.write_text(f"#!/bin/sh\necho {tool} >> '{tmp_path}/ran'\nexit 0\n")
        shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
    env["PATH"] = f"{bindir}{os.pathsep}{env['PATH']}"
    res = subprocess.run(["bash", "scripts/smoke.sh"], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    assert res.returncode == 2
    assert GUARD in res.stderr.splitlines()
    assert not (tmp_path / "ran").exists()
    assert "PASS" not in res.stdout and "smoke:" not in res.stdout


# ---------------- AC-091.2: the python runner, executed for real ----------------

class _Health(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = json.dumps({"status": "ok"}).encode() if self.path == "/health" else b"{}"
        self.send_response(200 if self.path == "/health" else 404)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # silence
        pass


@pytest.fixture()
def health_server():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = HTTPServer(("127.0.0.1", port), _Health)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}"
    srv.shutdown()


UV_SHIM = f"""#!{sys.executable}
import importlib.util, os, sys
args = sys.argv[1:]
assert args and args[0] == "run", args
args = args[1:]
while args and args[0] not in ("python", "python3"):
    args = args[1:]
args[0] = {sys.executable!r}
if importlib.util.find_spec("pytest_cov") is None:
    args = [a for a in args if a != "--no-cov"]
os.execv(args[0], args)
"""

SMOKE_TESTS = '''import json
import urllib.request

import pytest


@pytest.mark.smoke
def test_health_answers(smoke_base_url):
    assert not smoke_base_url.endswith("/")
    with urllib.request.urlopen(smoke_base_url + "/health") as r:
        assert r.status == 200 and json.load(r)["status"] == "ok"


@pytest.mark.smoke
def test_waits_for_a_feature(smoke_base_url):
    pytest.skip("not for this environment")


def test_an_ordinary_test_never_runs_in_smoke():
    raise RuntimeError("ordinary tests must not run in `devbox run smoke`")
'''

FAILING = '''import pytest


@pytest.mark.smoke
def test_the_feature(smoke_base_url):
    assert False, "the feature is broken"
'''


def run_python_smoke(tmp_path, tests: dict[str, str], url: str | None):
    shutil.copytree(TEMPLATES / "service-python" / "scripts", tmp_path / "scripts", dirs_exist_ok=True)
    (tmp_path / "tests").mkdir(exist_ok=True)
    for name, text in tests.items():
        (tmp_path / "tests" / name).write_text(text)
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    uv = bindir / "uv"
    uv.write_text(UV_SHIM)
    uv.chmod(uv.stat().st_mode | stat.S_IEXEC)
    env = {k: v for k, v in os.environ.items() if k not in ("SMOKE_BASE_URL", "PYTEST_ADDOPTS", "PYTEST_CURRENT_TEST")}
    env["PATH"] = f"{bindir}{os.pathsep}{env['PATH']}"
    if url is not None:
        env["SMOKE_BASE_URL"] = url
    return subprocess.run(["bash", "scripts/smoke.sh"], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)


def test_python_smoke_runs_only_smoke_tests_against_the_url_ac_091_2(tmp_path, health_server):  # AC-091.2
    res = run_python_smoke(tmp_path, {"test_smoke_a.py": SMOKE_TESTS}, health_server + "/")
    lines = res.stdout.splitlines()
    assert "PASS  tests/test_smoke_a.py::test_health_answers" in lines
    assert "SKIP  tests/test_smoke_a.py::test_waits_for_a_feature" in lines
    assert "smoke: 1 passed, 0 failed, 1 skipped" in lines
    assert not any("ordinary" in ln and ln.startswith(("PASS", "FAIL")) for ln in lines)
    assert res.returncode == 0, res.stdout + res.stderr


def test_python_smoke_exits_non_zero_when_a_test_fails_ac_091_2(tmp_path, health_server):  # AC-091.2
    res = run_python_smoke(tmp_path, {"test_smoke_a.py": SMOKE_TESTS, "test_smoke_b.py": FAILING}, health_server)
    lines = res.stdout.splitlines()
    assert "FAIL  tests/test_smoke_b.py::test_the_feature" in lines and "PASS  tests/test_smoke_a.py::test_health_answers" in lines
    assert "smoke: 1 passed, 1 failed, 1 skipped" in lines
    assert lines.index("smoke: 1 passed, 1 failed, 1 skipped") > lines.index("FAIL  tests/test_smoke_b.py::test_the_feature")
    assert res.returncode == 1


def test_python_smoke_without_smoke_tests_exits_zero_ac_091_2(tmp_path, health_server):  # AC-091.2
    res = run_python_smoke(tmp_path, {"test_plain.py": "def test_x():\n    assert True\n"}, health_server)
    assert res.stdout.splitlines()[-1] == "0 smoke tests" and res.returncode == 0, res.stdout + res.stderr


def test_python_tests_skip_smoke_without_a_base_url_ac_091_4(tmp_path):  # AC-091.4
    """What `test` / `ci` do: the plugin is loaded, SMOKE_BASE_URL is empty, smoke tests are reported as skipped."""
    shutil.copytree(TEMPLATES / "service-python" / "scripts", tmp_path / "scripts")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_smoke_a.py").write_text(SMOKE_TESTS)
    env = {k: v for k, v in os.environ.items() if k not in ("PYTEST_ADDOPTS", "PYTEST_CURRENT_TEST")}
    env["SMOKE_BASE_URL"] = ""
    res = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-p", "scripts.smoke_pytest", "-p", "no:cacheprovider", "-q", "-rs",
                          "-k", "not ordinary"], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    assert res.returncode == 0 and "2 skipped" in res.stdout and "failed" not in res.stdout, res.stdout + res.stderr


# ---------------- AC-091.16 / AC-091.2: web-nextjs, standard Playwright scaffold ----------------

def test_web_template_does_not_gate_playwright_on_needs_e2e_ac_091_16():  # AC-091.16
    cfg = yaml.safe_load((TEMPLATES / "web-nextjs" / "copier.yml").read_text())
    assert not any("needs_e2e" in str(x) for x in cfg["_exclude"])
    q = cfg.get("needs_e2e")
    assert q is None or q.get("when") is False                 # kept only as a hidden question so old answers files still apply
    for rel in ("devbox.json.jinja", "package.json.jinja", "playwright.config.ts.jinja", "CLAUDE.md.jinja"):
        assert "if needs_e2e" not in (TEMPLATES / "web-nextjs" / rel).read_text(), rel


def test_web_playwright_config_uses_the_base_url_ac_091_16():  # AC-091.16
    text = (TEMPLATES / "web-nextjs" / "playwright.config.ts.jinja").read_text()
    assert "process.env.SMOKE_BASE_URL" in text and "baseURL" in text and "webServer" in text
    assert (TEMPLATES / "web-nextjs/e2e/home.spec.ts.jinja").is_file()        # the former local checks moved here
    assert "@smoke" in (TEMPLATES / "web-nextjs/e2e/smoke.spec.ts.jinja").read_text()
    assert "@smoke" not in (TEMPLATES / "web-nextjs/e2e/home.spec.ts.jinja").read_text()


def test_web_smoke_runs_in_the_browser_runner_ac_091_16():  # AC-091.16
    text = (TEMPLATES / "web-nextjs" / "scripts" / "smoke.sh").read_text()
    assert "playwright install chromium" in text and "playwright test" in text and "@smoke" in text
    assert "playwright install" not in (recipe("web-nextjs", "ci") or "") + (recipe("web-nextjs", "test") or "")


# ---------------- AC-091.2 / AC-091.16: updated repos ----------------

def git(repo, *a):
    return subprocess.run(["git", *a], cwd=repo, text=True, capture_output=True, check=True).stdout.strip()


def commit(repo, msg):
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", msg)


@pytest.fixture()
def old_web_repo(tmp_path, new_service):
    """A web repo made before spec 091 and with `needs_e2e: false`: no Playwright anywhere."""
    new_service(["old-web", "desc", "--web", "--no-github", "--skip-tasks", "--dir", str(tmp_path), "--org", "acme"])
    repo = tmp_path / "old-web"
    shutil.rmtree(repo / "e2e", ignore_errors=True)
    (repo / "playwright.config.ts").unlink(missing_ok=True)
    (repo / "scripts" / "smoke.sh").unlink(missing_ok=True)
    pkg = json.loads((repo / "package.json").read_text())
    pkg["devDependencies"].pop("@playwright/test", None)
    pkg["scripts"].pop("e2e", None)
    (repo / "package.json").write_text(json.dumps(pkg, indent=2) + "\n")
    dev = json.loads((repo / "devbox.json").read_text())
    dev["shell"]["scripts"].pop("smoke", None)
    dev["shell"]["scripts"].pop("e2e", None)
    (repo / "devbox.json").write_text(json.dumps(dev, indent=2) + "\n")
    answers = repo / ".copier-answers.yml"
    answers.write_text(re.sub(r"^needs_e2e:.*\n", "", answers.read_text(), flags=re.M) + "needs_e2e: false\n")
    commit(repo, "as before spec 091")
    return repo


def fake_devbox(monkeypatch, rc=0):
    calls = []
    real = update.run

    def run(cmd, **kw):
        if cmd[:2] == ["devbox", "run"]:
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, rc, "", "registry unreachable" if rc else "")
        return real(cmd, **kw)
    monkeypatch.setattr(update, "run", run)
    return calls


def test_a_fresh_web_repo_has_the_playwright_scaffold_by_default_ac_091_16(tmp_path):  # AC-091.16
    newsvc.main(["fresh-web", "desc", "--web", "--no-github", "--skip-tasks", "--dir", str(tmp_path), "--org", "acme"])
    repo = tmp_path / "fresh-web"
    assert (repo / "playwright.config.ts").is_file() and (repo / "e2e" / "smoke.spec.ts").is_file() and (repo / "e2e" / "home.spec.ts").is_file()
    pkg = json.loads((repo / "package.json").read_text())
    assert "@playwright/test" in pkg["devDependencies"] and "e2e" in pkg["scripts"]
    devbox = json.loads((repo / "devbox.json").read_text())["shell"]["scripts"]
    assert devbox["smoke"] == "bash scripts/smoke.sh" and "e2e" in devbox
    assert (repo / "scripts" / "smoke.sh").is_file()


def test_update_brings_the_scaffold_to_a_web_repo_that_opted_out_ac_091_16(old_web_repo, monkeypatch, capsys):  # AC-091.16
    repo = old_web_repo
    pkg = json.loads((repo / "package.json").read_text())
    pkg["dependencies"]["zod"] = "^3.23.0"
    (repo / "package.json").write_text(json.dumps(pkg, indent=2) + "\n")
    commit(repo, "own dependency")
    calls = fake_devbox(monkeypatch)
    capsys.readouterr()
    assert update.main(["--repo", str(repo), "--skip-tasks"]) == 0
    out = capsys.readouterr().out
    assert (repo / "playwright.config.ts").is_file()                   # not project-owned: it arrives although needs_e2e is false
    after = json.loads((repo / "package.json").read_text())
    assert "@playwright/test" in after["devDependencies"] and after["dependencies"]["zod"] == "^3.23.0"
    assert list(after).index("scripts") < list(after).index("dependencies")           # key order kept
    assert (repo / "package.json").read_text().startswith('{\n  "name"')               # 2-space indentation
    assert "did: added @playwright/test to package.json (spec 091: browser smoke tests)" in out or \
        "added @playwright/test to package.json (spec 091: browser smoke tests)" in out
    assert any("pnpm install --lockfile-only" in " ".join(c) for c in calls)


def test_update_tells_how_to_refresh_the_lockfile_when_it_fails_ac_091_16(old_web_repo, monkeypatch, capsys):  # AC-091.16
    fake_devbox(monkeypatch, rc=1)
    capsys.readouterr()
    assert update.main(["--repo", str(old_web_repo), "--skip-tasks"]) == 0
    assert "refresh the lockfile: devbox run -- pnpm install, then commit pnpm-lock.yaml" in capsys.readouterr().out


def test_update_does_not_touch_a_package_json_that_has_playwright_ac_091_16(old_web_repo, monkeypatch, capsys):  # AC-091.16
    pkg = json.loads((old_web_repo / "package.json").read_text())
    pkg["dependencies"]["@playwright/test"] = "^1.50.0"
    (old_web_repo / "package.json").write_text(json.dumps(pkg, indent=2) + "\n")
    commit(old_web_repo, "has playwright")
    calls = fake_devbox(monkeypatch)
    capsys.readouterr()
    assert update.main(["--repo", str(old_web_repo), "--skip-tasks"]) == 0
    assert "added @playwright/test" not in capsys.readouterr().out
    assert json.loads((old_web_repo / "package.json").read_text())["dependencies"]["@playwright/test"] == "^1.50.0"
    assert not any("--lockfile-only" in " ".join(c) for c in calls)
    assert (old_web_repo / "scripts" / "smoke.sh").is_file()           # the rest of the update still arrives


def test_update_delivers_the_smoke_script_and_recipe_ac_091_2(old_web_repo, monkeypatch):  # AC-091.2
    fake_devbox(monkeypatch)
    assert update.main(["--repo", str(old_web_repo), "--skip-tasks"]) == 0
    assert (old_web_repo / "scripts" / "smoke.sh").is_file() and (old_web_repo / "scripts" / "smoke-summary.mjs").is_file()
    assert json.loads((old_web_repo / "devbox.json").read_text())["shell"]["scripts"]["smoke"] == "bash scripts/smoke.sh"
    assert not (old_web_repo / "e2e" / "smoke.spec.ts").exists()        # project-owned path: an updated repo gets no example test
