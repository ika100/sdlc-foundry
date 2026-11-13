"""Spec 187 acceptance tests: `cplat system set --observability` (AC-187.1-3), `cplat resource backup` setting options (AC-187.4-7)
and the command prompts (AC-187.8).

Contract: design.md "cplat system set --observability" and "cplat resource backup". Real renderer on a hand-built gitops checkout;
`gh` and the cluster are never used (`gitops.open_pr` is replaced, the on-demand path reads a FakeKube)."""
import copy
import json
import re

import pytest
import yaml

import gitops
from core import PlatformError
from backup_fixtures import APP, bdoc, bucket, kube, make_repo  # noqa: F401  (kube is a fixture)
from resources_fixtures import db
from system_fixtures import ROOT, files, git, tiny
from test_commands_114 import render_check, run, sysdoc

PR_URL = "https://github.com/acme/shop-gitops/pull/1"


def obs_repo(tmp_path, observability=None, env="dev"):
    doc = tiny()
    doc["components"] = {}
    if observability is not None:
        doc["environments"][env]["observability"] = copy.deepcopy(observability)
    return make_repo(tmp_path, doc)


def obs(repo, env="dev"):
    return sysdoc(repo)["environments"][env].get("observability", "absent")


def fake_pr(monkeypatch):
    seen = []
    monkeypatch.setattr(gitops, "open_pr", lambda repo, branch, title, body: seen.append((branch, title, body)) or PR_URL)
    return seen


def committed_files(repo):
    """The files the PR's commit holds: with `gitops.open_pr` faked nothing is committed, so these are the working-tree
    changes `open_pr` would stage (it commits every change under the generated folders and refuses any other)."""
    return [ln[3:] for ln in git(repo, "status", "--porcelain", "--untracked-files=all").splitlines() if ln]


# ---------------- AC-187.1: system set --observability lgtm ----------------

def test_lgtm_creates_the_observability_block_and_renders_ac_187_1(tmp_path, capsys):  # AC-187.1
    repo = obs_repo(tmp_path)
    rc, out, _ = run("system", "set", "--env", "dev", "--observability", "lgtm", "--repo-dir", repo, capsys=capsys)
    assert rc == 0
    assert obs(repo) == {"ui": "lgtm"}
    assert "observability" in out and "lgtm" in out
    assert render_check(repo).returncode == 0


def test_lgtm_keeps_the_other_observability_keys_ac_187_1(tmp_path):  # AC-187.1
    repo = obs_repo(tmp_path, {"ui": "none", "alerts": False})
    assert run("system", "set", "--env", "dev", "--observability", "lgtm", "--repo-dir", repo) == 0
    assert obs(repo) == {"ui": "lgtm", "alerts": False}


def test_dry_run_prints_the_change_and_writes_nothing_ac_187_1(tmp_path, capsys):  # AC-187.1
    repo = obs_repo(tmp_path)
    before = files(repo)
    rc, out, _ = run("system", "set", "--env", "dev", "--observability", "lgtm", "--dry-run", "--repo-dir", repo, capsys=capsys)
    assert rc == 0 and "observability" in out and "lgtm" in out
    assert files(repo) == before


def test_pr_opens_one_pull_request_with_only_generated_changes_ac_187_1(tmp_path, monkeypatch):  # AC-187.1
    repo = obs_repo(tmp_path)
    seen = fake_pr(monkeypatch)
    assert run("system", "set", "--env", "dev", "--observability", "lgtm", "--pr", "--repo-dir", repo) == 0
    assert len(seen) == 1 and seen[0][0] == "system/set-dev"
    changed = committed_files(repo)
    assert f"{APP}/system.yaml" in changed and all(f.split("/")[0] in gitops.GENERATED for f in changed)


# ---------------- AC-187.2: none and off ----------------

