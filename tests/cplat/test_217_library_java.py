"""Spec 217 acceptance tests: the library-java shape (a Maven jar on GitHub Packages, ADR-125).

Seams: the registry and the cplat modules that name shapes, the template files and a rendered copy (copier, rendered once per
process), the real `detect-shape.sh`, `cplat component new` / `cplat shape` in-process, and the template's `scripts/publish.sh`
run for real in a git repo with a fake `mvn` (evaluates and edits the POM, writes the jar, keeps the registry as files) and a
fake `curl` (asks that registry). Maven, Spotless, Checkstyle, the JaCoCo gate and a publish dry run on the real toolchain are
proved by the platform CI job `smoke-test-library-java`, which these tests check exists.
"""
import json
import os
import re
import shutil
import stat
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

import cplat
import newsvc
import shapes
from waiting import with_prelude

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "templates" / "library-java"
SCRIPT = TEMPLATE / "scripts" / "publish.sh"
SHAPE = "library-java"
REGISTRY = "https://maven.pkg.github.com/acme/shared-utils"
NS = {"m": "http://maven.apache.org/POM/4.0.0"}


def entry() -> dict:
    return next(s for s in shapes.load() if s["id"] == SHAPE)


def _render(dest: Path, **data: str) -> Path:
    cmd = ["uv", "tool", "run", "--from", "copier", "copier", "copy", str(TEMPLATE), str(dest), "--defaults", "--trust", "--skip-tasks",
           "--data", f"project_name={dest.name}", "--data", "description=check", "--data", "github_org=AcmeCo"]
    for k, v in data.items():
        cmd += ["--data", f"{k}={v}"]
    subprocess.run(cmd, check=True, capture_output=True)
    return dest


@pytest.fixture()
def default(shared_renders, tmp_path):
    return shared_renders.copy("217 shared-utils", lambda workdir: _render(workdir / "shared-utils"), tmp_path / "shared-utils")


def recipes(repo: Path) -> dict:
    return json.loads((repo / "devbox.json").read_text())["shell"]["scripts"]


def pom(repo: Path) -> ET.Element:
    return ET.parse(repo / "pom.xml").getroot()


def text(root: ET.Element, path: str) -> str | None:
    el = root.find(path, NS)
    return el.text.strip() if el is not None and el.text else None


# ---------------- AC-217.1: the registry ----------------

def test_the_registry_holds_the_library_shape_with_its_publish_block_ac_217_1():  # AC-217.1
    e = entry()
    assert (e["plugin"], e["template"], e["deployable"], e["library"]) == ("svc-java", SHAPE, False, True)
    assert e["default_stack"]["language"] == "java" and e["default_stack"]["build_tool"] == "maven" and "runtime" not in e
    assert e["publish"] == {"registry": "github-maven"}
    assert shapes.validate(shapes.load_all()) == []
    assert shapes.publish_errors(SHAPE, TEMPLATE, "github-maven") == []
    assert shapes.check_contract(shapes.load()) == []


def test_library_java_is_a_pair_and_a_lone_java_stays_a_service_ac_217_1():  # AC-217.1
    assert newsvc.shape_of_pair("library", "java") == SHAPE
    assert newsvc.shape_of_pair(None, "java") == "service-java"
    assert newsvc.shape_of_pair("library", None) == "library-python"
    assert ("library", "java") in newsvc.valid_pairs()


# ---------------- AC-217.2: creation and detection ----------------

def test_component_new_renders_the_template_ac_217_2(tmp_path):  # AC-217.2
    rc = cplat.main(["component", "new", "shared-utils", "Shared", "utils", "--type", "library", "--lang", "java",
                     "--no-github", "--skip-tasks", "--org", "acme", "--dir", str(tmp_path)])
    assert rc == 0
    repo = tmp_path / "shared-utils"
    assert re.search(r"^_src_path: .*templates/library-java$", (repo / ".copier-answers.yml").read_text(), re.M)
    assert (repo / "pom.xml").is_file() and text(pom(repo), "m:artifactId") == "shared-utils"


def _detect(repo: Path) -> str:
    return subprocess.run(["bash", str(ROOT / "scripts" / "detect-shape.sh"), str(repo)], capture_output=True, text=True).stdout.strip()


