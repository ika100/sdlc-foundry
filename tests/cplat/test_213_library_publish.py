"""Spec 213: a library release publishes its package on the tag (ADR-125).

The registry field and the template contract are checked through scripts/shapes.py; the library-python publish script runs
for real in a git repo with a fake `uv` (builds files named by the tag, like hatch-vcs) and a fake `gh` (keeps release state)."""
from __future__ import annotations

import copy
import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

import core  # noqa: F401  (puts scripts/ on sys.path)
import shapes  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "templates" / "library-python"
SCRIPT = LIB / "scripts" / "publish.sh"


def library_entry() -> dict:
    return copy.deepcopy(shapes.get("library-python"))


# ---------------- AC-213.1: the registry field ----------------

def test_library_python_declares_the_github_release_registry_ac_213_1():  # AC-213.1
    assert library_entry()["publish"] == {"registry": "github-release"}
    assert shapes.validate(shapes.load_all()) == []


@pytest.mark.parametrize("registry", ["github-release", "github-npm", "github-maven", "github-nuget"])
def test_every_known_registry_is_accepted_ac_213_1(registry):  # AC-213.1
    entry = library_entry()
    entry["publish"] = {"registry": registry}
    assert shapes.validate([entry]) == []


@pytest.mark.parametrize("publish, words", [
    (None, "library-python: a library shape needs a publish block"),
    ({"registry": "pypi"}, "library-python: publish.registry must be one of github-maven, github-npm, github-nuget, github-release"),
    ({}, "library-python: publish.registry must be one of"),
    ("github-release", "library-python: publish must be a map with registry"),
])
def test_a_library_without_a_valid_publish_block_is_refused_ac_213_1(publish, words):  # AC-213.1
    entry = library_entry()
    if publish is None:
        del entry["publish"]
    else:
        entry["publish"] = publish
    errs = shapes.validate([entry])
    assert any(e.startswith(words) for e in errs), errs


def test_a_planned_library_needs_no_publish_block_yet_ac_213_1():  # AC-213.1
    entry = library_entry()
    del entry["publish"]
    entry["status"] = "planned"
    assert not [e for e in shapes.validate([entry]) if "publish" in e]


def test_a_non_library_shape_with_a_publish_block_is_refused_ac_213_1():  # AC-213.1
    entry = copy.deepcopy(shapes.get("service-python"))
    entry["publish"] = {"registry": "github-release"}
    assert "service-python: only library shapes publish a package (spec 213)" in shapes.validate([entry])


# ---------------- AC-213.2: the template contract ----------------

def template_copy(tmp_path: Path) -> Path:
    dest = tmp_path / "library-python"
    shutil.copytree(LIB, dest)
    return dest


def edit_ci(tdir: Path, change) -> None:
    ci = tdir / ".github" / "workflows" / "ci.yml"
    ci.write_text(change(ci.read_text()))


def test_the_library_python_template_meets_the_publish_contract_ac_213_2():  # AC-213.2
    assert shapes.publish_errors("library-python", LIB, "github-release") == []
    assert shapes.check_contract(shapes.load()) == []


