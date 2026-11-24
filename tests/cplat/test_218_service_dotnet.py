"""Spec 218 acceptance tests: the service-dotnet shape (ASP.NET Core minimal APIs) and its svc-dotnet plugin.

Seams: the registry and the cplat modules that name shapes, the template files and their rendered variants (copier, rendered
once per process), the real `detect-shape.sh`, `smoke-summary.sh` run with bash on a TRX report, the `dotnet` runner of
`gate.sh` with a stub `dotnet`, the .NET failure-summary parsers on recorded output, and `cplat component new` / `cplat shape`
in-process. Restoring the packages, the coverage gate, the image build and the running service are proved by the platform CI
job `smoke-test-service-dotnet` (all four variants), which these tests check exists.
"""
import json
import os
import re
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

import cplat
import newsvc
import shapes
from waiting import with_prelude

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "templates" / "service-dotnet"
PLUGIN = ROOT / "plugins" / "svc-dotnet"
SHAPE = "service-dotnet"


def entry() -> dict:
    return next(s for s in shapes.load() if s["id"] == SHAPE)


def _render(dest: Path, **data: str) -> Path:
    cmd = ["uv", "tool", "run", "--from", "copier", "copier", "copy", str(TEMPLATE), str(dest), "--defaults", "--trust", "--skip-tasks",
           "--data", f"project_name={dest.name}", "--data", "description=check"]
    for k, v in data.items():
        cmd += ["--data", f"{k}={v}"]
    subprocess.run(cmd, check=True, capture_output=True)
    return dest


def _copy(shared_renders, tmp_path: Path, name: str, **data: str) -> Path:
    key = f"218 {name} {sorted(data.items())}"
    return shared_renders.copy(key, lambda workdir: _render(workdir / name, **data), tmp_path / name)


@pytest.fixture()
def default(shared_renders, tmp_path):
    return _copy(shared_renders, tmp_path, "orders-api")


@pytest.fixture()
def no_obs(shared_renders, tmp_path):
    return _copy(shared_renders, tmp_path, "orders-plain", needs_observability="false")


@pytest.fixture()
def with_db(shared_renders, tmp_path):
    return _copy(shared_renders, tmp_path, "orders-db", needs_database="true")


def recipes(repo: Path) -> dict:
    return json.loads((repo / "devbox.json").read_text())["shell"]["scripts"]


def src(repo: Path, ns: str = "OrdersApi") -> Path:
    return repo / "src" / ns


def unit_tests(repo: Path, ns: str = "OrdersApi") -> Path:
    return repo / "tests" / f"{ns}.Tests"


# ---------------- AC-218.1: the registry ----------------

def test_the_registry_holds_the_shape_with_its_runtime_ac_218_1():  # AC-218.1
    e = entry()
    assert (e["plugin"], e["template"], e["deployable"], e["library"]) == ("svc-dotnet", SHAPE, True, False)
    assert e["default_stack"]["language"] == "csharp"
    rt = e["runtime"]
    assert rt["port"] == 8080 and rt["probes"] == {"liveness": "/health", "readiness": "/ready"} and rt["metrics"] == "/metrics"
    assert isinstance(rt["user"], int) and rt["user"] > 0
    assert any(g.endswith("*.cs") for g in e["test_globs"])
    assert shapes.validate(shapes.load_all()) == []


def test_service_csharp_is_a_pair_and_a_lone_csharp_is_a_service_ac_218_1():  # AC-218.1
    assert newsvc.shape_of_pair("service", "csharp") == SHAPE
    assert newsvc.shape_of_pair(None, "csharp") == SHAPE
    assert ("service", "csharp") in newsvc.valid_pairs()


# ---------------- AC-218.2: creation and detection ----------------

def test_component_new_renders_the_template_with_a_pascal_case_namespace_ac_218_2(tmp_path):  # AC-218.2
    rc = cplat.main(["component", "new", "order-api", "Order", "service", "--type", "service", "--lang", "csharp",
                     "--no-github", "--skip-tasks", "--org", "acme", "--dir", str(tmp_path)])
    assert rc == 0
    repo = tmp_path / "order-api"
    assert re.search(r"^_src_path: .*templates/service-dotnet$", (repo / ".copier-answers.yml").read_text(), re.M)
    assert (repo / "src" / "OrderApi" / "OrderApi.csproj").is_file() and (repo / "OrderApi.slnx").is_file()
    assert "namespace OrderApi;" in (repo / "src" / "OrderApi" / "ServiceApp.cs").read_text()


