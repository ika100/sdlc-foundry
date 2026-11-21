"""Spec 215 acceptance tests: the library-typescript shape (an ESM npm package on GitHub Packages, ADR-125).

Seams: the registry and the cplat modules that name shapes, the template files and a rendered copy (copier, rendered once per
process), the real `detect-shape.sh`, `cplat component new` / `cplat shape` in-process, and the template's `scripts/publish.sh`
run for real in a git repo with real `node` and `tar` and a fake `pnpm` (builds dist/, packs package.json + dist) and `npm`
(edits the version, keeps the registry as files). Installing the packages, the Vitest coverage gate and a publish dry run on the
real toolchain are proved by the platform CI job `smoke-test-library-typescript`, which these tests check exists.
"""
import json
import os
import re
import shutil
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
TEMPLATE = ROOT / "templates" / "library-typescript"
SCRIPT = TEMPLATE / "scripts" / "publish.sh"
SHAPE = "library-typescript"
REGISTRY = "https://npm.pkg.github.com"


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
    return shared_renders.copy("215 shared-types", lambda workdir: _render(workdir / "shared-types"), tmp_path / "shared-types")


def recipes(repo: Path) -> dict:
    return json.loads((repo / "devbox.json").read_text())["shell"]["scripts"]


def package(repo: Path) -> dict:
    return json.loads((repo / "package.json").read_text())


# ---------------- AC-215.1: the registry ----------------

def test_the_registry_holds_the_library_shape_with_its_publish_block_ac_215_1():  # AC-215.1
    e = entry()
    assert (e["plugin"], e["template"], e["deployable"], e["library"]) == ("svc-ts", SHAPE, False, True)
    assert e["default_stack"]["language"] == "typescript" and "runtime" not in e
    assert e["publish"] == {"registry": "github-npm"}
    assert shapes.validate(shapes.load_all()) == []
    assert shapes.publish_errors(SHAPE, TEMPLATE, "github-npm") == []
    assert shapes.check_contract(shapes.load()) == []


def test_library_typescript_is_a_pair_and_a_lone_typescript_stays_a_website_ac_215_1():  # AC-215.1
    assert newsvc.shape_of_pair("library", "typescript") == SHAPE
    assert newsvc.shape_of_pair(None, "typescript") == "web-nextjs"
    assert newsvc.shape_of_pair("library", None) == "library-python"
    assert ("library", "typescript") in newsvc.valid_pairs()


# ---------------- AC-215.2: creation and detection ----------------

def test_component_new_renders_the_template_ac_215_2(tmp_path):  # AC-215.2
    rc = cplat.main(["component", "new", "shared-types", "Shared", "types", "--type", "library", "--lang", "typescript",
                     "--no-github", "--skip-tasks", "--org", "acme", "--dir", str(tmp_path)])
    assert rc == 0
    repo = tmp_path / "shared-types"
    assert re.search(r"^_src_path: .*templates/library-typescript$", (repo / ".copier-answers.yml").read_text(), re.M)
    assert (repo / "src" / "index.ts").is_file() and package(repo)["name"] == "@acme/shared-types"


def _detect(repo: Path) -> str:
    return subprocess.run(["bash", str(ROOT / "scripts" / "detect-shape.sh"), str(repo)], capture_output=True, text=True).stdout.strip()


@pytest.mark.parametrize("deps, files, expected", [
    ({"devDependencies": {"typescript": "~5.9.3"}}, [], SHAPE),
    ({"dependencies": {"fastify": "^5.0.0"}}, [], "service-typescript"),
    ({"dependencies": {"next": "16.0.0"}}, [], "web-nextjs"),
    ({"devDependencies": {"prettier": "3.0.0"}}, ["pyproject.toml"], "library-python"),
    ({"devDependencies": {"prettier": "3.0.0"}}, ["go.mod"], "service-go"),
])
def test_detection_by_sniffing_a_package_json_ac_215_2(tmp_path, deps, files, expected):  # AC-215.2
    (tmp_path / "package.json").write_text(json.dumps(deps))
    for f in files:
        (tmp_path / f).touch()
    assert _detect(tmp_path) == expected


