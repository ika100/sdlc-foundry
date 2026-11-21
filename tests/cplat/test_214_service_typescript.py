"""Spec 214 acceptance tests: the service-typescript shape (Fastify on Node) and its svc-ts plugin.

Seams: the registry and the cplat modules that name shapes, the template files and their rendered variants (copier, rendered
once per process), the real `detect-shape.sh`, `smoke-summary.mjs` run with node on a Vitest JSON report, and `cplat component
new` / `cplat shape` in-process. Installing the packages, the Vitest coverage gate, the image build and the running service are
proved by the platform CI job `smoke-test-service-typescript` (all four variants), which these tests check exists.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

import cplat
import newsvc
import shapes

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "templates" / "service-typescript"
PLUGIN = ROOT / "plugins" / "svc-ts"
SHAPE = "service-typescript"


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
    key = f"214 {name} {sorted(data.items())}"
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


def package(repo: Path) -> dict:
    return json.loads((repo / "package.json").read_text())


# ---------------- AC-214.1: the registry ----------------

def test_the_registry_holds_the_shape_with_its_runtime_ac_214_1():  # AC-214.1
    e = entry()
    assert (e["plugin"], e["template"], e["deployable"], e["library"]) == ("svc-ts", SHAPE, True, False)
    assert e["default_stack"]["language"] == "typescript" and e["default_stack"]["framework"] == "fastify"
    rt = e["runtime"]
    assert rt["port"] == 8080 and rt["probes"] == {"liveness": "/health", "readiness": "/ready"} and rt["metrics"] == "/metrics"
    assert isinstance(rt["user"], int) and rt["user"] > 0
    assert shapes.validate(shapes.load_all()) == []


def test_service_typescript_is_a_pair_and_a_lone_typescript_stays_a_website_ac_214_1():  # AC-214.1
    assert newsvc.shape_of_pair("service", "typescript") == SHAPE
    assert newsvc.shape_of_pair(None, "typescript") == "web-nextjs"
    assert newsvc.shape_of_pair("website", "typescript") == "web-nextjs"
    assert ("service", "typescript") in newsvc.valid_pairs()


# ---------------- AC-214.2: creation and detection ----------------

def test_component_new_renders_the_template_ac_214_2(tmp_path):  # AC-214.2
    rc = cplat.main(["component", "new", "orders", "Order", "service", "--type", "service", "--lang", "typescript",
                     "--no-github", "--skip-tasks", "--org", "acme", "--dir", str(tmp_path)])
    assert rc == 0
    answers = (tmp_path / "orders" / ".copier-answers.yml").read_text()
    assert re.search(r"^_src_path: .*templates/service-typescript$", answers, re.M)
    assert (tmp_path / "orders" / "src" / "app.ts").is_file()


def _detect(repo: Path) -> str:
    return subprocess.run(["bash", str(ROOT / "scripts" / "detect-shape.sh"), str(repo)], capture_output=True, text=True).stdout.strip()


def test_detection_by_answers_and_by_a_fastify_package_ac_214_2(tmp_path):  # AC-214.2
    answers = tmp_path / "answers"
    answers.mkdir()
    (answers / ".copier-answers.yml").write_text("_src_path: gh:ika100/sdlc-foundry/templates/service-typescript\n")
    assert _detect(answers) == SHAPE
    sniff = tmp_path / "sniff"
    sniff.mkdir()
    (sniff / "package.json").write_text(json.dumps({"dependencies": {"fastify": "^5.0.0"}}))
    assert _detect(sniff) == SHAPE
    web = tmp_path / "web"
    web.mkdir()
    (web / "package.json").write_text(json.dumps({"dependencies": {"next": "16.0.0", "fastify": "^5.0.0"}}))
    assert _detect(web) == "web-nextjs"


def test_a_fresh_render_is_detected_ac_214_2(default):  # AC-214.2
    assert _detect(default) == SHAPE


# ---------------- AC-214.3: recipes and gates ----------------

CANONICAL = ["lint", "lint-fix", "typecheck", "quality", "test", "test-fast", "security", "secrets-baseline", "ci", "smoke",
             "image-build", "image-scan", "deps-findings", "deps-bump", "spec-check"]


def test_the_render_has_the_canonical_recipes_behind_the_gate_helper_ac_214_3(default):  # AC-214.3
    r = recipes(default)
    assert [n for n in CANONICAL if n not in r] == []
    assert r["test"].startswith("SMOKE_BASE_URL= bash scripts/gate.sh tests test vitest -- ")
    assert r["test-fast"].startswith("SMOKE_BASE_URL= bash scripts/gate.sh tests test-fast vitest -- ")
    assert r["ci"].endswith("then devbox run ci-extra; fi") and "devbox run quality" in r["ci"] and "devbox run security" in r["ci"]
    assert r["quality"] == "devbox run lint && devbox run typecheck"
    scripts = package(default)["scripts"]
    assert scripts["test"] == "vitest run --coverage" and scripts["lint"] == "eslint ." and scripts["typecheck"] == "tsc --noEmit"
    cfg = (default / "vitest.config.mts").read_text()
    assert "thresholds: { lines: 80, functions: 80, statements: 80 }" in cfg


# ---------------- AC-214.4: probes, metrics, logs, traces ----------------

def test_the_app_serves_the_probes_and_metrics_ac_214_4(default):  # AC-214.4
    app = (default / "src" / "app.ts").read_text()
    assert 'app.get("/health"' in app and 'app.get("/ready"' in app and "code(503)" in app
    metrics = (default / "src" / "metrics.ts").read_text()
    assert '"http_requests_total"' in metrics and '"http_request_duration_seconds"' in metrics
    assert '["method", "route", "status"]' in metrics and "collectDefaultMetrics" in metrics and 'app.get("/metrics"' in metrics
    logger = (default / "src" / "logger.ts").read_text()
    assert "trace_id" in logger and "span_id" in logger and "isSpanContextValid" in logger
    telemetry = (default / "src" / "telemetry.ts").read_text()
    assert "if (process.env.OTEL_EXPORTER_OTLP_ENDPOINT" in telemetry and "sdk.start()" in telemetry
    assert '"--import", "./dist/telemetry.js"' in (default / "Dockerfile").read_text()
    tests = {p.name for p in (default / "tests").glob("*.test.ts")}
    assert {"app.test.ts", "metrics.test.ts", "logger.test.ts"} <= tests


def test_without_observability_there_are_no_metrics_and_no_opentelemetry_ac_214_4(no_obs):  # AC-214.4
    assert not (no_obs / "src" / "metrics.ts").exists() and not (no_obs / "src" / "telemetry.ts").exists()
    assert not (no_obs / "tests" / "metrics.test.ts").exists()
    pkg = json.dumps(package(no_obs))
    assert "opentelemetry" not in pkg and "prom-client" not in pkg
    assert "--import" not in (no_obs / "Dockerfile").read_text() and "opentelemetry" not in (no_obs / "src" / "logger.ts").read_text()


# ---------------- AC-214.5: the image ----------------

def test_the_dockerfile_is_multi_stage_distroless_and_non_root_ac_214_5(default):  # AC-214.5
    text = (default / "Dockerfile").read_text()
    froms = re.findall(r"^FROM (\S+)", text, re.M)
    major = yaml.safe_load((default / ".copier-answers.yml").read_text())["node_major"]
    assert len(froms) >= 3 and froms[-1] == f"gcr.io/distroless/nodejs{major}-debian13"
    assert re.search(r"^USER \d+:\d+$", text, re.M)
    assert "pnpm prune --prod" in text and "--frozen-lockfile" in text
    assert package(default)["engines"]["node"] == f">={major}"
    assert f'"nodejs@{major}"' in (default / "devbox.json").read_text()


# ---------------- AC-214.6: CI ----------------

def _workflow(repo: Path) -> dict:
    return yaml.safe_load((repo / ".github" / "workflows" / "ci.yml").read_text())


def test_ci_has_the_service_job_set_and_the_registry_checks_ac_214_6(default):  # AC-214.6
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


# ---------------- AC-214.7: smoke ----------------

def test_the_smoke_runner_selects_smoke_tests_and_leaves_out_writes_when_read_only_ac_214_7():  # AC-214.7
    text = (TEMPLATE / "scripts" / "smoke.sh").read_text()
    assert "exit 2" in text and "--config vitest.smoke.config.mts" in text
    assert "'^(?!.*@writes).*@smoke'" in text and '"${SMOKE_READ_ONLY:-}" = "1"' in text
    assert re.search(entry()["smoke_tag"], (TEMPLATE / "tests" / "smoke" / "health.test.ts").read_text())
    assert "describe.skipIf(!base)" in (TEMPLATE / "tests" / "smoke" / "health.test.ts").read_text()


def _report(tmp_path: Path, tests: list[tuple[str, str]]) -> Path:
    report = {"testResults": [{"name": str(tmp_path / "tests" / "smoke" / "x.test.ts"),
                               "assertionResults": [{"title": t, "fullName": f"smoke {t}", "status": s} for t, s in tests]}]}
    f = tmp_path / "report.json"
    f.write_text(json.dumps(report))
    return f


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
@pytest.mark.parametrize("pattern, lines, code", [
    ("@smoke", ["PASS  tests/smoke/x.test.ts::health @smoke", "FAIL  tests/smoke/x.test.ts::create @smoke @writes",
                "smoke: 1 passed, 1 failed, 0 skipped"], 1),
    ("^(?!.*@writes).*@smoke", ["PASS  tests/smoke/x.test.ts::health @smoke", "smoke: 1 passed, 0 failed, 0 skipped"], 0),
])
def test_the_summary_prints_the_contract_lines_for_the_selected_tests_ac_214_7(tmp_path, pattern, lines, code):  # AC-214.7
    report = _report(tmp_path, [("health @smoke", "passed"), ("create @smoke @writes", "failed"), ("not smoke", "passed")])
    proc = subprocess.run(["node", str(TEMPLATE / "scripts" / "smoke-summary.mjs"), str(report)], cwd=tmp_path,
                          env={"PATH": shutil.os.environ["PATH"], "SMOKE_PATTERN": pattern}, capture_output=True, text=True)
    assert proc.stdout.splitlines() == lines and proc.returncode == code


# ---------------- AC-214.8: PostgreSQL ----------------

def test_the_database_variant_has_drizzle_migrations_and_testcontainers_ac_214_8(with_db):  # AC-214.8
    for rel in ("src/db/schema.ts", "src/db/client.ts", "drizzle/meta/_journal.json", "drizzle.config.ts", "tests/db.test.ts"):
        assert (with_db / rel).is_file(), rel
    deps = package(with_db)
    assert {"drizzle-orm", "pg"} <= set(deps["dependencies"]) and {"drizzle-kit", "@testcontainers/postgresql"} <= set(deps["devDependencies"])
    client = (with_db / "src" / "db" / "client.ts").read_text()
    assert all(v in client for v in ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD")) and "migrate(" in client
    assert "migrateWithRetry" in (with_db / "src" / "server.ts").read_text()
    r = recipes(with_db)
    assert "postgres:" in r["db-up"] and "drizzle-kit" in package(with_db)["scripts"]["migrate:new"] and "migrate-new" in r
    assert "PostgreSqlContainer" in (with_db / "tests" / "db.test.ts").read_text()
    assert "COPY --from=builder /app/drizzle ./drizzle" in (with_db / "Dockerfile").read_text()


def test_without_a_database_none_of_it_is_there_ac_214_8(default):  # AC-214.8
    assert not (default / "src" / "db").exists() and not (default / "drizzle").exists() and not (default / "tests" / "db.test.ts").exists()
    assert "drizzle" not in json.dumps(package(default)) and "db-up" not in recipes(default)


# ---------------- AC-214.9: the svc-ts plugin ----------------

AGENTS = ["coder", "tester", "deployment", "observability", "release"]


def test_the_plugin_has_its_agents_hook_readme_and_versions_ac_214_9():  # AC-214.9
    for a in AGENTS:
        front = yaml.safe_load((PLUGIN / "agents" / f"{a}.md").read_text().split("---")[1])
        assert front["name"] == a and front["description"] and front["tools"] and front["model"], a
    hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text())
    assert "SessionStart" in hooks["hooks"] and (PLUGIN / "README.md").is_file()
    version = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())["version"]
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    assert next(p["version"] for p in market["plugins"] if p["name"] == "svc-ts") == version


def test_the_template_enables_the_plugins_ac_214_9():  # AC-214.9
    text = (TEMPLATE / ".claude" / "settings.json.jinja").read_text()
    for p in ("svc-ts", "svc", "shared"):
        assert f'"{p}@sdlc-foundry": true' in text


def test_cplat_shape_routes_the_roles_of_a_rendered_repo_ac_214_9(default, capsys):  # AC-214.9
    assert cplat.main(["shape", "--repo", str(default)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["shape"] == SHAPE and out["agents"]["coder"] == "svc-ts:coder" and out["agents"]["architect"] == "svc:architect"
    assert out["agents"]["deployment"] == "svc-ts:deployment"


def test_every_svc_ts_prompt_has_a_register_file_ac_214_9():  # AC-214.9
    for a in AGENTS:
        assert (ROOT / "docs" / "rules" / "plugins" / "svc-ts" / "agents" / f"{a}.yml").is_file(), a


# ---------------- AC-214.10: shape-wide tooling ----------------

def test_the_platform_tooling_knows_the_shape_ac_214_10():  # AC-214.10
    import buildtests
    import comprelease
    import deps_parse
    import newapp
    import stages
    assert deps_parse.TOOLS[SHAPE] == "pnpm-audit" and "pnpm-lock.yaml" in deps_parse.DEP_FILES[SHAPE]
    assert SHAPE in buildtests.TEST_FAST and SHAPE in newapp.SHAPE_ORDER and SHAPE in stages._SERVICE_SHAPES
    assert comprelease.next_dev("v1.2.3", SHAPE, Path("/nonexistent")) == {"file": "package.json", "next": "1.2.4-dev.0"}
    for rel in ("scripts/template-image-scan.py", "scripts/bump_template_pins.py", "scripts/sync-template-copies.py",
                "scripts/template-lint.py", "scripts/ci-local.sh", "templates/gitops-app/scripts/plan.py"):
        assert SHAPE in (ROOT / rel).read_text(), rel
    assert '("service", "typescript")' in (ROOT / "templates" / "gitops-app" / "scripts" / "render.py").read_text()


def test_the_platform_ci_smoke_tests_the_template_ac_214_10():  # AC-214.10
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text())
    job = wf["jobs"]["smoke-test-service-typescript"]
    assert job["if"] == "needs.changes.outputs.ts == 'true'"
    assert {(v["observability"], v["database"]) for v in job["strategy"]["matrix"]["include"]} == {
        (True, False), (False, False), (True, True), (False, True)}
    steps = " ".join(str(s.get("run", "")) for s in job["steps"])
    for needle in ("detect-shape.sh", 'template-lint.py" service-typescript', "test-fast", "docker build", "scripts/smoke.sh",
                   "checked nothing: 0 tests ran"):
        assert needle in steps, needle
    assert "smoke-test-service-typescript" in wf["jobs"]["ci-success"]["needs"]
    lint = next(s["run"] for s in wf["jobs"]["validate-shapes"]["steps"] if "actionlint" in str(s.get("run", "")))
    assert SHAPE in lint


# ---------------- AC-214.11: docs ----------------

@pytest.mark.parametrize("rel", ["docs/templates.md", "site/src/content/docs/concepts/shapes.md", "docs/requirements/platform-vision.md",
                                 "CLAUDE.md", "docs/AGENTS.md"])
def test_the_docs_name_the_shape_and_plugin_ac_214_11(rel):  # AC-214.11
    text = (ROOT / rel).read_text()
    assert SHAPE in text and "svc-ts" in text, rel


def test_an_adr_records_the_stack_ac_214_11():  # AC-214.11
    adr = next((ROOT / "docs" / "adr").glob("*-service-typescript-stack.md")).read_text()
    for word in ("Fastify", "Drizzle", "pino", "Vitest", "pnpm", "distroless"):
        assert word in adr, word