def _detect(repo: Path) -> str:
    return subprocess.run(["bash", str(ROOT / "scripts" / "detect-shape.sh"), str(repo)], capture_output=True, text=True).stdout.strip()


def test_detection_by_answers_and_by_a_project_with_a_dockerfile_ac_218_2(tmp_path):  # AC-218.2
    answers = tmp_path / "answers"
    answers.mkdir()
    (answers / ".copier-answers.yml").write_text("_src_path: gh:ika100/sdlc-foundry/templates/service-dotnet\n")
    assert _detect(answers) == SHAPE
    for name, files in {"slnx": ["Orders.slnx", "Dockerfile"], "sln": ["Orders.sln", "Dockerfile"],
                        "csproj": ["Orders/Orders.csproj", "Dockerfile"]}.items():
        d = tmp_path / name
        for f in files:
            (d / f).parent.mkdir(parents=True, exist_ok=True)
            (d / f).write_text("")
        assert _detect(d) == SHAPE, name
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "Orders.csproj").write_text("")
    assert _detect(lib) == "library-dotnet"   # without a Dockerfile a .NET project is a library (spec 221)


def test_a_fresh_render_is_detected_ac_218_2(default):  # AC-218.2
    assert _detect(default) == SHAPE


# ---------------- AC-218.3: recipes and gates ----------------

CANONICAL = ["install", "lint", "lint-fix", "typecheck", "quality", "test", "test-fast", "security", "secrets-baseline", "ci", "smoke",
             "image-build", "image-scan", "deps-findings", "deps-bump", "spec-check"]


def test_the_render_has_the_canonical_recipes_behind_the_gate_helper_ac_218_3(default):  # AC-218.3
    r = recipes(default)
    assert [n for n in CANONICAL if n not in r] == []
    assert r["test"].startswith("SMOKE_BASE_URL= bash scripts/gate.sh tests test dotnet -- dotnet test ")
    assert "-p:Threshold=80" in r["test"] and "-p:CollectCoverage=true" in r["test"]
    assert r["test-fast"].startswith("SMOKE_BASE_URL= bash scripts/gate.sh tests test-fast dotnet -- dotnet test")
    assert r["ci"].endswith("then devbox run ci-extra; fi") and "devbox run quality" in r["ci"] and "devbox run security" in r["ci"]
    assert r["quality"] == "devbox run lint && devbox run typecheck"
    assert "dotnet format --verify-no-changes" in r["lint"] and "--locked-mode" in r["install"]
    assert re.search(r'"dotnet-sdk_10@10\.\d+\.\d+"', (default / "devbox.json").read_text())
    props = (default / "Directory.Build.props").read_text()
    assert "<TreatWarningsAsErrors>true</TreatWarningsAsErrors>" in props and "<RestorePackagesWithLockFile>true" in props
    assert "coverlet.msbuild" in (unit_tests(default) / "OrdersApi.Tests.csproj").read_text()


def _stub_dotnet(bindir: Path, passed: int, failed: int) -> None:
    """A `dotnet test` stub that writes a TRX report with the given counters where --results-directory points."""
    script = f"""#!/bin/sh
dir=""
while [ $# -gt 0 ]; do
  case "$1" in --results-directory) dir="$2"; shift ;; esac
  shift
done
mkdir -p "$dir"
printf '<TestRun><ResultSummary outcome="x"><Counters total="%s" executed="%s" passed="{passed}" failed="{failed}" /></ResultSummary></TestRun>\\n' \\
  {passed + failed} {passed + failed} > "$dir/gate_1.trx"
[ {failed} -eq 0 ]
"""
    f = bindir / "dotnet"
    f.write_text(with_prelude(script))
    f.chmod(f.stat().st_mode | stat.S_IEXEC)