PLAIN_POM = "<project><artifactId>utils</artifactId></project>"
BOOT_POM = "<project><parent><artifactId>spring-boot-starter-parent</artifactId></parent></project>"


@pytest.mark.parametrize("files, expected", [
    ({"pom.xml": PLAIN_POM}, SHAPE),
    ({"pom.xml": PLAIN_POM, "Dockerfile": "FROM x"}, "service-java"),
    ({"pom.xml": BOOT_POM}, "service-java"),
    ({"build.gradle.kts": ""}, "service-java"),
])
def test_detection_by_sniffing_a_pom_ac_217_2(tmp_path, files, expected):  # AC-217.2
    for name, body in files.items():
        (tmp_path / name).write_text(body)
    assert _detect(tmp_path) == expected


def test_detection_by_answers_and_of_a_fresh_render_ac_217_2(tmp_path, default):  # AC-217.2
    (tmp_path / ".copier-answers.yml").write_text("_src_path: gh:ika100/sdlc-foundry/templates/library-java\n")
    assert _detect(tmp_path) == SHAPE
    assert _detect(default) == SHAPE


# ---------------- AC-217.3: recipes and gates ----------------

CANONICAL = ["lint", "lint-fix", "typecheck", "quality", "test", "test-fast", "audit", "security", "secrets-baseline", "ci", "build",
             "publish", "deps-findings", "deps-bump", "spec-check"]


def test_the_render_has_the_canonical_recipes_and_no_image_ac_217_3(default):  # AC-217.3
    r = recipes(default)
    assert [n for n in CANONICAL if n not in r] == []
    assert [n for n in ("smoke", "image-build", "image-scan", "dev") if n in r] == []
    assert r["test"] == 'bash scripts/gate.sh tests test maven -- mvn -B verify "$@"'
    assert r["test-fast"] == 'bash scripts/gate.sh tests test-fast maven -- mvn -B test "$@"'
    assert r["lint"] == "mvn -B spotless:check checkstyle:check"
    assert r["ci"].endswith("then devbox run ci-extra; fi") and "devbox run quality" in r["ci"] and "devbox run security" in r["ci"]
    assert r["publish"] == 'bash scripts/publish.sh "$@"'
    assert not (default / "Dockerfile").exists() and not (default / ".dockerignore").exists()
    assert (default / "scripts" / "gate.sh").read_bytes() == (ROOT / "templates" / "gitops-app" / "scripts" / "gate.sh").read_bytes()
    for name in ("deps.sh", "PomDeps.java"):
        assert (default / "scripts" / name).read_bytes() == (ROOT / "templates" / "service-java" / "scripts" / name).read_bytes()
    assert (default / "config" / "checkstyle.xml").read_bytes() == (ROOT / "templates" / "service-java" / "config" / "checkstyle.xml").read_bytes()
    tests = list((default / "src" / "test" / "java").rglob("*Test.java"))
    assert tests and any("@Test" in t.read_text() for t in tests)


def test_the_coverage_gate_is_80_percent_of_lines_ac_217_3(default):  # AC-217.3
    root = pom(default)
    jacoco = next(p for p in root.iterfind("m:build/m:plugins/m:plugin", NS) if text(p, "m:artifactId") == "jacoco-maven-plugin")
    limit = jacoco.find(".//m:limit", NS)
    assert (text(limit, "m:counter"), text(limit, "m:value"), text(limit, "m:minimum")) == ("LINE", "COVEREDRATIO", "0.80")


# ---------------- AC-217.4: the artifact ----------------

def test_the_pom_is_a_plain_jar_for_github_packages_ac_217_4(default):  # AC-217.4
    root = pom(default)
    assert root.find("m:parent", NS) is None
    assert (text(root, "m:groupId"), text(root, "m:artifactId"), text(root, "m:version"), text(root, "m:packaging")) == \
        ("io.github.acmeco", "shared-utils", "0.0.0-SNAPSHOT", "jar")
    assert text(root, "m:properties/m:maven.compiler.release") == "21"
    assert text(root, "m:url") == "https://github.com/AcmeCo/shared-utils"
    assert text(root, "m:scm/m:url") == "https://github.com/AcmeCo/shared-utils"
    repo = root.find("m:distributionManagement/m:repository", NS)
    assert (text(repo, "m:id"), text(repo, "m:url")) == ("github", "https://maven.pkg.github.com/acmeco/shared-utils")
    plugins = list(root.iterfind("m:build/m:plugins/m:plugin", NS))
    assert {text(p, "m:artifactId") for p in plugins} >= {"maven-source-plugin", "maven-compiler-plugin", "maven-surefire-plugin",
                                                          "maven-deploy-plugin", "spotless-maven-plugin", "maven-checkstyle-plugin"}
    assert [text(p, "m:artifactId") for p in plugins if not text(p, "m:version")] == []
    assert "spring" not in (default / "pom.xml").read_text().lower()


