"""Spec 130 acceptance tests: a quality gate that checked nothing fails (AC-130.1 to AC-130.16).

This is the platform test of AC-130.14: for each of the 7 templates it renders the template once, runs every covered gate against empty
input with stub tools first on PATH and asserts a non-zero exit and the AC-130.1 line
`<gate>: checked nothing: <what was empty> - <how to fix>`. A template in the shape registry without coverage here fails the suite.
Contract: docs/specs/130-quality-gates-fail-when-they-checked/design.md ("Contract"). `scripts/gate.sh` itself is tested in
test_130_gate_sh.py; the stub tools and renders are in gates130_support.py.

Nothing here runs a real toolchain (no go, mvn, pnpm, kustomize, kubeconform): the recipes of the rendered devbox.json run under
`sh -c`, the render scripts of the two gitops templates run for real."""
import fnmatch
import json
import re
import subprocess

import pytest
import yaml

import core
from gates130_support import (COVERED, EXCLUDED_FILE, FIX_TESTS, GATE_SOURCE, GITOPS_TEMPLATES, ROOT, SECRET_FLAGS,
                              SECRET_PATHSPEC, TEMPLATES, TEST_TEMPLATES, clean_env, make_stubs, nothing_lines, recipe_of,
                              recipes, render_line, rendered_repo, run_sh, secrets_line, no_tests_line, validate_line)

ALL_TEMPLATES = list(COVERED)
PYTHON = ["service-python", "library-python"]
GATES = ["test", "test-fast"]


@pytest.fixture(scope="session")
def stubs(tmp_path_factory):
    return make_stubs(tmp_path_factory.mktemp("stubs130"))


@pytest.fixture()
def world(shared_renders, tmp_path, stubs):
    """world(template, track=True, **env) -> (repo, env): a private rendered repo and the stub environment."""
    def make(template, track=True, **env):
        repo = rendered_repo(shared_renders, template, tmp_path / f"repo-{template}", track)
        log = tmp_path / "stub.log"
        return repo, clean_env(stubs, STUB_LOG=str(log), **env)
    make.log = lambda: (tmp_path / "stub.log").read_text() if (tmp_path / "stub.log").exists() else ""
    return make


def assert_red(proc, expected: str, code: int | None = None):
    assert proc.returncode != 0, f"gate passed although it checked nothing\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    if code is not None:
        assert proc.returncode == code, f"exit {proc.returncode}, expected {code}\n{proc.stderr}"
    lines = proc.stderr.splitlines()
    assert expected in lines, f"missing line on stderr: {expected!r}\nstderr:\n{proc.stderr}"
    assert len(nothing_lines(proc)) == 1, f"expected exactly one 'checked nothing' line:\n{proc.stderr}"


def empty_env(template: str) -> dict:
    """The stub environment under which the template's test runner reports no tests."""
    if template in PYTHON:
        return {"STUB_PYTEST": "empty", "STUB_PYTEST_EXIT": "5"}
    return {"service-go": {"STUB_GO": "empty"}, "service-java": {"STUB_MVN": "empty"},
            "web-nextjs": {"STUB_VITEST": "nofiles"}}.get(template, {})


def drop_system(repo):
    for f in repo.glob("applications/*/system.yaml"):
        f.unlink()


def empty_case(template: str, gate: str):
    """(track, setup(repo), env, expected line) of `gate` checking nothing in `template`."""
    nop = lambda repo: None   # noqa: E731
    if gate == "secrets-scan":
        return False, nop, {}, secrets_line()
    if template in TEST_TEMPLATES:
        return True, nop, empty_env(template), no_tests_line(gate)
    if gate in ("test", "validate"):
        return True, nop, {}, validate_line(template)
    if template == "gitops-app":
        return True, drop_system, {}, render_line(template, gate)
    return True, nop, {"STUB_RENDER_EMPTY": "1"}, render_line(template, gate)


# ---------------- AC-130.14: the coverage table ----------------

def test_the_coverage_table_names_exactly_the_templates_of_the_shape_registry_ac_130_14():  # AC-130.14
    registered = sorted({str(s["template"]).split("/")[-1] for s in core.registry.load() if s.get("template")})
    assert sorted(COVERED) == registered, "a template in shapes.yml without coverage here (or a stale row): add it to COVERED"
    on_disk = sorted(p.name for p in TEMPLATES.iterdir() if p.is_dir())
    assert sorted(COVERED) == on_disk


@pytest.mark.parametrize("template", ALL_TEMPLATES)
def test_every_covered_gate_is_a_recipe_of_the_rendered_template_ac_130_14(world, template):  # AC-130.14
    repo, _ = world(template)
    missing = [g for g in COVERED[template] if g not in recipes(repo)]
    assert not missing, f"{template}: no recipe {missing} in the rendered devbox.json"


