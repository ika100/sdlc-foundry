"""Spec 221 acceptance tests: the library-dotnet shape (a NuGet package on GitHub Packages, ADR-125).

Seams: the registry and the cplat modules that name shapes, the template files and a rendered copy (copier, rendered once per
process), the real `detect-shape.sh`, `cplat component new` / `cplat shape` in-process, and the template's `scripts/publish.sh`
run for real in a git repo with a fake `dotnet` (reads the project's properties, packs, and pushes into a registry kept as
files). The SDK, `dotnet format`, the analyzers, the coverage gate and a publish dry run on the real toolchain are proved by the
platform CI job `smoke-test-library-dotnet`, which these tests check exists.
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
TEMPLATE = ROOT / "templates" / "library-dotnet"
SCRIPT = TEMPLATE / "scripts" / "publish.sh"
SHAPE = "library-dotnet"
REGISTRY = "https://nuget.pkg.github.com/acme/index.json"


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
    return shared_renders.copy("221 shared-utils", lambda workdir: _render(workdir / "shared-utils"), tmp_path / "shared-utils")


def recipes(repo: Path) -> dict:
    return json.loads((repo / "devbox.json").read_text())["shell"]["scripts"]


def props(path: Path) -> dict[str, str]:
    """Every property of the project file's PropertyGroups (no MSBuild namespace in SDK-style projects)."""
    root = ET.parse(path).getroot()
    return {el.tag: (el.text or "").strip() for group in root.iter("PropertyGroup") for el in group}


# ---------------- AC-221.1: the registry ----------------

def test_the_registry_holds_the_library_shape_with_its_publish_block_ac_221_1():  # AC-221.1
    e = entry()
    assert (e["plugin"], e["template"], e["deployable"], e["library"]) == ("svc-dotnet", SHAPE, False, True)
    assert e["default_stack"]["language"] == "csharp" and "runtime" not in e
    assert e["publish"] == {"registry": "github-nuget"}
    assert not e.get("ux_designer")
    assert shapes.validate(shapes.load_all()) == []
    assert shapes.publish_errors(SHAPE, TEMPLATE, "github-nuget") == []
    assert shapes.check_contract(shapes.load()) == []


def test_library_csharp_is_a_pair_and_a_lone_csharp_stays_a_service_ac_221_1():  # AC-221.1
    assert newsvc.shape_of_pair("library", "csharp") == SHAPE
    assert newsvc.shape_of_pair(None, "csharp") == "service-dotnet"
    assert newsvc.shape_of_pair("library", None) == "library-python"
    assert ("library", "csharp") in newsvc.valid_pairs()


# ---------------- AC-221.2: creation and detection ----------------

def test_component_new_renders_the_template_ac_221_2(tmp_path):  # AC-221.2
    rc = cplat.main(["component", "new", "shared-utils", "Shared", "utils", "--type", "library", "--lang", "csharp",
                     "--no-github", "--skip-tasks", "--org", "acme", "--dir", str(tmp_path)])
    assert rc == 0
    repo = tmp_path / "shared-utils"
    assert re.search(r"^_src_path: .*templates/library-dotnet$", (repo / ".copier-answers.yml").read_text(), re.M)
    assert (repo / "src" / "SharedUtils" / "SharedUtils.csproj").is_file()


def _detect(repo: Path) -> str:
    return subprocess.run(["bash", str(ROOT / "scripts" / "detect-shape.sh"), str(repo)], capture_output=True, text=True).stdout.strip()


@pytest.mark.parametrize("files, expected", [
    ({"Lib.slnx": "<Solution />"}, SHAPE),
    ({"Lib.sln": ""}, SHAPE),
    ({"Lib.csproj": "<Project />"}, SHAPE),
    ({"src/Lib.csproj": "<Project />"}, SHAPE),
    ({"Lib.slnx": "<Solution />", "Dockerfile": "FROM x"}, "service-dotnet"),
    ({"src/Api.csproj": "<Project />", "Dockerfile": "FROM x"}, "service-dotnet"),
])
def test_detection_by_sniffing_a_solution_or_project_ac_221_2(tmp_path, files, expected):  # AC-221.2
    for name, body in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(body)
    assert _detect(tmp_path) == expected


