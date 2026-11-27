"""Spec 104 (private packages): TypeScript image builds take PACKAGES_READ_TOKEN as a build secret (AC-104.11) and
`cplat platform doctor` reports the missing secret (AC-104.12). `ship.gh` is replaced; no GitHub call is made."""
import json
import re
import subprocess
from pathlib import Path

import pytest
import yaml

from changelog_support import changelog_entry

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "templates"
SHAPES = ["web-nextjs", "service-typescript"]
BUILD_STEPS = ("build-try", "build-retry")


def _dockerfile(shape: str) -> str:
    return (TEMPLATES / shape / "Dockerfile.jinja").read_text()


def _ci(shape: str) -> dict:
    return yaml.safe_load((TEMPLATES / shape / ".github" / "workflows" / "ci.yml").read_text())


def _code(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]


@pytest.mark.parametrize("shape", SHAPES)
def test_dockerfile_takes_the_token_as_a_build_secret_only(shape):  # AC-104.11
    """AC-104.11: syntax line 1, the deps COPY with .npmrc*, the one secret-mounted install, no ARG / fallback, runtime stage clean."""
    text = _dockerfile(shape)
    assert text.splitlines()[0] == "# syntax=docker/dockerfile:1.10"
    lines = _code(text)
    assert "COPY package.json pnpm-lock.yaml pnpm-workspace.yaml* .npmrc* ./" in lines
    installs = [ln for ln in lines if "pnpm install" in ln]
    assert installs == ["RUN --mount=type=secret,id=PACKAGES_READ_TOKEN,env=NODE_AUTH_TOKEN pnpm install --frozen-lockfile"]
    for ln in lines:
        if "PACKAGES_READ_TOKEN" in ln or "NODE_AUTH_TOKEN" in ln:
            assert not ln.startswith("ARG") and "--build-arg" not in ln and "||" not in ln and "2>/dev/null" not in ln, ln
    runtime = "\n".join(_code(text[text.index("AS runtime"):]))
    for banned in ("PACKAGES_READ_TOKEN", "NODE_AUTH_TOKEN", ".npmrc"):
        assert banned not in runtime, banned


@pytest.mark.parametrize("shape", SHAPES)
def test_ci_docker_job_passes_the_token_as_a_secret_env(shape):  # AC-104.11
    """AC-104.11: build-try and build-retry pass PACKAGES_READ_TOKEN through secret-envs, never build-args or `secrets:`."""
    steps = {s.get("id") or s.get("name"): s for s in _ci(shape)["jobs"]["docker"]["steps"]}
    for name in BUILD_STEPS:
        step = steps[name]
        assert step.get("env", {}).get("PACKAGES_READ_TOKEN") == "${{ secrets.PACKAGES_READ_TOKEN }}"
        assert step["with"].get("secret-envs") =="PACKAGES_READ_TOKEN=PACKAGES_READ_TOKEN"
        assert "secrets" not in step["with"]
        assert "PACKAGES_READ_TOKEN" not in str(step["with"].get("build-args", ""))


@pytest.mark.parametrize("shape", SHAPES)
def test_ci_install_steps_get_node_auth_token_and_no_global_env(shape):  # AC-104.11
    """AC-104.11: `devbox run install` in the four jobs carries NODE_AUTH_TOKEN; no workflow- or job-level env has the token."""
    ci = _ci(shape)
    assert "PACKAGES_READ_TOKEN" not in str(ci.get("env", "")) and "NODE_AUTH_TOKEN" not in str(ci.get("env", ""))
    for job in ("quality", "test", "security", "ci-extra"):
        body = ci["jobs"][job]
        assert "PACKAGES_READ_TOKEN" not in str(body.get("env", "")) and "NODE_AUTH_TOKEN" not in str(body.get("env", "")), job
        installs = [s for s in body["steps"] if s.get("run") == "devbox run install"]
        assert installs, job
        for s in installs:
            assert s.get("env", {}).get("NODE_AUTH_TOKEN") == "${{ secrets.PACKAGES_READ_TOKEN }}", job


def test_the_two_ci_files_stay_identical():  # AC-104.11
    """AC-104.11: the web-nextjs and service-typescript ci.yml carry the same token wiring."""
    a, b = (TEMPLATES / s / ".github" / "workflows" / "ci.yml" for s in SHAPES)
    assert a.read_text() == b.read_text()