def test_none_sets_ui_and_keeps_the_other_keys_ac_187_2(tmp_path):  # AC-187.2
    repo = obs_repo(tmp_path, {"ui": "lgtm", "alerts": False})
    assert run("system", "set", "--env", "dev", "--observability", "none", "--repo-dir", repo) == 0
    assert obs(repo) == {"ui": "none", "alerts": False}


def test_off_removes_the_block_when_only_ui_is_in_it_ac_187_2(tmp_path):  # AC-187.2
    repo = obs_repo(tmp_path, {"ui": "lgtm"})
    assert run("system", "set", "--env", "dev", "--observability", "off", "--repo-dir", repo) == 0
    assert obs(repo) == "absent"
    assert render_check(repo).returncode == 0


def test_off_with_other_keys_exits_1_names_them_and_changes_nothing_ac_187_2(tmp_path, capsys):  # AC-187.2
    repo = obs_repo(tmp_path, {"ui": "none", "alerts": False})
    before = files(repo)
    rc, _, err = run("system", "set", "--env", "dev", "--observability", "off", "--repo-dir", repo, capsys=capsys)
    assert rc == 1 and "alerts" in err and "--observability none" in err
    assert files(repo) == before


# ---------------- AC-187.3: refusals ----------------

def test_an_unknown_value_names_the_key_and_the_allowed_values_ac_187_3(tmp_path, capsys):  # AC-187.3
    repo = obs_repo(tmp_path)
    before = files(repo)
    rc, _, err = run("system", "set", "--env", "dev", "--observability", "grafana", "--repo-dir", repo, capsys=capsys)
    assert rc == 1 and "environments.dev.observability.ui" in err
    assert all(v in err for v in ("lgtm", "none", "off"))
    assert files(repo) == before


def test_lgtm_with_export_to_is_refused_ac_187_3(tmp_path, capsys):  # AC-187.3
    repo = obs_repo(tmp_path, {"exportTo": "https://otlp.example.com"})
    before = files(repo)
    rc, _, err = run("system", "set", "--env", "dev", "--observability", "lgtm", "--repo-dir", repo, capsys=capsys)
    assert rc == 1 and "environments.dev.observability.exportTo" in err
    assert "ui lgtm and exportTo exclude each other" in err
    assert files(repo) == before


# ---------------- resource backup: set the scheduled backup ----------------

DEFAULTS = {"to": "backups", "schedule": "0 3 * * *", "retention": "30d"}


def backup_repo(tmp_path, dbb=None, **kw):
    return make_repo(tmp_path, bdoc(dbb=dbb, **kw))


def bk(repo, env="dev"):
    return sysdoc(repo)["resources"]["orders-db"].get("instances", {}).get(env, {}).get("backup", "absent")


def backup(repo, *args, capsys=None):
    return run("resource", "backup", "orders-db", "--env", "dev", "--repo-dir", repo, *args, capsys=capsys)


def test_to_sets_the_backup_with_the_defaults_ac_187_4(tmp_path):  # AC-187.4
    repo = backup_repo(tmp_path)
    assert backup(repo, "--to", "backups") == 0
    assert bk(repo) == DEFAULTS and list(bk(repo)) == ["to", "schedule", "retention"]
    assert render_check(repo).returncode == 0


def test_schedule_and_retention_are_stored_ac_187_4(tmp_path):  # AC-187.4
    repo = backup_repo(tmp_path)
    assert backup(repo, "--to", "backups", "--schedule", "30 2 * * *", "--retention", "8w") == 0
    assert bk(repo) == {"to": "backups", "schedule": "30 2 * * *", "retention": "8w"}


def test_setting_a_backup_takes_none_in_the_cluster_ac_187_4(tmp_path, kube):  # AC-187.4
    repo = backup_repo(tmp_path)
    assert backup(repo, "--to", "backups") == 0
    assert kube.calls == []


def test_backup_dry_run_prints_the_three_values_and_writes_nothing_ac_187_4(tmp_path, capsys):  # AC-187.4
    repo = backup_repo(tmp_path)
    before = files(repo)
    rc, out, _ = backup(repo, "--to", "backups", "--dry-run", capsys=capsys)
    assert rc == 0 and "backups" in out and "0 3 * * *" in out and "30d" in out
    assert files(repo) == before


