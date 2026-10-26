"""Spec 123 acceptance tests: the platform repo declares its own shape (AC-123.1 .. AC-123.23).

Contract: docs/specs/123-.../design.md. A repo says `shape: platform` in its committed `.platform-settings.yml`; the registry
gets a template-less entry that only shape resolution, routing and `cplat spec` see (`shapes.load_all()` / `get()`).
Commands run in-process (`cplat.main`) on temporary git repos with XDG_CONFIG_HOME pointed at a temporary directory; GitHub is
faked (test_ship.FakeGh, a fake `fleet.gh`). New functions are looked up with `need()`, so each test fails on its own while the
behaviour is missing and never breaks collection."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

import core
import cplat
import doctor
import fleet
import runs
import settings
import ship
import spec
import update
from system_fixtures import files, git, init_git
from test_runs import buffered_lines
from test_ship import check, gh, to_land  # noqa: F401  (fixture gh)
from test_spec import make

import shapes  # noqa: E402  (scripts/shapes.py, on sys.path through core)

ROOT = core.PLATFORM_ROOT
SETTINGS = ".platform-settings.yml"
PLATFORM = "shape: platform\n"
ORDER = ["coder", "tester", "product-manager", "architect", "reviewer", "quality", "security"]
CMDS = ROOT / "plugins" / "component" / "commands"
DECL_SENTENCE = ("A `cplat shape` error that names `.platform-settings.yml` (an invalid shape declaration) → stop and show it; "
                 "never ask for the shape.")


def need(mod, name):
    """The design's new function, or a clear failure of this test (not of the whole file)."""
    got = getattr(mod, name, None)
    assert got is not None, f"{mod.__name__}.{name} does not exist yet (design.md)"
    return got


def text(path: Path) -> str:
    return path.read_text()


@pytest.fixture(autouse=True)
def xdg(tmp_path, monkeypatch):
    d = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(d))
    monkeypatch.delenv("CPLAT_KUBE_CONTEXT", raising=False)
    return d


def user_settings(xdg: Path, body: str) -> None:
    f = xdg / "sdlc-foundry" / "settings.yml"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(body)


def mkrepo(tmp_path: Path, body: str | None = PLATFORM, name: str = "sdlc-foundry") -> Path:
    r = tmp_path / name
    r.mkdir()
    (r / "README.md").write_text("# platform\n")
    if body is not None:
        (r / SETTINGS).write_text(body)
    return init_git(r)


def cp(capsys, *argv):
    capsys.readouterr()
    rc = cplat.main([str(a) for a in argv])
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def registered() -> dict:
    """The platform entry of the registry (fails until `platform` is registered)."""
    entry = need(shapes, "get")("platform")
    assert entry is not None, "shapes.yml has no `platform` entry"
    return entry


@pytest.fixture()
def prepo(tmp_path):
    """A platform repo with an approved spec 007 whose front matter says `shape: platform`, remote origin set."""
    r = mkrepo(tmp_path, PLATFORM, "sdlc-foundry")
    make(r, status="approved")
    for f in (r / "docs" / "specs" / "007-price-alerts").glob("*.md"):
        f.write_text(f.read_text().replace("shape: service-python", "shape: platform"))
    git(r, "add", "-A")
    git(r, "commit", "-qm", "spec")
    git(r, "remote", "add", "origin", "https://github.com/acme/sdlc-foundry.git")
    return r


# ---------------- declaring and resolving the shape ----------------

def test_ac_123_1_declared_platform_resolves_with_its_routing(tmp_path, capsys):  # AC-123.1
    r = mkrepo(tmp_path)
    rc, out, err = cp(capsys, "shape", "--repo", r)
    assert rc == 0, err
    doc = json.loads(out)
    assert list(doc) == ["shape", "plugin", "deployable", "library", "agents"]
    assert (doc["shape"], doc["plugin"], doc["deployable"], doc["library"]) == ("platform", "svc", False, False)
    assert list(doc["agents"]) == ORDER
    assert doc["agents"] == {"coder": "svc:coder", "tester": "svc:tester", "product-manager": "svc:product-manager",
                             "architect": "svc:architect", "reviewer": "svc:reviewer", "quality": "shared:quality",
                             "security": "shared:security"}
    assert "unsupported" not in doc
    assert not {"deployment", "observability", "migrations", "release"} & set(doc["agents"])