@pytest.mark.parametrize("template", ALL_TEMPLATES)
def test_every_template_ships_gate_sh_byte_identical_to_the_source_ac_130_14(world, template):  # AC-130.1
    repo, _ = world(template)
    assert (repo / "scripts" / "gate.sh").read_bytes() == GATE_SOURCE.read_bytes()


# ---------------- AC-130.1 / AC-130.14: every covered gate of every template against empty input ----------------

MATRIX = [(t, g) for t in ALL_TEMPLATES for g in COVERED[t]]


@pytest.mark.parametrize("template,gate", MATRIX)
def test_a_covered_gate_that_checked_nothing_exits_non_zero_with_the_line_ac_130_1(world, template, gate):  # AC-130.1, AC-130.14
    track, setup, env, expected = empty_case(template, gate)
    repo, e = world(template, track, **env)
    setup(repo)
    proc = run_sh(recipe_of(repo, gate), repo, e)
    assert_red(proc, expected)


# ---------------- AC-130.2: python ----------------

@pytest.mark.parametrize("template", PYTHON)
@pytest.mark.parametrize("gate", GATES)
def test_pytest_exit_5_no_tests_collected_is_passed_through_with_the_line_ac_130_2(world, template, gate):  # AC-130.2
    repo, e = world(template, STUB_PYTEST="empty", STUB_PYTEST_EXIT="5")
    assert_red(run_sh(recipe_of(repo, gate), repo, e), no_tests_line(gate), code=5)


@pytest.mark.parametrize("template", PYTHON)
@pytest.mark.parametrize("gate", GATES)
def test_pytest_reporting_no_tests_with_exit_0_still_fails_ac_130_2(world, template, gate):  # AC-130.2
    repo, e = world(template, STUB_PYTEST="empty", STUB_PYTEST_EXIT="0")
    assert_red(run_sh(recipe_of(repo, gate), repo, e), no_tests_line(gate))


@pytest.mark.parametrize("template", PYTHON)
def test_the_fix_names_adding_a_test_ac_130_2(world, template):  # AC-130.2
    repo, e = world(template, **empty_env(template))
    proc = run_sh(recipe_of(repo, "test"), repo, e)
    assert f"0 tests ran - {FIX_TESTS}" in proc.stderr


# ---------------- AC-130.3: go ----------------

@pytest.mark.parametrize("gate", GATES)
def test_go_packages_without_test_functions_fail_with_the_line_ac_130_3(world, gate):  # AC-130.3
    repo, e = world("service-go", STUB_GO="empty")
    assert_red(run_sh(recipe_of(repo, gate), repo, e), no_tests_line(gate))


@pytest.mark.parametrize("gate", GATES)
def test_go_recipes_run_verbose_so_the_result_lines_can_be_counted_ac_130_3(world, gate):  # AC-130.3
    repo, e = world("service-go", STUB_GO="empty")
    run_sh(recipe_of(repo, gate), repo, e)
    assert re.search(r"go test .*-v\b", world.log()), world.log()


# ---------------- AC-130.4: java ----------------

@pytest.mark.parametrize("gate", GATES)
def test_maven_without_test_methods_fails_with_the_line_ac_130_4(world, gate):  # AC-130.4
    repo, e = world("service-java", STUB_MVN="empty")
    assert_red(run_sh(recipe_of(repo, gate), repo, e), no_tests_line(gate))


@pytest.mark.parametrize("gate", GATES)
def test_a_stale_surefire_report_does_not_count_as_a_test_that_ran_ac_130_4(world, gate):  # AC-130.4
    repo, e = world("service-java", STUB_MVN="empty")
    stale = repo / "target" / "surefire-reports"
    stale.mkdir(parents=True)
    (stale / "TEST-old.xml").write_text('<testsuite name="old" tests="4" errors="0" skipped="0" failures="0"></testsuite>')
    assert_red(run_sh(recipe_of(repo, gate), repo, e), no_tests_line(gate))


def test_no_java_recipe_or_pom_skips_the_test_phase_ac_130_4():  # AC-130.4
    skip = re.compile(r"skipTests|skipITs|maven\.test\.skip|-DskipT", re.I)
    for gate in GATES + ["ci"]:
        text = _template_recipe("service-java", gate)
        assert not skip.search(text), f"{gate}: {text}"
    assert not skip.search((TEMPLATES / "service-java" / "pom.xml.jinja").read_text())


# ---------------- AC-130.5: web ----------------

