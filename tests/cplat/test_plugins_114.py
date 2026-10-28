"""Spec 114 acceptance tests: plugins, tombstones, docs, site, release and the e2e script
(AC-114.27, .28, .30, .31, .33, .34, .36, .50 .. .56, .59, .61 .. .66, .71).

Contract: design.md "Contract — slash commands and plugins" and the 4.7 -> 5.0 command table. Everything here reads files of the
checkout; the history files (CHANGELOG sections before 5.0, docs/specs, docs/adr, docs/e2e) are never scanned for old words.
The CHANGELOG checks read the 5.0.0 section, or `[Unreleased]` while the release has not moved the entry (the release moves it)."""
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

import core
from system_fixtures import ALLOWED_TOP, ROOT

PLUGINS = ROOT / "plugins"
NOUNS = ["system", "component", "api", "resource", "instance", "issue", "platform"]
WORKING = {
    "system": ["new", "status", "spec", "plan", "ship", "set", "restore", "autonomy"],  # spec 117: system restore; spec 124: system autonomy
    "component": ["new", "add", "set", "remove", "spec", "plan", "build", "verify", "check", "ship", "fix", "release"],
    "api": ["list"], "resource": ["add", "remove", "backup", "restore", "upgrade"],  # spec 117: resource backup, restore; spec 121: resource upgrade
    "instance": ["promote", "secret", "verify"], "issue": ["triage", "report"],
    "platform": ["doctor", "update", "fleet", "runs", "retro", "ui"],
    "cluster": ["new", "add", "remove"],   # spec 125 adds the cluster noun after 5.0
}
# the 27 slash commands of 4.7 and the new command each one names (AC-114.65 gives the special targets)
OLD_TO_NEW = {
    "/shared:check-quality": "/component:check", "/shared:doctor": "/platform:doctor", "/shared:fleet": "/platform:fleet",
    "/shared:new-app": "/system:new", "/shared:new-service": "/component:new", "/shared:report-issue": "/issue:report",
    "/shared:status": "/system:status", "/shared:triage": "/issue:triage", "/shared:update-service": "/platform:update",
    "/svc:build": "/component:build", "/svc:fix-bug": "/component:fix", "/svc:plan": "/component:plan", "/svc:quick-task": "/component:fix",
    "/svc:release": "/component:release", "/svc:ship": "/component:ship", "/svc:spec": "/component:spec", "/svc:specs": "/component:spec",
    "/svc:verify": "/component:verify", "/app:build": "/system:ship", "/app:plan": "/system:plan", "/app:ship": "/system:ship",
    "/app:spec": "/system:spec", "/app:specs": "/system:spec", "/gitops:addon": "/resource:add", "/gitops:compose": "/component:add",
    "/gitops:promote": "/instance:promote", "/gitops:secret": "/instance:secret",
}
CPLAT_MOVED = ["cplat new-app", "cplat status", "cplat app-ship", "cplat new-service", "cplat compose", "cplat ship", "cplat build", "cplat addon",
               "cplat promote", "cplat secret", "cplat smoke", "cplat triage", "cplat doctor", "cplat update-service", "cplat fleet",
               "cplat runs", "cplat retro"]


def front(path: Path) -> tuple[dict, str]:
    text = path.read_text()
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
    assert m, f"{path.relative_to(ROOT)} has no front matter"
    return yaml.safe_load(m.group(1)) or {}, m.group(2)


def command(noun: str, verb: str) -> tuple[dict, str]:
    return front(PLUGINS / noun / "commands" / f"{verb}.md")


def old_path(old: str) -> Path:
    plugin, name = old[1:].split(":")
    return PLUGINS / plugin / "commands" / f"{name}.md"


def changelog_5() -> str:
    text = (ROOT / "docs" / "CHANGELOG.md").read_text()
    m = re.search(r"^## \[5\.0\.0\].*?(?=^## \[|\Z)", text, re.S | re.M)
    if m:
        return m.group(0)
    m = re.search(r"^## \[Unreleased\].*?(?=^## \[|\Z)", text, re.S | re.M)
    assert m and "5.0" in m.group(0), "the 5.0 entry is in [5.0.0] or, before the release, in [Unreleased]"
    return m.group(0)


# ---------------- AC-114.59: the working commands ----------------

