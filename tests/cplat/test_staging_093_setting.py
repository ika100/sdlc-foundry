"""Spec 093 acceptance tests, the setting and the static artefacts: `promotion.staging` validation in render.py (AC-093.13), the
app-wide default and per-service override (AC-093.15), the pin-staging workflow (AC-093.1, .5, .6, .7), the docs (AC-093.14) and
the ADR (AC-093.16). Contract: design.md "Setting", "Dispatch and the workflow". `staging` is imported inside the tests: it does
not exist yet."""
import importlib
import re
import subprocess

import pytest
import yaml

import core
from model_fixtures import model
from test_gitops import commit, composed_todo_api, gh, gitops_repo, run_compose, system_file  # noqa: F401  (fixtures)

ROOT = core.PLATFORM_ROOT
APP = "applications/todo"
TPL = ROOT / "templates" / "gitops-app"


def staging_mod():
    return importlib.import_module("staging")


def render(repo):
    return subprocess.run(["uv", "run", "scripts/render.py"], cwd=repo, capture_output=True, text=True)


def set_env(repo, env, **extra):
    """Set keys of `environments.<env>` in system.yaml."""
    f = system_file(repo)
    cfg = yaml.safe_load(f.read_text())
    cfg["environments"][env].update(extra)
    f.write_text(yaml.safe_dump(cfg, sort_keys=False))


def set_instance(repo, env, **extra):
    """Set keys of `components.todo-api.instances.<env>` (the instance is created when missing)."""
    f = system_file(repo)
    d = yaml.safe_load(f.read_text())
    d["components"]["todo-api"]["instances"].setdefault(env, {}).update(extra)
    f.write_text(yaml.safe_dump(d, sort_keys=False))


@pytest.fixture()
def app(tmp_path, new_service, shared_renders, gh):
    return composed_todo_api(tmp_path, new_service, shared_renders)


# ---------------- AC-093.15: where the setting lives and what it defaults to ----------------

def test_a_generated_gitops_app_has_staging_promotion_on_app_wide_ac_093_15(gitops_repo):  # AC-093.15
    cfg = yaml.safe_load(system_file(gitops_repo).read_text())
    assert cfg["environments"]["staging"]["promote"] == "after-dev-smoke"


def test_system_yaml_is_project_owned_so_an_update_never_switches_it_on_ac_093_15():  # AC-093.15
    skip = yaml.safe_load((TPL / "copier.yml").read_text())["_skip_if_exists"]
    assert "applications/**/system.yaml" in skip
    assert "applications/**/app.yaml" not in skip and "applications/**/services.yaml" not in skip      # 4.x files


@pytest.mark.parametrize("env_promote, instance_promote, want", [
    (None, None, False),                                  # nothing set: off
    ("after-dev-smoke", None, True),                      # app-wide (the staging environment) on
    ("manual", None, False),
    ("after-dev-smoke", "manual", False),                 # the component's instance wins
    ("manual", "after-dev-smoke", True),
    (None, "after-dev-smoke", True),
])
def test_effective_setting_is_the_instance_then_the_environment_then_off_ac_093_15(env_promote, instance_promote, want):  # AC-093.15
    doc = {"system": "todo", "owner": "acme",
           "environments": {"dev": {}, "staging": {"promote": env_promote} if env_promote else {}, "prod": {}},
           "components": {"api": {"type": "service", "lang": "python", "repo": "acme/api",
                                  "instances": {"dev": {}, "staging": {"promote": instance_promote} if instance_promote else {}}}}}
    m = model().build(doc, "todo")
    assert (m.staging_promotion(m.component("api")) == "after-dev-smoke") is want


def test_the_templates_document_the_key_ac_093_15():  # AC-093.15
    text = (TPL / "applications" / "{{ app_name }}" / "system.yaml.jinja").read_text()
    assert "promote" in text and "after-dev-smoke" in text


def test_a_valid_setting_renders_at_both_levels_ac_093_15(app):  # AC-093.15
    set_env(app, "staging", promote="after-dev-smoke")
    set_instance(app, "staging", promote="manual")
    p = render(app)
    assert p.returncode == 0, p.stderr


# ---------------- AC-093.13: prod is never automatic ----------------

@pytest.mark.parametrize("value", ["auto", True, "yes", {"auto": True}])
def test_an_automatic_prod_on_the_environment_is_rejected_ac_093_13(app, value):  # AC-093.13
    set_env(app, "prod", promote=value)
    p = render(app)
    assert p.returncode == 1
    assert "environments.prod.promote: prod is always promoted by hand (manual)" in p.stderr


def test_an_automatic_prod_on_a_component_is_rejected_and_names_it_ac_093_13(app):  # AC-093.13
    set_instance(app, "prod", promote="auto")
    p = render(app)
    assert p.returncode == 1
    assert "components.todo-api.instances.prod.promote: prod is always promoted by hand (manual), got 'auto'" in p.stderr


def test_prod_manual_is_accepted_ac_093_13(app):  # AC-093.13
    set_env(app, "staging", promote="after-dev-smoke")
    set_env(app, "prod", promote="manual")
    assert render(app).returncode == 0


