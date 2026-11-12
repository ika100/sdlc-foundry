"""Spec 186 acceptance tests: /component:release reuses the tagged commit's green CI run (AC-186.10, AC-186.11).

`cplat component release gates --commit S` decides: exit 0 and one line `gates: reused CI run <url> on <sha7> (<jobs>)`, or exit 1 and one
line `gates: run locally (<reason>)`, or exit 2 while main's run on S is still going after the timeout (design.md, Contract).

Seams: `ship.gh` (the `gh run list` and `gh run view` answers; every call is logged), the clock of `waits`, and a real git repo whose commit S
has a Dockerfile or has not (`git cat-file -e S:Dockerfile`). The verb is reached through `cplat.main`: it does not exist yet.
"""
import json
import subprocess
from datetime import datetime, timedelta, timezone

import pytest

import cplat
import ship
from prompts186_support import ROOT, prompt, sourced

URL = "https://github.com/acme/todo-api/actions/runs/42"
JOBS = [("quality (ruff + mypy)", "success"), ("test (pytest)", "success"), ("security (pip-audit)", "success"),
        ("ci-extra", "success"), ("pr-title (conventional commits)", "skipped")]
DOCKER = [("docker (amd64)", "success"), ("docker (arm64)", "success"), ("docker (publish multi-arch manifest)", "success")]


def ago(**delta):
    return (datetime.now(timezone.utc) - timedelta(**delta)).strftime("%Y-%m-%dT%H:%M:%SZ")


def reused(line):
    """The first words of the one line a reuse prints (the rest is the run's url, the commit and the job names)."""
    return line.split()[:4] == ["gates:", "reused", "CI", "run"]


def ci_run(rid=42, status="completed", conclusion="success", attempt=1, updated=None):
    return {"databaseId": rid, "status": status, "conclusion": conclusion, "attempt": attempt, "updatedAt": updated or ago(hours=1),
            "url": f"https://github.com/acme/todo-api/actions/runs/{rid}"}


def view(run, jobs):
    return {**{k: run[k] for k in ("databaseId", "attempt", "conclusion", "updatedAt", "url")},
            "jobs": [{"name": n, "conclusion": c, "status": "completed"} for n, c in jobs]}


def git(repo, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=repo, check=True, capture_output=True,
                          text=True).stdout.strip()