def test_the_publish_job_runs_on_the_tag_after_every_gate_with_the_only_write_permission_ac_213_2():  # AC-213.2
    """Structure of the shipped workflow, read as YAML after the Copier escapes are undone."""
    wf = shapes.workflow(LIB / ".github" / "workflows" / "ci.yml")
    job = wf["jobs"]["publish"]
    assert "refs/tags/v" in job["if"] and "push" in job["if"]
    assert {"quality", "test", "security", "ci-extra"} <= set(job["needs"])
    assert job["permissions"]["contents"] == "write"
    assert wf["permissions"] == {"contents": "read"}
    assert [n for n, j in wf["jobs"].items() if "write" in (j.get("permissions") or {}).values()] == ["publish"]
    checkout = next(s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/checkout@"))
    assert checkout["with"]["fetch-depth"] == 0   # the version is read from the tag (spec 138)
    assert any('devbox run publish "$GITHUB_REF_NAME"' in str(s.get("run", "")) for s in job["steps"])


@pytest.mark.parametrize("change, missing", [
    (lambda t: t.replace("\n  publish:\n", "\n  publish-package:\n"), "ci.yml has no `publish` job"),
    (lambda t: t.replace("startsWith(github.ref, 'refs/tags/v')", "true"), "the `publish` job must run only on a pushed v* tag"),
    (lambda t: t.replace("needs: [quality, test, security, ci-extra]", "needs: [quality, test]"), "the `publish` job must need quality, test, security and ci-extra"),
    (lambda t: t.replace('devbox run publish "$GITHUB_REF_NAME"', "echo publish"), "the `publish` job must run `devbox run publish` with the tag"),
    (lambda t: t.replace("permissions:\n  contents: read\n", "permissions:\n  contents: write\n", 1), "the workflow's default permissions must be `contents: read`"),
    (lambda t: t.replace("  quality:\n", "  quality:\n    permissions:\n      packages: write\n", 1), "only the `publish` job may get a write permission (quality has one)"),
    (lambda t: re.sub(r"(\n  publish:\n(?:    .*\n|\n)*?    permissions:\n)      contents: write[^\n]*\n", r"\1      contents: read\n", t), "the `publish` job needs `contents: write` for registry github-release"),
])
def test_a_template_that_breaks_the_contract_is_named_with_the_missing_piece_ac_213_2(tmp_path, change, missing):  # AC-213.2
    tdir = template_copy(tmp_path)
    edit_ci(tdir, change)
    errs = shapes.publish_errors("library-python", tdir, "github-release")
    assert f"library-python: {missing} (spec 213)" in errs, errs


def test_a_template_without_the_publish_recipe_is_named_ac_213_2(tmp_path):  # AC-213.2
    tdir = template_copy(tmp_path)
    devbox = tdir / "devbox.json"
    devbox.write_text(re.sub(r'\n\s*"publish":[^\n]*', "", devbox.read_text()))
    assert "library-python: devbox.json has no `publish` recipe (spec 213)" in shapes.publish_errors("library-python", tdir, "github-release")


def test_a_gitHub_packages_registry_needs_packages_write_ac_213_2(tmp_path):  # AC-213.2
    errs = shapes.publish_errors("library-python", LIB, "github-npm")
    assert "library-python: the `publish` job needs `packages: write` for registry github-npm (spec 213)" in errs


# ---------------- AC-213.3 / AC-213.4 / AC-213.5: the publish script ----------------

FAKE_UV = r"""#!/usr/bin/env bash
# fake uv: `uv build --out-dir DIR` writes a wheel and an sdist named like hatch-vcs would version them
set -euo pipefail
echo "uv $*" >> "$TOOL_LOG"
out=dist
while [ $# -gt 0 ]; do case "$1" in --out-dir|-o) out="$2"; shift 2;; *) shift;; esac; done
if v=$(git describe --tags --exact-match --match 'v*' 2>/dev/null) && git diff --quiet HEAD; then v="${v#v}"
elif git describe --tags --match 'v*' >/dev/null 2>&1; then v="0.1.dev1+g$(git rev-parse --short HEAD)"
else v="0.0.0"; fi
mkdir -p "$out"
touch "$out/demo_lib-$v-py3-none-any.whl" "$out/demo_lib-$v.tar.gz"
"""

FAKE_GH = r"""#!/usr/bin/env bash
# fake gh: keeps releases and their assets as files under $GH_STATE
set -euo pipefail
echo "gh $*" >> "$TOOL_LOG"
[ "$1" = release ] || exit 2
cmd="$2"; tag="$3"; shift 3
case "$cmd" in
  view) [ -d "$GH_STATE/$tag" ] ;;
  create) mkdir -p "$GH_STATE/$tag" ;;
  upload)
    [ -d "$GH_STATE/$tag" ] || { echo "release not found" >&2; exit 1; }
    for f in "$@"; do case "$f" in --*) ;; *)
      b=$(basename "$f")
      if [ -e "$GH_STATE/$tag/$b" ] && [[ " $* " != *" --clobber "* ]]; then echo "asset exists" >&2; exit 1; fi
      cp "$f" "$GH_STATE/$tag/$b";; esac; done ;;
  *) exit 2 ;;
esac
"""


@pytest.fixture
def lib_repo(tmp_path):
    repo = tmp_path / "demo-lib"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, repo / "scripts" / "publish.sh")
    (repo / "README.md").write_text("demo\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("uv", FAKE_UV), ("gh", FAKE_GH)):
        p = bin_dir / name
        p.write_text(body)
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "TOOL_LOG": str(tmp_path / "tools.log"),
           "GH_STATE": str(tmp_path / "gh"), "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}
    git = lambda *a: subprocess.run(["git", *a], cwd=repo, env=env, check=True, capture_output=True)  # noqa: E731
    git("init", "-q", "-b", "main")
    git("add", "-A")
    git("commit", "-qm", "init")

    class Repo:
        path, state, log = repo, tmp_path / "gh", tmp_path / "tools.log"

        @staticmethod
        def git(*a):
            git(*a)

        @staticmethod
        def publish(*args):
            return subprocess.run(["bash", "scripts/publish.sh", *args], cwd=repo, env=env, capture_output=True, text=True)

        @staticmethod
        def gh_calls():
            return [line for line in Repo.log.read_text().splitlines() if line.startswith("gh ")] if Repo.log.exists() else []

    return Repo


def test_the_script_is_rendered_by_copier_unchanged_ac_213_3():  # AC-213.3
    """library-python renders every file through Jinja (_templates_suffix: ""), so the script carries no Jinja syntax."""
    text = SCRIPT.read_text()
    assert not re.search(r"\{\{|\{%|\{#", text)


def test_the_recipe_runs_the_script_with_its_arguments_ac_213_3():  # AC-213.3
    recipe = json.loads(re.sub(r"\{\{[^}]*\}\}", "x", (LIB / "devbox.json").read_text()))["shell"]["scripts"]["publish"]
    assert recipe == 'bash scripts/publish.sh "$@"'


def test_a_tagged_head_publishes_wheel_and_sdist_to_a_new_release_ac_213_3(lib_repo):  # AC-213.3
    lib_repo.git("tag", "v1.2.3")
    out = lib_repo.publish("v1.2.3")
    assert out.returncode == 0, out.stderr
    assert sorted(p.name for p in (lib_repo.state / "v1.2.3").iterdir()) == ["demo_lib-1.2.3-py3-none-any.whl", "demo_lib-1.2.3.tar.gz"]
    calls = lib_repo.gh_calls()
    assert calls[0] == "gh release view v1.2.3"
    assert calls[1].startswith("gh release create v1.2.3 --verify-tag")
    assert calls[2].startswith("gh release upload v1.2.3") and calls[2].endswith("--clobber")


def test_a_second_run_replaces_the_files_on_the_existing_release_ac_213_3(lib_repo):  # AC-213.3
    lib_repo.git("tag", "v1.2.3")
    assert lib_repo.publish("v1.2.3").returncode == 0
    again = lib_repo.publish("v1.2.3")
    assert again.returncode == 0, again.stderr
    assert sorted(p.name for p in (lib_repo.state / "v1.2.3").iterdir()) == ["demo_lib-1.2.3-py3-none-any.whl", "demo_lib-1.2.3.tar.gz"]
    assert sum(c.startswith("gh release create") for c in lib_repo.gh_calls()) == 1


def test_an_existing_release_is_reused_not_created_ac_213_3(lib_repo):  # AC-213.3
    lib_repo.git("tag", "v2.0.0")
    (lib_repo.state / "v2.0.0").mkdir(parents=True)
    assert lib_repo.publish("v2.0.0").returncode == 0
    assert not [c for c in lib_repo.gh_calls() if c.startswith("gh release create")]


@pytest.mark.parametrize("setup, built", [
    ("tag-on-parent", "0.1.dev1+g"),
    ("no-tag", "0.0.0"),
])
def test_a_built_version_other_than_the_tag_fails_before_github_is_called_ac_213_4(lib_repo, setup, built):  # AC-213.4
    if setup == "tag-on-parent":
        lib_repo.git("tag", "v1.2.3")
        (lib_repo.path / "README.md").write_text("changed\n")
        lib_repo.git("commit", "-qam", "next")
    out = lib_repo.publish("v1.2.3")
    assert out.returncode == 1
    first = next(line for line in out.stderr.splitlines() if line.startswith("publish:"))
    assert "the tag is v1.2.3 (1.2.3)" in first and f"the built version is {built}" in first
    assert "fix:" in out.stderr
    assert lib_repo.gh_calls() == []
    assert not lib_repo.state.exists()


def test_a_dry_run_builds_checks_and_names_the_upload_without_github_ac_213_5(lib_repo):  # AC-213.5
    lib_repo.git("tag", "v0.3.0")
    out = lib_repo.publish("v0.3.0", "--dry-run")
    assert out.returncode == 0, out.stderr
    assert "would upload dist/demo_lib-0.3.0-py3-none-any.whl dist/demo_lib-0.3.0.tar.gz to the GitHub release v0.3.0" in out.stdout
    assert lib_repo.gh_calls() == []


def test_a_dry_run_still_fails_on_a_version_mismatch_ac_213_5(lib_repo):  # AC-213.5
    out = lib_repo.publish("v9.9.9", "--dry-run")
    assert out.returncode == 1 and "the tag is v9.9.9" in out.stderr


@pytest.mark.parametrize("args", [[], ["1.2.3"], ["v1.2.3", "--force"]])
def test_a_wrong_call_prints_the_usage_and_exits_2_ac_213_3(lib_repo, args):  # AC-213.3
    out = lib_repo.publish(*args)
    assert out.returncode == 2 and "usage: publish.sh vX.Y.Z [--dry-run]" in out.stderr


@pytest.mark.slow
@pytest.mark.skipif(not shutil.which("uv"), reason="needs uv")
def test_the_real_build_of_a_rendered_library_matches_its_tag_ac_213_3(tmp_path):  # AC-213.3, AC-213.4
    """The real copier render and the real `uv build` (hatch-vcs) in dry-run mode: tagged HEAD passes, a later commit fails."""
    repo = tmp_path / "todo-lib"
    subprocess.run(["uv", "tool", "run", "--from", "copier", "copier", "copy", str(LIB), str(repo), "--defaults", "--trust",
                    "--skip-tasks", "--data", "project_name=todo-lib", "--data", "module_name=todo_lib", "--data",
                    "description=check"], check=True, capture_output=True)
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    for cmd in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-qm", "init"], ["tag", "v1.2.3"]):
        subprocess.run(["git", *cmd], cwd=repo, env=env, check=True, capture_output=True)
    ok = subprocess.run(["bash", "scripts/publish.sh", "v1.2.3", "--dry-run"], cwd=repo, env=env, capture_output=True, text=True)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert "dist/todo_lib-1.2.3-py3-none-any.whl" in ok.stdout and "dist/todo_lib-1.2.3.tar.gz" in ok.stdout
    (repo / "README.md").write_text("next\n")
    subprocess.run(["git", "commit", "-qam", "next"], cwd=repo, env=env, check=True, capture_output=True)
    bad = subprocess.run(["bash", "scripts/publish.sh", "v1.2.3", "--dry-run"], cwd=repo, env=env, capture_output=True, text=True)
    assert bad.returncode == 1 and "the tag is v1.2.3 (1.2.3)" in bad.stderr


# ---------------- AC-213.6: the platform's CI proves it ----------------

def test_the_template_smoke_job_runs_the_publish_dry_run_and_the_mismatch_ac_213_6():  # AC-213.6
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text())
    steps = wf["jobs"]["smoke-test-templates"]["steps"]
    step = next(s for s in steps if "publish.sh" in str(s.get("run", "")))
    assert "library-python" in str(step.get("if", ""))
    run = step["run"]
    assert re.search(r"git tag v\d+\.\d+\.\d+", run)
    assert re.search(r"bash scripts/publish\.sh (v[\d.]+) --dry-run", run)
    assert "if bash scripts/publish.sh" in run   # the mismatch run is expected to fail
    assert "the built version is" in run


