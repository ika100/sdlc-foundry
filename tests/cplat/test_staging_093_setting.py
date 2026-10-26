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
from test_gitops import composed_todo_api, gh, gitops_repo, run_compose, commit  # noqa: F401  (fixtures)

ROOT = core.PLATFORM_ROOT
APP = "applications/todo"
TPL = ROOT / "templates" / "gitops-app"


def staging_mod():
    return importlib.import_module("staging")


def render(repo):
    return subprocess.run(["uv", "run", "scripts/render.py"], cwd=repo, capture_output=True, text=True)


def set_app(repo, **extra):
    f = repo / APP / "app.yaml"
    cfg = yaml.safe_load(f.read_text()) or {}
    cfg.update(extra)
    f.write_text(yaml.safe_dump(cfg))


def set_service(repo, **extra):
    f = repo / APP / "services.yaml"
    d = yaml.safe_load(f.read_text())
    d["services"][0].update(extra)
    f.write_text(yaml.safe_dump(d))


@pytest.fixture()
def app(tmp_path, new_service, shared_renders, gh):
    return composed_todo_api(tmp_path, new_service, shared_renders)


# ---------------- AC-093.15: where the setting lives and what it defaults to ----------------

def test_a_generated_gitops_app_has_staging_promotion_on_app_wide_ac_093_15(gitops_repo):  # AC-093.15
    cfg = yaml.safe_load((gitops_repo / APP / "app.yaml").read_text())
    assert cfg["promotion"] == {"staging": "auto"}


def test_app_yaml_is_project_owned_so_an_update_never_switches_it_on_ac_093_15():  # AC-093.15
    skip = yaml.safe_load((TPL / "copier.yml").read_text())["_skip_if_exists"]
    assert "applications/**/app.yaml" in skip and "applications/**/services.yaml" in skip


@pytest.mark.parametrize("app_cfg, entry, want", [
    ({}, {}, False),                                                             # nothing set: off
    ({"promotion": {"staging": "auto"}}, {}, True),                              # app-wide on
    ({"promotion": {"staging": "manual"}}, {}, False),
    ({"promotion": {"staging": "auto"}}, {"promotion": {"staging": "manual"}}, False),   # the service wins
    ({"promotion": {"staging": "manual"}}, {"promotion": {"staging": "auto"}}, True),
    ({}, {"promotion": {"staging": "auto"}}, True),
    ({"promotion": {}}, {"promotion": {}}, False),
])
def test_effective_setting_is_the_entry_then_the_app_then_off_ac_093_15(app_cfg, entry, want):  # AC-093.15
    assert staging_mod().effective(app_cfg, entry) is want


def test_the_templates_document_the_key_ac_093_15():  # AC-093.15
    services = (TPL / "applications" / "{{ app_name }}" / "services.yaml.jinja").read_text()
    appy = (TPL / "applications" / "{{ app_name }}" / "app.yaml.jinja").read_text()
    assert "promotion" in services and "promotion" in appy


def test_a_valid_setting_renders_at_both_levels_ac_093_15(app):  # AC-093.15
    set_app(app, promotion={"staging": "auto"})
    set_service(app, promotion={"staging": "manual"})
    p = render(app)
    assert p.returncode == 0, p.stderr


# ---------------- AC-093.13: prod is never automatic ----------------

@pytest.mark.parametrize("value", ["auto", True, "yes", {"auto": True}])
def test_an_automatic_prod_in_app_yaml_is_rejected_ac_093_13(app, value):  # AC-093.13
    set_app(app, promotion={"staging": "auto", "prod": value})
    p = render(app)
    assert p.returncode == 1
    assert "app.yaml: promotion.prod: prod is promoted only by /gitops:promote" in p.stderr


def test_an_automatic_prod_on_a_service_is_rejected_and_names_it_ac_093_13(app):  # AC-093.13
    set_service(app, promotion={"prod": "auto"})
    p = render(app)
    assert p.returncode == 1
    assert "services.yaml (todo-api): promotion.prod: prod is promoted only by /gitops:promote" in p.stderr
    assert "never automatically (spec 093)" in p.stderr


def test_prod_manual_is_accepted_ac_093_13(app):  # AC-093.13
    set_app(app, promotion={"staging": "auto", "prod": "manual"})
    assert render(app).returncode == 0


def test_other_invalid_values_are_rejected_with_their_own_messages_ac_093_13(app):  # AC-093.13
    set_app(app, promotion="auto")
    assert "app.yaml: promotion must be a mapping, e.g. {staging: auto}" in render(app).stderr
    set_app(app, promotion={"staging": "always"})
    assert "app.yaml: promotion.staging must be auto or manual, got 'always'" in render(app).stderr
    set_app(app, promotion={"dev": "auto"})
    assert "app.yaml: promotion.dev is not a setting (only staging; dev always follows main)" in render(app).stderr


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

DOC_FILES = [
    "docs/USER-JOURNEY.md", "docs/HOW-IT-WORKS.md", "templates/gitops-app/CLAUDE.md.jinja",
    "plugins/gitops/commands/promote.md", "plugins/gitops/agents/deployment.md",
]


@pytest.mark.parametrize("rel", DOC_FILES)
def test_no_document_says_staging_is_never_auto_merged_ac_093_14(rel):  # AC-093.14
    text = (ROOT / rel).read_text()
    assert not re.search(r"never auto-?merged", text, re.I), rel


@pytest.mark.parametrize("rel", ["docs/USER-JOURNEY.md", "docs/HOW-IT-WORKS.md", "templates/gitops-app/CLAUDE.md.jinja",
                                 "plugins/gitops/commands/promote.md"])
def test_the_documents_describe_automatic_staging_and_how_to_switch_it_off_ac_093_14(rel):  # AC-093.14
    text = (ROOT / rel).read_text()
    assert "pin-staging" in text or "spec 093" in text or "ADR-041" in text, rel
    assert re.search(r"promotion:\s*\{\s*staging:\s*manual\s*\}", text) or "staging: manual" in text, rel


def test_the_promote_command_describes_the_prod_evidence_summary_ac_093_14():  # AC-093.14
    text = (ROOT / "plugins/gitops/commands/promote.md").read_text()
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
