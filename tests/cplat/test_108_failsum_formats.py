"""Spec 108 acceptance tests: AC-108.2 (test entries), AC-108.3 (findings, dedup), AC-108.4 (recognized formats, unknown fallback).

Contract: design.md, `failsum.summarize(...).render()` (byte-exact entry lines `- <locator> | <kind> | <message>`), one sample log
per tool under fixtures/failsum/. `failsum` is imported inside the helpers, so every test fails until the package exists.
"""
import pytest

from failsum_support import excerpt_runs, formats_of, has, headers, marker, render, sample

APP = "/work/todo-api"
GO = "/work/shop-api"
WEB = "/work/web"

# (fixture, script, parser name, repo root, entry-line patterns that must match, strings that must not appear)
TESTS = [
    ("pytest-long.log", "test", "pytest", None, [
        r"^- tests/test_todos_api\.py::test_create_todo at src/todo_api/todos/service\.py:42 \| ValueError \| title must not be empty",
        r"^- tests/test_todos_api\.py::test_delete_todo at tests/test_todos_api\.py:31 \| AssertionError \| assert <n> == <n>",
        r"^- tests/test_todos_model\.py::test_fixture_user at tests/helpers\.py:5 \| RuntimeError \| db closed",
    ], ["site-packages", "httpx", "[ 66%]", "test session starts", "platform linux", "coverage: platform"]),
    ("pytest-tbline.log", "test-fast", "pytest", APP, [
        r"^- tests/test_todos_api\.py::test_delete_todo at src/todo_api/todos/router\.py:58 \| AssertionError \| expected <n>, got <n>",
    ], ["[100%]", "4 passed"]),
    ("surefire.log", "test", "surefire", None, [
        r"^- (com\.acme\.shop\.)?PriceServiceTest\.discountApplies at \S*PriceServiceTest\.java:27 \| (\S*\.)?AssertionFailedError \| .*expected",
        r"^- (com\.acme\.shop\.)?PriceServiceTest\.nullCart at \S*PriceService\.java:19 \| (\S*\.)?NullPointerException \| ",
    ], ["AssertionFailureBuilder", "Method.invoke", "T E S T S"]),
    ("go-test.log", "test", "go-test", GO, [
        r"^- \S*alerts\.TestPriceAlert at \S*alerts_test\.go:41 \| \S+ \| want <n> got <n>",
        r"^- \S*fee\.TestFee at internal/fee/fee\.go:22 \| panic \| ",
    ], ["testing.go:1631", "ok  \t"]),
    ("vitest.log", "test", "vitest", WEB, [
        r"^- src/lib/price\.test\.ts > formats cents > rounds half up at src/lib/price\.test\.ts:9 \| AssertionError \| ",
    ], ["node_modules", "pads zero", "slug.test", "RUN  v2"]),
]

