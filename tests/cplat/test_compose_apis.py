"""Spec 122 acceptance tests: `/component:add|set --provides NAME[:TYPE] --consumes NAME` (AC-122.50).

Contract: design.md "cplat component add|set ... --provides --consumes". Same world as the spec 114 command tests: a hand-built
gitops-app checkout with the real renderer, `gh` faked."""
import json
import re

import pytest

import gitops
from system_fixtures import ROOT, files
from test_commands_114 import APP, commit, gitops5, render_check, run, sysdoc  # noqa: F401  (gitops5 is a fixture)


@pytest.fixture()
def two(gitops5):
    """todo-api and todo-web are components of the system."""
    assert run("component", "add", "todo-api", "--repo-dir", gitops5) == 0
    commit(gitops5)
    assert run("component", "add", "todo-web", "--repo-dir", gitops5) == 0
    commit(gitops5)
    return gitops5


def test_provides_adds_a_new_api_with_the_default_type_openapi_ac_122_50(two):  # AC-122.50
    assert run("component", "set", "todo-api", "--provides", "orders", "--repo-dir", two) == 0
    doc = sysdoc(two)
    assert doc["apis"]["orders"] == {"type": "openapi"} and doc["components"]["todo-api"]["provides"] == ["orders"]
    assert render_check(two).returncode == 0
    assert "# the shop system (keep this comment)" in (two / APP / "system.yaml").read_text()


def test_provides_takes_a_type_ac_122_50(two):  # AC-122.50
    assert run("component", "set", "todo-api", "--provides", "feed:events", "--repo-dir", two) == 0
    assert sysdoc(two)["apis"]["feed"]["type"] == "events"


@pytest.mark.parametrize("kind", ["openapi", "grpc", "graphql", "events"])
def test_every_known_type_is_accepted_ac_122_50(two, kind):  # AC-122.50
    assert run("component", "set", "todo-api", "--provides", f"a:{kind}", "--repo-dir", two) == 0
    assert sysdoc(two)["apis"]["a"]["type"] == kind


def test_the_flags_are_repeatable_ac_122_50(two):  # AC-122.50
    assert run("component", "set", "todo-api", "--provides", "orders", "--provides", "feed:events", "--repo-dir", two) == 0
    api = sysdoc(two)["components"]["todo-api"]
    assert api["provides"] == ["orders", "feed"] and set(sysdoc(two)["apis"]) == {"orders", "feed"}


def test_consumes_names_an_api_somebody_provides_ac_122_50(two):  # AC-122.50
    run("component", "set", "todo-api", "--provides", "orders", "--repo-dir", two)
    commit(two)
    assert run("component", "set", "todo-web", "--consumes", "orders", "--repo-dir", two) == 0
    assert sysdoc(two)["components"]["todo-web"]["consumes"] == ["orders"]
    assert render_check(two).returncode == 0


def test_providing_the_same_api_twice_does_not_duplicate_the_name_ac_122_50(two):  # AC-122.50
    run("component", "set", "todo-api", "--provides", "orders", "--repo-dir", two)
    commit(two)
    assert run("component", "set", "todo-api", "--provides", "orders", "--repo-dir", two) == 0
    assert sysdoc(two)["components"]["todo-api"]["provides"] == ["orders"]


def test_add_takes_the_flags_too_ac_122_50(gitops5):  # AC-122.50
    assert run("component", "add", "todo-api", "--provides", "orders:grpc", "--repo-dir", gitops5) == 0
    doc = sysdoc(gitops5)
    assert doc["apis"]["orders"]["type"] == "grpc" and doc["components"]["todo-api"]["provides"] == ["orders"]


def test_a_second_provider_fails_naming_the_api_and_the_rule_and_changes_nothing_ac_122_50(two, capsys):  # AC-122.50
    run("component", "set", "todo-api", "--provides", "orders", "--repo-dir", two)
    commit(two)
    before = files(two)
    rc, _, err = run("component", "set", "todo-web", "--provides", "orders", "--repo-dir", two, capsys=capsys)
    assert rc == 1 and "orders" in err and "exactly one provider" in err
    assert files(two) == before


def test_an_unknown_type_is_refused_before_the_edit_ac_122_50(two, capsys):  # AC-122.50
    before = files(two)
    rc, _, err = run("component", "set", "todo-api", "--provides", "orders:rest", "--repo-dir", two, capsys=capsys)
    assert rc == 1 and "type must be one of openapi, grpc, graphql, events" in err and "orders" in err
    assert files(two) == before


def test_consuming_an_api_nobody_provides_fails_and_changes_nothing_ac_122_50(two, capsys):  # AC-122.50
    before = files(two)
    rc, _, err = run("component", "set", "todo-web", "--consumes", "ghost", "--repo-dir", two, capsys=capsys)
    assert rc == 1 and "ghost" in err and "provider" in err
    assert files(two) == before


def test_a_different_type_for_an_existing_api_is_an_error_ac_122_50(two, capsys):  # AC-122.50
    run("component", "set", "todo-api", "--provides", "orders:grpc", "--repo-dir", two)
    commit(two)
    before = files(two)
    rc, _, err = run("component", "set", "todo-api", "--provides", "orders:events", "--repo-dir", two, capsys=capsys)
    assert rc == 1 and "orders" in err
    assert files(two) == before


def test_the_flags_apply_to_exactly_one_component_ac_122_50(two, capsys):  # AC-122.50
    before = files(two)
    rc, _, err = run("component", "set", "todo-api", "todo-web", "--provides", "orders", "--repo-dir", two, capsys=capsys)
    assert rc != 0 and files(two) == before


def test_dry_run_json_lists_the_planned_api_changes_and_writes_nothing_ac_122_50(two, capsys):  # AC-122.50
    before = files(two)
    rc, out, _ = run("component", "set", "todo-api", "--provides", "orders:grpc", "--dry-run", "--json", "--repo-dir", two, capsys=capsys)
    assert rc == 0 and files(two) == before
    plan = json.loads(out)
    assert "orders" in json.dumps(plan["will_do"]) and "grpc" in json.dumps(plan["will_do"])


def test_one_pull_request_carries_the_change_ac_122_50(two, monkeypatch):  # AC-122.50
    seen = []
    monkeypatch.setattr(gitops, "open_pr", lambda repo, branch, title, body: seen.append((branch, title, body)) or "https://github.com/acme/shop-gitops/pull/1")
    assert run("component", "set", "todo-api", "--provides", "orders", "--pr", "--repo-dir", two) == 0
    assert len(seen) == 1


@pytest.mark.parametrize("verb", ["add", "set"])
def test_the_usage_line_names_the_flags_ac_122_50(verb):  # AC-122.50
    import yaml
    text = (ROOT / "plugins" / "component" / "commands" / f"{verb}.md").read_text()
    desc = yaml.safe_load(re.match(r"^---\n(.*?)\n---", text, re.S).group(1))["description"]
    assert len(desc) <= 260 and "--provides" in desc and "--consumes" in desc