# ---------------- AC-213.7 / AC-213.8: the guides ----------------

def section(text: str, heading: str) -> str:
    assert heading in text, f"no {heading!r}"
    return text.split(heading, 1)[1].split("\n## ", 1)[0]


def test_the_library_guide_says_how_it_is_released_and_installed_ac_213_7():  # AC-213.7
    text = (LIB / "CLAUDE.md").read_text()
    body = section(text, "## Releasing the package")
    for word in ("`publish`", "devbox run publish", ".whl", ".tar.gz", "git+https://github.com/", "releases/download/"):
        assert word in body, word
    assert "internal index" not in text


def test_the_convention_is_recorded_in_an_adr_and_the_registry_docs_ac_213_8():  # AC-213.8
    adr = next((ROOT / "docs" / "adr").glob("125-*.md"))
    text = adr.read_text()
    for word in ("github-release", "github-npm", "github-maven", "github-nuget", "`publish`", "--dry-run",
                 "contents: write", "packages: write", "PACKAGES_READ_TOKEN"):
        assert word in text, word
    assert adr.name in (ROOT / "docs" / "adr" / "README.md").read_text()
    assert "publish:" in (ROOT / "docs" / "adr" / "015-shape-registry-as-code.md").read_text()
    assert "`publish`" in section((ROOT / "docs" / "templates.md").read_text(), "## 1. Registry entry")
