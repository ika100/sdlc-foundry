"""Spec 184 acceptance tests: the templates a branch changes are linted locally and in the CI smoke jobs (AC-184.5).

`scripts/template-lint.py` is run as a program, in its two forms (design.md, Contract, "Template lint"):
`template-lint.py <template> <rendered dir>` lints one rendered project; `template-lint.py --changed [--base REF]` renders and lints
each template a branch changed. The lint tools (`uv`, `mvn`, `golangci-lint`, `npx`) and `copier` are fakes on PATH that log their
arguments and print what the real tool prints for a violation, so the parsers are tested through the lines the script prints.
Nothing here renders a template, starts a build or reaches the network.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import core
from waiting import with_prelude

ROOT = core.PLATFORM_ROOT
SCRIPT = ROOT / "scripts" / "template-lint.py"


def fake_tool(bin_dir: Path, name: str, body: str) -> None:
    """An executable `name` that logs its arguments (and cwd) to `calls.log` next to the bin folder and then runs `body` (Python)."""
    exe = bin_dir / name
    text = (f"#!{sys.executable}\nimport json, os, sys\n"
            f"open({str(bin_dir.parent / 'calls.log')!r}, 'a').write(json.dumps({{'tool': {name!r}, 'args': sys.argv[1:], 'cwd': os.getcwd()}}) + '\\n')\n"
            f"{body}\n")
    exe.write_text(with_prelude(text))
    exe.chmod(0o755)


@pytest.fixture()
def bin_dir(tmp_path):
    d = tmp_path / "bin"
    d.mkdir()
    return d


@pytest.fixture()
def rendered(tmp_path):
    d = tmp_path / "rendered"
    d.mkdir()
    return d


def calls(bin_dir):
    f = bin_dir.parent / "calls.log"
    return [json.loads(ln) for ln in f.read_text().splitlines()] if f.is_file() else []


def lint(template, rendered, bin_dir, *, keep_path=False):
    path = f"{bin_dir}{os.pathsep}{os.environ['PATH']}" if keep_path else str(bin_dir)
    return subprocess.run([sys.executable, str(SCRIPT), template, str(rendered)], capture_output=True, text=True,
                          env={"PATH": path, "HOME": str(bin_dir.parent), "LANG": "C.UTF-8"}, timeout=60)


def lines(res):
    return (res.stdout + res.stderr).splitlines()


UV_FAIL_CHECK = ("if 'check' in sys.argv and 'format' not in sys.argv:\n"
                 "    print('src/pkg/a.py:3:8: F401 [*] `os` imported but unused')\n"
                 "    print('src/pkg/a.py:9:1: E501 Line too long (130 > 120)')\n"
                 "    sys.exit(1)\n")
UV_FAIL_FORMAT = ("if 'format' in sys.argv:\n"
                  "    print('Would reformat: src/pkg/b.py')\n"
                  "    print('1 file would be reformatted')\n"
                  "    sys.exit(1)\n")


# ---------------- the parsers, through the lines the script prints ----------------

@pytest.mark.parametrize("template", ["service-python", "library-python"])
def test_a_ruff_violation_is_named_by_file_line_and_rule_ac_184_5(template, bin_dir, rendered):  # AC-184.5
    fake_tool(bin_dir, "uv", UV_FAIL_CHECK)
    res = lint(template, rendered, bin_dir)
    out = lines(res)
    assert res.returncode == 1
    assert f"{template}: src/pkg/a.py:3: F401: `os` imported but unused" in [re.sub(r"\[\*\] ", "", ln) for ln in out]
    assert any(ln.startswith(f"{template}: src/pkg/a.py:9: E501: ") for ln in out)
    assert out[-1] == f"template lint: {template} failed: 2 violation(s)"
    assert "src/pkg/a.py:3:8: F401" in res.stdout                                  # the tool's own output is printed as it comes
    assert {"tool": "uv", "args": ["run", "ruff", "check", "--output-format=concise", "."], "cwd": str(rendered.resolve())} in calls(bin_dir)


@pytest.mark.parametrize("template", ["service-python", "library-python"])
def test_a_ruff_format_finding_is_a_whole_file_violation_ac_184_5(template, bin_dir, rendered):  # AC-184.5
    fake_tool(bin_dir, "uv", UV_FAIL_FORMAT)
    res = lint(template, rendered, bin_dir)
    out = lines(res)
    assert res.returncode == 1
    assert any(ln.startswith(f"{template}: src/pkg/b.py:-: ruff-format: ") for ln in out)
    assert out[-1] == f"template lint: {template} failed: 1 violation(s)"
    assert ["run", "ruff", "format", "--check", "."] in [c["args"] for c in calls(bin_dir)]


@pytest.mark.parametrize("template", ["service-python", "library-python"])
def test_a_clean_render_passes_ac_184_5(template, bin_dir, rendered):  # AC-184.5
    fake_tool(bin_dir, "uv", "print('All checks passed!')")
    res = lint(template, rendered, bin_dir)
    assert res.returncode == 0 and lines(res)[-1] == f"template lint: {template} passed"
    assert len(calls(bin_dir)) == 2


def test_a_checkstyle_violation_names_file_line_and_rule_ac_184_5(bin_dir, rendered):  # AC-184.5
    fake_tool(bin_dir, "mvn", ("print('[INFO] --- checkstyle:3.6.0:check (default-cli) @ svc ---')\n"
                               "print(\"[WARN] /tmp/x/src/main/java/com/acme/Foo.java:[12,5] (naming) ConstantName: Name 'x' must match pattern '^[A-Z][A-Z0-9]*$'.\")\n"
                               "print('[WARNING] The POM for com.acme:old:jar:1.0 is invalid, transitive dependencies are not added')\n"
                               "print('[ERROR] /tmp/x/src/main/java/com/acme/Bar.java:[3,8] (imports) UnusedImports: Unused import - java.util.List.')\n"
                               "print('[ERROR] Failed to execute goal checkstyle:check: You have 2 Checkstyle violations.')\n"
                               "sys.exit(1)"))
    res = lint("service-java", rendered, bin_dir)
    out = lines(res)
    assert res.returncode == 1
    assert any(re.fullmatch(r"service-java: \S*Foo\.java:12: ConstantName: Name 'x' must match pattern .*", ln) for ln in out), out
    assert any(re.fullmatch(r"service-java: \S*Bar\.java:3: UnusedImports: Unused import - java\.util\.List\.", ln) for ln in out), out
    assert out[-1] == "template lint: service-java failed: 2 violation(s)"                    # the POM warning is no violation
    assert [c["args"] for c in calls(bin_dir)] == [["-B", "--no-transfer-progress", "spotless:check", "checkstyle:check"]]


def test_a_failing_command_without_a_parsed_line_still_fails_ac_184_5(bin_dir, rendered):  # AC-184.5
    fake_tool(bin_dir, "mvn", "print('[ERROR] BUILD FAILURE')\nsys.exit(3)")
    res = lint("service-java", rendered, bin_dir)
    out = lines(res)
    assert res.returncode == 1
    assert re.fullmatch(r"template lint: service-java failed: .*mvn.* exited 3", out[-1]), out[-1]
    assert not any(ln.startswith("service-java: ") for ln in out)


def test_a_golangci_lint_finding_names_file_line_and_linter_ac_184_5(bin_dir, rendered):  # AC-184.5
    fake_tool(bin_dir, "golangci-lint", ("print('main.go:10:2: exported var Version should have comment or be unexported (revive)')\n"
                                         "print('internal/x.go:4:1: Error return value of `f.Close` is not checked (errcheck)')\n"
                                         "sys.exit(1)"))
    res = lint("service-go", rendered, bin_dir)
    out = lines(res)
    assert res.returncode == 1
    assert "service-go: main.go:10: revive: exported var Version should have comment or be unexported" in out
    assert "service-go: internal/x.go:4: errcheck: Error return value of `f.Close` is not checked" in out
    assert out[-1] == "template lint: service-go failed: 2 violation(s)"
    assert [c["args"] for c in calls(bin_dir)] == [["run", "./..."]]


ESLINT = ("print('/tmp/x/app/page.tsx')\n"
          "print(\"  12:5  error  'x' is defined but never used  @typescript-eslint/no-unused-vars\")\n"
          "print('  14:1  warning  Unexpected console statement  no-console')\n"
          "print()\n"
          "print('2 problems (1 error, 1 warning)')\n")


def test_an_eslint_finding_names_file_line_and_rule_and_pnpm_is_installed_first_ac_184_5(bin_dir, rendered):  # AC-184.5
    fake_tool(bin_dir, "npx", f"if 'lint' in sys.argv:\n    " + ESLINT.replace("\n", "\n    ") + "sys.exit(1)")
    res = lint("web-nextjs", rendered, bin_dir)
    out = lines(res)
    assert res.returncode == 1
    assert "web-nextjs: /tmp/x/app/page.tsx:12: @typescript-eslint/no-unused-vars: 'x' is defined but never used" in out
    assert "web-nextjs: /tmp/x/app/page.tsx:14: no-console: Unexpected console statement" in out
    assert out[-1] == "template lint: web-nextjs failed: 2 violation(s)"
    assert [c["args"] for c in calls(bin_dir)] == [["-y", "pnpm@11.22.0", "install"], ["-y", "pnpm@11.22.0", "lint"]]


def test_pnpm_is_not_installed_again_when_node_modules_exists_ac_184_5(bin_dir, rendered):  # AC-184.5
    (rendered / "node_modules").mkdir()
    fake_tool(bin_dir, "npx", "print('ok')")
    res = lint("web-nextjs", rendered, bin_dir)
    assert res.returncode == 0 and lines(res)[-1] == "template lint: web-nextjs passed"
    assert [c["args"] for c in calls(bin_dir)] == [["-y", "pnpm@11.22.0", "lint"]]


@pytest.mark.parametrize("template", ["gitops-app", "cluster-gitops"])
def test_the_gitops_templates_are_rendered_without_a_lint_ac_184_5(template, bin_dir, rendered):  # AC-184.5
    res = lint(template, rendered, bin_dir)
    assert res.returncode == 0
    assert f"template lint: {template}: rendered (its smoke job runs no lint)" in lines(res)


@pytest.mark.parametrize("template, tool", [("service-python", "uv"), ("library-python", "uv"), ("service-java", "mvn"),
                                            ("service-go", "golangci-lint"), ("web-nextjs", "npx")])
def test_a_missing_tool_fails_naming_it_ac_184_5(template, tool, bin_dir, rendered):  # AC-184.5
    res = lint(template, rendered, bin_dir)
    assert res.returncode == 1
    assert f"template lint: {template} needs {tool}, which is not on PATH" in lines(res)


# ---------------- --changed ----------------

def sh(repo, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=repo, check=True, capture_output=True,
                          text=True).stdout.strip()


@pytest.fixture()
def project(tmp_path):
    """A small repository with three templates, on a branch off `main` (the script is copied in by `changed`)."""
    repo = tmp_path / "project"
    (repo / "scripts").mkdir(parents=True)
    for t in ("service-python", "gitops-app", "web-nextjs"):
        (repo / "templates" / t).mkdir(parents=True)
        (repo / "templates" / t / "copier.yml").write_text("a: 1\n")
    (repo / "README.md").write_text("project\n")
    sh(repo, "init", "-q", "-b", "main")
    sh(repo, "add", "-A")
    sh(repo, "commit", "-qm", "base")
    sh(repo, "checkout", "-q", "-b", "feature")
    return repo


COPIER = ("dest = sys.argv[3]\nos.makedirs(dest, exist_ok=True)\n")


def changed(project, bin_dir, *args):
    shutil.copy(SCRIPT, project / "scripts" / "template-lint.py")        # untracked, outside `templates/`: no change of a template
    return subprocess.run([sys.executable, str(project / "scripts" / "template-lint.py"), "--changed", *args], cwd=project,
                          capture_output=True, text=True, env={"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "HOME": str(bin_dir.parent),
                                                                 "LANG": "C.UTF-8"}, timeout=60)


def test_a_branch_that_changes_no_template_renders_none_ac_184_5(project, bin_dir):  # AC-184.5
    fake_tool(bin_dir, "copier", COPIER)
    (project / "README.md").write_text("changed\n")
    sh(project, "commit", "-qam", "docs only")
    res = changed(project, bin_dir, "--base", "main")
    assert res.returncode == 0
    assert "template lint: no template changed" in lines(res)
    assert calls(bin_dir) == []


def test_a_changed_template_is_rendered_with_its_defaults_and_linted_ac_184_5(project, bin_dir):  # AC-184.5
    fake_tool(bin_dir, "copier", COPIER)
    fake_tool(bin_dir, "uv", "print('All checks passed!')")
    (project / "templates" / "service-python" / "copier.yml").write_text("a: 2\n")
    sh(project, "commit", "-qam", "change the python template")
    res = changed(project, bin_dir, "--base", "main")
    assert res.returncode == 0, res.stdout + res.stderr
    (render,) = [c for c in calls(bin_dir) if c["tool"] == "copier"]
    args = render["args"]
    assert args[:2] == ["copy", "./templates/service-python"] and {"--defaults", "--trust", "--skip-tasks"} <= set(args)
    data = [args[i + 1] for i, a in enumerate(args) if a == "--data"]
    assert any(d.startswith("project_name=lint-") for d in data) and any(d.startswith("module_name=lint_") for d in data)
    assert [c["args"] for c in calls(bin_dir) if c["tool"] == "uv"] == [["run", "ruff", "check", "--output-format=concise", "."],
                                                                         ["run", "ruff", "format", "--check", "."]]
    assert "template lint: service-python passed" in lines(res)
    assert not [c for c in calls(bin_dir) if c["args"][1:2] == ["./templates/web-nextjs"]]    # the others are not rendered


def test_a_lint_violation_in_a_changed_template_fails_with_file_line_and_rule_ac_184_5(project, bin_dir):  # AC-184.5
    fake_tool(bin_dir, "copier", COPIER)
    fake_tool(bin_dir, "uv", UV_FAIL_CHECK)
    (project / "templates" / "service-python" / "copier.yml").write_text("a: 2\n")
    sh(project, "commit", "-qam", "change the python template")
    res = changed(project, bin_dir, "--base", "main")
    out = lines(res)
    assert res.returncode == 1
    assert any(ln.startswith("service-python: src/pkg/a.py:3: F401: ") for ln in out)
    assert "template lint: service-python failed: 2 violation(s)" in out


def test_uncommitted_and_untracked_template_files_count_as_changed_ac_184_5(project, bin_dir):  # AC-184.5
    fake_tool(bin_dir, "copier", COPIER)
    (project / "templates" / "gitops-app" / "copier.yml").write_text("a: 2\n")                    # tracked, not committed
    (project / "templates" / "web-nextjs" / "new.txt").write_text("new\n")                         # untracked
    fake_tool(bin_dir, "npx", "print('ok')")
    res = changed(project, bin_dir, "--base", "main")
    assert res.returncode == 0, res.stdout + res.stderr
    out = lines(res)
    assert "template lint: gitops-app: rendered (its smoke job runs no lint)" in out
    assert "template lint: web-nextjs passed" in out
    assert [c["args"][1] for c in calls(bin_dir) if c["tool"] == "copier"] == sorted(c["args"][1] for c in calls(bin_dir) if c["tool"] == "copier")
    assert len([c for c in calls(bin_dir) if c["tool"] == "copier"]) == 2


def test_the_base_defaults_to_main_without_an_origin_ac_184_5(project, bin_dir):  # AC-184.5
    fake_tool(bin_dir, "copier", COPIER)
    (project / "templates" / "gitops-app" / "copier.yml").write_text("a: 2\n")
    sh(project, "commit", "-qam", "change the gitops template")
    res = changed(project, bin_dir)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "template lint: gitops-app: rendered (its smoke job runs no lint)" in lines(res)


# ---------------- local CI and the CI smoke jobs ----------------

def test_the_local_ci_runs_the_changed_template_lint_before_the_cplat_tests_ac_184_5():  # AC-184.5
    text = (ROOT / "scripts" / "ci-local.sh").read_text()
    assert "template-lint.py --changed" in text
    assert text.index("template-lint.py --changed") < text.index("pytest tests/cplat")


def test_the_smoke_jobs_call_the_script_instead_of_their_own_lint_lines_ac_184_5():  # AC-184.5
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert text.count("scripts/template-lint.py") >= 4                      # the `changes` filter, python, java and web
    assert "uv run ruff check ." not in text and "uv run ruff format --check ." not in text
    assert "mvn -B -q spotless:check checkstyle:check" not in text
    assert "npx -y pnpm@11.22.0 lint" not in text
    shared = next(ln for ln in text.splitlines() if ln.strip().startswith("shared=$(has "))
    assert r"template-lint\.py" in shared                                   # a change of the script runs every smoke job
    assert "golangci/golangci-lint-action" in text                          # the go smoke job keeps its action


def test_devbox_provides_the_lint_tools_ac_184_5():  # AC-184.5
    packages = json.loads((ROOT / "devbox.json").read_text())["packages"]
    names = list(packages) if isinstance(packages, dict) else [str(p) for p in packages]
    assert any(re.match(r"go(@|$)", n) for n in names), names
    assert any(n.startswith("golangci-lint") for n in names), names
    assert any("jdk" in n and "21" in n for n in names), names
    assert any(n.startswith("maven") for n in names), names
