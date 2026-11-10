"""Spec 174: plugins bring what they need, and one plugin installs the starter set."""
import importlib.util
import json
import re
import shutil
import subprocess
import sys

import pytest

import doctor
from system_fixtures import ROOT

PLUGINS = ROOT / "plugins"
MARKET = ROOT / ".claude-plugin" / "marketplace.json"
LIVE = ("svc", "web", "svc-go", "svc-java", "system", "component", "api", "resource", "instance", "issue", "platform", "cluster")
TOMBS = ("app", "gitops")
INSTALL_BLOCK = "/plugin marketplace add ika100/sdlc-foundry\n/plugin install starter@sdlc-foundry\n"
PAGES = ("docs/QUICKSTART.md", "README.md", "docs/USER-JOURNEY.md", "site/src/content/docs/get-started/local-cluster.md")
SHARED_DESC = ("The cplat launcher every sdlc-foundry command calls, the quality and security agents and the session hooks. "
               "The other plugins depend on it and install it with them.")


def load(rel, name):
    path = ROOT / rel
    if not path.is_file():
        pytest.fail(f"{rel} is missing")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except ImportError as e:
        pytest.fail(f"{rel} cannot import what it needs: {e}")
    return mod


def plugin_set():
    return load("scripts/cplat/plugin_set.py", "plugin_set_174")


def deps_script():
    return load("scripts/check-plugin-deps.py", "check_plugin_deps_174")


def read(path):
    return json.loads(path.read_text())


def manifest(name):
    return read(PLUGINS / name / ".claude-plugin" / "plugin.json")


def entry(name):
    return next(p for p in read(MARKET)["plugins"] if p["name"] == name)


def blocks(text, lang="text"):
    return re.findall(rf"```{lang}\n(.*?)```", text, re.S)


def build(tmp, spec):
    """A scratch marketplace. spec: name -> {"tomb": bool, "deps": value or absent, "mdeps": value or absent}."""
    (tmp / ".claude-plugin").mkdir(parents=True)
    entries = []
    for name, s in spec.items():
        pdir = tmp / "plugins" / name
        (pdir / ".claude-plugin").mkdir(parents=True)
        (pdir / "commands").mkdir()
        head = "description: Moved in 5.0\nmoved-to: /x:y\n" if s.get("tomb") else "description: Does things\n"
        (pdir / "commands" / "run.md").write_text(f"---\n{head}---\nbody\n")
        pj = {"name": name, "version": "1.0.0"}
        if "deps" in s:
            pj["dependencies"] = s["deps"]
        (pdir / ".claude-plugin" / "plugin.json").write_text(json.dumps(pj))
        e = {"name": name, "source": f"./plugins/{name}", "version": "1.0.0"}
        if "mdeps" in s:
            e["dependencies"] = s["mdeps"]
        entries.append(e)
    (tmp / ".claude-plugin" / "marketplace.json").write_text(json.dumps({"name": "sdlc-foundry", "plugins": entries}))
    return tmp


def cli(root):
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "check-plugin-deps.py"), "--root", str(root)],
                          capture_output=True, text=True)


# ---------------- AC-174.1: live plugins depend on shared ----------------

@pytest.mark.parametrize("name", LIVE)
def test_a_live_plugin_depends_on_shared_ac_174_1(name):  # AC-174.1
    assert "shared" in manifest(name).get("dependencies", []), name


def test_shared_and_tombstone_plugins_declare_no_dependencies_ac_174_1():  # AC-174.1
    for name in ("shared", *TOMBS):
        assert "dependencies" not in manifest(name), name


def test_every_non_tombstone_plugin_of_the_marketplace_is_covered_ac_174_1():  # AC-174.1
    ps = plugin_set().catalog(ROOT)
    for name, e in ps.items():
        if name == "shared":
            continue
        tomb = plugin_set().is_tombstone_only(plugin_set().plugin_dir(ROOT, e))
        assert tomb == (name in TOMBS), name
        assert ("shared" in manifest(name).get("dependencies", [])) == (not tomb), name


