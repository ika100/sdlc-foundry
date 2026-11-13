"""Spec 197 acceptance tests: the seams journey 13 found (AC-197.1 to AC-197.4).

Seams: `cplat component build reviewed` on a git repo with a feature branch (AC-197.1); `cplat platform runs agent findings` on a
run record whose plan lost a task to `cplat plan merge` (AC-197.2); `cplat system set --observability` and `cplat system status`
and `model.grafana_*` (AC-197.3, AC-197.4). Contract: design.md "Reviewed step", "Merged-away deviation", "Grafana location".
Everything the feature adds is reached inside test bodies, so a missing function fails the test, not the collection."""
import json
import re

import pytest

import cplat
import model
import runs
import runs_agents
import status
from backup_fixtures import make_repo as make_gitops
from system_fixtures import rich5, tiny, write_system
from test_commands_114 import run
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)
from test_runs_agents import SPEC_ID as RUN_SPEC, agent, begin, end, entry, verification
from test_ship import repo as ship_repo  # noqa: F401  (fixture)
from units131_support import BRANCH, SPEC_ID, git, head, make_repo as make_spec_repo

ELSEWHERE = "answers only at grafana.localhost on that cluster's Gateway"


# ---------------- AC-197.1: the reviewed step finds the tester's commit ----------------

def branch_with(tmp_path, subject):
    repo = make_spec_repo(tmp_path)
    git(repo, "checkout", "-qb", BRANCH)
    (repo / "tests").mkdir(exist_ok=True)
    (repo / "tests" / "test_alerts.py").write_text("# AC-007.1\n\n\ndef test_alert():\n    assert True\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", subject)
    return repo


def reviewed(capsys, repo):
    capsys.readouterr()
    rc = cplat.main(["component", "build", "reviewed", SPEC_ID, "--repo", str(repo)])
    out = capsys.readouterr()
    return rc, out.out, out.err


@pytest.mark.parametrize("subject", [
    "test(price-alerts): acceptance tests for AC-007.1–AC-007.3",     # the tester's documented form: no spec id in it
    "test(price-alerts): acceptance tests for AC-007.1-AC-007.3",
    f"test(007): acceptance tests for {SPEC_ID}",                      # the old form keeps working
])
def test_the_reviewed_step_finds_the_testers_commit_ac_197_1(tmp_path, capsys, subject):  # AC-197.1
    repo = branch_with(tmp_path, subject)
    before = head(repo)
    rc, out, err = reviewed(capsys, repo)
    assert rc == 0, err
    assert git(repo, "log", "-1", "--format=%s") == f"test(007): reviewed acceptance tests for {SPEC_ID}"
    assert git(repo, "rev-parse", "HEAD~1") == before


@pytest.mark.parametrize("subject", [
    "test(other-spec): acceptance tests for AC-008.1–AC-008.2",       # another spec's criteria
    "test(price-alerts): acceptance tests for AC-0071.1–AC-0071.2",   # AC-0071. is not AC-007.
    "test(price-alerts): acceptance tests for the alerts",            # neither the spec id nor a criterion id
])
def test_another_specs_or_an_unnamed_acceptance_commit_is_refused_ac_197_1(tmp_path, capsys, subject):  # AC-197.1
    repo = branch_with(tmp_path, subject)
    before = head(repo)
    rc, out, err = reviewed(capsys, repo)
    assert rc == 1 and "ERROR:" in err and "no commit 'acceptance tests for" in err
    assert head(repo) == before


# ---------------- AC-197.2: a deviation naming a merged-away task ----------------

def merged(repo, task, into):
    runs_agents.task_merge(runs.current(repo), repo, task, into, "the store alone cannot pass without the switch")


def findings_of(repo, store):
    rec = end(repo, store)
    return rec, [e for e in entry(rec, "svc-go:coder")["events"] if e["kind"] == "finding"]


def test_a_deviation_naming_a_merged_task_is_recorded_on_the_target_ac_197_2(ship_repo, store, capsys):  # AC-197.2
    begin(ship_repo)
    verification(ship_repo, [("AC-007.1", "met")])
    merged(ship_repo, "t0", "t2")
    capsys.readouterr()
    assert agent(ship_repo, "findings", "--cycle", "1", "--deviation", "t0") == 0
    assert "WARNING" not in capsys.readouterr().err
    rec, found = findings_of(ship_repo, store)
    (ev,) = found
    assert (ev["severity"], ev["task"], ev["criterion"], ev["tasks"], ev["cycle"]) == ("deviation", "t2", None, ["t2"], 1)
    assert ev["note"] == "named as t0 (merged into t2)"
    assert rec["agent_metrics"]["complete"] is True and rec["agent_metrics"]["problems"] == []
    assert entry(rec, "svc-go:coder")["counts"]["findings"]["first"]["deviation"] == 1