def test_detection_by_answers_and_of_a_fresh_render_ac_221_2(tmp_path, default):  # AC-221.2
    (tmp_path / ".copier-answers.yml").write_text("_src_path: gh:ika100/sdlc-foundry/templates/library-dotnet\n")
    assert _detect(tmp_path) == SHAPE
    assert _detect(default) == SHAPE


# ---------------- AC-221.3: recipes and gates ----------------

CANONICAL = ["install", "build", "lint", "lint-fix", "typecheck", "quality", "test", "test-fast", "audit", "secrets-scan", "security",
             "secrets-baseline", "ci", "publish", "deps-findings", "deps-bump", "spec-check"]
SERVICE = ROOT / "templates" / "service-dotnet"


def test_the_render_has_the_canonical_recipes_and_no_image_ac_221_3(default):  # AC-221.3
    r = recipes(default)
    assert [n for n in CANONICAL if n not in r] == []
    assert [n for n in ("smoke", "image-build", "image-scan", "dev", "start") if n in r] == []
    assert r["install"] == "dotnet restore --locked-mode"
    assert r["test"].startswith("bash scripts/gate.sh tests test dotnet -- dotnet test -p:CollectCoverage=true -p:Threshold=80 -p:ThresholdType=line")
    assert r["test-fast"] == 'bash scripts/gate.sh tests test-fast dotnet -- dotnet test "$@"'
    assert r["lint"] == "dotnet format --verify-no-changes --severity warn"
    assert r["ci"].startswith("devbox run install && devbox run quality") and r["ci"].endswith("then devbox run ci-extra; fi")
    assert "devbox run security" in r["ci"]
    assert r["publish"] == 'bash scripts/publish.sh "$@"'
    assert not (default / "Dockerfile").exists() and not (default / ".dockerignore").exists()
    assert (default / "scripts" / "gate.sh").read_bytes() == (ROOT / "templates" / "gitops-app" / "scripts" / "gate.sh").read_bytes()
    assert (default / "scripts" / "deps.sh").read_bytes() == (SERVICE / "scripts" / "deps.sh").read_bytes()
    assert (default / ".editorconfig").read_bytes() == (SERVICE / ".editorconfig").read_bytes()
    tests = list((default / "tests").rglob("*Tests.cs"))
    assert tests and any("[Fact]" in t.read_text() for t in tests)


def test_the_build_settings_match_the_service_ac_221_3(default):  # AC-221.3
    p = props(default / "Directory.Build.props")
    assert p["TreatWarningsAsErrors"] == "true" and p["EnforceCodeStyleInBuild"] == "true"
    assert p["RestorePackagesWithLockFile"] == "true" and p["TargetFramework"] == "net10.0"
    assert "InvariantGlobalization" not in p   # a library leaves globalization to its consumer
    assert (default / "global.json").read_text() == (SERVICE / "global.json.jinja").read_text().replace("{{ dotnet_major }}", "10")
    answers = [yaml.safe_load((t / "copier.yml").read_text()) for t in (TEMPLATE, SERVICE)]
    for key in ("dotnet_major", "dotnet_sdk_version"):   # one pinned SDK for every .NET template
        assert answers[0][key]["default"] == answers[1][key]["default"], key
    devbox = json.loads((default / "devbox.json").read_text())
    assert f"dotnet-sdk_10@{answers[1]['dotnet_sdk_version']['default']}" in devbox["packages"]


# ---------------- AC-221.4: the package ----------------