@pytest.mark.parametrize("passed, failed, code, nothing", [(0, 0, 1, True), (3, 0, 0, False), (2, 1, 1, False)])
def test_the_dotnet_runner_of_gate_sh_counts_the_trx_results_ac_218_3(tmp_path, passed, failed, code, nothing):  # AC-218.3
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _stub_dotnet(bindir, passed, failed)
    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"}
    proc = subprocess.run(["bash", str(TEMPLATE / "scripts" / "gate.sh"), "tests", "test-fast", "dotnet", "--", "dotnet", "test"],
                          cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    assert proc.returncode == code
    assert ("test-fast: checked nothing: 0 tests ran - add at least one test" in proc.stderr) is nothing


# ---------------- AC-218.4: probes, metrics, logs, traces ----------------

def test_the_app_serves_the_probes_and_metrics_ac_218_4(default):  # AC-218.4
    app = (src(default) / "ServiceApp.cs").read_text()
    assert 'MapHealthChecks("/health"' in app and 'MapHealthChecks("/ready"' in app and "Status503ServiceUnavailable" in app
    assert 'MapMetrics("/metrics")' in app
    metrics = (src(default) / "HttpMetrics.cs").read_text()
    assert '"http_requests_total"' in metrics and '"http_request_duration_seconds"' in metrics
    assert '["method", "route", "status"]' in metrics and "RoutePattern" in metrics
    formatter = (src(default) / "JsonLineFormatter.cs").read_text()
    assert '"trace_id"' in formatter and '"span_id"' in formatter and "Activity.Current" in formatter
    telemetry = (src(default) / "Telemetry.cs").read_text()
    assert '"OTEL_EXPORTER_OTLP_ENDPOINT"' in telemetry and "AddOtlpExporter()" in telemetry and '"OTEL_SDK_DISABLED"' in telemetry
    tests = {p.name for p in unit_tests(default).glob("*.cs")}
    assert {"AppTests.cs", "MetricsTests.cs", "LoggingTests.cs"} <= tests


def test_without_observability_there_are_no_metrics_and_no_opentelemetry_ac_218_4(no_obs):  # AC-218.4
    ns = "OrdersPlain"
    assert not (src(no_obs, ns) / "HttpMetrics.cs").exists() and not (src(no_obs, ns) / "Telemetry.cs").exists()
    assert not (unit_tests(no_obs, ns) / "MetricsTests.cs").exists()
    packages = (no_obs / "Directory.Packages.props").read_text() + (src(no_obs, ns) / f"{ns}.csproj").read_text()
    assert "OpenTelemetry" not in packages and "prometheus" not in packages.lower()
    assert "MapMetrics" not in (src(no_obs, ns) / "ServiceApp.cs").read_text()


# ---------------- AC-218.5: the image ----------------

def test_the_dockerfile_is_multi_stage_chiseled_and_non_root_ac_218_5(default):  # AC-218.5
    text = (default / "Dockerfile").read_text()
    froms = re.findall(r"^FROM (?:--platform=\S+ )?(\S+)", text, re.M)
    major = yaml.safe_load((default / ".copier-answers.yml").read_text())["dotnet_major"]
    assert len(froms) >= 2 and froms[0] == f"mcr.microsoft.com/dotnet/sdk:{major}.0"
    assert froms[-1] == f"mcr.microsoft.com/dotnet/aspnet:{major}.0-noble-chiseled"
    assert re.search(r"^USER \d+:\d+$", text, re.M) and "--locked-mode" in text and "DOTNET_EnableDiagnostics=0" in text
    assert f"<TargetFramework>net{major}.0</TargetFramework>" in (default / "Directory.Build.props").read_text()
    assert json.loads((default / "global.json").read_text())["sdk"]["version"].startswith(f"{major}.0.")
    assert f'"dotnet-sdk_{major}@' in (default / "devbox.json").read_text()


# ---------------- AC-218.6: CI ----------------

def _workflow(repo: Path) -> dict:
    return yaml.safe_load((repo / ".github" / "workflows" / "ci.yml").read_text())


def test_ci_has_the_service_job_set_and_the_registry_checks_ac_218_6(default):  # AC-218.6
    wf = _workflow(default)
    jobs = wf["jobs"]
    assert [j for j in ("quality", "test", "security", "ci-extra", "pr-title", "branch-name", "docker", "release-image",
                        "docker-publish", "pin-dev") if j not in jobs] == []
    assert jobs["pin-dev"]["needs"] == "docker-publish"
    assert wf["permissions"] == {"contents": "read"}
    names = {j.get("name") for j in jobs.values()}
    assert [c for c in entry()["ci_checks"] if c not in names] == []
    uses = [st["uses"] for j in jobs.values() for st in j.get("steps", []) if "uses" in st]
    assert uses and all(re.search(r"@[0-9a-f]{40}$", u.split(" ")[0]) for u in uses), uses


# ---------------- AC-218.7: smoke ----------------

def test_the_smoke_runner_selects_smoke_tests_and_leaves_out_writes_when_read_only_ac_218_7():  # AC-218.7
    text = (TEMPLATE / "scripts" / "smoke.sh").read_text()
    assert "exit 2" in text and 'filter="Category=smoke"' in text
    assert 'filter="Category=smoke&Category!=writes"' in text and '"${SMOKE_READ_ONLY:-}" = "1"' in text
    example = (TEMPLATE / "tests" / "{{ namespace }}.Tests" / "Smoke" / "HealthSmokeTests.cs.jinja").read_text()
    assert re.search(entry()["smoke_tag"], example) and "Assert.SkipWhen(string.IsNullOrEmpty(baseUrl)" in example
    assert '"/health"' in example


TRX = """<?xml version="1.0" encoding="utf-8"?>
<TestRun>
  <Results>
    <UnitTestResult executionId="e1" testId="t1" testName="Orders.Tests.Smoke.HealthSmokeTests.Health_answers_ok" outcome="Passed" />
    <UnitTestResult executionId="e2" testId="t2" testName="Orders.Tests.Smoke.HealthSmokeTests.Creates_an_order" outcome="Failed">
    </UnitTestResult>
    <UnitTestResult executionId="e3" testId="t3" testName="Orders.Tests.Smoke.HealthSmokeTests.Later" outcome="NotExecuted" />
  </Results>
  <TestDefinitions>
    <UnitTest name="Health_answers_ok" id="t1"><Execution id="e1" />
      <TestMethod codeBase="x.dll" className="Orders.Tests.Smoke.HealthSmokeTests" name="Health_answers_ok" /></UnitTest>
    <UnitTest name="Creates_an_order" id="t2"><Execution id="e2" />
      <TestMethod codeBase="x.dll" className="Orders.Tests.Smoke.HealthSmokeTests" name="Creates_an_order" /></UnitTest>
    <UnitTest name="Later" id="t3"><Execution id="e3" />
      <TestMethod codeBase="x.dll" className="Orders.Tests.Smoke.HealthSmokeTests" name="Later" /></UnitTest>
  </TestDefinitions>
</TestRun>
"""


def test_the_summary_prints_the_contract_lines_with_the_test_file_path_ac_218_7(tmp_path):  # AC-218.7
    (tmp_path / "tests" / "Orders.Tests" / "Smoke").mkdir(parents=True)
    (tmp_path / "tests" / "Orders.Tests" / "Smoke" / "HealthSmokeTests.cs").write_text("public sealed class HealthSmokeTests {}\n")
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "smoke.trx").write_text(TRX)
    proc = subprocess.run(["bash", str(TEMPLATE / "scripts" / "smoke-summary.sh"), "results"], cwd=tmp_path, capture_output=True,
                          text=True, timeout=60)
    path = "tests/Orders.Tests/Smoke/HealthSmokeTests.cs"
    assert proc.stdout.splitlines() == [f"FAIL  {path}::Creates_an_order", f"PASS  {path}::Health_answers_ok", f"SKIP  {path}::Later",
                                        "smoke: 1 passed, 1 failed, 1 skipped"]
    assert proc.returncode == 1
    empty = subprocess.run(["bash", str(TEMPLATE / "scripts" / "smoke-summary.sh"), "nowhere"], cwd=tmp_path, capture_output=True,
                           text=True, timeout=60)
    assert empty.returncode == 2


