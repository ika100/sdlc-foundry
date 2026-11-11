"""#500: a `git push` that GitHub refuses for a transient reason (`fatal error in commit_refs_rules`, a 5xx, a dropped
connection) backs off and pushes again for a bounded time before it fails; any other refusal fails at once.

Seam: a fake `git` first on PATH that fails its first N pushes with a scripted stderr, and the clock of `core`."""
import os
import stat

import appship
import core
import pytest
from waiting import with_prelude

COMMIT_REFS = """To https://github.com/acme/taskboard-web.git
 ! [remote rejected] feature/001-task-page -> feature/001-task-page (fatal error in commit_refs_rules)
error: failed to push some refs to 'https://github.com/acme/taskboard-web.git'"""
HTTP_502 = "error: RPC failed; HTTP 502 curl 22 The requested URL returned error: 502\nfatal: the remote end hung up unexpectedly"
RESET = "fatal: unable to access 'https://github.com/acme/x.git/': Recv failure: Connection reset by peer"
NON_FF = """To https://github.com/acme/x.git
 ! [rejected]        main -> main (non-fast-forward)
error: failed to push some refs to 'https://github.com/acme/x.git'"""
PROTECTED = " ! [remote rejected] main -> main (protected branch hook declined)"


@pytest.fixture()
def fake_git(tmp_path, monkeypatch):
    """`fail(n, stderr)`: the next n pushes fail with `stderr`; returns the log of git calls."""
    bin_dir, state = tmp_path / "bin", tmp_path / "state"
    bin_dir.mkdir()
    state.mkdir()
    script = bin_dir / "git"
    script.write_text(with_prelude(f"""#!/bin/sh
echo "$*" >> {state}/calls
case " $* " in *" push "*) ;; *) exit 0 ;; esac
n=$(cat {state}/fails 2>/dev/null || echo 0)
if [ "$n" -gt 0 ]; then
  echo $((n - 1)) > {state}/fails
  cat {state}/stderr >&2
  exit 1
fi
echo pushed
"""))
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    slept: list[float] = []
    monkeypatch.setattr(core, "sleep", slept.append)

    class Fake:
        def fail(self, n, stderr):
            (state / "fails").write_text(str(n))
            (state / "stderr").write_text(stderr)

        @property
        def calls(self):
            p = state / "calls"
            return p.read_text().splitlines() if p.exists() else []

    f = Fake()
    f.slept = slept
    return f


@pytest.mark.parametrize("stderr", [COMMIT_REFS, HTTP_502, RESET])
def test_a_transient_push_refusal_backs_off_and_pushes_again_500(fake_git, tmp_path, capsys, stderr):  # #500
    fake_git.fail(2, stderr)
    proc = core.run(["git", "push", "-q", "-u", "origin", "feature/001"], cwd=tmp_path)
    assert proc.returncode == 0 and "pushed" in proc.stdout
    assert len([c for c in fake_git.calls if c.startswith("push")]) == 3
    assert fake_git.slept == [15, 30]
    assert "pushing again in 15 s" in capsys.readouterr().err


def test_the_push_helpers_of_a_ship_retry_too_500(fake_git, tmp_path):  # #500
    fake_git.fail(1, COMMIT_REFS)
    appship.git(tmp_path, "push", "-q", "-u", "origin", "feature/001")
    assert len(fake_git.calls) == 2 and fake_git.slept == [15]


def test_a_push_option_before_the_subcommand_still_counts_as_a_push_500(fake_git, tmp_path):  # #500
    fake_git.fail(1, COMMIT_REFS)
    assert core.run(["git", "-C", str(tmp_path), "push", "origin", "main"]).returncode == 0
    assert fake_git.slept == [15]


def test_a_refusal_that_does_not_clear_fails_after_a_bounded_wait_500(fake_git, tmp_path):  # #500
    fake_git.fail(100, COMMIT_REFS)
    with pytest.raises(core.PlatformError, match="commit_refs_rules"):
        core.run(["git", "push", "-u", "origin", "feature/001"], cwd=tmp_path)
    assert 4 * 60 <= sum(fake_git.slept) <= core.PUSH_RETRY_MAX_WAIT
    assert max(fake_git.slept) <= 120


def test_check_false_returns_the_last_failure_after_the_retries_500(fake_git, tmp_path):  # #500
    fake_git.fail(100, HTTP_502)
    proc = core.run(["git", "push", "origin", "x"], cwd=tmp_path, check=False)
    assert proc.returncode == 1 and "502" in proc.stderr and fake_git.slept


@pytest.mark.parametrize("stderr", [NON_FF, PROTECTED, "remote: Permission to acme/x.git denied to bot.\nfatal: ... error: 403"])
def test_any_other_push_refusal_fails_at_once_500(fake_git, tmp_path, stderr):  # #500
    fake_git.fail(1, stderr)
    with pytest.raises(core.PlatformError):
        core.run(["git", "push", "origin", "main"], cwd=tmp_path)
    assert fake_git.slept == [] and len(fake_git.calls) == 1


def test_other_git_commands_never_retry_500(monkeypatch, tmp_path):  # #500
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return core.subprocess.CompletedProcess(cmd, 1, "", "fatal: unable to access: Connection reset by peer")
    monkeypatch.setattr(core.subprocess, "run", fake_run)
    monkeypatch.setattr(core, "sleep", lambda s: pytest.fail("slept"))
    assert core.run(["git", "fetch", "origin"], check=False).returncode == 1 and len(calls) == 1