def test_other_invalid_values_are_rejected_with_their_own_messages_ac_093_13(app):  # AC-093.13
    set_env(app, "staging", promote="always")
    assert "environments.staging.promote must be after-dev-smoke or manual, got 'always'" in render(app).stderr
    set_env(app, "staging", promote="manual")
    set_env(app, "dev", promote="after-dev-smoke")
    assert "environments.dev.promote: dev follows main and takes no promote" in render(app).stderr
    f = system_file(app)
    doc = yaml.safe_load(f.read_text())
    del doc["environments"]["dev"]["promote"]
    doc["components"]["todo-api"]["promotion"] = {"staging": "auto"}          # the 4.x per-service key
    f.write_text(yaml.safe_dump(doc, sort_keys=False))
    assert "components.todo-api: promotion is replaced by instances.<env>.promote in 5.0" in render(app).stderr


def test_no_platform_workflow_pins_prod_ac_093_13():  # AC-093.13
    text = (TPL / ".github" / "workflows" / "pin-staging.yml").read_text()
    assert "pin.py prod" not in text and "pin.py staging" in text
    assert "overlays/prod" not in text


# ---------------- the pin-staging workflow, checked statically ----------------

def workflow():
    return (TPL / ".github" / "workflows" / "pin-staging.yml").read_text()


def test_the_workflow_is_triggered_by_the_dispatch_and_named_for_ship_ac_093_1():  # AC-093.1
    text = workflow()
    doc = yaml.safe_load(text)
    on = doc.get("on") or doc.get(True)
    assert on["repository_dispatch"]["types"] == ["pin-staging"]
    assert "run-name: pin-staging ${{ github.event.client_payload.service }} ${{ github.event.client_payload.tag }}" in text
    assert "group: pin-staging-${{ github.event.client_payload.service }}" in text
    assert list(doc["jobs"]) == ["pin", "ci", "merge"]
    assert doc["jobs"]["ci"]["uses"] == "./.github/workflows/ci.yml"


def test_every_action_is_pinned_by_sha_like_pin_dev_ac_093_1():  # AC-093.1
    uses = re.findall(r"^\s*-?\s*uses:\s*(\S+)", workflow(), re.M)
    assert uses
    for u in uses:
        assert u.startswith("./") or re.fullmatch(r".+@[0-9a-f]{40}", u), u


def test_the_workflow_validates_its_inputs_and_pins_staging_ac_093_1():  # AC-093.1
    text = workflow()
    assert "^[a-z0-9][a-z0-9-]*$" in text and "^sha-[0-9a-f]{40}$" in text and re.search(r"https://github\.com/", text)   # a text check, not URL sanitising (CodeQL)
    assert "scripts/pin.py staging" in text and "render.py --check" in text


def test_the_pr_says_it_is_automatic_and_names_what_changed_ac_093_7():  # AC-093.7
    text = workflow()
    assert "chore(staging): promote" in text and "(automatic, spec 093)" in text
    assert "Opened automatically under spec 093" in text
    for needle in ("staging ran before", "dev smoke", "run record", "Revert this PR to put staging back on"):
        assert needle in text, needle
    assert "pin/staging-" in text


def test_a_newer_promotion_closes_the_older_open_ones_ac_093_5():  # AC-093.5
    text = workflow()
    assert "Superseded by" in text and "a newer build" in text and "--delete-branch" in text


def test_a_red_ci_leaves_the_pr_open_with_a_comment_ac_093_6():  # AC-093.6
    text = workflow()
    assert "CI on this promotion ended with" in text and "so it was not merged and staging keeps" in text
    assert "exit 1" in text


# ---------------- AC-093.14: the docs describe the mechanism ----------------

DOC_FILES = [      # 5.0: /gitops:promote is /instance:promote; the gitops deployment agent is gone
    "docs/USER-JOURNEY.md", "docs/HOW-IT-WORKS.md", "templates/gitops-app/CLAUDE.md.jinja",
    "plugins/instance/commands/promote.md",
]


@pytest.mark.parametrize("rel", DOC_FILES)
def test_no_document_says_staging_is_never_auto_merged_ac_093_14(rel):  # AC-093.14
    text = (ROOT / rel).read_text()
    assert not re.search(r"never auto-?merged", text, re.I), rel


@pytest.mark.parametrize("rel", ["docs/USER-JOURNEY.md", "docs/HOW-IT-WORKS.md", "templates/gitops-app/CLAUDE.md.jinja",
                                 "plugins/instance/commands/promote.md"])
def test_the_documents_describe_automatic_staging_and_how_to_switch_it_off_ac_093_14(rel):  # AC-093.14
    text = (ROOT / rel).read_text()
    assert "pin-staging" in text or "spec 093" in text or "ADR-041" in text, rel
    assert "promote: manual" in text, rel


def test_the_promote_command_describes_the_prod_evidence_summary_ac_093_14():  # AC-093.14
    text = (ROOT / "plugins/instance/commands/promote.md").read_text()
    assert "evidence" in text.lower() and "smoke" in text.lower()


# ---------------- AC-093.16: the ADR ----------------

def test_the_adr_is_indexed_and_amends_adr_027_ac_093_16():  # AC-093.16
    readme = (ROOT / "docs/adr/README.md").read_text()
    assert re.search(r"\[?041\]?.*041-staging-follows-green-dev-smoke\.md", readme)
    adr = (ROOT / "docs/adr/041-staging-follows-green-dev-smoke.md").read_text()
    assert "Amends:" in adr and "027" in adr.splitlines()[3] and "manual" in adr


def test_adr_027_links_to_the_new_adr_ac_093_16():  # AC-093.16
    text = (ROOT / "docs/adr/027-dev-follows-main-through-pin-prs.md").read_text()
    assert "041-staging-follows-green-dev-smoke.md" in text