def test_detection_by_answers_and_of_a_fresh_render_ac_215_2(tmp_path, default):  # AC-215.2
    (tmp_path / ".copier-answers.yml").write_text("_src_path: gh:ika100/sdlc-foundry/templates/library-typescript\n")
    assert _detect(tmp_path) == SHAPE
    assert _detect(default) == SHAPE


# ---------------- AC-215.3: recipes and gates ----------------

CANONICAL = ["lint", "lint-fix", "typecheck", "quality", "test", "test-fast", "security", "secrets-baseline", "ci", "build", "publish",
             "deps-findings", "deps-bump", "spec-check"]


def test_the_render_has_the_canonical_recipes_and_no_image_ac_215_3(default):  # AC-215.3
    r = recipes(default)
    assert [n for n in CANONICAL if n not in r] == []
    assert [n for n in ("smoke", "image-build", "image-scan", "dev", "start") if n in r] == []
    assert r["test"].startswith("bash scripts/gate.sh tests test vitest -- ")
    assert r["test-fast"].startswith("bash scripts/gate.sh tests test-fast vitest -- ")
    assert r["ci"].endswith("then devbox run ci-extra; fi") and "devbox run quality" in r["ci"] and "devbox run security" in r["ci"]
    assert r["publish"] == 'bash scripts/publish.sh "$@"'
    assert not (default / "Dockerfile").exists() and not (default / ".dockerignore").exists()
    assert "thresholds: { lines: 80, functions: 80, statements: 80 }" in (default / "vitest.config.mts").read_text()
    assert (default / "scripts" / "gate.sh").read_bytes() == (ROOT / "templates" / "gitops-app" / "scripts" / "gate.sh").read_bytes()


# ---------------- AC-215.4: the package ----------------

def test_the_package_is_a_scoped_esm_package_for_github_packages_ac_215_4(default):  # AC-215.4
    pkg = package(default)
    assert pkg["name"] == "@acmeco/shared-types"   # the npm scope is the owner, lowercased
    assert pkg["type"] == "module" and pkg["files"] == ["dist"]
    assert pkg["exports"] == {".": {"types": "./dist/index.d.ts", "import": "./dist/index.js"}}
    assert "require" not in json.dumps(pkg["exports"]) and "main" not in pkg
    assert pkg["publishConfig"] == {"registry": REGISTRY}
    assert pkg["repository"]["url"] == "git+https://github.com/AcmeCo/shared-types.git"
    build = json.loads((default / "tsconfig.build.json").read_text())["compilerOptions"]
    assert build["outDir"] == "dist" and build["declaration"] is True
    assert json.loads((default / "tsconfig.json").read_text())["compilerOptions"]["module"] == "NodeNext"


# ---------------- AC-215.5 / AC-215.6 / AC-215.7: the publish script ----------------

FAKE_PNPM = r"""#!/usr/bin/env bash
# fake pnpm: `build` writes dist/, `pack --pack-destination D` packs package.json + dist like pnpm names the tarball
set -euo pipefail
echo "pnpm $*" >> "$TOOL_LOG"
case "$1" in
  build) mkdir -p dist && echo 'export const x = 1;' > dist/index.js && echo 'export declare const x = 1;' > dist/index.d.ts ;;
  pack)
    dest="$3"
    name=$(node -p 'require("./package.json").name.replace("@", "").replace("/", "-")')
    version=$(node -p 'require("./package.json").version')
    stage=$(mktemp -d) && mkdir "$stage/package" && cp -r package.json dist "$stage/package/"
    mkdir -p "$dest" && tar -czf "$dest/$name-$version.tgz" -C "$stage" package ;;
  *) exit 2 ;;
esac
"""