@pytest.mark.parametrize("gate", GATES)
@pytest.mark.parametrize("mode", ["nofiles", "zero"])
def test_a_web_repo_without_test_files_fails_with_the_line_ac_130_5(world, gate, mode):  # AC-130.5
    repo, e = world("web-nextjs", STUB_VITEST=mode)
    assert_red(run_sh(recipe_of(repo, gate), repo, e), no_tests_line(gate))


@pytest.mark.parametrize("gate", GATES)
def test_the_web_gate_asks_vitest_for_its_json_report_ac_130_5(world, gate):  # AC-130.5
    repo, e = world("web-nextjs", STUB_VITEST="pass")
    proc = run_sh(recipe_of(repo, gate), repo, e)
    assert proc.returncode == 0, proc.stderr   # the stub exits 97 when VITEST_GATE_REPORT is not set
    assert "VITEST_GATE_REPORT" not in proc.stderr


def test_no_web_script_or_config_passes_with_no_tests_ac_130_5():  # AC-130.5
    pat = re.compile(r"pass[-_]?with[-_]?no[-_]?tests", re.I)
    pkg = (TEMPLATES / "web-nextjs" / "package.json.jinja").read_text()
    scripts = json.loads(re.sub(r"\{%.*?%\}", "", re.sub(r"\{\{.*?\}\}", "x", pkg)))["scripts"]
    for name in ("test", "test:fast"):
        assert not pat.search(scripts[name]), f"{name}: {scripts[name]}"
    assert not pat.search((TEMPLATES / "web-nextjs" / "vitest.config.mts").read_text())
    for gate in GATES:
        assert not pat.search(_template_recipe("web-nextjs", gate))


def test_vitest_config_writes_the_json_report_only_under_the_gate_ac_130_5():  # AC-130.5
    text = (TEMPLATES / "web-nextjs" / "vitest.config.mts").read_text()
    assert "VITEST_GATE_REPORT" in text
    assert re.search(r"reporters\s*:\s*\[\s*[\"']default[\"']\s*,\s*[\"']json[\"']\s*\]", text)
    assert re.search(r"outputFile\s*:\s*\{\s*json\s*:", text)


# ---------------- AC-130.6: skipped tests do not count ----------------

SKIPPED = {"service-python": {"STUB_PYTEST": "skipped"}, "library-python": {"STUB_PYTEST": "skipped"},
           "service-go": {"STUB_GO": "skipped"}, "service-java": {"STUB_MVN": "skipped"}, "web-nextjs": {"STUB_VITEST": "skipped"}}


@pytest.mark.parametrize("template", TEST_TEMPLATES)
@pytest.mark.parametrize("gate", GATES)
def test_a_run_where_every_collected_test_was_skipped_fails_ac_130_6(world, template, gate):  # AC-130.6
    repo, e = world(template, **SKIPPED[template])
    assert_red(run_sh(recipe_of(repo, gate), repo, e), no_tests_line(gate))


@pytest.mark.parametrize("gate", GATES)
def test_some_skipped_tests_next_to_a_test_that_ran_still_pass_ac_130_6(world, gate):  # AC-130.6
    repo, e = world("service-python", STUB_PYTEST="mixed")
    proc = run_sh(recipe_of(repo, gate), repo, e)
    assert proc.returncode == 0 and "checked nothing" not in proc.stderr, proc.stderr


# ---------------- AC-130.7 / AC-130.8: validate counts resources ----------------

@pytest.mark.parametrize("gate", ["validate", "test"])
def test_gitops_app_validate_with_zero_resources_fails_with_the_line_ac_130_7(world, gate):  # AC-130.7
    repo, e = world("gitops-app")
    assert_red(run_sh(recipe_of(repo, gate), repo, e), validate_line("gitops-app"))


def test_gitops_app_validate_fix_text_is_the_contract_ac_130_7(world):  # AC-130.7
    repo, e = world("gitops-app")
    proc = run_sh(recipe_of(repo, "validate"), repo, e)
    assert "validate: checked nothing: 0 resources - run `devbox run render` and check that the system has components" in proc.stderr


def test_gitops_app_validate_counts_what_kubeconform_reports_not_the_files_it_visited_ac_130_7(world):  # AC-130.7
    repo, e = world("gitops-app", STUB_KUBECONFORM="Summary: 0 resources found in 2 files - Valid: 0, Invalid: 0, Errors: 0, Skipped: 0")
    assert_red(run_sh(recipe_of(repo, "validate"), repo, e), validate_line("gitops-app"))
    assert "kubeconform" in world.log()