def test_ac_123_1_the_platform_entry_is_registered_without_a_template():  # AC-123.1
    e = registered()
    assert (e["plugin"], e["template"], e["deployable"], e["library"]) == ("svc", None, False, False)
    assert e["detection"] == {"declared": SETTINGS}
    assert need(shapes, "declared_ids")() == ["platform"]
    assert "platform" in [s["id"] for s in need(shapes, "load_all")()]


def test_ac_123_2_without_a_shape_key_the_platform_repo_stays_unresolved(tmp_path, capsys):  # AC-123.2
    registered()                                  # the entry exists, and still nothing recognises the repo from its files
    r = mkrepo(tmp_path, "coordinator_model: opus\n")
    (r / "shapes.yml").write_text("shapes: []\n")
    (r / "plugins").mkdir()
    rc, out, err = cp(capsys, "shape", "--repo", r)
    assert rc == 1 and out == "" and "cannot determine the repo's shape" in err
    assert need(settings, "declared_shape")(r) is None


def test_ac_123_2_no_settings_file_at_all_is_unresolved_too(tmp_path, capsys):  # AC-123.2
    registered()
    rc, _, err = cp(capsys, "shape", "--repo", mkrepo(tmp_path, None))
    assert rc == 1 and "cannot determine the repo's shape" in err


@pytest.mark.parametrize("argv", [["shape", "--repo", "{r}"], ["spec", "--repo", "{r}", "new", "A title"],
                                  ["component", "ship", "--repo", "{r}", "start", "7"]])
def test_ac_123_3_an_unknown_shape_fails_before_anything_happens(tmp_path, capsys, argv):  # AC-123.3
    r = mkrepo(tmp_path, "shape: platfrom\n")
    make(r, status="approved")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "spec")
    before = files(r)
    full = [str(r) if a == "{r}" else a for a in argv]
    rc, _, err = cp(capsys, *full)
    assert rc == 1
    assert ".platform-settings.yml" in err and "platfrom" in err
    assert "the shapes that can be declared are: platform" in err
    assert "cannot determine" not in err
    assert files(r) == before                      # no spec created, no claim, no state
    assert not ship.state_path(r).exists()


def test_ac_123_3_declared_shape_raises_a_declaration_error(tmp_path):  # AC-123.3
    r = mkrepo(tmp_path, "shape: 42\n")
    err = need(settings, "ShapeDeclarationError")
    with pytest.raises(err, match=r"unknown shape '42'"):
        settings.declared_shape(r)


@pytest.mark.parametrize("value", ["service-python", "service-go", "library-python"])
def test_ac_123_4_a_component_shape_cannot_be_declared(tmp_path, capsys, value):  # AC-123.4
    r = mkrepo(tmp_path, f"shape: {value}\n")
    before = files(r)
    for argv in (["shape", "--repo", r], ["spec", "--repo", r, "new", "A title"]):
        rc, _, err = cp(capsys, *argv)
        assert rc == 1
        assert f"shape '{value}' cannot be declared: only 'platform' can be declared" in err
        assert "a component repo's shape comes from its .copier-answers.yml" in err
        assert f"cplat adopt --type {value}" in err
    assert files(r) == before