def test_backup_pr_opens_one_pull_request_with_only_generated_changes_ac_187_4(tmp_path, monkeypatch):  # AC-187.4
    repo = backup_repo(tmp_path)
    seen = fake_pr(monkeypatch)
    assert backup(repo, "--to", "backups", "--pr") == 0
    assert len(seen) == 1 and seen[0][0].startswith("resource/backup-")
    changed = committed_files(repo)
    assert f"{APP}/system.yaml" in changed and all(f.split("/")[0] in gitops.GENERATED for f in changed)


# ---------------- AC-187.5: change some values, turn off ----------------

def test_only_the_given_values_change_ac_187_5(tmp_path):  # AC-187.5
    repo = backup_repo(tmp_path, dbb={"dev": {"to": "backups", "schedule": "30 2 * * *", "retention": "8w"}})
    assert backup(repo, "--retention", "14d") == 0
    assert bk(repo) == {"to": "backups", "schedule": "30 2 * * *", "retention": "14d"}
    git(repo, "commit", "-qam", "retention")          # the first change is reviewed and merged: the clone is clean again
    assert backup(repo, "--schedule", "0 4 * * *") == 0
    assert bk(repo) == {"to": "backups", "schedule": "0 4 * * *", "retention": "14d"}


def test_off_removes_the_backup_and_says_the_bucket_keeps_the_backups_ac_187_5(tmp_path, capsys):  # AC-187.5
    repo = backup_repo(tmp_path, dbb={"dev": DEFAULTS})
    rc, out, _ = backup(repo, "--off", capsys=capsys)
    assert rc == 0 and bk(repo) == "absent"
    assert "backups" in out and "kept" in out
    assert render_check(repo).returncode == 0


# ---------------- AC-187.6: refusals ----------------

BK = "resources.orders-db.instances.dev.backup"


def refused(repo, capsys, *args, env="dev", db_name="orders-db", names=(), key=None):
    before = files(repo)
    rc, _, err = run("resource", "backup", db_name, "--env", env, "--repo-dir", repo, *args, capsys=capsys)
    assert rc == 1 and "fix:" in err
    if key:
        assert key in err, key
    for n in names:
        assert n in err, n
    assert files(repo) == before


def test_a_target_that_is_not_a_bucket_lists_the_buckets_ac_187_6(tmp_path, capsys):  # AC-187.6
    refused(backup_repo(tmp_path), capsys, "--to", "orders-db", names=("backups",), key=BK + ".to")


def test_an_unknown_bucket_is_refused_ac_187_6(tmp_path, capsys):  # AC-187.6
    refused(backup_repo(tmp_path), capsys, "--to", "nope", names=("nope", "backups"), key=BK + ".to")


def test_a_resource_that_is_not_a_database_is_refused_ac_187_6(tmp_path, capsys):  # AC-187.6
    refused(backup_repo(tmp_path), capsys, "--to", "backups", db_name="backups", names=("backups", "database"), key="resources.backups")


def test_an_external_database_is_refused_ac_187_6(tmp_path, capsys):  # AC-187.6
    repo = backup_repo(tmp_path, db_kw={"instances": {"prod": {"external": True}}})
    refused(repo, capsys, "--to", "backups", env="prod", names=("provider",), key="resources.orders-db.instances.prod")


def test_an_unknown_environment_is_refused_ac_187_6(tmp_path, capsys):  # AC-187.6
    refused(backup_repo(tmp_path), capsys, "--to", "backups", env="qa", names=("qa", "dev"), key="environments.qa")


@pytest.mark.parametrize("cron", ["0 3 * *", "every day", "0 3 * * * *"])
def test_a_schedule_that_is_not_five_field_cron_is_refused_ac_187_6(tmp_path, capsys, cron):  # AC-187.6
    refused(backup_repo(tmp_path), capsys, "--to", "backups", "--schedule", cron, names=("schedule",), key=BK + ".schedule")