def test_exactly_the_33_working_commands_exist_ac_114_59():  # AC-114.59  (spec 122 adds /system:set and /platform:ui, spec 124 /system:autonomy)
    found = {}
    for plugin in sorted(p.name for p in PLUGINS.iterdir() if p.is_dir()):
        for f in sorted((PLUGINS / plugin / "commands").glob("*.md")) if (PLUGINS / plugin / "commands").is_dir() else []:
            fm, _ = front(f)
            if "moved-to" not in fm:
                found.setdefault(plugin, []).append(f.stem)
    assert {k: sorted(v) for k, v in found.items()} == {k: sorted(v) for k, v in WORKING.items()}
    assert sum(len(v) for v in found.values()) == 40   # spec 121: plus /resource:upgrade; 32 (5.0 plus /platform:ui and /system:set), plus /cluster:new|add|remove (spec 125), plus /resource:backup|restore and /system:restore (spec 117), plus /system:autonomy (spec 124)
    assert not (PLUGINS / "api" / "commands" / "check.md").exists()


def test_the_marketplace_lists_the_noun_plugins_ac_114_59():  # AC-114.59
    names = [p["name"] for p in json.loads((ROOT / ".claude-plugin/marketplace.json").read_text())["plugins"]]
    assert set(NOUNS) <= set(names)
    for keep in ("svc", "svc-java", "svc-go", "web"):
        assert (PLUGINS / keep / "agents").is_dir()


@pytest.mark.parametrize("noun, verb", [(n, v) for n, vs in WORKING.items() for v in vs])
def test_every_working_command_has_a_usage_line_and_runs_the_5_0_form_ac_114_59(noun, verb):  # AC-114.59
    fm, body = command(noun, verb)
    desc = fm["description"]
    assert f"Usage: /{noun}:{verb}" in desc and len(desc) <= 260 and "moved-to" not in fm
    assert "$ARGUMENTS" in body or noun in ("api",) or verb in ("status", "doctor")


# ---------------- usage lines of the commands the criteria describe ----------------

@pytest.mark.parametrize("noun, verb, needles", [
    ("instance", "promote", ["--to <env>", "--all", "--version"]),
    ("instance", "secret", ["set <component>/<env>", "list"]),
    ("instance", "verify", ["[<env>]"]),
    ("resource", "add", ["postgres", "--version"]),
    ("resource", "remove", ["postgres"]),
    ("api", "list", []),
    ("component", "new", ["--type", "--lang", "--system"]),
    ("component", "set", ["--instance", "--replicas"]),
    ("system", "new", ["<manifest>"]),
])
def test_usage_lines_name_their_arguments_ac_114_28(noun, verb, needles):  # AC-114.28 AC-114.30 AC-114.31 AC-114.33 AC-114.34 AC-114.35 AC-114.36 AC-114.61
    fm, body = command(noun, verb)
    usage = fm["description"].split("Usage:", 1)[1]
    for n in needles:
        assert n in usage, (n, usage)
    assert f"cplat {noun} " in body


def test_instance_promote_keeps_the_production_gate_ac_114_28():  # AC-114.28
    _, body = command("instance", "promote")
    assert "prod" in body and "cplat instance promote" in body and "--to" in body and "/gitops:" not in body


def test_instance_secret_set_and_list_ac_114_30():  # AC-114.30
    _, body = command("instance", "secret")
    assert "cplat instance secret set" in body and "cplat instance secret list" in body


def test_instance_verify_runs_the_components_smoke_tests_ac_114_31():  # AC-114.31
    _, body = command("instance", "verify")
    assert "cplat instance verify" in body


def test_resource_add_explains_observability_is_per_environment_ac_114_36():  # AC-114.36
    _, body = command("resource", "add")
    assert "environments.<env>.observability" in body


def test_api_list_command_ac_114_61():  # AC-114.61
    _, body = command("api", "list")
    assert "cplat api list" in body


# ---------------- AC-114.62 .. AC-114.64: fix, check, spec ----------------

def test_component_fix_is_the_quick_task_pipeline_for_changes_and_bugs_ac_114_62():  # AC-114.62
    fm, body = command("component", "fix")
    assert "coder" in body and "quality" in body and "tester" in body and "criteri" in body
    assert "bug" in (fm["description"] + body).lower() and "fix-bug" not in body and "quick-task" not in body.replace("quick-task pipeline", "")
    assert not (PLUGINS / "component" / "commands" / "fix-bug.md").exists() and not (PLUGINS / "component" / "commands" / "quick-task.md").exists()