@pytest.mark.parametrize("argv", [["shape"], ["spec", "new", "A title"]])
def test_ac_123_5_two_sources_conflict_and_nothing_changes(tmp_path, capsys, argv):  # AC-123.5
    r = mkrepo(tmp_path)
    (r / ".copier-answers.yml").write_text("_src_path: gh:ika100/sdlc-foundry/templates/service-go\nproject_name: x\n")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "answers")
    before = files(r)
    rc, out, err = cp(capsys, argv[0], "--repo", r, *argv[1:])
    assert rc == 1 and out == ""
    assert "conflicting shape sources" in err and ".platform-settings.yml" in err and ".copier-answers.yml" in err
    assert "templates/service-go" in err
    assert files(r) == before and git(r, "status", "--porcelain") == ""


def test_ac_123_5_answers_naming_no_platform_template_do_not_conflict(tmp_path, capsys):  # AC-123.5
    r = mkrepo(tmp_path)
    (r / ".copier-answers.yml").write_text("_src_path: gh:other/stuff/templates/not-ours\n")
    rc, out, err = cp(capsys, "shape", "--repo", r)
    assert rc == 0, err
    assert json.loads(out)["shape"] == "platform"


@pytest.mark.parametrize("argv", [["shape"], ["spec", "new", "A title"]])
def test_ac_123_6_shape_in_the_personal_file_is_refused(tmp_path, capsys, xdg, argv):  # AC-123.6
    user_settings(xdg, "shape: platform\n")
    r = mkrepo(tmp_path, None)
    before = files(r)
    rc, out, err = cp(capsys, argv[0], "--repo", r, *argv[1:])
    assert rc == 1 and out == ""
    assert "belongs in the repo's committed .platform-settings.yml" in err
    assert "settings.yml" in err and "personal settings file" in err
    assert files(r) == before


def test_ac_123_6_any_personal_shape_value_is_refused(tmp_path, xdg):  # AC-123.6
    user_settings(xdg, "shape: whatever\n")
    with pytest.raises(need(settings, "ShapeDeclarationError"), match="belongs in the repo's committed"):
        settings.declared_shape(mkrepo(tmp_path, PLATFORM))


def test_ac_123_7_the_shape_key_changes_no_other_setting(tmp_path, xdg):  # AC-123.7
    body = ("coordinator_model: opus\nbudget: {minutes: 30, cost: off}\nkube_context: kind-dev\nvalidation: full\n")
    plain = mkrepo(tmp_path, body, "plain")
    declared = mkrepo(tmp_path, body + "shape: platform\n", "declared")
    assert need(settings, "declared_shape")(declared) == "platform" and settings.declared_shape(plain) is None
    for fn in (lambda r: settings.coordinator_model(r, "/component:build x", None), settings.kube_context, settings.budget_defaults):
        assert fn(declared) == fn(plain)
    import validate
    assert validate.settings_full(declared) == validate.settings_full(plain) == "validation: full in .platform-settings.yml"
    assert settings.coordinator_model(declared, "/x", None) == ("opus", "project")
    assert settings.budget_defaults(declared) == {"minutes": 30, "cost": None}


def test_ac_123_7_a_settings_file_without_shape_changes_nothing(tmp_path):  # AC-123.7
    r = mkrepo(tmp_path, "coordinator_model: haiku\n")
    assert need(settings, "declared_shape")(r) is None
    assert settings.coordinator_model(r, "/x", None) == ("haiku", "project")


def test_ac_123_8_the_platform_repo_commits_its_declaration(capsys):  # AC-123.8
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", SETTINGS], cwd=ROOT, capture_output=True, text=True)
    assert tracked.returncode == 0, f"{SETTINGS} is not committed in the platform repo"
    assert yaml.safe_load(text(ROOT / SETTINGS)) == {"shape": "platform"}
    ignored = subprocess.run(["git", "check-ignore", "-q", SETTINGS], cwd=ROOT)
    assert ignored.returncode == 1
    rc, out, err = cp(capsys, "shape", "--repo", ROOT)
    assert rc == 0, err
    assert json.loads(out)["shape"] == "platform"


# ---------------- the shape is never offered elsewhere ----------------