@pytest.mark.parametrize("shape", SHAPES)
def test_local_image_build_passes_the_secret(shape):  # AC-104.11
    """AC-104.11: the devbox image-build script (the scan build) passes the secret from NODE_AUTH_TOKEN."""
    text = (TEMPLATES / shape / "devbox.json.jinja").read_text()
    assert '"image-build": "docker build --secret id=PACKAGES_READ_TOKEN,env=NODE_AUTH_TOKEN -t {{ project_name }}:scan ."' in text


def test_platform_ci_proves_the_token_leaves_no_trace():  # AC-104.11
    """AC-104.11: the platform smoke jobs rebuild with a marker secret and search history, inspect and export for it."""
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    web = text.split("  smoke-test-web-nextjs:", 1)[1].split("\n  smoke-test-", 1)[0]
    ts = text.split("  smoke-test-service-typescript:", 1)[1].split("\n  smoke-test-", 1)[0]
    for job in (web, ts):
        assert "docker build --secret id=PACKAGES_READ_TOKEN,env=MARKER" in job
        for probe in ("docker history --no-trunc", "docker image inspect", "docker export"):
            assert probe in job, probe
    assert "Strict install rejects a stale lock" in ts and "ERR_PNPM_OUTDATED_LOCKFILE" in ts


def test_a_changelog_entry_names_the_token():  # AC-104.11
    """AC-104.11: the change is in the changelog."""
    assert changelog_entry(re.compile(r"PACKAGES_READ_TOKEN.*(build secret|private).*specs/104-", re.S))


# ---- AC-104.12: doctor ----

SLUG = "acme/shop-api"


def _repo(tmp_path, npmrc=None, pyproject=None):
    r = tmp_path / "shop-api"
    r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True)
    subprocess.run(["git", "remote", "add", "origin", f"https://github.com/{SLUG}.git"], cwd=r, check=True)
    if npmrc is not None:
        (r / ".npmrc").write_text(npmrc)
    if pyproject is not None:
        (r / "pyproject.toml").write_text(pyproject)
    return r


def _stub(monkeypatch, *, secrets=(), private=None, gh_installed=True):
    """Replace ship.gh: `secret list` returns `secrets` (None: unreadable); `api repos/<o>/<r> --jq .private` answers from `private`."""
    import doctor
    import ship
    calls = []

    def fake(args, *, cwd, check=True):
        calls.append(args)
        if args[:2] == ["secret", "list"]:
            if secrets is None:
                raise RuntimeError("no access")
            return json.dumps([{"name": n} for n in secrets])
        if args[0] == "api" and args[1].endswith("/actions/organization-secrets"):
            return "[]"
        if args[0] == "api" and args[2:] == ["--jq", ".private"]:
            slug = args[1].removeprefix("repos/")
            if private is None or slug not in private:
                raise RuntimeError("404")
            return "true\n" if private[slug] else "false\n"
        return ""

    monkeypatch.setattr(ship, "gh", fake)
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/usr/bin/gh" if gh_installed else None)
    return calls


NPMRC = "@acme:registry=https://npm.pkg.github.com\n"
WHEEL = 'dep = "https://github.com/acme/lib/releases/download/v1/lib-1-py3-none-any.whl"\n'


def test_a_missing_token_with_a_private_npm_scope_fails_with_the_fix(tmp_path, monkeypatch):  # AC-104.12
    """AC-104.12: FAIL names the source and gives the command that sets the secret."""
    import doctor
    import doctor_packages
    r = _repo(tmp_path, npmrc="# c\n; c\n@Acme:registry = https://npm.pkg.github.com/\n")
    _stub(monkeypatch)
    (c,) = doctor_packages.check_packages_token(r)
    assert c["status"] == doctor.FAIL
    assert c["name"] == "secret PACKAGES_READ_TOKEN"
    assert c["detail"] == "not set: CI and the image build cannot install @acme packages from npm.pkg.github.com"
    assert c["fix"] == ("create a token that can read packages (classic token, read:packages), then: "
                        f"gh secret set PACKAGES_READ_TOKEN -R {SLUG}")


def test_a_set_token_is_ok(tmp_path, monkeypatch):  # AC-104.12
    """AC-104.12: with the secret set the row is OK and names what it reads."""
    import doctor
    import doctor_packages
    r = _repo(tmp_path, npmrc=NPMRC)
    _stub(monkeypatch, secrets=["PACKAGES_READ_TOKEN"])
    (c,) = doctor_packages.check_packages_token(r)
    assert c["status"] == doctor.OK
    assert c["detail"] == "set: CI and the image build can read @acme packages from npm.pkg.github.com"


