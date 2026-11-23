"""#886: `/resource:backup <db> --env prod --to <name>` declared an in-cluster bucket, and right after `/platform:doctor` warned that
prod backups live in the same cluster as prod. The preview now says so where the person decides, and names the external option."""
import json

from backup_fixtures import bdoc, ext_prod_bucket, make_repo
from test_backup_new_bucket_860 import backup, repo_without_bucket

NOTE = "live in the same cluster as prod"


def test_a_prod_backup_to_a_new_in_cluster_bucket_names_the_same_cluster_and_the_external_option_886(tmp_path, capsys):
    rc, out, _ = backup(repo_without_bucket(tmp_path), "--to", "postgres-backups", "--dry-run", capsys=capsys)
    assert rc == 0 and NOTE in out and "--type bucket --external" in " ".join(out.split())


def test_a_prod_backup_to_a_declared_in_cluster_bucket_names_it_too_886(tmp_path, capsys):
    rc, out, _ = backup(make_repo(tmp_path, bdoc()), "--to", "backups", "--dry-run", "--json", capsys=capsys)
    assert rc == 0 and json.loads(out)["same_cluster"] is True


def test_an_external_prod_bucket_or_another_environment_has_no_note_886(tmp_path, capsys):
    rc, out, _ = backup(make_repo(tmp_path / "ext", bdoc(bucket_kw=ext_prod_bucket())), "--to", "backups", "--dry-run", capsys=capsys)
    assert rc == 0 and NOTE not in out
    rc, out, _ = backup(make_repo(tmp_path / "dev", bdoc()), "--to", "backups", "--dry-run", env="dev", capsys=capsys)
    assert rc == 0 and "same cluster" not in out