def test_the_project_is_a_packable_library_for_github_packages_ac_221_4(default):  # AC-221.4
    lib = default / "src" / "SharedUtils" / "SharedUtils.csproj"
    root = ET.parse(lib).getroot()
    assert root.get("Sdk") == "Microsoft.NET.Sdk"
    p = props(lib)
    assert (p["PackageId"], p["Version"], p["IsPackable"]) == ("SharedUtils", "0.0.0-dev", "true")
    assert p["Description"] == "check" and p["RepositoryUrl"] == "https://github.com/AcmeCo/shared-utils"
    assert p["PackageReadmeFile"] == "README.md"
    assert any(el.get("Include", "").endswith("README.md") and el.get("Pack") == "true" for el in root.iter("None"))
    assert props(default / "tests" / "SharedUtils.Tests" / "SharedUtils.Tests.csproj")["IsPackable"] == "false"
    solution = (default / "SharedUtils.slnx").read_text()
    assert re.findall(r'Path="([^"]+)"', solution) == ["src/SharedUtils/SharedUtils.csproj", "tests/SharedUtils.Tests/SharedUtils.Tests.csproj"]


def test_the_sample_code_lives_in_the_namespace_ac_221_4(default):  # AC-221.4
    main = list((default / "src" / "SharedUtils").glob("*.cs"))
    assert main and all("namespace SharedUtils;" in m.read_text() for m in main)


# ---------------- AC-221.5 / AC-221.6 / AC-221.7: the publish script ----------------

FAKE_DOTNET = r'''#!/usr/bin/env python3
"""fake dotnet: msbuild -getProperty, restore, pack (-p:Version, -o) and nuget push into $NUGET_STATE"""
import os, re, sys, pathlib
args = sys.argv[1:]
with open(os.environ["TOOL_LOG"], "a") as log:
    log.write("dotnet " + " ".join(args) + "\n")
def project():
    found = [a for a in args if a.endswith(".csproj")]
    return pathlib.Path(found[0]) if found else next(pathlib.Path("src").glob("*/*.csproj"))
def prop(text, name):
    m = re.search(r"<%s>([^<]*)</%s>" % (name, name), text)
    return m.group(1) if m else ""
if args[0] == "msbuild":
    text = project().read_text()
    name = next(a.split(":", 1)[1] for a in args if a.startswith("-getProperty:"))
    sys.stdout.write(prop(text, name) + "\n")
elif args[0] == "restore":
    pass
elif args[0] == "pack":
    text = project().read_text()
    version = next((a.split("=", 1)[1] for a in args if a.startswith("-p:Version=")), prop(text, "Version"))
    out = pathlib.Path(args[args.index("-o") + 1])
    out.mkdir(parents=True, exist_ok=True)
    (out / ("%s.%s.nupkg" % (prop(text, "PackageId"), version))).write_text("%s %s\n" % (prop(text, "PackageId"), version))
elif args[:2] == ["nuget", "push"]:
    assert "--skip-duplicate" in args and args[args.index("--source") + 1] == "github", args
    config = pathlib.Path(args[args.index("--configfile") + 1]).read_text()
    token = os.environ["GH_TOKEN"]
    assert 'key="github"' in config and token in config and "https://nuget.pkg.github.com/acme/index.json" in config, config
    assert os.environ.get("NUGET_API_KEY") == token and "--api-key" not in args and token not in " ".join(args), args
    with open(os.environ["TOOL_LOG"], "a") as log:
        log.write("token=%s\n" % token)
    pkg = pathlib.Path(args[2])
    state = pathlib.Path(os.environ["NUGET_STATE"])
    state.mkdir(parents=True, exist_ok=True)
    if (state / pkg.name).exists():
        print("warn : Conflict - The feed already contains '%s'." % pkg.name)
    else:
        (state / pkg.name).write_text(pkg.read_text())
        print("Your package was pushed.")
else:
    sys.exit("fake dotnet: unexpected %s" % args)
'''

CSPROJ = """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <PackageId>SharedUtils</PackageId>
    <Version>0.0.0-dev</Version>
    <IsPackable>true</IsPackable>
    <RepositoryUrl>https://github.com/Acme/shared-utils</RepositoryUrl>
  </PropertyGroup>
</Project>
"""

