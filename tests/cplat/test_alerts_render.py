"""Spec 092: `render.py` of the gitops-app validates the alert settings under the observability addon, so a broken rule makes
the repo's quality gate red (AC-092.6). Real `scripts/render.py` runs in a generated repo; nothing reaches the network."""
import subprocess

import pytest
import yaml

from test_gitops import commit, composed_todo_api, gh, render_check  # noqa: F401  (fixtures)

APP = "applications/todo"
GOOD = {"name": "HighErrorRate", "query": "up == 0", "severity": "warning", "summary": "down"}


def obs(repo, **conf):
    f = repo / APP / "app.yaml"
    cfg = yaml.safe_load(f.read_text()) or {}
    cfg.setdefault("addons", {})["observability"] = conf
    f.write_text(yaml.safe_dump(cfg))


def render(repo):
    return subprocess.run(["uv", "run", "scripts/render.py"], cwd=repo, capture_output=True, text=True)


@pytest.fixture()
def repo(tmp_path, new_service, shared_renders, gh):  # noqa: F811
    return composed_todo_api(tmp_path, new_service, shared_renders)


@pytest.mark.parametrize("rules, message", [
    ([{"query": "up == 0", "severity": "warning"}], "observability.rules[0] (no name): a rule needs a name"),
    ([{"name": "", "query": "up == 0", "severity": "warning"}], "observability.rules[0] (no name): a rule needs a name"),
    ([GOOD, {"name": "B", "query": "up == 0", "severity": "urgent"}], "observability.rules[1] (B): severity 'urgent' must be one of critical, warning, info"),
    ([GOOD, {**GOOD, "query": "up == 1"}], "observability.rules[1] (HighErrorRate): the name 'HighErrorRate' is used twice"),
    ([{"name": "A", "severity": "info"}], "observability.rules[0] (A): query must be a non-empty string (PromQL)"),
    ([{"name": "A", "query": "   ", "severity": "info"}], "observability.rules[0] (A): query must be a non-empty string (PromQL)"),
    ([{"name": "A", "query": 5, "severity": "info"}], "observability.rules[0] (A): query must be a non-empty string (PromQL)"),
    ([{"name": "A", "query": "up", "severity": "info", "summary": 3}], "observability.rules[0] (A): summary must be a string"),
])
def test_an_invalid_rule_fails_the_render_naming_the_rule_and_the_problem(repo, rules, message):
    """AC-092.6: no name, invalid severity, duplicate name, or a query that is not a non-empty string: exit 1 naming rule and problem."""
    obs(repo, ui="lgtm", rules=rules)
    p = render(repo)
    assert p.returncode == 1 and message in p.stderr


def test_rules_that_are_not_a_list_fail_the_render(repo):
    """AC-092.6: `rules` must be a list of {name, query, severity, summary}."""
    obs(repo, ui="lgtm", rules={"name": "A"})
    p = render(repo)
    assert p.returncode == 1 and "rules must be a list of {name, query, severity, summary}" in p.stderr


def test_the_quality_gate_is_red_for_an_invalid_rule(repo):
    """AC-092.6: `render.py --check` (part of `devbox run quality`) fails too."""
    obs(repo, ui="lgtm")
    assert render(repo).returncode == 0 and render_check(repo).returncode == 0
    commit(repo, "addon")
    obs(repo, ui="lgtm", rules=[{"name": "A", "query": "up", "severity": "urgent"}])
    p = render_check(repo)
    assert p.returncode != 0 and "severity 'urgent'" in p.stderr


@pytest.mark.parametrize("conf, message", [
    ({"alerts": "yes"}, "app.yaml: observability.alerts must be true or false"),
    ({"exportTo": "https://o.example.com", "queryURL": "prom.example.com"}, "app.yaml: observability.queryURL must be an http(s) URL"),
    ({"ui": "lgtm", "alertmanagerURL": "ftp://am.example.com"}, "app.yaml: observability.alertmanagerURL must be an http(s) URL"),
    ({"exportTo": "https://o.example.com", "queryURL": "https://p.example.com", "querySecret": "A_b"},
     "app.yaml: observability.querySecret must be <name> or <namespace>/<name>"),
])
def test_invalid_alert_settings_fail_the_render(repo, conf, message):
    """AC-092.6: `alerts`, `queryURL`, `alertmanagerURL` and `querySecret` are validated with a clear message."""
    obs(repo, **conf)
    p = render(repo)
    assert p.returncode == 1 and message in p.stderr


def snapshot(repo):
    return {str(p.relative_to(repo)): p.read_bytes() for p in sorted((repo / APP).rglob("*")) if p.is_file() and p.name != "app.yaml"}


def test_valid_rules_render_exactly_the_same_manifests(repo):
    """AC-092.4 AC-092.6: declared rules, alerts, queryURL, querySecret and alertmanagerURL are read only by the poll; the rendered tree does not change."""
    obs(repo, exportTo="https://o.example.com")
    assert render(repo).returncode == 0
    before = snapshot(repo)
    obs(repo, exportTo="https://o.example.com", alerts=True, queryURL="https://prom.example.com/api/prom", querySecret="obs-query",
        alertmanagerURL="https://am.example.com", rules=[GOOD, {"name": "Slow", "query": "up > 1", "severity": "info"}])
    p = render(repo)
    assert p.returncode == 0, p.stderr
    assert snapshot(repo) == before and render_check(repo).returncode == 0