# ---------------- AC-218.8: PostgreSQL ----------------

def test_the_database_variant_has_ef_core_migrations_and_testcontainers_ac_218_8(with_db):  # AC-218.8
    ns = "OrdersDb"
    data = src(with_db, ns) / "Data"
    for rel in ("AppDbContext.cs", "DatabaseSettings.cs", "DatabaseSetup.cs", "Migrations/README.md"):
        assert (data / rel).is_file(), rel
    assert "dotnet-ef" in (with_db / ".config" / "dotnet-tools.json").read_text()
    packages = (with_db / "Directory.Packages.props").read_text()
    assert "Npgsql.EntityFrameworkCore.PostgreSQL" in packages and "Testcontainers.PostgreSql" in packages
    settings = (data / "DatabaseSettings.cs").read_text()
    assert all(f'"{v}"' in settings for v in ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD"))
    setup = (data / "DatabaseSetup.cs").read_text()
    assert "MigrateAsync" in setup and "AddDbContextCheck" in setup and "Task.Yield()" in setup
    r = recipes(with_db)
    assert "postgres:" in r["db-up"] and "dotnet ef migrations add" in r["migrate-new"] and "dotnet tool restore" in r["install"]
    assert "PostgreSqlBuilder" in (unit_tests(with_db, ns) / "DatabaseTests.cs").read_text()


def test_without_a_database_none_of_it_is_there_ac_218_8(default):  # AC-218.8
    assert not (src(default) / "Data").exists() and not (default / ".config").exists()
    assert not (unit_tests(default) / "DatabaseTests.cs").exists()
    assert "EntityFrameworkCore" not in (default / "Directory.Packages.props").read_text() and "db-up" not in recipes(default)


# ---------------- AC-218.9: the svc-dotnet plugin ----------------

AGENTS = ["coder", "tester", "deployment", "observability", "release"]


def test_the_plugin_has_its_agents_hook_readme_and_versions_ac_218_9():  # AC-218.9
    for a in AGENTS:
        front = yaml.safe_load((PLUGIN / "agents" / f"{a}.md").read_text().split("---")[1])
        assert front["name"] == a and front["description"] and front["tools"] and front["model"], a
    hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text())
    assert "SessionStart" in hooks["hooks"] and (PLUGIN / "README.md").is_file()
    version = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())["version"]
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    assert next(p["version"] for p in market["plugins"] if p["name"] == "svc-dotnet") == version