FAKE_NPM = r"""#!/usr/bin/env bash
# fake npm: `pkg set version=V`, `view NAME@V version` (exit 0 when the registry state holds it), `publish TGZ` (stores it)
set -euo pipefail
echo "npm $*" >> "$TOOL_LOG"
case "$1" in
  pkg) node -e 'const f="package.json",p=JSON.parse(require("fs").readFileSync(f));p.version=process.argv[1];require("fs").writeFileSync(f,JSON.stringify(p,null,2)+"\n")' "${3#version=}" ;;
  view) [ -e "$NPM_STATE/$(echo "$2" | tr '/' '_')" ] ;;
  publish)
    grep -q '_authToken=${NODE_AUTH_TOKEN}' "$NPM_CONFIG_USERCONFIG"
    printf '%s\n' "token=$NODE_AUTH_TOKEN" >> "$TOOL_LOG"
    v=$(tar -xOzf "$2" package/package.json | node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{const p=JSON.parse(s);console.log(p.name+"@"+p.version)})')
    mkdir -p "$NPM_STATE" && cp "$2" "$NPM_STATE/$(echo "$v" | tr '/' '_')" ;;
  *) exit 2 ;;
esac
"""

needs_node = pytest.mark.skipif(not shutil.which("node"), reason="needs node")