def test_the_sample_code_lives_in_the_package_ac_217_4(default):  # AC-217.4
    main = list((default / "src" / "main" / "java" / "io" / "github" / "acmeco" / "sharedutils").glob("*.java"))
    assert main and all(m.read_text().startswith("package io.github.acmeco.sharedutils;") for m in main)


# ---------------- AC-217.5 / AC-217.6 / AC-217.7: the publish script ----------------

FAKE_MVN = r'''#!/usr/bin/env python3
"""fake mvn: help:evaluate, versions:set, package and deploy on ./pom.xml; deploy copies the jar into $MVN_STATE"""
import os, re, sys, pathlib
args = sys.argv[1:]
with open(os.environ["TOOL_LOG"], "a") as log:
    log.write("mvn " + " ".join(args) + "\n")
pom = pathlib.Path("pom.xml")
text = pom.read_text()
def value(name):
    return re.search(r"<%s>([^<]*)</%s>" % (name, name), text).group(1)
def prop(expr):
    if expr == "project.distributionManagement.repository.url":
        return re.search(r"<distributionManagement>.*?<url>([^<]*)</url>", text, re.S).group(1)
    return value(expr.split(".")[-1])
goal = next((a for a in args if a.endswith(":evaluate") or a.endswith(":set") or a in ("package", "deploy")), None)
opt = {a[2:].split("=", 1)[0]: a.split("=", 1)[1] for a in args if a.startswith("-D") and "=" in a}
if goal.endswith(":evaluate"):
    sys.stdout.write(prop(opt["expression"]))
elif goal.endswith(":set"):
    pom.write_text(re.sub(r"<version>[^<]*</version>", "<version>%s</version>" % opt["newVersion"], text, count=1))
else:
    assert "-DskipTests" in args and opt.get("jacoco.skip") == "true", args
    a, v, g = value("artifactId"), value("version"), value("groupId")
    pathlib.Path("target").mkdir(exist_ok=True)
    jar = pathlib.Path("target") / ("%s-%s.jar" % (a, v))
    jar.write_text("%s:%s:%s\n" % (g, a, v))
    if goal == "deploy":
        settings = pathlib.Path(args[args.index("-s") + 1]).read_text()
        assert "<id>github</id>" in settings and "${env.GH_TOKEN}" in settings, settings
        with open(os.environ["TOOL_LOG"], "a") as log:
            log.write("token=%s\n" % os.environ["GH_TOKEN"])
        state = pathlib.Path(os.environ["MVN_STATE"]) / g.replace(".", "/") / a / v
        state.mkdir(parents=True, exist_ok=True)
        (state / jar.name).write_text(jar.read_text())
        (state / ("%s-%s.pom" % (a, v))).write_text(text)
'''

FAKE_CURL = r"""#!/usr/bin/env bash
# fake curl: the last argument is the URL; it exists when $MVN_STATE holds the path under the registry
set -euo pipefail
echo "curl $*" >> "$TOOL_LOG"
url="${@: -1}"
case "$*" in *"-u "*":$GH_TOKEN"*) ;; *) exit 22 ;; esac
path="${url#https://maven.pkg.github.com/acme/shared-utils/}"
[ -e "$MVN_STATE/$path" ] || exit 22
"""

POM = """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>io.acme</groupId>
  <artifactId>shared-utils</artifactId>
  <version>0.0.0-SNAPSHOT</version>
  <distributionManagement>
    <repository>
      <id>github</id>
      <url>https://maven.pkg.github.com/acme/shared-utils</url>
    </repository>
  </distributionManagement>
</project>
"""