@pytest.mark.parametrize("gate", ["validate", "test"])
def test_cluster_gitops_empty_build_keeps_failing_prints_the_summary_and_the_line_ac_130_8(world, gate):  # AC-130.8
    repo, e = world("cluster-gitops")
    proc = run_sh(recipe_of(repo, gate), repo, e)
    assert_red(proc, validate_line("cluster-gitops"))
    assert "Summary: 0 resource" in proc.stdout, "kubeconform's summary is still printed"


def test_cluster_gitops_validate_fix_text_is_the_contract_ac_130_8(world):  # AC-130.8
    repo, e = world("cluster-gitops")
    proc = run_sh(recipe_of(repo, "validate"), repo, e)
    assert ("validate: checked nothing: 0 resources - run `devbox run render` and check that cluster/kustomization.yaml lists resources"
            in proc.stderr)
    assert "validate: kubeconform checked 0 resources" not in proc.stderr, "the #278 line is replaced by the AC-130.1 line"


def test_cluster_gitops_invalid_resources_still_fail_without_the_empty_line_ac_130_8(world):  # AC-130.8
    repo, e = world("cluster-gitops", STUB_KUBECONFORM="Summary: 3 resources found in 1 file - Valid: 2, Invalid: 1, Errors: 0, Skipped: 0",
                    STUB_KUBECONFORM_EXIT="1", STUB_KUSTOMIZE="kind: Namespace")
    proc = run_sh(recipe_of(repo, "validate"), repo, e)
    assert proc.returncode != 0
    assert "checked nothing" not in proc.stderr


# ---------------- AC-130.9: render-check compares files ----------------

@pytest.mark.parametrize("gate", ["render-check", "test-fast"])
def test_gitops_app_render_check_without_a_system_fails_with_the_line_ac_130_9(world, gate):  # AC-130.9
    repo, e = world("gitops-app")
    drop_system(repo)
    proc = run_sh(recipe_of(repo, gate), repo, e)
    assert_red(proc, render_line("gitops-app", gate))
    assert "OK: up to date" not in proc.stdout


@pytest.mark.parametrize("gate", ["render-check", "test-fast"])
def test_cluster_gitops_render_check_comparing_zero_files_fails_with_the_line_ac_130_9(world, gate):  # AC-130.9
    repo, e = world("cluster-gitops", STUB_RENDER_EMPTY="1")
    proc = run_sh(recipe_of(repo, gate), repo, e)
    assert_red(proc, render_line("cluster-gitops", gate))
    assert "OK: up to date" not in proc.stdout


@pytest.mark.parametrize("template", GITOPS_TEMPLATES)
def test_validate_names_itself_in_the_line_of_its_render_check_ac_130_9(world, template):  # AC-130.9
    repo, e = world(template, **({} if template == "gitops-app" else {"STUB_RENDER_EMPTY": "1"}))
    if template == "gitops-app":
        drop_system(repo)
    assert_red(run_sh(recipe_of(repo, "validate"), repo, e), render_line(template, "validate"))


def test_gitops_app_validate_stops_at_its_first_failing_step_ac_130_9(world):  # AC-130.9
    repo, e = world("gitops-app")
    drop_system(repo)
    proc = run_sh(recipe_of(repo, "validate"), repo, e)
    assert proc.returncode != 0
    assert "kubeconform" not in world.log() and "kustomize" not in world.log(), "later steps must not run after a red render check"


@pytest.mark.parametrize("template", GITOPS_TEMPLATES)
def test_render_check_of_a_fresh_render_still_says_up_to_date_ac_130_9(world, template):  # AC-130.9, AC-130.12
    repo, e = world(template)
    proc = run_sh(recipe_of(repo, "render-check"), repo, e)
    assert proc.returncode == 0 and "OK: up to date" in proc.stdout, proc.stdout + proc.stderr


# ---------------- AC-130.10: secrets-scan ----------------

@pytest.mark.parametrize("template", ALL_TEMPLATES)
def test_secrets_scan_with_nothing_to_scan_fails_and_never_runs_the_scanner_ac_130_10(world, template):  # AC-130.10
    repo, e = world(template, track=False)
    assert_red(run_sh(recipe_of(repo, "secrets-scan"), repo, e), secrets_line())
    assert "detect-secrets-hook" not in world.log()


@pytest.mark.parametrize("template", sorted(EXCLUDED_FILE))
def test_secrets_scan_where_the_exclusions_leave_no_file_fails_ac_130_10(world, template):  # AC-130.10
    repo, e = world(template, track=EXCLUDED_FILE[template])
    assert_red(run_sh(recipe_of(repo, "secrets-scan"), repo, e), secrets_line())
    assert "detect-secrets-hook" not in world.log()