FINDINGS = [
    ("ruff-full.log", "lint", "ruff", None, [
        r"^- src/todo_api/main\.py:3 \| F401 \| ",
        r"^- src/todo_api/todos/router\.py:20 \| E501 \| ",
    ]),
    ("ruff-format.log", "lint", "ruff-format", None, [
        r"^- src/todo_api/main\.py(:\d+)? \| format \| ",
        r"^- tests/test_todos_api\.py(:\d+)? \| format \| ",
    ]),
    ("mypy.log", "typecheck", "mypy", None, [
        r"^- src/todo_api/todos/service\.py:17 \| return-value \| ",
        r"^- src/todo_api/main\.py:9 \| name-defined \| ",
    ]),
    ("javac.log", "typecheck", "javac", "/work/shop-api", [
        r"^- src/main/java/com/acme/shop/PriceService\.java:19 \| \S+ \| cannot find symbol",
    ]),
    ("checkstyle.log", "lint", "checkstyle", None, [
        r"^- src/main/java/com/acme/shop/PriceService\.java:3 \| UnusedImports \| ",
        r"^- src/main/java/com/acme/shop/Item\.java:12 \| WhitespaceAround \| ",
    ]),
    ("spotless.log", "lint", "spotless", None, [
        r"^- src/main/java/com/acme/shop/PriceService\.java(:\d+)? \| spotless \| ",
        r"^- src/main/java/com/acme/shop/Item\.java(:\d+)? \| spotless \| ",
    ]),
    ("go-build.log", "typecheck", "go-build", GO, [
        r"^- internal/alerts/alerts\.go:14 \| compile \| undefined: Missing",
        r"^- internal/alerts/alerts\.go:20 \| compile \| ",
    ]),
    ("golangci.log", "lint", "golangci-lint", GO, [
        r"^- internal/alerts/alerts\.go:31 \| errcheck \| ",
        r"^- internal/fee/fee\.go:7 \| govet \| ",
    ]),
    ("eslint.log", "lint", "eslint", WEB, [
        r"^- src/app/page\.tsx:3 \| @typescript-eslint/no-unused-vars \| ",
        r"^- src/app/page\.tsx:8 \| no-console \| ",
    ]),
    ("tsc.log", "typecheck", "tsc", None, [
        r"^- src/lib/price\.ts:12 \| TS2322 \| ",
        r"^- src/app/page\.tsx:5 \| TS2304 \| ",
    ]),
    ("next-build.log", "build", "next-build", None, [r"^- src/app/page\.tsx:7 \| "]),
    ("gitops-scripts.log", "render-check", "gitops-scripts", None, [
        r"^- apps/shop/dev/values\.yaml(:\d+)? \| ",
        r"^- apps/shop/prod/values\.yaml:12 \| ",
    ]),
    ("kustomize.log", "validate", "kustomize", None, [r"^- apps/shop/overlays/dev \| "]),
    ("kubeconform.log", "validate", "kubeconform", None, [r"^- apps/shop/rendered/dev\.yaml\S* \| "]),
    ("kyverno.log", "policy-check", "kyverno", None, [r"^- .*CPU and memory limits are required"]),
    ("docker-build.log", "image-build", "docker-build", None, [r"^- Dockerfile:12 \| "]),
    ("pytest-cov.log", "test", "pytest-cov", None, [r"^- \S.* \| coverage \| "]),
    ("jacoco.log", "test", "jacoco", None, [r"^- \S.* \| coverage \| "]),
    ("vitest-cov.log", "test", "vitest", WEB, [r"^- \S.* \| coverage \| "]),
]

UNKNOWN = ["bandit-unknown.log"]


@pytest.mark.parametrize("fixture,script,parser,root,patterns,absent", TESTS, ids=[r[0] for r in TESTS])
def test_a_failing_test_run_has_one_entry_per_test_and_no_noise_ac_108_2(fixture, script, parser, root, patterns, absent):  # AC-108.2
    out = render(marker(script) + sample(fixture), script, root=root)
    (header,) = headers(out)
    assert parser in formats_of(header) and "unknown" not in formats_of(header)
    for p in patterns:
        assert has(out, p), f"no entry matching {p!r} in:\n{out}"
    entries = [ln for ln in out.splitlines() if ln.startswith("- ")]
    assert len(entries) == len(patterns), out
    for s in absent:
        assert s not in out
    assert all(n <= 10 for n in excerpt_runs(out))
    assert f"entries: {len(patterns)}" in header


def test_an_excerpt_has_at_most_ten_lines_ac_108_2():  # AC-108.2
    e_lines = "".join(f"E       detail line {i}\n" for i in range(30))
    log = ("______ test_big ______\n\n    def test_big():\n>       assert False\n" + e_lines +
           "\ntests/test_big.py:4: AssertionError\n=== short test summary info ===\n"
           "FAILED tests/test_big.py::test_big - AssertionError\n== 1 failed in 0.1s ==\n")
    out = render(log)
    assert has(out, r"^- tests/test_big\.py::test_big at tests/test_big\.py:4 \| AssertionError \| ")
    runs = excerpt_runs(out)
    assert runs and max(runs) <= 10


def test_every_failing_and_erroring_test_gets_its_own_entry_even_with_equal_messages_ac_108_2():  # AC-108.2
    log = ("/work/todo-api/tests/test_a.py:5: AssertionError: same\n/work/todo-api/tests/test_b.py:5: AssertionError: same\n"
           "FAILED tests/test_a.py::test_a - AssertionError: same\nFAILED tests/test_b.py::test_b - AssertionError: same\n"
           "2 failed in 0.1s\n")
    out = render(log, "test-fast", root=APP)
    assert has(out, r"^- tests/test_a\.py::test_a at tests/test_a\.py:5 \| AssertionError")
    assert has(out, r"^- tests/test_b\.py::test_b at tests/test_b\.py:5 \| AssertionError")
    assert "x2" not in out, "tests are never deduplicated"


