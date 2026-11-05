"""Spec 143 (AC-143.11): the CI wait of /component:release is a cplat wait. `cplat component release wait --commit SHA` waits for
`main`'s `ci` run on the commit to tag, with the exit codes of every wait (design.md, decision 12).

Seams: `ship.gh` (the `gh run list` answers, one per poll) and the clock of `waits`.
"""
import json
import subprocess

import pytest

import cplat
import ship

SHA = "4f2a91c" + "0" * 33


@pytest.fixture()
def comp(tmp_path, monkeypatch):
    repo = tmp_path / "todo-api"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "remote", "add", "origin", "https://github.com/acme/todo-api.git"], cwd=repo, check=True)
    t = {"now": 100.0, "slept": 0.0}
    monkeypatch.setattr("waits.now", lambda: t["now"])

    def sleep(s):
        t["now"] += s
        t["slept"] += s
    monkeypatch.setattr("waits.sleep", sleep)
    answers: list = []
    calls: list = []

    def gh(args, *, cwd, check=True):
        calls.append(args)
        if args[:2] == ["run", "list"]:
            return json.dumps(answers[min(len([c for c in calls if c[:2] == ["run", "list"]]) - 1, len(answers) - 1)])
        if args[:2] == ["run", "view"]:
            return "##[error] test failed: expected 3, got 4\n"
        return ""
    monkeypatch.setattr(ship, "gh", gh)
    return repo, answers, calls, t


def wait(capsys, repo, *args):
    capsys.readouterr()
    rc = cplat.main(["component", "release", "wait", "--commit", SHA, "--repo", str(repo), *args])
    return rc, capsys.readouterr().out.splitlines()


def run(status, conclusion=""):
    return [{"databaseId": 42, "status": status, "conclusion": conclusion}]


def test_a_green_ci_run_on_the_commit_exits_0_ac_143_11(comp, capsys):  # AC-143.11
    repo, answers, calls, t = comp
    answers += [[], run("in_progress"), run("completed", "success")]
    rc, out = wait(capsys, repo)
    assert rc == 0 and any(ln.startswith("GREEN:") for ln in out)
    listed = next(c for c in calls if c[:2] == ["run", "list"])
    assert "--commit" in listed and SHA in listed and "ci" in listed


def test_a_red_ci_run_exits_1_with_its_log_ac_143_11(comp, capsys):  # AC-143.11
    repo, answers, _, _ = comp
    answers += [run("completed", "failure")]
    rc, out = wait(capsys, repo)
    assert rc == 1 and out[0].startswith("RED:") and any("expected 3, got 4" in ln for ln in out)


def test_no_ci_run_after_two_minutes_exits_1_and_says_do_not_tag_ac_143_11(comp, capsys):  # AC-143.11
    repo, answers, _, t = comp
    answers += [[]]
    rc, out = wait(capsys, repo)
    assert rc == 1 and out[0].startswith("NO RUN:") and 120 <= t["slept"] < 540


def test_a_run_still_going_at_the_timeout_exits_2_ac_143_11(comp, capsys):  # AC-143.11
    repo, answers, _, t = comp
    answers += [run("in_progress")]
    rc, out = wait(capsys, repo, "--timeout", "300")
    assert rc == 2 and out[0].startswith("TIMEOUT:") and t["slept"] >= 300
