"""#860: `resource backup --to <bucket>` with a bucket that did not exist needed a bucket PR first and the backup PR after its merge;
auto mode refused to merge the bucket PR the user never asked for. A target that is not declared yet is now declared as an in-cluster
bucket in the same change, so the backup is one PR."""
from backup_fixtures import APP, bdoc, kube, make_repo  # noqa: F401  (kube is a fixture)
from system_fixtures import files
from test_commands_114 import render_check, run, sysdoc
from test_settings_commands_187 import committed_files, fake_pr

import gitops


def repo_without_bucket(tmp_path):
    doc = bdoc()
    del doc["resources"]["backups"]
    doc["components"]["api"]["uses"] = ["orders-db"]
    return make_repo(tmp_path, doc)


def backup(repo, *args, capsys=None, env="prod"):
    return run("resource", "backup", "orders-db", "--env", env, "--repo-dir", repo, *args, capsys=capsys)


def test_a_new_bucket_is_declared_with_the_backup_in_one_pr_860(tmp_path, monkeypatch):
    repo = repo_without_bucket(tmp_path)
    seen = fake_pr(monkeypatch)
    assert backup(repo, "--to", "postgres-backups", "--pr") == 0
    doc = sysdoc(repo)
    assert doc["resources"]["postgres-backups"] == {"type": "bucket", "storage": "10Gi", "versioning": False}
    assert doc["resources"]["orders-db"]["instances"]["prod"]["backup"]["to"] == "postgres-backups"
    assert len(seen) == 1, "one pull request, not a bucket PR and then a backup PR"
    assert "declare bucket postgres-backups" in seen[0][2]
    changed = committed_files(repo)
    assert f"{APP}/system.yaml" in changed and all(f.split("/")[0] in gitops.GENERATED for f in changed)
    assert any("/addons/prod/postgres-backups/" in f for f in changed), "the bucket is rendered in the same change"
    assert render_check(repo).returncode == 0


def test_the_preview_names_the_new_bucket_and_writes_nothing_860(tmp_path, capsys):
    repo = repo_without_bucket(tmp_path)
    before = files(repo)
    rc, out, _ = backup(repo, "--to", "postgres-backups", "--dry-run", capsys=capsys)
    assert rc == 0 and "declare bucket postgres-backups" in out and "0 3 * * *" in out
    assert files(repo) == before


def test_an_existing_bucket_is_not_declared_again_860(tmp_path, capsys):
    repo = make_repo(tmp_path, bdoc())
    rc, out, _ = backup(repo, "--to", "backups", "--dry-run", capsys=capsys)
    assert rc == 0 and "declare bucket" not in out