def test_secrets_scan_fix_text_is_the_contract_ac_130_10(world):  # AC-130.10
    repo, e = world("library-python", track=False)
    proc = run_sh(recipe_of(repo, "secrets-scan"), repo, e)
    assert ("secrets-scan: checked nothing: 0 files to scan - commit at least one file that the scan does not exclude (`git add`)"
            in proc.stderr)


@pytest.mark.parametrize("template", ALL_TEMPLATES)
def test_secrets_scan_with_files_runs_the_scanner_and_passes_ac_130_10(world, template):  # AC-130.10, AC-130.12
    repo, e = world(template)
    proc = run_sh(recipe_of(repo, "secrets-scan"), repo, e)
    assert proc.returncode == 0 and "checked nothing" not in proc.stderr, proc.stderr
    assert "detect-secrets-hook --baseline" in world.log()


@pytest.mark.parametrize("template", ALL_TEMPLATES)
def test_the_secrets_scan_recipe_keeps_the_scanner_flags_literally_ac_130_10(template):  # AC-130.10
    text = _template_recipe(template, "secrets-scan")
    assert text.startswith("bash scripts/gate.sh files secrets-scan "), text
    assert f"| xargs -0 detect-secrets-hook {SECRET_FLAGS}" in text
    spec = SECRET_PATHSPEC.get(template)
    if spec:
        assert text == (f"bash scripts/gate.sh files secrets-scan {spec} && git ls-files -z {spec} | xargs -0 detect-secrets-hook {SECRET_FLAGS}")
    else:
        assert re.fullmatch(rf"bash scripts/gate\.sh files secrets-scan \. && git ls-files -z( \.)? \| xargs -0 detect-secrets-hook {re.escape(SECRET_FLAGS)}",
                            text), text


# ---------------- AC-130.11: the composites ----------------

def _composites():
    out = []
    for t in ALL_TEMPLATES:
        out += [(t, "ci"), (t, "security")]
        if t in GITOPS_TEMPLATES:
            out.append((t, "quality"))
    return out


@pytest.mark.parametrize("template,composite", _composites())
def test_composites_turn_red_when_their_gate_checked_nothing_ac_130_11(world, template, composite):  # AC-130.11
    gate = {"security": "secrets-scan", "ci": "test", "quality": "validate"}[composite]
    track, setup, env, expected = empty_case(template, gate)
    repo, e = world(template, track, **env)
    setup(repo)
    assert_red(run_sh(recipe_of(repo, composite), repo, e), expected)


@pytest.mark.parametrize("template", ALL_TEMPLATES)
def test_composites_chain_their_gates_with_and_and_nothing_swallows_a_failure_ac_130_11(template):  # AC-130.11
    sec = _template_recipe(template, "security")
    assert "devbox run secrets-scan" in sec
    ci = _template_recipe(template, "ci")
    assert "devbox run security" in ci
    assert ("devbox run test" in ci) or ("devbox run validate" in ci)
    for name in ("ci", "security") + (("quality",) if template in GITOPS_TEMPLATES else ()):
        text = _template_recipe(template, name)
        assert "|| true" not in text and ";" not in text.replace("; then", "").replace("; fi", ""), text


# ---------------- AC-130.12: the passing side ----------------

PASSING = {"service-python": {"STUB_PYTEST": "pass"}, "library-python": {"STUB_PYTEST": "pass"}, "service-go": {"STUB_GO": "pass"},
           "service-java": {"STUB_MVN": "pass"}, "web-nextjs": {"STUB_VITEST": "pass"},
           "gitops-app": {"STUB_KUSTOMIZE": "kind: Deployment",
                          "STUB_KUBECONFORM": "Summary: 1 resource found in 1 file - Valid: 1, Invalid: 0, Errors: 0, Skipped: 0"},
           "cluster-gitops": {"STUB_KUSTOMIZE": "kind: Namespace",
                              "STUB_KUBECONFORM": "Summary: 3 resources found in 1 file - Valid: 3, Invalid: 0, Errors: 0, Skipped: 0"}}


@pytest.mark.parametrize("template,gate", MATRIX)
def test_a_covered_gate_with_input_passes_as_before_ac_130_12(world, template, gate):  # AC-130.12
    repo, e = world(template, **PASSING[template])
    proc = run_sh(recipe_of(repo, gate), repo, e)
    assert proc.returncode == 0, f"{template} {gate} failed\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    assert "checked nothing" not in proc.stderr


