"""Spec 138 (#426): a component release tags the build staging tested (option b). `cplat component release target` decides the
commit to tag; the command tags it and writes the CHANGELOG and the next development version in a follow-up PR after the tag.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMMAND = ROOT / "plugins/component/commands/release.md"
AGENTS = {p: ROOT / f"plugins/{p}/agents/release.md" for p in ("svc", "svc-java", "svc-go", "web")}
LIB = ROOT / "templates/library-python"
SVC = ROOT / "templates/service-python"


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def commit(repo: Path, subject: str) -> str:
    (repo / (re.sub(r"\W+", "-", subject) + ".txt")).write_text(subject + "\n")   # one file per commit: merges never conflict
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", subject)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture()
def comp(tmp_path, monkeypatch):
    """A component clone with origin: v0.2.0 on the first commit, then feat/fix commits; staging pin and shape replaceable."""
    import comprelease
    origin, repo = tmp_path / "origin.git", tmp_path / "repo"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(repo)], check=True, capture_output=True)
    for k, v in (("user.name", "t"), ("user.email", "t@example.com"), ("commit.gpgsign", "false"), ("tag.gpgsign", "false")):
        git(repo, "config", k, v)
    (repo / "pyproject.toml").write_text('[project]\nname = "shop"\nversion = "0.2.1.dev0"\n')
    (repo / ".platform-app.yml").write_text("apps:\n  - acme/shop-gitops\n")
    shas = {"base": commit(repo, "chore: base")}
    git(repo, "tag", "-a", "v0.2.0", "-m", "Release v0.2.0")
    shas["feat"] = commit(repo, "feat: orders")
    shas["fix"] = commit(repo, "fix: totals")
    shas["after"] = commit(repo, "feat: coupons")
    git(repo, "push", "-q", "origin", "main", "--tags")
    state = {"shape": ("service-python", True), "pin": f"sha-{shas['fix']}"}
    monkeypatch.setattr(comprelease, "shape_of", lambda r: state["shape"])
    monkeypatch.setattr(comprelease, "staging_pin", lambda r, apps, service: state["pin"])
    return repo, shas, state


def run_target(repo: Path, *extra: str) -> tuple[int, str]:
    import comprelease
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = comprelease.main(["target", "--repo", str(repo), *extra])
    return code, buf.getvalue()


# ---------------- AC-138.1: the commit staging runs ----------------

def test_the_release_tags_the_commit_staging_runs_ac_138_1(comp):  # AC-138.1
    repo, shas, _ = comp
    code, out = run_target(repo, "--json")
    assert code == 0
    data = json.loads(out)
    assert data["ok"] is True and data["commit"] == shas["fix"] and data["source"] == "staging"
    assert data["staging"] == f"sha-{shas['fix']}" and data["main"] == shas["after"]


def test_the_version_comes_from_the_commits_up_to_the_staging_commit_ac_138_1(comp):  # AC-138.1
    repo, shas, state = comp
    state["pin"] = f"sha-{shas['fix']}"
    data = json.loads(run_target(repo, "--json")[1])
    assert data["previous"] == "v0.2.0" and data["version"] == "v0.3.0"
    assert data["subjects"] == ["feat: orders", "fix: totals"]


def test_a_fix_only_staging_commit_is_a_patch_even_if_main_has_a_feature_after_it_ac_138_1(comp):  # AC-138.1
    repo, shas, state = comp
    git(repo, "checkout", "-q", "-b", "side", "v0.2.0")
    fix = commit(repo, "fix: only")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "-m", "Merge fix", fix)
    after = commit(repo, "feat: later")
    git(repo, "push", "-q", "origin", "main")
    git(repo, "tag", "-a", "v0.2.9", "-m", "r", shas["after"])    # a later release, so the range starts there
    git(repo, "push", "-q", "origin", "v0.2.9")
    state["pin"] = f"sha-{git(repo, 'rev-parse', 'HEAD~1')}"           # the merge commit
    data = json.loads(run_target(repo, "--json")[1])
    assert data["version"] == "v0.2.10" and data["previous"] == "v0.2.9"
    assert data["after"] == ["feat: later"] and data["main"] == after


def test_commits_after_the_staging_commit_are_named_as_not_released_ac_138_1(comp):  # AC-138.1
    repo, shas, _ = comp
    code, out = run_target(repo)
    assert code == 0
    assert f"Tag: {shas['fix']}" in out and "the commit staging runs" in out and "spec 106" in out
    main = next(ln for ln in out.splitlines() if ln.startswith("Main:"))
    assert shas["after"] in main and "1 commit" in main and "not in this release" in main
    assert "feat: coupons" in out


def test_the_cli_routes_component_release_target():  # AC-138.1
    import cplat
    assert cplat.NOUNS["component"]["release"][0] == "comprelease"


# ---------------- AC-138.2: no staging environment ----------------

def test_a_library_releases_mains_head_and_says_why_ac_138_2(comp):  # AC-138.2
    repo, shas, state = comp
    state["shape"] = ("library-python", False)
    state["pin"] = None
    code, out = run_target(repo, "--json")
    data = json.loads(out)
    assert code == 0 and data["commit"] == shas["after"] and data["source"] == "main"
    assert "no staging" in data["why"] and "library" in data["why"]
    assert data["version"] == "v0.3.0" and data["subjects"] == ["feat: orders", "fix: totals", "feat: coupons"]


def test_a_service_not_linked_to_a_gitops_app_releases_mains_head_ac_138_2(comp):  # AC-138.2
    repo, shas, state = comp
    (repo / ".platform-app.yml").unlink()
    state["pin"] = None
    code, out = run_target(repo)
    assert code == 0 and f"Tag: {shas['after']}" in out
    assert "main's head" in out and "gitops-app" in out


def test_the_command_waits_for_mains_ci_run_on_the_tagged_commit_ac_138_2():  # AC-138.2
    text = COMMAND.read_text()
    tag = text[text.index("## Phase 5"):text.index("## Phase 6")]
    assert "cplat component release wait --commit <TAG_COMMIT>" in tag and "do not tag" in tag       # spec 143: a cplat wait
    assert tag.index("cplat component release wait --commit") < tag.index("git tag -a vX.Y.Z")
    assert "git tag -a vX.Y.Z <TAG_COMMIT>" in tag


# ---------------- AC-138.3: refusals ----------------

def _refused(repo: Path, shas: dict) -> str:
    tags = git(repo, "tag", "--list")
    code, out = run_target(repo)
    assert code == 1
    assert out.startswith("REFUSED: ")
    assert "Staging commit: " in out
    assert f"Candidate commit: {shas['after']} (main's head)" in out
    nxt = next(ln for ln in out.splitlines() if ln.startswith("Next: "))
    assert "/instance:promote" in nxt and f"--sha {shas['after']}" in nxt and "/instance:verify staging" in nxt
    assert "/component:release" in nxt
    assert git(repo, "tag", "--list") == tags                      # nothing changed
    return out


def test_no_staging_instance_refuses_ac_138_3(comp):  # AC-138.3
    repo, shas, state = comp
    state["pin"] = None
    out = _refused(repo, shas)
    assert "no staging instance" in out and "Staging commit: none" in out


def test_a_staging_pin_that_is_not_a_sha_build_refuses_ac_138_3(comp):  # AC-138.3
    repo, shas, state = comp
    state["pin"] = "0.2.0"
    out = _refused(repo, shas)
    assert "0.2.0" in out and "sha-<40>" in out


def test_a_staging_commit_not_on_main_refuses_ac_138_3(comp):  # AC-138.3
    repo, shas, state = comp
    git(repo, "checkout", "-q", "-b", "side")
    side = commit(repo, "feat: unmerged")
    git(repo, "push", "-q", "origin", "side")
    git(repo, "checkout", "-q", "main")
    state["pin"] = f"sha-{side}"
    out = _refused(repo, shas)
    assert side in out and "not on main" in out


def test_a_staging_commit_already_released_refuses_ac_138_3(comp):  # AC-138.3
    repo, shas, state = comp
    state["pin"] = f"sha-{shas['base']}"
    out = _refused(repo, shas)
    assert "already released as v0.2.0" in out


def test_only_release_follow_up_commits_since_the_tag_refuses_ac_138_3(comp):  # AC-138.3
    repo, shas, state = comp
    git(repo, "tag", "-a", "v0.3.0", "-m", "r", shas["after"])
    follow = commit(repo, "chore(release): v0.3.0 changelog and next development version")
    git(repo, "push", "-q", "origin", "main", "--tags")
    state["pin"] = f"sha-{follow}"
    shas = {**shas, "after": follow}
    out = _refused(repo, shas)
    assert "nothing new since v0.3.0" in out


def test_without_origin_main_it_refuses_ac_138_3(tmp_path, monkeypatch):  # AC-138.3
    import comprelease
    repo = tmp_path / "solo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    monkeypatch.setattr(comprelease, "shape_of", lambda r: ("service-go", True))
    code, out = run_target(repo, "--json")
    data = json.loads(out)
    assert code == 1 and data["ok"] is False and "origin/main" in data["reason"]


def test_the_command_stops_on_a_refusal_before_the_gates_ac_138_3():  # AC-138.3
    text = COMMAND.read_text()
    assert "cplat component release target" in text
    assert text.index("cplat component release target") < text.index("## Phase 2")
    phase1 = text[text.index("## Phase 1"):text.index("## Phase 2")]
    assert "REFUSED:" in phase1 and "stop" in phase1.lower()
    assert "git switch --detach" in text[text.index("## Phase 1"):text.index("## Phase 3")]


# ---------------- AC-138.4: the follow-up PR after the tag ----------------

@pytest.mark.parametrize("shape,files,expected", [
    ("service-python", {"pyproject.toml": '[project]\nname = "x"\nversion = "0.2.1.dev0"\n'}, ("pyproject.toml", "0.3.1.dev0")),
    ("library-python", {"pyproject.toml": '[project]\nname = "x"\nversion = "0.2.0"\n'}, ("pyproject.toml", "0.3.1.dev0")),
    ("library-python", {"pyproject.toml": '[project]\nname = "x"\ndynamic = ["version"]\n'}, None),
    ("service-java", {"pom.xml": "<project><version>0.2.1-SNAPSHOT</version></project>"}, ("pom.xml", "0.3.1-SNAPSHOT")),
    ("web-nextjs", {"package.json": '{"version": "0.2.1-dev.0"}'}, ("package.json", "0.3.1-dev.0")),
    ("service-go", {}, None),
])
def test_the_next_development_version_per_template_ac_138_4(tmp_path, shape, files, expected):  # AC-138.4
    import comprelease
    for name, body in files.items():
        (tmp_path / name).write_text(body)
    got = comprelease.next_dev("v0.3.0", shape, tmp_path)
    assert (None if got is None else (got["file"], got["next"])) == expected


def test_the_target_names_the_version_file_of_the_follow_up_ac_138_4(comp):  # AC-138.4
    repo, _, _ = comp
    data = json.loads(run_target(repo, "--json")[1])
    assert data["version_file"] == {"file": "pyproject.toml", "next": "0.3.1.dev0"}


def test_the_command_tags_before_the_follow_up_pr_and_merges_none_before_ac_138_4():  # AC-138.4
    text = COMMAND.read_text()
    before_tag = text[:text.index("git tag -a vX.Y.Z")]
    assert "gh pr merge" not in before_tag and "release agent" not in before_tag.split("## Phase 1", 1)[1].lower()
    follow = text[text.index("## Phase 6"):text.index("## Phase 7")]
    assert "release agent" in follow.lower() and "cplat pr wait" in follow and "--merge" in follow
    for key in ("VERSION", "PREVIOUS", "TAG_COMMIT", "VERSION_FILE", "NEXT_DEV"):
        assert key in follow
    assert "never tag" in follow.lower() or "not tagged" in follow.lower()


@pytest.mark.parametrize("plugin", sorted(AGENTS))
def test_every_release_agent_writes_the_follow_up_from_main_and_never_tags_ac_138_4(plugin):  # AC-138.4
    text = AGENTS[plugin].read_text()
    low = text.lower()
    assert "follow-up" in low and "after the tag" in low
    assert "git merge --ff-only origin/main" in text and "release/vX.Y.Z" in text
    assert 'git log "$PREVIOUS..$VERSION"' in text or "git log PREVIOUS..VERSION" in text
    assert "chore(release): vX.Y.Z changelog and next development version" in text
    assert "never create the git tag" in low or "never tag" in low
    assert "determine the next semantic version" not in low      # the version comes from cplat, not from the agent
    assert "NEXT_DEV" in text


def test_the_agents_set_the_next_development_version_of_their_template_ac_138_4():  # AC-138.4
    py, java, go, web = (AGENTS[p].read_text() for p in ("svc", "svc-java", "svc-go", "web"))
    assert ".dev0" in py and "devbox run -- uv lock" in py and "git add CHANGELOG.md pyproject.toml uv.lock" in py
    assert 'dynamic = ["version"]' in py                               # a library that reads its tag has no file
    assert "-SNAPSHOT" in java and "git add CHANGELOG.md pom.xml" in java
    assert "-dev.0" in web and "git add CHANGELOG.md package.json" in web
    assert "git add CHANGELOG.md\n" in go and "ldflags" in go


# ---------------- AC-138.5: a library reads its version from the tag ----------------

def test_the_library_template_reads_its_version_from_the_git_tag_ac_138_5():  # AC-138.5
    py = (LIB / "pyproject.toml").read_text()
    project = py.split("[project]", 1)[1].split("\n[", 1)[0]
    assert 'dynamic = ["version"]' in project and not re.search(r"^version\s*=", project, re.M)
    assert re.search(r'requires = \[[^\]]*"hatch-vcs[^"]*"', py)
    assert re.search(r'^\[tool\.hatch\.version\]\nsource = "vcs"', py, re.M)
    assert "fallback-version" in py and "cache-keys" in py
    init = (LIB / "src/{{ module_name }}/__init__.py").read_text()
    assert "importlib.metadata" in init and '"0.1.0"' not in init
    smoke = (LIB / "tests/test_smoke.py").read_text()
    assert '"0.1.0"' not in smoke and "version(" in smoke


# ---------------- AC-138.6: a Python service has one version ----------------

def test_the_service_template_reads_its_version_from_the_package_metadata_ac_138_6():  # AC-138.6
    init = (SVC / "src/{{ module_name }}/__init__.py").read_text()
    assert "from importlib.metadata import version" in init and '__version__ = version("{{ project_name }}")' in init
    main = (SVC / "src/{{ module_name }}/main.py").read_text()
    assert "version=__version__" in main and "from . import __version__" in main and '"0.1.0"' not in main
    assert re.search(r'^version = "0\.1\.0"$', (SVC / "pyproject.toml").read_text(), re.M)   # the one place


# ---------------- AC-138.7: the summary ----------------

def test_the_summary_names_the_tagged_commit_and_why_ac_138_7():  # AC-138.7
    text = COMMAND.read_text()
    summary = text[text.index("## Final Summary"):text.index("## Rules")]
    assert "<commit>" in summary and "the commit staging runs" in summary and "spec 106" in summary
    assert "main's head" in summary
    assert "previous development version" in summary and "follow-up PR" in summary
    head = text.split("---", 2)[1]
    assert "staging" in head and "follow-up" in head          # the description says what it tags


def test_the_target_output_explains_the_version_file_ac_138_7(comp):  # AC-138.7
    repo, _, _ = comp
    out = run_target(repo)[1]
    line = next(ln for ln in out.splitlines() if ln.startswith("Version file:"))
    assert "pyproject.toml" in line and "0.3.1.dev0" in line and "previous development version" in line
    assert "the release version is the tag" in line


def test_the_changelog_fragment_exists_ac_138_7():  # AC-138.7
    import release_support
    _, text = release_support.entry(r"\(#426\)")      # a fragment until the release moves it into its section (#321)
    assert "/component:release" in text