needs_python = pytest.mark.skipif(not shutil.which("python3"), reason="needs python3")


@pytest.fixture
def lib_repo(tmp_path):
    repo = tmp_path / "shared-utils"
    (repo / "scripts").mkdir(parents=True)
    (repo / "src" / "SharedUtils").mkdir(parents=True)
    shutil.copy(SCRIPT, repo / "scripts" / "publish.sh")
    (repo / "src" / "SharedUtils" / "SharedUtils.csproj").write_text(CSPROJ)
    (repo / ".gitignore").write_text("artifacts/\nbin/\nobj/\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "dotnet"
    fake.write_text(with_prelude(FAKE_DOTNET))
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "TOOL_LOG": str(tmp_path / "tools.log"),
           "NUGET_STATE": str(tmp_path / "registry"), "GH_TOKEN": "tok-123", "GIT_AUTHOR_NAME": "t",
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
        def calls(prefix):
            return [x for x in Repo.log.read_text().splitlines() if x.startswith(prefix)] if Repo.log.exists() else []

        @staticmethod
        def published():
            return sorted(p.name for p in Repo.registry.glob("*.nupkg")) if Repo.registry.exists() else []

    return Repo


def test_the_script_is_copied_by_copier_unchanged_ac_221_5():  # AC-221.5
    """Only *.jinja files are rendered, so the script reaches the repo byte for byte."""
    assert yaml.safe_load((TEMPLATE / "copier.yml").read_text())["_templates_suffix"] == ".jinja"
    assert SCRIPT.stat().st_mode & stat.S_IXUSR


def _clean(repo: Path) -> bool:
    return subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True).stdout == ""


@needs_python
def test_a_tagged_head_pushes_the_tag_version_and_keeps_the_tree_ac_221_5(lib_repo):  # AC-221.5
    lib_repo.git("tag", "v1.2.3")
    r = lib_repo.publish("v1.2.3")
    assert r.returncode == 0, r.stderr
    assert f"publish: published SharedUtils 1.2.3 to {REGISTRY}" in r.stdout
    assert lib_repo.published() == ["SharedUtils.1.2.3.nupkg"]
    assert "token=tok-123" in lib_repo.log.read_text()
    pack = next(c for c in lib_repo.calls("dotnet pack"))
    assert "-p:Version=1.2.3" in pack and "--no-restore" in pack
    assert lib_repo.calls("dotnet restore") and "--locked-mode" in lib_repo.calls("dotnet restore")[0]
    assert (lib_repo.path / "src" / "SharedUtils" / "SharedUtils.csproj").read_text() == CSPROJ
    assert _clean(lib_repo.path)
    assert "tok-123" not in "".join(p.read_text(errors="ignore") for p in lib_repo.path.rglob("*") if p.is_file() and ".git" not in p.parts)


@needs_python
def test_a_rerun_of_a_published_version_is_a_no_op_ac_221_5(lib_repo):  # AC-221.5
    lib_repo.git("tag", "v1.2.3")
    assert lib_repo.publish("v1.2.3").returncode == 0
    r = lib_repo.publish("v1.2.3")
    assert r.returncode == 0, r.stderr
    assert "already in" in r.stdout and "nothing to do" in r.stdout
    assert lib_repo.published() == ["SharedUtils.1.2.3.nupkg"]
    assert _clean(lib_repo.path)


@needs_python
@pytest.mark.parametrize("setup", ["tag-on-other-commit", "no-tag", "dirty"])
def test_a_commit_that_is_not_the_tagged_one_publishes_nothing_ac_221_6(lib_repo, setup):  # AC-221.6
    if setup == "tag-on-other-commit":
        lib_repo.git("tag", "v1.2.3")
        lib_repo.git("commit", "-q", "--allow-empty", "-m", "next")
    elif setup == "dirty":
        lib_repo.git("tag", "v1.2.3")
        (lib_repo.path / "Extra.cs").write_text("x\n")
    r = lib_repo.publish("v1.2.3")
    assert r.returncode == 1
    assert "publish: the built version is 0.0.0-dev but the tag is v1.2.3 (1.2.3)" in r.stderr
    assert re.search(r"^fix: ", r.stderr, re.M)
    assert lib_repo.calls("dotnet pack") == [] and lib_repo.calls("dotnet nuget") == [] and lib_repo.published() == []