@pytest.mark.parametrize("fmt", ["pretty", "compact"])
def test_the_vitest_report_is_read_whatever_its_json_layout_ac_130_12(world, fmt):  # AC-130.12
    repo, e = world("web-nextjs", STUB_VITEST="pass", STUB_VITEST_FORMAT=fmt)
    proc = run_sh(recipe_of(repo, "test"), repo, e)
    assert proc.returncode == 0 and "checked nothing" not in proc.stderr, proc.stderr


@pytest.mark.parametrize("template", PYTHON + ["service-go", "service-java", "web-nextjs"])
def test_a_failing_test_keeps_failing_without_the_empty_line_ac_130_12(world, template):  # AC-130.12
    stub = {"service-python": "STUB_PYTEST", "library-python": "STUB_PYTEST", "service-go": "STUB_GO", "service-java": "STUB_MVN",
            "web-nextjs": "STUB_VITEST"}[template]
    repo, e = world(template, **{stub: "fail", "STUB_FAIL_EXIT": "1"})
    proc = run_sh(recipe_of(repo, "test"), repo, e)
    assert proc.returncode == 1 and "checked nothing" not in proc.stderr, proc.stderr


@pytest.mark.parametrize("template", PYTHON + ["service-go", "service-java", "web-nextjs"])
def test_a_broken_runner_is_not_reported_as_add_a_test_ac_130_12(world, template):  # AC-130.12
    stub = {"service-python": "STUB_PYTEST", "library-python": "STUB_PYTEST", "service-go": "STUB_GO", "service-java": "STUB_MVN",
            "web-nextjs": "STUB_VITEST"}[template]
    repo, e = world(template, **{stub: "broken", "STUB_BROKEN_EXIT": "3"})
    proc = run_sh(recipe_of(repo, "test"), repo, e)
    assert proc.returncode == 3 and "checked nothing" not in proc.stderr, proc.stderr


def test_extra_arguments_reach_the_runner_unchanged_after_the_gate_wrapper_ac_130_12(world):  # AC-130.12
    repo, e = world("service-python", STUB_PYTEST="pass")
    proc = run_sh(recipe_of(repo, "test-fast") + " tests/test_one.py -k one", repo, e)
    assert proc.returncode == 0, proc.stderr
    assert re.search(r"pytest .*tests/test_one\.py -k one", world.log()), world.log()


def _test_files(template: str) -> list:
    root = TEMPLATES / template
    pats = {"service-python": ["tests/test_*.py"], "library-python": ["tests/test_*.py"], "service-go": ["**/*_test.go*"],
            "service-java": ["src/test/**/*Test.java*"], "web-nextjs": ["tests/*.test.ts*"]}[template]
    return [p for pat in pats for p in root.glob(pat)]


@pytest.mark.parametrize("template", TEST_TEMPLATES)
def test_each_test_running_template_ships_at_least_one_test_ac_130_12(template):  # AC-130.12
    marker = {"service-python": r"def test_", "library-python": r"def test_", "service-go": r"func Test\w*\(", "service-java": r"@Test",
              "web-nextjs": r"\b(it|test)\("}[template]
    assert any(re.search(marker, p.read_text()) for p in _test_files(template)), f"{template} ships no test"


# ---------------- AC-130.13: no opt-out ----------------

OPT_OUTS = {"SKIP": "1", "SKIP_GATE": "1", "SKIP_TESTS": "1", "ALLOW_EMPTY": "1", "GATE_ALLOW_EMPTY": "1", "ALLOW_NO_TESTS": "1",
            "PASS_WITH_NO_TESTS": "1", "PASSWITHNOTESTS": "true", "CI": "false", "FORCE": "1", "CHECKED_NOTHING_OK": "1",
            "SECRETS_SCAN_SKIP": "1", "SKIP_SECRETS_SCAN": "1", "SKIP_VALIDATE": "1", "NO_FAIL_ON_EMPTY": "1"}
OPT_OUT_CASES = [("service-python", "test"), ("library-python", "test-fast"), ("service-go", "test"), ("service-java", "test-fast"),
                 ("web-nextjs", "test"), ("gitops-app", "validate"), ("cluster-gitops", "validate"), ("gitops-app", "secrets-scan"),
                 ("service-python", "secrets-scan")]


@pytest.mark.parametrize("template,gate", OPT_OUT_CASES)
def test_no_environment_variable_makes_an_empty_gate_pass_ac_130_13(world, template, gate):  # AC-130.13
    track, setup, env, expected = empty_case(template, gate)
    repo, e = world(template, track, **env, **OPT_OUTS)
    setup(repo)
    assert_red(run_sh(recipe_of(repo, gate), repo, e), expected)