def test_component_check_is_read_only_quality_and_security_ac_114_63():  # AC-114.63
    fm, body = command("component", "check")
    text = (fm["description"] + body).lower()
    assert "read-only" in text or "do not modify" in text
    assert "quality" in text and "security" in text and "cplat shape" in body


def test_component_spec_dispatches_on_its_first_argument_ac_114_64():  # AC-114.64
    fm, body = command("component", "spec")
    for a in ("--all", "index", "migrate", "--amend", "approve", "--from-plan"):
        assert a in body, a
    assert "show <id>" not in body and "abandon" not in body


def test_system_spec_dispatches_on_its_first_argument_ac_114_64():  # AC-114.64
    fm, body = command("system", "spec")
    for a in ("--all", "show <id>", "done <id>", "abandon <id>", "--amend", "approve"):
        assert a in body, a
    assert "--from-plan" not in body and "migrate" not in body


# ---------------- AC-114.27 / AC-114.65: tombstones ----------------

def tombstones():
    spec = importlib.util.spec_from_file_location("tombstones_under_test", ROOT / "scripts" / "tombstones.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_the_tombstone_table_has_the_27_commands_of_4_7_ac_114_27():  # AC-114.27
    moved = tombstones().MOVED
    assert sorted(moved) == sorted(OLD_TO_NEW) and len(moved) == 27
    for old, new in OLD_TO_NEW.items():
        assert moved[old].startswith(new) or new in moved[old], (old, moved[old])


@pytest.mark.parametrize("old", sorted(OLD_TO_NEW))
def test_every_old_command_is_a_tombstone_that_runs_nothing_ac_114_27(old):  # AC-114.27
    new = tombstones().MOVED[old]
    fm, body = front(old_path(old))
    assert fm["description"] == f"Moved in 5.0: {old} is {new}. Runs nothing."
    assert fm["moved-to"] == new and fm["allowed-tools"] == "Read, Glob"
    assert "Run no script, start no agent, change no file." in body
    assert f"`{old}` is `{new}` in 5.0." in body and f"`{old}` is `{new}` in 5.0; run `cplat platform update --migrate` first." in body
    assert "$ARGUMENTS" not in body and "Bash" not in body and "!`" not in body


def test_tombstones_check_is_clean_ac_114_27():  # AC-114.27
    p = subprocess.run([sys.executable, str(ROOT / "scripts" / "tombstones.py"), "check"], capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr


@pytest.mark.parametrize("old, expected", [
    ("/app:build", ["/system:ship"]), ("/svc:quick-task", ["/component:fix"]), ("/svc:fix-bug", ["/component:fix"]),
    ("/svc:specs", ["/component:spec"]), ("/app:specs", ["/system:spec"]), ("/shared:check-quality", ["/component:check"]),
    ("/gitops:addon", ["resources:", "system.yaml", "environments.<env>.observability"]),
    ("/gitops:secret", ["/instance:secret list"]),
])
def test_dropped_or_merged_commands_name_their_replacement_ac_114_65(old, expected):  # AC-114.65
    fm, _ = front(old_path(old))
    for e in expected:
        assert e in fm["moved-to"], (old, fm["moved-to"])


# ---------------- AC-114.66: plugin contents ----------------

def test_shared_holds_the_launcher_hooks_and_two_agents_only_ac_114_66():  # AC-114.66
    shared = PLUGINS / "shared"
    assert (shared / "bin" / "cplat").is_file() and (shared / "hooks" / "hooks.json").is_file()
    assert sorted(p.name for p in (shared / "agents").glob("*.md")) == ["quality.md", "security.md"]
    assert all("moved-to" in front(f)[0] for f in (shared / "commands").glob("*.md"))


def test_the_planner_moved_to_system_and_the_v1_agent_is_gone_ac_114_66():  # AC-114.66
    assert (PLUGINS / "system" / "agents" / "planner.md").is_file()
    assert not (PLUGINS / "app" / "agents").exists() and not (PLUGINS / "gitops" / "agents").exists()
    assert not (PLUGINS / "gitops" / "agents" / "deployment.md").exists()


def test_app_and_gitops_hold_only_tombstones_ac_114_66():  # AC-114.66
    for plugin in ("app", "gitops"):
        assert not (PLUGINS / plugin / "hooks").exists() and not (PLUGINS / plugin / "agents").exists()
        cmds = list((PLUGINS / plugin / "commands").glob("*.md"))
        assert cmds and all("moved-to" in front(f)[0] for f in cmds)
    for plugin in ("svc", "shared"):
        assert all("moved-to" in front(f)[0] for f in (PLUGINS / plugin / "commands").glob("*.md"))
    assert (PLUGINS / "svc" / "skills").is_dir() and list((PLUGINS / "svc" / "agents").glob("*.md"))


def test_the_changelog_says_app_and_gitops_leave_in_6_0_ac_114_66():  # AC-114.66
    text = changelog_5()
    assert re.search(r"(?s)`?app`?.{0,200}`?gitops`?.{0,200}6\.0|6\.0.{0,200}`?app`?.{0,100}`?gitops`?", text)


# ---------------- AC-114.50: versions ----------------

def test_the_marketplace_and_the_manifests_agree_ac_114_50():  # AC-114.50
    market = {p["name"]: p for p in json.loads((ROOT / ".claude-plugin/marketplace.json").read_text())["plugins"]}
    for name, entry in market.items():
        manifest = json.loads((PLUGINS / name / ".claude-plugin" / "plugin.json").read_text())
        assert manifest["version"] == entry["version"], name
    major = lambda n: core.vtuple(market[n]["version"])[0]
    for n in NOUNS:
        assert n in market and core.vtuple(market[n]["version"]) >= (1, 0, 0), n
    assert major("svc") >= 4 and major("shared") >= 1 and major("app") >= 2 and major("gitops") >= 2


def test_the_release_is_5_0_0_or_later_ac_114_50():  # AC-114.50
    assert core.vtuple(core.platform_version()) >= (5, 0, 0)
    assert "BREAKING" in changelog_5()


def test_the_gitops_app_shape_belongs_to_the_system_plugin_ac_114_50():  # AC-114.50
    shapes = yaml.safe_load((ROOT / "shapes.yml").read_text())["shapes"]
    assert next(s for s in shapes if s["id"] == "gitops-app")["plugin"] == "system"


# ---------------- AC-114.51: the CHANGELOG ----------------

def test_the_changelog_has_the_old_to_new_table_and_the_migration_steps_ac_114_51():  # AC-114.51
    text = changelog_5()
    assert "BREAKING" in text
    for old, new in OLD_TO_NEW.items():
        row = next((ln for ln in text.splitlines() if ln.startswith("|") and f"`{old}`" in ln), None)
        assert row, f"no table row for {old}"
        assert new.split("|")[0] in row, (old, row)
    for name in CPLAT_MOVED:
        assert any(ln.startswith("|") and f"`{name}`" in ln for ln in text.splitlines()), name
    for key in ("app.yaml", "services.yaml", "hosts", "urls", "policies.mode", "promotion", "addons.observability", "addons.postgres", "shape"):
        assert any(ln.startswith("|") and key in ln for ln in text.splitlines()), key
    assert "cplat platform update --migrate" in text and "/platform:fleet update" in text
    assert text.index("cplat platform update --migrate") > text.rindex("|")


# ---------------- AC-114.52: the same words everywhere ----------------

HISTORY_SECTIONS = {"docs/ADOPTING.md": ("Migrating from 4.x to 5.0",)}
OLD_COMMAND = re.compile(r"/(svc|app|gitops|shared):[a-z]|\bcplat (" + "|".join(n.split()[1] for n in CPLAT_MOVED) + r")\b|\bapp\.yaml\b|\bservices\.yaml\b")
OLD_NOUN = re.compile(r"(?<![\w/-])addons?(?![\w/-])|(?<![\w/-])product\b(?![ -](manager|owner|requirement|management|names))", re.I)


def in_scope() -> list[Path]:
    out: list[Path] = []
    for plugin in PLUGINS.iterdir():
        for sub in ("agents", "skills", "references"):
            out += [p for p in (plugin / sub).rglob("*.md")] if (plugin / sub).is_dir() else []
        if plugin.name in NOUNS:
            out += list((plugin / "commands").glob("*.md")) + [plugin / "README.md"]
        elif (plugin / "commands").is_dir():
            out += [f for f in (plugin / "commands").glob("*.md") if "moved-to" not in front(f)[0]]
    for t in (ROOT / "templates").iterdir():
        out += [p for p in t.rglob("*") if p.is_file() and (p.name.startswith(("CLAUDE.md", "README.md")) or "docs" in p.relative_to(t).parts[:1]) and p.suffix in (".md", ".jinja")]
    docs = ROOT / "docs"
    out += [p for p in docs.glob("*.md") if p.name not in ("CHANGELOG.md", "backlog.md")]
    for sub in ("plan", "requirements", "spikes"):
        out += list((docs / sub).rglob("*.md"))
    out += [docs / "img" / "sdlc-map.svg", docs / "img" / "model-lifecycles.svg"]
    out += [ROOT / n for n in ("README.md", "CONTRIBUTING.md", "CLAUDE.md")]
    out += [p for p in (ROOT / "site" / "src" / "content" / "docs").rglob("*") if p.suffix in (".md", ".mdx") and "reference" not in p.relative_to(ROOT).parts]
    return sorted({p for p in out if p.is_file()})


SYNCED = {f"site/src/content/docs/{slug}.md": src for src, slug in
          re.findall(r"src: '([^']+)', slug: '([^']+)'", (ROOT / "site" / "scripts" / "sync-docs.mjs").read_text())}


def hits(path: Path) -> list[str]:
    shown = path.relative_to(ROOT).as_posix()
    rel = SYNCED.get(shown, shown)   # a page the site build copied from the repo is judged as its source
    skip = False
    out = []
    for i, line in enumerate(path.read_text().splitlines(), 1):
        if path.suffix == ".md" and rel in HISTORY_SECTIONS and line.startswith("## "):
            skip = any(h in line for h in HISTORY_SECTIONS[rel])
        if skip or (rel == "docs/DOMAIN-MODEL.md" and line.startswith("|")):
            continue
        for rx in (OLD_COMMAND, OLD_NOUN):
            m = rx.search(line)
            if m:
                out.append(f"{shown}:{i}: {m.group(0)!r}")
    return out


def test_no_prompt_command_doc_or_site_page_names_a_4x_thing_ac_114_52():  # AC-114.52
    scope = in_scope()
    assert len(scope) > 60, "the scan must cover plugins, templates, docs and the site"
    found = [h for p in scope for h in hits(p)]
    assert found == [], f"{len(found)} hits:\n" + "\n".join(found[:80])


# ---------------- AC-114.53: the site command reference ----------------

def test_the_command_reference_is_grouped_by_noun_without_tombstones_ac_114_53():  # AC-114.53
    src = (ROOT / "site" / "scripts" / "generate-reference.mjs").read_text()
    assert "moved-to" in src
    order = [src.index(f"'{n}'") if f"'{n}'" in src else src.index(f'"{n}"') for n in NOUNS]
    assert order == sorted(order), "the nouns are listed in the order system, component, api, resource, instance, issue, platform"
    assert "services.yaml" not in src and "app.yaml" not in src
    nm = ROOT / "site" / "node_modules" / "yaml"
    if nm.is_dir():
        p = subprocess.run(["node", "site/scripts/generate-reference.mjs"], cwd=ROOT, capture_output=True, text=True)
        assert p.returncode == 0, p.stderr
        page = (ROOT / "site/src/content/docs/reference/commands.md").read_text()
        heads = [page.index(f"## {n}") for n in NOUNS]
        assert heads == sorted(heads) and "/svc:ship" not in page and "| `/instance:promote` |" in page


# ---------------- AC-114.54 / AC-114.71: DOMAIN-MODEL and ADOPTING ----------------

def domain() -> str:
    return (ROOT / "docs" / "DOMAIN-MODEL.md").read_text()


def example() -> dict:
    sec = domain().split("## One file per system", 1)[1]
    block = re.search(r"```yaml\n(.*?)```", sec, re.S).group(1)
    return yaml.safe_load(block)


def test_the_status_says_5_0_is_current_ac_114_54():  # AC-114.54
    status = next(ln for ln in domain().splitlines() if ln.startswith("**Status:**"))
    assert "5.0" in status and "current" in status and "target model" not in status
    assert "not the final schema" not in domain()


def test_the_full_example_uses_the_final_schema_ac_114_71():  # AC-114.71
    doc = example()
    assert set(doc) <= set(ALLOWED_TOP.split(", ")) and isinstance(doc["owner"], str) and doc["owner"].strip()
    assert list(doc["environments"]) == ["dev", "staging", "prod"]
    assert all(set(e) <= {"host", "url", "policy", "promote", "observability"} for e in doc["environments"].values())
    comps = doc["components"]
    assert any(set(c.get("instances") or {}) == {"dev", "staging", "prod"} for c in comps.values() if c["type"] != "library"), \
        "a component running in dev, staging and prod lists all three instance keys"
    assert all(set(c.get("instances") or {}) <= {"dev", "staging", "prod"} for c in comps.values())
    assert any(c["type"] == "website" and c["lang"] == "typescript" for c in comps.values())
    pg = doc["resources"]["postgres"]
    text = json.dumps(pg)
    assert "replicas" in text and "size" not in pg.get("instances", {}).get("prod", {})
    assert doc["apis"] and all(a["type"] in ("openapi", "grpc", "graphql", "events") for a in doc["apis"].values())


def test_the_command_tables_list_api_list_check_and_fix_ac_114_71():  # AC-114.71
    text = domain()
    table = text.split("## Commands follow the nouns", 1)[1].split("\n## ", 1)[0]
    api = next(ln for ln in table.splitlines() if ln.startswith("| `api`"))
    assert "`list`" in api and ("`check`" not in api or "spec 110" in api)
    comp = next(ln for ln in table.splitlines() if ln.startswith("| `component`"))
    assert "`check`" in comp and "`fix`" in comp
    assert re.search(r"(?s)fix.{0,300}quick-task|quick-task.{0,300}fix", table + text)
    assert "spec 110" in text
    assert not [ln for ln in text.splitlines() if "/api:check" in ln and "spec 110" not in ln and "coming" not in ln]


def test_adopting_has_the_migration_section_ac_114_54():  # AC-114.54
    text = (ROOT / "docs" / "ADOPTING.md").read_text()
    assert "## Migrating from 4.x to 5.0" in text
    sec = text.split("## Migrating from 4.x to 5.0", 1)[1].split("\n## ", 1)[0]
    assert "cplat platform update --migrate" in sec and "/platform:fleet update" in sec and "byte" in sec and "app@sdlc-foundry" in sec


# ---------------- AC-114.55: the spec-first rule of the templates ----------------

@pytest.mark.parametrize("template", sorted(p.name for p in (ROOT / "templates").iterdir() if p.is_dir()))
def test_every_template_names_the_5_0_spec_command_ac_114_55(template):  # AC-114.55
    f = next(p for p in (ROOT / "templates" / template).glob("CLAUDE.md*"))
    text = f.read_text()
    want = "/system:spec" if template == "gitops-app" else "/component:spec"
    assert want in text and "/svc:spec" not in text and "/app:spec" not in text


def test_the_shape_registry_check_passes_with_the_5_0_rule_ac_114_55():  # AC-114.55
    p = subprocess.run([sys.executable, str(ROOT / "scripts" / "shapes.py"), "check"], cwd=ROOT, capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
    src = (ROOT / "scripts" / "shapes.py").read_text()
    assert "/component:spec" in src and "/system:spec" in src and "/svc:spec" not in src


# ---------------- AC-114.56: the end-to-end cluster test ----------------

def test_the_e2e_script_uses_only_5_0_names_and_a_system_yaml_ac_114_56():  # AC-114.56
    text = (ROOT / "tests" / "e2e" / "run.sh").read_text()
    for needle in ("system new", "resource add postgres", "component ship start", "component ship finish", "instance verify dev",
                   "instance promote e2e-api --to staging", "instance verify staging", "instance secret set e2e-api/dev", "system.yaml"):
        assert needle in text, needle
    bad = [f"{i}: {m.group(0)}" for i, ln in enumerate(text.splitlines(), 1) for m in [OLD_COMMAND.search(ln)] if m]
    assert bad == [] and "--gitops" not in text and "--type service-" not in text