def test_ac_123_9_platform_is_registered_but_never_offered_for_creation():  # AC-123.9
    registered()
    import model
    assert "platform" not in [s["id"] for s in shapes.load()]
    assert not any("platform" in pair for pair in model.TYPE_LANGS)
    for cmd in (ROOT / "plugins" / "component" / "commands" / "new.md", ROOT / "plugins" / "system" / "commands" / "new.md"):
        assert not re.search(r"platform/(python|go|java|typescript)|shape:\s*platform|--type platform", text(cmd))


def test_ac_123_9_adopt_type_platform_lists_the_valid_shapes_without_it(tmp_path, capsys):  # AC-123.9
    registered()
    r = mkrepo(tmp_path)
    rc, _, err = cp(capsys, "adopt", "--type", "platform", "--repo", r, "--dry-run")
    assert rc == 1 and "unknown shape 'platform'" in err
    listed = [t.strip(",") for t in err.split("one of:", 1)[1].split()]
    assert "service-python" in listed and "gitops-app" in listed
    assert "platform" not in listed


def test_ac_123_10_the_registry_check_passes_with_platform_registered(capsys):  # AC-123.10
    registered()
    assert shapes.main(["validate"]) == 0
    assert shapes.main(["check"]) == 0, capsys.readouterr().err
    capsys.readouterr()
    shapes.main(["ids"])
    assert "platform" not in capsys.readouterr().out.split()


def good_platform() -> dict:
    return {"id": "platform", "plugin": "svc", "template": None, "deployable": False, "library": False,
            "detection": {"declared": SETTINGS}, "status": "stable", "adr": [55]}


def test_ac_123_10_a_declared_entry_validates_without_template_or_sniff_rule():  # AC-123.10
    assert shapes.validate([good_platform()]) == []
    assert shapes.check_files([good_platform()]) == []
    assert shapes.check_contract([good_platform()]) == []


@pytest.mark.parametrize("change, message", [
    ({"detection": {"declared": "other.yml"}}, "platform: detection.declared must be .platform-settings.yml (ADR-056)"),
    ({"detection": {"declared": SETTINGS, "sniff": ["x"]}}, "platform: a declared shape has no copier_src or sniff rule (ADR-056)"),
    ({"template": "service-go"}, "platform: a declared shape has no template (template: null, ADR-056)"),
    ({"deployable": True}, "platform: a declared shape is neither deployable nor a library (ADR-056)"),
    ({"library": True}, "platform: a declared shape is neither deployable nor a library (ADR-056)"),
    ({"smoke_tag": "x"}, "platform: a declared shape has no smoke_tag (ADR-056)"),
    ({"runtime": {"port": 1}}, "platform: a declared shape has no runtime (ADR-056)"),
])
def test_ac_123_10_a_malformed_declared_entry_fails(change, message):  # AC-123.10
    assert message in shapes.validate([{**good_platform(), **change}])


def test_ac_123_10_other_shapes_still_need_template_plugin_and_detection():  # AC-123.10
    registered()
    go = next(s for s in shapes.load() if s["id"] == "service-go")
    assert not [e for e in shapes.validate([go]) if "template missing" in e]
    errs = shapes.validate([{**go, "template": None}])
    assert "service-go: template missing: only a shape declared in .platform-settings.yml has none (ADR-056)" in errs
    assert any("detection" in e for e in shapes.validate([{k: v for k, v in go.items() if k != "detection"}]))
    assert any("plugins/nope/ missing" in e for e in shapes.check_files([{**go, "plugin": "nope"}]))
    assert any("plugins/nope/ missing" in e for e in shapes.check_files([{**good_platform(), "plugin": "nope"}]))


@pytest.mark.parametrize("extra", [[], ["--dry-run"], ["--migrate"]])
def test_ac_123_11_platform_update_refuses_the_platform_repo(tmp_path, capsys, extra):  # AC-123.11
    r = mkrepo(tmp_path)
    before = files(r)
    rc, out, err = cp(capsys, "platform", "update", "--repo", r, *extra)
    assert rc == 1
    assert "the platform repo is not updated from a template" in err
    assert files(r) == before and git(r, "status", "--porcelain") == ""
    assert git(r, "branch", "--show-current") == "main"