def test_a_chain_of_merges_resolves_to_the_last_task_ac_197_2(ship_repo, store, capsys):  # AC-197.2
    begin(ship_repo)
    verification(ship_repo, [("AC-007.1", "met")])
    merged(ship_repo, "t8", "t9")
    merged(ship_repo, "t9", "t3")
    capsys.readouterr()
    assert agent(ship_repo, "findings", "--cycle", "1", "--deviation", "t8") == 0
    assert "WARNING" not in capsys.readouterr().err
    rec, found = findings_of(ship_repo, store)
    (ev,) = found
    assert (ev["task"], ev["tasks"], ev["note"]) == ("t3", ["t3"], "named as t8 (merged into t3)")
    assert rec["agent_metrics"]["complete"] is True


@pytest.mark.parametrize("named, merge", [("t42", None), ("t7", ("t6", "t7"))])   # t7 is no plan task: the chain ends outside the plan
def test_an_id_that_is_no_plan_or_merged_task_still_warns_ac_197_2(ship_repo, store, capsys, named, merge):  # AC-197.2
    begin(ship_repo)
    verification(ship_repo, [("AC-007.1", "met")])
    if merge:
        merged(ship_repo, *merge)
    capsys.readouterr()
    assert agent(ship_repo, "findings", "--cycle", "1", "--deviation", merge[0] if merge else named) == 0
    err = capsys.readouterr().err
    assert "WARNING: agent metric not recorded" in err and "malformed: deviation" in err
    rec, found = findings_of(ship_repo, store)
    assert found == [] and rec["agent_metrics"]["complete"] is False


# ---------------- AC-197.3: system set names where Grafana answers ----------------

def gitops(tmp_path, staging_host="{component}.shop.example.com"):
    doc = tiny()
    doc["components"] = {}
    doc["environments"]["staging"]["host"] = staging_host
    return make_gitops(tmp_path, doc)


def grafana_line(out):
    m = re.search(r"^Grafana: (.*)$", out, re.M)
    return m.group(1) if m else None


def set_obs(repo, capsys, value, env="dev", *extra):
    rc, out, err = run("system", "set", "--env", env, "--observability", value, *extra, "--repo-dir", repo, capsys=capsys)
    assert rc == 0, err
    git(repo, "add", "-A")                                      # the next call refuses a dirty tree
    git(repo, "commit", "-q", "--allow-empty", "-m", "set")
    return out


def test_the_grafana_helpers_follow_the_local_port_rule_ac_197_3(monkeypatch):  # AC-197.3
    monkeypatch.delenv("LOCAL_HTTP_PORT", raising=False)
    assert model.local_port() == 8088
    assert model.grafana_url("{component}.shop-dev.localhost") == "http://grafana.localhost:8088/"
    assert model.grafana_url("{component}.shop.example.com") is None and model.grafana_url(None) is None
    assert model.grafana_location("{component}.shop-dev.localhost") == "http://grafana.localhost:8088/"
    assert model.grafana_location("{component}.shop.example.com") == model.GRAFANA_ELSEWHERE and ELSEWHERE in model.GRAFANA_ELSEWHERE
    monkeypatch.setenv("LOCAL_HTTP_PORT", "9090")
    assert model.local_port() == 9090 and model.grafana_url("a.localhost") == "http://grafana.localhost:9090/"
    monkeypatch.setenv("LOCAL_HTTP_PORT", "nope")
    assert model.local_port() == 8088


@pytest.mark.parametrize("extra", [(), ("--dry-run",)])
def test_a_local_environment_gets_the_grafana_url_line_ac_197_3(tmp_path, capsys, monkeypatch, extra):  # AC-197.3
    monkeypatch.delenv("LOCAL_HTTP_PORT", raising=False)
    out = set_obs(gitops(tmp_path), capsys, "lgtm", "dev", *extra)
    assert grafana_line(out) == "http://grafana.localhost:8088/"


def test_the_grafana_url_follows_the_local_http_port_ac_197_3(tmp_path, capsys, monkeypatch):  # AC-197.3
    monkeypatch.setenv("LOCAL_HTTP_PORT", "9090")
    out = set_obs(gitops(tmp_path), capsys, "lgtm")
    assert grafana_line(out) == "http://grafana.localhost:9090/"