@pytest.mark.parametrize("ret", ["0d", "30", "3m", "-1d", "d"])
def test_a_retention_that_is_not_n_days_or_weeks_is_refused_ac_187_6(tmp_path, capsys, ret):  # AC-187.6
    refused(backup_repo(tmp_path), capsys, "--to", "backups", "--retention", ret, names=("retention",), key=BK + ".retention")


def test_schedule_without_to_on_an_instance_without_backup_is_refused_ac_187_6(tmp_path, capsys):  # AC-187.6
    refused(backup_repo(tmp_path), capsys, "--schedule", "0 4 * * *", names=("--to",), key=BK)


def test_off_without_a_backup_is_refused_ac_187_6(tmp_path, capsys):  # AC-187.6
    refused(backup_repo(tmp_path), capsys, "--off", names=("backup",), key=BK)


def test_off_with_another_option_is_refused_ac_187_6(tmp_path, capsys):  # AC-187.6
    refused(backup_repo(tmp_path, dbb={"dev": DEFAULTS}), capsys, "--off", "--retention", "7d", names=("--off",), key=BK)


def test_a_failed_render_restores_the_files_ac_187_6(tmp_path, monkeypatch, capsys):  # AC-187.6
    repo = backup_repo(tmp_path)
    before = files(repo)

    def broken(_repo):
        raise PlatformError(f"render failed: {BK}: boom")  # the render names the key; the command passes it on

    monkeypatch.setattr(gitops, "render", broken)
    rc, _, err = run("resource", "backup", "orders-db", "--env", "dev", "--to", "backups", "--repo-dir", repo, capsys=capsys)
    assert rc == 1 and f"render failed: {BK}: boom" in err and "fix:" in err
    assert BK in err
    assert files(repo) == before


# ---------------- AC-187.7: no setting option, on-demand backup ----------------

def test_without_setting_options_dry_run_and_pr_are_refused_ac_187_7(tmp_path, capsys):  # AC-187.7
    repo = backup_repo(tmp_path, dbb={"dev": DEFAULTS})
    refused(repo, capsys, "--dry-run", names=("--dry-run",))
    refused(repo, capsys, "--pr", names=("--pr",))


def test_without_setting_options_the_system_file_is_untouched_ac_187_7(tmp_path, kube, capsys):  # AC-187.7
    repo = backup_repo(tmp_path, dbb={"dev": DEFAULTS})
    before = files(repo)
    run("resource", "backup", "orders-db", "--env", "dev", "--repo-dir", repo, capsys=capsys)
    assert files(repo) == before
    assert git(repo, "status", "--porcelain").strip() == ""


# ---------------- AC-187.8: the prompts ----------------

def front(path):
    text = (ROOT / path).read_text()
    return yaml.safe_load(re.match(r"^---\n(.*?)\n---", text, re.S).group(1))["description"], text


def test_resource_backup_usage_line_names_the_setting_options_ac_187_8():  # AC-187.8
    desc, text = front("plugins/resource/commands/backup.md")
    for opt in ("--to <bucket>", "--schedule <cron>", "--retention", "--off"):
        assert opt in desc, opt
    assert len(desc) <= 300 and "$ARGUMENTS" in text


def test_system_set_usage_line_names_the_observability_option_ac_187_8():  # AC-187.8
    desc, _ = front("plugins/system/commands/set.md")
    assert "--observability" in desc and "lgtm" in desc


def test_resource_add_points_to_resource_backup_ac_187_8():  # AC-187.8
    _, text = front("plugins/resource/commands/add.md")
    assert "/resource:backup" in text and "--to <bucket>" in text
    assert re.search(r"(?i)PITR and pooling are not provided", text)
    assert not re.search(r"(?i)\bno backups\b|backups? (is|are) not provided", text)
