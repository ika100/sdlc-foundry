"""Spec 122 acceptance tests: the forms of "Add to the model" show the command, the diff and the checks before anything runs
(AC-122.20, and the model parts of AC-122.18, AC-122.34, AC-122.35, AC-122.50, AC-122.51).

Contract: design.md Decisions (every form runs a real command; the preview runs it on a scratch copy and applies no rule of its own)
and plan t9: `console.preview.preview(snapshot_dir, form, fields) -> {"command", "diff", "checks", "valid", "consequence", "way_back"}`.
Form fields assumed by the tests: component {action, component}; api {action, component, provides[], consumes[]}; resource {action, resource};
environment {env, promote?, policy?, host?}. The world is the spec 114 gitops-app checkout (real renderer, `gh` faked)."""
import re

import pytest

from console_support import ROOT, STATIC, q
from system_fixtures import files
from test_commands_114 import APP, commit, gitops5, run, sysdoc  # noqa: F401  (gitops5 is a fixture)


def preview(repo, form, **fields):
    from console import preview as pv
    return pv.preview(repo, form, fields)


def failing(res):
    return [c for c in res["checks"] if not c["ok"]]


def test_an_environment_form_shows_the_exact_command_and_the_diff_ac_122_20(gitops5):  # AC-122.20
    before = files(gitops5)
    res = preview(gitops5, "environment", env="staging", promote="manual")
    assert res["command"] == "/system:set --env staging --promote manual"
    assert res["valid"] is True and not failing(res) and all({"key", "rule", "ok"} <= set(c) for c in res["checks"])
    assert re.search(r"^\+\s+promote: manual", res["diff"], re.M) and res["diff"].count("\n+++ ") == 1
    assert files(gitops5) == before                                  # the repo is untouched: the command ran on a scratch copy


def test_an_invalid_value_names_the_key_and_the_rule_and_is_not_valid_ac_122_20(gitops5):  # AC-122.20
    res = preview(gitops5, "environment", env="prod", promote="after-dev-smoke")
    assert res["valid"] is False
    [bad] = failing(res)
    assert "environments.prod.promote" in bad["key"] and "manual" in bad["rule"]
    assert res["command"].startswith("/system:set --env prod")


def test_the_preview_is_recomputed_for_every_change_ac_122_20(gitops5):  # AC-122.20
    a = preview(gitops5, "environment", env="staging", promote="manual")
    b = preview(gitops5, "environment", env="staging", promote="after-dev-smoke")
    c = preview(gitops5, "environment", env="staging", promote="manual", policy="enforce")
    assert a["diff"] != b["diff"] and a["diff"] != c["diff"] and "policy" in c["diff"] and "policy" not in a["diff"]
    assert preview(gitops5, "environment", env="staging", policy="strict")["valid"] is False


def test_the_checks_are_the_renderers_not_the_previews_own_ac_122_20(gitops5):  # AC-122.20
    run("component", "add", "todo-api", "--repo-dir", gitops5)
    commit(gitops5)
    res = preview(gitops5, "api", action="set", component="todo-api", provides=[], consumes=["ghost"])
    [bad] = failing(res)
    assert "apis.ghost" in bad["key"] and "provider" in bad["rule"]


def test_a_component_form_shows_command_diff_and_what_renders_ac_122_20(gitops5):  # AC-122.20
    res = preview(gitops5, "component", action="add", component="todo-api")
    assert res["command"] == "/component:add todo-api" and res["valid"] is True
    assert "todo-api" in res["diff"] and re.search(r"^\+", res["diff"], re.M)
    assert not (gitops5 / APP / "overlays" / "dev" / "todo-api").exists()


def test_a_resource_form_runs_resource_add_ac_122_20(gitops5):  # AC-122.20
    res = preview(gitops5, "resource", action="add", resource="postgres")
    assert res["command"] == "/resource:add postgres" and res["valid"] is True and "postgres" in res["diff"]


def test_a_resource_the_command_refuses_is_reported_with_its_message_ac_122_20(gitops5):  # AC-122.20
    res = preview(gitops5, "resource", action="add", resource="redis")
    assert res["valid"] is False and "--type is required for redis" in str(res["checks"])


def test_the_api_form_runs_provides_and_consumes_ac_122_50(gitops5):  # AC-122.50
    run("component", "add", "todo-api", "--repo-dir", gitops5)
    commit(gitops5)
    res = preview(gitops5, "api", action="set", component="todo-api", provides=["orders:grpc"], consumes=[])
    assert res["command"] == "/component:set todo-api --provides orders:grpc"
    assert res["valid"] is True and "orders" in res["diff"] and "grpc" in res["diff"]