@pytest.mark.parametrize("args", [[], ["1.2.3"], ["v1.2.3", "--force"], ["v1.2.3", "--dry-run", "x"], ["latest"]])
def test_a_wrong_argument_list_exits_2_with_the_usage_ac_221_6(lib_repo, args):  # AC-221.6
    r = lib_repo.publish(*args)
    assert r.returncode == 2 and "usage: publish.sh vX.Y.Z [--dry-run]" in r.stderr


@needs_python
def test_a_dry_run_packs_and_checks_without_the_registry_ac_221_7(lib_repo):  # AC-221.7
    lib_repo.git("tag", "v2.0.0")
    r = lib_repo.publish("v2.0.0", "--dry-run", GH_TOKEN="")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == f"publish: would publish artifacts/SharedUtils.2.0.0.nupkg as SharedUtils 2.0.0 to {REGISTRY}"
    assert (lib_repo.path / "artifacts" / "SharedUtils.2.0.0.nupkg").read_text() == "SharedUtils 2.0.0\n"
    assert lib_repo.calls("dotnet nuget") == [] and lib_repo.published() == []
    assert _clean(lib_repo.path)


@needs_python
def test_a_dry_run_of_another_commit_fails_the_same_way_ac_221_7(lib_repo):  # AC-221.7
    lib_repo.git("tag", "v2.0.0")
    lib_repo.git("commit", "-q", "--allow-empty", "-m", "next")
    r = lib_repo.publish("v2.0.0", "--dry-run")
    assert r.returncode == 1 and "but the tag is v2.0.0 (2.0.0)" in r.stderr


# ---------------- AC-221.8: CI ----------------

def _workflow(repo: Path) -> dict:
    return yaml.safe_load((repo / ".github" / "workflows" / "ci.yml").read_text())


def test_ci_has_the_library_job_set_and_the_publish_job_ac_221_8(default):  # AC-221.8
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
    assert pub["permissions"] == {"contents": "read", "packages": "write", "id-token": "write", "attestations": "write"}  # #966
    assert any(str(s.get("uses", "")).startswith("actions/attest-build-provenance@") for s in pub["steps"])
    assert [n for n, j in jobs.items() if "write" in (j.get("permissions") or {}).values()] == ["publish"]
    step = next(s for s in pub["steps"] if "devbox run publish" in str(s.get("run", "")))
    assert step["run"] == 'devbox run publish "$GITHUB_REF_NAME"'
    assert step["env"] == {"GH_TOKEN": "${{ secrets.GITHUB_TOKEN }}"}
    checkout = next(s for s in pub["steps"] if str(s.get("uses", "")).startswith("actions/checkout@"))
    assert checkout["with"]["fetch-depth"] == 0


# ---------------- AC-221.9: the consumer guide ----------------

def test_the_guide_says_how_the_package_is_released_and_used_ac_221_9(default):  # AC-221.9
    text_ = (default / "CLAUDE.md").read_text()
    section = text_.split("## Releasing the package", 1)[1].split("\n## ", 1)[0]
    for needle in ("`publish` job", "devbox run publish vX.Y.Z", "`SharedUtils`", "https://nuget.pkg.github.com/acmeco/index.json",
                   "<packageSourceCredentials>", "read:packages", "PACKAGES_READ_TOKEN", '<PackageReference Include="SharedUtils" />',
                   '<PackageVersion Include="SharedUtils"'):
        assert needle in section, needle


# ---------------- AC-221.10: shape-wide tooling ----------------