def test_an_unreadable_secret_list_warns(tmp_path, monkeypatch):  # AC-104.12
    """AC-104.12: a list that cannot be read is WARN with the same command."""
    import doctor
    import doctor_packages
    r = _repo(tmp_path, npmrc=NPMRC)
    _stub(monkeypatch, secrets=None)
    (c,) = doctor_packages.check_packages_token(r)
    assert c["status"] == doctor.WARN and c["detail"] == "could not be read with this gh login"
    assert f"gh secret set PACKAGES_READ_TOKEN -R {SLUG}" in c["fix"]


def test_a_private_release_asset_wheel_triggers_the_python_case(tmp_path, monkeypatch):  # AC-104.12
    """AC-104.12: a pyproject URL into a private repo's release assets; a public repo adds nothing; one source per distinct repo."""
    import doctor
    import doctor_packages
    py = WHEEL + WHEEL.replace("v1", "v2") + 'pub = "https://github.com/acme/open/releases/download/v1/x.whl"\n'
    r = _repo(tmp_path, pyproject=py)
    _stub(monkeypatch, private={"acme/lib": True, "acme/open": False})
    assert doctor_packages.private_package_sources(r, "acme") == ["wheels of acme/lib (private release assets)"]
    (c,) = doctor_packages.check_packages_token(r)
    assert c["status"] == doctor.FAIL
    assert c["detail"] == "not set: CI and the image build cannot install wheels of acme/lib (private release assets)"
    assert c["fix"] == ("create a token that can read acme/lib (fine-grained: Contents read), then: "
                        f"gh secret set PACKAGES_READ_TOKEN -R {SLUG}")


def test_an_unreadable_repo_visibility_counts_as_private(tmp_path, monkeypatch):  # AC-104.12
    """AC-104.12: when `gh api` fails the repo is treated as private."""
    import doctor_packages
    r = _repo(tmp_path, pyproject=WHEEL)
    _stub(monkeypatch, private=None)
    assert doctor_packages.private_package_sources(r, "acme") == ["wheels of acme/lib (private release assets)"]


def test_both_sources_are_joined_and_fixed_together(tmp_path, monkeypatch):  # AC-104.12
    """AC-104.12: npm and Python sources joined with `, `; the fix joins both token kinds with ` and `."""
    import doctor_packages
    r = _repo(tmp_path, npmrc=NPMRC, pyproject=WHEEL)
    _stub(monkeypatch, private={"acme/lib": True})
    (c,) = doctor_packages.check_packages_token(r)
    assert ("@acme packages from npm.pkg.github.com, wheels of acme/lib (private release assets)") in c["detail"]
    assert ("packages (classic token, read:packages) and acme/lib (fine-grained: Contents read)") in c["fix"]


@pytest.mark.parametrize("npmrc", [None, "@other:registry=https://npm.pkg.github.com\n", "# @acme:registry=https://npm.pkg.github.com\n",
                                   "@acme:registry=https://registry.npmjs.org\n"])
def test_a_repo_without_private_deps_gets_no_line(tmp_path, monkeypatch, npmrc):  # AC-104.12
    """AC-104.12: no trigger (another owner's scope, a comment, another registry, no .npmrc): no row."""
    import doctor_packages
    r = _repo(tmp_path, npmrc=npmrc)
    _stub(monkeypatch)
    assert doctor_packages.private_package_sources(r, "acme") == []
    assert doctor_packages.check_packages_token(r) == []


def test_no_row_when_gh_is_not_installed(tmp_path, monkeypatch):  # AC-104.12
    """AC-104.12: without gh there is nothing to check."""
    import doctor_packages
    r = _repo(tmp_path, npmrc=NPMRC)
    _stub(monkeypatch, gh_installed=False)
    assert doctor_packages.check_packages_token(r) == []


def test_run_checks_runs_the_packages_check_after_the_gitops_token(tmp_path, monkeypatch):  # AC-104.12
    """AC-104.12: doctor.run_checks calls check_packages_token right after check_gitops_token."""
    import inspect

    import doctor
    src = inspect.getsource(doctor.run_checks)
    assert "check_packages_token" in src
    assert src.index("check_gitops_token") < src.index("check_packages_token")