def test_the_template_enables_the_plugins_ac_218_9():  # AC-218.9
    text = (TEMPLATE / ".claude" / "settings.json.jinja").read_text()
    for p in ("svc-dotnet", "svc", "shared"):
        assert f'"{p}@sdlc-foundry": true' in text


def test_cplat_shape_routes_the_roles_of_a_rendered_repo_ac_218_9(default, capsys):  # AC-218.9
    assert cplat.main(["shape", "--repo", str(default)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["shape"] == SHAPE and out["agents"]["coder"] == "svc-dotnet:coder" and out["agents"]["architect"] == "svc:architect"
    assert out["agents"]["deployment"] == "svc-dotnet:deployment"


def test_every_svc_dotnet_prompt_has_a_register_file_ac_218_9():  # AC-218.9
    for a in AGENTS:
        assert (ROOT / "docs" / "rules" / "plugins" / "svc-dotnet" / "agents" / f"{a}.yml").is_file(), a


# ---------------- AC-218.10: shape-wide tooling ----------------

def test_the_platform_tooling_knows_the_shape_ac_218_10():  # AC-218.10
    import buildtests
    import comprelease
    import deps_parse
    import newapp
    import stages
    assert deps_parse.TOOLS[SHAPE] == "trivy" and "Directory.Packages.props" in deps_parse.DEP_FILES[SHAPE]
    assert SHAPE in buildtests.TEST_FAST and SHAPE in newapp.SHAPE_ORDER and SHAPE in stages._SERVICE_SHAPES
    assert comprelease.next_dev("v1.2.3", SHAPE, Path("/nonexistent")) is None   # the image tag is the version
    for rel in ("scripts/template-image-scan.py", "scripts/bump_template_pins.py", "scripts/sync-template-copies.py",
                "scripts/template-lint.py", "scripts/ci-local.sh", "templates/gitops-app/scripts/plan.py"):
        assert SHAPE in (ROOT / rel).read_text(), rel
    assert '("service", "csharp")' in (ROOT / "templates" / "gitops-app" / "scripts" / "render.py").read_text()


def test_deps_reads_the_central_versions_and_finds_the_lock_files_ac_218_10(tmp_path):  # AC-218.10
    import deps_parse
    (tmp_path / "Directory.Packages.props").write_text('<Project><ItemGroup>\n'
                                                       '<PackageVersion Include="Npgsql" Version="10.0.0" />\n</ItemGroup></Project>\n')
    for rel in ("src/A/packages.lock.json", "tests/A.Tests/packages.lock.json", "src/A/obj/packages.lock.json"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("{}")
    assert deps_parse.declared(SHAPE, tmp_path) == {"Npgsql"}
    assert deps_parse.dep_files(SHAPE, tmp_path) == ("Directory.Packages.props", "src/A/packages.lock.json",
                                                     "tests/A.Tests/packages.lock.json")
    bump = (TEMPLATE / "scripts" / "deps.sh").read_text()
    assert "--force-evaluate" in bump and "Directory.Packages.props" in bump


def test_build_tests_filters_dotnet_test_by_the_test_classes_ac_218_10(tmp_path):  # AC-218.10
    import buildtests
    f = tmp_path / "tests" / "A.Tests" / "OrdersTests.cs"
    f.parent.mkdir(parents=True)
    f.write_text("public sealed class OrdersTests { }\n")
    assert buildtests._args(tmp_path, "dotnet", ["tests/A.Tests/OrdersTests.cs"]) == ["--filter", "FullyQualifiedName~.OrdersTests."]


TEST_OUT = """  Failed Orders.Tests.ConfigTests.Defaults_apply [3 ms]
  Error Message:
   Assert.Equal() Failure: Values differ
Expected: 8081
Actual:   8080
  Stack Trace:
     at Orders.Tests.ConfigTests.Defaults_apply() in /repo/tests/Orders.Tests/ConfigTests.cs:line 10
   at System.Reflection.MethodBaseInvoker.InterpretedInvoke_Method(Object obj, IntPtr* args)
Failed!  - Failed:     1, Passed:    30, Skipped:     1, Total:    32, Duration: 312 ms - Orders.Tests.dll (net10.0)
"""
BUILD_OUT = """/repo/src/Orders/Broken.cs(1,58): error CS0029: Cannot implicitly convert type 'string' to 'int' [/repo/src/Orders/Orders.csproj]
Build FAILED.
/repo/src/Orders/Broken.cs(1,58): error CS0029: Cannot implicitly convert type 'string' to 'int' [/repo/src/Orders/Orders.csproj]
"""


def test_failure_summaries_read_dotnet_test_and_build_output_ac_218_10():  # AC-218.10
    import failsum
    test = failsum.summarize(TEST_OUT, title="t", check="test", command="devbox run test", exit_code=1, log=Path("/l"), root=Path("/repo"))
    text = test.render()
    assert "format: dotnet-test" in text and "Orders.Tests.ConfigTests.Defaults_apply at tests/Orders.Tests/ConfigTests.cs:10" in text
    assert "Values differ" in text
    build = failsum.summarize(BUILD_OUT, title="t", check="typecheck", command="devbox run typecheck", exit_code=1, log=Path("/l"),
                              root=Path("/repo"))
    text = build.render()
    assert "format: msbuild" in text and "entries: 1" in text and "src/Orders/Broken.cs:1 | CS0029" in text


def test_the_platform_ci_smoke_tests_the_template_ac_218_10():  # AC-218.10
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text())
    job = wf["jobs"]["smoke-test-service-dotnet"]
    assert job["if"] == "needs.changes.outputs.dotnet == 'true'"
    assert {(v["observability"], v["database"]) for v in job["strategy"]["matrix"]["include"]} == {
        (True, False), (False, False), (True, True), (False, True)}
    steps = " ".join(str(s.get("run", "")) for s in job["steps"])
    for needle in ("detect-shape.sh", 'template-lint.py" service-dotnet', "test-fast", "docker build", "scripts/smoke.sh",
                   "checked nothing: 0 tests ran", "--read-only"):
        assert needle in steps, needle
    assert "smoke-test-service-dotnet" in wf["jobs"]["ci-success"]["needs"]
    lint = next(s["run"] for s in wf["jobs"]["validate-shapes"]["steps"] if "actionlint" in str(s.get("run", "")))
    assert SHAPE in lint


# ---------------- AC-218.11: docs ----------------

@pytest.mark.parametrize("rel", ["docs/templates.md", "site/src/content/docs/concepts/shapes.md", "docs/requirements/platform-vision.md",
                                 "CLAUDE.md", "docs/AGENTS.md"])
def test_the_docs_name_the_shape_and_plugin_ac_218_11(rel):  # AC-218.11
    text = (ROOT / rel).read_text()
    assert SHAPE in text and "svc-dotnet" in text, rel


def test_an_adr_records_the_stack_ac_218_11():  # AC-218.11
    adr = next((ROOT / "docs" / "adr").glob("*-service-dotnet-stack.md")).read_text()
    for word in ("minimal APIs", "EF Core", "prometheus-net", "OpenTelemetry", "xUnit", "chiseled"):
        assert word in adr, word