def test_the_platform_tooling_knows_the_shape_ac_221_10():  # AC-221.10
    import buildtests
    import comprelease
    import deps_parse
    assert deps_parse.TOOLS[SHAPE] == "trivy" and deps_parse.DEP_FILES[SHAPE] == deps_parse.DEP_FILES["service-dotnet"]
    assert buildtests.TEST_FAST[SHAPE] == buildtests.TEST_FAST["service-dotnet"]
    assert comprelease.next_dev("v1.2.3", SHAPE, Path("/nonexistent")) is None   # the version comes from the tag
    for rel in ("scripts/bump_template_pins.py", "scripts/sync-template-copies.py", "scripts/template-lint.py",
                "scripts/ci-local.sh", "templates/gitops-app/scripts/plan.py", ".github/dependabot.yml"):
        assert SHAPE in (ROOT / rel).read_text(), rel
    for rel in ("templates/gitops-app/scripts/render.py", "templates/cluster-gitops/scripts/system_render.py"):
        assert '("library", "csharp")' in (ROOT / rel).read_text(), rel


def test_the_copies_are_kept_in_sync_ac_221_10():  # AC-221.10
    import importlib.util
    spec = importlib.util.spec_from_file_location("sync_copies", ROOT / "scripts" / "sync-template-copies.py")
    sync = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sync)
    copies = {str(c.relative_to(ROOT)) for _, c in sync.COPIES}
    assert {f"templates/{SHAPE}/scripts/{n}" for n in ("gate.sh", "deps.sh")} <= copies


def test_the_release_agent_keeps_the_tag_as_the_library_version_ac_221_10():  # AC-221.10
    """The orchestrator passes VERSION_FILE none for the shape; the agent's version step names the library case."""
    agent = (ROOT / "plugins" / "svc-dotnet" / "agents" / "release.md").read_text()
    step = agent.split("### 3.", 1)[1].split("\n### ", 1)[0]
    assert "library" in step and "0.0.0-dev" in step


def test_the_template_enables_the_plugins_ac_221_10():  # AC-221.10
    text_ = (TEMPLATE / ".claude" / "settings.json.jinja").read_text()
    for p in ("svc-dotnet", "svc", "shared"):
        assert f'"{p}@sdlc-foundry": true' in text_
    assert '"Read(~/.cache/sdlc-foundry/logs/**)",' in text_
    assert "docker" not in text_ and "kubectl" not in text_


def test_cplat_shape_routes_the_roles_of_a_rendered_repo_ac_221_10(default, capsys):  # AC-221.10
    assert cplat.main(["shape", "--repo", str(default)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["shape"] == SHAPE and out["library"] is True and out["deployable"] is False
    assert out["agents"]["coder"] == "svc-dotnet:coder" and out["agents"]["architect"] == "svc:architect"


def test_the_platform_ci_smoke_tests_the_template_ac_221_10():  # AC-221.10
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text())
    job = wf["jobs"]["smoke-test-library-dotnet"]
    assert job["if"] == "needs.changes.outputs.dotnetlib == 'true'"
    steps = " ".join(str(s.get("run", "")) for s in job["steps"])
    for needle in ("detect-shape.sh", 'template-lint.py" library-dotnet', '.shell.scripts["test"]', "publish.sh v1.2.3 --dry-run",
                   "git update-ref refs/tags/v1.2.3 HEAD", "but the tag is v1.2.3 (1.2.3)"):
        assert needle in steps, needle
    assert "smoke-test-library-dotnet" in wf["jobs"]["ci-success"]["needs"]
    lint = next(s["run"] for s in wf["jobs"]["validate-shapes"]["steps"] if "actionlint" in str(s.get("run", "")))
    assert SHAPE in lint


# ---------------- AC-221.11: docs ----------------

@pytest.mark.parametrize("rel", ["docs/templates.md", "site/src/content/docs/concepts/shapes.md", "docs/requirements/platform-vision.md",
                                 "CLAUDE.md", "plugins/svc-dotnet/README.md"])
def test_the_docs_name_the_shape_ac_221_11(rel):  # AC-221.11
    assert SHAPE in (ROOT / rel).read_text(), rel
