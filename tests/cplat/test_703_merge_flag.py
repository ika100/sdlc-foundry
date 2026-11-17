"""#703: to hold a running ship's merge during a release, `--no-merge` had to be written into cplat-ship.json by hand: the flag was
read only when the run was created. `ship start --no-merge` / `--merge` now change a run that already started; neither keeps it."""
import ship
from test_ship import gh, repo  # noqa: F401  (fixtures)


def start(repo, *flags, capsys=None):
    return ship.main(["--repo", str(repo), "start", "7", *flags])


def test_no_merge_on_a_started_run_stops_it_at_a_green_pr_and_says_so(repo, gh, capsys):  # noqa: F811
    ship.start(repo, "7", None)
    assert ship.load_state(repo)["merge"] is True                       # a new run merges
    assert start(repo, "--no-merge") == 0
    assert ship.load_state(repo)["merge"] is False
    assert "now stops at a green PR" in capsys.readouterr().out


def test_merge_turns_it_back_and_no_flag_keeps_the_setting(repo, gh, capsys):  # noqa: F811
    ship.start(repo, "7", False)
    start(repo)
    assert ship.load_state(repo)["merge"] is False                      # resumed without a flag: unchanged
    start(repo, "--merge")
    assert ship.load_state(repo)["merge"] is True and "now merges its PR" in capsys.readouterr().out