# ---------------- AC-174.2: the starter bundle ----------------

def test_the_starter_bundle_manifest_ac_174_2():  # AC-174.2
    m = manifest("starter")
    assert set(m) == {"name", "version", "description", "author", "license", "dependencies"}
    assert m["name"] == "starter"
    assert m["dependencies"] == ["shared", "system", "component", "platform"]
    e = entry("starter")
    assert e["version"] == m["version"] and e["description"] == m["description"]
    assert e["source"] == "./plugins/starter"
    for extra in ("commands", "agents", "skills", "hooks", "bin"):
        assert not (PLUGINS / "starter" / extra).exists(), extra


def test_the_starter_readme_says_what_it_installs_and_how_to_remove_it_ac_174_2():  # AC-174.2
    f = PLUGINS / "starter" / "README.md"
    assert f.is_file(), "plugins/starter/README.md is missing"
    text = f.read_text()
    for part in ("shared", "system", "component", "platform", "claude plugin uninstall starter@sdlc-foundry --prune"):
        assert part in text, part
    assert re.search(r"on (its|their) own|alone|individually", text)


# ---------------- AC-174.3: the dependency validator ----------------

def test_plugin_set_decides_tombstone_only_ac_174_3(tmp_path):  # AC-174.3
    ps = plugin_set()
    build(tmp_path, {"live": {}, "tomb": {"tomb": True}})
    assert ps.is_tombstone_only(tmp_path / "plugins" / "tomb") is True
    assert ps.is_tombstone_only(tmp_path / "plugins" / "live") is False
    (tmp_path / "plugins" / "tomb" / "agents").mkdir()
    assert ps.is_tombstone_only(tmp_path / "plugins" / "tomb") is False
    bundle = tmp_path / "plugins" / "bundle"
    (bundle / ".claude-plugin").mkdir(parents=True)
    assert ps.is_tombstone_only(bundle) is False, "no commands at all is not tombstone-only"


def test_plugin_set_reads_dependency_names_and_the_catalog_ac_174_3(tmp_path):  # AC-174.3
    ps = plugin_set()
    assert ps.dependency_name("shared") == "shared"
    assert ps.dependency_name("svc-go@sdlc-foundry") == "svc-go"
    for bad in ("shared@other", "shared@^1.0", "Shared", {"name": "shared"}, 3, ""):
        assert ps.dependency_name(bad) is None, bad
    build(tmp_path, {"b": {}, "a": {}})
    assert list(ps.catalog(tmp_path)) == ["b", "a"]
    (tmp_path / ".claude-plugin" / "marketplace.json").write_text("{nope")
    with pytest.raises(ValueError, match="marketplace.json"):
        ps.catalog(tmp_path)


def test_a_clean_marketplace_passes_ac_174_3(tmp_path):  # AC-174.3
    build(tmp_path, {"shared": {}, "a": {"deps": ["shared", "b@sdlc-foundry"]}, "b": {"deps": ["shared"]}, "t": {"tomb": True}})
    assert deps_script().problems(tmp_path) == []
    p = cli(tmp_path)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "OK: 2 plugin(s) declare dependencies" in p.stdout


