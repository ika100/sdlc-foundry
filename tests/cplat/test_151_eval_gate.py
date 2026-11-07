"""Spec 151 acceptance tests: the eval gate for prompt changes (ADR-085).

Seams: a real git repo under tmp_path with a `v1.0.0` tag and a `plugins/` tree; benchmark records passed in as a list
(`records=`), and `evalgate.check` replaced inside `platrelease` for the release test."""
import subprocess

import pytest

import core
import evalgate


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "platform"
    (r / "plugins/svc/agents").mkdir(parents=True)
    (r / "plugins/svc/agents/coder.md").write_text("You are the coder.\n")
    (r / "scripts").mkdir()
    (r / "scripts/x.py").write_text("x = 1\n")
    git(r, "init", "-q", "-b", "main")
    git(r, "config", "user.name", "t")
    git(r, "config", "user.email", "t@t")
    git(r, "add", "-A")
    git(r, "commit", "-q", "-m", "base")
    git(r, "tag", "v1.0.0")
    return r


def change(repo, path, text):
    (repo / path).write_text(text)
    git(repo, "commit", "-qam", f"change {path}")
    return git(repo, "rev-parse", "HEAD")


def bench(workflow, commit, outcome="done", tokens=1_000_000, version="1.0.1", dirty=False):
    return {"kind": "benchmark", "outcome": outcome, "platform_version": version, "run_id": f"r-{workflow}-{commit[:4]}",
            "ended_at": "2026-11-07T10:00:00Z", "usage": {"totals": {"input_tokens": tokens}},
            "benchmark": {"workflow": workflow, "plugins": {"commit": commit, "dirty": dirty}}}


def baseline(workflow, tokens=1_000_000):
    return {**bench(workflow, "0" * 40, tokens=tokens, version="1.0.0"), "benchmark": {"workflow": workflow}}


# ---------------- AC-151.1 ----------------

def test_no_prompt_change_needs_no_benchmark_ac_151_1(repo, capsys):  # AC-151.1
    change(repo, "scripts/x.py", "x = 2\n")
    assert evalgate.check(repo, records=lambda d: pytest.fail("read the store")) == ([], [])
    assert evalgate.main(["--repo", str(repo)]) == 0
    assert "no benchmark needed" in capsys.readouterr().out


# ---------------- AC-151.2 ----------------

def test_a_prompt_change_without_a_benchmark_fails_with_the_command_ac_151_2(repo):  # AC-151.2
    change(repo, "plugins/svc/agents/coder.md", "You are the coder. Decide by default.\n")
    changed, fails = evalgate.check(repo, records=lambda d: [])
    assert changed == ["plugins/svc/agents/coder.md"] and len(fails) == 2
    assert "cplat platform runs benchmark quick-task --plugins plugins --reset-first" in fails[0]


def test_a_benchmark_of_these_prompts_passes_and_another_tree_does_not_ac_151_2(repo):  # AC-151.2
    old = change(repo, "plugins/svc/agents/coder.md", "v2\n")
    new = change(repo, "plugins/svc/agents/coder.md", "v3\n")
    later = change(repo, "scripts/x.py", "x = 3\n")             # same plugins/ tree as `new`
    assert evalgate.check(repo, records=lambda d: [bench("quick-task", old), bench("build", old)])[1] != []
    assert evalgate.check(repo, records=lambda d: [bench("quick-task", new), bench("build", new)])[1] == []
    assert evalgate.check(repo, records=lambda d: [bench("quick-task", later), bench("build", later, dirty=True)])[1] == [
        "build: no benchmark ran with these prompts; run `cplat platform runs benchmark build --plugins plugins --reset-first`"]


# ---------------- AC-151.3 ----------------

def test_a_failed_or_costly_benchmark_fails_the_gate_ac_151_3(repo):  # AC-151.3
    c = change(repo, "plugins/svc/agents/coder.md", "v2\n")
    base = [baseline("quick-task", 1_000_000), baseline("quick-task", 1_200_000), baseline("build")]
    fails = evalgate.check(repo, records=lambda d: [*base, bench("quick-task", c, outcome="escalated"), bench("build", c)])[1]
    assert fails == [f"quick-task: the last benchmark with these prompts ended escalated (run r-quick-task-{c[:4]}); "
                     "fix the prompts and run `cplat platform runs benchmark quick-task --plugins plugins --reset-first` again"]
    fails = evalgate.check(repo, records=lambda d: [*base, bench("quick-task", c, tokens=1_700_000), bench("build", c)])[1]
    assert len(fails) == 1 and "1,700,000 tokens" in fails[0] and "1.0.0 median of 1,100,000" in fails[0]
    assert evalgate.check(repo, records=lambda d: [*base, bench("quick-task", c, tokens=1_600_000), bench("build", c)])[1] == []


# ---------------- AC-151.4 ----------------

def test_the_release_stops_before_its_branch_and_skip_eval_overrides_ac_151_4(monkeypatch, tmp_path):  # AC-151.4
    import platrelease
    monkeypatch.setattr(evalgate, "check", lambda repo: (["plugins/svc/agents/coder.md"], ["build: no benchmark ran"]))
    answers = {"config": "t", "status": "", "rev-parse": "abc", "show": "## [Unreleased]\n"}
    monkeypatch.setattr(platrelease, "_git", lambda repo, *a, check=True: answers.get(a[0], ""))
    monkeypatch.setattr(platrelease, "_fragments_at", lambda repo, ref: [("1-x.fixed.md", "x")])
    with pytest.raises(core.PlatformError, match="eval gate: 1 prompt file") as e:
        platrelease._preflight(tmp_path)
    assert "--skip-eval" in e.value.hint
    platrelease._preflight(tmp_path, "benchmark sample repo is down")       # no raise
    o, _ = platrelease._parse(["--skip-eval", "why"])
    assert o.skip_eval == "why"
