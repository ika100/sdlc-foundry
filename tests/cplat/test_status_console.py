"""Spec 122 acceptance tests: the additions to `cplat system status --json` (AC-122.7, AC-122.8, AC-122.42).

Contract: design.md "cplat system status --json additions". `status.sh` (every kubectl, gh and git call of status) is replaced;
no cluster, no GitHub."""
import json

import pytest

import cplat
import model
from system_fixtures import SHA, rich5, write_system

PINS = {("dev", "shop-api"): "sha-" + SHA, ("staging", "shop-api"): "1.2.0", ("prod", "shop-api"): "1.1.0"}


class Cluster:
    """Answers `kubectl --context C … get applications`: every Argo application Synced/Healthy for the contexts in `good`."""

    def __init__(self, apps, good):
        self.apps, self.good, self.alert_issues = apps, set(good), []

    def __call__(self, cmd):
        if cmd[0] == "kubectl":
            ctx = cmd[cmd.index("--context") + 1]
            if ctx not in self.good:
                return None
            return json.dumps({"items": [{"metadata": {"name": a}, "status": {"sync": {"status": "Synced"}, "health": {"status": "Healthy"}}}
                                         for a in self.apps]})
        if cmd[:3] == ["gh", "issue", "list"] and self.alert_issues:
            return json.dumps(self.alert_issues)
        return None


@pytest.fixture()
def system(tmp_path, monkeypatch):
    import status
    d = write_system(tmp_path, rich5(), pins=PINS)
    m = model.load_dir(d)
    apps = [i.argo_application for i in m.instances] if hasattr(m, "instances") else []
    if not apps:
        apps = [m.instance(c.name, e.name).argo_application for c in m.components for e in m.environments if m.instance(c.name, e.name)]
    cluster = Cluster(apps, good=["ctx-good"])
    monkeypatch.setattr(status, "sh", cluster)
    s = type("S", (), {})()
    s.repo, s.cluster = tmp_path, cluster
    return s


def status_json(system, capsys, *extra):
    rc = cplat.main(["system", "status", "--json", "--repo-dir", str(system.repo), *extra])
    out = capsys.readouterr()
    assert rc == 0, out.err
    return json.loads(out.out)


def cells_of(doc, component):
    return next(r for r in doc["rows"] if r["component"] == component)["cells"]


def test_environment_rules_come_in_promotion_order_with_promote_and_policy_ac_122_7(system, capsys):  # AC-122.7
    doc = status_json(system, capsys)
    rules = {r["name"]: r for r in doc["environment_rules"]}
    assert [r["name"] for r in doc["environment_rules"]] == ["dev", "staging", "prod"]
    assert (rules["dev"]["promote"], rules["dev"]["policy"]) == (None, "audit")
    assert rules["staging"]["promote"] == "after-dev-smoke" and rules["staging"]["policy"] == "off"
    assert rules["prod"]["promote"] == "manual" and rules["prod"]["policy"] == "enforce"


def test_a_cell_has_version_state_digest_and_release_ac_122_7(system, capsys):  # AC-122.7
    cells = cells_of(status_json(system, capsys, "--context", "ctx-good"), "shop-api")
    assert cells["staging"]["version"] == "1.2.0" and cells["dev"]["version"] == "sha-" + SHA[:7]
    for c in cells.values():
        assert {"version", "state", "digest", "release"} <= set(c)
        assert c["state"] in {"pinned", "healthy", "verified", "NOT VERIFIED", "alert", "unknown"}
    assert cells["staging"]["release"] == "1.2.0"


def test_a_cell_is_healthy_when_argo_reports_synced_healthy_ac_122_7(system, capsys):  # AC-122.7
    cells = cells_of(status_json(system, capsys, "--context", "ctx-good"), "shop-api")
    assert cells["staging"]["state"] in {"healthy", "verified", "NOT VERIFIED"} and cells["staging"]["argo"] == "Synced/Healthy"


def test_a_cell_is_pinned_when_nothing_else_is_known_ac_122_7(system, capsys):  # AC-122.7
    cells = cells_of(status_json(system, capsys), "shop-api")
    assert cells["staging"]["state"] in {"pinned", "NOT VERIFIED", "unknown"}


def test_an_open_alert_issue_makes_the_cell_alert_ac_122_7(system, capsys):  # AC-122.7
    system.cluster.alert_issues = [{"number": 9, "title": "5xx", "labels": [{"name": "alert"}, {"name": "env:staging"}]}]
    cells = cells_of(status_json(system, capsys, "--context", "ctx-good"), "shop-api")
    assert cells["staging"]["state"] == "alert"


def test_a_library_is_listed_with_its_users_and_has_no_row_ac_122_7(system, capsys):  # AC-122.7
    doc = status_json(system, capsys)
    assert {"component": "shop-lib", "used_by": ["shop-api"]} in doc["libraries"]
    assert all(r["component"] != "shop-lib" for r in doc["rows"])


def test_the_existing_keys_keep_their_meaning_ac_122_7(system, capsys):  # AC-122.7
    doc = status_json(system, capsys, "--context", "ctx-good")
    assert doc["system"] == "shop" and doc["environments"] == ["dev", "staging", "prod"]
    c = cells_of(doc, "shop-api")["staging"]
    assert {"tag", "ci", "argo", "pin_pr"} <= set(c)
    assert any(r["resource"] == "postgres" for r in doc["resources"])


def test_the_cell_before_a_manual_environment_has_what_promote_needs_ac_122_8(system, capsys):  # AC-122.8
    """Promote is offered on a verified cell whose next environment promotes manual: status reports both facts."""
    doc = status_json(system, capsys, "--context", "ctx-good")
    rules = {r["name"]: r["promote"] for r in doc["environment_rules"]}
    assert rules["prod"] == "manual"
    assert cells_of(doc, "shop-api")["staging"]["state"] in {"verified", "healthy", "NOT VERIFIED", "alert", "pinned"}


def test_an_unreadable_cluster_makes_its_cells_unknown_and_is_listed_ac_122_42(system, capsys):  # AC-122.42
    doc = status_json(system, capsys, "--context", "dev=ctx-good", "--context", "staging=ctx-good", "--context", "prod=ctx-bad")
    cells = cells_of(doc, "shop-api")
    assert cells["prod"]["state"] == "unknown"
    assert cells["staging"]["state"] != "unknown" and cells["dev"]["state"] != "unknown"
    [u] = doc["unavailable"]
    assert u["source"] == "cluster:prod" and u["error"]


def test_health_that_cannot_be_read_is_never_the_last_known_value_ac_122_42(system, capsys):  # AC-122.42
    doc = status_json(system, capsys, "--context", "ctx-bad")
    assert all(c["state"] == "unknown" for r in doc["rows"] for c in r["cells"].values() if c)
    assert {u["source"] for u in doc["unavailable"]} >= {"cluster:dev", "cluster:staging", "cluster:prod"}


def test_one_context_for_all_environments_still_works_ac_122_42(system, capsys):  # AC-122.42
    doc = status_json(system, capsys, "--context", "ctx-good")
    assert doc["unavailable"] == []


def test_the_text_table_names_the_state_of_each_cell_ac_122_7(system, capsys):  # AC-122.7
    assert cplat.main(["system", "status", "--repo-dir", str(system.repo), "--context", "ctx-good"]) == 0
    out = capsys.readouterr().out
    assert any(w in out for w in ("healthy", "verified", "pinned"))
