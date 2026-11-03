"""Spec 126 acceptance tests: `cplat headless` owns the run it resumes (AC-126.2) and names the cause of its no-progress
escalation by the same fixed rules as the Stop hook (AC-126.7).

Each `claude -p` session gets `CPLAT_SESSION_ID=<the --session-id>`. The progress key ignores `owner` and `stop_gate`, so a
new owner or the gate's bookkeeping alone is not progress. The cause is `ship.no_progress_cause(repo, st, message)`.
"""
import json
import os
import stat
import sys

import pytest

import core
import headless
import preflight
import ship
from test_headless import fake_claude, repo, runs, set_state  # noqa: F401  (fixtures, helpers)
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)
from units131_support import GH_STUB, git

SCRIPTS = str(core.PLATFORM_ROOT / "scripts" / "cplat")


@pytest.fixture(autouse=True)
def _no_session_env(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.delenv("CPLAT_SESSION_ID", raising=False)


@pytest.fixture(autouse=True)
def _isolated_preflight(repo, tmp_path, monkeypatch):
    """The preflight of `/component:ship` runs for real on a world of its own: the settings layers inside tmp_path, a `gh`
    stub that is logged in and may push, a git identity in the environment. The spec and its plan are committed on `main`
    (so a stall is in the unit the test means) and `origin` is a GitHub URL (the stub answers for it)."""
    stub = tmp_path / "gh-bin"
    stub.mkdir()
    gh = stub / "gh"
    gh.write_text(GH_STUB)
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{stub}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_GH_LOG", str(tmp_path / "gh.log"))
    monkeypatch.delenv("FAKE_GH_AUTH", raising=False)
    monkeypatch.delenv("FAKE_GH_PUSH", raising=False)
    for k, v in (("NAME", "Tester"), ("EMAIL", "tester@example.test")):
        monkeypatch.setenv(f"GIT_AUTHOR_{k}", v)
        monkeypatch.setenv(f"GIT_COMMITTER_{k}", v)
    user = tmp_path / "user-settings.json"
    user.write_text("{}")
    monkeypatch.setattr(preflight, "layers", lambda r=None: [
        ("managed", tmp_path / "no-managed.json"), ("user", user),
        ("project", repo / ".claude" / "settings.json"), ("local", repo / ".claude" / "settings.local.json")])
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "init")
    git(repo, "remote", "add", "origin", "https://github.com/acme/shop-api.git")


def claim_script(repo, say):
    """What `/component:ship 7` does inside the session: resume the run (so it takes the session as owner), then print `say`."""
    return (f'echo "$CPLAT_SESSION_ID $*" >> sessions.txt\n'
            f'PYTHONPATH={SCRIPTS} {sys.executable} -c "import ship, pathlib; ship.start(pathlib.Path(\'{repo}\'), \'7\', True)"\n'
            f"echo '{say}'")


def sessions(repo):
    rows = [ln.split(" ", 1) for ln in (repo / "sessions.txt").read_text().splitlines()]
    return [(sid, rest) for sid, rest in rows]


def test_ac_126_2_each_session_gets_cplat_session_id_equal_to_its_session_id_argument(repo, tmp_path, monkeypatch):  # AC-126.2
    ship.start(repo, "7", True)
    fake_claude(tmp_path, monkeypatch, 'echo "$CPLAT_SESSION_ID $*" >> sessions.txt')
    headless.main(["/component:ship 7", "--repo", str(repo), "--max-runs", "2"])
    rows = sessions(repo)
    assert len(rows) >= 1
    for sid, args in rows:
        assert sid and f"--session-id {sid}" in args
    assert len({sid for sid, _ in rows}) == len(rows)    # one id per session


def test_ac_126_2_the_session_that_resumes_the_run_becomes_its_owner(repo, tmp_path, monkeypatch):  # AC-126.2
    ship.start(repo, "7", True)
    set_state(repo, phase="pr")
    fake_claude(tmp_path, monkeypatch, claim_script(repo, "stuck"))
    headless.main(["/component:ship 7", "--repo", str(repo), "--max-runs", "1"])
    (sid, _), = sessions(repo)
    assert ship.load_state(repo)["owner"] == sid