@pytest.mark.parametrize("extra", [(), ("--dry-run",)])
def test_json_carries_the_grafana_url_ac_197_3(tmp_path, capsys, monkeypatch, extra):  # AC-197.3
    monkeypatch.delenv("LOCAL_HTTP_PORT", raising=False)
    doc = json.loads(set_obs(gitops(tmp_path), capsys, "lgtm", "dev", "--json", *extra))
    assert doc["grafana_url"] == "http://grafana.localhost:8088/"


def test_a_second_identical_call_still_reports_the_url_ac_197_3(tmp_path, capsys, monkeypatch):  # AC-197.3
    monkeypatch.delenv("LOCAL_HTTP_PORT", raising=False)
    repo = gitops(tmp_path)
    set_obs(repo, capsys, "lgtm")
    doc = json.loads(set_obs(repo, capsys, "lgtm", "dev", "--json"))
    assert doc["grafana_url"] == "http://grafana.localhost:8088/"


def test_a_non_local_environment_says_where_grafana_answers_ac_197_3(tmp_path, capsys):  # AC-197.3
    repo = gitops(tmp_path)
    out = set_obs(repo, capsys, "lgtm", "staging")
    line = grafana_line(out)
    assert line is not None and ELSEWHERE in line and "http" not in line
    assert json.loads(set_obs(repo, capsys, "lgtm", "staging", "--json"))["grafana_url"] is None


def test_a_given_host_decides_local_or_not_ac_197_3(tmp_path, capsys, monkeypatch):  # AC-197.3
    monkeypatch.delenv("LOCAL_HTTP_PORT", raising=False)
    repo = gitops(tmp_path)
    out = set_obs(repo, capsys, "lgtm", "dev", "--host", "{component}.shop.example.com", "--dry-run")
    line = grafana_line(out)
    assert line is not None and ELSEWHERE in line


@pytest.mark.parametrize("value", ["none", "off"])
def test_no_grafana_line_when_the_stack_is_turned_off_ac_197_3(tmp_path, capsys, value):  # AC-197.3
    repo = gitops(tmp_path)
    set_obs(repo, capsys, "lgtm")
    out = set_obs(repo, capsys, value)
    assert grafana_line(out) is None and "Grafana" not in out
    assert json.loads(set_obs(repo, capsys, "lgtm", "dev", "--json"))["grafana_url"]   # back on, to turn it off with --json
    assert json.loads(set_obs(repo, capsys, value, "dev", "--json"))["grafana_url"] is None


def test_without_the_option_json_has_no_grafana_key_ac_197_3(tmp_path, capsys):  # AC-197.3
    repo = gitops(tmp_path)
    rc, out, err = run("system", "set", "--env", "staging", "--policy", "enforce", "--json", "--repo-dir", repo, capsys=capsys)
    assert rc == 0, err
    assert "grafana_url" not in json.loads(out)


# ---------------- AC-197.4: system status names the Grafana location ----------------

@pytest.fixture()
def system(tmp_path, monkeypatch):
    monkeypatch.delenv("LOCAL_HTTP_PORT", raising=False)
    doc = rich5()
    doc["environments"]["dev"]["observability"] = {"ui": "lgtm"}                       # local host
    doc["environments"]["staging"]["observability"] = {"ui": "lgtm"}                   # a real host
    doc["environments"]["prod"]["observability"] = {"ui": "none"}
    write_system(tmp_path, doc)
    monkeypatch.setattr(status, "sh", lambda cmd: None)
    return tmp_path


def obs_cells(system, capsys):
    rc = cplat.main(["system", "status", "--json", "--repo-dir", str(system)])
    out = capsys.readouterr()
    assert rc == 0, out.err
    (row,) = [r for r in json.loads(out.out)["resources"] if r["resource"] == "observability"]
    return row["cells"]


def test_the_observability_cell_names_the_grafana_location_ac_197_4(system, capsys):  # AC-197.4
    cells = obs_cells(system, capsys)
    assert cells["dev"]["grafana_url"] == "http://grafana.localhost:8088/"
    assert cells["staging"]["grafana_url"] is None and "argo" in cells["staging"]


def test_an_environment_without_ui_lgtm_has_no_grafana_location_ac_197_4(system, capsys):  # AC-197.4
    cells = obs_cells(system, capsys)
    assert "grafana_url" in cells["dev"]                          # the feature exists ...
    assert not cells.get("prod") or "grafana_url" not in cells["prod"]


def test_the_table_prints_the_grafana_location_ac_197_4(system, capsys):  # AC-197.4
    assert cplat.main(["system", "status", "--repo-dir", str(system)]) == 0
    out = capsys.readouterr().out
    assert "Grafana http://grafana.localhost:8088/" in out
    assert f"Grafana {ELSEWHERE}" in out