needs_python = pytest.mark.skipif(not shutil.which("python3"), reason="needs python3")


@pytest.fixture
def lib_repo(tmp_path):
    repo = tmp_path / "shared-utils"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, repo / "scripts" / "publish.sh")
    (repo / "pom.xml").write_text(POM)
    (repo / ".gitignore").write_text("target/\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("mvn", FAKE_MVN), ("curl", FAKE_CURL)):
        p = bin_dir / name
        p.write_text(with_prelude(body))
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "TOOL_LOG": str(tmp_path / "tools.log"),
           "MVN_STATE": str(tmp_path / "registry"), "GH_TOKEN": "tok-123", "GIT_AUTHOR_NAME": "t",
           "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}

    def git(*a):
        subprocess.run(["git", *a], cwd=repo, env=env, check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    git("add", "-A")
    git("commit", "-qm", "init")

    class Repo:
        path, registry, log = repo, tmp_path / "registry", tmp_path / "tools.log"

        @staticmethod
        def git(*a):
            git(*a)

        @staticmethod
        def publish(*args, **extra):
            return subprocess.run(["bash", "scripts/publish.sh", *args], cwd=repo, env={**env, **extra}, capture_output=True, text=True)

        @staticmethod
        def calls(tool):
            return [x for x in Repo.log.read_text().splitlines() if x.startswith(tool + " ")] if Repo.log.exists() else []

        @staticmethod
        def builds():
            return [c for c in Repo.calls("mvn") if c.split()[-1] in ("package", "deploy") or ":set " in c + " "]

        @staticmethod
        def published():
            return sorted(str(p.relative_to(Repo.registry)) for p in Repo.registry.rglob("*.jar")) if Repo.registry.exists() else []

    return Repo


def test_the_script_is_copied_by_copier_unchanged_ac_217_5():  # AC-217.5
    """Only *.jinja files are rendered, so the script reaches the repo byte for byte."""
    assert yaml.safe_load((TEMPLATE / "copier.yml").read_text())["_templates_suffix"] == ".jinja"
    assert SCRIPT.stat().st_mode & stat.S_IXUSR


@needs_python
def test_a_tagged_head_deploys_the_tag_version_and_keeps_the_pom_ac_217_5(lib_repo):  # AC-217.5
    lib_repo.git("tag", "v1.2.3")
    r = lib_repo.publish("v1.2.3")
    assert r.returncode == 0, r.stderr
    assert f"publish: published io.acme:shared-utils:1.2.3 to {REGISTRY}" in r.stdout
    assert lib_repo.published() == ["io/acme/shared-utils/1.2.3/shared-utils-1.2.3.jar"]
    assert "token=tok-123" in lib_repo.log.read_text()
    deploy = next(c for c in lib_repo.calls("mvn") if c.endswith(" deploy"))
    assert " -s " in deploy and "-DskipTests" in deploy
    assert (lib_repo.path / "pom.xml").read_text() == POM
    assert subprocess.run(["git", "status", "--porcelain"], cwd=lib_repo.path, capture_output=True, text=True).stdout == ""
    assert "tok-123" not in "".join(p.read_text(errors="ignore") for p in lib_repo.path.rglob("*") if p.is_file() and ".git" not in p.parts)


@needs_python
def test_a_rerun_of_a_published_version_is_a_no_op_ac_217_5(lib_repo):  # AC-217.5
    lib_repo.git("tag", "v1.2.3")
    assert lib_repo.publish("v1.2.3").returncode == 0
    r = lib_repo.publish("v1.2.3")
    assert r.returncode == 0, r.stderr
    assert "already in" in r.stdout and "nothing to do" in r.stdout
    assert len([c for c in lib_repo.calls("mvn") if c.endswith(" deploy")]) == 1
    assert (lib_repo.path / "pom.xml").read_text() == POM


@needs_python
@pytest.mark.parametrize("setup", ["tag-on-other-commit", "no-tag", "dirty"])
def test_a_commit_that_is_not_the_tagged_one_publishes_nothing_ac_217_6(lib_repo, setup):  # AC-217.6
    if setup == "tag-on-other-commit":
        lib_repo.git("tag", "v1.2.3")
        lib_repo.git("commit", "-q", "--allow-empty", "-m", "next")
    elif setup == "dirty":
        lib_repo.git("tag", "v1.2.3")
        (lib_repo.path / "Extra.java").write_text("x\n")
    r = lib_repo.publish("v1.2.3")
    assert r.returncode == 1
    assert "publish: the built version is 0.0.0-SNAPSHOT but the tag is v1.2.3 (1.2.3)" in r.stderr
    assert re.search(r"^fix: ", r.stderr, re.M)
    assert lib_repo.builds() == [] and lib_repo.calls("curl") == [] and lib_repo.published() == []


@pytest.mark.parametrize("args", [[], ["1.2.3"], ["v1.2.3", "--force"], ["v1.2.3", "--dry-run", "x"], ["latest"]])
def test_a_wrong_argument_list_exits_2_with_the_usage_ac_217_6(lib_repo, args):  # AC-217.6
    r = lib_repo.publish(*args)
    assert r.returncode == 2 and "usage: publish.sh vX.Y.Z [--dry-run]" in r.stderr


@needs_python
def test_a_dry_run_builds_and_checks_without_the_registry_ac_217_7(lib_repo):  # AC-217.7
    lib_repo.git("tag", "v2.0.0")
    r = lib_repo.publish("v2.0.0", "--dry-run", GH_TOKEN="")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == f"publish: would publish target/shared-utils-2.0.0.jar as io.acme:shared-utils:2.0.0 to {REGISTRY}"
    assert (lib_repo.path / "target" / "shared-utils-2.0.0.jar").read_text() == "io.acme:shared-utils:2.0.0\n"
    assert lib_repo.calls("curl") == [] and lib_repo.published() == []
    assert not [c for c in lib_repo.calls("mvn") if c.endswith(" deploy")]
    assert (lib_repo.path / "pom.xml").read_text() == POM


@needs_python
def test_a_dry_run_of_another_commit_fails_the_same_way_ac_217_7(lib_repo):  # AC-217.7
    lib_repo.git("tag", "v2.0.0")
    lib_repo.git("commit", "-q", "--allow-empty", "-m", "next")
    r = lib_repo.publish("v2.0.0", "--dry-run")
    assert r.returncode == 1 and "but the tag is v2.0.0 (2.0.0)" in r.stderr


# ---------------- AC-217.8: CI ----------------

def _workflow(repo: Path) -> dict:
    return yaml.safe_load((repo / ".github" / "workflows" / "ci.yml").read_text())


def test_ci_has_the_library_job_set_and_the_publish_job_ac_217_8(default):  # AC-217.8
    wf = _workflow(default)
    jobs = wf["jobs"]
    assert set(jobs) == {"quality", "test", "security", "ci-extra", "publish", "pr-title"}
    assert wf["permissions"] == {"contents": "read"}
    names = {j.get("name") for j in jobs.values()}
    assert [c for c in entry()["ci_checks"] if c not in names] == []
    uses = [st["uses"] for j in jobs.values() for st in j.get("steps", []) if "uses" in st]
    assert uses and all(re.search(r"@[0-9a-f]{40}$", u.split(" ")[0]) for u in uses), uses
    pub = jobs["publish"]
    assert pub["if"] == "github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')"
    assert pub["needs"] == ["quality", "test", "security", "ci-extra"]
    assert pub["permissions"] == {"contents": "read", "packages": "write"}
    assert [n for n, j in jobs.items() if "write" in (j.get("permissions") or {}).values()] == ["publish"]
    step = next(s for s in pub["steps"] if "devbox run publish" in str(s.get("run", "")))
    assert step["run"] == 'devbox run publish "$GITHUB_REF_NAME"'
    assert step["env"] == {"GH_TOKEN": "${{ secrets.GITHUB_TOKEN }}"}
    checkout = next(s for s in pub["steps"] if str(s.get("uses", "")).startswith("actions/checkout@"))
    assert checkout["with"]["fetch-depth"] == 0


# ---------------- AC-217.9: the consumer guide ----------------

def test_the_guide_says_how_the_jar_is_released_and_used_ac_217_9(default):  # AC-217.9
    text_ = (default / "CLAUDE.md").read_text()
    section = text_.split("## Releasing the package", 1)[1].split("\n## ", 1)[0]
    for needle in ("`publish` job", "devbox run publish vX.Y.Z", "io.github.acmeco:shared-utils",
                   "https://maven.pkg.github.com/acmeco/shared-utils", "<id>github</id>", "<server>", "read:packages",
                   "PACKAGES_READ_TOKEN", "<artifactId>shared-utils</artifactId>"):
        assert needle in section, needle


# ---------------- AC-217.10: shape-wide tooling ----------------

def test_the_platform_tooling_knows_the_shape_ac_217_10():  # AC-217.10
    import buildtests
    import comprelease
    import deps_parse
    assert deps_parse.TOOLS[SHAPE] == "trivy" and deps_parse.DEP_FILES[SHAPE] == ("pom.xml",)
    assert buildtests.TEST_FAST[SHAPE] == buildtests.TEST_FAST["service-java"]
    assert comprelease.next_dev("v1.2.3", SHAPE, Path("/nonexistent")) is None   # the version comes from the tag
    for rel in ("scripts/bump_template_pins.py", "scripts/sync-template-copies.py", "scripts/template-lint.py",
                "scripts/ci-local.sh", "templates/gitops-app/scripts/plan.py", ".github/dependabot.yml"):
        assert SHAPE in (ROOT / rel).read_text(), rel
    for rel in ("templates/gitops-app/scripts/render.py", "templates/cluster-gitops/scripts/system_render.py"):
        assert '("library", "java")' in (ROOT / rel).read_text(), rel


def test_the_copies_are_kept_in_sync_ac_217_10():  # AC-217.10
    import importlib.util
    spec = importlib.util.spec_from_file_location("sync_copies", ROOT / "scripts" / "sync-template-copies.py")
    sync = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sync)
    copies = {str(c.relative_to(ROOT)) for _, c in sync.COPIES}
    assert {f"templates/{SHAPE}/scripts/{n}" for n in ("gate.sh", "deps.sh", "PomDeps.java")} <= copies


def test_the_release_agent_skips_the_version_file_for_a_library_ac_217_10():  # AC-217.10
    """The orchestrator passes VERSION_FILE none for the shape; the agent's version step names that case."""
    agent = (ROOT / "plugins" / "svc-java" / "agents" / "release.md").read_text()
    step = re.search(r"^### 3\..*$", agent, re.M).group(0)
    assert "none" in step


def test_the_template_enables_the_plugins_ac_217_10():  # AC-217.10
    text_ = (TEMPLATE / ".claude" / "settings.json.jinja").read_text()
    for p in ("svc-java", "svc", "shared"):
        assert f'"{p}@sdlc-foundry": true' in text_


def test_cplat_shape_routes_the_roles_of_a_rendered_repo_ac_217_10(default, capsys):  # AC-217.10
    assert cplat.main(["shape", "--repo", str(default)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["shape"] == SHAPE and out["library"] is True and out["deployable"] is False
    assert out["agents"]["coder"] == "svc-java:coder" and out["agents"]["architect"] == "svc:architect"


def test_the_platform_ci_smoke_tests_the_template_ac_217_10():  # AC-217.10
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text())
    job = wf["jobs"]["smoke-test-library-java"]
    assert job["if"] == "needs.changes.outputs.javalib == 'true'"
    steps = " ".join(str(s.get("run", "")) for s in job["steps"])
    for needle in ("detect-shape.sh", 'template-lint.py" library-java', "test-fast", "publish.sh v1.2.3 --dry-run",
                   "git update-ref refs/tags/v1.2.3 HEAD", "but the tag is v1.2.3 (1.2.3)", "checked nothing: 0 tests ran"):
        assert needle in steps, needle
    assert "smoke-test-library-java" in wf["jobs"]["ci-success"]["needs"]
    lint = next(s["run"] for s in wf["jobs"]["validate-shapes"]["steps"] if "actionlint" in str(s.get("run", "")))
    assert SHAPE in lint


# ---------------- AC-217.11: docs ----------------

@pytest.mark.parametrize("rel", ["docs/templates.md", "site/src/content/docs/concepts/shapes.md", "docs/requirements/platform-vision.md",
                                 "CLAUDE.md", "plugins/svc-java/README.md"])
def test_the_docs_name_the_shape_ac_217_11(rel):  # AC-217.11
    assert SHAPE in (ROOT / rel).read_text(), rel