@pytest.mark.parametrize("template,gate,arg", [("service-python", "test", "--passWithNoTests"), ("service-python", "test-fast", "--allow-empty"),
                                               ("service-go", "test", "-run NONE"), ("service-java", "test-fast", "-DskipTests"),
                                               ("web-nextjs", "test", "--passWithNoTests"), ("web-nextjs", "test-fast", "--pass-with-no-tests")])
def test_no_recipe_argument_makes_an_empty_gate_pass_ac_130_13(world, template, gate, arg):  # AC-130.13
    repo, e = world(template, **empty_env(template))
    assert_red(run_sh(recipe_of(repo, gate) + " " + arg, repo, e), no_tests_line(gate))


@pytest.mark.parametrize("template", PYTHON + ["service-go", "service-java", "web-nextjs"])
def test_no_recipe_contains_a_switch_that_skips_the_check_ac_130_13(template):  # AC-130.13
    for gate in GATES:
        text = _template_recipe(template, gate)
        assert not re.search(r"\$\{?(SKIP|ALLOW|FORCE)\w*|\|\|\s*(true|:|exit 0)", text), text


# ---------------- recipe texts of the contract ----------------

def _template_recipe(template: str, name: str) -> str:
    """The recipe from the template's devbox.json[.jinja] (read as text, so Jinja syntax cannot break it); `{{ module_name }}` is
    resolved the way the tests render the template."""
    for fname in ("devbox.json", "devbox.json.jinja"):
        f = TEMPLATES / template / fname
        if f.exists():
            m = re.search(rf'^\s*"{re.escape(name)}":\s*"((?:[^"\\]|\\.)*)"', f.read_text(), re.M)
            assert m, f"{template}: no recipe {name}"
            return json.loads('"' + m.group(1) + '"').replace("{{ module_name }}", "demo_app").replace("{{ project_name }}", "demo-app")
    raise AssertionError(f"no devbox.json in templates/{template}")


EXPECTED_TEST_RECIPES = {
    "service-python": ("SMOKE_BASE_URL= bash scripts/gate.sh tests test pytest -- uv run python -m pytest tests/ -p scripts.smoke_pytest --cov=demo_app --cov-report=term-missing",
                       "SMOKE_BASE_URL= bash scripts/gate.sh tests test-fast pytest -- uv run python -m pytest tests/ -p scripts.smoke_pytest -q --tb=line"),
    "library-python": ("bash scripts/gate.sh tests test pytest -- uv run pytest tests/ --cov=demo_app --cov-report=term-missing",
                       "bash scripts/gate.sh tests test-fast pytest -- uv run pytest tests/ -q --tb=line"),
    "service-go": ("SMOKE_BASE_URL= bash scripts/gate.sh tests test go -- go test -v -race -cover ./...",
                   "SMOKE_BASE_URL= bash scripts/gate.sh tests test-fast go -- go test -v ./..."),
    "service-java": ("SMOKE_BASE_URL= bash scripts/gate.sh tests test maven -- mvn -B verify",
                     "SMOKE_BASE_URL= bash scripts/gate.sh tests test-fast maven -- mvn -B test"),
    "web-nextjs": ("SMOKE_BASE_URL= bash scripts/gate.sh tests test vitest -- pnpm test",
                   "SMOKE_BASE_URL= bash scripts/gate.sh tests test-fast vitest -- pnpm test:fast"),
}


@pytest.mark.parametrize("template", TEST_TEMPLATES)
def test_test_and_test_fast_run_through_the_gate_helper_as_the_contract_says_ac_130_2(template):  # AC-130.2, AC-130.3, AC-130.4, AC-130.5
    test, fast = EXPECTED_TEST_RECIPES[template]
    assert _template_recipe(template, "test") == test
    assert _template_recipe(template, "test-fast") == fast


def test_gitops_app_recipes_follow_the_contract_ac_130_7():  # AC-130.7, AC-130.9
    validate = _template_recipe("gitops-app", "validate")
    for step in ("GATE_NAME=validate uv run scripts/render.py --check || exit 1", "uv run scripts/plan.py validate || exit 1",
                 "uv run scripts/check-k8s-labels.py . || exit 1", 'kustomize build "$d"', "bash scripts/check-policies.sh",
                 "bash scripts/gate.sh nothing validate '0 resources' '" + "run `devbox run render` and check that the system has components" + "'"):
        assert step in validate, step
    assert re.search(r"kubeconform -strict .*-summary \"\$f\"", validate)
    assert validate.index("scripts/render.py --check") < validate.index("kustomize build") < validate.index("gate.sh nothing validate")
    assert validate.index("gate.sh nothing validate") < validate.index("check-policies.sh")
    assert _template_recipe("gitops-app", "test") == "devbox run validate"
    assert _template_recipe("gitops-app", "test-fast") == "GATE_NAME=test-fast uv run scripts/render.py --check && uv run scripts/plan.py validate"
    assert _template_recipe("gitops-app", "render-check") == "uv run scripts/render.py --check"