class FakeFleetGh:
    def __init__(self, platform_repo: str):
        self.slug = platform_repo
        self.calls, self.unexpected, self.clones = [], [], []

    def entry(self):
        return {"nameWithOwner": self.slug, "isArchived": False, "isFork": False, "defaultBranchRef": {"name": "main"}}

    def __call__(self, args, *, cwd=None, input=None, timeout=60.0):
        a = list(args)
        self.calls.append(a)
        if a == ["api", "user", "-q", ".login"]:
            return 0, "acme\n", ""
        if a[:2] == ["repo", "list"]:
            return 0, json.dumps([self.entry()]), ""
        if a[:2] == ["repo", "view"]:
            return 0, json.dumps(self.entry()), ""
        if a[0] == "api" and "/contents/" in a[1]:
            path = a[1].split("/contents/", 1)[1]
            return (0, PLATFORM, "") if path == SETTINGS else (1, "", "gh: Not Found (HTTP 404)")
        self.unexpected.append(a)
        return 1, "", "unexpected gh call"

    def writes(self):
        return [c for c in self.calls if c[:2] in (["pr", "create"], ["pr", "edit"], ["pr", "comment"], ["pr", "merge"], ["label", "create"])]


@pytest.fixture()
def fleet_gh(monkeypatch):
    fake = FakeFleetGh("acme/sdlc-foundry")
    monkeypatch.setattr(fleet, "gh", fake)
    monkeypatch.setattr(fleet, "clone", lambda slug, dest: fake.clones.append(slug))
    monkeypatch.setattr(fleet, "sleep", lambda s: None)
    return fake


def test_ac_123_12_fleet_with_only_names_the_platform_repo_and_skips_it(fleet_gh, capsys):  # AC-123.12
    capsys.readouterr()
    rc = fleet.main(["update", "--json", "--only", "acme/sdlc-foundry"])
    doc = json.loads(capsys.readouterr().out)
    assert rc == 0
    (row,) = doc["repos"]
    assert row["repo"] == "acme/sdlc-foundry" and row["outcome"] == "skipped" and row["pr"] is None
    assert row["reason"] == "the platform repo is not updated from a template"
    assert fleet_gh.clones == [] and fleet_gh.writes() == [] and fleet_gh.unexpected == []


def test_ac_123_12_fleet_without_only_opens_nothing_for_it(fleet_gh, capsys):  # AC-123.12
    registered()
    capsys.readouterr()
    rc = fleet.main(["update", "--json"])
    doc = json.loads(capsys.readouterr().out)
    assert rc == 0 and doc["repos"] == []
    assert fleet_gh.clones == [] and fleet_gh.writes() == [] and fleet_gh.unexpected == []


def test_ac_123_13_doctor_reports_the_platform_source_version(tmp_path):  # AC-123.13
    r = mkrepo(tmp_path)
    (r / "docs").mkdir()
    (r / "docs" / "CHANGELOG.md").write_text("# CHANGELOG\n\n## [Unreleased]\n\n## [7.3.1] — 2026-10-26\n\nx\n")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "changelog")
    rows = {c["name"]: c for c in doctor.check_repo(r)}
    assert rows["repo shape"]["status"] == doctor.OK and rows["repo shape"]["detail"] == "platform"
    assert rows["repo platform version"]["status"] == doctor.OK
    assert rows["repo platform version"]["detail"] == "platform source at v7.3.1"
    assert not any("no .platform-version stamp" in c["detail"] for c in doctor.check_repo(r))


def test_ac_123_13_doctor_reports_a_bad_declaration_as_a_failure(tmp_path):  # AC-123.13
    rows = [c for c in doctor.check_repo(mkrepo(tmp_path, "shape: platfrom\n")) if c["name"] == "repo shape"]
    assert rows and rows[0]["status"] == doctor.FAIL and "platfrom" in rows[0]["detail"]