@pytest.mark.parametrize("fixture,script,parser,root,patterns", FINDINGS, ids=[r[0] for r in FINDINGS])
def test_a_failing_lint_type_or_build_run_has_one_entry_per_finding_ac_108_3(fixture, script, parser, root, patterns):  # AC-108.3
    out = render(marker(script) + sample(fixture), script, root=root)
    (header,) = headers(out)
    assert parser in formats_of(header)
    for p in patterns:
        assert has(out, p), f"no entry matching {p!r} in:\n{out}"
    assert len([ln for ln in out.splitlines() if ln.startswith("- ")]) == len(patterns), out


def test_identical_findings_are_listed_once_with_a_count_ac_108_3():  # AC-108.3
    out = render(marker("lint") + sample("ruff-concise.log"), "lint")
    f401 = [ln for ln in out.splitlines() if ln.startswith("- ") and "F401" in ln]
    assert len(f401) == 1
    assert f401[0].startswith("- src/todo_api/main.py:3 | F401 | ") and f401[0].endswith(" | x3 (lines 9, 14)")
    e501 = [ln for ln in out.splitlines() if "E501" in ln and ln.startswith("- ")]
    assert len(e501) == 1 and " | x" not in e501[0]
    assert "entries: 2" in headers(out)[0]


def test_a_finding_excerpt_is_the_code_frame_the_tool_printed_ac_108_3():  # AC-108.3
    out = render(sample("ruff-full.log"), "lint")
    assert has(out, r"^- src/todo_api/main\.py:3 \| F401 \| .*\n    > .*import os")


@pytest.mark.parametrize("fixture,script,parser,root,patterns,absent", TESTS, ids=[r[0] for r in TESTS])
def test_the_test_tools_of_the_templates_are_recognized_ac_108_4(fixture, script, parser, root, patterns, absent):  # AC-108.4
    assert "format: unknown" not in render(sample(fixture), script, root=root)


@pytest.mark.parametrize("fixture,script,parser,root,patterns", FINDINGS, ids=[r[0] for r in FINDINGS])
def test_the_lint_type_and_build_tools_of_the_templates_are_recognized_ac_108_4(fixture, script, parser, root, patterns):  # AC-108.4
    assert "format: unknown" not in render(sample(fixture), script, root=root)


def test_the_templates_formats_are_all_registered_ac_108_4():  # AC-108.4
    import failsum
    names = {p.name for mod in ("python", "java", "go", "web", "gitops", "docker")
             for p in __import__(f"failsum.{mod}", fromlist=["PARSERS"]).PARSERS}
    wanted = {"pytest", "pytest-cov", "ruff", "ruff-format", "mypy", "surefire", "javac", "checkstyle", "spotless", "jacoco",
              "go-test", "go-build", "golangci-lint", "vitest", "eslint", "tsc", "next-build", "gitops-scripts", "kustomize",
              "kubeconform", "kyverno", "docker-build"}
    assert wanted <= names and failsum.FORMAT_UNKNOWN == "unknown"


@pytest.mark.parametrize("fixture", UNKNOWN)
def test_another_format_says_unknown_and_shows_the_last_40_lines_ac_108_4(fixture):  # AC-108.4
    lines = [f"noise row {i}" for i in range(100)]
    out = render("\n".join(lines) + "\n", "security")
    (header,) = headers(out)
    assert "format: unknown" in header and "entries:" not in header
    shown = out.splitlines()[2:]
    assert shown == lines[-40:]
    bandit = render(sample(fixture), "security")
    assert "format: unknown" in bandit and "B105:hardcoded_password_string" in bandit  # spec 108 build: the tail is redacted (AC-108.7)


def test_output_the_summary_cannot_read_is_never_an_empty_summary_ac_108_4():  # AC-108.4
    for text in ("", "\x00\x01\x02 garbled ��\n", "FAILED tests/x.py::t - \n== 1 failed in\n", "\n\n   \n"):
        out = render(text)
        assert out.strip() and headers(out), repr(text)
        assert "format: unknown" in headers(out)[0]
    assert "(no output)" in render("")


def test_the_cluster_gitops_template_is_outside_the_six_and_falls_back_ac_108_4():  # AC-108.4
    out = render("ERROR cluster bootstrap failed: node not ready\nretrying\n", "cluster-check")
    assert "format: unknown" in out and "node not ready" in out
