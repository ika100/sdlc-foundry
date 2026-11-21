"""#862: `resource backup --schedule daily` was refused; only a cron expression worked, so the session retried with "0 3 * * *".
hourly, daily and weekly now map to fixed cron expressions in UTC, which the preview shows and system.yaml stores."""
import pytest

from backup_fixtures import bdoc, kube, make_repo  # noqa: F401  (kube is a fixture)
from system_fixtures import files
from test_commands_114 import render_check, run, sysdoc


def bk(repo, env="dev"):
    return sysdoc(repo)["resources"]["orders-db"]["instances"][env]["backup"]


def backup(repo, *args, capsys=None):
    return run("resource", "backup", "orders-db", "--env", "dev", "--repo-dir", repo, *args, capsys=capsys)


@pytest.mark.parametrize("word,cron", [("daily", "0 3 * * *"), ("weekly", "0 3 * * 0"), ("hourly", "0 * * * *"), ("Daily", "0 3 * * *")])
def test_a_schedule_word_is_stored_as_its_cron_expression_862(tmp_path, word, cron):
    repo = make_repo(tmp_path, bdoc())
    assert backup(repo, "--to", "backups", "--schedule", word) == 0
    assert bk(repo)["schedule"] == cron
    assert render_check(repo).returncode == 0


def test_the_preview_shows_the_cron_expression_of_the_word_862(tmp_path, capsys):
    repo = make_repo(tmp_path, bdoc())
    before = files(repo)
    rc, out, _ = backup(repo, "--to", "backups", "--schedule", "weekly", "--dry-run", capsys=capsys)
    assert rc == 0 and '"0 3 * * 0"' in out and "weekly" not in out.split("schedule", 1)[1].split("\n", 1)[0]
    assert files(repo) == before


def test_an_unknown_word_is_refused_and_the_hint_names_the_words_862(tmp_path, capsys):
    repo = make_repo(tmp_path, bdoc())
    rc, _, err = backup(repo, "--to", "backups", "--schedule", "monthly", capsys=capsys)
    assert rc == 1 and "daily" in err and "weekly" in err and "hourly" in err