def test_ac_126_7_a_new_owner_alone_is_not_progress_so_two_sessions_end_in_no_progress(repo, tmp_path, monkeypatch, capsys):  # AC-126.2 AC-126.7
    ship.start(repo, "7", True)
    set_state(repo, phase="pr")
    fake_claude(tmp_path, monkeypatch, claim_script(repo, "I cannot go on"))
    assert headless.main(["/component:ship 7", "--repo", str(repo)]) != 0
    assert runs(repo) == 2                               # not 3: owner and stop_gate changed, nothing else did
    owners = {sid for sid, _ in sessions(repo)}
    assert len(owners) == 2
    assert "no progress" in ship.load_state(repo)["escalated"]


def test_ac_126_7_the_progress_key_ignores_owner_and_stop_gate(repo):  # AC-126.7
    st = ship.start(repo, "7", True)
    k1 = headless.progress_key(repo, dict(st))
    k2 = headless.progress_key(repo, {**st, "owner": "another", "stop_gate": {"head": "h", "phase": "build", "no_progress": 1}})
    assert k1 == k2
    assert headless.progress_key(repo, {**st, "phase": "pr"}) != k1


def test_ac_126_7_the_reason_keeps_its_wording_and_adds_the_last_message(repo, tmp_path, monkeypatch):  # AC-126.7
    ship.start(repo, "7", True)
    set_state(repo, phase="pr")
    fake_claude(tmp_path, monkeypatch, "echo 'I could not find the failing test'")
    headless.main(["/component:ship 7", "--repo", str(repo)])
    # AC-131.5: unit mode words the stall by unit (phase pr: land); the excerpt of the last message stays
    assert ship.load_state(repo)["escalated"] == ("no progress: unit land after 2 sessions without a commit; "
                                                  "last message: I could not find the failing test")


def test_ac_126_7_a_matching_rule_on_the_last_message_gives_its_cause(repo, tmp_path, monkeypatch, store):  # AC-126.7
    ship.start(repo, "7", True)
    set_state(repo, phase="pr")
    fake_claude(tmp_path, monkeypatch, "echo 'waiting for approval to push the branch'")
    headless.main(["/component:ship 7", "--repo", str(repo)])
    st = ship.load_state(repo)
    assert st["cause"] == "environment"
    assert st["escalated"].endswith("; last message: waiting for approval to push the branch")
    esc = stored(store)[-1]["escalation"]
    assert (esc["cause"], esc["cause_source"]) == ("environment", "given")


def test_ac_126_7_criteria_without_a_test_in_build_are_code(repo, tmp_path, monkeypatch):  # AC-126.7
    ship.start(repo, "7", True)                          # phase build: the fixture's criteria have no test
    assert ship.load_state(repo)["phase"] == "build"
    fake_claude(tmp_path, monkeypatch, "echo 'I could not go further'")
    headless.main(["/component:ship 7", "--repo", str(repo)])
    assert ship.load_state(repo)["cause"] == "code"


def test_ac_126_7_without_a_rule_or_red_evidence_the_cause_is_a_decision_never_environment(repo, tmp_path, monkeypatch):  # AC-126.7
    ship.start(repo, "7", True)
    set_state(repo, phase="pr")
    fake_claude(tmp_path, monkeypatch, "echo 'unsure what to do'")
    headless.main(["/component:ship 7", "--repo", str(repo)])
    st = ship.load_state(repo)
    assert "no progress" in st["escalated"] and st["cause"] == "decision"


def test_ac_126_7_a_session_that_printed_nothing_has_no_excerpt_and_still_a_cause(repo, tmp_path, monkeypatch):  # AC-126.7
    ship.start(repo, "7", True)
    set_state(repo, phase="pr")
    fake_claude(tmp_path, monkeypatch, "true")
    headless.main(["/component:ship 7", "--repo", str(repo)])
    st = ship.load_state(repo)
    assert st["escalated"] == "no progress: unit land after 2 sessions without a commit"    # AC-131.5
    assert st["cause"] in {"code", "decision"}
