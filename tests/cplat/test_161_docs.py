"""Spec 161: a tested quickstart and leaner user docs (check-docs.py, docs/QUICKSTART.md, README, site navigation)."""
import importlib.util
import re
import subprocess
import sys

import pytest
import yaml

import compose
import cplat
from system_fixtures import ROOT

QUICKSTART = ROOT / "docs" / "QUICKSTART.md"
_spec = importlib.util.spec_from_file_location("check_docs", ROOT / "scripts" / "check-docs.py")
check_docs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_docs)


CMDS = check_docs.commands()
PLUGINS, RECIPES, PLAIN = check_docs.live_plugins(CMDS), check_docs.recipes(), list(check_docs.PLAIN)


def problems_in(tmp_path, monkeypatch, text, name="page.md", plain=False):
    """Run the page check on a page written into a scratch repository root, against the real commands and recipes."""
    page = tmp_path / name
    page.write_text(text)
    monkeypatch.setattr(check_docs, "ROOT", tmp_path)
    monkeypatch.setattr(check_docs, "PLAIN", [name] if plain else [])
    return check_docs.check_page(page, CMDS, PLUGINS, RECIPES)


def blocks(text, lang):
    return re.findall(rf"```{lang}\n(.*?)```", text, re.S)


# ---------------- AC-161.1: commands, flags, plugins, recipes ----------------

