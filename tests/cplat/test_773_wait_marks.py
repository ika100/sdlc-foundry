"""#773: a Stop hook blocked a finished unit for six stops on `cplat pr wait …acme/shop-api/pull/7 --merge`, a wait the session never
started: its mark had stayed in the git dir and its pid now belonged to another live process. A mark older than the process that
holds its pid is gone."""
import datetime as dt
import json
import os
import subprocess

import waits


def checkout(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


def mark(repo, pid, started_at):
    d = repo / ".git" / waits.WAITS_DIR
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{pid}.json"
    f.write_text(json.dumps({"pid": pid, "command": "cplat pr wait 7 --merge", "started_at": started_at.isoformat(timespec="seconds")}))
    return f


def test_a_mark_older_than_the_process_holding_its_pid_is_dropped(tmp_path):
    repo = checkout(tmp_path)
    f = mark(repo, os.getpid(), dt.datetime.now() - dt.timedelta(days=3))   # this test process is younger than three days
    assert waits.live(repo) == [] and not f.exists()


def test_a_mark_of_the_live_wait_that_wrote_it_still_holds(tmp_path):
    repo = checkout(tmp_path)
    with waits.running("cplat pr wait 7 --merge", cwd=repo):
        assert waits.live(repo) == ["cplat pr wait 7 --merge"]