# ---------------- the commands on the platform repo ----------------

@pytest.mark.parametrize("name", ["spec", "plan", "verify", "build", "ship"])
def test_ac_123_14_a_declaration_error_stops_the_commands_and_the_shape_is_never_asked(name):  # AC-123.14
    md = text(CMDS / f"{name}.md")
    assert DECL_SENTENCE in md
    assert "ask the user which shape" not in md.lower()


def test_ac_123_14_spec_records_the_shape_of_a_repo_that_has_one():  # AC-123.14
    md = text(CMDS / "spec.md")
    assert "shape: platform" in md and "no `--no-shape`" in md


def test_ac_123_14_the_routed_agents_are_the_platforms(tmp_path, capsys):  # AC-123.14
    rc, out, _ = cp(capsys, "shape", "--repo", mkrepo(tmp_path))
    agents = json.loads(out)["agents"]
    assert rc == 0 and agents["product-manager"] == "svc:product-manager" and agents["reviewer"] == "svc:reviewer"


def test_ac_123_15_spec_new_records_the_platform_shape_and_check_accepts_it(tmp_path, capsys):  # AC-123.15
    r = mkrepo(tmp_path)
    rc, out, err = cp(capsys, "spec", "--repo", r, "new", "Platform thing")
    assert rc == 0, err
    path = r / out.strip()
    meta, _ = spec.load(path)
    assert meta["shape"] == "platform"
    rc, out, err = cp(capsys, "spec", "--repo", r, "check")
    assert rc == 0, out + err


def test_ac_123_15_no_shape_still_records_none(tmp_path, capsys):  # AC-123.15
    r = mkrepo(tmp_path)
    assert need(settings, "declared_shape")(r) == "platform"
    rc, out, _ = cp(capsys, "spec", "--repo", r, "new", "--no-shape", "Other thing")
    assert rc == 0 and "shape" not in spec.load(r / out.strip())[0]


def test_ac_123_16_existing_specs_keep_passing_with_the_shape_declared(tmp_path):  # AC-123.16
    root = tmp_path / "copy"
    shutil.copytree(ROOT / "docs" / "specs", root / "docs" / "specs")
    before_checks = {s.id: spec.check(s, shape=spec.repo_shape(root)) for s in spec.all_specs(root)}
    before_ci = sorted((s.id, m) for s, m in spec.ci_problems(root))
    (root / SETTINGS).write_text(PLATFORM)
    shape = spec.repo_shape(root)
    assert shape == "platform"
    after_checks = {s.id: spec.check(s, shape=shape) for s in spec.all_specs(root)}
    assert after_checks == before_checks
    assert sorted((s.id, m) for s, m in spec.ci_problems(root)) == before_ci
    assert "104-" in "".join(after_checks)
    assert not [e for errs in after_checks.values() for e in errs if "(smoke) needs a deployable shape" in e]
    assert spec.main(["--repo", str(root), "check"]) == (1 if any(after_checks.values()) else 0)


def test_ac_123_16_the_spec_104_smoke_criterion_is_still_in_the_repo():  # AC-123.16
    s = next(x for x in spec.all_specs(ROOT) if x.id.startswith("104-"))
    assert any(ac == "AC-104.4" for ac in s.smoke_acs())
    assert "shape" not in s.meta


def smoke_spec(root: Path, shape_line: str = "shape: platform\n") -> Path:
    d = root / "docs" / "specs" / "900-smoky"
    d.mkdir(parents=True)
    (d / "spec.md").write_text(
        "---\nspec_id: 900-smoky\ntitle: Smoky\nstatus: draft\npriority: P1\n" + shape_line + "---\n\n# 900 — Smoky\n\n"
        "## Problem\n\nx\n\n## Acceptance criteria\n\n- **AC-900.1** Given a, when b, then c. (smoke)\n"
        "- **AC-900.2** Given a, when b, then d.\n\n## Non-goals\n\n- none\n\n## Open questions\n\nNone.\n\n## Changelog\n\n- 2026-10-26 created\n")
    return d