def test_the_repository_docs_pass_the_check_ac_161_1():  # AC-161.1
    p = subprocess.run([sys.executable, "scripts/check-docs.py"], cwd=ROOT, capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "OK: 0 problem(s)" in p.stdout


@pytest.mark.parametrize("line, found", [
    ("Run `/component:shipp 001`.", "/component:shipp is not a command"),
    ("Run `/svc:ship 001`.", "/svc:ship is a tombstone"),
    ("Run `/component:ship 001 --fast`.", "/component:ship has no --fast"),
    ("```text\n/plugin install gitops@sdlc-foundry\n```", "plugin gitops does not exist or holds only tombstones"),
    ("Then `devbox run cluster-upp`.", "devbox run cluster-upp is not a recipe"),
])
def test_a_page_naming_what_does_not_exist_fails_with_file_and_line_ac_161_1(tmp_path, monkeypatch, line, found):  # AC-161.1
    out = problems_in(tmp_path, monkeypatch, f"# Page\n\n{line}\n")
    assert any(found in p and p.startswith("page.md:") for p in out), out


def test_what_exists_passes_and_history_is_skipped_ac_161_1(tmp_path, monkeypatch):  # AC-161.1
    ok = ("# Page\n\nRun `/component:ship 001 --no-merge`, then `devbox run cluster-up`.\n\n"
          "`cplat headless \"/component:ship 012\" --quiet 23:30-07:00` waits for the window.\n\n"
          "| `/svc:ship` | `/component:ship` |\n\n## Migrating from 4.x\n\n`/gitops:addon` became a resource.\n")
    assert problems_in(tmp_path, monkeypatch, ok) == []
    assert problems_in(tmp_path, monkeypatch, "<!-- historical -->\n# Old\n\n`/svc:ship 001 --fast`\n") == []


def test_the_default_pages_cover_readme_guides_site_and_plugin_readmes_ac_161_1():  # AC-161.1
    rel = {p.relative_to(ROOT).as_posix() for p in check_docs.pages([], PLUGINS)}
    assert {"README.md", "docs/QUICKSTART.md", "docs/USER-JOURNEY.md", "plugins/component/README.md",
            "site/src/content/docs/get-started/local-cluster.md"} <= rel
    assert not rel & {"docs/CHANGELOG.md", "docs/backlog.md", "plugins/gitops/README.md"}
    assert not any(r.startswith(("docs/adr/", "docs/specs/", "site/src/content/docs/guides/")) for r in rel)


# ---------------- AC-161.2: manifests ----------------

def test_an_invalid_manifest_block_fails_and_a_valid_one_passes_ac_161_2(tmp_path, monkeypatch):  # AC-161.2
    bad = "# Page\n\n```yaml\nsystem: shop\nowner: me\ncomponents:\n  - {name: shop-api, description: API, shape: service-go}\n```\n"
    out = problems_in(tmp_path, monkeypatch, bad)
    assert out and out[0].startswith("page.md:3: invalid system manifest") and "shape" in out[0]
    good = bad.replace("shape: service-go", "type: service, lang: go")
    assert problems_in(tmp_path, monkeypatch, good) == []


def test_a_system_yaml_block_is_not_taken_for_a_manifest_ac_161_2(tmp_path, monkeypatch):  # AC-161.2
    doc = "# Page\n\n```yaml\nsystem: shop\nowner: me\ncomponents:\n  shop-api: {type: service, lang: go}\n```\n"
    assert problems_in(tmp_path, monkeypatch, doc) == []


# ---------------- AC-161.3: the starter set ----------------

def test_an_install_block_without_the_starter_set_fails_ac_161_3(tmp_path, monkeypatch):  # AC-161.3
    assert check_docs.STARTER == ("shared", "system", "component", "platform")
    out = problems_in(tmp_path, monkeypatch, "# Page\n\n```text\n/plugin install system@sdlc-foundry\n```\n")
    assert any("not the starter plugin(s) shared, component, platform" in p for p in out), out
    full = "".join(f"/plugin install {p}@sdlc-foundry\n" for p in check_docs.STARTER)
    assert problems_in(tmp_path, monkeypatch, f"# Page\n\n```text\n{full}/plugin install instance@sdlc-foundry\n```\n") == []


# ---------------- AC-161.4: wired into CI, quality and ci-local ----------------

def test_the_check_runs_in_ci_quality_and_ci_local_ac_161_4():  # AC-161.4
    cmd = "python scripts/check-docs.py"
    assert cmd in (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert cmd in __import__("json").loads((ROOT / "devbox.json").read_text())["shell"]["scripts"]["quality"]
    assert cmd in (ROOT / "scripts" / "ci-local.sh").read_text()


# ---------------- AC-161.5: the quickstart's manifest is the tested one ----------------

def test_the_quickstart_manifest_creates_the_system_ac_161_5(tmp_path, capsys, monkeypatch):  # AC-161.5
    text = QUICKSTART.read_text()
    installs = re.findall(r"/plugin install ([a-z-]+)@sdlc-foundry", "".join(blocks(text, "text")))
    assert set(check_docs.STARTER) <= set(installs)
    manifest = next(b for b in blocks(text, "yaml") if b.startswith("system:"))
    name = yaml.safe_load(manifest)["system"]
    f = tmp_path / f"{name}.yaml"
    f.write_text(manifest)
    assert f"/system:new {f.name}" in text
    calls = []
    monkeypatch.setattr(compose, "main", lambda argv: calls.append(argv) or 0)
    rc = cplat.main(["system", "new", str(f), "--no-github", "--skip-tasks", "--org", "acme", "--dir", str(tmp_path / "out")])
    assert rc == 0, capsys.readouterr().err
    out = tmp_path / "out"
    assert (out / f"{name}-gitops" / "applications" / name / "system.yaml").is_file()
    for c in yaml.safe_load(manifest)["components"]:
        assert (out / c["name"] / ".copier-answers.yml").is_file()
        assert f"{c['name']}.{name}-dev.localhost:8088" in text


# ---------------- AC-161.6: one getting-started page ----------------

def test_the_quickstart_is_the_one_getting_started_page_ac_161_6():  # AC-161.6
    text = QUICKSTART.read_text()
    steps = re.findall(r"^## \d\. .*\((?:about )?\d+ minutes\)$", text, re.M)
    assert len(steps) >= 5, "every step says how long it takes"
    assert text.count("**You will see**") >= len(steps) and text.count("**If ") >= len(steps)
    assert "/platform:doctor" in text and "## What just happened" in text and "## Next steps" in text
    sync = (ROOT / "site" / "scripts" / "sync-docs.mjs").read_text()
    assert "{ src: 'docs/QUICKSTART.md', slug: 'get-started'" in sync
    assert not (ROOT / "site" / "src" / "content" / "docs" / "get-started" / "index.md").exists()
    for page in ("README.md", "docs/USER-JOURNEY.md"):
        assert "QUICKSTART.md" in (ROOT / page).read_text(), page


# ---------------- AC-161.7: a lean README ----------------

def test_the_readme_is_lean_ac_161_7():  # AC-161.7
    text = (ROOT / "README.md").read_text()
    assert len(text.splitlines()) <= 120
    assert "Formerly *claude-platform*" not in text and "## Slash commands" not in text and "## Updates" not in text
    for part in ("demo.gif", "docs/QUICKSTART.md", "## Disclaimer, privacy, AI-assisted development", "## License", "reference/commands/"):
        assert part in text, part
    assert "## How changes reach consumers" in (ROOT / "CONTRIBUTING.md").read_text()


# ---------------- AC-161.8: outdated material ----------------

def test_outdated_material_leaves_the_site_and_is_marked_historical_ac_161_8():  # AC-161.8
    sync = (ROOT / "site" / "scripts" / "sync-docs.mjs").read_text()
    for src in ("docs/requirements/platform-vision.md", "docs/requirements/end-to-end-scenario.md",
                "docs/e2e/2026-10-08-todo-spec-driven.md", "docs/e2e/2026-10-09-todo-second-feature.md"):
        assert f"'{src}'" not in sync, src
        assert "<!-- historical -->" in (ROOT / src).read_text(), src
    assert "design-history" not in (ROOT / "site" / "astro.config.mjs").read_text()
    domain, adopting = (ROOT / "docs" / "DOMAIN-MODEL.md").read_text(), (ROOT / "docs" / "ADOPTING.md").read_text()
    assert "4.7 features on the model" not in domain and "/shared:new-app" not in domain
    migration = adopting.split("## Migrating from 4.x to 5.0", 1)[1].split("\n## ", 1)[0]
    assert "### What moved where" in migration and "| | `/gitops:compose` |" in migration
    journey = (ROOT / "docs" / "USER-JOURNEY.md").read_text().split("## Chapter 1", 1)[0]
    assert all(f"/plugin install {p}@sdlc-foundry" in journey for p in check_docs.STARTER)
    assert "devbox run cluster-up" in journey and "just `shared`" not in journey


# ---------------- AC-161.9: site navigation ----------------

def test_get_started_leads_with_the_quickstart_ac_161_9():  # AC-161.9
    config = (ROOT / "site" / "astro.config.mjs").read_text()
    get_started = re.search(r"label: 'Get started', items: \[(.*?)\] \}", config).group(1)
    assert re.findall(r"slug: '([^']+)'", get_started) == ["get-started", "get-started/local-cluster", "get-started/watch-a-run"]
    reference = config.split("label: 'Reference'", 1)[1]
    assert "slug: 'reference/performance'" in reference
    landing = (ROOT / "site" / "src" / "content" / "docs" / "index.mdx").read_text()
    first = re.search(r"actions:\n\s+- text: (.*)\n\s+link: (\S+)", landing)
    assert "Quickstart" in first.group(1) and first.group(2) == "/sdlc-foundry/get-started/"


# ---------------- AC-161.10: no jargon on newcomer pages ----------------

def test_newcomer_pages_keep_spec_numbers_in_background_ac_161_10(tmp_path, monkeypatch):  # AC-161.10
    for page in ("README.md", "docs/QUICKSTART.md", "docs/USER-JOURNEY.md", "docs/HOW-IT-WORKS.md",
                 "site/src/content/docs/get-started/local-cluster.md", "site/src/content/docs/concepts/index.md"):
        assert check_docs.is_plain(ROOT / page), page
    out = problems_in(tmp_path, monkeypatch, "# Page\n\nStaging follows dev (spec 093, AC-093.2).\n", plain=True)
    assert out and "'spec 093' on a reader page" in out[0]
    ok = "# Page\n\nStaging follows dev.\n\n## Background\n\nSee spec 093 and AC-093.2.\n"
    assert problems_in(tmp_path, monkeypatch, ok, plain=True) == []
