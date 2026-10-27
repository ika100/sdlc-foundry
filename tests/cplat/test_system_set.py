"""Spec 122 acceptance tests: `/system:set --env <env>` with --promote, --policy and --host (AC-122.51).

Contract: design.md "cplat system set". Dispatched through `cplat system set` on the spec 114 gitops-app checkout (real renderer)."""
import copy
import json
import re

import pytest
import yaml

import gitops
from system_fixtures import ROOT, files
from test_commands_114 import APP, gitops5, render_check, run, sysdoc  # noqa: F401  (gitops5 is a fixture)


def envs(repo):
    return sysdoc(repo)["environments"]


def test_promote_on_staging_changes_only_that_key_ac_122_51(gitops5):  # AC-122.51
    before = copy.deepcopy(sysdoc(gitops5))
    assert run("system", "set", "--env", "staging", "--promote", "manual", "--repo-dir", gitops5) == 0
    after = sysdoc(gitops5)
    assert after["environments"]["staging"]["promote"] == "manual"
    del after["environments"]["staging"]["promote"]
    assert after == before
    assert "# the shop system (keep this comment)" in (gitops5 / APP / "system.yaml").read_text()
    assert render_check(gitops5).returncode == 0


def test_policy_and_host_are_set_together_ac_122_51(gitops5):  # AC-122.51
    assert run("system", "set", "--env", "staging", "--policy", "enforce", "--host", "{component}.{system}-stg.example.com", "--repo-dir", gitops5) == 0
    st = envs(gitops5)["staging"]
    assert st["policy"] == "enforce" and st["host"] == "{component}.{system}-stg.example.com"
    assert envs(gitops5)["dev"]["host"] == "{component}.{system}-dev.localhost"


@pytest.mark.parametrize("policy", ["audit", "enforce", "off"])
def test_every_allowed_policy_is_accepted_ac_122_51(gitops5, policy):  # AC-122.51
    assert run("system", "set", "--env", "prod", "--policy", policy, "--repo-dir", gitops5) == 0
    assert envs(gitops5)["prod"]["policy"] == policy


def test_prod_takes_only_the_manual_promote_rule_ac_122_51(gitops5, capsys):  # AC-122.51
    assert run("system", "set", "--env", "prod", "--promote", "manual", "--repo-dir", gitops5) == 0
    commit_and_snapshot = files(gitops5)
    rc, _, err = run("system", "set", "--env", "prod", "--promote", "after-dev-smoke", "--repo-dir", gitops5, capsys=capsys)
    assert rc == 1 and "environments.prod.promote" in err and "manual" in err
    assert files(gitops5) == commit_and_snapshot


def test_dev_takes_no_promote_rule_ac_122_51(gitops5, capsys):  # AC-122.51
    before = files(gitops5)
    rc, _, err = run("system", "set", "--env", "dev", "--promote", "manual", "--repo-dir", gitops5, capsys=capsys)
    assert rc == 1 and "environments.dev.promote" in err
    assert files(gitops5) == before


def test_an_invalid_policy_names_the_key_and_the_allowed_values_ac_122_51(gitops5, capsys):  # AC-122.51
    before = files(gitops5)
    rc, _, err = run("system", "set", "--env", "staging", "--policy", "strict", "--repo-dir", gitops5, capsys=capsys)
    assert rc == 1 and "environments.staging.policy" in err
    assert all(v in err for v in ("audit", "enforce", "off"))
    assert files(gitops5) == before


def test_an_invalid_promote_rule_on_staging_names_the_allowed_values_ac_122_51(gitops5, capsys):  # AC-122.51
    rc, _, err = run("system", "set", "--env", "staging", "--promote", "sometimes", "--repo-dir", gitops5, capsys=capsys)
    assert rc == 1 and "environments.staging.promote" in err and "after-dev-smoke" in err and "manual" in err


def test_a_host_with_an_unknown_placeholder_changes_nothing_ac_122_51(gitops5, capsys):  # AC-122.51
    before = files(gitops5)
    rc, _, err = run("system", "set", "--env", "staging", "--host", "{bogus}.example.com", "--repo-dir", gitops5, capsys=capsys)
    assert rc == 1 and "environments.staging.host" in err
    assert files(gitops5) == before


def test_an_unknown_environment_lists_the_systems_environments_ac_122_51(gitops5, capsys):  # AC-122.51
    before = files(gitops5)
    rc, _, err = run("system", "set", "--env", "qa", "--policy", "audit", "--repo-dir", gitops5, capsys=capsys)
    assert rc == 1 and "qa" in err and "dev" in err and "staging" in err and "prod" in err
    assert files(gitops5) == before


def test_at_least_one_key_is_needed_ac_122_51(gitops5, capsys):  # AC-122.51
    before = files(gitops5)
    rc, _, err = run("system", "set", "--env", "staging", "--repo-dir", gitops5, capsys=capsys)
    assert rc == 1 and "--promote" in err and "--policy" in err and "--host" in err
    assert files(gitops5) == before


def test_one_pull_request_with_the_system_set_branch_and_title_ac_122_51(gitops5, monkeypatch):  # AC-122.51
    seen = []
    monkeypatch.setattr(gitops, "open_pr", lambda repo, branch, title, body: seen.append((branch, title, body)) or "https://github.com/acme/shop-gitops/pull/1")
    assert run("system", "set", "--env", "staging", "--promote", "manual", "--pr", "--repo-dir", gitops5) == 0
    [(branch, title, body)] = seen
    assert branch == "system/set-staging" and title.startswith("chore(system): set staging") and "promote" in title


def test_dry_run_json_lists_the_plan_and_writes_nothing_ac_122_51(gitops5, capsys):  # AC-122.51
    before = files(gitops5)
    rc, out, _ = run("system", "set", "--env", "staging", "--promote", "manual", "--dry-run", "--json", "--repo-dir", gitops5, capsys=capsys)
    assert rc == 0 and files(gitops5) == before
    plan = json.loads(out)
    assert plan["will_do"] and plan["pr"] is None and "promote" in json.dumps(plan["will_do"])


def test_the_command_file_exists_with_its_usage_line_ac_122_51():  # AC-122.51
    text = (ROOT / "plugins" / "system" / "commands" / "set.md").read_text()
    fm = yaml.safe_load(re.match(r"^---\n(.*?)\n---", text, re.S).group(1))
    assert "Usage: /system:set --env <env>" in fm["description"] and len(fm["description"]) <= 260
    assert "$ARGUMENTS" in text and "cplat system set" in text and "--dry-run" in text and "--pr" in text