def test_cluster_gitops_recipes_follow_the_contract_ac_130_8():  # AC-130.8, AC-130.9
    validate = _template_recipe("cluster-gitops", "validate")
    assert validate.startswith("GATE_NAME=validate uv run scripts/render.py --check")
    assert 'kustomize build cluster > "$dir/cluster.yaml"' in validate
    assert "bash scripts/gate.sh nothing validate '0 resources'" in validate
    assert "validate: kubeconform checked 0 resources" not in validate
    assert _template_recipe("cluster-gitops", "test") == "devbox run validate"
    assert _template_recipe("cluster-gitops", "test-fast") == "GATE_NAME=test-fast uv run scripts/render.py --check"
    assert _template_recipe("cluster-gitops", "render-check") == "uv run scripts/render.py --check"


@pytest.mark.parametrize("script", ["templates/gitops-app/scripts/render.py", "templates/cluster-gitops/scripts/render.py",
                                    "templates/cluster-gitops/scripts/system_render.py"])
def test_the_renderers_count_compared_files_and_read_the_gate_name_ac_130_9(script):  # AC-130.9
    text = (ROOT / script).read_text()
    assert "GATE_NAME" in text and "checked nothing" in text and "0 files compared" in text


# ---------------- AC-130.16: the update path ----------------

@pytest.mark.parametrize("template", ALL_TEMPLATES)
def test_the_files_that_change_are_platform_owned_so_an_update_applies_them_ac_130_16(template):  # AC-130.16
    conf = yaml.safe_load((TEMPLATES / template / "copier.yml").read_text())
    skip = conf.get("_skip_if_exists", [])
    changed = ["devbox.json", "scripts/gate.sh", "scripts/render.py", "vitest.config.mts"]
    for path in changed:
        assert not any(fnmatch.fnmatch(path, pat.replace("**", "*")) for pat in skip), f"{template}: {path} would not be updated"
    assert (TEMPLATES / template / "scripts" / "gate.sh").is_file(), f"{template} does not ship scripts/gate.sh"


def _unreleased() -> str:
    """The changelog section that holds the entry: [Unreleased] until the release, then its release section."""
    text = (ROOT / "docs" / "CHANGELOG.md").read_text()
    sections = re.findall(r"^## \[[^\]]+\][^\n]*\n(.*?)(?=^## \[|\Z)", text, re.S | re.M)
    assert sections, "docs/CHANGELOG.md has no sections"
    return next((s for s in sections if "checked nothing" in s), sections[0])


def test_the_changelog_lists_the_behaviour_change_with_symptom_and_fix_ac_130_16():  # AC-130.16
    body = _unreleased()
    paras = [p for p in body.split("\n\n") if "checked nothing" in p]
    assert paras, "no [Unreleased] entry names `checked nothing`"
    entry = paras[0]
    assert "add at least one test" in entry
    assert re.search(r"non-empty|not empty", entry), "name the fix for an empty build or file list"
    assert "#285" in entry
    assert re.search(r"behaviou?r change|breaking|turns? red", entry, re.I)


def test_the_release_is_a_minor_no_plugin_or_marketplace_major_bump_ac_130_16():  # AC-130.16
    tags = subprocess.run(["git", "tag", "--list", "v*", "--sort=-v:refname"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    if not tags:
        pytest.skip("no release tag to compare with")
    old = json.loads(subprocess.run(["git", "show", f"{tags[0]}:.claude-plugin/marketplace.json"], cwd=ROOT, capture_output=True,
                                    text=True, check=True).stdout)
    new = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    before = {p["name"]: int(p["version"].split(".")[0]) for p in old["plugins"]}
    for p in new["plugins"]:
        if p["name"] in before:
            assert int(p["version"].split(".")[0]) <= before[p["name"]], f"plugin {p['name']} got a major bump since {tags[0]}"


# ---------------- AC-130.15: the rule in the guides ----------------

@pytest.mark.parametrize("doc", ["CONTRIBUTING.md", "docs/templates.md"])
def test_the_guides_state_the_rule_and_point_to_the_platform_test_ac_130_15(doc):  # AC-130.15
    text = (ROOT / doc).read_text()
    assert "a gate that checked nothing fails" in text.lower(), f"{doc} lacks the rule"
    assert "tests/cplat/test_130_empty_gates.py" in text, f"{doc} does not point to the platform test"