@pytest.mark.parametrize("spec, expected", [
    ({"shared": {}, "a": {"deps": "shared"}},
     'a (plugins/a/.claude-plugin/plugin.json): dependencies is not a list'),
    ({"shared": {}, "a": {"deps": ["shared@^1.0.0"]}},
     'a (plugins/a/.claude-plugin/plugin.json): dependency "shared@^1.0.0" is not a plugin name or <name>@sdlc-foundry (version ranges are not supported)'),
    ({"shared": {}, "a": {"deps": ["shared@other"]}},
     'a (plugins/a/.claude-plugin/plugin.json): dependency "shared@other" is not a plugin name'),
    ({"shared": {}, "a": {"deps": [{"name": "shared"}]}},
     "a (plugins/a/.claude-plugin/plugin.json): dependency"),
    ({"shared": {}, "a": {"deps": ["ghost"]}},
     'a (plugins/a/.claude-plugin/plugin.json): dependency "ghost" names no plugin of this marketplace'),
    ({"shared": {}, "t": {"tomb": True}, "a": {"deps": ["t"]}},
     'a (plugins/a/.claude-plugin/plugin.json): dependency "t" holds only tombstones'),
    ({"shared": {}, "a": {"deps": ["a"]}},
     'a (plugins/a/.claude-plugin/plugin.json): dependency "a" is the plugin itself'),
    ({"shared": {}, "a": {"mdeps": ["ghost"]}},
     'a (.claude-plugin/marketplace.json): dependency "ghost" names no plugin of this marketplace'),
])
def test_a_bad_dependency_fails_with_plugin_and_entry_ac_174_3(tmp_path, spec, expected):  # AC-174.3
    build(tmp_path, spec)
    out = deps_script().problems(tmp_path)
    assert any(expected in line for line in out), out
    p = cli(tmp_path)
    assert p.returncode == 1, p.stdout
    assert f"ERROR: {expected}" in p.stdout
    assert "FAILED:" in p.stdout and "problem(s) in plugin dependencies" in p.stdout


def test_a_dependency_cycle_fails_once_ac_174_3(tmp_path):  # AC-174.3
    build(tmp_path, {"a": {"deps": ["b"]}, "b": {"deps": ["a"]}})
    out = deps_script().problems(tmp_path)
    assert [line for line in out if "cycle" in line] == [line for line in out]
    assert len(out) == 1 and "dependency cycle: a -> b -> a" in out[0], out
    p = cli(tmp_path)
    assert p.returncode == 1
    assert "ERROR: dependency cycle: a -> b -> a" in p.stdout and "FAILED: 1 problem(s)" in p.stdout


def test_unreadable_json_is_one_error_line_ac_174_3(tmp_path):  # AC-174.3
    build(tmp_path, {"shared": {}, "a": {"deps": ["shared"]}})
    (tmp_path / "plugins" / "a" / ".claude-plugin" / "plugin.json").write_text("{nope")
    p = cli(tmp_path)
    assert p.returncode == 1
    assert [x for x in p.stdout.splitlines() if x.startswith("ERROR: plugins/a/.claude-plugin/plugin.json")], p.stdout