def test_the_api_form_shows_a_second_provider_as_a_failed_check_ac_122_50(gitops5):  # AC-122.50
    for name in ("todo-api", "todo-web"):
        run("component", "add", name, "--repo-dir", gitops5)
        commit(gitops5)
    run("component", "set", "todo-api", "--provides", "orders", "--repo-dir", gitops5)
    commit(gitops5)
    res = preview(gitops5, "api", action="set", component="todo-web", provides=["orders"], consumes=[])
    assert res["valid"] is False
    [bad] = failing(res)
    assert "orders" in bad["key"] and "exactly one provider" in bad["rule"]


def test_the_api_form_offers_consumes_too_ac_122_50(gitops5):  # AC-122.50
    for name in ("todo-api", "todo-web"):
        run("component", "add", name, "--repo-dir", gitops5)
        commit(gitops5)
    run("component", "set", "todo-api", "--provides", "orders", "--repo-dir", gitops5)
    commit(gitops5)
    res = preview(gitops5, "api", action="set", component="todo-web", provides=[], consumes=["orders"])
    assert res["command"] == "/component:set todo-web --consumes orders" and res["valid"] is True


def test_the_environment_form_runs_system_set_ac_122_51(gitops5):  # AC-122.51
    res = preview(gitops5, "environment", env="staging", policy="enforce", host="{component}.{system}-stg.example.com")
    assert res["command"] == "/system:set --env staging --policy enforce --host {component}.{system}-stg.example.com"
    assert res["valid"] is True


def test_a_change_to_the_model_names_the_repos_prs_and_environments_ac_122_34(gitops5):  # AC-122.34
    res = preview(gitops5, "environment", env="staging", promote="manual")
    text = str(res["consequence"]).lower()
    assert "pull request" in text and "staging" in text


def test_adding_a_component_names_the_environments_that_render_it_ac_122_34(gitops5):  # AC-122.34
    text = str(preview(gitops5, "component", action="add", component="todo-api")["consequence"])
    assert "dev" in text


def test_the_way_back_of_a_model_change_is_closing_its_pull_request_or_the_remove_command_ac_122_35(gitops5):  # AC-122.35
    add = str(preview(gitops5, "component", action="add", component="todo-api")["way_back"])
    assert "pull request" in add.lower() and "/component:remove todo-api" in add
    res = str(preview(gitops5, "resource", action="add", resource="postgres")["way_back"])
    assert "/resource:remove postgres" in res
    env = str(preview(gitops5, "environment", env="staging", promote="manual")["way_back"])
    assert "pull request" in env.lower()


def test_the_preview_route_returns_the_same_document_ac_122_20(console, gitops5):  # AC-122.20
    c = console(repo_dir=gitops5)
    st, body = c.json("POST", "/api/preview", {"form": "environment", "fields": {"env": "staging", "promote": "manual"}})
    assert st == 200 and body["command"] == "/system:set --env staging --promote manual" and body["valid"] is True
    st, body = c.json("POST", "/api/preview", {"form": "environment", "fields": {"env": "prod", "promote": "sometimes"}})
    assert st == 200 and body["valid"] is False
    assert c.json("POST", "/api/preview", {"form": "nonsense", "fields": {}})[0] == 400
    assert c.json("POST", "/api/preview", {"form": "environment", "fields": {}}, token=False)[0] == 403


def test_a_form_starts_with_its_confirm_button_disabled_ac_122_20(console):  # AC-122.20
    root, _ = console().page("/system")
    forms = q(root, None, data_form=True)
    assert len(forms) == 5
    for f in forms:
        confirm = q(f, "button", data_action="model")
        assert len(confirm) == 1 and "disabled" in confirm[0].attrs and confirm[0].attrs.get("aria-disabled") == "true"
        assert q(f, "code", data_command=True) or q(f, None, data_preview=True)


def test_the_script_asks_for_a_new_preview_on_every_field_change_ac_122_20():  # AC-122.20
    t = (STATIC / "console.js").read_text()
    assert "/api/preview" in t and re.search(r"addEventListener\(\s*[\"'](input|change)[\"']", t)


def test_the_preview_runs_the_real_command_on_a_scratch_copy_ac_122_18():  # AC-122.18
    text = (ROOT / "scripts" / "cplat" / "console" / "preview.py").read_text()
    assert re.search(r"tempfile|mkdtemp|copytree", text)