def test_ac_123_17_a_platform_spec_cannot_have_a_smoke_criterion(tmp_path):  # AC-123.17
    r = mkrepo(tmp_path)
    d = smoke_spec(r)
    errs = spec.check(spec.read(d), shape=spec.repo_shape(r))
    assert "AC-900.1: (smoke) needs a deployable shape (platform has no smoke tests)" in errs
    assert not any("AC-900.2" in e for e in errs) and not any("unknown shape" in e for e in errs)


def test_ac_123_17_a_spec_without_a_shape_line_keeps_its_smoke_criterion(tmp_path):  # AC-123.17
    r = mkrepo(tmp_path)
    d = smoke_spec(r, "")
    assert need(spec, "spec_shape")(spec.read(d), "platform") is None
    assert not any("(smoke)" in e for e in spec.check(spec.read(d), shape=spec.repo_shape(r)))


def test_ac_123_17_spec_shape_prefers_the_specs_own_line(tmp_path):  # AC-123.17
    d = smoke_spec(mkrepo(tmp_path))
    s = spec.read(d)
    assert need(spec, "spec_shape")(s, "platform") == "platform"
    assert spec.spec_shape(s, None) == "platform"
    other = spec.read(smoke_spec(mkrepo(tmp_path, name="other"), "shape: service-go\n"))
    assert spec.spec_shape(other, "platform") == "service-go"
    assert spec.spec_shape(other, "service-go") == "service-go"


def test_ac_123_18_build_gates_run_through_the_repos_own_devbox_scripts(tmp_path, capsys):  # AC-123.18
    scripts = json.loads(text(ROOT / "devbox.json"))["shell"]["scripts"]
    for name in ("test-fast", "quality", "lint-fix", "ci"):
        assert name in scripts
    md = text(CMDS / "build.md")
    for name in ("test-fast", "quality", "lint-fix", "ci"):
        assert re.search(rf"cplat quiet {name}\b", md), name
    assert DECL_SENTENCE in md
    assert "Skip with `## Phase 5 skipped — <shape> is not deployable` when `deployable` is false" in md
    rc, out, _ = cp(capsys, "shape", "--repo", mkrepo(tmp_path))
    doc = json.loads(out)
    assert rc == 0 and doc["deployable"] is False and "deployment" not in doc["agents"]   # Phase 5 is skipped for platform


def test_ac_123_19_ship_start_asks_for_no_gitops_link_or_token(prepo, gh):  # AC-123.19
    gh.secrets = []                                   # no GITOPS_TOKEN anywhere
    assert not (prepo / ".platform-app.yml").exists()
    st = ship.start(prepo, "7", True)
    assert st["phase"] in {"plan", "build"} and st["shape"] == "platform"
    assert not any(a[:2] == ["secret", "list"] for a in gh.calls)
    assert ship.load_state(prepo)["shape"] == "platform"


def test_ac_123_20_land_waits_for_the_platform_checks_and_squash_merges(prepo, gh):  # AC-123.20
    to_land(prepo, gh)
    assert ship.load_state(prepo)["shape"] == "platform"
    names = ["ci-success", "DCO sign-off", "spec-required", "pr-title"]
    gh.checks = [[check(n, "pending") for n in names] + [check("smoke-service", "skipping")],
                 [check(n, "pass") for n in names] + [check("smoke-service", "skipping")]]
    ok, lines = ship.land(prepo, timeout=600, interval=10)
    assert ok
    assert gh.merges == [["gh", "pr", "merge", "https://github.com/acme/shop-api/pull/7", "--squash", "--delete-branch"]]
    assert ship.load_state(prepo)["phase"] == "deploy"