@pytest.fixture
def lib_repo(tmp_path):
    repo = tmp_path / "shared-types"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, repo / "scripts" / "publish.sh")
    (repo / "package.json").write_text(json.dumps({"name": "@acme/shared-types", "version": "0.0.0-dev.0", "type": "module",
                                                   "files": ["dist"]}, indent=2) + "\n")
    (repo / ".gitignore").write_text("dist/\n.pack/\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("pnpm", FAKE_PNPM), ("npm", FAKE_NPM)):
        p = bin_dir / name
        p.write_text(with_prelude(body))
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "TOOL_LOG": str(tmp_path / "tools.log"),
           "NPM_STATE": str(tmp_path / "registry"), "NODE_AUTH_TOKEN": "tok-123", "GIT_AUTHOR_NAME": "t",
           "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    env.pop("NPM_CONFIG_USERCONFIG", None)

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
        def published():
            return sorted(p.name for p in Repo.registry.iterdir()) if Repo.registry.exists() else []

    return Repo


def packed_version(tgz: Path) -> str:
    out = subprocess.run(["tar", "-xOzf", str(tgz), "package/package.json"], capture_output=True, text=True, check=True).stdout
    return json.loads(out)["version"]


def test_the_script_is_copied_by_copier_unchanged_ac_215_5():  # AC-215.5
    """Only *.jinja files are rendered, so the script reaches the repo byte for byte."""
    assert yaml.safe_load((TEMPLATE / "copier.yml").read_text())["_templates_suffix"] == ".jinja"
    assert SCRIPT.stat().st_mode & stat.S_IXUSR


@needs_node
def test_a_tagged_head_publishes_the_tag_version_and_keeps_package_json_ac_215_5(lib_repo):  # AC-215.5
    lib_repo.git("tag", "v1.2.3")
    r = lib_repo.publish("v1.2.3")
    assert r.returncode == 0, r.stderr
    assert f"publish: published @acme/shared-types@1.2.3 to {REGISTRY}" in r.stdout
    assert lib_repo.published() == ["@acme_shared-types@1.2.3"]
    assert packed_version(lib_repo.registry / "@acme_shared-types@1.2.3") == "1.2.3"
    assert "token=tok-123" in lib_repo.log.read_text()
    assert any(f"--registry {REGISTRY}" in c for c in lib_repo.calls("npm") if c.startswith("npm publish"))
    assert json.loads((lib_repo.path / "package.json").read_text())["version"] == "0.0.0-dev.0"
    assert subprocess.run(["git", "status", "--porcelain"], cwd=lib_repo.path, capture_output=True, text=True).stdout == ""


@needs_node
def test_a_rerun_of_a_published_version_is_a_no_op_ac_215_5(lib_repo):  # AC-215.5
    lib_repo.git("tag", "v1.2.3")
    assert lib_repo.publish("v1.2.3").returncode == 0
    r = lib_repo.publish("v1.2.3")
    assert r.returncode == 0, r.stderr
    assert "already in" in r.stdout and "nothing to do" in r.stdout
    assert len([c for c in lib_repo.calls("npm") if c.startswith("npm publish")]) == 1


@needs_node
@pytest.mark.parametrize("setup", ["tag-on-other-commit", "no-tag", "dirty"])
def test_a_commit_that_is_not_the_tagged_one_publishes_nothing_ac_215_6(lib_repo, setup):  # AC-215.6
    if setup == "tag-on-other-commit":
        lib_repo.git("tag", "v1.2.3")
        lib_repo.git("commit", "-q", "--allow-empty", "-m", "next")
    elif setup == "dirty":
        lib_repo.git("tag", "v1.2.3")
        (lib_repo.path / "extra.ts").write_text("x\n")
    r = lib_repo.publish("v1.2.3")
    assert r.returncode == 1
    assert "publish: the built version is 0.0.0-dev.0 but the tag is v1.2.3 (1.2.3)" in r.stderr
    assert re.search(r"^fix: ", r.stderr, re.M)
    assert lib_repo.calls("npm") == [] and lib_repo.calls("pnpm") == [] and lib_repo.published() == []


@pytest.mark.parametrize("args", [[], ["1.2.3"], ["v1.2.3", "--force"], ["v1.2.3", "--dry-run", "x"], ["latest"]])
def test_a_wrong_argument_list_exits_2_with_the_usage_ac_215_6(lib_repo, args):  # AC-215.6
    r = lib_repo.publish(*args)
    assert r.returncode == 2 and "usage: publish.sh vX.Y.Z [--dry-run]" in r.stderr


@needs_node
def test_a_dry_run_packs_and_checks_without_the_registry_ac_215_7(lib_repo):  # AC-215.7
    lib_repo.git("tag", "v2.0.0")
    r = lib_repo.publish("v2.0.0", "--dry-run", NODE_AUTH_TOKEN="")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == f"publish: would publish .pack/acme-shared-types-2.0.0.tgz as @acme/shared-types@2.0.0 to {REGISTRY}"
    assert packed_version(lib_repo.path / ".pack" / "acme-shared-types-2.0.0.tgz") == "2.0.0"
    assert [c for c in lib_repo.calls("npm") if not c.startswith("npm pkg ")] == [] and lib_repo.published() == []
    assert json.loads((lib_repo.path / "package.json").read_text())["version"] == "0.0.0-dev.0"


@needs_node
def test_a_dry_run_of_another_commit_fails_the_same_way_ac_215_7(lib_repo):  # AC-215.7
    lib_repo.git("tag", "v2.0.0")
    lib_repo.git("commit", "-q", "--allow-empty", "-m", "next")
    r = lib_repo.publish("v2.0.0", "--dry-run")
    assert r.returncode == 1 and "but the tag is v2.0.0 (2.0.0)" in r.stderr


# ---------------- AC-215.8: CI ----------------

def _workflow(repo: Path) -> dict:
    return yaml.safe_load((repo / ".github" / "workflows" / "ci.yml").read_text())


def test_ci_has_the_library_job_set_and_the_publish_job_ac_215_8(default):  # AC-215.8
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
    assert step["env"] == {"GH_TOKEN": "${{ secrets.GITHUB_TOKEN }}", "NODE_AUTH_TOKEN": "${{ secrets.GITHUB_TOKEN }}"}
    checkout = next(s for s in pub["steps"] if str(s.get("uses", "")).startswith("actions/checkout@"))
    assert checkout["with"]["fetch-depth"] == 0


# ---------------- AC-215.9: the consumer guide ----------------

def test_the_guide_says_how_the_package_is_released_and_installed_ac_215_9(default):  # AC-215.9
    text = (default / "CLAUDE.md").read_text()
    section = text.split("## Releasing the package", 1)[1].split("\n## ", 1)[0]
    for needle in ("`publish` job", "devbox run publish vX.Y.Z", "@acmeco/shared-types", REGISTRY,
                   "@acmeco:registry=https://npm.pkg.github.com", "read:packages", "PACKAGES_READ_TOKEN",
                   "pnpm add @acmeco/shared-types@X.Y.Z"):
        assert needle in section, needle
    assert "internal index" not in text


# ---------------- AC-215.10: shape-wide tooling ----------------

def test_the_platform_tooling_knows_the_shape_ac_215_10():  # AC-215.10
    import buildtests
    import comprelease
    import deps_parse
    assert deps_parse.TOOLS[SHAPE] == "pnpm-audit" and "pnpm-lock.yaml" in deps_parse.DEP_FILES[SHAPE]
    assert SHAPE in buildtests.TEST_FAST
    assert comprelease.next_dev("v1.2.3", SHAPE, Path("/nonexistent")) is None   # the version comes from the tag
    for rel in ("scripts/bump_template_pins.py", "scripts/sync-template-copies.py", "scripts/template-lint.py",
                "scripts/ci-local.sh", "templates/gitops-app/scripts/plan.py", ".github/dependabot.yml"):
        assert SHAPE in (ROOT / rel).read_text(), rel
    for rel in ("templates/gitops-app/scripts/render.py", "templates/cluster-gitops/scripts/system_render.py"):
        assert '("library", "typescript")' in (ROOT / rel).read_text(), rel


def test_the_template_enables_the_plugins_ac_215_10():  # AC-215.10
    text = (TEMPLATE / ".claude" / "settings.json.jinja").read_text()
    for p in ("svc-ts", "svc", "shared"):
        assert f'"{p}@sdlc-foundry": true' in text


def test_cplat_shape_routes_the_roles_of_a_rendered_repo_ac_215_10(default, capsys):  # AC-215.10
    assert cplat.main(["shape", "--repo", str(default)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["shape"] == SHAPE and out["library"] is True and out["deployable"] is False
    assert out["agents"]["coder"] == "svc-ts:coder" and out["agents"]["architect"] == "svc:architect"


def test_the_platform_ci_smoke_tests_the_template_ac_215_10():  # AC-215.10
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text())
    job = wf["jobs"]["smoke-test-library-typescript"]
    assert job["if"] == "needs.changes.outputs.tslib == 'true'"
    steps = " ".join(str(s.get("run", "")) for s in job["steps"])
    for needle in ("detect-shape.sh", 'template-lint.py" library-typescript', "test-fast", "publish.sh v1.2.3 --dry-run",
                   "git update-ref refs/tags/v1.2.3 HEAD", "but the tag is v1.2.3 (1.2.3)", "checked nothing: 0 tests ran"):
        assert needle in steps, needle
    assert "smoke-test-library-typescript" in wf["jobs"]["ci-success"]["needs"]
    lint = next(s["run"] for s in wf["jobs"]["validate-shapes"]["steps"] if "actionlint" in str(s.get("run", "")))
    assert SHAPE in lint


# ---------------- AC-215.11: docs ----------------

@pytest.mark.parametrize("rel", ["docs/templates.md", "site/src/content/docs/concepts/shapes.md", "docs/requirements/platform-vision.md",
                                 "CLAUDE.md", "plugins/svc-ts/README.md"])
def test_the_docs_name_the_shape_ac_215_11(rel):  # AC-215.11
    assert SHAPE in (ROOT / rel).read_text(), rel