@pytest.fixture()
def world(tmp_path, monkeypatch):
    repo = tmp_path / "todo-api"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "remote", "add", "origin", "https://github.com/acme/todo-api.git")
    (repo / "a.txt").write_text("x")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "init")
    w = type("World", (), {})()
    w.repo, w.sha = repo, git(repo, "rev-parse", "HEAD")
    w.polls, w.views, w.calls, w.error = [], {}, [], None
    w.t = {"now": 1000.0, "slept": 0.0}
    monkeypatch.setattr("waits.now", lambda: w.t["now"])

    def sleep(s):
        w.t["now"] += s
        w.t["slept"] += s
    monkeypatch.setattr("waits.sleep", sleep)
    monkeypatch.setattr(ship, "GH_ERRORS", {})

    def gh(args, *, cwd, check=True):
        w.calls.append(list(args))
        if args[:2] == ["run", "list"]:
            if w.error:
                ship.GH_ERRORS["run list"] = w.error
                return ""
            n = len([c for c in w.calls if c[:2] == ["run", "list"]]) - 1
            return json.dumps(w.polls[min(n, len(w.polls) - 1)] if w.polls else [])
        if args[:2] == ["run", "view"]:
            return json.dumps(w.views[int(args[2])])
        return ""
    monkeypatch.setattr(ship, "gh", gh)

    def dockerfile():
        (repo / "Dockerfile").write_text("FROM scratch\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "docker")
        w.sha = git(repo, "rev-parse", "HEAD")
    w.dockerfile = dockerfile

    def green(jobs=JOBS, **run_kw):
        run = ci_run(**run_kw)
        w.polls.append([run])
        w.views[run["databaseId"]] = view(run, jobs)
        return run
    w.green = green
    return w


def gates(capsys, w, *args):
    capsys.readouterr()
    rc = cplat.main(["component", "release", "gates", "--commit", w.sha, "--repo", str(w.repo), *args])
    return rc, capsys.readouterr().out.splitlines()


def local(capsys, w, reason):
    rc, out = gates(capsys, w)
    assert (rc, out) == (1, [f"gates: run locally ({reason})"])


# ---------------- AC-186.10: reuse ----------------

def test_a_green_ci_run_on_the_commit_is_reused_in_one_line_ac_186_10(world, capsys):  # AC-186.10
    world.green()
    rc, out = gates(capsys, world)
    assert rc == 0 and len(out) == 1
    head = f"gates: reused CI run {URL} on {world.sha[:7]} ("
    assert out[0].startswith(head) and out[0].endswith(")")
    named = out[0][len(head):-1]
    assert all(n in named for n in ("quality (ruff + mypy)", "test (pytest)", "security (pip-audit)"))
    assert named.index("quality") < named.index("test (pytest)") < named.index("security")        # in run order
    listed = next(c for c in world.calls if c[:2] == ["run", "list"])
    for want in ("-R", "acme/todo-api", "--workflow", "ci", "--branch", "main", "--commit", world.sha, "--event", "push"):
        assert want in listed, (want, listed)


def test_a_repo_with_a_dockerfile_needs_the_image_jobs_too_ac_186_10(world, capsys):  # AC-186.10
    world.dockerfile()
    world.green(JOBS + DOCKER)
    rc, out = gates(capsys, world)
    assert rc == 0 and reused(out[0]) and "docker (arm64)" in out[0]


def test_the_json_form_carries_the_decision_and_the_run_ac_186_10(world, capsys):  # AC-186.10
    run = world.green()
    rc, out = gates(capsys, world, "--json")
    data = json.loads("\n".join(out))
    assert rc == 0 and data["reuse"] is True and data["reason"] is None and reused(data["line"])
    assert data["run"]["id"] == 42 and data["run"]["url"] == URL and data["run"]["attempt"] == 1 and data["run"]["conclusion"] == "success"
    assert data["run"]["finished_at"] == run["updatedAt"]
    assert [j["name"] for j in data["jobs"]][:3] == ["quality (ruff + mypy)", "test (pytest)", "security (pip-audit)"]


def test_a_run_that_went_green_on_a_rerun_counts_ac_186_10(world, capsys):  # AC-186.10 (A9)
    world.green(attempt=2)
    rc, out = gates(capsys, world)
    assert rc == 0 and reused(out[0])


def test_a_run_of_six_days_ago_is_still_reused_ac_186_10(world, capsys):  # AC-186.10 (A9)
    world.green(updated=ago(days=6, hours=20))
    assert gates(capsys, world)[0] == 0


def test_the_newest_run_is_the_one_judged_ac_186_10(world, capsys):  # AC-186.10
    old, new = ci_run(41, conclusion="failure"), ci_run(42)
    world.polls.append([new, old])
    world.views.update({41: view(old, JOBS), 42: view(new, JOBS)})
    assert gates(capsys, world)[0] == 0


def test_a_run_still_going_is_waited_for_and_then_judged_ac_186_11(world, capsys):  # AC-186.11
    running = ci_run(status="in_progress", conclusion="")
    done = ci_run()
    world.polls += [[running], [running], [done]]
    world.views[42] = view(done, JOBS)
    rc, out = gates(capsys, world)
    assert rc == 0 and reused(out[0]) and world.t["slept"] > 0


def test_a_run_that_fails_while_it_is_waited_for_runs_the_gates_locally_ac_186_11(world, capsys):  # AC-186.11
    running, failed = ci_run(status="in_progress", conclusion=""), ci_run(conclusion="failure")
    world.polls += [[running], [failed]]
    world.views[42] = view(failed, JOBS)
    local(capsys, world, "ci run 42 failure on attempt 1")
    assert world.t["slept"] > 0


def test_a_run_that_is_still_going_at_the_timeout_exits_2_ac_186_11(world, capsys):  # AC-186.11
    world.polls.append([ci_run(status="in_progress", conclusion="")])
    rc, out = gates(capsys, world, "--timeout", "30")
    assert rc == 2 and out[0] == f"TIMEOUT: main's ci run on {world.sha[:7]} is still running after 30s"
    assert "same call again" in out[1] and world.t["slept"] >= 30


# ---------------- AC-186.11: the gates run as today ----------------

def test_no_ci_run_on_main_runs_the_gates_locally_ac_186_11(world, capsys):  # AC-186.11
    world.polls.append([])
    local(capsys, world, f"no ci run on main for {world.sha[:7]}")


@pytest.mark.parametrize("conclusion", ["failure", "cancelled"])
def test_a_run_that_failed_or_was_cancelled_runs_the_gates_locally_ac_186_11(world, capsys, conclusion):  # AC-186.11
    world.green(conclusion=conclusion, attempt=2)
    local(capsys, world, f"ci run 42 {conclusion} on attempt 2")


def test_a_gate_without_a_job_runs_the_gates_locally_ac_186_11(world, capsys):  # AC-186.11
    world.green([j for j in JOBS if not j[0].startswith("security")])
    local(capsys, world, "gate security has no job in ci run 42")


def test_the_image_gate_is_missing_when_the_repo_has_a_dockerfile_ac_186_11(world, capsys):  # AC-186.11
    world.dockerfile()
    world.green(JOBS)
    local(capsys, world, "gate docker has no job in ci run 42")


@pytest.mark.parametrize("name, conclusion", [("test (pytest)", "skipped"), ("quality (ruff + mypy)", "failure"),
                                              ("docker (arm64)", "cancelled")])
def test_a_gate_job_that_did_not_succeed_runs_the_gates_locally_ac_186_11(world, capsys, name, conclusion):  # AC-186.11
    world.dockerfile()
    world.green([(n, conclusion if n == name else c) for n, c in JOBS + DOCKER])
    local(capsys, world, f"gate job {name} {conclusion} in ci run 42")


def test_a_run_older_than_seven_days_runs_the_gates_locally_ac_186_11(world, capsys):  # AC-186.11 (A9)
    world.green(updated=ago(days=8, hours=2))
    local(capsys, world, "ci run 42 finished 8 days ago (more than 7)")


def test_an_unreadable_ci_run_list_runs_the_gates_locally_ac_186_11(world, capsys):  # AC-186.11
    world.error = "HTTP 502: bad gateway"
    rc, out = gates(capsys, world)
    assert rc == 1 and len(out) == 1 and out[0].startswith("gates: run locally (cannot read the ci runs: ") and "502" in out[0]


def test_the_json_form_of_a_local_run_names_the_reason_ac_186_11(world, capsys):  # AC-186.11
    world.polls.append([])
    rc, out = gates(capsys, world, "--json")
    data = json.loads("\n".join(out))
    assert rc == 1 and data["reuse"] is False and data["run"] is None and data["jobs"] == []
    assert data["reason"] == f"no ci run on main for {world.sha[:7]}" and data["line"] == f"gates: run locally ({data['reason']})"


# ---------------- AC-186.10 / AC-186.11: the release prompt ----------------

def test_the_release_prompt_asks_cplat_before_the_gate_phases_and_registers_it_ac_186_10():  # AC-186.10
    path = "plugins/component/commands/release.md"
    text = prompt(path)
    assert "release gates" in text and "--commit" in text
    assert text.index("release gates") < text.index("## Phase 2")          # decided before any gate agent starts
    found = sourced(path, "spec 186")
    assert found and any("release gates" in str(e["text"]) for e in found)


def test_the_rule_register_still_checks_with_the_release_entry_ac_186_10():  # AC-186.10
    import rulescheck
    assert sourced("plugins/component/commands/release.md", "spec 186")
    result = rulescheck.check(ROOT)
    assert result.ok, [f"{f.file}:{f.line} {f.kind}" for f in result.failures][:5]