def test_the_repository_dependencies_are_valid_ac_174_3():  # AC-174.3
    assert deps_script().problems(ROOT) == []
    p = subprocess.run([sys.executable, "scripts/check-plugin-deps.py"], cwd=ROOT, capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "OK:" in p.stdout


def test_the_validator_runs_in_validate_ci_and_ci_local_ac_174_3():  # AC-174.3
    cmd = "scripts/check-plugin-deps.py"
    assert cmd in read(ROOT / "devbox.json")["shell"]["scripts"]["validate"]
    assert cmd in (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert cmd in (ROOT / "scripts" / "ci-local.sh").read_text()


# ---------------- AC-174.4: check-docs reads the starter set ----------------

def test_check_docs_reads_the_starter_set_from_the_bundle_ac_174_4(tmp_path):  # AC-174.4
    ps_src = ROOT / "scripts" / "cplat" / "plugin_set.py"
    assert ps_src.is_file(), "scripts/cplat/plugin_set.py is missing"
    (tmp_path / "scripts" / "cplat").mkdir(parents=True)
    shutil.copy(ROOT / "scripts" / "check-docs.py", tmp_path / "scripts" / "check-docs.py")
    shutil.copy(ps_src, tmp_path / "scripts" / "cplat" / "plugin_set.py")
    (tmp_path / "plugins" / "starter" / ".claude-plugin").mkdir(parents=True)
    (tmp_path / "plugins" / "starter" / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "starter", "dependencies": ["shared", "system"]}))
    spec = importlib.util.spec_from_file_location("check_docs_tmp_174", tmp_path / "scripts" / "check-docs.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.STARTER == ("shared", "system")


def test_check_docs_has_no_starter_constant_of_its_own_ac_174_4():  # AC-174.4
    src = (ROOT / "scripts" / "check-docs.py").read_text()
    assert '("shared", "system", "component", "platform")' not in src
    assert "plugin_set" in src
    check_docs = load("scripts/check-docs.py", "check_docs_174")
    assert check_docs.STARTER == tuple(manifest("starter")["dependencies"])


def test_the_starter_bundle_is_live_and_tombstones_are_not_ac_174_4():  # AC-174.4
    check_docs = load("scripts/check-docs.py", "check_docs_174b")
    live = check_docs.live_plugins(check_docs.commands())
    assert "starter" in live and "shared" in live
    assert not live & set(TOMBS)


def test_installing_the_bundle_counts_as_the_whole_set_ac_174_4(tmp_path, monkeypatch):  # AC-174.4
    check_docs = load("scripts/check-docs.py", "check_docs_174c")
    cmds = check_docs.commands()
    live = check_docs.live_plugins(cmds)
    recipes = check_docs.recipes()
    page = tmp_path / "page.md"
    monkeypatch.setattr(check_docs, "ROOT", tmp_path)
    monkeypatch.setattr(check_docs, "PLAIN", [])
    page.write_text(f"# Page\n\n```text\n{INSTALL_BLOCK}```\n")
    assert check_docs.check_page(page, cmds, live, recipes) == []
    page.write_text("# Page\n\n```text\n/plugin install system@sdlc-foundry\n```\n")
    out = check_docs.check_page(page, cmds, live, recipes)
    assert any("not the starter plugin(s)" in p for p in out), out


# ---------------- AC-174.5: the two-line install in the docs ----------------

@pytest.mark.parametrize("page", PAGES)
def test_the_page_installs_the_starter_set_in_two_lines_ac_174_5(page):  # AC-174.5
    text = (ROOT / page).read_text()
    assert INSTALL_BLOCK in blocks(text), page
    prose = re.sub(r"```.*?```", "", text, flags=re.S)
    assert "`component`" in prose and re.search(r"alone|on its own", prose), page
    assert doctor.MIN_CLAUDE_VERSION in prose and "claude update" in prose, page
    assert not re.search(r"/plugin install (shared|system|component|platform)@", "".join(blocks(text))), page


# ---------------- AC-174.6: the doctor ----------------

def fake_claude(monkeypatch, version_out, *, rc=0, timeout=False, found=True):
    real = subprocess.run
    monkeypatch.setattr(shutil, "which", lambda t, *a, **k: "/bin/" + t if t != "claude" or found else None)

    def run(cmd, *a, **k):
        if isinstance(cmd, (list, tuple)) and cmd and str(cmd[0]).endswith("claude"):
            if timeout:
                raise subprocess.TimeoutExpired(cmd, 10)
            return subprocess.CompletedProcess(cmd, rc, version_out, "")
        return real(cmd, *a, **k)
    monkeypatch.setattr(subprocess, "run", run)


def version_row():
    return [c for c in doctor.check_tools() if c["name"] == "claude version"]


def test_the_minimum_claude_version_is_one_constant_ac_174_6():  # AC-174.6
    assert doctor.MIN_CLAUDE_VERSION == "2.1.311"


def test_an_old_claude_gets_a_warning_with_the_fix_ac_174_6(monkeypatch):  # AC-174.6
    fake_claude(monkeypatch, "2.1.310 (Claude Code)\n")
    (row,) = version_row()
    assert row["status"] == "warn" and row["fix"] == "claude update"
    assert "2.1.310" in row["detail"] and "2.1.311" in row["detail"]


def test_a_current_claude_gets_an_ok_row_ac_174_6(monkeypatch):  # AC-174.6
    fake_claude(monkeypatch, "2.2.0 (Claude Code)\n")
    (row,) = version_row()
    assert row["status"] == "ok" and "2.2.0" in row["detail"] and "2.1.311" in row["detail"]


@pytest.mark.parametrize("kw", [{"found": False, "version_out": ""}, {"version_out": "", "rc": 1},
                                {"version_out": "no version here"}, {"version_out": "", "timeout": True}])
def test_no_version_row_when_the_version_is_unknown_ac_174_6(monkeypatch, kw):  # AC-174.6
    kw = dict(kw)
    fake_claude(monkeypatch, kw.pop("version_out"), **kw)
    assert version_row() == []


def plugin_rows(monkeypatch, installed):
    monkeypatch.setattr(doctor, "installed_plugins", lambda: installed)
    monkeypatch.setattr(doctor, "legacy_plugins", lambda: {})
    return {c["name"]: c for c in doctor.check_plugins()}


def test_a_plugin_installed_without_shared_fails_with_the_fix_ac_174_6(monkeypatch):  # AC-174.6
    rows = plugin_rows(monkeypatch, {"component": "1.0.0", "system": "1.0.0"})
    row = rows["plugin shared"]
    assert row["status"] == "fail" and row["fix"] == "claude plugin install shared@sdlc-foundry"
    assert "component" in row["detail"] and "system" in row["detail"]


@pytest.mark.parametrize("installed", [{"shared": "1.0.0", "component": "1.0.0"}, {"app": "1.0.0"}, {"shared": "1.0.0"}])
def test_no_shared_row_when_nothing_needs_it_ac_174_6(monkeypatch, installed):  # AC-174.6
    assert "plugin shared" not in plugin_rows(monkeypatch, installed)


def test_the_none_installed_fix_names_the_starter_plugin_ac_174_6(monkeypatch):  # AC-174.6
    (row,) = [c for c in plugin_rows(monkeypatch, {}).values() if c["name"] == "plugins"]
    assert "/plugin install starter@sdlc-foundry" in row["fix"]


# ---------------- AC-174.7: versions, description, changelog ----------------

# the minor each plugin reached with spec 174 (one minor up from 5.16.0); later releases may only go higher, same major
SHIPPED = {"api": (1, 3), "cluster": (1, 4), "component": (1, 17), "instance": (1, 6), "issue": (1, 2), "platform": (1, 8), "resource": (1, 9), "shared": (1, 4), "svc": (4, 9), "svc-go": (0, 8), "svc-java": (0, 8), "system": (1, 16), "web": (0, 8)}


@pytest.mark.parametrize("name", (*LIVE, "shared"))
def test_a_changed_plugin_is_one_minor_up_in_both_files_ac_174_7(name):  # AC-174.7
    want = SHIPPED[name]
    for have in (manifest(name)["version"], entry(name)["version"]):
        got = tuple(int(x) for x in have.split("."))[:2]
        assert got[0] == want[0] and got >= want, (name, have, want)


def test_shared_describes_what_it_holds_today_ac_174_7():  # AC-174.7
    assert manifest("shared")["description"] == SHARED_DESC
    assert entry("shared")["description"] == SHARED_DESC
    assert "/new-service" not in SHARED_DESC


def test_a_changelog_fragment_announces_the_starter_ac_174_7():  # AC-174.7
    # a fragment until the release, then a paragraph of docs/CHANGELOG.md
    frags = [f.read_text() for f in (ROOT / "docs" / "changelog.d").glob("*.md") if f.name != "README.md"]
    released = (ROOT / "docs" / "CHANGELOG.md").read_text().split("\n\n")
    hits = [e for e in frags + released if "`starter`" in e and "/plugin marketplace update" in e]
    assert hits, "no changelog entry names `starter` and `/plugin marketplace update`"