def test_ac_123_20_land_ends_at_the_first_red_platform_check(prepo, gh):  # AC-123.20
    to_land(prepo, gh)
    assert ship.load_state(prepo)["shape"] == "platform"
    gh.checks = [[check("ci-success", "pending"), check("DCO sign-off", "fail"), check("spec-required", "pending"),
                  check("pr-title", "pass")]]
    ok, lines = ship.land(prepo, timeout=600, interval=10)
    assert not ok and gh.merges == [] and "DCO sign-off" in "\n".join(lines)


def landed(prepo, gh):
    to_land(prepo, gh)
    gh.checks = [[check("ci-success", "pass"), check("DCO sign-off", "pass")]]
    ok, _ = ship.land(prepo, timeout=60, interval=10)
    assert ok


def test_ac_123_21_deploy_is_done_at_once_for_the_platform(prepo, gh, monkeypatch):  # AC-123.21
    landed(prepo, gh)
    ran = []
    real = ship.run
    monkeypatch.setattr(ship, "run", lambda cmd, **kw: ran.append(list(cmd)) or real(cmd, **kw))
    before = len(gh.calls)
    ok, lines = ship.deploy(prepo, timeout=600, interval=10, context=None)
    assert ok and "not deployable (platform): nothing to deploy" in lines
    assert ship.load_state(prepo)["phase"] == "done"
    assert gh.calls[before:] == []                      # no pin PR, no run view, nothing from GitHub
    assert not any("smoke" in " ".join(c) or c[:1] == ["kubectl"] for c in ran)


def test_ac_123_21_deploy_never_runs_devbox_smoke_even_with_a_context(prepo, gh, monkeypatch):  # AC-123.21
    landed(prepo, gh)
    ran = []
    monkeypatch.setattr(ship, "run", lambda cmd, **kw: ran.append(list(cmd)) or subprocess.CompletedProcess(cmd, 0, "", ""))
    ok, lines = ship.deploy(prepo, timeout=600, interval=10, context="kind-dev")
    assert ok and lines[0] == "not deployable (platform): nothing to deploy"
    assert ran == []


def test_ac_123_22_the_finished_run_reports_not_deployable_and_names_the_shape(prepo, gh):  # AC-123.22
    landed(prepo, gh)
    ok, lines = ship.deploy(prepo, timeout=600, interval=10, context=None)
    assert ok
    assert "Smoke (dev): not deployable" in lines and "Promotion (staging): not deployable" in lines
    assert not any("/instance:promote" in ln for ln in lines)
    records = [r for r in buffered_lines() if r.get("workflow") == "ship" or r.get("kind") == "ship" or "shape" in r]
    assert any(r.get("shape") == "platform" and r.get("outcome") == "done" for r in records), buffered_lines()


def test_ac_123_22_ship_md_prints_not_deployable_rows_and_no_promote_step():  # AC-123.22
    md = text(CMDS / "ship.md")
    assert "not deployable (<shape>): nothing to deploy" in md
    assert "`Promotion (staging)`, `Smoke (staging)` and `Smoke (dev)` rows read `not deployable`" in md
    assert "every `Next:` line that names `/instance:promote`" in md
    assert "no `devbox run smoke` (which here smoke-tests the templates)" in md


def test_ac_123_23_release_refuses_without_a_release_role(tmp_path, capsys):  # AC-123.23
    rc, out, _ = cp(capsys, "shape", "--repo", mkrepo(tmp_path))
    assert rc == 0 and "release" not in json.loads(out)["agents"]
    md = text(CMDS / "release.md")
    assert "If `agents` has no `release` role (shape `platform`), stop before anything changes" in md
    assert "## Release refused: the platform is not released with /component:release" in md
    assert "version bumps in .claude-plugin/marketplace.json and each changed plugin's .claude-plugin/plugin.json" in md
    assert "It is described in CONTRIBUTING.md, section Releases." in md


def test_ac_123_23_contributing_says_where_the_procedure_is():  # AC-123.23
    md = text(ROOT / "CONTRIBUTING.md")
    releases = md.split("## Releases", 1)[1].split("\n## ", 1)[0]
    assert "/component:release" in releases and "refuses" in releases
